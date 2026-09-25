"""The ``inspect ctl ... --log-dir`` reader (``inspect_ai._control.log_dir``).

Rows, attempt folding, the key set and totals, per-sample reads against the
live terminal envelopes, the CRC-checked bounded re-reads, the delimited
walk, and the request counts the design states for these reads (see
design/ctl/log-dir-mode.md). The CLI surface is tested in test_ctl.py.
"""

import functools
import shutil
import zipfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import boto3
import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai._control.log_dir import consistency
from inspect_ai._control.log_dir.consistency import (
    LogChangedError,
    LogUnparseableError,
    read_consistently,
)
from inspect_ai._control.log_dir.samples import (
    SampleNotFoundError,
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
from inspect_ai._util.async_zip import AsyncZipReader, ZipCrcError
from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, read_eval_log_async, write_eval_log_async
from inspect_ai.log._recorders.eval import EvalRecorder
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
    assert source.samples is not None
    spec = source.eval.model_copy(
        update={
            "task_id": "RUNNINGTASK000000000000",
            "eval_id": "RUNNINGEVAL000000000000",
            "dataset": source.eval.dataset.model_copy(
                update={"sample_ids": sample_ids}
            ),
        }
    )
    location = (
        directory / "2026-09-01T00-00-00+00-00_alpha_RUNNINGTASK000000000000.eval"
    )
    recorder = EvalRecorder(str(directory))
    await recorder.log_init(spec, str(location))
    await recorder.log_start(spec, source.plan)
    by_id = {s.id: s for s in source.samples}
    for sample_id in logged:
        sample = by_id.get(sample_id) or by_id[1].model_copy(update={"id": sample_id})
        await recorder.log_sample(spec, sample)
    await recorder.flush(spec)
    return location


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
    # running samples are in shared buffers, which this step does not read
    assert samples["in_flight"] is None
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
