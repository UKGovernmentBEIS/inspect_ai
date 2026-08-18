"""Demo task for the inline elicitation (``ask_user``) card.

Runs a mockllm-driven react agent that fires ``ask_user`` twice:

1. First call: a single free-text question (the typical
   "what's the value of X?" shape).
2. Second call: a two-field form (the agent now has the first
   answer and wants more context in one round-trip).

…then submits. Exercises both the minimal single-Input card and
the multi-field card layout (label + Input rows stacked) without
needing to set up two separate demo files. The
:class:`_ElicitationCard` renders both shapes from the same
:class:`ElicitationForm` widget — the second call is a useful pin
for the "FieldRow margin between fields" CSS we tightened.

CLI:

    inspect eval examples/inline_cards/question.py
    inspect eval examples/inline_cards/question.py --acp-server
"""

from inspect_ai import Task, task
from inspect_ai.agent._react import react
from inspect_ai.agent._types import AgentSubmit
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import ask_user


def _single_question_schema() -> dict:
    """JSON-Schema dict for a single required free-text answer.

    Mirrors the shape :func:`ask_user` documents under "Simple
    required string" — minimal viable elicitation. ``title`` /
    ``description`` carry the per-field labels; the conversational
    prompt lives on the request's ``message`` field.
    """
    return {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "title": "Your answer",
                "description": "Free-form text.",
                "min_length": 1,
            }
        },
        "required": ["answer"],
    }


def _two_question_schema() -> dict:
    """JSON-Schema dict for two required free-text answers.

    Two ``string`` properties stack vertically as labelled
    :class:`Input` rows in :class:`ElicitationForm`. Both required
    so Submit stays disabled until both are filled — exercises the
    multi-field validation path alongside the single-field one
    above.
    """
    return {
        "type": "object",
        "properties": {
            "environment": {
                "type": "string",
                "title": "Environment",
                "description": "Which environment? (staging / prod / …)",
                "min_length": 1,
            },
            "expiry": {
                "type": "string",
                "title": "Expiry",
                "description": "Approximate expiry date (free-form).",
                "min_length": 1,
            },
        },
        "required": ["environment", "expiry"],
    }


@task
def question_demo() -> Task:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            # First turn: single-question elicitation — the agent
            # asks for the API key.
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="ask_user",
                tool_arguments={
                    "message": "What's the API key for the staging service?",
                    "schema": _single_question_schema(),
                },
            ),
            # Second turn: two-question elicitation — the agent
            # now needs the environment + expiry to file the key.
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="ask_user",
                tool_arguments={
                    "message": "A couple more details before I file the key:",
                    "schema": _two_question_schema(),
                },
            ),
            # Third turn: submit.
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "ok"},
            ),
        ],
    )

    return Task(
        dataset=[
            Sample(
                input=(
                    "Use the ask_user tool to collect the API key, then any "
                    "follow-up details the agent asks for, then submit 'ok'."
                ),
                target=["ok"],
            )
        ],
        solver=react(
            tools=[ask_user()],
            submit=AgentSubmit(
                name="submit",
                description="Submit the final answer once the operator has answered.",
            ),
        ),
        scorer=includes(),
        message_limit=10,
        model=model,
    )
