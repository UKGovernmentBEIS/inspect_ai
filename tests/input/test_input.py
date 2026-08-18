from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.schema import ElicitationSchema

from inspect_ai.util import (
    InputRequest,
    InputResult,
    request_input,
)
from inspect_ai.util._input import builtin as builtin_module
from inspect_ai.util._notify import apprise_scope

SCHEMA = ElicitationSchema()


# -- types -----------------------------------------------------------------


async def test_input_result_construction() -> None:
    r = InputResult(outcome="accepted", content={"answer": "yes"})
    assert r.outcome == "accepted"
    assert r.content == {"answer": "yes"}

    r2 = InputResult(outcome="cancelled")
    assert r2.outcome == "cancelled"
    assert r2.content is None


async def test_input_request_construction() -> None:
    req = InputRequest(message="hi", schema=SCHEMA)
    assert req.message == "hi"
    assert req.schema is SCHEMA


# -- orchestrator: builtin dispatch ---------------------------------------


async def test_empty_config_dispatches_to_console_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dispatch falls through to console without ACP or panel."""
    sentinel = InputResult(outcome="accepted", content={"from": "console"})
    called = 0

    from inspect_ai.util._input import console as console_module

    async def fake_console_handler(request: InputRequest) -> InputResult:
        nonlocal called
        called += 1
        return sentinel

    monkeypatch.setattr(console_module, "console_handler", fake_console_handler)

    result = await request_input(message="hello", schema=SCHEMA)
    assert result is sentinel
    assert called == 1


async def test_dispatch_builtin_prefers_acp_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When acp_handler returns a result, panel/console are not invoked."""
    from inspect_ai.util._input import acp as acp_module
    from inspect_ai.util._input import console as console_module

    acp_sentinel = InputResult(outcome="accepted", content={"from": "acp"})
    console_called = 0

    async def fake_acp_handler(request: InputRequest) -> InputResult | None:
        return acp_sentinel

    async def fake_console_handler(request: InputRequest) -> InputResult:
        nonlocal console_called
        console_called += 1
        return InputResult(outcome="accepted", content={"from": "console"})

    monkeypatch.setattr(acp_module, "acp_handler", fake_acp_handler)
    monkeypatch.setattr(console_module, "console_handler", fake_console_handler)

    result = await request_input(message="hello", schema=SCHEMA)
    assert result is acp_sentinel
    assert console_called == 0


async def test_dispatch_builtin_falls_through_when_acp_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When acp_handler returns None, dispatch continues to panel/console."""
    from inspect_ai.util._input import acp as acp_module
    from inspect_ai.util._input import console as console_module

    console_sentinel = InputResult(outcome="accepted", content={"from": "console"})

    async def fake_acp_handler(request: InputRequest) -> InputResult | None:
        return None

    async def fake_console_handler(request: InputRequest) -> InputResult:
        return console_sentinel

    monkeypatch.setattr(acp_module, "acp_handler", fake_acp_handler)
    monkeypatch.setattr(console_module, "console_handler", fake_console_handler)

    result = await request_input(message="hello", schema=SCHEMA)
    assert result is console_sentinel


# -- notification firing --------------------------------------------------


async def test_request_input_fires_notify_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """request_input fires notify() before dispatch when Apprise is active."""
    sentinel = InputResult(outcome="accepted")

    async def fake_dispatch(request: InputRequest) -> InputResult:
        return sentinel

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    fake_apprise = MagicMock()
    fake_apprise.notify = MagicMock(return_value=True)

    with apprise_scope(fake_apprise):
        result = await request_input(message="What's your name?", schema=SCHEMA)

    assert result is sentinel
    fake_apprise.notify.assert_called_once()
    kwargs = fake_apprise.notify.call_args.kwargs
    # No active sample in this test → default title is `Inspect Agent`
    # and the body is the unmodified message.
    assert kwargs.get("body") == "What's your name?"
    assert kwargs.get("title") == "Inspect Agent"


async def test_request_input_no_notify_when_apprise_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """request_input runs dispatch without any notification call when Apprise is off."""
    sentinel = InputResult(outcome="accepted")

    async def fake_dispatch(request: InputRequest) -> InputResult:
        return sentinel

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    # Ensure no Apprise scope leaks in from another test.
    with apprise_scope(None):
        result = await request_input(message="hi", schema=SCHEMA)

    assert result is sentinel


# -- transcript ------------------------------------------------------------


async def test_request_input_emits_input_event_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from acp.schema import ElicitationStringPropertySchema

    captured: list[Any] = []

    def fake_event(self: Any, event: Any) -> None:
        captured.append(event)

    from inspect_ai.log import _transcript as transcript_module

    monkeypatch.setattr(transcript_module.Transcript, "_event", fake_event)

    async def fake_dispatch(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted", content={"name": "alice"})

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(
                type="string", description="Your name"
            )
        },
        required=["name"],
    )
    result = await request_input(message="What is your name?", schema=schema)

    assert result.outcome == "accepted"
    events = [e for e in captured if getattr(e, "event", None) == "input"]
    assert len(events) == 1
    ev = events[0]
    assert ev.message == "What is your name?"
    assert ev.outcome == "accepted"
    assert ev.content == {"name": "alice"}
    assert ev.fields and len(ev.fields) == 1
    assert ev.fields[0].name == "name"
    assert ev.fields[0].type == "string"
    assert ev.fields[0].description == "Your name"
    assert "What is your name?" in ev.input
    assert "name: alice" in ev.input


async def test_request_input_emits_input_event_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    def fake_event(self: Any, event: Any) -> None:
        captured.append(event)

    from inspect_ai.log import _transcript as transcript_module

    monkeypatch.setattr(transcript_module.Transcript, "_event", fake_event)

    async def fake_dispatch(request: InputRequest) -> InputResult:
        return InputResult(outcome="declined")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    await request_input(message="q?", schema=SCHEMA)

    events = [e for e in captured if getattr(e, "event", None) == "input"]
    assert len(events) == 1
    assert events[0].outcome == "declined"
    assert events[0].content is None
    assert "[declined]" in events[0].input
