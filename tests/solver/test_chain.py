from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import (
    Generate,
    Plan,
    Solver,
    TaskState,
    chain,
    solver,
)
from inspect_ai.solver._task_state import sample_state, set_sample_state


@solver
def identity():
    async def solve(state: TaskState, _generate: Generate):
        return state

    return solve


def test_solver_chain():
    solver1 = identity()
    chain1 = chain(identity(), identity(), identity())
    assert len(chain(solver1, chain1)) == 4

    chain2 = chain(solver1, chain1, chain(identity(), identity()))
    assert len(chain2) == 6

    assert len(chain(chain2, deepcopy(chain2))) == 12


@solver
def replacer():
    """A solver that returns a *new* TaskState (the fork()/deepcopy pattern)."""

    async def solve(state: TaskState, _generate: Generate):
        return deepcopy(state)

    return solve


@solver
def appender():
    async def solve(state: TaskState, _generate: Generate):
        state.messages.append(ChatMessageUser(content="appended"))
        return state

    return solve


async def _run_with_active_sample(
    composed: Solver, monkeypatch: pytest.MonkeyPatch
) -> tuple[TaskState, TaskState, SimpleNamespace]:
    """Run `composed` with a fake ActiveSample tracking `live_state`."""
    import inspect_ai.log._samples as samples_mod

    state = simple_task_state()
    set_sample_state(state)
    active = SimpleNamespace(live_state=state)
    monkeypatch.setattr(samples_mod, "sample_active", lambda: active)
    result = await composed(state, cast(Generate, None))
    return state, result, active


async def test_chain_refreshes_sample_state_on_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A step returning a new TaskState must not strand sample_state()/live_state."""
    state, result, active = await _run_with_active_sample(
        chain(replacer(), appender()), monkeypatch
    )
    assert result is not state
    assert sample_state() is result
    assert active.live_state is result
    assert any(m.text == "appended" for m in active.live_state.messages)


async def test_plan_refreshes_sample_state_on_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, result, active = await _run_with_active_sample(
        Plan([replacer(), appender()], internal=True), monkeypatch
    )
    assert result is not state
    assert sample_state() is result
    assert active.live_state is result
    assert any(m.text == "appended" for m in active.live_state.messages)


@pytest.mark.parametrize(
    "make_branch",
    [
        lambda: chain(replacer(), appender()),
        lambda: Plan([replacer(), appender()], internal=True),
    ],
    ids=["chain", "plan"],
)
async def test_fork_branch_does_not_capture_live_state(
    monkeypatch: pytest.MonkeyPatch, make_branch
) -> None:
    """A Chain/Plan threading a fork branch's deepcopy lineage must not move the shared live_state handle."""
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._util._async import tg_collect

    state = simple_task_state()
    set_sample_state(state)
    active = SimpleNamespace(live_state=state)
    monkeypatch.setattr(samples_mod, "sample_active", lambda: active)

    # what fork()'s subtask does: run the branch on a deepcopy in its own
    # task, whose copied context still reaches the shared ActiveSample
    branch_state = deepcopy(state)
    branch = make_branch()
    (branch_result,) = await tg_collect(
        [lambda: branch(branch_state, cast(Generate, None))]
    )
    assert branch_result is not state
    # the ContextVar is context-isolated; the shared handle must hold too
    assert sample_state() is state
    assert active.live_state is state
