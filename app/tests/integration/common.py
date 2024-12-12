import subprocess
import tempfile
from dataclasses import dataclass

import pydicom
import requests


def send_dicom(ds, dest_host, dest_port) -> None:
    with tempfile.NamedTemporaryFile('w') as ds_temp:
        ds.save_as(ds_temp.name)
        subprocess.run(["dcmsend", dest_host, str(dest_port), ds_temp.name], check=True)


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
