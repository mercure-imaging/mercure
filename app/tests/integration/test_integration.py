import time
from pathlib import Path

import pytest
from common.types import FolderTarget, Module, Rule
from app.tests.integration.common import is_dicoms_in_folder, is_dicoms_received, is_series_registered, send_dicom
from tests.testing_common import create_minimal_dicom


@pytest.mark.parametrize("n_series", (2,))
@pytest.mark.skipif("os.getenv('TEST_FAST', False)")
def test_case_simple(mercure, mercure_config, mercure_base, receiver_port, bookkeeper_port, n_series):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="notification", action_trigger="series"
            ).dict(),
        }
    }
    mercure_config(config)
    supervisor = mercure(["receiver", "bookkeeper"])
    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Greg'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)
    time.sleep(2)
    is_dicoms_received(mercure_base, ds)
    supervisor.start_service("router:*")

    for n in range(1 + n_series // 2):
        try:
            is_dicoms_in_folder(mercure_base / "data" / "success", ds)
            is_series_registered(bookkeeper_port, ds)
            break
        except AssertionError:
            if n < n_series // 2 + 1:
                time.sleep(1)
            else:
                raise


@pytest.mark.parametrize("n_series", (2,))
@pytest.mark.skipif("os.getenv('TEST_FAST', False)")
def test_case_dispatch(mercure, mercure_config, mercure_base, receiver_port, bookkeeper_port, n_series):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="route", action_trigger="series", target="test_target"
            ).dict(),
        },
        "targets": {
            "test_target": FolderTarget(folder=str(mercure_base / "target")).dict()
        }
    }
    mercure_config(config)
    supervisor = mercure(["receiver", "router:*", "bookkeeper"])
    (mercure_base / "target").mkdir(parents=True, exist_ok=True)

    time.sleep(1)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Test'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)

    time.sleep(2 + n_series / 2)
    is_dicoms_in_folder(mercure_base / "data" / "outgoing", ds)

    supervisor.start_service("dispatcher:*")
    for n in range(2 + n_series // 2):
        try:
            is_dicoms_in_folder(mercure_base / "target", ds)
            is_series_registered(bookkeeper_port, ds)
        except AssertionError:
            if n < n_series // 2 + 2:
                time.sleep(1)
            else:
                raise


@pytest.mark.parametrize("n_series", (1,))
@pytest.mark.skipif("os.getenv('TEST_FAST', False)")
def test_case_process(mercure, mercure_config, mercure_base, receiver_port, bookkeeper_port, n_series):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="both", action_trigger="series", processing_module="dummy_module", target="test_target"
            ).dict(),
        },
        "modules": {
            "dummy_module": Module(
                docker_tag="mercureimaging/mercure-dummy-processor:latest"
            ).dict()
        },
        "targets": {
            "test_target": FolderTarget(folder=str(mercure_base / "target")).dict()
        }
    }
    mercure_config(config)
    mercure(["bookkeeper", "receiver", "router:*", "dispatcher:*", "processor:*"])
    time.sleep(5)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Test'}) for _ in range(n_series)]
    for d in ds:
        send_dicom(d, "localhost", receiver_port)

    for _ in range(60):
        try:
            is_dicoms_in_folder(mercure_base / "target", ds)
            break
        except AssertionError:
            time.sleep(1)
    else:
        raise Exception("Failed to find dicoms in target folder after 60 seconds.")
    is_series_registered(bookkeeper_port, ds)
    # t1.join(0.1)


@pytest.fixture(scope='function')
def inject_error():
    inject_path = Path("./dcm_inject_error")

    def inject(error_n):
        inject_path.write_text(str(error_n))
    yield inject
    inject_path.unlink(missing_ok=True)


@pytest.mark.skipif("os.getenv('TEST_FAST', False)")
@pytest.mark.parametrize("error", range(1, 8))
def test_case_error_inject(mercure, mercure_config, mercure_base, receiver_port, inject_error, error):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="notification", action_trigger="series"
            ).dict(),
        },
        "dicom_receiver": {
            "additional_tags": {"LUTFrameRange": "Value"}
        }
    }
    mercure_config(config)
    mercure(["receiver", "router:*"])
    time.sleep(2)
    ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Greg'}) for _ in range(1)]
    inject_error(error)
    for d in ds:
        send_dicom(d, "localhost", receiver_port)
    time.sleep(2)
    try:
        is_dicoms_in_folder(mercure_base / "data" / "error", ds)
        for d in (mercure_base / 'data' / "error").rglob('*'):
            if d.suffix == '.dcm':
                assert d.with_suffix('.dcm.error').exists(), f"Expected {d.with_suffix('.dcm.error')}"
            if d.suffix == '':
                assert d.with_suffix('.error').exists(), f"Expected {d.with_suffix('.error')}"
            if d.suffix == '.error':
                assert d.with_suffix('').exists(), f"Expected {d.with_suffix('')}"

    except AssertionError:
        for d in (mercure_base).rglob('*'):
            print(d)
        raise


@pytest.mark.skipif("os.getenv('TEST_FAST', False)")
def test_case_error_real(mercure, mercure_config, mercure_base, receiver_port, bookkeeper_port):
    config = {
        "rules": {
            "test_series": Rule(
                rule="True", action="notification", action_trigger="series"
            ).dict(),
        },
        "dicom_receiver": {
            "additional_tags": {"GarbageTag": "Value"}
        }
    }

    mercure_config(config)
    try:
        supervisor = mercure(["receiver"])
        time.sleep(1)
        ds = [create_minimal_dicom(None, None, additional_tags={'PatientName': 'Greg'}) for _ in range(1)]
        Path("./dcm_inject_error").write_text("3")

        for d in ds:
            send_dicom(d, "localhost", receiver_port)
        time.sleep(1)

        Path("./dcm_inject_error").unlink()
        is_dicoms_in_folder(mercure_base / "data" / "incoming" / "error", ds)
        supervisor.start_service("router:*")
        time.sleep(5)
        is_dicoms_in_folder(mercure_base / "data" / "error", ds)
        assert "Unable to read extra_tags file" in (
            next(d for d in (mercure_base / "data" / "error").glob('*.error')).read_text())
    finally:
        Path("./dicom_extra_tags").unlink(missing_ok=True)
