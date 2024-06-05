import inspect
from importlib import import_module
from inspect import get_annotations, getmodule, isclass
from typing import Any, Callable, Literal, cast

from pydantic import BaseModel, Field

from .constants import PKG_NAME

RegistryType = Literal[
    "modelapi", "task", "solver", "plan", "scorer", "metric", "tool", "toolenv"
]


class RegistryInfo(BaseModel):
    type: RegistryType
    name: str
    metadata: dict[str, Any] = Field(default={})


def registry_add(o: object, info: RegistryInfo) -> None:
    r"""Add an object to the registry.

    Add the passed object to the registry using the RegistryInfo
    to index it for retrieval. The RegistryInfo is also added
    to the object as an attribute, which can retrieved by calling
    registry_info() on an object instance.

    Args:
        o (object): Object to be registered (Metric, Solver, etc.)
        info (RegistryInfo): Metadata (name, etc.) for object.
    """
    # tag the object
    setattr(o, REGISTRY_INFO, info)

    # add to registry
    registry[registry_key(info.type, info.name)] = o


def registry_tag(
    type: Callable[..., Any],
    o: object,
    info: RegistryInfo,
    *args: list[Any],
    **kwargs: dict[str, Any],
) -> None:
    r"""Tag an object w/ registry info.

    Tag the passed object with RegistryInfo. This function DOES NOT
    add the object to the registry (call registry_add() to both
    tag and add an object to the registry). Call registry_info()
    on a tagged/registered object to retrieve its info

    Args:
        type (T): type of object being tagged
        o (object): Object to be registered (Metric, Solver, etc.)
        info (RegistryInfo): Metadata (name, etc.) for object.
        *args (list[Any]): Creation arguments
        **kwargs (dict[str,Any]): Creation keyword arguments
    """
    # determine arg names and add them to kwargs
    named_params: dict[str, Any] = {}
    if len(args) > 0:
        params = list(inspect.signature(type).parameters.keys())
        for i, arg in enumerate(args):
            named_params[params[i]] = arg
    named_params |= kwargs

    # callables are not serializable so use their names
    for param in named_params.keys():
        if is_registry_object(named_params[param]):
            named_params[param] = registry_info(named_params[param]).name
        elif hasattr(named_params[param], "__name__"):
            named_params[param] = getattr(named_params[param], "__name__")
        else:
            named_params[param] = str(named_params[param])

    # set attribute
    setattr(o, REGISTRY_INFO, info)
    setattr(o, REGISTRY_PARAMS, named_params)


def registry_name(o: object, name: str) -> str:
    r"""Compute the registry name of an object.

    This function checks whether the passed object is in a package,
    and if it is, prepends the package name as a namespace
    """
    package = get_package_name(o)
    return f"{package}/{name}" if package else name


def registry_lookup(type: RegistryType, name: str) -> object | None:
    r"""Lookup an object in the registry by type and name.

    Objects that defined in inspect extension packages (i.e. not
    directly within the core inspect_ai package) must be namespaced
    (e.g. "fancy_prompts/jailbreaker")

    Args:
        type: Type of object to find
        name: Name of object to find

    Returns:
        Object or None if not found.
    """
    # first try
    object = registry.get(registry_key(type, name))
    if object:
        return object
    # unnamespaced objects can also be found in inspect_ai
    elif name.find("/") == -1:
        return registry.get(registry_key(type, f"{PKG_NAME}/{name}"))
    else:
        return None


def registry_find(predicate: Callable[[RegistryInfo], bool]) -> list[object]:
    r"""Find objects in the registry that match the passed predicate.

    Args:
        predicate (Callable[[RegistryInfo], bool]): Predicate to find

    Returns:
        List of registry objects found
    """
    return [object for object in registry.values() if predicate(registry_info(object))]


def registry_create(type: RegistryType, name: str, **kwargs: Any) -> object:
    r"""Create a registry object.

    Registry objects can be ordinary functions that implement a protocol,
    factory functions that return a function based on **kwargs, or classes
    deriving that can be created using **kwargs

    Args:
        type (RegistryType): Type of registry object to create
        name (str): Name of registry options to create
        **kwargs (Any): Optional creation arguments

    Returns:
        Registry object with registry info attribute
    """
    # lookup the object
    obj = registry_lookup(type, name)

    # forward registry info to the instantiated object
    def with_registry_info(o: object) -> object:
        return set_registry_info(o, registry_info(obj))

    if isclass(obj):
        return with_registry_info(obj(**kwargs))
    elif callable(obj):
        return_type = getattr(get_annotations(obj)["return"], "__name__", None)
        if return_type and return_type.lower() == type:
            return with_registry_info(obj(**kwargs))
        else:
            return obj
    else:
        raise ValueError(f"{name} was not found in the registry")


def registry_info(o: object) -> RegistryInfo:
    r"""Lookup RegistryInfo for an object.

    Args:
        o (object): Object to lookup info for

    Returns:
        RegistryInfo for object.
    """
    info = getattr(o, REGISTRY_INFO)
    if info:
        return cast(RegistryInfo, info)
    else:
        raise ValueError("Object does not have registry info")


def registry_params(o: object) -> dict[str, Any]:
    r"""Lookup parameters used to instantiate a registry object.

    Args:
        o (object): Object to lookup info for

    Returns:
        Dictionary of parameters used to instantiate object.
    """
    params = getattr(o, REGISTRY_PARAMS)
    if params is not None:
        return cast(dict[str, Any], params)
    else:
        raise ValueError("Object does not have registry info")


def registry_log_name(o: object) -> str:
    r"""Name of object for logging.

    Registry objects defined by the inspect_ai package have their
    prefix stripped when written to the log (they in turn can also
    be created/referenced without the prefix).

    Args:
        o (object): Object to get name for

    Returns:
        Name of object for logging.
    """
    name = registry_info(o).name
    return name.replace(f"{PKG_NAME}/", "", 1)


def registry_unqualified_name(o: object | RegistryInfo) -> str:
    r"""Unqualified name of object (i.e. without package prefix).

    Args:
        o (object | str): Object or name to get unqualified name for

    Returns:
        Unqualified name of object
    """
    info = o if isinstance(o, RegistryInfo) else registry_info(o)
    parts = info.name.split("/")
    if len(parts) == 1:
        return parts[0]
    else:
        return "/".join(parts[1:])


def is_registry_object(o: object, type: RegistryType | None = None) -> bool:
    r"""Check if an object is a registry object.

    Args:
        o (object): Object to lookup info for
        type: (RegistryType | None): Optional. Check for a specific type

    Returns:
        True if the object is a registry object (optionally of the specified
        type). Otherwise, False
    """
    info = getattr(o, REGISTRY_INFO, None)
    if info:
        reg_info = cast(RegistryInfo, info)
        if type:
            return reg_info.type == type
        else:
            return True
    else:
        return False


def set_registry_info(o: object, info: RegistryInfo) -> object:
    r"""Set the RegistryInfo for an object.

    Args:
        o (object): Object to set the registry info for
        info: (object): Registry info

    Returns:
        Passed object, with RegistryInfo attached
    """
    setattr(o, REGISTRY_INFO, info)
    return o


def registry_key(type: RegistryType, name: str) -> str:
    return f"{type}:{name}"


REGISTRY_INFO = "__registry_info__"
REGISTRY_PARAMS = "__registry_params__"
registry: dict[str, object] = {}


def get_package_name(o: object) -> str | None:
    module = getmodule(o)
    package = str(getattr(module, "__package__", ""))
    if package:
        package = package.split(".")[0]
        if package != "None":
            package_module = import_module(package)
            if package_module:
                package_path = getattr(package_module, "__path__", None)
                if package_path:
                    return package

    return None
