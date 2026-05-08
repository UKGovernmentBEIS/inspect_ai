"""Tests for inspect_scout scanner integration in eval_set.

See `design/eval-set-scanners.md` for the design.
"""

import io
import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from shortuuid import uuid
from upath import UPath

from inspect_ai import Task, eval_set, task
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


# Module-level counter so scan_resume's freshly-instantiated scanner
# (rebuilt from the on-disk spec, not the original closure) still
# increments the same counter we observe from the test.
_picky_call_count = 0


@scanner(messages="all", name="picky_scanner")
def picky_scanner():
    """Errors on even sample ids, succeeds on odd — partial-failure case."""

    async def scan(transcript: Transcript) -> Result:
        global _picky_call_count
        _picky_call_count += 1
        sample_id = int(transcript.task_id or "0")
        if sample_id % 2 == 0:
            raise RuntimeError(f"refusing sample {sample_id}")
        return Result(value=f"ok:{sample_id}")

    return scan


# File path used by `flaky_scanner` to track which transcripts it has seen.
# Module-level state would not survive scout's `load_scanner_file` re-import,
# so we use the filesystem instead. Tests reset the file before each run.
_FLAKY_MARKER = Path(tempfile.gettempdir()) / "inspect_ai_test_flaky_scanner_seen.txt"


@scanner(messages="all", name="flaky_scanner")
def flaky_scanner():
    """Errors when the marker file lists the transcript_id, else succeeds.

    Uses a file at `_FLAKY_MARKER` so state survives across module re-imports
    (scout's `load_scanner_file` re-imports the file the scanner was defined
    in when reconstructing scanners on `scan_resume`, giving any module-level
    state a fresh empty value — see `load_module` in `inspect_ai._util.module`).
    """

    async def scan(transcript: Transcript) -> Result:
        tid = transcript.transcript_id
        marker = _FLAKY_MARKER
        seen: set[str] = set()
        if marker.exists():
            seen = set(marker.read_text().splitlines()) - {""}
        if tid not in seen:
            seen.add(tid)
            marker.write_text("\n".join(sorted(seen)))
            raise RuntimeError(f"first attempt failure for {tid}")
        return Result(value=f"ok:{tid}")

    return scan


@scanner(messages="all", name="id2_only_scanner")
def id2_only_scanner():
    """Errors only on sample id "2", passes on every other sample."""

    async def scan(transcript: Transcript) -> Result:
        if transcript.task_id == "2":
            raise RuntimeError("refusing sample id 2")
        return Result(value=f"ok:{transcript.task_id}")

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
    # read into BytesIO so this works against both local files and S3.
    # invalidate the fsspec metadata cache for this path first: scout's
    # `sync` rewrites the parquet via `mv`, and s3fs would otherwise
    # raise FileExpired if it has a cached etag from a prior read.
    fs = path.fs
    if hasattr(fs, "invalidate_cache"):
        fs.invalidate_cache(path.as_posix())
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


def _first_attempt_fails_for(*sample_ids: int | str):
    """Solver that fails on first attempt only for the given sample ids."""
    seen: set[tuple[int | str, int]] = set()
    target_ids = set(sample_ids)

    @solver
    def factory():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id in target_ids:
                key = (state.sample_id, state.epoch)
                if key not in seen:
                    seen.add(key)
                    raise ValueError(f"first attempt for sample {state.sample_id}")
            return state

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


def test_s3_scan_dir_contains_expected_files(mock_s3) -> None:
    """eval_set scanning to s3:// produces the full set of scan-dir files.

    Baseline correctness regression test: a successful scan against an
    S3 log_dir must leave behind:
      * `_scan.json`     - the spec
      * `_summary.json`  - aggregated counts; `complete=True` on a clean run
      * `_errors.jsonl`  - present (empty file is allowed)
      * `<scanner>.parquet` - the compacted output
    """
    log_dir = f"s3://test-bucket/{uuid()}"
    n = 3
    success, _ = eval_set(
        tasks=_task(n),
        log_dir=log_dir,
        scanner=[echo_scanner()],
        model="mockllm/model",
        retry_attempts=0,
        display="none",
    )
    assert success

    scan_dir = _scan_dir(log_dir)

    assert (scan_dir / "_scan.json").exists()
    assert (scan_dir / "_summary.json").exists()
    assert (scan_dir / "_errors.jsonl").exists()
    assert (scan_dir / "echo_scanner.parquet").exists()

    summary = _read_summary(scan_dir)
    assert summary["complete"] is True
    assert summary["scanners"]["echo_scanner"]["scans"] == n

    parquet = _read_parquet(scan_dir / "echo_scanner.parquet")
    assert parquet.metadata.num_rows == n


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
    * Previously errored samples re-run with fresh uuids and are
      scanned again. Their original errored-run rows are *orphans*
      (the old log files were deleted by `retry_cleanup`) and the
      orphan-cleanup pass at finalize sweeps them — so the parquet
      ends up with only the surviving N rows, not 2N.
    * `_summary.json.scans` still reflects the cumulative scan-call
      count across both runs (2N) — it counts work performed, not
      surviving rows.

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

        # the parquet has just N rows — the run-1 errored-run rows are
        # orphans (their old log file was deleted by retry_cleanup) and
        # the finalize-time orphan sweep removed them, leaving only the
        # surviving rerun's rows.
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        assert pf.metadata.num_rows == n

        # summary still accumulates across both calls — it counts
        # work performed, not surviving rows
        summary_2 = _read_summary(scan_dir)
        ss = summary_2["scanners"]["echo_scanner"]
        assert ss["scans"] == 2 * n, (
            f"expected accumulated scans across both runs ({2 * n}), got {ss['scans']}"
        )


def test_eval_set_resume_only_rescans_rerun_samples_keeps_run1_errors() -> None:
    """A second `eval_set` call only re-scans the samples eval_set re-runs.

    Setup — 4 samples (ids 1..4):
    - Solver: succeeds for ids 1, 2; fails first attempt for ids 3, 4.
    - Scanner: errors only on sample id "2", passes on every other id.

    Run 1:
    - Sample 1 → eval succeeds, scanner passes.
    - Sample 2 → eval succeeds, scanner errors (refuses id 2).
    - Samples 3, 4 → eval errors first attempt; scan_eval_sample still
      runs and records each errored transcript. Scanner passes on each
      (no id-2 match).
    - Total: 4 scans, 1 scanner error (id 2), `complete=False`.

    Run 2:
    - eval_set sees samples 1, 2 already succeeded — they are NOT re-run
      and therefore NOT re-scanned (so id 2's run-1 error stays on disk).
    - eval_set retries the failing task; samples 3, 4 succeed this time.
      Those retries have new uuids → new `transcript_id`s, so they look
      like brand new transcripts to the scan dir. Scanner passes on both.
    - Total: 6 scans, still 1 scanner error from run 1, `complete=False`
      because that lone id-2 error is still present.
    """
    n = 4
    fails_3_4_first_time = _first_attempt_fails_for(3, 4)

    def make_task():
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=[fails_3_4_first_time, generate()],
        )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: 1, 2 succeed; 3, 4 error first attempt; scanner refuses id 2
        success_1, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert not success_1

        scan_dir = _scan_dir(log_dir)
        summary_1 = _read_summary(scan_dir)
        ss_1 = summary_1["scanners"]["id2_only_scanner"]
        assert ss_1["scans"] == n
        assert ss_1["errors"] == 1  # only id 2
        assert ss_1["results"] == n - 1
        assert summary_1["complete"] is False

        # run 2: only the previously-failed eval samples (3, 4) re-run.
        # 1 and 2 already succeeded, so they aren't re-scanned. The
        # retried 3, 4 succeed now and the scanner passes on each (no
        # id-2 match).
        success_2, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert success_2

        summary_2 = _read_summary(scan_dir)
        ss_2 = summary_2["scanners"]["id2_only_scanner"]
        # run 2 added exactly 2 new scans (samples 3, 4 retried)
        assert ss_2["scans"] == n + 2
        # the lone id-2 error from run 1 is still the only scanner error
        assert ss_2["errors"] == 1
        # results: (n-1) from run 1 + 2 from run 2
        assert ss_2["results"] == (n - 1) + 2
        # complete stays False because the id-2 error persists across runs
        assert summary_2["complete"] is False


def _always_fails():
    """Solver that always raises — exercises sample-level retry exhaustion."""

    @solver
    def factory():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            raise ValueError(f"always fails for sample {state.sample_id}")

        return solve

    return factory()


def test_sample_retry_scans_only_final_attempt() -> None:
    """A sample retried via `retry_on_error` is scanned exactly once.

    Failed attempts that will be retried must NOT fire `scan_eval_sample`
    (otherwise the parquet would have one row per intermediate attempt,
    none of which represent a settled outcome). Only the final attempt
    — the one that won't be retried, whether it succeeded or exhausted
    the retry budget — should produce a scan.

    This pins the existing guard in `task_run_sample`:

        if not error or (retry_on_error == 0) or (cancelled_error is not None):
            ... log_sample + scan_eval_sample ...

    Setup: a solver that always raises, `retry_on_error=2` (so 3 total
    attempts, all failing). After the eval, the parquet should have
    exactly one row for the sample.
    """
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(
                dataset=[Sample(input="q", target="t")],
                solver=[_always_fails()],
            ),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_on_error=2,
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        df = pf.read().to_pandas()
        # exactly one row even though the sample was attempted 3 times
        assert len(df) == 1, (
            f"sample retried {3} times should produce exactly 1 scan row, got {len(df)}"
        )
        # the recorded transcript reflects an errored sample (final attempt)
        assert df.iloc[0]["transcript_error"]


def test_retry_immediate_cleans_up_orphan_scans_at_finalize() -> None:
    """Task-level retry leaves scan rows only for samples in surviving logs.

    With `retry_immediate=True`, a task that errors gets re-queued
    (up to `retry_attempts` times). Within each attempt errored
    samples come back as `None` from `sample_source` and get re-run
    by the eval phase with a fresh `uuid` — so each attempt records
    its own transcript_id mid-run.

    `retry_cleanup` (default on) deletes the older log files at the
    end of the call, leaving only the latest log per task. The
    transcript_ids from the deleted logs no longer correspond to any
    `EvalSample`. `scan_finalize` sweeps those orphans from the
    compacted parquet so the scan dir matches the surviving logs.

    Setup: 1 sample, always-fails solver, `retry_immediate=True`,
    `retry_attempts=2` → 3 attempts during the run, 1 surviving log
    after retry_cleanup, 1 row in the parquet after orphan cleanup.
    """
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(
                dataset=[Sample(input="q", target="t")],
                solver=[_always_fails()],
            ),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_on_error=0,
            retry_immediate=True,
            retry_attempts=2,
            continue_on_fail=True,
            display="none",
        )

        # only the latest log file survives retry_cleanup
        eval_logs = list((Path(log_dir)).glob("*.eval"))
        assert len(eval_logs) == 1
        from inspect_ai.log import read_eval_log

        surviving_uuids = {
            s.uuid for s in (read_eval_log(str(eval_logs[0])).samples or [])
        }
        assert len(surviving_uuids) == 1

        scan_dir = _scan_dir(log_dir)
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        df = pf.read().to_pandas()
        # parquet contains exactly the live sample uuids — orphans
        # from earlier failed attempts have been swept
        assert len(df) == 1
        assert set(df["transcript_id"].tolist()) == surviving_uuids
        assert df.iloc[0]["transcript_error"]


def test_print_scan_status_clean_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`print_scan_status` prints a plain `scan complete: <path>` line."""
    from inspect_ai._eval.task.scan import print_scan_status

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(dataset=[Sample(input="q", target="t")], solver=generate()),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        capsys.readouterr()  # discard eval output

        print_scan_status(log_dir)
        out = capsys.readouterr().out
        assert "scan complete:" in out
        # plain text — no rich markup tokens
        assert "[bold]" not in out
        assert "[/bold]" not in out
        # no recovery commands on a clean run
        assert "scout scan resume" not in out
        assert "scout scan complete" not in out


def test_print_scan_status_with_scan_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A run with scanner errors prints plain copyable resume / complete commands.

    Mirrors `scout scan`'s standalone output so users can recover with
    the same `scout scan resume <path>` / `scout scan complete <path>`
    commands they'd use after a direct scout invocation. Plain text —
    no rich markup or color — to keep the trailing summary unobtrusive.
    """
    from inspect_ai._eval.task.scan import print_scan_status

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(
                dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 4)],
                solver=generate(),
            ),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        capsys.readouterr()  # discard eval output

        print_scan_status(log_dir)
        out = capsys.readouterr().out
        assert "scan errors occurred" in out
        assert "scout scan resume" in out
        assert "scout scan complete" in out
        # plain text — no rich markup tokens
        assert "[bold]" not in out
        assert "[/bold]" not in out


def test_print_scan_status_noop_when_no_scan_dir(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`print_scan_status` is a no-op when there's no scan dir under log_dir."""
    from inspect_ai._eval.task.scan import print_scan_status

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(dataset=[Sample(input="q", target="t")], solver=generate()),
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        capsys.readouterr()
        print_scan_status(log_dir)
        out = capsys.readouterr().out
        assert "scan complete:" not in out
        assert "scout scan resume" not in out


def test_eval_set_prints_scan_status_from_api(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`eval_set` itself prints scan status — not deferred to the CLI.

    The status print lives in `eval_set` (and `eval`) so it fires for
    both `inspect eval-set` and direct API calls. With a leading blank
    line, it lands cleanly after the `Completed all tasks` /
    `Did not successfully complete` message that `eval_set` renders.
    """
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(
                dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 4)],
                solver=generate(),
            ),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        out = capsys.readouterr().out
        assert "scan errors occurred" in out
        assert "scout scan resume" in out
        assert "scout scan complete" in out
        # leading blank line emitted by eval_set so the status separates
        # from the prior `Completed all tasks` / `Did not...` line
        assert "\n\n" in out


def test_eval_set_retry_cleans_up_orphan_scans_at_finalize() -> None:
    """eval_set's retry path (tenacity, `retry_immediate=False`) is symmetric.

    With `retry_immediate=False` (the default), tenacity wraps
    `try_eval` and retries it on failure. Each retry re-discovers
    logs, treats the prior failed log as a `PreviousTask`, and
    runs the failed samples again with fresh uuids — same shape as
    `retry_immediate=True`, just driven from a different layer.

    The orphan-cleanup invariant should hold equally: each attempt
    accumulates a parquet row, `retry_cleanup` deletes the older log
    files, and `scan_finalize` sweeps orphan rows whose uuids no
    longer match any surviving log.

    Setup mirrors `test_retry_immediate_cleans_up_orphan_scans_at_finalize`
    but with `retry_immediate=False`; expectation is the same: 1
    surviving log, 1 parquet row.
    """
    from inspect_ai.log import read_eval_log

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(
                dataset=[Sample(input="q", target="t")],
                solver=[_always_fails()],
            ),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_on_error=0,
            retry_immediate=False,
            retry_attempts=2,
            retry_wait=0,
            continue_on_fail=True,
            display="none",
        )

        eval_logs = list(Path(log_dir).glob("*.eval"))
        assert len(eval_logs) == 1
        surviving_uuids = {
            s.uuid for s in (read_eval_log(str(eval_logs[0])).samples or [])
        }
        assert len(surviving_uuids) == 1

        scan_dir = _scan_dir(log_dir)
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        df = pf.read().to_pandas()
        assert len(df) == 1
        assert set(df["transcript_id"].tolist()) == surviving_uuids
        assert df.iloc[0]["transcript_error"]


def test_retry_immediate_keeps_all_scans_when_retry_cleanup_disabled() -> None:
    """With `retry_cleanup=False`, old log files survive and so do their scans.

    The orphan-cleanup pass at finalize keeps any scan row whose
    transcript_id matches a sample uuid in any *surviving* eval log.
    With `retry_cleanup=False` every retry attempt's log file stays
    on disk, so every transcript_id stays live and no rows are swept.

    Setup mirrors the cleanup test (1 always-failing sample,
    `retry_immediate=True`, `retry_attempts=2`) but explicitly
    disables `retry_cleanup`. After the eval: 3 eval logs, 3 parquet
    rows, each row's transcript_id matches a sample uuid in one of
    the surviving logs.
    """
    from inspect_ai.log import read_eval_log

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=Task(
                dataset=[Sample(input="q", target="t")],
                solver=[_always_fails()],
            ),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_on_error=0,
            retry_immediate=True,
            retry_attempts=2,
            retry_cleanup=False,
            continue_on_fail=True,
            display="none",
        )

        # all 3 attempts' log files survive
        eval_logs = sorted(Path(log_dir).glob("*.eval"))
        assert len(eval_logs) == 3

        live_uuids: set[str] = set()
        for log_path in eval_logs:
            for sample in read_eval_log(str(log_path)).samples or []:
                if sample.uuid is not None:
                    live_uuids.add(sample.uuid)
        assert len(live_uuids) == 3

        # parquet preserves all 3 rows; each transcript_id is in the
        # live set
        scan_dir = _scan_dir(log_dir)
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        df = pf.read().to_pandas()
        assert len(df) == 3
        assert set(df["transcript_id"].tolist()) == live_uuids


def test_eval_set_resume_scans_when_finalize_did_not_run_cleanly() -> None:
    """Per-sample resume-scan fires when the prior finalize wasn't clean.

    Errors captured by scout (rows with `scan_error` populated) are
    intentional outcomes and aren't re-scanned. The per-sample reuse
    path only does a status check when the most recent prior call's
    finalize wrote `complete=True`. Run 1 here records a scan error
    (id 2) → run 1's finalize writes `complete=False`, which keeps
    the gate open and run 2 catches id 3's missing row.

    Setup (5 samples, ids 1..5, `max_samples=1`, scan filter
    `"error = ''"` so the scanner skips eval-errored transcripts):
    - Solver fails first attempt for ids 4, 5 (so they're not yet
      properly run after run 1; resume re-runs them).
    - Scanner errors on sample id "2".
    - `scan_eval_sample` is monkey-patched to no-op for id "3"
      (simulates a crash in the log → scan window).

    Run 1:
    - 1: solver OK + scan OK → parquet row (success)
    - 2: solver OK + scan started + errored → parquet row (with error)
    - 3: solver OK + patched scan returns early → no parquet row
    - 4, 5: solver errored → filter skips scan → no parquet rows
    Run-1 finalize sees errors=1 → writes `complete=False`.

    Run 2 (no patch):
    - 1, 2: reused as PreviousTask. Per-sample check finds them in
      the compacted parquet → no extra scan.
    - 3: reused as PreviousTask. Per-sample check finds no row →
      scan dispatched.
    - 4, 5: previously errored → re-run, solver OK, scan OK.

    Final state — parquet rows: [1, 2 (error), 3, 4, 5]; all 5 ids
    present. summary.scans == 5, summary.errors == 1 (still just id 2).
    """
    import inspect_ai._eval.task.run as run_mod
    from inspect_ai import EvalScannerConfig

    n = 5
    orig_scan_eval_sample = run_mod.scan_eval_sample

    async def skip_sample_3(eval_sample, scanner, **kwargs):  # type: ignore[no-untyped-def]
        # simulate a crash in the window between log_sample and
        # scan_eval_sample for sample id 3 — log is durable, scan
        # never starts (no parquet row created for that sample)
        if str(eval_sample.id) == "3":
            return
        return await orig_scan_eval_sample(eval_sample, scanner, **kwargs)

    fails_4_5_first_time = _first_attempt_fails_for(4, 5)

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=[fails_4_5_first_time, generate()],
        )

    config = EvalScannerConfig(
        scanners=[id2_only_scanner()],
        filter="error = ''",
    )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: monkey-patch makes id 3's scan a no-op (the "scan
        # never started" gap); scanner naturally errors on id 2 (the
        # "scan started, errored" case); ids 4, 5 fail solver and are
        # filtered out of scanning entirely.
        run_mod.scan_eval_sample = skip_sample_3
        try:
            eval_set(
                tasks=make_task(),
                log_dir=log_dir,
                scanner=config,
                model="mockllm/model",
                max_samples=1,
                retry_attempts=0,
                continue_on_fail=True,
                display="none",
            )
        finally:
            run_mod.scan_eval_sample = orig_scan_eval_sample

        scan_dir = _scan_dir(log_dir)
        summary_1 = _read_summary(scan_dir)
        ss_1 = summary_1["scanners"]["id2_only_scanner"]
        # 2 scan rows after run 1: id 1 (ok) + id 2 (error). id 3's
        # scan was patched out — its gap persists into run 2.
        assert ss_1["scans"] == 2, f"expected 2 scans after run 1, got {ss_1}"
        assert ss_1["errors"] == 1  # only id 2 errored
        assert ss_1["results"] == 1  # id 1

        # run 1's id-2 error means run-1 finalize wrote complete=False;
        # the per-sample resume-scan check stays open for run 2 without
        # any test gymnastics.
        assert summary_1["complete"] is False

        # run 2: no patch. eval_set re-runs samples that previously
        # errored at the eval level (4, 5) AND resume-scans samples
        # whose scans never landed (id 3). id 1's existing scan and
        # id 2's existing scan-error row are left alone.
        success_2, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=config,
            model="mockllm/model",
            max_samples=1,
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert success_2

        summary_2 = _read_summary(scan_dir)
        ss_2 = summary_2["scanners"]["id2_only_scanner"]
        # 5 scan rows total: 1 (ok from run 1), 2 (error from run 1),
        # 3 (resume-scanned in run 2), 4, 5 (re-run + scan in run 2).
        assert ss_2["scans"] == 5, f"expected 5 scans (ids 1, 2, 3, 4, 5); got {ss_2}"
        assert ss_2["errors"] == 1  # still just id 2
        assert ss_2["results"] == 4  # 1, 3, 4, 5

        pf = _read_parquet(scan_dir / "id2_only_scanner.parquet")
        df = pf.read().to_pandas()
        # exactly one row per transcript, all 5 ids present
        scanned_task_ids = sorted(df["transcript_task_id"].astype(str).tolist())
        assert scanned_task_ids == ["1", "2", "3", "4", "5"], (
            f"all 5 ids should be present after resume-scan; got {scanned_task_ids}"
        )

        # id 2's scan-error row is preserved (not re-scanned), id 3's
        # row is a fresh successful scan.
        id2_rows = df[df["transcript_task_id"] == "2"]
        assert len(id2_rows) == 1
        assert id2_rows.iloc[0]["scan_error"]
        id3_rows = df[df["transcript_task_id"] == "3"]
        assert len(id3_rows) == 1
        assert not id3_rows.iloc[0]["scan_error"]


def test_eval_set_resume_scans_when_scanner_added_on_resume() -> None:
    """Resume-scan covers all previous samples when a scanner is added later.

    Run 1 has no scanner at all — every sample gets logged but no
    scan dir is created. Run 2 adds a scanner. eval_set sees no
    eval-level work to do (everything succeeded) but still routes
    `success_logs` through `run_eval` as `PreviousTask`s when a
    scanner is configured (see `evalset.py`'s "if not tasks_to_run"
    branch), so the per-sample reuse path runs for each previously-
    succeeded sample. scan_init creates a fresh scan dir on this
    call; `_summary.json` doesn't exist there yet (no prior
    finalize), so the per-sample check kicks in and dispatches scans
    for all transcripts.
    """
    n = 3

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=generate(),
        )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: NO scanner. Logs are written; no scan dir is created.
        success_1, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success_1
        assert not (Path(log_dir) / "scans").exists()

        # run 2: scanner added. No eval-level work needed (run 1
        # succeeded). The per-sample reuse path should scan every
        # previous sample.
        success_2, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success_2

        scan_dir = _scan_dir(log_dir)
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        df = pf.read().to_pandas()
        scanned_task_ids = sorted(df["transcript_task_id"].astype(str).tolist())
        assert scanned_task_ids == ["1", "2", "3"], (
            f"all 3 samples should be resume-scanned; got {scanned_task_ids}"
        )


def test_eval_set_resume_scans_when_intermediate_run_crashed_after_clean_finalize() -> (
    None
):
    """Stale `_summary.json` is NOT proof that on-disk state is consistent.

    A clean `_summary.json` from a prior run survives a subsequent
    crashed run, so its existence alone can't be the gate for skipping
    the per-sample resume-scan check.

    Sequence:
    - Run 1: cleanly finalizes a partial scan. Some samples scanned;
      `_summary.json` written with `complete=True`.
    - Run 2: runs the remaining samples; one sample's scan is patched
      out (logged but never recorded), and `scan_finalize` is patched
      to a no-op (simulating a crash before finalize). After run 2,
      `_summary.json` is still from run 1, even though run 2 left a
      gap.
    - Run 3: should detect and re-scan the sample that run 2 missed.

    This is the case the `_summary.json`-existence optimization fails:
    the summary on disk reflects run 1's clean state, but the gap is
    in run 2's work. A correct implementation must check on-disk
    parquet/buffer state per sample rather than trusting the stale
    summary.
    """
    import inspect_ai._eval.task.run as run_mod
    import inspect_ai._eval.task.scan as scan_mod
    from inspect_ai import EvalScannerConfig

    n = 5
    fails_3_4_5_first_time = _first_attempt_fails_for(3, 4, 5)

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=[fails_3_4_5_first_time, generate()],
        )

    config = EvalScannerConfig(
        scanners=[echo_scanner()],
        filter="error = ''",
    )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: samples 1, 2 succeed and get scanned; samples 3, 4, 5
        # error at the eval level and the filter excludes them. No scan
        # errors → finalize completes with complete=True.
        success_1, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=config,
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert success_1 is False  # samples 3, 4, 5 errored

        scan_dir = _scan_dir(log_dir)
        summary_1 = _read_summary(scan_dir)
        assert summary_1["complete"] is True  # the load-bearing premise
        ss_1 = summary_1["scanners"]["echo_scanner"]
        assert ss_1["scans"] == 2  # ids 1, 2 only

        # run 2: eval_set retries the previously-errored samples (3, 4,
        # 5). Patches simulate a crash in run 2:
        # - scan_eval_sample is no-op for id 4 (sample logged, scan
        #   never started — the gap)
        # - scan_finalize is no-op (process killed before sync ran)
        orig_scan_eval_sample = run_mod.scan_eval_sample
        orig_scan_finalize = scan_mod.scan_finalize

        async def skip_sample_4(eval_sample, scanner, **kwargs):  # type: ignore[no-untyped-def]
            if str(eval_sample.id) == "4":
                return
            return await orig_scan_eval_sample(eval_sample, scanner, **kwargs)

        async def no_finalize(*args, **kwargs):  # type: ignore[no-untyped-def]
            return

        run_mod.scan_eval_sample = skip_sample_4
        scan_mod.scan_eval_sample = skip_sample_4
        scan_mod.scan_finalize = no_finalize
        try:
            eval_set(
                tasks=make_task(),
                log_dir=log_dir,
                scanner=config,
                model="mockllm/model",
                retry_attempts=0,
                continue_on_fail=True,
                display="none",
            )
        finally:
            run_mod.scan_eval_sample = orig_scan_eval_sample
            scan_mod.scan_eval_sample = orig_scan_eval_sample
            scan_mod.scan_finalize = orig_scan_finalize

        # run 2's scan_init invalidated `complete` on attach, and
        # finalize never ran to overwrite it — so `_summary.json` now
        # reads complete=False, accurately reflecting the in-progress
        # state. (Without that invalidation, complete=True from run 1
        # would survive, masking the gap from any consumer that trusts
        # the flag.)
        summary_after_run_2 = _read_summary(scan_dir)
        assert summary_after_run_2["complete"] is False

        # run 3: no patches. eval_set sees all evals succeeded → no
        # eval-level work. The per-sample reuse path must catch id 4's
        # missing scan despite the stale clean `_summary.json`.
        success_3, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=config,
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert success_3

        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        df = pf.read().to_pandas()
        scanned_task_ids = sorted(df["transcript_task_id"].astype(str).tolist())
        assert scanned_task_ids == ["1", "2", "3", "4", "5"], (
            f"id 4's gap from run 2 should be repaired in run 3; got {scanned_task_ids}"
        )


@task
def _two_sample_task_a() -> Task:
    return Task(
        name="task_a",
        dataset=[Sample(input=f"a{i}", target=str(i)) for i in range(1, 3)],
        solver=generate(),
    )


@task
def _two_sample_task_b() -> Task:
    return Task(
        name="task_b",
        dataset=[Sample(input=f"b{i}", target=str(i)) for i in range(1, 3)],
        solver=generate(),
    )


def test_eval_set_resume_scans_success_logs_when_other_tasks_pending() -> None:
    """Resume-scan must fire for success_logs even when there are pending tasks.

    Setup:
    - Run 1: only task A, NO scanner. A's samples logged but no scan
      dir is created.
    - Run 2: tasks [A, B] WITH scanner. A is reused as a `success_log`
      (its eval succeeded in run 1). B is new.

    Run 2's `tasks_to_run` has only B (A is in `success_logs`). The
    bug: when `tasks_to_run` is non-empty, the all-success branch
    that routes `success_logs` through `PreviousTask` is skipped — so
    A's samples never reach the per-sample reuse path and stay
    unscanned. Both A's and B's samples should end up in the parquet.
    """
    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: only task A, no scanner → A's logs land but no scan_dir
        eval_set(
            tasks=_two_sample_task_a(),
            log_dir=log_dir,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert not (Path(log_dir) / "scans").exists()

        # run 2: add task B and a scanner. B is pending; A is in
        # success_logs and needs resume-scan.
        eval_set(
            tasks=[_two_sample_task_a(), _two_sample_task_b()],
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        df = pf.read().to_pandas()
        # 2 samples from task A + 2 from task B = 4 transcript rows
        assert len(df) == 4, (
            f"task A's samples should be resume-scanned alongside B's "
            f"new scans; got {len(df)} rows"
        )
        scanned_task_ids = sorted(df["transcript_task_id"].astype(str).tolist())
        assert scanned_task_ids == ["1", "1", "2", "2"]


def test_eval_set_resume_short_circuits_when_prior_scan_clean() -> None:
    """A no-op rerun against a clean prior scan does no scanner work.

    When `_summary.json` shows `complete=True` (i.e. the prior call's
    finalize wrote it and `scan_init` for THIS call hasn't run yet
    because there's no eval-level work to do), evalset short-circuits
    the success-logs → PreviousTask routing entirely. The scanner is
    never invoked again — confirms the fast-path optimization works.
    """
    from unittest.mock import patch

    n = 3

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=generate(),
        )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: clean scan, all samples succeed and scan
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        summary_1 = _read_summary(scan_dir)
        assert summary_1["complete"] is True
        ss_1 = summary_1["scanners"]["echo_scanner"]
        assert ss_1["scans"] == n

        # run 2: identical args. With the prior-clean optimization,
        # success_logs are returned directly and the scanner is never
        # called. We assert this by patching scan_eval_sample to track
        # invocations: it must NOT be called during run 2.
        import inspect_ai._eval.task.run as run_mod
        import inspect_ai._eval.task.scan as scan_mod

        invocations: list[str] = []
        orig = run_mod.scan_eval_sample

        async def tracking(eval_sample, scanner, **kwargs):  # type: ignore[no-untyped-def]
            invocations.append(str(eval_sample.id))
            return await orig(eval_sample, scanner, **kwargs)

        run_mod.scan_eval_sample = tracking
        scan_mod.scan_eval_sample = tracking
        try:
            eval_set(
                tasks=make_task(),
                log_dir=log_dir,
                scanner=[echo_scanner()],
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )
        finally:
            run_mod.scan_eval_sample = orig
            scan_mod.scan_eval_sample = orig

        assert invocations == [], (
            f"prior-clean optimization should skip all scan dispatches; "
            f"got {invocations}"
        )

        # also: the on-disk scan output is unchanged (no extra rows)
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        assert pf.metadata.num_rows == n
        # silence unused-import warning
        del patch


def test_summary_complete_flips_to_false_when_resume_introduces_scan_errors() -> None:
    """A clean run-1 followed by an errored run-2 should leave `complete=False`.

    `_summary.json` at the scan_dir is rewritten by `scan_finalize`
    every time it runs, with `complete = not errors_found_in_buffer`.
    So a previously-clean `complete=True` should be overwritten to
    `False` once a subsequent run records scanner errors.

    Setup: id2_only_scanner errors on sample id "2".
    - Run 1: limit=1 → only sample 1 runs and scans cleanly (no
      errors from this scanner since it's not id 2). After run 1,
      `complete=True`.
    - Run 2: limit=2 → sample 2 also runs; scanner errors → buffer
      records an error. After run 2's finalize, `complete=False`.
    """
    n = 4

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=generate(),
        )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: scan only sample 1 — no errors
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            limit=1,
            retry_attempts=0,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        summary_after_run_1 = _read_summary(scan_dir)
        assert summary_after_run_1["complete"] is True, (
            "run 1 had no scanner errors, expected complete=True"
        )

        # run 2: extend limit so sample 2 runs (and the scanner errors
        # on it). After run 2's finalize, the scan should reflect the
        # error and flip complete=False.
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            limit=2,
            retry_attempts=0,
            display="none",
        )

        summary_after_run_2 = _read_summary(scan_dir)
        assert summary_after_run_2["complete"] is False, (
            "run 2 introduced a scanner error on id 2; complete should "
            f"have flipped to False. summary={summary_after_run_2}"
        )
        # at least one scan errored (id 2). exact scan count varies with
        # how eval_set treats the limit change (it may re-run sample 1
        # under a fresh uuid), so we don't pin it here.
        ss = summary_after_run_2["scanners"]["id2_only_scanner"]
        assert ss["errors"] >= 1


def test_sync_does_not_duplicate_rows_across_resume() -> None:
    """`sync()` produces at most one row per `transcript_id` across calls.

    The compacted parquet at `<scan_dir>/<scanner>.parquet` is built
    via `scanner_table(buffer_dir, scanner, extra_inputs=[prior_compacted])`.
    When the buffer dir is preserved across a non-final sync (e.g.
    eval_set retry where `complete=False`), the per-transcript buffer
    parquets stay on disk. The next sync sees the same rows from
    *both* sources — buffer files AND the prior compacted file — and
    without dedup the merged output has each row twice.

    Reproduces with the smallest scenario that triggers two syncs
    against a non-empty buffer:

    - 2 samples, scanner errors on id 2 (so run 1's `complete=False`
      → buffer dir preserved, NOT cleaned up).
    - Run eval_set twice with identical args. Both samples succeed at
      the eval level on each call, so eval_set has no samples to
      re-run — but `scan_context` still wraps each call and triggers
      a sync at finalize.
    - After run 2, assert one row per `transcript_id` (not the bug's
      doubled count).
    """

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, 3)],
            solver=generate(),
        )

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        pf = _read_parquet(scan_dir / "id2_only_scanner.parquet")
        df_run1 = pf.read().to_pandas()
        # baseline: 2 transcripts, 2 rows
        assert len(df_run1) == 2
        assert df_run1["transcript_id"].nunique() == 2
        run1_transcript_ids = set(df_run1["transcript_id"].tolist())

        # run 2: identical args. Both samples already succeeded at the
        # eval level so nothing is re-run, but scan_context still calls
        # sync at finalize — re-merging the unchanged buffer with the
        # prior compacted output.
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[id2_only_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )

        pf = _read_parquet(scan_dir / "id2_only_scanner.parquet")
        df_run2 = pf.read().to_pandas()
        # the load-bearing assertion: dedup. Without the fix this is
        # 4 rows (each of the 2 transcripts duplicated).
        assert len(df_run2) == 2, (
            f"sync should produce one row per transcript_id; got "
            f"{len(df_run2)} rows for {df_run2['transcript_id'].nunique()} "
            f"unique transcript_ids — buffer + extra_inputs double-counted"
        )
        # the same transcript_ids are still present (not lost during dedup)
        assert set(df_run2["transcript_id"].tolist()) == run1_transcript_ids


def test_scanjob_config_filter_skips_unmatched_samples() -> None:
    """A SQL `filter` on `ScanJobConfig` excludes non-matching samples.

    Setup — 4 samples (ids 1..4), solver fails first attempt for 3, 4
    so they end up logged with `transcript.error` set. Pass the scanner
    via `ScanJobConfig` with `filter="error = ''"` (scout's convention:
    successful samples have empty-string error, errored samples have
    the message string). Only the eval-successful samples (1, 2) should
    be scanned — samples 3, 4 are skipped before the scanner runs.
    """
    from inspect_ai import EvalScannerConfig

    n = 4
    fails_3_4_first_time = _first_attempt_fails_for(3, 4)

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=[fails_3_4_first_time, generate()],
        )

    config = EvalScannerConfig(
        scanners=[echo_scanner()],
        filter="error = ''",
    )

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=config,
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        # only samples 1, 2 succeeded → only those scanned
        pf = _read_parquet(scan_dir / "echo_scanner.parquet")
        assert pf.metadata.num_rows == 2

        scanned_ids = sorted(
            tid
            for tid in pf.read(columns=["transcript_task_id"])
            .column("transcript_task_id")
            .to_pylist()
            if tid is not None
        )
        assert scanned_ids == ["1", "2"]

        summary = _read_summary(scan_dir)
        ss = summary["scanners"]["echo_scanner"]
        assert ss["scans"] == 2
        assert ss["errors"] == 0
        assert ss["results"] == 2


@pytest.mark.parametrize(
    "field",
    [
        "transcripts",
        "worklist",
        "limit",
        "shuffle",
        "max_processes",
        "max_transcripts",
        "validation",
        "log_level",
    ],
)
def test_eval_set_scanner_config_rejects_unsupported_fields(field: str) -> None:
    """`EvalScannerConfig` rejects scout fields that conflict with eval_set.

    Pydantic enforces this via `extra="forbid"` so misuse fails at
    construction time rather than mid-eval.
    """
    from pydantic import ValidationError

    from inspect_ai import EvalScannerConfig

    kwargs: dict[str, Any] = {field: "anything"}
    with pytest.raises(ValidationError, match=field):
        EvalScannerConfig(scanners=[echo_scanner()], **kwargs)


def test_scanjob_config_scans_overrides_output_location() -> None:
    """`ScanJobConfig.scans` overrides where scan output is written.

    By default scan output lands at `<log_dir>/scans/scan_id=<id>/`. A
    user can redirect to an arbitrary location (e.g. an S3 bucket) by
    setting `scans` on the config — useful when scan results should
    live separately from the eval logs.
    """
    from inspect_ai import EvalScannerConfig

    with tempfile.TemporaryDirectory() as log_dir:
        with tempfile.TemporaryDirectory() as scans_dir:
            config = EvalScannerConfig(
                scanners=[echo_scanner()],
                scans=scans_dir,
            )
            success, _ = eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=config,
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )
            assert success

            # default location should be empty (no scans dir under log_dir)
            assert not (Path(log_dir) / "scans").exists()

            # the override location holds the scan dir + parquet
            override_scans = list((Path(scans_dir)).glob("scan_id=*"))
            assert len(override_scans) == 1
            assert (override_scans[0] / "echo_scanner.parquet").exists()


def test_scan_name_defaults_to_eval_set() -> None:
    """`scan_name` defaults to "eval_set" when no override is provided.

    When the scanner is a plain list of Scanner objects (no
    ScanJob/ScanJobConfig wrapping), the scan spec's `scan_name` field
    falls back to the default "eval_set".
    """
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        spec = json.loads((scan_dir / "_scan.json").read_text())
        assert spec["scan_name"] == "eval_set"


def test_scan_name_override_from_scan_job() -> None:
    """`EvalScannerConfig.name` overrides the default `scan_name`."""
    from inspect_ai import EvalScannerConfig

    scanner = EvalScannerConfig(scanners=[echo_scanner()], name="my-custom-scan")

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=scanner,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        spec = json.loads((scan_dir / "_scan.json").read_text())
        assert spec["scan_name"] == "my-custom-scan"


def test_tags_and_metadata_written_to_scan_spec() -> None:
    """`tags` and `metadata` on `EvalScannerConfig` land in scan.json."""
    from inspect_ai import EvalScannerConfig

    tags = ["nightly", "experiment-42"]
    metadata = {"owner": "team-x", "iteration": 3}
    scanner = EvalScannerConfig(scanners=[echo_scanner()], tags=tags, metadata=metadata)

    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=scanner,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success

        scan_dir = _scan_dir(log_dir)
        spec = json.loads((scan_dir / "_scan.json").read_text())
        assert spec["tags"] == tags
        # metadata carries an inspect_ai-managed hash key alongside the
        # user's metadata — assert user-provided keys round-trip rather
        # than full dict equality
        for key, value in metadata.items():
            assert spec["metadata"][key] == value


def test_llm_scanner_inherits_eval_set_model_when_unspecified() -> None:
    """Scanner falls back to the eval's active model when no scan-side model is set.

    With no `ScanJob`/`ScanJobConfig` (just a list of scanners), there's
    nothing for `_install_scan_model_context` to override, so the
    scanner's `get_model()` resolves to whichever model
    `eval_set(model=...)` installed via inspect_ai's model context.
    Using mockllm here — which can't produce parseable boolean answers —
    so `results == 0`; the point is to confirm the model was reachable
    (`tokens > 0` and `mockllm/model` in `model_usage`).
    """
    from inspect_scout import llm_scanner

    scanner_fn = llm_scanner(question="Did anything notable happen?", answer="boolean")

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[scanner_fn],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        summary = _read_summary(scan_dir)
        assert len(summary["scanners"]) == 1
        ss = next(iter(summary["scanners"].values()))
        assert ss["scans"] >= 2
        # mockllm responded — non-zero token usage proves a model was
        # available to the scanner via the inspect_ai context.
        assert ss["tokens"] > 0
        assert "mockllm/model" in ss["model_usage"]
        # but no parseable boolean answer → no usable results.
        assert ss["results"] == 0


def test_install_scan_model_context_forwards_all_model_kwargs() -> None:
    """All model-related ScanJob fields are forwarded to scout.

    `model` / `model_base_url` / `model_args` / `generate_config` /
    `model_roles` are silent pass-throughs into scout's
    `init_scan_model_context`. Spy on that function via monkeypatch
    (no need for end-to-end mockllm runs that don't visibly differ
    by these fields) and assert the kwargs match what the ScanJob
    carries.
    """
    from unittest.mock import patch

    from inspect_ai import EvalScannerConfig
    from inspect_ai.model import GenerateConfig

    job = EvalScannerConfig(
        scanners=[echo_scanner()],
        model="mockllm/scan-model",
        model_base_url="https://example.test/api",
        model_args={"api_key": "redacted"},
        generate_config=GenerateConfig(temperature=0.5),
        model_roles={"grader": "mockllm/grader"},
    )

    captured: list[dict] = []

    def fake_init(**kwargs):
        captured.append(kwargs)
        # return value isn't read by our caller
        return (None, {}, None)

    with patch("inspect_scout._scan.init_scan_model_context", side_effect=fake_init):
        with tempfile.TemporaryDirectory() as log_dir:
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=job,
                model="mockllm/eval-model",
                retry_attempts=0,
                display="none",
            )

    # one call per scan_eval_sample dispatch (one per sample)
    assert len(captured) == 2
    for kwargs in captured:
        assert kwargs.get("model") == job.model
        assert kwargs.get("model_base_url") == "https://example.test/api"
        assert kwargs.get("model_args") == {"api_key": "redacted"}
        assert kwargs.get("model_config") == GenerateConfig(temperature=0.5)
        assert kwargs.get("model_roles") == job.model_roles


def test_scan_job_model_overrides_eval_model_for_scanner() -> None:
    """`ScanJob.model` is honored: the scanner uses it instead of the eval model.

    eval_set runs with `mockllm/eval-model`; the ScanJob carries
    `mockllm/scan-model`. The scanner's `model_usage` should show only
    the scan-model — confirming our integration calls scout's
    `init_scan_model_context` to override the active model just for the
    scanner call (not for the eval's solver/generate calls).
    """
    from inspect_scout import llm_scanner

    from inspect_ai import EvalScannerConfig

    scanner_fn = llm_scanner(question="Did anything notable happen?", answer="boolean")
    job = EvalScannerConfig(scanners=[scanner_fn], model="mockllm/scan-model")

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=job,
            model="mockllm/eval-model",
            retry_attempts=0,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        summary = _read_summary(scan_dir)
        ss = next(iter(summary["scanners"].values()))
        # scanner used the scan-model, not the eval-model
        assert "mockllm/scan-model" in ss["model_usage"]
        assert "mockllm/eval-model" not in ss["model_usage"]


def test_eval_and_scan_model_usage_are_partitioned() -> None:
    """Eval and scan usage track separately even when sharing a model.

    Sharing one model name forces a value-level check rather than a
    key-level one: contamination doesn't introduce a new key, just
    inflates existing totals.

    Approach: run the same eval twice — once *without* a scanner
    (baseline solver-only token counts) and once *with* a scanner —
    and assert the eval log's stats are byte-for-byte identical
    between runs. mockllm's outputs are deterministic given identical
    inputs, so any drift means the scanner contributed to the eval's
    tracker. We then check the additivity invariant
    (`log.stats == sum(per-sample)`) as a defense-in-depth signal that
    catches the simpler one-sided contamination case, and verify the
    scan summary captured the scanner's own usage independently.

    Runs multiple samples concurrently (`max_samples=n`) so structural
    mistakes where the override lands in the parent task's context
    show up here.
    """
    from inspect_scout import llm_scanner

    from inspect_ai import EvalScannerConfig
    from inspect_ai.log import read_eval_log

    model_name = "mockllm/model"
    n_samples = 4

    def _run(scanner: object | None) -> Path:
        log_dir = tempfile.mkdtemp()
        eval_set(
            tasks=_task(n_samples),
            log_dir=log_dir,
            scanner=scanner,  # type: ignore[arg-type]
            model=model_name,
            retry_attempts=0,
            max_samples=n_samples,
            display="none",
        )
        return Path(log_dir)

    # ---- baseline run (no scanner) ----
    baseline_log_dir = _run(None)
    baseline_log = read_eval_log(str(next(baseline_log_dir.glob("*.eval"))))
    assert baseline_log.samples is not None
    baseline_usage = baseline_log.stats.model_usage[model_name]

    # ---- run with scanner ----
    scanner_fn = llm_scanner(question="Did anything happen?", answer="boolean")
    job = EvalScannerConfig(scanners=[scanner_fn], model=model_name)
    scanned_log_dir = _run(job)
    log = read_eval_log(str(next(scanned_log_dir.glob("*.eval"))))
    assert log.samples is not None
    assert len(log.samples) == n_samples

    # only the shared model appears
    assert set(log.stats.model_usage.keys()) == {model_name}

    # eval log stats match the no-scanner baseline exactly. With the
    # same model on both sides, this is the load-bearing assertion:
    # any contamination of either the per-sample tracker or the
    # eval-level tracker by scanner tokens would inflate these
    # numbers above the baseline.
    log_usage = log.stats.model_usage[model_name]
    assert log_usage.input_tokens == baseline_usage.input_tokens, (
        f"input_tokens={log_usage.input_tokens} != "
        f"baseline {baseline_usage.input_tokens} — scanner tokens leaked"
    )
    assert log_usage.output_tokens == baseline_usage.output_tokens, (
        f"output_tokens={log_usage.output_tokens} != "
        f"baseline {baseline_usage.output_tokens} — scanner tokens leaked"
    )

    # additivity sanity check: log stats == sum of per-sample.
    sample_total_input = sum(
        s.model_usage[model_name].input_tokens for s in log.samples
    )
    sample_total_output = sum(
        s.model_usage[model_name].output_tokens for s in log.samples
    )
    assert log_usage.input_tokens == sample_total_input
    assert log_usage.output_tokens == sample_total_output
    assert sample_total_input > 0
    assert sample_total_output > 0

    # ---- scan side ----
    scan_dir = _scan_dir(str(scanned_log_dir))
    summary = _read_summary(scan_dir)
    ss = next(iter(summary["scanners"].values()))

    # only the shared model appears on the scan side too
    assert set(ss["model_usage"].keys()) == {model_name}

    # scanner consumed real tokens via the scan tracker
    scan_usage = ss["model_usage"][model_name]
    assert scan_usage["input_tokens"] > 0
    assert scan_usage["output_tokens"] > 0
    # the scan summary's `tokens` counter equals the scanner's
    # aggregated total_tokens for its sole model
    assert ss["tokens"] == scan_usage["total_tokens"]


def test_llm_scanner_inherits_task_model_when_eval_set_model_omitted() -> None:
    """Scanner picks up the task's model when eval_set's model is omitted.

    Same fallback as above, but the model lives on `Task(model=...)`
    instead of `eval_set(model=...)`. Inspect_ai's per-task model
    populates the model context for the task's samples, and the
    scanner's `get_model()` returns it.
    """
    from inspect_scout import llm_scanner

    scanner_fn = llm_scanner(question="Did anything notable happen?", answer="boolean")

    with tempfile.TemporaryDirectory() as log_dir:
        # model on the Task; no `model=` on eval_set — the eval-level
        # default is overridden by the task-level one for any task that
        # specifies it.
        task = Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(2)],
            solver=generate(),
            model="mockllm/model",
        )
        eval_set(
            tasks=task,
            log_dir=log_dir,
            scanner=[scanner_fn],
            retry_attempts=0,
            display="none",
        )

        scan_dir = _scan_dir(log_dir)
        summary = _read_summary(scan_dir)
        ss = next(iter(summary["scanners"].values()))
        assert ss["tokens"] > 0
        assert "mockllm/model" in ss["model_usage"]
        assert ss["results"] == 0


def test_scanner_resume_with_changed_scanner_set_fails_loudly() -> None:
    """A second eval_set call must reject a changed scanner set up front.

    Without validation, scout's `RecorderBuffer.record` would `KeyError`
    on any scanner not in the on-disk spec; that error is caught by
    `task_run_sample`'s sample-error handling and silently turns
    successful samples into errors, corrupting the eval's success result.
    `scan_init` validates upfront and raises `PrerequisiteError`
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


@scanner(messages="all", name="param_scanner")
def param_scanner(target_word: str = "hello") -> Any:
    """Scanner that takes a parameter — used in config-change tests."""

    async def scan(transcript: Transcript) -> Result:
        return Result(value=f"matched:{target_word}")

    return scan


def test_scanner_change_param_rejected() -> None:
    """Same scanner name but different params is rejected on reattach.

    `ScannerSpec.params` is part of scout's per-scanner identity. A
    change there means the scanner will produce different output for
    the same transcripts; reusing the prior parquet rows would be wrong.
    """
    from inspect_ai._util.error import PrerequisiteError

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[param_scanner(target_word="hello")],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        with pytest.raises(PrerequisiteError, match="config has changed"):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=[param_scanner(target_word="goodbye")],
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


def test_scanner_change_version_rejected() -> None:
    """A change to `ScannerSpec.version` (e.g. scanner code bump) rejected.

    Mutates the on-disk spec to simulate a scanner version bump — the
    user-visible scenario is a developer adding `version=N` to the
    `@scanner` decorator. The check compares full `ScannerSpec`
    equality so any version drift triggers it.
    """
    from inspect_ai._util.error import PrerequisiteError

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        spec_path = scan_dir / "_scan.json"
        spec = json.loads(spec_path.read_text())
        spec["scanners"]["echo_scanner"]["version"] = 99
        spec_path.write_text(json.dumps(spec))

        with pytest.raises(PrerequisiteError, match="config has changed"):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=[echo_scanner()],
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


def test_scanner_change_filter_rejected() -> None:
    """`EvalScannerConfig.filter` change is rejected — the user's repro.

    Run 1 with filter="error != ''" and run 2 with no filter would
    silently leave previously-filtered-out transcripts unscanned
    because the prior_scan_clean path treats the prior run as
    "everything done." Detecting the filter change forces a clean
    error instead.
    """
    from inspect_ai import EvalScannerConfig
    from inspect_ai._util.error import PrerequisiteError

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=EvalScannerConfig(
                scanners=[echo_scanner()],
                filter="error != ''",
            ),
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        with pytest.raises(PrerequisiteError, match="Eval-set-level"):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=EvalScannerConfig(scanners=[echo_scanner()]),
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


def test_scanner_change_model_rejected() -> None:
    """Scanner-side model override change is rejected on reattach."""
    from inspect_ai import EvalScannerConfig
    from inspect_ai._util.error import PrerequisiteError

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=EvalScannerConfig(
                scanners=[echo_scanner()],
                model="mockllm/model",
            ),
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        with pytest.raises(PrerequisiteError, match="Eval-set-level"):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=EvalScannerConfig(
                    scanners=[echo_scanner()],
                    model="mockllm/other",
                ),
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


def test_scanner_change_model_args_rejected() -> None:
    """Scanner-side `model_args` change is rejected on reattach."""
    from inspect_ai import EvalScannerConfig
    from inspect_ai._util.error import PrerequisiteError

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=EvalScannerConfig(
                scanners=[echo_scanner()],
                model_args={"temperature": 0.0},
            ),
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        with pytest.raises(PrerequisiteError, match="Eval-set-level"):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=EvalScannerConfig(
                    scanners=[echo_scanner()],
                    model_args={"temperature": 0.7},
                ),
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


def test_scanner_change_generate_config_rejected() -> None:
    """Scanner-side `generate_config` change is rejected on reattach."""
    from inspect_ai import EvalScannerConfig
    from inspect_ai._util.error import PrerequisiteError
    from inspect_ai.model import GenerateConfig

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=EvalScannerConfig(
                scanners=[echo_scanner()],
                generate_config=GenerateConfig(temperature=0.0),
            ),
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        with pytest.raises(PrerequisiteError, match="Eval-set-level"):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=EvalScannerConfig(
                    scanners=[echo_scanner()],
                    generate_config=GenerateConfig(temperature=0.5),
                ),
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


def test_scanner_change_labels_only_accepted() -> None:
    """Changing labels only (tags / metadata / scan name) is NOT rejected.

    Tags, metadata, and `name` are intentionally excluded from the
    config hash — they're labels, not behavior. A user re-running with
    additional tags or updated metadata should not be forced to start
    a fresh scan.
    """
    from inspect_ai import EvalScannerConfig

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=EvalScannerConfig(
                scanners=[echo_scanner()],
                tags=["a"],
                metadata={"owner": "team-x"},
                name="run-1",
            ),
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        success_2, _ = eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=EvalScannerConfig(
                scanners=[echo_scanner()],
                tags=["a", "b", "extra"],
                metadata={"owner": "team-y", "iteration": 2},
                name="run-2",
            ),
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success_2


def test_scanner_eval_level_model_change_accepted() -> None:
    """Changing the eval-level model across runs is NOT rejected.

    The eval-level model (the `model=` arg on `eval_set` / `eval`)
    affects which transcripts get produced — each transcript has a
    fresh uuid that already differentiates work in the scan dir.
    Capturing it in the scanner config hash would force a fresh
    log_dir for every model swap, which is wrong: the scan dir is
    designed to accumulate rows from multiple models, each row tied
    to the transcript it was produced from.

    This is also a guard against someone "fixing" the hash to include
    the eval-level model — that fix would break this case.
    """
    import pyarrow.parquet as pq

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(3)],
            solver=generate(),
        )

    def parquet_tids(scan_dir: UPath) -> set[str]:
        pf = pq.ParquetFile((scan_dir / "echo_scanner.parquet").as_posix())
        out: set[str] = set()
        for i in range(pf.metadata.num_row_groups):
            rg = pf.read_row_group(i, columns=["transcript_id"])
            out.update(t for t in rg.column("transcript_id").to_pylist() if t)
        return out

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: model A
        success_1, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/a",
            retry_attempts=0,
            display="none",
        )
        assert success_1
        scan_dir = _scan_dir(log_dir)
        tids_after_run_1 = parquet_tids(scan_dir)
        assert len(tids_after_run_1) == 3

        # run 2: model B against the same log_dir. task_identifier
        # differs (model is part of it), so the prior logs aren't
        # reused; samples re-execute with fresh uuids and fresh scans
        # land in the parquet alongside the prior rows.
        # `log_dir_allow_dirty=True` lets the prior model-A log coexist
        # with the model-B run — without it eval_set refuses on the
        # mismatched task_identifier of the prior log file.
        success_2, _ = eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/b",
            retry_attempts=0,
            log_dir_allow_dirty=True,
            display="none",
        )
        assert success_2

        # the scan dir must still resolve to the same scan_id (same
        # eval_set_id auto-detected from log_dir)
        assert _scan_dir(log_dir) == scan_dir

        tids_after_run_2 = parquet_tids(scan_dir)
        # both runs' tids should be present, disjoint (fresh uuids per
        # run), totaling 6 rows = 2 runs × 3 samples × 1 scanner
        assert len(tids_after_run_2) == 6
        assert tids_after_run_1.issubset(tids_after_run_2), (
            "expected run 1's tids to carry forward; the eval-level model "
            "change should not invalidate prior scan rows"
        )
        run_2_only = tids_after_run_2 - tids_after_run_1
        assert len(run_2_only) == 3, (
            f"expected 3 fresh tids from the model-B run; got {len(run_2_only)}"
        )


def test_scanner_unchanged_config_accepted() -> None:
    """Reattach with byte-identical config succeeds (regression guard)."""
    from inspect_ai import EvalScannerConfig

    with tempfile.TemporaryDirectory() as log_dir:
        scanner = EvalScannerConfig(
            scanners=[echo_scanner()],
            filter="error = ''",
            model="mockllm/model",
            model_args={"temperature": 0.0},
        )
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=scanner,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        # rebuild an equivalent config (a fresh object with the same
        # values) — should compare equal across runs
        scanner_2 = EvalScannerConfig(
            scanners=[echo_scanner()],
            filter="error = ''",
            model="mockllm/model",
            model_args={"temperature": 0.0},
        )
        success_2, _ = eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=scanner_2,
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success_2


def test_scanner_partial_errors_recorded() -> None:
    """A scanner that errors on some samples records those failures.

    The eval itself is unaffected — sample outcomes are determined by the
    solver, not by scanner success. Scanner failures land as `Error`
    records in the compacted parquet's `scan_error` column and as counts
    in `_summary.json`.

    Finalize marks the scan `complete=False` when any scanner error is
    present so scout's `scan_resume` can re-run only the failed scans.
    See `test_scout_scan_resume_reruns_failed_scans` for the resume path.
    """
    n = 4  # ids 1..4: scanner errors on 2 and 4, succeeds on 1 and 3
    expected_errors = n // 2
    expected_results = n - expected_errors

    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=_task(n),
            log_dir=log_dir,
            scanner=[picky_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        # the eval succeeds — scanner failures are isolated from sample state
        assert success

        scan_dir = _scan_dir(log_dir)

        # summary tracks per-scanner success/error counts across all samples
        summary = _read_summary(scan_dir)
        ss = summary["scanners"]["picky_scanner"]
        assert ss["scans"] == n
        assert ss["errors"] == expected_errors
        assert ss["results"] == expected_results
        # scanner errors leave the scan resumable
        assert summary["complete"] is False

        # the compacted parquet has one row per sample, with `scan_error`
        # populated for failed scans and null for successful ones
        pf = _read_parquet(scan_dir / "picky_scanner.parquet")
        assert pf.metadata.num_rows == n
        scan_errors = pf.read(columns=["scan_error"]).column("scan_error").to_pylist()
        assert sum(1 for e in scan_errors if e is not None) == expected_errors
        assert sum(1 for e in scan_errors if e is None) == expected_results

        # `_errors.jsonl` accumulates across samples — `FileRecorder.attach`
        # preserves the errors file rather than truncating it (unlike
        # `resume`, which is for scout's retry-errored model)
        errors_jsonl = (scan_dir / "_errors.jsonl").read_text().strip()
        error_lines = [line for line in errors_jsonl.split("\n") if line]
        assert len(error_lines) == expected_errors
        for line in error_lines:
            err = json.loads(line)
            assert err["scanner"] == "picky_scanner"
            assert "refusing sample" in err["error"]


def test_scout_scan_resume_reruns_failed_scans() -> None:
    """Scout's `scan_resume` re-runs scans that errored in eval_set.

    The eval_set finalize leaves `complete=False` when there are scanner
    errors and writes a `spec.transcripts` snapshot to `_scan.json`.
    Together those let scout's `scan_resume` pick up the scan, identify
    transcripts whose per-scanner parquet has a non-null `scan_error`
    (via `is_recorded`), and re-run only those scanners.

    Uses `flaky_scanner` which errors on its first call per transcript
    and succeeds afterwards. The resume re-runs every transcript and
    they all succeed, so the scan ends `complete=True`. The summary
    accumulates totals across both runs (scout's behavior — it's a
    running tally of every scanner invocation).
    """
    from inspect_scout import scan_resume

    if _FLAKY_MARKER.exists():
        _FLAKY_MARKER.unlink()

    n = 4
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(n),
            log_dir=log_dir,
            scanner=[flaky_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)

        # all n samples errored on the first scanner attempt
        summary_1 = _read_summary(scan_dir)
        ss_1 = summary_1["scanners"]["flaky_scanner"]
        assert ss_1["scans"] == n
        assert ss_1["errors"] == n
        assert ss_1["results"] == 0
        # errors → scan is left resumable
        assert summary_1["complete"] is False

        # resume picks up where eval_set left off; flaky_scanner now
        # succeeds on every retry. The errors file is truncated by
        # scout's resume(), and no new errors land, so the scan is
        # marked complete.
        status = scan_resume(str(scan_dir), display="none")
        assert status.complete
        assert status.errors == []

        summary_2 = _read_summary(scan_dir)
        ss_2 = summary_2["scanners"]["flaky_scanner"]
        # totals accumulate: original n errors + n successful retries
        assert ss_2["scans"] == 2 * n
        assert ss_2["errors"] == n
        assert ss_2["results"] == n
        assert summary_2["complete"] is True


# --- config file loading ----------------------------------------------------


def test_from_file_loads_yaml_with_scanner_specs() -> None:
    """`EvalScannerConfig.from_file` resolves `ScannerSpec` entries.

    Reads a YAML file and turns `ScannerSpec` entries (registry name +
    params) into live `Scanner` objects suitable for use in
    `eval_set(scanner=...)`.
    """
    import yaml

    from inspect_ai import EvalScannerConfig

    yaml_body = yaml.safe_dump(
        {
            "name": "from_yaml",
            "scanners": [{"name": "echo_scanner"}],
            "tags": ["yaml-loaded"],
        }
    )
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text(yaml_body)

        config = EvalScannerConfig.from_file(str(cfg_path))

    assert config.name == "from_yaml"
    assert config.tags == ["yaml-loaded"]
    # scanners realized — list of callables, not list of dicts
    assert isinstance(config.scanners, list)
    assert len(config.scanners) == 1
    assert callable(config.scanners[0])


def test_from_file_loads_json_with_dict_scanners() -> None:
    """`from_file` accepts JSON files and the dict-of-specs form."""
    from inspect_ai import EvalScannerConfig

    body = json.dumps(
        {
            "scanners": {
                "alpha": {"name": "scanner_a"},
                "beta": {"name": "scanner_b"},
            }
        }
    )
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.json"
        cfg_path.write_text(body)

        config = EvalScannerConfig.from_file(str(cfg_path))

    assert isinstance(config.scanners, dict)
    assert set(config.scanners.keys()) == {"alpha", "beta"}
    assert all(callable(s) for s in config.scanners.values())


def test_from_file_rejects_unsupported_field() -> None:
    """File-loaded configs are validated the same way as direct construction.

    Pydantic's `extra="forbid"` catches unsupported scout fields (e.g.
    `limit`) at file-load time, mirroring direct constructor behavior.
    """
    import yaml
    from pydantic import ValidationError

    from inspect_ai import EvalScannerConfig

    yaml_body = yaml.safe_dump({"scanners": [{"name": "echo_scanner"}], "limit": 10})
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text(yaml_body)

        with pytest.raises(ValidationError, match="limit"):
            EvalScannerConfig.from_file(str(cfg_path))


def test_from_file_missing_path_raises() -> None:
    """A missing config file raises `PrerequisiteError`.

    This is a clear failure mode rather than a downstream filesystem
    traceback that would obscure the cause.
    """
    from inspect_ai import EvalScannerConfig
    from inspect_ai._util.error import PrerequisiteError

    with tempfile.TemporaryDirectory() as d:
        missing = Path(d) / "does_not_exist.yaml"
        with pytest.raises(PrerequisiteError, match="does not exist"):
            EvalScannerConfig.from_file(str(missing))


def test_from_file_config_runs_in_eval_set() -> None:
    """End-to-end: a YAML-loaded config drives a real `eval_set` run."""
    import yaml

    from inspect_ai import EvalScannerConfig

    yaml_body = yaml.safe_dump(
        {
            "name": "yaml_run",
            "scanners": [{"name": "echo_scanner"}],
            "tags": ["loaded-from-disk"],
        }
    )
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "config.yaml"
        cfg_path.write_text(yaml_body)

        config = EvalScannerConfig.from_file(str(cfg_path))

        with tempfile.TemporaryDirectory() as log_dir:
            success, _ = eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=config,
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )
            assert success
            scan_dir = _scan_dir(log_dir)
            assert (scan_dir / "echo_scanner.parquet").exists()
            spec = json.loads((scan_dir / "_scan.json").read_text())
            assert spec["scan_name"] == "yaml_run"
            assert spec["tags"] == ["loaded-from-disk"]


# --- standalone eval() ------------------------------------------------------


def test_eval_scanner_produces_complete_scan_dir() -> None:
    """`eval()` (no eval_set) writes a complete scan dir under log_dir/scans/.

    Confirms scan_init and scan_finalize fire for plain eval too — the
    final `_summary.json` lands at the canonical location and `complete`
    is True when no scanner errored.
    """
    from inspect_ai import eval

    with tempfile.TemporaryDirectory() as log_dir:
        eval(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        assert (scan_dir / "echo_scanner.parquet").exists()
        # _summary.json sits at the final scan dir (only written there
        # by sync at finalize)
        summary = _read_summary(scan_dir)
        assert summary["complete"] is True
        ss = summary["scanners"]["echo_scanner"]
        assert ss["scans"] == 2
        assert ss["errors"] == 0


def test_eval_no_scanner_no_scan_dir() -> None:
    """`eval()` without a scanner doesn't touch the scans/ tree."""
    from inspect_ai import eval

    with tempfile.TemporaryDirectory() as log_dir:
        eval(
            tasks=_task(2),
            log_dir=log_dir,
            model="mockllm/model",
            display="none",
        )
        assert not (Path(log_dir) / "scans").exists()


# --- CLI integration --------------------------------------------------------


def test_cli_resolve_yaml_config() -> None:
    """`--scanner foo.yaml` loads the YAML via `EvalScannerConfig.from_file`."""
    import yaml

    from inspect_ai._cli._scanner import resolve_cli_scanner

    body = yaml.safe_dump({"name": "cli_yaml", "scanners": [{"name": "echo_scanner"}]})
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "scanner.yaml"
        cfg_path.write_text(body)

        result = resolve_cli_scanner(str(cfg_path), scanner_arg=())

    from inspect_ai import EvalScannerConfig

    assert isinstance(result, EvalScannerConfig)
    assert result.name == "cli_yaml"


def test_cli_resolve_python_file() -> None:
    """`--scanner foo.py` loads @scanner-decorated functions from a Python file."""
    from inspect_ai._cli._scanner import resolve_cli_scanner

    py_body = """\
from inspect_scout import Result, Transcript, scanner


@scanner(messages="all", name="cli_py_scanner")
def cli_py_scanner():
    async def scan(transcript: Transcript) -> Result:
        return Result(value=transcript.transcript_id)
    return scan
"""
    with tempfile.TemporaryDirectory() as d:
        py_path = Path(d) / "scanners.py"
        py_path.write_text(py_body)

        result = resolve_cli_scanner(str(py_path), scanner_arg=())

    assert isinstance(result, list)
    assert len(result) == 1
    assert callable(result[0])


def test_cli_resolve_registry_ref() -> None:
    """`--scanner pkg/name` resolves a registered scanner by name."""
    from inspect_scout._scanner.scanner import scanner_create  # noqa: F401

    from inspect_ai._cli._scanner import resolve_cli_scanner

    # `scanner_a` is registered at module-load time as a bare name.
    # Scout's `scanner_create` requires a "/" qualified name, so this
    # path uses scout's built-in `inspect_scout/llm_scanner` instead.
    result = resolve_cli_scanner(
        "inspect_scout/llm_scanner",
        scanner_arg=("question=anything?", "answer=boolean"),
    )

    assert isinstance(result, list)
    assert len(result) == 1
    assert callable(result[0])


def test_cli_resolve_unknown_spec_raises() -> None:
    """A spec that doesn't match any pattern raises `click.UsageError`.

    CLI-arg shape errors should surface as click usage errors so the
    process exits with code 2 and click prints "Usage: ..." rather than
    a Python traceback.
    """
    import click

    from inspect_ai._cli._scanner import resolve_cli_scanner

    with pytest.raises(click.UsageError, match="Could not resolve --scanner"):
        resolve_cli_scanner("not_a_file_or_ref", scanner_arg=())


def test_cli_resolve_none() -> None:
    """No `--scanner` flag returns None (no scanner runs)."""
    from inspect_ai._cli._scanner import resolve_cli_scanner

    assert resolve_cli_scanner(None, scanner_arg=()) is None


def test_cli_overrides_promote_list_to_config() -> None:
    """CLI scan-* flags wrap a bare scanner list into `EvalScannerConfig`.

    A registry-ref scanner alone returns a list; once any override
    (e.g. `--scan-tags`) is set, the resolver wraps it so the override
    has a place to land.
    """
    from inspect_ai import EvalScannerConfig
    from inspect_ai._cli._scanner import resolve_cli_scanner

    result = resolve_cli_scanner(
        "inspect_scout/llm_scanner",
        scanner_arg=("question=anything?", "answer=boolean"),
        scan_tags="alpha,beta",
        scan_name="cli_scan",
        scans="/tmp/scan-out",
        scan_metadata=("env=ci", "owner=team"),
        scan_filter=("error = ''",),
        scan_model="mockllm/model",
        scan_model_base_url="http://localhost:1234",
        scan_model_arg=("api_key=abc",),
        scan_model_role=("grader=mockllm/model",),
    )

    assert isinstance(result, EvalScannerConfig)
    assert result.name == "cli_scan"
    assert result.scans == "/tmp/scan-out"
    assert result.tags == ["alpha", "beta"]
    assert result.metadata == {"env": "ci", "owner": "team"}
    assert result.filter == ["error = ''"]
    assert result.model == "mockllm/model"
    assert result.model_base_url == "http://localhost:1234"
    assert result.model_args == {"api_key": "abc"}
    assert "grader" in (result.model_roles or {})


def test_cli_overrides_win_over_yaml_config() -> None:
    """CLI scan-* flags override values from a YAML config file.

    Otherwise users would have to edit the YAML for a one-off run.
    """
    import yaml

    from inspect_ai._cli._scanner import resolve_cli_scanner

    body = yaml.safe_dump(
        {
            "name": "from_yaml",
            "scanners": [{"name": "echo_scanner"}],
            "tags": ["yaml-tag"],
            "model": "yaml-model/x",
        }
    )
    with tempfile.TemporaryDirectory() as d:
        cfg_path = Path(d) / "scanner.yaml"
        cfg_path.write_text(body)

        result = resolve_cli_scanner(
            str(cfg_path),
            scanner_arg=(),
            scan_name="cli-name",
            scan_tags="cli-tag",
            scan_model="cli-model/x",
        )

    from inspect_ai import EvalScannerConfig

    assert isinstance(result, EvalScannerConfig)
    # CLI values won
    assert result.name == "cli-name"
    assert result.tags == ["cli-tag"]
    assert result.model == "cli-model/x"


def test_cli_overrides_without_scanner_raise() -> None:
    """Setting `--scan-*` overrides without `--scanner` is a usage error."""
    import click

    from inspect_ai._cli._scanner import resolve_cli_scanner

    with pytest.raises(click.UsageError, match="require --scanner"):
        resolve_cli_scanner(None, scanner_arg=(), scan_model="mockllm/model")


def test_cli_scan_generate_config_loads_from_file() -> None:
    """`--scan-generate-config FILE` loads a `GenerateConfig` from YAML/JSON."""
    import yaml

    from inspect_ai._cli._scanner import resolve_cli_scanner
    from inspect_ai.model import GenerateConfig

    gen_body = yaml.safe_dump({"max_tokens": 42, "temperature": 0.3})
    with tempfile.TemporaryDirectory() as d:
        gen_path = Path(d) / "generate.yaml"
        gen_path.write_text(gen_body)

        result = resolve_cli_scanner(
            "inspect_scout/llm_scanner",
            scanner_arg=("question=anything?", "answer=boolean"),
            scan_generate_config=str(gen_path),
        )

    from inspect_ai import EvalScannerConfig

    assert isinstance(result, EvalScannerConfig)
    assert isinstance(result.generate_config, GenerateConfig)
    assert result.generate_config.max_tokens == 42
    assert result.generate_config.temperature == 0.3


def test_cli_eval_set_command_with_scanner_yaml() -> None:
    """End-to-end: `inspect eval-set --scanner foo.yaml` runs scanners.

    Drives the click command with `CliRunner.isolated_filesystem()` so
    relative task/config paths resolve under a temporary working dir
    (eval-set's task loader globs from the cwd). Verifies the eval
    succeeded and the scan parquet landed.
    """
    import yaml
    from click.testing import CliRunner

    from inspect_ai._cli.eval import eval_set_command

    task_body = """\
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate


@task
def hello_task() -> Task:
    return Task(
        dataset=[Sample(input="hi", target="hi")],
        solver=generate(),
    )
"""
    body = yaml.safe_dump({"name": "cli_e2e", "scanners": [{"name": "echo_scanner"}]})

    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("hello_task.py").write_text(task_body)
        Path("scanner.yaml").write_text(body)

        result = runner.invoke(
            eval_set_command,
            [
                "hello_task.py",
                "--model",
                "mockllm/model",
                "--log-dir",
                "logs",
                "--scanner",
                "scanner.yaml",
                "--retry-attempts",
                "0",
                "--display",
                "none",
            ],
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
        scan_dir = _scan_dir("logs")
        assert (scan_dir / "echo_scanner.parquet").exists()
        spec = json.loads((scan_dir / "_scan.json").read_text())
        assert spec["scan_name"] == "cli_e2e"


# --- end CLI integration ----------------------------------------------------


def test_max_connections_caps_eval_plus_scanner_when_model_is_shared() -> None:
    """`max_connections` caps total in-flight calls across eval + scanner.

    When the scanner inherits the eval's model (no `model` field on the
    config), both sides reach the same `ModelAPI`. Inspect's connection
    semaphore is keyed by `connection_key()`, so a single semaphore
    governs both — `max_connections` should bound the *combined* peak.

    Approach: register a tracking `ModelAPI` whose `generate` increments
    a counter on entry, sleeps briefly so other tasks can pile up, then
    decrements on exit. Run an `eval_set` with N samples (each makes
    one solver `generate`) plus a scanner that makes one `generate` per
    sample, for `2N` total calls. Without the cap, peak would reach
    `min(2N, max_samples)`. With the cap, peak must stay ≤
    `max_connections`. We also assert peak ≥ 2 to confirm the test
    actually exercises concurrency (otherwise the cap is meaningless).
    """
    import anyio

    from inspect_ai._util.registry import _registry
    from inspect_ai.model import ModelAPI, ModelOutput
    from inspect_ai.model._generate_config import GenerateConfig
    from inspect_ai.model._registry import modelapi
    from inspect_ai.tool import ToolChoice, ToolInfo

    state = {"in_flight": 0, "peak": 0, "total_calls": 0}

    class _TrackingAPI(ModelAPI):
        def __init__(
            self,
            model_name: str,
            base_url: str | None = None,
            api_key: str | None = None,
            config: GenerateConfig = GenerateConfig(),
            **model_args: Any,
        ) -> None:
            super().__init__(
                model_name=model_name,
                base_url=base_url,
                api_key=api_key,
                config=config,
            )

        async def generate(
            self,
            input: list,
            tools: list[ToolInfo],
            tool_choice: ToolChoice,
            config: GenerateConfig,
        ) -> ModelOutput:
            # increment + peak update happen without an intervening
            # await, so they're atomic on the single event loop
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
            state["total_calls"] += 1
            try:
                # hold the call long enough for sibling tasks to pile up
                await anyio.sleep(0.05)
                return ModelOutput.from_content(self.model_name, "ok")
            finally:
                state["in_flight"] -= 1

        def connection_key(self) -> str:
            # isolate this API's semaphore from any other ModelAPI
            return self.model_name

    @modelapi(name="trackapi")
    def _trackapi() -> type[ModelAPI]:
        return _TrackingAPI

    @scanner(messages="all", name="generate_calling_scanner")
    def generate_calling_scanner():
        from inspect_ai.model import get_model

        async def scan(transcript: Transcript) -> Result:
            await get_model().generate("hello")
            return Result(value="ok")

        return scan

    n_samples = 8
    max_conn = 2
    try:
        with tempfile.TemporaryDirectory() as log_dir:
            success, _ = eval_set(
                tasks=_task(n_samples),
                log_dir=log_dir,
                scanner=[generate_calling_scanner()],
                model="trackapi/test",
                max_connections=max_conn,
                # let many samples run at once so the cap (not the
                # sample fan-out) is the limiting factor
                max_samples=n_samples,
                retry_attempts=0,
                display="none",
            )
            assert success

        # sanity: actual concurrency happened, otherwise the cap is
        # vacuously satisfied and proves nothing
        assert state["peak"] >= 2, (
            f"no concurrency observed (peak={state['peak']}); "
            "test cannot validate the cap"
        )
        # the cap held — combined eval + scanner peak respected it
        assert state["peak"] <= max_conn, (
            f"peak in-flight {state['peak']} exceeded max_connections "
            f"{max_conn} — eval and scanner do not share the pool"
        )
        # both sides reached the API: n solver calls + n scanner calls
        assert state["total_calls"] == 2 * n_samples, (
            f"expected {2 * n_samples} total generate calls "
            f"(eval + scanner), got {state['total_calls']}"
        )
    finally:
        # clean up so other tests don't see the registered API
        _registry.pop("modelapi:trackapi", None)


# --- scan display state -----------------------------------------------------
#
# `scan_display.ScanDisplayState` is updated by the per-sample scan dispatch
# path so the Textual `ScanView` widget can render scout's `scan_panel`
# from in-memory state (no per-tick file I/O). These tests pin the
# semantics: `scan_init` activates state with a Summary; `scan_eval_sample`
# pushes an updated Summary after each `recorder.record()`.


def test_scan_display_inactive_when_no_scanner() -> None:
    """`is_active()` is False before any scan_init runs."""
    from inspect_ai._eval.task.scan_display import get_state, reset_state

    reset_state()
    assert get_state().active is False
    assert get_state().spec is None
    assert get_state().samples_completed == 0


def test_scan_display_activates_after_scan_init() -> None:
    """After eval_set runs scan_init, state is active with a spec.

    The eval_set call writes records, each of which triggers a
    `push_results`. After the run, `samples_completed == n` (one push
    per (sample, scanner) pair, summing across scanners).
    """
    from inspect_ai._eval.task.scan_display import get_state, reset_state

    reset_state()

    n = 3
    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=_task(n),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success

        state = get_state()
        assert state.active is True, "scan_init should mark the state active"
        assert state.spec is not None
        assert state.scan_dir is not None
        # one scanner x n samples → n pushes
        assert state.samples_completed == n
        assert state.scanners_seen == {"echo_scanner"}
        assert state.summary is not None
        assert state.summary.scanners["echo_scanner"].scans == n


def test_scan_display_push_results_increments_count() -> None:
    """Each `push_results` bumps samples_completed and replaces the summary."""
    from inspect_scout._recorder.summary import Summary

    from inspect_ai._eval.task.scan_display import (
        get_state,
        push_results,
        reset_state,
        set_active,
    )

    reset_state()

    # need a real ScanSpec — easiest is to drive it through eval_set
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(1),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        snapshot = get_state()
        assert snapshot.spec is not None
        assert snapshot.scan_dir is not None

        # construct a fresh Summary whose scanner counts differ — proves
        # push_results replaces the summary rather than merging it.
        # explicit seed of `samples_completed=5` because set_active
        # doesn't auto-preserve the prior counter — callers are
        # responsible for passing the seed (see scan_init's prior-run
        # seeding for the reattach case).
        new_summary = Summary(complete=False, scanners=["echo_scanner"])
        new_summary.scanners["echo_scanner"].scans = 99
        set_active(
            scan_dir=snapshot.scan_dir,
            spec=snapshot.spec,
            summary=new_summary,
            samples_completed=5,
        )

        push_results(summary=new_summary, scanner="echo_scanner")
        assert get_state().samples_completed == 6
        assert get_state().summary is new_summary

        push_results(summary=new_summary, scanner="echo_scanner")
        assert get_state().samples_completed == 7


def test_scan_display_push_drops_when_inactive() -> None:
    """`push_results` before `set_active` is a silent no-op (no crash)."""
    from inspect_scout._recorder.summary import Summary

    from inspect_ai._eval.task.scan_display import (
        get_state,
        push_results,
        reset_state,
    )

    reset_state()
    summary = Summary(complete=False, scanners=["echo_scanner"])
    push_results(summary=summary, scanner="echo_scanner")
    assert get_state().active is False
    assert get_state().samples_completed == 0


def test_scan_display_short_circuit_marks_completed_on_limit_increase() -> None:
    """Resume-scan short-circuit calls `mark_completed` for reused samples.

    When eval_set is rerun against an existing scan dir with a higher
    `limit`, the prior run's samples are reused via PreviousTask (their
    tids match the snapshot) and the resume-scan path short-circuits
    them without firing `push_results`. Without `mark_completed`, the
    progress counter would only reflect newly-scanned samples and stall
    short of `samples_total`.

    Mirrors the user-facing scenario: `--limit 3` then `--limit 5` on
    the same dataset. samples_completed reaches 5 = 3 mark_completed
    (reused) + 2 push_results (new), matching `samples_total = 5 × 1`.
    """
    from inspect_ai._eval.task.scan_display import get_state, reset_state

    reset_state()

    # dataset must stay the same length across runs — what changes is
    # the eval_set `limit`, which slices it. eval_log_sample_source
    # only reuses when `eval_log.eval.dataset.samples == len(dataset)`,
    # so we keep the dataset at 10 and vary the limit.
    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(10)],
            solver=generate(),
        )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: limit 3 → 3 push_results
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            limit=3,
            display="none",
        )
        assert get_state().samples_completed == 3

        # run 2: limit 5 — the prior 3 samples reuse via PreviousTask
        # and short-circuit (mark_completed × 3); samples 4 and 5 are
        # new (push_results × 2). Total: 5, matching samples_total of
        # 5 × 1 scanner.
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            limit=5,
            display="none",
        )
        assert get_state().samples_completed == 5, (
            "expected 3 mark_completed (reused) + 2 push_results (new) = 5; "
            f"got {get_state().samples_completed}"
        )


def test_scan_display_no_overcount_on_re_execution() -> None:
    """Re-executions don't double-count against `samples_total`.

    When samples can't be reused via PreviousTask (e.g. a continue_on_fail
    run where errored samples are re-executed with new uuids), the new
    uuids aren't in the prior snapshot, so resume_scan_previous_sample
    takes the dispatch branch (no `mark_completed`). `scan_eval_sample`
    fires `push_results` for each scanner. samples_completed grows by
    n_samples × n_scanners — never exceeds `samples_total` (would have
    if we'd seeded from prior cumulative summary.scans).
    """
    from inspect_ai._eval.task.scan_display import get_state, reset_state

    reset_state()

    n = 3
    fails_first_time = _first_attempt_fails()

    def make_task():
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(n)],
            solver=[fails_first_time, generate()],
        )

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: every sample errors first attempt, gets logged + scanned
        # then continue_on_fail records the fail. summary.scans = n.
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        assert get_state().samples_completed == n

        # run 2: every errored sample re-executes with a new uuid. Old
        # tids are orphans, new tids aren't in the snapshot, so
        # resume_scan_previous_sample takes the dispatch branch (not the
        # mark_completed short-circuit). push_results fires n times.
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            continue_on_fail=True,
            display="none",
        )
        # exactly n pushes — not 2n (would happen if we still seeded
        # with prior cumulative summary.scans) and not 0 (would happen
        # if we never recorded re-executed samples)
        assert get_state().samples_completed == n, (
            f"expected {n} samples_completed from re-execution pushes only; "
            f"got {get_state().samples_completed}"
        )


def test_scan_dir_preserves_reused_sample_rows_across_runs() -> None:
    """A reused sample's parquet row carries forward — same timestamp.

    When eval_set is rerun with a higher limit, samples already
    completed in the prior run are reused via PreviousTask (their uuids
    are preserved). The scanner-level resume short-circuit
    (`resume_scan_previous_sample` → `mark_completed`) must NOT
    re-record those samples — their existing parquet rows should carry
    forward unchanged, with the same timestamp from the prior run.

    This is the regression test for the case where reused samples were
    re-scanned despite their tids being in the prior parquet,
    introducing wasted LLM calls and overwriting the prior rows.
    """
    import pyarrow.parquet as pq

    def make_task() -> Task:
        # 10 samples in the dataset; limit will slice into it
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(10)],
            solver=generate(),
        )

    def read_rows(path: UPath) -> dict[str, str]:
        """Map transcript_id → timestamp by reading the parquet."""
        pf = pq.ParquetFile(path.as_posix())
        out: dict[str, str] = {}
        for i in range(pf.metadata.num_row_groups):
            tbl = pf.read_row_group(i, columns=["transcript_id", "timestamp"])
            for tid, ts in zip(
                tbl.column("transcript_id").to_pylist(),
                tbl.column("timestamp").to_pylist(),
            ):
                if tid:
                    out[tid] = ts
        return out

    with tempfile.TemporaryDirectory() as log_dir:
        # run 1: limit 3 → 3 records, captured here as the prior set
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            limit=3,
            display="none",
        )
        scan_dir = _scan_dir(log_dir)
        prior_rows = read_rows(scan_dir / "echo_scanner.parquet")
        assert len(prior_rows) == 3, f"expected 3 prior rows, got {len(prior_rows)}"

        # run 2: limit 5 — samples 1-3 reuse via PreviousTask; their uuids
        # match the prior snapshot, so resume_scan_previous_sample should
        # short-circuit them (mark_completed only — no recorder.record).
        # Samples 4-5 are fresh → 2 new records.
        eval_set(
            tasks=make_task(),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            limit=5,
            display="none",
        )
        post_rows = read_rows(scan_dir / "echo_scanner.parquet")

        # 5 distinct rows total
        assert len(post_rows) == 5, (
            f"expected 5 post-run rows, got {len(post_rows)}: "
            f"{sorted(post_rows.keys())}"
        )

        # each prior tid is still present and its timestamp is unchanged.
        # If reused samples were re-scanned, their timestamps would have
        # been overwritten with run-2 timestamps (or the prior tids would
        # be missing entirely, replaced by fresh records).
        for tid, prior_ts in prior_rows.items():
            assert tid in post_rows, (
                f"prior tid {tid} missing after resume — was it overwritten "
                f"by a re-execution with a new uuid? "
                f"post_rows keys: {sorted(post_rows.keys())}"
            )
            assert post_rows[tid] == prior_ts, (
                f"prior tid {tid} was re-recorded — timestamp changed "
                f"from {prior_ts} to {post_rows[tid]}. The resume_scan "
                f"short-circuit failed to skip a reused sample."
            )

        # exactly 2 NEW tids in the post-run set (samples 4 and 5)
        new_tids = set(post_rows.keys()) - set(prior_rows.keys())
        assert len(new_tids) == 2, (
            f"expected 2 new tids from samples 4 and 5, got {len(new_tids)}"
        )


def test_scan_display_clears_stale_transcripts_snapshot_on_reattach() -> None:
    """`spec.transcripts` is cleared from the display copy on reattach.

    After the first run finalizes, `<scan_dir>/_scan.json` carries a
    `transcripts` snapshot with the run's transcript ids. The next run's
    `scan_init` reads that spec back via `recorder.attach`, but copies
    it with `transcripts=None` for the display so `scan_title` doesn't
    show a stale count while the new run is in progress.
    """
    from inspect_scout._scanspec import ScanSpec

    from inspect_ai._eval.task.scan_display import get_state, reset_state

    reset_state()

    with tempfile.TemporaryDirectory() as log_dir:
        # first run finalizes a snapshot to disk
        eval_set(
            tasks=_task(3),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        # confirm on-disk snapshot is populated
        scan_dir = _scan_dir(log_dir)
        on_disk_spec = ScanSpec.model_validate_json(
            (scan_dir / "_scan.json").read_text()
        )
        assert on_disk_spec.transcripts is not None
        assert len(on_disk_spec.transcripts.transcript_ids) == 3

        # second run reattaches; scan_init clears spec.transcripts on
        # the display copy. After the second run, get_state().spec
        # is what set_active stored at scan_init — should have
        # transcripts=None even though the on-disk snapshot was
        # refreshed by the second run's finalize.
        eval_set(
            tasks=_task(3),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        state = get_state()
        assert state.spec is not None
        assert state.spec.transcripts is None, (
            "expected display copy of spec to have transcripts=None on reattach; "
            f"got transcripts={state.spec.transcripts}"
        )


def test_scan_display_strips_max_transcripts_from_options() -> None:
    """`spec.options.max_transcripts` is stripped from the display copy.

    `max_transcripts` is scout's worker-pool concurrency knob — only
    meaningful for scout's standalone `scan_async` orchestration.
    inspect_ai's eval_set dispatches scanners via `_scan_one` directly,
    so the value has no effect on the run. Showing it in the panel
    config line ("max_transcripts: 25") would be misleading.

    Setting it to None on the display copy makes scout's
    `scan_config_str` skip it via `model_dump(exclude_none=True)`.
    """
    from inspect_ai._eval.task.scan_display import get_state, reset_state

    reset_state()

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )

        state = get_state()
        assert state.spec is not None
        assert state.spec.options.max_transcripts is None, (
            "expected max_transcripts stripped to None on display spec; "
            f"got {state.spec.options.max_transcripts}"
        )


def test_scan_display_reset_clears_state() -> None:
    from inspect_ai._eval.task.scan_display import get_state, reset_state

    reset_state()
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=[echo_scanner()],
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert get_state().active is True

    reset_state()
    state = get_state()
    assert state.active is False
    assert state.spec is None
    assert state.summary is None
    assert state.samples_completed == 0
    assert state.scanners_seen == set()


# --- filter parity with scout ----------------------------------------------
#
# `_sample_matches_filters` evaluates `EvalScannerConfig.filter` clauses
# using scout's `condition_as_sql` against an in-memory sqlite row.
# The row must populate every column scout's transcript schema exposes
# (`inspect_scout/_transcript/eval_log.py:TranscriptColumns`) so a
# filter that's valid against scout's direct scan path also evaluates
# correctly here. Missing columns either silently mis-evaluate (sqlite's
# DQS-compat treats `"col" = 'x'` as `'col' = 'x'` → False when col
# doesn't exist) or fail with malformed-JSON errors on JSON-path
# filters like `sample_metadata.group = 'a'`.


def _make_eval_sample(
    *,
    sample_id: int | str = 1,
    epoch: int = 1,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
    total_time: float | None = 1.0,
    working_time: float | None = 1.0,
    model_usage: dict[str, Any] | None = None,
) -> Any:
    """Construct a minimal EvalSample for filter unit tests."""
    from inspect_ai._util.error import EvalError
    from inspect_ai.log._log import EvalSample
    from inspect_ai.model import ModelUsage

    return EvalSample(
        id=sample_id,
        epoch=epoch,
        input="q",
        target="t",
        metadata=metadata or {},
        error=EvalError(message=error, traceback="", traceback_ansi="")
        if error is not None
        else None,
        total_time=total_time,
        working_time=working_time,
        model_usage=(
            {k: ModelUsage(**v) for k, v in model_usage.items()} if model_usage else {}
        ),
    )


def _make_eval_spec(
    *,
    task: str = "my_task",
    model: str = "openai/gpt-4o",
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    task_args: dict[str, Any] | None = None,
) -> Any:
    """Construct a minimal EvalSpec for filter unit tests.

    Uses `model_construct` to skip Pydantic validation — we only set
    the handful of fields the filter row builder reads.
    """
    from inspect_ai.log._log import EvalConfig, EvalDataset, EvalSpec
    from inspect_ai.model._generate_config import GenerateConfig

    return EvalSpec.model_construct(
        eval_id="eid",
        run_id="rid",
        created="2026-05-08T00:00:00+00:00",
        task=task,
        task_id="tid",
        task_args=task_args or {},
        task_args_passed=task_args or {},
        tags=tags,
        dataset=EvalDataset(samples=1),
        model=model,
        model_generate_config=GenerateConfig(),
        model_args={},
        config=EvalConfig(),
        metadata=metadata or {},
    )


def test_filter_matches_eval_model() -> None:
    """`model = '...'` evaluates against the eval-level model."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    sample = _make_eval_sample()
    spec = _make_eval_spec(model="openai/gpt-4o")
    assert _sample_matches_filters(sample, ["model = 'openai/gpt-4o'"], eval_spec=spec)
    assert not _sample_matches_filters(
        sample, ["model = 'openai/gpt-5'"], eval_spec=spec
    )


def test_filter_matches_total_tokens() -> None:
    """`total_tokens > 0` is computed from `EvalSample.model_usage`."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    used = _make_eval_sample(
        model_usage={"openai/gpt-4o": {"total_tokens": 100}},
    )
    spec = _make_eval_spec()
    assert _sample_matches_filters(used, ["total_tokens > 0"], eval_spec=spec)
    assert not _sample_matches_filters(used, ["total_tokens > 1000"], eval_spec=spec)

    unused = _make_eval_sample(model_usage={})
    assert not _sample_matches_filters(unused, ["total_tokens > 0"], eval_spec=spec)


def test_filter_matches_working_time() -> None:
    """`working_time` is on `EvalSample`, not derived from `total_time`."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    sample = _make_eval_sample(working_time=2.5)
    spec = _make_eval_spec()
    assert _sample_matches_filters(sample, ["working_time > 1"], eval_spec=spec)
    assert not _sample_matches_filters(sample, ["working_time > 5"], eval_spec=spec)


def test_filter_matches_sample_metadata_json_path() -> None:
    """`sample_metadata.group = 'a'` uses sqlite's `json_extract`.

    Without proper JSON-string serialization of the metadata column,
    scout's emitted SQL fails with `OperationalError: malformed JSON`.
    """
    from inspect_ai._eval.task.scan import _sample_matches_filters

    a = _make_eval_sample(metadata={"group": "a", "n": 1})
    b = _make_eval_sample(metadata={"group": "b", "n": 2})
    spec = _make_eval_spec()
    assert _sample_matches_filters(a, ["sample_metadata.group = 'a'"], eval_spec=spec)
    assert not _sample_matches_filters(
        a, ["sample_metadata.group = 'b'"], eval_spec=spec
    )
    assert _sample_matches_filters(b, ["sample_metadata.group = 'b'"], eval_spec=spec)


def test_filter_matches_eval_metadata_json_path() -> None:
    """`eval_metadata.foo = 'bar'` evaluates against `EvalSpec.metadata`."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    sample = _make_eval_sample()
    spec = _make_eval_spec(metadata={"foo": "bar", "n": 7})
    assert _sample_matches_filters(
        sample, ["eval_metadata.foo = 'bar'"], eval_spec=spec
    )
    assert not _sample_matches_filters(
        sample, ["eval_metadata.foo = 'baz'"], eval_spec=spec
    )


def test_filter_matches_task_set() -> None:
    """`task_set = '...'` evaluates against `EvalSpec.task`."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    sample = _make_eval_sample()
    spec = _make_eval_spec(task="my_task")
    assert _sample_matches_filters(sample, ["task_set = 'my_task'"], eval_spec=spec)
    assert not _sample_matches_filters(
        sample, ["task_set = 'other_task'"], eval_spec=spec
    )


def test_filter_unknown_column_raises() -> None:
    """A filter referencing a nonexistent column raises, not silently False."""
    import sqlite3

    from inspect_ai._eval.task.scan import _sample_matches_filters

    sample = _make_eval_sample()
    spec = _make_eval_spec()
    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        _sample_matches_filters(sample, ["nonexistent_column = 'x'"], eval_spec=spec)


def test_filter_error_column_regression() -> None:
    """`error = ''` and `error != ''` (existing behavior) still works."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    spec = _make_eval_spec()
    success = _make_eval_sample(error=None)
    failed = _make_eval_sample(error="boom")
    assert _sample_matches_filters(success, ["error = ''"], eval_spec=spec)
    assert not _sample_matches_filters(failed, ["error = ''"], eval_spec=spec)
    assert _sample_matches_filters(failed, ["error != ''"], eval_spec=spec)
    assert not _sample_matches_filters(success, ["error != ''"], eval_spec=spec)


def test_filter_no_eval_spec_still_works_for_sample_only_columns() -> None:
    """Calling without eval_spec leaves eval-level columns NULL but sample-level filters (error, score, etc.) still work."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    sample = _make_eval_sample(error="oops")
    assert _sample_matches_filters(sample, ["error != ''"])


def test_filter_safe_against_malicious_score_name() -> None:
    """Column names from `score_*` expansion can't break the filter SQL.

    Score names come from scorer config — typically developer-controlled
    but could be loaded from external eval logs or arbitrary inputs.
    A malicious score name like `evil") CHECK(0=1)) --` would inject
    a constraint into our `CREATE TABLE` if column names aren't
    properly escaped. The fix: SQL-escape `"` → `""` per the standard
    identifier-quoting rule.
    """
    from inspect_ai._eval.task.scan import _sample_matches_filters
    from inspect_ai.scorer._metric import Score

    sample = _make_eval_sample()
    sample.scores = {
        # benign one alongside an injection attempt that would, if
        # interpolated naively, add a CHECK(0=1) constraint that
        # makes every INSERT fail
        "good": Score(value=1),
        'evil") CHECK(0=1)) --': Score(value=2),
    }
    spec = _make_eval_spec()

    # filters that don't reference the malicious column should still
    # evaluate correctly — proves the malicious name doesn't break the
    # CREATE TABLE / INSERT pipeline
    assert _sample_matches_filters(sample, ["epoch = 1"], eval_spec=spec)
    assert _sample_matches_filters(sample, ["error = ''"], eval_spec=spec)

    """Calling without eval_spec leaves eval-level columns NULL but
    sample-level filters (error, score, etc.) still work."""
    from inspect_ai._eval.task.scan import _sample_matches_filters

    sample = _make_eval_sample(error="oops")
    assert _sample_matches_filters(sample, ["error != ''"])
