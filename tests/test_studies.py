from datetime import datetime, timedelta
import importlib
import os
import stat
import time
from typing import Tuple
from unittest.mock import call
import json
from pprint import pprint
import uuid

import pytest
from common.helper import FileLock
from common.monitor import m_events, task_event, severity
from common.types import *
import common
from pyfakefs.fake_filesystem import FakeFilesystem
from pyfakefs import fake_filesystem
import routing
import routing.generate_taskfile
import router, dispatcher
from pathlib import Path
from freezegun import freeze_time
from testing_common import *


def create_series(mocked, fs, config, study_uid, series_uid, series_description) -> Tuple[str, str]:
    # task_id = "test_task_" + str(uuid.uuid1())

    image_uid = str(uuid.uuid4())
    # mocked.patch("uuid.uuid1", new=lambda: task_id)

    tags = {"SeriesInstanceUID": series_uid, "StudyInstanceUID": study_uid, "SeriesDescription": series_description}
    # image_f = fs.create_file(f"{config.incoming_folder}/{series_uid}#{image_uid}.dcm", contents="asdfasdfafd")
    # tags_f = fs.create_file(f"{config.incoming_folder}/{series_uid}#{image_uid}.tags", contents=json.dumps(tags))
    image_f, tags_f = mock_incoming_uid(config, fs, series_uid, json.dumps(tags), image_uid)
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



def test_route_study_simple(fs: FakeFilesystem, mercure_config, mocked):
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
        frozen_time.tick(delta=timedelta(seconds=31))
        # Complete the study
        router.run_router()
        assert list(out_path.glob("**/*")) != []
