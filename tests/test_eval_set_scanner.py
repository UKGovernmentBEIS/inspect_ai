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


def test_scanjob_config_filter_skips_unmatched_samples() -> None:
    """A SQL `filter` on `ScanJobConfig` excludes non-matching samples.

    Setup — 4 samples (ids 1..4), solver fails first attempt for 3, 4
    so they end up logged with `transcript.error` set. Pass the scanner
    via `ScanJobConfig` with `filter="error = ''"` (scout's convention:
    successful samples have empty-string error, errored samples have
    the message string). Only the eval-successful samples (1, 2) should
    be scanned — samples 3, 4 are skipped before the scanner runs.
    """
    from inspect_scout import ScanJobConfig
    from inspect_scout._scanspec import ScannerSpec

    n = 4
    fails_3_4_first_time = _first_attempt_fails_for(3, 4)

    def make_task() -> Task:
        return Task(
            dataset=[Sample(input=f"q{i}", target=str(i)) for i in range(1, n + 1)],
            solver=[fails_3_4_first_time, generate()],
        )

    config = ScanJobConfig(
        scanners=[ScannerSpec(name="echo_scanner", file=__file__)],
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


def _validation_kwarg() -> dict[str, object]:
    """Build a minimal `validation` kwarg for ScanJobConfig."""
    from inspect_scout._validation.types import ValidationCase, ValidationSet

    return {
        "echo_scanner": ValidationSet(
            cases=[ValidationCase(id="any-id", target="any-target")],
            predicate="eq",
        )
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("transcripts", "some/external/logs"),
        ("worklist", [{"scanner": "echo_scanner", "transcripts": ["abc"]}]),
        ("limit", 5),
        ("shuffle", True),
        ("max_processes", 2),
        ("validation", _validation_kwarg()),
        ("log_level", "debug"),
    ],
)
def test_scanjob_config_rejects_unsupported_fields(field: str, value: object) -> None:
    """Reject ScanJobConfig fields that conflict with eval_set."""
    from inspect_scout import ScanJobConfig
    from inspect_scout._scanspec import ScannerSpec

    from inspect_ai._util.error import PrerequisiteError

    config_kwargs: dict[str, object] = {
        "scanners": [ScannerSpec(name="echo_scanner", file=__file__)],
    }
    config_kwargs[field] = value
    config = ScanJobConfig(**config_kwargs)  # type: ignore[arg-type]

    with tempfile.TemporaryDirectory() as log_dir:
        with pytest.raises(PrerequisiteError, match=field):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=config,
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


@pytest.mark.parametrize(
    "field, value",
    [
        ("limit", 5),
        ("shuffle", True),
        ("max_processes", 2),
        ("validation", _validation_kwarg()),
        ("log_level", "debug"),
    ],
)
def test_scanjob_rejects_unsupported_fields(field: str, value: object) -> None:
    """Same validation must hit the `ScanJob` instance path.

    `ScanJob` exposes these as `@property` accessors backed by
    `_field` attributes, while `ScanJobConfig` has them as direct
    Pydantic fields. The validator uses `getattr`, so they share a
    code path — but a rename or default-change on either side could
    break only one without this dual coverage.
    """
    from inspect_scout import ScanJob

    from inspect_ai._util.error import PrerequisiteError

    job = ScanJob(scanners=[echo_scanner()], **{field: value})

    with tempfile.TemporaryDirectory() as log_dir:
        with pytest.raises(PrerequisiteError, match=field):
            eval_set(
                tasks=_task(2),
                log_dir=log_dir,
                scanner=job,
                model="mockllm/model",
                retry_attempts=0,
                display="none",
            )


def test_scanjob_config_scans_overrides_output_location() -> None:
    """`ScanJobConfig.scans` overrides where scan output is written.

    By default scan output lands at `<log_dir>/scans/scan_id=<id>/`. A
    user can redirect to an arbitrary location (e.g. an S3 bucket) by
    setting `scans` on the config — useful when scan results should
    live separately from the eval logs.
    """
    from inspect_scout import ScanJobConfig
    from inspect_scout._scanspec import ScannerSpec

    with tempfile.TemporaryDirectory() as log_dir:
        with tempfile.TemporaryDirectory() as scans_dir:
            config = ScanJobConfig(
                scanners=[ScannerSpec(name="echo_scanner", file=__file__)],
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


@pytest.mark.parametrize("scanner_kind", ["scanjob", "scanjob_config"])
def test_tags_and_metadata_written_to_scan_spec(scanner_kind: str) -> None:
    """`tags` and `metadata` on `ScanJob`/`ScanJobConfig` land in scan.json.

    Both fields are stored on the `ScanSpec` that scout writes to
    `_scan.json` at scan-init time. We extract them in `scan_eval_set_init`
    when constructing the spec, so they appear verbatim on disk.
    """
    from inspect_scout import ScanJob, ScanJobConfig
    from inspect_scout._scanspec import ScannerSpec

    tags = ["nightly", "experiment-42"]
    metadata = {"owner": "team-x", "iteration": 3}

    scanner: object
    if scanner_kind == "scanjob_config":
        scanner = ScanJobConfig(
            scanners=[ScannerSpec(name="echo_scanner", file=__file__)],
            tags=tags,
            metadata=metadata,
        )
    else:
        scanner = ScanJob(
            scanners=[echo_scanner()],
            tags=tags,
            metadata=metadata,
        )

    with tempfile.TemporaryDirectory() as log_dir:
        success, _ = eval_set(
            tasks=_task(2),
            log_dir=log_dir,
            scanner=scanner,  # type: ignore[arg-type]
            model="mockllm/model",
            retry_attempts=0,
            display="none",
        )
        assert success

        scan_dir = _scan_dir(log_dir)
        spec = json.loads((scan_dir / "_scan.json").read_text())
        assert spec["tags"] == tags
        assert spec["metadata"] == metadata


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


def test_scan_job_model_overrides_eval_model_for_scanner() -> None:
    """`ScanJob.model` is honored: the scanner uses it instead of the eval model.

    eval_set runs with `mockllm/eval-model`; the ScanJob carries
    `mockllm/scan-model`. The scanner's `model_usage` should show only
    the scan-model — confirming our integration calls scout's
    `init_scan_model_context` to override the active model just for the
    scanner call (not for the eval's solver/generate calls).
    """
    from inspect_scout import ScanJob, llm_scanner

    scanner_fn = llm_scanner(question="Did anything notable happen?", answer="boolean")
    job = ScanJob(scanners=[scanner_fn], model="mockllm/scan-model")

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
