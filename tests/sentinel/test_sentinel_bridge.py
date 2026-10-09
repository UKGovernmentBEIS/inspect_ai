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

    with active(observe_only([bridge_recording(seen)])):
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

    with active(observe_only([bridge_recording(seen)])):
        await generate(bridge, model, [ChatMessageUser(content=TASK)])

    [step] = seen
    assert step.view.call is not None
    assert step.view.call.content == "Reading `notes.txt`"


def test_evicting_an_unreported_scaffold_call_warns_once(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from inspect_ai._util import logger as inspect_logger
    from inspect_ai.agent._bridge import _sentinel

    monkeypatch.setattr(_sentinel, "_MAX_PENDING_CALLS", 2)
    monkeypatch.setattr(inspect_logger, "_warned", [])
    bridge = in_process_bridge([])
    checks = [
        _sentinel.SentinelCheck(call, call, None, "", [], [])
        for call in [replace(READ, id=f"read_{i}") for i in range(4)]
    ]

    with caplog.at_level("WARNING"):
        _sentinel.track_sentinel_calls(bridge, checks[:3], [False] * 3)
        _sentinel.track_sentinel_calls(bridge, checks[3:], [False])

    warnings = [r for r in caplog.records if "awaiting their results" in r.message]
    assert len(warnings) == 1
    assert "tool_result check may be skipped" in warnings[0].message
    unbound = _sentinel._result_checks[bridge].unbound.values()
    assert [i.check.handed.id for i in unbound if i.check] == ["read_2", "read_3"]


@protocol
def terminate_on_secret() -> Protocol:
    async def after(context: Context, step: AfterToolCall) -> Decision | None:
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

    with active(observe_only([bridge_recording(seen)])):
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


async def test_google_results_of_repeated_calls_are_matched_in_order() -> None:
    seen: Steps = []
    calls = [replace(READ, id=f"read_{i}") for i in range(3)]
    model = Scripted(*[calls_output(call) for call in calls], calls_output())
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"inspect": model.model}
    )

    with active(observe_only([bridge_recording(seen)])):
        await google_round_trips(bridge, model, ["same", "same", "new"])

    assert [(s.call.id, s.output) for s in seen if isinstance(s, AfterToolCall)] == [
        ("read_0", '{"out": "same"}'),
        ("read_1", '{"out": "same"}'),
        ("read_2", '{"out": "new"}'),
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
    async def after(context: Context, step: AfterToolCall) -> Decision | None:
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

    with active(observe_only([bridge_recording(seen)])):
        output = await generate(bridge, model, history)
        await generate(
            bridge,
            model,
            [
                *history,
                output.message,
                ChatMessageTool(content="a", tool_call_id=one.id),
                ChatMessageTool(content="b", tool_call_id=two.id),
            ],
        )

    # a response's results are checked concurrently
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
        async def rewrite(context: Context, step: BeforeToolCall) -> Decision | None:
            if step.call.arguments["path"] != "other":
                return None
            modified = replace(step.call, arguments={"path": "safe.txt"})
            return Decision(action="modify", modified=modified, explanation="safer")

        return rewrite

    with active(modify_other()):
        output = await generate(bridge, model, [ChatMessageUser(content=TASK)])

    assert output.message.tool_calls == [
        one,
        replace(two, arguments={"path": "safe.txt"}),
    ]


async def test_a_host_call_beyond_the_scaffold_cap_is_still_checked() -> None:
    from inspect_ai.agent._bridge._sentinel import _MAX_PENDING_CALLS

    calls = [
        replace(
            READ,
            id=f"call_{i}",
            function="mcp__host__read_file",
            arguments={"path": str(i)},
        )
        for i in range(_MAX_PENDING_CALLS + 1)
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

    assert isinstance(bridge._failure, TerminateSampleError)


async def test_a_host_tool_error_reaches_the_scaffold_once_checked() -> None:
    from inspect_ai.tool import ToolError

    seen: Steps = []
    call = replace(READ, function="mcp__host__read_file")
    bridge = sandbox_bridge(AsyncMock(side_effect=ToolError("secret error text")))
    model = Scripted(calls_output(call))

    with active(observe_only([bridge_recording(seen)])):
        await generate(
            bridge, model, [ChatMessageUser(content=TASK)], declare_read_file()
        )
        with pytest.raises(ToolError, match="secret error text"):
            await call_host_tool(bridge)("host", "read_file", READ.arguments)

    _, after = seen
    assert isinstance(after, AfterToolCall)
    assert after.result.error is not None
    assert after.result.error.message == "secret error text"
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
    with active(observe_only([bridge_recording(seen)])):
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
