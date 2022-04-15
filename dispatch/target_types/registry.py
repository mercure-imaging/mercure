from typing import Dict
from common.types import Target, Any
from .base import TargetHandler


_registry: Dict[Target, TargetHandler] = {}
_registry_names: Dict[str, Target] = {}


def handler_for(target_type):
    def decorator(Cls):
        _registry[target_type] = Cls()
        _registry_names[target_type.get_name()] = target_type

        assert target_type != Target and issubclass(
            target_type, Target
        ), f"Target handlers must be handlers for Target subclasses, but {Cls.__name__} is registered on {target_type}"
        return Cls

    return decorator


def get_handler(target) -> TargetHandler:
    if isinstance(target, type):
        return _registry[target]
    if isinstance(target, str):
        try:
            return _registry[_registry_names[target]]
        except:
            raise ValueError(f"No handler for target {target}")

    return _registry[type(target)]


def type_from_name(name):
    try:
        return _registry_names[name]
    except:
        raise ValueError(f"No such target type {name}")


def target_types():
    return _registry.keys()
