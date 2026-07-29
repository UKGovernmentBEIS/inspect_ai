"""Tool approval for bridged agents (see `agent/_bridge/approval.py`).

A bridged scaffold runs its own tool calls, so the only thing approval can act
on is the model reply before the scaffold sees it. These tests pin what the
scaffold is left holding for each decision, which is the whole safety property:
a rejected call must not survive in the reply.
"""

from typing import cast

import pytest
from anthropic.types import Message

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    bridge_generate,
    default_code_execution_providers,
    internal_web_search_providers,
)
from inspect_ai.approval import (
    Approval,
    ApprovalDecision,
    ApprovalPolicy,
    Approver,
    approval,
    approver,
    auto_approver,
)
from inspect_ai.event import ApprovalEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

MODEL = "mockllm/model"


def tool_call_output(*calls: ToolCall, content: str = "running tools") -> ModelOutput:
    return ModelOutput(
        model=MODEL,
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=content,
                    model=MODEL,
                    source="generate",
                    tool_calls=list(calls),
                ),
                stop_reason="tool_calls",
            )
        ],
    )


def bash_call(cmd: str = "ls", id: str = "1") -> ToolCall:
    return ToolCall(id=id, function="bash", arguments={"cmd": cmd})


async def generate_through_bridge(
    output: ModelOutput, policies: list[ApprovalPolicy] | None
) -> ModelOutput:
    """Run `output` through `bridge_generate` under `policies`."""
    init_transcript(Transcript())
    model = get_model(MODEL, custom_outputs=[output])
    bridge = AgentBridge(AgentState(messages=[]))

    async def run() -> ModelOutput:
        result, _ = await bridge_generate(
            bridge,
            model,
            [ChatMessageUser(content="do a thing")],
            [],
            None,
            GenerateConfig(),
        )
        return result

    if policies is None:
        return await run()
    with approval(policies):
        return await run()


def auto_policy(decision: ApprovalDecision, tools: str = "*") -> list[ApprovalPolicy]:
    return [ApprovalPolicy(approver=auto_approver(decision), tools=tools)]


async def test_no_policy_leaves_tool_calls_alone() -> None:
    """Control: with no approval policy the reply is untouched."""
    output = await generate_through_bridge(tool_call_output(bash_call()), None)

    assert [call.function for call in output.message.tool_calls or []] == ["bash"]
    assert output.stop_reason == "tool_calls"


async def test_approve_leaves_tool_calls_alone() -> None:
    output = await generate_through_bridge(
        tool_call_output(bash_call()), auto_policy("approve")
    )

    assert [call.function for call in output.message.tool_calls or []] == ["bash"]
    assert output.stop_reason == "tool_calls"
    assert "rejected" not in output.message.text


async def test_reject_removes_tool_call_and_explains() -> None:
    """A rejected call must not reach the scaffold, and the model must be told."""
    output = await generate_through_bridge(
        tool_call_output(bash_call()), auto_policy("reject")
    )

    assert not output.message.tool_calls
    # no tool calls left, so this is an ordinary assistant turn
    assert output.stop_reason == "stop"
    assert "`bash`" in output.message.text
    assert "rejected" in output.message.text
    # the original content is preserved alongside the explanation
    assert "running tools" in output.message.text


async def test_reject_is_scoped_to_matching_tools() -> None:
    """A sibling call the policy approves survives, and the turn continues."""
    output = await generate_through_bridge(
        tool_call_output(
            bash_call(id="1"), ToolCall(id="2", function="read", arguments={})
        ),
        [
            ApprovalPolicy(approver=auto_approver("reject"), tools="bash"),
            ApprovalPolicy(approver=auto_approver("approve"), tools="*"),
        ],
    )

    assert [call.function for call in output.message.tool_calls or []] == ["read"]
    # an approved call remains, so the scaffold still owes us tool results
    assert output.stop_reason == "tool_calls"
    assert "`bash`" in output.message.text


async def test_unmatched_tool_is_rejected() -> None:
    """A policy that doesn't cover a tool rejects it (standard policy behaviour).

    Worth pinning for bridges specifically: a scaffold brings a large, largely
    undeclared toolset, so a policy that enumerates only some tools silently
    denies the rest. Bridge policies want a catch-all rule.
    """
    output = await generate_through_bridge(
        tool_call_output(bash_call()), auto_policy("approve", tools="read")
    )

    assert not output.message.tool_calls
    assert "`bash`" in output.message.text


@approver(name="test_modifier")
def modifier() -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(
                id=call.id, function=call.function, arguments={"cmd": "ls -l"}
            ),
            explanation="hardened",
        )

    return approve


async def test_modify_replaces_the_call_the_scaffold_runs() -> None:
    output = await generate_through_bridge(
        tool_call_output(bash_call(cmd="rm -rf /")),
        [ApprovalPolicy(approver=modifier(), tools="*")],
    )

    calls = output.message.tool_calls or []
    assert [call.arguments for call in calls] == [{"cmd": "ls -l"}]
    assert output.stop_reason == "tool_calls"


async def test_terminate_raises() -> None:
    with pytest.raises(TerminateSampleError):
        await generate_through_bridge(
            tool_call_output(bash_call()), auto_policy("terminate")
        )


async def test_approval_event_recorded_in_transcript() -> None:
    """Approvals of bridged tool calls show up in the transcript."""
    await generate_through_bridge(tool_call_output(bash_call()), auto_policy("reject"))

    events = [e for e in transcript().events if isinstance(e, ApprovalEvent)]
    assert len(events) == 1
    assert events[0].decision == "reject"
    assert events[0].call.function == "bash"


async def test_text_only_reply_is_untouched() -> None:
    """No tool calls means no approval work (and no spurious text)."""
    output = await generate_through_bridge(
        ModelOutput.from_content(MODEL, "just talking"), auto_policy("reject")
    )

    assert output.message.text == "just talking"


async def anthropic_bridge_reply(policies: list[ApprovalPolicy]) -> Message:
    """Serve one Anthropic-dialect bridge request under `policies`."""
    init_transcript(Transcript())
    # alias the requested model to our mock instance, since the handler resolves
    # the model by name from the request body
    model = get_model(
        MODEL, custom_outputs=[tool_call_output(bash_call())], memoize=False
    )
    bridge = AgentBridge(AgentState(messages=[]), model_aliases={MODEL: model})
    request = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "list the files"}],
        "max_tokens": 1024,
        "tools": [
            {
                "name": "bash",
                "description": "run a shell command",
                "input_schema": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                },
            }
        ],
    }
    with approval(policies):
        message = await inspect_anthropic_api_request(
            request,
            None,
            internal_web_search_providers(),
            default_code_execution_providers(),
            bridge,
        )
    return cast(Message, message)


async def test_rejected_call_absent_from_scaffold_response() -> None:
    """The safety property, end to end: no `tool_use` block reaches the scaffold.

    Goes through the real Anthropic-dialect handler (what claude_code talks to)
    rather than `bridge_generate` alone, since dropping the Inspect `ToolCall`
    only matters if it also drops the block the scaffold would act on.
    """
    message = await anthropic_bridge_reply(auto_policy("reject"))

    assert [block.type for block in message.content] == ["text"]
    assert message.stop_reason == "end_turn"
    assert "`bash`" in message.content[0].text  # type: ignore[union-attr]


async def test_approved_call_present_in_scaffold_response() -> None:
    """Control for the above: an approved call still reaches the scaffold."""
    message = await anthropic_bridge_reply(auto_policy("approve"))

    assert "tool_use" in [block.type for block in message.content]
    assert message.stop_reason == "tool_use"
