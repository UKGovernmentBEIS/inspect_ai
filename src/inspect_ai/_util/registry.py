from __future__ import annotations

import sys
from inspect import get_annotations, isclass
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Literal,
    overload,
)

from inspect_ai.core import _registry as _core_registry
from inspect_ai.core._registry import _instantiate_registry_object

# isort: split
# Backward-compatible re-exports of names that moved to inspect_ai.core.
from inspect_ai.core._registry import _REGISTRY_TYPE_VALUES as _REGISTRY_TYPE_VALUES
from inspect_ai.core._registry import REGISTRY_INFO as REGISTRY_INFO
from inspect_ai.core._registry import REGISTRY_PARAMS as REGISTRY_PARAMS
from inspect_ai.core._registry import ModelDict as ModelDict
from inspect_ai.core._registry import RegistryDict as RegistryDict
from inspect_ai.core._registry import RegistryInfo as RegistryInfo
from inspect_ai.core._registry import RegistryType as RegistryType
from inspect_ai.core._registry import _registry as _registry
from inspect_ai.core._registry import _registry_get as _registry_get
from inspect_ai.core._registry import create_registry_object as create_registry_object
from inspect_ai.core._registry import extract_named_params as extract_named_params
from inspect_ai.core._registry import has_registry_params as has_registry_params
from inspect_ai.core._registry import is_model_dict as is_model_dict
from inspect_ai.core._registry import is_registry_dict as is_registry_dict
from inspect_ai.core._registry import is_registry_object as is_registry_object
from inspect_ai.core._registry import obj_type as obj_type
from inspect_ai.core._registry import registry_add as registry_add
from inspect_ai.core._registry import registry_arg as registry_arg
from inspect_ai.core._registry import (
    registry_create_from_dict as registry_create_from_dict,
)
from inspect_ai.core._registry import registry_find as registry_find
from inspect_ai.core._registry import registry_has as registry_has
from inspect_ai.core._registry import registry_info as registry_info
from inspect_ai.core._registry import registry_key as registry_key
from inspect_ai.core._registry import registry_kwargs as registry_kwargs
from inspect_ai.core._registry import registry_log_name as registry_log_name
from inspect_ai.core._registry import registry_lookup as registry_lookup
from inspect_ai.core._registry import registry_name as registry_name
from inspect_ai.core._registry import registry_package_name as registry_package_name
from inspect_ai.core._registry import registry_params as registry_params
from inspect_ai.core._registry import registry_tag as registry_tag
from inspect_ai.core._registry import (
    registry_unqualified_name as registry_unqualified_name,
)
from inspect_ai.core._registry import registry_value as registry_value
from inspect_ai.core._registry import registry_version as registry_version
from inspect_ai.core._registry import set_registry_info as set_registry_info
from inspect_ai.core._registry import set_registry_params as set_registry_params

# End of backward-compatible re-exports.

if TYPE_CHECKING:
    from inspect_ai import Task
    from inspect_ai.agent import Agent
    from inspect_ai.approval import Approver
    from inspect_ai.hooks._hooks import Hooks
    from inspect_ai.model import ModelAPI
    from inspect_ai.review import Reviewer
    from inspect_ai.scorer import Metric, Scorer, ScoreReducer
    from inspect_ai.solver import Plan, Solver
    from inspect_ai.tool import Tool
    from inspect_ai.util import SandboxEnvironment


if TYPE_CHECKING:
    _registry_version: int
else:

    def __getattr__(name: str) -> int:
        """Read `_registry_version` from `inspect_ai.core._registry` on each access.

        A re-export would bind the value at import and go stale on the next
        `registry_add()`. Type checkers see the declaration above instead, because
        a module `__getattr__` would make them accept any name imported from here.
        """
        if name == "_registry_version":
            return _core_registry._registry_version
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def set_annotations(wrapper: Callable[..., Any], annotations: dict[str, Any]) -> None:
    """Set `wrapper`'s annotations in both PEP 649 representations.

    On Python 3.14+ a bare `wrapper.__annotations__ = ...` assignment sets the lazy
    `__annotate__` to None, and mutating the dict in place doesn't update
    `__annotate__` at all. Either way, a further `functools.wraps` layer (which
    copies `__annotate__`, not `__annotations__`) then silently drops the
    annotations — e.g. in user decorators that extend @task/@solver/@agent and
    re-register their own wrapper. Setting both representations keeps annotations
    consistent under further wrapping. Always use this instead of assigning
    `__annotations__` directly.
    """
    annotations = dict(annotations)
    wrapper.__annotations__ = annotations
    if sys.version_info >= (3, 14):
        from annotationlib import Format  # type: ignore[import-not-found,unused-ignore]

        def __annotate__(format: Format) -> dict[str, Any]:
            # NotImplementedError is the protocol's "format not supported" signal:
            # PEP 749 requires it for VALUE_WITH_FAKE_GLOBALS (hand-written annotate
            # functions can't run under fake globals), and annotationlib's consumers
            # compute FORWARDREF/STRING themselves by falling back to VALUE. See
            # "Format compatibility" in the annotationlib docs:
            # https://docs.python.org/3.14/library/annotationlib.html
            if format != Format.VALUE:
                raise NotImplementedError(format)
            return dict(annotations)

        wrapper.__annotate__ = __annotate__  # type: ignore[attr-defined,unused-ignore]


def set_return_annotation(wrapper: Callable[..., Any], return_type: type[Any]) -> None:
    """Restore `wrapper`'s return annotation after `functools.wraps` clobbered it.

    Decorators like @task wrap the user's function with `functools.wraps` (so name,
    docstring, and params carry over) but need the wrapper itself to be annotated as
    returning the registry type: `registry_create` consults the return
    annotation to decide whether a registered callable is a factory to invoke.
    """
    set_annotations(wrapper, {**wrapper.__annotations__, "return": return_type})


@overload
def registry_create(type: Literal["agent"], name: str, **kwargs: Any) -> Agent: ...


@overload
def registry_create(
    type: Literal["approver"], name: str, **kwargs: Any
) -> Approver: ...


@overload
def registry_create(
    type: Literal["reviewer"], name: str, **kwargs: Any
) -> "Reviewer": ...


@overload
def registry_create(type: Literal["hooks"], name: str, **kwargs: Any) -> Hooks: ...


@overload
def registry_create(type: Literal["metric"], name: str, **kwargs: Any) -> Metric: ...


@overload
def registry_create(
    type: Literal["modelapi"], name: str, **kwargs: Any
) -> ModelAPI: ...


@overload
def registry_create(type: Literal["plan"], name: str, **kwargs: Any) -> Plan: ...


@overload
def registry_create(
    type: Literal["sandboxenv"], name: str, **kwargs: Any
) -> SandboxEnvironment: ...


@overload
def registry_create(type: Literal["scorer"], name: str, **kwargs: Any) -> Scorer: ...


@overload
def registry_create(
    type: Literal["score_reducer"], name: str, **kwargs: Any
) -> ScoreReducer: ...


@overload
def registry_create(type: Literal["solver"], name: str, **kwargs: Any) -> Solver: ...


@overload
def registry_create(type: Literal["task"], name: str, **kwargs: Any) -> Task: ...


@overload
def registry_create(type: Literal["tool"], name: str, **kwargs: Any) -> Tool: ...


@overload
def registry_create(type: Literal["loader"], name: str, **kwargs: Any) -> Any: ...


@overload
def registry_create(type: Literal["scanner"], name: str, **kwargs: Any) -> Any: ...


@overload
def registry_create(type: Literal["scanjob"], name: str, **kwargs: Any) -> Any: ...


# No "monitor"/"protocol" overloads: they are built with
# create_registry_object(), so registry_create() is a type error.


def registry_create(type: RegistryType, name: str, **kwargs: Any) -> object:  # type: ignore[return]
    r"""Create a registry object.

    Creates objects registered via decorator (e.g. `@task`, `@solver`). Note
    that this can also create registered objects within Python packages, in
    which case the name of the package should be used a prefix, e.g.

    ```python
    registry_create("scorer", "mypackage/myscorer", ...)
    ```

    Object within the Inspect package do not require a prefix, nor do
    objects from imported modules that aren't in a package.

    Args:
        type: Type of registry object to create
        name: Name of registry object to create
        **kwargs: Optional creation arguments

    Returns:
        Instance of specified name and type.

    Raises:
        LookupError: If the named object was not found in the registry.
        TypeError: If the specified parameters are not valid for the object.
    """
    obj = registry_lookup(type, name)

    if isclass(obj):
        return _instantiate_registry_object(obj, kwargs)
    elif callable(obj):
        return_type = get_annotations(obj, eval_str=True).get("return")
        # Until we remove the MetricDeprecated symbol we need this extra
        # bit to map the Metric union back to Metric
        if "_metric.Metric" in str(return_type):
            return_type = "Metric"
        else:
            return_type = getattr(return_type, "__name__", None)
        if return_type and return_type.lower() == type:
            return _instantiate_registry_object(obj, kwargs)
        else:
            return obj
    else:
        raise LookupError(f"{name} was not found in the registry")


def model_create_from_dict(d: ModelDict) -> object:
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._model import get_model

    return get_model(
        d["model"],
        config=GenerateConfig(**d["config"]),
        base_url=d["base_url"],
        **d["model_args"],
    )
