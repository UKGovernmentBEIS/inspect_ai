"""Tests for the control-channel cancel directives (phase 3).

Covers the directive functions in ``inspect_ai._control.cancel`` (task cancel:
task-keyed, resolved to the latest attempt's registered ``TaskCancel``; sample
cancel: interrupt via ``ActiveSample.interrupt``) and the server routes that
wrap them (``POST /tasks/<id>/cancel``, ``POST /evals/<id>/sample/cancel``).
"""

from typing import Any, Literal

import httpx
import pytest
from test_helpers.live_eval_data import FakeLiveEvalData

from inspect_ai._control.cancel import cancel_sample, cancel_task
from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    get_eval_state,
    mark_eval_retry_pending,
    record_sample_errored,
    register_completed_eval,
    register_eval,
)
from inspect_ai._display.core.display import CancelType, TaskCancel


@pytest.fixture(autouse=True)
def _clear_states():
    clear_all_eval_states()
    yield
    clear_all_eval_states()


class _FakeTaskCancel(TaskCancel):
    """A ``TaskCancel`` whose fired cancel types are recorded, not applied."""

    def __init__(self, can_retry: bool = False) -> None:
        self.fired: list[CancelType] = []

        def _fire(cancel_type: CancelType) -> None:
            self.fired.append(cancel_type)
            self.cancel_type = cancel_type

        super().__init__(can_retry=can_retry, cancel_task=_fire)


class _FakeActiveSample:
    """The slice of ``ActiveSample`` the sample-cancel directive touches."""

    class _Sample:
        def __init__(self, id: str | int) -> None:
            self.id = id

    def __init__(
        self,
        *,
        eval_id: str = "e1",
        sample_id: str | int = "s1",
        epoch: int = 1,
        started: float | None = 1.0,
        completed: float | None = None,
        fails_on_error: bool = False,
    ) -> None:
        self.eval_id = eval_id
        self.sample = self._Sample(sample_id)
        self.epoch = epoch
        self.started = started
        self.completed = completed
        self.fails_on_error = fails_on_error
        self.interrupts: list[str] = []

    def interrupt(self, action: Literal["score", "error"]) -> None:
        self.interrupts.append(action)


def _patch_active_samples(
    monkeypatch: pytest.MonkeyPatch, samples: list[_FakeActiveSample]
) -> None:
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: samples)


# ---------------------------------------------------------------------------
# cancel_task directive
# ---------------------------------------------------------------------------


def test_cancel_task_fires_abort() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task="my_task", task_cancel=handle)

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["task_id"] == "t1" and result["eval_id"] == "e1"
    assert handle.fired == ["abort"]


def test_cancel_task_unknown_is_none() -> None:
    assert cancel_task("nope") is None
    assert cancel_task("") is None


def test_cancel_task_dry_run_does_not_fire() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    result = cancel_task("t1", dry_run=True)
    assert result is not None
    assert result["changed"] is True and result["dry_run"] is True
    assert handle.fired == []


def test_cancel_task_repeat_is_idempotent_noop() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    assert (cancel_task("t1") or {})["changed"] is True
    repeat = cancel_task("t1")
    assert repeat is not None
    assert repeat["changed"] is False and "already requested" in repeat["reason"]
    assert handle.fired == ["abort"]  # fired exactly once


def test_cancel_task_finished_is_idempotent_noop() -> None:
    register_completed_eval("e1", total=5, completed=5, task_id="t1", task="my_task")
    result = cancel_task("t1")
    assert result is not None
    assert result["changed"] is False and "finished" in result["reason"]


def test_cancel_task_between_attempts_rejected() -> None:
    """An errored attempt with a retry queued must not report "finished"."""
    handle = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=handle)
    record_sample_errored("e1")  # attempt finishes (completed_at stamped) ...
    mark_eval_retry_pending("e1")  # ... and the eval-set queues a retry

    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is False and "between attempts" in result["error"]
    assert handle.fired == []


def test_cancel_task_after_pending_retry_starts() -> None:
    """Once the retry registers, the task-keyed cancel targets it normally."""
    old = _FakeTaskCancel(can_retry=True)
    register_eval("e1", 1, task_id="t1", will_retry=True, task_cancel=old)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")
    new = _FakeTaskCancel()
    register_eval("e2", 1, task_id="t1", task_cancel=new)

    result = cancel_task("t1")
    assert result is not None
    assert result["changed"] is True and result["eval_id"] == "e2"
    assert old.fired == [] and new.fired == ["abort"]


def test_mark_eval_retry_pending_unregistered_is_noop() -> None:
    mark_eval_retry_pending("nope")  # must not raise


def test_cancel_task_running_without_handle_rejected() -> None:
    # a running (not finished) state with no cancel handle can't be cancelled
    register_eval("e1", 5, task_id="t1")
    result = cancel_task("t1")
    assert result is not None
    assert result["ok"] is False and "not cancellable" in result["error"]


def test_cancel_task_resolves_latest_attempt() -> None:
    """A retry registers a fresh attempt; the task-keyed cancel targets it."""
    old = _FakeTaskCancel()
    new = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=old)
    register_eval("e2", 5, task_id="t1", task_cancel=new)

    result = cancel_task("t1")
    assert result is not None and result["eval_id"] == "e2"
    assert old.fired == [] and new.fired == ["abort"]


def test_cancel_task_counts_in_flight_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    _patch_active_samples(
        monkeypatch,
        [
            _FakeActiveSample(sample_id="s1"),
            _FakeActiveSample(sample_id="s2", started=None),  # queued
            _FakeActiveSample(sample_id="s3", completed=2.0),  # finished
            _FakeActiveSample(sample_id="s4", eval_id="other"),
        ],
    )
    result = cancel_task("t1", dry_run=True)
    assert result is not None and result["in_flight"] == 1


# ---------------------------------------------------------------------------
# cancel_sample directive
# ---------------------------------------------------------------------------


async def test_cancel_sample_interrupts_with_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True and result["changed"] is True
    assert result["sample_id"] == "s1" and result["epoch"] == 1
    assert result["action"] == "score"
    assert sample.interrupts == ["score"]


async def test_cancel_sample_matches_integer_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample(sample_id=7)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "7", 1)
    assert result is not None and result["changed"] is True
    assert result["sample_id"] == 7
    assert sample.interrupts == ["score"]


async def test_cancel_sample_error_action(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample(fails_on_error=False)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, action="error")
    assert result is not None and result["changed"] is True
    assert sample.interrupts == ["error"]


async def test_cancel_sample_error_action_gated_by_fails_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample(fails_on_error=True)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, action="error")
    assert result is not None
    assert result["ok"] is False and "fail on errors" in result["error"]
    assert sample.interrupts == []


async def test_cancel_sample_dry_run_does_not_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1, dry_run=True)
    assert result is not None
    assert result["changed"] is True and result["dry_run"] is True
    assert sample.interrupts == []


async def test_cancel_sample_queued_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample(started=None)
    _patch_active_samples(monkeypatch, [sample])

    result = await cancel_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is False and "queued" in result["error"]
    assert sample.interrupts == []


async def test_cancel_sample_terminal_is_idempotent_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sample that already finished reports a clean no-op, not an error."""
    from inspect_ai.log._log import EvalSample

    _patch_active_samples(monkeypatch, [])

    async def _read(
        id: str | int, epoch: int, *, exclude_fields: set[str] | None = None
    ) -> EvalSample:
        return EvalSample(id="s1", epoch=1, input="q", target="a")

    register_eval("e1", 1, task_id="t1", live=FakeLiveEvalData(sample=_read))

    result = await cancel_sample("e1", "s1", 1)
    assert result is not None
    assert result["ok"] is True and result["changed"] is False
    assert result["status"] == "completed"


async def test_cancel_sample_unknown_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_active_samples(monkeypatch, [])
    assert await cancel_sample("e1", "s1", 1) is None


async def test_cancel_sample_epoch_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample(epoch=2)
    _patch_active_samples(monkeypatch, [sample])

    assert await cancel_sample("e1", "s1", 1) is None
    assert sample.interrupts == []


# ---------------------------------------------------------------------------
# Server routes
# ---------------------------------------------------------------------------


def _app() -> Any:
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


async def test_task_cancel_route_ok_404_and_409() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    register_eval("e2", 5, task_id="t2")  # running, but no cancel handle

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post("/tasks/t1/cancel")
        assert ok.status_code == 200, ok.text
        assert ok.json()["changed"] is True
        assert handle.fired == ["abort"]

        repeat = await client.post("/tasks/t1/cancel")
        assert repeat.status_code == 200
        assert repeat.json()["changed"] is False

        missing = await client.post("/tasks/missing/cancel")
        assert missing.status_code == 404

        rejected = await client.post("/tasks/t2/cancel")
        assert rejected.status_code == 409
        assert "not cancellable" in rejected.json()["error"]


async def test_task_cancel_route_between_attempts_409() -> None:
    register_eval("e1", 1, task_id="t1", will_retry=True)
    record_sample_errored("e1")
    mark_eval_retry_pending("e1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post("/tasks/t1/cancel")
        assert rejected.status_code == 409
        assert "between attempts" in rejected.json()["error"]


async def test_task_cancel_route_dry_run() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        dry = await client.post("/tasks/t1/cancel", params={"dry_run": True})
        assert dry.status_code == 200, dry.text
        body = dry.json()
        assert body["changed"] is True and body["dry_run"] is True
        assert handle.fired == []


async def test_sample_cancel_route(monkeypatch: pytest.MonkeyPatch) -> None:
    sample = _FakeActiveSample()
    _patch_active_samples(monkeypatch, [sample])
    register_eval("e1", 1, task_id="t1")

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        ok = await client.post(
            "/evals/e1/sample/cancel", params={"sample_id": "s1", "epoch": 1}
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["changed"] is True
        assert sample.interrupts == ["score"]

        missing = await client.post(
            "/evals/e1/sample/cancel", params={"sample_id": "nope", "epoch": 1}
        )
        assert missing.status_code == 404

        bad_action = await client.post(
            "/evals/e1/sample/cancel",
            params={"sample_id": "s1", "epoch": 1, "action": "explode"},
        )
        assert bad_action.status_code == 400
        assert "score" in bad_action.json()["error"]


async def test_sample_cancel_route_gates_error_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _FakeActiveSample(fails_on_error=True)
    _patch_active_samples(monkeypatch, [sample])

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost"
    ) as client:
        rejected = await client.post(
            "/evals/e1/sample/cancel",
            params={"sample_id": "s1", "epoch": 1, "action": "error"},
        )
        assert rejected.status_code == 409
        assert sample.interrupts == []


def test_register_eval_carries_task_cancel() -> None:
    handle = _FakeTaskCancel()
    register_eval("e1", 5, task_id="t1", task_cancel=handle)
    state = get_eval_state("e1")
    assert state is not None and state.task_cancel is handle
