"""
test_bookkeeper.py
==================
"""
import bookkeeper as b
import testing_common
from testing_common import *


def test_config(mercure_config, mocker):
    c = mercure_config(
        {
            "rules": {
                "catchall": {
                    "rule": "True",
                    "target": "test_target",
                    "disabled": "False",
                    "fallback": "False",
                    "contact": "",
                    "comment": "",
                    "tags": "",
                    "action": "route",
                    "action_trigger": "series",
                    "study_trigger_condition": "timeout",
                    "study_trigger_series": "",
                    "priority": "normal",
                    "processing_module": "",
                    "processing_settings": "",
                    "notification_webhook": "",
                    "notification_payload": "",
                    "notification_trigger_reception": "False",
                    "notification_trigger_completion": "False",
                    "notification_trigger_error": "False",
                }
            }
        },
    )
    print(c.rules["catchall"])
