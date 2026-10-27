import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, patch

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._sentinel._config import resolve_sentinel_root, resolve_sentinel_spec
from inspect_ai._sentinel._context import SentinelFailure, init_sentinel
from inspect_ai._util.content import ContentImage, ContentReasoning, ContentText
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


def sentinel_events() -> list[SentinelEvent]:
    return [e for e in transcript().events if isinstance(e, SentinelEvent)]


def root_decisions() -> list[tuple[str, str, str | None]]:
    return [
        (e.step_id, e.stage, e.action)
        for e in sentinel_events()
        if e.path == "" and e.kind == "decision"
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
        ("bridge_waiting", "cancelled")
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
                    ChatMessageTool(content="contents", tool_call_id=call.id),
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
    checks = [
        _sentinel.SentinelCheck(call, call, None, "", "message_1", [])
        for call in [replace(READ, id=f"read_{i}") for i in range(4)]
    ]

    with caplog.at_level("WARNING"):
        _sentinel._result_checks(bridge).issue(checks[:3])
        _sentinel._result_checks(bridge).issue(checks[3:])

    warnings = [
        r for r in caplog.records if "the oldest proposal was dropped" in r.message
    ]
    assert len(warnings) == 1
    proposals = _sentinel._result_checks(bridge).proposals.values()
    assert [p.handed.id for p in proposals] == ["read_2", "read_3"]


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


async def test_an_evicted_execution_never_matches_a_newer_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai.agent._bridge import _sentinel

    monkeypatch.setattr(_sentinel, "_MAX_PROPOSALS", 1)
    seen: Steps = []
    model = Scripted(calls_output(READ), calls_output(READ), calls_output())
    bridge = in_process_bridge([])
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]

    with active([bridge_recording(seen)]):
        older = await generate(bridge, model, history)
        newer = await generate(bridge, model, history)
        # the newer execution's result, then the older one's, identical
        for output in [newer, older]:
            [call] = output.message.tool_calls or []
            await generate(
                bridge,
                model,
                [
                    *history,
                    output.message.model_copy(update={"id": "echoed"}),
                    ChatMessageTool(content="same", tool_call_id=call.id),
                ],
            )

    # the older execution is still known by its token once its proposal is
    # gone, so its result is checked, under the model's id, without context
    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [(s.call.id, s.input) for s in afters] == [
        (READ.id, model.inputs[1]),
        (READ.id, None),
    ]


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


async def dialect_round_trip(dialect: str, bridge: AgentBridge) -> None:
    """A scaffold sending one request, then its response and the call's result."""
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
        messages += [
            message.model_dump(exclude_none=True),
            {"role": "tool", "tool_call_id": message.tool_calls[0].id, "content": "x"},
        ]
        await inspect_completions_api_request(
            {"model": "inspect", "messages": messages, "tools": tools}, None, bridge
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
        turns += [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": use["id"], "content": "x"}
                ],
            },
        ]
        await inspect_anthropic_api_request(request(), None, None, None, bridge)
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
        items += [
            *output,
            {"type": "function_call_output", "call_id": call["call_id"], "output": "x"},
        ]
        await inspect_responses_api_request(
            responses_request(), None, None, None, bridge
        )


@pytest.mark.parametrize("dialect", ["completions", "anthropic", "responses"])
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


REWRITES = ["unchanged", "compaction", "whitespace", "split_text", "result_parts"]


@pytest.mark.parametrize("rewrite", REWRITES)
async def test_a_result_is_checked_once_however_the_scaffold_rewrites_history(
    rewrite: str,
) -> None:
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
        elif rewrite == "whitespace":
            history[0] = ChatMessageUser(content="Old task details ")
            result = ChatMessageTool(content="same  result\n", tool_call_id=READ.id)
        elif rewrite == "split_text":
            history[0] = ChatMessageUser(
                content=[ContentText(text="Old task"), ContentText(text=" details")]
            )
        elif rewrite == "result_parts":
            result = ChatMessageTool(
                content=[ContentText(text="same"), ContentText(text=" result")],
                tool_call_id=READ.id,
            )
        await generate(bridge, model, [*history, echoed, result])

    [after] = [s for s in seen if isinstance(s, AfterToolCall)]
    assert after.input == model.inputs[0]


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


async def test_calls_sharing_a_model_id_are_handed_over_under_their_own_tokens() -> (
    None
):
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

    # the first keeps the model's id; the second gets a token of its own
    assert first_call.id == READ.id and second_call.id != READ.id
    # the model's proposal stays on the record
    model_events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    assert [e.output.message.tool_calls for e in model_events[:2]] == [[READ]] * 2
    # the steps show the model's id, each with its own generation's input
    afters = [s for s in seen if isinstance(s, AfterToolCall)]
    assert [(s.call.id, s.input) for s in afters] == [
        (READ.id, model.inputs[0]),
        (READ.id, model.inputs[1]),
    ]


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
                        ChatMessageTool(content="contents", tool_call_id=call.id),
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
    assert bridge._sentinel_results is None or not bridge._sentinel_results.proposals


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

    # the scaffold is handed each call under its own id
    handed = [call.id for call in output.message.tool_calls or []]
    assert handed[0] == "one" and handed[1] != "one"
    assert handed[1] == ("two" if not duplicate_id else handed[1])
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

    first, second = output.message.tool_calls or []
    assert first == one
    # the scaffold gets the second call under an id of its own
    assert second == replace(two, id=second.id, arguments={"path": "safe.txt"})
    assert second.id != one.id


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


@pytest.mark.parametrize("filter", [None, "rewrites", "generates"])
async def test_both_stages_see_the_input_the_model_was_sent(
    filter: str | None,
) -> None:
    seen: Steps = []
    # Model.generate adds the configured system message and drops reasoning
    # history after the bridge hands over its input
    model = Scripted(
        calls_output(READ),
        calls_output(),
        config=GenerateConfig(system_message=POLICY, reasoning_history="none"),
    )
    history = reasoned_history()
    bridge = in_process_bridge(history)

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

    if filter is not None:
        bridge.filter = passes_through
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
    model_event = next(e for e in transcript().events if isinstance(e, ModelEvent))
    assert before.input == model_event.input == model.inputs[0]
    assert after.input == before.input
    assert before.input is not None
    assert isinstance(before.input[0], ChatMessageSystem)
    assert before.input[0].text == POLICY
    assert not any(
        isinstance(content, ContentReasoning)
        for message in before.input
        if not isinstance(message.content, str)
        for content in message.content
    )


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


@pytest.mark.parametrize("forward", [True, False])
async def test_step_input_with_a_model_event_sink(forward: bool) -> None:
    seen: Steps = []
    model = Scripted(
        calls_output(READ), calls_output(), config=GenerateConfig(system_message=POLICY)
    )
    history: list[ChatMessage] = [ChatMessageUser(content=TASK)]
    bridge = in_process_bridge(history)
    sink = RecordingSink(forward)
    bridge.model_event_sink = sink

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
    if forward:
        # a sink that emits the event (as inspect_swe's do) leaves it findable
        assert before.input == sink.events[0].input == model.inputs[0]
        assert after.input == before.input
    else:
        # one that withholds it leaves no record of what the model was sent
        assert before.input is None and after.input is None


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
            ChatMessageTool(content="benign", tool_call_id=call.id),
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
                    ChatMessageTool(content="secret", tool_call_id=call.id),
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
    assert after.call.function == (call.function if proposed else "read_file")
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
