from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.scorer import Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver


@task
def arithmetic_prefill():
    """Task demonstrating prefilling of assistant messages."""
    return Task(
        dataset=[
            Sample(
                input="What is 1+1?",
                target="2",
            ),
            Sample(
                input="What is 5+7?",
                target="12",
            ),
            Sample(
                input="What is 3*4?",
                target="12",
            ),
        ],
        solver=prefill_solver(),
        scorer=score_arithmetic(),
    )


@solver
def prefill_solver() -> Solver:
    """Solver that prefills assistant messages to guide the model's response."""

    async def solve(state: TaskState, generate: Generate):
        # Extract the question from the user prompt
        question = state.user_prompt.content

        # Create a new set of messages with a prefilled assistant message
        state.messages = [
            ChatMessageUser(content=question),
            ChatMessageAssistant(content="The answer is: "),  # prefilled message
        ]

        # Generate the completion from the prefilled message
        state = await generate(state)
        return state

    return solve


@scorer(metrics=[accuracy()])
def score_arithmetic():
    """Simple scorer that extracts the number from the output and compares it to the target."""

    async def score(state: TaskState, target: Target):
        output = state.output.completion

        # Extract the answer (assuming it follows "The answer is: ")
        if "The answer is: " in output:
            answer_part = output.split("The answer is: ")[1].strip()
            # Extract just the first number from the answer
            import re

            numbers = re.findall(r"\d+", answer_part)
            if numbers:
                answer = numbers[0]
                correct = answer == target.text
                return Score(
                    value=1.0 if correct else 0.0,
                    answer=answer,
                )

        # Fallback if we can't parse properly
        return Score(
            value=0.0,
            answer=output,
            explanation="Could not extract a numerical answer",
        )

    return score
