from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

import inspect_ai.agent._react as react_module
from inspect_ai.agent import Agent, AgentState
from inspect_ai.model import ChatMessageUser, ModelOutput
from inspect_ai.util._checkpoint import Attempt


class _ResumeForScoringCheckpointer:
    def __init__(self) -> None:
        self.tracked: list[str] = []
        self.ticks = 0

    @property
    def attempt(self) -> Attempt:
        return Attempt.RESUME_FOR_SCORING

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
    def attempt(self) -> Attempt:
        return Attempt.INITIAL


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
