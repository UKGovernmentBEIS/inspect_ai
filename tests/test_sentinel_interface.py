from collections.abc import Sequence

import pytest

from inspect_ai._sentinel import _interface
from inspect_ai._sentinel._interface import (
    ModelInputStep,
    ModelOutputStep,
    SentinelEscalation,
    SentinelEvalContext,
    SentinelHost,
    SentinelHumanAnswer,
    SentinelImplementation,
    SentinelRecord,
    SentinelStep,
    SentinelVerdict,
    ToolCallStep,
    ToolResultStep,
    Truncation,
    register_sentinel,
    sentinel_implementation,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.event._sentinel import SentinelStage
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.tool import ToolCall, ToolCallView, ToolChoice, ToolInfo
from inspect_ai.util import Store


@pytest.fixture(autouse=True)
def no_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_interface, "_implementation", None)


class FakeHost:
    def __init__(self) -> None:
        self.asked: list[tuple[SentinelStep, list[str], list[SentinelEscalation]]] = []
        self.records: list[SentinelRecord] = []
        self._store = Store()

    @property
    def eval(self) -> SentinelEvalContext | None:
        return None

    @property
    def store(self) -> Store:
        return self._store

    async def generate(
        self,
        input: str | list[ChatMessage],
        *,
        model: str | None = None,
        role: str | None = None,
        tools: list[ToolInfo] | None = None,
        tool_choice: ToolChoice | None = None,
        config: GenerateConfig | None = None,
    ) -> ModelOutput:
        return ModelOutput.from_content(model or role or "monitor", "0.9")

    async def ask_human(
        self,
        step: SentinelStep,
        choices: Sequence[str],
        escalations: Sequence[SentinelEscalation],
    ) -> SentinelHumanAnswer:
        self.asked.append((step, list(choices), list(escalations)))
        return SentinelHumanAnswer(decision="reject", reason="no")

    def record(self, record: SentinelRecord) -> None:
        self.records.append(record)


class FakeImplementation:
    """Watches every stage; scores the step, asks a person and rejects."""

    def resolve(self, sentinels: object) -> object:
        return sentinels

    def watched_stages(self, root: object) -> frozenset[SentinelStage]:
        return frozenset({"model_input", "model_output", "tool_call", "tool_result"})

    async def run(
        self, root: object, host: SentinelHost, step: SentinelStep
    ) -> SentinelVerdict | None:
        output = await host.generate("score it", role="monitor")
        host.record(
            SentinelRecord(
                factory="fake/monitor",
                path="monitor",
                kind="observation",
                status="reported",
                function="check",
                suspicion=float(output.completion),
            )
        )
        answer = await host.ask_human(
            step, ["approve", "reject"], [SentinelEscalation("monitor", "high")]
        )
        return SentinelVerdict(
            action="proceed" if answer.decision == "approve" else answer.decision,
            message=answer.reason,
        )


CALL = ToolCall(id="call_1", function="bash", arguments={"cmd": "ls"})
HISTORY: list[ChatMessage] = [
    ChatMessageUser(content="list files"),
    ChatMessageAssistant(content="", tool_calls=[CALL]),
]
TOOLS = [ToolInfo(name="bash", description="Run a command.")]

STEPS: list[SentinelStep] = [
    ModelInputStep(
        model="mockllm/model",
        conversation="c",
        input=HISTORY[:1],
        history=HISTORY[:1],
        tools=TOOLS,
        tool_choice="auto",
        config=GenerateConfig(),
    ),
    ModelOutputStep(
        model="mockllm/model",
        conversation="c",
        input=HISTORY[:1],
        history=HISTORY[:1],
        tools=TOOLS,
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_message(HISTORY[1]),
    ),
    ToolCallStep(
        conversation="c",
        message="",
        call=CALL,
        view=ToolCallView(),
        input=HISTORY[:1],
        history=HISTORY,
        tools=TOOLS,
    ),
    ToolResultStep(
        conversation="c",
        message="",
        call=CALL,
        result=ChatMessageTool(content="a\nb", tool_call_id="call_1"),
        output="a\nb",
        view=ToolCallView(),
        input=None,
        history=HISTORY,
        tools=None,
        truncated=Truncation(original_bytes=100, limit_bytes=3),
    ),
]


def test_a_call_with_nothing_registered_raises() -> None:
    with pytest.raises(PrerequisiteError, match="inspect_sentinel"):
        sentinel_implementation()


def test_registering_the_same_implementation_again_does_nothing() -> None:
    implementation = FakeImplementation()
    register_sentinel(implementation)
    register_sentinel(implementation)
    assert sentinel_implementation() is implementation


def test_registering_a_different_implementation_raises() -> None:
    first = FakeImplementation()
    register_sentinel(first)
    with pytest.raises(RuntimeError, match="already registered"):
        register_sentinel(FakeImplementation())
    assert sentinel_implementation() is first


@pytest.mark.parametrize("step", STEPS, ids=lambda step: step.stage)
async def test_a_fake_implementation_runs_each_stage(step: SentinelStep) -> None:
    fake: SentinelImplementation = FakeImplementation()
    register_sentinel(fake)
    implementation = sentinel_implementation()
    root = implementation.resolve(["fake/monitor"])
    assert step.stage in implementation.watched_stages(root)

    host = FakeHost()
    verdict = await implementation.run(root, host, step)

    assert verdict == SentinelVerdict(action="reject", message="no")
    assert host.asked == [
        (step, ["approve", "reject"], [SentinelEscalation("monitor", "high")])
    ]
    assert [(r.path, r.suspicion) for r in host.records] == [("monitor", 0.9)]
