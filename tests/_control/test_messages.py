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
    out = _project(
        ChatMessageUser(id="m1", content="hello there"), 0, content=True, full=False
    )
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
    out = _project(message, 3, content=True, full=False)
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
    out = _project(message, 4, content=True, full=False)
    assert out["role"] == "tool"
    assert out["function"] == "search"
    assert out["error"] == "boom"
    assert out["has_error"] is True


def test_project_metadata_default_withholds_free_text() -> None:
    """Without ``content`` the projection is metadata only.

    Index / role / tool-call function names / error presence, none of the
    agent-controlled text (message content, tool arguments, error messages).
    """
    out = _project(
        ChatMessageUser(id="m1", content="agent-controlled"),
        0,
        content=False,
        full=False,
    )
    assert out["role"] == "user"
    assert "content" not in out

    assistant = ChatMessageAssistant(
        id="a1",
        content="calling a tool",
        tool_calls=[
            ToolCall(id="c1", function="search", arguments={"query": "payload"})
        ],
    )
    out = _project(assistant, 1, content=False, full=False)
    assert "content" not in out
    [call] = out["tool_calls"]
    assert call["function"] == "search"
    assert "arguments" not in call

    tool = ChatMessageTool(
        id="t1",
        content="payload",
        function="search",
        error=ToolCallError(type="unknown", message="boom"),
    )
    out = _project(tool, 2, content=False, full=False)
    assert out["function"] == "search"
    assert out["has_error"] is True
    assert "content" not in out and "error" not in out


def test_project_full_is_raw_dump() -> None:
    out = _project(ChatMessageUser(id="m1", content="hi"), 2, content=False, full=True)
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

    page = await sample_messages("e1", "1", 1, tail=3, content=True)
    assert page is not None
    # count is the full conversation length; only the tail is projected, with
    # its absolute indices preserved
    assert page["count"] == 10
    assert [m["index"] for m in page["messages"]] == [7, 8, 9]
    assert [m["content"] for m in page["messages"]] == ["m7", "m8", "m9"]

    # the metadata-only default withholds the message text
    page = await sample_messages("e1", "1", 1, tail=3)
    assert page is not None
    assert all("content" not in m for m in page["messages"])


async def test_negative_tail_clamps_to_empty_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A negative tail (raw HTTP callers) is an empty window, not a crash."""
    import inspect_ai.log._samples as samples_mod

    messages = [ChatMessageUser(content=f"m{i}") for i in range(5)]
    monkeypatch.setattr(
        samples_mod, "active_samples", lambda: [_fake_running_sample(messages)]
    )

    page = await sample_messages("e1", "1", 1, tail=-3)
    assert page is not None
    # count still reports the full conversation; the window is just empty
    assert page["count"] == 5
    assert page["messages"] == []


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

    excluded: list[Any] = []

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        excluded.append(exclude_fields)
        return sample if str(id) == "s1" and epoch == 1 else None

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page = await sample_messages("e1", "s1", 1)
        assert page is not None
        assert page["status"] == "completed"
        assert page["count"] == 2
        assert [m["role"] for m in page["messages"]] == ["user", "assistant"]
        # heavy unconsumed fields are excluded from the read; the fields the
        # response is built from are not
        assert excluded == [{"events", "store", "output"}]
    finally:
        clear_all_eval_states()


async def test_terminal_sample_resolves_message_attachments(
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
        messages=[ChatMessageUser(content="attachment://abc123")],
        attachments={"abc123": "the real content"},
    )

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        return sample

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page = await sample_messages("e1", "s1", 1, content=True)
        assert page is not None
        assert page["messages"][0]["content"] == "the real content"
    finally:
        clear_all_eval_states()


async def test_terminal_source_resolved_once_across_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling a terminal sample's messages parses the sample once, not per poll.

    On the terminal path `tail` bounds the *response*, not the *read*: the
    whole-conversation parse and attachment resolution ran per request against
    an immutable source. The short-TTL cache collapses that; clearing the
    eval states (the run boundary) also drops the cache.
    """
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log._log import EvalSample

    monkeypatch.setattr(samples_mod, "active_samples", lambda: [])

    sample = EvalSample(
        id="s1",
        epoch=1,
        input="question",
        target="answer",
        messages=[ChatMessageUser(content=f"m{i}") for i in range(5)],
    )
    reads = [0]

    async def read_sample(id: Any, epoch: int, *, exclude_fields: Any = None) -> Any:
        reads[0] += 1
        return sample

    try:
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        page1 = await sample_messages("e1", "s1", 1, tail=2, content=True)
        page2 = await sample_messages("e1", "s1", 1, tail=2, content=True)
        assert page1 is not None and page2 is not None
        assert [m["content"] for m in page2["messages"]] == ["m3", "m4"]
        assert reads[0] == 1

        # the run-boundary registry clear also drops the cached source
        clear_all_eval_states()
        register_eval("e1", 1, live=FakeLiveEvalData(sample=read_sample))
        assert await sample_messages("e1", "s1", 1) is not None
        assert reads[0] == 2
    finally:
        clear_all_eval_states()


async def test_running_attempt_invalidates_other_endpoints_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observing a retry on the messages endpoint drops the events cache too.

    The mirror of the events-side test: a retry supersedes the prior
    attempt's terminal source in both projections, so the invalidation must
    reach every registered cache, not just this endpoint's.
    """
    import inspect_ai._control.events as events_mod
    import inspect_ai._control.messages as messages_mod
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.events import EventsSource

    key = ("e1", "1", 1)
    events_mod._terminal_sources.put(
        key, EventsSource(nonce="n", fetch=lambda start, limit: [], total=0, done=True)
    )

    running = _fake_running_sample([ChatMessageUser(content="retrying")])
    monkeypatch.setattr(samples_mod, "active_samples", lambda: [running])
    assert await sample_messages("e1", "1", 1) is not None

    assert events_mod._terminal_sources.get(key) is None
    assert messages_mod._terminal_sources.get(key) is None


async def test_terminal_errored_sample_reports_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._samples as samples_mod
    from inspect_ai._control.eval_state import clear_all_eval_states, register_eval
    from inspect_ai.log import EvalError, EvalSample

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
