"""Unit tests for the per-sample lifecycle helpers in `_eval/task/run.py`.

`SampleTerminalReporter` owns the side-effects every terminal sample-run
outcome must perform (see design/sample-lifecycle.md's side-effect table);
these tests pin that matrix — including the counter → slot-release → metrics
order — so a change to one outcome's bookkeeping is deliberate.
`SampleAttempt` derives the retry budget from the accrued error history; the
tests pin that derivation.
"""

from typing import Any

import pytest

import inspect_ai._eval.task.run as run_module
from inspect_ai._control.eval_state import (
    clear_all_eval_states,
    get_eval_state,
    register_eval,
)
from inspect_ai._eval.task.run import (
    SampleAttempt,
    SampleTerminalReporter,
    _SampleRetry,
    _SampleUsage,
)
from inspect_ai.log._log import EvalRetryError
from inspect_ai.scorer._metric import SampleScore, Score

EVAL_ID = "reporter-test-eval"


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_all_eval_states()
    register_eval(EVAL_ID, 4)
    yield
    clear_all_eval_states()


class ReporterHarness:
    """A reporter wired to recording stubs, plus the calls it made.

    The `record_sample_*` module globals are wrapped (delegating to the real
    functions, so the eval-state counters still accumulate) to make the
    counter's position in the call order observable alongside the metrics
    and slot-release callbacks.
    """

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, with_slot_release: bool = True
    ) -> None:
        self.calls: list[tuple[str, Any]] = []

        for bucket in ("completed", "errored", "cancelled"):
            name = f"record_sample_{bucket}"
            original = getattr(run_module, name)

            def wrapper(
                *args: Any,
                _original: Any = original,
                _bucket: str = bucket,
                **kwargs: Any,
            ) -> None:
                self.calls.append(("counter", _bucket))
                _original(*args, **kwargs)

            monkeypatch.setattr(run_module, name, wrapper)

        self.reporter = self.new_reporter(with_slot_release)

    def new_reporter(self, with_slot_release: bool = True) -> SampleTerminalReporter:
        """A fresh reporter (a new run) wired to the same recording stubs."""

        async def sample_complete(
            sample_id: int | str, epoch: int, scores: dict[str, SampleScore]
        ) -> None:
            self.calls.append(("metrics", (sample_id, epoch, scores)))

        return SampleTerminalReporter(
            task_id=EVAL_ID,
            progress=lambda units: self.calls.append(("progress", units)),
            sample_complete=sample_complete,
            sample_terminal=(
                (lambda outcome: self.calls.append(("slot", outcome)))
                if with_slot_release
                else None
            ),
        )

    def counters(self) -> tuple[int, int, int]:
        state = get_eval_state(EVAL_ID)
        assert state is not None
        return (state.completed, state.errored, state.cancelled)

    def usage(self) -> tuple[int, int]:
        state = get_eval_state(EVAL_ID)
        assert state is not None
        return (state.total_tokens, state.total_messages)


def scores() -> dict[str, SampleScore]:
    return {"scorer": SampleScore(score=Score(value=1), sample_id="s1")}


async def test_completed_reports_counter_slot_and_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = ReporterHarness(monkeypatch)
    sample_scores = scores()

    await harness.reporter.completed(
        "s1", 1, sample_scores, started=123.0, usage=_SampleUsage(10, 3)
    )

    # the counter and slot release fire first (terminal state is stamped
    # before any user code runs), then metrics — the design doc's stated order
    assert harness.calls == [
        ("counter", "completed"),
        ("slot", "completed"),
        ("metrics", ("s1", 1, sample_scores)),
    ]
    assert harness.counters() == (1, 0, 0)
    assert harness.usage() == (10, 3)


async def test_completed_empty_scores_still_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a scoreless success reports an empty dict (progress results and the
    # display's completion count include it), unlike scores=None
    harness = ReporterHarness(monkeypatch)

    await harness.reporter.completed("s1", 1, {})

    assert ("metrics", ("s1", 1, {})) in harness.calls


async def test_completed_without_scores_skips_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the early-stop shape: terminal completed, nothing scored, no usage
    harness = ReporterHarness(monkeypatch)

    await harness.reporter.completed("s1", 1)

    assert harness.calls == [("counter", "completed"), ("slot", "completed")]
    assert harness.counters() == (1, 0, 0)
    assert harness.usage() == (0, 0)


async def test_errored_with_scores_reports_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # score_on_error: the errored sample's scores reach metrics so the log
    # and metrics never diverge
    harness = ReporterHarness(monkeypatch)
    sample_scores = scores()

    await harness.reporter.errored(
        "s1", 1, sample_scores, started=123.0, usage=_SampleUsage(7, 2)
    )

    assert harness.calls == [
        ("counter", "errored"),
        ("slot", "errored"),
        ("metrics", ("s1", 1, sample_scores)),
    ]
    assert harness.counters() == (0, 1, 0)
    assert harness.usage() == (7, 2)


async def test_errored_without_scores_skips_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the raise shape: the eval is dying, scores stay in the sample log only
    harness = ReporterHarness(monkeypatch)

    await harness.reporter.errored("s1", 1, usage=_SampleUsage(7, 2))

    assert harness.calls == [("counter", "errored"), ("slot", "errored")]
    assert harness.counters() == (0, 1, 0)


def test_cancelled_reports_counter_and_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    # cancelled carries no scores by signature — never a metric
    harness = ReporterHarness(monkeypatch)

    harness.reporter.cancelled(started=123.0, usage=_SampleUsage(5, 1))

    assert harness.calls == [("counter", "cancelled"), ("slot", "cancelled")]
    assert harness.counters() == (0, 0, 1)
    assert harness.usage() == (5, 1)


def test_cancelled_abandoned_before_start(monkeypatch: pytest.MonkeyPatch) -> None:
    # abandoned while queued: no usage, no start time — just the counter
    harness = ReporterHarness(monkeypatch)

    harness.reporter.cancelled()

    assert harness.counters() == (0, 0, 1)
    assert harness.usage() == (0, 0)


async def test_no_slot_release_for_seed_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # seed (non-injected) samples have no slot to release
    harness = ReporterHarness(monkeypatch, with_slot_release=False)

    await harness.reporter.completed("s1", 1)
    harness.new_reporter(with_slot_release=False).cancelled()

    assert harness.calls == [("counter", "completed"), ("counter", "cancelled")]
    assert harness.counters() == (1, 0, 1)


async def test_double_terminal_report_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a run goes terminal exactly once — a second report on the same
    # reporter is the double-count dual of the missed-report bug class
    harness = ReporterHarness(monkeypatch)

    await harness.reporter.completed("s1", 1)
    with pytest.raises(AssertionError):
        harness.reporter.cancelled()

    assert harness.counters() == (1, 0, 0)


async def test_raising_metrics_cannot_unbucket_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # metrics run user code (custom metrics, the early-stopping hook); a
    # raise there tears the task down but must not leave the run outside
    # every terminal bucket — under the prior metrics-first order nothing
    # had counted the run yet, so the dying task could never reach `total`
    harness = ReporterHarness(monkeypatch)

    async def raising_sample_complete(
        sample_id: int | str, epoch: int, sample_scores: dict[str, SampleScore]
    ) -> None:
        raise RuntimeError("hook failure")

    reporter = SampleTerminalReporter(
        task_id=EVAL_ID,
        progress=lambda units: None,
        sample_complete=raising_sample_complete,
    )
    with pytest.raises(RuntimeError, match="hook failure"):
        await reporter.errored("s1", 1, scores(), usage=_SampleUsage(7, 2))

    assert harness.counters() == (0, 1, 0)


async def test_completed_at_stamps_before_metrics_await() -> None:
    # the control channel's task-finished gates (task cancel, sample
    # requeue) key on `completed_at`; it must be stamped before the
    # potentially suspending metrics/early-stopping await, so those gates
    # reject operations arriving while the last sample's hook is suspended
    clear_all_eval_states()
    register_eval(EVAL_ID, 1)
    completed_at_during_metrics: list[float | None] = []

    async def observing_sample_complete(
        sample_id: int | str, epoch: int, sample_scores: dict[str, SampleScore]
    ) -> None:
        state = get_eval_state(EVAL_ID)
        assert state is not None
        completed_at_during_metrics.append(state.completed_at)

    reporter = SampleTerminalReporter(
        task_id=EVAL_ID,
        progress=lambda units: None,
        sample_complete=observing_sample_complete,
    )
    await reporter.completed("s1", 1, scores())

    assert completed_at_during_metrics and completed_at_during_metrics[0] is not None


def test_progress_ticks_one_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = ReporterHarness(monkeypatch)

    harness.reporter.progress()

    assert harness.calls == [("progress", 1)]


def retry(message: str) -> _SampleRetry:
    return _SampleRetry(
        error=EvalRetryError(message=message, traceback="", traceback_ansi=""),
        sample_uuid="uuid-1",
    )


def test_sample_attempt_budget_derives_from_errors() -> None:
    attempt = SampleAttempt(retry_limit=2)
    assert attempt.number == 1
    assert attempt.is_first
    assert attempt.retries_remaining == 2

    attempt = attempt.advance(retry("first failure"))
    assert attempt.number == 2
    assert not attempt.is_first
    assert attempt.retries_remaining == 1
    assert attempt.sample_uuid == "uuid-1"
    assert [e.message for e in attempt.errors] == ["first failure"]

    attempt = attempt.advance(retry("second failure"))
    assert attempt.retries_remaining == 0
    assert [e.message for e in attempt.errors] == ["first failure", "second failure"]


def test_sample_attempt_advance_does_not_mutate() -> None:
    first = SampleAttempt(retry_limit=1)
    second = first.advance(retry("boom"))
    assert first.errors == ()
    assert first.sample_uuid is None
    assert second is not first
