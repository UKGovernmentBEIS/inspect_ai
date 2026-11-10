import json
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from checkpoint.test_checkpointer import (
    _CountingCheckpointer,
    _fake_hydration,
    _patch_sample_runtime,
)
from pydantic import JsonValue, TypeAdapter, ValidationError
from pydantic_core import to_json
from test_helpers.checkpoint import RecordingCheckpointer
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
)

from inspect_ai import Task, eval
from inspect_ai._sentinel._config import resolve_sentinel_root, resolve_sentinel_spec
from inspect_ai._sentinel._context import SentinelFailure, init_sentinel
from inspect_ai._sentinel._scope import sentinel_solving
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.content import (
    Content,
    ContentImage,
    ContentReasoning,
    ContentText,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.agent._acp.transport_live import LiveAcpTransport
from inspect_ai.agent._bridge._errors import PROVIDER_ERROR_KEY
from inspect_ai.agent._bridge._sentinel import _SavedHandedCalls
from inspect_ai.agent._bridge.sandbox.service import _forward_provider_errors
from inspect_ai.agent._bridge.sandbox.service import call_tool as call_host_tool
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import bridge_generate
from inspect_ai.approval import (
    Approval,
    ApprovalPolicy,
    Approver,
    approver,
    auto_approver,
)
from inspect_ai.dataset import Sample
from inspect_ai.event import ModelEvent, SentinelEvent, SpanBeginEvent, SpanEndEvent
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._assistant_internal import init_sample_assistant_internal
from inspect_ai.model._model import GenerateFilter, GenerateInput
from inspect_ai.model._model_data.model_data import ModelCost, ModelInfo
from inspect_ai.model._model_info import clear_model_info_cache, set_model_info
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.model._providers._google_computer_use_name import (
    gemini_computer_action_name,
)
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import (
    Tool,
    ToolCall,
    ToolCallContent,
    ToolCallView,
    ToolChoice,
    ToolInfo,
    tool,
)
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.tool._tool_call import default_tool_call_viewer
from inspect_ai.tool._tool_params import ToolParam, ToolParams
from inspect_ai.util._checkpoint import Manual
from inspect_ai.util._checkpoint._layout.host_context import read as read_host_context
from inspect_ai.util._checkpoint.checkpointer import Checkpointer, ResumeCheckpoint
from inspect_ai.util._checkpoint.config import ResolvedCheckpointConfig
from inspect_ai.util._limit import LimitExceededError, cost_limit
from inspect_ai.util._span import span

# mypy checks the tests against inspect_sentinel's API; they run on the fake
if TYPE_CHECKING:
    from inspect_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        monitor,
        protocol,
    )
else:
    from test_helpers.fake_sentinel import (
        AfterGenerate,
        AfterToolCall,
        BeforeGenerate,
        BeforeToolCall,
        Context,
        Decision,
        Escalations,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        monitor,
        protocol,
    )

pytestmark = pytest.mark.usefixtures("fake_sentinel")


TASK = "Tidy up the working directory."

Steps = list[BeforeToolCall | AfterToolCall]


@monitor
def bridge_recording(seen: Any) -> MonitorGroup:
    async def before(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(step)
        return Observation.score(0.1, "looked")

    async def after(context: Context, step: AfterToolCall) -> Observation | None:
        seen.append(step)
        return Observation.score(0.2, "looked at the result")

    return MonitorGroup(before, after)


@protocol
def bridge_reject(
    message: str | None = "Use a safer command.", seen: Any = None
) -> ProtocolGroup:
    async def decide(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.function == "bash":
            return Decision.reject("risky", message=message)
        return None

    async def later(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if seen is not None:
            seen.append(step)
        return None

    return ProtocolGroup(decide, later)


@protocol
def bridge_modify() -> Protocol:
    async def rewrite(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        modified = replace(step.call, arguments={"path": "safe.txt"})
        return Decision(action="modify", modified=modified, explanation="narrowed")

    return rewrite


@protocol
def bridge_terminate(after: bool = False) -> ProtocolGroup:
    async def before(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        return None if after else Decision.terminate("too risky")

    async def later(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        return Decision.terminate(f"saw {step.result.text}") if after else None

    return ProtocolGroup(before, later)


@protocol
def bridge_raising(after: bool = False) -> ProtocolGroup:
    async def before(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if not after:
            raise PermissionError("sentinel denied")
        return None

    async def later(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if after:
            raise PermissionError("sentinel denied")
        return None

    return ProtocolGroup(before, later)


@monitor
def bridge_waiting(started: Any, cleaned_up: Any) -> MonitorGroup:
    async def before(context: Context, step: BeforeToolCall) -> Observation | None:
        started.set()
        try:
            await anyio.sleep_forever()
        finally:
            cleaned_up.set()
        return None

    async def after(context: Context, step: AfterToolCall) -> Observation | None:
        return None

    return MonitorGroup(before, after)


@approver(name="bridge_sentinel_modify")
def modifying_approver() -> Approver:
    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision="modify", modified=replace(call, arguments={"path": "a.txt"})
        )

    return approve


@contextmanager
def active(sentinel: Any) -> Iterator[None]:
    init_sentinel(resolve_sentinel_root(resolve_sentinel_spec(sentinel)))
    try:
        yield
    finally:
        init_sentinel(None)


@pytest.fixture(autouse=True)
def fresh_transcript() -> None:
    init_transcript(Transcript())


@pytest.fixture(autouse=True)
def fresh_assistant_internal() -> None:
    # as each sample starts with its own: a provider's state for a call id
    # changes how a bridge hands over a later call reusing it
    init_sample_assistant_internal()


def calls_output(*calls: ToolCall, content: str = "On it.") -> ModelOutput:
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=content, tool_calls=list(calls)),
                stop_reason="tool_calls",
            )
        ],
    )


class Scripted:
    """A model that returns `outputs` in turn and records the input of each call."""

    def __init__(
        self, *outputs: ModelOutput, config: GenerateConfig | None = None
    ) -> None:
        self.outputs = list(outputs)
        self.inputs: list[list[ChatMessage]] = []

        def respond(
            input: list[ChatMessage], tools: Any, tool_choice: Any, config: Any
        ) -> ModelOutput:
            self.inputs.append(list(input))
            return self.outputs[min(len(self.inputs), len(self.outputs)) - 1]

        self.model = get_model(
            "mockllm/model",
            config=config or GenerateConfig(),
            custom_outputs=respond,
            memoize=False,
        )


async def generate(
    bridge: AgentBridge,
    model: Scripted,
    input: list[ChatMessage],
    tools: list[ToolInfo] | None = None,
) -> ModelOutput:
    output, _ = await bridge_generate(
        bridge,
        model.model,
        list(input),
        list(tools or []),
        None,
        GenerateConfig(),
        requested_model=None,
    )
    return output


def in_process_bridge(input: list[ChatMessage]) -> AgentBridge:
    return AgentBridge(AgentState(messages=list(input)))


READ_FILE = "Read a file from the host."


@tool
def read_file(mock: AsyncMock) -> Tool:
    async def execute(path: str) -> str:
        """Read a file from the host.

        Args:
            path: Path of the file to read.
        """
        result: str = await mock(path=path)
        return result

    return execute


def sandbox_bridge(
    tool: AsyncMock | None = None, tools: dict[str, Tool] | None = None
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        bridged_tools={"host": tools or {"read_file": read_file(tool or AsyncMock())}},
    )


def declare_read_file(name: str = "mcp__host__read_file") -> list[ToolInfo]:
    return [
        ToolInfo(
            name=name,
            description=READ_FILE,
            parameters=ToolParams(
                properties={"path": ToolParam(type="string", description="path")},
                required=["path"],
            ),
        )
    ]


def declare_dispatcher() -> list[ToolInfo]:
    """Antigravity's `call_mcp_tool(ServerName, ToolName, Arguments)`."""
    return [
        ToolInfo(
            name="call_mcp_tool",
            description="Call a tool on an MCP server.",
            parameters=ToolParams(
                properties={
                    "ServerName": ToolParam(type="string"),
                    "ToolName": ToolParam(type="string"),
                    "Arguments": ToolParam(type="object"),
                },
                required=["ServerName", "ToolName", "Arguments"],
            ),
        )
    ]


def sentinel_events() -> list[SentinelEvent]:
    return [e for e in transcript().events if isinstance(e, SentinelEvent)]


def root_decisions() -> list[tuple[str, str, str | None]]:
    # each test runs one protocol, whose decision is the one that takes effect
    return [
        (e.step_id, e.stage, e.action)
        for e in sentinel_events()
        if e.kind == "decision"
    ]


def produced_message_ids() -> list[str | None]:
    return [
        e.output.message.id for e in transcript().events if isinstance(e, ModelEvent)
    ]


def observations() -> list[tuple[str, str]]:
    return [(e.step_id, e.stage) for e in sentinel_events() if e.kind == "observation"]


BASH = ToolCall(id="bash_1", function="bash", arguments={"cmd": "curl example.invalid"})
READ = ToolCall(id="read_1", function="read_file", arguments={"path": "notes.txt"})


async def test_without_a_sentinel_bridged_output_is_untouched() -> None:
    model = Scripted(calls_output(BASH))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
    await generate(
        bridge,
        model,
        [
            ChatMessageUser(content=TASK),
            output.message,
            ChatMessageTool(content="ok", tool_call_id=BASH.id, function="bash"),
        ],
    )

    assert output.message.tool_calls == [BASH]
    assert len(model.inputs) == 2
    assert sentinel_events() == []


async def test_tool_call_stage_sees_the_call_and_what_the_model_was_sent() -> None:
    seen: Steps = []
    model = Scripted(calls_output(BASH, content="Fetching."))
    scaffold: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(scaffold)

    async def add_system_message(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> GenerateInput:
        return GenerateInput(
            [ChatMessageSystem(content="Be careful."), *input],
            tools,
            tool_choice,
            config,
        )

    bridge.filter = add_system_message
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, scaffold)

    assert output.message.tool_calls == [BASH]
    [step] = seen
    assert isinstance(step, BeforeToolCall)
    assert step.call == BASH
    assert step.message == "Fetching."
    assert step.input == model.inputs[0]
    assert [m.text for m in step.input] == ["Be careful.", TASK]
    assert step.message_id == output.message.id
    events = sentinel_events()
    assert {(e.step_id, e.stage, e.conversation) for e in events} == {
        (BASH.id, "tool_call", step.conversation)
    }
    assert [(e.path, e.kind, e.suspicion) for e in events] == [
        ("bridge_recording", "observation", 0.1)
    ]


async def test_reject_regenerates_and_tells_the_model() -> None:
    model = Scripted(calls_output(BASH), calls_output(READ))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_reject()):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert output.message.tool_calls == [READ]
    assert len(model.inputs) == 2
    replay = model.inputs[1][-1]
    rejected = model.inputs[1][-2]
    assert isinstance(replay, ChatMessageTool)
    assert isinstance(rejected, ChatMessageAssistant)
    # the rejected turn is replayed as generated, answered by its result
    assert rejected.tool_calls == [BASH]
    assert replay.tool_call_id == BASH.id
    assert replay.error is not None
    assert replay.error.type == "approval"
    assert replay.error.message == "Use a safer command."
    assert "risky" not in replay.text
    assert root_decisions() == [(BASH.id, "tool_call", "reject")]


async def test_reject_without_a_message_uses_the_default() -> None:
    model = Scripted(calls_output(BASH), calls_output(READ))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_reject(message=None)):
        await generate(bridge, model, [ChatMessageUser(content=TASK)])

    replay = model.inputs[1][-1]
    assert isinstance(replay, ChatMessageTool) and replay.error is not None
    assert replay.error.message == "Tool call not approved."


async def test_repeated_rejections_terminate_the_sample() -> None:
    model = Scripted(calls_output(BASH))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_reject()):
        with pytest.raises(TerminateSampleError, match="consecutive generations"):
            await generate(bridge, model, [ChatMessageUser(content=TASK)])


async def test_modify_rewrites_the_arguments_handed_to_the_scaffold() -> None:
    proposed = calls_output(READ)
    model = Scripted(proposed)
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_modify()):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert output.message.tool_calls == [replace(READ, arguments={"path": "safe.txt"})]
    # the model's proposal stays on the record
    assert proposed.message.tool_calls == [READ]
    [model_event] = [e for e in transcript().events if isinstance(e, ModelEvent)]
    assert model_event.output.message.tool_calls == [READ]
    [decision] = [e for e in sentinel_events() if e.path == ""]
    assert decision.action == "modify"
    assert decision.modified is not None
    assert decision.modified.arguments == {"path": "safe.txt"}


@monitor
def edits_in_place(change: str, seen: Any) -> MonitorGroup:
    """Changes the call it is shown in place, the first time, and returns nothing."""

    async def before(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(step)
        if len(seen) == 1:
            if change == "arguments":
                step.call.arguments["path"] = "/etc/shadow"
            elif change == "function":
                step.call.function = "write_file"
            else:
                step.call.id = "other"
        return None

    return MonitorGroup(before)


@pytest.mark.parametrize("dispatched", [False, True])
@pytest.mark.parametrize("change", ["arguments", "function", "id"])
async def test_a_call_a_monitor_changed_in_place_is_rejected(
    change: str, dispatched: bool
) -> None:
    seen: Steps = []
    tool = AsyncMock(return_value="contents")
    bridge = sandbox_bridge(tool)
    proposed = (
        ToolCall(
            id="d_1",
            function="call_mcp_tool",
            arguments={
                "ServerName": "host",
                "ToolName": "read_file",
                "Arguments": {"path": "notes.txt"},
            },
        )
        if dispatched
        else ToolCall(
            id="h_1", function="mcp__host__read_file", arguments={"path": "notes.txt"}
        )
    )
    model = Scripted(calls_output(proposed), calls_output(deepcopy(proposed)))

    with active([edits_in_place(change, seen)]):
        output = await generate(
            bridge,
            model,
            [ChatMessageUser(content=TASK)],
            declare_dispatcher() if dispatched else declare_read_file(),
        )
        # the edited call is denied; the call the model made runs
        with pytest.raises(PermissionError):
            await call_host_tool(bridge)("host", "read_file", {"path": "/etc/shadow"})
        await call_host_tool(bridge)("host", "read_file", {"path": "notes.txt"})

    # the edited response was rejected and the model generated again
    assert len(model.inputs) == 2
    [rejection] = [m for m in model.inputs[1] if isinstance(m, ChatMessageTool)]
    assert rejection.error is not None
    assert "changed the tool call in place" in rejection.error.message
    # proposed again after its rejection, the call keeps its id
    assert output.message.tool_calls == [proposed]
    tool.assert_awaited_once_with(path="notes.txt")
    # the second look saw the call as the model made it
    target = "read_file"
    assert (seen[1].call.function, seen[1].call.arguments) == (
        target,
        {"path": "notes.txt"},
    )


@protocol
def bridge_retarget() -> Protocol:
    async def rewrite(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        modified = replace(step.call, function="write_file")
        return Decision(action="modify", modified=modified, explanation="retargeted")

    return rewrite


RETARGETED = (
    "A sentinel monitor returned a modified call to 'write_file' for a call to "
    "'read_file'"
)


@protocol
def bridge_new_id() -> Protocol:
    async def rewrite(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        modified = replace(step.call, id="other", arguments={"path": "safe.txt"})
        return Decision(action="modify", modified=modified, explanation="new id")

    return rewrite


@pytest.mark.parametrize("sandbox", [False, True])
async def test_a_modify_that_changes_the_id_fails_the_sample(sandbox: bool) -> None:
    model = Scripted(calls_output(READ))
    bridge = sandbox_bridge() if sandbox else in_process_bridge([])

    with active(bridge_new_id()):
        with pytest.raises(
            RuntimeError,
            match="A sentinel monitor returned a modified call with id 'other' for "
            f"the call with id '{READ.id}'",
        ):
            await generate(bridge, model, [ChatMessageUser(content=TASK)])

    if sandbox:
        assert isinstance(bridge, SandboxAgentBridge)
        assert isinstance(bridge._failure, RuntimeError)


@monitor
def conversations(seen: Any) -> MonitorGroup:
    """Records the conversation each stage runs in."""

    async def before_generate(
        context: Context, step: BeforeGenerate
    ) -> Observation | None:
        seen.append(("generate", step.conversation))
        return None

    async def tool_call(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(("tool_call", step.conversation))
        return None

    async def tool_result(context: Context, step: AfterToolCall) -> Observation | None:
        seen.append(("tool_result", step.conversation))
        return None

    return MonitorGroup(before_generate, tool_call, tool_result)


class SubAgentSink:
    """A model event sink whose `on_start` runs each generate in the span `sub-agent`."""

    def on_start(self, input: list[ChatMessage]) -> str | None:
        return "sub-agent"

    def on_pending(self, event: ModelEvent) -> None:
        transcript()._event(event)

    def on_complete(self, event: ModelEvent) -> None:
        transcript()._event_updated(event)


@pytest.mark.parametrize("sink", [False, True])
def test_a_bridged_calls_stages_are_in_its_generations_conversation(
    sink: bool,
) -> None:
    seen: list[tuple[str, str]] = []
    # the solver's own argument is named generate
    bridged_generate = generate

    @solver
    def bridged() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            async with span("outer", type="agent", id="outer"):
                transcript()._event(
                    SpanBeginEvent(
                        id="sub-agent", parent_id="outer", type="agent", name="sub"
                    )
                )
                model = Scripted(calls_output(READ), calls_output())
                history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
                bridge = in_process_bridge(history)
                if sink:
                    bridge.model_event_sink = SubAgentSink()
                output = await bridged_generate(bridge, model, history)
                await bridged_generate(
                    bridge,
                    model,
                    [
                        *history,
                        output.message,
                        ChatMessageTool(content="x", tool_call_id=READ.id),
                    ],
                )
                transcript()._event(SpanEndEvent(id="sub-agent"))
            return state

        return solve

    [log] = eval(
        Task(
            dataset=[Sample(input="Hi.")],
            solver=bridged(),
            sentinel=[conversations(seen)],
        ),
        model="mockllm/model",
    )

    assert log.status == "success", log.error
    expected = "sub-agent" if sink else "outer"
    assert seen == [
        ("generate", expected),
        ("tool_call", expected),
        ("tool_result", expected),
        ("generate", expected),
    ]


async def test_a_bridged_calls_stages_do_not_see_the_enclosing_agents_messages() -> (
    None
):
    # the call belongs to the bridged scaffold, whose list the bridge rebuilds
    # from its requests, at the host tool's result stage too
    seen: Steps = []
    call = replace(READ, function="mcp__host__read_file")

    @agent(name="bridge_enclosing")
    def enclosing() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            bridge = sandbox_bridge(AsyncMock(return_value="contents"))
            await generate(
                bridge,
                Scripted(calls_output(call)),
                [ChatMessageUser(content=TASK)],
                declare_read_file(),
            )
            await call_host_tool(bridge)("host", "read_file", READ.arguments)
            return state

        return execute

    with active([bridge_recording(seen)]):
        await enclosing()(AgentState(messages=[ChatMessageUser(content="Outer.")]))

    assert [type(step) for step in seen] == [BeforeToolCall, AfterToolCall]
    assert [step.agent_messages for step in seen] == [None, None]


@pytest.mark.parametrize("sandbox", [False, True])
async def test_a_modify_that_changes_the_function_fails_the_sample(
    sandbox: bool,
) -> None:
    model = Scripted(calls_output(READ))
    bridge = sandbox_bridge() if sandbox else in_process_bridge([])

    with active(bridge_retarget()):
        with pytest.raises(RuntimeError, match=RETARGETED):
            await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert len(model.inputs) == 1
    if sandbox:
        # raised in the service task, so the bridge's monitor fails the sample
        assert isinstance(bridge, SandboxAgentBridge)
        assert isinstance(bridge._failure, RuntimeError)
        assert str(bridge._failure).startswith(RETARGETED)


async def test_a_modify_that_changes_a_dispatched_target_fails_the_sample() -> None:
    call = ToolCall(
        id="d_1",
        function="call_mcp_tool",
        arguments={
            "ServerName": "host",
            "ToolName": "read_file",
            "Arguments": {"path": "notes.txt"},
        },
    )
    bridge = sandbox_bridge()

    with active(bridge_retarget()):
        with pytest.raises(RuntimeError, match=RETARGETED):
            await generate(
                bridge, Scripted(calls_output(call)), [ChatMessageUser(content=TASK)]
            )

    assert isinstance(bridge._failure, RuntimeError)


@pytest.mark.parametrize("dialect", ["completions", "anthropic", "responses", "google"])
async def test_a_modify_that_changes_the_function_fails_each_dialect(
    dialect: str,
) -> None:
    model = Scripted(calls_output(READ))
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active(bridge_retarget()):
        with pytest.raises(RuntimeError, match=RETARGETED):
            await dialect_round_trip(dialect, bridge)

    assert len(model.inputs) == 1


async def test_terminate_ends_the_sample() -> None:
    model = Scripted(calls_output(BASH))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_terminate()):
        with pytest.raises(TerminateSampleError, match="too risky"):
            await generate(bridge, model, [ChatMessageUser(content=TASK)])


async def test_sandbox_terminate_propagates_without_signalling_the_monitor() -> None:
    model = Scripted(calls_output(BASH))
    bridge = sandbox_bridge()

    # the service dispatcher answers the RPC and propagates the termination
    with active(bridge_terminate()):
        with pytest.raises(TerminateSampleError, match="too risky"):
            await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert not bridge._failure_requested.is_set()


async def test_an_approvers_modify_reaches_the_sentinel() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    bridge.approval = [ApprovalPolicy(modifying_approver(), "*")]

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    [step] = seen
    assert step.call.arguments == {"path": "a.txt"}
    assert output.message.tool_calls == [replace(READ, arguments={"path": "a.txt"})]


async def test_an_approval_reject_skips_the_sentinel() -> None:
    seen: Steps = []
    model = Scripted(calls_output(BASH), calls_output(READ))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    bridge.approval = [
        ApprovalPolicy(auto_approver("reject"), "bash"),
        ApprovalPolicy(auto_approver("approve"), "*"),
    ]

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert output.message.tool_calls == [READ]
    assert [step.call.id for step in seen] == [READ.id]


async def test_tool_result_stage_runs_when_the_result_reaches_the_bridge() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ, content="Reading."), calls_output())
    scaffold: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(scaffold)

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, scaffold)
        result = ChatMessageTool(
            content="file contents", tool_call_id=READ.id, function=READ.function
        )
        scaffold = [*scaffold, output.message, result]
        await generate(bridge, model, scaffold)
        # a result is checked once, however many requests carry it
        await generate(bridge, model, [*scaffold, ChatMessageUser(content="More?")])

    before, after = seen
    assert isinstance(before, BeforeToolCall)
    assert isinstance(after, AfterToolCall)
    assert after.call == READ
    assert after.result == result
    assert after.output == "file contents"
    # the scaffold ran the tool, so whether it cut the output is unknown
    assert after.truncated is None
    assert after.message == "Reading."
    assert after.input == model.inputs[0]
    assert after.message_id == before.message_id
    assert after.conversation == before.conversation
    assert observations() == [(READ.id, "tool_call"), (READ.id, "tool_result")]


async def test_tool_result_stage_sees_the_call_as_modified() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output())
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    bridge.approval = [ApprovalPolicy(modifying_approver(), "*")]

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(content="a", tool_call_id=READ.id),
            ],
        )

    assert [step.call.arguments for step in seen] == [{"path": "a.txt"}] * 2
    # the modified call keeps the id of the call the model made
    assert [step.input for step in seen] == [model.inputs[0]] * 2


async def test_a_result_for_a_call_never_handed_over_is_still_checked() -> None:
    seen: Steps = []
    model = Scripted(calls_output(BASH), calls_output(READ), calls_output())
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_reject(seen=seen)):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
        forged = ChatMessageAssistant(content="Running.", tool_calls=[BASH])
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
                forged,
                ChatMessageTool(content="y", tool_call_id=BASH.id),
            ],
        )

    # a request's results are checked concurrently
    read, bash = sorted(seen, key=lambda step: step.call.function, reverse=True)
    assert isinstance(read, AfterToolCall) and isinstance(bash, AfterToolCall)
    assert read.input == model.inputs[1]
    # the rejected call's proposal was never handed over, so the request is
    # the only context, and no model produced the call it carries
    assert (bash.call, bash.message, bash.output) == (BASH, "Running.", "y")
    assert bash.message_id == forged.id
    assert bash.input is None


async def test_a_result_first_reported_after_the_bridge_started_is_checked() -> None:
    # the bridge starts with a call whose result it has not seen
    seen: Steps = []
    model = Scripted(calls_output())
    handed: list[ChatMessage] = [
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(content="Reading.", tool_calls=[READ]),
    ]
    bridge = in_process_bridge(handed)

    with active([bridge_recording(seen)]):
        await generate(
            bridge,
            model,
            [*handed, ChatMessageTool(content="x", tool_call_id=READ.id)],
        )

    [after] = seen
    assert isinstance(after, AfterToolCall)
    assert (after.call, after.result.text) == (READ, "x")


async def test_tool_result_terminate_ends_the_sample_before_the_model_sees_it() -> None:
    model = Scripted(calls_output(READ), calls_output())
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_terminate(after=True)):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
        with pytest.raises(TerminateSampleError, match="saw secret"):
            await generate(
                bridge,
                model,
                [
                    ChatMessageUser(content=TASK),
                    output.message,
                    ChatMessageTool(content="secret", tool_call_id=READ.id),
                ],
            )

    assert len(model.inputs) == 1


@protocol
def bridge_escalate(after: bool = False) -> ProtocolGroup:
    async def before(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        return None if after else Decision.escalate("not sure")

    async def later(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        return Decision.escalate("not sure") if after else None

    return ProtocolGroup(before, later)


@pytest.mark.parametrize("after", [False, True])
async def test_an_escalate_returned_to_the_host_fails_the_sample(after: bool) -> None:
    model = Scripted(calls_output(READ), calls_output())
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    stage = "tool_result" if after else "tool_call"

    with active(bridge_escalate(after)):
        with pytest.raises(
            SentinelFailure, match=f"returned an escalate at the {stage}"
        ):
            output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
            await generate(
                bridge,
                model,
                [
                    ChatMessageUser(content=TASK),
                    output.message,
                    ChatMessageTool(content="x", tool_call_id=READ.id),
                ],
            )

    assert len(model.inputs) == 1
    assert root_decisions() == [
        (READ.id, "tool_result" if after else "tool_call", "escalate")
    ]


async def test_host_tool_result_is_checked_in_the_service() -> None:
    seen: Steps = []
    read = ToolCall(
        id="host_1", function="mcp__host__read_file", arguments=READ.arguments
    )
    model = Scripted(calls_output(read), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value="host contents"))

    with active([bridge_recording(seen)]):
        output = await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        assert await call_host_tool(bridge)("host", "read_file", READ.arguments) == (
            "host contents"
        )
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(
                    content="host contents",
                    tool_call_id=read.id,
                    function=read.function,
                ),
            ],
            declare_read_file(),
        )

    _, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.call == replace(read, function="read_file")
    assert after.output == "host contents"
    assert after.truncated is False
    assert after.result.tool_call_id == read.id
    assert after.result.function == "read_file"
    assert after.result.text == "host contents"
    assert observations() == [(read.id, "tool_call"), (read.id, "tool_result")]


async def test_a_bridge_s_tool_checks_are_marked_for_replay() -> None:
    read = ToolCall(
        id="host_1", function="mcp__host__read_file", arguments=READ.arguments
    )
    model = Scripted(calls_output(read), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value="host contents"))

    with active([bridge_recording([])]):
        output = await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        await call_host_tool(bridge)("host", "read_file", READ.arguments)
        # the scaffold reports the host call's result changed, so it is
        # checked again
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(
                    content="host contents, edited",
                    tool_call_id=read.id,
                    function=read.function,
                ),
            ],
            declare_read_file(),
        )

    begins = {e.id: e for e in transcript().events if isinstance(e, SpanBeginEvent)}
    checks = {
        e.span_id: (e.stage, begins[e.span_id].type, begins[e.span_id].name)
        for e in sentinel_events()
        if e.span_id is not None
    }
    # a call, a host call's result, and the scaffold's report of it
    assert list(checks.values()) == [
        ("tool_call", "sentinel", "sentinel_bridge"),
        ("tool_result", "sentinel", "sentinel_bridge"),
        ("tool_result", "sentinel", "sentinel_bridge"),
    ]


async def test_host_tool_result_terminate_propagates_from_the_service() -> None:
    read = ToolCall(
        id="host_1", function="mcp__host__read_file", arguments=READ.arguments
    )
    model = Scripted(calls_output(read))
    bridge = sandbox_bridge(AsyncMock(return_value="secret"))

    with active(bridge_terminate(after=True)):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(TerminateSampleError, match="saw secret"):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    # the service dispatcher answers the RPC and propagates the termination
    assert not bridge._failure_requested.is_set()


@pytest.mark.parametrize("after", [False, True])
async def test_sentinel_errors_fail_the_sample(after: bool) -> None:
    model = Scripted(calls_output(READ), calls_output())
    bridge = sandbox_bridge()

    with active(bridge_raising(after=after)):
        with pytest.raises(SentinelFailure, match="sentinel denied"):
            output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
            await generate(
                bridge,
                model,
                [
                    ChatMessageUser(content=TASK),
                    output.message,
                    ChatMessageTool(content="x", tool_call_id=READ.id),
                ],
            )

    assert isinstance(bridge._failure, SentinelFailure)
    assert isinstance(bridge._failure.error, PermissionError)


@protocol
def bridge_grouped_failure(after: bool, reverse: bool) -> ProtocolGroup:
    async def before(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        if not after:
            fail()
        return None

    async def later(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if after:
            fail()
        return None

    def fail() -> None:
        limit = LimitExceededError("working", value=10, limit=5)
        defect = RuntimeError("grouped sentinel defect")
        leaves = [limit, defect]
        raise ExceptionGroup("sentinel failures", leaves[::-1] if reverse else leaves)

    return ProtocolGroup(before, later)


@tool
def bridge_unused_tool() -> Tool:
    async def execute() -> str:
        """A host tool that this test never calls."""
        return "ok"

    return execute


@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("after", [False, True])
async def test_grouped_bridge_sentinel_defect_fails_in_both_leaf_orders(
    sandbox: bool, after: bool
) -> None:
    for reverse in (False, True):
        model = Scripted(calls_output(READ), calls_output())
        bridge = (
            sandbox_bridge(tools={"unused": bridge_unused_tool()})
            if sandbox
            else in_process_bridge([])
        )
        with active(bridge_grouped_failure(after, reverse)):
            with pytest.raises(SentinelFailure) as raised:
                output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
                await generate(
                    bridge,
                    model,
                    [
                        ChatMessageUser(content=TASK),
                        output.message,
                        ChatMessageTool(content="x", tool_call_id=READ.id),
                    ],
                )
        assert isinstance(raised.value.error, ExceptionGroup)
        assert any(
            isinstance(error, RuntimeError) and str(error) == "grouped sentinel defect"
            for error in raised.value.error.exceptions
        )
        if sandbox:
            assert isinstance(bridge, SandboxAgentBridge)
            assert isinstance(bridge._failure, SentinelFailure)


@pytest.fixture
def priced_model() -> Iterator[None]:
    cost = ModelCost(
        input=1000.0, output=1000.0, input_cache_write=0.0, input_cache_read=0.0
    )
    set_model_info("model", ModelInfo(cost=cost))
    yield
    clear_model_info_cache()


@pytest.mark.timeout(30)
@pytest.mark.usefixtures("priced_model")
async def test_a_result_monitor_crossing_a_cost_limit_is_forwarded_once() -> None:
    # the limit is unwrapped from its SentinelFailure without a cause back to
    # it, so forwarding it (which walks causes) ends
    checks: list[AfterToolCall] = []
    judge = Scripted(calls_output())
    model = Scripted(calls_output())
    bridge = sandbox_bridge()

    @protocol
    def judging() -> Protocol:
        async def after(
            context: Context, step: AfterToolCall, escalations: Escalations
        ) -> Decision | None:
            checks.append(step)
            await judge.model.generate("Judge the tool result.")
            return None

        return after

    async def request(
        json_data: dict[str, JsonValue], headers: dict[str, str] | None = None
    ) -> dict[str, JsonValue]:
        await generate(bridge, model, conversation("result"))
        return {}

    forward = _forward_provider_errors(request, bridge)
    with cost_limit(0.001), active(judging()):
        first = await forward({})
        second = await forward({})

    assert PROVIDER_ERROR_KEY in first
    assert second == first
    assert bridge.generation_limit is not None
    assert bridge.generation_limit.type == "cost"
    assert bridge.generation_limit.__cause__ is None
    assert not isinstance(bridge.generation_limit.__context__, SentinelFailure)
    assert len(checks) == 1
    assert len(judge.inputs) == 1
    assert model.inputs == []


async def test_cancellation_during_the_tool_call_stage_propagates() -> None:
    started = anyio.Event()
    cleaned_up = anyio.Event()
    model = Scripted(calls_output(BASH))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    outputs: list[ModelOutput] = []

    with active([bridge_waiting(started, cleaned_up)]):
        with anyio.CancelScope() as scope:

            async def cancel() -> None:
                await started.wait()
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel)
                outputs.append(
                    await generate(bridge, model, [ChatMessageUser(content=TASK)])
                )

    assert scope.cancelled_caught
    assert cleaned_up.is_set()
    assert outputs == []
    assert [(e.path, e.status) for e in sentinel_events()] == [
        ("bridge_waiting", "cancelled"),
        ("", "cancelled"),
    ]


def openai_scaffold() -> Agent:
    """A minimal tool loop over the OpenAI client, running its tools itself."""

    @agent(name="openai_scaffold")
    def scaffold() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            from openai import AsyncOpenAI

            from inspect_ai.model._openai import messages_to_openai

            async with agent_bridge(state) as bridge:
                messages: list[Any] = await messages_to_openai(state.messages)
                async with AsyncOpenAI(api_key="sk-test") as client:
                    for _ in range(3):
                        completion = await client.chat.completions.create(
                            model="inspect",
                            messages=messages,
                            tools=[
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "description": "Read a file.",
                                        "parameters": {
                                            "type": "object",
                                            "properties": {"path": {"type": "string"}},
                                        },
                                    },
                                }
                            ],
                        )
                        message = completion.choices[0].message
                        messages.append(message.model_dump(exclude_none=True))
                        if not message.tool_calls:
                            break
                        for call in message.tool_calls:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call.id,
                                    "content": "file contents",
                                }
                            )
                return bridge.state

        return execute

    return scaffold()


def test_an_in_process_bridged_agent_runs_both_stages() -> None:
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            calls_output(READ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
        memoize=False,
    )
    seen: Steps = []
    log = eval(
        Task(
            dataset=[Sample(input=TASK)],
            solver=openai_scaffold(),
            sentinel=[bridge_recording(seen)],
        ),
        model=model,
    )[0]

    assert log.status == "success", log.error
    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, SentinelEvent)]
    assert [(e.step_id, e.stage, e.kind) for e in events] == [
        (READ.id, "tool_call", "observation"),
        (READ.id, "tool_result", "observation"),
    ]
    assert len({e.conversation for e in events}) == 1
    before, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.result.text == "file contents"
    model_events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert after.input == model_events[0].input


@monitor
def every_stage(seen: Any) -> MonitorGroup:
    async def model_input(context: Context, step: BeforeGenerate) -> Observation | None:
        seen.append(step)
        return None

    async def model_output(context: Context, step: AfterGenerate) -> Observation | None:
        seen.append(step)
        return None

    async def tool_call(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(step)
        return None

    async def tool_result(context: Context, step: AfterToolCall) -> Observation | None:
        seen.append(step)
        return None

    return MonitorGroup(model_input, model_output, tool_call, tool_result)


def test_a_bridged_agent_runs_every_stage_once_in_order() -> None:
    model = get_model(
        "mockllm/model",
        config=GenerateConfig(system_message="Be careful."),
        custom_outputs=[
            calls_output(READ),
            ModelOutput.from_content("mockllm/model", "done"),
        ],
        memoize=False,
    )
    seen: list[Any] = []
    log = eval(
        Task(
            dataset=[Sample(input=TASK)],
            solver=openai_scaffold(),
            sentinel=[every_stage(seen)],
        ),
        model=model,
    )[0]

    assert log.status == "success", log.error
    # each generation is checked inside Model.generate, and its tool calls once
    # the response comes back to the bridge, before the scaffold receives them;
    # a call's result is checked when the scaffold reports it, before the next
    # generation
    assert [type(step) for step in seen] == [
        BeforeGenerate,
        AfterGenerate,
        BeforeToolCall,
        AfterToolCall,
        BeforeGenerate,
        AfterGenerate,
    ]
    generated, call, result = seen[1], seen[2], seen[3]
    assert call.input == result.input == generated.input
    assert call.input[0].text == "Be careful."


async def test_a_dispatched_call_is_checked_as_its_target() -> None:
    seen: Steps = []
    call = ToolCall(
        id="d_1",
        function="call_mcp_tool",
        arguments={
            "ServerName": "host",
            "ToolName": "read_file",
            "Arguments": {"path": "notes.txt"},
        },
    )
    model = Scripted(calls_output(call))
    bridge = sandbox_bridge()

    with active([bridge_modify(), bridge_recording(seen)]):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    [step] = seen
    assert (step.call.id, step.call.function) == ("d_1", "read_file")
    assert step.input == model.inputs[0]
    assert output.message.tool_calls == [
        replace(
            call,
            arguments={
                "ServerName": "host",
                "ToolName": "read_file",
                "Arguments": {"path": "safe.txt"},
            },
        )
    ]


async def test_an_approval_reject_of_a_sibling_runs_no_sentinel() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ, BASH), calls_output(READ))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    bridge.approval = [
        ApprovalPolicy(auto_approver("reject"), "bash"),
        ApprovalPolicy(auto_approver("approve"), "*"),
    ]

    with active([bridge_recording(seen)]):
        await generate(bridge, model, [ChatMessageUser(content=TASK)])

    # only the regenerated response reached the sentinel
    assert [step.call.id for step in seen] == [READ.id]


async def test_a_google_result_is_matched_to_the_call_handed_over() -> None:
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    tools: Any = [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ]
        }
    ]
    user: Any = {"role": "user", "parts": [{"text": TASK}]}

    with active([bridge_recording(seen)]):
        first = await inspect_google_api_request(
            {"model": "inspect", "contents": [user], "tools": tools},
            None,
            None,
            bridge,
        )
        parts: Any = first["candidates"][0]["content"]["parts"]
        response: Any = {
            "role": "user",
            "parts": [
                {"functionResponse": {"name": "read_file", "response": {"out": "x"}}}
            ],
        }
        await inspect_google_api_request(
            {
                "model": "inspect",
                "contents": [user, {"role": "model", "parts": parts}, response],
                "tools": tools,
            },
            None,
            None,
            bridge,
        )

    before, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.call == before.call
    assert [(e.step_id, e.stage) for e in sentinel_events()] == [
        (READ.id, "tool_call"),
        (READ.id, "tool_result"),
    ]


async def test_a_host_call_that_fails_validation_has_no_tool_result_stage() -> None:
    seen: Steps = []
    read = ToolCall(id="host_1", function="mcp__host__read_file", arguments={"path": 1})
    model = Scripted(calls_output(read), calls_output())
    tool = AsyncMock(return_value="x")
    bridge = sandbox_bridge(tool)

    with active([bridge_recording(seen)]):
        output = await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(ToolParsingError):
            await call_host_tool(bridge)("host", "read_file", {"path": 1})
        assert [type(step) for step in seen] == [BeforeToolCall]
        # what the scaffold then reports for the call is its own content
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(content="bad arguments", tool_call_id=read.id),
            ],
            declare_read_file(),
        )

    tool.assert_not_awaited()
    _, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.result.text == "bad arguments"


async def test_a_host_call_matching_several_proposals_gets_no_proposal_context() -> (
    None
):
    seen: Steps = []
    stale = ToolCall(
        id="stale", function="mcp__host__read_file", arguments=READ.arguments
    )
    fresh = replace(stale, id="fresh")
    model = Scripted(calls_output(stale), calls_output(fresh))
    bridge = sandbox_bridge(AsyncMock(return_value="contents"))

    with active([bridge_recording(seen)]):
        # the scaffold never ran the first response's call
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        await call_host_tool(bridge)("host", "read_file", READ.arguments)
        # the scaffold reports the result under either call's id: it was
        # checked for both
        for call in [stale, fresh]:
            await generate(
                bridge,
                model,
                [
                    ChatMessageUser(content=TASK),
                    ChatMessageAssistant(content="On it.", tool_calls=[call]),
                    ChatMessageTool(
                        content="contents", tool_call_id=call.id, function=call.function
                    ),
                ],
                declare_read_file(),
            )

    # an MCP call carries no call id, so which execution it is can't be told
    [after] = [step for step in seen if isinstance(step, AfterToolCall)]
    assert after.call.id not in {"stale", "fresh"}
    assert after.call.function == "read_file"
    assert after.message == "" and after.input is None


def read_file_view(call: ToolCall) -> ToolCallView:
    return ToolCallView(
        call=ToolCallContent(
            format="markdown", content=f"Reading `{call.arguments['path']}`"
        )
    )


@tool(viewer=read_file_view)
def viewed_read_file(mock: AsyncMock) -> Tool:
    async def execute(path: str) -> str:
        """Read a file from the host.

        Args:
            path: Path of the file to read.
        """
        result: str = await mock(path=path)
        return result

    return execute


async def test_a_host_tool_is_viewed_with_its_registered_viewer() -> None:
    seen: Steps = []
    read = ToolCall(
        id="host_1", function="mcp__host__read_file", arguments=READ.arguments
    )
    model = Scripted(calls_output(read, BASH), calls_output())
    bridge = sandbox_bridge(
        tools={"viewed_read_file": viewed_read_file(AsyncMock(return_value="contents"))}
    )

    with active([bridge_recording(seen)]):
        output = await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        await call_host_tool(bridge)("host", "viewed_read_file", READ.arguments)
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(content="contents", tool_call_id=read.id),
                ChatMessageTool(content="ok", tool_call_id=BASH.id),
            ],
            declare_read_file(),
        )

    views = {(step.call.id, type(step)): step.view for step in seen}
    assert len(views) == 4
    for stage in (BeforeToolCall, AfterToolCall):
        host_view = views[(read.id, stage)].call
        assert host_view is not None
        assert host_view.content == "Reading `notes.txt`"
        assert views[(BASH.id, stage)] == default_tool_call_viewer(BASH)


async def test_a_dispatched_call_is_viewed_with_its_targets_viewer() -> None:
    seen: Steps = []
    call = ToolCall(
        id="d_1",
        function="call_mcp_tool",
        arguments={
            "ServerName": "host",
            "ToolName": "viewed_read_file",
            "Arguments": {"path": "notes.txt"},
        },
    )
    model = Scripted(calls_output(call))
    bridge = sandbox_bridge(tools={"viewed_read_file": viewed_read_file(AsyncMock())})

    with active([bridge_recording(seen)]):
        await generate(bridge, model, [ChatMessageUser(content=TASK)])

    [step] = seen
    assert step.view.call is not None
    assert step.view.call.content == "Reading `notes.txt`"


def test_dropping_old_proposals_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from inspect_ai._util import logger as inspect_logger
    from inspect_ai.agent._bridge import _sentinel

    monkeypatch.setattr(_sentinel, "_MAX_PROPOSALS", 2)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    bridge = in_process_bridge([])
    request = _sentinel.bridged_request([])
    calls = [replace(READ, id=f"read_{i}") for i in range(4)]
    checks = [
        _sentinel.SentinelCheck(call, call, None, "", "message_1") for call in calls
    ]

    with caplog.at_level("WARNING"):
        bridge._handed_calls.hand_over(request, calls[:3], calls[:3], checks[:3])
        bridge._handed_calls.hand_over(request, calls[3:], calls[3:], checks[3:])

    warnings = [
        r for r in caplog.records if "the oldest proposal was dropped" in r.message
    ]
    assert len(warnings) == 1
    proposals = bridge._handed_calls.proposals.values()
    assert [p.handed.id for p in proposals] == ["read_2", "read_3"]


def test_claiming_a_requests_results_takes_memory_linear_in_its_results() -> None:
    import tracemalloc

    from inspect_ai.agent._bridge._sentinel import _HandedCalls

    def claimed_bytes(results: int) -> int:
        input: list[ChatMessage] = [ChatMessageUser(content=TASK)]
        for index in range(results):
            call = replace(READ, id=f"read_{index}", arguments={"path": f"{index}"})
            input += [
                ChatMessageAssistant(content="", tool_calls=[call]),
                ChatMessageTool(content=f"{index}", tool_call_id=call.id),
            ]
        tracemalloc.start()
        try:
            claimed = _HandedCalls(
                _SavedHandedCalls(reserved_ids=[], handed={}, checked=[])
            ).claim(input)
            retained, _ = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert len(claimed.owned) == results
        return retained

    # linear is about 4x; copying each result's conversation is about 16x
    assert claimed_bytes(4000) < 6 * claimed_bytes(1000)


def _multipart_request(dialect: str, text: int, calls: int) -> list[Any]:
    """A request whose assistant turn has two text parts and `calls` calls, each answered."""
    half = "x" * (text // 2)
    ids = [f"call_{index}" for index in range(calls)]
    if dialect == "completions":
        return [
            {"role": "user", "content": TASK},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": half}] * 2,
                "tool_calls": [
                    {
                        "id": id,
                        "type": "function",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({"p": id}),
                        },
                    }
                    for id in ids
                ],
            },
            *[{"role": "tool", "tool_call_id": id, "content": id} for id in ids],
        ]
    if dialect == "responses":
        return [
            {"type": "message", "role": "user", "content": TASK},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": half, "annotations": []}]
                * 2,
            },
            *[
                {
                    "type": "function_call",
                    "call_id": id,
                    "name": "read",
                    "arguments": json.dumps({"p": id}),
                }
                for id in ids
            ],
            *[
                {"type": "function_call_output", "call_id": id, "output": id}
                for id in ids
            ],
        ]
    if dialect == "anthropic":
        return [
            {"role": "user", "content": TASK},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": half}] * 2
                + [
                    {"type": "tool_use", "id": id, "name": "read", "input": {"p": id}}
                    for id in ids
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": id, "content": id}
                    for id in ids
                ],
            },
        ]
    return [
        {"role": "user", "parts": [{"text": TASK}]},
        {
            "role": "model",
            "parts": [{"text": half}] * 2
            + [
                {"functionCall": {"id": id, "name": "read", "args": {"p": id}}}
                for id in ids
            ],
        },
        {
            "role": "user",
            "parts": [
                {"functionResponse": {"id": id, "name": "read", "response": {"o": id}}}
                for id in ids
            ],
        },
    ]


async def _converted(dialect: str, request: list[Any]) -> list[ChatMessage]:
    from inspect_ai.agent._bridge.anthropic_api_impl import (
        messages_from_anthropic_input,
    )
    from inspect_ai.agent._bridge.google_api_impl import messages_from_google_contents
    from inspect_ai.agent._bridge.responses_impl import messages_from_responses_input
    from inspect_ai.model._openai_convert import messages_from_openai

    if dialect == "completions":
        return await messages_from_openai(request, "model")
    if dialect == "responses":
        return messages_from_responses_input(request, [], "model")
    if dialect == "anthropic":
        return await messages_from_anthropic_input(request, [])
    return messages_from_google_contents(request, None, call_ids=True)


@pytest.mark.parametrize("dialect", ["completions", "responses", "anthropic", "google"])
async def test_scanning_a_requests_results_takes_memory_linear_in_its_size(
    dialect: str,
) -> None:
    import tracemalloc

    from inspect_ai.agent._bridge._sentinel import (
        _HandedCalls,
        inherited_result_keys,
    )

    async def peak_bytes(text: int, calls: int) -> int:
        input = await _converted(dialect, _multipart_request(dialect, text, calls))
        [assistant] = [m for m in input if isinstance(m, ChatMessageAssistant)]
        assert isinstance(assistant.content, list)
        assert len(assistant.tool_calls or []) == calls
        tracemalloc.start()
        try:
            claimed = _HandedCalls(
                _SavedHandedCalls(reserved_ids=[], handed={}, checked=[])
            ).claim(input)
            _, claim_peak = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            inherited = inherited_result_keys(input)
            _, inherited_peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert len(claimed.owned) == len(inherited) == calls
        return max(claim_peak, inherited_peak)

    # the request grows about 1.1x with 4x the text, and 3-4x with 4x the
    # calls; a copy of the text per call grows 4x with either
    assert await peak_bytes(32768, 1000) < 1.5 * await peak_bytes(8192, 1000)
    assert await peak_bytes(32768, 1000) < 6 * await peak_bytes(32768, 250)


def test_results_answering_one_call_key_its_arguments_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.agent._bridge import _sentinel

    keyed: list[ToolCall] = []
    call_key = _sentinel._call_key

    def counting_call_key(call: ToolCall, orphan: str | None = None) -> str:
        keyed.append(call)
        return call_key(call, orphan)

    monkeypatch.setattr(_sentinel, "_call_key", counting_call_key)
    input: list[ChatMessage] = [
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(content="", tool_calls=[READ]),
        *[
            ChatMessageTool(content=f"{index}", tool_call_id=READ.id)
            for index in range(100)
        ],
    ]

    keys = _sentinel.inherited_result_keys(input)
    claimed = _sentinel._HandedCalls(
        _sentinel._SavedHandedCalls(reserved_ids=[], handed={}, checked=[])
    ).claim(input)

    assert len(keys) == len(claimed.owned) == 100
    assert len(keyed) == 2


async def test_a_host_result_for_several_executions_is_keyed_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.agent._bridge import _sentinel

    keyed: list[ChatMessageTool] = []
    content_key = _sentinel._content_key

    def counting_content_key(result: ChatMessageTool) -> str:
        keyed.append(result)
        return content_key(result)

    monkeypatch.setattr(_sentinel, "_content_key", counting_content_key)
    bridge = in_process_bridge([])
    candidates = [
        _sentinel.SentinelCheck(
            READ, READ, None, "", "message_1", execution_id=f"t{index}"
        )
        for index in range(50)
    ]

    await _sentinel.sentinel_host_tool_result(
        bridge, candidates[0], "contents", "contents", candidates=candidates
    )

    assert len(keyed) == 1
    # the call key they share (none of them was handed over)
    assert len(bridge._handed_calls.checked) == 1


async def test_a_result_whose_proposal_was_dropped_is_still_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.agent._bridge import _sentinel

    monkeypatch.setattr(_sentinel, "_MAX_PROPOSALS", 1)
    first = replace(READ, id="first")
    second = replace(READ, id="second", arguments={"path": "other"})
    model = Scripted(calls_output(first, content="Reading."), calls_output(second))
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    with active(terminate_on_secret()):
        one = await generate(bridge, model, history)
        await generate(bridge, model, history)
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(
                bridge,
                model,
                [
                    *history,
                    one.message,
                    ChatMessageTool(content="secret", tool_call_id=first.id),
                ],
            )


@protocol
def terminate_on_secret() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if "secret" in step.result.text:
            return Decision.terminate("blocked secret")
        return None

    return after


@pytest.mark.parametrize("repeat_arguments", [False, True])
async def test_an_earlier_result_never_takes_a_later_calls_check(
    repeat_arguments: bool,
) -> None:
    first = replace(READ, id="first")
    second = replace(
        READ,
        id="second",
        arguments=READ.arguments if repeat_arguments else {"path": "other"},
    )
    model = Scripted(calls_output(first), calls_output(second), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    with active(terminate_on_secret()):
        one = await generate(bridge, model, history)
        history += [
            one.message,
            ChatMessageTool(content="benign", tool_call_id="first"),
        ]
        two = await generate(bridge, model, history)
        history += [
            two.message,
            ChatMessageTool(content="secret", tool_call_id="second"),
        ]
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(bridge, model, history)

    assert len(model.inputs) == 2


@pytest.mark.parametrize("sandbox", [False, True])
async def test_repeated_calls_are_checked_with_their_own_results(
    sandbox: bool,
) -> None:
    seen: Steps = []
    calls = [replace(READ, id=f"read_{i}") for i in range(3)]
    model = Scripted(*[calls_output(call) for call in calls], calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = sandbox_bridge() if sandbox else in_process_bridge(history)

    with active([bridge_recording(seen)]):
        for index, call in enumerate(calls):
            output = await generate(bridge, model, history)
            history += [
                output.message,
                ChatMessageTool(content=f"output {index}", tool_call_id=call.id),
            ]
        await generate(bridge, model, history)

    assert [(s.call.id, s.output) for s in seen if isinstance(s, AfterToolCall)] == [
        (call.id, f"output {index}") for index, call in enumerate(calls)
    ]


async def google_round_trips(
    bridge: AgentBridge, model: Scripted, outputs: list[str]
) -> None:
    """A Google scaffold running each call it is handed, reporting `outputs` in turn."""
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    tools: Any = [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ]
        }
    ]
    contents: list[Any] = [{"role": "user", "parts": [{"text": TASK}]}]
    for output in [*outputs, None]:
        response: Any = await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )
        if output is not None:
            contents += [
                {
                    "role": "model",
                    "parts": response["candidates"][0]["content"]["parts"],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "read_file",
                                "response": {"out": output},
                            }
                        }
                    ],
                },
            ]


async def test_google_results_of_repeated_calls_are_each_checked() -> None:
    seen: Steps = []
    calls = [replace(READ, id=f"read_{i}") for i in range(3)]
    model = Scripted(*[calls_output(call) for call in calls], calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_recording(seen)]):
        await google_round_trips(bridge, model, ["same", "same", "new"])

    # Google mints the same id for each call, but each is its own execution
    assert [(s.call.id, s.output) for s in seen if isinstance(s, AfterToolCall)] == [
        ("read_0", '{"out": "same"}'),
        ("read_1", '{"out": "same"}'),
        ("read_2", '{"out": "new"}'),
    ]


async def test_google_identical_results_of_repeated_calls_are_each_checked() -> None:
    seen: Steps = []
    calls = [replace(READ, id=f"read_{i}") for i in range(3)]
    model = Scripted(*[calls_output(call) for call in calls], calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_recording(seen)]):
        await google_round_trips(bridge, model, ["same", "same", "same"])

    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [s.call.id for s in afters] == ["read_0", "read_1", "read_2"]
    # each with the input of the generation that proposed it
    assert [s.input for s in afters] == model.inputs[:3]


@pytest.mark.parametrize("ids", [("123", "read_file__123"), ("read_file__123", "123")])
@pytest.mark.parametrize("echo", ["unchanged", "prefix_first", "prefix_second"])
async def test_google_echoes_preserve_distinct_issued_call_ids(
    ids: tuple[str, str],
    echo: str,
) -> None:
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    seen: Steps = []
    calls = [
        replace(READ, id=ids[0], arguments={"path": "one"}),
        replace(READ, id=ids[1], arguments={"path": "two"}),
    ]
    model = Scripted(calls_output(*calls), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    tools: Any = [{"functionDeclarations": [{"name": "read_file"}]}]
    contents: list[Any] = [{"role": "user", "parts": [{"text": TASK}]}]

    with active([bridge_recording(seen)]):
        first: Any = await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )
        parts = first["candidates"][0]["content"]["parts"]
        issued = [
            part["functionCall"]["id"] for part in parts if "functionCall" in part
        ]
        assert len(issued) == 2
        assert issued[0] != "read_file__" + issued[1]
        assert issued[1] != "read_file__" + issued[0]
        if echo != "unchanged":
            target = 0 if echo == "prefix_first" else 1
            for index, part in enumerate(
                part for part in parts if "functionCall" in part
            ):
                if index == target:
                    part["functionCall"]["id"] = "read_file__" + issued[index]
        response_parts = [
            {
                "functionResponse": {
                    "id": part["functionCall"]["id"],
                    "name": "read_file",
                    "response": {"out": "same"},
                }
            }
            for part in parts
            if "functionCall" in part
        ]
        contents += [
            {"role": "model", "parts": parts},
            {"role": "user", "parts": response_parts},
        ]
        await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )

    before = [step for step in seen if isinstance(step, BeforeToolCall)]
    after = [step for step in seen if isinstance(step, AfterToolCall)]
    assert [step.call.arguments for step in before] == [
        {"path": "one"},
        {"path": "two"},
    ]
    assert sorted(
        (step.call.arguments for step in after), key=lambda args: args["path"]
    ) == [
        {"path": "one"},
        {"path": "two"},
    ]
    parsed = model.inputs[1]
    assert [
        call.id
        for message in parsed
        if isinstance(message, ChatMessageAssistant)
        for call in message.tool_calls or []
    ] == issued
    assert [
        message.tool_call_id
        for message in parsed
        if isinstance(message, ChatMessageTool)
    ] == issued


OLD_REQUEST = "Old request: confidential context"
NEW_REQUEST = "New unrelated request"


async def test_google_overlapping_requests_keep_their_own_context() -> None:
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    seen: Steps = []
    model = Scripted(
        calls_output(replace(READ, id="old")),
        calls_output(replace(READ, id="new")),
        calls_output(),
    )
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    tools: Any = [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ]
        }
    ]

    async def request(contents: list[Any]) -> Any:
        return await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )

    old_user = {"role": "user", "parts": [{"text": OLD_REQUEST}]}
    with active([bridge_recording(seen)]):
        old = await request([old_user])
        await request([{"role": "user", "parts": [{"text": NEW_REQUEST}]}])
        # the same call, made with the same arguments in both conversations,
        # answered first in the older one
        await request(
            [
                old_user,
                {"role": "model", "parts": old["candidates"][0]["content"]["parts"]},
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": "read_file",
                                "response": {"out": "old result"},
                            }
                        }
                    ],
                },
            ]
        )

    [after] = [s for s in seen if isinstance(s, AfterToolCall)]
    assert after.call.id == "old"
    assert after.input == model.inputs[0]
    assert after.message_id == produced_message_ids()[0]


@pytest.mark.parametrize("same_id", [False, True])
async def test_a_result_never_takes_another_outstanding_calls_context(
    same_id: bool,
) -> None:
    seen: Steps = []
    old_call = READ if same_id else replace(READ, id="old")
    new_call = READ if same_id else replace(READ, id="new")
    model = Scripted(calls_output(old_call), calls_output(new_call), calls_output())
    bridge = in_process_bridge([])
    old_history: list[ChatMessage] = [ChatMessageUser(content=OLD_REQUEST)]

    with active([bridge_recording(seen)]):
        old = await generate(bridge, model, old_history)
        await generate(bridge, model, [ChatMessageUser(content=NEW_REQUEST)])
        await generate(
            bridge,
            model,
            [
                *old_history,
                old.message,
                ChatMessageTool(content="old result", tool_call_id=old_call.id),
            ],
        )

    [after] = [s for s in seen if isinstance(s, AfterToolCall)]
    assert after.call == old_call
    assert after.input == model.inputs[0]
    assert after.message_id == old.message.id


async def test_a_result_whose_proposal_was_evicted_gets_no_other_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.agent._bridge import _sentinel

    monkeypatch.setattr(_sentinel, "_MAX_PROPOSALS", 1)
    seen: Steps = []
    old_call, new_call = replace(READ, id="old"), replace(READ, id="new")
    model = Scripted(calls_output(old_call), calls_output(new_call), calls_output())
    bridge = in_process_bridge([])
    old_history: list[ChatMessage] = [ChatMessageUser(content=OLD_REQUEST)]

    with active([bridge_recording(seen)]):
        old = await generate(bridge, model, old_history)
        await generate(bridge, model, [ChatMessageUser(content=NEW_REQUEST)])
        # as parsed back from a dialect: the scaffold's message has a new id
        echoed = old.message.model_copy(update={"id": "echoed"})
        await generate(
            bridge,
            model,
            [
                *old_history,
                echoed,
                ChatMessageTool(content="old result", tool_call_id="old"),
            ],
        )

    [after] = [s for s in seen if isinstance(s, AfterToolCall)]
    assert after.call == old_call
    assert after.message_id == echoed.id
    assert after.input is None


async def test_a_result_keeps_its_proposal_when_the_system_prompt_changes() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    with active([bridge_recording(seen)]):
        output = await generate(
            bridge, model, [ChatMessageSystem(content="Monday."), *history]
        )
        echoed = output.message.model_copy(update={"id": "echoed"})
        await generate(
            bridge,
            model,
            [
                ChatMessageSystem(content="Tuesday."),
                *history,
                echoed,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.message_id == before.message_id
    assert after.input == model.inputs[0]


PATH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string"}},
}


async def dialect_round_trip(
    dialect: str, bridge: AgentBridge, results: Sequence[Any] = ("x",)
) -> None:
    """A scaffold sending one request, then its response and the call's result.

    With several `results`, a request is sent with each in turn, as a
    scaffold reporting the call's result again, changed.
    """
    if dialect == "completions":
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        messages: list[Any] = [
            {"role": "system", "content": "Be careful."},
            {"role": "user", "content": TASK},
        ]
        tools: Any = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": PATH_SCHEMA,
                },
            }
        ]
        completion = await inspect_completions_api_request(
            {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
        )
        message = completion.choices[0].message
        assert message.tool_calls
        call_id = message.tool_calls[0].id
        messages.append(message.model_dump(exclude_none=True))
        for text in results:
            await inspect_completions_api_request(
                {
                    "model": "inspect",
                    "messages": [
                        *messages,
                        {"role": "tool", "tool_call_id": call_id, "content": text},
                    ],
                    "tools": tools,
                },
                None,
                bridge,
            )
    elif dialect == "anthropic":
        from inspect_ai.agent._bridge.anthropic_api import (
            inspect_anthropic_api_request,
        )

        turns: list[Any] = [{"role": "user", "content": TASK}]
        anthropic_tools: Any = [
            {
                "name": "read_file",
                "description": "Read a file.",
                "input_schema": PATH_SCHEMA,
            }
        ]

        def request() -> dict[str, Any]:
            return {
                "model": "inspect",
                "max_tokens": 100,
                "system": "Be careful.",
                "messages": turns,
                "tools": anthropic_tools,
            }

        response = await inspect_anthropic_api_request(
            request(), None, None, None, bridge
        )
        content = [block.model_dump(exclude_none=True) for block in response.content]
        [use] = [block for block in content if block["type"] == "tool_use"]
        turns.append({"role": "assistant", "content": content})
        for text in results:
            turns[2:] = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": use["id"],
                            "content": text,
                        }
                    ],
                }
            ]
            await inspect_anthropic_api_request(request(), None, None, None, bridge)
    elif dialect == "google":
        from inspect_ai.agent._bridge.google_api import inspect_google_api_request

        contents: list[Any] = [{"role": "user", "parts": [{"text": TASK}]}]
        google_tools: Any = [
            {
                "functionDeclarations": [
                    {
                        "name": "read_file",
                        "description": "Read a file.",
                        "parameters": PATH_SCHEMA,
                    }
                ]
            }
        ]

        def google_request() -> dict[str, Any]:
            return {
                "model": "inspect",
                "systemInstruction": {"parts": [{"text": "Be careful."}]},
                "contents": contents,
                "tools": google_tools,
            }

        first: Any = await inspect_google_api_request(
            google_request(), None, None, bridge
        )
        parts = first["candidates"][0]["content"]["parts"]
        [function_call] = [p["functionCall"] for p in parts if "functionCall" in p]
        contents.append({"role": "model", "parts": parts})
        for text in results:
            contents[2:] = [
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": function_call.get("id"),
                                "name": "read_file",
                                "response": {"output": text},
                            }
                        }
                    ],
                }
            ]
            await inspect_google_api_request(google_request(), None, None, bridge)
    else:
        from inspect_ai.agent._bridge.responses import inspect_responses_api_request

        items: list[Any] = [{"role": "user", "content": TASK}]
        responses_tools: Any = [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file.",
                "parameters": PATH_SCHEMA,
            }
        ]

        def responses_request() -> dict[str, Any]:
            return {
                "model": "inspect",
                "instructions": "Be careful.",
                "input": items,
                "tools": responses_tools,
            }

        result = await inspect_responses_api_request(
            responses_request(), None, None, None, bridge
        )
        output = [item.model_dump(exclude_none=True) for item in result.output]
        [call] = [item for item in output if item["type"] == "function_call"]
        items += output
        answered = len(items)
        for text in results:
            items[answered:] = [
                {
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": text,
                }
            ]
            await inspect_responses_api_request(
                responses_request(), None, None, None, bridge
            )


DIALECTS = ["completions", "anthropic", "responses", "google"]


async def dialect_history_request(
    dialect: str, bridge: AgentBridge, call: ToolCall, result: str
) -> None:
    """A scaffold sending the conversation it was handed (a task, a call, its result) in `dialect`."""
    await dialect_turns_request(dialect, bridge, [(call, result)])


async def dialect_turns_request(
    dialect: str, bridge: AgentBridge, turns: Sequence[tuple[ToolCall, str]]
) -> None:
    """A scaffold sending a task, then each call with its result, in `dialect`."""
    if dialect == "completions":
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        messages: list[Any] = [{"role": "user", "content": TASK}]
        for call, result in turns:
            messages += [
                {
                    "role": "assistant",
                    "content": "Reading.",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": call.id, "content": result},
            ]
        await inspect_completions_api_request(
            {"model": "inspect", "messages": messages}, None, bridge
        )
    elif dialect == "anthropic":
        from inspect_ai.agent._bridge.anthropic_api import (
            inspect_anthropic_api_request,
        )

        anthropic_turns: list[Any] = [{"role": "user", "content": TASK}]
        for call, result in turns:
            anthropic_turns += [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Reading."},
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.function,
                            "input": call.arguments,
                        },
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": result,
                        }
                    ],
                },
            ]
        await inspect_anthropic_api_request(
            {"model": "inspect", "max_tokens": 100, "messages": anthropic_turns},
            None,
            None,
            None,
            bridge,
        )
    elif dialect == "google":
        from inspect_ai.agent._bridge.google_api import inspect_google_api_request

        contents: list[Any] = [{"role": "user", "parts": [{"text": TASK}]}]
        for call, result in turns:
            contents += [
                {
                    "role": "model",
                    "parts": [
                        {"text": "Reading."},
                        {
                            "functionCall": {
                                "id": call.id,
                                "name": call.function,
                                "args": call.arguments,
                            }
                        },
                    ],
                },
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": call.id,
                                "name": call.function,
                                "response": {"output": result},
                            }
                        }
                    ],
                },
            ]
        await inspect_google_api_request(
            {"model": "inspect", "contents": contents}, None, None, bridge
        )
    else:
        from inspect_ai.agent._bridge.responses import inspect_responses_api_request

        items: list[Any] = [{"role": "user", "content": TASK}]
        for call, result in turns:
            items += [
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.function,
                    "arguments": json.dumps(call.arguments),
                },
                {"type": "function_call_output", "call_id": call.id, "output": result},
            ]
        await inspect_responses_api_request(
            {"model": "inspect", "input": items}, None, None, None, bridge
        )


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_the_bridge_started_with_is_checked_only_if_changed(
    dialect: str, sandbox: bool, changed: bool
) -> None:
    seen: Steps = []
    model = Scripted(calls_output())
    state = AgentState(
        messages=[
            ChatMessageUser(content=TASK),
            ChatMessageAssistant(content="Reading.", tool_calls=[READ]),
            ChatMessageTool(
                content="file contents", tool_call_id=READ.id, function=READ.function
            ),
        ]
    )
    bridge = (
        SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            model_aliases={"inspect": model.model},
        )
        if sandbox
        else AgentBridge(state, model_aliases={"inspect": model.model})
    )

    with active([bridge_recording(seen)]):
        await dialect_history_request(
            dialect,
            bridge,
            READ,
            "file contents, edited" if changed else "file contents",
        )

    sent = "file contents, edited" if changed else "file contents"
    # the Google bridge reads a functionResponse's `response` as its JSON, so
    # a result handed over in Google's form is never the one the bridge
    # started with, and is checked
    received = json.dumps({"output": sent}) if dialect == "google" else sent
    assert len(model.inputs) == 1
    assert [
        (step.call, step.result.text)
        for step in seen
        if isinstance(step, AfterToolCall)
    ] == ([(READ, received)] if changed or dialect == "google" else [])


def started_with(
    sandbox: bool,
    model: Model,
    state: AgentState,
    checkpointer: Checkpointer | None = None,
) -> AgentBridge:
    return (
        SandboxAgentBridge(
            state=state,
            filter=None,
            retry_refusals=None,
            compaction=None,
            port=13131,
            model=None,
            model_aliases={"inspect": model},
            checkpointer=checkpointer,
        )
        if sandbox
        else AgentBridge(
            state, model_aliases={"inspect": model}, checkpointer=checkpointer
        )
    )


def as_handed(dialect: str, text: str) -> str:
    """A result's content as the dialect's bridge parses it (Google's `response` JSON)."""
    return json.dumps({"output": text}) if dialect == "google" else text


@pytest.mark.parametrize("change", ["content", "part"])
@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_the_bridge_started_with_changed_in_place_is_checked(
    dialect: str, sandbox: bool, change: str
) -> None:
    seen: Steps = []
    model = Scripted(calls_output(), calls_output())
    part = ContentText(text=as_handed(dialect, "safe"))
    result = ChatMessageTool(
        content=as_handed(dialect, "safe") if change == "content" else [part],
        tool_call_id=READ.id,
        function=READ.function,
    )
    state = AgentState(
        messages=[
            ChatMessageUser(content=TASK),
            ChatMessageAssistant(content="Reading.", tool_calls=[READ]),
            result,
        ]
    )
    bridge = started_with(sandbox, model.model, state)

    # changed before the bridge's first request
    if change == "content":
        result.content = as_handed(dialect, "secret")
    else:
        part.text = as_handed(dialect, "secret")

    with active([bridge_recording(seen)]):
        await dialect_history_request(dialect, bridge, READ, "secret")
        await dialect_history_request(dialect, bridge, READ, "safe")

    assert [
        (step.call, step.result.text)
        for step in seen
        if isinstance(step, AfterToolCall)
    ] == [(READ, as_handed(dialect, "secret"))]


@protocol
def terminate_on_old_secret() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.call.arguments == OLD.arguments and "secret" in step.result.text:
            return Decision.terminate("blocked old secret")
        return None

    return after


OLD = replace(READ, arguments={"path": "old.txt"})
SUMMARY = ChatMessageUser(content="Summary: notes were read.")


async def reintroduce_after_a_summary(bridge: AgentBridge, model: Scripted) -> None:
    """A first request without the starting history, then the old call reported changed."""
    with active(terminate_on_old_secret()):
        proposed = await generate(bridge, model, [SUMMARY])
        [handed] = proposed.message.tool_calls or []
        await generate(
            bridge,
            model,
            [
                SUMMARY,
                proposed.message,
                ChatMessageTool(
                    content="secret", tool_call_id=handed.id, function=READ.function
                ),
            ],
        )
        with pytest.raises(TerminateSampleError, match="blocked old secret"):
            await generate(bridge, model, old_conversation("secret"))

    assert len(model.inputs) == 2


def old_conversation(result: str) -> list[ChatMessage]:
    return [
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(content="Reading.", tool_calls=[OLD]),
        ChatMessageTool(content=result, tool_call_id=OLD.id, function=OLD.function),
    ]


@pytest.mark.parametrize("sandbox", [False, True])
async def test_a_starting_call_id_is_not_reissued_when_a_request_omits_it(
    sandbox: bool,
) -> None:
    new = replace(READ, arguments={"path": "new.txt"})
    model = Scripted(calls_output(new), calls_output())
    bridge = started_with(
        sandbox, model.model, AgentState(messages=old_conversation("safe"))
    )

    await reintroduce_after_a_summary(bridge, model)


@pytest.mark.parametrize(
    "keys",
    [
        ["bridge_handed_calls"],
        # a checkpoint written without the reservations: those of its prefix
        # and its conversation
        [],
    ],
)
@pytest.mark.parametrize("sandbox", [False, True])
async def test_a_resumed_bridge_keeps_its_starting_call_ids_reserved(
    sandbox: bool, keys: list[str]
) -> None:
    new = replace(READ, arguments={"path": "new.txt"})
    model = Scripted(calls_output(new), calls_output())
    first = RecordingCheckpointer()
    started_with(
        sandbox, model.model, AgentState(messages=old_conversation("safe")), first
    )
    checkpointer = RecordingCheckpointer(
        restored=saved(first, "bridge_compaction_prefix", *keys)
    )
    bridge = started_with(
        sandbox, model.model, AgentState(messages=[SUMMARY]), checkpointer
    )

    await reintroduce_after_a_summary(bridge, model)


def conversation(result: str) -> list[ChatMessage]:
    return [
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(content="Reading.", tool_calls=[READ]),
        ChatMessageTool(content=result, tool_call_id=READ.id, function=READ.function),
    ]


def saved(checkpointer: RecordingCheckpointer, *keys: str) -> dict[str, object]:
    """Tracked values as a checkpoint saves and resume restores them."""
    types: dict[str, Any] = {
        "bridge_compaction_prefix": list[ChatMessage],
        "bridge_handed_calls": _SavedHandedCalls,
    }
    return {
        key: TypeAdapter(types[key]).validate_json(
            to_json(checkpointer.callbacks[key]())
        )
        for key in keys
    }


@pytest.mark.parametrize("sandbox", [False, True])
async def test_a_resumed_bridge_inherits_the_results_it_first_started_with(
    sandbox: bool,
) -> None:
    seen: Steps = []
    model = Scripted(calls_output(), calls_output())
    first = RecordingCheckpointer()
    started_with(sandbox, model.model, AgentState(messages=conversation("safe")), first)
    checkpointer = RecordingCheckpointer(
        restored=saved(first, "bridge_compaction_prefix", "bridge_handed_calls")
    )
    bridge = started_with(
        sandbox, model.model, AgentState(messages=conversation("secret")), checkpointer
    )

    with active([bridge_recording(seen)]):
        await dialect_history_request("completions", bridge, READ, "safe")
        await dialect_history_request("completions", bridge, READ, "secret")

    assert [
        (step.call, step.result.text)
        for step in seen
        if isinstance(step, AfterToolCall)
    ] == [(READ, "secret")]


@pytest.mark.parametrize("sandbox", [False, True])
async def test_a_bridge_resumed_without_its_inherited_results_checks_every_result(
    sandbox: bool,
) -> None:
    seen: Steps = []
    model = Scripted(calls_output())
    first = RecordingCheckpointer()
    started_with(sandbox, model.model, AgentState(messages=conversation("safe")), first)
    checkpointer = RecordingCheckpointer(
        restored=saved(first, "bridge_compaction_prefix")
    )
    bridge = started_with(
        sandbox, model.model, AgentState(messages=conversation("safe")), checkpointer
    )

    with active([bridge_recording(seen)]):
        await dialect_history_request("completions", bridge, READ, "safe")

    assert [
        (step.call, step.result.text)
        for step in seen
        if isinstance(step, AfterToolCall)
    ] == [(READ, "safe")]


def real_checkpointer(
    root: Path, agent_state: dict[str, Any] | None = None
) -> _CountingCheckpointer:
    """The production checkpointer with restic stubbed; resuming `agent_state` if given."""
    context = root / "context"
    context.mkdir(exist_ok=True)
    hydration = _fake_hydration(str(root), str(context))
    hydration.host.agent_state = agent_state
    return _CountingCheckpointer(
        config=ResolvedCheckpointConfig(trigger=Manual()),
        hydration=hydration,
        resume_checkpoint=None
        if agent_state is None
        else ResumeCheckpoint(attempt="resume"),
    )


@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_changed_before_a_checkpoint_is_checked_after_resume(
    dialect: str, sandbox: bool, tmp_path: Path
) -> None:
    model = Scripted(calls_output())
    result = ChatMessageTool(
        content=as_handed(dialect, "safe"), tool_call_id=READ.id, function=READ.function
    )
    state = AgentState(
        messages=[
            ChatMessageUser(content=TASK),
            ChatMessageAssistant(content="Reading.", tool_calls=[READ]),
            result,
        ]
    )

    async with AsyncFilesystem():
        with _patch_sample_runtime([]):
            first = real_checkpointer(tmp_path)
            started_with(sandbox, model.model, state, first)
            # changed before the checkpoint, and before the bridge checks it
            result.content = as_handed(dialect, "secret")
            await first.checkpoint()
            first.close()
            assert first.fire_count == 1

            saved = read_host_context(str(tmp_path / "context")).agent_state
            resumed = real_checkpointer(tmp_path, saved)
            try:
                bridge = started_with(
                    sandbox,
                    model.model,
                    AgentState(messages=deepcopy(state.messages)),
                    resumed,
                )
                with active(terminate_on_secret()):
                    with pytest.raises(TerminateSampleError, match="blocked secret"):
                        await dialect_history_request(dialect, bridge, READ, "secret")
            finally:
                resumed.close()

    assert model.inputs == []


async def dialect_proposal(dialect: str, bridge: AgentBridge, prompt: str) -> str:
    """A scaffold sending `prompt` alone in `dialect`: the id it is handed for the model's call."""
    if dialect == "completions":
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        completion = await inspect_completions_api_request(
            {"model": "inspect", "messages": [{"role": "user", "content": prompt}]},
            None,
            bridge,
        )
        [call] = completion.choices[0].message.tool_calls or []
        return call.id
    elif dialect == "anthropic":
        from inspect_ai.agent._bridge.anthropic_api import (
            inspect_anthropic_api_request,
        )

        response = await inspect_anthropic_api_request(
            {
                "model": "inspect",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
            },
            None,
            None,
            None,
            bridge,
        )
        [use] = [block for block in response.content if block.type == "tool_use"]
        return use.id
    elif dialect == "google":
        from inspect_ai.agent._bridge.google_api import inspect_google_api_request

        answer: Any = await inspect_google_api_request(
            {
                "model": "inspect",
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            },
            None,
            None,
            bridge,
        )
        parts = answer["candidates"][0]["content"]["parts"]
        [function_call] = [p["functionCall"] for p in parts if "functionCall" in p]
        return cast(str, function_call["id"])
    else:
        from inspect_ai.agent._bridge.responses import inspect_responses_api_request

        result = await inspect_responses_api_request(
            {"model": "inspect", "input": [{"role": "user", "content": prompt}]},
            None,
            None,
            None,
            bridge,
        )
        [item] = [item for item in result.output if item.type == "function_call"]
        return item.call_id


# a model id the bridge first sees after it is constructed (Groq's streaming
# fallback ids repeat across conversations)
LATE = "tool_call_0_0"


# a checkpoint written before the bridge saved its result checks
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("first", ["compacted", "another"])
@pytest.mark.parametrize("seen_as", ["issued", "observed", "observed_alias"])
@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_resumed_bridge_keeps_the_call_ids_it_issued_or_observed(
    dialect: str, sandbox: bool, seen_as: str, first: str, legacy: bool, tmp_path: Path
) -> None:
    old = replace(
        OLD, id=f"{OLD.function}__{LATE}" if seen_as == "observed_alias" else LATE
    )
    new = replace(READ, id=LATE, arguments={"path": "new.txt"})
    proposals = [calls_output(old)] if seen_as == "issued" else []
    model = Scripted(*proposals, calls_output(), calls_output(new), calls_output())
    start = AgentState(messages=[ChatMessageUser(content=TASK)])

    async with AsyncFilesystem():
        with _patch_sample_runtime([]):
            checkpointer = real_checkpointer(tmp_path)
            bridge = started_with(sandbox, model.model, deepcopy(start), checkpointer)
            with active(terminate_on_old_secret()):
                if seen_as == "issued":
                    assert await dialect_proposal(dialect, bridge, TASK) == old.id
                await dialect_history_request(dialect, bridge, old, "safe")
            await checkpointer.checkpoint()
            checkpointer.close()

            saved = read_host_context(str(tmp_path / "context")).agent_state
            assert saved is not None
            if legacy:
                del saved["bridge_handed_calls"]
            resumed = real_checkpointer(tmp_path, saved)
            try:
                bridge = started_with(sandbox, model.model, deepcopy(start), resumed)
                with active(terminate_on_old_secret()):
                    handed = await dialect_proposal(
                        dialect,
                        bridge,
                        SUMMARY.text if first == "compacted" else "Name this session.",
                    )
                    assert handed != LATE
                    await dialect_history_request(
                        dialect, bridge, replace(new, id=handed), "fine"
                    )
                    with pytest.raises(
                        TerminateSampleError, match="blocked old secret"
                    ):
                        await dialect_history_request(dialect, bridge, old, "secret")
            finally:
                resumed.close()

    assert len(model.inputs) == len(proposals) + 3


@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_bridge_does_not_resume_from_incomplete_result_checks(
    dialect: str, sandbox: bool, tmp_path: Path
) -> None:
    model = Scripted(calls_output(replace(OLD, id=LATE)), calls_output())
    start = AgentState(messages=[ChatMessageUser(content=TASK)])

    async with AsyncFilesystem():
        with _patch_sample_runtime([]):
            checkpointer = real_checkpointer(tmp_path)
            bridge = started_with(sandbox, model.model, deepcopy(start), checkpointer)
            with active(terminate_on_old_secret()):
                handed = await dialect_proposal(dialect, bridge, TASK)
                await dialect_history_request(
                    dialect, bridge, replace(OLD, id=handed), "safe"
                )
            await checkpointer.checkpoint()
            checkpointer.close()

            saved = read_host_context(str(tmp_path / "context")).agent_state
            assert saved is not None
            del saved["bridge_handed_calls"]["reserved_ids"]
            resumed = real_checkpointer(tmp_path, saved)
            try:
                with pytest.raises(ValidationError, match="reserved_ids"):
                    started_with(sandbox, model.model, deepcopy(start), resumed)
            finally:
                resumed.close()

    assert len(model.inputs) == 2


@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_checked_before_a_checkpoint_is_not_checked_again_after_resume(
    dialect: str, sandbox: bool, tmp_path: Path
) -> None:
    seen: Steps = []
    model = Scripted(calls_output(replace(READ, id=LATE)), calls_output())
    start = AgentState(messages=[ChatMessageUser(content=TASK)])

    async with AsyncFilesystem():
        with _patch_sample_runtime([]):
            checkpointer = real_checkpointer(tmp_path)
            bridge = started_with(sandbox, model.model, deepcopy(start), checkpointer)
            with active([bridge_recording(seen)]):
                handed = await dialect_proposal(dialect, bridge, TASK)
                await dialect_history_request(
                    dialect, bridge, replace(READ, id=handed), "safe"
                )
            await checkpointer.checkpoint()
            checkpointer.close()

            saved = read_host_context(str(tmp_path / "context")).agent_state
            resumed = real_checkpointer(tmp_path, saved)
            try:
                bridge = started_with(sandbox, model.model, deepcopy(start), resumed)
                with active([bridge_recording(seen)]):
                    await dialect_history_request(
                        dialect, bridge, replace(READ, id=handed), "safe"
                    )
                    await dialect_history_request(
                        dialect, bridge, replace(READ, id=handed), "changed"
                    )
            finally:
                resumed.close()

    assert [step.result.text for step in seen if isinstance(step, AfterToolCall)] == [
        as_handed(dialect, "safe"),
        as_handed(dialect, "changed"),
    ]


@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_takes_its_proposal_through_each_dialect(dialect: str) -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ, content="Reading."), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_recording(seen)]):
        await dialect_round_trip(dialect, bridge)

    before, after = seen
    assert isinstance(before, BeforeToolCall) and isinstance(after, AfterToolCall)
    assert after.call == before.call
    assert after.message_id == before.message_id
    assert after.input == before.input == model.inputs[0]
    assert after.input is not None and after.input[0].text == "Be careful."


@pytest.mark.parametrize("filter", [None, "rewrites"])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_each_dialect_sees_what_the_model_was_sent_through_a_sink(
    dialect: str, filter: str | None
) -> None:
    seen: Steps = []
    model = Scripted(
        calls_output(READ, content="Reading."),
        calls_output(),
        config=GenerateConfig(system_message=POLICY),
    )
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model.model},
        filter=passing_filter(filter),
    )
    sink = RecordingSink(forward=False)
    bridge.model_event_sink = sink

    with active([bridge_recording(seen)]):
        await dialect_round_trip(dialect, bridge)

    before, after = seen
    assert before.input == after.input == sink.events[0].input == model.inputs[0]
    assert [m.text for m in before.input][:2] == [POLICY, "Be careful."]


REWRITES = ["unchanged", "compaction", "history_whitespace", "history_parts"]
CHANGES = ["result_whitespace", "result_parts"]


@pytest.mark.parametrize("rewrite", REWRITES + CHANGES)
async def test_a_result_is_checked_again_only_if_it_changed(rewrite: str) -> None:
    # however the scaffold rewrites the rest of its history; any change to the
    # result itself, down to its whitespace and parts, is checked again
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = in_process_bridge([])
    history: list[ChatMessage] = [
        ChatMessageUser(content="Old task details"),
        ChatMessageAssistant(content="Earlier answer"),
        ChatMessageUser(content="Read it"),
    ]

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        echoed = output.message.model_copy(update={"id": "echoed"})
        result = ChatMessageTool(content="same result", tool_call_id=READ.id)
        await generate(bridge, model, [*history, echoed, result])
        if rewrite == "compaction":
            history = [ChatMessageUser(content="Summary of older turns"), history[-1]]
        elif rewrite == "history_whitespace":
            history[0] = ChatMessageUser(content="Old task details ")
        elif rewrite == "history_parts":
            history[0] = ChatMessageUser(
                content=[ContentText(text="Old task"), ContentText(text=" details")]
            )
        elif rewrite == "result_whitespace":
            result = ChatMessageTool(content="same  result\n", tool_call_id=READ.id)
        elif rewrite == "result_parts":
            result = ChatMessageTool(
                content=[ContentText(text="same"), ContentText(text=" result")],
                tool_call_id=READ.id,
            )
        await generate(bridge, model, [*history, echoed, result])

    after = [s for s in seen if isinstance(s, AfterToolCall)]
    assert len(after) == (2 if rewrite in CHANGES else 1)
    assert all(step.input == model.inputs[0] for step in after)


@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_changed_only_in_whitespace_is_checked_again(
    dialect: str,
) -> None:
    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active(terminate_on_secret()):
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await dialect_round_trip(dialect, bridge, results=["s e c r e t", "secret"])

    # the first result went on to the model, the second did not
    assert len(model.inputs) == 2


# pairs of results a murmur3 result key cannot tell apart: under `read_file`
# as sent, under `read_file` as Google's `{"output": ...}` response, and under
# the host tool's name
COLLIDING = (
    "public0000000000000000.................",
    "secret00000000023eb3dc.gYu6Lo|zUGobXv|!",
)
GOOGLE_COLLIDING = (
    "public00................................",
    "secret00:Y2;ICd)e)te-'3sV[W%aA.ih[iJCu4M",
)
HOST_COLLIDING = (
    "public000000................................",
    "secret000000AQaQ:.eE5OJ~//7+~;_Z+G'}b(W(yet;",
)


def colliding(dialect: str) -> tuple[str, str]:
    return GOOGLE_COLLIDING if dialect == "google" else COLLIDING


@pytest.mark.parametrize("secret_first", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_colliding_with_a_checked_result_is_checked(
    dialect: str, secret_first: bool
) -> None:
    public, secret = colliding(dialect)
    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active(terminate_on_secret()):
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await dialect_round_trip(
                dialect,
                bridge,
                results=[secret, public] if secret_first else [public, secret],
            )

    assert len(model.inputs) == (1 if secret_first else 2)


@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_colliding_with_one_the_bridge_started_with_is_checked(
    dialect: str, sandbox: bool
) -> None:
    public, secret = colliding(dialect)
    seen: Steps = []
    model = Scripted(calls_output())
    state = AgentState(
        messages=[
            ChatMessageUser(content=TASK),
            ChatMessageAssistant(content="Reading.", tool_calls=[READ]),
            ChatMessageTool(
                content=as_handed(dialect, public),
                tool_call_id=READ.id,
                function=READ.function,
            ),
        ]
    )
    bridge = started_with(sandbox, model.model, state)

    with active([bridge_recording(seen)]):
        await dialect_history_request(dialect, bridge, READ, secret)

    assert [
        (step.call, step.result.text)
        for step in seen
        if isinstance(step, AfterToolCall)
    ] == [(READ, as_handed(dialect, secret))]


async def test_a_colliding_result_of_a_call_never_handed_over_is_checked() -> None:
    public, secret = COLLIDING
    seen: Steps = []
    model = Scripted(calls_output(), calls_output())
    bridge = in_process_bridge([])
    history: list[ChatMessage] = [
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(content="Reading.", tool_calls=[READ]),
    ]

    with active([bridge_recording(seen)]):
        for text in (public, secret):
            result = ChatMessageTool(
                content=text, tool_call_id=READ.id, function=READ.function
            )
            await generate(bridge, model, [*history, result])

    assert [step.result.text for step in seen if isinstance(step, AfterToolCall)] == [
        public,
        secret,
    ]


async def test_a_result_colliding_with_a_checked_host_result_is_checked() -> None:
    public, secret = HOST_COLLIDING
    seen: Steps = []
    read = ToolCall(
        id="host_1", function="mcp__host__read_file", arguments=READ.arguments
    )
    model = Scripted(calls_output(read), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value=public))

    with active([bridge_recording(seen)]):
        output = await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        await call_host_tool(bridge)("host", "read_file", READ.arguments)
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(
                    content=secret, tool_call_id=read.id, function=read.function
                ),
            ],
            declare_read_file(),
        )

    assert [step.result.text for step in seen if isinstance(step, AfterToolCall)] == [
        public,
        secret,
    ]


@protocol
def terminate_on_secret_internal() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        content = step.result.content
        if not isinstance(content, str) and any(
            isinstance(part, ContentText) and part.internal == "secret"
            for part in content
        ):
            return Decision.terminate("blocked internal")
        return None

    return after


@pytest.mark.parametrize("dialect", ["anthropic", "completions"])
async def test_a_result_changed_only_in_its_text_internal_is_checked_again(
    dialect: str,
) -> None:
    # the scaffold's tagged text is parsed into a text part's `internal`, which
    # the Anthropic provider sends back to the model in the text
    from inspect_ai.model._internal import content_internal_tag

    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    results = [
        [{"type": "text", "text": f"x\n{content_internal_tag(internal)}"}]
        for internal in ("safe", "secret")
    ]

    with active(terminate_on_secret_internal()):
        with pytest.raises(TerminateSampleError, match="blocked internal"):
            await dialect_round_trip(dialect, bridge, results=results)

    assert len(model.inputs) == 2


# the same payload in two key orders, which `content_internal_tag()` sends as
# different text
REORDERED_INTERNAL: dict[str, tuple[JsonValue, JsonValue]] = {
    "top": ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
    "nested": ({"n": {"a": 1, "b": 2}}, {"n": {"b": 2, "a": 1}}),
}


@protocol
def terminate_on_the_reordered_internal() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        content = step.result.content
        if not isinstance(content, str) and any(
            isinstance(part, ContentText)
            and json.dumps(part.internal)
            in (json.dumps(pair[1]) for pair in REORDERED_INTERNAL.values())
            for part in content
        ):
            return Decision.terminate("blocked reordered internal")
        return None

    return after


@pytest.mark.parametrize("sandbox", [False, True], ids=["agent", "sandbox"])
@pytest.mark.parametrize("shape", list(REORDERED_INTERNAL))
@pytest.mark.parametrize("dialect", ["anthropic", "completions"])
async def test_a_result_changed_only_in_its_internal_key_order_is_checked_again(
    dialect: str, shape: str, sandbox: bool
) -> None:
    from inspect_ai.model._internal import content_internal_tag

    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = started_with(sandbox, model.model, AgentState(messages=[]))
    results = [
        [{"type": "text", "text": f"x\n{content_internal_tag(internal)}"}]
        for internal in REORDERED_INTERNAL[shape]
    ]

    with active(terminate_on_the_reordered_internal()):
        with pytest.raises(TerminateSampleError, match="blocked reordered internal"):
            await dialect_round_trip(dialect, bridge, results=results)

    assert len(model.inputs) == 2


@pytest.mark.parametrize("shape", list(REORDERED_INTERNAL))
@pytest.mark.parametrize("dialect", ["responses", "google"])
async def test_a_result_text_tag_changed_only_in_key_order_is_checked_again(
    dialect: str, shape: str
) -> None:
    # these dialects keep the tagged payload in the result's text
    from inspect_ai.model._internal import content_internal_tag

    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = started_with(False, model.model, AgentState(messages=[]))
    results = [
        f"x\n{content_internal_tag(internal)}" for internal in REORDERED_INTERNAL[shape]
    ]

    with active([bridge_recording(seen)]):
        await dialect_round_trip(dialect, bridge, results=results)

    assert len([step for step in seen if isinstance(step, AfterToolCall)]) == 2


@protocol
def terminate_on_a_secret_function() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if step.result.function == "secret":
            return Decision.terminate("blocked function")
        return None

    return after


async def test_a_result_reported_under_another_function_is_checked_again() -> None:
    # the function a result is reported under reaches the model (Google's
    # FunctionResponse.name), so a result that changes only it is new
    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = in_process_bridge([])

    with active(terminate_on_a_secret_function()):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
        with pytest.raises(TerminateSampleError, match="blocked function"):
            for function in ("read_file", "secret"):
                await generate(
                    bridge,
                    model,
                    [
                        ChatMessageUser(content=TASK),
                        output.message,
                        ChatMessageTool(
                            content="x", tool_call_id=READ.id, function=function
                        ),
                    ],
                )

    assert len(model.inputs) == 2


async def test_a_google_result_renamed_by_the_scaffold_is_checked_again() -> None:
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    tools: Any = [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": PATH_SCHEMA,
                }
            ]
        }
    ]
    user: Any = {"role": "user", "parts": [{"text": TASK}]}

    with active(terminate_on_a_secret_function()):
        first: Any = await inspect_google_api_request(
            {"model": "inspect", "contents": [user], "tools": tools}, None, None, bridge
        )
        parts = first["candidates"][0]["content"]["parts"]
        [function_call] = [p["functionCall"] for p in parts if "functionCall" in p]
        with pytest.raises(TerminateSampleError, match="blocked function"):
            for name in ("read_file", "secret"):
                response: Any = {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "id": function_call.get("id"),
                                "name": name,
                                "response": {"output": "x"},
                            }
                        }
                    ],
                }
                await inspect_google_api_request(
                    {
                        "model": "inspect",
                        "contents": [user, {"role": "model", "parts": parts}, response],
                        "tools": tools,
                    },
                    None,
                    None,
                    bridge,
                )

    assert len(model.inputs) == 2


async def test_a_result_whose_text_moved_across_an_image_is_checked_again() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = in_process_bridge([])
    caption: Content = ContentText(text="Caption.")
    image: Content = ContentImage(image=PNG)

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
        for content in ([caption, image], [image, caption]):
            await generate(
                bridge,
                model,
                [
                    ChatMessageUser(content=TASK),
                    output.message,
                    ChatMessageTool(content=content, tool_call_id=READ.id),
                ],
            )

    after = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [
        [c.type for c in step.result.content if not isinstance(c, str)]
        for step in after
    ] == [
        ["text", "image"],
        ["image", "text"],
    ]


async def test_a_scaffold_report_of_a_checked_host_result_changed_only_in_whitespace() -> (
    None
):
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value="s e c r e t"))

    with active(terminate_on_secret()):
        output = await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        assert await call_host_tool(bridge)("host", "read_file", READ.arguments) == (
            "s e c r e t"
        )
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(
                bridge,
                model,
                [
                    ChatMessageUser(content=TASK),
                    output.message,
                    ChatMessageTool(content="secret", tool_call_id=call.id),
                ],
            )

    assert len(model.inputs) == 1


@protocol
def terminate_on_a_second_result(seen: Any) -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        seen.append(step)
        if len(seen) > 1:
            return Decision.terminate("an execution was checked twice")
        return None

    return after


async def test_a_result_protocol_runs_once_per_execution_across_compaction() -> None:
    seen: list[AfterToolCall] = []
    model = Scripted(calls_output(READ), calls_output(), calls_output())
    bridge = in_process_bridge([])
    initial: list[ChatMessage] = [ChatMessageUser(content="Original context")]

    with active(terminate_on_a_second_result(seen)):
        output = await generate(bridge, model, initial)
        tail: list[ChatMessage] = [
            output.message.model_copy(update={"id": "echoed"}),
            ChatMessageTool(content="same", tool_call_id=READ.id),
        ]
        await generate(bridge, model, [*initial, *tail])
        await generate(bridge, model, [ChatMessageUser(content="Summary"), *tail])

    assert len(seen) == 1


@pytest.mark.parametrize("context", ["identical", "system", "images"])
async def test_equal_calls_in_equal_looking_conversations_are_separate_executions(
    context: str,
) -> None:
    seen: Steps = []
    old_call, new_call = replace(READ, id="old"), replace(READ, id="new")
    model = Scripted(
        calls_output(old_call, content="old explanation"),
        calls_output(new_call, content="new explanation"),
        calls_output(),
        calls_output(),
    )
    bridge = in_process_bridge([])

    def conversation(system: str, image: str) -> list[ChatMessage]:
        user = ChatMessageUser(
            content=[ContentText(text="Read it"), ContentImage(image=image)]
            if context == "images"
            else "Read it"
        )
        if context == "system":
            return [ChatMessageSystem(content=system), user]
        return [user]

    old_history = conversation("Old instructions", "data:image/png;base64,aGVsbG8=")
    new_history = conversation("New instructions", "data:image/png;base64,d29ybGQ=")
    with active([bridge_recording(seen)]):
        old = await generate(bridge, model, old_history)
        new = await generate(bridge, model, new_history)
        for history, output, call in [
            (old_history, old, old_call),
            (new_history, new, new_call),
        ]:
            await generate(
                bridge,
                model,
                [
                    *history,
                    output.message.model_copy(update={"id": f"echoed_{call.id}"}),
                    ChatMessageTool(content="same", tool_call_id=call.id),
                ],
            )

    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [(s.call.id, s.input) for s in afters] == [
        ("old", model.inputs[0]),
        ("new", model.inputs[1]),
    ]


@pytest.mark.parametrize("sandbox", [False, True])
@pytest.mark.parametrize("same_output", [False, True])
async def test_initial_history_id_cannot_be_reissued_for_a_new_call(
    sandbox: bool, same_output: bool
) -> None:
    seen: Steps = []
    function = "mcp__host__read_file" if sandbox else "read_file"
    old = ToolCall(id="read_1", function=function, arguments={"path": "old.txt"})
    new = replace(old, arguments={"path": "new.txt"})
    old_output = "contents" if same_output else "old contents"
    new_output = "contents" if same_output else "new contents"
    history: list[ChatMessage] = [
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(content="Reading old file.", tool_calls=[old]),
        ChatMessageTool(content=old_output, tool_call_id=old.id, function=function),
    ]
    model = Scripted(calls_output(new), calls_output())
    bridge = sandbox_bridge() if sandbox else in_process_bridge(history)
    tools = declare_read_file() if sandbox else []

    with active([bridge_recording(seen)]):
        proposed = await generate(bridge, model, history, tools)
        [handed] = proposed.message.tool_calls or []

        await generate(bridge, model, [*history, proposed.message], tools)
        # the in-process bridge started with the old result, so it is not
        # checked again
        checked = [] if not sandbox else [(old.arguments, old_output)]
        afters = [step for step in seen if isinstance(step, AfterToolCall)]
        assert [(step.call.arguments, step.output) for step in afters] == checked
        assert handed.id != old.id

        await generate(
            bridge,
            model,
            [
                *history,
                proposed.message,
                ChatMessageTool(
                    content=new_output, tool_call_id=handed.id, function=function
                ),
            ],
            tools,
        )

    afters = [step for step in seen if isinstance(step, AfterToolCall)]
    assert [(step.call.arguments, step.output) for step in afters] == [
        *checked,
        (new.arguments, new_output),
    ]


async def test_result_only_id_in_initial_history_cannot_be_issued() -> None:
    history: list[ChatMessage] = [
        ChatMessageUser(content=TASK),
        ChatMessageTool(content="old", tool_call_id=READ.id, function="read_file"),
    ]
    bridge = in_process_bridge(history)

    with active([bridge_recording([])]):
        output = await generate(bridge, Scripted(calls_output(READ)), history)

    [handed] = output.message.tool_calls or []
    assert handed.id != READ.id


async def test_a_call_handed_over_twice_keeps_its_id_and_its_latest_handout() -> None:
    """Two generations give one call (a scaffold retry served from the cache).

    Both handouts keep the model's id, and the result, which the scaffold
    reports for each conversation, is checked once, with the latest handout's
    context.
    """
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output(READ), calls_output())
    bridge = in_process_bridge([])
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active([bridge_recording(seen)]):
        first = await generate(bridge, model, history)
        second = await generate(bridge, model, history)
        [first_call] = first.message.tool_calls or []
        [second_call] = second.message.tool_calls or []
        for output, call in [(first, first_call), (second, second_call)]:
            await generate(
                bridge,
                model,
                [
                    *history,
                    output.message,
                    ChatMessageTool(content="same", tool_call_id=call.id),
                ],
            )

    assert first_call.id == second_call.id == READ.id
    model_events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    assert [e.output.message.tool_calls for e in model_events[:2]] == [[READ]] * 2
    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [(s.call.id, s.input) for s in afters] == [(READ.id, model.inputs[1])]


async def test_a_result_under_an_id_never_handed_out_is_checked_once() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output())
    bridge = in_process_bridge([])
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        # a scaffold that mints its own id for the call on every request
        for id in ["scaffold_1", "scaffold_2"]:
            call = replace(READ, id=id)
            await generate(
                bridge,
                model,
                [
                    *history,
                    ChatMessageAssistant(content="On it.", tool_calls=[call]),
                    ChatMessageTool(content="other", tool_call_id=id),
                ],
            )
        # the handed-over call's result, then the same result under an id of
        # the scaffold's own
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="same", tool_call_id=READ.id),
            ],
        )
        await generate(
            bridge,
            model,
            [
                *history,
                ChatMessageAssistant(
                    content="On it.", tool_calls=[replace(READ, id="scaffold_3")]
                ),
                ChatMessageTool(content="same", tool_call_id="scaffold_3"),
            ],
        )

    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    # the unmatched result once, with no model input; the handed-over call's
    # result once, with its proposal, and not again without its token
    assert [(s.call.id, s.output, s.input) for s in afters] == [
        ("scaffold_1", "other", None),
        (READ.id, "same", model.inputs[0]),
    ]


async def gemini_cli_round_trips(
    bridge: AgentBridge,
    outputs: list[str],
    keep_ids: bool = True,
    compact: bool = False,
) -> None:
    """A gemini-cli-like scaffold: it prefixes call ids with `name__` and echoes them."""
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    tools: Any = [
        {
            "functionDeclarations": [
                {"name": "read_file", "description": "Read", "parameters": PATH_SCHEMA}
            ]
        }
    ]
    contents: list[Any] = [{"role": "user", "parts": [{"text": TASK}]}]

    async def request() -> Any:
        return await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )

    for output in outputs:
        response = await request()
        parts = response["candidates"][0]["content"]["parts"]
        response_part: dict[str, Any] = {
            "name": "read_file",
            "response": {"out": output},
        }
        for part in parts:
            if "functionCall" in part:
                call = part["functionCall"]
                if keep_ids:
                    call["id"] = f"read_file__{call['id']}"
                    response_part["id"] = call["id"]
                else:
                    del call["id"]
        contents += [
            {"role": "model", "parts": parts},
            {"role": "user", "parts": [{"functionResponse": response_part}]},
        ]
    await request()
    if compact:
        # gemini-cli's compression: a summary, then the latest pair
        contents = [
            {"role": "user", "parts": [{"text": "Summary of earlier turns"}]},
            *contents[-2:],
        ]
        await request()


@pytest.mark.parametrize("compact", [False, True])
async def test_gemini_cli_results_are_matched_by_the_ids_it_echoes(
    compact: bool,
) -> None:
    seen: Steps = []
    calls = [replace(READ, id=f"read_{i}") for i in range(3)]
    model = Scripted(*[calls_output(call) for call in calls], calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_recording(seen)]):
        await gemini_cli_round_trips(bridge, ["same"] * 3, compact=compact)

    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [(s.call.id, s.input) for s in afters] == [
        (call.id, input) for call, input in zip(calls, model.inputs)
    ]


@pytest.mark.parametrize("with_old_call", [False, True])
@pytest.mark.parametrize(
    ("old_id", "new_id"),
    [("read_file__123", "123"), ("123", "read_file__123")],
)
async def test_google_initial_history_alias_cannot_claim_new_result(
    with_old_call: bool, old_id: str, new_id: str
) -> None:
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    seen: Steps = []
    new = ToolCall(id=new_id, function="delete_file", arguments={"path": "new.txt"})
    model = Scripted(calls_output(new), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    contents: list[Any] = [
        {"role": "user", "parts": [{"text": "Read old.txt, then delete new.txt."}]}
    ]
    if with_old_call:
        contents.append(
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "id": old_id,
                            "name": "read_file",
                            "args": {"path": "old.txt"},
                        }
                    }
                ],
            }
        )
    contents.append(
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": old_id,
                        "name": "read_file",
                        "response": {"out": "old contents"},
                    }
                }
            ],
        }
    )
    tools: list[Any] = [
        {"functionDeclarations": [{"name": "read_file"}, {"name": "delete_file"}]}
    ]

    async def request() -> Any:
        return await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )

    with active([bridge_recording(seen)]):
        first = await request()
        parts = first["candidates"][0]["content"]["parts"]
        handed = next(
            part["functionCall"]["id"] for part in parts if "functionCall" in part
        )
        contents.append({"role": "model", "parts": parts})
        await request()
        afters = [step for step in seen if isinstance(step, AfterToolCall)]
        assert [(step.call.function, step.output) for step in afters] == [
            ("read_file", '{"out": "old contents"}')
        ]
        # the history id and the new one are different calls' (another
        # function's), so the new call keeps the model's id
        assert handed == new_id

        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "id": handed,
                            "name": "delete_file",
                            "response": {"out": "deleted"},
                        }
                    }
                ],
            }
        )
        await request()

    afters = [step for step in seen if isinstance(step, AfterToolCall)]
    assert [
        (step.call.function, step.call.arguments, step.output) for step in afters
    ] == [
        (
            "read_file",
            {"path": "old.txt"} if with_old_call else {},
            '{"out": "old contents"}',
        ),
        ("delete_file", {"path": "new.txt"}, '{"out": "deleted"}'),
    ]


async def test_google_results_without_ids_are_checked_once_per_call_and_result() -> (
    None
):
    seen: Steps = []
    calls = [replace(READ, id=f"read_{i}") for i in range(3)]
    model = Scripted(*[calls_output(call) for call in calls], calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_recording(seen)]):
        await gemini_cli_round_trips(
            bridge, ["same", "same", "new"], keep_ids=False, compact=True
        )

    # without ids a result can't be matched to its execution: an identical
    # result of an identical call is not checked again, and none gets a
    # proposal's context
    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [(s.output, s.input) for s in afters] == [
        ('{"out": "same"}', None),
        ('{"out": "new"}', None),
    ]


async def test_google_terminates_on_a_repeated_calls_new_result() -> None:
    calls = [replace(READ, id=f"read_{i}") for i in range(3)]
    model = Scripted(*[calls_output(call) for call in calls], calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active(terminate_on_secret()):
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await google_round_trips(bridge, model, ["benign", "benign", "secret"])

    assert len(model.inputs) == 3


async def test_a_scaffold_result_cannot_stand_in_for_a_host_result() -> None:
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call), calls_output())
    tool = AsyncMock(return_value="secret")
    bridge = sandbox_bridge(tool)
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active(terminate_on_secret()):
        one = await generate(bridge, model, history, declare_read_file())
        await generate(
            bridge,
            model,
            [
                *history,
                one.message,
                ChatMessageTool(content="benign", tool_call_id=call.id),
            ],
            declare_read_file(),
        )
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    tool.assert_awaited_once()


class Hold:
    """Holds each `tool_result` check of `held_terminate` until released."""

    def __init__(self, calls: int = 1) -> None:
        self.calls = calls
        self.started: list[str] = []
        self.ready = anyio.Event()
        self.release = anyio.Event()
        self.cleaned_up = 0


@protocol
def held_terminate(hold: Any) -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        hold.started.append(step.call.id)
        if len(hold.started) >= hold.calls:
            hold.ready.set()
        try:
            await hold.release.wait()
        finally:
            hold.cleaned_up += 1
        return Decision.terminate("blocked secret")

    return after


@pytest.mark.parametrize("calls", [1, 2])
async def test_an_interrupted_result_check_runs_again(calls: int) -> None:
    hold = Hold(calls)
    handed = [
        replace(READ, id=f"read_{i}", arguments={"path": f"{i}.txt"})
        for i in range(calls)
    ]
    model = Scripted(calls_output(*handed), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    with active(held_terminate(hold)):
        output = await generate(bridge, model, history)
        history += [
            output.message,
            *[ChatMessageTool(content="secret", tool_call_id=c.id) for c in handed],
        ]
        with anyio.CancelScope() as scope:

            async def cancel() -> None:
                await hold.ready.wait()
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel)
                await generate(bridge, model, history)

        assert scope.cancelled_caught
        assert hold.cleaned_up == calls
        assert sorted(hold.started) == [c.id for c in handed]

        hold.release.set()
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(bridge, model, history)

    assert len(hold.started) > calls
    assert len(model.inputs) == 1


async def test_a_concurrent_request_waits_for_an_inflight_result_check() -> None:
    hold = Hold()
    model = Scripted(calls_output(READ), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    leaked: list[ModelOutput] = []

    with active(held_terminate(hold)):
        output = await generate(bridge, model, history)
        history += [
            output.message,
            ChatMessageTool(content="secret", tool_call_id=READ.id),
        ]

        async def first() -> None:
            with pytest.raises(TerminateSampleError):
                await generate(bridge, model, history)

        async def second() -> None:
            try:
                leaked.append(await generate(bridge, model, history))
            except TerminateSampleError:
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(first)
            await hold.ready.wait()
            tg.start_soon(second)
            # the second request reaches the in-flight check before its release
            await anyio.wait_all_tasks_blocked()
            hold.release.set()

    assert leaked == []
    assert hold.started == [READ.id]
    assert len(model.inputs) == 1


OTHER_READ = replace(READ, id="read_2", arguments={"path": "other.txt"})
UNISSUED_READ = replace(READ, id="read_9")


def overlapping_turns(unissued_first: bool = False) -> list[tuple[ToolCall, str]]:
    """A result under its token and again under an unissued id, then another result."""
    same = [(READ, "contents"), (UNISSUED_READ, "contents")]
    return [*(same[::-1] if unissued_first else same), (OTHER_READ, "other")]


@pytest.mark.parametrize("unissued_first", [False, True])
@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_result_reported_under_its_token_and_an_unissued_id(
    dialect: str, unissued_first: bool
) -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ, OTHER_READ), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_recording(seen)]):
        await generate(bridge, model, [ChatMessageUser(content=TASK)])
        with anyio.fail_after(10):
            await dialect_turns_request(
                dialect, bridge, overlapping_turns(unissued_first)
            )

    assert len(model.inputs) == 2
    # the unissued result is the token result's conservative key, so it is
    # checked only when reported first
    checked = [step.call.id for step in seen if isinstance(step, AfterToolCall)]
    assert sorted(checked) == sorted(
        [READ.id, OTHER_READ.id, *([UNISSUED_READ.id] if unissued_first else [])]
    )


@protocol
def held_other(started: Any, release: Any) -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if "other" in step.result.text:
            started.set()
            await release.wait()
        return None

    return after


@pytest.mark.parametrize("dialect", DIALECTS)
async def test_a_cancelled_request_with_overlapping_results_releases_each_check(
    dialect: str,
) -> None:
    started, release = anyio.Event(), anyio.Event()
    model = Scripted(calls_output(READ, OTHER_READ), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active(held_other(started, release)):
        await generate(bridge, model, [ChatMessageUser(content=TASK)])
        with anyio.CancelScope() as scope:

            async def cancel() -> None:
                await started.wait()
                # the other results' checks finish first
                await anyio.wait_all_tasks_blocked()
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel)
                await dialect_turns_request(dialect, bridge, overlapping_turns())

        assert scope.cancelled_caught
        release.set()
        with anyio.fail_after(10):
            await dialect_turns_request(dialect, bridge, overlapping_turns())

    assert len(model.inputs) == 2


async def test_a_release_that_raises_still_releases_the_other_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.agent._bridge._sentinel import _HandedCalls

    release = _HandedCalls.release
    failures = [RuntimeError("release failed")]

    def failing_release(self: _HandedCalls, claim: Any) -> None:
        release(self, claim)
        if failures:
            raise failures.pop()

    monkeypatch.setattr(_HandedCalls, "release", failing_release)
    started, held = anyio.Event(), anyio.Event()
    model = Scripted(calls_output(READ, OTHER_READ), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active(held_other(started, held)):
        await generate(bridge, model, [ChatMessageUser(content=TASK)])
        with anyio.CancelScope() as scope:

            async def cancel() -> None:
                await started.wait()
                scope.cancel()

            with pytest.raises(ExceptionGroup) as raised:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(cancel)
                    await dialect_turns_request(
                        "completions", bridge, overlapping_turns()
                    )

        assert raised.group_contains(RuntimeError, match="release failed")
        held.set()
        with anyio.fail_after(10):
            await dialect_turns_request("completions", bridge, overlapping_turns())

    assert len(model.inputs) == 2


async def test_a_reused_id_in_a_new_conversation_is_checked() -> None:
    first = READ
    second = replace(READ, arguments={"path": "other"})
    model = Scripted(calls_output(first), calls_output(second), calls_output())
    bridge = in_process_bridge([])
    user = ChatMessageUser(content=TASK)

    with active(terminate_on_secret()):
        one = await generate(bridge, model, [user])
        two = await generate(
            bridge,
            model,
            [
                user,
                one.message,
                ChatMessageTool(content="benign", tool_call_id=READ.id),
            ],
        )
        # a compacted conversation, or another one sharing the bridge
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(
                bridge,
                model,
                [
                    user,
                    two.message,
                    ChatMessageTool(content="secret", tool_call_id=READ.id),
                ],
            )


async def test_a_changed_result_is_checked_again() -> None:
    model = Scripted(calls_output(READ), calls_output())
    bridge = in_process_bridge([])
    user = ChatMessageUser(content=TASK)

    with active(terminate_on_secret()):
        one = await generate(bridge, model, [user])
        await generate(
            bridge,
            model,
            [
                user,
                one.message,
                ChatMessageTool(content="benign", tool_call_id=READ.id),
            ],
        )
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(
                bridge,
                model,
                [
                    user,
                    one.message,
                    ChatMessageTool(content="secret", tool_call_id=READ.id),
                ],
            )


@protocol
def held_benign(started: Any, release: Any) -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if "secret" in step.result.text:
            return Decision.terminate("blocked secret")
        started.set()
        await release.wait()
        return None

    return after


@protocol
def counted_held(seen: Any, started: Any, release: Any) -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        seen.append(step)
        started.set()
        await release.wait()
        return None

    return after


async def test_a_host_result_reported_during_its_check_is_checked_once() -> None:
    seen: list[AfterToolCall] = []
    started, release = anyio.Event(), anyio.Event()
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value="contents"))
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active(counted_held(seen, started, release)):
        output = await generate(bridge, model, history, declare_read_file())

        async def execute() -> None:
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

        async with anyio.create_task_group() as tg:
            tg.start_soon(execute)
            await started.wait()

            async def report() -> None:
                await generate(
                    bridge,
                    model,
                    [
                        *history,
                        output.message,
                        ChatMessageTool(
                            content="contents",
                            tool_call_id=call.id,
                            function=call.function,
                        ),
                    ],
                    declare_read_file(),
                )

            tg.start_soon(report)
            await anyio.sleep(0.05)
            release.set()

    assert len(seen) == 1


@pytest.mark.parametrize("same_call", [True, False])
async def test_a_concurrent_changed_result_is_checked(same_call: bool) -> None:
    started, release = anyio.Event(), anyio.Event()
    other = READ if same_call else replace(READ, arguments={"path": "other"})
    model = Scripted(calls_output(READ), calls_output(other), calls_output())
    bridge = in_process_bridge([])
    user = ChatMessageUser(content=TASK)
    leaked: list[ModelOutput] = []

    with active(held_benign(started, release)):
        one = await generate(bridge, model, [user])
        # the same call, or the same id in a second conversation on the bridge
        two = one if same_call else await generate(bridge, model, [user])

        async def benign() -> None:
            await generate(
                bridge,
                model,
                [
                    user,
                    one.message,
                    ChatMessageTool(content="benign", tool_call_id=READ.id),
                ],
            )

        async def changed() -> None:
            try:
                leaked.append(
                    await generate(
                        bridge,
                        model,
                        [
                            user,
                            two.message,
                            ChatMessageTool(content="secret", tool_call_id=READ.id),
                        ],
                    )
                )
            except TerminateSampleError:
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(benign)
            await started.wait()
            tg.start_soon(changed)
            await anyio.wait_all_tasks_blocked()
            release.set()

    assert leaked == []


async def test_a_google_repeated_call_is_checked_after_compaction() -> None:
    from inspect_ai.agent._bridge.google_api import inspect_google_api_request

    model = Scripted(
        calls_output(replace(READ, id="first")),
        calls_output(replace(READ, id="second")),
        calls_output(),
    )
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    user: Any = {"role": "user", "parts": [{"text": TASK}]}
    tools: Any = [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                }
            ]
        }
    ]

    async def request(contents: list[Any]) -> Any:
        return await inspect_google_api_request(
            {"model": "inspect", "contents": contents, "tools": tools},
            None,
            None,
            bridge,
        )

    def turn(response: Any, out: str) -> list[Any]:
        response_part = {
            "functionResponse": {"name": "read_file", "response": {"out": out}}
        }
        return [
            {"role": "model", "parts": response["candidates"][0]["content"]["parts"]},
            {"role": "user", "parts": [response_part]},
        ]

    with active(terminate_on_secret()):
        first = await request([user])
        second = await request([user, *turn(first, "benign")])
        # the scaffold drops the earlier call and its result
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await request([user, *turn(second, "secret")])


async def test_a_result_is_checked_with_its_proposal_once_its_call_is_compacted() -> (
    None
):
    seen: Steps = []
    model = Scripted(calls_output(READ, content="Reading."), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    with active([bridge_recording(seen)]):
        await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content="Summary of earlier turns."),
                ChatMessageTool(content="contents", tool_call_id=READ.id),
            ],
        )

    # the token identifies the execution whatever happened to its call
    before, after = seen
    assert isinstance(after, AfterToolCall)
    assert (after.call, after.message, after.output) == (READ, "Reading.", "contents")
    assert after.input == model.inputs[0]
    assert after.message_id == before.message_id


async def test_a_cancelled_host_result_check_consumes_the_grant() -> None:
    hold = Hold()
    tool = AsyncMock(return_value="secret")
    bridge = sandbox_bridge(tool)
    model = Scripted(calls_output(replace(READ, function="mcp__host__read_file")))
    handed: list[Any] = []

    with active(held_terminate(hold)):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with anyio.CancelScope() as scope:

            async def cancel() -> None:
                await hold.ready.wait()
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel)
                handed.append(
                    await call_host_tool(bridge)("host", "read_file", READ.arguments)
                )

        assert scope.cancelled_caught
        assert hold.cleaned_up == 1
        assert handed == []
        assert not bridge._tool_execution_grants
        with pytest.raises(PermissionError):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    tool.assert_awaited_once()


async def test_a_cancelled_tool_call_stage_registers_nothing() -> None:
    started, cleaned = anyio.Event(), anyio.Event()
    bridge = sandbox_bridge()
    model = Scripted(calls_output(replace(READ, function="mcp__host__read_file")))
    handed: list[ModelOutput] = []

    with active([bridge_waiting(started, cleaned)]):
        with anyio.CancelScope() as scope:

            async def cancel() -> None:
                await started.wait()
                scope.cancel()

            async with anyio.create_task_group() as tg:
                tg.start_soon(cancel)
                handed.append(
                    await generate(
                        bridge,
                        model,
                        [ChatMessageUser(content=TASK)],
                        declare_read_file(),
                    )
                )

        assert scope.cancelled_caught

    assert cleaned.is_set()
    assert handed == []
    assert not bridge._tool_execution_grants
    assert bridge._handed_calls is None or not bridge._handed_calls.proposals


@pytest.mark.parametrize("duplicate_id", [False, True])
async def test_calls_sharing_an_id_keep_their_own_result_checks(
    duplicate_id: bool,
) -> None:
    one = replace(READ, id="one")
    two = replace(
        READ, id="one" if duplicate_id else "two", arguments={"path": "other"}
    )
    seen: Steps = []
    model = Scripted(calls_output(one, two), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                *[
                    ChatMessageTool(content=content, tool_call_id=call.id)
                    for content, call in zip("ab", output.message.tool_calls or [])
                ],
            ],
        )

    # the scaffold is handed each call under the model's id, shared or not
    handed = [call.id for call in output.message.tool_calls or []]
    assert handed == (["one", "one"] if duplicate_id else ["one", "two"])
    # a response's results are checked concurrently, each as its own call
    assert sorted(
        (s.call.arguments["path"], s.output)
        for s in seen
        if isinstance(s, AfterToolCall)
    ) == [("notes.txt", "a"), ("other", "b")]


async def test_calls_sharing_an_id_keep_their_own_modifications() -> None:
    one = replace(READ, id="one")
    two = replace(READ, id="one", arguments={"path": "other"})
    model = Scripted(calls_output(one, two))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    @protocol
    def modify_other() -> Protocol:
        async def rewrite(
            context: Context, step: BeforeToolCall, escalations: Escalations
        ) -> Decision | None:
            if step.call.arguments["path"] != "other":
                return None
            modified = replace(step.call, arguments={"path": "safe.txt"})
            return Decision(action="modify", modified=modified, explanation="safer")

        return rewrite

    with active(modify_other()):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    # each call keeps its own arguments, under the id they share
    first, second = output.message.tool_calls or []
    assert first == one
    assert second == replace(two, arguments={"path": "safe.txt"})


async def test_a_host_call_beyond_the_scaffold_cap_is_still_checked() -> None:
    from inspect_ai.agent._bridge._sentinel import _MAX_PROPOSALS

    calls = [
        replace(
            READ,
            id=f"call_{i}",
            function="mcp__host__read_file",
            arguments={"path": str(i)},
        )
        for i in range(_MAX_PROPOSALS + 1)
    ]
    bridge = sandbox_bridge(AsyncMock(return_value="secret"))
    model = Scripted(calls_output(*calls))

    with active(terminate_on_secret()):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await call_host_tool(bridge)("host", "read_file", {"path": "0"})


async def test_an_evicted_host_grant_takes_its_check_and_denies_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.agent._bridge.sandbox import types as sandbox_types

    monkeypatch.setattr(sandbox_types, "_MAX_TOOL_EXECUTION_GRANTS", 2)
    calls = [
        replace(
            READ,
            id=f"call_{i}",
            function="mcp__host__read_file",
            arguments={"path": str(i)},
        )
        for i in range(3)
    ]
    tool = AsyncMock(return_value="secret")
    bridge = sandbox_bridge(tool)
    model = Scripted(calls_output(*calls))

    with active(terminate_on_secret()):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(PermissionError):
            await call_host_tool(bridge)("host", "read_file", {"path": "0"})
        tool.assert_not_awaited()
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await call_host_tool(bridge)("host", "read_file", {"path": "2"})


async def test_a_host_tool_error_is_checked_before_it_is_returned() -> None:
    from inspect_ai.tool import ToolError

    call = replace(READ, function="mcp__host__read_file")
    bridge = sandbox_bridge(AsyncMock(side_effect=ToolError("secret error text")))
    model = Scripted(calls_output(call))

    with active(bridge_terminate(after=True)):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(TerminateSampleError):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    assert not bridge._failure_requested.is_set()


async def test_a_host_tool_error_reaches_the_scaffold_once_checked() -> None:
    from inspect_ai.tool import ToolError

    seen: Steps = []
    call = replace(READ, function="mcp__host__read_file")
    bridge = sandbox_bridge(AsyncMock(side_effect=ToolError("secret error text")))
    model = Scripted(calls_output(call))

    with active([bridge_recording(seen)]):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(ToolError, match="secret error text"):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    _, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.result.error is not None
    assert after.result.error.type == "unknown"
    assert after.result.error.message == (
        "Error calling method call_tool: secret error text"
    )
    assert bridge._failure is None


def host_errors() -> list[Exception]:
    from inspect_ai.tool import ToolError

    return [
        TimeoutError("secret token"),
        ToolError("secret token"),
        ExceptionGroup("secret group", [TimeoutError("timed out")]),
        ExceptionGroup("tool failed", [ToolError("secret token")]),
    ]


@pytest.mark.parametrize("decided_by", ["defect", "limit", "bare_limit", "tool_errors"])
async def test_a_host_tool_exception_group_is_decided_before_its_result_check(
    decided_by: str,
) -> None:
    # the group is classified by its decisive leaf (a defect, then a limit,
    # before an expected tool error), whatever its order, before the
    # tool_result stage decides whether the model sees an error to check
    from inspect_ai.tool import ToolError
    from inspect_ai.util._limit import LimitExceededError

    bug = RuntimeError("tool bug")
    limit = LimitExceededError("message", value=2, limit=1)
    second: Exception = {
        "defect": bug,
        "limit": limit,
        "bare_limit": limit,
        "tool_errors": ToolError("another"),
    }[decided_by]
    group = ExceptionGroup("secret group", [ToolError("secret token"), second])
    seen: Steps = []
    call = replace(READ, function="mcp__host__read_file")
    bridge = sandbox_bridge(
        AsyncMock(side_effect=limit if decided_by == "bare_limit" else group)
    )

    with active([bridge_recording(seen)]):
        await generate(
            bridge,
            Scripted(calls_output(call)),
            [ChatMessageUser(content=TASK)],
            declare_read_file(),
        )
        with pytest.raises(Exception) as raised:
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    after = [step for step in seen if isinstance(step, AfterToolCall)]
    if decided_by == "defect":
        # a bug in the eval's tool fails the sample; the model sees no error
        assert after == []
        assert bridge._failure is bug
        assert raised.value is group
    elif decided_by in ("limit", "bare_limit"):
        # main turns a limit into a model-facing tool error
        [checked] = after
        assert checked.result.error is not None
        assert checked.result.error.type == "limit"
        assert bridge._failure is None
        assert isinstance(raised.value, ToolError)
        assert "message limit of 1" in str(raised.value)
    else:
        # the scaffold receives the group's error, which is checked as such
        [checked] = after
        assert checked.result.error is not None
        assert checked.result.error.message == (
            "Error calling method call_tool: secret group (2 sub-exceptions)"
        )
        assert bridge._failure is None
        assert raised.value is group


@protocol
def terminate_on_secret_text() -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        if "secret" in result_text(step):
            return Decision.terminate("blocked secret")
        return None

    return after


def result_text(step: AfterToolCall) -> str:
    """The result's text and its error's message, as rules read a result."""
    error = step.result.error
    return step.result.text + (f"\n{error.message}" if error is not None else "")


async def deliver_host_call(bridge: SandboxAgentBridge) -> str | None:
    """The error the sandbox service delivers for a call to the host `read_file`."""
    from inspect_ai.agent._bridge.sandbox.service import MODEL_SERVICE
    from inspect_ai.util import ExecResult, SandboxEnvironment
    from inspect_ai.util._sandbox.service import SandboxService

    request_id = "req1"
    request = {
        "id": request_id,
        "method": "call_tool",
        "params": {"server": "host", "tool": "read_file", "arguments": READ.arguments},
    }
    service = SandboxService(
        name=MODEL_SERVICE, sandbox=cast(SandboxEnvironment, object())
    )
    service._requests_dir = "/requests"
    service.add_method("call_tool", call_host_tool(bridge))
    read = AsyncMock(return_value=ExecResult(True, 0, json.dumps(request), ""))
    write = AsyncMock()
    with (
        patch.object(service, "_exec", read),
        patch.object(service, "_write_response", write),
    ):
        await service._handle_request(f"/requests/{request_id}.json")
    _, _, result, error = write.call_args.args
    assert result is None
    return cast(str | None, error)


@pytest.mark.parametrize("error", host_errors(), ids=repr)
async def test_a_host_tool_error_is_checked_as_the_scaffold_receives_it(
    error: Exception,
) -> None:
    seen: Steps = []
    call = replace(READ, function="mcp__host__read_file")
    bridge = sandbox_bridge(AsyncMock(side_effect=error))
    model = Scripted(calls_output(call))

    with active([bridge_recording(seen)]):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        delivered = await deliver_host_call(bridge)

    _, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.result.error is not None
    assert after.result.error.message == delivered
    assert after.result.text == ""
    assert bridge._failure is None


@pytest.mark.parametrize(
    "error,terminates",
    list(zip(host_errors(), [True, True, True, False])),
    ids=repr,
)
async def test_a_host_tool_error_terminates_on_what_the_scaffold_receives(
    error: Exception, terminates: bool
) -> None:
    call = replace(READ, function="mcp__host__read_file")
    bridge = sandbox_bridge(AsyncMock(side_effect=error))
    model = Scripted(calls_output(call))

    with active(terminate_on_secret_text()):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        if terminates:
            with pytest.raises(TerminateSampleError, match="blocked secret"):
                await deliver_host_call(bridge)
        else:
            # a group's message, not its members', is what the scaffold receives
            assert (
                await deliver_host_call(bridge)
                == "Error calling method call_tool: tool failed (1 sub-exception)"
            )
    assert bridge._failure is None


@pytest.mark.parametrize("generates", [False, True])
async def test_both_stages_see_the_input_a_filter_sent(generates: bool) -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    async def add_system_message(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput:
        input = [ChatMessageSystem(content="Filtered."), *input]
        if generates:
            return await model.generate(
                input=input, tools=tools, tool_choice=tool_choice, config=config
            )
        return GenerateInput(input, tools, tool_choice, config)

    bridge.filter = add_system_message
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    assert before.input == model.inputs[0]
    assert after.input == model.inputs[0]
    assert [m.text for m in before.input] == ["Filtered.", TASK]


POLICY = "Author policy: read only safe.txt."


def reasoned_history() -> list[ChatMessage]:
    return [
        ChatMessageUser(content=TASK),
        ChatMessageAssistant(
            content=[
                ContentReasoning(reasoning="Earlier thoughts."),
                ContentText(text="Looked around."),
            ]
        ),
        ChatMessageUser(content="Go on."),
    ]


class RecordingSink:
    """A model event sink that keeps events, emitting them only if `forward`."""

    def __init__(self, forward: bool) -> None:
        self.forward = forward
        self.events: list[ModelEvent] = []

    def on_pending(self, event: ModelEvent) -> None:
        self.events.append(event)
        if self.forward:
            transcript()._event(event)

    def on_complete(self, event: ModelEvent) -> None:
        if self.forward:
            transcript()._event_updated(event)


def sink_for(sink: str | None) -> RecordingSink | None:
    return RecordingSink(forward=sink == "forwards") if sink is not None else None


def model_events(sink: RecordingSink | None) -> list[ModelEvent]:
    """Every `ModelEvent`, whether the transcript or a withholding sink holds it."""
    recorded = [e for e in transcript().events if isinstance(e, ModelEvent)]
    held = [e for e in sink.events if e not in recorded] if sink is not None else []
    return recorded + held


def passing_filter(filter: str | None) -> GenerateFilter | None:
    """A filter that hands back its input (`rewrites`) or generates it (`generates`)."""

    async def passes_through(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput:
        if filter == "generates":
            return await model.generate(
                input=input, tools=tools, tool_choice=tool_choice, config=config
            )
        return GenerateInput(input, tools, tool_choice, config)

    return passes_through if filter is not None else None


@pytest.mark.parametrize("sink", [None, "forwards", "withholds"])
@pytest.mark.parametrize("filter", [None, "rewrites", "generates"])
@pytest.mark.parametrize("normalized", ["system_message", "reasoning_history"])
async def test_both_stages_see_the_input_the_model_was_sent(
    normalized: str, filter: str | None, sink: str | None
) -> None:
    seen: Steps = []
    # Model.generate adds the configured system message or drops reasoning
    # history after the bridge hands over its input
    model = Scripted(
        calls_output(READ),
        calls_output(),
        config=GenerateConfig(system_message=POLICY)
        if normalized == "system_message"
        else GenerateConfig(reasoning_history="none"),
    )
    history = reasoned_history()
    bridge = in_process_bridge(history)
    bridge.filter = passing_filter(filter)
    bridge.model_event_sink = sink_for(sink)

    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    sent = model_events(bridge.model_event_sink)[0].input
    assert before.input == sent == model.inputs[0]
    assert after.input == sent
    reasoning = [
        content
        for message in sent
        if not isinstance(message.content, str)
        for content in message.content
        if isinstance(content, ContentReasoning)
    ]
    if normalized == "system_message":
        assert isinstance(sent[0], ChatMessageSystem) and sent[0].text == POLICY
        assert reasoning
    else:
        assert not reasoning


@monitor
def judging_output(seen: Any, judge: Model) -> MonitorGroup:
    """Records the tool steps, and asks a judge model about each model output."""

    async def judged(context: Context, step: AfterGenerate) -> Observation | None:
        await judge.generate([ChatMessageUser(content="Judge this.")])
        return None

    async def before(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(step)
        return None

    async def after(context: Context, step: AfterToolCall) -> Observation | None:
        seen.append(step)
        return None

    return MonitorGroup(judged, before, after)


@pytest.mark.parametrize("sink", ["forwards", "withholds"])
async def test_a_monitors_generation_is_not_taken_for_the_proposal(sink: str) -> None:
    seen: Steps = []
    judge = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", "Fine.")] * 4,
        memoize=False,
    )
    model = Scripted(calls_output(READ), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    bridge.model_event_sink = sink_for(sink)

    # an agent turn, so the model_output stage runs inside Model.generate,
    # under the bridge's sink
    with sentinel_solving(), active([judging_output(seen, judge)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    assert before.input == after.input == model.inputs[0]


@pytest.mark.parametrize("sink", [None, "forwards", "withholds"])
async def test_both_stages_see_the_input_a_response_filter_regenerated_from(
    sink: str | None,
) -> None:
    seen: Steps = []
    model = Scripted(calls_output(), calls_output(READ), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    async def regenerate(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        if output.message.tool_calls:
            return None
        return await model.generate(
            input=[ChatMessageSystem(content="Regenerated."), *input.input],
            tools=input.tools,
            tool_choice=input.tool_choice,
            config=input.config,
        )

    bridge.response_filter = regenerate
    bridge.model_event_sink = sink_for(sink)
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    assert before.input == after.input == model.inputs[1]


@pytest.mark.parametrize("sink", [None, "forwards", "withholds"])
@pytest.mark.parametrize("filter", ["returns", "regenerates", "discards"])
async def test_a_response_filter_output_with_the_generations_message_id(
    sink: str | None, filter: str
) -> None:
    # the filter returns the generation's output, or regenerates an equal one
    # and returns or discards it
    seen: Steps = []
    generated = calls_output(READ)
    # an equal message keeps its id through the response filter
    # (`_settle_message_ids`), so the id alone can't tell the two generations apart
    regenerated = [generated.model_copy(deep=True)] if filter != "returns" else []
    model = Scripted(generated, *regenerated, calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    filtered: list[bool] = []

    async def returns_equal(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        if filtered:
            return None
        filtered.append(True)
        if filter == "returns":
            return output
        regeneration = await model.generate(
            input=[ChatMessageSystem(content="Regenerated."), *input.input],
            tools=input.tools,
            tool_choice=input.tool_choice,
            config=input.config,
        )
        return regeneration if filter == "regenerates" else None

    bridge.response_filter = returns_equal
    bridge.model_event_sink = sink_for(sink)
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    assert output.message.id == generated.message.id
    before, after = seen
    sent = model.inputs[1] if filter == "regenerates" else model.inputs[0]
    assert before.input == after.input == sent


@pytest.mark.parametrize("sink", [None, "forwards", "withholds"])
@pytest.mark.parametrize(
    "returned,sent",
    [
        ("argument", 0),
        ("first", 1),
        ("second", 2),
        ("copy", None),
        ("copy_after_both", None),
    ],
)
async def test_the_steps_see_the_input_of_the_generation_a_response_filter_returned(
    sink: str | None, returned: str, sent: int | None
) -> None:
    # every generation has an equal message with the same id, so only the
    # object the filter returned says which one produced the response; a copy
    # of one is from no generation the bridge saw
    seen: Steps = []
    generated = calls_output(READ)
    regenerations = (
        [generated.model_copy(deep=True) for _ in range(2)]
        if returned not in ["argument", "copy"]
        else []
    )
    model = Scripted(generated, *regenerations, calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    filtered: list[bool] = []

    async def response_filter(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        if filtered:
            return None
        filtered.append(True)
        if returned == "argument":
            return output
        if returned == "copy":
            return output.model_copy(deep=True)
        first, second = [
            await model.generate(
                input=[ChatMessageSystem(content=name), *input.input],
                tools=input.tools,
                tool_choice=input.tool_choice,
                config=input.config,
            )
            for name in ["First.", "Second."]
        ]
        if returned == "first":
            return first
        if returned == "second":
            return second
        return output.model_copy(deep=True)

    bridge.response_filter = response_filter
    bridge.model_event_sink = sink_for(sink)
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    expected = model.inputs[sent] if sent is not None else None
    assert before.input == after.input == expected


@pytest.mark.parametrize("sink", [None, "forwards", "withholds"])
@pytest.mark.parametrize(
    "change", ["graft_choices", "graft_message", "graft_calls", "edit", "regeneration"]
)
async def test_a_response_filter_output_changed_since_its_generation_has_no_input(
    sink: str | None, change: str
) -> None:
    # the response handed over is no longer what a generation returned, so no
    # generation's input is what the model was sent for it
    seen: Steps = []
    retarget = replace(READ, arguments={"path": "/etc/shadow"})
    retries = [calls_output(retarget)] if change != "edit" else []
    model = Scripted(calls_output(READ), *retries, calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    filtered: list[bool] = []

    async def response_filter(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        if filtered:
            return None
        filtered.append(True)
        if change == "edit":
            output.message.tool_calls = [retarget]
            return output
        retry = await model.generate(
            input=[ChatMessageSystem(content="Retry."), *input.input],
            tools=input.tools,
            tool_choice=input.tool_choice,
            config=input.config,
        )
        if change == "graft_choices":
            output.choices = retry.choices
        elif change == "graft_message":
            output.choices[0].message = retry.message
        elif change == "graft_calls":
            output.message.tool_calls = retry.message.tool_calls
        else:
            retry.message.tool_calls = [READ]
            return retry
        return output

    bridge.response_filter = response_filter
    bridge.model_event_sink = sink_for(sink)
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    assert before.input is None and after.input is None


class Unserializable:
    """Metadata a message log can't serialize, so its event keeps the live message."""


@pytest.mark.parametrize("filter", ["request", "response"])
async def test_an_edited_output_whose_event_kept_the_live_message_has_no_input(
    filter: str,
) -> None:
    # the event's output shares the message, so an edit changes both sides
    # and comparing them can't show it
    seen: Steps = []
    first = calls_output(READ)
    first.message.metadata = {"opaque": Unserializable()}
    second = calls_output(replace(READ, arguments={"path": "/etc/shadow"}))
    outputs = [first, second, calls_output()]
    model = Scripted(*(outputs if filter == "request" else [calls_output(), *outputs]))
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    filtered: list[bool] = []

    async def graft(model: Model, input: GenerateInput) -> ModelOutput:
        one, two = [
            await model.generate(
                input=[ChatMessageSystem(content=name), *input.input],
                tools=input.tools,
                tool_choice=input.tool_choice,
                config=input.config,
            )
            for name in ["One.", "Two."]
        ]
        one.message.tool_calls = two.message.tool_calls
        return one

    async def request_filter(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput | None:
        if filtered:
            return None
        filtered.append(True)
        return await graft(model, GenerateInput(messages, tools, tool_choice, config))

    async def response_filter(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        if filtered:
            return None
        filtered.append(True)
        return await graft(model, input)

    if filter == "request":
        bridge.filter = request_filter
    else:
        bridge.response_filter = response_filter
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)

    assert output.message.tool_calls == second.message.tool_calls
    [before] = seen
    assert before.input is None


async def test_non_google_computer_scroll_with_observe_only_sentinel() -> None:
    call = ToolCall(
        id="scroll",
        function="computer",
        arguments={
            "action": "scroll",
            "coordinate": [100, 200],
            "scroll_amount": 3.0,
        },
    )
    seen: Steps = []
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    with active([bridge_recording(seen)]):
        output = await generate(
            bridge,
            Scripted(calls_output(call)),
            [ChatMessageUser(content=TASK)],
        )
    assert output.message.tool_calls == [call]
    assert [step.call.function for step in seen] == ["computer"]


@pytest.mark.parametrize(("original", "edited"), [(True, 1), (False, 0), (1, True)])
async def test_boolean_numeric_response_filter_edit_clears_tool_producer(
    original: bool | int, edited: bool | int
) -> None:
    call = replace(READ, arguments={"path": original})
    changed = replace(READ, arguments={"path": edited})
    model = Scripted(calls_output(call), calls_output())
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    seen: Steps = []
    filtered = False

    async def response_filter(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        nonlocal filtered
        if filtered:
            return None
        filtered = True
        output.message.tool_calls = [changed]
        return output

    bridge.response_filter = response_filter
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )
    assert output.message.tool_calls == [changed]
    before, after = seen
    assert (before.input, after.input) == (None, None)
    assert (before.tools, after.tools) == (None, None)


async def test_an_output_two_generations_returned_has_no_input() -> None:
    # a model that returns the same object for two inputs: which one the
    # response answers can't be told
    seen: Steps = []
    shared = calls_output(READ)
    model = Scripted(shared)
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)

    async def probes(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        await model.generate(
            input=[ChatMessageSystem(content="Probe."), *input.input],
            tools=input.tools,
            tool_choice=input.tool_choice,
            config=input.config,
        )
        return None

    bridge.response_filter = probes
    with active([bridge_recording(seen)]):
        await generate(bridge, model, history)

    [before] = seen
    assert before.input is None


@pytest.mark.parametrize("returned", ["argument", "copy"])
async def test_concurrent_bridges_keep_their_own_generations(returned: str) -> None:
    shared = calls_output(READ)
    both_filtering = anyio.Event()
    filtering: list[str] = []
    seen: dict[str, Steps] = {}
    inputs: dict[str, list[ChatMessage]] = {}

    async def run(name: str) -> None:
        seen[name] = []
        # both bridges' generations have the same message id
        model = Scripted(shared.model_copy(deep=True))
        bridge = in_process_bridge([])
        bridge.model_event_sink = sink_for("forwards")

        async def response_filter(
            model: Model, output: ModelOutput, input: GenerateInput
        ) -> ModelOutput | None:
            filtering.append(name)
            if len(filtering) == 2:
                both_filtering.set()
            await both_filtering.wait()
            return output if returned == "argument" else output.model_copy(deep=True)

        bridge.response_filter = response_filter
        with active([bridge_recording(seen[name])]):
            await generate(
                bridge,
                model,
                [ChatMessageSystem(content=name), ChatMessageUser(content=TASK)],
            )
        inputs[name] = model.inputs[0]

    async with anyio.create_task_group() as tg:
        tg.start_soon(run, "A")
        tg.start_soon(run, "B")

    for name in ["A", "B"]:
        [step] = seen[name]
        assert step.input == (inputs[name] if returned == "argument" else None)


class AnnotatingSink:
    """A model event sink as inspect_swe's Claude Code and Codex consumers are.

    It attributes each call to a span in `on_pending` (a sub-agent's, with
    `span_id`), and attaches its own rendering to the logged snapshot's tool
    calls in `on_complete`, as both consumers do for their built-in tools.
    """

    def __init__(self, span_id: str | None = None) -> None:
        self.span_id = span_id

    def on_pending(self, event: ModelEvent) -> None:
        if self.span_id is not None:
            event.span_id = self.span_id
        transcript()._event(event)

    def on_complete(self, event: ModelEvent) -> None:
        for tool_call in event.output.message.tool_calls or []:
            if tool_call.view is None:
                tool_call.view = ToolCallContent(
                    format="markdown", content=f"**{tool_call.function}**"
                )
        transcript()._event_updated(event)


@pytest.mark.parametrize("span_id", [None, "sub-agent"])
@pytest.mark.parametrize("filter", [None, "argument"])
async def test_a_sinks_display_annotations_keep_the_calls_generation(
    span_id: str | None, filter: str | None
) -> None:
    seen: Steps = []
    model = Scripted(
        calls_output(READ), calls_output(), config=GenerateConfig(system_message=POLICY)
    )
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    bridge.model_event_sink = AnnotatingSink(span_id)

    async def returns_its_argument(
        model: Model, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput | None:
        return output

    if filter is not None:
        bridge.response_filter = returns_its_argument
    with active([bridge_recording(seen)]):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
            ],
        )

    before, after = seen
    for step in (before, after):
        assert step.input == model.inputs[0]
        assert step.input is not None and step.input[0].text == POLICY
        assert step.tools is not None and step.tool_choice is not None


@pytest.mark.parametrize("executed", [False, True])
async def test_a_scaffold_result_for_a_host_call_is_checked(executed: bool) -> None:
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call), calls_output())
    tool = AsyncMock(return_value="benign")
    bridge = sandbox_bridge(tool)
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active(terminate_on_secret()):
        one = await generate(bridge, model, history, declare_read_file())
        if executed:
            assert await call_host_tool(bridge)(
                "host", "read_file", READ.arguments
            ) == ("benign")
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(
                bridge,
                model,
                [
                    *history,
                    one.message,
                    ChatMessageTool(content="secret", tool_call_id=call.id),
                ],
                declare_read_file(),
            )
        # checking the scaffold's result leaves the host call's own check pending
        if not executed:
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    assert len(model.inputs) == 1
    tool.assert_awaited_once()


async def test_a_host_result_changed_in_a_later_request_is_checked() -> None:
    seen: list[AfterToolCall] = []
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value="benign"))
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active(recording_terminate_on_secret(seen)):
        one = await generate(bridge, model, history, declare_read_file())
        await call_host_tool(bridge)("host", "read_file", READ.arguments)
        delivered = [
            *history,
            one.message,
            ChatMessageTool(
                content="benign", tool_call_id=call.id, function=call.function
            ),
        ]
        await generate(bridge, model, delivered, declare_read_file())
        assert len(seen) == 1
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(
                bridge,
                model,
                [
                    *delivered,
                    ChatMessageUser(content="Again."),
                    one.message,
                    ChatMessageTool(
                        content="secret", tool_call_id=call.id, function=call.function
                    ),
                ],
                declare_read_file(),
            )

    assert len(model.inputs) == 2


async def test_a_scaffold_result_during_the_host_check_is_checked() -> None:
    started, release = anyio.Event(), anyio.Event()
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value="benign"))
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    returned: list[Any] = []

    with active(held_benign(started, release)):
        one = await generate(bridge, model, history, declare_read_file())

        async def execute() -> None:
            returned.append(
                await call_host_tool(bridge)("host", "read_file", READ.arguments)
            )

        async with anyio.create_task_group() as tg:
            tg.start_soon(execute)
            await started.wait()
            with pytest.raises(TerminateSampleError, match="blocked secret"):
                await generate(
                    bridge,
                    model,
                    [
                        *history,
                        one.message,
                        ChatMessageTool(content="secret", tool_call_id=call.id),
                    ],
                    declare_read_file(),
                )
            release.set()

    assert returned == ["benign"]
    assert len(model.inputs) == 1


@protocol
def recording_terminate_on_secret(seen: Any) -> Protocol:
    async def after(
        context: Context, step: AfterToolCall, escalations: Escalations
    ) -> Decision | None:
        seen.append(step)
        if "secret" in step.result.text:
            return Decision.terminate("blocked secret")
        return None

    return after


@pytest.mark.parametrize("result_id", [None, ""])
async def test_a_result_without_an_id_is_checked(result_id: str | None) -> None:
    model = Scripted(calls_output())
    bridge = in_process_bridge([])

    with active(terminate_on_secret()):
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await generate(
                bridge,
                model,
                [
                    ChatMessageUser(content=TASK),
                    ChatMessageTool(
                        content="secret", function="read_file", tool_call_id=result_id
                    ),
                ],
            )

    assert model.inputs == []


@pytest.mark.parametrize("result_id", [None, ""])
async def test_a_responses_result_without_an_id_is_checked(
    result_id: str | None,
) -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request

    seen: list[AfterToolCall] = []
    model = Scripted(calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    def request(output: str) -> dict[str, Any]:
        result: dict[str, Any] = {"type": "function_call_output", "output": output}
        if result_id is not None:
            result["call_id"] = result_id
        return {
            "model": "inspect",
            "input": [{"role": "user", "content": TASK}, result],
        }

    with active(recording_terminate_on_secret(seen)):
        for _ in range(2):
            await inspect_responses_api_request(
                request("benign"), None, None, None, bridge
            )
        assert [step.result.text for step in seen] == ["benign"]
        # no assistant message in the request made the call
        assert seen[0].message_id == ""
        assert seen[0].input is None
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await inspect_responses_api_request(
                request("secret"), None, None, None, bridge
            )

    assert [step.result.text for step in seen] == ["benign", "secret"]
    assert len(model.inputs) == 2


PNG = "data:image/png;base64,iVBORw0KGgo="


@pytest.mark.parametrize(
    "result,checked",
    [
        ([ContentText(text="benign", internal={"note": "secret"})], None),
        (
            [
                ContentText(text="Screenshot:", internal={"note": "secret"}),
                ContentImage(image=PNG),
            ],
            [ContentText(text="Screenshot:"), ContentImage(image=PNG)],
        ),
        (
            ContentImage(image="https://example.invalid/a.png"),
            [ContentText(text="https://example.invalid/a.png")],
        ),
    ],
    ids=["serialized", "mcp", "url"],
)
async def test_host_content_is_checked_as_delivered(result: Any, checked: Any) -> None:
    seen: Steps = []
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call))
    bridge = sandbox_bridge(AsyncMock(return_value=result))

    with active([bridge_recording(seen)]):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        delivered = await call_host_tool(bridge)("host", "read_file", READ.arguments)

    _, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.output == result
    if checked is None:
        assert isinstance(delivered, str) and "secret" in delivered
        assert after.result.content == delivered
    else:
        assert after.result.content == checked
        assert delivered == [mcp_block(content) for content in checked]


def mcp_block(content: Any) -> dict[str, Any]:
    if isinstance(content, ContentImage):
        return {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}
    return {"type": "text", "text": content.text}


async def test_without_a_sentinel_host_content_is_delivered_unchanged() -> None:
    result = [
        ContentText(text="caption", internal={"marker": "expected"}),
        ContentImage(image=PNG),
    ]
    bridge = sandbox_bridge(AsyncMock(return_value=result))
    bridge.proposal_exempt_servers.add("host")

    delivered = await call_host_tool(bridge)("host", "read_file", READ.arguments)

    assert delivered == [
        {"internal": {"marker": "expected"}, "type": "text", "text": "caption"},
        {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"},
    ]


@pytest.mark.parametrize("proposed", [False, True])
async def test_an_exempt_host_result_is_checked(proposed: bool) -> None:
    seen: Steps = []
    call = replace(READ, function="mcp__host__read_file")
    bridge = sandbox_bridge(AsyncMock(return_value="secret"))
    bridge.proposal_exempt_servers.add("host")
    bridge.state.messages = [ChatMessageUser(content=TASK)]

    with active(recording_terminate_on_secret(seen)):
        output = (
            await generate(
                bridge,
                Scripted(calls_output(call)),
                [ChatMessageUser(content=TASK)],
                declare_read_file(),
            )
            if proposed
            else None
        )
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    (after,) = seen
    assert isinstance(after, AfterToolCall)
    assert after.call.function == "read_file"
    assert after.call.arguments == READ.arguments
    assert after.message_id == (output.message.id if output is not None else "")
    # what the model was sent when it proposed the call, else nothing
    assert (after.input is not None) is proposed
    assert after.result.text == "secret"


async def test_serialized_host_content_terminates_on_what_is_delivered() -> None:
    call = replace(READ, function="mcp__host__read_file")
    model = Scripted(calls_output(call))
    bridge = sandbox_bridge(
        AsyncMock(
            return_value=[ContentText(text="benign", internal={"note": "secret"})]
        )
    )

    with active(terminate_on_secret_text()):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(TerminateSampleError, match="blocked secret"):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)


@pytest.mark.parametrize("terminate", [True, False])
async def test_a_bridge_whose_result_check_failed_is_collectable(
    terminate: bool,
) -> None:
    import gc
    import weakref

    sentinel = terminate_on_secret() if terminate else bridge_raising(after=True)
    raised = TerminateSampleError if terminate else SentinelFailure

    async def failed_bridge() -> "weakref.ref[AgentBridge]":
        bridge = in_process_bridge([])
        with active(sentinel):
            with pytest.raises(raised):
                await generate(
                    bridge,
                    Scripted(calls_output()),
                    [
                        ChatMessageUser(content=TASK),
                        ChatMessageTool(content="secret", tool_call_id="unproposed"),
                    ],
                )
        return weakref.ref(bridge)

    bridge = await failed_bridge()
    gc.collect()
    assert bridge() is None


async def dialect_orphan_result(dialect: str, bridge: AgentBridge, id: str) -> None:
    """A scaffold sending a result that answers no call in its request."""
    if dialect == "completions":
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [
                    {"role": "user", "content": TASK},
                    {"role": "tool", "tool_call_id": id, "content": "x"},
                ],
            },
            None,
            bridge,
        )
    else:
        from inspect_ai.agent._bridge.responses import inspect_responses_api_request

        await inspect_responses_api_request(
            {
                "model": "inspect",
                "input": [
                    {"role": "user", "content": TASK},
                    {"type": "function_call_output", "call_id": id, "output": "x"},
                ],
            },
            None,
            None,
            None,
            bridge,
        )


def signed_parallel_output() -> ModelOutput:
    """A Gemini response: a signed call, then an unsigned parallel sibling."""
    first = replace(READ, id="read_a", arguments={"path": "a.txt"})
    second = replace(READ, id="read_b", arguments={"path": "b.txt"})
    return ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=[
                        ContentReasoning(
                            reasoning="c2lnbmF0dXJl",
                            redacted=True,
                            internal={"gemini_function_call_id": first.id},
                        ),
                        ContentReasoning(
                            reasoning="",
                            redacted=True,
                            internal={"gemini_function_call_id": second.id},
                        ),
                    ],
                    tool_calls=[first, second],
                ),
                stop_reason="tool_calls",
            )
        ],
    )


async def dialect_repeated_parallel_calls(
    dialect: str, bridge: AgentBridge
) -> list[str]:
    """A scaffold sending one request twice, then answering the second response's calls.

    Returns the ids the second response handed over.
    """
    if dialect == "completions":
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        messages: list[Any] = [{"role": "user", "content": TASK}]
        tools: Any = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": PATH_SCHEMA,
                },
            }
        ]
        request = {"model": "inspect", "messages": messages, "tools": tools}
        await inspect_completions_api_request(request, None, bridge)
        completion = await inspect_completions_api_request(request, None, bridge)
        message = completion.choices[0].message
        ids = [call.id for call in message.tool_calls or []]
        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [
                    *messages,
                    message.model_dump(exclude_none=True),
                    *[
                        {"role": "tool", "tool_call_id": id, "content": "x"}
                        for id in ids
                    ],
                ],
                "tools": tools,
            },
            None,
            bridge,
        )
        return ids
    else:
        from inspect_ai.agent._bridge.responses import inspect_responses_api_request

        items: list[Any] = [{"role": "user", "content": TASK}]
        responses_tools: Any = [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file.",
                "parameters": PATH_SCHEMA,
            }
        ]
        responses_request = {
            "model": "inspect",
            "input": items,
            "tools": responses_tools,
        }
        await inspect_responses_api_request(responses_request, None, None, None, bridge)
        result = await inspect_responses_api_request(
            responses_request, None, None, None, bridge
        )
        output = [item.model_dump(exclude_none=True) for item in result.output]
        ids = [item["call_id"] for item in output if item["type"] == "function_call"]
        await inspect_responses_api_request(
            {
                "model": "inspect",
                "input": [
                    *items,
                    *output,
                    *[
                        {"type": "function_call_output", "call_id": id, "output": "x"}
                        for id in ids
                    ],
                ],
                "tools": responses_tools,
            },
            None,
            None,
            None,
            bridge,
        )
        return ids


@pytest.mark.parametrize("dialect", ["completions", "responses"])
async def test_a_repeated_gemini_response_keeps_its_signatures_on_its_calls(
    dialect: str,
) -> None:
    from unittest.mock import MagicMock

    from inspect_ai.model._providers.google import content as google_content

    output = signed_parallel_output()
    model = Scripted(output, output, calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_recording([])]):
        ids = await dialect_repeated_parallel_calls(dialect, bridge)

    # the second response was handed over again under the model's ids
    assert ids == ["read_a", "read_b"]
    [assistant] = [m for m in model.inputs[2] if isinstance(m, ChatMessageAssistant)]
    assert [call.id for call in assistant.tool_calls or []] == ids
    replayed = await google_content(MagicMock(), assistant)
    calls = [part for part in replayed.parts or [] if part.function_call]
    assert [part.function_call.id for part in calls if part.function_call] == ids
    assert [part.thought_signature is not None for part in calls] == [True, False]
    # the model's output stays on the record as it was generated
    recorded = [e.output for e in transcript().events if isinstance(e, ModelEvent)]
    assert [
        content.internal
        for content in recorded[1].message.content
        if isinstance(content, ContentReasoning)
    ] == [{"gemini_function_call_id": "read_a"}, {"gemini_function_call_id": "read_b"}]


GEMINI_ACTIONS: list[tuple[str, dict[str, Any]]] = [
    ("click_at", {"x": 10, "y": 20}),
    ("hover_at", {"x": 10, "y": 20}),
    ("key_combination", {"keys": "control+c"}),
    ("type_text_at", {"x": 10, "y": 20, "text": "hi"}),
    ("scroll_document", {"direction": "down"}),
    ("scroll_at", {"x": 10, "y": 20, "direction": "up", "magnitude": 300}),
    ("drag_and_drop", {"x": 1, "y": 2, "destination_x": 3, "destination_y": 4}),
    ("wait_5_seconds", {}),
    ("open_web_browser", {}),
    ("navigate", {"url": "https://example.invalid"}),
]


@pytest.mark.parametrize(
    ("action", "args"), GEMINI_ACTIONS, ids=[a for a, _ in GEMINI_ACTIONS]
)
async def test_a_repeated_gemini_computer_action_keeps_its_name(
    action: str, args: dict[str, Any]
) -> None:
    from unittest.mock import MagicMock

    from google.genai.types import FunctionCall

    from inspect_ai.model._providers._google_computer_use import (
        tool_call_from_gemini_computer_action,
    )
    from inspect_ai.model._providers.google import as_chat_messages

    call = tool_call_from_gemini_computer_action(FunctionCall(name=action, args=args))
    model = Scripted(calls_output(call), calls_output(call), calls_output())
    bridge = in_process_bridge([])
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active([bridge_recording([])]):
        await generate(bridge, model, history)
        output = await generate(bridge, model, history)
        [handed] = output.message.tool_calls or []
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(
                    content="done", tool_call_id=handed.id, function="computer"
                ),
            ],
        )

    # handed over again, the call keeps its id
    assert handed.id == call.id
    replayed = await as_chat_messages(MagicMock(), model.inputs[2])
    parts = [part for content in replayed for part in content.parts or []]
    calls = [part.function_call.name for part in parts if part.function_call]
    results = [part.function_response.name for part in parts if part.function_response]
    assert (calls, results) == ([action], [action])


@protocol
def bridge_modify_action(arguments: dict[str, Any]) -> Protocol:
    async def rewrite(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        modified = replace(step.call, arguments=arguments)
        return Decision(action="modify", modified=modified, explanation="changed")

    return rewrite


CLICK: dict[str, Any] = {"action": "left_click", "coordinate": [100, 200]}
WAIT: dict[str, Any] = {"action": "wait"}
NAVIGATE: dict[str, Any] = {"action": "navigate", "text": "https://example.com"}
SCROLL_AT: dict[str, Any] = {
    "action": "scroll",
    "coordinate": [100, 200],
    "scroll_direction": "down",
    "scroll_amount": 3,
}
SCROLL_DOCUMENT: dict[str, Any] = {
    "action": "scroll",
    "scroll_direction": "down",
    "scroll_amount": 3,
}

ACTION_CHANGES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    *[
        (action, args, CLICK if action == "wait_5_seconds" else WAIT)
        for action, args in GEMINI_ACTIONS
    ],
    ("scroll_at", {"x": 10, "y": 20, "direction": "down"}, SCROLL_DOCUMENT),
    ("scroll_document", {"direction": "down"}, SCROLL_AT),
    ("search", {"query": "inspect"}, NAVIGATE),
    ("go_back", {}, {"action": "key", "text": "alt+Right"}),
    ("go_forward", {}, {"action": "key", "text": "alt+Left"}),
    (
        "scroll_at",
        {"x": 10, "y": 20, "direction": "down"},
        {k: v for k, v in SCROLL_AT.items() if k != "coordinate"},
    ),
]


async def computer_continuation(dialect: str, bridge: AgentBridge) -> None:
    """A scaffold in `dialect` running the computer call it is handed and sending its result."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"action": {"type": "string"}},
    }
    if dialect == "completions":
        from inspect_ai.agent._bridge.completions import (
            inspect_completions_api_request,
        )

        messages: list[Any] = [{"role": "user", "content": TASK}]
        tools: Any = [
            {
                "type": "function",
                "function": {
                    "name": "computer",
                    "description": "Use the computer.",
                    "parameters": schema,
                },
            }
        ]
        completion = await inspect_completions_api_request(
            {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
        )
        message = completion.choices[0].message
        assert message.tool_calls
        call_id = message.tool_calls[0].id
        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [
                    *messages,
                    message.model_dump(exclude_none=True),
                    {"role": "tool", "tool_call_id": call_id, "content": "done"},
                ],
                "tools": tools,
            },
            None,
            bridge,
        )
    elif dialect == "anthropic":
        from inspect_ai.agent._bridge.anthropic_api import (
            inspect_anthropic_api_request,
        )

        turns: list[Any] = [{"role": "user", "content": TASK}]
        anthropic_tools: Any = [
            {
                "name": "computer",
                "description": "Use the computer.",
                "input_schema": schema,
            }
        ]

        def request() -> dict[str, Any]:
            return {
                "model": "inspect",
                "max_tokens": 100,
                "messages": turns,
                "tools": anthropic_tools,
            }

        response = await inspect_anthropic_api_request(
            request(), None, None, None, bridge
        )
        content = [block.model_dump(exclude_none=True) for block in response.content]
        [use] = [block for block in content if block["type"] == "tool_use"]
        turns += [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": use["id"], "content": "done"}
                ],
            },
        ]
        await inspect_anthropic_api_request(request(), None, None, None, bridge)
    else:
        from inspect_ai.agent._bridge.google_api import inspect_google_api_request

        contents: list[Any] = [{"role": "user", "parts": [{"text": TASK}]}]
        google_tools: Any = [
            {
                "functionDeclarations": [
                    {
                        "name": "computer",
                        "description": "Use the computer.",
                        "parameters": schema,
                    }
                ]
            }
        ]

        def google_request() -> dict[str, Any]:
            return {"model": "inspect", "contents": contents, "tools": google_tools}

        first: Any = await inspect_google_api_request(
            google_request(), None, None, bridge
        )
        parts = first["candidates"][0]["content"]["parts"]
        [function_call] = [p["functionCall"] for p in parts if "functionCall" in p]
        contents += [
            {"role": "model", "parts": parts},
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "id": function_call.get("id"),
                            "name": function_call["name"],
                            "response": {"output": "done"},
                        }
                    }
                ],
            },
        ]
        await inspect_google_api_request(google_request(), None, None, bridge)


@pytest.mark.parametrize(
    ("action", "args", "modified"),
    ACTION_CHANGES,
    ids=[
        f"{action}-{gemini_computer_action_name(modified)}{'-partial' if index == len(ACTION_CHANGES) - 1 else ''}"
        for index, (action, _, modified) in enumerate(ACTION_CHANGES)
    ],
)
@pytest.mark.parametrize("dialect", ["completions", "anthropic", "google"])
async def test_a_modified_gemini_computer_action_continues_as_the_modified_action(
    dialect: str, action: str, args: dict[str, Any], modified: dict[str, Any]
) -> None:
    from unittest.mock import MagicMock

    from google.genai.types import FunctionCall

    from inspect_ai.model._providers._google_computer_use import (
        gemini_action_from_tool_call,
        gemini_replay_action_name,
        gemini_replay_args,
        tool_call_from_gemini_computer_action,
    )
    from inspect_ai.model._providers._google_computer_use_name import (
        gemini_computer_action_names,
    )
    from inspect_ai.model._providers.google import as_chat_messages

    call = tool_call_from_gemini_computer_action(FunctionCall(name=action, args=args))
    model = Scripted(calls_output(call), calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active([bridge_modify_action(modified)]):
        await computer_continuation(dialect, bridge)

    # the action of the modified arguments, or, for a call coming back as a
    # computer call, the parsed action when that fits them (`search` parses as
    # navigation); a Google scaffold runs and sends back the action it is
    # handed, the arguments' own
    handed = replace(call, arguments=modified)
    expected = (
        gemini_action_from_tool_call(handed)[0]
        if dialect == "google"
        else gemini_replay_action_name(handed)
    )
    assert expected in gemini_computer_action_names(modified)
    expected_args = (
        gemini_replay_args(expected, handed)
        if expected == action
        else gemini_action_from_tool_call(handed)[1]
    )
    replayed = await as_chat_messages(MagicMock(), model.inputs[1])
    parts = [part for content in replayed for part in content.parts or []]
    calls = [
        (part.function_call.name, part.function_call.args)
        for part in parts
        if part.function_call
    ]
    results = [part.function_response.name for part in parts if part.function_response]
    assert (calls, results) == ([(expected, expected_args)], [expected])


@pytest.mark.parametrize(
    ("action", "args"),
    [("go_back", {}), ("go_forward", {}), ("search", {"query": "inspect"})],
)
async def test_a_gemini_computer_action_parsed_as_another_keeps_its_id(
    action: str, args: dict[str, Any]
) -> None:
    from google.genai.types import FunctionCall

    from inspect_ai.model._providers._google_computer_use import (
        tool_call_from_gemini_computer_action,
    )

    call = tool_call_from_gemini_computer_action(FunctionCall(name=action, args=args))
    model = Scripted(calls_output(call))

    with active([bridge_recording([])]):
        output = await generate(
            in_process_bridge([]), model, [ChatMessageUser(content=TASK)]
        )

    assert [handed.id for handed in output.message.tool_calls or []] == [call.id]


@monitor
def generation_only() -> MonitorGroup:
    async def model_input(context: Context, step: BeforeGenerate) -> Observation | None:
        return None

    return MonitorGroup(model_input)


@pytest.mark.parametrize("proposed", [False, True])
async def test_without_a_tool_stage_host_content_is_delivered_unchanged(
    proposed: bool,
) -> None:
    result = [
        ContentText(text="caption", internal={"marker": "expected"}),
        ContentImage(image=PNG),
    ]
    bridge = sandbox_bridge(AsyncMock(return_value=result))
    if not proposed:
        bridge.proposal_exempt_servers.add("host")

    with active([generation_only()]):
        if proposed:
            await generate(
                bridge,
                Scripted(calls_output(replace(READ, function="mcp__host__read_file"))),
                [ChatMessageUser(content=TASK)],
                declare_read_file(),
            )
        delivered = await call_host_tool(bridge)("host", "read_file", READ.arguments)

    assert delivered == [
        {"internal": {"marker": "expected"}, "type": "text", "text": "caption"},
        {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"},
    ]
    assert not [e for e in sentinel_events() if e.stage in ("tool_call", "tool_result")]


@monitor
def tool_stages(seen: Any) -> MonitorGroup:
    async def before(context: Context, step: BeforeToolCall) -> Observation | None:
        seen.append(step)
        return None

    async def after(context: Context, step: AfterToolCall) -> Observation | None:
        seen.append(step)
        return None

    return MonitorGroup(before, after)


class DialectScaffold:
    """A scaffold keeping its conversation in `dialect` and answering each call."""

    def __init__(self, dialect: str, bridge: AgentBridge) -> None:
        self.dialect = dialect
        self.bridge = bridge
        self.history: list[Any] = [{"role": "user", "content": TASK}]

    async def request(self) -> str | None:
        """Send the conversation; returns the id the scaffold was handed, if any."""
        if self.dialect == "completions":
            from inspect_ai.agent._bridge.completions import (
                inspect_completions_api_request,
            )

            completion = await inspect_completions_api_request(
                {"model": "inspect", "messages": self.history}, None, self.bridge
            )
            message = completion.choices[0].message
            if not message.tool_calls:
                return None
            self.history.append(message.model_dump(exclude_none=True))
            return message.tool_calls[0].id
        from inspect_ai.agent._bridge.responses import inspect_responses_api_request

        response = await inspect_responses_api_request(
            {"model": "inspect", "input": self.history}, None, None, None, self.bridge
        )
        items = [item.model_dump(exclude_none=True) for item in response.output]
        calls = [item["call_id"] for item in items if item["type"] == "function_call"]
        self.history += items
        return calls[0] if calls else None

    def answer(self, call_id: str, result: str) -> None:
        self.history.append(
            {"role": "tool", "tool_call_id": call_id, "content": result}
            if self.dialect == "completions"
            else {"type": "function_call_output", "call_id": call_id, "output": result}
        )


def checked_results(seen: Steps) -> list[tuple[Any, Any]]:
    return [
        (step.output, step.call.arguments["path"])
        for step in seen
        if isinstance(step, AfterToolCall)
    ]


@pytest.mark.parametrize("dialect", ["completions", "responses"])
async def test_a_generate_only_interval_never_reuses_a_handed_out_id(
    dialect: str,
) -> None:
    seen: Steps = []
    old = replace(READ, arguments={"path": "old.txt"})
    new = replace(READ, arguments={"path": "new.txt"})
    model = Scripted(calls_output(old), calls_output(new), calls_output())
    scaffold = DialectScaffold(
        dialect,
        AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model.model}),
    )

    with active([tool_stages(seen)]):
        old_id = await scaffold.request()
    assert old_id is not None
    scaffold.answer(old_id, "old result")
    with active([generation_only()]):
        new_id = await scaffold.request()
    assert new_id not in (None, old_id)
    scaffold.answer(new_id, "new result")
    with active([tool_stages(seen)]):
        await scaffold.request()

    assert checked_results(seen) == [("new result", "new.txt")]


@pytest.mark.parametrize("dialect", ["completions", "responses"])
async def test_a_generate_only_interval_keeps_a_repeated_result_checked(
    dialect: str,
) -> None:
    seen: Steps = []
    old = replace(READ, arguments={"path": "old.txt"})
    new = replace(READ, arguments={"path": "new.txt"})
    model = Scripted(
        calls_output(old), calls_output(), calls_output(new), calls_output()
    )
    scaffold = DialectScaffold(
        dialect,
        AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model.model}),
    )

    with active([tool_stages(seen)]):
        old_id = await scaffold.request()
        assert old_id is not None
        scaffold.answer(old_id, "same result")
        await scaffold.request()
    with active([generation_only()]):
        new_id = await scaffold.request()
    assert new_id not in (None, old_id)
    scaffold.answer(new_id, "same result")
    with active([tool_stages(seen)]):
        await scaffold.request()

    assert checked_results(seen) == [
        ("same result", "old.txt"),
        ("same result", "new.txt"),
    ]


async def test_a_repeated_anthropic_response_keeps_its_interleaved_calls() -> None:
    from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    init_sample_assistant_internal()
    # as the provider parses a turn interleaving thinking with calls, recording
    # each call's position under the model's ID
    blocks: Any = [
        {"type": "thinking", "thinking": "first", "signature": "c2ln"},
        {"type": "tool_use", "id": "toolu_a", "name": "read_file", "input": {}},
        {"type": "thinking", "thinking": "second", "signature": "c2lnMg=="},
        {"type": "tool_use", "id": "toolu_b", "name": "read_file", "input": {}},
    ]
    tools = [ToolInfo(name="read_file", description="Read a file.")]
    output = await _anthropic_output(blocks, tools)
    # a cache hit returns the same output, parsed once
    model = Scripted(output, output)
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    request: Any = {
        "model": "inspect",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": TASK}],
        "tools": [
            {"name": "read_file", "description": "Read a file.", "input_schema": {}}
        ],
    }

    with active([bridge_recording([])]):
        first = await inspect_anthropic_api_request(request, None, None, None, bridge)
        second = await inspect_anthropic_api_request(request, None, None, None, bridge)

    order = ["thinking", "tool_use", "thinking", "tool_use"]
    assert [block.type for block in first.content] == order
    assert [block.type for block in second.content] == order
    # handed over again, under the model's ids
    uses = [block for block in second.content if block.type == "tool_use"]
    assert [block.id for block in uses] == ["toolu_a", "toolu_b"]
    # the model's output stays on the record as it was generated
    recorded = [e.output for e in transcript().events if isinstance(e, ModelEvent)]
    assert [call.id for call in recorded[1].message.tool_calls or []] == [
        "toolu_a",
        "toolu_b",
    ]


PNG_DATA_URI = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlE"
    "QVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.mark.parametrize("kind", ["custom", "computer"])
async def test_a_repeated_responses_native_call_stays_native(kind: str) -> None:
    from openai.types.responses import (
        ResponseComputerToolCall,
        ResponseCustomToolCall,
    )
    from openai.types.responses.computer_action import Screenshot

    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal
    from inspect_ai.model._openai_responses import openai_responses_inputs

    init_sample_assistant_internal()
    # as the provider parses the call, caching its native item under its ID
    item: Any
    tool: Any
    if kind == "custom":
        item = ResponseCustomToolCall(
            id="ctc_1",
            type="custom_tool_call",
            call_id="call_patch",
            name="apply_patch",
            input="*** Begin Patch\n*** End Patch",
        )
        tool = {
            "type": "custom",
            "name": "apply_patch",
            "description": "Patch.",
            "format": {"type": "text"},
        }
        result: Any = {"type": "custom_tool_call_output", "output": "Done."}
    else:
        item = ResponseComputerToolCall(
            id="cu_1",
            type="computer_call",
            call_id="call_computer",
            actions=[Screenshot(type="screenshot")],
            pending_safety_checks=[],
            status="completed",
        )
        tool = {
            "type": "computer_use_preview",
            "display_width": 1024,
            "display_height": 768,
            "environment": "linux",
        }
        result = {
            "type": "computer_call_output",
            "output": {"type": "computer_screenshot", "image_url": PNG_DATA_URI},
        }
    output = await _responses_output(item)
    # a cache hit returns the same output, parsed once
    model = Scripted(output, output, calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    items: list[Any] = [{"role": "user", "content": TASK}]

    def request(input: list[Any]) -> dict[str, Any]:
        return {"model": "inspect", "input": input, "tools": [tool]}

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_recording([])]),
    ):
        await inspect_responses_api_request(request(items), None, None, None, bridge)
        response = await inspect_responses_api_request(
            request(items), None, None, None, bridge
        )
        handed = [item.model_dump(exclude_none=True) for item in response.output]
        [call] = [item for item in handed if "call_id" in item]
        assert call["type"] == item.type and call["call_id"] == item.call_id
        await inspect_responses_api_request(
            request([*items, *handed, {**result, "call_id": call["call_id"]}]),
            None,
            None,
            None,
            bridge,
        )

    # the continuation replays to the model as generated
    replayed = await openai_responses_inputs(model.inputs[2])
    assert [
        (param["type"], param.get("call_id"))
        for param in replayed
        if "call_id" in param
    ] == [(item.type, item.call_id), (result["type"], item.call_id)]
    assert item.id in [param.get("id") for param in replayed]


# Python `==` takes these for the proposed arguments, JSON does not
_PROPOSED_NUMBERS = {"payload": {"enabled": 1, "flags": [0]}}
_APPROVED_BOOLEANS = {"payload": {"enabled": True, "flags": [False]}}


def _responses_modified_call(
    kind: str, change: str = "edit"
) -> tuple[Any, Any, Any, dict[str, Any]]:
    """A native Responses call, its tool, its result and approved arguments."""
    from openai.types.responses import (
        ResponseComputerToolCall,
        ResponseCustomToolCall,
        ResponseFunctionToolCall,
        ResponseToolSearchCall,
    )
    from openai.types.responses.computer_action import Click

    if change == "booleans":
        item, tool, result, _ = _responses_modified_call(kind)
        if kind == "function":
            item.arguments = json.dumps(_PROPOSED_NUMBERS)
            tool["parameters"]["properties"] = {"payload": {"type": "object"}}
        else:
            item.arguments = _PROPOSED_NUMBERS
        return item, tool, result, _APPROVED_BOOLEANS
    elif kind == "custom":
        return (
            ResponseCustomToolCall(
                id="ctc_1",
                type="custom_tool_call",
                call_id="call_patch",
                name="apply_patch",
                input="*** Begin Patch\n*** Delete File: notes.txt\n*** End Patch",
            ),
            {
                "type": "custom",
                "name": "apply_patch",
                "description": "Patch.",
                "format": {"type": "text"},
            },
            {"type": "custom_tool_call_output", "output": "Done."},
            {"input": "*** Begin Patch\n*** End Patch"},
        )
    elif kind == "function":
        return (
            ResponseFunctionToolCall(
                id="fc_1",
                type="function_call",
                call_id="call_read",
                name="read_file",
                arguments='{"path": "notes.txt"}',
            ),
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {"type": "function_call_output", "output": "contents"},
            {"path": "safe.txt"},
        )
    elif kind == "computer":
        return (
            ResponseComputerToolCall(
                id="cu_1",
                type="computer_call",
                call_id="call_computer",
                actions=[Click(type="click", button="left", x=10, y=20)],
                pending_safety_checks=[],
                status="completed",
            ),
            {
                "type": "computer_use_preview",
                "display_width": 1024,
                "display_height": 768,
                "environment": "linux",
            },
            {
                "type": "computer_call_output",
                "output": {"type": "computer_screenshot", "image_url": PNG_DATA_URI},
            },
            {"actions": [{"action": "wait"}]},
        )
    else:
        return (
            ResponseToolSearchCall(
                id="ts_1",
                type="tool_search_call",
                call_id="call_search",
                arguments={"query": "file tools"},
                execution="client",
                status="completed",
            ),
            {
                "type": "tool_search",
                "description": "Search for available tools",
                "execution": "client",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "type": "tool_search_output",
                "tools": [],
                "execution": "client",
                "status": "completed",
            },
            {"query": "approved tools"},
        )


def _responses_native_arguments(param: Any) -> Any:
    """What a native Responses call item carries as its arguments."""
    match param["type"]:
        case "custom_tool_call":
            return param["input"]
        case "function_call":
            return json.loads(param["arguments"])
        case "computer_call":
            return [dict(action) for action in param["actions"]]
        case _:
            return param["arguments"]


@pytest.mark.parametrize("repeated", [False, True])
@pytest.mark.parametrize(
    ("kind", "change"),
    [
        ("custom", "edit"),
        ("function", "edit"),
        ("computer", "edit"),
        ("tool_search", "edit"),
        ("function", "booleans"),
        ("tool_search", "booleans"),
    ],
)
async def test_a_modified_responses_call_continues_as_approved(
    kind: str, change: str, repeated: bool
) -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal
    from inspect_ai.model._openai_responses import (
        assistant_internal,
        openai_responses_inputs,
    )

    init_sample_assistant_internal()
    item, tool, result, approved = _responses_modified_call(kind, change)
    output = await _responses_output(item)
    original = deepcopy(assistant_internal().tool_calls[item.call_id])
    # a cache hit returns the same output, parsed once
    outputs = [output, output] if repeated else [output]
    model = Scripted(*outputs, calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    items: list[Any] = [{"role": "user", "content": TASK}]

    def request(input: list[Any]) -> dict[str, Any]:
        return {"model": "inspect", "input": input, "tools": [tool]}

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_modify_action(approved)]),
    ):
        response = await inspect_responses_api_request(
            request(items), None, None, None, bridge
        )
        if repeated:
            response = await inspect_responses_api_request(
                request(items), None, None, None, bridge
            )
        handed = [item.model_dump(exclude_none=True) for item in response.output]
        [call] = [item for item in handed if "call_id" in item]
        assert call["call_id"] == item.call_id
        await inspect_responses_api_request(
            request([*items, *handed, {**result, "call_id": call["call_id"]}]),
            None,
            None,
            None,
            bridge,
        )

    # the continuation replays the approved call natively, under the model's id
    # and without the item's id, which a stored response would resolve to the
    # generated arguments
    replayed: list[Any] = await openai_responses_inputs(model.inputs[len(outputs)])
    [replayed_call] = [param for param in replayed if param["type"] == item.type]
    assert replayed_call["call_id"] == item.call_id
    assert "id" not in replayed_call
    # as JSON, which tells `true` from `1`
    assert json.dumps(_responses_native_arguments(replayed_call)) == json.dumps(
        _responses_native_arguments(call)
    )
    assert json.dumps(_responses_native_arguments(call)) != json.dumps(
        _responses_native_arguments(original)
    )
    if change == "booleans":
        assert json.dumps(_responses_native_arguments(call)) == json.dumps(approved)


@pytest.mark.parametrize(
    ("param", "modified", "expected"),
    [
        (
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_plan",
                "name": "update_plan",
                "arguments": '{"plan": []}',
            },
            ToolCall(
                id="call_plan",
                function="todo_write",
                arguments={"todos": [{"content": "Tidy", "status": "pending"}]},
            ),
            {
                "arguments": json.dumps(
                    {"plan": [{"step": "Tidy", "status": "pending"}]}
                )
            },
        ),
        (
            {
                "type": "computer_call",
                "id": "cu_1",
                "call_id": "call_computer",
                "action": {"type": "click", "button": "left", "x": 1, "y": 2},
                "pending_safety_checks": [],
                "status": "completed",
            },
            ToolCall(
                id="call_computer",
                function="computer",
                arguments={"actions": [{"action": "wait"}]},
            ),
            {"actions": [{"type": "wait"}]},
        ),
    ],
    ids=["update_plan", "legacy_computer_action"],
)
def test_a_modified_responses_item_carries_the_approved_arguments(
    param: dict[str, Any], modified: ToolCall, expected: dict[str, Any]
) -> None:
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal
    from inspect_ai.model._openai_responses import (
        assistant_internal,
        hand_openai_tool_call,
    )

    init_sample_assistant_internal()
    assistant_internal().tool_calls[param["call_id"]] = cast(Any, deepcopy(param))
    hand_openai_tool_call(modified)

    handed = cast(dict[str, Any], assistant_internal().tool_calls[param["call_id"]])
    assert handed == {
        **{key: value for key, value in param.items() if key not in ("action", "id")},
        **expected,
    }


class Parsing:
    """A model whose responses are parsed as its provider parses them, when generated.

    With `wire`, each request's input is also serialized as its provider
    serializes it, when generated, into `wire`.
    """

    def __init__(
        self,
        *responses: Callable[[], ModelOutput | Awaitable[ModelOutput]],
        cache: bool = False,
        wire: Callable[[list[ChatMessage]], Awaitable[Any]] | None = None,
    ) -> None:
        self.inputs: list[list[ChatMessage]] = []
        self.wire: list[Any] = []

        async def respond(
            input: list[ChatMessage], tools: Any, tool_choice: Any, config: Any
        ) -> ModelOutput:
            self.inputs.append(list(input))
            if wire is not None:
                self.wire.append(await wire(list(input)))
            output = responses[min(len(self.inputs), len(responses)) - 1]()
            return output if isinstance(output, ModelOutput) else await output

        self.model = get_model(
            "mockllm/model",
            config=GenerateConfig(cache=cache),
            custom_outputs=respond,
            memoize=False,
        )


async def _responses_output(*items: Any) -> ModelOutput:
    """A Responses generation of `items`, as the provider parses it."""
    from openai.types.responses import Response

    from inspect_ai.model import model_output_from_openai_responses

    return await model_output_from_openai_responses(
        Response.model_validate(
            {
                "id": "resp_1",
                "created_at": 0,
                "model": "mockllm/model",
                "object": "response",
                "output": list(items),
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            }
        )
    )


def _responses_parsed(item: Any) -> Callable[[], Awaitable[ModelOutput]]:
    """The output of a Responses generation of `item`, parsed when generated."""
    return lambda: _responses_output(item)


async def _responses_wire(input: list[ChatMessage]) -> list[Any]:
    from inspect_ai.model._openai_responses import openai_responses_inputs

    return cast(list[Any], await openai_responses_inputs(input))


def _responses_replayed(wire: list[Any], type: str) -> list[tuple[str, Any]]:
    """Each call of `type` in a serialized request: its id and native arguments."""
    return [
        (param["call_id"], _responses_native_arguments(param))
        for param in wire
        if param["type"] == type
    ]


async def _anthropic_wire(input: list[ChatMessage]) -> list[list[Any]]:
    """Each assistant message in a serialized request, as its blocks."""
    from inspect_ai.model._providers.anthropic import assistant_message_block_params

    return [
        list(await assistant_message_block_params(message))
        for message in input
        if isinstance(message, ChatMessageAssistant)
    ]


def _anthropic_shapes(wire: list[list[Any]]) -> list[list[tuple[str, str | None]]]:
    """Each serialized assistant message's blocks: their types and names."""
    return [[(block["type"], block.get("name")) for block in blocks] for blocks in wire]


ANTHROPIC_TOOLS = [
    ToolInfo(name="bash_session", description="Run a command."),
    ToolInfo(name="read_file", description="Read a file."),
]
# interleaved thinking, then a response reusing `toolu_a` at another position,
# under a name of its own
ANTHROPIC_FIRST: Any = [
    {"type": "thinking", "thinking": "first", "signature": "c2ln"},
    {
        "type": "tool_use",
        "id": "toolu_a",
        "name": "bash",
        "input": {"command": "cat old.txt"},
    },
    {"type": "thinking", "thinking": "second", "signature": "c2lnMg=="},
    {"type": "tool_use", "id": "toolu_b", "name": "read_file", "input": {}},
]
ANTHROPIC_SECOND: Any = [
    {
        "type": "tool_use",
        "id": "toolu_a",
        "name": "read_file",
        "input": {"path": "new.txt"},
    },
    {"type": "thinking", "thinking": "third", "signature": "c2lnMw=="},
]
ANTHROPIC_FIRST_REPLAY = [
    ("thinking", None),
    ("tool_use", "bash"),
    ("thinking", None),
    ("tool_use", "read_file"),
]
# a message can't end with thinking
ANTHROPIC_SECOND_REPLAY = [
    ("tool_use", "read_file"),
    ("thinking", None),
    ("text", None),
]


async def _anthropic_output(
    blocks: Any,
    tools: list[ToolInfo] = ANTHROPIC_TOOLS,
    client: Any = None,
) -> ModelOutput:
    """An Anthropic generation of `blocks`, as the provider parses it.

    With a `client`, the provider counts each thinking block's tokens.
    """
    from anthropic.types import Message

    from inspect_ai.model._providers.anthropic import model_output_from_message

    output, _ = await model_output_from_message(
        client,
        "claude-sonnet-4-5" if client is not None else None,
        Message.model_validate(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-5",
                "content": blocks,
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        ),
        tools,
    )
    return output


def _anthropic_parsed(blocks: Any) -> Callable[[], Awaitable[ModelOutput]]:
    """The output of an Anthropic generation of `blocks`, parsed when generated."""
    return lambda: _anthropic_output(blocks)


def _responses_call_reading(kind: str, path: str, generation: int) -> Any:
    """A native Responses call to `kind` reading `path`, under a reused call id."""
    from openai.types.responses.computer_action import Type

    item, _, _, _ = _responses_modified_call(kind)
    update: dict[str, Any] = {"id": f"{item.id}_{generation}", "call_id": "call_reused"}
    match kind:
        case "custom":
            update["input"] = f"*** Begin Patch\n*** Delete File: {path}\n*** End Patch"
        case "function":
            update["arguments"] = json.dumps({"path": path})
        case "computer":
            update["actions"] = [Type(type="type", text=path)]
        case _:
            update["arguments"] = {"query": path}
    return item.model_copy(update=update)


# a compatible server may leave out a call's item id
RESPONSES_REUSED_CALLS = [
    ("function", True),
    ("custom", True),
    ("computer", True),
    ("tool_search", True),
    ("function", False),
]


def _responses_calls_reading(kind: str, first_item_id: bool) -> list[Any]:
    """Two native Responses calls to `kind` under one call id, reading old then new."""
    first = _responses_call_reading(kind, "old.txt", 1)
    return [
        first if first_item_id else first.model_copy(update={"id": None}),
        _responses_call_reading(kind, "new.txt", 2),
    ]


@pytest.mark.parametrize(("kind", "first_item_id"), RESPONSES_REUSED_CALLS)
async def test_a_reused_responses_call_id_replays_each_call_with_its_own_arguments(
    kind: str, first_item_id: bool
) -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    init_sample_assistant_internal()
    _, tool, result, _ = _responses_modified_call(kind)
    generated = _responses_calls_reading(kind, first_item_id)

    # the model reuses its call id in a second, freshly parsed response
    model = Parsing(
        *[_responses_parsed(item) for item in generated],
        lambda: calls_output(),
        wire=_responses_wire,
    )
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    items: list[Any] = [{"role": "user", "content": TASK}]
    handed_ids: list[str] = []

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_recording([])]),
    ):
        for _ in generated:
            response = await inspect_responses_api_request(
                {"model": "inspect", "input": items, "tools": [tool]},
                None,
                None,
                None,
                bridge,
            )
            handed = [item.model_dump(exclude_none=True) for item in response.output]
            [call] = [item for item in handed if "call_id" in item]
            handed_ids.append(call["call_id"])
            items = [*items, *handed, {**result, "call_id": call["call_id"]}]
        await inspect_responses_api_request(
            {"model": "inspect", "input": items, "tools": [tool]},
            None,
            None,
            None,
            bridge,
        )

    # the reusing call is handed over under a fresh id, and the id's state
    # (the second parse's) is dropped, so each call replays with its own
    # arguments, from itself
    assert handed_ids[0] == "call_reused" != handed_ids[1]
    assert [
        (param["call_id"], _path(param))
        for param in model.wire[2]
        if param["type"] in RESPONSES_CALL_TYPES
    ] == list(zip(handed_ids, ["old.txt", "new.txt"]))


async def _pass_through(
    model: Any, output: ModelOutput, input: GenerateInput
) -> ModelOutput:
    return output


async def _rebuilt(
    model: Any, output: ModelOutput, input: GenerateInput
) -> ModelOutput:
    return ModelOutput.model_validate(output.model_dump())


RESPONSE_FILTERS: dict[str, Any] = {
    "unfiltered": None,
    "pass_through": _pass_through,
    "rebuilt": _rebuilt,
}


@pytest.mark.parametrize(
    ("kind", "first_item_id", "filtered"),
    [
        *[(kind, item_id, "unfiltered") for kind, item_id in RESPONSES_REUSED_CALLS],
        *[(kind, item_id, "pass_through") for kind, item_id in RESPONSES_REUSED_CALLS],
        # an output the filter rebuilt keeps its generation's replay state
        *[(kind, item_id, "rebuilt") for kind, item_id in RESPONSES_REUSED_CALLS],
    ],
)
async def test_a_cached_responses_call_replays_its_own_arguments_after_its_id_is_reused(
    kind: str,
    first_item_id: bool,
    filtered: str,
    isolated_cache: Callable[[], None],
) -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    isolated_cache()
    init_sample_assistant_internal()
    _, tool, result, _ = _responses_modified_call(kind)
    generated = _responses_calls_reading(kind, first_item_id)
    model = Parsing(
        *[_responses_parsed(item) for item in generated],
        lambda: calls_output(),
        cache=True,
        wire=_responses_wire,
    )
    # a response filter returning the output re-validates it
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model.model},
        response_filter=RESPONSE_FILTERS[filtered],
    )
    items: list[Any] = [{"role": "user", "content": TASK}]
    handed: list[dict[str, Any]] = []

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_recording([])]),
    ):
        # the scaffold asks again for the first response after the model reused
        # its call id in another: a cache hit
        for path in ["old.txt", "new.txt", "old.txt"]:
            response = await inspect_responses_api_request(
                {
                    "model": "inspect",
                    "input": [{"role": "user", "content": f"Read {path}."}],
                    "tools": [tool],
                },
                None,
                None,
                None,
                bridge,
            )
            [call] = [
                item.model_dump(exclude_none=True)
                for item in response.output
                if hasattr(item, "call_id")
            ]
            handed.append(call)
            items += [call, {**result, "call_id": call["call_id"]}]
        await inspect_responses_api_request(
            {"model": "inspect", "input": items, "tools": [tool]},
            None,
            None,
            None,
            bridge,
        )

    assert [e.cache for e in transcript().events if isinstance(e, ModelEvent)] == [
        "write",
        "write",
        "read",
        "write",
    ]
    # the reusing call gets a fresh id; the cache hit hands the first call over
    # again under its id
    model_id = generated[0].call_id
    assert [call["call_id"] == model_id for call in handed] == [True, False, True]
    # each call replays with its own arguments (the reused id's state is
    # dropped, so not in its native form)
    assert [
        (param["call_id"], _path(param))
        for param in model.wire[-1]
        if param["type"] in RESPONSES_CALL_TYPES
    ] == [
        (call["call_id"], path)
        for call, path in zip(handed, ["old.txt", "new.txt", "old.txt"])
    ]


async def test_a_responses_call_without_an_item_id_replays_its_own_arguments() -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    init_sample_assistant_internal()
    _, tool, result, _ = _responses_modified_call("function")
    # a compatible server leaves out the item id of a call reusing an id
    generated = [
        _responses_call_reading("function", "old.txt", 1),
        _responses_call_reading("function", "new.txt", 2).model_copy(
            update={"id": None}
        ),
    ]
    model = Parsing(
        *[_responses_parsed(item) for item in generated],
        lambda: calls_output(),
        wire=_responses_wire,
    )
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    items: list[Any] = [{"role": "user", "content": TASK}]

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_recording([])]),
    ):
        for _ in range(3):
            response = await inspect_responses_api_request(
                {"model": "inspect", "input": items, "tools": [tool]},
                None,
                None,
                None,
                bridge,
            )
            handed = [item.model_dump(exclude_none=True) for item in response.output]
            items += [
                *handed,
                *[
                    {**result, "call_id": item["call_id"]}
                    for item in handed
                    if "call_id" in item
                ],
            ]

    assert [
        arguments
        for _, arguments in _responses_replayed(model.wire[2], "function_call")
    ] == [{"path": "old.txt"}, {"path": "new.txt"}]


async def test_a_call_a_response_filter_changed_replays_as_handed() -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal
    from inspect_ai.model._openai_responses import openai_responses_inputs

    init_sample_assistant_internal()
    _, tool, result, _ = _responses_modified_call("function")
    model = Parsing(
        _responses_parsed(_responses_call_reading("function", "old.txt", 1)),
        lambda: calls_output(),
    )

    async def edit(
        model: Any, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput:
        for call in output.message.tool_calls or []:
            call.arguments = {"path": "edited.txt"}
        return output

    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model.model},
        response_filter=edit,
    )
    items: list[Any] = [{"role": "user", "content": TASK}]

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_recording([])]),
    ):
        for _ in range(2):
            response = await inspect_responses_api_request(
                {"model": "inspect", "input": items, "tools": [tool]},
                None,
                None,
                None,
                bridge,
            )
            handed = [item.model_dump(exclude_none=True) for item in response.output]
            items += [
                *handed,
                *[
                    {**result, "call_id": item["call_id"]}
                    for item in handed
                    if "call_id" in item
                ],
            ]

    [call] = [item for item in items if item.get("type") == "function_call"]
    assert call["call_id"] == "call_reused"
    replayed: list[Any] = await openai_responses_inputs(model.inputs[1])
    assert [
        (param["call_id"], json.loads(param["arguments"]), "id" in param)
        for param in replayed
        if param["type"] == "function_call"
    ] == [(call["call_id"], {"path": "edited.txt"}, False)]


RESPONSES_RESULT_TYPES = {
    "function_call": "function_call_output",
    "custom_tool_call": "custom_tool_call_output",
    "computer_call": "computer_call_output",
    "tool_search_call": "tool_search_output",
}


def _editing(arguments: Callable[[ToolCall], dict[str, Any]], rebuild: bool) -> Any:
    """A response filter giving each call `arguments(call)`, optionally rebuilding."""

    async def edit(
        model: Any, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput:
        for call in output.message.tool_calls or []:
            call.arguments = arguments(call)
        return ModelOutput.model_validate(output.model_dump()) if rebuild else output

    return edit


@pytest.mark.parametrize("filtered", ["rebuilt", "edited", "edited_rebuilt"])
@pytest.mark.parametrize("kind", ["function", "custom", "computer", "tool_search"])
async def test_a_call_a_response_filter_returned_continues_in_its_native_form(
    kind: str, filtered: str
) -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request

    init_sample_assistant_internal()
    item, tool, result, approved = _responses_modified_call(kind)
    model = Parsing(
        _responses_parsed(item), lambda: calls_output(), wire=_responses_wire
    )
    response_filter = (
        _rebuilt
        if filtered == "rebuilt"
        else _editing(lambda call: approved, rebuild=filtered == "edited_rebuilt")
    )
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model.model},
        response_filter=response_filter,
    )
    items: list[Any] = [{"role": "user", "content": TASK}]

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_recording([])]),
    ):
        for _ in range(2):
            response = await inspect_responses_api_request(
                {"model": "inspect", "input": items, "tools": [tool]},
                None,
                None,
                None,
                bridge,
            )
            handed = [item.model_dump(exclude_none=True) for item in response.output]
            items += [
                *handed,
                *[
                    {**result, "call_id": item["call_id"]}
                    for item in handed
                    if "call_id" in item
                ],
            ]

    [call] = [param for param in items if param.get("type") == item.type]
    replayed = model.wire[1]
    # the call and its result, each as the native item of the call's type (a
    # function call's output can't hold a screenshot, which follows it)
    assert [
        (param["type"], param["call_id"]) for param in replayed if "call_id" in param
    ] == [
        (item.type, call["call_id"]),
        (RESPONSES_RESULT_TYPES[item.type], call["call_id"]),
    ]
    assert _responses_replayed(replayed, item.type) == [
        (call["call_id"], _responses_native_arguments(call))
    ]
    if filtered == "rebuilt":
        assert _responses_native_arguments(call) == _responses_native_arguments(
            item.model_dump(exclude_none=True)
        )
    else:
        # an edited call replays as edited, under the model's id and without
        # the generated item's id
        assert call["call_id"] == item.call_id
        assert _responses_native_arguments(call) != _responses_native_arguments(
            item.model_dump(exclude_none=True)
        )
        assert item.id not in [param.get("id") for param in replayed]


@pytest.mark.parametrize("filtered", ["rebuilt", "edited", "edited_rebuilt"])
async def test_an_anthropic_turn_a_response_filter_returned_continues_as_generated(
    filtered: str,
) -> None:
    model = Parsing(
        _anthropic_parsed(ANTHROPIC_FIRST),
        lambda: calls_output(),
        wire=_anthropic_wire,
    )
    bridge = in_process_bridge([])
    bridge.response_filter = (
        _rebuilt
        if filtered == "rebuilt"
        else _editing(
            lambda call: {**call.arguments, "edited": True},
            rebuild=filtered == "edited_rebuilt",
        )
    )
    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active([bridge_recording([])]):
        for _ in range(2):
            output, _ = await bridge_generate(
                bridge,
                model.model,
                list(messages),
                list(ANTHROPIC_TOOLS),
                None,
                GenerateConfig(),
                requested_model=None,
            )
            messages = _answered(messages, output)

    [replayed] = model.wire[1]
    assert _anthropic_shapes([replayed]) == [ANTHROPIC_FIRST_REPLAY]
    handed = messages[1]
    assert isinstance(handed, ChatMessageAssistant)
    assert [
        (block["id"], block["input"])
        for block in replayed
        if block["type"] == "tool_use"
    ] == [(call.id, call.arguments) for call in handed.tool_calls or []]


@pytest.mark.parametrize("filtered", list(RESPONSE_FILTERS))
@pytest.mark.parametrize(
    "kind", ["function", "function_pair", "custom", "computer", "tool_search"]
)
async def test_parallel_responses_calls_sharing_an_id_continue_with_their_own_arguments(
    kind: str, filtered: str
) -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request

    init_sample_assistant_internal()
    pair = kind == "function_pair"
    _, tool, result, _ = _responses_modified_call("function" if pair else kind)
    generated = _responses_calls_reading("function" if pair else kind, True)
    tools = [tool]
    if pair:
        # calls to different functions
        generated[1] = generated[1].model_copy(update={"name": "list_files"})
        tools.append({**tool, "name": "list_files"})
    model = Parsing(
        lambda: _responses_output(*generated),
        lambda: calls_output(),
        wire=_responses_wire,
    )
    bridge = AgentBridge(
        AgentState(messages=[]),
        model_aliases={"inspect": model.model},
        response_filter=RESPONSE_FILTERS[filtered],
    )
    items: list[Any] = [{"role": "user", "content": TASK}]

    with (
        patch(
            "inspect_ai.agent._bridge.responses_impl._is_openai_responses_provider",
            return_value=True,
        ),
        active([bridge_recording([])]),
    ):
        for _ in range(2):
            response = await inspect_responses_api_request(
                {"model": "inspect", "input": items, "tools": tools},
                None,
                None,
                None,
                bridge,
            )
            handed = [item.model_dump(exclude_none=True) for item in response.output]
            items += [
                *handed,
                *[
                    {**result, "call_id": item["call_id"]}
                    for item in handed
                    if "call_id" in item
                ],
            ]

    calls = [param for param in items if param.get("type") == generated[0].type]
    expected = [
        _responses_native_arguments(item.model_dump(exclude_none=True))
        for item in generated
    ]
    # the scaffold runs each call as generated, under the id they share
    assert [_responses_native_arguments(call) for call in calls] == expected
    assert {call["call_id"] for call in calls} == {"call_reused"}
    # the continuation replays each call with its own arguments, and no other
    # call's item (replay in the native form is not guaranteed)
    replayed = [
        param for param in model.wire[1] if param["type"] in RESPONSES_CALL_TYPES
    ]
    assert [(param["call_id"], _path(param)) for param in replayed] == [
        (call["call_id"], path) for call, path in zip(calls, ["old.txt", "new.txt"])
    ]
    assert all(
        param.get("id") in (None, param["call_id"])
        or param["id"].endswith(("_1", "_2")[i])
        for i, param in enumerate(replayed)
    ), replayed


@protocol
def bridge_reject_nth(nth: int | None) -> Protocol:
    """Rejects the `nth` call it sees, or every call."""
    seen: list[ToolCall] = []

    async def decide(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        seen.append(step.call)
        if nth is None or len(seen) == nth:
            return Decision.reject("risky", message="Denied.")
        return None

    return decide


@approver(name="bridge_reject_nth")
def rejecting_approver(nth: int | None) -> Approver:
    """Rejects the `nth` call it sees, or every call."""
    seen: list[ToolCall] = []

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        seen.append(call)
        if nth is None or len(seen) == nth:
            return Approval(decision="reject", explanation="Denied.")
        return Approval(decision="approve")

    return approve


def _keeping(kept: str, rebuild: bool, edited: dict[str, Any]) -> Any:
    """A response filter keeping two calls, the first, the last, or both reversed.

    `edited` keeps both, giving the first those arguments.
    """

    async def keep(
        model: Any, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput:
        calls = output.message.tool_calls or []
        if kept == "edited" and calls:
            calls[0].arguments = edited
        output.message.tool_calls = {
            "both": calls,
            "edited": calls,
            "first": calls[:1],
            "last": calls[-1:],
            "reversed": calls[::-1],
        }[kept]
        return ModelOutput.model_validate(output.model_dump()) if rebuild else output

    return keep


# what a Responses call of each kind carries natively once a filter gives it
# `_responses_modified_call`'s approved arguments
RESPONSES_EDITED_NATIVE: dict[str, Any] = {
    "function": {"path": "safe.txt"},
    "custom": "*** Begin Patch\n*** End Patch",
    "computer": [{"type": "wait"}],
    "tool_search": {"query": "approved tools"},
}
ANTHROPIC_EDITED = {"command": "edited"}


@pytest.mark.parametrize("rejecter", ["sentinel", "approval"])
@pytest.mark.parametrize(
    ("kept", "filtered"),
    [
        ("both", "unfiltered"),
        *[
            (kept, filtered)
            for kept in ["both", "first", "last", "reversed", "edited"]
            for filtered in ["in_place", "rebuilt"]
        ],
    ],
)
@pytest.mark.parametrize(
    "kind", ["function", "custom", "computer", "tool_search", "anthropic"]
)
async def test_a_rejected_turn_replays_each_call_as_generated(
    kind: str, kept: str, filtered: str, rejecter: str
) -> None:
    from contextlib import nullcontext

    init_sample_assistant_internal()
    generated: list[Any] = []
    if kind == "anthropic":
        model = Parsing(
            _anthropic_parsed(ANTHROPIC_FIRST),
            lambda: calls_output(),
            wire=_anthropic_wire,
        )
        tools = list(ANTHROPIC_TOOLS)
    else:
        generated = _responses_calls_reading(kind, True)
        generated[1] = generated[1].model_copy(update={"call_id": "call_distinct"})
        model = Parsing(
            lambda: _responses_output(*generated),
            lambda: calls_output(),
            wire=_responses_wire,
        )
        tools = [ToolInfo(name="read_file", description="Read a file.")]
    edited = (
        ANTHROPIC_EDITED if kind == "anthropic" else _responses_modified_call(kind)[3]
    )
    bridge = in_process_bridge([])
    if filtered != "unfiltered":
        bridge.response_filter = _keeping(kept, filtered == "rebuilt", edited)
    # the indices of the generated calls the filter keeps; the last is rejected
    indices = {"first": [0], "last": [1], "reversed": [1, 0]}.get(kept, [0, 1])
    if rejecter == "approval":
        bridge.approval = [ApprovalPolicy(rejecting_approver(len(indices)), "*")]

    with (
        active([bridge_reject_nth(len(indices))])
        if rejecter == "sentinel"
        else (nullcontext())
    ):
        await bridge_generate(
            bridge,
            model.model,
            [ChatMessageUser(content=TASK)],
            tools,
            None,
            GenerateConfig(),
            requested_model=None,
        )

    # the retry replays the rejected turn, each call with its own result
    [rejected] = [m for m in model.inputs[1] if isinstance(m, ChatMessageAssistant)]
    results = [m for m in model.inputs[1] if isinstance(m, ChatMessageTool)]
    ids = [call.id for call in rejected.tool_calls or []]
    assert len(set(ids)) == len(indices)
    assert [result.tool_call_id for result in results] == ids
    # only the rejected call carries the rejection
    explanations = [result.error.message if result.error else "" for result in results]
    assert [
        explanation.startswith("This tool call was not executed")
        for explanation in explanations
    ] == [True] * (len(indices) - 1) + [False]
    assert explanations[-1].startswith("Denied.")
    if kind == "anthropic":
        [replayed] = model.wire[1]
        removed = {("tool_use", ["bash", "read_file"][i]) for i in (0, 1)} - {
            ("tool_use", ["bash", "read_file"][i]) for i in indices
        }
        expected = [shape for shape in ANTHROPIC_FIRST_REPLAY if shape not in removed]
        if expected[-1][0] == "thinking":
            # a message can't end with thinking
            expected.append(("text", None))
        assert _anthropic_shapes([replayed]) == [expected]
        # in their generated positions, whatever the filter's order
        assert {
            block["id"]: block["input"]
            for block in replayed
            if block["type"] == "tool_use"
        } == {
            call_id: ANTHROPIC_EDITED
            if kept == "edited" and i == 0
            else ANTHROPIC_FIRST[[1, 3][i]]["input"]
            for call_id, i in zip(ids, indices)
        }
    else:
        replayed = model.wire[1]
        assert _responses_replayed(replayed, generated[0].type) == [
            (
                call_id,
                RESPONSES_EDITED_NATIVE[kind]
                if kept == "edited" and i == 0
                else _responses_native_arguments(
                    generated[i].model_dump(exclude_none=True)
                ),
            )
            for call_id, i in zip(ids, indices)
        ]
        assert [
            param["call_id"]
            for param in replayed
            if param["type"] == RESPONSES_RESULT_TYPES[generated[0].type]
        ] == ids


@pytest.mark.parametrize("distinct", [False, True])
@pytest.mark.parametrize("rejecter", ["sentinel", "approval"])
@pytest.mark.parametrize("filtered", ["unfiltered", "in_place", "rebuilt"])
@pytest.mark.parametrize(
    "kind", ["function", "custom", "computer", "tool_search", "anthropic"]
)
async def test_a_rejected_turn_keeps_its_own_state_after_a_later_rejection_reuses_its_id(
    kind: str, filtered: str, rejecter: str, distinct: bool
) -> None:
    """A second generation reuses the id of the first's rejected call, and is rejected too.

    With distinct ids both turns replay as generated. With the reused id the
    second call gets a fresh id, and the state recorded under the id (the
    second call's) is dropped, so each call replays from itself.
    """
    from contextlib import nullcontext

    init_sample_assistant_internal()
    # the first generation's last call, kept (alone, when filtered) and rejected;
    # then a second generation reusing its id, also rejected
    first: Any
    second: Any
    if kind == "anthropic":
        first, second = deepcopy(ANTHROPIC_FIRST), deepcopy(ANTHROPIC_SECOND)
        if distinct:
            second[0]["id"] = "toolu_distinct"
        elif filtered != "unfiltered":
            # the id of the call the filter keeps
            second[0]["id"] = first[3]["id"]
        model = Parsing(
            _anthropic_parsed(first),
            _anthropic_parsed(second),
            lambda: calls_output(),
            wire=_anthropic_wire,
        )
        tools = list(ANTHROPIC_TOOLS)
    else:
        first = [_responses_call_reading(kind, "old.txt", 1)]
        if filtered != "unfiltered":
            first.insert(
                0,
                _responses_call_reading(kind, "removed.txt", 0).model_copy(
                    update={"call_id": "call_removed"}
                ),
            )
        second = _responses_call_reading(kind, "new.txt", 2)
        if distinct:
            second = second.model_copy(update={"call_id": "call_distinct"})
        model = Parsing(
            lambda: _responses_output(*first),
            lambda: _responses_output(second),
            lambda: calls_output(),
            wire=_responses_wire,
        )
        tools = [ToolInfo(name="read_file", description="Read a file.")]
    bridge = in_process_bridge([])
    if filtered != "unfiltered":
        bridge.response_filter = _keeping("last", filtered == "rebuilt", {})
    if rejecter == "approval":
        bridge.approval = [ApprovalPolicy(rejecting_approver(None), "*")]

    with (
        active([bridge_reject_nth(None)]) if rejecter == "sentinel" else (nullcontext())
    ):
        await bridge_generate(
            bridge,
            model.model,
            [ChatMessageUser(content=TASK)],
            tools,
            None,
            GenerateConfig(),
            requested_model=None,
        )

    assert len(model.wire) == 3
    rejected = [m for m in model.inputs[2] if isinstance(m, ChatMessageAssistant)]
    calls = [call for message in rejected for call in message.tool_calls or []]
    results = [m for m in model.inputs[2] if isinstance(m, ChatMessageTool)]
    assert [result.tool_call_id for result in results] == [call.id for call in calls]
    assert len({call.id for call in calls}) == len(calls)
    # the first turn keeps the model's ids
    first_id = first[-1]["id"] if kind == "anthropic" else first[-1].call_id
    assert first_id in {call.id for call in rejected[0].tool_calls or []}
    if kind == "anthropic":
        assert [
            (block["id"], block["input"])
            for blocks in model.wire[2]
            for block in blocks
            if block["type"] == "tool_use"
        ] == [(call.id, call.arguments) for call in calls]
    else:
        # each call replays with its own arguments
        assert [
            (param["call_id"], _path(param))
            for param in model.wire[2]
            if param["type"] in RESPONSES_CALL_TYPES
        ] == [(call.id, _path(call.arguments)) for call in calls]
    if not distinct:
        return
    # the third request replays the first rejected turn as the second did
    assert model.wire[2][: len(model.wire[1])] == model.wire[1]
    if kind == "anthropic":
        kept = (
            ANTHROPIC_FIRST_REPLAY
            if filtered == "unfiltered"
            else [("thinking", None), ("thinking", None), ("tool_use", "read_file")]
        )
        assert _anthropic_shapes(model.wire[2]) == [kept, ANTHROPIC_SECOND_REPLAY]
    else:
        assert _responses_replayed(model.wire[2], first[0].type) == [
            (call.id, _responses_native_arguments(item.model_dump(exclude_none=True)))
            for call, item in zip(calls, [first[-1], second])
        ]


GOOGLE_SIGNATURE = b"old-call-signature"
RESPONSES_KINDS = ["function", "custom", "computer", "tool_search"]
RESPONSES_CALL_TYPES = {
    "function_call",
    "custom_tool_call",
    "computer_call",
    "tool_search_call",
}


def _calls_reading_old_then_new(
    dialect: str, shared: bool
) -> tuple[Callable[[], Any], list[ToolInfo], Callable[[list[ChatMessage]], Any]]:
    """A generation of two parallel calls reading old.txt then new.txt.

    Under one call id when `shared`. Returns the generation (parsed as its
    provider parses it), the tools, and a serializer giving each replayed call
    of each assistant message as `(id, path, state)`: the path the call reads,
    and the provider state replayed with it (a Responses item id, an Anthropic
    internal name, a Google thought signature).
    """
    if dialect == "completions":
        from inspect_ai.model._openai import openai_chat_message

        second = "call_reused" if shared else "call_distinct"

        def completions() -> ModelOutput:
            return calls_output(
                ToolCall(
                    id="call_reused",
                    function="read_file",
                    arguments={"path": "old.txt"},
                ),
                ToolCall(
                    id=second, function="read_file", arguments={"path": "new.txt"}
                ),
            )

        async def completions_wire(input: list[ChatMessage]) -> Any:
            replayed = []
            for message in input:
                if isinstance(message, ChatMessageAssistant):
                    param: Any = await openai_chat_message(message)
                    replayed.append(
                        [
                            (call["id"], _path(call), None)
                            for call in param.get("tool_calls", [])
                        ]
                    )
            return replayed

        return (
            completions,
            [ToolInfo(name="read_file", description="Read.")],
            completions_wire,
        )
    elif dialect == "anthropic":
        blocks: Any = [
            {"type": "thinking", "thinking": "first", "signature": "c2ln"},
            {
                "type": "tool_use",
                "id": "toolu_a",
                "name": "bash",
                "input": {"command": "cat old.txt"},
            },
            {"type": "thinking", "thinking": "second", "signature": "c2lnMg=="},
            {
                "type": "tool_use",
                "id": "toolu_a" if shared else "toolu_b",
                "name": "read_file",
                "input": {"path": "new.txt"},
            },
        ]

        async def anthropic_wire(input: list[ChatMessage]) -> Any:
            return [
                [
                    (block["id"], _path(block["input"]), block["name"])
                    for block in blocks
                    if block["type"] == "tool_use"
                ]
                for blocks in await _anthropic_wire(input)
            ]

        return _anthropic_parsed(blocks), list(ANTHROPIC_TOOLS), anthropic_wire
    elif dialect == "google":
        from google.genai.types import (
            Candidate,
            Content,
            FinishReason,
            FunctionCall,
            Part,
        )

        from inspect_ai.model._providers.google import (
            completion_choice_from_candidate,
        )
        from inspect_ai.model._providers.google import content as google_content

        def google() -> ModelOutput:
            choice = completion_choice_from_candidate(
                "gemini-3-flash-preview",
                Candidate(
                    content=Content(
                        role="model",
                        parts=[
                            Part(
                                function_call=FunctionCall(
                                    id="shared",
                                    name="read_file",
                                    args={"path": "old.txt"},
                                ),
                                thought_signature=GOOGLE_SIGNATURE,
                            ),
                            Part(
                                function_call=FunctionCall(
                                    id="shared" if shared else "distinct",
                                    name="read_file",
                                    args={"path": "new.txt"},
                                )
                            ),
                        ],
                    ),
                    finish_reason=FinishReason.STOP,
                ),
            )
            return ModelOutput(model="mockllm/model", choices=[choice])

        async def google_wire(input: list[ChatMessage]) -> Any:
            replayed = []
            for message in input:
                if isinstance(message, ChatMessageAssistant):
                    parts = (await google_content(AsyncMock(), message)).parts or []
                    replayed.append(
                        [
                            (
                                part.function_call.id,
                                _path(part.function_call.args),
                                part.thought_signature,
                            )
                            for part in parts
                            if part.function_call is not None
                        ]
                    )
            return replayed

        return google, [ToolInfo(name="read_file", description="Read.")], google_wire
    else:
        generated = _responses_calls_reading(dialect, True)
        if not shared:
            generated[1] = generated[1].model_copy(update={"call_id": "call_distinct"})

        async def responses_wire(input: list[ChatMessage]) -> Any:
            # one request's items; split into the assistant turns they replay
            replayed: list[list[Any]] = []
            for message in input:
                if isinstance(message, ChatMessageAssistant):
                    items = await _responses_wire([message])
                    replayed.append(
                        [
                            (item["call_id"], _path(item), item.get("id"))
                            for item in items
                            if item.get("type") in RESPONSES_CALL_TYPES
                        ]
                    )
            return replayed

        return (
            lambda: _responses_output(*generated),
            [ToolInfo(name="read_file", description="Read a file.")],
            responses_wire,
        )


def _path(value: Any) -> str | None:
    """Which of old.txt and new.txt a call carries, or None for both or neither."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    paths = [path for path in ("old.txt", "new.txt") if path in text]
    return paths[0] if len(paths) == 1 else None


def _own_state(dialect: str, path: str, state: Any, shared: bool) -> bool:
    """Whether `state` is the replay state of the call reading `path`, or none.

    For calls sharing an id, replay state is dropped rather than risk another
    call's; Google's thought signature is the one state that is checked as
    dropped, since it is the state a removed or reordered sibling could donate.
    """
    old = path == "old.txt"
    match dialect:
        case "completions":
            return state is None
        case "anthropic":
            names = {"bash", "bash_session"} if old else {"read_file"}
            return (
                state in names if shared else state == ("bash" if old else "read_file")
            )
        case "google":
            return state == (GOOGLE_SIGNATURE if old and not shared else None)
        case _:
            # a native item under the model's id names the generated item
            return state is None or str(state).endswith("_1" if old else "_2")


@pytest.mark.parametrize(
    "outcome", ["accepted", "sentinel_rejected", "approval_rejected"]
)
@pytest.mark.parametrize(
    ("kept", "rebuilt"),
    [
        ("unfiltered", False),
        *[
            (kept, rebuilt)
            for kept in ["first", "last", "reversed"]
            for rebuilt in [False, True]
        ],
    ],
)
@pytest.mark.parametrize("shared", [True, False])
@pytest.mark.parametrize(
    "dialect", ["completions", *RESPONSES_KINDS, "anthropic", "google"]
)
async def test_parallel_calls_never_replay_another_calls_state(
    dialect: str, shared: bool, kept: str, rebuilt: bool, outcome: str
) -> None:
    from contextlib import AbstractContextManager, nullcontext

    init_sample_assistant_internal()
    generation, tools, wire = _calls_reading_old_then_new(dialect, shared)
    model = Parsing(generation, lambda: calls_output(), wire=wire)
    bridge = in_process_bridge([])
    if kept != "unfiltered":
        bridge.response_filter = _keeping(kept, rebuilt, {})
    if outcome == "approval_rejected":
        bridge.approval = [ApprovalPolicy(rejecting_approver(None), "*")]
    sentinel: AbstractContextManager[None] = (
        nullcontext()
        if outcome == "approval_rejected"
        else active(
            [
                bridge_reject_nth(None)
                if outcome == "sentinel_rejected"
                else bridge_recording([])
            ]
        )
    )

    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    with sentinel:
        output, _ = await bridge_generate(
            bridge,
            model.model,
            list(messages),
            tools,
            None,
            GenerateConfig(),
            requested_model=None,
        )
        if outcome == "accepted":
            messages = _answered(messages, output)
            await bridge_generate(
                bridge,
                model.model,
                list(messages),
                tools,
                None,
                GenerateConfig(),
                requested_model=None,
            )

    # the next request replays the turn: each call once, under the model's id
    # (calls sharing one keep it, as on main), answered by its own result
    [turn] = [m for m in model.inputs[1] if isinstance(m, ChatMessageAssistant)]
    calls = turn.tool_calls or []
    results = [m for m in model.inputs[1] if isinstance(m, ChatMessageTool)]
    assert [result.tool_call_id for result in results] == [call.id for call in calls]
    expected = {
        "first": ["old.txt"],
        "last": ["new.txt"],
        "reversed": ["new.txt", "old.txt"],
    }.get(kept, ["old.txt", "new.txt"])
    assert [_path(call.arguments) for call in calls] == expected
    assert len({call.id for call in calls}) == (1 if shared else len(calls))
    # in its generated position (Anthropic, Google) or in call order, with its
    # own arguments and provider state, or with none
    [replayed] = model.wire[1]
    assert sorted((call_id, path) for call_id, path, _ in replayed) == sorted(
        (call.id, _path(call.arguments)) for call in calls
    )
    assert all(
        _own_state(dialect, path, state, shared) for _, path, state in replayed
    ), replayed


@pytest.mark.parametrize("anchors", ["kept", "signed", "none"])
@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("rebuilt", [False, True])
@pytest.mark.parametrize("kept", ["first", "last"])
@pytest.mark.parametrize(
    ("shared", "outcome"),
    [
        *[
            (shared, outcome)
            for shared in [True, False]
            for outcome in ["accepted", "sentinel_rejected", "approval_rejected"]
        ],
        # without a sentinel, accepted calls sharing an id replay by id, as on main
        (False, "unchecked"),
    ],
)
async def test_a_google_anchor_naming_no_returned_call_signs_no_call(
    shared: bool, outcome: str, kept: str, rebuilt: bool, renamed: bool, anchors: str
) -> None:
    """A filter keeps one call, maybe renaming it, and some or none of the anchors.

    An anchor whose call the filter removed or renamed names no returned call;
    its signature must not go on the call that is left. The kept call keeps its
    own signature only when it keeps its id and anchor and no other call shared
    that id.
    """
    from contextlib import AbstractContextManager, nullcontext

    init_sample_assistant_internal()
    generation, tools, wire = _calls_reading_old_then_new("google", shared)
    model = Parsing(generation, lambda: calls_output(), wire=wire)
    bridge = in_process_bridge([])

    async def keep_one(
        model: Any, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput:
        calls = output.message.tool_calls or []
        if not calls or isinstance(output.message.content, str):
            return output
        output.message.tool_calls = calls[:1] if kept == "first" else calls[-1:]
        if renamed:
            output.message.tool_calls[0].id = "filter_id"
        if anchors == "signed":
            output.message.content = [
                part
                for part in output.message.content
                if isinstance(part, ContentReasoning) and part.reasoning
            ]
        elif anchors == "none":
            output.message.content = []
        return ModelOutput.model_validate(output.model_dump()) if rebuilt else output

    bridge.response_filter = keep_one
    if outcome == "approval_rejected":
        bridge.approval = [ApprovalPolicy(rejecting_approver(None), "*")]
    sentinel: AbstractContextManager[None] = (
        nullcontext()
        if outcome in ("approval_rejected", "unchecked")
        else active(
            [
                bridge_reject_nth(None)
                if outcome == "sentinel_rejected"
                else bridge_recording([])
            ]
        )
    )

    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    with sentinel:
        output, _ = await bridge_generate(
            bridge,
            model.model,
            list(messages),
            tools,
            None,
            GenerateConfig(),
            requested_model=None,
        )
        if outcome in ("accepted", "unchecked"):
            await bridge_generate(
                bridge,
                model.model,
                _answered(messages, output),
                tools,
                None,
                GenerateConfig(),
                requested_model=None,
            )

    [replayed] = model.wire[1]
    path = "old.txt" if kept == "first" else "new.txt"
    own = kept == "first" and not shared and not renamed and anchors != "none"
    assert [(call[1], call[2]) for call in replayed] == [
        (path, GOOGLE_SIGNATURE if own else None)
    ]


@pytest.mark.parametrize(
    "outcome", ["accepted", "sentinel_rejected", "approval_rejected"]
)
@pytest.mark.parametrize("rebuilt", [False, True])
@pytest.mark.parametrize(
    "replay",
    [
        "current",
        # an earlier Responses parse recorded the id
        "id_parsed_before",
        "cached",
        "request_filter",
    ],
)
async def test_a_call_kept_from_calls_sharing_an_id_replays_unsigned(
    replay: str, rebuilt: bool, outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filter keeps the last of two calls sharing an id, and the signed anchor.

    The kept call names the signed anchor's id, but that id was shared in the
    output the filter received, so the signature is the removed call's as much
    as the kept one's. The kept call replays without it.
    """
    from contextlib import AbstractContextManager, nullcontext

    init_sample_assistant_internal()
    generation, tools, wire = _calls_reading_old_then_new("google", True)
    if replay == "id_parsed_before":
        await _responses_output(
            {
                "type": "function_call",
                "id": "fc_prior",
                "call_id": "shared",
                "name": "read_file",
                "arguments": '{"path": "prior.txt"}',
            }
        )
    generated = replay in ("current", "id_parsed_before")
    model = Parsing(
        *([generation] if generated else []),
        lambda: calls_output(),
        cache=replay.startswith("cached"),
        wire=wire,
    )
    if replay.startswith("cached"):
        entries = [ModelOutput.model_validate(generation().model_dump())]
        monkeypatch.setattr(
            "inspect_ai.model._model.cache_fetch",
            lambda entry: entries.pop() if entries else None,
        )
    bridge = in_process_bridge([])
    if replay == "request_filter":
        substitutes = [generation()]

        async def substitute(*args: Any) -> ModelOutput | None:
            return substitutes.pop() if substitutes else None

        bridge.filter = substitute

    async def keep_last(
        model: Any, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput:
        if not output.message.tool_calls or isinstance(output.message.content, str):
            return output
        output.message.tool_calls = output.message.tool_calls[-1:]
        output.message.content = [
            part
            for part in output.message.content
            if isinstance(part, ContentReasoning) and part.reasoning
        ]
        return ModelOutput.model_validate(output.model_dump()) if rebuilt else output

    bridge.response_filter = keep_last
    if outcome == "approval_rejected":
        bridge.approval = [ApprovalPolicy(rejecting_approver(None), "*")]
    sentinel: AbstractContextManager[None] = (
        nullcontext()
        if outcome == "approval_rejected"
        else active(
            [
                bridge_reject_nth(None)
                if outcome == "sentinel_rejected"
                else bridge_recording([])
            ]
        )
    )

    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    with sentinel:
        output, _ = await bridge_generate(
            bridge,
            model.model,
            list(messages),
            tools,
            None,
            GenerateConfig(),
            requested_model=None,
        )
        if outcome == "accepted":
            await bridge_generate(
                bridge,
                model.model,
                _answered(messages, output),
                tools,
                None,
                GenerateConfig(),
                requested_model=None,
            )

    [replayed] = model.wire[1 if generated else 0]
    assert [(call[1], call[2]) for call in replayed] == [("new.txt", None)]


@pytest.mark.parametrize("renamed", [False, True])
@pytest.mark.parametrize("rebuilt", [False, True])
@pytest.mark.parametrize("removed", ["nothing", "call_anchors", "signed_text"])
@pytest.mark.parametrize("replay", ["current", "request_filter"])
@pytest.mark.parametrize(
    ("shared", "outcome"),
    [
        *[
            (shared, outcome)
            for shared in [True, False]
            for outcome in ["accepted", "sentinel_rejected", "approval_rejected"]
        ],
        # without a sentinel, accepted calls sharing an id replay by id, as on main
        (False, "unchecked"),
    ],
)
async def test_a_signed_text_parts_signature_goes_on_no_call(
    shared: bool,
    outcome: str,
    replay: str,
    removed: str,
    rebuilt: bool,
    renamed: bool,
) -> None:
    """A filter keeps the last of two calls after a signed text part.

    It may rename the call, and remove every call anchor or the signed text
    while keeping the text's signature. Whatever is left, the text's signature
    goes only on the text, and the kept call, whose own anchor is unsigned,
    replays without a signature. Without anchors, the serializer would take
    the message for a legacy one and put the pending signature on the call.
    """
    from contextlib import AbstractContextManager, nullcontext

    from google.genai.types import (
        Candidate,
        Content,
        FinishReason,
        FunctionCall,
        Part,
    )

    from inspect_ai.model._providers.google import completion_choice_from_candidate
    from inspect_ai.model._providers.google import content as google_content

    init_sample_assistant_internal()
    _, tools, _ = _calls_reading_old_then_new("google", shared)

    def generation() -> ModelOutput:
        choice = completion_choice_from_candidate(
            "gemini-3-flash-preview",
            Candidate(
                content=Content(
                    role="model",
                    parts=[
                        Part(text="Reading both.", thought_signature=b"text-signature"),
                        *[
                            Part(
                                function_call=FunctionCall(
                                    id=call_id, name="read_file", args={"path": path}
                                ),
                                thought_signature=signature,
                            )
                            for call_id, path, signature in [
                                ("shared", "old.txt", GOOGLE_SIGNATURE),
                                ("shared" if shared else "distinct", "new.txt", None),
                            ]
                        ],
                    ],
                ),
                finish_reason=FinishReason.STOP,
            ),
        )
        return ModelOutput(model="mockllm/model", choices=[choice])

    async def wire(input: list[ChatMessage]) -> Any:
        return [
            [
                (part.text, None, part.thought_signature)
                if part.function_call is None
                else (None, _path(part.function_call.args), part.thought_signature)
                for part in (await google_content(AsyncMock(), message)).parts or []
            ]
            for message in input
            if isinstance(message, ChatMessageAssistant)
        ]

    generated = replay == "current"
    model = Parsing(
        *([generation] if generated else []), lambda: calls_output(), wire=wire
    )
    bridge = in_process_bridge([])
    if replay == "request_filter":
        substitutes = [generation()]

        async def substitute(*args: Any) -> ModelOutput | None:
            return substitutes.pop() if substitutes else None

        bridge.filter = substitute

    async def keep_last(
        model: Any, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput:
        calls = output.message.tool_calls or []
        if not calls or isinstance(output.message.content, str):
            return output
        output.message.tool_calls = calls[-1:]
        if renamed:
            output.message.tool_calls[0].id = "filter_id"
        if removed == "call_anchors":
            output.message.content = [
                part
                for part in output.message.content
                if not (
                    isinstance(part, ContentReasoning)
                    and isinstance(part.internal, dict)
                    and "gemini_function_call_id" in part.internal
                )
            ]
        elif removed == "signed_text":
            output.message.content = [
                part
                for part in output.message.content
                if not isinstance(part, ContentText)
            ]
        return ModelOutput.model_validate(output.model_dump()) if rebuilt else output

    bridge.response_filter = keep_last
    if outcome == "approval_rejected":
        bridge.approval = [ApprovalPolicy(rejecting_approver(None), "*")]
    sentinel: AbstractContextManager[None] = (
        nullcontext()
        if outcome in ("approval_rejected", "unchecked")
        else active(
            [
                bridge_reject_nth(None)
                if outcome == "sentinel_rejected"
                else bridge_recording([])
            ]
        )
    )

    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    with sentinel:
        output, _ = await bridge_generate(
            bridge,
            model.model,
            list(messages),
            tools,
            None,
            GenerateConfig(),
            requested_model=None,
        )
        if outcome in ("accepted", "unchecked"):
            await bridge_generate(
                bridge,
                model.model,
                _answered(messages, output),
                tools,
                None,
                GenerateConfig(),
                requested_model=None,
            )

    [replayed] = model.wire[1 if generated else 0]
    text = (
        [] if removed == "signed_text" else [("Reading both.", None, b"text-signature")]
    )
    assert replayed == [*text, (None, "new.txt", None)]


@pytest.mark.parametrize("rebuilt", [False, True])
@pytest.mark.parametrize(
    "outcome", ["accepted", "sentinel_rejected", "approval_rejected", "unchecked"]
)
async def test_a_trailing_signature_goes_on_no_renamed_call(
    outcome: str, rebuilt: bool
) -> None:
    """A filter renames the second of two calls and drops an empty signed text.

    Gemini can end a response with an empty text part carrying a signature.
    With the text removed, its signature is still pending at the end of the
    content, where the serializer would give it to the renamed call, which no
    anchor names, though the first call keeps its anchor.
    """
    from contextlib import AbstractContextManager, nullcontext

    from google.genai.types import (
        Candidate,
        Content,
        FinishReason,
        FunctionCall,
        Part,
    )

    from inspect_ai.model._providers.google import completion_choice_from_candidate

    init_sample_assistant_internal()
    _, tools, wire = _calls_reading_old_then_new("google", False)

    def generation() -> ModelOutput:
        choice = completion_choice_from_candidate(
            "gemini-3-flash-preview",
            Candidate(
                content=Content(
                    role="model",
                    parts=[
                        *[
                            Part(
                                function_call=FunctionCall(
                                    id=call_id, name="read_file", args={"path": path}
                                ),
                                thought_signature=signature,
                            )
                            for call_id, path, signature in [
                                ("shared", "old.txt", GOOGLE_SIGNATURE),
                                ("distinct", "new.txt", None),
                            ]
                        ],
                        Part(text="", thought_signature=b"trailing-signature"),
                    ],
                ),
                finish_reason=FinishReason.STOP,
            ),
        )
        return ModelOutput(model="mockllm/model", choices=[choice])

    model = Parsing(generation, lambda: calls_output(), wire=wire)
    bridge = in_process_bridge([])

    async def rename_second(
        model: Any, output: ModelOutput, input: GenerateInput
    ) -> ModelOutput:
        calls = output.message.tool_calls or []
        if len(calls) < 2 or isinstance(output.message.content, str):
            return output
        calls[1].id = "filter_id"
        output.message.content = [
            part for part in output.message.content if not isinstance(part, ContentText)
        ]
        return ModelOutput.model_validate(output.model_dump()) if rebuilt else output

    bridge.response_filter = rename_second
    if outcome == "approval_rejected":
        bridge.approval = [ApprovalPolicy(rejecting_approver(None), "*")]
    sentinel: AbstractContextManager[None] = (
        nullcontext()
        if outcome in ("approval_rejected", "unchecked")
        else active(
            [
                bridge_reject_nth(None)
                if outcome == "sentinel_rejected"
                else bridge_recording([])
            ]
        )
    )

    messages: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    with sentinel:
        output, _ = await bridge_generate(
            bridge,
            model.model,
            list(messages),
            tools,
            None,
            GenerateConfig(),
            requested_model=None,
        )
        if outcome in ("accepted", "unchecked"):
            await bridge_generate(
                bridge,
                model.model,
                _answered(messages, output),
                tools,
                None,
                GenerateConfig(),
                requested_model=None,
            )

    [replayed] = model.wire[1]
    assert [(call[1], call[2]) for call in replayed] == [
        ("old.txt", GOOGLE_SIGNATURE),
        ("new.txt", None),
    ]


def test_an_id_several_google_anchors_name_is_shared() -> None:
    from inspect_ai.model._providers._google_reasoning import gemini_shared_call_ids

    output = calls_output(
        ToolCall(id="named_twice", function="read_file", arguments={"path": "a"}),
        ToolCall(id="unanchored", function="read_file", arguments={"path": "b"}),
    )
    output.message.content = [
        ContentReasoning(
            reasoning=signature,
            redacted=True,
            internal={"gemini_function_call_id": "named_twice"},
        )
        for signature in ["c2ln", ""]
    ]
    assert gemini_shared_call_ids(output.message) == {"named_twice"}


def _answered(input: list[ChatMessage], output: ModelOutput) -> list[ChatMessage]:
    """`input` continued with `output` and a result for each of its calls."""
    return [
        *input,
        output.message,
        *[
            ChatMessageTool(content="[]", tool_call_id=call.id)
            for call in output.message.tool_calls or []
        ],
    ]


def test_a_generation_without_a_model_event_has_no_known_producer() -> None:
    # a refusal recovered after the provider's error has no event of its own
    from inspect_ai.agent._bridge.util import _Generations

    generations = _Generations()
    output = calls_output(READ)

    generations.record(output, None)

    assert generations.producer(output) is None


@protocol
def bridge_reject_first() -> Protocol:
    rejected = False

    async def decide(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        nonlocal rejected
        if rejected:
            return None
        rejected = True
        return Decision.reject("risky", message="Not that one.")

    return decide


def _request_filter_edited(
    kind: str,
) -> tuple[
    Callable[[], ModelOutput | Awaitable[ModelOutput]],
    list[ToolInfo],
    Callable[[ToolCall], dict[str, Any]],
    Callable[[list[ChatMessage]], Awaitable[list[tuple[str, Any]]]],
    Callable[[ToolCall], Any],
]:
    """A generation of one `kind` of call, and how a request filter edits it.

    Returns the generation, its tools, the arguments the filter gives a call,
    each call a serialized request replays (its id and native arguments), and
    the native arguments a call handed on with its arguments serializes to.
    """
    if kind in RESPONSES_KINDS:
        item, _, _, approved = _responses_modified_call(kind)

        async def responses_replayed(input: list[ChatMessage]) -> list[Any]:
            return _responses_replayed(await _responses_wire(input), item.type)

        def responses_native(call: ToolCall) -> Any:
            native = {
                "function": lambda: call.arguments,
                "custom": lambda: call.arguments["input"],
                "computer": lambda: [{"type": "wait"}],
                "tool_search": lambda: call.arguments,
            }
            return native[kind]()

        return (
            _responses_parsed(item),
            [],
            lambda call: approved,
            responses_replayed,
            responses_native,
        )
    elif kind == "anthropic":

        async def anthropic_replayed(input: list[ChatMessage]) -> list[Any]:
            return [
                (block["id"], block["input"])
                for blocks in await _anthropic_wire(input)
                for block in blocks
                if block["type"] == "tool_use"
            ]

        return (
            _anthropic_parsed(ANTHROPIC_FIRST),
            list(ANTHROPIC_TOOLS),
            lambda call: {**call.arguments, "edited": True},
            anthropic_replayed,
            lambda call: call.arguments,
        )
    elif kind == "google":
        from google.genai.types import (
            Candidate,
            Content,
            FinishReason,
            FunctionCall,
            Part,
        )

        from inspect_ai.model._providers.google import (
            completion_choice_from_candidate,
        )
        from inspect_ai.model._providers.google import content as google_content

        def google() -> ModelOutput:
            call = FunctionCall(
                id="call_read", name="read_file", args={"path": "notes.txt"}
            )
            choice = completion_choice_from_candidate(
                "gemini-3-flash-preview",
                Candidate(
                    content=Content(
                        role="model",
                        parts=[Part(function_call=call, thought_signature=b"sig")],
                    ),
                    finish_reason=FinishReason.STOP,
                ),
            )
            return ModelOutput(model="mockllm/model", choices=[choice])

        async def google_replayed(input: list[ChatMessage]) -> list[Any]:
            replayed: list[Any] = []
            for message in input:
                if isinstance(message, ChatMessageAssistant):
                    parts = (await google_content(AsyncMock(), message)).parts or []
                    replayed += [
                        (part.function_call.id, part.function_call.args)
                        for part in parts
                        if part.function_call is not None
                    ]
            return replayed

        return (
            google,
            [ToolInfo(name="read_file", description="Read.")],
            lambda call: {"path": "safe.txt"},
            google_replayed,
            lambda call: call.arguments,
        )
    else:
        from inspect_ai.model._openai import openai_chat_message

        async def completions_replayed(input: list[ChatMessage]) -> list[Any]:
            replayed: list[Any] = []
            for message in input:
                if isinstance(message, ChatMessageAssistant):
                    param: Any = await openai_chat_message(message)
                    replayed += [
                        (call["id"], json.loads(call["function"]["arguments"]))
                        for call in param.get("tool_calls", [])
                    ]
            return replayed

        return (
            lambda: calls_output(deepcopy(READ)),
            [ToolInfo(name="read_file", description="Read.")],
            lambda call: {"path": "safe.txt"},
            completions_replayed,
            lambda call: call.arguments,
        )


@pytest.mark.parametrize("outcome", ["accepted", "rejected"])
@pytest.mark.parametrize("source", ["generated", "substituted"])
@pytest.mark.parametrize(
    "kind", [*RESPONSES_KINDS, "anthropic", "google", "completions"]
)
async def test_a_call_a_request_filter_edited_continues_as_edited(
    kind: str, source: str, outcome: str
) -> None:
    generation, tools, edited, replayed, native = _request_filter_edited(kind)
    # a substitute is a provider's parse the filter returns without generating
    model = Parsing(
        *([generation] if source == "generated" else []), lambda: calls_output()
    )
    substitute = source == "substituted"

    async def edit(
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        nonlocal substitute
        if substitute:
            substitute = False
            parsed = generation()
            output = parsed if isinstance(parsed, ModelOutput) else await parsed
        else:
            output = await model.generate(messages, tools, tool_choice, config)
        for call in output.message.tool_calls or []:
            call.arguments = edited(call)
        return output

    bridge = in_process_bridge([])
    bridge.filter = edit
    input: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    sentinel = bridge_reject_first() if outcome == "rejected" else bridge_recording([])
    with active([sentinel]):
        output = await _generate_bridged(bridge, model.model, input, tools)
        if outcome == "accepted":
            await _generate_bridged(
                bridge, model.model, _answered(input, output), tools
            )

    # the next request replays each call as the scaffold was handed it, or,
    # for a rejected turn, with the arguments that were rejected
    next_input = model.inputs[-1]
    rejected = next_input[1]
    assert isinstance(rejected, ChatMessageAssistant)
    calls = (
        output.message.tool_calls if outcome == "accepted" else rejected.tool_calls
    ) or []
    assert calls
    assert all(call.arguments == edited(call) for call in calls)
    assert await replayed(next_input) == [(call.id, native(call)) for call in calls]


def _acp_router(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Attach an ACP router to the transcript; returns what it publishes."""
    return _acp_session(monkeypatch)[1]


def _acp_session(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[LiveAcpTransport, list[Any]]:
    """A live ACP session routing the transcript, and what it publishes."""
    from inspect_ai.agent._acp.event_mapping import _AcpEventRouter

    session = LiveAcpTransport()
    session._attachable_override = True
    published: list[Any] = []
    monkeypatch.setattr(session, "publish", published.append)
    session._router = _AcpEventRouter(session)
    session._router.attach()
    return session, published


def _acp_cards(notifications: Sequence[Any]) -> dict[str, list[str | None]]:
    """Each ACP tool call card's statuses: its start's, then each update's."""
    from acp.schema import ToolCallProgress, ToolCallStart

    cards: dict[str, list[str | None]] = {}
    for notification in notifications:
        update = notification.update
        if isinstance(update, ToolCallStart | ToolCallProgress):
            cards.setdefault(update.tool_call_id, []).append(update.status)
    return cards


def _replayed_acp_cards() -> dict[str, list[str | None]]:
    from inspect_ai.agent._acp.event_mapping import replay_transcript

    return _acp_cards(list(replay_transcript(transcript().events, session_id="s")))


HOST_READ_ITEM: dict[str, Any] = {
    "type": "function_call",
    "id": "fc_1",
    "call_id": "call_read",
    "name": "mcp__host__read_file",
    "arguments": '{"path": "notes.txt"}',
}


async def test_a_modified_host_calls_acp_card_shows_the_arguments_that_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The proposal's card, settled by the modified call's host run, shows that run."""
    from acp.schema import ToolCallProgress, ToolCallStart

    init_sample_assistant_internal()
    published = _acp_router(monkeypatch)
    ran: list[str] = []

    async def read_file(path: str) -> str:
        ran.append(path)
        return f"contents of {path}"

    bridge = sandbox_bridge(AsyncMock(side_effect=read_file))
    model = Parsing(lambda: _responses_output(HOST_READ_ITEM))
    with active([bridge_modify()]):
        output = await _generate_bridged(
            bridge, model.model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        [handed] = output.message.tool_calls or []
        await call_host_tool(bridge)("host", "read_file", handed.arguments)

    assert ran == ["safe.txt"]
    assert _acp_cards(published) == {
        "call_read": ["in_progress", "in_progress", "completed"]
    }
    updates = [
        n.update
        for n in published
        if isinstance(n.update, ToolCallStart | ToolCallProgress)
    ]
    # the latest title and raw input a client holds for the card
    raw_input = next(u.raw_input for u in reversed(updates) if u.raw_input is not None)
    title = next(u.title for u in reversed(updates) if u.title is not None)
    assert raw_input == handed.arguments == {"path": "safe.txt"}
    assert "safe.txt" in title and "notes.txt" not in title


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("provider", ["responses", "anthropic"])
async def test_a_modified_scaffold_calls_acp_card_shows_the_arguments_that_ran(
    provider: str, replay: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proposal's card, settled by the scaffold's result for the modified call, shows that call.

    A modified Responses call is handed on under a token; a modified Anthropic
    call keeps the model's id.
    """
    from acp.schema import ToolCallProgress, ToolCallStart

    from inspect_ai.agent._acp.event_mapping import replay_transcript

    init_sample_assistant_internal()
    published = _acp_router(monkeypatch)
    model = Parsing(
        (lambda: _responses_output({**HOST_READ_ITEM, "name": "read_file"}))
        if provider == "responses"
        else (
            lambda: _anthropic_output(
                [
                    {
                        "type": "tool_use",
                        "id": "call_read",
                        "name": "read_file",
                        "input": {"path": "notes.txt"},
                    }
                ]
            )
        ),
        lambda: calls_output(),
    )
    bridge = in_process_bridge([])
    input: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    with active([bridge_modify()]):
        output = await _generate_bridged(
            bridge, model.model, input, declare_read_file("read_file")
        )
        [handed] = output.message.tool_calls or []
        result = ChatMessageTool(
            content=f"contents of {handed.arguments['path']}",
            tool_call_id=handed.id,
            function=handed.function,
        )
        await _generate_bridged(
            bridge,
            model.model,
            [*input, output.message, result],
            declare_read_file("read_file"),
        )

    if replay:
        published = list(replay_transcript(transcript().events, session_id="s"))
    assert _acp_cards(published) == {
        "call_read": ["completed"] if replay else ["in_progress", "completed"]
    }
    updates = [
        n.update
        for n in published
        if isinstance(n.update, ToolCallStart | ToolCallProgress)
    ]
    # the latest title and raw input a client holds for the card
    raw_input = next(u.raw_input for u in reversed(updates) if u.raw_input is not None)
    title = next(u.title for u in reversed(updates) if u.title is not None)
    assert raw_input == handed.arguments == {"path": "safe.txt"}
    assert "safe.txt" in title and "notes.txt" not in title
    # the model's proposal stays as generated
    proposal = next(e for e in transcript().events if isinstance(e, ModelEvent))
    [proposed] = proposal.output.message.tool_calls or []
    assert (proposed.id, proposed.arguments) == ("call_read", {"path": "notes.txt"})


async def test_cancelling_a_modified_host_calls_acp_card_cancels_its_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The proposal's card, advertised cancelable once the host run backs it, cancels that run."""
    from types import SimpleNamespace

    from acp.schema import ToolCallProgress

    from inspect_ai.agent._acp.connection import Bound, ConnectionHandler
    from inspect_ai.agent._acp.inspect_ext import TOOL_CALL_CANCELABLE_META_KEY
    from inspect_ai.tool import ToolError

    init_sample_assistant_internal()
    session, published = _acp_session(monkeypatch)
    started, release = anyio.Event(), anyio.Event()
    finished: list[str] = []

    async def read_file(path: str) -> str:
        started.set()
        await release.wait()
        finished.append(path)
        return "contents"

    bridge = sandbox_bridge(AsyncMock(side_effect=read_file))
    model = Parsing(lambda: _responses_output(HOST_READ_ITEM))
    handler = ConnectionHandler()
    handler.state.binding = Bound(
        wire_session_id="wire", target_session_id="target", interactive=True
    )
    monkeypatch.setattr(
        "inspect_ai.agent._acp.connection._find_active_sample",
        lambda _: SimpleNamespace(transcript=transcript(), acp_transport=session),
    )

    errors: list[str] = []
    with active([bridge_modify()]):
        output = await _generate_bridged(
            bridge, model.model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        [handed] = output.message.tool_calls or []

        async def execute() -> None:
            # an operator cancel reaches the scaffold as the native timeout
            try:
                await call_host_tool(bridge)("host", "read_file", handed.arguments)
            except ToolError as ex:
                errors.append(str(ex))

        async with anyio.create_task_group() as tg:
            tg.start_soon(execute)
            await started.wait()
            try:
                [card] = [
                    n.update
                    for n in published
                    if isinstance(n.update, ToolCallProgress)
                    and (n.update.field_meta or {}).get(TOOL_CALL_CANCELABLE_META_KEY)
                ]
                assert card.tool_call_id == "call_read" == handed.id
                cancelled = await handler.cancel_tool_call("wire", card.tool_call_id)
            finally:
                release.set()

    assert cancelled == {"cancelled": True}
    assert finished == []
    assert errors == ["Command timed out before completing."]
    assert _acp_cards(published)["call_read"][-1] == "failed"


def _google_after_signed_text(*calls: tuple[str, str, bytes | None]) -> ModelOutput:
    """A Gemini response, as the provider parses it: a signed text part, then `calls`.

    Each call is `(id, path, signature)`.
    """
    from google.genai.types import Candidate, Content, FinishReason, FunctionCall, Part

    from inspect_ai.model._providers.google import completion_choice_from_candidate

    choice = completion_choice_from_candidate(
        "gemini-3-flash-preview",
        Candidate(
            content=Content(
                role="model",
                parts=[
                    Part(text="Reading.", thought_signature=b"text-signature"),
                    *[
                        Part(
                            function_call=FunctionCall(
                                id=call_id, name="read_file", args={"path": path}
                            ),
                            thought_signature=signature,
                        )
                        for call_id, path, signature in calls
                    ],
                ],
            ),
            finish_reason=FinishReason.STOP,
        ),
    )
    return ModelOutput(model="mockllm/model", choices=[choice])


async def _google_wire(input: list[ChatMessage]) -> Any:
    """Each assistant message as the Google provider serializes it: `(text, path, signature)` per part."""
    from inspect_ai.model._providers.google import content as google_content

    return [
        [
            (part.text, None, part.thought_signature)
            if part.function_call is None
            else (None, _path(part.function_call.args), part.thought_signature)
            for part in (await google_content(AsyncMock(), message)).parts or []
        ]
        for message in input
        if isinstance(message, ChatMessageAssistant)
    ]


@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize("case", ["shared", "anchor_removed"])
async def test_a_google_scaffold_is_handed_no_other_parts_signature_on_a_call(
    case: str, checked: bool
) -> None:
    """The Google dialect hands a call only the signature its anchor names.

    `shared`: two calls share an id, so their anchors' signatures are dropped
    (`gemini_shared_call_ids`). `anchor_removed`: a response filter
    removes the one call's anchor. Either way the call is unsigned, and the
    text part's signature goes on no call, in the response the scaffold gets
    (its `thoughtSignature` and the embedded reasoning) and in the request
    built from the history the scaffold sends back.
    """
    from contextlib import nullcontext

    from inspect_ai.agent._bridge.google_api import inspect_google_api_request
    from inspect_ai.model._reasoning import parse_content_with_reasoning

    init_sample_assistant_internal()
    calls = (
        [("shared", "old.txt", GOOGLE_SIGNATURE), ("shared", "new.txt", None)]
        if case == "shared"
        else [("distinct", "new.txt", GOOGLE_SIGNATURE)]
    )
    model = Parsing(
        lambda: _google_after_signed_text(*calls),
        lambda: calls_output(),
        wire=_google_wire,
    )
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )
    if case == "anchor_removed":

        async def remove_anchors(
            model: Any, output: ModelOutput, input: GenerateInput
        ) -> ModelOutput:
            if not isinstance(output.message.content, str):
                output.message.content = [
                    part
                    for part in output.message.content
                    if not (
                        isinstance(part, ContentReasoning)
                        and isinstance(part.internal, dict)
                        and "gemini_function_call_id" in part.internal
                    )
                ]
            return output

        bridge.response_filter = remove_anchors
    tools: Any = [
        {
            "functionDeclarations": [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": PATH_SCHEMA,
                }
            ]
        }
    ]
    user: Any = {"role": "user", "parts": [{"text": TASK}]}

    with active([bridge_recording([])]) if checked else nullcontext():
        first = await inspect_google_api_request(
            {"model": "inspect", "contents": [user], "tools": tools},
            None,
            None,
            bridge,
        )
        parts: Any = first["candidates"][0]["content"]["parts"]
        responses: Any = {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        **{
                            key: value
                            for key, value in part["functionCall"].items()
                            if key in ("id", "name")
                        },
                        "response": {"out": "x"},
                    }
                }
                for part in parts
                if "functionCall" in part
            ],
        }
        await inspect_google_api_request(
            {
                "model": "inspect",
                "contents": [user, {"role": "model", "parts": parts}, responses],
                "tools": tools,
            },
            None,
            None,
            bridge,
        )

    handed = [part.get("thoughtSignature") for part in parts if "functionCall" in part]
    assert handed == [None] * len(calls)
    capsules = [
        capsule
        for part in parts
        if "text" in part
        and (capsule := parse_content_with_reasoning(part["text"])[1]) is not None
    ]
    assert capsules == []
    [replayed] = model.wire[1]
    assert replayed == [
        ("Reading.", None, None),
        *[(None, path, None) for _, path, _ in calls],
    ]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("signed", GOOGLE_SIGNATURE),
        ("unsigned", None),
        ("shared_cleared", None),
        ("anchor_removed", None),
        ("legacy", b"text-signature"),
    ],
)
async def test_the_google_first_call_signature_is_the_providers(
    message: str, expected: bytes | None
) -> None:
    """The Google dialect's signature for a first call is the one the provider replays."""
    import base64

    from inspect_ai.agent._bridge.util import (
        _hold_signatures_in_place,
        gemini_first_call_signature,
    )
    from inspect_ai.model._providers.google import content as google_content

    if message == "shared_cleared":
        output = _google_after_signed_text(
            ("shared", "old.txt", GOOGLE_SIGNATURE), ("shared", "new.txt", None)
        )
    else:
        output = _google_after_signed_text(
            ("distinct", "new.txt", None if message == "unsigned" else GOOGLE_SIGNATURE)
        )
    received = output.model_copy(deep=True)
    assistant = output.message
    assert isinstance(assistant.content, list)
    anchors = [
        part
        for part in assistant.content
        if isinstance(part, ContentReasoning)
        and isinstance(part.internal, dict)
        and "gemini_function_call_id" in part.internal
    ]
    if message == "shared_cleared":
        for anchor in anchors:
            anchor.reasoning = ""
    elif message in ("anchor_removed", "legacy"):
        assistant.content = [part for part in assistant.content if part not in anchors]
        if message == "anchor_removed":
            _hold_signatures_in_place(received, output)

    signed = gemini_first_call_signature(assistant)
    replayed = await google_content(AsyncMock(), assistant)
    first_call = next(part for part in replayed.parts or [] if part.function_call)
    assert first_call.thought_signature == expected
    assert (base64.b64decode(signed.reasoning) if signed else None) == expected


async def _regenerate_rebuilt(
    model: Model, output: ModelOutput, input: GenerateInput
) -> ModelOutput:
    """A response filter that regenerates, and returns the replacement rebuilt from its fields."""
    replacement = await model.generate(*input)
    return ModelOutput.model_validate(replacement.model_dump())


@pytest.mark.parametrize("path", ["handed_over", "approval_rejected"])
@pytest.mark.parametrize("kind", ["custom", "computer", "tool_search", "anthropic"])
async def test_a_regenerated_output_a_response_filter_rebuilt_replays_natively(
    kind: str, path: str
) -> None:
    """A response filter regenerates and returns the output rebuilt from its fields.

    Its calls replay in their native form, with the replay state of the
    regeneration that parsed them, whether a sentinel hands them on or approval
    rejects them without one.
    """
    from contextlib import nullcontext

    init_sample_assistant_internal()
    if kind == "anthropic":

        def bash(call_id: str) -> Callable[[], Awaitable[ModelOutput]]:
            return _anthropic_parsed(
                [
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": "bash",
                        "input": {"command": "cat notes.txt"},
                    }
                ]
            )

        generations = [bash("toolu_first"), bash("toolu_regenerated")]
        tools = list(ANTHROPIC_TOOLS)
        wire: Callable[[list[ChatMessage]], Awaitable[Any]] = _anthropic_wire
    else:
        item = _responses_modified_call(kind)[0]
        generations = [
            _responses_parsed(
                item.model_copy(update={"id": f"{item.id}_{n}", "call_id": f"call_{n}"})
            )
            for n in ("first", "regenerated")
        ]
        tools = [ToolInfo(name="read_file", description="Read a file.")]
        wire = _responses_wire
    model = Parsing(*generations, lambda: calls_output(), wire=wire)
    bridge = in_process_bridge([])
    bridge.response_filter = _regenerate_rebuilt
    if path == "approval_rejected":
        bridge.approval = [ApprovalPolicy(rejecting_approver(1), "*")]
    input: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active([bridge_recording([])]) if path == "handed_over" else nullcontext():
        output = await _generate_bridged(bridge, model.model, input, tools)
        if path == "handed_over":
            await _generate_bridged(
                bridge, model.model, _answered(input, output), tools
            )

    # the request after the regeneration replays the handed or rejected turn
    replayed = model.wire[2]
    if kind == "anthropic":
        assert _anthropic_shapes(replayed) == [[("tool_use", "bash")]]
    else:
        assert [
            param["type"] for param in replayed if param["type"] in RESPONSES_CALL_TYPES
        ] == [_responses_modified_call(kind)[0].type]


def _reusing_model(kind: str, cache: bool = False) -> tuple[Parsing, list[ToolInfo]]:
    """A model generating two calls of `kind` under one id, reading old then new."""
    if kind == "anthropic":
        return Parsing(
            _anthropic_parsed(ANTHROPIC_FIRST),
            _anthropic_parsed(ANTHROPIC_SECOND),
            lambda: calls_output(),
            cache=cache,
            wire=_anthropic_wire,
        ), list(ANTHROPIC_TOOLS)
    return Parsing(
        *[_responses_parsed(item) for item in _responses_calls_reading(kind, True)],
        lambda: calls_output(),
        cache=cache,
        wire=_responses_wire,
    ), []


def _replays_reading(kind: str, wire: Any, call_id: str, generation: int) -> bool:
    """Whether a serialized request replays the generation's call as generated."""
    if kind == "anthropic":
        return _anthropic_shapes(wire) == [
            [ANTHROPIC_FIRST_REPLAY, ANTHROPIC_SECOND_REPLAY][generation]
        ]
    item = _responses_calls_reading(kind, True)[generation]
    return _responses_replayed(wire, item.type) == [
        (call_id, _responses_native_arguments(item.model_dump(exclude_none=True)))
    ]


async def _generate_bridged(
    bridge: AgentBridge, model: Model, input: list[ChatMessage], tools: list[ToolInfo]
) -> ModelOutput:
    output, _ = await bridge_generate(
        bridge, model, input, tools, None, GenerateConfig(), requested_model=None
    )
    return output


async def test_a_provider_output_rebuilt_from_its_fields_replays_its_own_calls() -> (
    None
):
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    init_sample_assistant_internal()
    old, new = _responses_calls_reading("function", True)

    # a provider parses its response, then returns the output rebuilt from its
    # fields after another generation in the sample reused the call's id
    async def rebuilt() -> ModelOutput:
        output = await _responses_output(new)
        await _responses_output(old)
        return ModelOutput.model_validate_json(output.model_dump_json())

    model = Parsing(rebuilt, lambda: calls_output(), wire=_responses_wire)
    bridge = in_process_bridge([])
    input: list[ChatMessage] = [ChatMessageUser(content="Read new.txt.")]

    with active([bridge_recording([])]):
        output = await _generate_bridged(bridge, model.model, input, [])
        await _generate_bridged(bridge, model.model, _answered(input, output), [])

    # the item under the id is the other generation's: the call replays with
    # its own arguments
    [handed] = output.message.tool_calls or []
    assert handed.id == "call_reused"
    assert _responses_replayed(model.wire[1], "function_call") == [
        (handed.id, {"path": "new.txt"})
    ]


@pytest.fixture
def isolated_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], None]:
    """Gives the test a new empty model output cache, so its first request misses.

    Call it at the start of each attempt: a flaky retry runs the test again with
    the same fixtures.
    """

    def isolate() -> None:
        monkeypatch.setenv("INSPECT_CACHE_DIR", mkdtemp(dir=tmp_path))

    return isolate


@skip_if_no_anthropic
async def test_live_anthropic_cached_retries_with_interleaved_thinking_continue(
    isolated_cache: Callable[[], None],
) -> None:
    from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    isolated_cache()
    # a flaky retry runs the test again in the same transcript
    init_transcript(Transcript())
    init_sample_assistant_internal()
    model = get_model(
        "anthropic/claude-sonnet-4-5",
        config=GenerateConfig(cache=True, reasoning_tokens=1024),
    )
    bridge = AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model})
    files = {"a.txt": "Now read b.txt.", "b.txt": "That is all."}
    turns: list[Any] = [
        {
            "role": "user",
            "content": "Read a.txt with read_file and follow its instructions.",
        }
    ]

    def request() -> dict[str, Any]:
        return {
            "model": "inspect",
            "max_tokens": 4096,
            "messages": turns,
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file.",
                    "input_schema": PATH_SCHEMA,
                }
            ],
        }

    # each step's response is retried, as a scaffold retrying a request; the
    # retry is a cache hit, handed over under new IDs
    with active([bridge_recording([])]):
        for _ in files:
            first = await inspect_anthropic_api_request(
                request(), None, None, None, bridge
            )
            retry = await inspect_anthropic_api_request(
                request(), None, None, None, bridge
            )
            assert [block.type for block in retry.content] == [
                block.type for block in first.content
            ]
            assert "thinking" in [block.type for block in retry.content]
            content = [block.model_dump(exclude_none=True) for block in retry.content]
            uses = [block for block in content if block["type"] == "tool_use"]
            assert uses and not {use["id"] for use in uses} & {
                block.id for block in first.content if block.type == "tool_use"
            }
            turns += [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": use["id"],
                            "content": files.get(use["input"].get("path"), "None."),
                        }
                        for use in uses
                    ],
                },
            ]
        continuation = await inspect_anthropic_api_request(
            request(), None, None, None, bridge
        )

    # a generation and a cache hit per step, and the continuation
    assert [e.cache for e in transcript().events if isinstance(e, ModelEvent)] == [
        "write",
        "read",
        "write",
        "read",
        "write",
    ]
    assert continuation.content


LIVE_RESPONSES_CALLS: dict[str, tuple[str, Any, Any, dict[str, Any]]] = {
    "custom": (
        "openai/gpt-5",
        {
            "type": "custom",
            "name": "apply_patch",
            "description": "Apply a patch in the V4A diff format.",
            "format": {"type": "text"},
        },
        {"type": "custom_tool_call_output", "output": "Done."},
        {"input": "*** Begin Patch\n*** Add File: hello.txt\n+approved\n*** End Patch"},
    ),
    "computer": (
        "openai/gpt-5.4",
        {"type": "computer"},
        {
            "type": "computer_call_output",
            "output": {"type": "computer_screenshot", "image_url": PNG_DATA_URI},
        },
        {"actions": [{"action": "wait"}]},
    ),
}


@protocol
def modifies_retries(arguments: dict[str, Any]) -> Protocol:
    """Approves a call the first time it is proposed and modifies it after."""
    proposals: list[ToolCall] = []

    async def rewrite(
        context: Context, step: BeforeToolCall, escalations: Escalations
    ) -> Decision | None:
        proposals.append(step.call)
        if len(proposals) == 1:
            return None
        modified = replace(step.call, arguments=arguments)
        return Decision(action="modify", modified=modified, explanation="changed")

    return rewrite


@skip_if_no_openai
@pytest.mark.parametrize("kind", ["custom", "computer"])
async def test_live_responses_cached_retry_with_native_call_continues(
    kind: str, isolated_cache: Callable[[], None]
) -> None:
    from inspect_ai.agent._bridge.responses import inspect_responses_api_request
    from inspect_ai.model._assistant_internal import init_sample_assistant_internal

    isolated_cache()
    # a flaky retry runs the test again in the same transcript
    init_transcript(Transcript())
    init_sample_assistant_internal()
    name, tool, result, approved = LIVE_RESPONSES_CALLS[kind]
    model = get_model(name, config=GenerateConfig(cache=True))
    bridge = AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model})
    task = (
        "Use apply_patch to add a file hello.txt containing 'hi'."
        if kind == "custom"
        else "Take a screenshot of the screen."
    )
    items: list[Any] = [{"role": "user", "content": task}]

    def request(input: list[Any]) -> dict[str, Any]:
        return {"model": "inspect", "input": input, "tools": [tool]}

    # the retry is modified, so it is handed over under a fresh ID with the
    # approved arguments
    with active([modifies_retries(approved)]):
        first = await inspect_responses_api_request(
            request(items), None, None, None, bridge
        )
        retry = await inspect_responses_api_request(
            request(items), None, None, None, bridge
        )
        handed = [item.model_dump(exclude_none=True) for item in retry.output]
        [call] = [item for item in handed if "call_id" in item]
        await inspect_responses_api_request(
            request([*items, *handed, {**result, "call_id": call["call_id"]}]),
            None,
            None,
            None,
            bridge,
        )

    [original] = [item for item in first.output if hasattr(item, "call_id")]
    assert call["type"] == original.type and call["call_id"] != original.call_id
    events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    assert [e.cache for e in events] == ["write", "read", "write"]
    # the continuation sent the model the approved call
    assert events[-1].call is not None
    sent_input: list[Any] = cast(list[Any], events[-1].call.request["input"])
    [sent] = [
        item
        for item in sent_input
        if item.get("call_id") == call["call_id"] and item.get("type") == call["type"]
    ]
    assert _responses_native_arguments(sent) == _responses_native_arguments(call)
    assert _responses_native_arguments(call) != _responses_native_arguments(
        original.model_dump(exclude_none=True)
    )


@skip_if_no_google
async def test_live_modified_gemini_computer_action_continues() -> None:
    from unittest.mock import MagicMock

    from inspect_ai.agent._bridge.completions import inspect_completions_api_request
    from inspect_ai.model._providers.google import as_chat_messages
    from inspect_ai.tool import ToolDef
    from inspect_ai.tool._tools._computer._computer import computer

    init_transcript(Transcript())
    model = get_model(
        "google/gemini-3-flash-preview",
        config=GenerateConfig(max_retries=2, timeout=120),
    )
    bridge = AgentBridge(AgentState(messages=[]), model_aliases={"inspect": model})
    parameters = ToolDef(computer()).parameters
    tools: Any = [
        {
            "type": "function",
            "function": {
                "name": "computer",
                "description": "Use the computer.",
                "parameters": parameters.model_dump(exclude_none=True),
            },
        }
    ]
    messages: list[Any] = [
        {
            "role": "user",
            "content": "The browser is open. Click the center of the screen.",
        }
    ]
    modified: list[dict[str, Any]] = []

    @protocol
    def change_action() -> Protocol:
        async def rewrite(
            context: Context, step: BeforeToolCall, escalations: Escalations
        ) -> Decision | None:
            arguments = WAIT if step.call.arguments.get("action") != "wait" else CLICK
            modified.append(arguments)
            return Decision(
                action="modify",
                modified=replace(step.call, arguments=arguments),
                explanation="changed",
            )

        return rewrite

    with active([change_action()]):
        completion = await inspect_completions_api_request(
            {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
        )
        message = completion.choices[0].message
        assert message.tool_calls
        await inspect_completions_api_request(
            {
                "model": "inspect",
                "messages": [
                    *messages,
                    message.model_dump(exclude_none=True),
                    *[
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": [
                                {"type": "text", "text": "done"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": PNG_DATA_URI},
                                },
                            ],
                        }
                        for call in message.tool_calls
                    ],
                ],
                "tools": tools,
            },
            None,
            bridge,
        )

    events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    assert len(events) == 2 and events[1].error is None
    replayed = await as_chat_messages(MagicMock(), events[1].input)
    parts = [part for content in replayed for part in content.parts or []]
    calls = [part.function_call.name for part in parts if part.function_call]
    results = [part.function_response.name for part in parts if part.function_response]
    expected = gemini_computer_action_name(modified[0])
    assert calls[0] == results[0] == expected
