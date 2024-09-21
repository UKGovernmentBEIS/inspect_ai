from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import (
    Generate,
    TaskState,
    fork,
    solver,
)
from inspect_ai.util import store


def test_forking_solver():
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

            return state

        return solve

    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")], plan=forking_solver()
    )

    eval(task, model="mockllm/model")
