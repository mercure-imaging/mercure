import asyncio
import json
import threading
from pathlib import Path

import graphyte

from common.monitor import s_events, send_series_event

# Global variable to broadcast when the process should terminate
terminate = False
loop = asyncio.get_event_loop()


def is_ready_for_sending(folder):
    """Checks if a case in the outgoing folder is ready for sending by the dispatcher.

    No lock file (.lock) should be in sending folder and no error file (.error),
    if there is one copy/move is not done yet. Also at least some dicom files
    should be there for sending. Also checks for a target.json file and if it is
    valid.
    """
    path = Path(folder)
    folder_status = (
        not (path / ".lock").exists()
        and not (path / ".error").exists()
        and not (path / ".sending").exists()
        and len(list(path.glob("*.dcm"))) > 0
    )
    content = is_target_json_valid(folder)
    if folder_status and content:
        return content
    return False


def has_been_send(folder):
    """Checks if the given folder has already been sent."""
    return (Path(folder) / "sent.txt").exists()


def is_target_json_valid(folder):
    """
    Checks if the target.json file exists and is also valid. Mandatory
    keys are target_ip, target_port and target_aet_target.
    """
    path = Path(folder) / "target.json"
    if not path.exists():
        return None

    with open(path, "r") as f:
        target = json.load(f)

    if not all(
        [key in target for key in ["target_ip", "target_port", "target_aet_target"]]
    ):
        send_series_event(
            s_events.ERROR,
            target.get("series_uid", None),
            0,
            target.get("target_name", None),
            f"target.json is missing a mandatory key {target}",
        )
        return None
    return target


def triggerTerminate():
    """Trigger that the processing loop should terminate after finishing the currently active task."""
    global terminate
    terminate = True


def isTerminated():
    """Checks if the process will terminate after the current task."""
    return terminate


async def sendToGraphite(*args, **kwargs):
    """Wrapper for asynchronous graphite call to avoid wait time of main loop."""
    if graphyte.default_sender == None:
        return
    graphyte.default_sender.send(*args, **kwargs)


def g_log(*args, **kwargs):
    """Sends diagnostic information to graphite (if configured)."""
    asyncio.run_coroutine_threadsafe(sendToGraphite(*args, **kwargs), loop)


class RepeatedTimer(object):
    """
    Helper class for running a continuous timer that is suspended
    while the worker function is running
    """

    def __init__(self, interval, function, exit_function, *args, **kwargs):
        self._timer        = None
        self.interval      = interval
        self.function      = function
        self.exit_function = exit_function
        self.args          = args
        self.kwargs        = kwargs
        self.is_running    = False

    def _run(self):
        """Callback function for the timer event. Will execute the defined function and restart
           the timer after completion, unless the eventloop has been asked to shut down."""
        global terminate
        self.is_running = False
        self.function(*self.args, **self.kwargs)
        if not terminate:
            self.start()
        else:
            self.exit_function(*self.args, **self.kwargs)

    def start(self):
        """Starts the timer for triggering the calllback after the defined interval."""
        if not self.is_running:
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        """Stops the timer and executes the defined exit callback function."""
        self._timer.cancel()
        self.is_running = False
        self.exit_function(*self.args, **self.kwargs)
