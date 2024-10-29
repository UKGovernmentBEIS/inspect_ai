import inspect
from inspect import get_annotations, isclass
from typing import Any, Callable, Literal, TypedDict, TypeGuard, cast

from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python

from inspect_ai._util.package import get_installed_package_name

from .constants import PKG_NAME
from .entrypoints import ensure_entry_points

obj_type = type

RegistryType = Literal[
    "modelapi",
    "task",
    "solver",
    "plan",
    "scorer",
    "metric",
    "tool",
    "sandboxenv",
    "score_reducer",
    "approver",
]


class RegistryInfo(BaseModel):
    type: RegistryType
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    _registry[registry_key(info.type, info.name)] = o


def registry_tag(
    type: Callable[..., Any],
    o: object,
    info: RegistryInfo,
    *args: Any,
    **kwargs: Any,
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
    # bind arguments to params
    named_params: dict[str, Any] = {}
    bound_params = inspect.signature(type).bind(*args, **kwargs)
    for param, value in bound_params.arguments.items():
        named_params[param] = registry_value(value)

    # callables are not serializable so use their names
    for param in named_params.keys():
        if is_registry_object(named_params[param]):
            named_params[param] = registry_info(named_params[param]).name
        elif callable(named_params[param]) and hasattr(named_params[param], "__name__"):
            named_params[param] = getattr(named_params[param], "__name__")
        elif isinstance(named_params[param], dict | list):
            named_params[param] = to_jsonable_python(
                named_params[param], fallback=lambda x: getattr(x, "__name__", None)
            )
        elif isinstance(named_params[param], str | int | float | str | bool | None):
            named_params[param] = named_params[param]
        else:
            named_params[param] = (
                getattr(named_params[param], "name", None)
                or getattr(named_params[param], "__name__", None)
                or getattr(obj_type(named_params[param]), "__name__", None)
                or "<unknown>"
            )

    # set attribute
    setattr(o, REGISTRY_INFO, info)
    setattr(o, REGISTRY_PARAMS, named_params)


def registry_name(o: object, name: str) -> str:
    r"""Compute the registry name of an object.

    This function checks whether the passed object is in a package,
    and if it is, prepends the package name as a namespace
    """
    package = get_installed_package_name(o)
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

    def _lookup() -> object | None:
        # first try
        object = _registry.get(registry_key(type, name))
        if object:
            return object
        # unnamespaced objects can also be found in inspect_ai
        elif name.find("/") == -1:
            return _registry.get(registry_key(type, f"{PKG_NAME}/{name}"))
        else:
            return None

    o = _lookup()

    # try to recover
    if o is None:
        # load entry points for this package as required
        if name.find("/") != -1 and name.find(".") == -1:
            package = name.split("/")[0]
            ensure_entry_points(package)

        return _lookup()
    else:
        return o


def registry_find(predicate: Callable[[RegistryInfo], bool]) -> list[object]:
    r"""Find objects in the registry that match the passed predicate.

    Args:
        predicate (Callable[[RegistryInfo], bool]): Predicate to find

    Returns:
        List of registry objects found
    """

    def _find() -> list[object]:
        return [
            object for object in _registry.values() if predicate(registry_info(object))
        ]

    o = _find()
    if len(o) == 0:
        ensure_entry_points()
        return _find()
    else:
        return o


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

    # instantiate registry objects
    for param in kwargs.keys():
        value = kwargs[param]
        if is_registry_dict(value):
            kwargs[param] = registry_create(
                value["type"], value["name"], **value["params"]
            )

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
    info = getattr(o, REGISTRY_INFO, None)
    if info is not None:
        return cast(RegistryInfo, info)
    else:
        name = getattr(o, "__name__", "unknown")
        decorator = " @solver " if name == "solve" else " "
        raise ValueError(
            f"Object '{name}' does not have registry info. Did you forget to add a{decorator}decorator somewhere?"
        )


def registry_params(o: object) -> dict[str, Any]:
    r"""Lookup parameters used to instantiate a registry object.

    Args:
        o (object): Object to lookup info for

    Returns:
        Dictionary of parameters used to instantiate object.
    """
    params = getattr(o, REGISTRY_PARAMS, None)
    if params is not None:
        return cast(dict[str, Any], params)
    else:
        raise ValueError("Object does not have registry info")


def registry_log_name(o: str | object) -> str:
    r"""Name of object for logging.

    Registry objects defined by the inspect_ai package have their
    prefix stripped when written to the log (they in turn can also
    be created/referenced without the prefix).

    Args:
        o (str | object): Name or object to get name for

    Returns:
        Name of object for logging.
    """
    name = o if isinstance(o, str) else registry_info(o).name
    return name.replace(f"{PKG_NAME}/", "", 1)


def registry_unqualified_name(o: str | object | RegistryInfo) -> str:
    r"""Unqualified name of object (i.e. without package prefix).

    Args:
        o (str | object | RegistryInfo): string, registry object, or RegistryInfo to get unqualified name for.

    Returns:
        Unqualified name of object
    """
    if isinstance(o, str):
        name = o
    else:
        info = o if isinstance(o, RegistryInfo) else registry_info(o)
        name = info.name
    parts = name.split("/")
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


def set_registry_params(o: object, params: dict[str, Any]) -> object:
    r"""Set the registry params for an object.

    Args:
        o (object): Object to set the registry params for
        params: (dict[str, Any]): Registry params

    Returns:
        Passed object, with registry params attached
    """
    setattr(o, REGISTRY_PARAMS, params)
    return o


def has_registry_params(o: object) -> bool:
    r"""Check if the object has registry params.

    Args:
        o (object): Object to check.

    Returns:
        True if the object has registry params, else False.
    """
    return is_registry_object(o) and hasattr(o, REGISTRY_PARAMS)


def registry_key(type: RegistryType, name: str) -> str:
    return f"{type}:{name}"


REGISTRY_INFO = "__registry_info__"
REGISTRY_PARAMS = "__registry_params__"
_registry: dict[str, object] = {}


class RegistryDict(TypedDict):
    type: RegistryType
    name: str
    params: dict[str, Any]


def is_registry_dict(o: object) -> TypeGuard[RegistryDict]:
    return isinstance(o, dict) and "type" in o and "name" in o and "params" in o


def registry_value(o: object) -> Any:
    # treat tuple as list
    if isinstance(o, tuple):
        o = list(o)

    # recurse through collection types
    if isinstance(o, list):
        return [registry_value(x) for x in o]
    elif isinstance(o, dict):
        return {k: registry_value(v) for k, v in o.items()}
    elif has_registry_params(o):
        return dict(
            type=registry_info(o).type,
            name=registry_log_name(o),
            params=registry_params(o),
        )
    else:
        return o


def registry_create_from_dict(d: RegistryDict) -> object:
    return registry_create(d["type"], d["name"], **d["params"])
