from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Literal

import pytest
from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python
from test_helpers.checkpoint import RecordingCheckpointer

import inspect_ai.agent._react as react_module
from inspect_ai.agent import Agent, AgentState
from inspect_ai.model import (
    ChatMessage,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._compaction import CompactionSummary
from inspect_ai.model._compaction._compaction import _CompactionState
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util._limited_conversation import ChatMessageList


class _ResumeForScoringCheckpointer:
    def __init__(self) -> None:
        self.tracked: list[str] = []
        self.ticks = 0

    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        return "resume_for_scoring"

    async def __aenter__(self) -> "_ResumeForScoringCheckpointer":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def track(
        self,
        key: str,
        callback: Callable[[], Any],
        initial_value: Any,
        *,
        value_type: type[Any] | None = None,
    ) -> Any:
        self.tracked.append(key)
        return initial_value

    async def tick(self) -> None:
        self.ticks += 1


class _InitialCheckpointer(_ResumeForScoringCheckpointer):
    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        return "initial"


class _ProbeContext:
    def __init__(
        self, name: str, events: list[str], value: object | None = None
    ) -> None:
        self._name = name
        self._events = events
        self._value = value if value is not None else object()

    async def __aenter__(self) -> object:
        self._events.append(f"enter:{self._name}")
        return self._value

    async def __aexit__(self, *exc: object) -> None:
        self._events.append(f"exit:{self._name}")
        return None


class _FakeAgentChannel:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def before_turn(self, _messages: object) -> list[object]:
        self._events.append("before_turn")
        return []

    @contextmanager
    def turn_scope(self) -> Iterator[None]:
        self._events.append("turn_scope")
        yield

    async def after_cancel(self, _messages: object) -> list[object]:
        raise AssertionError("agent was not interrupted")


@pytest.mark.parametrize(
    "agent_factory",
    [
        pytest.param(lambda: react_module.react(prompt=None), id="react"),
        pytest.param(
            lambda: react_module.react(prompt=None, submit=False),
            id="react_no_submit",
        ),
    ],
)
async def test_scoring_resume_skips_mcp_and_agent_channel(
    monkeypatch: pytest.MonkeyPatch,
    agent_factory: Callable[[], Agent],
) -> None:
    cp = _ResumeForScoringCheckpointer()
    events: list[str] = []

    def mcp_connection(_tools: object) -> _ProbeContext:
        events.append("call:mcp")
        return _ProbeContext("mcp", events)

    def agent_channel() -> _ProbeContext:
        events.append("call:channel")
        return _ProbeContext("channel", events)

    monkeypatch.setattr(react_module, "checkpointer", lambda: cp)
    monkeypatch.setattr(react_module, "mcp_connection", mcp_connection)
    monkeypatch.setattr(react_module, "agent_channel", agent_channel)

    agent = agent_factory()
    state = AgentState(messages=[ChatMessageUser(content="restored")])

    result = await agent(state)

    assert result is state
    assert cp.tracked == ["messages", "output"]
    assert events == []


@pytest.mark.parametrize(
    ("agent_factory", "output_factory", "tracked"),
    [
        pytest.param(
            lambda: react_module.react(prompt=None),
            lambda: ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
            ["messages", "output", "attempt_count"],
            id="react",
        ),
        pytest.param(
            lambda: react_module.react(prompt=None, submit=False),
            lambda: ModelOutput.from_content(
                model="mockllm/model",
                content="done",
            ),
            ["messages", "output"],
            id="react_no_submit",
        ),
    ],
)
async def test_initial_attempt_enters_mcp_and_agent_channel(
    monkeypatch: pytest.MonkeyPatch,
    agent_factory: Callable[[], Agent],
    output_factory: Callable[[], ModelOutput],
    tracked: list[str],
) -> None:
    cp = _InitialCheckpointer()
    events: list[str] = []
    channel = _FakeAgentChannel(events)

    def mcp_connection(_tools: object) -> _ProbeContext:
        events.append("call:mcp")
        return _ProbeContext("mcp", events)

    def agent_channel() -> _ProbeContext:
        events.append("call:channel")
        return _ProbeContext("channel", events, channel)

    async def agent_generate(
        _model: object,
        state: AgentState,
        _tools: object,
        _retry_refusals: object,
        _compact: object,
    ) -> AgentState:
        output = output_factory()
        state.output = output
        state.messages.append(output.message)
        return state

    monkeypatch.setattr(react_module, "checkpointer", lambda: cp)
    monkeypatch.setattr(react_module, "mcp_connection", mcp_connection)
    monkeypatch.setattr(react_module, "agent_channel", agent_channel)
    monkeypatch.setattr(react_module, "_agent_generate", agent_generate)

    agent = agent_factory()
    state = AgentState(messages=[ChatMessageUser(content="input")])

    result = await agent(state)

    assert result is state
    assert cp.tracked == tracked
    assert cp.ticks == 1
    assert events == [
        "call:mcp",
        "enter:mcp",
        "call:channel",
        "enter:channel",
        "before_turn",
        "turn_scope",
        "exit:channel",
        "exit:mcp",
    ]


def _patch_checkpointer(
    monkeypatch: pytest.MonkeyPatch, cp: RecordingCheckpointer
) -> None:
    @asynccontextmanager
    async def session() -> AsyncIterator[RecordingCheckpointer]:
        yield cp

    monkeypatch.setattr(react_module, "checkpointer", session)


def _words(tag: str, n: int) -> str:
    """Varied filler text (repeated single chars compress under tiktoken)."""
    return " ".join(f"{tag}{i}" for i in range(n))


class _PhaseComplete(Exception):
    """Raised by the phase-2 mock model once the input under test is captured."""


async def test_resumed_compaction_prefix_excludes_prior_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a checkpoint resume, compaction must not re-prepend the restored history.

    react() passes `state.messages` to the compaction handler as the
    always-preserve `prefix`. On a fresh run that is [system, input] — but on
    resume `cp.track("messages", ...)` has already replaced `state.messages`
    with the full restored conversation, so the entire pre-crash history
    becomes the compaction prefix. Every subsequent summary compaction then
    prepends the whole history to its output, making compaction a no-op that
    *grows* the context (summary is appended to an undiminished prefix).

    This test simulates a crashed run (mockllm runs out of outputs), round-trips
    the tracked state through JSON exactly as the checkpointer would, resumes,
    drives the conversation over the compaction threshold, and asserts the
    first post-compaction generate no longer sees the pre-crash conversation.
    """
    threshold = 2000

    def make_agent(model_output_source: object) -> Agent:
        return react_module.react(
            prompt="You are being evaluated on filler-text tasks.",
            compaction=CompactionSummary(threshold=threshold, memory=False),
            model=get_model(
                "mockllm/model",
                memoize=False,
                custom_outputs=model_output_source,
            ),
        )

    # ---- phase 1: fresh run that "crashes" mid-task (outputs run out) ----
    cp1 = RecordingCheckpointer()
    _patch_checkpointer(monkeypatch, cp1)

    agent1 = make_agent(
        [
            ModelOutput.from_content("mockllm/model", _words("alpha", 150)),
            ModelOutput.from_content("mockllm/model", _words("bravo", 150)),
        ]
    )
    state1 = AgentState(
        messages=[ChatMessageUser(content="Do the task.", source="input")]
    )
    with pytest.raises(ValueError, match="custom_outputs ran out"):
        await agent1(state1)

    # capture tracked state as a checkpoint fire would, then JSON round-trip
    snap_messages = cp1.callbacks["messages"]()
    snap_output = cp1.callbacks["output"]()
    snap_compaction = cp1.callbacks["compaction"]()
    assert isinstance(snap_messages, list) and isinstance(
        snap_compaction, _CompactionState
    )
    # sanity: the crash happened before any compaction (under threshold)
    assert not any("summary" in (m.metadata or {}) for m in snap_messages)
    assert snap_messages[0].role == "system"
    assert snap_messages[1].role == "user" and snap_messages[1].source == "input"
    pre_crash_conversation_ids = {m.id for m in snap_messages[2:]}
    assert pre_crash_conversation_ids  # assistant turns + continue prompts

    # ChatMessageList satisfies the test double's isinstance check against the
    # tracked initial value (a plain list restore is what the real
    # checkpointer produces; the wrapper is behaviorally identical here)
    restored_messages = ChatMessageList(
        TypeAdapter(list[ChatMessage]).validate_python(
            to_jsonable_python(snap_messages)
        )
    )
    restored_state = {
        "messages": restored_messages,
        "output": ModelOutput.model_validate(to_jsonable_python(snap_output)),
        "compaction": _CompactionState.model_validate(
            snap_compaction.model_dump(mode="json")
        ),
        "attempt_count": 0,
    }

    # ---- phase 2: resume, then grow past the threshold to force compaction ----
    cp2 = RecordingCheckpointer(restored=restored_state)
    _patch_checkpointer(monkeypatch, cp2)

    generate_inputs: list[list[ChatMessage]] = []
    phase2_outputs = [
        # turn 1: big assistant turn that pushes the next turn over threshold
        ModelOutput.from_content("mockllm/model", _words("charlie", 900)),
        # compaction's summarization call
        ModelOutput.from_content("mockllm/model", "Summary of the work so far."),
    ]

    def phase2_model(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        generate_inputs.append(list(input))
        if len(generate_inputs) <= len(phase2_outputs):
            return phase2_outputs[len(generate_inputs) - 1]
        # third call is the post-compaction generate — input captured, stop here
        raise _PhaseComplete()

    agent2 = make_agent(phase2_model)
    state2 = AgentState(
        messages=[ChatMessageUser(content="Do the task.", source="input")]
    )
    with pytest.raises(_PhaseComplete):
        await agent2(state2)

    assert len(generate_inputs) == 3
    # sanity: call 2 was the summarization call triggered by compaction
    assert "continuation summary" in generate_inputs[1][-1].text

    post_compaction_input = generate_inputs[2]
    # the compacted view must retain the true prefix and the summary ...
    assert any(m.role == "system" for m in post_compaction_input)
    assert any("summary" in (m.metadata or {}) for m in post_compaction_input)
    # ... but NOT the entire pre-crash conversation. On a resumed run react()
    # passes the restored history as the compaction prefix, so summary
    # compaction prepends it all back and the context can never shrink.
    leaked = [m for m in post_compaction_input if m.id in pre_crash_conversation_ids]
    assert not leaked, (
        f"post-compaction model input still contains {len(leaked)} message(s) "
        f"from the pre-crash conversation (roles: {[m.role for m in leaked]}); "
        "the resumed react() agent used the restored history as the "
        "always-preserve compaction prefix instead of [system, input]"
    )
