from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import (
    Generate,
    TaskState,
    fork,
    solver,
)
from inspect_ai.solver._chain import chain
from inspect_ai.util import store


def test_forking_solver():
    eval(forking_solver_task(), model="mockllm/model")


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
