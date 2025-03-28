import pytest
from test_helpers.tools import addition

from inspect_ai.model import ModelOutput, get_model


@pytest.mark.anyio
async def test_generate_loop():
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "addition", {"x": 1, "y": 2}),
            ModelOutput.for_tool_call("mockllm/model", "addition", {"x": 2, "y": 4}),
            ModelOutput.from_content("mockllm/model", "All done!"),
        ],
    )
    messages, output = await model.generate_loop(
        "Please call the addition function", tools=[addition()]
    )

    assert len(messages) == 5
