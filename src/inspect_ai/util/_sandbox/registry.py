from typing import Callable, Type, TypeVar, cast

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_find,
    registry_name,
    registry_unqualified_name,
)

from .environment import SandboxEnvironment

T = TypeVar("T", bound=SandboxEnvironment)


def sandboxenv(name: str) -> Callable[..., Type[T]]:
    r"""Decorator for registering sandbox environments.

    Args:
        name (str): Name of SandboxEnvironment type
    """

    def wrapper(sandboxenv_type: Type[T] | Callable[..., Type[T]]) -> Type[T]:
        # resolve if its a function
        if not isinstance(sandboxenv_type, type):
            sandboxenv_type = sandboxenv_type()
        # determine name
        sandboxenv_name = registry_name(sandboxenv_type, name)

        # register
        return sandboxenv_register(sandboxenv_type, sandboxenv_name)

    return wrapper


def sandboxenv_register(sandboxenv_type: Type[T], name: str) -> Type[T]:
    registry_add(
        sandboxenv_type,
        RegistryInfo(type="sandboxenv", name=name),
    )
    return sandboxenv_type


def registry_find_sandboxenv(envtype: str) -> type[SandboxEnvironment]:
    # find a matching sandboxenv_type
    sanxboxenv_types = registry_find(registry_match_sandboxenv(envtype))
    if len(sanxboxenv_types) > 0:
        sandboxenv_type = cast(type[SandboxEnvironment], sanxboxenv_types[0])
        return sandboxenv_type
    else:
        raise ValueError(f"SandboxEnvironment type '{envtype}' not recognized.")


def registry_has_sandboxenv(envtype: str) -> bool:
    # see if we have this type
    return len(registry_find(registry_match_sandboxenv(envtype))) > 0


def registry_match_sandboxenv(envtype: str) -> Callable[[RegistryInfo], bool]:
    # check for sandboxenv name matching unqualified name (package prefix not
    # required as sandboxenv providers are registred globally for ease of
    # use from the command line and .env files)
    def match(info: RegistryInfo) -> bool:
        if info.type == "sandboxenv" and registry_unqualified_name(info) == envtype:
            return True
        else:
            return False

    return match
