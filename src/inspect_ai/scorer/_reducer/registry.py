import re
from typing import Any, Callable, TypeVar, cast, overload

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_create,
    registry_info,
    registry_log_name,
    registry_name,
    registry_params,
    registry_tag,
    set_registry_info,
)

from .types import ScoreReducer, ScoreReducers

REDUCER_NAME = "__REDUCER_NAME__"


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
        func (ScoreReducerType | None): Function returning `ScoreReducer` targeted by
            plain task decorator without attributes (e.g. `@score_reducer`)
        name (str | None): Optional name for reducer. If the decorator has no name
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
            # If a name has been explicitly set, use that
            reducer_nm = getattr(score_reducer, REDUCER_NAME, reducer_name)
            # tag it
            registry_tag(
                reducer_type,
                score_reducer,
                RegistryInfo(
                    type="score_reducer",
                    name=reducer_nm,
                ),
                *w_args,
                **w_kwargs,
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
        name = f"{name}_{params.get('k')}"
    return name


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
        match = re.match(r"^(.*?)_(\d+)$", name)
        if match:
            name = match.group(1)
            params["k"] = int(match.group(2))

        return cast(
            Callable[..., ScoreReducer], registry_create("score_reducer", name)
        )(**params)

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
            if name.startswith("pass_at") or name.startswith("at_least"):
                raise PrerequisiteError(
                    f"Reducer '{name}_{k}' requires {k} epochs however evaluation has only {epochs} epochs."
                )
