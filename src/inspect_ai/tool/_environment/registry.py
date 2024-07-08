from typing import Callable, cast

from inspect_ai._util.entrypoints import ensure_entry_points
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_find,
    registry_name,
    registry_unqualified_name,
)

from .environment import ToolEnvironment


def toolenv(name: str) -> Callable[..., type[ToolEnvironment]]:
    r"""Decorator for registering tool environments.

    Args:
        name (str): Name of ToolEnvironment type
    """

    def wrapper(
        toolenv_type: type[ToolEnvironment] | Callable[..., type[ToolEnvironment]],
    ) -> type[ToolEnvironment]:
        # resolve if its a function
        if not isinstance(toolenv_type, type):
            toolenv_type = toolenv_type()

        # determine name
        toolenv_name = registry_name(toolenv_type, name)

        # register
        return toolenv_register(toolenv_type, toolenv_name)

    return wrapper


def toolenv_register(
    toolenv_type: type[ToolEnvironment], name: str
) -> type[ToolEnvironment]:
    registry_add(
        toolenv_type,
        RegistryInfo(type="toolenv", name=name),
    )
    return toolenv_type


def registry_find_toolenv(envtype: str) -> type[ToolEnvironment]:
    # ensure external packages are loaded
    ensure_entry_points()

    # find a matching toolenv_type
    toolenv_types = registry_find(registry_match_toolenv(envtype))
    if len(toolenv_types) > 0:
        toolenv_type = cast(type[ToolEnvironment], toolenv_types[0])
        return toolenv_type
    else:
        raise ValueError(f"ToolEnvironment type '{envtype}' not recognized.")


def registry_has_toolenv(envtype: str) -> bool:
    # ensure external packages are loaded
    ensure_entry_points()

    # see if we have this type
    return len(registry_find(registry_match_toolenv(envtype))) > 0


def registry_match_toolenv(envtype: str) -> Callable[[RegistryInfo], bool]:
    # check for toolenv name matching unqualified name (package prefix not
    # required as toolenv providers are registred globally for ease of
    # use from the command line and .env files)
    def match(info: RegistryInfo) -> bool:
        if info.type == "toolenv" and registry_unqualified_name(info) == envtype:
            return True
        else:
            return False

    return match
