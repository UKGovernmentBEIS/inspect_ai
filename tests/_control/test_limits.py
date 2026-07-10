"""Tests for the control-channel modify-limits directive: ``limits``.

Covers the directive function in ``inspect_ai._control.limits`` (resolved
through the task_id-keyed sample-semaphore registry and the process-global
sandbox-limiter registry), the server routes that wrap it, and the CLI rendering helper.
"""

import asyncio
from typing import Any, cast

import httpx
import pytest
from test_helpers.utils import register_adaptive_controller as _register_controller

from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    register_eval,
)
from inspect_ai._control.limits import task_limits
from inspect_ai.model._generate_overrides import (
    generate_config_override,
    reset_generate_config_overrides,
    set_generate_config_override,
)
from inspect_ai.util._concurrency import (
    AdaptiveConcurrencyController,
    ResizableLimiter,
    ResizableSemaphore,
    init_concurrency,
    register_sandbox_limiter,
    register_task_sample_semaphore,
)


@pytest.fixture(autouse=True)
def _clear_states():
    clear_all_eval_states()
    init_concurrency()  # resets the sandbox-limiter registry
    reset_generate_config_overrides()
    yield
    clear_all_eval_states()
    init_concurrency()
    reset_generate_config_overrides()


# ---------------------------------------------------------------------------
# Directive function
# ---------------------------------------------------------------------------


async def test_limits_read_only() -> None:
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", ResizableLimiter(20))

    result = await task_limits("t1")
    assert result is not None
    assert result["dry_run"] is False
    assert result["max_samples"] == {"limit": 20, "in_use": 0, "adjustable": True}
    assert result["max_sandboxes"] == []
    assert result["requested"] is None
    assert result["warnings"] == []


async def test_limits_set_max_samples() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", limiter)

    result = await task_limits("t1", max_samples=30)
    assert result is not None
    assert result["max_samples"]["limit"] == 30
    assert result["requested"] == {"max_samples": 30}
    # the underlying limiter was actually retuned
    assert limiter.limit == 30


async def test_limits_dry_run_does_not_apply() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", limiter)

    result = await task_limits("t1", max_samples=30, dry_run=True)
    assert result is not None
    assert result["dry_run"] is True
    assert result["requested"] == {"max_samples": 30}
    # view reflects the current (unchanged) value, and nothing was applied
    assert result["max_samples"]["limit"] == 20
    assert limiter.limit == 20


async def test_limits_max_samples_not_adjustable_warns() -> None:
    # no sample semaphore registered (reused-log task / ran no samples here)
    register_eval("e1", 5, task_id="t1")

    result = await task_limits("t1", max_samples=30)
    assert result is not None
    assert result["max_samples"] == {"adjustable": False, "tracks_adaptive": False}
    assert any("max_samples is not adjustable" in w for w in result["warnings"])


async def test_limits_adaptive_semaphore_not_adjustable() -> None:
    """A DynamicSampleLimiter registry entry (adaptive path) is not a setpoint."""
    from inspect_ai.util._concurrency import AdaptiveConcurrency, DynamicSampleLimiter

    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore(
        "t1", DynamicSampleLimiter(AdaptiveConcurrency(min=1, max=100, start=10), "k")
    )

    result = await task_limits("t1", max_samples=30)
    assert result is not None
    assert result["max_samples"] == {"adjustable": False, "tracks_adaptive": True}
    assert any("max_samples is not adjustable" in w for w in result["warnings"])
    # the never-matching "k" key also surfaces the no-controller warning
    assert any("no matching connection controller" in w for w in result["warnings"])


async def test_limits_set_max_sandboxes() -> None:
    docker = ResizableSemaphore("docker", 4, True)
    local = ResizableSemaphore("local", 2, True)
    register_sandbox_limiter("docker", docker)
    register_sandbox_limiter("local", local)
    register_eval("e1", 5, task_id="t1")

    result = await task_limits("t1", max_sandboxes=8)
    assert result is not None
    # applied to every provider's limiter
    assert docker.concurrency == 8
    assert local.concurrency == 8
    by_type = {s["type"]: s for s in result["max_sandboxes"]}
    assert by_type["docker"]["limit"] == 8
    assert by_type["local"]["limit"] == 8
    assert result["requested"] == {"max_sandboxes": 8}


async def test_limits_max_sandboxes_not_adjustable_warns() -> None:
    register_eval("e1", 5, task_id="t1")  # no sandbox limiters in effect

    result = await task_limits("t1", max_sandboxes=8)
    assert result is not None
    assert result["max_sandboxes"] == []
    assert any("max_sandboxes is not adjustable" in w for w in result["warnings"])


async def test_limits_max_sandboxes_adjustable_before_first_acquire() -> None:
    """Run startup pre-registers the sandbox limiter, so a startup retune lands.

    Regression: registration used to happen only inside the first sample's
    acquired concurrency context, so a `--max-sandboxes` issued while sandbox
    startup (image pulls can take minutes) was still running found an empty
    registry and was dropped with a factually wrong "no limit in effect"
    warning.
    """
    from inspect_ai._eval.task.sandbox import ensure_sandbox_limiter
    from inspect_ai.util._sandbox.local import LocalSandboxEnvironment

    register_eval("e1", 5, task_id="t1")
    # run-level sandbox startup (before task_init / before any sample acquires).
    # max_sandboxes is explicit, so the provider type's default is never read.
    resolved = await ensure_sandbox_limiter(LocalSandboxEnvironment, "docker", 8)
    assert resolved == 8

    result = await task_limits("t1", max_sandboxes=2)
    assert result is not None
    assert result["warnings"] == []
    assert result["max_sandboxes"] == [{"type": "docker", "limit": 2, "in_use": 0}]

    # the per-sample path re-ensures (idempotent) without resetting the retune
    assert await ensure_sandbox_limiter(LocalSandboxEnvironment, "docker", 8) == 8
    read = await task_limits("t1")
    assert read is not None
    assert read["max_sandboxes"][0]["limit"] == 2


async def test_limits_all_knobs() -> None:
    """All three knobs land in one request (per-task and process-global)."""
    limiter = ResizableLimiter(10)
    docker = ResizableSemaphore("docker", 4, True)
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", limiter)
    register_sandbox_limiter("docker", docker)
    ctrl = await _register_controller(max=100, start=50)

    result = await task_limits(
        "t1", max_samples=15, max_sandboxes=6, max_connections=30
    )
    assert result is not None
    assert limiter.limit == 15
    assert docker.concurrency == 6
    # ceiling lowered and live limit clamped down to it
    assert (ctrl.max, ctrl.concurrency) == (30, 30)
    a = result["adaptive"][0]
    assert (a["max"], a["limit"]) == (30, 30)
    assert result["requested"] == {
        "max_samples": 15,
        "max_sandboxes": 6,
        "max_connections": 30,
    }


async def test_limits_none_when_task_missing() -> None:
    assert await task_limits("nope") is None


async def test_limits_unaffected_by_retry_supersede() -> None:
    """A retry superseding an attempt doesn't disturb the task's limits.

    The directive is keyed by task_id (stable across retries) and reads the
    limiter from the task_id-keyed semaphore registry — not from any attempt's
    state — so a retry (TaskLogger.reinit → detach_eval_live + a fresh eval_id
    under the same task_id) leaves reads and retunes working unchanged.
    """
    from inspect_ai._control.eval_state import detach_eval_live

    limiter = ResizableLimiter(20)
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", limiter)
    detach_eval_live("e1")  # retry supersedes e1...
    register_eval("e2", 5, task_id="t1")  # ...and registers a fresh attempt

    result = await task_limits("t1", max_samples=2)
    assert result is not None
    assert result["max_samples"]["limit"] == 2
    assert limiter.limit == 2  # the task's (shared) limiter was retuned


async def test_limits_adaptive_read_view() -> None:
    """The adaptive path reports live controller state (read-only)."""
    register_eval("e1", 5, task_id="t1")  # adaptive path: no registered setpoint
    ctrl = await _register_controller(start=10)
    ctrl.notify_retry()  # record a scale-down: 10 -> 8 (rate_limit)

    result = await task_limits("t1")
    assert result is not None
    # no task semaphore registered in this synthetic setup — not adjustable,
    # and not claimed to track the (other) controller
    assert result["max_samples"] == {"adjustable": False, "tracks_adaptive": False}
    assert len(result["adaptive"]) == 1
    a = result["adaptive"][0]
    assert a["name"] == "openai/gpt-4"
    assert a["limit"] == 8
    assert a["in_use"] == 0
    assert a["min"] == 1
    assert a["max"] == 100
    last = a["recent_changes"][-1]
    assert (last["from"], last["to"], last["reason"]) == (10, 8, "rate_limit")
    assert isinstance(last["at"], float)


async def test_limits_adaptive_empty_when_no_controllers() -> None:
    register_eval("e1", 5, task_id="t1")
    result = await task_limits("t1")
    assert result is not None
    assert result["adaptive"] == []


async def test_limits_max_connections_not_adjustable_without_controllers() -> None:
    register_eval("e1", 5, task_id="t1")  # no adaptive controllers registered
    result = await task_limits("t1", max_connections=30)
    assert result is not None
    assert result["adaptive"] == []
    assert any("max_connections is not adjustable" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Process-level directive (no eval)
# ---------------------------------------------------------------------------


async def test_process_limits_read_only() -> None:
    from inspect_ai._control.limits import process_limits

    result = await process_limits()  # no eval, no controllers/sandboxes
    assert result["dry_run"] is False
    assert result["max_sandboxes"] == []
    assert result["adaptive"] == []
    assert result["requested"] is None
    assert result["warnings"] == []
    # process view carries no per-eval max_samples
    assert "max_samples" not in result


async def test_process_limits_set_max_connections() -> None:
    from inspect_ai._control.limits import process_limits

    ctrl = await _register_controller(max=100, start=50)
    result = await process_limits(max_connections=30)
    assert result["requested"] == {"max_connections": 30}
    assert ctrl.max == 30
    assert result["adaptive"][0]["max"] == 30


async def test_process_limits_set_max_sandboxes() -> None:
    from inspect_ai._control.limits import process_limits

    docker = ResizableSemaphore("docker", 4, True)
    register_sandbox_limiter("docker", docker)
    result = await process_limits(max_sandboxes=8)
    assert docker.concurrency == 8
    assert result["requested"] == {"max_sandboxes": 8}
    assert result["max_sandboxes"][0]["limit"] == 8


async def test_process_limits_dry_run_does_not_apply() -> None:
    from inspect_ai._control.limits import process_limits

    ctrl = await _register_controller(max=100, start=50)
    result = await process_limits(max_connections=30, dry_run=True)
    assert result["dry_run"] is True
    assert result["requested"] == {"max_connections": 30}
    assert ctrl.max == 100  # unchanged


def test_match_controllers_semantics() -> None:
    """--model matching: name-start or leaf (after '/') prefix, exact wins."""
    from inspect_ai._control.limits import _match_controllers
    from inspect_ai.util._concurrency import AdaptiveConcurrency

    def ctrl(name: str) -> AdaptiveConcurrencyController:
        return AdaptiveConcurrencyController(name, AdaptiveConcurrency(), visible=True)

    ctrls = [ctrl("openai/gpt-4"), ctrl("openai/gpt-4-turbo"), ctrl("anthropic/claude")]

    def names(query: str) -> set[str]:
        return {c.name for c in _match_controllers(ctrls, query)}

    assert names("openai") == {"openai/gpt-4", "openai/gpt-4-turbo"}  # name prefix
    assert names("claude") == {"anthropic/claude"}  # leaf prefix
    assert names("gpt-4") == {"openai/gpt-4"}  # exact leaf wins over prefix
    assert names("mistral") == set()  # no match


async def test_process_limits_model_filter_scopes_set() -> None:
    """--model restricts max_connections (and the view) to matching controllers."""
    from inspect_ai._control.limits import process_limits

    gpt = await _register_controller(name="openai/gpt-4", max=100, start=50)
    claude = await _register_controller(name="anthropic/claude", max=100, start=50)

    result = await process_limits(max_connections=30, model="claude")
    assert (claude.max, claude.concurrency) == (30, 30)  # matched → retuned
    assert (gpt.max, gpt.concurrency) == (100, 50)  # unmatched → untouched
    assert [a["name"] for a in result["adaptive"]] == ["anthropic/claude"]


async def test_process_limits_model_no_match_warns() -> None:
    from inspect_ai._control.limits import process_limits

    gpt = await _register_controller(name="openai/gpt-4", max=100, start=50)
    result = await process_limits(max_connections=30, model="mistral")
    assert gpt.max == 100  # nothing retuned
    assert result["adaptive"] == []
    assert any(
        "no adaptive connection controller matches model 'mistral'" in w
        for w in result["warnings"]
    )


# ---------------------------------------------------------------------------
# Retry-loop overrides (timeout / attempt_timeout / max_retries)
# ---------------------------------------------------------------------------


async def test_retry_overrides_default_view() -> None:
    from inspect_ai._control.limits import process_limits

    result = await process_limits()
    assert result["retry"] == {
        "timeout": None,
        "attempt_timeout": None,
        "max_retries": None,
    }


async def test_retry_overrides_set_and_clear() -> None:
    from inspect_ai._control.limits import process_limits

    result = await process_limits(timeout=120, attempt_timeout=30, max_retries=5)
    assert result["requested"] == {
        "timeout": 120,
        "attempt_timeout": 30,
        "max_retries": 5,
    }
    assert result["retry"] == {"timeout": 120, "attempt_timeout": 30, "max_retries": 5}
    # always adjustable — the override layer exists regardless of launch config
    assert result["warnings"] == []
    assert generate_config_override("timeout") == 120

    # "clear" removes an override (restoring launch config); the others stand
    result = await process_limits(timeout="clear")
    assert result["requested"] == {"timeout": "clear"}
    assert result["retry"] == {"timeout": None, "attempt_timeout": 30, "max_retries": 5}
    assert generate_config_override("timeout") is None

    # 0 is a real value, not a clear — max_retries 0 = no retries (fail fast)
    result = await process_limits(max_retries=0)
    assert result["requested"] == {"max_retries": 0}
    assert result["retry"]["max_retries"] == 0
    assert generate_config_override("max_retries") == 0


async def test_retry_overrides_dry_run_does_not_apply() -> None:
    from inspect_ai._control.limits import process_limits

    result = await process_limits(max_retries=2, dry_run=True)
    assert result["dry_run"] is True
    assert result["requested"] == {"max_retries": 2}
    assert result["retry"]["max_retries"] is None
    assert generate_config_override("max_retries") is None


async def test_retry_overrides_via_task_limits() -> None:
    register_eval("e1", 5, task_id="t1")

    result = await task_limits("t1", max_retries=3)
    assert result is not None
    assert result["retry"]["max_retries"] == 3
    assert result["requested"] == {"max_retries": 3}
    assert generate_config_override("max_retries") == 3


def test_retry_override_reaches_live_retry_stop() -> None:
    """The tenacity stop reads the overrides on every post-attempt check.

    This is the mid-flight contract: a retune reaches generate calls already
    inside their retry loop (whose stop was built before the override was
    set), not just calls started afterwards.
    """
    from tenacity import RetryCallState

    from inspect_ai.model._retry import model_retry_config

    retry_config = model_retry_config(
        "m",
        None,  # max_retries: launch config says retry forever
        None,  # timeout
        lambda ex: True,
        lambda ex: None,
        lambda name, rs: None,
    )
    stop = retry_config["stop"]
    assert callable(stop)

    state = RetryCallState(cast(Any, None), None, (), {})
    state.attempt_number = 5
    assert stop(state) is False  # no override → retry forever

    # max_retries counts retries: N allows N+1 attempts, so after attempt 5
    # an override of 4 (4 retries = 5 attempts) stops and 5 keeps going
    set_generate_config_override("max_retries", 4)
    assert stop(state) is True  # the same stop now fails fast
    set_generate_config_override("max_retries", 5)
    assert stop(state) is False
    set_generate_config_override("max_retries", None)
    assert stop(state) is False

    # 0 = no retries: stop right after the first attempt
    set_generate_config_override("max_retries", 0)
    state.attempt_number = 1
    assert stop(state) is True
    set_generate_config_override("max_retries", None)
    state.attempt_number = 5

    # total-budget override (timeout) keys on seconds_since_start
    state.outcome_timestamp = state.start_time + 100
    set_generate_config_override("timeout", 50)
    assert stop(state) is True
    set_generate_config_override("timeout", 200)
    assert stop(state) is False


def test_retry_override_defers_to_base_config_when_unset() -> None:
    """Without an override the per-call config's own values stand."""
    from tenacity import RetryCallState

    from inspect_ai.model._retry import model_retry_config

    retry_config = model_retry_config(
        "m",
        2,  # max_retries from the call's GenerateConfig
        300,  # timeout
        lambda ex: True,
        lambda ex: None,
        lambda name, rs: None,
    )
    stop = retry_config["stop"]
    assert callable(stop)

    state = RetryCallState(cast(Any, None), None, (), {})
    state.attempt_number = 2
    assert stop(state) is False  # 2 retries = 3 attempts; attempt 2 continues
    state.attempt_number = 3
    assert stop(state) is True  # base max_retries exhausted after attempt 3

    # raising the override rides out what the base config would stop
    set_generate_config_override("max_retries", 10)
    assert stop(state) is False
    state.outcome_timestamp = state.start_time + 400
    assert stop(state) is True  # base timeout still stands (not overridden)


def test_retry_override_opted_out_for_batch_admin_ops() -> None:
    """`live_overrides=False` (batcher admin ops) pins the launch config.

    A fail-fast retune must not reach batch create/poll retry loops — an
    exhausted admin-op retry fails every request riding the batch.
    """
    from tenacity import RetryCallState

    from inspect_ai.model._retry import model_retry_config

    retry_config = model_retry_config(
        "m",
        None,  # launch config: retry forever
        None,
        lambda ex: True,
        lambda ex: None,
        lambda name, rs: None,
        live_overrides=False,
    )
    stop = retry_config["stop"]
    assert callable(stop)

    state = RetryCallState(cast(Any, None), None, (), {})
    state.attempt_number = 5
    set_generate_config_override("max_retries", 0)
    set_generate_config_override("timeout", 1)
    state.outcome_timestamp = state.start_time + 100
    assert stop(state) is False  # the fail-fast retune is ignored


def test_set_generate_config_override_rejects_negative() -> None:
    """A programmatic sign bug errors loudly instead of becoming an override."""
    with pytest.raises(ValueError, match="max_retries"):
        set_generate_config_override("max_retries", -1)
    assert generate_config_override("max_retries") is None


# ---------------------------------------------------------------------------
# Server routes
# ---------------------------------------------------------------------------


def _app():
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_limits_route_get_and_patch() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", limiter)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        got = await client.get("/tasks/t1/config")
        assert got.status_code == 200, got.text
        assert got.json()["max_samples"]["limit"] == 20

        patched = await client.patch("/tasks/t1/config", params={"max_samples": 40})
        assert patched.status_code == 200, patched.text
        assert patched.json()["max_samples"]["limit"] == 40
        assert limiter.limit == 40

        missing = await client.get("/tasks/missing/config")
        assert missing.status_code == 404


async def test_limits_route_rejects_below_one() -> None:
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", ResizableLimiter(20))

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        bad = await client.patch("/tasks/t1/config", params={"max_samples": 0})
        assert bad.status_code == 400
        assert "max_samples" in bad.json()["error"]


async def test_limits_route_patch_max_connections() -> None:
    register_eval("e1", 5, task_id="t1")
    ctrl = await _register_controller(max=100, start=50)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        patched = await client.patch("/tasks/t1/config", params={"max_connections": 25})
        assert patched.status_code == 200, patched.text
        assert patched.json()["adaptive"][0]["max"] == 25
        assert ctrl.max == 25

        bad = await client.patch("/tasks/t1/config", params={"max_connections": 0})
        assert bad.status_code == 400
        assert "max_connections" in bad.json()["error"]


async def test_process_limits_route_get_and_patch() -> None:
    """The process-level /config route reads and retunes without an eval id."""
    ctrl = await _register_controller(max=100, start=50)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        got = await client.get("/config")
        assert got.status_code == 200, got.text
        assert got.json()["adaptive"][0]["max"] == 100
        assert "max_samples" not in got.json()  # process view, no per-eval knob

        patched = await client.patch("/config", params={"max_connections": 25})
        assert patched.status_code == 200, patched.text
        assert patched.json()["adaptive"][0]["max"] == 25
        assert ctrl.max == 25

        bad = await client.patch("/config", params={"max_connections": 0})
        assert bad.status_code == 400
        assert "max_connections" in bad.json()["error"]


async def test_process_limits_route_model_filter() -> None:
    """`model` on the /config route scopes the retune to matching controllers."""
    gpt = await _register_controller(name="openai/gpt-4", max=100, start=50)
    claude = await _register_controller(name="anthropic/claude", max=100, start=50)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        patched = await client.patch(
            "/config", params={"max_connections": 20, "model": "gpt-4"}
        )
        assert patched.status_code == 200, patched.text
        assert [a["name"] for a in patched.json()["adaptive"]] == ["openai/gpt-4"]
        assert gpt.max == 20
        assert claude.max == 100  # unmatched, untouched


async def test_retry_overrides_route_patch_and_clear() -> None:
    register_eval("e1", 5, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        patched = await client.patch("/config", params={"timeout": 90})
        assert patched.status_code == 200, patched.text
        assert patched.json()["retry"]["timeout"] == 90
        assert generate_config_override("timeout") == 90

        # the task-keyed route carries the same knobs (process-scoped)
        patched = await client.patch("/tasks/t1/config", params={"max_retries": 4})
        assert patched.status_code == 200, patched.text
        assert patched.json()["retry"] == {
            "timeout": 90,
            "attempt_timeout": None,
            "max_retries": 4,
        }

        # "clear" removes an override; 0 is a real value (no retries)
        cleared = await client.patch("/config", params={"timeout": "clear"})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["retry"]["timeout"] is None
        zeroed = await client.patch("/config", params={"max_retries": 0})
        assert zeroed.status_code == 200, zeroed.text
        assert zeroed.json()["retry"]["max_retries"] == 0
        assert generate_config_override("max_retries") == 0
        restored = await client.patch("/config", params={"max_retries": 4})
        assert restored.status_code == 200, restored.text

        # negative and non-integer garbage are rejected on both routes
        for path in ("/config", "/tasks/t1/config"):
            for bad_value in ("-1", "unset"):
                bad = await client.patch(path, params={"attempt_timeout": bad_value})
                assert bad.status_code == 400
                assert "attempt_timeout" in bad.json()["error"]

        # GET reports the active overrides too
        got = await client.get("/config")
        assert got.status_code == 200, got.text
        assert got.json()["retry"]["max_retries"] == 4


async def test_limits_route_dry_run() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", limiter)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        resp = await client.patch(
            "/tasks/t1/config", params={"max_samples": 40, "dry_run": True}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["dry_run"] is True
        assert resp.json()["max_samples"]["limit"] == 20  # unchanged
        assert limiter.limit == 20


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def test_print_config(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                "max_samples": {
                    "scope": "task",
                    "limit": 20,
                    "in_use": 5,
                    "adjustable": True,
                },
                "max_sandboxes": {
                    "scope": "process",
                    "providers": [{"type": "docker", "limit": 8, "in_use": 3}],
                },
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "config:" in out
    # every knob line is labeled with its scope
    assert "max samples [task]:      20 (5 in use)" in out
    assert "max sandboxes [process]: docker 8 (3 in use)" in out


def test_print_config_updated_with_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                "max_samples": {"scope": "task", "adjustable": False},
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": {"max_samples": 30},
            "warnings": ["max_samples is not adjustable for this eval."],
            "notes": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "updated config:" in out
    assert "not adjustable" in out
    assert "max sandboxes [process]: none in effect" in out
    assert "! max_samples is not adjustable" in out


def test_print_config_dry_run_header(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": True,
            "knobs": {
                "max_samples": {
                    "scope": "task",
                    "limit": 20,
                    "in_use": 0,
                    "adjustable": True,
                },
                "max_sandboxes": {
                    "scope": "process",
                    "providers": [{"type": "docker", "limit": 8, "in_use": 3}],
                },
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": {"max_samples": 40, "max_sandboxes": 16},
            "warnings": [],
            "notes": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "would-be config (dry run):" in out
    # would-be values render as `current → requested`, not the bare current value
    assert "max samples [task]:      20 → 40 (0 in use)" in out
    assert "docker 8 → 16 (3 in use)" in out


def test_print_config_dry_run_unchanged_knob_has_no_arrow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dry-run knob whose requested value equals the current one shows no arrow."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": True,
            "knobs": {
                "max_samples": {
                    "scope": "task",
                    "limit": 20,
                    "in_use": 0,
                    "adjustable": True,
                },
                # max_sandboxes not in `requested` (only max_samples was set),
                # and max_samples requested == current, so no line gets an arrow.
                "max_sandboxes": {
                    "scope": "process",
                    "providers": [{"type": "docker", "limit": 8, "in_use": 3}],
                },
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": {"max_samples": 20},
            "warnings": [],
            "notes": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "→" not in out
    assert "max samples [task]:      20 (0 in use)" in out
    assert "docker 8 (3 in use)" in out


def test_print_config_adaptive_section(capsys: pytest.CaptureFixture[str]) -> None:
    """The adaptive path renders live controller state instead of a bare label."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                "max_samples": {
                    "scope": "task",
                    "adjustable": False,
                    "tracks_adaptive": True,
                },
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {
                    "scope": "process",
                    "adaptive": [
                        {
                            "name": "openai/gpt-4",
                            "limit": 45,
                            "in_use": 40,
                            "min": 1,
                            "max": 100,
                            "recent_changes": [
                                {
                                    "at": 1.0,
                                    "from": 50,
                                    "to": 45,
                                    "reason": "rate_limit",
                                },
                            ],
                        }
                    ],
                },
            },
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "max samples [task]:      tracks adaptive connections (see below)" in out
    assert "adaptive connections [process]:" in out
    assert "openai/gpt-4: 45 (40 in use), range 1–100" in out
    assert "last: 50→45 rate_limit" in out


def test_print_config_adaptive_dry_run_shows_ceiling_arrow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dry-run max_connections renders the ceiling as `max → requested`."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": True,
            "knobs": {
                "max_samples": {"scope": "task", "adjustable": False},
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {
                    "scope": "process",
                    "adaptive": [
                        {
                            "name": "openai/gpt-4",
                            "limit": 50,
                            "in_use": 10,
                            "min": 1,
                            "max": 100,
                            "recent_changes": [],
                        }
                    ],
                },
            },
            "requested": {"max_connections": 30},
            "warnings": [],
            "notes": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "range 1–100 → 30" in out


def test_print_config_process_scope(capsys: pytest.CaptureFixture[str]) -> None:
    """The process-level view (no max_samples knob) shows max samples as per-task."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                # note: no "max_samples" knob → process scope
                "max_sandboxes": {
                    "scope": "process",
                    "providers": [{"type": "docker", "limit": 8, "in_use": 3}],
                },
                "max_connections": {
                    "scope": "process",
                    "adaptive": [
                        {
                            "name": "openai/gpt-4",
                            "limit": 45,
                            "in_use": 40,
                            "min": 1,
                            "max": 100,
                            "recent_changes": [],
                        }
                    ],
                },
            },
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "max samples [task]:      per task (pass a task to view/set)" in out
    assert "docker 8 (3 in use)" in out
    assert "adaptive connections [process]:" in out


def test_print_config_buffer_knobs_and_notes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The absorbed buffer knobs render with their task scope; notes print last."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {"scope": "process", "adaptive": []},
                "log_buffer": {"scope": "task", "value": 10, "pending": 2},
                "log_shared": {"scope": "task", "value": None},
            },
            "requested": None,
            "warnings": [],
            "notes": ["--max-connections applies process-wide."],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "log buffer [task]:       10 samples (2 pending)" in out
    assert "shared sync [task]:      off" in out
    assert "note: --max-connections applies process-wide." in out


def test_print_config_retry_overrides(capsys: pytest.CaptureFixture[str]) -> None:
    """Retry knobs render the live override, or 'launch config' when unset."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {"scope": "process", "adaptive": []},
                "timeout": {"scope": "process", "override": None},
                "attempt_timeout": {"scope": "process", "override": 30},
                "max_retries": {"scope": "process", "override": None},
            },
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "  timeout [process]:       launch config" in out
    assert "  attempt timeout [process]: 30s (override)" in out
    assert "  max retries [process]:   launch config" in out


def test_print_config_retry_overrides_dry_run_arrows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dry-run renders `current → requested`, with `clear` shown as its meaning."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": True,
            "knobs": {
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {"scope": "process", "adaptive": []},
                "timeout": {"scope": "process", "override": None},
                "attempt_timeout": {"scope": "process", "override": 30},
                "max_retries": {"scope": "process", "override": None},
            },
            "requested": {"timeout": 300, "attempt_timeout": "clear", "max_retries": 0},
            "warnings": [],
            "notes": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "launch config → 300s" in out
    assert "30s (override) → launch config" in out
    # 0 is a real requested value (no retries), not a clear
    assert "  max retries [process]:   launch config → 0\n" in out


def test_print_config_omits_retry_knobs_for_older_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An older server's view has no retry knobs — no line, no value claim."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "timeout" not in out
    assert "max retries" not in out


def test_process_scope_note() -> None:
    """The process-wide scope note fires only for a global knob in a multi-eval process."""
    from inspect_ai._cli.ctl import _process_scope_note

    # nothing set → no note
    assert _process_scope_note([], 3) is None
    # global knob set but process hosts a single eval → distinction invisible
    assert _process_scope_note(["--max-connections"], 1) is None
    # single global knob across a multi-eval process → singular "applies"
    note = _process_scope_note(["--max-connections"], 3)
    assert note == (
        "--max-connections applies process-wide — every active task in "
        "this process is affected."
    )
    # both global knobs → plural "apply", joined
    note = _process_scope_note(["--max-connections", "--max-sandboxes"], 2)
    assert (
        note
        == "--max-connections and --max-sandboxes apply process-wide — every active task in this process is affected."
    )


def test_limits_route_error_becomes_500() -> None:
    """A directive exception surfaces as the structured 500."""
    from inspect_ai._control import server as server_mod

    # a limiter whose setter raises when applied
    class _Boom(ResizableLimiter):
        @property
        def limit(self) -> int:
            return 5

        @limit.setter
        def limit(self, value: int) -> None:
            raise RuntimeError("boom")

    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", _Boom(5))

    async def scenario() -> httpx.Response:
        app = server_mod.ControlServer(run_id="test")._build_app()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            return await client.patch("/tasks/t1/config", params={"max_samples": 9})

    response = asyncio.run(scenario())
    assert response.status_code == 500
    assert "boom" in response.json()["error"]
