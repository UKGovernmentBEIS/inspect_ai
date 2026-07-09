"""Tests for the control-channel modify-limits directive: ``limits``.

Covers the directive function in ``inspect_ai._control.limits`` (resolved
through the task_id-keyed sample-semaphore registry and the process-global
sandbox-limiter registry), the server routes that wrap it, and the CLI rendering helper.
"""

import asyncio

import httpx
import pytest
from test_helpers.utils import register_adaptive_controller as _register_controller

from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    register_eval,
)
from inspect_ai._control.limits import task_limits
from inspect_ai.util._concurrency import (
    AdaptiveConcurrencyController,
    ResizableLimiter,
    ResizableSemaphore,
    init_concurrency,
    register_sandbox_limiter,
    register_subprocess_limiter,
    register_task_sample_semaphore,
)


@pytest.fixture(autouse=True)
def _clear_states():
    clear_all_eval_states()
    init_concurrency()  # resets the sandbox-limiter registry
    yield
    clear_all_eval_states()
    init_concurrency()


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


async def test_limits_set_max_subprocesses() -> None:
    subprocs = ResizableSemaphore("subprocesses", 8, True)
    register_subprocess_limiter(subprocs)
    register_eval("e1", 5, task_id="t1")

    result = await task_limits("t1", max_subprocesses=4)
    assert result is not None
    assert subprocs.concurrency == 4
    assert result["max_subprocesses"] == {"limit": 4, "in_use": 0}
    assert result["requested"] == {"max_subprocesses": 4}


async def test_limits_max_subprocesses_not_adjustable_warns() -> None:
    register_eval("e1", 5, task_id="t1")  # no subprocess has run in this process

    result = await task_limits("t1", max_subprocesses=4)
    assert result is not None
    assert result["max_subprocesses"] is None
    assert any("max_subprocesses is not adjustable" in w for w in result["warnings"])


async def test_limits_max_subprocesses_dry_run_does_not_apply() -> None:
    subprocs = ResizableSemaphore("subprocesses", 8, True)
    register_subprocess_limiter(subprocs)
    register_eval("e1", 5, task_id="t1")

    result = await task_limits("t1", max_subprocesses=2, dry_run=True)
    assert result is not None
    assert result["dry_run"] is True
    assert result["requested"] == {"max_subprocesses": 2}
    # view reflects the current (unchanged) value, and nothing was applied
    assert result["max_subprocesses"] == {"limit": 8, "in_use": 0}
    assert subprocs.concurrency == 8


async def test_limits_all_knobs() -> None:
    """All concurrency knobs land in one request (per-task and process-global)."""
    limiter = ResizableLimiter(10)
    docker = ResizableSemaphore("docker", 4, True)
    subprocs = ResizableSemaphore("subprocesses", 8, True)
    register_eval("e1", 5, task_id="t1")
    register_task_sample_semaphore("t1", limiter)
    register_sandbox_limiter("docker", docker)
    register_subprocess_limiter(subprocs)
    ctrl = await _register_controller(max=100, start=50)

    result = await task_limits(
        "t1", max_samples=15, max_sandboxes=6, max_subprocesses=12, max_connections=30
    )
    assert result is not None
    assert limiter.limit == 15
    assert docker.concurrency == 6
    assert subprocs.concurrency == 12
    # ceiling lowered and live limit clamped down to it
    assert (ctrl.max, ctrl.concurrency) == (30, 30)
    a = result["adaptive"][0]
    assert (a["max"], a["limit"]) == (30, 30)
    assert result["requested"] == {
        "max_samples": 15,
        "max_sandboxes": 6,
        "max_subprocesses": 12,
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


async def test_process_limits_set_max_subprocesses() -> None:
    from inspect_ai._control.limits import process_limits

    subprocs = ResizableSemaphore("subprocesses", 8, True)
    register_subprocess_limiter(subprocs)
    result = await process_limits(max_subprocesses=16)
    assert subprocs.concurrency == 16
    assert result["requested"] == {"max_subprocesses": 16}
    assert result["max_subprocesses"] == {"limit": 16, "in_use": 0}


async def test_process_limits_max_subprocesses_not_adjustable_warns() -> None:
    from inspect_ai._control.limits import process_limits

    result = await process_limits(max_subprocesses=16)  # no subprocess has run
    assert result["max_subprocesses"] is None
    assert any("max_subprocesses is not adjustable" in w for w in result["warnings"])


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


async def test_process_limits_route_patch_max_subprocesses() -> None:
    """max_subprocesses rides the process /config route like the other knobs."""
    subprocs = ResizableSemaphore("subprocesses", 8, True)
    register_subprocess_limiter(subprocs)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        got = await client.get("/config")
        assert got.status_code == 200, got.text
        assert got.json()["max_subprocesses"] == {"limit": 8, "in_use": 0}

        patched = await client.patch("/config", params={"max_subprocesses": 3})
        assert patched.status_code == 200, patched.text
        assert patched.json()["max_subprocesses"] == {"limit": 3, "in_use": 0}
        assert subprocs.concurrency == 3

        bad = await client.patch("/config", params={"max_subprocesses": 0})
        assert bad.status_code == 400
        assert "max_subprocesses" in bad.json()["error"]


async def test_limits_route_patch_max_subprocesses_task_keyed() -> None:
    """max_subprocesses also rides the task config route (process-scoped knob)."""
    subprocs = ResizableSemaphore("subprocesses", 8, True)
    register_subprocess_limiter(subprocs)
    register_eval("e1", 5, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        patched = await client.patch("/tasks/t1/config", params={"max_subprocesses": 5})
        assert patched.status_code == 200, patched.text
        assert patched.json()["max_subprocesses"] == {"limit": 5, "in_use": 0}
        assert subprocs.concurrency == 5


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
    assert "max samples [task]:         20 (5 in use)" in out
    assert "max sandboxes [process]:    docker 8 (3 in use)" in out


def test_print_config_max_subprocesses(capsys: pytest.CaptureFixture[str]) -> None:
    """An active subprocess limiter renders its limit; a dry-run set an arrow."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": True,
            "knobs": {
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_subprocesses": {"scope": "process", "limit": 16, "in_use": 9},
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": {"max_subprocesses": 4},
            "warnings": [],
            "notes": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "max subprocesses [process]: 16 → 4 (9 in use)" in out


def test_print_config_max_subprocesses_inactive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run with no subprocess limiter yet renders the knob as inactive."""
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "dry_run": False,
            "knobs": {
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_subprocesses": {"scope": "process"},
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "max subprocesses [process]: inactive (no subprocess has run yet)" in out


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
    assert "max sandboxes [process]:    none in effect" in out
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
    assert "max samples [task]:         20 → 40 (0 in use)" in out
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
    assert "max samples [task]:         20 (0 in use)" in out
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
    assert "max samples [task]:         tracks adaptive connections (see below)" in out
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
    assert "max samples [task]:         per task (pass a task to view/set)" in out
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
    assert "log buffer [task]:          10 samples (2 pending)" in out
    assert "shared sync [task]:         off" in out
    assert "note: --max-connections applies process-wide." in out


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
