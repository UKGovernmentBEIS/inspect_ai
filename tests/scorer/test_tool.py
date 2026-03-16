import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.scorer import CORRECT, Target, match, require_tool
from inspect_ai.tool import ToolCall


@pytest.mark.anyio
async def test_require_tool_happy_path():
    """Tests the normal case: the tool is correctly used in the last message."""
    base_scorer = match()
    scorer = require_tool(base_scorer, tool_name="submit", fail_value="I")

    # The agent correctly uses the tool in its last message
    msg = ChatMessageAssistant(
        content="I have the answer.",
        tool_calls=[
            ToolCall(id="call_1", function="submit", arguments={"answer": "42"})
        ],
    )

    state = simple_task_state(messages=[msg], model_output="42")

    result = await scorer(state, Target(["42"]))
    # The base_scorer (match) should take over and return CORRECT
    assert result.text == CORRECT


@pytest.mark.anyio
async def test_require_tool_aborted_run_error_flag():
    """Explicitly tests that `state.output.error` causes an immediate fail (I)."""
    base_scorer = match()
    scorer = require_tool(base_scorer, tool_name="submit", fail_value="I")

    # 1. Pretend the model used the tool correctly
    msg = ChatMessageAssistant(
        content="I am submitting the answer now.",
        tool_calls=[
            ToolCall(id="call_1", function="submit", arguments={"answer": "42"})
        ],
    )

    state = simple_task_state(messages=[msg], model_output="42")

    # 2. BUT: we set a hard framework error (e.g. timeout while executing)
    state.output.error = "execution_timeout"

    result = await scorer(state, Target(["42"]))

    # 3. Now it MUST return "I" — solely because of the error,
    # even though the tool call was actually present.
    assert result.value == "I"


@pytest.mark.anyio
async def test_require_tool_missing_tool():
    """Tests the case where the agent finishes normally but forgets the tool."""
    base_scorer = match()
    scorer = require_tool(base_scorer, tool_name="submit", fail_value="I")

    msg = ChatMessageAssistant(content="The final answer is 42.")

    state = simple_task_state(messages=[msg], model_output="The final answer is 42.")

    result = await scorer(state, Target(["42"]))
    assert result.value == "I"


@pytest.mark.anyio
async def test_require_tool_zombie_submit():
    """Tests your discovery: the tool was used earlier, but not at the end."""
    base_scorer = match()
    scorer = require_tool(base_scorer, tool_name="submit", fail_value="I")

    # Turn 1: model guesses wrong and uses the tool
    msg1 = ChatMessageAssistant(
        content="Submitting 99.",
        tool_calls=[
            ToolCall(id="call_1", function="submit", arguments={"answer": "99"})
        ],
    )
    # Turn 2: system says "Incorrect"
    msg2 = ChatMessageUser(content="Incorrect. Try again.")
    # Turn 3: model thinks out loud and happens to hit the right number (without the tool!)
    msg3 = ChatMessageAssistant(content="Damn. Maybe it is 42 then?")

    state = simple_task_state(
        messages=[msg1, msg2, msg3],
        model_output="Damn. Maybe it is 42 then?",
    )

    result = await scorer(state, Target(["42"]))

    # Since msg3 (the last action) contains no tool call, it must fail!
    assert result.value == "I"
