from itertools import product
import time
from typing import Tuple
import os
import shutil
import unittest
from unittest.mock import call
import uuid
from pytest_mock import MockerFixture
import common
from common import notification
from common.monitor import task_event

import process.process_series
import router
import daiquiri
import processor, dispatcher
from common.constants import mercure_events, mercure_version

import json
from pprint import pprint
from common.types import *
import routing
import routing.generate_taskfile
from pathlib import Path

from testing_common import *

from docker.models.containers import ContainerCollection

from nomad.api.job import Job
from nomad.api.jobs import Jobs
import socket
import unittest.mock
logger = config.get_logger()

processor_path = Path()

def make_config(action, trigger_reception, trigger_completion, trigger_completion_on_request, trigger_error, do_request=False) -> Dict[str, Dict]:
    return {
        "modules": {
            "test_module_1": Module(docker_tag="busybox:stable",settings={"fizz":"buzz","result":{"value":[1,2,3,4],"__mercure_notification": {"text":"notification","requested": do_request}}}).dict(),
            "test_module_2": Module(docker_tag="busybox:stable",settings={"fizz":"bing","result":{"value":[100,200,300,400]}}).dict(),
        },
        "rules": {
            "catchall": Rule(
                rule="True",
                action=action,
                target="dummy" if action in ("both","route") else "",
                action_trigger="series",
                study_trigger_condition="timeout",
                notification_webhook="localhost:1234",
                processing_module=["test_module_1", "test_module_2"],
                processing_settings=[{"foo":"bar"},{"bar":"baz"}],
                processing_retain_images=True,
                notification_trigger_completion=trigger_completion,
                notification_trigger_reception=trigger_reception,
                notification_trigger_completion_on_request=trigger_completion_on_request,
                notification_trigger_error=trigger_error
            ).dict()
        },
    }

class CaptureValues(object):
    def __init__(self, func):
        self.func = func
        self.return_values = []

    def __call__(self, *args, **kwargs):
        answer = self.func(*args, **kwargs)
        self.return_values.append(answer)
        return answer

from unittest.mock import patch

@pytest.mark.asyncio
async def test_notifications(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture):
    assert hasattr(notification.trigger_notification_for_rule,'call_count')
    assert hasattr(notification.trigger_notification_for_rule,'spy_return')
    assert hasattr(notification.trigger_notification_for_rule,'assert_called_with')
    
    uuids = [str(uuid.uuid1()) for i in range(10000)]
    
    def generate_uuids() -> Iterator[str]:
        yield from uuids

    generator = generate_uuids()
    mocked.patch("uuid.uuid1", new=lambda: next(generator))


    options = product(["process","both"],*[(True,False)]*2)
    # options = [("both", True, True)]#, ("process", True, True)]
    n=0
    for action, on_reception, on_completion  in options: # type: ignore
        on_request, do_request, do_error, on_error = (False,False, False,False)
        logger.info(f"++++++++++ TESTING: {on_reception=}, {on_completion=}, {do_request=}, {on_request=}, {do_error=}, {on_error=}")
        task_id = uuids[n]
        new_task_id = uuids[n+1]
        # new_task_id = "new-task-" + str(uuid.uuid1())
        # task_id = "task-" + str(uuid.uuid1())
        # mock_task_ids(mocked,task_id, new_task_id)
        # mocked.patch("routing.route_series.parse_ascconv", new=lambda x: {})
        uid = "TESTFAKEUID"
        fs.create_file(f"/var/incoming/{uid}#bar.dcm", contents="asdfasdfafd")
        fs.create_file(f"/var/incoming/{uid}#bar.tags", contents="{}")

        config = mercure_config(
            {"process_runner": "docker", **make_config(action=action, trigger_reception=on_reception, trigger_completion=on_completion, trigger_completion_on_request=on_request, trigger_error=on_error, do_request=do_request)},
        )
        router.run_router()
        notification.trigger_notification_for_rule.assert_called_with("catchall", task_id, mercure_events.RECEPTION)
        assert notification.trigger_notification_for_rule.spy_return == on_reception # next(iter(config.rules.values())).notification_trigger_reception 

        fake_run = mocked.Mock(return_value=FakeDockerContainer(), side_effect=make_fake_processor(fs,mocked, do_error))  # type: ignore
        mocked.patch.object(ContainerCollection, "run", new=fake_run)
        await processor.run_processor()
        # assert notification.trigger_notification_for_rule.call_count == 2 
        # logger.info(notification.trigger_notification_for_rule.call_args_list)  # type: ignore
        dispatcher.dispatch()
        if not do_error:
            notification.trigger_notification_for_rule.assert_called_with( 
                "catchall",new_task_id, mercure_events.COMPLETION, "test_module_1: notification", unittest.mock.ANY, do_request)
            assert notification.trigger_notification_for_rule.spy_return == on_completion #or (do_request and on_request)) # next(iter(config.rules.values())).notification_trigger_completion
        else:
            notification.trigger_notification_for_rule.assert_called_with( 
                "catchall",new_task_id, mercure_events.ERROR,'', unittest.mock.ANY, False)
            assert notification.trigger_notification_for_rule.spy_return == on_error

        n = n+2