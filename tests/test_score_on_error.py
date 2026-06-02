from pathlib import Path

import anyio
from test_helpers.utils import failing_solver_deterministic

from inspect_ai import Task, eval
from inspect_ai._eval.task.run import PreviousError, eval_log_sample_source
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState
from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint


@scorer(metrics=[mean(), stderr()])
def constant_scorer(value: float = 1.0) -> Scorer:
    """Trivial scorer that returns a fixed value, even on partial state."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=value)

    return score


def _make_task(
    should_fail: list[bool],
    *,
    n_samples: int | None = None,
    score_on_error: bool | None = None,
    fail_on_error: bool | float | None = None,
) -> Task:
    samples = n_samples if n_samples is not None else len(should_fail)
    return Task(
        dataset=MemoryDataset(
            [Sample(id=i + 1, input="hi", target="hi") for i in range(samples)]
        ),
        solver=failing_solver_deterministic(should_fail),
        scorer=constant_scorer(),
        score_on_error=score_on_error,
        fail_on_error=fail_on_error,
    )


def test_score_on_error_basic():
    log = eval(_make_task([True]), score_on_error=True, fail_on_error=False)[0]
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert sample.scores is not None and len(sample.scores) > 0


def test_score_on_error_disabled_default_behavior():
    log = eval(_make_task([True]), fail_on_error=False)[0]
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert not sample.scores


def test_score_on_error_default_fail_on_error_marks_error():
    # default fail_on_error=True means any error fails the eval log status,
    # but with score_on_error the eval doesn't crash mid-run and the sample
    # is scored.
    log = eval(_make_task([True]), score_on_error=True)[0]
    assert log.status == "error"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert sample.scores is not None and len(sample.scores) > 0


def test_score_on_error_with_no_fail_on_error_clean_status():
    log = eval(_make_task([True]), score_on_error=True, fail_on_error=False)[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert sample.scores is not None and len(sample.scores) > 0


def test_score_on_error_with_threshold_below_fails():
    # 4 of 10 samples error (40%), threshold 70% → success, all errored scored
    should_fail = [True] * 4 + [False] * 6
    log = eval(
        _make_task(should_fail),
        score_on_error=True,
        fail_on_error=0.7,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    errored = [s for s in log.samples if s.error is not None]
    assert len(errored) == 4
    for s in errored:
        assert s.scores is not None and len(s.scores) > 0


def test_score_on_error_with_threshold_above_fails():
    # 7 of 10 samples error (70%), threshold 30% → error, all errored still scored
    should_fail = [True] * 7 + [False] * 3
    log = eval(
        _make_task(should_fail),
        score_on_error=True,
        fail_on_error=0.3,
    )[0]
    assert log.status == "error"
    assert log.samples is not None
    errored = [s for s in log.samples if s.error is not None]
    assert len(errored) == 7
    for s in errored:
        assert s.scores is not None and len(s.scores) > 0


def test_score_on_error_with_retry_intermediate_not_scored():
    # 1 sample, solver fails twice, succeeds on third attempt: only the
    # successful final attempt is scored; intermediate errored attempts NOT scored.
    log = eval(
        _make_task([True, True, False], n_samples=1),
        score_on_error=True,
        retry_on_error=2,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is None
    assert len(sample.error_retries) == 2
    assert sample.scores is not None and len(sample.scores) > 0


def test_score_on_error_with_retry_final_attempt_scored():
    # 1 sample, always-failing solver: after retries exhausted the final
    # attempt is scored.
    log = eval(
        _make_task([True, True, True], n_samples=1),
        score_on_error=True,
        retry_on_error=2,
        fail_on_error=False,
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert len(sample.error_retries) == 2
    assert sample.scores is not None and len(sample.scores) > 0


def test_score_on_error_via_task_arg():
    log = eval(
        _make_task([True], score_on_error=True, fail_on_error=False),
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert sample.scores is not None and len(sample.scores) > 0


def test_score_on_error_eval_arg_overrides_task():
    # Task says score_on_error=False but eval call says True → eval wins
    task = _make_task([True], score_on_error=False, fail_on_error=False)
    log = eval(task, score_on_error=True)[0]
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is not None
    assert sample.scores is not None and len(sample.scores) > 0


def test_score_on_error_sample_source_seeds_retry_for_errored():
    # Run a real eval producing an errored-but-scored sample, then feed the
    # log to eval_log_sample_source — for an errored sample it returns a
    # PreviousError carrying the prior error's retry history (so eval_set
    # retries re-run it from scratch but seed error_retries with the prior
    # error, surfacing the retry on the re-run sample).
    log = eval(_make_task([True]), score_on_error=True, fail_on_error=False)[0]
    assert log.samples is not None
    errored_sample = log.samples[0]
    assert errored_sample.error is not None
    assert errored_sample.scores is not None and len(errored_sample.scores) > 0

    dataset = MemoryDataset([Sample(id=errored_sample.id, input="hi", target="hi")])
    source = eval_log_sample_source(log, None, dataset)

    async def call() -> object:
        return await source(errored_sample.id, errored_sample.epoch)

    result = anyio.run(call)
    assert isinstance(result, PreviousError)
    assert result.sample.id == errored_sample.id
    assert result.sample.error is not None
    assert result.sample.error.message == errored_sample.error.message


def test_eval_log_sample_source_resume_when_checkpoint_exists(tmp_path: Path) -> None:
    # errored sample + sidecar on disk → factory returns ResumeCheckpoint
    log = eval(_make_task([True]), score_on_error=True, fail_on_error=False)[0]
    assert log.samples is not None
    errored_sample = log.samples[0]

    eval_ckpt_dir = tmp_path / "eval.checkpoints"
    sample_dir = eval_ckpt_dir / f"{errored_sample.id}__{errored_sample.epoch}"
    sample_dir.mkdir(parents=True)
    (sample_dir / "ckpt-00001.json").write_text("{}")

    dataset = MemoryDataset([Sample(id=errored_sample.id, input="hi", target="hi")])
    source = eval_log_sample_source(log, None, dataset, str(eval_ckpt_dir))

    async def call() -> object:
        async with AsyncFilesystem():
            return await source(errored_sample.id, errored_sample.epoch)

    result = anyio.run(call)
    assert isinstance(result, ResumeCheckpoint)
    assert result.sample_checkpoints_dir == str(sample_dir)


def test_eval_log_sample_source_no_resume_when_sidecar_absent(tmp_path: Path) -> None:
    # errored sample + no sidecar → no checkpoint resume, so the factory
    # falls back to a PreviousError seeding the re-run's error_retries
    log = eval(_make_task([True]), score_on_error=True, fail_on_error=False)[0]
    assert log.samples is not None
    errored_sample = log.samples[0]

    eval_ckpt_dir = tmp_path / "eval.checkpoints"
    # intentionally do not create any sidecar

    dataset = MemoryDataset([Sample(id=errored_sample.id, input="hi", target="hi")])
    source = eval_log_sample_source(log, None, dataset, str(eval_ckpt_dir))

    async def call() -> object:
        async with AsyncFilesystem():
            return await source(errored_sample.id, errored_sample.epoch)

    result = anyio.run(call)
    assert isinstance(result, PreviousError)
    assert result.sample.error is not None
