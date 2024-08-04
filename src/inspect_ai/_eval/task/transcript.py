import contextlib
from typing import Iterator

from inspect_ai._util.json import json_changes
from inspect_ai._util.registry import (
    registry_log_name,
)
from inspect_ai.solver import Solver, TaskState, transcript
from inspect_ai.solver._subtask.transcript import StateEvent
from inspect_ai.solver._task_state import set_sample_state, state_jsonable


class SolverTranscript:
    def __init__(self, before_state: TaskState) -> None:
        self.before = state_jsonable(before_state)

    def complete(self, after_state: TaskState) -> None:
        after = state_jsonable(after_state)
        changes = json_changes(self.before, after)
        if changes:
            transcript()._event(StateEvent(changes=changes))


@contextlib.contextmanager
def solver_transcript(solver: Solver, state: TaskState) -> Iterator[SolverTranscript]:
    set_sample_state(state)
    with transcript().step(name=registry_log_name(solver), type="solver"):
        yield SolverTranscript(state)
