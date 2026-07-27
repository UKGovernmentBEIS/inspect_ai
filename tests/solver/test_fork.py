from copy import deepcopy

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.log._samples import sample_active
from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import (
    Generate,
    TaskState,
    fork,
    solver,
)
from inspect_ai.solver._chain import chain
from inspect_ai.solver._task_state import sample_state
from inspect_ai.util import store


def test_forking_solver():
    log = eval(forking_solver_task(), model="mockllm/model")[0]
    assert log.status == "success"


@task
def forking_solver_task():
    COOKIE = "cookie"
    MONSTER = "monster"

    @solver
    def forked_solver(cookie: str):
        async def solve(state: TaskState, generate: Generate):
            store().set(COOKIE, cookie)
            state.store.set(MONSTER, cookie)
            state.metadata[COOKIE] = cookie

            return await generate(state)

        return solve

    def check_state(state: TaskState, cookie: str):
        assert state.store.get(COOKIE) == cookie
        assert state.store.get(MONSTER) == cookie
        assert state.metadata[COOKIE] == cookie

    @solver
    def forking_solver():
        async def solve(state: TaskState, _generate: Generate):
            results = await fork(state, [forked_solver("foo"), forked_solver("bar")])
            check_state(results[0], "foo")
            check_state(results[1], "bar")

            state = await fork(state, forked_solver("foo"))
            check_state(state, "foo")

            state = await fork(
                state,
                chain(forked_solver("a"), forked_solver("b"), forked_solver("c")),
            )
            check_state(state, "c")

            return state

        return solve

    return Task(
        dataset=[Sample(input="Say Hello", target="Hello")], solver=forking_solver()
    )


def test_fork_does_not_capture_live_state():
    """Real fork() branches must not move the shared `ActiveSample.live_state`.

    Unlike the simulation in `test_chain.py` (deepcopy + task spawn), this
    pins the actual `fork()`/`subtask` mechanics: the branch's copied context
    still reaches the shared `ActiveSample`, so only the CAS guard in
    `set_active_sample_state` keeps a branch `Chain` from serving its branch
    conversation as the sample's main thread.
    """
    log = eval(fork_live_state_task(), model="mockllm/model")[0]
    assert log.status == "success"


@task
def fork_live_state_task():
    @solver
    def state_replacer():
        """Return a *new* TaskState (the deepcopy pattern the CAS guards)."""

        async def solve(state: TaskState, _generate: Generate):
            return deepcopy(state)

        return solve

    @solver
    def marker(text: str):
        async def solve(state: TaskState, _generate: Generate):
            state.messages.append(ChatMessageUser(content=text))
            return state

        return solve

    @solver
    def forking_solver():
        async def solve(state: TaskState, _generate: Generate):
            active = sample_active()
            assert active is not None
            # the runner registered this sample's state as the live view
            assert active.live_state is state
            assert sample_state() is state

            # bare-solver branch
            result = await fork(state, marker("branch-a"))
            assert result is not state
            assert active.live_state is state
            assert sample_state() is state

            # Chain branch that replaces the state mid-branch: exercises the
            # CAS-guarded step refresh inside the fork subtask (a capture
            # would persist in live_state until pre-scoring, so these
            # post-fork asserts do detect it)
            result = await fork(state, chain(state_replacer(), marker("branch-b")))
            assert result is not state
            assert any(m.text == "branch-b" for m in result.messages)
            assert active.live_state is state
            assert sample_state() is state
            # no branch conversation leaked into the main thread
            assert not any(m.text in ("branch-a", "branch-b") for m in state.messages)

            return state

        return solve

    return Task(
        dataset=[Sample(input="Say Hello", target="Hello")], solver=forking_solver()
    )
