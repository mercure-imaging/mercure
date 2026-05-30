import os
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pydicom
import requests


def _here() -> Path:
    """Return the project root (the directory that contains the 'app' subdirectory)."""
    cwd = Path(os.getcwd()).resolve()
    if (cwd / "app").exists():
        return cwd
    return cwd.parent


def _app() -> Path:
    """Return the app directory (project root / 'app')."""
    return _here() / "app"


def wait_for_port(host: str, port: int, timeout: float = 30.0, interval: float = 0.25) -> None:
    """Block until a TCP port is accepting connections, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection((host, port), timeout=interval):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Port {host}:{port} did not open within {timeout}s")
            time.sleep(interval)


def wait_for(fn, timeout: float = 30.0, interval: float = 0.25, msg: str = "") -> None:
    """Poll fn() until it stops raising AssertionError, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    last_exc: AssertionError = AssertionError("never ran")
    while True:
        try:
            fn()
            return
        except AssertionError as e:
            last_exc = e
            if time.monotonic() >= deadline:
                raise TimeoutError(msg or f"Condition not met within {timeout}s") from last_exc
            time.sleep(interval)


def send_dicom(ds, dest_host, dest_port, retries=10, retry_delay=1.0) -> None:
    dcmsend = _app() / "bin" / "dcmtk" / "dcmsend"
    dicom_dic = _app() / "bin" / "dcmtk" / "dicom.dic"
    env = os.environ.copy()
    env["DCMDICTPATH"] = str(dicom_dic)
    wait_for_port(dest_host, dest_port)
    with tempfile.NamedTemporaryFile(suffix='.dcm') as ds_temp:
        ds.save_as(ds_temp.name)
        for attempt in range(retries):
            result = subprocess.run([str(dcmsend), dest_host, str(dest_port), ds_temp.name], env=env)
            if result.returncode == 0:
                return
            if attempt < retries - 1:
                time.sleep(retry_delay)
        raise RuntimeError(
            f"dcmsend to {dest_host}:{dest_port} failed after {retries} attempts "
            f"(last exit code: {result.returncode})"
        )


@dataclass
class MercureService:
    name: str
    command: str
    numprocs: int = 1
    stopasgroup: bool = False
    startsecs: int = 0


def is_dicoms_received(mercure_base, dicoms) -> None:
    dicoms_recieved = set()
    for series_folder in (mercure_base / 'data' / 'incoming').glob('*/'):
        for dicom in series_folder.glob('*.dcm'):
            ds_ = pydicom.dcmread(dicom)
            assert ds_.SeriesInstanceUID == series_folder.name
            assert ds_.SOPInstanceUID not in dicoms_recieved
            dicoms_recieved.add(ds_.SOPInstanceUID)

    assert dicoms_recieved == set(ds.SOPInstanceUID for ds in dicoms)
    print(f"Received {len(dicoms)} dicoms as expected")


def is_dicoms_in_folder(folder, dicoms) -> None:
    uids_found = set()
    print(f"Looking for dicoms in {folder}")
    dicoms_found = []
    for f in folder.rglob('*'):
        if not f.is_file():
            continue
        if f.suffix == '.dcm':
            dicoms_found.append(f)
        if f.suffix not in ('.error', '.tags'):
            dicoms_found.append(f)
    print("Dicoms", dicoms_found)
    for dicom in dicoms_found:

        try:
            uid = pydicom.dcmread(dicom).SOPInstanceUID
            uids_found.add(uid)
        except Exception:
            pass
    try:
        assert uids_found == set(ds.SOPInstanceUID for ds in dicoms), f"Dicoms missing from {folder}"
    except Exception:
        print("Expected dicoms not found")
        for dicom in folder.glob('**/*.dcm'):
            print(dicom)
        raise
    print(f"Found {len(dicoms)} dicoms in {folder.name} as expected")


def is_series_registered(bookkeeper_port, dicoms) -> None:
    result = requests.get(f"http://localhost:{bookkeeper_port}/query/series",
                          headers={"Authorization": "Token test"})
    assert result.status_code == 200
    result_json = result.json()
    assert set([r['series_uid'] for r in result_json]) == set([d.SeriesInstanceUID for d in dicoms])
