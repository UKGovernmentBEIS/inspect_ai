"""Mock-model react integration test for the `ask_user` tool.

Proves the end-to-end contract: the model emits an `ask_user` tool call,
`request_input` dispatches to the built-in handler chain, and the answer
flows back to the model so it can submit a final result.
"""

import json

import pytest
from acp.schema import (
    ElicitationSchema,
    ElicitationStringPropertySchema,
)

from inspect_ai import Task, eval
from inspect_ai.agent._react import react
from inspect_ai.agent._types import AgentPrompt, AgentSubmit
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import includes
from inspect_ai.tool import ask_user
from inspect_ai.util import InputRequest, InputResult
from inspect_ai.util._input import builtin as builtin_module


def test_react_ask_user_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_question: dict[str, object] = {}

    async def stub_dispatch(request: InputRequest) -> InputResult:
        captured_question["message"] = request.message
        captured_question["schema"] = request.schema
        return InputResult(outcome="accepted", content={"answer": "42"})

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", stub_dispatch)

    task = Task(
        dataset=[Sample(input="Ask the user for the answer.", target=["42"])],
        solver=react(
            prompt=AgentPrompt(),
            tools=[ask_user()],
            submit=AgentSubmit(name="submit", description="Submit the answer."),
        ),
        scorer=includes(),
        message_limit=10,
    )

    # First turn: model emits ask_user with a small schema.
    # Second turn: model submits the answer it received.
    schema_dict = ElicitationSchema(
        properties={
            "answer": ElicitationStringPropertySchema(type="string", title="Answer")
        },
        required=["answer"],
    ).model_dump(mode="json")

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="ask_user",
                tool_arguments={
                    "message": "What is the answer?",
                    "schema": schema_dict,
                },
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "42"},
            ),
        ],
    )

    log = eval(task, model=model)[0]

    assert log.status == "success", f"unexpected status: {log.status}"
    assert captured_question["message"] == "What is the answer?"
    # The dispatch stub received an actual ElicitationSchema (framework validated it).
    assert isinstance(captured_question["schema"], ElicitationSchema)

    # The ask_user tool returned JSON content; the model's next turn used it
    # to submit "42", which `includes()` scored against the target "42".
    assert log.samples is not None and len(log.samples) == 1
    sample = log.samples[0]

    # Find the ChatMessageTool result for ask_user and verify it's the answer.
    ask_user_result = next(
        (
            m.content
            for m in sample.messages
            if getattr(m, "function", None) == "ask_user"
        ),
        None,
    )
    assert ask_user_result is not None, "ask_user tool result not found in transcript"
    # Tool result content can be a string or a list of content parts.
    if isinstance(ask_user_result, list):
        result_text = "".join(getattr(part, "text", "") for part in ask_user_result)
    else:
        result_text = ask_user_result
    assert json.loads(result_text) == {"answer": "42"}
