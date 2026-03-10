from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import Generate, Solver, TaskState, solver


@solver
def fixed_turn_loop(turns: int = 40) -> Solver:
    """Force a fixed number of model generations in one sample."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # First generation responds to the initial sample input.
        state = await generate(state, tool_calls="none")

        # Then keep appending a new user turn and generating again.
        for turn in range(2, turns + 1):
            state.messages.append(
                ChatMessageUser(
                    content=(
                        f"Turn {turn}/{turns}. "
                        f"Reply with exactly ACK-{turn} and nothing else."
                    )
                )
            )
            state = await generate(state, tool_calls="none")

            # Stop if a hard message/token/time limit ended the sample.
            if state.completed:
                break

        return state

    return solve


@task
def streaming_turn_stress(turns: int = 40) -> Task:
    return Task(
        dataset=[
            Sample(
                input=(
                    "Turn 1/{}: Reply with exactly ACK-1 and nothing else. "
                    "You will receive many follow-up turns."
                ).format(turns)
            )
        ],
        solver=fixed_turn_loop(turns=turns),
        # Keep this comfortably above the expected conversation length.
        message_limit=max(400, turns * 6),
    )
