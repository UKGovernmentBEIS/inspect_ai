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
from functools import partial
from pathlib import Path, PurePosixPath
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterator,
    Literal,
    NamedTuple,
    Sequence,
    cast,
    get_args,
)
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from acp.schema import SessionNotification, ToolCallProgress, ToolCallStart
from pydantic import JsonValue
from test_helpers.checkpoint import RecordingCheckpointer
from test_helpers.message_ids import (
    assert_message_ids,
    edited_id,
    handed_calls,
    message_id_violations,
    recording_placements,
    tool_event_producers,
)
from test_helpers.service_dispatch import (
    dispatching_service,
    serve_beside_failure_monitor,
)
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
)

import inspect_ai._util.logger as inspect_logger
import inspect_ai.agent._bridge.types as bridge_types
from inspect_ai import Task, eval
from inspect_ai._util._async import tg_collect
from inspect_ai._util.content import ContentImage, ContentText, ContentToolUse
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
    _Proposal,
    _ToolExecutionGrant,
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
from inspect_ai.log import EvalLog, read_eval_log, resolve_sample_attachments
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
from inspect_ai.model._message_ids import canonical_tool_arguments
from inspect_ai.model._model import (
    GenerateInput,
    Model,
    ModelResponseFilter,
    get_model,
)
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput, ModelUsage
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
    config: GenerateConfig | None = None,
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
        config or GenerateConfig(),
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


async def test_renamed_declaration_is_approved_under_the_bridged_tools_name() -> None:
    """A policy scoped to a bridged tool governs a call to it under any declared name.

    The grant resolves the call by its served description, so approval must review
    it as that tool too: reviewed under the declared name, the call would fall
    through to the catch-all and still be granted the host tool.
    """
    tool = AsyncMock(return_value="secret")
    bridge = sandbox_bridge_with_tool(
        tool,
        [
            ApprovalPolicy(reject_approver("No host files."), "read_file"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )
    call = ToolCall(id="proposed", function="summarize", arguments={"path": "/secret"})

    run = await run_bridge(
        [
            tool_calls_output(call),
            ModelOutput.from_content(model="mockllm/model", content="Done."),
        ],
        bridge=bridge,
        tools=declare("summarize"),
    )

    assert run.generations == 2
    (result,) = run.tool_results(1)
    assert result.error is not None
    assert "No host files." in result.error.message
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "/secret"})
    tool.assert_not_awaited()


async def test_renamed_declaration_approver_sees_the_bridged_tool_call() -> None:
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    bridge = sandbox_bridge_with_tool(
        AsyncMock(), [ApprovalPolicy(recording_approver(seen), "read_file")]
    )
    call = ToolCall(id="proposed", function="summarize", arguments={"path": "a.txt"})

    run = await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare("summarize")
    )

    ((_, reviewed, history),) = seen
    assert reviewed == ToolCall(
        id="proposed", function="read_file", arguments={"path": "a.txt"}
    )
    # the turn under review and the response handed over keep the declared name
    assert isinstance(history[-1], ChatMessageAssistant)
    assert history[-1].tool_calls == [call]
    assert run.output.message.tool_calls == [call]


async def test_renamed_declaration_modify_rewrites_what_the_grant_binds() -> None:
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool,
        [
            ApprovalPolicy(modifying_approver({"path": "allowed.txt"}), "read_file"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )
    call = ToolCall(id="proposed", function="summarize", arguments={"path": "/secret"})

    run = await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare("summarize")
    )

    assert run.output.message.tool_calls == [
        ToolCall(id="proposed", function="summarize", arguments={"path": "allowed.txt"})
    ]
    execute = call_host_tool(bridge)
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await execute("host", "read_file", {"path": "/secret"})
    assert await execute("host", "read_file", {"path": "allowed.txt"}) == "contents"
    tool.assert_awaited_once_with(path="allowed.txt")


@approver(name="test_bridge_parse_aware")
def parse_aware_approver() -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        if call.parse_error is not None:
            return Approval(decision="reject", explanation=call.parse_error)
        return Approval(decision="approve")

    return approve


@pytest.mark.parametrize("declared", ["read_file", "summarize"])
async def test_malformed_arguments_reach_the_approver_as_a_parse_error(
    declared: str,
) -> None:
    """Reviewing a call as the bridged tool keeps its parse error.

    Unparseable arguments become `{}`; without the error an approver would see a
    valid call, and the grant would run the tool with its defaults.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(parse_aware_approver(), "*")]
    )
    call = parse_tool_call("proposed", declared, "{")
    assert call.parse_error is not None and call.arguments == {}

    run = await run_bridge(
        [
            tool_calls_output(call),
            ModelOutput.from_content(model="mockllm/model", content="Done."),
        ],
        bridge=bridge,
        tools=declare(declared),
    )

    assert run.generations == 2
    (result,) = run.tool_results(1)
    assert result.error is not None
    assert call.parse_error in result.error.message
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {})
    tool.assert_not_awaited()


def indistinct_read_and_delete(
    approval: list[ApprovalPolicy],
) -> tuple[SandboxAgentBridge, AsyncMock, AsyncMock]:
    """Bridged `one/read_file` and `two/delete_file`, served the same description."""
    read = AsyncMock(return_value="read")
    delete = AsyncMock(return_value="deleted")
    bridge = sandbox_bridge_with_servers(
        {
            "one": {"read_file": served_tool(read)},
            "two": {"delete_file": served_tool(delete, name="delete_file")},
        }
    )
    bridge.approval = approval
    return bridge, read, delete


async def test_call_denoting_indistinct_tools_is_approved_as_each_of_them() -> None:
    """A proposal granting several bridged tools is rejected if any of them is."""
    bridge, read, delete = indistinct_read_and_delete(
        [
            ApprovalPolicy(reject_approver("No deleting."), "delete_file"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ]
    )
    call = ToolCall(id="proposed", function="summarize", arguments={"path": "x"})

    run = await run_bridge(
        [
            tool_calls_output(call),
            ModelOutput.from_content(model="mockllm/model", content="Done."),
        ],
        bridge=bridge,
        tools=declare("summarize"),
    )

    assert run.generations == 2
    (result,) = run.tool_results(1)
    assert result.error is not None
    assert "No deleting." in result.error.message
    assert len(bridge._tool_execution_grants) == 0
    read.assert_not_awaited()
    delete.assert_not_awaited()


async def test_modify_of_a_call_denoting_indistinct_tools_fails_the_sample() -> None:
    """The other tool's review approved the unmodified arguments, so a rewrite is refused."""
    bridge, _, _ = indistinct_read_and_delete(
        [
            ApprovalPolicy(modifying_approver({"path": "y"}), "read_file"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ]
    )
    call = ToolCall(id="proposed", function="summarize", arguments={"path": "x"})

    with pytest.raises(RuntimeError, match="several bridged tools sharing a"):
        await run_bridge(
            [tool_calls_output(call)], bridge=bridge, tools=declare("summarize")
        )

    assert isinstance(bridge._failure, RuntimeError)
    assert len(bridge._tool_execution_grants) == 0


@approver(name="test_bridge_approve_with_call")
def approving_with_attached_call(arguments: dict[str, object]) -> Approver:
    """Approves, with a `modified` call attached that an `approve` must not apply."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="approve",
            modified=ToolCall(id=call.id, function=call.function, arguments=arguments),
        )

    return approve


async def test_approve_with_an_attached_call_grants_indistinct_tools_the_proposal() -> (
    None
):
    """Only a `modify` rewrites a call, so an `approve` of an ambiguous call is no modify."""
    bridge, _, _ = indistinct_read_and_delete(
        [ApprovalPolicy(approving_with_attached_call({"path": "y"}), "*")]
    )
    call = ToolCall(id="proposed", function="summarize", arguments={"path": "x"})

    run = await run_bridge(
        [tool_calls_output(call)], bridge=bridge, tools=declare("summarize")
    )

    assert run.output.message.tool_calls == [call]
    assert bridge._failure is None
    for server, name in (("one", "read_file"), ("two", "delete_file")):
        assert not bridge.consume_tool_execution_grant(server, name, {"path": "y"})
        assert bridge.consume_tool_execution_grant(server, name, {"path": "x"})


@approver(name="test_bridge_mutate_in_place")
def mutating_in_place_approver() -> Approver:
    """Changes a nested argument of the call it is shown, then approves."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        call.arguments["options"]["mode"] = "changed"
        return Approval(decision="approve")

    return approve


async def test_in_place_change_by_a_later_target_review_is_rejected() -> None:
    """A review can't change, through shared arguments, what another review approved.

    As on the native path, an `approve` of a call changed in place is a
    rejection: no grant is minted, and the proposal and the earlier review keep
    the arguments the model produced.
    """
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    bridge, read, delete = indistinct_read_and_delete(
        [
            ApprovalPolicy(recording_approver(seen), "read_file"),
            ApprovalPolicy(mutating_in_place_approver(), "delete_file"),
        ]
    )
    arguments = {"path": "x", "options": {"mode": "original"}}
    call = ToolCall(id="proposed", function="summarize", arguments=arguments)
    proposed = tool_calls_output(call)

    run = await run_bridge(
        [proposed, ModelOutput.from_content(model="mockllm/model", content="Done.")],
        bridge=bridge,
        tools=declare("summarize"),
    )

    assert run.generations == 2
    (result,) = run.tool_results(1)
    assert result.error is not None
    assert "changed the tool call in place" in result.error.message
    assert len(bridge._tool_execution_grants) == 0
    original = {"path": "x", "options": {"mode": "original"}}
    assert call.arguments == original
    ((_, reviewed, _),) = seen
    assert reviewed.arguments == original
    execute = call_host_tool(bridge)
    changed: dict[str, JsonValue] = {"path": "x", "options": {"mode": "changed"}}
    for server, name in (("one", "read_file"), ("two", "delete_file")):
        with pytest.raises(PermissionError, match="was not proposed by the model"):
            await execute(server, name, changed)
    read.assert_not_awaited()
    delete.assert_not_awaited()


async def test_dispatcher_shaped_call_to_a_bridged_tool_is_approved_as_that_tool() -> (
    None
):
    """Approval follows the grant when content matching wins over dispatch.

    The declaration is the bridged `host/call_mcp_tool` tool, so the grant binds
    that tool; approval must review it, not the `other/read_file` its arguments
    name.
    """
    seen: list[tuple[str, ToolCall, list[ChatMessage]]] = []
    bridge = sandbox_bridge_with_servers(
        {
            "host": {
                DISPATCHER: served_tool(
                    AsyncMock(), "Route a call.", DISPATCHER_PARAMETERS, name=DISPATCHER
                )
            },
            "other": {"read_file": served_tool(AsyncMock())},
        }
    )
    bridge.approval = [ApprovalPolicy(recording_approver(seen), "*")]
    arguments = {"ServerName": "other", "ToolName": "read_file", "Arguments": {}}
    call = ToolCall(id="proposed", function=DISPATCHER, arguments=arguments)

    await run_bridge(
        [tool_calls_output(call)],
        bridge=bridge,
        tools=declare(
            DISPATCHER, description="Route a call.", parameters=DISPATCHER_PARAMETERS
        ),
    )

    ((_, reviewed, _),) = seen
    assert reviewed == ToolCall(id="proposed", function=DISPATCHER, arguments=arguments)


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


async def test_approval_resolves_against_the_declarations_the_filter_generated_with() -> (
    None
):
    """A filter that declares a bridged tool under a local name gets that tool's policy."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool,
        [
            ApprovalPolicy(reject_approver("No host files."), "read_file"),
            ApprovalPolicy(auto_approver("approve"), "*"),
        ],
    )

    async def declare_host_tool(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> GenerateInput:
        return GenerateInput(input, declare("summarize"), tool_choice, config)

    bridge.filter = declare_host_tool
    call = ToolCall(id="proposed", function="summarize", arguments={"path": "x"})

    run = await run_bridge(
        [
            tool_calls_output(call),
            ModelOutput.from_content(model="mockllm/model", content="Done."),
        ],
        bridge=bridge,
        tools=declare("summarize", description="Summarize the notes."),
    )

    assert run.generations == 2
    (result,) = run.tool_results(1)
    assert result.error is not None
    assert "No host files." in result.error.message
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


def module_warnings(caplog: pytest.LogCaptureFixture, module: str) -> list[str]:
    """Messages logged by `module`.

    pytest also attaches `caplog.handler` to the root logger, so `caplog.records`
    can hold unrelated records, such as asyncio's "Unclosed client session"
    errors when the GC finalizes a session an earlier test leaked.
    """
    return [r.getMessage() for r in caplog.records if r.name == module]


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

    warnings = module_warnings(caplog, SandboxAgentBridge.__module__)
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

    warnings = module_warnings(caplog, SandboxAgentBridge.__module__)
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

    assert module_warnings(caplog, SandboxAgentBridge.__module__) == []


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
    warnings = module_warnings(caplog, execute_host_tool.__module__)
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

    [warning] = module_warnings(caplog, SandboxAgentBridge.__module__)
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


@approver(name="test_bridge_rename_then_modify")
def renaming_modify_approver(keep_function: bool) -> Approver:
    """Renames the call it is shown in place, then returns a modify.

    The modify names the original function when `keep_function`, else the new one.
    """

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        original = call.function
        call.function = "write_file"
        return Approval(
            decision="modify",
            modified=ToolCall(
                id=call.id,
                function=original if keep_function else call.function,
                arguments={"path": "b.txt"},
            ),
        )

    return approve


class ModifiedShape(NamedTuple):
    """A proposal of the bridged `read_file`, as declared and as modified to b.txt."""

    call: ToolCall
    tools: list[ToolInfo]
    modified: ToolCall


MODIFIED_SHAPES = {
    "renamed": ModifiedShape(
        ToolCall(id="1", function="summarize", arguments={"path": "a.txt"}),
        declare("summarize"),
        ToolCall(id="1", function="summarize", arguments={"path": "b.txt"}),
    ),
    "dispatcher": ModifiedShape(
        dispatched("1", {"path": "a.txt"}),
        declare_dispatcher(),
        dispatched("1", {"path": "b.txt"}),
    ),
}


@pytest.mark.parametrize("shape", MODIFIED_SHAPES.values(), ids=MODIFIED_SHAPES.keys())
async def test_modify_is_judged_against_the_call_as_shown(shape: ModifiedShape) -> None:
    """An approver that renames its input in place can't change what a modify selects.

    A modify naming the original function is accepted; one naming the new name
    fails the sample before any grant, as on the native path.
    """
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(renaming_modify_approver(True), "read_file")]
    )

    run = await run_bridge(
        [tool_calls_output(shape.call)], bridge=bridge, tools=shape.tools
    )

    assert run.output.message.tool_calls == [shape.modified]
    assert await call_host_tool(bridge)("host", "read_file", {"path": "b.txt"})

    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(renaming_modify_approver(False), "read_file")]
    )

    with pytest.raises(RuntimeError, match="may change only the arguments"):
        await run_bridge(
            [tool_calls_output(shape.call)], bridge=bridge, tools=shape.tools
        )

    assert isinstance(bridge._failure, RuntimeError)
    assert len(bridge._tool_execution_grants) == 0
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "b.txt"})
    tool.assert_not_awaited()


@approver(name="test_bridge_reidentify")
def reidentifying_approver() -> Approver:
    """Returns a modify with another call id."""

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(id="other", function=call.function, arguments={}),
        )

    return approve


async def test_modify_changing_the_call_id_fails_the_sample() -> None:
    shape = MODIFIED_SHAPES["renamed"]
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(
        tool, [ApprovalPolicy(reidentifying_approver(), "read_file")]
    )

    with pytest.raises(RuntimeError, match="not its id"):
        await run_bridge(
            [tool_calls_output(shape.call)], bridge=bridge, tools=shape.tools
        )

    assert isinstance(bridge._failure, RuntimeError)
    assert len(bridge._tool_execution_grants) == 0


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
    assert reviewed == call
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
    assert reviewed == call
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
    assert reviewed == call


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

    await bridge._track_state(messages, run.output, [])
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


async def test_tool_renamed_in_a_tool_search_result_is_approved_under_its_name() -> (
    None
):
    """Approval resolves a call against in-input declarations, as its grant does."""
    tool = AsyncMock(return_value="contents")
    call = ToolCall(id="c1", function="summarize", arguments={"path": "/secret"})
    bridge = sandbox_responses_bridge(
        tool,
        [
            tool_calls_output(call),
            ModelOutput.from_content(model="mockllm/model", content="Done."),
        ],
    )
    bridge.approval = [
        ApprovalPolicy(reject_approver("No host files."), "read_file"),
        ApprovalPolicy(auto_approver("approve"), "*"),
    ]
    discovered = discovered_read_file_namespace()
    discovered["tools"][0]["name"] = "summarize"

    response = await inspect_responses_api_request(
        responses_request_with_tool_search([discovered]),
        None,
        internal_web_search_providers(),
        default_code_execution_providers(),
        bridge,
    )

    assert [item for item in response.output if item.type == "function_call"] == []
    with pytest.raises(PermissionError, match="was not proposed by the model"):
        await call_host_tool(bridge)("host", "read_file", {"path": "/secret"})
    tool.assert_not_awaited()


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
    [proposing] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert event.call_message_id == proposing.output.message.id
    assert event.call_message_id is not None
    assert recorded.completions(event) == 1


async def test_alternate_selected_by_response_filter_names_its_model_choice() -> None:
    """A selected alternate host call names the choice that proposed it."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None)
    call = ToolCall(id="alternate", function="read_file", arguments={"path": "a"})
    generated = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(message=ChatMessageAssistant(content="first")),
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="alternate", tool_calls=[call]),
                stop_reason="tool_calls",
            ),
        ],
    )

    async def select_alternate(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        return output.model_copy(update={"choices": output.choices[::-1]})

    bridge.response_filter = select_alternate
    with recorded_transcript() as recorded:
        await run_bridge([generated], bridge=bridge, tools=declare("read_file"))
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [event] = recorded.tool_events
    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert event.call_message_id == generation.output.choices[1].message.id


@pytest.mark.parametrize(
    ("same_arguments", "response_filter"),
    [
        (False, None),
        (True, None),
        (False, "edit_text"),
        (False, "returns_none"),
        (False, "returns_unchanged"),
    ],
)
async def test_reused_call_id_across_choices_keeps_selected_producer(
    same_arguments: bool,
    response_filter: str | None,
) -> None:
    """The selected choice wins, whatever the filter returns; indistinguishable proposals stay unlinked."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    first = ToolCall(id="same", function="read_file", arguments={"path": "a"})
    second = ToolCall(
        id="same",
        function="read_file",
        arguments={"path": "a" if same_arguments else "b"},
    )
    generated = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="first", tool_calls=[first]),
                stop_reason="tool_calls",
            ),
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="second", tool_calls=[second]),
                stop_reason="tool_calls",
            ),
        ],
    )

    async def edit_text(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        output.message.content = "filtered first"
        return output

    async def returns_none(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> None:
        return None

    async def returns_unchanged(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        return output

    filters: dict[str, ModelResponseFilter] = {
        "edit_text": edit_text,
        "returns_none": returns_none,
        "returns_unchanged": returns_unchanged,
    }
    if response_filter is not None:
        bridge.response_filter = filters[response_filter]

    with recorded_transcript() as recorded:
        await run_bridge([generated], bridge=bridge, tools=declare("read_file"))
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [event] = recorded.tool_events
    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert event.call_message_id == (
        None if same_arguments else generation.output.choices[0].message.id
    )


async def test_duplicate_call_ids_in_one_reply_keep_proposing_message() -> None:
    """Two calls in one reply share one unambiguous proposing message."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    calls = [
        ToolCall(id="unknown", function="read_file", arguments={"path": path})
        for path in ("a", "b")
    ]
    generated = tool_calls_output(*calls)

    with recorded_transcript() as recorded:
        await run_bridge([generated], bridge=bridge, tools=declare("read_file"))
        for path in ("a", "b"):
            await call_host_tool(bridge)("host", "read_file", {"path": path})

    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert len(recorded.tool_events) == 2
    assert [e.call_message_id for e in recorded.tool_events] == [
        generation.output.message.id
    ] * 2


async def test_identical_duplicate_calls_have_no_unique_producer() -> None:
    """Identical duplicate calls cannot each name one generated call."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    calls = [
        ToolCall(id="same", function="read_file", arguments={"path": "a"})
        for _ in range(2)
    ]
    with recorded_transcript() as recorded:
        await run_bridge(
            [tool_calls_output(*calls)], bridge=bridge, tools=declare("read_file")
        )
        for _ in calls:
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    assert len(recorded.tool_events) == 2
    assert all(event.call_message_id is None for event in recorded.tool_events)


async def test_recovered_refusal_keeps_host_call_provenance() -> None:
    """A response filter can recover a refusal without losing its producer."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    call = ToolCall(id="recovered", function="read_file", arguments={"path": "a"})
    generated = tool_calls_output(call)
    generated.choices[0].stop_reason = "content_filter"

    async def recover(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        output.choices[0].stop_reason = "tool_calls"
        return output

    bridge.response_filter = recover
    with recorded_transcript() as recorded:
        await run_bridge(
            [generated],
            bridge=bridge,
            tools=declare("read_file"),
            config=GenerateConfig(fail_on_refusal=True),
        )
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [event] = recorded.tool_events
    assert event.call_message_id == generation.output.message.id


async def test_synthetic_request_filter_call_has_no_proposing_message() -> None:
    """A request filter's call has no producer when it did not generate."""
    tool = AsyncMock(return_value="contents")

    async def synthetic(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        return tool_calls_output(
            ToolCall(id="synthetic", function="read_file", arguments={"path": "a"})
        )

    bridge = sandbox_bridge_with_tool(tool, None)
    bridge.filter = synthetic
    with recorded_transcript() as recorded:
        await run_bridge(
            [ModelOutput.from_content("mockllm/model", "unused")],
            bridge=bridge,
            tools=declare("read_file"),
        )
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    assert not any(isinstance(e, ModelEvent) for e in recorded.events)
    [event] = recorded.tool_events
    assert event.call_message_id is None


async def test_generating_request_filter_keeps_proposing_message() -> None:
    """A filter that calls the model still links its host call to that generation."""
    tool = AsyncMock(return_value="contents")

    async def generate_in_filter(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        return await model.generate(
            input=input, tools=tools, tool_choice=tool_choice, config=config
        )

    bridge = sandbox_bridge_with_tool(tool, None)
    bridge.filter = generate_in_filter
    call = ToolCall(id="generated", function="read_file", arguments={"path": "a"})
    with recorded_transcript() as recorded:
        await run_bridge(
            [tool_calls_output(call)], bridge=bridge, tools=declare("read_file")
        )
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [event] = recorded.tool_events
    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert event.call_message_id == generation.output.message.id


@pytest.mark.parametrize("path", ["a", "b"])
async def test_generating_request_filter_rewritten_call_is_verified(path: str) -> None:
    """A filter's copy of a generated call links only if its arguments are unchanged."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)

    async def generate_and_rewrite(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        output = await model.generate(
            input=input, tools=tools, tool_choice=tool_choice, config=config
        )
        output = output.model_copy(deep=True)
        assert output.message.tool_calls
        output.message.tool_calls[0].arguments = {"path": path}
        return output

    bridge.filter = generate_and_rewrite
    call = ToolCall(id="generated", function="read_file", arguments={"path": "a"})
    with recorded_transcript() as recorded:
        await run_bridge(
            [tool_calls_output(call)], bridge=bridge, tools=declare("read_file")
        )
        await call_host_tool(bridge)("host", "read_file", {"path": path})

    [event] = recorded.tool_events
    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert event.call_message_id == (
        generation.output.message.id if path == "a" else None
    )


async def test_generating_request_filter_reordered_choice_keeps_provenance() -> None:
    """A filter's selected alternate links to its recorded generated choice."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    call = ToolCall(id="alternate", function="read_file", arguments={"path": "a"})
    generated = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(message=ChatMessageAssistant(content="first")),
            ChatCompletionChoice(
                message=ChatMessageAssistant(content="alternate", tool_calls=[call]),
                stop_reason="tool_calls",
            ),
        ],
    )

    async def generate_and_select(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        output = await model.generate(
            input=input, tools=tools, tool_choice=tool_choice, config=config
        )
        return output.model_copy(update={"choices": output.choices[::-1]})

    bridge.filter = generate_and_select
    with recorded_transcript() as recorded:
        await run_bridge([generated], bridge=bridge, tools=declare("read_file"))
        await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [event] = recorded.tool_events
    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert event.call_message_id == generation.output.choices[1].message.id


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
    assert event.call_message_id is None
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


@pytest.mark.parametrize("replacement", ["returned", "choices", "message"])
@pytest.mark.parametrize("reuse_id", [False, True])
@pytest.mark.parametrize("same_arguments", [False, True])
async def test_response_filter_replacement_does_not_claim_initial_proposal(
    replacement: str, reuse_id: bool, same_arguments: bool
) -> None:
    """A separately generated replacement cannot claim the initial proposal."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    bridge.model_event_sink = StartingStampingSink({"stamp", "open"})

    async def replace(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        generated = await model.generate(
            input=generate_input.input,
            tools=generate_input.tools,
            tool_choice=generate_input.tool_choice,
            config=generate_input.config,
        )
        if replacement == "returned":
            return generated
        if replacement == "choices":
            output.choices = generated.choices
        else:
            output.choices[0].message = generated.message
        return output

    bridge.response_filter = replace
    first = ToolCall(id="same", function="read_file", arguments={"path": "a"})
    second = ToolCall(
        id="same" if reuse_id else "other",
        function="read_file",
        arguments={"path": "a" if same_arguments else "b"},
    )
    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            await run_bridge(
                [tool_calls_output(first), tool_calls_output(second)],
                bridge=bridge,
                tools=declare("read_file"),
            )
            await call_host_tool(bridge)(
                "host", "read_file", {"path": "a" if same_arguments else "b"}
            )

    generations = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [event] = recorded.tool_events
    assert len(generations) == 2
    assert generations[0].span_id == "agent-sub"
    assert generations[1].span_id == outer
    assert event.call_message_id is None
    assert event.span_id == outer


@pytest.mark.parametrize(
    "edit", ["arguments", "append", "append-duplicate", "parallel-edit"]
)
async def test_response_filter_keeps_each_original_call_attribution(edit: str) -> None:
    """Only unchanged call signatures retain their link and span."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    bridge.model_event_sink = StartingStampingSink({"stamp", "open"})

    async def change(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        tool_calls = output.message.tool_calls
        assert tool_calls is not None
        if edit == "arguments":
            tool_calls[0].arguments = {"path": "b"}
        elif edit.startswith("append"):
            tool_calls.append(
                ToolCall(
                    id="original" if edit == "append-duplicate" else "added",
                    function="read_file",
                    arguments={"path": "b"},
                )
            )
        else:
            tool_calls[1].arguments = {"path": "c"}
        return output

    bridge.response_filter = change
    calls = [ToolCall(id="original", function="read_file", arguments={"path": "a"})]
    if edit == "parallel-edit":
        calls.append(
            ToolCall(id="second", function="read_file", arguments={"path": "b"})
        )
    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            await run_bridge(
                [tool_calls_output(*calls)], bridge=bridge, tools=declare("read_file")
            )
            await call_host_tool(bridge)(
                "host", "read_file", {"path": "b" if edit == "arguments" else "a"}
            )
            if edit.startswith("append"):
                await call_host_tool(bridge)("host", "read_file", {"path": "b"})
            elif edit == "parallel-edit":
                await call_host_tool(bridge)("host", "read_file", {"path": "c"})

    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    first, *rest = recorded.tool_events
    assert first.call_message_id == (
        None if edit == "arguments" else generation.output.message.id
    )
    assert first.span_id == (outer if edit == "arguments" else "agent-sub")
    if rest:
        [second] = rest
        assert second.call_message_id is None
        assert second.span_id == outer


@pytest.mark.parametrize("edit", ["unchanged", "changed_id", "missing_id", "rebuilt"])
async def test_response_filter_kept_server_item_does_not_infer_call_attribution(
    edit: str,
) -> None:
    """Replay ownership does not by itself prove a host-call producer."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    bridge.model_event_sink = StartingStampingSink({"stamp", "open"})

    async def change(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        if edit == "changed_id":
            output.message.id = "filter-chosen-id"
        elif edit == "missing_id":
            output.message.id = None
        elif edit == "rebuilt":
            output.choices[0].message = ChatMessageAssistant.model_validate(
                output.message.model_dump(exclude={"id"})
            )
        return output

    bridge.response_filter = change
    call = ToolCall(id="original", function="read_file", arguments={"path": "a"})
    initial = tool_calls_output(call)
    initial.message.content = [
        ContentText(text="Searched; now reading."),
        ContentToolUse(
            id="server-search",
            tool_type="web_search",
            name="web_search",
            arguments='{"query":"test"}',
            result="found",
        ),
    ]
    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            run = await run_bridge([initial], bridge=bridge, tools=declare("read_file"))
            await call_host_tool(bridge)("host", "read_file", {"path": "a"})

    [generation] = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [event] = recorded.tool_events
    assert run.output.message.id == generation.output.message.id
    assert run.output.message.tool_calls == generation.output.message.tool_calls
    assert event.call_message_id == (
        generation.output.message.id if edit == "unchanged" else None
    )
    assert event.span_id == ("agent-sub" if edit == "unchanged" else outer)


async def test_filter_generated_replacement_with_server_item_stays_unlinked() -> None:
    """Replay ownership cannot establish a replacement host call's producer."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    bridge.model_event_sink = StartingStampingSink({"stamp", "open"})

    async def replace(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        generated = await model.generate(
            input=generate_input.input,
            tools=generate_input.tools,
            tool_choice=generate_input.tool_choice,
            config=generate_input.config,
        )
        replacement = generated.model_copy(deep=True)
        replacement.message.content = output.message.content
        return replacement

    bridge.response_filter = replace
    original = ToolCall(id="same", function="read_file", arguments={"path": "original"})
    replacement = ToolCall(
        id="same", function="read_file", arguments={"path": "replacement"}
    )
    first = tool_calls_output(original)
    first.message.content = [
        ContentText(text="Searched."),
        ContentToolUse(
            id="server-search",
            tool_type="web_search",
            name="web_search",
            arguments='{"query":"test"}',
            result="found",
        ),
    ]
    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            run = await run_bridge(
                [first, tool_calls_output(replacement)],
                bridge=bridge,
                tools=declare("read_file"),
            )
            await call_host_tool(bridge)("host", "read_file", {"path": "replacement"})

    first_event, second_event = [
        event for event in recorded.events if isinstance(event, ModelEvent)
    ]
    [event] = recorded.tool_events
    # an edit of the output whose server item it keeps (no work left running)
    assert run.output.message.id == edited_id(
        first_event.output.message.id, run.output.message
    )
    assert second_event.output.message.id != first_event.output.message.id
    assert event.call_message_id is None
    assert event.span_id == outer


async def test_filter_retained_server_item_does_not_replace_verified_call_source() -> (
    None
):
    """Replay ownership cannot replace a different choice's verified producer."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    bridge.model_event_sink = StartingStampingSink({"stamp", "open"})

    async def select_second(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        output.choices[1].message.content = output.choices[0].message.content
        return output.model_copy(update={"choices": [output.choices[1]]})

    bridge.response_filter = select_second
    first = tool_calls_output(
        ToolCall(id="same", function="read_file", arguments={"path": "a"})
    )
    first.message.content = [
        ContentText(text="Searched."),
        ContentToolUse(
            id="server-search",
            tool_type="web_search",
            name="web_search",
            arguments='{"query":"test"}',
            result="found",
        ),
    ]
    second = tool_calls_output(
        ToolCall(id="same", function="read_file", arguments={"path": "b"})
    )
    generated = ModelOutput(
        model=first.model,
        choices=[first.choices[0], second.choices[0]],
    )
    with recorded_transcript() as recorded:
        async with span("outer"):
            await run_bridge([generated], bridge=bridge, tools=declare("read_file"))
            await call_host_tool(bridge)("host", "read_file", {"path": "b"})

    [generation] = [event for event in recorded.events if isinstance(event, ModelEvent)]
    [event] = recorded.tool_events
    assert event.call_message_id == generation.output.choices[1].message.id
    assert event.span_id == "agent-sub"


async def test_filter_prepended_duplicate_id_does_not_claim_original() -> None:
    """Duplicate IDs are matched by their arguments across reordered calls."""
    bridge = sandbox_bridge_with_tool(AsyncMock(return_value="contents"), None)
    bridge.model_event_sink = StartingStampingSink({"stamp", "open"})

    async def prepend(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput:
        calls = output.message.tool_calls
        assert calls is not None
        calls[:] = [
            ToolCall(id="same", function="read_file", arguments={"path": "synthetic"}),
            calls[1],
            calls[0],
        ]
        return output

    bridge.response_filter = prepend
    original_calls = [
        ToolCall(id="same", function="read_file", arguments={"path": path})
        for path in ("a", "b")
    ]
    with recorded_transcript() as recorded:
        async with span("outer"):
            outer = current_span_id()
            await run_bridge(
                [tool_calls_output(*original_calls)],
                bridge=bridge,
                tools=declare("read_file"),
            )
            for path in ("synthetic", "b", "a"):
                await call_host_tool(bridge)("host", "read_file", {"path": path})

    [generation] = [event for event in recorded.events if isinstance(event, ModelEvent)]
    synthetic, second, first = recorded.tool_events
    assert synthetic.call_message_id is None
    assert synthetic.span_id == outer
    assert [second.call_message_id, first.call_message_id] == [
        generation.output.message.id
    ] * 2
    assert second.span_id == first.span_id == "agent-sub"


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


async def test_limit_is_recorded_and_raised_as_its_native_tool_error() -> None:
    """The scaffold reads the message the model reads natively, not the limit."""
    error = LimitExceededError("token", value=2, limit=1)
    message = "The tool exceeded its token limit of 1."

    bridge, event, raised = await run_failing(error)

    assert type(raised) is ToolError
    assert str(raised) == message
    assert raised.__cause__ is error
    assert event.error == ToolCallError("limit", message)
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


async def _suffix_filter(
    model: Model, output: ModelOutput, generate_input: GenerateInput
) -> ModelOutput:
    output.message.content = output.message.text + " FILTERED"
    return output


HostDialect = Literal["completions", "responses", "anthropic", "google"]
HostMode = Literal[
    "plain", "filter", "approval", "request_copy", "request_edit", "javascript"
]


def _generating_request_filter(edit: bool) -> Callable[..., Awaitable[ModelOutput]]:
    """A request filter returning a copy of its own generation, with `edit` its text changed."""

    async def generate(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        output = await model.generate(
            input=input, tools=tools, tool_choice=tool_choice, config=config
        )
        output = output.model_copy(deep=True)
        if edit:
            output.message.content = output.message.text + " EDITED"
        return output

    return generate


class _HostConversation:
    """One dialect's wire conversation, for a scaffold running every call as a host tool."""

    def __init__(
        self,
        dialect: HostDialect,
        prompt: str,
        info: ToolInfo,
        javascript: bool = False,
        others: Sequence[ToolInfo] = (),
    ) -> None:
        self.dialect = dialect
        self.infos = [info, *others]
        self.javascript = javascript
        self.history: list[dict[str, Any]] = (
            [{"role": "user", "parts": [{"text": prompt}]}]
            if dialect == "google"
            else [{"role": "user", "content": prompt}]
        )
        self.returned_ids: list[str] = []

    async def request(
        self, bridge: SandboxAgentBridge
    ) -> list[tuple[str, dict[str, Any]]]:
        """Send the conversation; append the reply and return its (call id or name, arguments).

        With `javascript`, the reply and its arguments are kept as a JavaScript
        scaffold's JSON round-trip leaves them.
        """
        start = len(self.history)
        calls = await self._request(bridge)
        if self.javascript:
            self.history[start:] = _javascript_json(self.history[start:])
            calls = [(id, _javascript_json(arguments)) for id, arguments in calls]
        return calls

    async def _request(
        self, bridge: SandboxAgentBridge
    ) -> list[tuple[str, dict[str, Any]]]:
        infos = self.infos
        match self.dialect:
            case "completions":
                tools: list[dict[str, Any]] = [
                    {"type": "function", "function": info.model_dump(exclude_none=True)}
                    for info in infos
                ]
                completion = await inspect_completions_api_request(
                    {"model": "inspect", "messages": self.history, "tools": tools},
                    None,
                    bridge,
                )
                reply = completion.choices[0].message
                self.history.append(reply.model_dump(exclude_none=True))
                return [
                    (call.id, json.loads(call.function.arguments))
                    for call in reply.tool_calls or []
                    if call.type == "function"
                ]
            case "responses":
                tools = [
                    {
                        "type": "function",
                        "name": info.name,
                        "description": info.description,
                        "parameters": _parameters(info),
                    }
                    for info in infos
                ]
                response = await inspect_responses_api_request(
                    {"model": "inspect", "input": self.history, "tools": tools},
                    None,
                    internal_web_search_providers(),
                    default_code_execution_providers(),
                    bridge,
                )
                self.returned_ids.append(response.id)
                self.history.extend(
                    item.model_dump(exclude_none=True) for item in response.output
                )
                return [
                    (item.call_id, json.loads(item.arguments))
                    for item in response.output
                    if item.type == "function_call"
                ]
            case "anthropic":
                tools = [
                    {
                        "name": info.name,
                        "description": info.description,
                        "input_schema": _parameters(info),
                    }
                    for info in infos
                ]
                message = await inspect_anthropic_api_request(
                    {
                        "model": "inspect",
                        "max_tokens": 1024,
                        "messages": self.history,
                        "tools": tools,
                    },
                    None,
                    internal_web_search_providers(),
                    default_code_execution_providers(),
                    bridge,
                )
                self.returned_ids.append(message.id)
                self.history.append(
                    {
                        "role": "assistant",
                        "content": [
                            block.model_dump(exclude_none=True)
                            for block in message.content
                        ],
                    }
                )
                return [
                    (block.id, cast(dict[str, Any], block.input))
                    for block in message.content
                    if block.type == "tool_use"
                ]
            case "google":
                declarations = [
                    {
                        "name": info.name,
                        "description": info.description,
                        "parametersJsonSchema": _parameters(info),
                    }
                    for info in infos
                ]
                gemini = await inspect_google_api_request(
                    {
                        "contents": self.history,
                        "tools": [{"functionDeclarations": declarations}],
                    },
                    internal_web_search_providers(),
                    default_code_execution_providers(),
                    bridge,
                )
                content = gemini["candidates"][0]["content"]
                self.history.append(content)
                return [
                    (part["functionCall"]["name"], part["functionCall"]["args"])
                    for part in content["parts"]
                    if "functionCall" in part
                ]

    def results(
        self,
        calls: list[tuple[str, Any]],
        outputs: list[JsonValue],
        listed: bool = False,
        error: bool = False,
        padded: bool = False,
    ) -> None:
        """Append the results of `calls` the way the dialect sends them.

        With `listed`, each result's text is sent as a list of text parts (one,
        or none for empty text), where the dialect allows one (Google results
        are JSON objects); with `padded` as well, the list starts and ends with
        an empty text part. With `error`, Anthropic results are sent as errors.
        """

        def content(output: JsonValue, text_type: str = "text") -> Any:
            if not listed:
                return str(output)
            parts = [{"type": text_type, "text": str(output)}] if output != "" else []
            empty = [{"type": text_type, "text": ""}] if padded else []
            return [*empty, *parts, *empty]

        match self.dialect:
            case "completions":
                self.history.extend(
                    {"role": "tool", "tool_call_id": id, "content": content(output)}
                    for (id, _), output in zip(calls, outputs)
                )
            case "responses":
                self.history.extend(
                    {
                        "type": "function_call_output",
                        "call_id": id,
                        "output": content(output, "input_text"),
                    }
                    for (id, _), output in zip(calls, outputs)
                )
            case "anthropic":
                self.history.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": id,
                                "content": content(output),
                                **({"is_error": True} if error else {}),
                            }
                            for (id, _), output in zip(calls, outputs)
                        ],
                    }
                )
            case "google":
                self.history.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": name,
                                    "response": {"output": str(output)},
                                }
                            }
                            for (name, _), output in zip(calls, outputs)
                        ],
                    }
                )


def _parameters(info: ToolInfo) -> dict[str, Any]:
    return info.parameters.model_dump(exclude_none=True)


def _javascript_json(value: Any, key: str | None = None) -> Any:
    """`value` after a JavaScript JSON round-trip, which writes 5.0 as 5."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and key == "arguments":
        return json.dumps(_javascript_json(json.loads(value)))
    if isinstance(value, dict):
        return {k: _javascript_json(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_javascript_json(v) for v in value]
    return value


def _numbered_results() -> AsyncMock:
    """A host tool mock whose every result is different."""
    count = 0

    async def read(**arguments: Any) -> str:
        nonlocal count
        count += 1
        return f"{arguments.get('path')} result {count}"

    return AsyncMock(side_effect=read)


@agent
def host_scaffold(mode: HostMode, dialect: HostDialect = "completions") -> Agent:
    """A scaffold running every call it gets as a bridged host tool, in parallel."""

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=_generating_request_filter(mode == "request_edit")
            if mode in ("request_copy", "request_edit")
            else None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(_numbered_results())}},
            response_filter=_suffix_filter if mode == "filter" else None,
            approval=[ApprovalPolicy(modifying_approver({"path": "safe"}), "*")]
            if mode == "approval"
            else None,
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation(
            dialect, state.messages[0].text, info, javascript=mode == "javascript"
        )
        while True:
            calls = await conversation.request(bridge)
            if not calls:
                return bridge.state
            outputs = await tg_collect(
                [
                    partial(call_host_tool(bridge), "host", "read_file", arguments)
                    for _, arguments in calls
                ]
            )
            conversation.results(calls, outputs)

    return execute


def _host_outputs() -> list[ModelOutput]:
    """Two rounds of two parallel calls (the first call's id repeats), then an answer."""
    name = "mcp__host__read_file"
    return [
        tool_calls_output(
            ToolCall(id="repeat", function=name, arguments={"path": "a"}),
            ToolCall(id="parallel", function=name, arguments={"path": "b"}),
            content=f"round {n}",
        )
        for n in range(2)
    ] + [ModelOutput.from_content("mockllm/model", "done")]


def _run_host_scaffold(
    mode: HostMode,
    dialect: HostDialect,
    tmp_path: Path,
    outputs: list[ModelOutput] | None = None,
) -> EvalSample:
    log = eval(
        Task(
            dataset=[Sample(input="Read both files twice.")],
            solver=host_scaffold(mode, dialect),
        ),
        model=get_model("mockllm/model", custom_outputs=outputs or _host_outputs()),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")
    assert_message_ids(sample)
    return sample


@pytest.mark.parametrize("mode", ["plain", "filter", "approval"])
def test_host_tool_events_name_the_generated_output(
    mode: Literal["plain", "filter", "approval"], tmp_path: Path
) -> None:
    """Each host tool event names exactly one model event's output, whatever changed the reply."""
    sample = _run_host_scaffold(mode, "completions", tmp_path)
    assert tool_event_producers(sample) == [1, 1, 1, 1]
    replies = [
        m
        for m in sample.messages
        if isinstance(m, ChatMessageAssistant) and m.tool_calls
    ]
    outputs_by_id = {
        e.output.message.id: e.output.message
        for e in sample.events
        if isinstance(e, ModelEvent)
    }
    for reply in replies:
        if mode == "plain":
            assert reply.id in outputs_by_id
        else:
            assert any(reply.id == edited_id(source, reply) for source in outputs_by_id)
    if mode == "approval":
        assert {
            call.arguments["path"] for r in replies for call in r.tool_calls or []
        } == {"safe"}


@pytest.mark.parametrize("edit", [False, True])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
def test_generating_request_filter_text_edit_is_unverified(
    dialect: HostDialect, edit: bool, tmp_path: Path
) -> None:
    """A request filter's copy of its generation keeps the generated id only if unchanged."""
    sample = _run_host_scaffold(
        "request_edit" if edit else "request_copy", dialect, tmp_path
    )

    generated = {
        e.output.message.id for e in sample.events if isinstance(e, ModelEvent)
    }
    replies = [
        m
        for m in sample.messages
        if isinstance(m, ChatMessageAssistant) and m.tool_calls
    ]
    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert len(replies) == 2 and len(events) == 4
    if edit:
        assert all(r.text.endswith(" EDITED") for r in replies)
        assert not any(r.id in generated for r in replies)
        assert all(e.call_message_id is None for e in events)
    else:
        assert tool_event_producers(sample) == [1, 1, 1, 1]


@pytest.mark.parametrize("mode", ["plain", "filter", "approval"])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
def test_host_tool_events_name_their_result_message(
    dialect: HostDialect, mode: HostMode, tmp_path: Path
) -> None:
    """Each host tool event's `message_id` is the tool message the scaffold sent its result in."""
    sample = _run_host_scaffold(mode, dialect, tmp_path)

    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert len(events) == 4
    if dialect == "google" or mode == "approval":
        # each round's calls share a function, and a Google result names only
        # its function, so which call it answers is unknown; the approver
        # gives each round's calls the same arguments, so which call's grant
        # an execution took is unknown
        assert all(e.message_id is None for e in events)
        return
    _assert_linked(sample, events)


@agent
def crossed_grants_scaffold(dialect: HostDialect, declared_only: bool) -> Agent:
    """Two conversations each get the same host call; the second one's executes first.

    With `declared_only`, the sub-agent's call is forwarded with only the
    properties the host tool declares.
    """

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(_numbered_results())}},
        )
        [info] = declare("mcp__host__read_file")
        main = _HostConversation(dialect, state.messages[0].text, info)
        sub = _HostConversation(dialect, "Sub-agent: read a.", info)
        main_calls = await main.request(bridge)
        sub_calls = await sub.request(bridge)
        sub_arguments = sub_calls[0][1]
        if declared_only:
            sub_arguments = {"path": sub_arguments["path"]}
        sub_output = await call_host_tool(bridge)("host", "read_file", sub_arguments)
        main_output = await call_host_tool(bridge)(
            "host", "read_file", main_calls[0][1]
        )
        main.results(main_calls, [main_output])
        sub.results(sub_calls, [sub_output])
        await main.request(bridge)
        await sub.request(bridge)
        return bridge.state

    return execute


@pytest.mark.parametrize("declared_only", [False, True])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
def test_host_calls_whose_grants_cross_stay_unlinked(
    dialect: HostDialect, declared_only: bool, tmp_path: Path
) -> None:
    """Two replies making the same call leave both executions unlinked.

    The sub-agent's execution matches both replies' grants and takes the
    older, the main conversation's, so each event holds the other
    conversation's result. Which call an execution ran is unknown, so
    neither event names a result message. With `declared_only`, the
    sub-agent's call also proposes an undeclared property that its scaffold
    drops when executing: its grant matches only once that property is
    dropped, and the main conversation's exact match does not hide it.
    """
    name = "mcp__host__read_file"
    sub_arguments: dict[str, object] = {"path": "a"}
    if declared_only:
        sub_arguments["unexpected"] = "value"
    log = eval(
        Task(
            dataset=[Sample(input="Read a.")],
            solver=crossed_grants_scaffold(dialect, declared_only),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_calls_output(
                    ToolCall(id="call_main", function=name, arguments={"path": "a"}),
                    content="Reading.",
                ),
                tool_calls_output(
                    ToolCall(id="call_sub", function=name, arguments=sub_arguments),
                    content="On it.",
                ),
                ModelOutput.from_content("mockllm/model", "done"),
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, ToolEvent)]
    assert [(e.id, e.result) for e in events] == [
        ("call_main", "a result 1"),
        ("call_sub", "a result 2"),
    ]
    assert [e.message_id for e in events] == [None, None]


LIST_DIR = "List a directory on the host."


@agent
def delayed_second_grant_scaffold(dialect: HostDialect, unrelated: int) -> Agent:
    """Executes a call on server `a`, then `unrelated` other host calls, then the call's remaining grant on server `b`, then sends `a`'s answer."""

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={
                "a": {"read_file": read_file(AsyncMock(return_value="from a"))},
                "b": {"read_file": read_file(AsyncMock(return_value="from b"))},
                "other": {
                    "list_dir": served_tool(
                        AsyncMock(return_value="listed"),
                        description=LIST_DIR,
                        name="list_dir",
                    )
                },
            },
        )
        [info] = declare("mcp__host__read_file")
        main = _HostConversation(dialect, state.messages[0].text, info)
        main_calls = await main.request(bridge)
        [(_, arguments)] = main_calls
        a_output = await call_host_tool(bridge)("a", "read_file", arguments)
        if unrelated:
            [list_info] = declare("list_dir", description=LIST_DIR)
            sub = _HostConversation(dialect, "Sub-agent: list.", list_info)
            for _, listed in await sub.request(bridge):
                await call_host_tool(bridge)("other", "list_dir", listed)
        await call_host_tool(bridge)("b", "read_file", arguments)
        main.results(main_calls, [a_output])
        await main.request(bridge)
        return bridge.state

    return execute


@pytest.mark.parametrize(
    "unrelated", [0, bridge_types._MAX_AWAITED_RESULTS], ids=["kept", "evicted"]
)
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
def test_delayed_second_execution_of_a_proposal_stays_unlinked(
    dialect: HostDialect, unrelated: int, tmp_path: Path
) -> None:
    """A proposal's second execution links nothing, even after its first's tracking was dropped.

    Two servers serve the same description, so the proposal grants each one
    execution. The scaffold answers the call with server `a`'s result; with
    `unrelated` host calls in between, the bridge has stopped tracking the
    first execution by the time `b`'s runs.
    """
    log = eval(
        Task(
            dataset=[Sample(input="Read a.")],
            solver=delayed_second_grant_scaffold(dialect, unrelated),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_calls_output(
                    ToolCall(
                        id="call_main",
                        function="mcp__host__read_file",
                        arguments={"path": "a"},
                    ),
                    content="Reading.",
                ),
                *(
                    [
                        tool_calls_output(
                            *(
                                ToolCall(
                                    id=f"call_list_{n}",
                                    function="list_dir",
                                    arguments={"path": f"d{n}"},
                                )
                                for n in range(unrelated)
                            )
                        )
                    ]
                    if unrelated
                    else []
                ),
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")
    events = [
        e
        for e in sample.events
        if isinstance(e, ToolEvent) and bridge_metadata(e)["tool"] == "read_file"
    ]
    assert [(bridge_metadata(e)["server"], e.result) for e in events] == [
        ("a", "from a"),
        ("b", "from b"),
    ]
    assert all(bridge_metadata(e)["proposal_id"] == "call_main" for e in events)
    assert [e.message_id for e in events] == [None, None]


@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
def test_host_tool_grant_matches_numeric_reserialization(
    dialect: HostDialect, tmp_path: Path
) -> None:
    """A JavaScript scaffold sends 5.0 back as 5: the call still runs and links its result."""
    call = ToolCall(
        id="call",
        function="mcp__host__read_file",
        arguments={"path": "a", "offset": 5.0},
    )
    sample = _run_host_scaffold(
        "javascript",
        dialect,
        tmp_path,
        [tool_calls_output(call), ModelOutput.from_content("mockllm/model", "done")],
    )

    [reply] = [
        m
        for m in sample.messages
        if isinstance(m, ChatMessageAssistant) and m.tool_calls
    ]
    assert reply.tool_calls and type(reply.tool_calls[0].arguments["offset"]) is int
    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert len(events) == 1 and events[0].error is None
    _assert_linked(sample, events)


def _assert_linked(sample: EvalSample, events: list[ToolEvent]) -> None:
    """Each event names a distinct tool message, answering its proposing reply, that holds its result."""
    positions = {m.id: i for i, m in enumerate(sample.messages)}
    for event in events:
        assert event.message_id is not None
        result = sample.messages[positions[event.message_id]]
        assert isinstance(result, ChatMessageTool)
        assert str(event.result) in result.text
        proposing = next(
            m
            for m in reversed(sample.messages[: positions[event.message_id]])
            if isinstance(m, ChatMessageAssistant)
        )
        assert result.tool_call_id in [c.id for c in proposing.tool_calls or []]
    assert len({e.message_id for e in events}) == len(events)


@agent
def identical_host_scaffold(
    results: Literal["equal", "numbered"],
    reorder: bool,
    executed: int | None,
    edited: Literal["none", "one", "both"] = "none",
) -> Agent:
    """A Google scaffold running identical parallel calls as host tools.

    It runs the first `executed` calls (all when `None`), with `reorder` sends
    the calls back, and their results, in reverse order, and replaces the last
    result it sends, or every result, with other text as `edited` says.
    """

    async def execute(state: AgentState) -> AgentState:
        tool = (
            AsyncMock(return_value="same contents")
            if results == "equal"
            else _numbered_results()
        )
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(tool)}},
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation("google", state.messages[0].text, info)
        while True:
            calls = await conversation.request(bridge)
            if not calls:
                return bridge.state
            run = calls if executed is None else calls[:executed]
            outputs: list[JsonValue] = list(
                await tg_collect(
                    [
                        partial(call_host_tool(bridge), "host", "read_file", arguments)
                        for _, arguments in run
                    ]
                )
            )
            outputs += ["not run"] * (len(calls) - len(run))
            if edited == "one":
                outputs[-1] = "edited"
            elif edited == "both":
                outputs = ["edited"] * len(outputs)
            if reorder:
                parts = conversation.history[-1]["parts"]
                conversation.history[-1]["parts"] = [
                    p for p in parts if "functionCall" not in p
                ] + [p for p in reversed(parts) if "functionCall" in p]
                calls, outputs = calls[::-1], outputs[::-1]
            conversation.results(calls, outputs)

    return execute


@pytest.mark.parametrize(
    "results,reorder,count,executed,edited",
    [
        ("equal", False, 2, None, "none"),
        ("equal", True, 2, None, "none"),
        ("numbered", False, 2, None, "none"),
        ("numbered", True, 2, None, "none"),
        ("equal", False, 3, 2, "none"),
        ("equal", False, 2, None, "one"),
        ("equal", False, 2, None, "both"),
    ],
    ids=[
        "equal results",
        "equal results, reordered",
        "different results",
        "different results, reordered",
        "one of three not executed",
        "one tool message edited",
        "both tool messages edited identically",
    ],
)
def test_identical_google_host_calls_stay_unlinked(
    results: Literal["equal", "numbered"],
    reorder: bool,
    count: int,
    executed: int | None,
    edited: Literal["none", "one", "both"],
    tmp_path: Path,
) -> None:
    """Google calls with the same function and arguments can't be told apart, whatever their results."""
    name = "mcp__host__read_file"
    log = eval(
        Task(
            dataset=[Sample(input="Read a twice.")],
            solver=identical_host_scaffold(results, reorder, executed, edited),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_calls_output(
                    *[
                        ToolCall(id=f"call_{n}", function=name, arguments={"path": "a"})
                        for n in range(count)
                    ]
                ),
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")
    assert_message_ids(sample)

    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert len(events) == (executed or count)
    assert all(e.message_id is None for e in events)


@agent
def cancelled_then_reused_scaffold(dialect: HostDialect) -> Agent:
    """A scaffold that cancels a proposed call, executes a later one under the same id, then sends the cancellation as its result."""

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(_numbered_results())}},
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation(dialect, state.messages[0].text, info)
        cancelled = await conversation.request(bridge)
        conversation.results(cancelled, ["Cancelled."])
        cancellation = conversation.history[-1]
        calls = await conversation.request(bridge)
        [(_, arguments)] = calls
        await call_host_tool(bridge)("host", "read_file", arguments)
        conversation.history = [
            conversation.history[0],
            conversation.history[-1],
            cancellation,
        ]
        await conversation.request(bridge)
        return bridge.state

    return execute


@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic"])
def test_earlier_cancellation_under_a_reused_id_is_not_the_later_calls_result(
    dialect: HostDialect, tmp_path: Path
) -> None:
    """A cancellation already sent for an unexecuted call doesn't link to a later call under its id.

    Sent again after the later reply, it equals the message sent before, so
    it isn't new in that request and the later call doesn't link it.
    """
    name = "mcp__host__read_file"
    log = eval(
        Task(
            dataset=[Sample(input="Read a, then b.")],
            solver=cancelled_then_reused_scaffold(dialect),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                *[
                    tool_calls_output(
                        ToolCall(id="same", function=name, arguments={"path": path})
                    )
                    for path in ["a", "b"]
                ],
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")

    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    [sent] = [m for m in model_events[1].input if m.role == "tool"]
    [returned] = [m for m in model_events[2].input if m.role == "tool"]
    assert returned.text == sent.text
    [event] = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert event.arguments == {"path": "b"}
    assert event.message_id is None


def _replace_value(value: Any, old: str, new: str) -> Any:
    if value == old:
        return new
    if isinstance(value, dict):
        return {k: _replace_value(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_value(v, old, new) for v in value]
    return value


@agent
def scaffold_only_id_scaffold(dialect: HostDialect, answer: str) -> Agent:
    """A scaffold running a local call, then two host calls, sending the first host call under the local call's id with `answer`."""

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(_numbered_results())}},
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation(dialect, state.messages[0].text, info)
        local = await conversation.request(bridge)
        conversation.results(local, ["LOCAL RESULT"])
        start = len(conversation.history)
        calls = await conversation.request(bridge)
        outputs = [
            await call_host_tool(bridge)("host", "read_file", arguments)
            for _, arguments in calls
        ]
        if dialect != "google":
            [(local_id, _)] = local
            host_id = calls[0][0]
            conversation.history[start:] = _replace_value(
                conversation.history[start:], host_id, local_id
            )
            calls[0] = (local_id, calls[0][1])
        conversation.results(calls, [answer, outputs[1]])
        await conversation.request(bridge)
        return bridge.state

    return execute


@pytest.mark.parametrize("answer", ["LOCAL RESULT rewritten", "LOCAL RESULT"])
@pytest.mark.parametrize("dialect", get_args(HostDialect))
def test_host_result_is_not_claimed_through_a_scaffold_only_calls_id(
    dialect: HostDialect, answer: str, tmp_path: Path
) -> None:
    """A copy giving a host call an earlier scaffold-only call's id, and an answer under it, links neither host call.

    The scaffold ran the earlier call itself, so no grant or execution
    records its id. The copy is an edit of the reply, which the bridge
    doesn't place, so neither call's result links (in Google its two results
    of one function can't be told apart either).
    """
    name = "mcp__host__read_file"
    log = eval(
        Task(
            dataset=[Sample(input="Read a locally, then a and b on the host.")],
            solver=scaffold_only_id_scaffold(dialect, answer),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_calls_output(
                    ToolCall(id="local", function="read_file", arguments={"path": "a"})
                ),
                tool_calls_output(
                    ToolCall(id="host_a", function=name, arguments={"path": "a"}),
                    ToolCall(id="host_b", function=name, arguments={"path": "b"}),
                ),
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")
    assert_message_ids(sample)

    events = {e.arguments["path"]: e for e in sample.events if isinstance(e, ToolEvent)}
    assert events["a"].message_id is None
    assert events["b"].message_id is None


@agent
def surrogate_host_scaffold(outcome: Literal["result", "error"]) -> Agent:
    """A Completions scaffold reading two files whose host results, or errors, hold a lone surrogate."""

    async def execute(state: AgentState) -> AgentState:
        tool = (
            AsyncMock(return_value=SURROGATE_TEXT)
            if outcome == "result"
            else AsyncMock(side_effect=ToolError(SURROGATE_TEXT))
        )
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(tool)}},
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation("completions", state.messages[0].text, info)
        while True:
            calls = await conversation.request(bridge)
            if not calls:
                return bridge.state
            [(_, arguments)] = calls
            try:
                await call_host_tool(bridge)("host", "read_file", arguments)
            except ToolError:
                assert outcome == "error"
            # the surrogate's escaped form, as the scaffold's JSON round-trip leaves it
            conversation.results(calls, [ESCAPED_SURROGATE_TEXT])

    return execute


SURROGATE_TEXT = "decoded \ud800 text"
ESCAPED_SURROGATE_TEXT = "decoded \\ud800 text"


@pytest.mark.parametrize("outcome", ["result", "error"])
def test_host_outcome_with_a_lone_surrogate_links_its_result(
    outcome: Literal["result", "error"], tmp_path: Path
) -> None:
    """A lone surrogate in a host result or mapped error doesn't break linking, then or in the next request."""
    name = "mcp__host__read_file"
    log = eval(
        Task(
            dataset=[Sample(input="Read a and b.")],
            solver=surrogate_host_scaffold(outcome),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                *[
                    tool_calls_output(
                        ToolCall(
                            id=f"call_{path}", function=name, arguments={"path": path}
                        )
                    )
                    for path in ["a", "b"]
                ],
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")

    final_input = [e for e in sample.events if isinstance(e, ModelEvent)][-1].input
    results = [m.id for m in final_input if m.role == "tool"]
    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert len(results) == 2
    assert [e.message_id for e in events] == results


@agent
def compacting_host_scaffold(
    dialect: HostDialect,
    results: tuple[str, str],
    copied: bool,
    placed: bool,
    compacted: bool = True,
) -> Agent:
    """A scaffold reading a file in two turns as a host tool, compacting to the latest reply and result, then continuing.

    The tool returns `results[turn]` in each turn. With `copied`, the
    scaffold sends the first result again in place of the latest. With
    `placed`, the scaffold sends the first result, then compacts to the reply
    to it before the second turn, whose reply is then the latest generation's.
    Without `compacted`, the scaffold keeps the full conversation.
    """

    async def execute(state: AgentState) -> AgentState:
        turn = 0
        tool = AsyncMock(side_effect=lambda **_: results[turn])
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(tool)}},
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation(dialect, state.messages[0].text, info)
        summary = _user_turn(dialect, "Summary: read a once.")
        sent: JsonValue = None
        kept = 0
        for turn in range(2):
            kept = len(conversation.history)
            if turn and placed:
                await conversation.request(bridge)
                conversation.history = [
                    summary,
                    conversation.history[-1],
                    _user_turn(dialect, "Read it again."),
                ]
            calls = await conversation.request(bridge)
            outputs = [
                await call_host_tool(bridge)("host", "read_file", arguments)
                for _, arguments in calls
            ]
            sent = outputs[0] if sent is None or not copied else sent
            # a lone surrogate's escaped form, as the scaffold's JSON round-trip leaves it
            escaped = (
                sent.encode(errors="backslashreplace").decode()
                if isinstance(sent, str)
                else sent
            )
            conversation.results(calls, [escaped] * len(calls))
        if compacted and not placed:
            conversation.history = [summary, *conversation.history[kept:]]
        await conversation.request(bridge)
        conversation.history.append(_user_turn(dialect, "Thanks."))
        await conversation.request(bridge)
        return bridge.state

    return execute


def _user_turn(dialect: HostDialect, text: str) -> dict[str, Any]:
    return (
        {"role": "user", "parts": [{"text": text}]}
        if dialect == "google"
        else {"role": "user", "content": text}
    )


@pytest.mark.parametrize(
    "results,parallel,copied,evicted",
    [
        (("contents", "contents"), False, False, False),
        ((SURROGATE_TEXT, SURROGATE_TEXT), False, False, False),
        (("contents", "changed"), False, True, False),
        ((SURROGATE_TEXT, ESCAPED_SURROGATE_TEXT), False, True, False),
        (("contents", "contents"), True, False, False),
        (("contents", "contents"), False, False, True),
    ],
    ids=[
        "equal result",
        "equal lone surrogate",
        "copied",
        "copied over its lone surrogate's escape",
        "parallel then single",
        "earlier reply evicted",
    ],
)
@pytest.mark.parametrize("placed", [True, False], ids=["placed", "unplaced"])
@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
def test_compacted_equal_host_result_shares_its_id_and_links_nothing(
    dialect: HostDialect,
    placed: bool,
    results: tuple[str, str],
    parallel: bool,
    copied: bool,
    evicted: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After compaction, a later call's answer equal to the dropped first answer shares its id and links nothing.

    The provider reuses the call id, so the answer (the later execution's
    equal result, or a copy of the first answer) equals the first answer,
    which compaction dropped. It gets the first answer's id, so it isn't new
    in the request, and which execution it holds can't be told: the later
    call stays unlinked, also in the next request.

    With `parallel`, the first turn makes two identical calls, which can't be
    told apart and stay unlinked. With `evicted`, the bridge no
    longer tracks the first reply when the compacted result arrives. With
    `placed`, the later reply was generated after a compaction that kept a
    later reply, so the bridge places it.
    """
    if evicted:
        monkeypatch.setattr(bridge_types, "_MAX_AWAITED_RESULTS", 1)
    name = "mcp__host__read_file"
    first_calls = [
        # the provider reuses the call id
        ToolCall(id=f"call_{n + 1}", function=name, arguments={"path": "a"})
        for n in range(2 if parallel else 1)
    ]
    log = eval(
        Task(
            dataset=[Sample(input="Read a twice.")],
            solver=compacting_host_scaffold(dialect, results, copied, placed),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_calls_output(*first_calls),
                *([ModelOutput.from_content("mockllm/model", "noted")] * placed),
                tool_calls_output(first_calls[0]),
                *[ModelOutput.from_content("mockllm/model", "done")] * 2,
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")

    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 4 + placed
    first_results = [m.id for m in model_events[1].input if m.role == "tool"]
    [latest_result] = [m.id for m in model_events[-2].input if m.role == "tool"]
    [next_result] = [m.id for m in model_events[-1].input if m.role == "tool"]
    assert next_result == latest_result
    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    # identical parallel calls can't be told apart by the executions they took
    first_links = [None, None] if parallel else first_results
    assert latest_result == first_results[0]
    assert [e.message_id for e in events] == [*first_links, None]


@pytest.mark.parametrize(
    "results,copied",
    [
        (("contents", "changed"), True),
        ((SURROGATE_TEXT, ESCAPED_SURROGATE_TEXT), True),
        (("contents", "changed"), False),
        (("contents", "contents"), False),
    ],
    ids=[
        "copied",
        "copied over its lone surrogate's escape",
        "new result",
        "equal new result",
    ],
)
@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
def test_full_history_host_result_links_to_the_later_calls_answer(
    dialect: HostDialect,
    results: tuple[str, str],
    copied: bool,
    tmp_path: Path,
) -> None:
    """With the full conversation kept, the answer sent after the later reply links to the later call, whatever it holds.

    The provider reuses the call id (Google re-derives call ids), so a copy of
    the earlier answer equals it. Both are in the request, so the copy gets an
    id of its own, new in that request, and it is the later call's answer.
    """
    name = "mcp__host__read_file"
    call = ToolCall(id="call_1", function=name, arguments={"path": "a"})
    log = eval(
        Task(
            dataset=[Sample(input="Read a twice.")],
            solver=compacting_host_scaffold(
                dialect, results, copied, placed=False, compacted=False
            ),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_calls_output(call),
                tool_calls_output(call),
                *[ModelOutput.from_content("mockllm/model", "done")] * 2,
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")

    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 4
    [first_result] = [m.id for m in model_events[1].input if m.role == "tool"]
    first, latest = [m for m in model_events[-2].input if m.role == "tool"]
    assert first.id == first_result
    assert [m.id for m in model_events[-1].input if m.role == "tool"] == [
        first.id,
        latest.id,
    ]
    assert latest.id != first.id
    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert [e.message_id for e in events] == [first.id, latest.id]


@pytest.mark.parametrize("resumed", [False, True], ids=["live", "resumed"])
@pytest.mark.parametrize("sent", ["copy", "own"])
@pytest.mark.parametrize(
    "answered", ["before start", "while running", "after completion"]
)
@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
async def test_answer_sent_before_its_execution_completes_links_nothing(
    dialect: HostDialect, answered: str, sent: str, resumed: bool
) -> None:
    """An answer sent before an execution of its call completes never links that execution.

    The call runs on `a` returning "OLD", and its answer links. The scaffold
    compacts that exchange away and an equal call under the same id runs on
    `a` returning "NEW". It answers that call with a copy of the "OLD"
    answer (or, as a control, its own answer: "NEW" once the execution has
    completed, else a timeout message) `answered` relative to the execution,
    then resends the conversation. An answer sent before the execution
    completed can't hold its result. With `resumed`, the later call is made
    to a bridge resumed from a checkpoint taken after the first answer.
    """
    outputs = [
        tool_calls_output(
            ToolCall(id="call_1", function="read_file", arguments={"path": "p"}),
            content="Reading p.",
        ),
        ModelOutput.from_content("mockllm/model", "Noted."),
        tool_calls_output(
            ToolCall(id="call_1", function="read_file", arguments={"path": "p"}),
            content="Reading p again.",
        ),
        *[ModelOutput.from_content("mockllm/model", "Done.")] * 2,
    ]
    model = get_model("mockllm/model", custom_outputs=outputs)
    started, release = anyio.Event(), anyio.Event()
    executions = 0

    async def result(**_: Any) -> str:
        nonlocal executions
        executions += 1
        if executions == 1:
            return "OLD"
        started.set()
        await release.wait()
        return "NEW"

    def host_bridge(checkpointer: RecordingCheckpointer) -> SandboxAgentBridge:
        return SandboxAgentBridge(
            state=AgentState(messages=[ChatMessageUser(content="Read p.")]),
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            model_aliases={"inspect": model},
            bridged_tools={
                "a": {"read_file": read_file(AsyncMock(side_effect=result))}
            },
            checkpointer=checkpointer,
        )

    checkpointer = RecordingCheckpointer()
    bridge = host_bridge(checkpointer)
    [info] = declare("read_file")
    conversation = _HostConversation(dialect, "Read p.", info)
    with recorded_transcript() as recorded:
        first = await conversation.request(bridge)
        await call_host_tool(bridge)("a", "read_file", first[0][1])
        conversation.results(first, ["OLD"])
        await conversation.request(bridge)
        if resumed:
            bridge = host_bridge(
                RecordingCheckpointer(
                    restored=json.loads(json.dumps(checkpointer.snapshot())),
                    serialized=True,
                )
            )
        conversation.history = [_user_turn(dialect, "Summary: p reads OLD.")]
        second = await conversation.request(bridge)

        async def execute() -> None:
            await call_host_tool(bridge)("a", "read_file", second[0][1])

        async def answer() -> None:
            own = "NEW" if answered == "after completion" else "Timed out."
            conversation.results(second, ["OLD" if sent == "copy" else own])
            await conversation.request(bridge)

        if answered == "before start":
            await answer()
            release.set()
            await execute()
        elif answered == "while running":
            async with anyio.create_task_group() as tg:
                tg.start_soon(execute)
                await started.wait()
                await answer()
                release.set()
        else:
            release.set()
            await execute()
            await answer()
        conversation.history.append(_user_turn(dialect, "Continue."))
        await conversation.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [latest] = [m.id for m in model_events[-1].input if m.role == "tool"]
    tool_events = [e for e in recorded.events if isinstance(e, ToolEvent)]
    assert [e.result for e in tool_events] == ["OLD", "NEW"]
    assert tool_events[0].message_id is not None
    linked = sent == "own" and answered == "after completion"
    assert tool_events[-1].message_id == (latest if linked else None)


def _without_text(dialect: HostDialect, reply: list[dict[str, Any]]) -> list[Any]:
    """`reply`'s wire items with its assistant text removed, keeping its calls."""
    match dialect:
        case "completions":
            return [{k: v for k, v in item.items() if k != "content"} for item in reply]
        case "responses":
            return [item for item in reply if item.get("type") != "message"]
        case "anthropic":
            return [
                {
                    **item,
                    "content": [b for b in item["content"] if b["type"] != "text"],
                }
                for item in reply
            ]
        case "google":
            return [
                {**item, "parts": [p for p in item["parts"] if "text" not in p]}
                for item in reply
            ]


_RESENT_FORMS = [
    *[
        (dialect, resent)
        for dialect in ["completions", "responses", "anthropic"]
        for resent in [
            "listed timeout",
            "string timeout",
            "listed empty",
            "string empty",
            "listed result",
            "padded timeout",
            "padded empty",
            "padded result",
        ]
    ],
    ("anthropic", "listed error"),
    ("anthropic", "string error"),
    ("anthropic", "padded error"),
    ("anthropic", "padded empty error"),
]


@pytest.mark.parametrize("dialect,resent", _RESENT_FORMS)
async def test_answer_resent_in_another_form_is_not_a_new_answer(
    dialect: HostDialect, resent: str
) -> None:
    """An answer sent while the execution ran stays sent when it comes back in another form.

    While `read_file` runs, the scaffold sends a compacted context: a
    summary, the reply without its text, and an answer (a timeout, an
    empty answer, or with `error` an Anthropic error). Once the execution
    completes, it continues the original thread with that answer again, as
    a list of text parts (`listed`, none for the empty answer; `padded`
    between empty text parts) or as the string it was. Each is the answer
    sent before the execution completed, so the execution links nothing. As
    a control, the execution's own result sent as a list (`listed result`,
    `padded result`) links.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_1", function="read_file", arguments={"path": "p"}),
                content="Reading p.",
            ),
            *[ModelOutput.from_content("mockllm/model", "Noted.")] * 2,
        ],
    )
    started, release = anyio.Event(), anyio.Event()

    async def result(**_: Any) -> str:
        started.set()
        await release.wait()
        return "NEW"

    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read p.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={"a": {"read_file": read_file(AsyncMock(side_effect=result))}},
    )
    [info] = declare("read_file")
    conversation = _HostConversation(dialect, "Read p.", info)
    sent = "" if "empty" in resent else "Timed out."
    error = resent.endswith("error")
    fresh = resent.endswith("result")
    with recorded_transcript() as recorded:
        calls = await conversation.request(bridge)
        original = list(conversation.history)

        async def execute() -> None:
            await call_host_tool(bridge)("a", "read_file", calls[0][1])

        async with anyio.create_task_group() as tg:
            tg.start_soon(execute)
            await started.wait()
            conversation.history = [
                _user_turn(dialect, "Summary: reading p."),
                *_without_text(dialect, original[1:]),
            ]
            conversation.results(calls, [sent], error=error)
            await conversation.request(bridge)
            release.set()
        conversation.history = original
        conversation.results(
            calls,
            ["NEW" if fresh else sent],
            listed=resent.startswith(("listed", "padded")),
            error=error,
            padded=resent.startswith("padded"),
        )
        await conversation.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [latest] = [m.id for m in model_events[-1].input if m.role == "tool"]
    [event] = [e for e in recorded.events if isinstance(e, ToolEvent)]
    assert event.result == "NEW"
    assert event.message_id == (latest if fresh else None)


@pytest.mark.parametrize("resent", ["timeout", "listed timeout", "result"])
@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
async def test_answer_sent_while_a_reused_call_id_ran_links_nothing(
    dialect: HostDialect, resent: str
) -> None:
    """An answer sent while a call ran links nothing, also when an earlier call under its id had the same answer.

    The provider reuses the call id (Google derives it from the call), and
    the first call's answer is a timeout. While the second call runs, the
    scaffold sends a compacted context with the same timeout answer, which
    takes the first answer's id. Once the execution completes, it continues
    the full conversation with that timeout again (as a string, or as a list
    of one text part where the dialect allows one), so the request holds two
    equal answers. The second was sent before the execution completed and
    links nothing. As a control, the execution's own result links.
    """
    if dialect == "google" and resent == "listed timeout":
        pytest.skip("Google results are JSON objects")
    call = ToolCall(id="call_1", function="read_file", arguments={"path": "p"})
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(call, content="Reading p."),
            tool_calls_output(call, content="Reading p again."),
            *[ModelOutput.from_content("mockllm/model", "Noted.")] * 2,
        ],
    )
    started, release = anyio.Event(), anyio.Event()
    executions = 0

    async def result(**_: Any) -> str:
        nonlocal executions
        executions += 1
        if executions == 1:
            return "OLD"
        started.set()
        await release.wait()
        return "NEW"

    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read p.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={"a": {"read_file": read_file(AsyncMock(side_effect=result))}},
    )
    [info] = declare("read_file")
    conversation = _HostConversation(dialect, "Read p.", info)
    with recorded_transcript() as recorded:
        first = await conversation.request(bridge)
        await call_host_tool(bridge)("a", "read_file", first[0][1])
        conversation.results(first, ["Timed out."])
        second = await conversation.request(bridge)
        original = list(conversation.history)

        async def execute() -> None:
            await call_host_tool(bridge)("a", "read_file", second[0][1])

        async with anyio.create_task_group() as tg:
            tg.start_soon(execute)
            await started.wait()
            conversation.history = [
                _user_turn(dialect, "Summary: reading p."),
                *_without_text(dialect, original[-1:]),
            ]
            conversation.results(second, ["Timed out."])
            await conversation.request(bridge)
            release.set()
        conversation.history = original
        conversation.results(
            second,
            ["NEW" if resent == "result" else "Timed out."],
            listed=resent == "listed timeout",
        )
        await conversation.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    answers = [m.id for m in model_events[-1].input if m.role == "tool"]
    events = [e for e in recorded.events if isinstance(e, ToolEvent)]
    assert [e.result for e in events] == ["OLD", "NEW"]
    assert events[0].message_id == answers[0]
    assert events[1].message_id == (answers[1] if resent == "result" else None)


@pytest.mark.parametrize("side", [True, False], ids=["side request", "none"])
@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
async def test_equal_earlier_answer_copied_while_a_call_runs_keeps_its_link(
    dialect: HostDialect, side: bool
) -> None:
    """A side request copying an equal earlier answer of another call leaves the running call's link.

    The reply reads `a`, answered "File written.". The next reads `b`. While
    it runs, the scaffold sends a side request (a loop check) with its own
    prompt and a copy of the conversation up to `a`'s answer. Once `b` completes, its own result, also "File
    written.", links: the copied answer answers `a`, also in Google, whose
    results name only their function.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_a", function="read_file", arguments={"path": "a"})
            ),
            tool_calls_output(
                ToolCall(id="call_b", function="read_file", arguments={"path": "b"})
            ),
            *[ModelOutput.from_content("mockllm/model", "Noted.")] * 2,
        ],
    )
    started, release = anyio.Event(), anyio.Event()

    async def result(path: str) -> str:
        if path == "b":
            started.set()
            await release.wait()
        return "File written."

    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a, then b.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={"h": {"read_file": read_file(AsyncMock(side_effect=result))}},
    )
    [info] = declare("read_file")
    conversation = _HostConversation(dialect, "Read a, then b.", info)
    with recorded_transcript() as recorded:
        first = await conversation.request(bridge)
        await call_host_tool(bridge)("h", "read_file", first[0][1])
        conversation.results(first, ["File written."])
        copied = list(conversation.history)
        second = await conversation.request(bridge)
        original = list(conversation.history)

        async def execute() -> None:
            await call_host_tool(bridge)("h", "read_file", second[0][1])

        async with anyio.create_task_group() as tg:
            tg.start_soon(execute)
            await started.wait()
            if side:
                conversation.history = [
                    _user_turn(dialect, "Check this conversation for loops."),
                    *copied[1:],
                ]
                await conversation.request(bridge)
            release.set()
        conversation.history = original
        conversation.results(second, ["File written."])
        await conversation.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    answers = [m.id for m in model_events[-1].input if m.role == "tool"]
    events = [e for e in recorded.events if isinstance(e, ToolEvent)]
    assert [e.message_id for e in events] == answers


@pytest.mark.parametrize(
    "reuse",
    ["while both run", "while one runs", "after both complete", "none"],
)
@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
async def test_reply_reused_unplaced_while_its_calls_run_links_nothing(
    dialect: HostDialect, reuse: str
) -> None:
    """A reply resent unplaced keeps its calls unlinked, also those whose executions complete after.

    The reply reads `p` and lists `d`, both host tools. The scaffold runs
    both in the background, sending a placeholder answer for each in the
    reply's thread while they run. It then sends the reply again after a
    summary (a compacted context), which places no thread, so the reply
    takes the id it was sent with: which reply it is can't be told. `reuse`
    is when, relative to the executions. The scaffold then sends the
    executions' results in the compacted context, where the reply is placed.
    No result links. With no reuse (`none`), the scaffold sends the results
    in the reply's thread once both executions completed, and both link.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_read", function="read_file", arguments={"path": "p"}),
                ToolCall(id="call_list", function="list_dir", arguments={"path": "d"}),
                content="Reading p and listing d.",
            ),
            *[ModelOutput.from_content("mockllm/model", "Noted.")] * 3,
        ],
    )
    started = {"p": anyio.Event(), "d": anyio.Event()}
    release = {"p": anyio.Event(), "d": anyio.Event()}
    completed = {"p": anyio.Event(), "d": anyio.Event()}

    async def result(path: str) -> str:
        started[path].set()
        await release[path].wait()
        return f"{path} result"

    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read p, list d.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "host": {
                "read_file": read_file(AsyncMock(side_effect=result)),
                "list_dir": served_tool(
                    AsyncMock(side_effect=result), description=LIST_DIR, name="list_dir"
                ),
            }
        },
    )
    [read_info] = declare("read_file")
    [list_info] = declare("list_dir", description=LIST_DIR)
    conversation = _HostConversation(
        dialect, "Read p, list d.", read_info, others=[list_info]
    )
    with recorded_transcript() as recorded:
        calls = await conversation.request(bridge)
        assert [arguments for _, arguments in calls] == [{"path": "p"}, {"path": "d"}]
        reply = conversation.history[1:]

        async def execute(tool: str, arguments: dict[str, Any]) -> None:
            await call_host_tool(bridge)("host", tool, arguments)
            completed[arguments["path"]].set()

        async def complete(path: str) -> None:
            release[path].set()
            await completed[path].wait()

        async with anyio.create_task_group() as tg:
            for (_, arguments), tool in zip(calls, ["read_file", "list_dir"]):
                tg.start_soon(execute, tool, arguments)
            for event in started.values():
                await event.wait()
            if reuse != "none":
                conversation.results(calls, ["Running in background."] * 2)
                await conversation.request(bridge)
                if reuse == "while one runs":
                    await complete("p")
                elif reuse == "after both complete":
                    await complete("p")
                    await complete("d")
                copied = [
                    _user_turn(dialect, "Summary: reading p, listing d."),
                    *reply,
                ]
                conversation.history = list(copied)
                await conversation.request(bridge)
                conversation.history = copied
            for path in started:
                release[path].set()
        conversation.results(calls, ["p result", "d result"])
        await conversation.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    answers = [m.id for m in model_events[-1].input if m.role == "tool"][-2:]
    tool_events = [e for e in recorded.events if isinstance(e, ToolEvent)]
    assert sorted(str(e.result) for e in tool_events) == ["d result", "p result"]
    expected = answers if reuse == "none" else [None, None]
    links = {e.function: e.message_id for e in tool_events}
    assert [links["read_file"], links["list_dir"]] == expected


@pytest.mark.parametrize(
    "shape",
    [
        "cached retry, evicted",
        "cached retry, kept",
        "uncached retry, evicted",
        "uncached retry, kept",
        "cached, no retry",
    ],
)
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_reply_handed_out_again_links_no_execution(
    dialect: HostDialect, shape: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A reply handed out a second time (a cached retry) links none of its executions.

    The scaffold executes the reply's call and holds the answer. With
    `evicted`, it then runs `_MAX_AWAITED_RESULTS` unrelated host calls, so
    the bridge stops tracking the first execution. It retries the first
    request, which with caching hands out the same reply again, and executes
    the call again (a different result). It then sends the first execution's
    answer in the original thread. Neither execution links: which execution
    the answer holds is unknown. An uncached retry hands out a new reply (with
    other text, so that Google's wire form, which has no call ids, tells the
    two apart), but its identical call runs while the first execution awaits
    its answer, so it may be a retry of that call and neither links either;
    with no retry, a cached generation links as any other.
    """
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "cache"))
    cached = shape.startswith("cached")
    retry = "no retry" not in shape
    unrelated = bridge_types._MAX_AWAITED_RESULTS if "evicted" in shape else 0
    main_output = tool_calls_output(
        ToolCall(id="call_main", function="read_file", arguments={"path": "a"}),
        content="Reading.",
    )
    model = get_model(
        "mockllm/model",
        config=GenerateConfig(cache=cached),
        custom_outputs=[
            main_output,
            *(
                [
                    tool_calls_output(
                        *(
                            ToolCall(
                                id=f"call_list_{n}",
                                function="list_dir",
                                arguments={"path": f"d{n}"},
                            )
                            for n in range(unrelated)
                        )
                    )
                ]
                if unrelated
                else []
            ),
            *(
                [
                    tool_calls_output(
                        ToolCall(
                            id="call_retry",
                            function="read_file",
                            arguments={"path": "a"},
                        ),
                        content="Reading a.",
                    )
                ]
                if retry and not cached
                else []
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "host": {
                "read_file": read_file(AsyncMock(side_effect=["first", "second"])),
                "list_dir": served_tool(
                    AsyncMock(return_value="listed"),
                    description=LIST_DIR,
                    name="list_dir",
                ),
            }
        },
    )
    [read_info] = declare("read_file")
    [list_info] = declare("list_dir", description=LIST_DIR)
    with recorded_transcript() as recorded:
        main = _HostConversation(dialect, "Read a.", read_info)
        main_calls = await main.request(bridge)
        [(_, arguments)] = main_calls
        first = await call_host_tool(bridge)("host", "read_file", arguments)
        if unrelated:
            sub = _HostConversation(dialect, "Sub-agent: list.", list_info)
            listed = await sub.request(bridge)
            assert len(listed) == unrelated
            for _, list_arguments in listed:
                await call_host_tool(bridge)("host", "list_dir", list_arguments)
        if retry:
            again = _HostConversation(dialect, "Read a.", read_info)
            [(_, retried)] = await again.request(bridge)
            await call_host_tool(bridge)("host", "read_file", retried)
        main.results(main_calls, [first])
        await main.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    if retry:
        assert (
            model_events[-2].output.message.id == model_events[0].output.message.id
        ) == cached
    [answer] = [m.id for m in model_events[-1].input if m.role == "tool"]
    reads = [
        e
        for e in recorded.events
        if isinstance(e, ToolEvent) and e.function == "read_file"
    ]
    assert [e.result for e in reads] == (["first", "second"] if retry else ["first"])
    first_link = answer if not unrelated and not retry else None
    assert [e.message_id for e in reads] == [first_link, *([None] if retry else [])]


@pytest.mark.parametrize("cached", [True, False], ids=["cached", "uncached"])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_reply_handed_out_again_after_resume_links_no_execution(
    dialect: HostDialect, cached: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A reply handed out before a checkpoint and again after resuming from it links nothing.

    The resumed bridge has no record of the first execution, but its
    checkpoint knows the reply's id. With caching, the retry after the resume
    hands out the same reply, and the first execution's answer, sent after the
    second execution, links neither. Without caching the retry's reply is new,
    and its execution links its own answer.
    """
    monkeypatch.setenv("INSPECT_CACHE_DIR", str(tmp_path / "cache"))
    model = get_model(
        "mockllm/model",
        config=GenerateConfig(cache=cached),
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_main", function="read_file", arguments={"path": "a"}),
                content="Reading.",
            ),
            *(
                []
                if cached
                else [
                    tool_calls_output(
                        ToolCall(
                            id="call_retry",
                            function="read_file",
                            arguments={"path": "a"},
                        ),
                        content="Reading a.",
                    )
                ]
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    tools = {
        "host": {"read_file": read_file(AsyncMock(side_effect=["first", "second"]))}
    }

    def bridge(checkpointer: RecordingCheckpointer) -> SandboxAgentBridge:
        return SandboxAgentBridge(
            state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            model_aliases={"inspect": model},
            bridged_tools=tools,
            checkpointer=checkpointer,
        )

    [info] = declare("read_file")
    checkpointer = _TickCheckpointer()
    with recorded_transcript() as recorded:
        original = bridge(checkpointer)
        main = _HostConversation(dialect, "Read a.", info)
        main_calls = await main.request(original)
        [(_, arguments)] = main_calls
        first = await call_host_tool(original)("host", "read_file", arguments)
        resumed = bridge(
            RecordingCheckpointer(restored=checkpointer.saved, serialized=True)
        )
        again = _HostConversation(dialect, "Read a.", info)
        again_calls = await again.request(resumed)
        [(_, retried)] = again_calls
        second = await call_host_tool(resumed)("host", "read_file", retried)
        if cached:
            main.results(main_calls, [first])
            await main.request(resumed)
        else:
            again.results(again_calls, [second])
            await again.request(resumed)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    assert (
        model_events[1].output.message.id == model_events[0].output.message.id
    ) == cached
    [answer] = [m.id for m in model_events[-1].input if m.role == "tool"]
    reads = [e for e in recorded.events if isinstance(e, ToolEvent)]
    assert [e.result for e in reads] == ["first", "second"]
    assert [e.message_id for e in reads] == [None, None if cached else answer]


@pytest.mark.parametrize("evicted", ["own grant", "other grant"])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_reply_whose_grant_is_evicted_links_no_execution(
    dialect: HostDialect, evicted: str
) -> None:
    """A reply that loses an execution grant to eviction links none of its executions.

    Servers `a` and `b` serve the same description, so the reply's call is
    granted once for each; `a` is registered with `require_proposal=False`.
    With `own grant`, a sub-agent's unconsumed calls fill the grant store and
    evict the call's grant for `a`, so its execution there runs ungranted and
    untracked; the execution on `b` then holds the call's only grant, and the
    scaffold sends `a`'s answer. Neither execution links. With `other grant`,
    the sub-agent's calls come first and the call's grants evict theirs; the
    call runs once, on `b`, and links its answer.
    """
    filler = _MAX_TOOL_EXECUTION_GRANTS - 1
    main_output = tool_calls_output(
        ToolCall(id="call_main", function="read_file", arguments={"path": "a"}),
        content="Reading.",
    )
    sub_output = tool_calls_output(
        *(
            ToolCall(
                id=f"call_list_{n}", function="list_dir", arguments={"path": f"d{n}"}
            )
            for n in range(filler + (2 if evicted == "other grant" else 0))
        )
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            *(
                [main_output, sub_output]
                if evicted == "own grant"
                else [sub_output, main_output]
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "a": {"read_file": read_file(AsyncMock(return_value="from a"))},
            "b": {"read_file": read_file(AsyncMock(return_value="from b"))},
            "other": {
                "list_dir": served_tool(
                    AsyncMock(return_value="listed"),
                    description=LIST_DIR,
                    name="list_dir",
                )
            },
        },
        proposal_exempt_servers={"a"},
    )
    [read_info] = declare("read_file")
    [list_info] = declare("list_dir", description=LIST_DIR)
    main = _HostConversation(dialect, "Read a.", read_info)
    sub = _HostConversation(dialect, "Sub-agent: list.", list_info)
    with recorded_transcript() as recorded:
        if evicted == "other grant":
            await sub.request(bridge)
        main_calls = await main.request(bridge)
        if evicted == "own grant":
            await sub.request(bridge)
        assert len(bridge._tool_execution_grants) == _MAX_TOOL_EXECUTION_GRANTS
        [(_, arguments)] = main_calls
        outputs = []
        if evicted == "own grant":
            outputs.append(await call_host_tool(bridge)("a", "read_file", arguments))
        await call_host_tool(bridge)("b", "read_file", arguments)
        if evicted == "other grant":
            outputs.append("from b")
        main.results(main_calls, outputs)
        await main.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [answer] = [m.id for m in model_events[-1].input if m.role == "tool"]
    reads = [e for e in recorded.events if isinstance(e, ToolEvent)]
    if evicted == "own grant":
        assert [(bridge_metadata(e)["server"], e.result) for e in reads] == [
            ("a", "from a"),
            ("b", "from b"),
        ]
        assert [e.message_id for e in reads] == [None, None]
    else:
        assert [e.result for e in reads] == ["from b"]
        assert [e.message_id for e in reads] == [answer]


@pytest.mark.parametrize(
    "shape",
    ["unproposed call first", "proposed call only", "requires proposals"],
)
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_execution_on_an_exempt_server_links_nothing(
    dialect: HostDialect, shape: str
) -> None:
    """An execution on a `require_proposal=False` server never links its result message.

    There, a call the model did not propose (from code the model wrote, say)
    with a pending proposal's arguments takes that proposal's grant, and the
    proposed call runs ungranted. With `unproposed call first`, the proposed
    call's answer would otherwise link to the unproposed call's execution.
    The control, a server that requires proposals, links its one execution.
    """
    exempt = shape != "requires proposals"
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_main", function="read_file", arguments={"path": "a"}),
                content="Reading.",
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "host": {"read_file": read_file(AsyncMock(side_effect=["first", "second"]))}
        },
        proposal_exempt_servers={"host"} if exempt else None,
    )
    [info] = declare("read_file")
    main = _HostConversation(dialect, "Read a.", info)
    with recorded_transcript() as recorded:
        main_calls = await main.request(bridge)
        [(_, arguments)] = main_calls
        if shape == "unproposed call first":
            await call_host_tool(bridge)("host", "read_file", arguments)
        output = await call_host_tool(bridge)("host", "read_file", arguments)
        main.results(main_calls, [output])
        await main.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [answer] = [m.id for m in model_events[-1].input if m.role == "tool"]
    reads = [e for e in recorded.events if isinstance(e, ToolEvent)]
    if shape == "unproposed call first":
        assert [(e.result, bridge_metadata(e)["grant"]) for e in reads] == [
            ("first", "consumed"),
            ("second", "exempt"),
        ]
        assert [e.message_id for e in reads] == [None, None]
    else:
        assert [e.result for e in reads] == ["first"]
        assert [e.message_id for e in reads] == [None if exempt else answer]


@pytest.mark.parametrize("later", [False, True], ids=["control", "later ambiguity"])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_execution_made_ambiguous_after_it_completed_links_nothing(
    dialect: HostDialect, later: bool
) -> None:
    """An execution that completed before a later one made its proposal ambiguous links nothing.

    Servers `a` and `b` serve the same description, so the reply's call is
    granted once on each. The call carries a bookkeeping field the scaffold
    drops when it executes (matched with undeclared keys dropped). It runs on
    `a` and its answer is held. A sub-agent's reply then proposes the call
    without the field, and the scaffold runs the call again on `b`: that
    execution matches both proposals, so which one it ran is unknown, and
    the answer the scaffold sends holds `b`'s result. `a`'s execution, which
    was already awaiting its answer, stays unlinked. With no sub-agent
    (`control`), `a`'s answer links.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(
                    id="call_main",
                    function="read_file",
                    arguments={"path": "a", "unexpected": "metadata"},
                ),
                content="Reading.",
            ),
            *(
                [
                    tool_calls_output(
                        ToolCall(
                            id="call_sub", function="read_file", arguments={"path": "a"}
                        ),
                        content="On it.",
                    )
                ]
                if later
                else []
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "a": {"read_file": read_file(AsyncMock(return_value="from a"))},
            "b": {"read_file": read_file(AsyncMock(return_value="from b"))},
        },
    )
    [info] = declare("read_file")
    main = _HostConversation(dialect, "Read a.", info)
    sub = _HostConversation(dialect, "Sub-agent: read a.", info)
    with recorded_transcript() as recorded:
        calls = await main.request(bridge)
        output = await call_host_tool(bridge)("a", "read_file", {"path": "a"})
        if later:
            await sub.request(bridge)
            output = await call_host_tool(bridge)("b", "read_file", {"path": "a"})
        main.results(calls, [output])
        await main.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [answer] = [m.id for m in model_events[-1].input if m.role == "tool"]
    reads = [e for e in recorded.events if isinstance(e, ToolEvent)]
    if later:
        assert [e.result for e in reads] == ["from a", "from b"]
        assert [e.message_id for e in reads] == [None, None]
    else:
        assert [e.result for e in reads] == ["from a"]
        assert [e.message_id for e in reads] == [answer]


@pytest.mark.parametrize(
    "retry",
    [
        "none",
        "denied after it completed",
        "denied while it runs",
        "denied with unreadable arguments",
        "other call denied",
    ],
)
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_execution_whose_call_is_denied_again_links_nothing(
    dialect: HostDialect, retry: str
) -> None:
    """An execution whose call the scaffold sends again, and the bridge denies, links nothing.

    The call's one grant is consumed by its execution, so a retry (a client
    that lost the first response, say) is denied, and the scaffold may send
    the denial as the call's answer. The execution stays unlinked whether the
    retry comes after it completed or while it runs, and when the retry's
    arguments can't be read (so it may be any call of the tool). A denied call
    with other arguments is not a retry of the call, which links; so does the
    call with no retry (`none`).
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_main", function="read_file", arguments={"path": "a"}),
                content="Reading.",
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    started = anyio.Event()
    release = anyio.Event()

    async def result(**_: Any) -> str:
        started.set()
        await release.wait()
        return "successful first result"

    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={"host": {"read_file": read_file(AsyncMock(side_effect=result))}},
    )
    retried: JsonValue = (
        "a"
        if retry == "denied with unreadable arguments"
        else {"path": "b" if retry == "other call denied" else "a"}
    )

    async def denied() -> str:
        with pytest.raises(PermissionError) as raised:
            await call_host_tool(bridge)("host", "read_file", retried)
        return str(raised.value)

    [info] = declare("read_file")
    main = _HostConversation(dialect, "Read a.", info)
    with recorded_transcript() as recorded:
        calls = await main.request(bridge)
        [(_, arguments)] = calls
        outputs: list[JsonValue] = []

        async def execute() -> None:
            outputs.append(await call_host_tool(bridge)("host", "read_file", arguments))

        async with anyio.create_task_group() as tg:
            tg.start_soon(execute)
            await started.wait()
            if retry == "denied while it runs":
                outputs.append(await denied())
            release.set()
        if retry not in ("none", "denied while it runs"):
            outputs.append(await denied())
        main.results(calls, [outputs[-1]])
        await main.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [answer] = [m.id for m in model_events[-1].input if m.role == "tool"]
    events = [e for e in recorded.events if isinstance(e, ToolEvent)]
    [execution] = [e for e in events if bridge_metadata(e)["grant"] == "consumed"]
    assert execution.result == "successful first result"
    assert [e.message_id for e in events if e is not execution] == [None] * (
        len(events) - 1
    )
    linked = retry in ("none", "other call denied")
    assert execution.message_id == (answer if linked else None)


def _recording_bridge() -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={},
        bridged_tools={
            "host": {
                "read_file": read_file(AsyncMock()),
                "list_dir": served_tool(AsyncMock(), name="list_dir"),
            }
        },
    )


def _execute(
    bridge: SandboxAgentBridge, reply_id: str, calls: list[ToolCall]
) -> list[ToolEvent]:
    """Hand out a reply with `calls` and execute each on host server `host`; the events."""
    handed = handed_calls(bridge, reply_id, calls)
    events = []
    for call, handed_call in zip(calls, handed):
        bridge._record_execution(
            _ToolExecutionGrant(
                "host",
                call.function,
                call.arguments,
                _Proposal(call, None, reply_id, handed_call),
            )
        )
        event = ToolEvent(
            id=call.id, function=call.function, arguments=call.arguments, result="ok"
        )
        bridge._await_result_message(handed_call, event)
        events.append(event)
    return events


def _answer(
    bridge: SandboxAgentBridge,
    reply_id: str,
    calls: list[ToolCall],
    answered: list[int],
) -> None:
    """Send the reply back with fresh answers to the calls at `answered`."""
    answers = [
        ChatMessageTool(
            id=f"{reply_id}-result-{n}",
            content="ok",
            tool_call_id=calls[n].id,
            function=calls[n].function,
        )
        for n in answered
    ]
    bridge._link_result_messages(
        [ChatMessageAssistant(id=reply_id, content="", tool_calls=calls), *answers],
        {0: reply_id},
        set(range(1, len(answers) + 1)),
        set(),
        {},
    )


def test_settled_executions_are_pruned_from_the_tool_index() -> None:
    """Repeated settled executions of one call keep the per-tool record bounded."""
    bridge = _recording_bridge()
    call = ToolCall(id="call", function="read_file", arguments={"path": "a"})
    for n in range(1000):
        [event] = _execute(bridge, f"reply-{n}", [call])
        _answer(bridge, f"reply-{n}", [call], [0])
        assert event.message_id == f"reply-{n}-result-0"

    assert len(bridge._executed_tools[("host", "read_file")].calls) <= 16


@pytest.mark.parametrize(
    "denied", [None, {"path": "a"}], ids=["unreadable arguments", "same call"]
)
@pytest.mark.parametrize("read", ["settled", "awaiting its answer"])
def test_denial_keeps_a_settled_calls_reply_linked(
    read: str, denied: dict[str, Any] | None
) -> None:
    """A denied call unlinks only replies whose call it may repeat may still link.

    The reply runs `read_file` and `list_dir`. Once `read_file`'s answer has
    linked, a denied `read_file` call (with unreadable arguments, or the same
    ones) can't be its answer, so the reply's pending `list_dir` call still
    links. While `read_file` awaits its answer, the denial may be it, so the
    reply is unlinked.
    """
    bridge = _recording_bridge()
    calls = [
        ToolCall(id="call_read", function="read_file", arguments={"path": "a"}),
        ToolCall(id="call_list", function="list_dir", arguments={"path": "d"}),
    ]
    events = _execute(bridge, "reply", calls)
    if read == "settled":
        _answer(bridge, "reply", calls, [0])

    bridge.unlink_denied_call("host", "read_file", denied)
    _answer(bridge, "reply", calls, [0, 1])

    if read == "settled":
        assert [e.message_id for e in events] == ["reply-result-0", "reply-result-1"]
    else:
        assert [e.message_id for e in events] == [None, None]


@pytest.mark.parametrize(
    "recorded",
    [
        "nothing",
        "another tool executed",
        "executed",
        "executed, then an unreadable denial",
        "pending grant",
    ],
)
def test_denial_hashes_arguments_only_when_a_call_of_the_tool_is_recorded(
    recorded: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A denied call hashes its arguments only when it may repeat a recorded call.

    Hashing serializes the whole arguments, so a large denied call of a tool
    with no executed call or pending grant must not pay for it. An unreadable
    denial drops the tool's per-tool record but leaves its per-key record,
    which a later denial still checks.
    """
    bridge = _recording_bridge()
    call = ToolCall(id="call", function="read_file", arguments={"path": "a"})
    if recorded == "another tool executed":
        _execute(
            bridge,
            "reply",
            [ToolCall(id="call", function="list_dir", arguments={"path": "a"})],
        )
    elif recorded.startswith("executed"):
        _execute(bridge, "reply", [call])
        if recorded == "executed, then an unreadable denial":
            bridge.unlink_denied_call("host", "read_file", None)
            assert ("host", "read_file") not in bridge._executed_tools
    elif recorded == "pending grant":
        [handed] = handed_calls(bridge, "reply", [call])
        bridge._tool_execution_grants.append(
            _ToolExecutionGrant(
                "host",
                "read_file",
                call.arguments,
                _Proposal(call, None, "reply", handed),
            )
        )
    hashed: list[dict[str, Any]] = []
    call_keys = bridge._call_keys

    def spy(server: str, tool: str, arguments: dict[str, Any]) -> set[str]:
        hashed.append(arguments)
        return call_keys(server, tool, arguments)

    monkeypatch.setattr(bridge, "_call_keys", spy)
    bridge.unlink_denied_call("host", "read_file", {"path": "a"})

    assert bool(hashed) is (recorded not in ("nothing", "another tool executed"))


@pytest.mark.parametrize("later_call", ["denied", "takes a third grant"])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_call_whose_grant_was_evicted_taking_a_later_replys_grant_links_nothing(
    dialect: HostDialect, later_call: str
) -> None:
    """A call whose grant was evicted, run on a later reply's identical grant, leaves that reply unlinked.

    A sub-agent's unconsumed calls evict the first reply's grant. A later
    reply proposes the same call, and the scaffold then runs the first
    reply's call, which takes the later reply's grant: matching no longer
    knows the first reply, so the execution pairs with the later one. The
    later reply's own call is then denied, which unlinks it, so its answer
    (the denial) doesn't link to the execution that ran the first reply's
    call. When a third reply proposes the call before that, the later
    reply's own call takes the third reply's grant instead: the execution
    paired with the later reply is still awaiting its answer, so both
    replies are unlinked.
    """
    call: dict[str, JsonValue] = {"path": "a"}
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_first", function="read_file", arguments=call),
                content="Reading.",
            ),
            tool_calls_output(
                *(
                    ToolCall(
                        id=f"call_list_{n}",
                        function="list_dir",
                        arguments={"path": f"d{n}"},
                    )
                    for n in range(_MAX_TOOL_EXECUTION_GRANTS)
                )
            ),
            tool_calls_output(
                ToolCall(id="call_later", function="read_file", arguments=call),
                content="Reading again.",
            ),
            *(
                [
                    tool_calls_output(
                        ToolCall(id="call_third", function="read_file", arguments=call),
                        content="Reading a third time.",
                    )
                ]
                if later_call == "takes a third grant"
                else []
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "host": {
                "read_file": read_file(
                    AsyncMock(side_effect=["first result", "later result"])
                ),
                "list_dir": served_tool(
                    AsyncMock(return_value="listed"),
                    description=LIST_DIR,
                    name="list_dir",
                ),
            }
        },
    )
    [read_info] = declare("read_file")
    [list_info] = declare("list_dir", description=LIST_DIR)
    # the later reply's conversation is the sample's, so the bridge tracks it
    first = _HostConversation(dialect, "Earlier: read a.", read_info)
    sub = _HostConversation(dialect, "Sub-agent: list.", list_info)
    later = _HostConversation(dialect, "Read a.", read_info)
    third = _HostConversation(dialect, "Side call: read a.", read_info)
    with recorded_transcript() as recorded:
        await first.request(bridge)
        await sub.request(bridge)
        later_calls = await later.request(bridge)
        await call_host_tool(bridge)("host", "read_file", call)
        if later_call == "denied":
            with pytest.raises(PermissionError) as denied:
                await call_host_tool(bridge)("host", "read_file", call)
            answer: JsonValue = str(denied.value)
        else:
            await third.request(bridge)
            answer = await call_host_tool(bridge)("host", "read_file", call)
        later.results(later_calls, [answer])
        await later.request(bridge)

    reads = [
        e
        for e in recorded.events
        if isinstance(e, ToolEvent) and e.function == "read_file"
    ]
    assert [(bridge_metadata(e)["grant"], e.result) for e in reads] == [
        ("consumed", "first result"),
        ("denied", "") if later_call == "denied" else ("consumed", "later result"),
    ]
    assert bridge_metadata(reads[0])["proposal_id"] == "call_later"
    assert [e.message_id for e in reads] == [None, None]


@pytest.mark.parametrize(
    "shape",
    [
        "retry, answer before a later denial",
        "retry, no later call",
        "sequential, answered first",
        "no retry",
    ],
)
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_retry_taking_a_later_replys_identical_grant_links_nothing(
    dialect: HostDialect, shape: str
) -> None:
    """A retry that takes a later reply's identical grant leaves both replies unlinked.

    The main reply's call executes and its response is lost, so its answer
    is not yet sent. A sub-agent's reply then proposes the identical call,
    and the client's retry of the main call takes that grant: no denial, and
    no pending ambiguity. The main thread's answer holds the retry's result,
    so neither execution links, also when the sub-agent's own call is then
    denied after the answer arrived. When the main call's answer arrived
    before the identical call executed (`sequential, answered first`), both
    executions link their own answers, as the main execution does with no
    retry.
    """
    retry = shape.startswith("retry")
    sequential = shape == "sequential, answered first"
    main_output = tool_calls_output(
        ToolCall(id="call_main", function="read_file", arguments={"path": "a"}),
        content="Reading.",
    )
    sub_output = tool_calls_output(
        ToolCall(id="call_sub", function="read_file", arguments={"path": "a"}),
        content="On it.",
    )
    done = ModelOutput.from_content("mockllm/model", "done")
    model = get_model(
        "mockllm/model",
        custom_outputs=[main_output, done, sub_output, done]
        if sequential
        else [main_output, sub_output, done],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "host": {
                "read_file": read_file(
                    AsyncMock(side_effect=["FIRST RESULT", "SECOND RESULT"])
                )
            }
        },
    )
    [info] = declare("read_file")
    main = _HostConversation(dialect, "Read a.", info)
    sub = _HostConversation(dialect, "Sub-agent: read a.", info)
    with recorded_transcript() as recorded:
        main_calls = await main.request(bridge)
        [(_, arguments)] = main_calls
        first = await call_host_tool(bridge)("host", "read_file", arguments)
        if sequential:
            main.results(main_calls, [first])
            await main.request(bridge)
        sub_calls = await sub.request(bridge)
        if retry:
            first = await call_host_tool(bridge)("host", "read_file", arguments)
        if not sequential:
            main.results(main_calls, [first])
            await main.request(bridge)
        if shape == "retry, answer before a later denial":
            with pytest.raises(PermissionError):
                await call_host_tool(bridge)("host", "read_file", arguments)
        if sequential:
            second = await call_host_tool(bridge)("host", "read_file", arguments)
            sub.results(sub_calls, [second])
            await sub.request(bridge)

    answers = {
        m.text: m.id
        for e in recorded.events
        if isinstance(e, ModelEvent)
        for m in e.input
        if m.role == "tool"
    }

    def answer_holding(result: str) -> str:
        [id] = [id for text, id in answers.items() if result in text]
        assert id is not None
        return id

    reads = [
        e
        for e in recorded.events
        if isinstance(e, ToolEvent) and bridge_metadata(e)["grant"] == "consumed"
    ]
    results = (
        ["FIRST RESULT", "SECOND RESULT"] if shape != "no retry" else ["FIRST RESULT"]
    )
    assert [e.result for e in reads] == results
    if retry:
        assert [bridge_metadata(e)["proposal_id"] for e in reads] == [
            "call_main",
            "call_sub",
        ]
        assert [e.message_id for e in reads] == [None, None]
    else:
        assert [e.message_id for e in reads] == [
            answer_holding(str(e.result)) for e in reads
        ]


@pytest.mark.parametrize("second", [False, True], ids=["control", "second running"])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_second_execution_of_a_proposal_unlinks_it_when_it_starts(
    dialect: HostDialect, second: bool
) -> None:
    """A proposal's completed first execution stops linking as soon as its second starts.

    Servers `a` and `b` serve the same description, so the call is granted
    once on each. It completes on `a`, and its answer is held. The second
    execution, on `b`, starts and blocks; the client times out waiting for
    it and sends a timeout message as the call's answer, and `b`'s execution
    is then cancelled. Neither execution links. With no second execution
    (`control`), `a`'s answer links.
    """
    started = anyio.Event()

    async def blocked(**_: Any) -> str:
        started.set()
        await anyio.sleep_forever()
        return "SECOND RESULT"

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_main", function="read_file", arguments={"path": "a"}),
                content="Reading.",
            ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read a.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={
            "a": {"read_file": read_file(AsyncMock(return_value="FIRST RESULT"))},
            "b": {"read_file": read_file(AsyncMock(side_effect=blocked))},
        },
    )
    [info] = declare("read_file")
    main = _HostConversation(dialect, "Read a.", info)
    cancelled = anyio.Event()
    with recorded_transcript() as recorded:
        calls = await main.request(bridge)
        first = await call_host_tool(bridge)("a", "read_file", {"path": "a"})
        if second:

            async def execute() -> None:
                try:
                    await call_host_tool(bridge)("b", "read_file", {"path": "a"})
                finally:
                    cancelled.set()

            async with anyio.create_task_group() as tg:
                tg.start_soon(execute)
                await started.wait()
                main.results(calls, ["Client timed out waiting for server b."])
                await main.request(bridge)
                tg.cancel_scope.cancel()
            assert cancelled.is_set()
        else:
            main.results(calls, [first])
            await main.request(bridge)

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    [answer] = [m.id for m in model_events[-1].input if m.role == "tool"]
    reads = [e for e in recorded.events if isinstance(e, ToolEvent)]
    if second:
        assert [(bridge_metadata(e)["server"], e.result) for e in reads] == [
            ("a", "FIRST RESULT"),
            ("b", ""),
        ]
        assert reads[1].error is not None and reads[1].error.type == "cancelled"
        assert [e.message_id for e in reads] == [None, None]
    else:
        assert [e.message_id for e in reads] == [answer]


@agent
def fabricating_host_scaffold(dialect: HostDialect, fabricated_id: str) -> Agent:
    """A scaffold running a reply's two calls as host tools, then sending in the reply's place its own text and one call under `fabricated_id`, with the first call's function and arguments and its own answer."""

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(_numbered_results())}},
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation(dialect, state.messages[0].text, info)
        calls = await conversation.request(bridge)
        for _, arguments in calls:
            await call_host_tool(bridge)("host", "read_file", arguments)
        call = (fabricated_id, calls[0][1])
        conversation.history[1:] = _fabricated_reply(dialect, info.name, *call)
        conversation.results([call], ["fabricated answer"])
        await conversation.request(bridge)
        return bridge.state

    return execute


def _fabricated_reply(
    dialect: HostDialect, name: str, call_id: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    match dialect:
        case "completions":
            return [
                {
                    "role": "assistant",
                    "content": "Unrelated.",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
            ]
        case "responses":
            return [
                {"role": "assistant", "content": "Unrelated."},
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            ]
        case "anthropic":
            return [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Unrelated."},
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": name,
                            "input": arguments,
                        },
                    ],
                }
            ]
        case "google":
            raise ValueError("Google regenerates incoming call ids")


@pytest.mark.parametrize(
    "fabricated_id",
    ["call_a\ncall_b", "call_a\ncall_c"],
    ids=["joined ids of the reply's calls", "noncolliding"],
)
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic"])
def test_reply_with_one_call_under_the_joined_ids_of_two_is_not_their_reply(
    dialect: HostDialect, fabricated_id: str, tmp_path: Path
) -> None:
    """A fabricated reply whose one call's id is two calls' ids joined with a newline is neither their reply nor an edit of it, and their host results don't link to its answer.

    Its call has the first call's function and arguments. The scaffold never
    sends the executions' results, so the host events stay unlinked.
    """
    name = "mcp__host__read_file"
    log = eval(
        Task(
            dataset=[Sample(input="Read a and b.")],
            solver=fabricating_host_scaffold(dialect, fabricated_id),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_calls_output(
                    ToolCall(id="call_a", function=name, arguments={"path": "a"}),
                    ToolCall(id="call_b", function=name, arguments={"path": "b"}),
                ),
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")
    assert_message_ids(sample)

    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 2
    original = model_events[0].output.message
    [fabricated] = [m for m in model_events[1].input if m.role == "assistant"]
    assert fabricated.tool_calls and fabricated.tool_calls[0].id == fabricated_id
    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert [e.message_id for e in events] == [None, None]
    assert fabricated.id not in (original.id, edited_id(original.id, fabricated))


@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
async def test_empty_text_tool_reply_never_takes_an_earlier_replys_id(
    dialect: HostDialect,
) -> None:
    """A tool-only reply equal to an earlier one in its wire form is never placed as either.

    Responses and Anthropic send a reply with empty text back without the
    text, and Google re-derives call ids, so the second reply, generated after
    compaction, comes back as the first one's copy did. Either could hold it,
    so it isn't placed: it gets the id the equal copy had, and keeps it.
    """

    def calls() -> ModelOutput:
        return tool_calls_output(
            ToolCall(id="reused", function="read_file", arguments={"path": "a"}),
            content="",
        )

    outputs = [
        calls(),
        ModelOutput.from_content("mockllm/model", "Read it."),
        calls(),
        *[ModelOutput.from_content("mockllm/model", "Done.")] * 2,
    ]
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content="Read twice.")]),
        model_aliases={"inspect": get_model("mockllm/model", custom_outputs=outputs)},
    )
    [info] = declare("read_file")
    conversation = _HostConversation(dialect, "Read twice.", info)
    with recorded_transcript() as recorded, recording_placements() as placements:
        first = await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.results(first, ["same"])
        await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.history = [_user_turn(dialect, "Summary: read once.")]
        second = await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.results(second, ["same"])
        await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.history.append(_user_turn(dialect, "Thanks."))
        await conversation.request(cast(SandboxAgentBridge, bridge))

    events = [e for e in recorded.events if isinstance(e, ModelEvent)]

    def ids(event: ModelEvent) -> list[str | None]:
        return [m.id for m in event.input if m.role in ("assistant", "tool")]

    assert len(ids(events[3])) == 2
    assert ids(events[3])[0] not in placements[3]
    assert ids(events[4])[:2] == ids(events[3])


class _TickCheckpointer(RecordingCheckpointer):
    """Saves a serialized snapshot each time the bridge reaches its checkpoint boundary."""

    saved: dict[str, Any] = {}

    async def tick(self) -> None:
        self.saved = json.loads(json.dumps(self.snapshot()))


@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
async def test_empty_text_tool_reply_keeps_its_ids_when_resumed_from_its_checkpoint(
    dialect: HostDialect,
) -> None:
    """A checkpoint saved as a reply is generated holds the form the reply is sent back in.

    The second tool-only reply equals the first in that form. The checkpoint
    its request saves equals the bridge's state once the request returns, and
    a bridge resumed from it doesn't place the reply either, giving it the
    ids the uninterrupted bridge gives.
    """

    def calls() -> ModelOutput:
        return tool_calls_output(
            ToolCall(id="reused", function="read_file", arguments={"path": "a"}),
            content="",
        )

    outputs = [
        calls(),
        ModelOutput.from_content("mockllm/model", "Read it."),
        calls(),
        *[ModelOutput.from_content("mockllm/model", "Done.")] * 2,
    ]
    model = get_model("mockllm/model", custom_outputs=outputs)
    task = ChatMessageUser(content="Read twice.")
    checkpointer = _TickCheckpointer()
    bridge = AgentBridge(
        AgentState(messages=[task]),
        checkpointer=checkpointer,
        model_aliases={"inspect": model},
    )
    [info] = declare("read_file")
    conversation = _HostConversation(dialect, "Read twice.", info)
    with recorded_transcript() as recorded, recording_placements() as placements:
        first = await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.results(first, ["same"])
        await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.history = [_user_turn(dialect, "Summary: read once.")]
        second = await conversation.request(cast(SandboxAgentBridge, bridge))
        saved = checkpointer.saved
        assert saved == json.loads(json.dumps(checkpointer.snapshot()))
        conversation.results(second, ["same"])
        history = list(conversation.history)
        await conversation.request(cast(SandboxAgentBridge, bridge))
        resumed = AgentBridge(
            AgentState(messages=[task]),
            checkpointer=RecordingCheckpointer(restored=saved, serialized=True),
            model_aliases={"inspect": model},
        )
        conversation.history = history
        await conversation.request(cast(SandboxAgentBridge, resumed))

    events = [e for e in recorded.events if isinstance(e, ModelEvent)]

    def ids(event: ModelEvent) -> list[str | None]:
        return [m.id for m in event.input if m.role in ("assistant", "tool")]

    first_ids = {events[0].output.message.id, *ids(events[1])}
    known = first_ids | {events[2].output.message.id}

    def owners(event: ModelEvent) -> list[str]:
        return [
            "first" if id in first_ids else "second" if id in known else "new"
            for id in ids(event)
        ]

    assert not set(ids(events[3])[:1]) & (placements[3] | placements[4])
    assert owners(events[4]) == owners(events[3])


@pytest.mark.parametrize("functions", ["same", "different"])
@pytest.mark.parametrize("order", ["proposed", "reversed"])
async def test_google_results_link_only_when_their_function_names_one_call(
    order: str, functions: str
) -> None:
    """A Google result names its function but not its call, so it isn't linked when several calls share the name.

    The bridge assigns such results the reply's call ids in proposal order,
    which is wrong when the scaffold sends them in completion order. Results
    of calls with different functions link in either order.
    """
    paths = ["a", "b"]
    names = ["read_file", "read_file" if functions == "same" else "list_dir"]
    reply = tool_calls_output(
        *[
            ToolCall(id=f"call_{p}", function=name, arguments={"path": p})
            for p, name in zip(paths, names)
        ],
        content="Reading.",
    )
    outputs = [reply, *[ModelOutput.from_content("mockllm/model", "Done.")] * 2]
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content="Read both.")]),
        model_aliases={"inspect": get_model("mockllm/model", custom_outputs=outputs)},
    )
    [info] = declare("read_file")
    conversation = _HostConversation("google", "Read both.", info)
    with recorded_transcript():
        handed = await conversation.request(cast(SandboxAgentBridge, bridge))
        [message] = [m for m in bridge.state.messages if m.role == "assistant"]
        assert isinstance(message, ChatMessageAssistant) and message.tool_calls
        events = []
        for index, path in enumerate(paths):
            call = message.tool_calls[index]
            event = ToolEvent(
                id=call.id,
                function=call.function,
                arguments=call.arguments,
                result=f"contents {path}",
            )
            bridge._await_result_message(
                handed_calls(bridge, cast(str, message.id), message.tool_calls)[index],
                event,
            )
            events.append(event)
        results = [f"contents {p}" for p in paths]
        if order == "reversed":
            handed, results = handed[::-1], results[::-1]
        conversation.results(handed, cast(list[JsonValue], results))
        await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.history.append(_user_turn("google", "Thanks."))
        await conversation.request(cast(SandboxAgentBridge, bridge))

    assert not any(_awaited_events(bridge))
    if functions == "same":
        assert [e.message_id for e in events] == [None, None]
    else:
        texts = {m.id: m.text for m in bridge.state.messages if m.role == "tool"}
        for event, path in zip(events, paths):
            assert event.message_id is not None
            assert f"contents {path}" in texts[event.message_id]


async def _answer_host_read(
    dialect: HostDialect,
    answer: Callable[[_HostConversation, list[tuple[str, Any]]], None],
) -> tuple[ToolEvent, list[ChatMessageTool]]:
    """Run one host `read_file` call returning "NEW", let `answer` answer it, and send the answers.

    Returns the execution's event and the tool messages of the request.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            tool_calls_output(
                ToolCall(id="call_1", function="read_file", arguments={"path": "p"}),
                content="Reading p.",
            ),
            ModelOutput.from_content("mockllm/model", "Noted."),
        ],
    )
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[ChatMessageUser(content="Read p.")]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model},
        bridged_tools={"a": {"read_file": read_file(AsyncMock(return_value="NEW"))}},
    )
    [info] = declare("read_file")
    conversation = _HostConversation(dialect, "Read p.", info)
    with recorded_transcript() as recorded:
        calls = await conversation.request(bridge)
        await call_host_tool(bridge)("a", "read_file", calls[0][1])
        answer(conversation, calls)
        await conversation.request(bridge)
    [event] = [e for e in recorded.events if isinstance(e, ToolEvent)]
    assert event.result == "NEW"
    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    tools = [m for m in model_events[-1].input if isinstance(m, ChatMessageTool)]
    return event, tools


@pytest.mark.parametrize("answers", [["Stale.", "NEW"], ["NEW"]], ids=["twice", "once"])
@pytest.mark.parametrize("dialect", ["google", "completions", "responses", "anthropic"])
async def test_host_call_answered_twice_links_neither_answer(
    dialect: HostDialect, answers: list[JsonValue]
) -> None:
    """A host call the scaffold answers twice links neither answer; answered once, it links.

    Which answer holds the execution's result can't be told. Google answers
    name only their function, so both answer the one `read_file` call.
    """
    event, tools = await _answer_host_read(
        dialect,
        lambda conversation, calls: conversation.results(calls * len(answers), answers),
    )
    assert len(tools) == len(answers)
    assert event.message_id == (tools[0].id if len(answers) == 1 else None)


@pytest.mark.parametrize("answers", [["Stale.", "NEW"], ["NEW"]], ids=["twice", "once"])
@pytest.mark.parametrize("split", [False, True], ids=["together", "split"])
@pytest.mark.parametrize("key", ["functionResponse", "function_response"])
@pytest.mark.parametrize("role", ["user", "model"])
async def test_google_responses_naming_one_call_link_only_alone(
    role: str, key: str, split: bool, answers: list[str]
) -> None:
    """Several Google responses naming one call's function leave it unlinked, the first too.

    A response names only its function, so the first takes the call's id and
    the next an id of its own. Which of them holds the execution's result
    can't be told, in either role or key spelling, sent in one turn or one
    turn each. A single response links.
    """

    def answer(conversation: _HostConversation, calls: list[tuple[str, Any]]) -> None:
        [(name, _)] = calls
        parts = [{key: {"name": name, "response": {"output": a}}} for a in answers]
        turns = [[part] for part in parts] if split else [parts]
        conversation.history.extend({"role": role, "parts": turn} for turn in turns)

    event, tools = await _answer_host_read("google", answer)
    assert len(tools) == len(answers)
    assert event.message_id == (tools[0].id if len(answers) == 1 else None)


@pytest.mark.parametrize("compacted", [False, True], ids=["full", "compacted"])
async def test_reordered_google_results_never_take_each_others_ids(
    compacted: bool,
) -> None:
    """Distinct Google results of calls sharing a function, sent again in another order, never take each other's ids.

    The bridge infers their call ids from order, so a result sent at another
    position carries the other call's id: neither is the message sent before
    at its position, and neither links.
    """
    outputs = ["A", "B"]
    reply = tool_calls_output(
        *[
            ToolCall(id=path, function="read_file", arguments={"path": path})
            for path in ["a", "b"]
        ],
        content="Read both.",
    )
    done = ModelOutput.from_content("mockllm/model", "Done.")
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content="Read files.")]),
        model_aliases={
            "inspect": get_model("mockllm/model", custom_outputs=[reply, *[done] * 3])
        },
    )
    [info] = declare("read_file")
    conversation = _HostConversation("google", "Read files.", info)
    with recorded_transcript() as recorded:
        calls = await conversation.request(cast(SandboxAgentBridge, bridge))
        [message] = [m for m in bridge.state.messages if m.role == "assistant"]
        assert isinstance(message, ChatMessageAssistant) and message.tool_calls
        events = []
        for handed, output in zip(
            handed_calls(bridge, cast(str, message.id), message.tool_calls), outputs
        ):
            call = message.tool_calls[handed.position]
            event = ToolEvent(
                id=call.id, function=call.function, arguments={}, result=output
            )
            bridge._await_result_message(handed, event)
            events.append(event)
        conversation.results(calls, cast(list[JsonValue], outputs))
        bundle = conversation.history[-1]
        await conversation.request(cast(SandboxAgentBridge, bridge))
        model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
        own_a, own_b = [m.id for m in model_events[-1].input if m.role == "tool"]
        bundle["parts"] = bundle["parts"][::-1]
        if compacted:
            conversation.history = [
                _user_turn("google", "Summary."),
                *conversation.history[1:3],
            ]
        conversation.history.append(_user_turn("google", "Continue."))
        await conversation.request(cast(SandboxAgentBridge, bridge))
        conversation.history.append(_user_turn("google", "Thanks."))
        await conversation.request(cast(SandboxAgentBridge, bridge))

    model_events = [e for e in recorded.events if isinstance(e, ModelEvent)]
    reordered = [m.id for m in model_events[-2].input if m.role == "tool"]
    sent_b, sent_a = reordered
    assert sent_b != own_a and sent_a != own_b, (own_a, own_b, reordered)
    assert len(set(reordered)) == 2
    assert [e.message_id for e in events] == [None, None]
    assert [m.id for m in model_events[-1].input if m.role == "tool"] == reordered


@pytest.mark.parametrize("host", [False, True], ids=["scaffold", "host"])
def test_matching_same_name_google_results_is_linear(host: bool) -> None:
    """Matching a batch of results of calls sharing a function is linear in the batch."""
    import sys

    from inspect_ai.agent._bridge.google_api_impl import (
        messages_from_google_contents,
    )

    def work(n: int) -> int:
        calls = [
            ToolCall(id=f"call_{i}", function="read_file", arguments={"path": str(i)})
            for i in range(n)
        ]
        reply = ChatMessageAssistant(content="", tool_calls=calls)
        bridge = AgentBridge(AgentState(messages=[ChatMessageUser(content="Read.")]))
        bridge._assign_message_ids([ChatMessageUser(content="Read."), reply])
        contents = [
            {"role": "user", "parts": [{"text": "Read."}]},
            {
                "role": "model",
                "parts": [
                    {"functionCall": {"name": "read_file", "args": {"path": str(i)}}}
                    for i in range(n)
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "read_file",
                            "response": {"output": "OK" if i % 2 else str(i)},
                        }
                    }
                    for i in range(n)
                ],
            },
        ]
        lines = 0

        def trace(frame: Any, event: str, arg: Any) -> Any:
            nonlocal lines
            if event == "line" and "inspect_ai" in frame.f_code.co_filename:
                lines += 1
            return trace

        sys.settrace(trace)
        try:
            if host:
                assert reply.id is not None
                for handed in handed_calls(bridge, reply.id, calls):
                    bridge._await_result_message(
                        handed,
                        ToolEvent(
                            id=calls[handed.position].id,
                            function="read_file",
                            arguments={},
                            result="OK",
                        ),
                    )
            inferred: list[ChatMessageTool] = []
            messages = messages_from_google_contents(contents, None, inferred)
            assert len(inferred) == n
            bridge._assign_message_ids(messages, inferred)
        finally:
            sys.settrace(None)
        return lines

    small, large = work(16), work(128)
    # linear is 8x; comparing each result with each call is 64x
    assert large <= 12 * small, (small, large)


@pytest.mark.parametrize("case", ["shared", "distinct"])
@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic"])
async def test_matching_results_of_calls_sharing_an_id_is_linear(
    dialect: HostDialect, case: str
) -> None:
    """Matching a batch of results of calls sharing a call id is linear in the batch.

    Measured: all matching of the request sending the results.
    """
    import sys

    async def work(n: int) -> int:
        output = tool_calls_output(
            *[
                ToolCall(
                    id="unknown" if case == "shared" else f"call_{i}",
                    function="read_file",
                    arguments={"path": str(i)},
                )
                for i in range(n)
            ]
        )
        outputs = [output, ModelOutput.from_content("mockllm/model", "Done.")]
        bridge = AgentBridge(
            AgentState(messages=[ChatMessageUser(content="Read files.")]),
            model_aliases={
                "inspect": get_model("mockllm/model", custom_outputs=outputs)
            },
        )
        [info] = declare("read_file")
        conversation = _HostConversation(dialect, "Read files.", info)
        lines = 0

        def trace(frame: Any, event: str, arg: Any) -> Any:
            if not frame.f_code.co_filename.endswith("_bridge/types.py"):
                return None
            if event == "line":
                nonlocal lines
                lines += 1
            return trace

        with recorded_transcript():
            calls = await conversation.request(cast(SandboxAgentBridge, bridge))
            conversation.results(calls, [str(i) for i in range(n)])
            sys.settrace(trace)
            try:
                await conversation.request(cast(SandboxAgentBridge, bridge))
            finally:
                sys.settrace(None)
        return lines

    small, large = await work(16), await work(128)
    assert small > 0
    # linear is 8x; matching each result with each sibling call is 64x
    assert large <= 12 * small, (small, large)


@pytest.mark.parametrize("dialect", get_args(HostDialect))
@pytest.mark.parametrize("case", ["parse_error", "shared", "distinct"])
async def test_handing_over_many_calls_sharing_an_id_is_linear(
    dialect: HostDialect, case: str
) -> None:
    """Handing over a reply's calls is linear in its calls, however many share an id.

    The Llama parser gives every malformed `<tool_call>` block the call id and
    function `unknown`. Measured: argument canonicalizations and all work of the
    generation request.
    """
    import sys

    import inspect_ai.agent._bridge.util as bridge_util

    def call(i: int) -> ToolCall:
        match case:
            case "parse_error":
                return ToolCall(
                    id="unknown", function="unknown", arguments={}, parse_error="bad"
                )
            case "shared":
                return ToolCall(
                    id="unknown", function="read_file", arguments={"path": str(i)}
                )
            case _:
                return ToolCall(
                    id=f"call_{i}", function="read_file", arguments={"path": str(i)}
                )

    async def work(n: int) -> tuple[int, int]:
        outputs = [tool_calls_output(*[call(i) for i in range(n)])]
        bridge = AgentBridge(
            AgentState(messages=[ChatMessageUser(content="Read files.")]),
            model_aliases={
                "inspect": get_model("mockllm/model", custom_outputs=outputs)
            },
        )
        [info] = declare("read_file")
        conversation = _HostConversation(dialect, "Read files.", info)
        canonicalized = lines = 0
        canonical = canonical_tool_arguments

        def counted_canonical(arguments: dict[str, Any]) -> str:
            nonlocal canonicalized
            canonicalized += 1
            return canonical(arguments)

        def trace(frame: Any, event: str, arg: Any) -> Any:
            if "inspect_ai" not in frame.f_code.co_filename:
                return None
            if event == "line":
                nonlocal lines
                lines += 1
            return trace

        with (
            recorded_transcript(),
            patch.object(bridge_util, "canonical_tool_arguments", counted_canonical),
        ):
            sys.settrace(trace)
            try:
                calls = await conversation.request(cast(SandboxAgentBridge, bridge))
            finally:
                sys.settrace(None)
        assert len(calls) == n
        return canonicalized, lines

    await work(4)
    small, large = await work(100), await work(800)
    assert small[1] > 0 and large[1] > 0
    # linear is 8x; scanning every generated call for each handed call is 64x
    assert large[0] <= 12 * max(small[0], 1), (small, large)
    assert large[1] <= 12 * small[1], (small, large)


class _CountingAnswers(dict[str, Any]):
    reads = 0

    def __getitem__(self, key: str) -> Any:
        _CountingAnswers.reads += 1
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        _CountingAnswers.reads += 1
        return super().get(key, default)


@pytest.mark.parametrize("host", [False, True], ids=["scaffold", "host"])
async def test_repeated_google_results_are_matched_in_linear_time(host: bool) -> None:
    """Matching a compacted run of repeated results doesn't rescan their earlier copies.

    A Google scaffold polls one status call, which gets `working` each time,
    then compacts to a summary and its newest half of turns. Measured: all
    matching of the compacted request.
    """
    import sys

    from inspect_ai.agent._bridge.google_api_impl import (
        messages_from_google_contents,
    )

    async def work(turns: int) -> int:
        prompt = "Poll status until done."
        bridge = AgentBridge(AgentState(messages=[ChatMessageUser(content=prompt)]))
        contents: list[Any] = [{"role": "user", "parts": [{"text": prompt}]}]
        call = {"functionCall": {"name": "status", "args": {}}}
        result = {
            "functionResponse": {"name": "status", "response": {"output": "working"}}
        }
        compacted = 0

        def trace(frame: Any, event: str, arg: Any) -> Any:
            if "inspect_ai" not in frame.f_code.co_filename:
                return None
            if event == "line":
                nonlocal compacted
                compacted += 1
            return trace

        try:
            for i in range(turns):
                messages = messages_from_google_contents(contents, None)
                bridge._assign_message_ids(messages)
                reply = ChatMessageAssistant(
                    content="",
                    tool_calls=[
                        ToolCall(id=f"provider-{i}", function="status", arguments={})
                    ],
                )
                wire = {"role": "model", "parts": [call]}
                await bridge._track_state(
                    messages,
                    ModelOutput.from_message(reply),
                    [messages_from_google_contents([wire], None)],
                )
                if host:
                    assert reply.id is not None
                    [handed] = handed_calls(bridge, reply.id, reply.tool_calls or [])
                    bridge._await_result_message(
                        handed,
                        ToolEvent(
                            id=f"provider-{i}",
                            function="status",
                            arguments={},
                            result="working",
                        ),
                    )
                contents += [wire, {"role": "user", "parts": [result]}]
            summary = {"role": "user", "parts": [{"text": "Summary: still waiting."}]}
            messages = messages_from_google_contents(
                [summary, *contents[1 + 2 * (turns // 2) :]], None
            )
            sys.settrace(trace)
            bridge._assign_message_ids(messages)
        finally:
            sys.settrace(None)
        return compacted

    works = [await work(turns) for turns in (32, 64, 128)]
    assert works[0] > 0
    # linear is 2x per doubling; rescanning the earlier copies is 4x
    assert works[1] <= 2.5 * works[0], works
    assert works[2] <= 5 * works[0], works


def _awaited_events(bridge: AgentBridge) -> list[ToolEvent | None]:
    return [
        event
        for reply in bridge._awaited_results.values()
        for event in reply.events.values()
    ]


@agent
def identical_replies_compacting_scaffold() -> Agent:
    """A Google scaffold reading a file in two identical turns (results `A`, `B`), compacting to both, then to a third turn and the `B` result."""

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={
                "host": {"read_file": read_file(AsyncMock(side_effect=["A", "B", "A"]))}
            },
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation("google", state.messages[0].text, info)
        for _ in range(2):
            [(_, arguments)] = calls = await conversation.request(bridge)
            result = await call_host_tool(bridge)("host", "read_file", arguments)
            conversation.results(calls, [result])
        earlier_b = conversation.history[-1]
        conversation.history = [
            _user_turn("google", "Summary: read twice."),
            *conversation.history[1:],
        ]
        [(_, arguments)] = await conversation.request(bridge)
        await call_host_tool(bridge)("host", "read_file", arguments)
        conversation.history = [
            _user_turn("google", "Summary: checking."),
            conversation.history[-1],
            earlier_b,
        ]
        await conversation.request(bridge)
        return bridge.state

    return execute


def test_answer_after_identical_replies_gives_no_later_link(tmp_path: Path) -> None:
    """An answer following a reply identical to another isn't evidence that a later equal message answers a later call.

    Compacting two identical Google replies can recognize each as the other,
    so the `B` answer may be taken for the first reply's (whose execution
    returned `A`). A later call that returned `A` must not link to that `B`
    message sent again.
    """
    name = "mcp__host__read_file"
    log = eval(
        Task(
            dataset=[Sample(input="Read a three times.")],
            solver=identical_replies_compacting_scaffold(),
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                *[
                    tool_calls_output(
                        ToolCall(
                            id=f"call_{n}", function=name, arguments={"path": "a"}
                        ),
                        content="On it." if n < 2 else "Checking again.",
                    )
                    for n in range(3)
                ],
                ModelOutput.from_content("mockllm/model", "done"),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")

    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert [e.result for e in events] == ["A", "B", "A"]
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    [resent_b] = [m for m in model_events[-1].input if m.role == "tool"]
    assert "B" in resent_b.text
    assert events[2].message_id is None


# live

LiveHostShape = Literal["sequential", "parallel", "reordered", "compacted"]

LIVE_HOST_MODELS: dict[HostDialect, str] = {
    "completions": "openai/gpt-4o-mini",
    "responses": "openai/gpt-5-mini",
    "anthropic": "anthropic/claude-haiku-4-5",
    "google": "google/gemini-3.1-flash-lite",
}

SEQUENTIAL_READS = (
    "Use the read_file tool to read the file 'a'. Only after you have its "
    "contents, read the file 'b'. Make one tool call per turn. Then reply with "
    "the single word done."
)
PARALLEL_READS = (
    "Read the files 'a' and 'b' with the read_file tool, making both calls "
    "together in this one turn. Then reply with the single word done."
)


@agent
def live_host_scaffold(
    dialect: HostDialect, shape: LiveHostShape, returned_ids: list[str]
) -> Agent:
    """A scaffold running a live model's calls as host tools.

    `reordered` sends each reply back with its calls (and their results) in
    reverse order. `compacted` continues after the second turn from a summary
    and that turn's reply and results, then sends one more request.
    """

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(_numbered_results())}},
        )
        [info] = declare("mcp__host__read_file")
        conversation = _HostConversation(dialect, state.messages[0].text, info)
        for turn in range(6):
            start = len(conversation.history)
            calls = await conversation.request(bridge)
            if not calls:
                break
            outputs = list(
                await tg_collect(
                    [
                        partial(call_host_tool(bridge), "host", "read_file", arguments)
                        for _, arguments in calls
                    ]
                )
            )
            if shape == "reordered":
                _reverse_calls(conversation.history, start)
                calls, outputs = calls[::-1], outputs[::-1]
            conversation.results(calls, outputs)
            if shape == "compacted" and turn == 1:
                summary = _user_turn(dialect, "Summary: you read the file 'a'.")
                conversation.history = [summary, *conversation.history[start:]]
        if shape == "compacted":
            conversation.history.append(_user_turn(dialect, "Thanks."))
            await conversation.request(bridge)
        returned_ids.extend(conversation.returned_ids)
        return bridge.state

    return execute


def _reverse_calls(history: list[dict[str, Any]], start: int) -> None:
    reply = history[start:]
    if "tool_calls" in reply[-1]:
        reply[-1]["tool_calls"] = reply[-1]["tool_calls"][::-1]
    elif reply[0].get("type"):
        calls = [i for i in reply if i["type"] == "function_call"]
        history[start:] = [i for i in reply if i["type"] != "function_call"] + calls[
            ::-1
        ]
    else:
        key, is_call = (
            ("parts", lambda p: "functionCall" in p)
            if "parts" in reply[-1]
            else ("content", lambda b: b["type"] == "tool_use")
        )
        items = reply[-1][key]
        reply[-1][key] = [i for i in items if not is_call(i)] + [
            i for i in reversed(items) if is_call(i)
        ]


def _live_sample(log: EvalLog) -> EvalSample:
    assert log.status == "success", log.error
    read = read_eval_log(log.location)
    assert read.samples
    sample = resolve_sample_attachments(read.samples[0], "full")
    assert sample.error is None, sample.error
    return sample


def _sent_tool_messages(
    sample: EvalSample,
) -> dict[str, tuple[ChatMessageTool, ChatMessageAssistant]]:
    found: dict[str, tuple[ChatMessageTool, ChatMessageAssistant]] = {}
    for event in sample.events:
        if not isinstance(event, ModelEvent):
            continue
        reply: ChatMessageAssistant | None = None
        for message in event.input:
            if isinstance(message, ChatMessageAssistant):
                reply = message
            elif isinstance(message, ChatMessageTool) and message.id and reply:
                found.setdefault(message.id, (message, reply))
    return found


def _result_sent_later(sample: EvalSample, event: ToolEvent) -> bool:
    start = next(n for n, e in enumerate(sample.events) if e is event)
    for model_event in sample.events[start:]:
        if not isinstance(model_event, ModelEvent):
            continue
        reply: ChatMessageAssistant | None = None
        for message in model_event.input:
            if isinstance(message, ChatMessageAssistant):
                reply = message
            elif (
                isinstance(message, ChatMessageTool)
                and reply
                and str(event.result) in message.text
                and any(c.arguments == event.arguments for c in reply.tool_calls or [])
            ):
                return True
    return False


def _scripted_host_model(shape: LiveHostShape, reread: str | None = None) -> Model:
    """A model making the calls a live model makes for `shape`'s prompt.

    With `reread`, the model reads that file again after a compaction.
    """
    name = "mcp__host__read_file"
    a = ToolCall(id="call_a", function=name, arguments={"path": "a"})
    b = ToolCall(id="call_b", function=name, arguments={"path": "b"})
    calls = (
        [tool_calls_output(a, b)]
        if shape in ("parallel", "reordered")
        else [tool_calls_output(a), tool_calls_output(b)]
    )
    if reread:
        calls.append(
            tool_calls_output(
                ToolCall(id="call_c", function=name, arguments={"path": reread})
            )
        )
    answers = 2 if shape == "compacted" else 1
    return get_model(
        "mockllm/model",
        custom_outputs=calls
        + [ModelOutput.from_content("mockllm/model", "done")] * answers,
    )


def _run_live_host(
    dialect: HostDialect,
    shape: LiveHostShape,
    tmp_path: Path,
    model: Model | None = None,
) -> None:
    """Run host tools with a live model (or `model`) and check the ids and tool event joins."""
    prompt = PARALLEL_READS if shape in ("parallel", "reordered") else SEQUENTIAL_READS
    returned_ids: list[str] = []
    sample = _live_sample(
        eval(
            Task(
                dataset=[Sample(input=prompt)],
                solver=live_host_scaffold(dialect, shape, returned_ids),
            ),
            model=model or LIVE_HOST_MODELS[dialect],
            log_dir=str(tmp_path),
            display="plain",
        )[0]
    )
    assert_message_ids(sample)

    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    generated = {e.output.message.id: e.output.message for e in model_events}
    events = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert {e.arguments.get("path") for e in events} == {"a", "b"}

    # each event names the one generated reply that proposed its call
    assert tool_event_producers(sample) == [1] * len(events)
    proposing = {e.id: generated[e.call_message_id] for e in events}
    for event in events:
        calls = proposing[event.id].tool_calls or []
        assert any(c.arguments == event.arguments for c in calls)
    multi_call = {
        id for id, m in generated.items() if m.tool_calls and len(m.tool_calls) > 1
    }
    if shape in ("parallel", "reordered"):
        assert multi_call, "the model made no parallel calls"
    else:
        assert not multi_call, "the model made parallel calls"

    # the request after the summary continues no known thread, so the reply
    # it keeps (the second turn's) isn't placed; the next request, continuing
    # it unchanged, sends that reply and its result again under the same ids
    kept_reply: str | None = None
    retained_ids: set[str | None] = set()
    if shape == "compacted":
        compacted = next(
            n
            for n, e in enumerate(model_events)
            if e.input and e.input[0].text.startswith("Summary:")
        )
        summary_call, next_call = model_events[compacted], model_events[compacted + 1]
        kept_reply = model_events[compacted - 1].output.message.id
        retained_ids = {
            m.id for m in summary_call.input if isinstance(m, ChatMessageAssistant)
        }
        assert len(retained_ids) == 1
        assert any(e.call_message_id == kept_reply for e in events)
        kept = [m.id for m in summary_call.input if m.role in ("assistant", "tool")]
        assert (
            kept
            == [m.id for m in next_call.input if m.role in ("assistant", "tool")][
                : len(kept)
            ]
        )

    # a reply sent back keeps its generated id (Google: or an edit of it); a
    # reordered reply isn't recognized and gets a fresh id, and so does the
    # compacted request's reply, which no earlier request held
    sent_replies = [
        m for e in model_events for m in e.input if isinstance(m, ChatMessageAssistant)
    ]
    for reply in sent_replies:
        derived = reply.id in generated or any(
            reply.id == edited_id(source, reply) for source in generated
        )
        if shape == "reordered" and reply.tool_calls and len(reply.tool_calls) > 1:
            assert not derived
        elif reply.id in retained_ids:
            assert not derived
        elif dialect == "google":
            assert derived
        else:
            assert reply.id in generated

    # the id Responses and Anthropic return is the generated reply's
    if dialect in ("responses", "anthropic"):
        assert returned_ids == [e.output.message.id for e in model_events]

    # every result is sent back after the reply proposing its call; Google
    # results of several calls of one function, and the calls of a reordered
    # reply or of the compacted request's reply, stay unlinked. A model may
    # repeat a call of the compacted request's reply after the summary; that
    # reply's answer was never placed, so the repeat may stay unlinked too
    sent_results = _sent_tool_messages(sample)
    kept_calls = [e.arguments for e in events if e.call_message_id == kept_reply]
    for event in events:
        assert _result_sent_later(sample, event), f"{event.result!r} wasn't sent"
        unlinked = (
            (shape == "reordered" and event.call_message_id in multi_call)
            or (dialect == "google" and event.call_message_id in multi_call)
            or (kept_reply is not None and event.call_message_id == kept_reply)
        )
        if unlinked:
            assert event.message_id is None
            continue
        if event.message_id is None and event.arguments in kept_calls:
            continue
        assert event.message_id is not None
        result, answered = sent_results[event.message_id]
        assert str(event.result) in result.text
        if dialect != "google":
            call_ids = [c.id for c in answered.tool_calls or []]
            assert result.tool_call_id in call_ids
    linked = [e.message_id for e in events if e.message_id is not None]
    assert len(set(linked)) == len(linked)


@pytest.mark.parametrize("dialect", get_args(HostDialect))
@pytest.mark.parametrize("shape", get_args(LiveHostShape))
def test_host_ids_with_scripted_calls(
    dialect: HostDialect, shape: LiveHostShape, tmp_path: Path
) -> None:
    """The live host-tool checks pass with a model scripted to make the calls a live model makes."""
    _run_live_host(dialect, shape, tmp_path, _scripted_host_model(shape))


@pytest.mark.parametrize("dialect", get_args(HostDialect))
@pytest.mark.parametrize("path", ["a", "b"])
def test_host_ids_with_a_scripted_reread_after_compaction(
    dialect: HostDialect, path: str, tmp_path: Path
) -> None:
    """The live checks allow a model to read a file again after the summary."""
    _run_live_host(
        dialect, "compacted", tmp_path, _scripted_host_model("compacted", path)
    )


@skip_if_no_openai
@pytest.mark.parametrize("shape", get_args(LiveHostShape))
def test_live_host_ids_completions(shape: LiveHostShape, tmp_path: Path) -> None:
    _run_live_host("completions", shape, tmp_path)


@skip_if_no_openai
@pytest.mark.parametrize("shape", get_args(LiveHostShape))
def test_live_host_ids_responses(shape: LiveHostShape, tmp_path: Path) -> None:
    _run_live_host("responses", shape, tmp_path)


@skip_if_no_anthropic
@pytest.mark.parametrize("shape", get_args(LiveHostShape))
def test_live_host_ids_anthropic(shape: LiveHostShape, tmp_path: Path) -> None:
    _run_live_host("anthropic", shape, tmp_path)


@skip_if_no_google
@pytest.mark.parametrize("shape", get_args(LiveHostShape))
def test_live_host_ids_google(shape: LiveHostShape, tmp_path: Path) -> None:
    _run_live_host("google", shape, tmp_path)


SERVER_WORK_PROMPT = (
    "Do two things in this same turn, issuing both tool calls before waiting "
    "for either result: (1) use code execution to run Python that writes the "
    "text 'seed-417' to /tmp/marker.txt and then prints the contents of "
    "/tmp/marker.txt; (2) call read_file with path 'a'. After you have both "
    "results, use code execution again to print /tmp/marker.txt, then reply "
    "with the single word done."
)


@agent
def server_work_scaffold(
    response_filter: ModelResponseFilter | None, replies: list[Any]
) -> Agent:
    """An Anthropic scaffold with code execution and a host tool, sending each reply back as received."""

    async def execute(state: AgentState) -> AgentState:
        bridge = SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            bridged_tools={"host": {"read_file": read_file(_numbered_results())}},
            response_filter=response_filter,
        )
        [info] = declare("mcp__host__read_file")
        tools: list[dict[str, Any]] = [
            {"type": "code_execution_20250825", "name": "code_execution"},
            {
                "name": info.name,
                "description": info.description,
                "input_schema": info.parameters.model_dump(exclude_none=True),
            },
        ]
        history: list[dict[str, Any]] = [
            {"role": "user", "content": state.messages[0].text}
        ]
        for _ in range(6):
            message = await inspect_anthropic_api_request(
                {
                    "model": "inspect",
                    "max_tokens": 4096,
                    "messages": history,
                    "tools": tools,
                },
                None,
                internal_web_search_providers(),
                default_code_execution_providers(),
                bridge,
            )
            replies.append(message)
            history.append(
                {
                    "role": "assistant",
                    "content": [
                        block.model_dump(mode="json", exclude_none=True)
                        for block in message.content
                    ],
                }
            )
            calls = [b for b in message.content if b.type == "tool_use"]
            if not calls:
                if message.stop_reason == "pause_turn":
                    continue
                break
            outputs = await tg_collect(
                [
                    partial(
                        call_host_tool(bridge),
                        "host",
                        "read_file",
                        cast(JsonValue, b.input),
                    )
                    for b in calls
                ]
            )
            history.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": b.id,
                            "content": str(output),
                        }
                        for b, output in zip(calls, outputs)
                    ],
                }
            )
        return bridge.state

    return execute


def _filter_text(message: ChatMessageAssistant) -> None:
    for item in message.content:
        if isinstance(item, ContentText):
            item.text = f"{item.text} FILTERED"
            break


async def _edit_text_filter(
    model: Model, output: ModelOutput, generate_input: GenerateInput
) -> ModelOutput:
    _filter_text(output.message)
    return output


def _left_server_work_running(event: ModelEvent) -> bool:
    """Whether the Anthropic turn of `event` ended with server tool work still running.

    That is a server tool use with no result, in the response or among the
    output's completed items (a continued generation records its first
    response; work a continuation leaves running is not seen).
    """
    response = event.call.response if event.call is not None else None
    content = response.get("content") if response is not None else None
    if not isinstance(content, list):
        return False
    blocks = cast(list[dict[str, Any]], content)
    uses = {b["id"] for b in blocks if b["type"] == "server_tool_use"}
    results = {b["tool_use_id"] for b in blocks if b["type"].endswith("_tool_result")}
    completed = {
        c.id for c in event.output.message.content if isinstance(c, ContentToolUse)
    }
    return bool(uses - results - completed)


def _filtered_reply_id(event: ModelEvent) -> str:
    """The id of the output of `event` returned through `_edit_text_filter`.

    An unchanged reply keeps the output's id, as does a reply keeping server
    tool items of a turn that left server work running (that work replays from
    state kept under the output's id); any other changed reply gets an id
    derived from the output's.
    """
    output = event.output.message
    assert output.id is not None
    edited = output.model_copy(deep=True)
    _filter_text(edited)
    if edited.content == output.content:
        return output.id
    if any(
        isinstance(c, ContentToolUse) for c in output.content
    ) and _left_server_work_running(event):
        return output.id
    return edited_id(output.id, edited)


def test_filtered_reply_ids_follow_server_items(tmp_path: Path) -> None:
    """`_filtered_reply_id` names the id each filtered reply comes back under.

    The replies, parsed by the Anthropic provider so it records their replay
    state, cover its four cases: server tool items beside edited text, from a
    turn that left server work running and from one that didn't; a reply the
    filter leaves unchanged; and edited text only.
    """
    from anthropic.types import Message

    from inspect_ai.model._providers.anthropic import model_output_from_message

    name = "mcp__host__read_file"
    [info] = declare(name)

    def read(path: str) -> dict[str, Any]:
        return {
            "type": "tool_use",
            "id": f"toolu_{path}",
            "name": name,
            "input": {"path": path},
        }

    caller = {"type": "code_execution_20260120", "tool_id": "srvtoolu_ce"}
    turns: list[tuple[list[dict[str, Any]], str]] = [
        (
            [
                {"type": "text", "text": "Checking."},
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_ce",
                    "name": "code_execution",
                    "input": {"code": "print('seed-417')"},
                    "caller": {"type": "direct"},
                },
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_ws",
                    "name": "web_search",
                    "input": {"query": "seed"},
                    "caller": caller,
                },
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "srvtoolu_ws",
                    "content": [
                        {
                            "type": "web_search_result",
                            "title": "Seed",
                            "url": "https://example.com/seed",
                            "encrypted_content": "ENCRYPTED_CONTENT",
                        }
                    ],
                    "caller": caller,
                },
                read("a"),
            ],
            "tool_use",
        ),
        (
            [
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_done",
                    "name": "web_search",
                    "input": {"query": "seed"},
                    "caller": {"type": "direct"},
                },
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "srvtoolu_done",
                    "content": [],
                    "caller": {"type": "direct"},
                },
                {"type": "text", "text": "Searched."},
                read("b"),
            ],
            "tool_use",
        ),
        ([read("c")], "tool_use"),
        ([{"type": "text", "text": "done"}], "end_turn"),
    ]
    served: list[list[dict[str, Any]]] = []

    async def serve(*args: Any) -> ModelOutput:
        blocks, stop_reason = turns[len(served)]
        served.append(blocks)
        message = Message.model_validate(
            {
                "id": f"msg_{len(served)}",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": blocks,
                "stop_reason": stop_reason,
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "container": {
                    "id": "container_1",
                    "expires_at": "2026-12-01T00:00:00Z",
                },
            }
        )
        output, _ = await model_output_from_message(
            client=None, model="claude-haiku-4-5", message=message, tools=[info]
        )
        output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return output

    replies: list[Any] = []
    sample = _live_sample(
        eval(
            Task(
                dataset=[Sample(input="go")],
                solver=server_work_scaffold(_edit_text_filter, replies),
            ),
            model=get_model("mockllm/model", custom_outputs=serve),
            log_dir=str(tmp_path),
            display="none",
        )[0]
    )
    # each event as the provider would record it, with its response
    events = [
        e.model_copy(
            update={"call": ModelCall.create(request={}, response={"content": blocks})}
        )
        for e, blocks in zip(
            [e for e in sample.events if isinstance(e, ModelEvent)], served, strict=True
        )
    ]
    outputs = [e.output.message.id for e in events]

    assert [_left_server_work_running(e) for e in events] == [True, False, False, False]
    expected = [_filtered_reply_id(e) for e in events]
    assert [r.id for r in replies] == expected
    assert expected[0] == outputs[0]
    assert expected[1] != outputs[1]
    assert expected[2] == outputs[2]
    assert expected[3] != outputs[3]


@skip_if_no_anthropic
@pytest.mark.parametrize("filtered", [False, True], ids=["unfiltered", "text_filter"])
def test_live_anthropic_pending_server_work_ids(filtered: bool, tmp_path: Path) -> None:
    """A reply that leaves code execution pending beside a host call, sent back as received.

    Anthropic replays the pending work from state keyed by the reply's id, so
    the reply must keep its generated id. A response filter that edits the
    text gives the reply an edit id and drops the pending work, which has no
    content item for the filter to keep.
    """
    replies: list[Any] = []
    sample = _live_sample(
        eval(
            Task(
                dataset=[Sample(input=SERVER_WORK_PROMPT)],
                solver=server_work_scaffold(
                    _edit_text_filter if filtered else None, replies
                ),
            ),
            model="anthropic/claude-haiku-4-5",
            log_dir=str(tmp_path),
            display="plain",
        )[0]
    )
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]

    # the first generation leaves code execution pending beside the host call
    first, second = replies[0], replies[1]
    assert model_events[0].call is not None
    response = cast(dict[str, Any], model_events[0].call.response)
    [pending] = [b["id"] for b in response["content"] if b["type"] == "server_tool_use"]
    assert [
        b["type"] for b in response["content"] if b["type"].endswith("_result")
    ] == []
    assert [b.type for b in first.content if b.type == "tool_use"] == ["tool_use"]
    assert first.stop_reason == "tool_use"

    # the reply comes back under the id it was returned with: the generated
    # one, or with the filter an edit of it
    generated = model_events[0].output.message
    assert generated.id is not None
    [sent] = [m for m in model_events[1].input if isinstance(m, ChatMessageAssistant)]
    assert sent.id == first.id
    if filtered:
        assert sent.text.endswith("FILTERED")
        assert sent.id == edited_id(generated.id, sent) != generated.id
    else:
        assert sent.id == generated.id
    # later replies come back under their output's id, or with the filter
    # under the id `_filtered_reply_id` gives
    assert [r.id for r in replies[1:]] == [
        _filtered_reply_id(e) if filtered else e.output.message.id
        for e in model_events[1:]
    ]

    # the continuation replays the pending work only under the generated id
    assert model_events[1].call is not None
    request = cast(dict[str, Any], model_events[1].call.request)
    [request_reply] = [m for m in request["messages"] if m["role"] == "assistant"]
    replayed = [
        b["id"] for b in request_reply["content"] if b["type"] == "server_tool_use"
    ]
    resumed = getattr(second.content[0], "tool_use_id", None) == pending
    shown = [b.id for b in first.content if b.type == "server_tool_use"]
    if filtered:
        assert shown == replayed == [] and not resumed
    else:
        assert shown == replayed == [pending] and resumed

    # the host call links to its proposing output and to its result
    [event] = [e for e in sample.events if isinstance(e, ToolEvent)]
    assert event.call_message_id == generated.id
    assert tool_event_producers(sample) == [1]
    _assert_linked(sample, [event])

    # a filtered reply keeping server tool items of a turn that left server
    # work running keeps the output's id (whether a later reply does depends
    # on the model)
    kept_output_ids = {
        e.output.message.id
        for e in model_events
        if e.output.message.id is not None
        and any(isinstance(c, ContentToolUse) for c in e.output.message.content)
        and _left_server_work_running(e)
    }
    violations = message_id_violations(sample)
    if filtered:
        assert all(any(id in v for id in kept_output_ids) for v in violations)
    else:
        assert not violations
