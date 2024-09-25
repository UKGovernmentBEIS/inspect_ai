import contextlib
from typing import Iterator

from inspect_ai._util.json import json_changes
from inspect_ai._util.registry import registry_log_name

from ._solver import Solver
from ._task_state import TaskState, state_jsonable


class SolverTranscript:
    def __init__(self, name: str, before_state: TaskState) -> None:
        self.name = name
        self.before = state_jsonable(before_state)

    def complete(self, after_state: TaskState) -> None:
        from inspect_ai.log._transcript import StateEvent, transcript

        after = state_jsonable(after_state)
        changes = json_changes(self.before, after)
        if changes:
            transcript()._event(StateEvent(changes=changes))


@contextlib.contextmanager
def solver_transcript(
    solver: Solver, state: TaskState, name: str | None = None
) -> Iterator[SolverTranscript]:
    from inspect_ai.log._transcript import transcript

    name = registry_log_name(name or solver)
    with transcript().step(name=name, type="solver"):
        yield SolverTranscript(name, state)
