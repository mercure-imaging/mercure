from typing import Callable, Dict, KeysView, Type, Union
from common.types import Target
from .base import TargetHandler


_registry: Dict[Type[Target], TargetHandler] = {}
_registry_names: Dict[str, Type[Target]] = {}


# def register_handler_class(Cls: Type[TargetHandler]):
#     try:
#         target_type = typing.get_args(Cls.__orig_bases__[0])[0]
#     except Exception:
#         return None

#     if not isinstance(target_type, Target):
#         return None
#     _registry[target_type] = Cls()
#     _registry_names[target_type.get_name()] = target_type

#     assert target_type != Target and issubclass(
#         target_type, Target
#     ), f"Target handlers must be handlers for Target subclasses, but {Cls.__name__} is registered on {target_type}"
#     return Cls


def handler_for(target_type: Type[Target]) -> Callable[[Type[TargetHandler]], Type[TargetHandler]]:
    def decorator(Cls: Type[TargetHandler]):
        assert target_type != Target and issubclass(
            target_type, Target
        ), f"Target handlers must be handlers for Target subclasses, but {Cls.__name__} is registered on {target_type}"

        _registry[target_type] = Cls()
        _registry_names[target_type.get_name()] = target_type
        return Cls

    return decorator


def get_handler(target: Union[Target, Type[Target], str]) -> TargetHandler:
    if isinstance(target, Target):
        return _registry[type(target)]
    if isinstance(target, type):
        return _registry[target]
    if isinstance(target, str):
        try:
            return _registry[_registry_names[target]]
        except Exception:
            raise ValueError(f"No handler for target {target}")

    return _registry[type(target)]


def type_from_name(name) -> Type[Target]:
    try:
        return _registry_names[name]
    except Exception:
        raise ValueError(f"No such target type {name}")


def target_types() -> KeysView[Type[Target]]:
    return _registry.keys()
