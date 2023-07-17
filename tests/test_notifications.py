import asyncio
from itertools import product
import unittest
from unittest.mock import call
import uuid
from pytest_mock import MockerFixture
from common import notification
import router
import processor, dispatcher
from common.constants import mercure_events
from collections.abc import Iterable
from pprint import pprint
from common.types import *
from pathlib import Path
from testing_common import *
from docker.models.containers import ContainerCollection
import unittest.mock
logger = config.get_logger()

processor_path = Path()

def make_config(action, trigger_reception, trigger_completion, trigger_completion_on_request, trigger_error, do_request) -> Dict[str, Dict]:
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
                notification_webhook="",
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

TF = (True, False)

def get_params(**params) -> Any:
    params_keys = list(params.keys())
    values_list: List[Any] = []

    for v in params.values():
        if not isinstance(v, Iterable):
            values_list.append((v,))
        else:
            values_list.append(v)
    
    cases = list(product(*values_list))
    cases_print = [[{True:"T",False:"F"}.get(v,v) for v in c] for c in cases]
    ids = [",".join([f"{param}={value}" for param, value in zip(params_keys, c)]) for c in cases_print]
    return dict(params_keys=params_keys, cases=cases, ids=ids)

def parametrize_with(*args) -> Any:
    cases = p_add(args)
    return pytest.mark.parametrize(",".join(cases["params_keys"]),cases["cases"], ids=cases["ids"])
import itertools

def p_add(c_info) -> Any:
    return dict(params_keys=c_info[0]["params_keys"], cases = list(itertools.chain(*[c["cases"] for c in c_info])), ids= list(itertools.chain(*[c["ids"] for c in c_info])))
    
p = get_params(action=["process","both"], on_reception=TF, on_completion=TF, on_request=TF, do_request=TF, do_error=TF, on_error=TF)
# TODO: routing errors?
p_route = get_params(action=["route"], on_reception=TF, on_completion=TF, on_request=False, do_request=False, do_error=False, on_error=False)
p_notification =  get_params(action=["notification"], on_reception=TF, on_completion=TF, on_request=False, do_request=False, do_error=False, on_error=False)
pytestmark = parametrize_with(p,p_route,p_notification)

@pytest.mark.asyncio
async def test_notifications(fs, mercure_config: Callable[[Dict], Config], mocked: MockerFixture, \
                              action, on_reception, on_completion, on_request, do_request, 
                              do_error, on_error):
    if (do_error and action == "route"):
        return
    assert hasattr(notification.trigger_notification_for_rule,"call_count")
    assert hasattr(notification.trigger_notification_for_rule,"spy_return")
    assert hasattr(notification.trigger_notification_for_rule,"assert_called_with")
    
    uuids = [str(uuid.uuid1()) for i in range(2)]
    
    def generate_uuids() -> Iterator[str]:
        yield from uuids

    generator = generate_uuids()
    mocked.patch("uuid.uuid1", new=lambda: next(generator))

    task_id = uuids[0]
    new_task_id = uuids[1]

    uid = "TESTFAKEUID"
    fs.create_file(f"/var/incoming/{uid}#bar.dcm", contents="asdfasdfafd")
    fs.create_file(f"/var/incoming/{uid}#bar.tags", contents="{}")

    config = mercure_config(
        {"process_runner": "docker", 
            **make_config(action=action, trigger_reception=on_reception, trigger_completion=on_completion, trigger_completion_on_request=on_request,
                           trigger_error=on_error, do_request=do_request)},
    )
    router.run_router()
    if action=="notification":
        notification.trigger_notification_for_rule.assert_has_calls( 
            [
                call("catchall", task_id, mercure_events.RECEPTION),
                call("catchall", task_id, mercure_events.COMPLETION)
            ])
        assert notification.trigger_notification_for_rule.spy_return == on_completion
        return
    else:
        notification.trigger_notification_for_rule.assert_called_with("catchall", task_id, mercure_events.RECEPTION)
    assert notification.trigger_notification_for_rule.spy_return == on_reception

    fake_run = mocked.Mock(return_value=FakeDockerContainer(), side_effect=make_fake_processor(fs,mocked, do_error))  # type: ignore
    mocked.patch.object(ContainerCollection, "run", new=fake_run)
    if action != "route":
        await processor.run_processor()
    # assert notification.trigger_notification_for_rule.call_count == 2 
    # logger.info(notification.trigger_notification_for_rule.call_args_list)  # type: ignore
    dispatcher.dispatch()
    if not do_error:
        notification.trigger_notification_for_rule.assert_called_with( 
            "catchall",new_task_id, mercure_events.COMPLETION, "test_module_1: notification" if action in ("process","both") else None, unittest.mock.ANY, on_request and do_request if action in ("process","both") else False)
        assert notification.trigger_notification_for_rule.spy_return == on_completion or (on_request and do_request)
    else:
        notification.trigger_notification_for_rule.assert_called_with( 
            "catchall",new_task_id, mercure_events.ERROR,'', unittest.mock.ANY, False)
        assert notification.trigger_notification_for_rule.spy_return == on_error

