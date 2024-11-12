from enum import Enum, auto
import enum


@enum.unique
class StringEnum(Enum):
    """An enum class that can be converted to a string based on the name, so str(enum.FOO) == "FOO" """

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"<{self.__class__.__name__}.{self.name}>"

    def _generate_next_value_(name, *args):
        return name


class m_events(StringEnum):
    """Event types for general mercure monitoring."""

    UNKNOWN = auto()
    BOOT = auto()
    SHUTDOWN = auto()
    SHUTDOWN_REQUEST = auto()
    CONFIG_UPDATE = auto()
    PROCESSING = auto()


class w_events(StringEnum):
    """Event types for monitoring the webgui activity."""

    UNKNOWN = auto()
    LOGIN = auto()
    LOGIN_FAIL = auto()
    LOGOUT = auto()
    USER_CREATE = auto()
    USER_DELETE = auto()
    USER_EDIT = auto()
    RULE_CREATE = auto()
    RULE_DELETE = auto()
    RULE_EDIT = auto()
    TARGET_CREATE = auto()
    TARGET_DELETE = auto()
    TARGET_EDIT = auto()
    SERVICE_CONTROL = auto()
    CONFIG_EDIT = auto()


class task_event(StringEnum):
    """Event types for monitoring everything related to one specific series."""

    UNKNOWN = auto()
    REGISTER = auto()
    PROCESS_BEGIN = auto()
    PROCESS_COMPLETE = auto()
    DISCARD = auto()
    DISPATCH_BEGIN = auto()
    DISPATCH_COMPLETE = auto()
    CLEAN = auto()
    ERROR = auto()
    SUSPEND = auto()
    COMPLETE = auto()
    ASSIGN = auto()
    NOTIFICATION = auto()
    DELEGATE = auto()
    MOVE = auto()
    COPY = auto()
    REMOVE = auto()
    PROCESS_MODULE_BEGIN = auto()
    PROCESS_MODULE_COMPLETE = auto()
    
class severity(Enum):
    """Severity level associated to the mercure events."""

    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3


class FailStage(StringEnum):
    """Enum for the stages a task can fail at."""

    DISPATCHING = auto()
    PROCESSING = auto()
    ROUTING = auto()