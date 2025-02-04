from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, loop, solver


@solver
def increase_counter():
    """A simple solver that increments a counter stored in the TaskState."""

    async def solve(state: TaskState, _generate: Generate) -> TaskState:
        counter = state.store.get("counter", 0)
        state.store.set("counter", counter + 1)
        return state

    return solve


@solver
def complete_immediately():
    """A solver that increments the counter and then marks the state as complete.

    This should cause loop termination after one iteration.
    """

    async def solve(state: TaskState, _generate: Generate) -> TaskState:
        counter = state.store.get("counter", 0)
        state.store.set("counter", counter + 1)
        state.completed = True
        return state

    return solve


@task
def loop_condition_task():
    """Test that the loop stops once the counter in the state store reaches 3."""

    @solver
    def loop_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # Create a loop solver that runs 'increase_counter'
            state = await loop(
                solver=increase_counter(),
                condition=lambda s: s.store.get("counter", 0) >= 3,
                max_iterations=10,
            )(state, generate)
            # Verify that the counter is exactly 3.
            assert state.store.get("counter", 0) == 3, (
                f"Expected counter to be 3, got {state.store.get('counter', 0)}"
            )
            return state

        return solve

    return Task(
        dataset=[Sample(input="dummy", target="dummy")],
        solver=loop_solver(),
    )


@task
def loop_max_iterations_task():
    """Test that if the stop condition is never met, the loop runs for exactly max_iterations iterations."""

    @solver
    def loop_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state = await loop(
                solver=increase_counter(),
                condition=lambda s: False,  # Never stops early.
                max_iterations=5,
            )(state, generate)
            assert state.store.get("counter", 0) == 5, (
                f"Expected counter to be 5, got {state.store.get('counter', 0)}"
            )
            return state

        return solve

    return Task(
        dataset=[Sample(input="dummy", target="dummy")],
        solver=loop_solver(),
    )


@task
def loop_completion_task():
    """Test that the loop stops immediately when the solver flags state.completed."""

    @solver
    def loop_solver():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state = await loop(
                solver=complete_immediately(),
                condition=lambda s: False,  # Condition not used since .completed wins.
                max_iterations=10,
            )(state, generate)
            # The counter should be 1 because complete_immediately marks the state as completed.
            assert state.store.get("counter", 0) == 1, (
                f"Expected counter to be 1, got {state.store.get('counter', 0)}"
            )
            return state

        return solve

    return Task(
        dataset=[Sample(input="dummy", target="dummy")],
        solver=loop_solver(),
    )


def test_loop_condition():
    eval(loop_condition_task(), model="mockllm/model")


def test_loop_max_iterations():
    eval(loop_max_iterations_task(), model="mockllm/model")


def test_loop_completion():
    eval(loop_completion_task(), model="mockllm/model")
