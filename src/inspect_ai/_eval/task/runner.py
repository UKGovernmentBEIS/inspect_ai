import contextlib
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from inspect_ai._util.timeouts import timeout
from inspect_ai.model import ChatMessage, Content, ModelOutput
from inspect_ai.scorer import Score
from inspect_ai.solver import Generate, Solver, TaskState, solver

RUNNER_SCORES = "inspect_ai:runner_scores"


@runtime_checkable
class Runner(Protocol):
    """Run a sample, producing either output or scores.

    Runners operate at a lower level than solvers, and can
    be used with either standard scorers (by returning output)
    or optionally also bypass scorers by returning a dictionary
    of scores.

    Args:
       input (str | list[ChatMessage]): The input to be evaluated.
       metadata (dict[str,Any]): Metadata associated with the sample.

    Returns:
       Either output (to be scored) or a dictionary of scores
       if the runner does its own scoring.
    """

    async def __call__(
        self, input: str | list[ChatMessage], metadata: dict[str, Any]
    ) -> str | list[Content] | dict[str, Score]: ...


@contextlib.asynccontextmanager
async def runner_limits() -> AsyncIterator[None]:
    """Async context manager for applying standard limits to task runners.

    Exceptions are thrown when limits are exceeded. The following exceptions should be handled within `runner_limits()`:

      - TimeoutError: Occurs if the `time_limit` is exceeded.

    In the near future support for handling token limits will also be added.

    Note that you only need to use this context manager in cases where
    your runner yields scores (as opposed to output). This is required
    because
    """
    # use timeout if provided
    time_limit: int | None = 60
    timeout_cm = (
        timeout(time_limit) if time_limit is not None else contextlib.nullcontext()
    )

    async with timeout_cm:
        yield


@solver
def runner_solver(runner: Runner) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # run it
        result = await runner(state.input, state.metadata)

        # if scores are returned then set them so we can collect
        # them from the main loop
        if isinstance(result, dict):
            state.store.set(RUNNER_SCORES, result)

        # otherwise just set output to whatever was returned
        else:
            state.output = ModelOutput.from_content(str(state.model), result)

        return state

    return solve
