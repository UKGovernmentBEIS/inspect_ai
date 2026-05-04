"""Tests for inspect_scout scanner integration in eval_set.

See `design/eval-set-scanners.md` for the design.
"""

import io
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from shortuuid import uuid
from upath import UPath

from inspect_ai import Task, eval_set
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, generate, solver

# inspect_scout is an optional runtime dep; skip these tests if unavailable.
inspect_scout = pytest.importorskip("inspect_scout")

from inspect_scout import Result, Transcript, scanner  # noqa: E402

# --- scanner fixtures -------------------------------------------------------


@scanner(messages="all")
def echo_scanner():
    """Returns the transcript_id as the result value (one row per sample)."""

    async def scan(transcript: Transcript) -> Result:
        return Result(value=f"scanned:{transcript.transcript_id}")

    return scan


@scanner(messages="all")
def constant_scanner():
    """Always returns 1 (truthy)."""

    async def scan(transcript: Transcript) -> Result:
        return Result(value=1)

    return scan


@scanner(messages="all")
def failing_scanner():
    """Always raises — exercises the error-capture path."""

    async def scan(transcript: Transcript) -> Result:
        raise RuntimeError("scanner exploded")

    return scan


@scanner(messages="all", name="scanner_a")
def scanner_a():
    async def scan(transcript: Transcript) -> Result:
        return Result(value="A")

    return scan


@scanner(messages="all", name="scanner_b")
def scanner_b():
    async def scan(transcript: Transcript) -> Result:
        return Result(value="B")

    return scan


@scanner(messages="all", name="scanner_c")
def scanner_c():
    async def scan(transcript: Transcript) -> Result:
        return Result(value="C")

    return scan


# --- helpers ----------------------------------------------------------------


def _task(n_samples: int = 2) -> Task:
    return Task(
        dataset=[
            Sample(input=f"question {i}", target=str(i)) for i in range(n_samples)
        ],
        solver=generate(),
    )


def _scan_dir(log_dir: str) -> UPath:
    """Locate the single `scan_id=...` directory under log_dir/scans.

    Returns a UPath so the same helper works against both local
    `tempfile.TemporaryDirectory` paths and `s3://...` URLs.
    """
    scans = list((UPath(log_dir) / "scans").iterdir())
    assert len(scans) == 1, (
        f"expected exactly one scan dir, found {[p.name for p in scans]}"
    )
    return scans[0]


def _read_parquet(path: UPath) -> "pq.ParquetFile":
    # read into BytesIO so this works against both local files and S3
    return pq.ParquetFile(io.BytesIO(path.read_bytes()))


def _read_summary(scan_dir: UPath) -> dict:
    return json.loads((scan_dir / "_summary.json").read_text())


@contextmanager
def _log_dir(backend: str) -> Iterator[str]:
    """Yield a log dir suitable for `eval_set(log_dir=...)`.

    `backend="local"`: a `tempfile.TemporaryDirectory`.
    `backend="s3"`: a unique prefix on the moto-mocked test bucket.
    """
    if backend == "s3":
        # the `mock_s3` fixture creates the bucket; per-test prefix isolates
        # parametrized invocations from each other within a module-scoped
        # bucket
        yield f"s3://test-bucket/{uuid()}"
        return
    with tempfile.TemporaryDirectory() as d:
        yield d


# --- tests ------------------------------------------------------------------


def test_no_scanner_no_scan_dir() -> None:
    """eval_set without a scanner does not create scans/."""
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success
        assert not (Path(log_dir) / "scans").exists()


def test_scanner_writes_parquet_per_sample() -> None:
    """One row per (scanner, transcript) in the compacted parquet."""
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=_task(3),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success

        scan_dir = _scan_dir(log_dir)
        parquet = scan_dir / "echo_scanner.parquet"
        assert parquet.exists(), f"expected compacted parquet at {parquet}"

        pf = _read_parquet(parquet)
        assert pf.metadata.num_rows == 3

        table = pf.read(columns=["transcript_id", "value"])
        ids = table.column("transcript_id").to_pylist()
        values = table.column("value").to_pylist()

        # one row per distinct sample uuid
        assert len(set(ids)) == 3
        # value column reflects scanner output
        for tid, val in zip(ids, values):
            assert val == f"scanned:{tid}"


def test_scanner_summary_accurate_under_concurrency() -> None:
    """`_summary.json` reflects all samples — no lost updates under the lock."""
    n = 8
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(n),
            log_dir=log_dir,
            scanner=[constant_scanner()],
            model="mockllm/model",
            max_samples=n,  # all samples concurrent
            retry_attempts=0,
            display="none",
        )

        summary = _read_summary(_scan_dir(log_dir))
        assert summary["complete"] is True
        scanner_summary = summary["scanners"]["constant_scanner"]
        assert scanner_summary["scans"] == n
        assert scanner_summary["results"] == n  # all truthy
        assert scanner_summary["errors"] == 0


def test_multiple_scanners_each_get_a_parquet() -> None:
    """Each scanner writes its own `<name>.parquet`; summary tracks both."""
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[echo_scanner(), constant_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        assert (scan_dir / "echo_scanner.parquet").exists()
        assert (scan_dir / "constant_scanner.parquet").exists()

        summary = _read_summary(scan_dir)
        assert set(summary["scanners"].keys()) == {"echo_scanner", "constant_scanner"}
        for name in ("echo_scanner", "constant_scanner"):
            assert summary["scanners"][name]["scans"] == 2


def test_scanner_errors_captured_not_raised() -> None:
    """A scanner that raises gets an Error record; the eval still succeeds."""
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[failing_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success

        scan_dir = _scan_dir(log_dir)
        summary = _read_summary(scan_dir)
        assert summary["scanners"]["failing_scanner"]["errors"] == 2

        # parquet still gets one row per sample (with scan_error populated)
        pf = _read_parquet(scan_dir / "failing_scanner.parquet")
        assert pf.metadata.num_rows == 2
        scan_errors = pf.read(columns=["scan_error"]).column("scan_error").to_pylist()
        assert all(e is not None for e in scan_errors)


def test_eval_set_id_in_scan_dir_name() -> None:
    """`scan_id={eval_set_id}` so retries reuse the same scan dir."""
    with tempfile.TemporaryDirectory() as log_dir:
        explicit_id = "test-eval-set-fixed-id"
        eval_set(
            tasks=_task(1),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            eval_set_id=explicit_id,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        assert scan_dir.name == f"scan_id={explicit_id}"


# --- failure + resume tests -------------------------------------------------


def _first_attempt_fails():
    """Solver that fails on first attempt for each sample, succeeds after.

    State lives in a closure-captured set so a single solver instance reused
    across `eval_set` calls preserves the "already attempted" memory.
    """
    seen: set[tuple[int | str, int]] = set()

    @solver
    def factory():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            key = (state.sample_id, state.epoch)
            if key in seen:
                return state
            seen.add(key)
            raise ValueError(f"first attempt for sample {state.sample_id}")

        return solve

    return factory()


def test_scanner_consistent_state_after_failure() -> None:
    """When eval_set fails partway, finalize produces a consistent scan dir.

    Samples that errored still get scanned (one parquet row each); summary
    is written from the `finally` clause of the context manager.
    """
    n = 3
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=Task(
                dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(n)],
                solver=[_first_attempt_fails(), generate()],
            ),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        # eval_set ran out of retries with samples still failing
        assert not success

        scan_dir = _scan_dir(log_dir)
        # finalize ran (via the context manager's `finally`) so all the
        # canonical files exist
        assert (scan_dir / "_scan.json").exists()
        assert (scan_dir / "_summary.json").exists()
        parquet = scan_dir / "echo_scanner.parquet"
        assert parquet.exists()

        # one parquet row per (errored) sample
        pf = _read_parquet(parquet)
        assert pf.metadata.num_rows == n

        # summary reflects that all N samples were errored runs
        summary = _read_summary(scan_dir)
        ss = summary["scanners"]["echo_scanner"]
        assert ss["scans"] == n
        # echo_scanner returns a Result regardless, so no scanner errors —
        # the sample errors are recorded via `transcript.error`, not summary
        # `errors` (which counts scanner-side failures).
        assert ss["errors"] == 0


def test_scanner_buffer_cleaned_up_after_eval_set() -> None:
    """Scout's per-transcript buffer dir is cleaned up after eval_set.

    Compaction folds buffer contents into `<scanner>.parquet`, so leaving
    the buffer in place would bloat the OS cache for every eval_set run.
    """
    from inspect_scout._recorder.buffer import RecorderBuffer

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(3),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        buffer_dir = RecorderBuffer.buffer_dir(str(scan_dir))
        leftover = list(buffer_dir.rglob("*.parquet")) if buffer_dir.exists() else []
        assert not leftover, (
            f"buffer dir not cleaned up; leftover parquets: "
            f"{[p.relative_to(buffer_dir).as_posix() for p in leftover]}"
        )


@pytest.mark.parametrize("backend", ["local", "s3"])
def test_scanner_resume_accumulates_summary_and_only_scans_rerun_samples(
    backend: str, request: pytest.FixtureRequest
) -> None:
    """A second `eval_set` call on the same `log_dir` resumes:

    * Previously successful samples short-circuit and are not re-scanned.
    * Previously errored samples re-run and are scanned again.
    * `_summary.json` reflects the *union* of scans across both runs (it is
      not wiped on the second call).

    Runs against both a local temp dir and an S3-mocked log dir to cover
    the local `os.replace` path and the fsspec `mv` (copy+delete) path
    that scout's `sync` falls back to for object stores.
    """
    if backend == "s3":
        request.getfixturevalue("mock_s3")

    n = 3
    # one solver instance, reused across both calls — its closure state
    # remembers which samples have already been attempted
    fails_first_time = _first_attempt_fails()

    def make_task():
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(n)],
            solver=[fails_first_time, generate()],
        )

    with _log_dir(backend) as log_dir:
        # call 1: every sample fails on its first attempt. continue_on_fail
        # ensures all N samples run and log/scan their error before the eval
        # is marked as failed (without it, the eval aborts on the first error
        # and only some samples would scan, racing with cross-sample
        # parallelism — the local case happened to win that race, S3 didn't).
        success_1, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert not success_1

        scan_dir = _scan_dir(log_dir)
        # after call 1: N parquet rows (one per errored sample), summary scans=N
        assert _read_parquet(scan_dir / "echo_scanner.parquet").metadata.num_rows == n
        summary_1 = _read_summary(scan_dir)
        assert summary_1["scanners"]["echo_scanner"]["scans"] == n

        # call 2: same log_dir → eval_set picks up the same eval_set_id and
        # retries the failing task. Every sample is now in the solver's
        # `seen` set, so the second attempt succeeds.
        success_2, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert success_2
        # the scan dir is the same (same eval_set_id auto-detected from log_dir)
        assert _scan_dir(log_dir) == scan_dir

        # all N samples re-ran and re-scanned (the prior errored runs do not
        # short-circuit), so the compacted parquet has 2*N rows
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        assert pf.metadata.num_rows == 2 * n

        # summary accumulates across both calls — this is the key invariant
        summary_2 = _read_summary(scan_dir)
        ss = summary_2["scanners"]["echo_scanner"]
        assert ss["scans"] == 2 * n, (
            f"expected accumulated scans across both runs ({2 * n}), got {ss['scans']}"
        )


def test_scanner_resume_with_changed_scanner_set_fails_loudly() -> None:
    """A second eval_set call must reject a changed scanner set up front.

    Without validation, scout's `RecorderBuffer.record` would `KeyError`
    on any scanner not in the on-disk spec; that error is caught by
    `task_run_sample`'s sample-error handling and silently turns
    successful samples into errors, corrupting the eval's success result.
    `scan_eval_set_init` validates upfront and raises `PrerequisiteError`
    before any samples run.
    """
    from inspect_ai._util.error import PrerequisiteError

    n = 3
    fails_first_time = _first_attempt_fails()

    def make_task():
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(n)],
            solver=[fails_first_time, generate()],
        )

    with tempfile.TemporaryDirectory() as log_dir:
        # call 1: scanners A and B
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[scanner_a(), scanner_b()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        # capture state we expect to be unchanged after the failed call 2
        a_rows_before = _read_parquet(scan_dir / "scanner_a.parquet").metadata.num_rows
        b_rows_before = _read_parquet(scan_dir / "scanner_b.parquet").metadata.num_rows
        spec_before = json.loads((scan_dir / "_scan.json").read_text())

        # call 2: scanner_a dropped, scanner_c added → must fail before
        # running any samples
        with pytest.raises(PrerequisiteError, match="Scanner set has changed"):
            eval_set(
                tasks=make_task(),
                log_dir=log_dir,
                scanner=[scanner_b(), scanner_c()],
                model="mockllm/model",
                retry_attempts=0,
                continue_on_fail=True,
                display="none",
            )

        # the scan dir should be left untouched by the rejected call
        assert (
            _read_parquet(scan_dir / "scanner_a.parquet").metadata.num_rows
            == a_rows_before
        )
        assert (
            _read_parquet(scan_dir / "scanner_b.parquet").metadata.num_rows
            == b_rows_before
        )
        assert not (scan_dir / "scanner_c.parquet").exists()
        assert json.loads((scan_dir / "_scan.json").read_text()) == spec_before

        # the solver's `seen` set should also be untouched (no sample re-ran),
        # so `n` more failures' worth of state remains: a third call with the
        # same scanner set as call 1 still completes successfully
        success_3, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[scanner_a(), scanner_b()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert success_3
