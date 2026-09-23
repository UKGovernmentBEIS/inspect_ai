"""Tool approval for tool calls made by bridged agents.

A bridged scaffold runs its own tool loop, so `execute_tools()` approval never
runs for it. `bridge_generate` approves the tool calls in each model response
instead, and resolves a rejection by telling the model and regenerating rather
than by editing the response the scaffold sees.
"""

import json
import logging
from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable, Iterator
from unittest.mock import AsyncMock

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
from inspect_ai.agent._bridge.sandbox.bridge import _monitor_failure
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
from inspect_ai.event._approval import ApprovalEvent
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.model._compaction import CompactionTrim
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import GenerateInput, Model, get_model
from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput
from inspect_ai.model._openai_responses import (
    TOOL_SEARCH_NAME,
    tool_search_output_tools,
)
from inspect_ai.tool import Tool, tool
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParam, ToolParams

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
        bridge, model, list(messages), list(tools or []), None, GenerateConfig()
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

    assert not bridge._failure_requested.is_set()
    with pytest.raises(TerminateSampleError):
        bridge.request_terminate("approver said stop")

    assert bridge._failure_requested.is_set()
    assert isinstance(bridge._failure, TerminateSampleError)
    assert bridge._failure.reason == "approver said stop"


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
    bridge.request_fail(TerminateSampleError("approver said stop"))

    with pytest.raises(TerminateSampleError, match="approver said stop"):
        await _monitor_failure(bridge)


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


@pytest.fixture
def capture_bridge_warnings(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Route the sandbox bridge module's warnings to caplog.

    Attached directly because `init_logger` stops the inspect_ai logger
    propagating once an earlier test has triggered it.
    """
    module_logger = logging.getLogger(SandboxAgentBridge.__module__)
    module_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=module_logger.name):
            yield
    finally:
        module_logger.removeHandler(caplog.handler)


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


async def test_opted_out_server_stores_no_grants() -> None:
    """Grants nothing will consume must not fill the bounded store."""
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge_with_tool(tool, None, require_proposal=False)

    bridge.register_tool_execution_grants(
        [ToolCall(id="proposed", function="read_file", arguments={"path": "a"})],
        declare("read_file"),
    )

    assert len(bridge._tool_execution_grants) == 0


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
