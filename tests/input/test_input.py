from typing import Any, Callable, cast

import anyio
import pytest
from acp.schema import ElicitationSchema

from inspect_ai._util.registry import registry_create
from inspect_ai.input import (
    InputConfig,
    InputHandler,
    InputNotification,
    InputNotifier,
    InputRequest,
    InputResult,
    input_handler,
    input_notifier,
    request_input,
)
from inspect_ai.input import builtin as builtin_module
from inspect_ai.input import request as request_module
from inspect_ai.input._config import active_input_config, input_config

SCHEMA = ElicitationSchema()
REQUEST = InputRequest(message="q", schema=SCHEMA)


# -- types -----------------------------------------------------------------


async def test_input_result_construction() -> None:
    r = InputResult(outcome="accepted", content={"answer": "yes"})
    assert r.outcome == "accepted"
    assert r.content == {"answer": "yes"}

    r2 = InputResult(outcome="cancelled")
    assert r2.outcome == "cancelled"
    assert r2.content is None


async def test_input_notification_construction() -> None:
    n = InputNotification(
        action="posted",
        request=InputRequest(message="hi", schema=SCHEMA),
        sample_id="s1",
        task_name="t1",
    )
    assert n.action == "posted"
    assert n.request.message == "hi"
    assert n.metadata is None


# -- registry --------------------------------------------------------------


async def test_input_handler_registers_and_creates() -> None:
    @input_handler(name="test_handler_a")
    def factory(answer: str) -> InputHandler:
        async def handle(request: InputRequest) -> InputResult:
            return InputResult(outcome="accepted", content={"a": answer})

        return handle

    # snake-cased registry types return the raw factory from registry_create;
    # caller calls it with kwargs to instantiate (see scorer/_reducer/registry.py).
    factory_fn = cast(
        Callable[..., InputHandler],
        registry_create("input_handler", "test_handler_a"),
    )
    handler = factory_fn(answer="42")
    result = await handler(REQUEST)
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"a": "42"}


async def test_input_notifier_registers_and_creates() -> None:
    seen: list[str] = []

    @input_notifier(name="test_notifier_a")
    def factory(channel: str) -> InputNotifier:
        async def notify(event: InputNotification) -> None:
            seen.append(f"{channel}:{event.request.message}")

        return notify

    factory_fn = cast(
        Callable[..., InputNotifier],
        registry_create("input_notifier", "test_notifier_a"),
    )
    notifier = factory_fn(channel="#x")
    await notifier(
        InputNotification(
            action="posted",
            request=InputRequest(message="m", schema=SCHEMA),
            sample_id="",
            task_name="",
        )
    )
    assert seen == ["#x:m"]


# -- orchestrator: builtin dispatch ---------------------------------------


async def test_empty_config_dispatches_to_console_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With no custom handler configured, request_input falls through to
    # _dispatch_builtin. With no ACP session bound (default) and no
    # Textual panel, dispatch falls through to console_handler.
    sentinel = InputResult(outcome="accepted", content={"from": "console"})
    called = 0

    from inspect_ai.input import console as console_module

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
    """When acp_handler returns a result, panel/console are not invoked.

    Pins the ACP-first selection order added in Phase 6a. If acp_handler
    returns ``None`` (no live ACP session), dispatch continues to fall
    through to panel/console — covered by the surrounding tests.
    """
    from inspect_ai.input import acp as acp_module
    from inspect_ai.input import console as console_module

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
    from inspect_ai.input import acp as acp_module
    from inspect_ai.input import console as console_module

    console_sentinel = InputResult(outcome="accepted", content={"from": "console"})

    async def fake_acp_handler(request: InputRequest) -> InputResult | None:
        return None

    async def fake_console_handler(request: InputRequest) -> InputResult:
        return console_sentinel

    monkeypatch.setattr(acp_module, "acp_handler", fake_acp_handler)
    monkeypatch.setattr(console_module, "console_handler", fake_console_handler)

    result = await request_input(message="hello", schema=SCHEMA)
    assert result is console_sentinel


# -- orchestrator: custom handler outcomes --------------------------------


async def test_custom_handler_returns_result_skips_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_calls = 0

    async def fake_dispatch(request: InputRequest) -> InputResult:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return InputResult(outcome="cancelled")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def handler(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted", content={"x": 1})

    with input_config(InputConfig(input_handler=handler)):
        result = await request_input(message="q", schema=SCHEMA)

    assert result.outcome == "accepted"
    assert result.content == {"x": 1}
    assert dispatch_calls == 0


async def test_custom_handler_returns_none_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_calls = 0
    sentinel = InputResult(outcome="declined")

    async def fake_dispatch(request: InputRequest) -> InputResult:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return sentinel

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def handler(request: InputRequest) -> InputResult | None:
        return None

    with input_config(InputConfig(input_handler=handler)):
        result = await request_input(message="q", schema=SCHEMA)

    assert result is sentinel
    assert dispatch_calls == 1


async def test_custom_handler_timeout_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_calls = 0
    sentinel = InputResult(outcome="declined")

    async def fake_dispatch(request: InputRequest) -> InputResult:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return sentinel

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def slow_handler(request: InputRequest) -> InputResult | None:
        await anyio.sleep(5)
        return InputResult(outcome="accepted")  # should never be reached

    with input_config(
        InputConfig(input_handler=slow_handler, input_handler_timeout=0.05)
    ):
        result = await request_input(message="q", schema=SCHEMA)

    assert result is sentinel
    assert dispatch_calls == 1


# -- orchestrator: notifier fan-out ---------------------------------------


async def test_notifier_fanout_runs_concurrently_with_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_dispatch(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    started = anyio.Event()
    handler_can_proceed = anyio.Event()
    notifier_seen: list[str] = []

    async def gated_handler(request: InputRequest) -> InputResult | None:
        started.set()
        await handler_can_proceed.wait()
        return None  # fall through to fake_dispatch

    async def make_notifier(label: str) -> Any:
        async def notify(event: InputNotification) -> None:
            await started.wait()  # require the handler to have started
            notifier_seen.append(label)
            if len(notifier_seen) == 3:
                handler_can_proceed.set()

        return notify

    n1 = await make_notifier("a")
    n2 = await make_notifier("b")
    n3 = await make_notifier("c")

    with input_config(
        InputConfig(input_handler=gated_handler, input_notifiers=[n1, n2, n3])
    ):
        result = await request_input(message="q", schema=SCHEMA)

    assert result.outcome == "accepted"
    assert sorted(notifier_seen) == ["a", "b", "c"]


async def test_notifier_exception_logged_and_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def capture(msg: str, *args: Any, **kwargs: Any) -> None:
        captured.append(msg % args if args else msg)

    monkeypatch.setattr(request_module.logger, "warning", capture)

    async def fake_dispatch(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    other_called = anyio.Event()

    async def bad_notifier(event: InputNotification) -> None:
        raise RuntimeError("boom")

    async def good_notifier(event: InputNotification) -> None:
        other_called.set()

    with input_config(InputConfig(input_notifiers=[bad_notifier, good_notifier])):
        result = await request_input(message="q", schema=SCHEMA)

    assert result.outcome == "accepted"
    assert other_called.is_set()
    assert any("input notifier" in m and "boom" in m for m in captured)


async def test_notifier_timeout_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    fast_done = anyio.Event()

    async def slow_notifier(event: InputNotification) -> None:
        await anyio.sleep(5)  # longer than notifier_timeout

    async def fast_notifier(event: InputNotification) -> None:
        fast_done.set()

    with input_config(
        InputConfig(
            input_notifiers=[slow_notifier, fast_notifier],
            notifier_timeout=0.05,
        )
    ):
        with anyio.fail_after(2):  # whole request shouldn't take long
            result = await request_input(message="q", schema=SCHEMA)

    assert result.outcome == "accepted"
    assert fast_done.is_set()


# -- orchestrator: metadata + config scoping ------------------------------


async def test_metadata_passes_through_to_notifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_dispatch(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    seen: list[dict[str, Any] | None] = []

    async def notifier(event: InputNotification) -> None:
        seen.append(event.metadata)

    md = {"thread_id": "T-123"}
    with input_config(InputConfig(input_notifiers=[notifier])):
        await request_input(message="q", schema=SCHEMA, metadata=md)

    assert seen == [md]


async def test_concurrent_request_inputs_see_isolated_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_dispatch(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted", content={"from": "builtin"})

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def handler_a(request: InputRequest) -> InputResult:
        await anyio.sleep(0.01)
        return InputResult(outcome="accepted", content={"from": "a"})

    async def handler_b(request: InputRequest) -> InputResult:
        await anyio.sleep(0.01)
        return InputResult(outcome="accepted", content={"from": "b"})

    results: dict[str, InputResult] = {}

    async def run_with(key: str, handler: Any) -> None:
        with input_config(InputConfig(input_handler=handler)):
            results[key] = await request_input(message="q", schema=SCHEMA)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_with, "a", handler_a)
        tg.start_soon(run_with, "b", handler_b)

    assert results["a"].content == {"from": "a"}
    assert results["b"].content == {"from": "b"}


def test_active_input_config_default_outside_scope() -> None:
    cfg = active_input_config()
    assert cfg.input_handler is None
    assert cfg.input_notifiers == []
    assert cfg.input_handler_timeout == 600.0
    assert cfg.notifier_timeout == 30.0


async def test_request_input_emits_input_event_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Capture any InputEvent emitted by request_input via the transcript.
    from acp.schema import ElicitationStringPropertySchema

    captured: list[Any] = []

    def fake_event(self: Any, event: Any) -> None:
        captured.append(event)

    from inspect_ai.log import _transcript as transcript_module

    monkeypatch.setattr(transcript_module.Transcript, "_event", fake_event)

    async def handler(request: InputRequest) -> InputResult:
        return InputResult(outcome="accepted", content={"name": "alice"})

    schema = ElicitationSchema(
        properties={
            "name": ElicitationStringPropertySchema(
                type="string", description="Your name"
            )
        },
        required=["name"],
    )
    with input_config(InputConfig(input_handler=handler)):
        result = await request_input(message="What is your name?", schema=schema)

    assert result.outcome == "accepted"
    # request_input emitted exactly one InputEvent with structured fields.
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
    # Synthesized text includes the message and the answer.
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

    async def handler(request: InputRequest) -> InputResult:
        return InputResult(outcome="declined")

    with input_config(InputConfig(input_handler=handler)):
        await request_input(message="q?", schema=SCHEMA)

    events = [e for e in captured if getattr(e, "event", None) == "input"]
    assert len(events) == 1
    assert events[0].outcome == "declined"
    assert events[0].content is None
    assert "[declined]" in events[0].input


def test_notifier_timeout_round_trip_via_spec() -> None:
    # Spec carries notifier_timeout into the resolved InputConfig...
    from inspect_ai.input import InputConfigSpec
    from inspect_ai.input._config import (
        config_from_input_config,
        resolve_input_config,
    )

    spec = InputConfigSpec(notifier_timeout=12.5)
    cfg = resolve_input_config(spec)
    assert cfg is not None
    assert cfg.notifier_timeout == 12.5

    # ...and back out via config_from_input_config for log serialization.
    round_tripped = config_from_input_config(InputConfig(notifier_timeout=7.0))
    assert round_tripped is not None
    assert round_tripped.notifier_timeout == 7.0

    # A default-only InputConfig produces no spec (nothing worth logging).
    assert config_from_input_config(InputConfig()) is None
