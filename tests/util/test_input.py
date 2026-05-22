import sys
from typing import Any, Callable, cast

import anyio
import pytest
from acp.schema import ElicitationSchema

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

from inspect_ai._util.registry import registry_create
from inspect_ai.util._input import (
    InputConfig,
    InputHandler,
    InputNotification,
    InputNotifier,
    InputResult,
    active_input_config,
    input_config,
    input_handler,
    input_notifier,
    request_input,
)
from inspect_ai.util._input import builtin as builtin_module
from inspect_ai.util._input import request as request_module

SCHEMA = ElicitationSchema()


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
        event="posted",
        message="hi",
        schema=SCHEMA,
        sample_id="s1",
        task_name="t1",
    )
    assert n.event == "posted"
    assert n.metadata is None


# -- registry --------------------------------------------------------------


async def test_input_handler_registers_and_creates() -> None:
    @input_handler(name="test_handler_a")
    def factory(answer: str) -> InputHandler:
        async def handle(message: str, schema: ElicitationSchema) -> InputResult:
            return InputResult(outcome="accepted", content={"a": answer})

        return handle

    # snake-cased registry types return the raw factory from registry_create;
    # caller calls it with kwargs to instantiate (see scorer/_reducer/registry.py).
    factory_fn = cast(
        Callable[..., InputHandler],
        registry_create("input_handler", "test_handler_a"),
    )
    handler = factory_fn(answer="42")
    result = await handler("ignored", SCHEMA)
    assert result is not None
    assert result.outcome == "accepted"
    assert result.content == {"a": "42"}


async def test_input_notifier_registers_and_creates() -> None:
    seen: list[str] = []

    @input_notifier(name="test_notifier_a")
    def factory(channel: str) -> InputNotifier:
        async def notify(event: InputNotification) -> None:
            seen.append(f"{channel}:{event.message}")

        return notify

    factory_fn = cast(
        Callable[..., InputNotifier],
        registry_create("input_notifier", "test_notifier_a"),
    )
    notifier = factory_fn(channel="#x")
    await notifier(
        InputNotification(
            event="posted", message="m", schema=SCHEMA, sample_id="", task_name=""
        )
    )
    assert seen == ["#x:m"]


# -- orchestrator: builtin dispatch ---------------------------------------


async def test_empty_config_dispatches_to_builtin_which_raises() -> None:
    # No custom handler, no notifiers -> falls through to _dispatch_builtin
    # (Phase 1 stub raises NotImplementedError).
    with pytest.raises(BaseExceptionGroup) as exc_info:
        await request_input("hello", SCHEMA)
    assert any(isinstance(e, NotImplementedError) for e in exc_info.value.exceptions)


# -- orchestrator: custom handler outcomes --------------------------------


async def test_custom_handler_returns_result_skips_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_calls = 0

    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return InputResult(outcome="cancelled")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def handler(message: str, schema: ElicitationSchema) -> InputResult:
        return InputResult(outcome="accepted", content={"x": 1})

    with input_config(InputConfig(input_handler=handler)):
        result = await request_input("q", SCHEMA)

    assert result.outcome == "accepted"
    assert result.content == {"x": 1}
    assert dispatch_calls == 0


async def test_custom_handler_returns_none_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_calls = 0
    sentinel = InputResult(outcome="declined")

    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return sentinel

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def handler(message: str, schema: ElicitationSchema) -> InputResult | None:
        return None

    with input_config(InputConfig(input_handler=handler)):
        result = await request_input("q", SCHEMA)

    assert result is sentinel
    assert dispatch_calls == 1


async def test_custom_handler_timeout_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch_calls = 0
    sentinel = InputResult(outcome="declined")

    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
        nonlocal dispatch_calls
        dispatch_calls += 1
        return sentinel

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def slow_handler(
        message: str, schema: ElicitationSchema
    ) -> InputResult | None:
        await anyio.sleep(5)
        return InputResult(outcome="accepted")  # should never be reached

    with input_config(
        InputConfig(input_handler=slow_handler, input_handler_timeout=0.05)
    ):
        result = await request_input("q", SCHEMA)

    assert result is sentinel
    assert dispatch_calls == 1


# -- orchestrator: notifier fan-out ---------------------------------------


async def test_notifier_fanout_runs_concurrently_with_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
        return InputResult(outcome="accepted")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    started = anyio.Event()
    handler_can_proceed = anyio.Event()
    notifier_seen: list[str] = []

    async def gated_handler(
        message: str, schema: ElicitationSchema
    ) -> InputResult | None:
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
        result = await request_input("q", SCHEMA)

    assert result.outcome == "accepted"
    assert sorted(notifier_seen) == ["a", "b", "c"]


async def test_notifier_exception_logged_and_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def capture(msg: str, *args: Any, **kwargs: Any) -> None:
        captured.append(msg % args if args else msg)

    monkeypatch.setattr(request_module.logger, "warning", capture)

    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
        return InputResult(outcome="accepted")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    other_called = anyio.Event()

    async def bad_notifier(event: InputNotification) -> None:
        raise RuntimeError("boom")

    async def good_notifier(event: InputNotification) -> None:
        other_called.set()

    with input_config(InputConfig(input_notifiers=[bad_notifier, good_notifier])):
        result = await request_input("q", SCHEMA)

    assert result.outcome == "accepted"
    assert other_called.is_set()
    assert any("input notifier" in m and "boom" in m for m in captured)


async def test_notifier_timeout_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
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
            result = await request_input("q", SCHEMA)

    assert result.outcome == "accepted"
    assert fast_done.is_set()


# -- orchestrator: metadata + config scoping ------------------------------


async def test_metadata_passes_through_to_notifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
        return InputResult(outcome="accepted")

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    seen: list[dict[str, Any] | None] = []

    async def notifier(event: InputNotification) -> None:
        seen.append(event.metadata)

    md = {"thread_id": "T-123"}
    with input_config(InputConfig(input_notifiers=[notifier])):
        await request_input("q", SCHEMA, metadata=md)

    assert seen == [md]


async def test_concurrent_request_inputs_see_isolated_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_dispatch(message: str, schema: ElicitationSchema) -> InputResult:
        return InputResult(outcome="accepted", content={"from": "builtin"})

    monkeypatch.setattr(builtin_module, "_dispatch_builtin", fake_dispatch)

    async def handler_a(message: str, schema: ElicitationSchema) -> InputResult:
        await anyio.sleep(0.01)
        return InputResult(outcome="accepted", content={"from": "a"})

    async def handler_b(message: str, schema: ElicitationSchema) -> InputResult:
        await anyio.sleep(0.01)
        return InputResult(outcome="accepted", content={"from": "b"})

    results: dict[str, InputResult] = {}

    async def run_with(key: str, handler: Any) -> None:
        with input_config(InputConfig(input_handler=handler)):
            results[key] = await request_input("q", SCHEMA)

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
