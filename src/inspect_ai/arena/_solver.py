from typing import Literal

from inspect_ai.model import Model, get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import collect

from ._state import ArenaState


@solver
def arena_solver(
    contestants: list[str | Model],
    parallel: bool = True,
    on_contestant_error: Literal["skip", "raise"] = "skip",
) -> Solver:
    """Fan out to multiple contestants on the same input.

    Each contestant generates a response from `state.input`. Responses are
    written into `ArenaState` for downstream consumption by `pairwise_scorer`.

    Args:
        contestants: List of model specs (strings like `"openai/gpt-4o"`) or
            pre-resolved `Model` instances. Contestant identity in the
            resulting `ArenaState` is the canonical name (`str(model)`).
        parallel: If `True` (default), all contestants generate concurrently
            via `collect()`. Set `False` for deterministic sequential runs.
        on_contestant_error: `"skip"` (default) records the failure in
            `ArenaState.failed` and continues with remaining contestants.
            `"raise"` propagates the first exception, failing the sample.
    """
    resolved: list[Model] = [
        c if isinstance(c, Model) else get_model(c) for c in contestants
    ]
    names = [str(m) for m in resolved]

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        arena = state.store_as(ArenaState)

        async def call(name: str, model: Model) -> tuple[str, str | None]:
            try:
                output = await model.generate(state.input)
                return name, output.completion
            except Exception:
                if on_contestant_error == "raise":
                    raise
                return name, None

        if parallel:
            results = await collect(
                *(call(name, model) for name, model in zip(names, resolved))
            )
        else:
            results = [await call(name, model) for name, model in zip(names, resolved)]

        for name, completion in results:
            if completion is None:
                arena.failed.append(name)
            else:
                arena.responses[name] = completion

        return state

    return solve
