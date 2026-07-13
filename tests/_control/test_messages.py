"""Unit tests for the control-channel per-sample messages helpers.

The per-message projection is a pure function over `ChatMessage`s, exercised
directly. The end-to-end `sample_messages` (live `TaskState` vs terminal
recorder/log source, tail windowing) is exercised by monkeypatching the two
sources the way `test_events.py` does.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai._control.messages import _content_summary, _project, sample_messages
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
    ChatMessageUser,
)
from inspect_ai.tool._tool_call import ToolCall, ToolCallError

# --- projection -----------------------------------------------------------


def test_project_compact_user_message() -> None:
    out = _project(ChatMessageUser(id="m1", content="hello there"), 0, full=False)
    assert out["index"] == 0
    assert out["id"] == "m1"
    assert out["role"] == "user"
    assert out["content"] == "hello there"
    # a plain user message has no tool-call / tool fields
    assert "tool_calls" not in out


def test_project_compact_assistant_with_tool_calls() -> None:
    message = ChatMessageAssistant(
        id="a1",
        content="calling a tool",
        tool_calls=[
            ToolCall(id="c1", function="search", arguments={"query": "weather"})
        ],
    )
    out = _project(message, 3, full=False)
    assert out["role"] == "assistant"
    assert out["content"] == "calling a tool"
    [call] = out["tool_calls"]
    assert call["function"] == "search"
    assert "weather" in call["arguments"]


def test_project_compact_tool_message_with_error() -> None:
    message = ChatMessageTool(
        id="t1",
        content="stack trace…",
        function="search",
        error=ToolCallError(type="unknown", message="boom"),
    )
    out = _project(message, 4, full=False)
    assert out["role"] == "tool"
    assert out["function"] == "search"
    assert out["error"] == "boom"


def test_project_full_is_raw_dump() -> None:
    out = _project(ChatMessageUser(id="m1", content="hi"), 2, full=True)
    # raw form keeps the full model dump, plus the injected index
    assert out["index"] == 2
    assert out["role"] == "user"
    assert out["content"] == "hi"


def test_content_summary_summarizes_non_text_items() -> None:
    message = ChatMessageUser(
        content=[
            ContentText(text="look at this"),
            ContentImage(image="data:image/png;base64,AAAA"),
        ]
    )
    summary = _content_summary(message)
    assert "look at this" in summary
    # the image is summarized, not dumped as base64
    assert "[image]" in summary
    assert "base64" not in summary


def test_content_summary_truncates_long_text() -> None:
    message = ChatMessageUser(content="x" * 1000)
    summary = _content_summary(message)
    assert len(summary) < 1000
    assert summary.endswith("…")


# --- running source (live TaskState) --------------------------------------


def _fake_running_sample(messages: list[Any], *, completed: bool = False) -> Any:
    """A minimal stand-in for an in-flight ``ActiveSample`` carrying a state."""
    return SimpleNamespace(
        eval_id="e1",
        epoch=1,
        sample=SimpleNamespace(id=1),
        live_state=SimpleNamespace(messages=messages),
        completed=object() if completed else None,
    )


async def test_running_sample_serves_live_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod

    messages = [
        ChatMessageSystem(content="be helpful"),
        ChatMessageUser(content="hi"),
        ChatMessageAssistant(content="hello"),
    ]
    monkeypatch.setattr(
        samples_mod, "active_samples", lambda: [_fake_running_sample(messages)]
    )

    page = await sample_messages("e1", "1", 1)
    assert page is not None
    assert page["status"] == "running"
    assert page["count"] == 3
    assert [m["role"] for m in page["messages"]] == ["system", "user", "assistant"]
    # indices are absolute
    assert [m["index"] for m in page["messages"]] == [0, 1, 2]


async def test_running_sample_tail_windows_from_the_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod

    messages = [ChatMessageUser(content=f"m{i}") for i in range(10)]
    monkeypatch.setattr(
        samples_mod, "active_samples", lambda: [_fake_running_sample(messages)]
    )

    page = await sample_messages("e1", "1", 1, tail=3)
    assert page is not None
    # count is the full conversation length; only the tail is projected, with
    # its absolute indices preserved
    assert page["count"] == 10
    assert [m["index"] for m in page["messages"]] == [7, 8, 9]
    assert [m["content"] for m in page["messages"]] == ["m7", "m8", "m9"]


async def test_missing_sample_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import inspect_ai._control.state as state_mod
    import inspect_ai.log._samples as samples_mod

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    async def no_sample(*args: Any, **kwargs: Any) -> Any:
        return None

    monkeypatch.setattr(state_mod, "_full_sample", no_sample)

    assert await sample_messages("e1", "nope", 1) is None


# --- terminal source (recorder / log) -------------------------------------


async def test_terminal_sample_serves_logged_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log._log import EvalSample

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    sample = EvalSample(
        id="s1",
        epoch=1,
        input="question",
        target="answer",
        messages=[
            ChatMessageUser(content="question"),
            ChatMessageAssistant(content="answer"),
        ],
    )

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        return sample if str(id) == "s1" and epoch == 1 else None

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page = await sample_messages("e1", "s1", 1)
        assert page is not None
        assert page["status"] == "completed"
        assert page["count"] == 2
        assert [m["role"] for m in page["messages"]] == ["user", "assistant"]
    finally:
        clear_all_eval_states()


async def test_terminal_errored_sample_reports_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log._log import EvalError, EvalSample

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    sample = EvalSample(
        id="s1",
        epoch=1,
        input="q",
        target="t",
        messages=[ChatMessageUser(content="q")],
        error=EvalError(message="boom", traceback="", traceback_ansi=""),
    )

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        return sample

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page = await sample_messages("e1", "s1", 1)
        assert page is not None
        assert page["status"] == "error"
    finally:
        clear_all_eval_states()
