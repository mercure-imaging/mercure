import asyncio
import shutil
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Tuple

import pytest
from common import notification
from common.constants import mercure_events, mercure_names
from common.types import Module, Rule
from freezegun import freeze_time
from nomad.api.job import Job
from nomad.api.jobs import Jobs
from process import processor
from pyfakefs.fake_filesystem import FakeFilesystem
from routing import router

from .testing_common import mock_incoming_uid


def create_series(mocked, fs, config, study_uid, series_uid, series_description, study_description="") -> Tuple[str, str]:
    # task_id = "test_task_" + str(uuid.uuid1())

    image_uid = str(uuid.uuid4())
    # mocked.patch("uuid.uuid1", new=lambda: task_id)

    tags = {"SeriesInstanceUID": series_uid, "StudyInstanceUID": study_uid,
            "SeriesDescription": series_description, "StudyDescription": study_description}
    # image_f = fs.create_file(f"{config.incoming_folder}/{series_uid}#{image_uid}.dcm", contents="asdfasdfafd")
    # tags_f = fs.create_file(f"{config.incoming_folder}/{series_uid}#{image_uid}.tags", contents=json.dumps(tags))
    image_f, tags_f = mock_incoming_uid(config, fs, series_uid, tags, image_uid)
    return image_f, tags_f


def test_route_study_pending(fs: FakeFilesystem, mercure_config, mocked):
    """
    Test that a study with a pending series is not routed until the pending series itself times out.
    """
    config = mercure_config(
        {
            "series_complete_trigger": 10,
            "study_complete_trigger": 30,
            "rules": {
                "route_study": Rule(
                    rule="True",  # """@StudyDescription@ == "foo" """,
                    action="route",
                    study_trigger_condition="timeout",
                    target="test_target_2",
                    action_trigger="study",
                ).dict(),
            },
        }
    )
    study_uid = str(uuid.uuid4())
    series_uid = str(uuid.uuid4())
    series_description = "test_series_complete"
    out_path = Path(config.outgoing_folder)

    with freeze_time("2020-01-01 00:00:00") as frozen_time:
        # Create the initial series.
        create_series(mocked, fs, config, study_uid, series_uid, series_description)
        frozen_time.tick(delta=timedelta(seconds=11))
        # Run the router as the first series completes to generate a study task
        router.run_router()
        frozen_time.tick(delta=timedelta(seconds=25))  # The study has nearly timed out...
        # A new incomplete series is created
        series_uid_incomplete = "pending-" + str(uuid.uuid4())
        create_series(mocked, fs, config, study_uid, series_uid_incomplete, "test_series_incomplete")
        frozen_time.tick(delta=timedelta(seconds=7))
        # The new series hasn't completed yet, so the study hasn't timed out yet
        router.run_router()
        # So the study hasn't been routed yet
        assert list(out_path.glob("**/*")) == []
        frozen_time.tick(delta=timedelta(seconds=5))
        # The new series has completed
        router.run_router()
        # This reset the clock on the study timeout
        assert list(out_path.glob("**/*")) == []
        frozen_time.tick(delta=timedelta(seconds=35))
        # The study has timed out
        router.run_router()
        assert list(out_path.glob("**/*")) != []


@pytest.mark.parametrize("action, force", [("route", True),
                                           ("route", False),
                                           ("notification", False)])
def test_route_study_simple(fs: FakeFilesystem, mercure_config, mocked, action, force):
    """
    Test that a study with a pending series is not routed until the pending series itself times out.
    """
    config = mercure_config(
        {
            "series_complete_trigger": 10,
            "study_complete_trigger": 30,
            "rules": {
                "route_study": Rule(
                    rule="True",
                    action="route" if action == "route" else "notification",
                    study_trigger_condition="timeout",
                    target="test_target_2",
                    action_trigger="study",
                ).dict(),
            },
        }
    )
    study_uid = str(uuid.uuid4())
    series_uid = str(uuid.uuid4())
    series_description = "test_series_complete"
    out_path = Path(config.outgoing_folder)

    with freeze_time("2020-01-01 00:00:00") as frozen_time:
        # Create the initial series.
        create_series(mocked, fs, config, study_uid, series_uid, series_description)
        frozen_time.tick(delta=timedelta(seconds=11))
        # Run the router as the first series completes to generate a study task
        router.run_router()
        if force:
            (next(Path(config.studies_folder).iterdir()) / mercure_names.FORCE_COMPLETE).touch()
        else:
            frozen_time.tick(delta=timedelta(seconds=31))
        # Complete the study
        router.run_router()
        if action == "route":
            assert list(out_path.glob("**/*")) != []
        else:
            assert list(Path(config.success_folder).glob("**/*")) != []
            notification.trigger_notification_for_rule.assert_has_calls(  # type: ignore
                [
                    unittest.mock.call("route_study", unittest.mock.ANY, mercure_events.RECEIVED, task=unittest.mock.ANY),
                    unittest.mock.call("route_study", unittest.mock.ANY, mercure_events.COMPLETED, task=unittest.mock.ANY)
                ])


def test_route_study_error(fs: FakeFilesystem, mercure_config, mocked):
    """
    Test that a study with a pending series is not routed until the pending series itself times out.
    """
    config = mercure_config(
        {
            "series_complete_trigger": 10,
            "study_complete_trigger": 30,
            "rules": {
                "route_study": Rule(
                    rule="True",  # """@StudyDescription@ == "foo" """,
                    action="route",
                    study_trigger_condition="timeout",
                    target="test_target_2",
                    action_trigger="study",
                ).dict(),
            },
        }
    )
    study_uid = str(uuid.uuid4())
    series_uid = str(uuid.uuid4())
    series_description = "test_series_complete"
    # out_path = Path(config.outgoing_folder)

    with freeze_time("2020-01-01 00:00:00") as frozen_time:
        # Create the initial series.
        create_series(mocked, fs, config, study_uid, series_uid, series_description)
        frozen_time.tick(delta=timedelta(seconds=11))
        # Run the router as the first series completes to generate a study task
        router.run_router()
        # mocked.patch.object(helper.FileLock, "__init__" new=lambda x: raise Exception("oops"))
        # TODO: simulate an exception in  route_study
        mocked.patch("routing.route_studies.route_study", side_effect=lambda x: False)
        frozen_time.tick(delta=timedelta(seconds=31))
        router.run_router()
        assert list(Path(config.error_folder).glob("**/*")) != []


@pytest.mark.parametrize("do_error", [True, False])
def test_route_study_processing(fs: FakeFilesystem, mercure_config, mocked, do_error):
    config = mercure_config(
        {
            "process_runner": "nomad",
            "modules": {
                "test_module_1": Module(docker_tag="busybox:stable",
                                        settings={"fizz": "buzz", "result": {"value": [1, 2, 3, 4]}}).dict(),
            },
            "series_complete_trigger": 10,
            "study_complete_trigger": 30,
            "rules": {
                "route_study": Rule(
                    rule="True",  # """@StudyDescription@ == "foo" """,
                    action="both",
                    study_trigger_condition="timeout",
                    target="test_target",
                    processing_module=["test_module_1" if not do_error else "missing_module"],
                    action_trigger="study",
                ).dict(),
            },
        }
    )
    fs.create_file("nomad/mercure-processor-template.nomad", contents="foo")
    mocked.patch.object(Jobs, "parse", new=lambda x, y: {})

    study_uid = str(uuid.uuid4())
    series_uid = str(uuid.uuid4())
    series_description = "test_series_complete"
    processing_path = Path(config.processing_folder)

    with freeze_time("2020-01-01 00:00:00") as frozen_time:
        # Create the initial series.
        create_series(mocked, fs, config, study_uid, series_uid, series_description)
        frozen_time.tick(delta=timedelta(seconds=11))
        # Run the router as the first series completes to generate a study task
        router.run_router()
        frozen_time.tick(delta=timedelta(seconds=31))
        # Complete the study
        router.run_router()
        assert list(processing_path.glob("**/*")) != []
        processor_path = next(Path("/var/processing").iterdir())

        def fake_processor(tag=None, meta=None, do_process=True, **kwargs):
            in_ = processor_path / "in"
            out_ = processor_path / "out"
            # print(f"Processing {processor_path}")
            for child in in_.iterdir():
                # print(f"Moving {child} to {out_ / child.name})")
                shutil.copy(child, out_ / child.name)
            return unittest.mock.DEFAULT

        fake_run = mocked.Mock(
            side_effect=fake_processor,
            return_value={
                "DispatchedJobID": "mercure-processor/dispatch-1624378734-e8388181",
                "EvalID": "f2fd681b-bc41-50cc-3d15-79f2f5c661e2",
                "EvalCreateIndex": 1138,
                "JobCreateIndex": 1137,
                "Index": 1138,
            },
        )
        mocked.patch.object(Job, "get_allocations", new=lambda x, y: None)
        mocked.patch.object(Job, "register_job", new=lambda *args: None)
        mocked.patch.object(Job, "dispatch_job", new=fake_run)
        mocked.patch.object(Job, "get_job", new=lambda x, y: dict(Status="dead"))

        asyncio.run(processor.run_processor())
        # await processor.run_processor()
        assert fake_run.called is not do_error
        if do_error:
            assert list(Path(config.error_folder).glob("**/*")) != [], "Error folder should not be empty."
        else:
            assert list(Path(config.outgoing_folder).glob("**/*")) != [], "Outgoing folder should not be empty."


def test_route_study_series_trigger(fs: FakeFilesystem, mercure_config, mocked):
    """
    Test that a study with a pending series is not routed until the pending series itself times out.
    """
    config = mercure_config(
        {
            "series_complete_trigger": 5,
            "study_complete_trigger": 30,
            "rules": {
                "route_study": Rule(
                    rule="True",  # """@StudyDescription@ == "foo" """,
                    action="route",
                    study_trigger_condition="received_series",
                    study_trigger_series=" 'test_series_complete' ",
                    target="test_target_2",
                    action_trigger="study",
                ).dict(),
            },
        }
    )
    study_uid = str(uuid.uuid4())
    series_uid = str(uuid.uuid4())
    series_description = "test_series_complete"
    out_path = Path(config.outgoing_folder)

    with freeze_time("2020-01-01 00:00:00") as frozen_time:
        # Create the initial series.
        create_series(mocked, fs, config, study_uid, series_uid, series_description)
        frozen_time.tick(delta=timedelta(seconds=4))
        create_series(mocked, fs, config, study_uid, str(uuid.uuid4()), "pending")
        router.run_router()
        assert list(out_path.glob("**/*")) == []  # Pending series should prevent routing
        frozen_time.tick(delta=timedelta(seconds=2))  # Tick to the point that the pending series is timed out
        router.run_router()
        assert list(out_path.glob("**/*")) != []

# def test_route_study_multiple_series(fs: FakeFilesystem, mercure_config, mocked):
#     config = mercure_config({
#         "series_complete_trigger": 1,
#         "study_complete_trigger": 30,
#         "rules": {
#             "study_rule": Rule(
#                 rule="@StudyDescription@ == 'MultiSeries'",
#                 action="route",
#                 action_trigger="study",
#                 study_trigger_condition="received_series",
#                 study_trigger_series="'Series1' and 'Series2'",
#                 target="test_target_2"
#             ).dict()
#         }
#     })

#     study_uid = str(uuid.uuid4())
#     with freeze_time("2020-01-01 00:00:00") as frozen_time:
#         create_series(mocked, fs, config, study_uid, "series1", "Series1", "MultiSeries")
#         frozen_time.tick(delta=timedelta(seconds=2))
#         router.run_router()
#         create_series(mocked, fs, config, study_uid, "series2", "Series2", "MultiSeries")
#         frozen_time.tick(delta=timedelta(seconds=2))
#         router.run_router()

#     routing.route_studies.route_study.assert_called_once()
#     routing.route_studies.move_study_folder.assert_called_once()
#     assert routing.route_studies.move_study_folder.call_args[0][2] == "OUTGOING"
#     outgoing = Path(config.outgoing_folder)
#     for k in Path("/var").glob("**/*.dcm"):
#         print(k)
#     assert ( outgoing / study_uid).exists()

#     assert list((outgoing / study_uid).glob("**/*.dcm")) != []


@pytest.mark.parametrize("force_complete_action", ["ignore", "proceed", "discard"])
def test_route_study_force_complete(fs: FakeFilesystem, mercure_config, mocked, force_complete_action):
    """
    Test that a study exceeding the force completion timeout is handled according to the action specified.
    """
    config = mercure_config(
        {
            "series_complete_trigger": 10,
            "study_complete_trigger": 30,
            "study_forcecomplete_trigger": 60,
            "rules": {
                "route_study": Rule(
                    rule="True",
                    action="route",
                    study_trigger_condition="received_series",
                    study_trigger_series=" 'test_series_complete' and 'test_series_missing' ",
                    target="test_target_2",
                    action_trigger="study",
                    study_force_completion_action=force_complete_action,
                ).dict(),
            },
        }
    )
    study_uid = str(uuid.uuid4())
    series_uid = str(uuid.uuid4())
    series_description = "test_series_complete"
    out_path = Path(config.outgoing_folder)
    discard_path = Path(config.discard_folder)

    with freeze_time("2020-01-01 00:00:00") as frozen_time:
        # Create the initial series.
        create_series(mocked, fs, config, study_uid, series_uid, series_description)
        frozen_time.tick(delta=timedelta(seconds=11))
        # Run the router as the first series completes to generate a study task.
        router.run_router()
        frozen_time.tick(delta=timedelta(seconds=61))
        # Run router after force complete trigger.
        router.run_router()

        if force_complete_action == "ignore":
            # ensure that the study is not routed
            assert list(out_path.glob("**/*")) == []
            assert list(discard_path.glob("**/*")) == []
        elif force_complete_action == "proceed":
            # run router again to proceed with the force complete file.
            router.run_router()
            assert list(out_path.glob("**/*")) != []
            assert list(discard_path.glob("**/*")) == []
        elif force_complete_action == "discard":
            assert list(discard_path.glob("**/*")) != []
            assert list(out_path.glob("**/*")) == []
