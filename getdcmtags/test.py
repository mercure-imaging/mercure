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


if __name__ == "__main__":
    binary = sys.argv[1] if len(sys.argv) > 1 else "./getdcmtags"
    print(f"Testing with binary: {binary}")
    test_basic_tags(binary)
    test_bookkeeper(binary)
    print("All tests passed")
