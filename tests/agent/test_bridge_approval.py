"""Tool approval for tool calls made by bridged agents.

A bridged scaffold runs its own tool loop, so `execute_tools()` approval never
runs for it. `bridge_generate` approves the tool calls in each model response
instead, and resolves a rejection by telling the model and regenerating rather
than by editing the response the scaffold sees.
"""

import pytest

from inspect_ai import Task, eval
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.agent._bridge._approval import MAX_CONSECUTIVE_REJECTIONS
from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
from inspect_ai.agent._bridge.bridge import agent_bridge
from inspect_ai.agent._bridge.completions import inspect_completions_api_request
from inspect_ai.agent._bridge.google_api import inspect_google_api_request
from inspect_ai.agent._bridge.responses import inspect_responses_api_request
from inspect_ai.agent._bridge.sandbox.bridge import _monitor_terminate
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    bridge_generate,
    default_code_execution_providers,
    internal_web_search_providers,
)
from inspect_ai.approval import (
    Approval,
    ApprovalPolicy,
    Approver,
    approver,
    auto_approver,
)
from inspect_ai.dataset import Sample
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction import CompactionTrim
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.tool._tool_call import ToolCall, ToolCallView

TASK = "Tidy up the working directory."


@approver(name="test_bridge_reject")
def reject_approver(explanation: str = "Command is not permitted.") -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(decision="reject", explanation=explanation)

    return approve


@approver(name="test_bridge_record")
def recording_approver(seen: list[tuple[str, ToolCall, list[ChatMessage]]]) -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        seen.append((message, call, list(history)))
        return Approval(decision="approve")

    return approve


@approver(name="test_bridge_modify")
def modifying_approver(arguments: dict[str, object]) -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(
                id=call.id, function=call.function, arguments=dict(arguments)
            ),
        )

    return approve


def tool_calls_output(*calls: ToolCall, content: str = "On it.") -> ModelOutput:
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=content, tool_calls=list(calls)),
                stop_reason="tool_calls",
            )
        ],
    )


class BridgeRun:
    """Result of driving `bridge_generate` against a scripted model."""

    def __init__(self, output: ModelOutput, inputs: list[list[ChatMessage]]) -> None:
        self.output = output
        self.inputs = inputs

    @property
    def generations(self) -> int:
        return len(self.inputs)

    def tool_results(self, generation: int) -> list[ChatMessageTool]:
        """Tool messages appended to the input of `generation` (0-based)."""
        return [m for m in self.inputs[generation] if isinstance(m, ChatMessageTool)]


async def run_bridge(
    outputs: list[ModelOutput],
    *,
    approval: list[ApprovalPolicy] | None = None,
    bridge: AgentBridge | None = None,
    input: list[ChatMessage] | None = None,
) -> BridgeRun:
    """Drive `bridge_generate`, recording the input each generation saw."""
    inputs: list[list[ChatMessage]] = []
    remaining = list(outputs)

    def custom_outputs(
        model_input: list[ChatMessage],
        tools: object,
        tool_choice: object,
        config: object,
    ) -> ModelOutput:
        inputs.append(list(model_input))
        # repeat the final output once the script is exhausted, so a test that
        # over-rejects fails on its assertion rather than on StopIteration
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    model = get_model("mockllm/model", custom_outputs=custom_outputs)
    messages: list[ChatMessage] = input or [ChatMessageUser(content=TASK)]
    bridge = bridge or AgentBridge(AgentState(messages=list(messages)))
    if approval is not None:
        bridge.approval = approval

    output, _ = await bridge_generate(
        bridge, model, list(messages), [], None, GenerateConfig()
    )
    return BridgeRun(output, inputs)


# ---------------------------------------------------------------------------
# pass-through
# ---------------------------------------------------------------------------


async def test_no_approver_leaves_output_untouched() -> None:
    """With no policy configured the bridge must not add a generation."""
    call = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    run = await run_bridge([tool_calls_output(call)])

    assert run.generations == 1
    assert run.output.message.tool_calls == [call]


async def test_approved_call_passes_through() -> None:
    call = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    run = await run_bridge(
        [tool_calls_output(call)],
        approval=[ApprovalPolicy(auto_approver("approve"), "*")],
    )

    assert run.generations == 1
    assert run.output.message.tool_calls == [call]


async def test_response_without_tool_calls_skips_approval() -> None:
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    run = await run_bridge(
        [ModelOutput.from_content(model="mockllm/model", content="all done")],
        approval=[ApprovalPolicy(recording_approver(seen), "*")],
    )

    assert run.generations == 1
    assert seen == []


async def test_approver_receives_message_and_history() -> None:
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    call = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    await run_bridge(
        [tool_calls_output(call, content="Listing the directory.")],
        approval=[ApprovalPolicy(recording_approver(seen), "*")],
    )

    assert len(seen) == 1
    message, approved_call, history = seen[0]
    assert message == "Listing the directory."
    assert approved_call.function == "bash"
    # the assistant turn under review terminates the history, as on the native path
    # (`_call_tools.py` passes the conversation whose last message carries the calls)
    assert [m.text for m in history] == [TASK, "Listing the directory."]


async def test_approver_can_see_sibling_calls() -> None:
    """An approver must be able to weigh a call against its siblings.

    The native path gives approvers the assistant message carrying every call in the
    response; a policy that only sees the call under review can't spot a dangerous
    combination.
    """
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    first = ToolCall(id="1", function="read_file", arguments={"path": "a.txt"})
    second = ToolCall(id="2", function="bash", arguments={"cmd": "ls"})
    await run_bridge(
        [tool_calls_output(first, second)],
        approval=[ApprovalPolicy(recording_approver(seen), "*")],
    )

    _, _, history = seen[0]
    assert isinstance(history[-1], ChatMessageAssistant)
    assert history[-1].tool_calls == [first, second]


async def test_approval_history_does_not_leak_into_tracked_state() -> None:
    """Appending the assistant turn for approvers must not touch the caller's list."""
    call = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    await run_bridge(
        [tool_calls_output(call)],
        approval=[ApprovalPolicy(auto_approver("approve"), "*")],
        input=messages,
    )

    assert [(m.role, m.text) for m in messages] == [("user", TASK)]


# ---------------------------------------------------------------------------
# modify
# ---------------------------------------------------------------------------


async def test_modify_is_discarded_when_a_sibling_is_rejected() -> None:
    """A rejected response must replay the model's own turn, not a rewritten one.

    Modifications are applied only once the whole response is approved. Applying
    one as we go would leave the replayed assistant turn attributing arguments to
    the model that it never produced.
    """
    modified = ToolCall(id="1", function="read_file", arguments={"path": "a.txt"})
    unsafe = ToolCall(id="2", function="bash", arguments={"cmd": "rm -rf /"})
    run = await run_bridge(
        [
            tool_calls_output(modified, unsafe),
            ModelOutput.from_content(model="mockllm/model", content="understood"),
        ],
        approval=[
            ApprovalPolicy(reject_approver(), "bash"),
            ApprovalPolicy(modifying_approver({"path": "rewritten.txt"}), "read_file"),
        ],
    )

    replayed = [m for m in run.inputs[1] if isinstance(m, ChatMessageAssistant)][-1]
    assert replayed.tool_calls is not None
    assert replayed.tool_calls[0].arguments == {"path": "a.txt"}


async def test_modify_rewrites_arguments_handed_to_the_scaffold() -> None:
    call = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    run = await run_bridge(
        [tool_calls_output(call)],
        approval=[ApprovalPolicy(modifying_approver({"cmd": "ls"}), "*")],
    )

    assert run.generations == 1
    assert run.output.message.tool_calls is not None
    assert run.output.message.tool_calls[0].arguments == {"cmd": "ls"}


async def test_modify_preserves_the_original_call_in_the_transcript() -> None:
    """The log must still show what the model proposed, not what was approved.

    The `ApprovalEvent` holds the very `ToolCall` object the model produced and the
    `ModelEvent` holds the very `ModelOutput` — pydantic stores both by reference —
    so rewriting arguments in place would erase the evidence that approval changed
    them.
    """
    original = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    proposed = tool_calls_output(original)
    run = await run_bridge(
        [proposed],
        approval=[ApprovalPolicy(modifying_approver({"cmd": "ls"}), "*")],
    )

    # the scaffold gets the approved arguments...
    assert run.output.message.tool_calls is not None
    assert run.output.message.tool_calls[0].arguments == {"cmd": "ls"}
    # ...while the recorded output and its tool call still hold the proposal
    assert original.arguments == {"cmd": "rm -rf /"}
    assert proposed.message.tool_calls is not None
    assert proposed.message.tool_calls[0].arguments == {"cmd": "rm -rf /"}
    assert run.output is not proposed


# ---------------------------------------------------------------------------
# reject: the internal round-trip
# ---------------------------------------------------------------------------


async def test_reject_regenerates_and_hides_the_rejected_call() -> None:
    """The scaffold sees the replacement; the rejected call never reaches it."""
    rejected = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    replacement = ToolCall(id="2", function="bash", arguments={"cmd": "ls"})
    run = await run_bridge(
        [tool_calls_output(rejected), tool_calls_output(replacement)],
        approval=[
            ApprovalPolicy(reject_approver(), "bash(cmd='rm"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    assert run.generations == 2
    assert run.output.message.tool_calls == [replacement]


async def test_reject_replays_the_rejection_to_the_model() -> None:
    """The retry input carries the assistant turn and an approval tool error."""
    rejected = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    run = await run_bridge(
        [
            tool_calls_output(rejected),
            ModelOutput.from_content(model="mockllm/model", content="understood"),
        ],
        approval=[
            ApprovalPolicy(reject_approver("Destructive command."), "bash(cmd='rm"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    retry_input = run.inputs[1]
    assert isinstance(retry_input[-2], ChatMessageAssistant)
    assert retry_input[-2].tool_calls == [rejected]

    results = run.tool_results(1)
    assert len(results) == 1
    assert results[0].tool_call_id == "1"
    assert results[0].error is not None
    assert results[0].error.type == "approval"
    assert "Destructive command." in results[0].error.message


async def test_reject_all_gives_every_call_a_result_naming_the_culprit() -> None:
    """One rejected call discards its peers, and each peer learns which one.

    Uses two calls to the *same* tool with different arguments: a collateral
    message that named only the function would be ambiguous here, and the
    approval policy has to match on the arguments to single one out.
    """
    safe = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    unsafe = ToolCall(id="2", function="bash", arguments={"cmd": "rm -rf /"})
    run = await run_bridge(
        [
            tool_calls_output(safe, unsafe),
            ModelOutput.from_content(model="mockllm/model", content="understood"),
        ],
        approval=[
            ApprovalPolicy(reject_approver("Destructive command."), "bash(cmd='rm"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    # every tool_use needs a tool_result or the retry 400s on Anthropic
    results = run.tool_results(1)
    assert [r.tool_call_id for r in results] == ["1", "2"]
    assert all(r.error is not None and r.error.type == "approval" for r in results)

    collateral = results[0].error.message  # type: ignore[union-attr]
    assert "bash(cmd='rm -rf /')" in collateral
    assert "Destructive command." in collateral
    assert "not itself rejected" in collateral
    # must not be mistakable for a rejection of the safe call
    assert "bash(cmd='ls')" not in collateral

    rejected_message = results[1].error.message  # type: ignore[union-attr]
    assert rejected_message.startswith("Destructive command.")
    assert "The other tool call in this response was not executed" in rejected_message


async def test_collateral_message_bounds_a_huge_rejected_call() -> None:
    """The pointer at the rejected call must not replay its whole payload.

    Arguments can be arbitrarily large and this description lands in every peer's
    result on every retry, so an unbounded render would multiply a big file write
    across the conversation.
    """
    safe = ToolCall(id="1", function="read_file", arguments={"path": "a.txt"})
    huge = ToolCall(id="2", function="write_file", arguments={"content": "x" * 50_000})
    run = await run_bridge(
        [
            tool_calls_output(safe, huge),
            ModelOutput.from_content(model="mockllm/model", content="understood"),
        ],
        approval=[
            ApprovalPolicy(reject_approver(), "write_file"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    collateral = run.tool_results(1)[0].error.message  # type: ignore[union-attr]
    assert "write_file" in collateral
    assert len(collateral) < 1_000


async def test_reject_short_circuits_sibling_evaluation() -> None:
    """Peers after the rejected call are never put to an approver."""
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    trailing = ToolCall(id="2", function="read_file", arguments={"path": "a.txt"})
    await run_bridge(
        [
            tool_calls_output(unsafe, trailing),
            ModelOutput.from_content(model="mockllm/model", content="understood"),
        ],
        approval=[
            ApprovalPolicy(reject_approver(), "bash"),
            ApprovalPolicy(recording_approver(seen), "*"),
        ],
    )

    assert seen == []


# ---------------------------------------------------------------------------
# termination
# ---------------------------------------------------------------------------


async def test_repeated_rejections_terminate_the_sample() -> None:
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    with pytest.raises(TerminateSampleError) as ex:
        await run_bridge(
            [tool_calls_output(unsafe)],
            approval=[ApprovalPolicy(reject_approver(), "*")],
        )

    assert str(MAX_CONSECUTIVE_REJECTIONS) in str(ex.value)


async def test_approved_generation_does_not_accumulate_rejections() -> None:
    """A rejection followed by an approval must not count toward the cap."""
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    safe = ToolCall(id="2", function="read_file", arguments={"path": "a.txt"})
    run = await run_bridge(
        [tool_calls_output(unsafe), tool_calls_output(safe)],
        approval=[
            ApprovalPolicy(reject_approver(), "bash"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    assert run.generations == 2
    assert run.output.message.tool_calls == [safe]


async def test_terminate_decision_terminates_immediately() -> None:
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    with pytest.raises(TerminateSampleError):
        await run_bridge(
            [tool_calls_output(unsafe)],
            approval=[ApprovalPolicy(auto_approver("terminate"), "*")],
        )


def test_sandbox_bridge_terminate_signals_the_monitor() -> None:
    """Sandbox generations run where exceptions can't propagate, so also signal."""
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
    )

    assert not bridge._terminate_requested.is_set()
    with pytest.raises(TerminateSampleError):
        bridge.request_terminate("approver said stop")

    assert bridge._terminate_requested.is_set()
    assert bridge._terminate_reason == "approver said stop"


async def test_sandbox_terminate_monitor_raises_for_the_task_group() -> None:
    """The monitor is what actually reaches the sample runner.

    `request_terminate`'s own raise is swallowed by the sandbox service (which turns
    exceptions into RPC error responses), so the monitor running in the bridge's task
    group is the path that unwinds the agent.
    """
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
    )
    bridge._terminate_reason = "approver said stop"
    bridge._terminate_requested.set()

    with pytest.raises(TerminateSampleError, match="approver said stop"):
        await _monitor_terminate(bridge)


# ---------------------------------------------------------------------------
# policy plumbing
# ---------------------------------------------------------------------------


async def test_escalation_falls_through_to_the_next_policy() -> None:
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    with pytest.raises(TerminateSampleError):
        await run_bridge(
            [tool_calls_output(unsafe)],
            approval=[
                ApprovalPolicy(auto_approver("escalate"), "*"),
                ApprovalPolicy(auto_approver("terminate"), "*"),
            ],
        )


async def test_unmatched_tool_is_rejected_by_the_policy_approver() -> None:
    """Approval mode is deny-by-default: no matching policy means rejection."""
    call = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    run = await run_bridge(
        [
            tool_calls_output(call),
            ModelOutput.from_content(model="mockllm/model", content="understood"),
        ],
        approval=[ApprovalPolicy(auto_approver("approve"), "read_file")],
    )

    assert run.generations == 2
    results = run.tool_results(1)
    assert results[0].error is not None
    assert "No approvers registered for tool bash" in results[0].error.message


async def test_track_state_is_unaffected_by_the_round_trip() -> None:
    """The retry messages stay out of the state the scaffold's impl records.

    `_track_state` fingerprints message prefixes to follow the main thread; if the
    synthetic rejection leaked into the caller's list the next scaffold request
    would no longer extend it.
    """
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    safe = ToolCall(id="2", function="read_file", arguments={"path": "a.txt"})
    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = AgentBridge(AgentState(messages=list(messages)))

    run = await run_bridge(
        [tool_calls_output(unsafe), tool_calls_output(safe)],
        approval=[
            ApprovalPolicy(reject_approver(), "bash"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
        bridge=bridge,
        input=messages,
    )

    # the caller's list is what the dialect impl hands to _track_state
    assert [(m.role, m.text) for m in messages] == [("user", TASK)]

    await bridge._track_state(messages, run.output)
    assert [m.text for m in bridge.state.messages] == [TASK, run.output.message.text]


# ---------------------------------------------------------------------------
# end to end through agent_bridge() and a task-level policy
# ---------------------------------------------------------------------------


@agent
def openai_bridge_agent(scaffold_saw: list[list[str]]) -> Agent:
    """Bridged agent that talks OpenAI Completions, as a real scaffold would."""

    async def execute(state: AgentState) -> AgentState:
        from openai import AsyncOpenAI

        from inspect_ai.model._openai import messages_to_openai

        async with agent_bridge(state) as bridge:
            async with AsyncOpenAI(api_key="sk-test") as client:
                completion = await client.chat.completions.create(
                    model="inspect",
                    messages=await messages_to_openai(state.messages),
                )
            # what the scaffold would go on to execute
            calls = completion.choices[0].message.tool_calls or []
            scaffold_saw.append(
                [c.function.name for c in calls if c.type == "function"]
            )
            return bridge.state

    return execute


def test_task_level_policy_reaches_a_bridged_agent() -> None:
    """A `Task(approval=...)` policy must govern an in-process bridged agent.

    Exercises the whole path a real scaffold takes — the patched OpenAI client, the
    completions dialect impl, `bridge_generate` — rather than calling the hook
    directly, and pins that ambient (non-`approval=`) policies apply.
    """
    scaffold_saw: list[list[str]] = []
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    outputs = [
        tool_calls_output(unsafe),
        ModelOutput.from_content(model="mockllm/model", content="I'll stop there."),
    ]

    log = eval(
        Task(
            dataset=[Sample(input="Tidy up.")],
            solver=openai_bridge_agent(scaffold_saw),
            approval=[
                ApprovalPolicy(reject_approver("Destructive command."), "bash"),
                ApprovalPolicy(auto_approver("approve"), "*"),
            ],
        ),
        model=get_model("mockllm/model", custom_outputs=outputs),
        display="none",
    )[0]

    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]

    # the rejected call never reached the scaffold
    assert scaffold_saw == [[]]

    # and the rejection is on the record
    approvals = [e for e in sample.events if isinstance(e, ApprovalEvent)]
    assert [(e.decision, e.call.function) for e in approvals] == [("reject", "bash")]
    # the recorded call still shows what the model proposed
    assert approvals[0].call.arguments == {"cmd": "rm -rf /"}


# ---------------------------------------------------------------------------
# wiring, and interaction with the rest of bridge_generate
# ---------------------------------------------------------------------------


async def test_agent_bridge_accepts_approval_policies() -> None:
    """The `approval=` parameter must reach the bridge (pure wiring)."""
    policies = [ApprovalPolicy(auto_approver("approve"), "*")]
    async with agent_bridge(approval=policies) as bridge:
        assert bridge.approval is policies


def test_sandbox_bridge_accepts_approval_policies() -> None:
    policies = [ApprovalPolicy(auto_approver("approve"), "*")]
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        approval=policies,
    )
    assert bridge.approval is policies


async def test_bridge_policies_replace_ambient_ones() -> None:
    """`approval=` is documented as replacing active policies for its duration."""
    from inspect_ai.approval import approval as approval_context

    call = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    with approval_context([ApprovalPolicy(auto_approver("terminate"), "*")]):
        run = await run_bridge(
            [tool_calls_output(call)],
            approval=[ApprovalPolicy(auto_approver("approve"), "*")],
        )

    assert run.generations == 1
    assert run.output.message.tool_calls == [call]


async def test_successive_rejections_accumulate_in_the_replayed_input() -> None:
    """Each rejection round must add to the replay, not replace the previous one."""
    first = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    second = ToolCall(id="2", function="bash", arguments={"cmd": "rm -rf /tmp"})
    run = await run_bridge(
        [
            tool_calls_output(first, content="first attempt"),
            tool_calls_output(second, content="second attempt"),
            ModelOutput.from_content(model="mockllm/model", content="giving up"),
        ],
        approval=[
            ApprovalPolicy(reject_approver(), "bash"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    assert run.generations == 3
    # the third input carries BOTH rejected turns and BOTH results, in order
    assert [m.text for m in run.inputs[2] if isinstance(m, ChatMessageAssistant)] == [
        "first attempt",
        "second attempt",
    ]
    assert [r.tool_call_id for r in run.tool_results(2)] == ["1", "2"]


async def test_refusal_retry_still_works_alongside_approval() -> None:
    """The refusal retry shares `bridge_generate`'s loop with approval."""
    refusal = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="refused"),
                stop_reason="content_filter",
            )
        ],
    )
    call = ToolCall(id="1", function="bash", arguments={"cmd": "ls"})
    bridge = AgentBridge(AgentState(messages=[]), retry_refusals=1)
    run = await run_bridge(
        [refusal, tool_calls_output(call)],
        approval=[ApprovalPolicy(auto_approver("approve"), "*")],
        bridge=bridge,
    )

    assert run.generations == 2
    assert run.output.message.tool_calls == [call]
    # a refusal retry resets the input; it must not leave approval artifacts behind
    assert run.tool_results(1) == []


async def test_filter_supplied_output_is_approved() -> None:
    """A filter can substitute the output entirely; those calls still reach the agent."""
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    substituted = [tool_calls_output(unsafe)]

    async def filter(
        model: object,
        input: list[ChatMessage],
        tools: object,
        tool_choice: object,
        config: object,
    ) -> ModelOutput | None:
        return substituted.pop() if substituted else None

    bridge = AgentBridge(AgentState(messages=[]), filter=filter)
    run = await run_bridge(
        [ModelOutput.from_content(model="mockllm/model", content="safer plan")],
        approval=[
            ApprovalPolicy(reject_approver(), "bash"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
        bridge=bridge,
    )

    # the filter's rejected call was replaced, not handed to the agent
    assert run.output.message.tool_calls is None
    assert run.output.message.text == "safer plan"


# ---------------------------------------------------------------------------
# dialects
#
# The hook lives in `bridge_generate`, below dialect translation, so approval
# should behave identically whichever API the scaffold speaks. These drive each
# dialect impl the way a scaffold's request arrives.
# ---------------------------------------------------------------------------

BRIDGE_MODEL = "inspect"


def rejecting_bridge(outputs: list[ModelOutput]) -> AgentBridge:
    model = get_model("mockllm/model", custom_outputs=outputs)
    return AgentBridge(
        AgentState(messages=[]),
        model_aliases={BRIDGE_MODEL: model},
        approval=[
            ApprovalPolicy(reject_approver("Destructive command."), "bash"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )


def rejected_then_safe() -> list[ModelOutput]:
    return [
        tool_calls_output(ToolCall(id="1", function="bash", arguments={"cmd": "rm"})),
        ModelOutput.from_content(model="mockllm/model", content="safer plan"),
    ]


async def test_completions_dialect_hides_the_rejected_call() -> None:
    bridge = rejecting_bridge(rejected_then_safe())
    completion = await inspect_completions_api_request(
        {"model": BRIDGE_MODEL, "messages": [{"role": "user", "content": TASK}]},
        None,
        bridge,
    )

    assert completion.choices[0].message.tool_calls is None
    assert completion.choices[0].message.content == "safer plan"


async def test_anthropic_dialect_hides_the_rejected_call() -> None:
    bridge = rejecting_bridge(rejected_then_safe())
    message = await inspect_anthropic_api_request(
        {
            "model": BRIDGE_MODEL,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": TASK}],
        },
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    assert [b.type for b in message.content] == ["text"]
    assert message.content[0].text == "safer plan"  # type: ignore[union-attr]


async def test_responses_dialect_hides_the_rejected_call() -> None:
    bridge = rejecting_bridge(rejected_then_safe())
    response = await inspect_responses_api_request(
        {"model": BRIDGE_MODEL, "input": TASK},
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    assert [item.type for item in response.output] == ["message"]
    assert response.output_text == "safer plan"


async def test_google_dialect_hides_the_rejected_call() -> None:
    bridge = rejecting_bridge(rejected_then_safe())
    response = await inspect_google_api_request(
        {"contents": [{"role": "user", "parts": [{"text": TASK}]}]},
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    parts = response["candidates"][0]["content"]["parts"]
    assert not any("functionCall" in p or "function_call" in p for p in parts)
    assert parts[0]["text"] == "safer plan"


# ---------------------------------------------------------------------------
# compaction
# ---------------------------------------------------------------------------


async def test_rejection_replay_survives_compaction() -> None:
    """Compaction runs once before the retry loop; the replay is appended after.

    Both features rewrite `bridge_generate`'s input, so this pins that a rejection
    round-trip still reaches the model when a compaction strategy is configured.
    """
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    bridge = AgentBridge(
        AgentState(messages=[]),
        compaction=CompactionTrim(),
        approval=[
            ApprovalPolicy(reject_approver("Destructive command."), "bash"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )
    run = await run_bridge(
        [
            tool_calls_output(unsafe),
            ModelOutput.from_content(model="mockllm/model", content="safer plan"),
        ],
        bridge=bridge,
    )

    assert run.generations == 2
    assert run.output.message.text == "safer plan"
    results = run.tool_results(1)
    assert len(results) == 1
    assert results[0].error is not None
    assert "Destructive command." in results[0].error.message
