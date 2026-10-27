import re
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar, cast, overload

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import (
    RegistryInfo,
    create_registry_object,
    is_registry_object,
    registry_add,
    registry_info,
    registry_log_name,
    registry_lookup,
    registry_name,
    registry_params,
    registry_tag,
    set_registry_info,
)

from .._metric import value_to_float, value_to_float_params
from .types import ScoreReducer, ScoreReducers

ScoreReducerType = TypeVar("ScoreReducerType", bound=Callable[..., ScoreReducer])


@overload
def score_reducer(func: ScoreReducerType) -> ScoreReducerType: ...


@overload
def score_reducer() -> Callable[[ScoreReducerType], ScoreReducerType]: ...


@overload
def score_reducer(*, name: str) -> Callable[[ScoreReducerType], ScoreReducerType]: ...


def score_reducer(
    func: ScoreReducerType | None = None, *, name: str | None = None
) -> Callable[[ScoreReducerType], ScoreReducerType] | ScoreReducerType:
    """Decorator for registering Score Reducers.

    Args:
        func: Function returning `ScoreReducer` targeted by
            plain task decorator without attributes (e.g. `@score_reducer`)
        name: Optional name for reducer. If the decorator has no name
            argument then the name of the function will be used to automatically assign a name.

    Returns:
        ScoreReducer with registry attributes or a decorator function.
    """

    def create_reducer_wrapper(reducer_type: ScoreReducerType) -> ScoreReducerType:
        # get the name and params
        nonlocal name
        reducer_name = name or registry_name(
            reducer_type, getattr(reducer_type, "__name__")
        )

        # create and return the wrapper
        def wrapper(*w_args: Any, **w_kwargs: Any) -> ScoreReducer:
            # create the task
            score_reducer = reducer_type(*w_args, **w_kwargs)
            # tag it (callable arguments are recorded in a form that
            # create_reducers_from_specs can rebuild or reject explicitly;
            # the original calling convention is preserved so positional
            # and variadic factories tag exactly as before)
            registry_tag(
                reducer_type,
                score_reducer,
                RegistryInfo(
                    type="score_reducer",
                    name=reducer_name,
                ),
                *[_taggable_value(arg) for arg in w_args],
                **{k: _taggable_value(v) for k, v in w_kwargs.items()},
            )
            # return it
            return score_reducer

        return reducer_register(
            score_reducer=cast(ScoreReducerType, wrapper), name=reducer_name
        )

    if func is not None:
        return create_reducer_wrapper(func)
    else:
        return create_reducer_wrapper


def _taggable_value(value: Any) -> Any:
    """A creation argument in a form `registry_tag` records faithfully.

    A callable that cannot describe how to rebuild itself is replaced
    with an unsupported-callable marker under a reserved key, so
    reconstruction from recorded specs fails explicitly instead of
    replaying the callable's name as a string argument. Converters
    created by `value_to_float()` are replaced with their constructor
    arguments under a reserved key. Callables with `_repr_params_` and
    registry objects are passed through for `registry_tag` to record.
    Containers are recursed into so nested callables are handled the
    same way.
    """
    if is_registry_object(value) or hasattr(value, "_repr_params_"):
        return value
    if callable(value):
        converter_params = value_to_float_params(value)
        if converter_params is not None:
            return {"__value_to_float__": converter_params}
        return {
            "__unsupported_callable__": getattr(value, "__name__", None)
            or getattr(type(value), "__name__", "<unknown>")
        }
    if isinstance(value, dict):
        return {k: _taggable_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_taggable_value(v) for v in value]
    return value


def reducer_register(score_reducer: ScoreReducerType, name: str) -> ScoreReducerType:
    r"""Register a task.

    Args:
        score_reducer (ReducerType):
            function that returns a Task or class
            deriving from Task
        name (str): Name of task

    Returns:
        ScoreReducer with registry attributes.
    """
    registry_add(
        score_reducer,
        RegistryInfo(type="score_reducer", name=name),
    )
    return score_reducer


def reducer_log_names(
    reducer: ScoreReducer | list[ScoreReducer] | None,
) -> list[str] | None:
    reducer = [reducer] if isinstance(reducer, ScoreReducer) else reducer
    if reducer is not None:
        names = [reducer_log_name(r) for r in reducer]
        return names
    else:
        return None


def reducer_log_name(reducer: ScoreReducer) -> str:
    name = registry_log_name(reducer)
    params = registry_params(reducer)
    if "k" in params:
        suffix = f"_{params.get('k')}"
        if not name.endswith(suffix):
            name = f"{name}{suffix}"
    return name


@dataclass(frozen=True)
class ReducerSpec:
    """Score reducer specification used to (re-)create reducers."""

    name: str
    """Reducer name"""

    args: dict[str, Any] = field(default_factory=dict)
    """Reducer arguments."""


def reducer_specs(
    reducer: ScoreReducer | list[ScoreReducer] | None,
) -> list[ReducerSpec] | None:
    # Arguments are recorded in the eval log, so only JSON-serializable
    # values round-trip. Callable arguments are recorded as their
    # constructor arguments when they support it (e.g. `value_to_float()`)
    # and as an unsupported-callable marker otherwise; see
    # create_reducers_from_specs for how each form is handled on rebuild.
    reducer = [reducer] if isinstance(reducer, ScoreReducer) else reducer
    if reducer is not None:
        return [
            ReducerSpec(name=registry_log_name(r), args=registry_params(r))
            for r in reducer
        ]
    else:
        return None


def create_reducers_from_specs(specs: list[ReducerSpec]) -> list[ScoreReducer]:
    return [
        cast(
            ScoreReducer,
            create_registry_object("score_reducer", spec.name, _rebuild_args(spec)),
        )
        for spec in specs
    ]


def _rebuild_args(spec: ReducerSpec) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for arg_name, value in spec.args.items():
        if arg_name == "value_to_float" and isinstance(value, str):
            # Logs written before callable arguments were recorded hold
            # only the callable's name; there is nothing faithful to
            # rebuild, so fail explicitly rather than pass the string
            # through as the converter.
            raise PrerequisiteError(
                f"Cannot rebuild reducer '{spec.name}' from the eval log: "
                "argument 'value_to_float' was recorded as a name only "
                "by an earlier version and cannot be reconstructed. "
                "Re-run the eval or score with a reducer whose arguments "
                "are serializable."
            )
        args[arg_name] = _rebuild_value(spec.name, arg_name, value)
    return args


def _rebuild_value(spec_name: str, arg_name: str, value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__value_to_float__"}:
            record = value["__value_to_float__"]
            # Only the recorded keys are passed, so a partial record
            # falls back to the value_to_float() defaults for the rest.
            converter_args = {
                key: record[key]
                for key in ("correct", "incorrect", "partial", "noanswer")
                if isinstance(record, dict) and key in record
            }
            return value_to_float(**converter_args)
        if set(value) == {"__unsupported_callable__"}:
            raise PrerequisiteError(
                f"Cannot rebuild reducer '{spec_name}' from the eval log: "
                f"argument '{arg_name}' was a callable "
                f"('{value['__unsupported_callable__']}') that cannot be "
                "recorded in a log. Re-run the eval or score with a "
                "reducer whose arguments are serializable."
            )
        return {k: _rebuild_value(spec_name, arg_name, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rebuild_value(spec_name, arg_name, v) for v in value]
    return value


@overload
def create_reducers(reducers: ScoreReducers) -> list[ScoreReducer]: ...


@overload
def create_reducers(reducers: None) -> None: ...


def create_reducers(reducers: ScoreReducers | None) -> list[ScoreReducer] | None:
    if reducers is None:
        return None

    def create_reducer(name: str) -> ScoreReducer:
        # special case to get digit parameters
        params: dict[str, Any] = {}
        # only apply the `<name>_<k>` shorthand when the literal name is
        # not itself a registered reducer (so e.g. a custom reducer named
        # "top_5" is not rewritten to a lookup of "top" with k=5)
        if registry_lookup("score_reducer", name) is None:
            match = re.match(r"^(.*?)_(\d+)$", name)
            if match:
                name = match.group(1)
                params["k"] = int(match.group(2))

        return cast(
            ScoreReducer,
            create_registry_object("score_reducer", name, params),
        )

    if isinstance(reducers, ScoreReducer):
        return [reducers]
    elif isinstance(reducers, str):
        return [create_reducer(reducers)]
    else:
        return [
            r if isinstance(r, ScoreReducer) else create_reducer(r) for r in reducers
        ]


def set_reducer_name(reducer: ScoreReducer, name: str) -> None:
    info = registry_info(reducer)
    set_registry_info(
        reducer,
        RegistryInfo(
            type="score_reducer",
            name=name,
            metadata=info.metadata,
        ),
    )


def validate_reducer(epochs: int, reducer: ScoreReducer) -> None:
    params = registry_params(reducer)
    if "k" in params:
        k = int(params["k"])
        if k > epochs:
            name = registry_log_name(reducer)
            # don't interfere w/ unknown uses of 'k' (i.e. only validate built in)
            if (
                name.startswith("pass_at")
                or name.startswith("pass_k")
                or name.startswith("at_least")
            ):
                raise PrerequisiteError(
                    f"Reducer '{reducer_log_name(reducer)}' requires {k} epochs however evaluation has only {epochs} epochs."
                )
