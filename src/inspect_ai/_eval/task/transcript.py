import contextlib
from typing import Any, Iterator, cast

from pydantic_core import to_jsonable_python

from inspect_ai._util.json import json_changes
from inspect_ai._util.registry import (
    registry_log_name,
)
from inspect_ai.solver import Solver, StateEvent, TaskState, transcript
from inspect_ai.solver._subtask.store import store_jsonable
from inspect_ai.tool._tool_def import tools_info


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
    with transcript().step(name=registry_log_name(solver), type="solver"):
        yield SolverTranscript(state)


def state_jsonable(state: TaskState) -> dict[str, Any]:
    def as_jsonable(value: Any) -> Any:
        return to_jsonable_python(value, exclude_none=True, fallback=lambda _x: None)

    state_data = dict(
        messages=as_jsonable(state.messages),
        tools=tools_info(state.tools),
        tool_choice=state.tool_choice,
        store=store_jsonable(state.store),
        output=state.output,
        completed=state.completed,
    )
    jsononable = as_jsonable(state_data)
    return cast(dict[str, Any], jsononable)
