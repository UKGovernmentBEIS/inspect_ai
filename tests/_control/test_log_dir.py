"""The ``inspect ctl ... --log-dir`` reader (``inspect_ai._control.log_dir``).

Rows, attempt folding, the key set and totals, per-sample reads against the
live terminal envelopes, the CRC-checked bounded re-reads, the delimited
walk, and the request counts the design states for these reads (see
design/ctl/log-dir-mode.md). The CLI surface is tested in test_ctl.py.
"""

import errno
import functools
import os
import shutil
import zipfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import anyio
import boto3
import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval, eval_async
from inspect_ai._control.events import decode_cursor
from inspect_ai._control.log_dir import consistency
from inspect_ai._control.log_dir.consistency import (
    LogChangedError,
    LogUnparseableError,
    read_consistently,
)
from inspect_ai._control.log_dir.samples import (
    SampleNotFoundError,
    SampleUnsupportedError,
    sample_detail,
    sample_events,
    sample_messages,
    sample_store,
)
from inspect_ai._control.log_dir.select import (
    KnownKey,
    MemberSnapshot,
    SampleKey,
    select_source,
    totals,
)
from inspect_ai._control.log_dir.snapshot import (
    LogDirIndex,
    LogicalTask,
    identity_row,
    index_log_dir,
    read_plan,
    read_snapshot,
    read_task_views,
    sample_listing,
    task_row,
)
from inspect_ai._control.log_dir.walk import walk_log_dir
from inspect_ai._control.state import _iso_to_timestamp
from inspect_ai._util.async_zip import AsyncZipReader, ZipCrcError
from inspect_ai._util.asyncfiles import AsyncFilesystem, FileContent
from inspect_ai.dataset import Sample
from inspect_ai.event import InfoEvent, ModelEvent
from inspect_ai.log import (
    EvalLog,
    EvalSample,
    EvalSpec,
    read_eval_log_async,
    write_eval_log_async,
)
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.filestore import (
    Manifest,
    SampleBufferFilestore,
    SampleManifest,
    SampleSegmentEntry,
    Segment,
    SegmentFile,
)
from inspect_ai.log._recorders.buffer.types import (
    CallPoolData,
    EventData,
    MessagePoolData,
    SampleData,
)
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver
from inspect_ai.util import store

# The additive keys every log-dir task row carries on top of the live keys.
_LIVE_TASK_ROW_KEYS = {
    "run_id",
    "eval_id",
    "task",
    "task_id",
    "model",
    "solver",
    "log_location",
    "status",
    "started_at",
    "completed_at",
    "paused",
    "paused_now",
    "quiesced",
    "held",
    "resolving",
    "attempts",
    "epochs",
    "samples",
    "total_tokens",
    "tokens_per_second",
    "total_messages",
    "refusals",
    "http_retries",
    "keep_alive",
    "process_paused",
    "process_paused_now",
    "paused_models",
    "api_version",
    "pid",
    "socket_path",
}
_LOG_DIR_TASK_ROW_KEYS = {
    "source",
    "log_target",
    "updated_at",
    "live_samples",
    "current_attempt",
    "incomplete",
    "unreadable",
}


@solver
def _fail_on(ids: list[int]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        store().set("seen", state.sample_id)
        if state.sample_id in ids:
            raise RuntimeError(f"sample {state.sample_id} failed")
        return state

    return solve


def _run_eval(
    log_dir: Path, name: str, *, fail_ids: list[int], fail_on_error: bool = False
) -> EvalLog:
    task = Task(
        name=name,
        dataset=[Sample(id=i, input=f"q{i}", target="x") for i in (1, 2, 3)],
        solver=[_fail_on(fail_ids), generate()],
        scorer=match(),
    )
    [log] = eval(
        task,
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        fail_on_error=False if not fail_on_error else True,
    )
    return log


@pytest.fixture(scope="module")
def finished_log(tmp_path_factory: pytest.TempPathFactory) -> EvalLog:
    """A finished (success) log: samples 1 and 3 complete, sample 2 errored."""
    log = _run_eval(tmp_path_factory.mktemp("finished"), "alpha", fail_ids=[2])
    # materialize the lazily loaded samples here: the sync loader refuses to
    # run inside the trio variants of the tests
    log.samples = list(log.samples or [])
    return log


@pytest.fixture
def log_dir(tmp_path: Path, finished_log: EvalLog) -> Path:
    shutil.copy(finished_log.location, tmp_path / Path(finished_log.location).name)
    return tmp_path


async def _attempt(source: EvalLog, directory: Path, stamp: str, **header: Any) -> Path:
    """Write ``source`` as another attempt of its task under a new timestamp."""
    log = source.model_copy(deep=True)
    for key, value in header.items():
        setattr(log, key, value)
    path = directory / f"{stamp}_{source.eval.task}_{source.eval.task_id}.eval"
    await write_eval_log_async(log, str(path))
    return path


async def _index(root: Path | str) -> tuple[LogDirIndex, list[dict[str, Any]]]:
    async with AsyncFilesystem() as fs:
        index = await index_log_dir(fs, str(root))
        views = await read_task_views(fs, index.tasks)
    return index, [task_row(view) for view in views]


async def _write_running_log(
    directory: Path,
    source: EvalLog,
    *,
    logged: list[int],
    sample_ids: list[int] | None,
) -> Path:
    """A running log (journal only, no header.json) holding ``logged`` samples."""
    running = await _start_running_log(
        directory, source, logged=logged, sample_ids=sample_ids
    )
    return running.location


class _RunningLog(NamedTuple):
    location: Path
    recorder: EvalRecorder
    spec: EvalSpec
    samples: dict[int | str, EvalSample]
    """The source log's samples by id, to flush more of them later."""

    def sample(self, sample_id: int, **update: Any) -> EvalSample:
        """A source sample (sample 1 renamed, for an id the source lacks)."""
        base = self.samples.get(sample_id) or self.samples[1].model_copy(
            update={"id": sample_id}
        )
        return base.model_copy(update=update)


async def _flush(running: _RunningLog, samples: list[EvalSample]) -> None:
    """Log ``samples`` and flush, as a worker's flush does (the log is replaced)."""
    for sample in samples:
        await running.recorder.log_sample(running.spec, sample)
    await running.recorder.flush(running.spec)


async def _start_running_log(
    directory: Path,
    source: EvalLog,
    *,
    logged: list[int],
    sample_ids: list[int] | None,
    log_shared: int | None = None,
) -> _RunningLog:
    """A running log holding ``logged`` samples, with its recorder kept open.

    ``log_shared`` records the eval as run with ``--log-shared``, so a
    shared buffer beside it is read.
    """
    assert source.samples is not None
    spec = source.eval.model_copy(
        update={
            "task_id": "RUNNINGTASK000000000000",
            "eval_id": "RUNNINGEVAL000000000000",
            "dataset": source.eval.dataset.model_copy(
                update={"sample_ids": sample_ids}
            ),
            "config": source.eval.config.model_copy(update={"log_shared": log_shared}),
        }
    )
    location = (
        directory / "2026-09-01T00-00-00+00-00_alpha_RUNNINGTASK000000000000.eval"
    )
    recorder = EvalRecorder(str(directory))
    await recorder.log_init(spec, str(location))
    await recorder.log_start(spec, source.plan)
    running = _RunningLog(location, recorder, spec, {s.id: s for s in source.samples})
    await _flush(running, [running.sample(i) for i in logged])
    return running


# --- task rows -----------------------------------------------------------------


async def test_finished_log_row_has_every_live_key_and_counts(
    log_dir: Path, finished_log: EvalLog
) -> None:
    index, rows = await _index(log_dir)
    [row] = rows
    assert set(row) == _LIVE_TASK_ROW_KEYS | _LOG_DIR_TASK_ROW_KEYS
    assert row["task_id"] == finished_log.eval.task_id
    assert row["eval_id"] == finished_log.eval.eval_id
    assert row["status"] == "completed"
    assert row["completed_at"] is not None
    assert row["source"] == "log_dir"
    assert row["log_target"] == f"log:{finished_log.eval.task_id}"
    assert row["current_attempt"] == "log"
    assert row["attempts"] == 1
    assert row["incomplete"] is False and row["unreadable"] == []
    assert row["samples"] == {
        "total": 3,
        "completed": 2,
        "errored": 1,
        "cancelled": 0,
        "in_flight": 0,
        "queued": None,
        "conflicted": 0,
        "unfinished": 0,
        "total_final": True,
        "pending_unlisted": 0,
    }
    assert row["total_tokens"] > 0
    # live-only state is null, not a false zero
    assert row["pid"] is None and row["paused"] is None and row["refusals"] is None
    assert row["paused_models"] == []


async def test_retries_fold_into_one_row_with_the_newest_current(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    await _attempt(
        finished_log,
        tmp_path,
        "2026-01-01T00-00-00+00-00",
        status="error",
        results=None,
    )
    newer = await _attempt(finished_log, tmp_path, "2026-01-02T00-00-00+00-00")
    _, rows = await _index(tmp_path)
    [row] = rows
    assert row["attempts"] == 2
    assert row["log_location"] == str(newer)
    assert row["samples"]["total_final"] is True


async def test_recovered_copy_is_current_over_its_original(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    original = await _attempt(finished_log, tmp_path, "2026-01-01T00-00-00+00-00")
    recovered = original.with_name(original.stem + "-recovered.eval")
    shutil.copy(original, recovered)
    _, rows = await _index(tmp_path)
    [row] = rows
    assert row["attempts"] == 2
    assert row["log_location"] == str(recovered)


async def test_distinct_tasks_get_distinct_rows_and_targets(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    await _attempt(finished_log, tmp_path, "2026-01-01T00-00-00+00-00")
    other = finished_log.model_copy(deep=True)
    other.eval.task_id = "OTHERTASK00000000000000"
    await _attempt(other, tmp_path, "2026-01-02T00-00-00+00-00")
    _, rows = await _index(tmp_path)
    assert sorted(r["log_target"] for r in rows) == sorted(
        [f"log:{finished_log.eval.task_id}", "log:OTHERTASK00000000000000"]
    )


async def test_running_log_reports_a_lower_bound_and_pending_rows(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    await _write_running_log(tmp_path, finished_log, logged=[1], sample_ids=[1, 2, 3])
    index, rows = await _index(tmp_path)
    [row] = rows
    assert row["status"] == "running"
    assert row["completed_at"] is None
    samples = row["samples"]
    assert samples["total"] == 3
    assert samples["total_final"] is False
    assert samples["pending_unlisted"] is None
    # running samples are visible only in a shared buffer, which it has none of
    assert samples["in_flight"] is None
    assert row["live_samples"] == "none"
    assert samples["completed"] == 1 and samples["unfinished"] == 2

    [view] = await _views(index)
    listing = sample_listing(view)
    assert listing.counts["completed"] == 1 and listing.counts["pending"] == 2
    assert [(r["sample_id"], r["status"]) for r in listing.samples] == [
        (1, "completed"),
        (2, "pending"),
        (3, "pending"),
    ]


async def _views(index: LogDirIndex) -> list[Any]:
    async with AsyncFilesystem() as fs:
        return await read_task_views(fs, index.tasks)


async def test_a_sample_the_recorded_selection_does_not_name_is_listed_and_readable(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    # a SampleSource can admit samples the header's sample_ids never recorded
    await _write_running_log(tmp_path, finished_log, logged=[99], sample_ids=[1])
    index, rows = await _index(tmp_path)
    [row] = rows
    assert row["samples"]["total"] == 2
    assert row["samples"]["unfinished"] == 1
    async with AsyncFilesystem() as fs:
        detail = await sample_detail(fs, index.tasks[0], "99", 1)
    assert detail["sample_id"] == 99


async def test_a_log_without_recorded_ids_counts_its_summaries(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    await _write_running_log(tmp_path, finished_log, logged=[1, 3], sample_ids=None)
    _, rows = await _index(tmp_path)
    [row] = rows
    assert row["samples"]["total"] == 2
    assert row["samples"]["total_final"] is False


async def test_finished_log_without_results_is_a_lower_bound(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    await _attempt(
        finished_log,
        tmp_path,
        "2026-01-01T00-00-00+00-00",
        status="error",
        results=None,
    )
    _, rows = await _index(tmp_path)
    [row] = rows
    assert row["samples"]["total_final"] is False
    assert row["samples"]["pending_unlisted"] is None


def test_totals_rules() -> None:
    assert totals(None, 4) == (4, False, None)
    assert totals(10, 4) == (10, True, 6)
    assert totals(4, 4) == (4, True, 0)
    # an authoritative total below the known keys is not final
    assert totals(3, 4) == (4, False, None)


async def test_select_source_reports_a_key_two_members_hold_as_a_conflict(
    log_dir: Path,
) -> None:
    index, _ = await _index(log_dir)
    async with AsyncFilesystem() as fs:
        member = await read_snapshot(fs, index.tasks[0].current)
    other = MemberSnapshot(plan=member.plan, summaries=dict(member.summaries))
    key = KnownKey(SampleKey("1", 1), 1)
    assert select_source([member], key).kind == "log"
    choice = select_source([member, other], key)
    assert choice.kind == "conflict" and len(choice.holders) == 2
    assert select_source([member], KnownKey(SampleKey("7", 1), 7)).kind == "pending"


# --- sample listing ------------------------------------------------------------


async def test_sample_listing_filters_caps_and_gates_content(log_dir: Path) -> None:
    index, _ = await _index(log_dir)
    [view] = await _views(index)

    full = sample_listing(view)
    assert full.counts["completed"] == 2 and full.counts["error"] == 1
    assert {r["log_location"] for r in full.samples} == {view.member.plan.file.location}
    assert all(r["shard"] is None and r["conflict"] is False for r in full.samples)
    # metadata-only default: status says "error", the message is withheld
    [errored] = [r for r in full.samples if r["status"] == "error"]
    assert errored["error"] is None

    with_content = sample_listing(view, content=True)
    [errored] = [r for r in with_content.samples if r["status"] == "error"]
    assert "sample 2 failed" in errored["error"]

    errors = sample_listing(view, sample_filter="errors")
    assert [r["sample_id"] for r in errors.samples] == [2]
    assert errors.counts["completed"] == 0

    filtered = sample_listing(view, statuses=frozenset({"completed"}), limit=1)
    assert len(filtered.samples) == 1 and filtered.truncated
    # counts cover the whole task regardless of the filter and cap
    assert filtered.counts["completed"] == 2


# --- per-sample reads ----------------------------------------------------------


@pytest.fixture
def live_terminal_state(finished_log: EvalLog) -> Iterator[str]:
    """The same log registered as a finished eval, so the live path reads it."""
    from inspect_ai._control.eval_state import (
        clear_all_eval_states,
        register_completed_eval,
    )

    register_completed_eval(
        finished_log.eval.eval_id,
        total=3,
        completed=2,
        errored=1,
        task=finished_log.eval.task,
        task_id=finished_log.eval.task_id,
        log_location=finished_log.location,
    )
    try:
        yield finished_log.eval.eval_id
    finally:
        clear_all_eval_states()


@pytest.mark.parametrize("sample_id", ["1", "2"])
@pytest.mark.parametrize("content", [False, True])
async def test_per_sample_reads_equal_the_live_terminal_envelopes(
    finished_log: EvalLog,
    live_terminal_state: str,
    sample_id: str,
    content: bool,
) -> None:
    from inspect_ai._control import events, messages, state
    from inspect_ai._control import store as control_store

    eval_id = live_terminal_state
    root = str(Path(finished_log.location).parent)
    index, _ = await _index(root)
    task = index.tasks[0]
    async with AsyncFilesystem() as fs:
        detail = await sample_detail(fs, task, sample_id, 1, content=content)
        page = await sample_events(fs, task, sample_id, 1, types=frozenset({"*"}))
        convo = await sample_messages(fs, task, sample_id, 1, content=content)
        values = await sample_store(fs, task, sample_id, 1, content=content)

    assert detail == await state.sample_error_detail(eval_id, sample_id, 1, content)
    assert page == await events.sample_events(
        eval_id, sample_id, 1, types=frozenset({"*"})
    )
    live_convo = await messages.sample_messages(eval_id, sample_id, 1, content=content)
    live_store = await control_store.sample_store(
        eval_id, sample_id, 1, content=content
    )
    assert live_convo is not None and live_store is not None
    assert {**convo, "as_of": 0} == {**live_convo, "as_of": 0}
    assert {**values, "as_of": 0} == {**live_store, "as_of": 0}
    assert values["store"]["seen"]["type"] == "number"


async def test_per_sample_read_of_a_pending_sample_is_not_found(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    await _write_running_log(tmp_path, finished_log, logged=[1], sample_ids=[1, 2])
    index, _ = await _index(tmp_path)
    async with AsyncFilesystem() as fs:
        with pytest.raises(SampleNotFoundError, match="not in .* yet"):
            await sample_detail(fs, index.tasks[0], "2", 1)
        with pytest.raises(SampleNotFoundError, match="not found"):
            await sample_detail(fs, index.tasks[0], "42", 1)


async def test_events_cursor_pages_through_the_logged_sample(log_dir: Path) -> None:
    index, _ = await _index(log_dir)
    task = index.tasks[0]
    async with AsyncFilesystem() as fs:
        first = await sample_events(fs, task, "1", 1, types=frozenset({"*"}), limit=2)
        rest = await sample_events(
            fs, task, "1", 1, types=frozenset({"*"}), since=first["next"]
        )
    assert len(first["events"]) == 2 and not first["done"]
    assert rest["done"] and rest["events"]


# --- consistency ---------------------------------------------------------------


async def test_a_log_replaced_after_its_plan_was_read_is_re_read(
    log_dir: Path, finished_log: EvalLog
) -> None:
    [path] = list(log_dir.glob("*.eval"))
    async with AsyncFilesystem() as fs:
        index = await index_log_dir(fs, str(log_dir))
        # the worker rewrites the log (sample 2 now succeeded) after the plan
        # read, so the plan's central directory describes the old object
        replaced = await read_eval_log_async(str(path))
        assert replaced.samples is not None
        replaced.samples[1] = replaced.samples[1].model_copy(
            update={"error": None, "metadata": {"padding": "x" * 4096}}
        )
        replaced.status = "started"
        await write_eval_log_async(replaced, str(path))
        member = await read_snapshot(fs, index.tasks[0].current)
    # the stale central directory failed the CRC check and was re-read
    assert member.plan.central_directory != index.tasks[0].current.central_directory
    assert member.summaries[SampleKey("2", 1)].error is None


async def test_exhausted_re_reads_fail_the_read_and_mark_list_reads_incomplete(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, _ = await _index(log_dir)
    reads = Counter[str]()

    def always_torn(filename: str, entry: Any, crc: int) -> None:
        reads[entry.filename] += 1
        raise ZipCrcError(f"torn {entry.filename}")

    monkeypatch.setattr("inspect_ai._util.async_zip._check_crc", always_torn)
    async with AsyncFilesystem() as fs:
        with pytest.raises(LogChangedError, match="changed during the read"):
            await read_snapshot(fs, index.tasks[0].current)
        [view] = await read_task_views(fs, index.tasks)
    # per read: the first attempt reuses the plan's central directory and
    # reads summaries.json; each re-read starts again from header.json
    assert reads == Counter(
        {"summaries.json": 2, "header.json": 2 * consistency.MAX_REREADS}
    )
    row = task_row(view)
    assert row["incomplete"] is True
    assert row["unreadable"][0]["log_location"] == view.task.current.file.location
    assert row["samples"]["total"] == 0
    assert sample_listing(view).samples == []


async def test_read_consistently_retries_torn_reads_then_succeeds(
    log_dir: Path,
) -> None:
    [path] = list(log_dir.glob("*.eval"))
    attempts: list[bool] = []

    async def read(reader: AsyncZipReader, fresh: bool) -> str:
        attempts.append(fresh)
        if len(attempts) < 3:
            raise ZipCrcError("torn")
        return "ok"

    async with AsyncFilesystem() as fs:
        cd = await AsyncZipReader(fs, str(path)).entries()
        assert (
            await read_consistently(fs, str(path), read, central_directory=cd) == "ok"
        )
    # the first attempt reused the given central directory; re-reads did not
    assert attempts == [False, True, True]


async def test_an_unparseable_log_is_reported_not_raised(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    shutil.copy(finished_log.location, tmp_path / Path(finished_log.location).name)
    (tmp_path / "2026-01-01T00-00-00+00-00_junk_JUNK.eval").write_bytes(b"not a zip")
    with zipfile.ZipFile(tmp_path / "other.eval", "w") as zf:
        zf.writestr("unrelated.txt", "hello")
    (tmp_path / "2026-01-01T00-00-00+00-00_old_OLD.json").write_text("{}")
    index, rows = await _index(tmp_path)
    assert len(rows) == 1
    reasons = {Path(u.location).name: u.reason for u in index.unattributed}
    assert set(reasons) == {
        "2026-01-01T00-00-00+00-00_junk_JUNK.eval",
        "other.eval",
        "2026-01-01T00-00-00+00-00_old_OLD.json",
    }
    assert "neither header.json" in reasons["other.eval"]
    assert (
        "not read in --log-dir mode"
        in reasons["2026-01-01T00-00-00+00-00_old_OLD.json"]
    )
    async with AsyncFilesystem() as fs:
        with pytest.raises(LogUnparseableError):
            await read_plan(
                fs,
                next(
                    f
                    for f in (await walk_log_dir(fs, str(tmp_path))).eval_files
                    if f.name == "other.eval"
                ),
            )


async def test_an_unreadable_newer_attempt_blocks_per_sample_reads(
    log_dir: Path, finished_log: EvalLog
) -> None:
    # a newer attempt of the same task (by file name) that cannot be read:
    # the row is flagged, and a sample read refuses to answer from the older
    # attempt
    newer = (
        log_dir / f"2099-01-01T00-00-00+00-00_alpha_{finished_log.eval.task_id}.eval"
    )
    newer.write_bytes(b"truncated upload")
    index, rows = await _index(log_dir)
    [row] = rows
    assert row["incomplete"] is True
    assert row["attempts"] == 2
    assert [u["log_location"] for u in row["unreadable"]] == [str(newer)]
    assert index.tasks[0].newest_unreadable is not None
    async with AsyncFilesystem() as fs:
        with pytest.raises(LogUnparseableError):
            await sample_detail(fs, index.tasks[0], "1", 1)


# --- walk ----------------------------------------------------------------------


async def test_walk_skips_buffers_and_checkpoints_and_descends_other_dirs(
    tmp_path: Path, finished_log: EvalLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = Path(finished_log.location).name
    shutil.copy(finished_log.location, tmp_path / name)
    (tmp_path / "nested" / "deeper").mkdir(parents=True)
    shutil.copy(finished_log.location, tmp_path / "nested" / "deeper" / name)
    for skipped in (".buffer/x", "run.checkpoints/1"):
        (tmp_path / skipped).mkdir(parents=True)
        shutil.copy(finished_log.location, tmp_path / skipped / name)
    listed: list[str] = []
    original = AsyncFilesystem.list_dir

    async def spy(self: AsyncFilesystem, base: str) -> Any:
        listed.append(base)
        return await original(self, base)

    monkeypatch.setattr(AsyncFilesystem, "list_dir", spy)
    async with AsyncFilesystem() as fs:
        listing = await walk_log_dir(fs, str(tmp_path))
    assert [Path(f.location).relative_to(tmp_path) for f in listing.eval_files] == [
        Path(name),
        Path("nested/deeper") / name,
    ]
    assert sorted(Path(p).relative_to(tmp_path) for p in listed) == [
        Path("."),
        Path("nested"),
        Path("nested/deeper"),
    ]


async def test_walk_does_not_follow_directory_symlinks(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    shutil.copy(finished_log.location, tmp_path / Path(finished_log.location).name)
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    async with AsyncFilesystem() as fs:
        listing = await walk_log_dir(fs, str(tmp_path))
    assert len(listing.eval_files) == 1


async def test_walk_of_a_missing_root_raises_file_not_found(tmp_path: Path) -> None:
    async with AsyncFilesystem() as fs:
        with pytest.raises(FileNotFoundError):
            await walk_log_dir(fs, str(tmp_path / "absent"))


async def test_cancelling_a_walk_propagates_and_reports_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = anyio.Event()

    async def blocked(self: AsyncFilesystem, base: str) -> Any:
        started.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(AsyncFilesystem, "list_dir", blocked)
    result: list[LogDirIndex] = []
    async with AsyncFilesystem() as fs:
        async with anyio.create_task_group() as tg:

            async def run() -> None:
                result.append(await index_log_dir(fs, str(tmp_path)))

            tg.start_soon(run)
            await started.wait()
            tg.cancel_scope.cancel()
    assert result == []


async def test_identity_rows_come_from_plans_alone(log_dir: Path) -> None:
    index, _ = await _index(log_dir)
    row = identity_row(index.tasks[0])
    assert "samples" not in row
    assert row["log_target"].startswith("log:")
    assert isinstance(index.tasks[0], LogicalTask)


def test_read_only_commands_leave_the_directory_unchanged(
    log_dir: Path, finished_log: EvalLog
) -> None:
    from _control.conftest import cli_runner
    from inspect_ai._cli.ctl import ctl_command

    def snapshot() -> dict[str, tuple[int, int]]:
        return {
            str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in log_dir.rglob("*")
        }

    before = snapshot()
    runner = cli_runner()
    task_id = finished_log.eval.task_id
    for args in (
        ["task", "list"],
        ["sample", "list"],
        ["sample", "errors"],
        ["sample", "show", task_id, "1"],
        ["sample", "events", task_id, "1"],
        ["sample", "messages", task_id, "1"],
        ["sample", "store", task_id, "1"],
    ):
        result = runner.invoke(
            ctl_command, [*args, "--json", "--log-dir", str(log_dir)]
        )
        assert result.exit_code == 0, (args, result.output)
    assert snapshot() == before


# --- S3 request counts ---------------------------------------------------------


@pytest.fixture
def s3_requests(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    """Count S3 operations issued through AsyncFilesystem's async client."""
    counts = Counter[str]()
    original = AsyncFilesystem._create_s3_client_async

    async def counting(**kwargs: Any) -> Any:
        client = await original(**kwargs)

        def record(model: Any, **_: Any) -> None:
            counts[model.name] += 1

        client.meta.events.register("before-call.s3", record)
        return client

    monkeypatch.setattr(
        AsyncFilesystem, "_create_s3_client_async", staticmethod(counting)
    )
    return counts


def _upload(path: Path | str, key: str) -> None:
    boto3.client("s3").upload_file(str(path), "test-bucket", key)


@skip_if_trio
async def test_s3_walk_lists_each_directory_once_and_never_a_buffer(
    mock_s3: None, finished_log: EvalLog, s3_requests: Counter[str]
) -> None:
    prefix = "log-dir-walk"
    name = Path(finished_log.location).name
    _upload(finished_log.location, f"{prefix}/{name}")
    _upload(finished_log.location, f"{prefix}/sub/{name}")
    for i in range(300):
        boto3.client("s3").put_object(
            Bucket="test-bucket", Key=f"{prefix}/.buffer/x/segment.{i}.zip", Body=b""
        )
        boto3.client("s3").put_object(
            Bucket="test-bucket", Key=f"{prefix}/run.checkpoints/{i}", Body=b""
        )
    async with AsyncFilesystem() as fs:
        listing = await walk_log_dir(fs, f"s3://test-bucket/{prefix}")
    assert len(listing.eval_files) == 2
    # root and sub: one delimited LIST each, whatever the buffers hold
    assert s3_requests == Counter({"ListObjectsV2": 2})


@skip_if_trio
async def test_s3_request_counts_for_list_and_sample_reads(
    mock_s3: None, finished_log: EvalLog, s3_requests: Counter[str]
) -> None:
    root = "s3://test-bucket/log-dir-costs"
    _upload(finished_log.location, f"log-dir-costs/{Path(finished_log.location).name}")
    async with AsyncFilesystem() as fs:
        index = await index_log_dir(fs, root)
        # the plan: the central directory (one suffix GET for a small log)
        # and header.json
        assert s3_requests == Counter({"ListObjectsV2": 1, "GetObject": 2})
        s3_requests.clear()

        [view] = await read_task_views(fs, index.tasks)
        # the snapshot reuses the plan's central directory: summaries.json only
        assert s3_requests == Counter({"GetObject": 1})
        assert task_row(view)["samples"]["completed"] == 2
        s3_requests.clear()

        await sample_detail(fs, index.tasks[0], "1", 1)
        # the key refresh (summaries.json), then the field-excluding sample
        # read: the member's local header and its body
        assert s3_requests == Counter({"GetObject": 3})
        s3_requests.clear()

        await sample_events(fs, index.tasks[0], "1", 1)
        # the key refresh, then one full member read
        assert s3_requests == Counter({"GetObject": 2})


@skip_if_trio
async def test_s3_running_log_reads_each_journal_summary(
    mock_s3: None, tmp_path: Path, finished_log: EvalLog, s3_requests: Counter[str]
) -> None:
    location = await _write_running_log(
        tmp_path, finished_log, logged=[1, 2], sample_ids=[1, 2, 3]
    )
    _upload(location, f"log-dir-running/{location.name}")
    async with AsyncFilesystem() as fs:
        index = await index_log_dir(fs, "s3://test-bucket/log-dir-running")
        s3_requests.clear()
        [view] = await read_task_views(fs, index.tasks)
    journal = [
        n
        for n in zipfile.ZipFile(location).namelist()
        if n.startswith("_journal/summaries/")
    ]
    assert s3_requests == Counter({"GetObject": len(journal)})
    assert task_row(view)["samples"]["total"] == 3


@skip_if_trio
async def test_s3_missing_bucket_raises_client_error(mock_s3: None) -> None:
    from botocore.exceptions import ClientError

    async with AsyncFilesystem() as fs:
        with pytest.raises(ClientError, match="NoSuchBucket"):
            await walk_log_dir(fs, "s3://no-such-bucket-for-log-dir/x")


# --- through the CLI -----------------------------------------------------------


def _ctl(log_dir: Path | str, *args: str) -> Any:
    """Invoke ``inspect ctl <args> --log-dir <log_dir>``."""
    from _control.conftest import cli_runner
    from inspect_ai._cli.ctl import ctl_command

    return cli_runner().invoke(ctl_command, [*args, "--log-dir", str(log_dir)])


@pytest.fixture
def no_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> Any:
        raise AssertionError("log-dir reads must not reach discovery")

    monkeypatch.setattr("inspect_ai._cli.ctl._http.list_discovered_servers", forbidden)


def test_cli_sample_list_envelope_and_rows(
    log_dir: Path, finished_log: EvalLog, no_discovery: None
) -> None:
    import json

    result = _ctl(str(log_dir), "sample", "list", "alpha", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "as_of",
        "counts",
        "samples",
        "truncated",
        "conflicted",
        "incomplete",
        "unreadable",
    }
    assert payload["counts"]["completed"] == 2 and payload["counts"]["error"] == 1
    assert payload["conflicted"] == 0 and payload["incomplete"] is False
    row = payload["samples"][0]
    assert row["task_id"] == finished_log.eval.task_id and row["task"] == "alpha"
    assert row["log_location"] == str(log_dir / Path(finished_log.location).name)


def test_cli_unscoped_sample_list_routes_each_task_by_its_target(
    tmp_path: Path, finished_log: EvalLog, no_discovery: None
) -> None:
    import json

    anyio.run(_attempt, finished_log, tmp_path, "2026-01-01T00-00-00+00-00")
    other = finished_log.model_copy(deep=True)
    other.eval.task_id = "OTHERTASK00000000000000"
    assert other.samples is not None
    other.samples = [s for s in other.samples if s.id == 1]
    anyio.run(_attempt, other, tmp_path, "2026-01-02T00-00-00+00-00")

    result = _ctl(str(tmp_path), "sample", "list", "--json")
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)["samples"]
    by_task = Counter(r["task_id"] for r in rows)
    assert by_task == {finished_log.eval.task_id: 3, "OTHERTASK00000000000000": 3}

    # the name matches both tasks; a task id selects exactly one
    ambiguous = _ctl(str(tmp_path), "sample", "show", "alpha", "1", "--json")
    assert ambiguous.exit_code == 1
    assert json.loads(ambiguous.stdout)["error"]["kind"] == "ambiguous"
    shown = _ctl(str(tmp_path), "sample", "show", "OTHERTASK", "2", "--json")
    # sample 2 is pending in the second task's log (not logged there)
    assert json.loads(shown.stdout)["error"]["kind"] == "not_found"


def test_cli_per_sample_failures_map_to_error_kinds(
    log_dir: Path, finished_log: EvalLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    task_id = finished_log.eval.task_id
    missing = _ctl(str(log_dir), "sample", "show", task_id, "42", "--json")
    assert json.loads(missing.stdout)["error"]["kind"] == "not_found"

    from inspect_ai._util import async_zip

    check_crc = async_zip._check_crc

    def torn_samples(filename: str, entry: Any, crc: int) -> None:
        if entry.filename.startswith("samples/"):
            raise ZipCrcError("torn")
        check_crc(filename, entry, crc)

    monkeypatch.setattr("inspect_ai._util.async_zip._check_crc", torn_samples)
    torn = _ctl(str(log_dir), "sample", "store", task_id, "1", "--json")
    assert torn.exit_code == 1
    error = json.loads(torn.stdout)["error"]
    assert error["kind"] == "storage_error"
    assert error["exception"] == "inspect_ai.LogChangedError"
    assert "changed during the read" in error["message"]


def test_cli_list_reads_report_a_torn_member_and_sample_reads_fail(
    log_dir: Path, finished_log: EvalLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    task_id = finished_log.eval.task_id

    def always_torn(filename: str, entry: Any, crc: int) -> None:
        raise ZipCrcError("torn")

    monkeypatch.setattr("inspect_ai._util.async_zip._check_crc", always_torn)
    # a list read keeps going: the log is reported, not fatal
    listed = _ctl(str(log_dir), "task", "list", "--json")
    assert listed.exit_code == 0
    payload = json.loads(listed.stdout)
    assert payload["tasks"] == [] and payload["incomplete"] is True
    assert payload["unreadable"][0]["log_location"].endswith(".eval")
    # a single-target read does not answer "nothing here" over it
    shown = _ctl(str(log_dir), "sample", "show", task_id, "1", "--json")
    assert shown.exit_code == 1
    assert json.loads(shown.stdout)["error"]["kind"] == "storage_error"


def test_cli_newer_unreadable_attempt_is_invalid_response(
    log_dir: Path, finished_log: EvalLog
) -> None:
    import json

    task_id = finished_log.eval.task_id
    (log_dir / f"2099-01-01T00-00-00+00-00_alpha_{task_id}.eval").write_bytes(b"x")
    result = _ctl(str(log_dir), "sample", "show", task_id, "1", "--json")
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["kind"] == "invalid_response"


def test_cli_human_output_sanitizes_hostile_file_names(
    log_dir: Path, finished_log: EvalLog
) -> None:
    (log_dir / "evil\x1b]0;owned\x07name.eval").write_bytes(b"not a zip")
    result = _ctl(str(log_dir), "task", "list")
    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.stderr and "\x07" not in result.stderr
    assert "warning: skipped" in result.stderr


def test_cli_never_resolves_scorers_or_imports_task_code(
    log_dir: Path, finished_log: EvalLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("log-dir reads must not run task code")

    monkeypatch.setattr("inspect_ai._eval.score.resolve_scorers_info", forbidden)
    monkeypatch.setattr("inspect_ai._eval.loader.load_tasks", forbidden)
    task_id = finished_log.eval.task_id
    for args in (["task", "list"], ["sample", "show", task_id, "2", "--content"]):
        result = _ctl(str(log_dir), *args, "--json")
        assert result.exit_code == 0, result.output


# --- review round 1 regressions ------------------------------------------------


def _json(result: Any) -> Any:
    import json

    return json.loads(result.stdout)


@pytest.mark.parametrize("verb", ["list", "errors"])
@pytest.mark.parametrize("scoped", [False, True])
def test_cli_sample_listings_keep_the_envelope_when_no_log_is_readable(
    tmp_path: Path, verb: str, scoped: bool
) -> None:
    selector = ["alpha"] if scoped else []
    empty = _ctl(str(tmp_path), "sample", verb, *selector, "--json")
    assert empty.exit_code == 0, empty.output
    assert _json(empty)["incomplete"] is False and _json(empty)["unreadable"] == []
    assert _json(empty)["conflicted"] == 0

    (tmp_path / "bad.eval").write_bytes(b"not a zip")
    broken = _ctl(str(tmp_path), "sample", verb, *selector, "--json")
    assert broken.exit_code == 0, broken.output
    payload = _json(broken)
    assert payload["samples"] == [] and payload["incomplete"] is True
    assert [u["log_location"] for u in payload["unreadable"]] == [
        str(tmp_path / "bad.eval")
    ]


def test_cli_scoped_listing_reports_unidentified_but_not_other_tasks_failures(
    log_dir: Path, finished_log: EvalLog
) -> None:
    (log_dir / "bad.eval").write_bytes(b"not a zip")
    other = log_dir / "2099-01-01T00-00-00+00-00_broken_BROKENTASK000000000000.eval"
    other.write_bytes(b"not a zip")
    scoped = _ctl(str(log_dir), "sample", "list", finished_log.eval.task_id, "--json")
    assert scoped.exit_code == 0, scoped.output
    payload = _json(scoped)
    assert payload["counts"]["completed"] == 2 and payload["incomplete"] is True
    assert [u["log_location"] for u in payload["unreadable"]] == [
        str(log_dir / "bad.eval")
    ]
    unscoped = _json(_ctl(str(log_dir), "sample", "list", "--json"))
    assert {u["log_location"] for u in unscoped["unreadable"]} == {
        str(log_dir / "bad.eval"),
        str(other),
    }
    assert Counter(r["task_id"] for r in unscoped["samples"]) == {
        finished_log.eval.task_id: 3
    }


@pytest.mark.parametrize("verb", ["show", "events", "messages", "store"])
def test_cli_a_task_whose_only_log_is_unreadable_reports_its_failure(
    log_dir: Path, finished_log: EvalLog, verb: str
) -> None:
    (
        log_dir / "2099-01-01T00-00-00+00-00_broken_BROKENTASK000000000000.eval"
    ).write_bytes(b"not a zip")
    broken = _ctl(
        str(log_dir),
        "sample",
        verb,
        "BROKENTASK000000000000",
        "1",
        "--json",
    )
    assert broken.exit_code == 1
    assert _json(broken)["error"]["kind"] == "invalid_response"
    # the healthy neighbour still reads
    healthy = _ctl(
        str(log_dir),
        "sample",
        verb,
        finished_log.eval.task_id,
        "1",
        "--json",
    )
    assert healthy.exit_code == 0, healthy.output


async def test_file_uri_roots_with_reserved_characters_in_names(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    nested = tmp_path / "dir #1?x"
    nested.mkdir()
    shutil.copy(finished_log.location, nested / "percent%20literal.eval")
    plain_index, plain_rows = await _index(tmp_path)
    uri_index, uri_rows = await _index(tmp_path.as_uri())
    assert len(plain_rows) == len(uri_rows) == 1
    assert uri_index.unattributed == [] and uri_rows[0]["incomplete"] is False
    assert uri_rows[0]["log_location"] == str(nested / "percent%20literal.eval")
    assert uri_rows[0]["samples"] == plain_rows[0]["samples"]
    async with AsyncFilesystem() as fs:
        detail = await sample_detail(fs, uri_index.tasks[0], "1", 1)
    assert detail["sample_id"] == 1


async def test_a_sample_read_that_switches_versions_uses_that_versions_summary(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._control.log_dir import samples as samples_module

    [path] = list(log_dir.glob("*.eval"))
    index, _ = await _index(log_dir)
    replacement = await read_eval_log_async(str(path))
    assert replacement.samples is not None
    replacement.samples[0] = replacement.samples[0].model_copy(
        update={"total_time": 777.0, "metadata": {"padding": "y" * 4096}}
    )
    from inspect_ai.log._file import read_eval_log_sample_async as original

    calls: list[int] = []

    async def replace_first(*args: Any, **kwargs: Any) -> Any:
        if not calls:
            # the worker rewrites the log between the key refresh and the
            # sample-member read
            await write_eval_log_async(replacement, str(path))
        calls.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(samples_module, "read_eval_log_sample_async", replace_first)
    async with AsyncFilesystem() as fs:
        detail = await sample_detail(fs, index.tasks[0], "1", 1)
    assert len(calls) >= 2
    assert detail["total_time"] == 777.0


def _drop_journal_member(source: Path, dest: Path) -> None:
    """Copy a running log with its first journal summary renamed to ``2.json``."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(dest, "w") as out:
        for info in src.infolist():
            name = info.filename
            if name == "_journal/summaries/1.json":
                name = "_journal/summaries/2.json"
            out.writestr(name, src.read(info.filename))


def test_cli_a_journal_missing_a_summary_member_is_an_unreadable_log(
    log_dir: Path, finished_log: EvalLog, tmp_path_factory: pytest.TempPathFactory
) -> None:
    source_dir = tmp_path_factory.mktemp("running-source")
    running = anyio.run(
        functools.partial(
            _write_running_log,
            source_dir,
            finished_log,
            logged=[1],
            sample_ids=[1, 2],
        )
    )
    _drop_journal_member(running, log_dir / running.name)
    listed = _ctl(str(log_dir), "task", "list", "--json")
    assert listed.exit_code == 0, listed.output
    rows = {r["task_id"]: r for r in _json(listed)["tasks"]}
    assert rows[finished_log.eval.task_id]["incomplete"] is False
    broken = rows["RUNNINGTASK000000000000"]
    assert broken["incomplete"] is True
    assert "missing member" in broken["unreadable"][0]["reason"]
    samples = _ctl(str(log_dir), "sample", "list", "--json")
    assert samples.exit_code == 0 and _json(samples)["incomplete"] is True
    shown = _ctl(
        str(log_dir),
        "sample",
        "show",
        "RUNNINGTASK000000000000",
        "1",
        "--json",
    )
    assert shown.exit_code == 1
    assert _json(shown)["error"]["kind"] == "invalid_response"


async def test_names_without_a_timestamp_order_by_mtime_alone(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    import os

    old = tmp_path / "old-recovered.eval"
    new = tmp_path / "new.eval"
    shutil.copy(finished_log.location, old)
    shutil.copy(finished_log.location, new)
    os.utime(old, (100, 100))
    os.utime(new, (200, 200))
    _, rows = await _index(tmp_path)
    [row] = rows
    assert row["attempts"] == 2
    assert row["log_location"] == str(new)


def test_cli_errored_footer_points_at_the_log_dir(log_dir: Path) -> None:
    import shlex

    result = _ctl(str(log_dir), "task", "list")
    assert result.exit_code == 0, result.output
    assert (
        f"see `inspect ctl sample errors --log-dir {shlex.quote(str(log_dir))}`"
        in result.stdout
    )


_BROKEN = "2099-01-01T00-00-00+00-00_broken_BROKENTASK000000000000.eval"


@pytest.mark.parametrize("verb", ["show", "events", "messages", "list", "errors"])
@pytest.mark.parametrize("selector", ["BROKENTASK000000000000", "BROKENT", "broken"])
def test_cli_model_filter_keeps_an_unreadable_task_of_unknown_model(
    log_dir: Path, verb: str, selector: str
) -> None:
    broken = log_dir / _BROKEN
    broken.write_bytes(b"not a zip")
    args = ["1"] if verb in ("show", "events", "messages") else []
    result = _ctl(
        str(log_dir),
        "sample",
        verb,
        selector,
        *args,
        "--model",
        "openai/gpt-4o",
        "--json",
    )
    if args:
        assert result.exit_code == 1
        assert _json(result)["error"]["kind"] == "invalid_response"
    else:
        assert result.exit_code == 0, result.output
        payload = _json(result)
        assert payload["samples"] == [] and payload["incomplete"] is True
        assert [u["log_location"] for u in payload["unreadable"]] == [str(broken)]


def test_cli_an_unknown_model_candidate_does_not_settle_a_name_ambiguity(
    log_dir: Path,
) -> None:
    # an unreadable log of another task with the same name: its model is
    # unknown, so --model cannot rule it out
    (
        log_dir / "2099-01-01T00-00-00+00-00_alpha_BROKENTASK000000000000.eval"
    ).write_bytes(b"not a zip")
    result = _ctl(
        str(log_dir),
        "sample",
        "show",
        "alpha",
        "1",
        "--model",
        "mockllm/model",
        "--json",
    )
    assert result.exit_code == 1
    assert _json(result)["error"]["kind"] == "ambiguous"


def test_cli_model_filter_still_disambiguates_healthy_tasks(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    anyio.run(_attempt, finished_log, tmp_path, "2026-01-01T00-00-00+00-00")
    other = finished_log.model_copy(deep=True)
    other.eval.task_id = "OTHERTASK00000000000000"
    other.eval.model = "openai/gpt-4o"
    anyio.run(_attempt, other, tmp_path, "2026-01-02T00-00-00+00-00")
    result = _ctl(
        str(tmp_path),
        "sample",
        "show",
        "alpha",
        "1",
        "--model",
        "openai/gpt-4o",
        "--json",
    )
    assert result.exit_code == 0, result.output
    assert _json(result)["task_id"] == "OTHERTASK00000000000000"
    mismatch = _ctl(
        str(tmp_path),
        "sample",
        "show",
        "OTHERTASK00000000000000",
        "1",
        "--model",
        "mockllm/model",
        "--json",
    )
    assert _json(mismatch)["error"]["kind"] == "not_found"


# --- shared sample buffers -----------------------------------------------------

# A start time after every record the fixture logs, as for a key re-run
# after its record was flushed (a requeue, or a seeded retry's re-run).
_LATER = "2099-01-01T00:00:00+00:00"


def _buffer_summary(
    sample_id: int,
    *,
    started_at: str = _LATER,
    completed: bool = False,
    error: str | None = None,
) -> EvalSampleSummary:
    """A manifest row: a running start snapshot, or a completed sample's summary."""
    return EvalSampleSummary(
        id=sample_id,
        epoch=1,
        input=f"q{sample_id}",
        target="x",
        started_at=started_at,
        completed_at=started_at if completed else None,
        completed=completed,
        error=error,
        uuid=f"uuid-{sample_id}",
    )


def _info(data: str, uuid: str) -> dict[str, Any]:
    return InfoEvent(data=data, uuid=uuid).model_dump(mode="json")


def _write_buffer(
    log: Path,
    rows: list[tuple[EvalSampleSummary, list[list[dict[str, Any]] | SampleData]]],
) -> Path:
    """Write the shared buffer a ``--log-shared`` worker syncs beside ``log``.

    Each row is a manifest entry and its segments: a batch of events, or a
    segment's ``SampleData`` as given. Returns the ``.buffer/<stem>/``
    directory.
    """
    store = SampleBufferFilestore(str(log))
    segments: list[Segment] = []
    samples: list[SampleManifest] = []
    event_id = 0
    for summary, batches in rows:
        sample_segments: list[SampleSegmentEntry] = []
        for batch in batches:
            events = []
            for event in batch if isinstance(batch, list) else []:
                event_id += 1
                events.append(
                    EventData(
                        id=event_id,
                        event_id=event["uuid"],
                        sample_id=str(summary.id),
                        epoch=summary.epoch,
                        event=event,
                    )
                )
            data = (
                batch
                if isinstance(batch, SampleData)
                else SampleData(events=events, attachments=[])
            )
            segment = Segment(
                id=len(segments) + 1, last_event_id=event_id, last_attachment_id=0
            )
            store.write_segment(
                segment["id"],
                [SegmentFile(id=summary.id, epoch=summary.epoch, data=data)],
            )
            segments.append(segment)
            sample_segments.append(segment)
        samples.append(SampleManifest(summary=summary, segments=sample_segments))
    store.write_manifest(Manifest(samples=samples, segments=segments))
    return log.parent / ".buffer" / log.stem


# the segment reader, as the per-sample reads call it
_READ_SAMPLE_DATA = "inspect_ai._control.log_dir.samples.read_sample_data"


def _statuses(listing: Any) -> dict[Any, str]:
    return {r["sample_id"]: r["status"] for r in listing.samples}


async def test_buffer_rows_show_running_and_unflushed_samples(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    running = await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2, 3, 4], log_shared=10
    )
    logged_start = running.sample(1).started_at
    assert logged_start is not None
    buffer = _write_buffer(
        running.location,
        [
            # already flushed, not yet dropped from the manifest: the log wins
            (_buffer_summary(1, started_at=logged_start, completed=True), []),
            (_buffer_summary(2), [[_info("a", "e1")]]),
            (_buffer_summary(3, completed=True), [[_info("b", "e2")]]),
            # admitted by a SampleSource: named by the manifest alone
            (_buffer_summary(99), []),
        ],
    )
    synced = running.location.stat().st_mtime + 100
    os.utime(buffer / "manifest.json", (synced, synced))

    index, rows = await _index(tmp_path)
    [row] = rows
    assert row["live_samples"] == "buffer"
    assert row["updated_at"] == pytest.approx(synced)
    assert row["samples"] == {
        "total": 5,
        "completed": 2,
        "errored": 0,
        "cancelled": 0,
        "in_flight": 2,
        "queued": None,
        "conflicted": 0,
        "unfinished": 3,
        "total_final": False,
        "pending_unlisted": None,
    }

    [view] = await _views(index)
    listing = sample_listing(view)
    assert _statuses(listing) == {
        1: "completed",
        2: "running",
        3: "completed",
        4: "pending",
        99: "running",
    }
    assert listing.counts["running"] == 2 and listing.counts["pending"] == 1
    [two] = [r for r in listing.samples if r["sample_id"] == 2]
    # a running row is the start snapshot: no live progress fields
    assert two["activity"] is None and two["events"] is None
    assert two["last_activity_at"] is None and two["total_tokens"] == 0
    assert two["log_location"] == str(running.location)
    [one] = [r for r in listing.samples if r["sample_id"] == 1]
    assert one["completed_at"] != _iso_to_timestamp(logged_start)

    async with AsyncFilesystem() as fs:
        added = await sample_detail(fs, index.tasks[0], "99", 1)
    assert added["status"] == "running" and added["error_retries"] == []


async def test_a_running_log_with_no_manifest_yet_reports_unknown_in_flight(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2], log_shared=10
    )
    # another log's buffer: this log has not synced one yet
    (tmp_path / ".buffer" / "other").mkdir(parents=True)
    index, rows = await _index(tmp_path)
    [row] = rows
    assert row["samples"]["in_flight"] is None and row["live_samples"] == "none"
    async with AsyncFilesystem() as fs:
        with pytest.raises(SampleNotFoundError, match="--log-shared"):
            await sample_detail(fs, index.tasks[0], "2", 1)


async def test_a_manifest_is_not_read_without_log_shared(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    running = await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2]
    )
    _write_buffer(running.location, [(_buffer_summary(2), [])])
    _, rows = await _index(tmp_path)
    [row] = rows
    assert row["samples"]["in_flight"] is None and row["live_samples"] == "none"


async def test_every_read_follows_a_re_run_key_through_its_attempt(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    running = await _start_running_log(
        tmp_path, finished_log, logged=[1, 2], sample_ids=[1, 2], log_shared=10
    )
    events = [_info("a", "e1"), _info("b", "e2")]
    everything = frozenset({"*"})

    async def reads() -> tuple[Any, dict[str, Any], dict[str, Any]]:
        index, _ = await _index(tmp_path)
        task = index.tasks[0]
        [view] = await _views(index)
        async with AsyncFilesystem() as fs:
            detail = await sample_detail(fs, task, "1", 1, content=True)
            page = await sample_events(fs, task, "1", 1, types=everything, full=True)
        return sample_listing(view), detail, page

    # the flushed key re-runs: its new attempt is running
    _write_buffer(running.location, [(_buffer_summary(1), [events])])
    listing, detail, page = await reads()
    assert _statuses(listing)[1] == "running"
    assert detail["status"] == "running" and detail["error_retries"] == []
    assert [e["data"] for e in page["events"]] == ["a", "b"]
    assert page["done"] is False
    buffer_cursor = page["next"]
    index, _ = await _index(tmp_path)
    async with AsyncFilesystem() as fs:
        with pytest.raises(SampleUnsupportedError, match="still running; its message"):
            await sample_messages(fs, index.tasks[0], "1", 1)
        with pytest.raises(SampleUnsupportedError, match="its store"):
            await sample_store(fs, index.tasks[0], "1", 1)

    # completed, not yet flushed
    _write_buffer(
        running.location,
        [(_buffer_summary(1, completed=True, error="boom"), [events])],
    )
    listing, detail, page = await reads()
    assert _statuses(listing)[1] == "error"
    [view] = await _views((await _index(tmp_path))[0])
    errors = sample_listing(view, sample_filter="errors", content=True)
    # the unflushed error is listed with the flushed one (sample 2)
    assert {r["sample_id"]: r["error"] for r in errors.samples}[1] == "boom"
    assert {r["sample_id"] for r in errors.samples} == {1, 2}
    assert detail["status"] == "error"
    assert detail["error"] == {
        "message": "boom",
        "traceback": None,
        "traceback_ansi": None,
    }
    assert page["done"] is True
    async with AsyncFilesystem() as fs:
        withheld = await sample_detail(fs, index.tasks[0], "1", 1)
        assert withheld["error"] == {}
        with pytest.raises(SampleUnsupportedError, match="not yet in the log"):
            await sample_messages(fs, index.tasks[0], "1", 1)

    # flushed: the log holds the new attempt and the manifest drops it
    await _flush(running, [running.sample(1, started_at=_LATER, completed_at=_LATER)])
    _write_buffer(running.location, [])
    listing, detail, page = await reads()
    assert _statuses(listing)[1] == "completed"
    assert detail["status"] == "completed" and detail["started_at"] == (
        _iso_to_timestamp(_LATER)
    )
    index, _ = await _index(tmp_path)
    async with AsyncFilesystem() as fs:
        # the buffer cursor is foreign to the logged source: the read restarts
        resumed = await sample_events(
            fs,
            index.tasks[0],
            "1",
            1,
            types=everything,
            full=True,
            since=buffer_cursor,
        )
        assert resumed == page and resumed["done"] is True
        convo = await sample_messages(fs, index.tasks[0], "1", 1)
    assert convo["messages"]


async def test_a_key_flushed_after_the_plan_read_is_read_from_the_log(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    running = await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2], log_shared=10
    )
    _write_buffer(running.location, [(_buffer_summary(2, completed=True), [])])
    async with AsyncFilesystem() as fs:
        index = await index_log_dir(fs, str(tmp_path))
        plan = index.tasks[0].current
        # unchanged since the plan: its central directory is reused
        [view] = await read_task_views(fs, index.tasks)
        assert view.member is not None
        assert view.member.plan.central_directory is plan.central_directory

        # the worker flushes sample 2 and drops it from the manifest, both
        # after this poll's listing and plan read
        await _flush(running, [running.sample(2)])
        _write_buffer(running.location, [])
        # the flush appended to the log, so the plan's central directory
        # still reads cleanly, without sample 2: the stale view
        stale = await read_snapshot(fs, plan)
        assert SampleKey("2", 1) not in stale.summaries

        [view] = await read_task_views(fs, index.tasks)
    # the freshness check after the manifest saw the new log
    assert view.member is not None
    assert view.member.plan.central_directory is not plan.central_directory
    assert _statuses(sample_listing(view))[2] == "error"
    assert task_row(view)["samples"]["unfinished"] == 0


async def test_a_segment_removed_mid_read_re_selects_the_flushed_record(
    tmp_path: Path, finished_log: EvalLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._control.log_dir.buffer import read_sample_data

    running = await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2], log_shared=10
    )
    buffer = _write_buffer(
        running.location, [(_buffer_summary(2, completed=True), [[_info("a", "e1")]])]
    )
    index, _ = await _index(tmp_path)
    calls = 0

    async def worker_finishes_first(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            # the worker's final flush, then its buffer cleanup
            await _flush(running, [running.sample(2)])
            shutil.rmtree(buffer)
        return await read_sample_data(*args)

    monkeypatch.setattr(_READ_SAMPLE_DATA, worker_finishes_first)
    async with AsyncFilesystem() as fs:
        page = await sample_events(fs, index.tasks[0], "2", 1, types=frozenset({"*"}))
    assert calls == 1
    # served from the flushed record: the log's cursor nonce, all its events
    nonce, _ = decode_cursor(page["next"])
    assert nonce is not None and not nonce.startswith("buffer:")
    assert page["done"] is True and page["events"]


async def test_segments_that_keep_disappearing_fail_the_read(
    tmp_path: Path, finished_log: EvalLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2], log_shared=10
    )
    _write_buffer(running.location, [(_buffer_summary(2), [[_info("a", "e1")]])])
    index, _ = await _index(tmp_path)
    calls = 0

    async def gone(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        raise FileNotFoundError(errno.ENOENT, "gone", "segment.1.zip")

    monkeypatch.setattr(_READ_SAMPLE_DATA, gone)
    async with AsyncFilesystem() as fs:
        with pytest.raises(LogChangedError, match="segment.1.zip"):
            await sample_events(fs, index.tasks[0], "2", 1)
    assert calls == consistency.MAX_REREADS + 1


async def test_a_torn_manifest_is_re_read_and_an_unparseable_one_reported(
    tmp_path: Path, finished_log: EvalLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2], log_shared=10
    )
    buffer = _write_buffer(running.location, [(_buffer_summary(2), [])])
    read_file_info = AsyncFilesystem.read_file_info
    reads = 0

    async def torn_once(self: AsyncFilesystem, filename: str) -> FileContent:
        nonlocal reads
        reads += 1
        content = await read_file_info(self, filename)
        # a local manifest is rewritten in place: the first read sees half
        return content._replace(data=content.data[:10]) if reads == 1 else content

    monkeypatch.setattr(AsyncFilesystem, "read_file_info", torn_once)
    _, rows = await _index(tmp_path)
    assert reads == 2 and rows[0]["samples"]["in_flight"] == 1
    monkeypatch.undo()

    (buffer / "manifest.json").write_text("{")
    index, rows = await _index(tmp_path)
    [row] = rows
    assert row["incomplete"] is True
    assert "manifest.json" in row["unreadable"][0]["reason"]
    async with AsyncFilesystem() as fs:
        with pytest.raises(LogUnparseableError, match="manifest.json"):
            await sample_detail(fs, index.tasks[0], "2", 1)


def test_buffered_events_collapse_versions_and_resolve_pools() -> None:
    from inspect_ai._control.log_dir.buffer import BufferSnapshot, buffered_events
    from inspect_ai.event._pool import condense_model_event_inputs
    from inspect_ai.model import ChatMessageUser, ModelOutput

    model = ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="hi")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", "hello"),
    )
    [condensed], _, pool = condense_model_event_inputs([model], 0, {})
    assert isinstance(condensed, ModelEvent) and not condensed.input
    rows = [
        EventData(
            id=i + 1,
            event_id=event["uuid"],
            sample_id="1",
            epoch=1,
            event=event,
        )
        for i, event in enumerate(
            [
                _info("pending", "e1"),
                condensed.model_dump(mode="json"),
                _info("resolved", "e1"),
            ]
        )
    ]
    data = SampleData(
        events=rows,
        attachments=[],
        message_pool=[
            MessagePoolData(
                id=1, sample_id="1", epoch=1, msg_id=msg_id, data=msg.model_dump_json()
            )
            for msg_id, msg in pool
        ],
    )
    events = buffered_events(
        data,
        BufferSnapshot(location="b/", manifest=Manifest(), samples={}, mtime=None),
        SampleManifest(summary=_buffer_summary(1)),
    )
    # the superseded version collapses in place; the pooled input is restored
    assert [e.event for e in events] == ["info", "model"]
    info, model_event = events
    assert isinstance(info, InfoEvent) and info.data == "resolved"
    assert isinstance(model_event, ModelEvent) and model_event.input[0].text == "hi"


@skip_if_trio
async def test_s3_request_counts_for_buffer_reads(
    mock_s3: None, tmp_path: Path, finished_log: EvalLog, s3_requests: Counter[str]
) -> None:
    running = await _start_running_log(
        tmp_path, finished_log, logged=[1], sample_ids=[1, 2, 3], log_shared=10
    )
    buffer = _write_buffer(
        running.location,
        [(_buffer_summary(2), [[_info("a", "e1")], [_info("b", "e2")]])],
    )
    prefix = "log-dir-buffer"
    root = f"s3://test-bucket/{prefix}"

    def upload() -> int:
        _upload(running.location, f"{prefix}/{running.location.name}")
        return len(
            [
                n
                for n in zipfile.ZipFile(running.location).namelist()
                if n.startswith("_journal/summaries/")
            ]
        )

    journal = upload()
    for path in buffer.iterdir():
        _upload(path, f"{prefix}/.buffer/{buffer.name}/{path.name}")
    async with AsyncFilesystem() as fs:
        index = await index_log_dir(fs, root)
        # the walk never lists .buffer/; the plan reads no manifest
        assert s3_requests == Counter({"ListObjectsV2": 1, "GetObject": 2})
        s3_requests.clear()
        task = index.tasks[0]

        [view] = await read_task_views(fs, index.tasks)
        # the manifest, the freshness check, then the journal summaries
        # through the plan's (still current) central directory
        assert s3_requests == Counter({"GetObject": 1 + journal, "HeadObject": 1})
        assert task_row(view)["samples"]["in_flight"] == 1
        s3_requests.clear()

        await sample_detail(fs, task, "2", 1)
        # the key refresh only: a buffer row's detail is its manifest summary
        assert s3_requests == Counter({"GetObject": 1 + journal, "HeadObject": 1})
        s3_requests.clear()

        page = await sample_events(fs, task, "2", 1, types=frozenset({"*"}), full=True)
        # the key refresh, then one GET per segment the manifest lists
        assert s3_requests == Counter({"GetObject": 1 + journal + 2, "HeadObject": 1})
        assert [e["data"] for e in page["events"]] == ["a", "b"]
        s3_requests.clear()

        # a flush after the plan read: the freshness check sees it, and the
        # central directory and journal are re-read (start.json is not)
        await _flush(running, [running.sample(3)])
        journal = upload()
        [view] = await read_task_views(fs, index.tasks)
        assert s3_requests == Counter({"GetObject": 1 + 1 + journal, "HeadObject": 1})
        assert task_row(view)["samples"]["completed"] == 2


def test_cli_buffer_rows_messages_and_store_are_unsupported(
    tmp_path: Path, finished_log: EvalLog, no_discovery: None
) -> None:
    running = anyio.run(
        functools.partial(
            _start_running_log,
            tmp_path,
            finished_log,
            logged=[1],
            sample_ids=[1, 2],
            log_shared=10,
        )
    )
    _write_buffer(running.location, [(_buffer_summary(2), [[_info("a", "e1")]])])
    task_id = running.spec.task_id

    listed = _json(_ctl(str(tmp_path), "task", "list", "--json"))
    [row] = listed["tasks"]
    assert row["samples"]["in_flight"] == 1 and row["live_samples"] == "buffer"
    shown = _ctl(str(tmp_path), "sample", "show", task_id, "2", "--json")
    assert shown.exit_code == 0 and _json(shown)["status"] == "running"
    for verb, read in (("messages", "message list"), ("store", "store")):
        result = _ctl(str(tmp_path), "sample", verb, task_id, "2", "--json")
        assert result.exit_code == 1
        error = _json(result)["error"]
        assert error["kind"] == "unsupported"
        assert error["status"] is None and error["exception"] is None
        assert f"its {read} is not in the shared buffer" in error["message"]
        assert (
            f"`inspect ctl sample events {task_id} 2 1 --type model --log-dir "
            f"{tmp_path}` shows its model calls." in error["message"]
        )
    human = _ctl(str(tmp_path), "task", "list")
    assert "running samples are visible only with --log-shared" in human.stderr


def test_cli_buffer_reads_leave_the_directory_unchanged(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    running = anyio.run(
        functools.partial(
            _start_running_log,
            tmp_path,
            finished_log,
            logged=[1],
            sample_ids=[1, 2],
            log_shared=10,
        )
    )
    _write_buffer(running.location, [(_buffer_summary(2), [[_info("a", "e1")]])])
    task_id = running.spec.task_id

    def snapshot() -> dict[str, tuple[int, int]]:
        return {
            str(p): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in tmp_path.rglob("*")
        }

    before = snapshot()
    for args in (
        ["task", "list"],
        ["sample", "list"],
        ["sample", "errors"],
        ["sample", "show", task_id, "2"],
        ["sample", "events", task_id, "2"],
        ["sample", "messages", task_id, "2"],
        ["sample", "store", task_id, "2"],
    ):
        _ctl(str(tmp_path), *args, "--json")
    assert snapshot() == before


@solver
def _wait_after_generate(started: anyio.Event, release: anyio.Event) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        started.set()
        await release.wait()
        return state

    return solve


@skip_if_trio
async def test_a_running_eval_with_log_shared_is_read_from_its_buffer(
    tmp_path: Path,
) -> None:
    started, release = anyio.Event(), anyio.Event()
    task = Task(
        name="live",
        dataset=[Sample(id=1, input="q", target="x")],
        solver=_wait_after_generate(started, release),
    )
    everything = frozenset({"*"})
    buffered: dict[str, Any] = {}

    async def read_while_running() -> None:
        await started.wait()
        with anyio.fail_after(60):
            while True:
                index, rows = await _index(tmp_path)
                if rows and rows[0]["samples"]["in_flight"] == 1:
                    break
                # polling the worker's buffer sync thread, not a sibling task
                await anyio.sleep(0.2)
        async with AsyncFilesystem() as fs:
            buffered["detail"] = await sample_detail(fs, index.tasks[0], "1", 1)
            buffered["page"] = await sample_events(
                fs, index.tasks[0], "1", 1, types=everything, full=True
            )
        release.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(read_while_running)
        [log] = await eval_async(
            task,
            model="mockllm/model",
            log_dir=str(tmp_path),
            log_shared=1,
        )
    assert log.status == "success"
    assert buffered["detail"]["status"] == "running"
    page = buffered["page"]
    assert page["done"] is False and page["events"]

    # the buffered events are the flushed sample's, up to the last sync
    index, _ = await _index(tmp_path)
    async with AsyncFilesystem() as fs:
        logged = await sample_events(
            fs, index.tasks[0], "1", 1, types=everything, full=True
        )
    prefix = logged["events"][: len(page["events"])]
    assert [e["uuid"] for e in page["events"]] == [e["uuid"] for e in prefix]
    buffered_model = next(e for e in page["events"] if e["event"] == "model")
    logged_model = next(e for e in prefix if e["event"] == "model")
    assert buffered_model["input"] == logged_model["input"]
    assert buffered_model["output"] == logged_model["output"]


def test_a_retry_attempts_cursor_restarts_on_the_next_attempt(
    tmp_path: Path, finished_log: EvalLog
) -> None:
    from inspect_ai.log._recorders.buffer.database import (
        SampleBufferDatabase,
        sync_to_filestore,
    )
    from inspect_ai.log._recorders.types import SampleEvent

    running = anyio.run(
        functools.partial(
            _start_running_log,
            tmp_path,
            finished_log,
            logged=[1],
            sample_ids=[1, 2],
            log_shared=10,
        )
    )
    db = SampleBufferDatabase(
        location=str(running.location), create=True, db_dir=tmp_path / "db"
    )
    store = SampleBufferFilestore(str(running.location))
    everything = frozenset({"*"})

    async def events(since: str | None = None) -> dict[str, Any]:
        index, _ = await _index(tmp_path)
        async with AsyncFilesystem() as fs:
            return await sample_events(
                fs, index.tasks[0], "2", 1, types=everything, full=True, since=since
            )

    def attempt(started_at: str, data: str) -> None:
        # `retry_on_error` re-runs with the same uuid and no retry count on
        # the running summary; only its start time differs
        db.start_sample(
            _buffer_summary(2, started_at=started_at).model_copy(
                update={"uuid": "same-uuid"}
            )
        )
        db.log_events([SampleEvent(id=2, epoch=1, event=InfoEvent(data=data))])
        sync_to_filestore(db, store)

    attempt("2099-01-01T00:00:00+00:00", "old")
    first = anyio.run(events)
    assert [e["data"] for e in first["events"]] == ["old"]
    # the failed attempt's rows are removed, and a sync sees it gone
    db.remove_samples([(2, 1)])
    sync_to_filestore(db, store)
    attempt("2099-01-01T00:01:00+00:00", "new")

    resumed = anyio.run(functools.partial(events, first["next"]))
    # the old attempt's cursor is foreign to the new attempt: it restarts
    assert [e["data"] for e in resumed["events"]] == ["new"]


@pytest.mark.parametrize("broken", ["event", "message_pool", "call_pool"])
def test_cli_buffer_events_that_do_not_parse_are_invalid_response(
    tmp_path: Path, finished_log: EvalLog, broken: str
) -> None:
    running = anyio.run(
        functools.partial(
            _start_running_log,
            tmp_path,
            finished_log,
            logged=[1],
            sample_ids=[1, 2],
            log_shared=10,
        )
    )
    event: dict[str, Any] = (
        {"uuid": "e1", "event": "no-such-event"}
        if broken == "event"
        else _info("a", "e1")
    )
    data = SampleData(
        events=[EventData(id=1, event_id="e1", sample_id="2", epoch=1, event=event)],
        attachments=[],
        message_pool=[
            MessagePoolData(id=1, sample_id="2", epoch=1, msg_id="m", data="{")
        ]
        if broken == "message_pool"
        else [],
        call_pool=[CallPoolData(id=1, sample_id="2", epoch=1, hash="h", data="{")]
        if broken == "call_pool"
        else [],
    )
    buffer = _write_buffer(running.location, [(_buffer_summary(2), [data])])
    result = _ctl(
        str(tmp_path), "sample", "events", running.spec.task_id, "2", "--json"
    )
    assert result.exit_code == 1
    error = _json(result)["error"]
    assert error["kind"] == "invalid_response"
    assert error["exception"] == "inspect_ai.LogUnparseableError"
    assert f"{buffer}/" in error["message"] and "segment.1.zip" in error["message"]
