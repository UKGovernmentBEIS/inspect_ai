import re

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


@task
def arithmetic_prefill():
    """Task demonstrating prefilling of assistant messages."""
    return Task(
        dataset=[
            Sample(
                input="What is 1+1?",
                target="2",
                metadata={"prefill": "1+1="},
            ),
            Sample(
                input="What is 5+7?",
                target="12",
                metadata={"prefill": "5+7="},
            ),
            Sample(
                input="What is 3*4?",
                target="12",
                metadata={"prefill": "3*4="},
            ),
        ],
        solver=[prefill(), generate()],
        scorer=score_arithmetic(),
    )


@solver
def prefill() -> Solver:
    """Solver that prefills assistant messages to guide the model's response."""

    async def solve(state: TaskState, generate: Generate):
        # Extract the question from the user prompt
        question = state.user_prompt.content

        # Create a new set of messages with a prefilled assistant message
        state.messages = [
            ChatMessageUser(content=question),
            ChatMessageAssistant(
                content=state.metadata["prefill"]
            ),  # prefilled message
        ]

        return state

    return solve


@scorer(metrics=[accuracy()])
def score_arithmetic():
    """Simple scorer that extracts the number from the output and compares it to the target."""

    async def score(state: TaskState, target: Target):
        output = state.output.completion.strip()
        # Since we're using prefill, the output should start with a number
        # Extract the first number from the output
        match = re.match(r"^(\d+)", output)
        if match:
            answer = match.group(1)
            correct = answer == target.text
            return Score(
                value=1.0 if correct else 0.0,
                answer=output,
            )

        return Score(
            value=0.0,
            answer=output,
            explanation="Could not extract a numerical answer",
        )

    return score
