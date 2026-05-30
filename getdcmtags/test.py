#!/usr/bin/env python3
"""Tests for getdcmtags binary."""

import json
import shutil
import subprocess
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

SERIES_UID = "1.2.276.0.7230010.3.1.3.9022104837472469675953272569912339663578"


def find_free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BookkeeperHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        self.server.last_request = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": parse_qs(body),
        }
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format, *_args):
        pass


def check_key(tags, key, expected):
    actual = tags.get(key)
    if actual is None:
        print(f"FAIL: key '{key}' not found in tags file")
        print(json.dumps(tags, indent=2))
        sys.exit(1)
    if actual != expected:
        print(f"FAIL: key '{key}' = {actual!r}, expected {expected!r}")
        print(json.dumps(tags, indent=2))
        sys.exit(1)


def cleanup(*names):
    shutil.rmtree(SERIES_UID, ignore_errors=True)
    shutil.rmtree("error", ignore_errors=True)
    for name in names:
        for suffix in ["", ".error", ".error.lock"]:
            Path(name + suffix).unlink(missing_ok=True)


def test_basic_tags(binary):
    """Test that getdcmtags produces correct tags file."""
    print("test_basic_tags")
    shutil.copy("test_dcm", "test_dcm_copy")
    try:
        subprocess.run(
            [binary, "test_dcm_copy", "sender_address", "sender_aet",
             "receiver_aet", "0.0.0.0", "asdf",
             "--set-tag", "forceKey=forcedValue"],
            check=True,
        )
        tags_path = Path(SERIES_UID) / f"{SERIES_UID}#test_dcm_copy.tags"
        if not tags_path.exists():
            print(f"FAIL: tags file not created at {tags_path}")
            sys.exit(1)
        tags = json.loads(tags_path.read_text())
        check_key(tags, "Filename", "test_dcm_copy")
        check_key(tags, "SenderAddress", "sender_address")
        check_key(tags, "SenderAET", "sender_aet")
        check_key(tags, "ReceiverAET", "receiver_aet")
        check_key(tags, "SeriesInstanceUID", SERIES_UID)
        check_key(tags, "forceKey", "forcedValue")
    finally:
        cleanup("test_dcm_copy")
    print("  PASS")


def test_bookkeeper(binary):
    """Test that getdcmtags sends the right POST to the bookkeeper."""
    print("test_bookkeeper")
    port = find_free_port()
    server = HTTPServer(("127.0.0.1", port), BookkeeperHandler)
    server.last_request = None
    t = threading.Thread(target=server.handle_request)
    t.start()

    shutil.copy("test_dcm", "test_dcm_copy2")
    try:
        subprocess.run(
            [binary, "test_dcm_copy2", "sender_address", "sender_aet",
             "receiver_aet", f"127.0.0.1:{port}", "test_token_123"],
            check=True,
        )
        t.join(timeout=5)

        req = server.last_request
        if req is None:
            print("FAIL: bookkeeper received no request")
            sys.exit(1)

        if req["path"] != "/register-dicom":
            print(f"FAIL: expected POST /register-dicom, got {req['path']}")
            sys.exit(1)

        if req["authorization"] != "Token test_token_123":
            print(f"FAIL: authorization = {req['authorization']!r}")
            sys.exit(1)

        if req["content_type"] != "application/x-www-form-urlencoded":
            print(f"FAIL: content_type = {req['content_type']!r}")
            sys.exit(1)

        body = req["body"]
        expected_filename = f"{SERIES_UID}#test_dcm_copy2"
        if body.get("filename", [None])[0] != expected_filename:
            print(f"FAIL: filename = {body.get('filename')!r}, expected {expected_filename!r}")
            sys.exit(1)

        if body.get("series_uid", [None])[0] != SERIES_UID:
            print(f"FAIL: series_uid = {body.get('series_uid')!r}")
            sys.exit(1)

        if not body.get("file_uid", [None])[0]:
            print("FAIL: file_uid missing or empty")
            sys.exit(1)

        print(req)
    finally:
        server.server_close()
        cleanup("test_dcm_copy2")
    print("  PASS")


def test_dict_default_path(bin_dir):
    """Test that DCMTK binaries find dicom.dic without DCMDICTPATH set."""
    print("test_dict_default_path")
    import os
    import tempfile

    storescu = os.path.join(bin_dir, "storescu")
    if not os.path.isfile(storescu):
        print(f"  SKIP: {storescu} not found")
        return

    # Run storescu --version with DCMDICTPATH explicitly unset.
    # If the compiled-in default path is wrong, stderr will contain
    # "no data dictionary loaded" or "Cannot open file".
    env = {k: v for k, v in os.environ.items() if k != "DCMDICTPATH"}
    result = subprocess.run(
        [storescu, "--version"],
        env=env,
        capture_output=True,
        timeout=5,
    )
    stderr = result.stderr.decode()
    if "no data dictionary loaded" in stderr or "Cannot open file" in stderr:
        print(f"FAIL: binary can't find dicom.dic without DCMDICTPATH")
        print(f"  stderr: {stderr}")
        sys.exit(1)
    print("  PASS")


def test_storescp_receive(bin_dir):
    """Test that storescp --fork can receive a DICOM file without crashing."""
    print("test_storescp_receive")
    import os
    import tempfile
    import time
    import signal

    storescp = os.path.join(bin_dir, "storescp")
    storescu = os.path.join(bin_dir, "storescu")
    dicom_dic = os.path.join(bin_dir, "dicom.dic")

    if not os.path.isfile(storescp):
        print(f"  SKIP: {storescp} not found")
        return
    if not os.path.isfile(storescu):
        print(f"  SKIP: {storescu} not found")
        return

    port = find_free_port()
    # Don't set DCMDICTPATH — rely on the compiled-in default path
    env = {k: v for k, v in os.environ.items() if k != "DCMDICTPATH"}

    with tempfile.TemporaryDirectory() as incoming:
        # Start storescp with --fork
        scp = subprocess.Popen(
            [storescp, "--fork", "--promiscuous", "-od", incoming, "+uf", str(port)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            time.sleep(1)  # let it bind

            if scp.poll() is not None:
                stderr = scp.stderr.read().decode()
                print(f"FAIL: storescp exited early (rc={scp.returncode})")
                print(f"  stderr: {stderr}")
                sys.exit(1)

            # Send a DICOM file via storescu
            result = subprocess.run(
                [storescu, "127.0.0.1", str(port), "test_dcm"],
                env=env,
                capture_output=True,
                timeout=15,
            )

            if result.returncode != 0:
                print(f"FAIL: storescu exit code {result.returncode}")
                print(f"  stderr: {result.stderr.decode()}")
                sys.exit(1)

            time.sleep(1)  # let storescp finish writing

            # Verify storescp is still running (didn't crash)
            if scp.poll() is not None:
                stderr = scp.stderr.read().decode()
                print(f"FAIL: storescp crashed after receive (rc={scp.returncode})")
                print(f"  stderr: {stderr}")
                sys.exit(1)

            # Verify a file was written to incoming dir
            received = list(Path(incoming).iterdir())
            if not received:
                print("FAIL: no files received in incoming directory")
                sys.exit(1)

            print(f"  received {len(received)} file(s): {[f.name for f in received]}")
        finally:
            scp.terminate()
            try:
                scp.wait(timeout=5)
            except subprocess.TimeoutExpired:
                scp.kill()
                scp.wait()
    print("  PASS")


if __name__ == "__main__":
    binary = sys.argv[1] if len(sys.argv) > 1 else "./getdcmtags"
    bin_dir = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Testing with binary: {binary}")
    test_basic_tags(binary)
    test_bookkeeper(binary)
    if bin_dir:
        test_dict_default_path(bin_dir)
        test_storescp_receive(bin_dir)
    print("All tests passed")
