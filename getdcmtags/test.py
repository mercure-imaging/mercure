#!/usr/bin/env python3
"""Tests for getdcmtags binary."""

import argparse
from contextlib import suppress
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs

SERIES_UID = "1.2.276.0.7230010.3.1.3.9022104837472469675953272569912339663578"
FIXTURE_DIR = Path(__file__).resolve().parent


def run_helper(command, arguments, *, cwd=None, expected_returncode=0):
    """Check termination as well as output; Memcheck errors use exit status 99."""
    result = subprocess.run(command + list(map(str, arguments)), cwd=cwd,
                            capture_output=True, text=True, timeout=30)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode != expected_returncode:
        raise AssertionError(f"helper exit {result.returncode}, expected {expected_returncode}")
    return result


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
        run_helper(
            binary, ["test_dcm_copy", "sender_address", "sender_aet",
                     "receiver_aet", "0.0.0.0", "asdf",
                     "--set-tag", "forceKey=forcedValue"],
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


def test_character_sets(binary):
    """Synthetic fixtures contain no patient data; test without a bookkeeper."""
    for fixture, charset, patient_name in [
        ("test_dcm", "", ""),
        ("test_latin1.dcm", "ISO_IR 100", "Müller^Synthetic"),
        ("test_utf8.dcm", "ISO_IR 192", "山田^Synthetic"),
    ]:
        print(f"test_character_sets: {fixture}")
        with tempfile.TemporaryDirectory() as directory:
            incoming = Path(directory)
            shutil.copy(FIXTURE_DIR / fixture, incoming / "input")
            run_helper(binary, [incoming / "input", "sender", "SENDER", "MERCURE"], cwd=incoming)
            tags_paths = list(incoming.rglob("*.tags"))
            assert len(tags_paths) == 1, tags_paths
            tags = json.loads(tags_paths[0].read_text(encoding="utf-8"))
            check_key(tags, "SpecificCharacterSet", charset)
            check_key(tags, "PatientName", patient_name)
            check_key(tags, "SeriesInstanceUID", SERIES_UID)
            check_key(tags, "Filename", "input")
            assert len(list(incoming.rglob("*.dcm"))) == 1
        print("  PASS")


def test_error_after_conversion_setup(binary):
    """An ordinary error return must also close descriptors before cleanup."""
    print("test_error_after_conversion_setup")
    with tempfile.TemporaryDirectory() as directory:
        incoming = Path(directory)
        shutil.copy(FIXTURE_DIR / "test_latin1.dcm", incoming / "input")
        (incoming / "dcm_inject_error").write_text("5\n")
        run_helper(binary, [incoming / "input", "sender", "SENDER", "MERCURE",
                            "", "", "--inject-errors"], cwd=incoming, expected_returncode=1)
        error = incoming / "error" / "input.dcm.error"
        assert error.exists(), list(incoming.rglob("*"))
        assert "Unable to create series folder" in error.read_text()
        assert (incoming / "error" / "input.dcm").exists()
        assert not list(incoming.rglob("*.tags"))
    print("  PASS")


def test_bookkeeper(binary):
    """Test that getdcmtags sends the right POST to the bookkeeper."""
    print("test_bookkeeper")
    port = find_free_port()
    server = HTTPServer(("127.0.0.1", port), BookkeeperHandler)
    server.timeout = 10
    server.last_request = None
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    shutil.copy("test_dcm", "test_dcm_copy2")
    try:
        run_helper(
            binary, ["test_dcm_copy2", "sender_address", "sender_aet",
                     "receiver_aet", f"127.0.0.1:{port}", "test_token_123"],
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
        t.join(timeout=11)
        server.server_close()
        cleanup("test_dcm_copy2")
    print("  PASS")


def test_dict_default_path(bin_dir):
    """Test that DCMTK binaries find dicom.dic without DCMDICTPATH set."""
    print("test_dict_default_path")
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
        print("FAIL: binary can't find dicom.dic without DCMDICTPATH")
        print(f"  stderr: {stderr}")
        sys.exit(1)
    print("  PASS")


def test_storescp_receive(bin_dir, binary):
    """Check the real reception hook, including the helper's exit status."""
    print("test_storescp_receive")
    storescp = os.path.join(bin_dir, "storescp")
    storescu = os.path.join(bin_dir, "storescu")

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
        status_path = Path(incoming) / "helper.status"
        hook = (f'{shlex.join(binary)} "{incoming}/#f" "#r" "#a" "#c"; '
                f'status=$?; printf "%s\\n" "$status" > {shlex.quote(str(status_path))}.tmp; '
                f'mv {shlex.quote(str(status_path))}.tmp {shlex.quote(str(status_path))}')
        # Start storescp with --fork
        scp = subprocess.Popen(
            [storescp, "--fork", "--promiscuous", "-od", incoming, "+uf", "-xcr", hook, str(port)],
            env=env,
            start_new_session=True,
        )
        try:
            time.sleep(1)  # let it bind

            if scp.poll() is not None:
                raise AssertionError(f"storescp exited early (rc={scp.returncode})")

            # Send a DICOM file via storescu
            result = subprocess.run(
                [storescu, "127.0.0.1", str(port), str(FIXTURE_DIR / "test_latin1.dcm")],
                env=env,
                capture_output=True,
                timeout=15,
            )

            if result.returncode != 0:
                print(f"FAIL: storescu exit code {result.returncode}")
                print(f"  stderr: {result.stderr.decode()}")
                sys.exit(1)

            deadline = time.monotonic() + 30
            while not status_path.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            assert status_path.exists(), "reception hook did not finish"
            assert status_path.read_text().strip() == "0", "reception hook failed"

            # Verify storescp is still running (didn't crash)
            if scp.poll() is not None:
                raise AssertionError(f"storescp crashed after receive (rc={scp.returncode})")

            # Verify a file was written to incoming dir
            tags_paths = list(Path(incoming).rglob("*.tags"))
            assert len(tags_paths) == 1, tags_paths
            tags = json.loads(tags_paths[0].read_text(encoding="utf-8"))
            check_key(tags, "PatientName", "Müller^Synthetic")
            check_key(tags, "SeriesInstanceUID", SERIES_UID)
            assert len(list(Path(incoming).rglob("*.dcm"))) == 1
        finally:
            with suppress(ProcessLookupError):
                os.killpg(scp.pid, signal.SIGTERM)
            try:
                scp.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(scp.pid, signal.SIGKILL)
                scp.wait()
    print("  PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", nargs="?", default="./getdcmtags")
    parser.add_argument("bin_dir", nargs="?")
    parser.add_argument("--valgrind", action="store_true", help="check helper memory access at shutdown")
    args = parser.parse_args()
    binary = [str(Path(args.binary).resolve())]
    bin_dir = str(Path(args.bin_dir).resolve()) if args.bin_dir else None
    dictionary = Path(bin_dir or "bin/dcmtk") / "dicom.dic"
    if dictionary.exists():
        os.environ["DCMDICTPATH"] = str(dictionary.resolve())
    if args.valgrind:
        binary = ["valgrind", "--tool=memcheck", "--error-exitcode=99", "--leak-check=no",
                  "--num-callers=24"] + binary
    print(f"Testing with binary: {binary}")
    test_basic_tags(binary)
    test_character_sets(binary)
    test_error_after_conversion_setup(binary)
    test_bookkeeper(binary)
    if bin_dir:
        test_dict_default_path(bin_dir)
        test_storescp_receive(bin_dir, binary)
    print("All tests passed")
