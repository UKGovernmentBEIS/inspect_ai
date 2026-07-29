"""Tool approval for bridged agents (see `agent/_bridge/approval.py`).

A bridged scaffold runs its own tool calls, so Inspect never gets to hand it a
tool result the way native approval does. `reject` therefore discards the
whole rejected turn and asks the model again, with the rejection appended to
the conversation as an ordinary tool-result message -- the same shape a
native rejection takes, just never sent to the scaffold. These tests pin:
the resample behaviour, that the scaffold never sees a rejected call, and
that the transcript's `ModelEvent`s always show exactly what the model
generated (never a retroactively edited version).
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
from inspect_ai.event import ApprovalEvent, ModelEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._limit import LimitExceededError, message_limit

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
    outputs: list[ModelOutput], policies: list[ApprovalPolicy] | None
) -> tuple[ModelOutput, list[ModelEvent]]:
    """Run `bridge_generate` under `policies`, serving `outputs` to successive attempts.

    More than one `model.generate()` call happens only if a rejection
    resamples. Returns the final result plus every `ModelEvent` recorded along
    the way, in call order -- one per attempt, each showing exactly what that
    attempt produced.
    """
    init_transcript(Transcript())
    model = get_model(MODEL, custom_outputs=outputs)
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
        result = await run()
    else:
        with approval(policies):
            result = await run()

    events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    return result, events


def auto_policy(decision: ApprovalDecision, tools: str = "*") -> list[ApprovalPolicy]:
    return [ApprovalPolicy(approver=auto_approver(decision), tools=tools)]


async def test_no_policy_leaves_tool_calls_alone() -> None:
    """Control: with no approval policy the reply is untouched."""
    output, events = await generate_through_bridge(
        [tool_call_output(bash_call())], None
    )

    assert [call.function for call in output.message.tool_calls or []] == ["bash"]
    assert output.stop_reason == "tool_calls"
    assert len(events) == 1


async def test_approve_leaves_tool_calls_alone() -> None:
    output, events = await generate_through_bridge(
        [tool_call_output(bash_call())], auto_policy("approve")
    )

    assert [call.function for call in output.message.tool_calls or []] == ["bash"]
    assert output.stop_reason == "tool_calls"
    assert len(events) == 1


async def test_reject_resamples_and_returns_only_the_accepted_attempt() -> None:
    """A rejected call is never returned; the model gets a second try.

    The safety property is unaffected by which attempt eventually succeeds --
    only the final, accepted output is ever handed back to the caller
    (and so to the scaffold).
    """
    output, events = await generate_through_bridge(
        [tool_call_output(bash_call()), ModelOutput.from_content(MODEL, "giving up")],
        auto_policy("reject"),
    )

    assert output.message.text == "giving up"
    assert not output.message.tool_calls
    # both attempts really happened and are both in the transcript, untouched
    assert len(events) == 2
    assert events[0].output.message.tool_calls == [bash_call()]
    assert events[1].output.message.text == "giving up"


async def test_rejected_attempt_reaches_the_model_as_a_tool_result() -> None:
    """The resampled generate() call sees the rejected turn as a real tool result.

    Same shape as a native rejection (the model's own tool_use, followed by a
    tool-result carrying the approver's explanation) -- it just never reaches
    the scaffold, only the model's own next generate() call.
    """
    _, events = await generate_through_bridge(
        [tool_call_output(bash_call()), ModelOutput.from_content(MODEL, "ok")],
        auto_policy("reject"),
    )

    second_input = events[1].input
    assert second_input[-2] is events[0].output.message
    tool_result = second_input[-1]
    assert isinstance(tool_result, ChatMessageTool)
    assert tool_result.tool_call_id == "1"
    assert tool_result.error is not None
    assert tool_result.error.type == "approval"


async def test_reject_discards_whole_turn_including_approved_siblings() -> None:
    """Any rejection in a turn discards the *entire* turn, not just that call.

    The scaffold can only receive one coherent reply, so a turn can't be
    partially resampled -- an approved sibling is retried along with the
    rejected call, and told why in its own tool result.
    """
    output, events = await generate_through_bridge(
        [
            tool_call_output(
                bash_call(id="1"), ToolCall(id="2", function="read", arguments={})
            ),
            ModelOutput.from_content(MODEL, "ok"),
        ],
        [
            ApprovalPolicy(approver=auto_approver("reject"), tools="bash"),
            ApprovalPolicy(approver=auto_approver("approve"), tools="*"),
        ],
    )

    assert output.message.text == "ok"
    assert len(events) == 2
    tool_results = [m for m in events[1].input[-2:] if isinstance(m, ChatMessageTool)]
    results = {m.tool_call_id: m for m in tool_results}
    assert results["1"].error is not None
    assert "sibling" not in results["1"].error.message.lower()  # real reason
    assert results["2"].error is not None
    assert "sibling" in results["2"].error.message


async def test_unmatched_tool_is_rejected() -> None:
    """A policy that doesn't cover a tool rejects it (standard policy behaviour).

    Worth pinning for bridges specifically: a scaffold brings a large, largely
    undeclared toolset, so a policy that enumerates only some tools silently
    denies the rest.
    """
    output, events = await generate_through_bridge(
        [tool_call_output(bash_call()), ModelOutput.from_content(MODEL, "ok")],
        auto_policy("approve", tools="read"),
    )

    assert output.message.text == "ok"
    assert len(events) == 2


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


async def test_modify_returns_the_substitution_without_touching_the_transcript() -> (
    None
):
    """`modify` is faithful to native semantics: the transcript is never rewritten.

    The scaffold-facing result carries the substitution (so that's what
    actually runs), but the `ModelEvent` still shows exactly what the model
    asked for -- matching how a native `modify` leaves the recorded
    `ToolEvent` alone and records the substitution only on the `ApprovalEvent`.
    """
    output, events = await generate_through_bridge(
        [tool_call_output(bash_call(cmd="rm -rf /"))],
        [ApprovalPolicy(approver=modifier(), tools="*")],
    )

    calls = output.message.tool_calls or []
    assert [call.arguments for call in calls] == [{"cmd": "ls -l"}]
    assert len(events) == 1
    assert events[0].output.message.tool_calls == [bash_call(cmd="rm -rf /")]


async def test_terminate_raises() -> None:
    with pytest.raises(TerminateSampleError):
        await generate_through_bridge(
            [tool_call_output(bash_call())], auto_policy("terminate")
        )


async def test_approval_event_recorded_per_attempt() -> None:
    """Every approver decision -- across every resample attempt -- lands in the transcript."""
    await generate_through_bridge(
        [tool_call_output(bash_call()), ModelOutput.from_content(MODEL, "ok")],
        auto_policy("reject"),
    )

    events = [e for e in transcript().events if isinstance(e, ApprovalEvent)]
    assert len(events) == 1
    assert events[0].decision == "reject"
    assert events[0].call.function == "bash"


async def test_text_only_reply_is_untouched() -> None:
    """No tool calls means no approval work (and no resampling)."""
    output, events = await generate_through_bridge(
        [ModelOutput.from_content(MODEL, "just talking")], auto_policy("reject")
    )

    assert output.message.text == "just talking"
    assert len(events) == 1


async def test_reject_resampling_is_bounded_by_message_limit() -> None:
    """No bespoke retry cap -- resampling is bounded by the sample's own limits.

    Each resample is an ordinary generate() call, so it's bounded the same
    way a native agentic loop that keeps getting the same tool call rejected
    would be.
    """
    always_rejected = [tool_call_output(bash_call(id=str(i))) for i in range(10)]

    with message_limit(2):
        with pytest.raises(LimitExceededError):
            await generate_through_bridge(always_rejected, auto_policy("reject"))


async def anthropic_bridge_reply(policies: list[ApprovalPolicy]) -> Message:
    """Serve one Anthropic-dialect bridge request under `policies`."""
    init_transcript(Transcript())
    # alias the requested model to our mock instance, since the handler resolves
    # the model by name from the request body
    model = get_model(
        MODEL,
        custom_outputs=[
            tool_call_output(bash_call()),
            ModelOutput.from_content(MODEL, "ok"),
        ],
        memoize=False,
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
    """The safety property, end to end: no `tool_use` block ever reaches the scaffold.

    Goes through the real Anthropic-dialect handler (what claude_code talks to)
    rather than `bridge_generate` alone, since dropping the Inspect `ToolCall`
    only matters if it also drops the block the scaffold would act on.
    """
    message = await anthropic_bridge_reply(auto_policy("reject"))

    assert [block.type for block in message.content] == ["text"]
    assert message.stop_reason == "end_turn"


async def test_approved_call_present_in_scaffold_response() -> None:
    """Control for the above: an approved call still reaches the scaffold."""
    message = await anthropic_bridge_reply(auto_policy("approve"))

    assert "tool_use" in [block.type for block in message.content]
    assert message.stop_reason == "tool_use"
