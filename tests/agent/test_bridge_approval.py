"""Tool approval for tool calls made by bridged agents.

A bridged scaffold runs its own tool loop, so `execute_tools()` approval never
runs for it. `bridge_generate` approves the tool calls in each model response
instead, and resolves a rejection by telling the model and regenerating rather
than by editing the response the scaffold sees.
"""

import inspect
import json
import logging
import re
from collections import deque
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable, Iterator, Literal, NamedTuple, cast
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from acp.schema import SessionNotification, ToolCallProgress, ToolCallStart
from pydantic import JsonValue
from test_helpers.service_dispatch import (
    dispatching_service,
    serve_beside_failure_monitor,
)

import inspect_ai._util.logger as inspect_logger
from inspect_ai import Task, eval
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent._acp.event_mapping import _AcpEventRouter, replay_transcript
from inspect_ai.agent._acp.transport import AcpUpdate
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.agent._bridge._approval import MAX_CONSECUTIVE_REJECTIONS
from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
from inspect_ai.agent._bridge.bridge import agent_bridge
from inspect_ai.agent._bridge.completions import inspect_completions_api_request
from inspect_ai.agent._bridge.google_api import inspect_google_api_request
from inspect_ai.agent._bridge.responses import inspect_responses_api_request
from inspect_ai.agent._bridge.sandbox.host_tool import execute_host_tool
from inspect_ai.agent._bridge.sandbox.service import (
    _forward_provider_errors,
    generate_completions,
)
from inspect_ai.agent._bridge.sandbox.service import call_tool as call_host_tool
from inspect_ai.agent._bridge.sandbox.types import (
    _MAX_TOOL_EXECUTION_GRANTS,
    SandboxAgentBridge,
)
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
from inspect_ai.event import Event
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.event._info import InfoEvent
from inspect_ai.event._logger import LoggerEvent
from inspect_ai.event._model import ModelEvent
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.event._tool import ToolEvent
from inspect_ai.event._tree import EventTreeSpan, event_tree
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._log import EvalSample
from inspect_ai.log._samples import _sample_active
from inspect_ai.log._transcript import Transcript, _transcript, transcript
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction import CompactionTrim
from inspect_ai.model._generate_config import (
    GenerateConfig,
    active_generate_config_context_var,
)
from inspect_ai.model._model import GenerateInput, Model, get_model
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.model._openai_responses import (
    TOOL_SEARCH_NAME,
    tool_search_output_tools,
)
from inspect_ai.tool import Tool, ToolError, tool
from inspect_ai.tool._tool import ToolParsingError, ToolResult
from inspect_ai.tool._tool_call import ToolCall, ToolCallError, ToolCallView
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParam, ToolParams
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._sandbox.events import SandboxTimeoutError
from inspect_ai.util._span import (
    SpanRotationScope,
    current_span_id,
    parent_span,
    span,
    span_id_provider,
)
from inspect_ai.util._store import Store, _subtask_store

TASK = "Tidy up the working directory."

READ_FILE = "Read a file from the host."
"""The description the bridge serves for the test's bridged `read_file` tool."""

DISPATCHER = "call_mcp_tool"
DISPATCHER_DESCRIPTION = "Call a lazy-loaded MCP tool."
DISPATCHER_PARAMETERS = ("ServerName", "ToolName", "Arguments")


def params(*names: str) -> ToolParams:
    return ToolParams(
        properties={name: ToolParam(type="string", description=name) for name in names},
        required=list(names),
    )


def declare(
    *names: str,
    description: str = READ_FILE,
    parameters: tuple[str, ...] = ("path",),
) -> list[ToolInfo]:
    """The scaffold's declarations of these tools to the model.

    Whatever the scaffold named the tool, it forwards the description (and schema)
    the bridge served; by default that is the test's `read_file` tool's.
    """
    return [
        ToolInfo(name=name, description=description, parameters=params(*parameters))
        for name in names
    ]


def declare_dispatcher() -> list[ToolInfo]:
    """Antigravity's `call_mcp_tool(ServerName, ToolName, Arguments)` declaration."""
    return declare(
        DISPATCHER, description=DISPATCHER_DESCRIPTION, parameters=DISPATCHER_PARAMETERS
    )


def served_tool(
    mock: AsyncMock,
    description: str = READ_FILE,
    parameters: tuple[str, ...] = ("path",),
    name: str = "read_file",
) -> Tool:
    """A bridged tool the bridge serves with this description and schema; runs `mock`."""

    async def execute(**kwargs: Any) -> str:
        return await mock(**kwargs)

    return ToolDef(
        execute, name=name, description=description, parameters=params(*parameters)
    ).as_tool()


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
def modifying_approver(
    arguments: dict[str, object], function: str | None = None
) -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(
                id=call.id,
                function=function or call.function,
                arguments=dict(arguments),
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
    tools: list[ToolInfo] | None = None,
) -> BridgeRun:
    """Drive `bridge_generate`, recording the input each generation saw.

    `tools` are the declarations the scaffold made in the request; grants are
    resolved against them.
    """
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
        bridge,
        model,
        list(messages),
        list(tools or []),
        None,
        GenerateConfig(),
        requested_model=None,
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


async def test_modify_changing_the_function_fails_the_sample() -> None:
    """A `modify` may change only the arguments; a new function is an approver bug."""
    original = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})

    with pytest.raises(RuntimeError, match="may change only the arguments"):
        await run_bridge(
            [tool_calls_output(original)],
            approval=[
                ApprovalPolicy(
                    modifying_approver({"path": "a.txt"}, function="read_file"), "*"
                )
            ],
        )


async def test_dispatched_call_modify_changing_the_target_fails_the_sample() -> None:
    """For a dispatcher call the reviewed target's function may not change either."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool,
        [
            ApprovalPolicy(
                modifying_approver({"path": "b.txt"}, function="write_file"),
                "read_file",
            )
        ],
    )

    with pytest.raises(
        RuntimeError, match="call to 'write_file' for a call to 'read_file'"
    ):
        await run_bridge(
            [tool_calls_output(dispatched("1", {"path": "a.txt"}))], bridge=bridge
        )

    # the sandbox bridge's monitor task fails the sample with the same error
    assert isinstance(bridge._failure, RuntimeError)
    assert "may change only the arguments" in str(bridge._failure)
    # and no host tool may run for the call
    execute = call_host_tool(bridge)
    for path in ("a.txt", "b.txt"):
        with pytest.raises(PermissionError, match="was not proposed by the model"):
            await execute("host", "read_file", {"path": path})
    tool.assert_not_awaited()


async def test_modify_without_a_modified_call_is_rejected() -> None:
    """A `modify` that carries no modified call never hands the original over."""
    original = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    replacement = ToolCall(id="2", function="bash", arguments={"cmd": "ls"})
    run = await run_bridge(
        [tool_calls_output(original), tool_calls_output(replacement)],
        approval=[
            ApprovalPolicy(auto_approver("modify"), "bash", arguments={"cmd": "rm*"}),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    # the model is told and generates again; the scaffold sees only the replacement
    assert run.generations == 2
    assert run.output.message.tool_calls == [replacement]
    (result,) = run.tool_results(1)
    assert result.tool_call_id == "1"
    assert result.error is not None
    assert result.error.type == "approval"
    assert "no modified call" in result.error.message


async def test_sandbox_modify_without_a_modified_call_grants_nothing() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool,
        [
            ApprovalPolicy(
                auto_approver("modify"), "read_file", arguments={"path": "secret*"}
            ),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )
    original = ToolCall(id="1", function="read_file", arguments={"path": "secret"})
    replacement = ToolCall(id="2", function="read_file", arguments={"path": "a.txt"})

    run = await run_bridge(
        [tool_calls_output(original), tool_calls_output(replacement)],
        bridge=bridge,
        tools=declare("read_file"),
    )

    assert run.generations == 2
    assert run.output.message.tool_calls == [replacement]
    execute = call_host_tool(bridge)
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "secret"})
    tool.assert_not_awaited()


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
            ApprovalPolicy(reject_approver(), "bash", arguments={"cmd": "rm*"}),
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
            ApprovalPolicy(
                reject_approver("Destructive command."),
                "bash",
                arguments={"cmd": "rm*"},
            ),
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
            ApprovalPolicy(
                reject_approver("Destructive command."),
                "bash",
                arguments={"cmd": "rm*"},
            ),
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


def test_sandbox_bridge_terminate_raises_for_the_service_dispatcher() -> None:
    """A sandbox bridge terminates by raising, as an in-process bridge does.

    The sandbox service dispatcher answers the RPC and propagates the
    `TerminateSampleError` out of the service task, so the monitor task is not
    signalled as well.
    """
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
    )

    with pytest.raises(TerminateSampleError, match="approver said stop"):
        bridge.request_terminate("approver said stop")

    assert not bridge._failure_requested.is_set()


@pytest.mark.parametrize("repeated", [False, True], ids=["terminate", "rejections"])
async def test_sandbox_approver_termination_ends_the_sample_once(
    monkeypatch: pytest.MonkeyPatch, repeated: bool
) -> None:
    """An approver's termination in a sandbox generation ends the sample once.

    The generation runs in the sandbox service task. `_forward_provider_errors`
    lets the `TerminateSampleError` through to the service dispatcher, which
    answers the RPC once and propagates it out of the service task: that unwinds
    the bridge's task group. The monitor task is not signalled, so the group
    unwinds with the one termination. Covers a `terminate` decision and too many
    consecutive rejections.
    """
    unsafe = ToolCall(id="1", function="bash", arguments={"cmd": "rm -rf /"})
    model = get_model(
        "mockllm/model",
        custom_outputs=[tool_calls_output(unsafe)] * (MAX_CONSECUTIVE_REJECTIONS + 1),
    )
    policy = ApprovalPolicy(
        reject_approver() if repeated else auto_approver("terminate"), "*"
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={BRIDGE_MODEL: model},
        approval=[policy],
    )
    replies: list[str | None] = []
    service = dispatching_service(
        monkeypatch,
        "generate_completions",
        _forward_provider_errors(generate_completions(bridge), bridge),
        {
            "json_data": {
                "model": BRIDGE_MODEL,
                "messages": [{"role": "user", "content": TASK}],
            },
        },
        replies,
    )

    unwound = await serve_beside_failure_monitor(service, bridge)

    assert [type(ex) for ex in unwound] == [TerminateSampleError]
    reason = cast(TerminateSampleError, unwound[0]).reason
    assert reason.startswith("Tool call approver ")
    assert replies == [f"Terminating: {reason}"]
    assert not bridge._failure_requested.is_set()


# ---------------------------------------------------------------------------
# sandbox host-tool execution boundary
# ---------------------------------------------------------------------------


@tool
def read_file(mock: AsyncMock) -> Tool:
    """A typed host tool that hands the arguments it receives to `mock`.

    `call_tool` validates arguments against the tool's schema before calling
    it, so a bare `AsyncMock` (whose signature is `*args, **kwargs`) cannot be
    bridged directly. The parameters cover every shape these tests send.
    """

    async def execute(
        path: str | None = None,
        mode: str | None = None,
        offset: int | None = None,
        raw: bool | None = None,
    ) -> str:
        """Read a file from the host.

        Args:
            path: Path of the file to read.
            mode: Mode to open the file in.
            offset: Offset to start reading from.
            raw: Whether to return raw bytes.
        """
        passed = {"path": path, "mode": mode, "offset": offset, "raw": raw}
        result: str = await mock(**{k: v for k, v in passed.items() if v is not None})
        return result

    return execute


def sandbox_bridge_with_tool(
    tool: AsyncMock,
    approval: list[ApprovalPolicy] | None,
    *,
    require_proposal: bool = True,
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        approval=approval,
        bridged_tools={"host": {"read_file": read_file(tool)}},
        proposal_exempt_servers=set() if require_proposal else {"host"},
    )


async def test_forged_host_tool_call_is_rejected_before_execution() -> None:
    tool = AsyncMock(return_value="secret")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "/secret"})

    tool.assert_not_awaited()


async def test_approved_host_tool_call_has_one_exact_execution_grant() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )
    call = ToolCall(
        id="approved", function="read_file", arguments={"path": "notes.txt"}
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    execute = call_host_tool(bridge)
    assert await execute("host", "read_file", {"path": "notes.txt"}) == "contents"
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "notes.txt"})

    tool.assert_awaited_once_with(path="notes.txt")


async def test_host_tool_execution_grant_binds_arguments() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )
    call = ToolCall(
        id="approved", function="read_file", arguments={"path": "notes.txt"}
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "/secret"})

    tool.assert_not_awaited()


async def test_host_tool_grant_matches_regardless_of_argument_key_order() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )
    call = ToolCall(
        id="approved", function="read_file", arguments={"path": "a", "mode": "r"}
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    # the scaffold re-issues the approved call with the keys in a different order
    result = await call_host_tool(bridge)(
        "host", "read_file", {"mode": "r", "path": "a"}
    )

    assert result == "contents"


# ---------------------------------------------------------------------------
# matching a proposal to the bridged tool it denotes, by served content
# ---------------------------------------------------------------------------


def sandbox_bridge_with_servers(
    bridged_tools: dict[str, dict[str, Tool]],
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        bridged_tools=bridged_tools,
    )


@pytest.mark.parametrize(
    "function",
    [
        "read_file",
        "mcp__host__read_file",
        "mcp_host_read_file",
        "host_read_file",
        "read_fil_9f2b038d5e15",
        "mcp_" + "s" * 26 + "..." + "s" * 20 + "_read_file",
    ],
    ids=["bare", "claude-code", "gemini-cli", "opencode", "codex-hashed", "gemini-cut"],
)
async def test_declared_name_plays_no_part_in_resolution(function: str) -> None:
    """Whatever the scaffold renamed, cut or hashed the tool to, the served description finds it."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(id="proposed", function=function, arguments={"path": "notes.txt"})

    await run_bridge([tool_calls_output(call)], bridge=bridge, tools=declare(function))

    result = await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})

    assert result == "contents"
    tool.assert_awaited_once_with(path="notes.txt")


async def test_declaration_with_another_description_denotes_nothing() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "x"})

    await run_bridge(
        [tool_calls_output(call)],
        bridge=bridge,
        tools=declare("read_file", description="Read a file from the sandbox."),
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "x"})
    tool.assert_not_awaited()


async def test_undeclared_call_registers_no_grant() -> None:
    """A name the scaffold never declared to the model denotes nothing."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={})], []
    )

    assert len(bridge._tool_execution_grants) == 0


async def test_grants_resolve_against_the_declarations_the_filter_generated_with() -> (
    None
):
    """A filter that rewrites the declarations changes what a call denotes.

    The scaffold declared the bridged tool, but the filter replaced that
    declaration with an unrelated local one of the same name before generation;
    the model's call names the local tool, so no host grant is minted.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)

    async def replace_declarations(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> GenerateInput:
        return GenerateInput(
            input,
            declare("read_file", description="Read a file inside the sandbox."),
            tool_choice,
            config,
        )

    bridge.filter = replace_declarations
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "x"})

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare("read_file")
    )

    assert len(bridge._tool_execution_grants) == 0


async def test_empty_declared_description_resolves_an_empty_served_one() -> None:
    """An empty description is matched like any other, so an undocumented tool stays usable.

    `ToolDef` rejects a missing description, so whitespace-only is the served
    empty case.
    """
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(AsyncMock(), description=" ")}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=""),
    )

    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "x"})


async def test_local_tool_with_a_bridged_tools_description_grants_it() -> None:
    """Chosen behaviour: content is the identity, so an identically described local tool is the same tool.

    The bridge cannot tell a scaffold-local tool declared with a bridged tool's
    exact served description and schema from the bridged tool; a call to it
    grants the bridged tool, bounded to the call's arguments. Bridged tools
    should carry distinctive descriptions.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)

    bridge.register_tool_execution_grants(
        [ToolCall(id="local", function="read_file_local", arguments={"path": "x"})],
        declare("read_file_local"),
    )

    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "x"})


def two_tools_one_description() -> SandboxAgentBridge:
    return sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock())},
            "b": {"read_file": served_tool(AsyncMock())},
        }
    )


async def test_declared_schema_does_not_affect_matching() -> None:
    """Scaffolds rewrite schemas (Gemini CLI adds `wait_for_previous`), so only the description counts."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", parameters=("path", "encoding", "wait_for_previous")),
    )

    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "x"})


async def test_same_description_and_schema_grants_each_once() -> None:
    """Two bridged tools the served content cannot tell apart: one grant each.

    Whichever the scaffold's `tools/call` targets runs once with the proposed
    arguments; a second call to the same tool, or other arguments, is denied.
    """
    bridge = two_tools_one_description()

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file"),
    )

    assert not bridge.consume_tool_execution_grant("a", "read_file", {"path": "y"})
    assert bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})
    assert not bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})
    assert bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})
    assert not bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})


def capture_module_warnings(
    caplog: pytest.LogCaptureFixture, module: str
) -> Iterator[None]:
    """Route a module's warnings to caplog.

    Attached directly because `init_logger` stops the inspect_ai logger
    propagating once an earlier test has triggered it.
    """
    module_logger = logging.getLogger(module)
    module_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=module_logger.name):
            yield
    finally:
        module_logger.removeHandler(caplog.handler)


@pytest.fixture
def capture_bridge_warnings(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Route the sandbox bridge module's warnings to caplog."""
    yield from capture_module_warnings(caplog, SandboxAgentBridge.__module__)


@pytest.fixture
def capture_host_tool_warnings(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Route the host tool service's warnings to caplog, with `warn_once` reset.

    `warn_once` dedupes on a module-level list, so an earlier denial of the
    same tool would otherwise suppress the warning.
    """
    monkeypatch.setattr(inspect_logger, "_warned", [])
    yield from capture_module_warnings(caplog, execute_host_tool.__module__)


@pytest.mark.usefixtures("capture_bridge_warnings")
def test_setup_warns_once_naming_every_tool_sharing_a_description(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bridge = two_tools_one_description()

    bridge.warn_indistinct_tools()

    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == 1
    assert "sharing a description" in warnings[0]
    assert "a/read_file" in warnings[0] and "b/read_file" in warnings[0]


@pytest.mark.usefixtures("capture_bridge_warnings")
def test_setup_warns_about_tools_sharing_an_empty_description(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`ToolDef` rejects a missing description, so a whitespace-only one is the empty case."""
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), description=" ")},
            "b": {"read_file": served_tool(AsyncMock(), description="\n")},
        }
    )

    bridge.warn_indistinct_tools()

    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == 1
    assert "a/read_file" in warnings[0] and "b/read_file" in warnings[0]


@pytest.mark.usefixtures("capture_bridge_warnings")
def test_setup_is_silent_for_distinct_descriptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), "Read from a.")},
            "b": {"read_file": served_tool(AsyncMock(), "Read from b.")},
        }
    )

    bridge.warn_indistinct_tools()

    assert caplog.records == []


async def test_description_selects_the_server_whatever_the_name() -> None:
    bridge = sandbox_bridge_with_servers(
        {
            "a": {
                "read_file": served_tool(AsyncMock(return_value="a"), "Read from a.")
            },
            "b": {
                "read_file": served_tool(AsyncMock(return_value="b"), "Read from b.")
            },
        }
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="mcp__a__read_file", arguments={})],
        declare("mcp__a__read_file", description="Read from b."),
    )

    assert not bridge.consume_tool_execution_grant("a", "read_file", {})
    assert bridge.consume_tool_execution_grant("b", "read_file", {})


# ---------------------------------------------------------------------------
# truncated descriptions
# ---------------------------------------------------------------------------

LONG = "Read a file from the host and return its contents. " * 60
"""A served description far longer than any scaffold's limit (about 3000 chars)."""


@pytest.mark.parametrize(
    "declared",
    [
        LONG[:2048] + "… [truncated]",
        LONG[:2048] + "...",
        LONG[:100] + " [...]",
        LONG[:100].rstrip() + "…",
    ],
    ids=["claude-code-style", "ellipsis", "bracketed", "single-ellipsis-char"],
)
async def test_truncated_description_resolves(declared: str) -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(tool, LONG)}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=declared),
    )

    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "x"})


async def test_truncation_shorter_than_the_minimum_prefix_does_not_resolve() -> None:
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(AsyncMock(), LONG)}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=LONG[:40] + "..."),
    )

    assert len(bridge._tool_execution_grants) == 0


async def test_rewritten_tail_longer_than_a_marker_does_not_resolve() -> None:
    """A truncation marker is short; a longer tail after the common prefix is a rewrite."""
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(AsyncMock(), LONG)}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare(
            "read_file",
            description=LONG[:2048] + " (the scaffold's own note on this tool)",
        ),
    )

    assert len(bridge._tool_execution_grants) == 0


def two_tools_sharing_a_prefix() -> SandboxAgentBridge:
    return sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), LONG + " Text files only.")},
            "b": {"read_file": served_tool(AsyncMock(), LONG + " Any file type.")},
        }
    )


async def test_truncation_matching_two_tools_grants_both() -> None:
    bridge = two_tools_sharing_a_prefix()

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=LONG[:2048] + "… [truncated]"),
    )

    assert bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})
    assert bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})
    assert len(bridge._tool_execution_grants) == 0


async def test_served_description_that_prefixes_another_grants_both_when_truncated() -> (
    None
):
    """A truncation ending exactly at the shorter description could be either tool."""
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), LONG)},
            "b": {"read_file": served_tool(AsyncMock(), LONG + " Any file type.")},
        }
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=LONG.rstrip() + "…"),
    )

    assert bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})
    assert bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})


async def test_exact_match_wins_over_a_prefix_match() -> None:
    """A declaration equal to the shorter description is that tool; the scaffold forwarded it whole."""
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), LONG)},
            "b": {"read_file": served_tool(AsyncMock(), LONG + " Any file type.")},
        }
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=LONG),
    )

    assert not bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})
    assert bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})


ANTIGRAVITY_PREAMBLE = "This is a tool from the host MCP server.\n\n"


async def test_description_with_a_scaffold_preamble_resolves() -> None:
    """Antigravity declares every MCP tool as a fixed sentence plus the served description."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(tool, LONG)}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=ANTIGRAVITY_PREAMBLE + LONG),
    )

    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "x"})


async def test_preamble_longer_than_a_scaffold_sentence_does_not_resolve() -> None:
    """A long leading text is a rewrite, not a preamble, and denotes nothing."""
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(AsyncMock(), LONG)}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=("x" * 97) + LONG),
    )

    assert len(bridge._tool_execution_grants) == 0


async def test_preamble_before_a_short_description_does_not_resolve() -> None:
    """A short served text could be the accidental tail of any declaration."""
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(AsyncMock(), "Read a file.")}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=ANTIGRAVITY_PREAMBLE + "Read a file."),
    )

    assert len(bridge._tool_execution_grants) == 0


async def test_exact_match_wins_over_a_preamble_match() -> None:
    """A declaration equal to one served description is that tool, not another it also ends with."""
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), ANTIGRAVITY_PREAMBLE + LONG)},
            "b": {"read_file": served_tool(AsyncMock(), LONG)},
        }
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=ANTIGRAVITY_PREAMBLE + LONG),
    )

    assert not bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})
    assert bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})


async def test_prefixed_copy_of_a_longer_description_does_not_grant_its_tail() -> None:
    """The whole longer description is present, so the shorter tool it ends with is not denoted."""
    tail = LONG
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), "Only when asked. " + tail)},
            "b": {"read_file": served_tool(AsyncMock(), tail)},
        }
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare(
            "read_file", description=ANTIGRAVITY_PREAMBLE + "Only when asked. " + tail
        ),
    )

    assert not bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})
    assert bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})
    assert len(bridge._tool_execution_grants) == 0


async def test_prefixed_copy_of_a_shared_description_grants_both() -> None:
    """Two tools served the same text cannot be told apart through a preamble either."""
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(), LONG)},
            "b": {"read_file": served_tool(AsyncMock(), LONG)},
        }
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=ANTIGRAVITY_PREAMBLE + LONG),
    )

    assert bridge.consume_tool_execution_grant("a", "read_file", {"path": "x"})
    assert bridge.consume_tool_execution_grant("b", "read_file", {"path": "x"})


INDENTED = """Control a browser and report what the page shows.

        Use it to open pages and read their contents.

        Args:
            action: What to do.
            url: Where to go.
        """
"""A served description that is a raw method docstring, as Python 3.10-3.12 keep it."""


async def test_dedented_copy_of_an_indented_description_resolves() -> None:
    """Antigravity declares `inspect.cleandoc` of an indented served description."""
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(AsyncMock(), INDENTED)}}
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare(
            "read_file",
            description=ANTIGRAVITY_PREAMBLE + inspect.cleandoc(INDENTED) + "\n",
        ),
    )

    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "x"})


async def test_copy_flattening_relative_indentation_does_not_resolve() -> None:
    """Only the common indentation may be removed; nested indentation is content."""
    bridge = sandbox_bridge_with_servers(
        {"host": {"read_file": served_tool(AsyncMock(), INDENTED)}}
    )
    flattened = "\n".join(line.strip() for line in INDENTED.strip().split("\n"))

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "x"})],
        declare("read_file", description=ANTIGRAVITY_PREAMBLE + flattened),
    )

    assert len(bridge._tool_execution_grants) == 0


# ---------------------------------------------------------------------------
# a granted key the served schema does not declare (consume_tool_execution_grant)
# ---------------------------------------------------------------------------


async def test_undeclared_granted_key_absent_from_executed_args_still_grants() -> None:
    """A scaffold-proposed bookkeeping key the schema never declared is dropped.

    Measured from a real Antigravity session: the scaffold proposes
    `{"action": "navigate", "url": ..., "toolSummary": ...}` to the model for the
    `browser` tool, whose own schema declares only `action` and `url`, then
    dispatches the real call without `toolSummary`. The grant must still resolve.
    """
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                "browser": served_tool(
                    AsyncMock(), parameters=("action", "url"), name="browser"
                )
            }
        }
    )

    bridge.register_tool_execution_grants(
        [
            ToolCall(
                id="proposed",
                function="browser",
                arguments={
                    "action": "navigate",
                    "url": "https://example.com/product/814207",
                    "toolSummary": "Product page lookup",
                },
            )
        ],
        declare("browser", parameters=("action", "url")),
    )

    assert bridge.consume_tool_execution_grant(
        "host",
        "browser",
        {"action": "navigate", "url": "https://example.com/product/814207"},
    )


async def test_executed_args_with_an_undeclared_key_still_denies() -> None:
    """Dropping an undeclared GRANTED key never licenses an undeclared EXECUTED one."""
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                "browser": served_tool(
                    AsyncMock(), parameters=("action", "url"), name="browser"
                )
            }
        }
    )

    bridge.register_tool_execution_grants(
        [
            ToolCall(
                id="proposed",
                function="browser",
                arguments={
                    "action": "navigate",
                    "url": "https://example.com/product/814207",
                },
            )
        ],
        declare("browser", parameters=("action", "url")),
    )

    assert not bridge.consume_tool_execution_grant(
        "host",
        "browser",
        {
            "action": "navigate",
            "url": "https://example.com/product/814207",
            "unexpected": "value",
        },
    )


async def test_executed_args_repeating_a_proposed_undeclared_key_still_grants() -> None:
    """A call executed exactly as proposed is granted, undeclared keys included."""
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                "browser": served_tool(
                    AsyncMock(), parameters=("action", "url"), name="browser"
                )
            }
        }
    )
    proposed = {
        "action": "navigate",
        "url": "https://example.com/product/814207",
        "unexpected": "value",
    }

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="browser", arguments=proposed)],
        declare("browser", parameters=("action", "url")),
    )

    assert bridge.consume_tool_execution_grant("host", "browser", dict(proposed))
    assert len(bridge._tool_execution_grants) == 0


async def test_an_exact_grant_wins_over_an_earlier_filtered_one() -> None:
    """A call consumes the grant it repeats exactly before one it matches only after filtering."""
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                "browser": served_tool(
                    AsyncMock(), parameters=("action", "url"), name="browser"
                )
            }
        }
    )
    without_extra = {"action": "navigate", "url": "https://example.com/product/814207"}
    with_extra = {**without_extra, "unexpected": "value"}

    bridge.register_tool_execution_grants(
        [
            ToolCall(id="first", function="browser", arguments=with_extra),
            ToolCall(id="second", function="browser", arguments=without_extra),
        ],
        declare("browser", parameters=("action", "url")),
    )

    assert bridge.consume_tool_execution_grant("host", "browser", dict(without_extra))
    assert bridge.consume_tool_execution_grant("host", "browser", dict(with_extra))
    assert len(bridge._tool_execution_grants) == 0


async def test_executed_args_changing_a_declared_value_still_denies() -> None:
    """A declared key must still match exactly, value included."""
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                "browser": served_tool(
                    AsyncMock(), parameters=("action", "url"), name="browser"
                )
            }
        }
    )

    bridge.register_tool_execution_grants(
        [
            ToolCall(
                id="proposed",
                function="browser",
                arguments={
                    "action": "navigate",
                    "url": "https://example.com/product/814207",
                    "toolSummary": "Product page lookup",
                },
            )
        ],
        declare("browser", parameters=("action", "url")),
    )

    assert not bridge.consume_tool_execution_grant(
        "host",
        "browser",
        {"action": "navigate", "url": "https://example.com/product/999999"},
    )


async def test_executed_args_dropping_a_declared_key_still_denies() -> None:
    """A declared key must still be PRESENT on the executed side."""
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                "browser": served_tool(
                    AsyncMock(), parameters=("action", "url"), name="browser"
                )
            }
        }
    )

    bridge.register_tool_execution_grants(
        [
            ToolCall(
                id="proposed",
                function="browser",
                arguments={
                    "action": "navigate",
                    "url": "https://example.com/product/814207",
                    "toolSummary": "Product page lookup",
                },
            )
        ],
        declare("browser", parameters=("action", "url")),
    )

    assert not bridge.consume_tool_execution_grant(
        "host", "browser", {"action": "navigate"}
    )


async def test_closed_schema_without_properties_drops_every_undeclared_key() -> None:
    """A schema that declares no arguments and forbids others binds an empty call."""
    bridge = sandbox_bridge_with_servers(
        {"host": {"browser": served_tool(AsyncMock(), parameters=(), name="browser")}}
    )

    bridge.register_tool_execution_grants(
        [
            ToolCall(
                id="proposed",
                function="browser",
                arguments={"toolSummary": "Product page lookup"},
            )
        ],
        declare("browser", parameters=()),
    )

    assert bridge.consume_tool_execution_grant("host", "browser", {})


async def test_host_tool_executes_without_a_proposed_key_its_schema_forbids() -> None:
    """The measured Antigravity shape, through the host tool service."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(
        id="proposed",
        function="read_file",
        arguments={"path": "notes.txt", "toolSummary": "Read the notes"},
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    execute = call_host_tool(bridge)
    assert await execute("host", "read_file", {"path": "notes.txt"}) == "contents"
    tool.assert_awaited_once_with(path="notes.txt")


DELETE_PATH = "Delete a path on the host, or report what would be deleted."


def open_host_tool(
    mock: AsyncMock, additional_properties: ToolParam | bool | None
) -> Tool:
    """A variadic host tool declaring `path` that accepts other arguments too."""

    async def execute(**kwargs: Any) -> str:
        return await mock(**kwargs)

    return ToolDef(
        execute,
        name="delete_path",
        description=DELETE_PATH,
        parameters=ToolParams(
            properties={"path": ToolParam(type="string", description="path")},
            required=["path"],
            additionalProperties=additional_properties,
        ),
    ).as_tool()


@pytest.mark.parametrize(
    "additional_properties",
    [True, ToolParam(type="boolean"), None],
    ids=["true", "schema", "omitted"],
)
async def test_open_schema_host_tool_cannot_drop_an_approved_argument(
    additional_properties: ToolParam | bool | None,
) -> None:
    """On a schema admitting other arguments, an undeclared one is a real argument.

    The approver adds `dry_run`; executing without it would run a different
    action than the one approved.
    """
    tool = AsyncMock(return_value="done")
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        approval=[
            ApprovalPolicy(modifying_approver({"path": "target", "dry_run": True}), "*")
        ],
        bridged_tools={
            "host": {"delete_path": open_host_tool(tool, additional_properties)}
        },
    )
    call = ToolCall(id="proposed", function="delete_path", arguments={"path": "target"})

    await run_bridge(
        [tool_calls_output(call)],
        bridge=bridge,
        tools=declare(call.function, description=DELETE_PATH),
    )

    execute = call_host_tool(bridge)
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "delete_path", {"path": "target"})
    tool.assert_not_awaited()
    assert await execute(
        "host", "delete_path", {"path": "target", "dry_run": True}
    ) == ("done")
    tool.assert_awaited_once_with(path="target", dry_run=True)


# ---------------------------------------------------------------------------
# the dispatcher shape (Antigravity's call_mcp_tool)
# ---------------------------------------------------------------------------


async def test_dispatcher_call_grants_the_named_target_with_its_arguments() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(
        id="proposed",
        function=DISPATCHER,
        arguments={
            "ServerName": "host",
            "ToolName": "read_file",
            "Arguments": {"path": "notes.txt"},
        },
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare_dispatcher()
    )

    execute = call_host_tool(bridge)
    assert await execute("host", "read_file", {"path": "notes.txt"}) == "contents"
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "notes.txt"})
    tool.assert_awaited_once_with(path="notes.txt")


@pytest.mark.parametrize(
    "arguments",
    [
        {"ServerName": "other", "ToolName": "read_file", "Arguments": {}},
        {"ServerName": "host", "ToolName": "write_file", "Arguments": {}},
        {"ServerName": "host", "ToolName": "read_file", "Arguments": "{}"},
        {"ServerName": "host", "ToolName": "read_file"},
        {"server": "host", "tool": "read_file", "arguments": {}},
    ],
    ids=[
        "unknown-server",
        "unknown-tool",
        "arguments-not-an-object",
        "no-arguments",
        "other-parameter-names",
    ],
)
async def test_dispatcher_call_off_shape_registers_no_grant(
    arguments: dict[str, object],
) -> None:
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function=DISPATCHER, arguments=arguments)],
        declare_dispatcher(),
    )

    assert len(bridge._tool_execution_grants) == 0


@pytest.mark.parametrize("function", ["bash", "read_file"], ids=["local", "bridged"])
async def test_ordinary_call_with_dispatcher_shaped_arguments_mints_no_grant(
    function: str,
) -> None:
    """Only `call_mcp_tool` dispatches; naming a bridged tool in arguments is not a proposal.

    The local `bash` declaration denotes nothing; the bridged `read_file`
    declaration denotes itself, so its grant binds these odd arguments and the
    nested `Arguments` never reach `host/read_file`.
    """
    tool = AsyncMock(return_value="secret")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(
        id="proposed",
        function=function,
        arguments={
            "cmd": "ls",
            "ServerName": "host",
            "ToolName": "read_file",
            "Arguments": {"path": "/secret"},
        },
    )
    declarations = (
        declare("bash", description="Run a shell command.", parameters=("cmd",))
        if function == "bash"
        else declare("read_file")
    )

    await run_bridge([tool_calls_output(call)], bridge=bridge, tools=declarations)

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "/secret"})
    tool.assert_not_awaited()


async def test_bridged_tool_matched_by_content_takes_precedence_over_dispatch() -> None:
    """A bridged tool that happens to look like a dispatcher is that tool, not a dispatch."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                DISPATCHER: served_tool(
                    tool, "Route a call.", DISPATCHER_PARAMETERS, name=DISPATCHER
                )
            },
            "other": {"read_file": served_tool(AsyncMock(return_value="other"))},
        }
    )
    arguments = {"ServerName": "other", "ToolName": "read_file", "Arguments": {}}

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function=DISPATCHER, arguments=arguments)],
        declare(
            DISPATCHER, description="Route a call.", parameters=DISPATCHER_PARAMETERS
        ),
    )

    assert not bridge.consume_tool_execution_grant("other", "read_file", {})
    assert bridge.consume_tool_execution_grant("host", DISPATCHER, arguments)


async def test_scaffold_local_tool_calls_are_not_stored() -> None:
    """Calls whose names cannot denote a bridged tool must not fill the store."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )

    bridge.register_tool_execution_grants(
        [ToolCall(id="local", function="bash", arguments={"cmd": "ls"})],
        declare("bash", description="Run a shell command.", parameters=("cmd",)),
    )

    assert len(bridge._tool_execution_grants) == 0


async def test_host_tool_grant_matches_numeric_reserialization() -> None:
    """A JS scaffold's JSON round-trip coerces 5.0 to 5; both must match."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )
    call = ToolCall(id="approved", function="read_file", arguments={"offset": 5.0})

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    result = await call_host_tool(bridge)("host", "read_file", {"offset": 5})

    assert result == "contents"


async def test_host_tool_grant_normalizes_non_json_arguments() -> None:
    """Approver `modify` can inject non-JSON values.

    The grant must match the JSON form a scaffold re-sends over MCP, not the
    raw Python object.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool,
        [ApprovalPolicy(modifying_approver({"path": PurePosixPath("x.txt")}), "*")],
    )
    call = ToolCall(id="approved", function="read_file", arguments={"path": "a.txt"})

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "x.txt"})


async def test_host_tool_grant_distinguishes_bool_from_number() -> None:
    """Python `True == 1`, but a bool approval must not authorize a number."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )
    call = ToolCall(id="approved", function="read_file", arguments={"raw": True})

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    execute = call_host_tool(bridge)
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"raw": 1})
    assert await execute("host", "read_file", {"raw": True}) == "contents"


async def test_multi_choice_response_truncated_under_approval() -> None:
    """Only the primary choice is reviewed, so alternates must not reach the scaffold."""
    unreviewed = ToolCall(id="alt", function="bash", arguments={"cmd": "rm -rf /"})
    output = tool_calls_output(
        ToolCall(id="main", function="bash", arguments={"cmd": "ls"})
    )
    output.choices.append(
        ChatCompletionChoice(
            message=ChatMessageAssistant(content="", tool_calls=[unreviewed]),
            stop_reason="tool_calls",
        )
    )

    run = await run_bridge(
        [output], approval=[ApprovalPolicy(auto_approver("approve"), "*")]
    )

    assert len(run.output.choices) == 1
    assert run.output.message.tool_calls is not None
    assert run.output.message.tool_calls[0].id == "main"


async def test_multi_choice_text_alternates_pass_through_under_approval() -> None:
    """Alternates without tool calls carry nothing to review, so they survive."""
    output = tool_calls_output(
        ToolCall(id="main", function="bash", arguments={"cmd": "ls"})
    )
    output.choices.append(
        ChatCompletionChoice(
            message=ChatMessageAssistant(content="alternate"),
            stop_reason="stop",
        )
    )

    run = await run_bridge(
        [output], approval=[ApprovalPolicy(auto_approver("approve"), "*")]
    )

    assert len(run.output.choices) == 2


async def test_multi_choice_response_passes_through_without_approval() -> None:
    output = tool_calls_output(
        ToolCall(id="main", function="bash", arguments={"cmd": "ls"})
    )
    output.choices.append(
        ChatCompletionChoice(
            message=ChatMessageAssistant(content="alternate"),
            stop_reason="stop",
        )
    )

    run = await run_bridge([output])

    assert len(run.output.choices) == 2


async def test_host_tool_grant_binds_to_approver_modified_arguments() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(modifying_approver({"path": "rewritten.txt"}), "*")]
    )
    call = ToolCall(
        id="approved", function="read_file", arguments={"path": "original.txt"}
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    execute = call_host_tool(bridge)
    # the model's original arguments are not what the approver approved
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "original.txt"})
    # the modified arguments are the approved action
    assert await execute("host", "read_file", {"path": "rewritten.txt"}) == "contents"
    tool.assert_awaited_once_with(path="rewritten.txt")


# ---------------------------------------------------------------------------
# sandbox host-tool execution boundary without an approval policy
# ---------------------------------------------------------------------------


async def test_unproposed_host_tool_call_is_denied_without_approval_policy() -> None:
    """A host tool runs only for a call the model proposed, policy or no policy."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})

    tool.assert_not_awaited()


async def test_proposed_host_tool_call_executes_once_without_approval_policy() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(
        id="proposed", function="read_file", arguments={"path": "notes.txt"}
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    execute = call_host_tool(bridge)
    assert await execute("host", "read_file", {"path": "notes.txt"}) == "contents"
    # a second call for the same proposal (e.g. a scaffold retrying after a
    # transport failure) is denied; the model has to propose the call again
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "notes.txt"})

    tool.assert_awaited_once_with(path="notes.txt")


async def test_host_tool_call_with_other_arguments_is_denied_without_approval_policy() -> (
    None
):
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(
        id="proposed", function="read_file", arguments={"path": "notes.txt"}
    )

    await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare(call.function)
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "/secret"})

    tool.assert_not_awaited()


async def test_host_tool_grants_are_stored_without_approval_policy() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "a"})],
        declare("read_file"),
    )

    assert len(bridge._tool_execution_grants) == 1


async def test_opted_out_server_executes_without_a_proposal() -> None:
    """`require_proposal=False` gives up the correspondence for that server."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)

    result = await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})

    assert result == "contents"
    tool.assert_awaited_once_with(path="notes.txt")


async def test_opted_out_server_stores_grants_for_attribution() -> None:
    """A proposed call on an opted-out server still pairs with its proposal.

    The grant is not required to execute; it only lets the host tool's event
    carry the proposing call's id.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "a"})],
        declare("read_file"),
    )

    assert len(bridge._tool_execution_grants) == 1
    grant = bridge.consume_tool_execution_grant("host", "read_file", {"path": "a"})
    assert grant is not None
    assert grant.proposal.call.id == "proposed"


@pytest.mark.usefixtures("capture_host_tool_warnings")
async def test_denial_warning_names_the_opt_out(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log names `require_proposal=False`; the error the model sees is unchanged."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)

    with pytest.raises(PermissionError) as denied:
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})

    assert str(denied.value) == (
        "Host tool call 'host/read_file' was not proposed by the model in a "
        "bridged generation (a bridged host tool runs once per proposed call)"
    )
    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == 1
    assert warnings[0].startswith("Denied host tool call 'host/read_file'")
    assert (
        "set require_proposal=False on the existing BridgedToolsSpec for server "
        "'host'" in warnings[0]
    )


CODE_MODE_EXEC = (
    "Run JavaScript code to orchestrate/compose tool calls.\n\n"
    "### `mcp__host__read_file`\n"
    f"{READ_FILE}\n\n"
    "```ts\n"
    "declare function mcp__host__read_file(args: { path?: string }): "
    "Promise<unknown>;\n"
    "```\n"
)
"""Codex code mode's `exec` description with the inline nested-tool catalog."""


async def run_code_mode_exec(bridge: SandboxAgentBridge) -> None:
    """A code-mode turn: the model proposes only `exec`, whose script calls `read_file`."""
    call = ToolCall(
        id="exec",
        function="exec",
        arguments={"input": 'await tools.mcp__host__read_file({"path": "notes.txt"});'},
    )
    await run_bridge(
        [tool_calls_output(call)],
        bridge=bridge,
        tools=declare("exec", description=CODE_MODE_EXEC, parameters=("input",))
        + declare("wait", description="Wait for a running exec.", parameters=()),
    )


async def test_code_mode_exec_call_grants_no_nested_tool() -> None:
    """An `exec` proposal grants nothing for the host tool calls its script makes.

    The script's calls and their arguments are decided when it runs in the
    sandbox, so a grant from the `exec` proposal would authorize whatever the
    sandbox makes of the script; parsing literal calls out of the script would
    bring back name matching and cover only some scripts. The bridge does not
    detect code mode either: current Codex defers MCP tools in code mode, so the
    `exec` declaration names none of them, and an unproposed call from a script
    looks the same as a model probing the endpoint.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)

    await run_code_mode_exec(bridge)

    assert len(bridge._tool_execution_grants) == 0
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})
    tool.assert_not_awaited()


async def test_code_mode_exec_call_runs_nested_tool_when_opted_out() -> None:
    """`require_proposal=False` is the remedy the docs give for code mode."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)

    await run_code_mode_exec(bridge)

    result = await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})

    assert result == "contents"
    tool.assert_awaited_once_with(path="notes.txt")


def multi_choice_output_with_tool_call_alternate() -> ModelOutput:
    output = tool_calls_output(
        ToolCall(id="main", function="bash", arguments={"cmd": "ls"})
    )
    output.choices.append(
        ChatCompletionChoice(
            message=ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(id="alt", function="bash", arguments={"cmd": "rm -rf /"})
                ],
            ),
            stop_reason="tool_calls",
        )
    )
    return output


async def test_multi_choice_alternates_with_tool_calls_dropped_for_sandbox_bridge() -> (
    None
):
    """Alternates' calls would have no execution grant, so they must not reach the scaffold."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)

    run = await run_bridge(
        [multi_choice_output_with_tool_call_alternate()], bridge=bridge
    )

    assert len(run.output.choices) == 1
    assert run.output.message.tool_calls is not None
    assert run.output.message.tool_calls[0].id == "main"


async def test_multi_choice_alternates_pass_through_for_in_process_bridge() -> None:
    """An in-process bridge grants nothing, so without a policy there is nothing to protect."""
    run = await run_bridge([multi_choice_output_with_tool_call_alternate()])

    assert len(run.output.choices) == 2


@pytest.mark.usefixtures("capture_bridge_warnings")
@pytest.mark.parametrize("exempt", [False, True], ids=["required", "exempt"])
def test_eviction_warning_says_what_the_evicted_grant_loses(
    exempt: bool, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exempt server's grant only loses pairing; a required server's loses execution."""
    monkeypatch.setattr(inspect_logger, "_warned", [])
    bridge = sandbox_bridge_with_tool(
        AsyncMock(return_value="contents"), None, require_proposal=not exempt
    )

    bridge.register_tool_execution_grants(
        [
            ToolCall(id=str(index), function="read_file", arguments={"path": "a"})
            for index in range(_MAX_TOOL_EXECUTION_GRANTS + 1)
        ],
        declare("read_file"),
    )

    [warning] = [r.getMessage() for r in caplog.records]
    assert "require_proposal=False servers count too" in warning
    if exempt:
        assert "that call still executes" in warning
        assert "no longer pairs" in warning
    else:
        assert "can no longer be executed" in warning


async def test_host_tool_execution_grants_are_bounded() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")]
    )

    bridge.register_tool_execution_grants(
        [
            ToolCall(
                id=str(index),
                function="read_file",
                arguments={"path": str(index)},
            )
            for index in range(_MAX_TOOL_EXECUTION_GRANTS + 1)
        ],
        declare("read_file"),
    )

    assert len(bridge._tool_execution_grants) == _MAX_TOOL_EXECUTION_GRANTS
    assert not bridge.consume_tool_execution_grant("host", "read_file", {"path": "0"})
    assert bridge.consume_tool_execution_grant("host", "read_file", {"path": "1"})


# ---------------------------------------------------------------------------
# dispatcher calls (Antigravity's call_mcp_tool)
# ---------------------------------------------------------------------------


def dispatched(
    call_id: str, arguments: dict[str, object], *, tool: str = "read_file"
) -> ToolCall:
    """A `call_mcp_tool` dispatcher call targeting bridged `host/<tool>`."""
    return ToolCall(
        id=call_id,
        function="call_mcp_tool",
        arguments={"ServerName": "host", "ToolName": tool, "Arguments": arguments},
    )


async def test_dispatched_call_is_matched_by_the_target_tool_name() -> None:
    """A policy scoped to the bridged tool's name governs a dispatcher call to it."""
    bridge = sandbox_bridge_with_tool(
        AsyncMock(),
        [
            ApprovalPolicy(reject_approver(), "read_file"),
            ApprovalPolicy(auto_approver(), "*"),
        ],
    )
    safe = ToolCall(id="2", function="bash", arguments={"cmd": "ls"})

    run = await run_bridge(
        [
            tool_calls_output(dispatched("1", {"path": "a.txt"})),
            tool_calls_output(safe),
        ],
        bridge=bridge,
    )

    assert run.generations == 2
    assert run.output.message.tool_calls == [safe]
    (result,) = run.tool_results(1)
    assert result.tool_call_id == "1"
    assert result.function == "call_mcp_tool"


async def test_dispatched_call_approver_sees_the_target_call() -> None:
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    bridge = sandbox_bridge_with_tool(
        AsyncMock(), [ApprovalPolicy(recording_approver(seen), "read_file")]
    )
    call = dispatched("1", {"path": "a.txt"})

    run = await run_bridge([tool_calls_output(call)], bridge=bridge)

    ((_, reviewed, history),) = seen
    assert reviewed == ToolCall(
        id="1", function="read_file", arguments={"path": "a.txt"}
    )
    # the turn under review still carries the call as the model made it
    assert isinstance(history[-1], ChatMessageAssistant)
    assert history[-1].tool_calls == [call]
    # and so does the response handed to the scaffold
    assert run.output.message.tool_calls == [call]


async def test_dispatched_call_rejection_names_the_target_tool() -> None:
    """The bridge's own explanation (approver gave none) names the target tool."""
    bridge = sandbox_bridge_with_tool(
        AsyncMock(),
        [
            ApprovalPolicy(reject_approver(explanation=""), "read_file"),
            ApprovalPolicy(auto_approver(), "*"),
        ],
    )
    safe = ToolCall(id="2", function="bash", arguments={"cmd": "ls"})

    run = await run_bridge(
        [
            tool_calls_output(dispatched("1", {"path": "a.txt"})),
            tool_calls_output(safe),
        ],
        bridge=bridge,
    )

    (result,) = run.tool_results(1)
    assert result.error is not None
    assert "Tool call 'read_file' was rejected" in result.error.message


async def test_dispatched_call_modify_rewrites_the_nested_arguments() -> None:
    """The approver modifies the target's arguments; the scaffold gets a dispatcher call."""
    bridge = sandbox_bridge_with_tool(
        AsyncMock(),
        [ApprovalPolicy(modifying_approver({"path": "b.txt"}), "read_file")],
    )
    call = dispatched("1", {"path": "a.txt"})

    run = await run_bridge([tool_calls_output(call)], bridge=bridge)

    assert run.output.message.tool_calls == [dispatched("1", {"path": "b.txt"})]
    # the model's proposal is preserved for the transcript
    assert call.arguments["Arguments"] == {"path": "a.txt"}


@pytest.mark.parametrize(
    "arguments",
    [
        # target is not a bridged tool
        {"ServerName": "host", "ToolName": "write_file", "Arguments": {}},
        {"ServerName": "other", "ToolName": "read_file", "Arguments": {}},
        # not the dispatcher shape
        {"ServerName": "host", "ToolName": "read_file", "Arguments": "path=a"},
        {"ServerName": "host", "ToolName": ["read_file"], "Arguments": {}},
        {"ServerName": "host", "ToolName": "read_file"},
        {"server": "host", "tool": "read_file", "arguments": {}},
    ],
    ids=[
        "unknown-tool",
        "unknown-server",
        "args-not-object",
        "tool-not-string",
        "no-args",
        "other-keys",
    ],
)
async def test_call_that_dispatches_nothing_is_reviewed_as_itself(
    arguments: dict[str, object],
) -> None:
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    bridge = sandbox_bridge_with_tool(
        AsyncMock(), [ApprovalPolicy(recording_approver(seen), "*")]
    )
    call = ToolCall(id="1", function="call_mcp_tool", arguments=arguments)

    run = await run_bridge([tool_calls_output(call)], bridge=bridge)

    ((_, reviewed, _),) = seen
    assert reviewed is call
    assert run.output.message.tool_calls == [call]


@pytest.mark.parametrize(
    "function", ["bash", "read_file", "mcp__host__read_file", "host__read_file"]
)
async def test_only_the_dispatcher_function_is_unwrapped(function: str) -> None:
    """An ordinary call whose arguments carry the dispatcher fields is itself."""
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    bridge = sandbox_bridge_with_tool(
        AsyncMock(), [ApprovalPolicy(recording_approver(seen), "*")]
    )
    call = ToolCall(
        id="1",
        function=function,
        arguments={
            "cmd": "ls",
            "ServerName": "host",
            "ToolName": "read_file",
            "Arguments": {"path": "a.txt"},
        },
    )

    run = await run_bridge([tool_calls_output(call)], bridge=bridge)

    ((_, reviewed, _),) = seen
    assert reviewed is call
    assert run.output.message.tool_calls == [call]


async def test_dispatcher_shaped_arguments_do_not_borrow_another_tools_policy() -> None:
    """A rejected tool cannot be approved by naming a permitted one in its arguments."""
    bridge = sandbox_bridge_with_tool(
        AsyncMock(),
        [
            ApprovalPolicy(reject_approver(), "bash"),
            ApprovalPolicy(auto_approver(), "read_file"),
            ApprovalPolicy(auto_approver(), "*"),
        ],
    )
    decoy = ToolCall(
        id="1",
        function="bash",
        arguments={
            "cmd": "rm -rf /",
            "ServerName": "host",
            "ToolName": "read_file",
            "Arguments": {"path": "a.txt"},
        },
    )
    safe = ToolCall(id="2", function="ls", arguments={})

    run = await run_bridge(
        [tool_calls_output(decoy), tool_calls_output(safe)], bridge=bridge
    )

    assert run.generations == 2
    assert run.output.message.tool_calls == [safe]


async def test_in_process_bridge_does_not_unwrap_dispatcher_shaped_calls() -> None:
    """Without bridged tools there is nothing a call could dispatch to."""
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    call = dispatched("1", {"path": "a.txt"})

    await run_bridge(
        [tool_calls_output(call)],
        approval=[ApprovalPolicy(recording_approver(seen), "*")],
    )

    ((_, reviewed, _),) = seen
    assert reviewed is call


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


async def test_parsed_key_collision_raises_instead_of_approving() -> None:
    """An argument whose keys convert to one key is not matched on the lossy text."""
    tools = [
        ToolInfo(
            name="f",
            description="f",
            parameters=ToolParams(properties={"value": ToolParam(type="object")}),
        )
    ]
    call = parse_tool_call(
        "1", "f", '2024-01-01: blocked\n"2024-01-01": allowed', tools
    )
    assert call.parse_error is None
    with pytest.raises(ValueError, match="two object keys"):
        await run_bridge(
            [tool_calls_output(call)],
            approval=[
                ApprovalPolicy(
                    auto_approver(),
                    "f",
                    arguments={"value": '{"2024-01-01": "allowed"}'},
                ),
                ApprovalPolicy(reject_approver(), "*"),
            ],
        )


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


def sandbox_responses_bridge(
    tool: AsyncMock, outputs: list[ModelOutput]
) -> SandboxAgentBridge:
    """A sandbox bridge serving `host/read_file`, reached through the Responses dialect."""
    bridge = sandbox_bridge_with_tool(tool, None)
    bridge.model_aliases = {
        BRIDGE_MODEL: get_model("mockllm/model", custom_outputs=outputs)
    }
    return bridge


def discovered_read_file_namespace() -> dict[str, Any]:
    """`mcp__host` as a Codex `tool_search_output` lists it: served description and schema."""
    return {
        "type": "namespace",
        "name": "mcp__host",
        "description": "Tools from the host server.",
        "tools": [
            {
                "type": "function",
                "name": "read_file",
                "description": READ_FILE,
                "parameters": params("path").model_dump(exclude_none=True),
            }
        ],
    }


def responses_request_with_tool_search(
    discovered: list[Any],
) -> dict[str, Any]:
    """A Responses request whose top-level tools declare only `tool_search`."""
    return {
        "model": BRIDGE_MODEL,
        "tools": [{"type": "tool_search", "execution": "client"}],
        "input": [
            {"role": "user", "content": TASK},
            {
                "type": "tool_search_call",
                "id": "x1",
                "call_id": "ts_1",
                "arguments": {"query": "file tools"},
                "execution": "client",
                "status": "completed",
            },
            {
                "type": "tool_search_output",
                "call_id": "ts_1",
                "tools": discovered,
                "execution": "client",
                "status": "completed",
            },
        ],
    }


async def test_tool_discovered_through_tool_search_is_granted() -> None:
    """A Codex tool declared only inside a `tool_search_output` item is a declaration.

    The call comes back under its namespace as before, and the host service
    executes it once against the grant it minted.
    """
    tool = AsyncMock(return_value="contents")
    call = ToolCall(id="c1", function="read_file", arguments={"path": "notes.txt"})
    bridge = sandbox_responses_bridge(tool, [tool_calls_output(call)])

    response = await inspect_responses_api_request(
        responses_request_with_tool_search([discovered_read_file_namespace()]),
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    calls = [item for item in response.output if item.type == "function_call"]
    assert [(c.name, c.namespace) for c in calls] == [("read_file", "mcp__host")]
    execute = call_host_tool(bridge)
    assert await execute("host", "read_file", {"path": "notes.txt"}) == "contents"
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "notes.txt"})
    tool.assert_awaited_once_with(path="notes.txt")


def tool_search_result(messages: list[ChatMessage]) -> ChatMessageTool:
    """The `tool_search_output` item as the model sees it: a tool result carrying JSON."""
    (message,) = [
        m
        for m in messages
        if isinstance(m, ChatMessageTool) and m.function == TOOL_SEARCH_NAME
    ]
    return message


def with_tool_search_result(
    messages: list[ChatMessage], discovered: list[dict[str, Any]]
) -> list[ChatMessage]:
    """`messages` with the tool-search result replaced by one listing `discovered`.

    A copy, not an in-place edit: the request's own message objects must stay as
    the scaffold sent them, so a stale snapshot of them would not see the rewrite.
    """
    result = tool_search_result(messages)
    replacement = result.model_copy(update={"content": json.dumps(discovered)})
    return [replacement if m is result else m for m in messages]


def discovery_rewriting_filter(
    rewrite: Callable[[list[ChatMessage], list[ToolInfo]], GenerateInput],
) -> Callable[..., Awaitable[GenerateInput]]:
    async def filter(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> GenerateInput:
        rewritten = rewrite(list(input), list(tools))
        return GenerateInput(rewritten.input, rewritten.tools, tool_choice, config)

    return filter


async def request_with_rewritten_discovery(
    tool: AsyncMock,
    discovered: list[dict[str, Any]],
    rewrite: Callable[[list[ChatMessage], list[ToolInfo]], GenerateInput],
) -> SandboxAgentBridge:
    call = ToolCall(id="c1", function="read_file", arguments={"path": "notes.txt"})
    bridge = sandbox_responses_bridge(tool, [tool_calls_output(call)])
    bridge.filter = discovery_rewriting_filter(rewrite)
    await inspect_responses_api_request(
        responses_request_with_tool_search(discovered),
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )
    return bridge


async def test_discovery_removed_by_a_filter_does_not_grant() -> None:
    """The declarations are the ones the model saw, not the request's.

    The filter drops the discovery result and declares a local `read_file`
    instead; the model's call names that local tool, so `host/read_file` is not
    proposed.
    """
    tool = AsyncMock(return_value="contents")

    def remove_discovery(
        input: list[ChatMessage], tools: list[ToolInfo]
    ) -> GenerateInput:
        without = [m for m in input if m is not tool_search_result(input)]
        local = declare("read_file", description="Read a file inside the sandbox.")
        return GenerateInput(without, local, None, GenerateConfig())

    bridge = await request_with_rewritten_discovery(
        tool, [discovered_read_file_namespace()], remove_discovery
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})
    tool.assert_not_awaited()


async def test_discovery_description_rewritten_by_a_filter_does_not_grant() -> None:
    tool = AsyncMock(return_value="contents")

    def rewrite_description(
        input: list[ChatMessage], tools: list[ToolInfo]
    ) -> GenerateInput:
        namespace = discovered_read_file_namespace()
        namespace["tools"][0]["description"] = "Read a file inside the sandbox."
        return GenerateInput(
            with_tool_search_result(input, [namespace]), tools, None, GenerateConfig()
        )

    bridge = await request_with_rewritten_discovery(
        tool, [discovered_read_file_namespace()], rewrite_description
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})
    tool.assert_not_awaited()


async def test_discovery_added_by_a_filter_grants_once() -> None:
    """A declaration the filter put in front of the model counts, once."""
    tool = AsyncMock(return_value="contents")

    def add_discovery(input: list[ChatMessage], tools: list[ToolInfo]) -> GenerateInput:
        return GenerateInput(
            with_tool_search_result(input, [discovered_read_file_namespace()]),
            tools,
            None,
            GenerateConfig(),
        )

    bridge = await request_with_rewritten_discovery(tool, [], add_discovery)

    execute = call_host_tool(bridge)
    assert await execute("host", "read_file", {"path": "notes.txt"}) == "contents"
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "notes.txt"})
    tool.assert_awaited_once_with(path="notes.txt")


def responses_request_with_ordinary_tool_search_result(output: Any) -> dict[str, Any]:
    """A request whose ordinary function tool happens to be named `tool_search`.

    Its result replays as a `function_call_output`, not a native
    `tool_search_output`; the model's own `read_file` is a local tool.
    """
    return {
        "model": BRIDGE_MODEL,
        "tools": [
            {
                "type": "function",
                "name": TOOL_SEARCH_NAME,
                "description": "Search the notes.",
                "parameters": params("query").model_dump(exclude_none=True),
                "strict": False,
            },
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file inside the sandbox.",
                "parameters": params("path").model_dump(exclude_none=True),
                "strict": False,
            },
        ],
        "input": [
            {"role": "user", "content": TASK},
            {
                "type": "function_call",
                "id": "fc_notes",
                "call_id": "fc_notes_1",
                "name": TOOL_SEARCH_NAME,
                "arguments": json.dumps({"query": "file tools"}),
                "status": "completed",
            },
            {
                "type": "function_call_output",
                "call_id": "fc_notes_1",
                "output": json.dumps(output),
            },
        ],
    }


async def test_ordinary_result_from_a_tool_named_tool_search_declares_nothing() -> None:
    """Only a native tool-search result is discovery; an ordinary tool's output is not.

    The output carries the host tool's declaration, but the model's `read_file`
    is the local one, so `host/read_file` is not proposed.
    """
    tool = AsyncMock(return_value="contents")
    call = ToolCall(id="c1", function="read_file", arguments={"path": "notes.txt"})
    bridge = sandbox_responses_bridge(tool, [tool_calls_output(call)])

    await inspect_responses_api_request(
        responses_request_with_ordinary_tool_search_result(
            [discovered_read_file_namespace()]
        ),
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})
    tool.assert_not_awaited()


@pytest.mark.parametrize("sandbox", [True, False], ids=["sandbox", "in-process"])
async def test_ordinary_tool_search_result_of_strings_is_ignored(sandbox: bool) -> None:
    """An ordinary result that is not tool declarations must not break the request."""
    tool = AsyncMock(return_value="contents")
    call = ToolCall(id="c1", function="read_file", arguments={"path": "notes.txt"})
    outputs = [tool_calls_output(call)]
    bridge: AgentBridge = (
        sandbox_responses_bridge(tool, outputs)
        if sandbox
        else AgentBridge(
            AgentState(messages=[]),
            model_aliases={
                BRIDGE_MODEL: get_model("mockllm/model", custom_outputs=outputs)
            },
        )
    )

    response = await inspect_responses_api_request(
        responses_request_with_ordinary_tool_search_result(["note-one", "note-two"]),
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    assert [item.type for item in response.output] == ["message", "function_call"]
    if isinstance(bridge, SandboxAgentBridge):
        with pytest.raises(PermissionError, match="was not proposed by the model"):
            await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})
    tool.assert_not_awaited()


@pytest.mark.parametrize(
    "invalid_entry",
    [
        "note-one",
        7,
        {"type": "telepathy", "name": "read_minds"},
        {"type": "function", "name": "read_file"},
    ],
    ids=["string", "number", "unknown-type", "incomplete-function"],
)
async def test_native_discovery_the_encoder_rejects_declares_nothing(
    invalid_entry: Any,
) -> None:
    """Grants follow the wire: the encoder validates the list as a whole.

    One invalid entry makes the replayed `tool_search_output` carry no tools, so
    the model was told nothing about `host/read_file`; the valid entry beside it
    is not salvaged for grants and the call is denied.
    """
    discovered = [invalid_entry, discovered_read_file_namespace()]
    as_the_model_sees_it = ChatMessageTool(
        tool_call_id="ts_1", function=TOOL_SEARCH_NAME, content=json.dumps(discovered)
    )
    assert tool_search_output_tools(as_the_model_sees_it) == []

    tool = AsyncMock(return_value="contents")
    call = ToolCall(id="c1", function="read_file", arguments={"path": "notes.txt"})
    bridge = sandbox_responses_bridge(tool, [tool_calls_output(call)])

    await inspect_responses_api_request(
        responses_request_with_tool_search(discovered),
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})
    tool.assert_not_awaited()


async def test_undiscovered_and_undeclared_call_is_still_denied() -> None:
    """Without the `tool_search_output` declaration the call denotes nothing."""
    tool = AsyncMock(return_value="contents")
    call = ToolCall(id="c1", function="read_file", arguments={"path": "notes.txt"})
    bridge = sandbox_responses_bridge(tool, [tool_calls_output(call)])
    request = responses_request_with_tool_search([])

    await inspect_responses_api_request(
        request,
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})
    tool.assert_not_awaited()


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


# ---------------------------------------------------------------------------
# host tool events: every `call_tool` request is recorded as one `ToolEvent`
# ---------------------------------------------------------------------------


class RecordedTranscript:
    """A fresh sample transcript and every emission a subscriber saw."""

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.emissions: list[tuple[Event, bool | None]] = []
        transcript._subscribe(lambda e: self.emissions.append((e, e.pending)))

    @property
    def events(self) -> list[Event]:
        return list(self.transcript.events)

    @property
    def tool_events(self) -> list[ToolEvent]:
        return [e for e in self.events if isinstance(e, ToolEvent)]

    def completions(self, event: ToolEvent) -> int:
        """How many times `event` was published as no longer pending."""
        return sum(1 for e, pending in self.emissions if e is event and not pending)


@contextmanager
def recorded_transcript() -> Iterator[RecordedTranscript]:
    """A fresh transcript, and a fresh store so spans record no store changes."""
    transcript = Transcript()
    token = _transcript.set(transcript)
    store_token = _subtask_store.set(Store())
    try:
        yield RecordedTranscript(transcript)
    finally:
        _subtask_store.reset(store_token)
        _transcript.reset(token)


def bridge_metadata(event: ToolEvent) -> dict[str, Any]:
    assert event.metadata is not None
    metadata: dict[str, Any] = event.metadata["bridge"]
    return metadata


async def propose(
    bridge: SandboxAgentBridge, *calls: ToolCall, function: str = "read_file"
) -> None:
    """Run a bridged generation proposing `calls`, as the scaffold declared them."""
    await run_bridge(
        [tool_calls_output(*calls)], bridge=bridge, tools=declare(function)
    )


@pytest.mark.parametrize("approval", [True, False], ids=["policy", "no-policy"])
async def test_proposed_host_tool_call_is_recorded_with_the_proposing_id(
    approval: bool,
) -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(auto_approver("approve"), "*")] if approval else None
    )
    call = ToolCall(
        id="proposed",
        function="mcp__host__read_file",
        arguments={"path": "notes.txt", "mode": "r"},
    )

    with recorded_transcript() as recorded:
        await propose(bridge, call, function=call.function)
        result = await call_host_tool(bridge)(
            "host", "read_file", {"mode": "r", "path": "notes.txt"}
        )

    assert result == "contents"
    [event] = recorded.tool_events
    assert event.id == "proposed"
    assert event.function == "read_file"
    assert list(event.arguments.items()) == [("mode", "r"), ("path", "notes.txt")]
    assert event.result == "contents"
    assert event.error is None
    assert event.failed is None
    assert event.pending is None
    assert event.completed is not None
    assert event.working_time is not None
    assert event.truncated is None
    assert bridge_metadata(event) == {
        "server": "host",
        "tool": "read_file",
        "function": "mcp__host__read_file",
        "proposal_id": "proposed",
        "grant": "consumed",
    }
    assert recorded.completions(event) == 1


async def test_host_tool_event_has_the_native_span_layout() -> None:
    """The event sits beside its `tool` span, with the tool's own events inside it."""

    async def read(**kwargs: Any) -> str:
        transcript().info("reading")
        return "contents"

    bridge = sandbox_bridge_with_tool(AsyncMock(side_effect=read), None)
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            await propose(bridge, call)
            start = len(recorded.events)
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})
        events = recorded.events[start:]

    begin, event, info, end = events[:4]
    assert isinstance(begin, SpanBeginEvent) and begin.type == "tool"
    assert isinstance(event, ToolEvent)
    assert isinstance(info, InfoEvent)
    assert isinstance(end, SpanEndEvent) and end.id == begin.id
    assert event.span_id == outer
    assert begin.parent_id == outer
    assert info.span_id == begin.id


async def test_denied_host_tool_call_is_recorded_in_its_own_tool_span() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)

    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            with pytest.raises(PermissionError) as raised:
                await call_host_tool(bridge)("host", "read_file", {"path": "a"})
        # The denial's warn_once becomes a LoggerEvent only on the process's
        # first denial of host/read_file, and only once an earlier eval has
        # installed Inspect's log handler, so it depends on test order.
        events = [e for e in recorded.events if not isinstance(e, LoggerEvent)]

    assert str(raised.value) == (
        "Host tool call 'host/read_file' was not proposed by the model in a "
        "bridged generation (a bridged host tool runs once per proposed call)"
    )
    tool.assert_not_awaited()
    begin, event, end = events[1:4]
    assert isinstance(begin, SpanBeginEvent) and begin.type == "tool"
    assert begin.parent_id == outer
    assert isinstance(event, ToolEvent) and event.span_id == outer
    assert isinstance(end, SpanEndEvent) and end.id == begin.id
    assert event.id != "proposed"
    assert event.function == "read_file"
    assert event.arguments == {"path": "a"}
    assert event.error is not None
    assert event.error.type == "permission"
    assert event.error.message == str(raised.value)
    assert event.failed is None
    assert event.pending is None
    assert bridge_metadata(event)["grant"] == "denied"
    assert bridge_metadata(event)["function"] is None
    assert bridge_metadata(event)["proposal_id"] is None
    assert recorded.completions(event) == 1


class StampingSink:
    """A `ModelEventSink` that attributes generations to a sub-agent span.

    `script` names what each generation's sink calls do, in order: `stamp`
    places the event in `agent-sub` (as inspect_swe's sinks do in
    `on_pending`), `current` leaves it in the current span, `open` emits the
    span's begin in `on_complete`, and `close` emits its end in `on_pending`
    (the codex_cli lifecycle).
    """

    def __init__(self, *script: set[str]) -> None:
        self.script = list(script)
        self.actions: set[str] = set()
        self.opened = False

    def on_pending(self, event: ModelEvent) -> None:
        self.actions = self.script.pop(0)
        if "close" in self.actions:
            transcript()._event(SpanEndEvent(id="agent-sub"))
        if "stamp" in self.actions:
            event.span_id = "agent-sub"

    def on_complete(self, event: ModelEvent) -> None:
        transcript()._event(event)
        if "open" in self.actions:
            self.opened = True
            transcript()._event(
                SpanBeginEvent(
                    id="agent-sub",
                    parent_id=current_span_id(),
                    type="agent",
                    name="sub",
                )
            )


class StartingStampingSink(StampingSink):
    """As `StampingSink`, but the script runs once per generation, in `on_start`.

    `stamp` names `agent-sub` as the span the generation runs under, as
    inspect_swe's sinks do with `on_start` (beginning it first if no `open`
    has), and `close` emits the span's end there (the per-generation
    bookkeeping codex_cli does). `current` leaves the generation in the
    current span by returning `None`.
    """

    def on_start(self, input: list[ChatMessage]) -> str | None:
        self.actions = self.script.pop(0)
        if "close" in self.actions:
            transcript()._event(SpanEndEvent(id="agent-sub"))
        if "stamp" in self.actions:
            if not self.opened:
                self.opened = True
                transcript()._event(
                    SpanBeginEvent(
                        id="agent-sub",
                        parent_id=current_span_id(),
                        type="agent",
                        name="sub",
                    )
                )
            return "agent-sub"
        return self.current()

    def current(self) -> str | None:
        return None

    def on_pending(self, event: ModelEvent) -> None:
        pass


class CurrentStartingSink(StartingStampingSink):
    """As `StartingStampingSink`, but `current` names the current span explicitly.

    inspect_swe's sinks attribute a main-thread call to `current_span_id()`.
    """

    def current(self) -> str | None:
        return current_span_id()


SINKS = {
    "on-pending": StampingSink,
    "on-start": StartingStampingSink,
    "on-start-current": CurrentStartingSink,
}


def sandbox_bridge_with_sink(tool: AsyncMock, sink: StampingSink) -> SandboxAgentBridge:
    bridge = sandbox_bridge_with_tool(tool, None)
    bridge.model_event_sink = sink
    return bridge


@pytest.mark.parametrize("sink", SINKS)
async def test_execution_is_placed_in_the_span_a_sink_gave_its_proposal(
    sink: str,
) -> None:
    bridge = sandbox_bridge_with_sink(
        AsyncMock(return_value="contents"), SINKS[sink]({"stamp"})
    )
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        async with span("outer"):
            await propose(bridge, call)
            assert bridge._tool_execution_grants[0].proposal.span_id == "agent-sub"
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [event] = recorded.tool_events
    assert event.span_id == "agent-sub"
    [tool_span] = [
        e for e in recorded.events if isinstance(e, SpanBeginEvent) and e.type == "tool"
    ]
    assert tool_span.parent_id == "agent-sub"


class MovesBackSink(StartingStampingSink):
    """Runs the generation under `agent-sub`, then moves its event back to the span current at `on_start`."""

    def on_start(self, input: list[ChatMessage]) -> str | None:
        self.started_in = current_span_id()
        return super().on_start(input)

    def on_pending(self, event: ModelEvent) -> None:
        event.span_id = self.started_in


class MovingStartingSink(StartingStampingSink):
    """Runs the generation under `agent-sub`, then moves its event to `agent-other`."""

    def on_pending(self, event: ModelEvent) -> None:
        event.span_id = "agent-other"


async def test_execution_follows_an_on_start_sink_s_later_move_of_its_proposal() -> (
    None
):
    """The grant carries the span the proposing event is logged in."""
    bridge = sandbox_bridge_with_sink(
        AsyncMock(return_value="contents"), MovingStartingSink({"stamp"})
    )
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        async with span("outer"):
            await propose(bridge, call)
            assert bridge._tool_execution_grants[0].proposal.span_id == "agent-other"
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [model_event] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert model_event.span_id == "agent-other"
    [event] = recorded.tool_events
    assert event.span_id == "agent-other"


async def test_a_sink_without_on_start_is_wrapped_without_one() -> None:
    """The bridge runs such a sink's generation as before: no span lookup at all."""
    from inspect_ai.agent._bridge.util import _span_capturing_sink
    from inspect_ai.model._model import _StartingModelEventSink

    assert not isinstance(_span_capturing_sink(StampingSink()), _StartingModelEventSink)
    assert isinstance(
        _span_capturing_sink(StartingStampingSink()), _StartingModelEventSink
    )
    bridge = sandbox_bridge_with_sink(
        AsyncMock(return_value="contents"), StampingSink({"current"})
    )
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})
    with recorded_transcript() as recorded:
        # a current span this transcript has no begin for
        with parent_span("elsewhere"):
            await propose(bridge, call)
    [model_event] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert model_event.span_id == "elsewhere"


@pytest.mark.parametrize("sink", SINKS)
async def test_sink_attributing_to_the_current_span_stores_none(sink: str) -> None:
    """The span current at execution is followed (a checkpoint span may rotate)."""
    bridge = sandbox_bridge_with_sink(
        AsyncMock(return_value="contents"), SINKS[sink]({"current"})
    )
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        async with span("proposed in"):
            await propose(bridge, call)
        assert bridge._tool_execution_grants[0].proposal.span_id is None
        async with span("executed in"):
            executed_in = current_span_id()
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [event] = recorded.tool_events
    assert event.span_id == executed_in


@approver(name="test_bridge_pausing")
def pausing_approver(approving: anyio.Event, resume: anyio.Event) -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        approving.set()
        await resume.wait()
        return Approval(decision="approve")

    return approve


@pytest.mark.parametrize("sink", [*SINKS, "on-start-moves-back", None])
async def test_a_checkpoint_rotating_during_approval_is_followed(
    sink: str | None,
) -> None:
    """A rotation while the call awaits approval is not taken for a sink's own span."""
    approving, rotated = anyio.Event(), anyio.Event()
    bridge = sandbox_bridge_with_tool(
        AsyncMock(return_value="contents"),
        [ApprovalPolicy(pausing_approver(approving, rotated), "*")],
    )
    if sink == "on-start-moves-back":
        bridge.model_event_sink = MovesBackSink({"stamp"})
    elif sink is not None:
        bridge.model_event_sink = SINKS[sink]({"current"})
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})
    checkpoints = SpanRotationScope(type="checkpoint")

    async def rotate() -> None:
        await approving.wait()
        await checkpoints.end_span()
        await checkpoints.begin_span("checkpoint 2")
        rotated.set()

    with recorded_transcript() as recorded:
        await checkpoints.open("checkpoint 1")
        first = current_span_id()
        async with anyio.create_task_group() as tg:
            tg.start_soon(rotate)
            await propose(bridge, call)
        second = current_span_id()
        assert second is not None and second != first
        assert bridge._tool_execution_grants[0].proposal.span_id is None
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})
        await checkpoints.close()

    [model_event] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert model_event.span_id == first
    [event] = recorded.tool_events
    assert event.span_id == second


@pytest.mark.parametrize("sink", SINKS)
async def test_execution_after_its_proposal_span_closed_still_nests_under_it(
    sink: str,
) -> None:
    """codex_cli closes a sub-agent span in a later generation's `on_pending` (or `on_start`)."""
    bridge = sandbox_bridge_with_sink(
        AsyncMock(return_value="contents"),
        SINKS[sink]({"open"}, {"stamp"}, {"close"}),
    )
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        await run_bridge(
            [ModelOutput.from_content("mockllm/model", "spawn")], bridge=bridge
        )
        await propose(bridge, call)
        await run_bridge(
            [ModelOutput.from_content("mockllm/model", "done")], bridge=bridge
        )
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    events = recorded.events
    [event] = recorded.tool_events
    [span_end] = [e for e in events if isinstance(e, SpanEndEvent)][:1]
    assert span_end.id == "agent-sub"
    assert events.index(span_end) < events.index(event)
    assert event.span_id == "agent-sub"
    [sub] = [
        node
        for node in event_tree(events)
        if isinstance(node, EventTreeSpan) and node.id == "agent-sub"
    ]
    assert event in sub.children


class RecordingAcpTransport(LiveAcpTransport):
    """An ACP transport that keeps the session notifications it publishes."""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[SessionNotification] = []

    def publish(self, update: AcpUpdate) -> None:
        if isinstance(update, SessionNotification):
            self.published.append(update)


@pytest.mark.parametrize("sink", SINKS)
@pytest.mark.parametrize("filtered", [True, False], ids=["filtered", "unfiltered"])
async def test_acp_keeps_a_closed_sub_agent_spans_host_call_out_of_the_conversation(
    filtered: bool, sink: str
) -> None:
    """ACP filters the late execution by its attributed span, live and on replay."""
    bridge = sandbox_bridge_with_sink(
        AsyncMock(return_value="contents"),
        SINKS[sink]({"open"}, {"stamp"}, {"close"}),
    )
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        session = RecordingAcpTransport()
        session._attachable_override = True
        session._filter_subagent_events = filtered
        published = session.published
        _AcpEventRouter(session).attach()
        async with span("main", type="agent"):
            await run_bridge(
                [ModelOutput.from_content("mockllm/model", "spawn")], bridge=bridge
            )
            await propose(bridge, call)
            await run_bridge(
                [ModelOutput.from_content("mockllm/model", "done")], bridge=bridge
            )
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})
        replayed = list(
            replay_transcript(recorded.events, "s", filter_subagents=filtered)
        )

    def cards(notifications: list[SessionNotification]) -> list[str]:
        return [
            n.update.tool_call_id
            for n in notifications
            if isinstance(n.update, (ToolCallStart, ToolCallProgress))
        ]

    for notifications in (published, replayed):
        if filtered:
            assert cards(notifications) == []
        else:
            assert "proposed" in cards(notifications)


async def test_opted_out_server_pairs_a_proposed_call() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        await propose(bridge, call)
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})
        await call_host_tool(bridge)("host", "read_file", {"path": "b"})

    paired, unproposed = recorded.tool_events
    assert paired.id == "proposed"
    assert bridge_metadata(paired)["grant"] == "consumed"
    assert unproposed.id not in ("proposed", paired.id)
    assert unproposed.error is None
    assert unproposed.result == "contents"
    assert bridge_metadata(unproposed)["grant"] == "exempt"
    assert bridge_metadata(unproposed)["proposal_id"] is None


async def test_opted_out_server_pairs_the_first_matching_call() -> None:
    """A documented limitation: matching is by arguments, first come first served.

    An unproposed call (e.g. from model-written code) with the same arguments
    as a pending proposal takes its id; the proposed call then runs exempt.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        await propose(bridge, call)
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    assert tool.await_count == 2
    first, second = recorded.tool_events
    assert first.id == "proposed"
    assert bridge_metadata(first)["grant"] == "consumed"
    assert bridge_metadata(first)["proposal_id"] == "proposed"
    assert second.id != "proposed"
    assert second.error is None
    assert bridge_metadata(second)["grant"] == "exempt"
    assert bridge_metadata(second)["proposal_id"] is None


@tool
def sized_output() -> Tool:
    async def execute(size: int) -> ToolResult:
        """Return `size` bytes of text (as content when `size` is negative).

        Args:
            size: Number of bytes to return.
        """
        if size < 0:
            return [ContentText(text="x" * -size)]
        return "x" * size

    return execute


def sized_output_bridge(max_output: int | None = None) -> SandboxAgentBridge:
    tool = sized_output()
    if max_output is not None:
        tool = ToolDef(tool, max_output=max_output).as_tool()
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        bridged_tools={"host": {"sized_output": tool}},
        proposal_exempt_servers={"host"},
    )


@pytest.mark.parametrize(
    "max_tool_output,max_output,limit",
    [(None, None, 16 * 1024), (1024, None, 1024), (None, 64, 64)],
    ids=["default", "max_tool_output", "max_output"],
)
async def test_truncated_result_is_recorded_as_delivered(
    max_tool_output: int | None, max_output: int | None, limit: int
) -> None:
    bridge = sized_output_bridge(max_output)
    token = active_generate_config_context_var.set(
        GenerateConfig(max_tool_output=max_tool_output)
    )
    try:
        with recorded_transcript() as recorded:
            result = await call_host_tool(bridge)(
                "host", "sized_output", {"size": 20 * 1024}
            )
    finally:
        active_generate_config_context_var.reset(token)

    assert isinstance(result, str)
    assert result.startswith("\nThe output of your call to sized_output was too long")
    [event] = recorded.tool_events
    assert event.result == result
    assert event.truncated == (20 * 1024, limit)


async def test_content_result_is_recorded_whole() -> None:
    bridge = sized_output_bridge(64)

    with recorded_transcript() as recorded:
        await call_host_tool(bridge)("host", "sized_output", {"size": -20 * 1024})

    [event] = recorded.tool_events
    assert event.result == [ContentText(text="x" * 20 * 1024)]
    assert event.truncated is None


async def test_unknown_server_is_recorded_as_a_parsing_error() -> None:
    bridge = sandbox_bridge_with_tool(AsyncMock(), None)

    with recorded_transcript() as recorded:
        with pytest.raises(ValueError) as raised:
            await call_host_tool(bridge)("nowhere", "read_file", {"path": "a"})

    assert str(raised.value) == "Unknown bridged tools server: nowhere"
    [event] = recorded.tool_events
    assert event.function == "read_file"
    assert event.arguments == {"path": "a"}
    assert event.error == ToolCallError("parsing", str(raised.value))
    assert bridge_metadata(event) == {
        "server": "nowhere",
        "tool": "read_file",
        "function": None,
        "proposal_id": None,
        "grant": None,
    }


async def test_unknown_tool_is_recorded_as_a_parsing_error() -> None:
    bridge = sandbox_bridge_with_tool(AsyncMock(), None)

    with recorded_transcript() as recorded:
        with pytest.raises(ValueError) as raised:
            await call_host_tool(bridge)("host", "write_file", {"path": "a"})

    assert str(raised.value) == "Unknown tool 'write_file' in server 'host'"
    [event] = recorded.tool_events
    assert event.function == "write_file"
    assert event.error == ToolCallError("parsing", str(raised.value))


def nested(depth: int) -> dict[str, Any]:
    """An object `depth` containers deep (counting itself)."""
    value: dict[str, Any] = {}
    for _ in range(depth - 1):
        value = {"v": value}
    return value


@pytest.mark.parametrize("depth,executes", [(101, False), (100, True)])
async def test_arguments_deeper_than_the_native_bound_are_rejected(
    depth: int, executes: bool
) -> None:
    received: list[Any] = []

    async def echo(**arguments: Any) -> str:
        received.append(arguments)
        return "ok"

    echo_tool = ToolDef(
        echo,
        name="echo",
        description="Echo.",
        parameters=ToolParams(
            properties={"v": ToolParam(type="object", description="Value.")}
        ),
    ).as_tool()
    bridge = sandbox_bridge_with_servers({"host": {"echo": echo_tool}})
    bridge.proposal_exempt_servers.add("host")
    arguments = nested(depth)

    with recorded_transcript() as recorded:
        if executes:
            assert await call_host_tool(bridge)("host", "echo", arguments) == "ok"
        else:
            with pytest.raises(ToolParsingError, match="maximum supported nesting"):
                await call_host_tool(bridge)("host", "echo", arguments)

    [event] = recorded.tool_events
    assert len(received) == (1 if executes else 0)
    if executes:
        assert event.error is None
        assert event.arguments == arguments
    else:
        assert event.error is not None
        assert event.error.type == "parsing"
        assert "maximum supported nesting depth of 100" in event.error.message
        assert event.arguments == {}
        assert bridge_metadata(event)["grant"] is None


async def test_arguments_failing_validation_are_recorded_as_sent() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)

    with recorded_transcript() as recorded:
        with pytest.raises(ToolParsingError) as raised:
            await call_host_tool(bridge)("host", "read_file", {"offset": "three"})

    tool.assert_not_awaited()
    [event] = recorded.tool_events
    assert event.arguments == {"offset": "three"}
    assert event.error == ToolCallError("parsing", raised.value.message)
    assert bridge_metadata(event)["grant"] == "exempt"


async def test_proposed_call_failing_validation_pairs_with_its_proposal() -> None:
    """The grant is consumed before validation, as for an execution."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(id="proposed", function="read_file", arguments={"offset": "x"})

    with recorded_transcript() as recorded:
        await propose(bridge, call)
        with pytest.raises(ToolParsingError):
            await call_host_tool(bridge)("host", "read_file", {"offset": "x"})

    tool.assert_not_awaited()
    [event] = recorded.tool_events
    assert event.id == "proposed"
    assert event.error is not None and event.error.type == "parsing"
    assert bridge_metadata(event)["grant"] == "consumed"


async def test_non_object_arguments_are_recorded_as_empty() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)

    with recorded_transcript() as recorded:
        with pytest.raises(ValueError, match="Unknown bridged tools server"):
            await call_host_tool(bridge)("nowhere", "read_file", ["a"])
        with pytest.raises(ToolParsingError, match="is not of type 'object'"):
            await call_host_tool(bridge)("host", "read_file", ["a"])

    tool.assert_not_awaited()
    unknown, invalid = recorded.tool_events
    assert unknown.arguments == {}
    assert unknown.error is not None and "Unknown bridged" in unknown.error.message
    assert invalid.arguments == {}
    assert invalid.error is not None
    assert "is not of type 'object'" in invalid.error.message


async def test_non_object_arguments_on_a_server_requiring_proposals_are_denied() -> (
    None
):
    """Grants bind objects, so nothing matches; the denial is recorded as usual."""
    bridge = sandbox_bridge_with_tool(AsyncMock(), None)

    with recorded_transcript() as recorded:
        with pytest.raises(PermissionError):
            await call_host_tool(bridge)("host", "read_file", ["a"])

    [event] = recorded.tool_events
    assert event.arguments == {}
    assert bridge_metadata(event)["grant"] == "denied"


async def test_identical_proposals_pair_in_proposal_order() -> None:
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    first = ToolCall(id="a", function="read_file", arguments={"path": "x"})
    second = ToolCall(id="b", function="read_file", arguments={"path": "x"})

    with recorded_transcript() as recorded:
        await propose(bridge, first, second)
        execute = call_host_tool(bridge)
        await execute("host", "read_file", {"path": "x"})
        await execute("host", "read_file", {"path": "x"})

    assert [e.id for e in recorded.tool_events] == ["a", "b"]


async def test_proposal_executed_on_two_indistinct_tools_takes_its_id_once() -> None:
    """The second execution of one proposal gets a fresh id but names the proposal.

    The tools' schemas differ, which resolution ignores (only the served
    description counts).
    """

    async def read(**kwargs: Any) -> str:
        return "b"

    with_encoding = ToolParams(
        properties={
            "path": ToolParam(type="string", description="path"),
            "encoding": ToolParam(type="string", description="encoding"),
        },
        required=["path"],
    )
    bridge = sandbox_bridge_with_servers(
        {
            "a": {"read_file": served_tool(AsyncMock(return_value="a"))},
            "b": {
                "read_file": ToolDef(
                    read,
                    name="read_file",
                    description=READ_FILE,
                    parameters=with_encoding,
                ).as_tool()
            },
        }
    )
    call = ToolCall(id="p", function="read_file", arguments={"path": "x"})

    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            await propose(bridge, call)
            await call_host_tool(bridge)("a", "read_file", {"path": "x"})
            await call_host_tool(bridge)("b", "read_file", {"path": "x"})

    first, second = recorded.tool_events
    assert first.id == "p"
    assert second.id != "p"
    for event in (first, second):
        assert bridge_metadata(event)["proposal_id"] == "p"
        assert bridge_metadata(event)["grant"] == "consumed"
        assert event.span_id == outer


async def test_tool_discovered_through_tool_search_pairs_its_execution() -> None:
    tool = AsyncMock(return_value="contents")
    call = ToolCall(id="c1", function="read_file", arguments={"path": "notes.txt"})
    bridge = sandbox_responses_bridge(tool, [tool_calls_output(call)])

    with recorded_transcript() as recorded:
        await inspect_responses_api_request(
            responses_request_with_tool_search([discovered_read_file_namespace()]),
            None,
            internal_web_search_providers(),
            default_code_execution_providers(),
            bridge,
        )
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})

    [event] = recorded.tool_events
    assert event.id == "c1"
    assert bridge_metadata(event)["function"] == "read_file"
    assert bridge_metadata(event)["grant"] == "consumed"


async def test_call_naming_a_bridged_tool_in_its_arguments_is_recorded_denied() -> None:
    tool = AsyncMock(return_value="secret")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(
        id="proposed",
        function="bash",
        arguments={
            "cmd": "ls",
            "ServerName": "host",
            "ToolName": "read_file",
            "Arguments": {"path": "/secret"},
        },
    )

    with recorded_transcript() as recorded:
        await run_bridge(
            [tool_calls_output(call)],
            bridge=bridge,
            tools=declare(
                "bash", description="Run a shell command.", parameters=("cmd",)
            ),
        )
        with pytest.raises(PermissionError):
            await call_host_tool(bridge)("host", "read_file", {"path": "/secret"})

    [event] = recorded.tool_events
    assert event.id != "proposed"
    assert bridge_metadata(event)["grant"] == "denied"


def container_sizes(bridge: SandboxAgentBridge) -> dict[str, int]:
    return {
        name: len(value)
        for name, value in vars(bridge).items()
        if isinstance(value, (list, dict, set, deque))
    }


async def test_pairing_state_does_not_grow_with_executions() -> None:
    """No per-proposal state outlives its grants, over more proposals than the store holds."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    sizes = container_sizes(bridge)
    execute = call_host_tool(bridge)
    count = _MAX_TOOL_EXECUTION_GRANTS + 76

    with recorded_transcript() as recorded:
        for index in range(count):
            bridge.register_tool_execution_grants(
                [
                    ToolCall(
                        # ids recur, as a later proposal may reuse an earlier id
                        id=f"c{index % 3}",
                        function="read_file",
                        arguments={"path": str(index)},
                    )
                ],
                declare("read_file"),
            )
            await execute("host", "read_file", {"path": str(index)})
            assert container_sizes(bridge) == sizes

    assert [e.id for e in recorded.tool_events] == [
        f"c{index % 3}" for index in range(count)
    ]


async def test_reused_call_id_pairs_again() -> None:
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    call = ToolCall(id="same", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        for _ in range(2):
            await propose(bridge, call)
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    assert [e.id for e in recorded.tool_events] == ["same", "same"]


async def test_large_arguments_on_a_denied_call_are_condensed() -> None:
    bridge = sandbox_bridge_with_tool(AsyncMock(), None)
    path = "x" * (1024 * 1024)

    with recorded_transcript() as recorded:
        with pytest.raises(PermissionError):
            await call_host_tool(bridge)("host", "read_file", {"path": path})

    [event] = recorded.tool_events
    assert event.arguments == {"path": path}
    sample = EvalSample(
        id="sample", epoch=1, input="input", target="target", events=[event]
    )
    condensed = condense_sample(sample)
    [condensed_event] = [e for e in condensed.events if isinstance(e, ToolEvent)]
    reference = condensed_event.arguments["path"]
    assert isinstance(reference, str) and reference.startswith("attachment://")
    assert condensed.attachments[reference.removeprefix("attachment://")] == path


async def run_failing(
    error: BaseException | Callable[..., Awaitable[str]],
) -> tuple[SandboxAgentBridge, ToolEvent, BaseException]:
    """Execute an exempt host call whose tool raises `error`; the event and what was raised."""
    mock = AsyncMock(side_effect=error)
    bridge = sandbox_bridge_with_tool(mock, None, require_proposal=False)
    with recorded_transcript() as recorded:
        try:
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})
        except BaseException as ex:
            raised = ex
        else:
            raise AssertionError("the host call did not raise")
    [event] = recorded.tool_events
    assert recorded.completions(event) == 1
    return bridge, event, raised


@pytest.mark.parametrize(
    "error,expected",
    [
        (ToolError("tool says no"), ToolCallError("unknown", "tool says no")),
        (
            PermissionError("not allowed"),
            ToolCallError("permission", "not allowed."),
        ),
        (
            TimeoutError("tool-specific timeout"),
            ToolCallError("timeout", "Command timed out before completing."),
        ),
        (
            LimitExceededError("token", value=2, limit=1),
            ToolCallError("limit", "The tool exceeded its token limit of 1."),
        ),
    ],
    ids=lambda v: type(v).__name__,
)
async def test_mapped_tool_exception_is_recorded_and_propagates_unchanged(
    error: Exception, expected: ToolCallError
) -> None:
    bridge, event, raised = await run_failing(error)

    assert raised is error
    assert event.error == expected
    assert event.failed is None
    assert event.result == ""
    assert not bridge._failure_requested.is_set()


async def test_sandbox_timeout_records_its_truncated_output() -> None:
    error = SandboxTimeoutError("sandbox timeout", truncated_output="partial")

    _, event, raised = await run_failing(error)

    assert raised is error
    assert str(raised) == "sandbox timeout"
    assert event.error is not None and event.error.type == "timeout"
    assert event.result == "partial"


@pytest.mark.parametrize("require_proposal", [True, False], ids=["required", "exempt"])
async def test_a_schema_that_cannot_be_checked_fails_the_sample_and_is_recorded(
    require_proposal: bool,
) -> None:
    """An error checking the arguments is a programming error, as in the tool body."""
    mock = AsyncMock(return_value="contents")

    async def execute(**kwargs: Any) -> str:
        return await mock(**kwargs)

    invalid_pattern = ToolParams(
        properties={"path": ToolParam(type="string", description="path", pattern="[")},
        required=["path"],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        bridged_tools={
            "host": {
                "read_file": ToolDef(
                    execute,
                    name="read_file",
                    description=READ_FILE,
                    parameters=invalid_pattern,
                ).as_tool()
            }
        },
        proposal_exempt_servers=set() if require_proposal else {"host"},
    )
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})

    with recorded_transcript() as recorded:
        if require_proposal:
            await propose(bridge, call)
        with pytest.raises(re.error) as raised:
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    mock.assert_not_awaited()
    assert bridge._failure is raised.value
    [event] = recorded.tool_events
    assert recorded.completions(event) == 1
    assert event.failed is True
    assert event.error is None
    assert event.arguments == {"path": "a"}
    if require_proposal:
        assert event.id == "proposed"
        assert bridge_metadata(event)["grant"] == "consumed"
        assert bridge_metadata(event)["proposal_id"] == "proposed"
    else:
        assert bridge_metadata(event)["grant"] == "exempt"


async def test_tool_error_from_a_task_group_is_classified_unwrapped() -> None:
    async def raise_in_group(**kwargs: Any) -> str:
        async def child() -> None:
            raise ToolError("recoverable")

        async with anyio.create_task_group() as tg:
            tg.start_soon(child)
        return "unreachable"

    bridge, event, raised = await run_failing(raise_in_group)

    assert isinstance(raised, ExceptionGroup)
    assert event.error == ToolCallError("unknown", "recoverable")
    assert not bridge._failure_requested.is_set()


async def read_a(bridge: SandboxAgentBridge) -> None:
    await call_host_tool(bridge)("host", "read_file", {"path": "a"})


def blocking_tool() -> tuple[AsyncMock, anyio.Event, anyio.Event]:
    """A tool mock that signals `started` and then waits for `release`."""
    started = anyio.Event()
    release = anyio.Event()

    async def block(**kwargs: Any) -> str:
        started.set()
        await release.wait()
        return "released"

    return AsyncMock(side_effect=block), started, release


PNG = "data:image/png;base64,iVBORw0KGgo="


class ChildRaises(NamedTuple):
    """A tool whose task group child raises `error` when it is cancelled."""

    error: Exception


async def run_child_raising(error: Exception, started: anyio.Event) -> None:
    """Wait in a task group whose child raises `error` when cancelled."""
    child_started = anyio.Event()

    async def child() -> None:
        child_started.set()
        try:
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            raise error from None

    async with anyio.create_task_group() as tg:
        tg.start_soon(child)
        await child_started.wait()
        started.set()
        await anyio.sleep_forever()


# how each ending is produced: what the tool does (or None for the span-ID
# provider endings) and what interrupts the call once it has started
ENDINGS: dict[str, tuple[Any, Literal["operator", "outer"] | None]] = {
    "text": ("contents", None),
    "content": ([ContentText(text="contents")], None),
    "image": (ContentImage(image=PNG), None),
    "structured": ({"a": 1}, None),
    # 255 levels pass ContentText validation but not serialization
    "content-unserializable": (ContentText(text="x", internal=nested(255)), None),
    "structured-unserializable": (nested(301), None),
    "mapped-error": (ToolError("tool says no"), None),
    "unexpected-error": (KeyError("missing"), None),
    "operator-cancel-propagates": ("propagates", "operator"),
    "operator-cancel-returns": (None, "operator"),
    "operator-cancel-raises": (RuntimeError("cleanup failed"), "operator"),
    "operator-cancel-raises-group": (
        ExceptionGroup("cleanup", [RuntimeError("cleanup failed")]),
        "operator",
    ),
    # a task group child that raises while being cancelled (Trio then raises
    # a group mixing that error with the cancellation)
    "operator-cancel-child-raises": (
        ChildRaises(RuntimeError("cleanup failed")),
        "operator",
    ),
    "operator-cancel-child-raises-tool-error": (
        ChildRaises(ToolError("cleanup failed")),
        "operator",
    ),
    "operator-cancel-raises-tool-error": (ToolError("cleanup failed"), "operator"),
    "outer-cancel": ("propagates", "outer"),
    "span-allocation-fails": (None, None),
    "span-allocation-cancelled": (None, "outer"),
}

# what the scaffold gets ("result", "error" or "cancelled"), the recorded
# error type, and whether the sample fails
EXPECTED: dict[str, tuple[str, str | None, bool]] = {
    "text": ("result", None, False),
    "content": ("result", None, False),
    "image": ("result", None, False),
    "structured": ("result", None, False),
    "content-unserializable": ("error", None, True),
    "structured-unserializable": ("error", None, True),
    "mapped-error": ("error", "unknown", False),
    "unexpected-error": ("error", None, True),
    "operator-cancel-propagates": ("error", "timeout", False),
    "operator-cancel-returns": ("error", "timeout", False),
    "operator-cancel-raises": ("error", "timeout", False),
    "operator-cancel-raises-group": ("error", "timeout", False),
    "operator-cancel-child-raises": ("error", "timeout", False),
    "operator-cancel-child-raises-tool-error": ("error", "timeout", False),
    "operator-cancel-raises-tool-error": ("error", "timeout", False),
    "outer-cancel": ("cancelled", "cancelled", False),
    "span-allocation-fails": ("error", None, True),
    "span-allocation-cancelled": ("cancelled", "cancelled", False),
}


@pytest.mark.parametrize("require_proposal", [True, False], ids=["required", "exempt"])
@pytest.mark.parametrize("ending", list(ENDINGS))
async def test_every_ending_records_one_event_matching_the_reply(
    ending: str, require_proposal: bool
) -> None:
    """However a host call ends, one terminal event records what the scaffold got."""
    behaviour, interrupt = ENDINGS[ending]
    rpc, error_type, fatal = EXPECTED[ending]
    started = anyio.Event()

    async def run_tool(**kwargs: Any) -> Any:
        if isinstance(behaviour, ChildRaises):
            await run_child_raising(behaviour.error, started)
        started.set()
        if interrupt is not None:
            try:
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                if behaviour == "propagates":
                    raise
        if isinstance(behaviour, BaseException):
            raise behaviour
        return behaviour

    async def provider(
        name: str, parent_id: str | None, requested_id: str | None
    ) -> str:
        started.set()
        if interrupt is None:
            raise RuntimeError("no span id")
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    tool = AsyncMock(side_effect=run_tool)
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=require_proposal)
    returned: list[JsonValue] = []
    raised: list[Exception] = []

    async def call() -> None:
        try:
            returned.append(
                await call_host_tool(bridge)("host", "read_file", {"path": "a"})
            )
        except Exception as ex:
            raised.append(ex)

    with recorded_transcript() as recorded:
        if require_proposal:
            await propose(
                bridge,
                ToolCall(id="proposed", function="read_file", arguments={"path": "a"}),
            )
        allocating = ending.startswith("span-allocation")
        with span_id_provider(provider if allocating else None):
            async with anyio.create_task_group() as tg:
                tg.start_soon(call)
                if interrupt is not None:
                    await started.wait()
                    if interrupt == "operator":
                        [running] = recorded.tool_events
                        running._cancel()
                    else:
                        tg.cancel_scope.cancel()

    [event] = recorded.tool_events
    assert recorded.completions(event) == 1
    assert event.pending is None
    assert len(returned) == (rpc == "result")
    assert len(raised) == (rpc == "error")
    assert (event.error.type if event.error else None) == error_type
    assert (event.failed is True) == fatal
    assert bridge._failure_requested.is_set() == fatal
    if fatal:
        assert bridge._failure is raised[0]
    if rpc == "error" and not fatal:
        assert event.error is not None
    if error_type == "timeout":
        assert isinstance(raised[0], ToolError)
        assert raised[0].message == "Command timed out before completing."
    if require_proposal:
        assert event.id == "proposed"
        assert bridge_metadata(event)["grant"] == "consumed"
    else:
        assert bridge_metadata(event)["grant"] == "exempt"


async def test_execution_observer_tracks_the_running_call() -> None:
    mock, started, release = blocking_tool()
    bridge = sandbox_bridge_with_tool(mock, None)
    call = ToolCall(id="proposed", function="read_file", arguments={"path": "a"})
    tracked: list[tuple[str, ToolEvent | None]] = []

    class Observer:
        @contextmanager
        def track_tool_call(
            self, tool_call_id: str, event: ToolEvent | None = None
        ) -> Iterator[None]:
            tracked.append((tool_call_id, event))
            yield

    sample = MagicMock()
    sample.execution_observer = Observer()
    with recorded_transcript() as recorded:
        await propose(bridge, call)
        token = _sample_active.set(sample)
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(read_a, bridge)
                await started.wait()
                release.set()
        finally:
            _sample_active.reset(token)

    [event] = recorded.tool_events
    assert tracked == [("proposed", event)]


@pytest.mark.parametrize("allocation", ["fails", "cancelled"])
@pytest.mark.parametrize("request_kind", ["denied", "rejected"])
async def test_a_rejection_is_recorded_when_its_span_cannot_be_allocated(
    request_kind: str, allocation: str
) -> None:
    """A rejected request is still recorded as decided; a provider error fails the sample."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    allocating = anyio.Event()
    failure = RuntimeError("no span id")

    async def provider(
        name: str, parent_id: str | None, requested_id: str | None
    ) -> str:
        allocating.set()
        if allocation == "fails":
            raise failure
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    server = "nowhere" if request_kind == "rejected" else "host"
    raised: list[BaseException] = []

    async def request() -> None:
        with span_id_provider(provider):
            try:
                await call_host_tool(bridge)(server, "read_file", {"path": "a"})
            except Exception as ex:
                raised.append(ex)

    with recorded_transcript() as recorded:
        async with anyio.create_task_group() as tg:
            tg.start_soon(request)
            await allocating.wait()
            if allocation == "cancelled":
                tg.cancel_scope.cancel()

    tool.assert_not_awaited()
    [event] = recorded.tool_events
    assert recorded.completions(event) == 1
    assert event.error is not None
    assert event.error.type == (
        "parsing" if request_kind == "rejected" else "permission"
    )
    if allocation == "fails":
        assert raised == [failure]
        assert bridge._failure is failure
    else:
        assert raised == []
        assert not bridge._failure_requested.is_set()
