"""Tests for the control-channel modify-limits directive: ``limits``.

Covers the directive function in ``inspect_ai._control.limits`` (resolved
through ``EvalState.sample_limiter`` and the process-global sandbox-limiter
registry), the server routes that wrap it, and the CLI rendering helper.
"""

import asyncio

import httpx
import pytest

from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    register_eval,
)
from inspect_ai._control.limits import eval_limits
from inspect_ai.util._concurrency import (
    ResizableLimiter,
    ResizableSemaphore,
    init_concurrency,
    register_sandbox_limiter,
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
    register_eval("e1", 5, sample_limiter=ResizableLimiter(20))

    result = await eval_limits("e1")
    assert result is not None
    assert result["dry_run"] is False
    assert result["max_samples"] == {"limit": 20, "in_use": 0, "adjustable": True}
    assert result["max_sandboxes"] == []
    assert result["requested"] is None
    assert result["warnings"] == []


async def test_limits_set_max_samples() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, sample_limiter=limiter)

    result = await eval_limits("e1", max_samples=30)
    assert result is not None
    assert result["max_samples"]["limit"] == 30
    assert result["requested"] == {"max_samples": 30}
    # the underlying limiter was actually retuned
    assert limiter.limit == 30


async def test_limits_dry_run_does_not_apply() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, sample_limiter=limiter)

    result = await eval_limits("e1", max_samples=30, dry_run=True)
    assert result is not None
    assert result["dry_run"] is True
    assert result["requested"] == {"max_samples": 30}
    # view reflects the current (unchanged) value, and nothing was applied
    assert result["max_samples"]["limit"] == 20
    assert limiter.limit == 20


async def test_limits_max_samples_not_adjustable_warns() -> None:
    # no sample limiter attached (the adaptive path)
    register_eval("e1", 5)

    result = await eval_limits("e1", max_samples=30)
    assert result is not None
    assert result["max_samples"] == {"adjustable": False}
    assert any("max_samples is not adjustable" in w for w in result["warnings"])


async def test_limits_set_max_sandboxes() -> None:
    docker = ResizableSemaphore("docker", 4, True)
    local = ResizableSemaphore("local", 2, True)
    register_sandbox_limiter("docker", docker)
    register_sandbox_limiter("local", local)
    register_eval("e1", 5)

    result = await eval_limits("e1", max_sandboxes=8)
    assert result is not None
    # applied to every provider's limiter
    assert docker.concurrency == 8
    assert local.concurrency == 8
    by_type = {s["type"]: s for s in result["max_sandboxes"]}
    assert by_type["docker"]["limit"] == 8
    assert by_type["local"]["limit"] == 8
    assert result["requested"] == {"max_sandboxes": 8}


async def test_limits_max_sandboxes_not_adjustable_warns() -> None:
    register_eval("e1", 5)  # no sandbox limiters in effect

    result = await eval_limits("e1", max_sandboxes=8)
    assert result is not None
    assert result["max_sandboxes"] == []
    assert any("max_sandboxes is not adjustable" in w for w in result["warnings"])


async def test_limits_both_knobs() -> None:
    limiter = ResizableLimiter(10)
    docker = ResizableSemaphore("docker", 4, True)
    register_eval("e1", 5, sample_limiter=limiter)
    register_sandbox_limiter("docker", docker)

    result = await eval_limits("e1", max_samples=15, max_sandboxes=6)
    assert result is not None
    assert limiter.limit == 15
    assert docker.concurrency == 6
    assert result["requested"] == {"max_samples": 15, "max_sandboxes": 6}


async def test_limits_none_when_eval_missing() -> None:
    assert await eval_limits("nope") is None


async def test_limits_adaptive_read_view() -> None:
    """The adaptive path reports live controller state (read-only)."""
    from inspect_ai.util._concurrency import (
        AdaptiveConcurrency,
        AdaptiveConcurrencyController,
        get_or_create_semaphore,
    )

    register_eval("e1", 5)  # adaptive path: no sample_limiter attached
    ctrl = await get_or_create_semaphore(
        "openai/gpt-4", 10, None, True, AdaptiveConcurrency(min=1, max=100, start=10)
    )
    assert isinstance(ctrl, AdaptiveConcurrencyController)
    ctrl.notify_retry()  # record a scale-down: 10 -> 8 (rate_limit)

    result = await eval_limits("e1")
    assert result is not None
    # sample concurrency tracks the controller, so max_samples has no setpoint
    assert result["max_samples"] == {"adjustable": False}
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
    register_eval("e1", 5)
    result = await eval_limits("e1")
    assert result is not None
    assert result["adaptive"] == []


# ---------------------------------------------------------------------------
# Server routes
# ---------------------------------------------------------------------------


def _app():
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_limits_route_get_and_patch() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, sample_limiter=limiter)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        got = await client.get("/evals/e1/limits")
        assert got.status_code == 200, got.text
        assert got.json()["max_samples"]["limit"] == 20

        patched = await client.patch("/evals/e1/limits", params={"max_samples": 40})
        assert patched.status_code == 200, patched.text
        assert patched.json()["max_samples"]["limit"] == 40
        assert limiter.limit == 40

        missing = await client.get("/evals/missing/limits")
        assert missing.status_code == 404


async def test_limits_route_rejects_below_one() -> None:
    register_eval("e1", 5, sample_limiter=ResizableLimiter(20))

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        bad = await client.patch("/evals/e1/limits", params={"max_samples": 0})
        assert bad.status_code == 400
        assert "max_samples" in bad.json()["error"]


async def test_limits_route_dry_run() -> None:
    limiter = ResizableLimiter(20)
    register_eval("e1", 5, sample_limiter=limiter)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        resp = await client.patch(
            "/evals/e1/limits", params={"max_samples": 40, "dry_run": True}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["dry_run"] is True
        assert resp.json()["max_samples"]["limit"] == 20  # unchanged
        assert limiter.limit == 20


# ---------------------------------------------------------------------------
# CLI rendering
# ---------------------------------------------------------------------------


def test_print_limits(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_limits

    _print_limits(
        {
            "dry_run": False,
            "max_samples": {"limit": 20, "in_use": 5, "adjustable": True},
            "max_sandboxes": [{"type": "docker", "limit": 8, "in_use": 3}],
            "requested": None,
            "warnings": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "limits:" in out
    assert "max samples:   20 (5 in use)" in out
    assert "docker 8 (3 in use)" in out


def test_print_limits_updated_with_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_ai._cli.ctl import _print_limits

    _print_limits(
        {
            "dry_run": False,
            "max_samples": {"adjustable": False},
            "max_sandboxes": [],
            "requested": {"max_samples": 30},
            "warnings": ["max_samples is not adjustable for this eval."],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "updated limits:" in out
    assert "not adjustable" in out
    assert "max sandboxes: none in effect" in out
    assert "! max_samples is not adjustable" in out


def test_print_limits_dry_run_header(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_limits

    _print_limits(
        {
            "dry_run": True,
            "max_samples": {"limit": 20, "in_use": 0, "adjustable": True},
            "max_sandboxes": [{"type": "docker", "limit": 8, "in_use": 3}],
            "requested": {"max_samples": 40, "max_sandboxes": 16},
            "warnings": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "would-be limits (dry run):" in out
    # would-be values render as `current → requested`, not the bare current value
    assert "max samples:   20 → 40 (0 in use)" in out
    assert "docker 8 → 16 (3 in use)" in out


def test_print_limits_dry_run_unchanged_knob_has_no_arrow(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dry-run knob whose requested value equals the current one shows no arrow."""
    from inspect_ai._cli.ctl import _print_limits

    _print_limits(
        {
            "dry_run": True,
            "max_samples": {"limit": 20, "in_use": 0, "adjustable": True},
            # max_sandboxes not in `requested` (only max_samples was set), and
            # max_samples requested == current, so neither line gets an arrow.
            "max_sandboxes": [{"type": "docker", "limit": 8, "in_use": 3}],
            "requested": {"max_samples": 20},
            "warnings": [],
        },
        changed=True,
    )
    out = capsys.readouterr().out
    assert "→" not in out
    assert "max samples:   20 (0 in use)" in out
    assert "docker 8 (3 in use)" in out


def test_print_limits_adaptive_section(capsys: pytest.CaptureFixture[str]) -> None:
    """The adaptive path renders live controller state instead of a bare label."""
    from inspect_ai._cli.ctl import _print_limits

    _print_limits(
        {
            "dry_run": False,
            "max_samples": {"adjustable": False},
            "max_sandboxes": [],
            "adaptive": [
                {
                    "name": "openai/gpt-4",
                    "limit": 45,
                    "in_use": 40,
                    "min": 1,
                    "max": 100,
                    "recent_changes": [
                        {"at": 1.0, "from": 50, "to": 45, "reason": "rate_limit"},
                    ],
                }
            ],
            "requested": None,
            "warnings": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "max samples:   tracks adaptive connections (see below)" in out
    assert "adaptive connections:" in out
    assert "openai/gpt-4: 45 (40 in use), range 1–100" in out
    assert "last: 50→45 rate_limit" in out


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

    register_eval("e1", 5, sample_limiter=_Boom(5))

    async def scenario() -> httpx.Response:
        app = server_mod.ControlServer(run_id="test")._build_app()
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            return await client.patch("/evals/e1/limits", params={"max_samples": 9})

    response = asyncio.run(scenario())
    assert response.status_code == 500
    assert "boom" in response.json()["error"]
