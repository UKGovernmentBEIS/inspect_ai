from __future__ import annotations

import inspect
from inspect import isclass
from typing import (
    Any,
    Callable,
    Literal,
    Protocol,
    TypeGuard,
    cast,
    get_args,
    runtime_checkable,
)

from pydantic import BaseModel, Field
from pydantic_core import to_jsonable_python
from typing_extensions import TypedDict

from ._constants import PKG_NAME
from ._entrypoints import ensure_entry_points
from ._package import get_installed_package_name

obj_type = type

RegistryType = Literal[
    "agent",
    "approver",
    "hooks",
    "reviewer",
    "metric",
    "modelapi",
    "plan",
    "sandboxenv",
    "score_reducer",
    "scorer",
    "solver",
    "task",
    "task_source",
    "tool",
    "loader",
    "scanner",
    "scanjob",
    "validation_predicate",
    "monitor",
    "protocol",
]
"""Enumeration of registry object types.

These are the types of objects in this system that can be
registered using a decorator (e.g. `@task`, `@solver`). The "monitor" and
"protocol" types are constructed via `create_registry_object()` rather than
`registry_create()`; see the note above the `registry_create()` overloads in
`inspect_ai._util.registry`.
Registered objects can in turn be created dynamically using
the `registry_create()` function.
"""

_REGISTRY_TYPE_VALUES: frozenset[str] = frozenset(get_args(RegistryType))


class RegistryInfo(BaseModel):
    """Registry information for registered object (e.g. solver, scorer, etc.)."""

    type: RegistryType
    """Type of registry object."""

    name: str
    """Registered name."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Additional registry metadata."""


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

    # bump version so caches keyed on registry contents (e.g. get_all_hooks)
    # know to invalidate
    global _registry_version
    _registry_version += 1


def registry_tag(
    type: Callable[..., Any],
    o: object,
    info: RegistryInfo,
    /,
    *args: Any,
    **kwargs: Any,
) -> None:
    r"""Tag an object w/ registry info.

    Tag the passed object with RegistryInfo. This function DOES NOT
    add the object to the registry (call registry_add() to both
    tag and add an object to the registry). Call registry_info()
    on a tagged/registered object to retrieve its info

    `type`, `o` and `info` are positional-only so that a creation keyword
    argument sharing one of those names (e.g. a `@solver` that takes a
    `type` **kwarg) lands in `**kwargs` instead of colliding with the
    parameter and raising `TypeError: got multiple values for argument`.

    Args:
        type (T): type of object being tagged
        o (object): Object to be registered (Metric, Solver, etc.)
        info (RegistryInfo): Metadata (name, etc.) for object.
        *args (list[Any]): Creation arguments
        **kwargs (dict[str,Any]): Creation keyword arguments
    """
    # bind arguments to params
    named_params = extract_named_params(type, False, *args, **kwargs)

    # set attribute
    setattr(o, REGISTRY_INFO, info)
    setattr(o, REGISTRY_PARAMS, named_params)


def extract_named_params(
    type: Callable[..., Any], apply_defaults: bool, /, *args: Any, **kwargs: Any
) -> dict[str, Any]:
    # positional-only for the same collision reason documented on
    # registry_tag: a creation keyword argument named `type` must land in
    # **kwargs rather than in these leading parameters.
    named_params: dict[str, Any] = {}

    sig = inspect.signature(type)
    if apply_defaults:
        bound_params = sig.bind_partial(*args, **kwargs)
        bound_params.apply_defaults()
    else:
        bound_params = sig.bind(*args, **kwargs)

    # arguments passed through a **kwargs (VAR_KEYWORD) parameter are collected
    # by inspect under the variadic parameter's own name (e.g. {"kwargs": {...}}).
    # Record them under their original keyword names instead, so that capturing
    # and then replaying a spec is idempotent rather than nesting the kwargs one
    # level deeper on every round-trip (#4374).
    var_keyword = next(
        (
            name
            for name, param in sig.parameters.items()
            if param.kind == inspect.Parameter.VAR_KEYWORD
        ),
        None,
    )

    # limitation: flattening last means a **kwargs key that shares its name with
    # a positional-only parameter (e.g. `def f(x, /, **kw)` called as `f(1, x=2)`)
    # overwrites that parameter's captured value. Such a signature could never
    # replay from a kwargs dict anyway, so we accept the lossy capture.
    for param, value in bound_params.arguments.items():
        if param == var_keyword and isinstance(value, dict):
            for kwarg_name, kwarg_value in value.items():
                named_params[kwarg_name] = registry_value(kwarg_value)
        else:
            named_params[param] = registry_value(value)

    # callables are not serializable so use their names
    for param in named_params.keys():
        if hasattr(named_params[param], "_repr_params_"):
            named_params[param] = named_params[param]._repr_params_()

        if is_registry_object(named_params[param]):
            named_params[param] = registry_info(named_params[param]).name
        elif callable(named_params[param]) and hasattr(named_params[param], "__name__"):
            named_params[param] = getattr(named_params[param], "__name__")
        elif isinstance(named_params[param], dict | list | BaseModel):
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

    return named_params


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
    o = _registry_get(type, name)

    # try to recover
    if o is None:
        # load entry points for this package as required
        if name.find("/") != -1 and name.find(".") == -1:
            package = name.split("/")[0]
            ensure_entry_points(package)

        return _registry_get(type, name)
    else:
        return o


def registry_has(type: RegistryType, name: str) -> bool:
    """Whether `name` is already registered as `type`, without loading entry points.

    Safe to call from a decorator at import time, where `registry_lookup()`
    could trigger entry-point loading mid-import.
    """
    return _registry_get(type, name) is not None


def _registry_get(type: RegistryType, name: str) -> object | None:
    object = _registry.get(registry_key(type, name))
    if object:
        return object
    # unnamespaced objects can also be found in inspect_ai
    elif name.find("/") == -1:
        return _registry.get(registry_key(type, f"{PKG_NAME}/{name}"))
    else:
        return None


def registry_package_name(name: str) -> str | None:
    if name.find("/") != -1 and name.find(".") == -1:
        return name.split("/")[0]
    else:
        return None


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


def create_registry_object(
    type: RegistryType, name: str, args: dict[str, Any]
) -> object:
    """Restore a registry object, passing creation arguments as a dict.

    Serialized registry arguments describe an instance, so registered classes
    and factories are always instantiated. The explicit arguments dictionary
    also avoids collisions with `registry_create()`'s positional parameters
    (e.g. replaying a factory such as `react` that has its own `name` parameter).
    """
    obj = registry_lookup(type, name)

    if isclass(obj) or callable(obj):
        return _instantiate_registry_object(obj, args)
    else:
        raise LookupError(f"{name} was not found in the registry")


def _instantiate_registry_object(
    obj: Callable[..., object], args: dict[str, Any]
) -> object:
    instance = obj(**registry_kwargs(**args))
    info = registry_info(obj)
    # Objects created by self-tagging factories (e.g. @agent / @solver) already
    # carry richer metadata. Preserve it while retaining the factory identity.
    if is_registry_object(instance) and registry_info(instance).metadata:
        info = info.model_copy(update={"metadata": registry_info(instance).metadata})
    return set_registry_info(instance, info)


def registry_info(o: object) -> RegistryInfo:
    r"""Lookup RegistryInfo for an object.

    Args:
        o (object): Object to lookup info for

    Returns:
        RegistryInfo for object.

    Raises:
        ValueError: If the object does not have registry info.
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

# Monotonic counter bumped by `registry_add` on every mutation. Used by
# consumers (e.g. `get_all_hooks`) to cache results derived from the registry
# while invalidating automatically when new entries are added. Module-private
# — read it via `registry_version()` if needed externally.
_registry_version: int = 0


def registry_version() -> int:
    """Current registry version. Bumped on each `registry_add`."""
    return _registry_version


class RegistryDict(TypedDict):
    type: RegistryType
    name: str
    params: dict[str, Any]


def is_registry_dict(o: object) -> TypeGuard[RegistryDict]:
    if not isinstance(o, dict):
        return False
    registry_type = o.get("type")
    if not isinstance(registry_type, str) or registry_type not in _REGISTRY_TYPE_VALUES:
        return False
    if not isinstance(o.get("name"), str):
        return False
    if not isinstance(o.get("params"), dict):
        return False
    return True


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
        return RegistryDict(
            type=registry_info(o).type,
            name=registry_log_name(o),
            params=registry_params(o),
        )
    elif not isclass(o) and isinstance(o, RegistryValue):
        return o._registry_value()
    else:
        return o


def registry_arg(arg: Any) -> Any:
    if isinstance(arg, dict):
        if is_registry_dict(arg):
            return create_registry_object(arg["type"], arg["name"], arg["params"])
        elif is_model_dict(arg):
            if _model_from_dict is None:
                raise RuntimeError("Restoring a model argument requires inspect_ai.")
            return _model_from_dict(arg)
        else:
            return {k: registry_arg(v) for k, v in arg.items()}
    elif isinstance(arg, (list, tuple)):
        return [registry_arg(item) for item in arg]
    else:
        return arg


# resolve embedded registry objects and models
def registry_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Resolve any registry and model dicts in the given kwargs."""
    return {k: registry_arg(v) for k, v in kwargs.items()}


def registry_create_from_dict(d: RegistryDict) -> object:
    return create_registry_object(d["type"], d["name"], d["params"])


class ModelDict(TypedDict):
    model: str
    config: dict[str, Any]
    base_url: str | None
    model_args: dict[str, Any]


def is_model_dict(o: object) -> TypeGuard[ModelDict]:
    return (
        isinstance(o, dict)
        and "model" in o
        and "config" in o
        and "base_url" in o
        and "model_args" in o
    )


@runtime_checkable
class RegistryValue(Protocol):
    """An object that records itself in registry params with `_registry_value()`.

    `registry_value()` records an object that implements this method as the
    method's return value. inspect_ai's `Model` implements it and returns a
    `ModelDict`.
    """

    def _registry_value(self) -> object: ...


def set_model_from_dict(restore: Callable[[ModelDict], object]) -> None:
    """Set the function that `registry_arg()` uses to restore a `ModelDict`.

    `inspect_ai.model` sets it when imported.
    """
    global _model_from_dict
    _model_from_dict = restore


_model_from_dict: Callable[[ModelDict], object] | None = None
