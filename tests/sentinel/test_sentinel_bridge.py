from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._sentinel._config import resolve_sentinel_root, resolve_sentinel_spec
from inspect_ai._sentinel._context import SentinelFailure, init_sentinel
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
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
from inspect_ai.event import ModelEvent, SentinelEvent
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
from inspect_ai.model._model import GenerateInput
from inspect_ai.model._model_output import ChatCompletionChoice
from inspect_ai.tool import Tool, ToolCall, ToolCallView, ToolChoice, ToolInfo, tool
from inspect_ai.tool._tool import ToolParsingError
from inspect_ai.tool._tool_params import ToolParam, ToolParams

try:
    from inspect_sentinel import (
        AfterToolCall,
        BeforeToolCall,
        Context,
        Decision,
        MonitorGroup,
        Observation,
        Protocol,
        ProtocolGroup,
        monitor,
        observe_only,
        protocol,
    )
except ImportError:
    pytest.skip("inspect_sentinel is not installed", allow_module_level=True)


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
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        if step.call.function == "bash":
            return Decision.reject("risky", message=message)
        return None

    async def later(context: Context, step: AfterToolCall) -> Decision | None:
        if seen is not None:
            seen.append(step)
        return None

    return ProtocolGroup(decide, later)


@protocol
def bridge_modify() -> Protocol:
    async def rewrite(context: Context, step: BeforeToolCall) -> Decision | None:
        modified = replace(step.call, arguments={"path": "safe.txt"})
        return Decision(action="modify", modified=modified, explanation="narrowed")

    return rewrite


@protocol
def bridge_terminate(after: bool = False) -> ProtocolGroup:
    async def before(context: Context, step: BeforeToolCall) -> Decision | None:
        return None if after else Decision.terminate("too risky")

    async def later(context: Context, step: AfterToolCall) -> Decision | None:
        return Decision.terminate(f"saw {step.result.text}") if after else None

    return ProtocolGroup(before, later)


@protocol
def bridge_raising(after: bool = False) -> ProtocolGroup:
    async def before(context: Context, step: BeforeToolCall) -> Decision | None:
        if not after:
            raise PermissionError("sentinel denied")
        return None

    async def later(context: Context, step: AfterToolCall) -> Decision | None:
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

    def __init__(self, *outputs: ModelOutput) -> None:
        self.outputs = list(outputs)
        self.inputs: list[list[ChatMessage]] = []

        def respond(
            input: list[ChatMessage], tools: Any, tool_choice: Any, config: Any
        ) -> ModelOutput:
            self.inputs.append(list(input))
            return self.outputs[min(len(self.inputs), len(self.outputs)) - 1]

        self.model = get_model("mockllm/model", custom_outputs=respond, memoize=False)


async def generate(
    bridge: AgentBridge,
    model: Scripted,
    input: list[ChatMessage],
    tools: list[ToolInfo] | None = None,
) -> ModelOutput:
    output, _ = await bridge_generate(
        bridge, model.model, list(input), list(tools or []), None, GenerateConfig()
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


def sandbox_bridge(tool: AsyncMock | None = None) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        bridged_tools={"host": {"read_file": read_file(tool or AsyncMock())}},
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


def sentinel_events() -> list[SentinelEvent]:
    return [e for e in transcript().events if isinstance(e, SentinelEvent)]


def root_decisions() -> list[tuple[str, str, str | None]]:
    return [
        (e.step_id, e.stage, e.action)
        for e in sentinel_events()
        if e.path == "" and e.kind == "decision"
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
    with active(observe_only([bridge_recording(seen)])):
        output = await generate(bridge, model, scaffold)

    assert output.message.tool_calls == [BASH]
    [step] = seen
    assert isinstance(step, BeforeToolCall)
    assert step.call == BASH
    assert step.message == "Fetching."
    assert step.input == model.inputs[0]
    assert [m.text for m in step.input] == ["Be careful.", TASK]
    assert [m.text for m in step.history] == [TASK, "Fetching."]
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
    assert isinstance(replay, ChatMessageTool)
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


async def test_terminate_ends_the_sample() -> None:
    model = Scripted(calls_output(BASH))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_terminate()):
        with pytest.raises(TerminateSampleError, match="too risky"):
            await generate(bridge, model, [ChatMessageUser(content=TASK)])


async def test_sandbox_terminate_signals_the_monitor() -> None:
    model = Scripted(calls_output(BASH))
    bridge = sandbox_bridge()

    with active(bridge_terminate()):
        with pytest.raises(TerminateSampleError):
            await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert bridge._failure_requested.is_set()
    assert isinstance(bridge._failure, TerminateSampleError)
    assert bridge._failure.reason == "too risky"


async def test_an_approvers_modify_reaches_the_sentinel() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    bridge.approval = [ApprovalPolicy(modifying_approver(), "*")]

    with active(observe_only([bridge_recording(seen)])):
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

    with active(observe_only([bridge_recording(seen)])):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert output.message.tool_calls == [READ]
    assert [step.call.id for step in seen] == [READ.id]


async def test_tool_result_stage_runs_when_the_result_reaches_the_bridge() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ, content="Reading."), calls_output())
    scaffold: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(scaffold)

    with active(observe_only([bridge_recording(seen)])):
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
    assert after.message == "Reading."
    assert after.input == model.inputs[0]
    assert after.history == before.history
    assert after.conversation == before.conversation
    assert observations() == [(READ.id, "tool_call"), (READ.id, "tool_result")]


async def test_tool_result_stage_sees_the_call_as_modified() -> None:
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output())
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    bridge.approval = [ApprovalPolicy(modifying_approver(), "*")]

    with active(observe_only([bridge_recording(seen)])):
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


async def test_a_rejected_call_has_no_tool_result_stage() -> None:
    seen: Steps = []
    model = Scripted(calls_output(BASH), calls_output(READ), calls_output())
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])

    with active(bridge_reject(seen=seen)):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])
        await generate(
            bridge,
            model,
            [
                ChatMessageUser(content=TASK),
                output.message,
                ChatMessageTool(content="x", tool_call_id=READ.id),
                ChatMessageTool(content="y", tool_call_id=BASH.id),
            ],
        )

    assert [step.call.id for step in seen] == [READ.id]


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


async def test_host_tool_result_is_checked_in_the_service() -> None:
    seen: Steps = []
    read = ToolCall(
        id="host_1", function="mcp__host__read_file", arguments=READ.arguments
    )
    model = Scripted(calls_output(read), calls_output())
    bridge = sandbox_bridge(AsyncMock(return_value="host contents"))

    with active(observe_only([bridge_recording(seen)])):
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
                ChatMessageTool(content="host contents", tool_call_id=read.id),
            ],
            declare_read_file(),
        )

    _, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.call == read
    assert after.output == "host contents"
    assert after.result.tool_call_id == read.id
    assert after.result.function == read.function
    assert after.result.text == "host contents"
    assert observations() == [(read.id, "tool_call"), (read.id, "tool_result")]


async def test_host_tool_result_terminate_signals_the_monitor() -> None:
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

    assert isinstance(bridge._failure, TerminateSampleError)


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


async def test_cancellation_during_the_tool_call_stage_propagates() -> None:
    started = anyio.Event()
    cleaned_up = anyio.Event()
    model = Scripted(calls_output(BASH))
    bridge = in_process_bridge([ChatMessageUser(content=TASK)])
    outputs: list[ModelOutput] = []

    with active(observe_only([bridge_waiting(started, cleaned_up)])):
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
            sentinel=observe_only([bridge_recording(seen)]),
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

    with active([bridge_modify(), observe_only([bridge_recording(seen)])]):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    [step] = seen
    assert (step.call.id, step.call.function) == ("d_1", "read_file")
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

    with active(observe_only([bridge_recording(seen)])):
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

    with active(observe_only([bridge_recording(seen)])):
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

    with active(observe_only([bridge_recording(seen)])):
        output = await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(ToolParsingError):
            await call_host_tool(bridge)("host", "read_file", {"path": 1})
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
    assert [type(step) for step in seen] == [BeforeToolCall]


async def test_a_host_result_is_attributed_to_the_latest_matching_proposal() -> None:
    seen: Steps = []
    stale = ToolCall(
        id="stale", function="mcp__host__read_file", arguments=READ.arguments
    )
    fresh = replace(stale, id="fresh")
    model = Scripted(calls_output(stale), calls_output(fresh))
    bridge = sandbox_bridge(AsyncMock(return_value="contents"))

    with active(observe_only([bridge_recording(seen)])):
        # the scaffold never ran the first response's call
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        await call_host_tool(bridge)("host", "read_file", READ.arguments)

    assert [step.call.id for step in seen if isinstance(step, AfterToolCall)] == [
        "fresh"
    ]
