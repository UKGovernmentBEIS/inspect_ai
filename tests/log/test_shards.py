import contextlib
import enum
import functools
import json
import os
import zipfile
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, BinaryIO, cast

import anyio
import boto3
import pytest

from inspect_ai import Epochs, Task, eval, eval_retry, task, task_with
from inspect_ai._eval.task import run as run_module
from inspect_ai._util.async_zip import AsyncZipReader, ZipCrcError
from inspect_ai._util.asyncfiles import AsyncFilesystem, DirListing
from inspect_ai._util.error import WriteConflictError
from inspect_ai._util.file import FileInfo, local_path
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    EvalLog,
    ShardMergeResult,
    ShardSelectionError,
    ShardSetError,
    ShardSetIncomplete,
    merge_eval_log_shards,
    read_eval_log,
    read_eval_log_async,
    write_eval_log,
)
from inspect_ai.log._file import is_log_file
from inspect_ai.log._log import EvalShardEntry
from inspect_ai.log._recorders.recorder import SampleRecordKey
from inspect_ai.log._shards._plan import (
    Selection,
    parse_sample_member,
    plan_status,
    selection_digest,
)
from inspect_ai.log._shards._walk import (
    ShardDir,
    ShardSetListing,
    attempt_sort_key,
    is_shard_path,
    list_shard_set,
)
from inspect_ai.model import get_model
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    Value,
    ValueToFloat,
    accuracy,
    aggregate,
    at_least,
    frequency,
    grouped,
    krippendorff_alpha,
    match,
    mean,
    mean_score,
    metric,
    pass_at,
    pass_k,
    scorer,
    value_to_float,
)
from inspect_ai.scorer._metric import MetricProtocol
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver

T1 = "2026-09-30T10-00-00-00-00"
T2 = "2026-09-30T11-00-00-00-00"
T0 = "2026-09-30T09-59-59-00-00"


def _touch(path: Path, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _info(name: str, mtime: float | None = None) -> FileInfo:
    return FileInfo(name=name, type="file", size=1, mtime=mtime)


def _names(shard: ShardDir) -> list[str]:
    return [Path(a.name).name for a in shard.attempts]


def _companion(root: Path) -> Path:
    """A companion covering every listing rule."""
    shards = root / "run.shards"
    # one attempt
    _touch(shards / "0" / f"{T1}_task_a.eval")
    # an original and its recovered copy, the original written last
    _touch(shards / "1" / f"{T1}_task_b-recovered.eval", mtime=1000)
    _touch(shards / "1" / f"{T1}_task_b.eval", mtime=2000)
    # two attempts, the older one touched last
    _touch(shards / "2" / f"{T2}_task_c.eval", mtime=1000)
    _touch(shards / "2" / f"{T1}_task_c.eval", mtime=2000)
    # a buffer, scan results, a checkpoints directory, another file
    _touch(shards / "2" / ".buffer" / "seg" / "segment.0.zip")
    _touch(shards / "2" / "scans" / "scan_id=x" / "rows.parquet")
    _touch(shards / "2" / f"{T2}_task_c.checkpoints" / "1")
    _touch(shards / "2" / "notes.txt")
    # a shard holding only a buffer
    _touch(shards / "3" / ".buffer" / "seg" / "segment.0.zip")
    # an empty shard directory is left out
    (shards / "4").mkdir()
    # a dot-prefixed directory is not a shard; its logs are stray
    _touch(shards / ".hidden" / f"{T1}_task_d.eval")
    _touch(shards / ".hidden" / "notes.txt")
    # stray: eval and json logs in the companion root, a json log in a shard
    _touch(shards / f"{T1}_task_e.eval")
    _touch(shards / f"{T1}_task_e.json")
    _touch(shards / "0" / f"{T1}_task_a.json")
    # a file that is not a log is ignored in the root
    _touch(shards / "run.merge.lock")
    # logs nested deeper are not listed, and are not shard paths
    _touch(shards / "2" / "scans" / f"{T1}_task_f.eval")
    _touch(shards / ".hidden" / "sub" / f"{T1}_task_g.eval")
    return shards


async def test_list_shard_set_applies_the_shard_set_rules(tmp_path: Path) -> None:
    shards_dir = _companion(tmp_path)
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, str(shards_dir))

    assert [s.name for s in listing.shards] == ["0", "1", "2", "3"]
    s0, s1, s2, s3 = listing.shards
    assert s0.dir == f"{shards_dir}/0"
    assert _names(s0) == [f"{T1}_task_a.eval"]
    assert s0.ancillary == [] and not s0.has_buffer
    assert _names(s1) == [f"{T1}_task_b.eval", f"{T1}_task_b-recovered.eval"]
    assert s1.current is not None and s1.current.name.endswith("-recovered.eval")
    assert _names(s2) == [f"{T1}_task_c.eval", f"{T2}_task_c.eval"]
    assert s2.has_buffer
    assert s2.ancillary == [
        f"{shards_dir}/2/{T2}_task_c.checkpoints",
        f"{shards_dir}/2/notes.txt",
        f"{shards_dir}/2/scans",
    ]
    assert s3 == ShardDir(
        name="3", dir=f"{shards_dir}/3", attempts=[], has_buffer=True, ancillary=[]
    )
    assert s3.current is None
    stray = {
        Path(s.path).relative_to(shards_dir).as_posix(): s.reason for s in listing.stray
    }
    assert list(stray) == [
        f".hidden/{T1}_task_d.eval",
        f"0/{T1}_task_a.json",
        f"{T1}_task_e.eval",
        f"{T1}_task_e.json",
    ]
    assert "starts with '.'" in stray[f".hidden/{T1}_task_d.eval"]
    assert "json log in a shard directory" in stray[f"0/{T1}_task_a.json"]
    assert "directly in the shards directory" in stray[f"{T1}_task_e.eval"]
    assert "directly in the shards directory" in stray[f"{T1}_task_e.json"]
    # the directories below the listed ones, buffers excepted
    assert [
        Path(d).relative_to(shards_dir).as_posix() for d in listing.unlisted_dirs
    ] == [".hidden/sub", f"2/{T2}_task_c.checkpoints", "2/scans"]


def _nested_companions(shards: Path) -> tuple[Path, Path]:
    """Companions nested in a shard's ancillary directory and a hidden one."""
    in_shard = shards / "2" / "x.shards"
    in_hidden = shards / ".hidden" / "y.shards"
    for nested in (in_shard, in_hidden):
        _touch(nested / "1" / f"{T1}_task_h.eval")
        _touch(nested / f"{T1}_task_i.eval")
    return in_shard, in_hidden


@pytest.mark.parametrize("form", ["path", "uri"])
async def test_list_shard_set_reports_every_log_is_shard_path_places_in_it(
    tmp_path: Path, form: str
) -> None:
    def location(path: Path) -> str:
        return path.as_uri() if form == "uri" else str(path)

    shards_dir = _companion(tmp_path)
    nested = _nested_companions(shards_dir)
    logs = {
        Path(directory) / name
        for directory, _, names in os.walk(tmp_path)
        for name in names
        if is_log_file(name, [".json"])
    }

    async def reported(companion: Path) -> set[Path]:
        async with AsyncFilesystem() as fs:
            listing = await list_shard_set(fs, location(companion))
        assert all(s.dir.startswith(location(companion)) for s in listing.shards)
        return {
            Path(local_path(a.name)) for s in listing.shards for a in s.attempts
        } | {Path(local_path(s.path)) for s in listing.stray}

    # from the log directory, the outer companion's walk reports exactly its
    # shard paths; the logs below it that it does not list are ordinary logs
    shard_paths = {
        log for log in logs if is_shard_path(location(tmp_path), location(log))
    }
    assert shard_paths == await reported(shards_dir)
    # with the logs nested in the directories it does not list, the walk
    # accounts for every log in the companion
    async with AsyncFilesystem() as fs:
        unlisted = (await list_shard_set(fs, location(shards_dir))).unlisted_dirs
    nested_logs = {
        log for log in logs if any(Path(local_path(d)) in log.parents for d in unlisted)
    }
    assert shard_paths | nested_logs == {
        log for log in logs if shards_dir in log.parents
    }
    assert not shard_paths & nested_logs
    assert logs - shard_paths == {
        shards_dir / "2" / "scans" / f"{T1}_task_f.eval",
        shards_dir / ".hidden" / "sub" / f"{T1}_task_g.eval",
        *(log for companion in nested for log in logs if companion in log.parents),
    }

    # from the directory holding a nested companion, its walk agrees in turn
    for companion in nested:
        root = companion.parent
        below = {log for log in logs if root in log.parents}
        shard_paths = {
            log for log in below if is_shard_path(location(root), location(log))
        }
        assert shard_paths == await reported(companion)
        assert len(shard_paths) == 2


async def test_list_shard_set_on_s3_reports_every_log_is_shard_path_places_in_it(
    mock_s3: None,
) -> None:
    s3 = boto3.client("s3")
    keys = [
        f"consistency/run.shards/0/{T1}_task_a.eval",
        f"consistency/run.shards/0/{T1}_task_a.json",
        f"consistency/run.shards/{T1}_task_b.eval",
        f"consistency/run.shards/{T1}_task_b.json",
        f"consistency/run.shards/.hidden/{T1}_task_c.eval",
        f"consistency/run.shards/0/scans/{T1}_task_d.eval",
        f"consistency/run.shards/0/x.shards/1/{T1}_task_e.eval",
        f"consistency/run.shards/.hidden/y.shards/1/{T1}_task_f.eval",
        "consistency/run.shards/0/.buffer/seg/segment.0.zip",
        "consistency/run.shards/.buffer/stem/segment.0.zip",
        f"consistency/{T1}_task_g.eval",
    ]
    for key in keys:
        s3.put_object(Bucket="test-bucket", Key=key, Body=b"x")
    root = "s3://test-bucket/consistency"
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, f"{root}/run.shards")
    reported = {a.name for s in listing.shards for a in s.attempts} | {
        s.path for s in listing.stray
    }
    shard_paths = {
        f"s3://test-bucket/{key}"
        for key in keys
        if is_shard_path(root, f"s3://test-bucket/{key}")
    }
    assert shard_paths == reported
    assert listing.unlisted_dirs == [
        f"{root}/run.shards/.hidden/y.shards",
        f"{root}/run.shards/0/scans",
        f"{root}/run.shards/0/x.shards",
    ]
    assert {
        f"s3://test-bucket/{key}" for key in keys if is_log_file(key, [".json"])
    } - shard_paths == {
        f"{root}/run.shards/0/scans/{T1}_task_d.eval",
        f"{root}/run.shards/0/x.shards/1/{T1}_task_e.eval",
        f"{root}/run.shards/.hidden/y.shards/1/{T1}_task_f.eval",
        f"{root}/{T1}_task_g.eval",
    }


async def test_list_shard_set_orders_numeric_shard_names_numerically(
    tmp_path: Path,
) -> None:
    shards_dir = tmp_path / "run.shards"
    names = [str(k) for k in range(12)] + ["010", "a", "b10", "b9"]
    for name in names:
        _touch(shards_dir / name / f"{T1}_task_a.eval")
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, str(shards_dir))
    assert [s.name for s in listing.shards] == [
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "010", "10", "11",
        "a", "b10", "b9",
    ]  # fmt: skip


async def test_list_shard_set_keeps_the_file_uri_form(tmp_path: Path) -> None:
    shards_dir = tmp_path / "run.shards"
    _touch(shards_dir / "k 1" / f"{T1}_task_a.eval")
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, shards_dir.as_uri())

    (shard,) = listing.shards
    assert shard.name == "k 1"
    assert shard.dir == f"{shards_dir.as_uri()}/k%201"
    assert shard.current is not None
    assert shard.current.name == f"{shards_dir.as_uri()}/k%201/{T1}_task_a.eval"


async def test_list_shard_set_of_a_missing_local_dir_is_empty(tmp_path: Path) -> None:
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, str(tmp_path / "absent.shards"))
    assert listing == ShardSetListing(shards=[], stray=[], unlisted_dirs=[])


async def test_list_shard_set_leaves_out_a_shard_removed_during_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shards_dir = tmp_path / "run.shards"
    _touch(shards_dir / "0" / f"{T1}_task_a.eval")
    _touch(shards_dir / "1" / f"{T1}_task_b.eval")
    original = AsyncFilesystem.list_dir

    async def removed(self: AsyncFilesystem, base: str, **kwargs: Any) -> DirListing:
        if base.endswith("/1"):
            raise FileNotFoundError(base)
        return await original(self, base, **kwargs)

    monkeypatch.setattr(AsyncFilesystem, "list_dir", removed)
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, str(shards_dir))
    assert [s.name for s in listing.shards] == ["0"]


async def test_list_shard_set_lists_at_most_32_shards_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shards_dir = tmp_path / "run.shards"
    for k in range(40):
        _touch(shards_dir / str(k) / f"{T1}_task_a.eval")
    original = AsyncFilesystem.list_dir
    in_flight = 0
    peak = 0
    full = anyio.Event()

    async def gated(self: AsyncFilesystem, base: str, **kwargs: Any) -> DirListing:
        nonlocal in_flight, peak
        if base == str(shards_dir):
            return await original(self, base, **kwargs)
        in_flight += 1
        peak = max(peak, in_flight)
        if in_flight == 32:
            full.set()
        await full.wait()
        in_flight -= 1
        return await original(self, base, **kwargs)

    monkeypatch.setattr(AsyncFilesystem, "list_dir", gated)
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, str(shards_dir))
    assert peak == 32
    assert len(listing.shards) == 40


async def test_list_shard_set_keeps_to_a_given_limiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shards_dir = tmp_path / "run.shards"
    for k in range(10):
        _touch(shards_dir / str(k) / f"{T1}_task_a.eval")
    original = AsyncFilesystem.list_dir
    in_flight = 0
    peak = 0

    async def counted(self: AsyncFilesystem, base: str, **kwargs: Any) -> DirListing:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await anyio.sleep(0.01)
            return await original(self, base, **kwargs)
        finally:
            in_flight -= 1

    monkeypatch.setattr(AsyncFilesystem, "list_dir", counted)
    limiter = anyio.CapacityLimiter(2)
    async with AsyncFilesystem() as fs:
        async with anyio.create_task_group() as tg:
            # a second walk sharing the limiter
            tg.start_soon(lambda: list_shard_set(fs, str(shards_dir), limiter=limiter))
            listing = await list_shard_set(fs, str(shards_dir), limiter=limiter)
    assert peak == 2
    assert len(listing.shards) == 10


async def test_cancelling_list_shard_set_cancels_its_listings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shards_dir = tmp_path / "run.shards"
    for k in range(40):
        (shards_dir / str(k)).mkdir(parents=True)
    original = AsyncFilesystem.list_dir
    started = 0
    cancelled = 0
    all_started = anyio.Event()

    async def blocked(self: AsyncFilesystem, base: str, **kwargs: Any) -> DirListing:
        nonlocal started, cancelled
        if base == str(shards_dir):
            return await original(self, base, **kwargs)
        started += 1
        if started == 32:
            all_started.set()
        try:
            await anyio.sleep_forever()
        finally:
            cancelled += 1
        raise AssertionError("unreachable")

    monkeypatch.setattr(AsyncFilesystem, "list_dir", blocked)
    result: list[ShardSetListing] = []
    async with AsyncFilesystem() as fs:
        async with anyio.create_task_group() as tg:

            async def run() -> None:
                result.append(await list_shard_set(fs, str(shards_dir)))

            tg.start_soon(run)
            await all_started.wait()
            tg.cancel_scope.cancel()
    assert result == []
    assert started == 32
    assert cancelled == 32


async def test_list_shard_set_on_s3(mock_s3: None) -> None:
    s3 = boto3.client("s3")
    prefix = "logs/run.shards"
    for key in (
        f"{prefix}/0/{T2}_task_a.eval",
        f"{prefix}/0/{T1}_task_a.eval",
        f"{prefix}/0/.buffer/seg/segment.0.zip",
        f"{prefix}/0/scans/scan_id=x/rows.parquet",
        f"{prefix}/0/{T1}_task_a.json",
        f"{prefix}/.hidden/{T1}_task_b.eval",
        f"{prefix}/{T1}_task_c.eval",
        f"{prefix}/{T1}_task_c.json",
    ):
        s3.put_object(Bucket="test-bucket", Key=key, Body=b"x")
    # a "folder" marker lists as a directory with nothing in it
    s3.put_object(Bucket="test-bucket", Key=f"{prefix}/1/", Body=b"")

    shards_dir = f"s3://test-bucket/{prefix}"
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, shards_dir)
        empty = await list_shard_set(fs, "s3://test-bucket/logs/absent.shards")

    (shard,) = listing.shards
    assert shard.name == "0" and shard.dir == f"{shards_dir}/0"
    assert [a.name for a in shard.attempts] == [
        f"{shards_dir}/0/{T1}_task_a.eval",
        f"{shards_dir}/0/{T2}_task_a.eval",
    ]
    assert shard.has_buffer
    assert shard.ancillary == [f"{shards_dir}/0/scans"]
    assert [s.path for s in listing.stray] == [
        f"{shards_dir}/.hidden/{T1}_task_b.eval",
        f"{shards_dir}/0/{T1}_task_a.json",
        f"{shards_dir}/{T1}_task_c.eval",
        f"{shards_dir}/{T1}_task_c.json",
    ]
    assert empty == ShardSetListing(shards=[], stray=[], unlisted_dirs=[])


async def test_list_shard_set_on_s3_leaves_out_a_shard_emptied_during_the_walk(
    mock_s3: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = boto3.client("s3")
    prefix = "logs/run.shards"
    for k in ("0", "1"):
        s3.put_object(
            Bucket="test-bucket", Key=f"{prefix}/{k}/{T1}_task_a.eval", Body=b"x"
        )
    shards_dir = f"s3://test-bucket/{prefix}"
    original = AsyncFilesystem.list_dir

    async def emptied(self: AsyncFilesystem, base: str, **kwargs: Any) -> DirListing:
        if base == f"{shards_dir}/1":
            s3.delete_object(Bucket="test-bucket", Key=f"{prefix}/1/{T1}_task_a.eval")
        return await original(self, base, **kwargs)

    monkeypatch.setattr(AsyncFilesystem, "list_dir", emptied)
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, shards_dir)
    assert [s.name for s in listing.shards] == ["0"]


_WEBHDFS = "webhdfs://user@namenode:9870/logs"


def _fake_webhdfs(monkeypatch: pytest.MonkeyPatch, files: list[str]) -> None:
    """Answer WebHDFS `LISTSTATUS` calls as a name node holding `files`.

    Only the service response is faked: `WebHDFS.ls` still names each entry
    with the qualified URL it was listed with. A path with an empty component
    lists that component as an entry with an empty suffix.
    """
    from types import SimpleNamespace
    from urllib.parse import urlsplit

    from inspect_ai._util.file import filesystem

    def call(self: Any, op: str, path: str = "", **kwargs: Any) -> Any:
        assert op == "LISTSTATUS"
        directory = urlsplit(path).path.rstrip("/")
        children: dict[str, str] = {}
        for file in files:
            if file.startswith(f"{directory}/"):
                head, nested, _ = file[len(directory) + 1 :].partition("/")
                children[head] = "DIRECTORY" if nested else "FILE"
        if not children:
            raise FileNotFoundError(path)
        statuses = [
            {"pathSuffix": name, "type": kind, "length": 1, "mtime": 1000.0}
            for name, kind in sorted(children.items())
        ]
        return SimpleNamespace(json=lambda: {"FileStatuses": {"FileStatus": statuses}})

    monkeypatch.setattr(type(filesystem(_WEBHDFS).fs), "_call", call)


@pytest.mark.parametrize(
    "hidden",
    [None, "run.shards//worker.eval", "run.shards/1//worker.eval"],
    ids=["ordinary", "root-empty", "shard-empty"],
)
async def test_list_shard_set_on_a_qualified_webhdfs_url(
    monkeypatch: pytest.MonkeyPatch, hidden: str | None
) -> None:
    files = [
        f"/logs/run.shards/0/{T1}_task_a.eval",
        f"/logs/run.shards/1/{T1}_task_b.eval",
        "/logs/run.shards/1/notes.txt",
    ]
    _fake_webhdfs(monkeypatch, files + ([f"/logs/{hidden}"] if hidden else []))
    shards_dir = f"{_WEBHDFS}/run.shards"
    async with AsyncFilesystem() as fs:
        if hidden is not None:
            with pytest.raises(ShardSetError, match="not a file or directory directly"):
                await list_shard_set(fs, shards_dir)
            return
        listing = await list_shard_set(fs, shards_dir)
    # locations keep the qualified URL they were listed with
    assert [(s.name, s.dir) for s in listing.shards] == [
        ("0", f"{shards_dir}/0"),
        ("1", f"{shards_dir}/1"),
    ]
    assert [a.name for s in listing.shards for a in s.attempts] == [
        f"{shards_dir}/0/{T1}_task_a.eval",
        f"{shards_dir}/1/{T1}_task_b.eval",
    ]
    assert listing.shards[1].ancillary == [f"{shards_dir}/1/notes.txt"]


def test_attempt_sort_key_parses_the_timestamp_as_a_datetime() -> None:
    # as text, "T10:30" sorts after "T10-45" (":" > "-"); as a time it is earlier
    colon = _info("2026-09-30T10:30:00+00:00_task_a.eval", mtime=3)
    dash = _info("2026-09-30T10-45-00-00-00_task_a.eval", mtime=1)
    earlier = _info(f"{T0}_task_a.eval", mtime=2)
    assert sorted([dash, colon, earlier], key=attempt_sort_key) == [
        earlier,
        colon,
        dash,
    ]


def test_attempt_sort_key_puts_recovered_after_its_source() -> None:
    recovered = _info(f"s3://b/k/{T1}_task_a-recovered.eval", mtime=1)
    source = _info(f"s3://b/k/{T1}_task_a.eval", mtime=2)
    later = _info(f"s3://b/k/{T2}_task_a.eval", mtime=0)
    assert sorted([later, recovered, source], key=attempt_sort_key) == [
        source,
        recovered,
        later,
    ]


def test_attempt_sort_key_falls_back_to_mtime() -> None:
    same_newer = _info(f"{T1}_task_a.eval", mtime=2)
    same_older = _info(f"{T1}_task_a.eval", mtime=1)
    plain_newer = _info("attempt.eval", mtime=20)
    plain_older = _info("attempt.eval", mtime=10)
    no_mtime = _info("attempt.eval", mtime=None)
    # a prefix that matches the pattern but is not a date sorts as untimestamped
    bad_date = _info("2026-13-45T10-00-00_task_a.eval", mtime=15)
    assert sorted(
        [same_newer, plain_newer, same_older, bad_date, plain_older, no_mtime],
        key=attempt_sort_key,
    ) == [no_mtime, plain_older, bad_date, plain_newer, same_older, same_newer]


@pytest.mark.parametrize(
    "root,path,expected",
    [
        ("/logs", "/logs/run.shards/0/a.eval", True),
        ("/logs", "/logs/sub/run.shards/0/a.eval", True),
        ("/logs", "/logs/a.eval", False),
        ("/logs", "/logs/sub/a.eval", False),
        # a file named like a companion is not a directory component
        ("/logs", "/logs/sub/x.shards", False),
        # a user directory named "shards", or exactly ".shards"
        ("/logs", "/logs/shards/0/a.eval", False),
        ("/logs", "/logs/.shards/0/a.eval", False),
        # a root that is itself a shard directory (a worker's view)
        ("/logs/run.shards/0", "/logs/run.shards/0/a.eval", False),
        ("/logs/run.shards", "/logs/run.shards/0/a.eval", False),
        # a companion nested in a shard is a companion only from a root
        # below the outer one; from above, its logs are too deep
        ("/logs/run.shards/0", "/logs/run.shards/0/x.shards/1/a.eval", True),
        ("/logs/run.shards/0", "/logs/run.shards/0/x.shards/a.eval", True),
        ("/logs", "/logs/run.shards/0/x.shards/1/a.eval", False),
        ("/logs", "/logs/run.shards/0/x.shards/a.eval", False),
        ("/logs", "/logs/run.shards/.hidden/y.shards/1/a.eval", False),
        (
            "/logs/run.shards/.hidden",
            "/logs/run.shards/.hidden/y.shards/1/a.eval",
            True,
        ),
        # directly in a companion, or in a dot-prefixed directory of one
        ("/logs", "/logs/run.shards/a.eval", True),
        ("/logs", "/logs/run.shards/.hidden/a.eval", True),
        # nested deeper than a shard directory
        ("/logs", "/logs/run.shards/0/scans/a.eval", False),
        ("/logs", "/logs/run.shards/.hidden/sub/a.eval", False),
        ("/logs/", "/logs/run.shards/0/a.eval", True),
        ("s3://b/logs", "s3://b/logs/run.shards/0/a.eval", True),
        ("s3://b/logs/run.shards/0", "s3://b/logs/run.shards/0/a.eval", False),
        ("file:///logs", "/logs/run.shards/0/a.eval", True),
        ("/logs", "file:///logs/run.shards/0/a.eval", True),
        ("file:///logs/a%20b.shards/0", "/logs/a b.shards/0/a.eval", False),
    ],
)
def test_is_shard_path(root: str, path: str, expected: bool) -> None:
    assert is_shard_path(root, path) is expected


def test_is_shard_path_resolves_relative_local_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    shard = (tmp_path / "logs" / "run.shards" / "0" / "a.eval").as_uri()
    assert is_shard_path("logs", shard)
    assert not is_shard_path("logs/run.shards/0", shard)


@pytest.mark.parametrize(
    "root,path",
    [
        ("/logs", "/other/run.shards/0/a.eval"),
        ("s3://b/logs", "/logs/run.shards/0/a.eval"),
        ("s3://b/logs", "s3://c/logs/run.shards/0/a.eval"),
    ],
)
def test_is_shard_path_refuses_a_path_outside_the_root(root: str, path: str) -> None:
    with pytest.raises(ValueError, match="is not below"):
        is_shard_path(root, path)


def _client_error(code: str) -> Exception:
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": code}}, "GetObject")


# The merge. Shards are written by mock-model evals into
# `<dir>/<NAME>.shards/<k>/`, as a launcher's workers would write them.

TASK = "shardy"
RUN_ID = "Zx7Run1Id"
NAME = f"2026-10-16T10-00-00-00-00_{TASK}_{RUN_ID}"
MATCH = "Default output from mockllm/model"


def _task(
    *, epochs: int | Epochs = 1, samples: int = 6, solver: Solver | None = None
) -> Task:
    return Task(
        dataset=[
            Sample(
                id=i,
                input=f"question {i}",
                target=MATCH if i % 2 else "something else",
                metadata={"index": i},
            )
            for i in range(1, samples + 1)
        ],
        solver=solver or generate(),
        scorer=match(),
        name=TASK,
        epochs=epochs,
    )


def _run(shards: str, k: str, task: Task | None = None, **kwargs: Any) -> EvalLog:
    return eval(
        task or _task(),
        model="mockllm/model",
        log_dir=f"{shards}/{k}",
        display="none",
        **kwargs,
    )[0]


def _paths(root: Path | str) -> tuple[str, str]:
    """The merged log and its shards directory under `root`."""
    return f"{root}/{NAME}.eval", f"{root}/{NAME}.shards"


def _rewrite(log: EvalLog, change: Callable[[EvalLog], None]) -> None:
    full = read_eval_log(log.location)
    change(full)
    write_eval_log(full, log.location)


def _as_running(log: EvalLog, keep: set[tuple[int, int]] | None = None) -> None:
    """Make a finished shard look like a running attempt holding `keep`."""

    def change(full: EvalLog) -> None:
        full.status = "started"
        full.stats.completed_at = ""
        full.results = None
        if keep is not None:
            assert full.samples is not None
            full.samples = [s for s in full.samples if (s.id, s.epoch) in keep]

    _rewrite(log, change)


def _members(log: str) -> list[str]:
    with zipfile.ZipFile(local_path(log)) as zf:
        return sorted(n for n in zf.namelist() if n.startswith("samples/"))


def _keys(log: str) -> set[tuple[str, int]]:
    keys = set()
    for name in _members(log):
        key = parse_sample_member(name)
        assert key is not None
        keys.add((key.sample_id, key.epoch))
    return keys


# ids the `_flaky` solver fails on; module state rather than a solver
# argument, so the task identifier is the same whichever samples fail
_FAILING: set[int] = set()


@solver
def _flaky() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.sample_id in _FAILING:
            raise RuntimeError(f"failed on {state.sample_id}")
        return await generate(state)

    return solve


@pytest.fixture
def failing() -> Any:
    _FAILING.clear()
    yield _FAILING
    _FAILING.clear()


def test_merge_refuses_a_recovered_log_name(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    recovered = f"{tmp_path}/{NAME}-recovered.eval"
    with pytest.raises(ValueError, match=f"{NAME}.eval.*{NAME}.shards"):
        merge_eval_log_shards(recovered, _task())
    assert not os.path.exists(recovered) and not os.path.exists(merged)

    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    before = Path(merged).read_bytes()
    with pytest.raises(ValueError, match="recovered"):
        merge_eval_log_shards(recovered, _task())
    assert not os.path.exists(recovered)
    assert Path(merged).read_bytes() == before


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"sample_ids": []}, "non-empty"),
        ({"sample_count": 0}, "at least 1"),
        ({"sample_ids": [1], "sample_count": 1}, "at most one"),
    ],
)
def test_merge_refuses_invalid_arguments(
    tmp_path: Path, kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        merge_eval_log_shards(_paths(tmp_path)[0], _task(), **kwargs)


def test_merge_with_neither_log_nor_shards_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        merge_eval_log_shards(_paths(tmp_path)[0], _task())


def test_merge_of_sample_id_shards_matches_an_unsharded_run(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(epochs=Epochs(2, "mean"))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    unsharded = eval(
        task, model="mockllm/model", log_dir=str(tmp_path / "unsharded"), display="none"
    )[0]

    result = merge_eval_log_shards(f"{shards}/", task)
    assert result.written
    header = result.log
    assert header.location == merged
    assert header.status == "success"
    assert header.eval.task_id == RUN_ID
    assert header.eval.config.sample_id is None
    assert header.eval.dataset.sample_ids == [1, 2, 3, 4, 5, 6]
    assert header.eval.shards is not None
    assert header.eval.shards.selection == "none"
    assert [e.shard for e in header.eval.shards.ledger] == ["0", "1"]
    assert [e.samples for e in header.eval.shards.ledger] == [6, 6]
    assert header.results is not None and unsharded.results is not None
    assert header.results.total_samples == unsharded.results.total_samples == 12
    assert header.results.scores == unsharded.results.scores

    log = read_eval_log(merged)
    assert log.samples is not None
    assert sorted((s.id, s.epoch) for s in log.samples) == [
        (i, e) for i in range(1, 7) for e in (1, 2)
    ]
    assert log.reductions is not None and unsharded.reductions is not None
    assert log.reductions[0].samples == unsharded.reductions[0].samples


@scorer(metrics={"other": [mean()]})
def parts() -> Scorer:
    """A per-key scorer whose key is another declared scorer's name."""

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value={"other": float(int(state.sample_id) % 2)})

    return score


@scorer(metrics=[accuracy()])
def other() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT if int(state.sample_id) <= 4 else INCORRECT)

    return score


def test_merge_keeps_declared_scorer_names_that_collide_with_result_names(
    tmp_path: Path,
) -> None:
    # `parts` reports a result named `other`, the name of a later scorer
    task = _task()
    task.scorer = [parts(), other()]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    unsharded = eval(
        task, model="mockllm/model", log_dir=str(tmp_path / "unsharded"), display="none"
    )[0]
    assert unsharded.results is not None

    result = merge_eval_log_shards(merged, task)
    assert result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores
    [declared] = [s for s in result.log.results.scores if "accuracy" in s.metrics]
    assert declared.metrics["accuracy"].value == pytest.approx(4 / 6)
    assert declared.scored_samples == 6


def test_a_scorer_declared_twice_merges_to_the_unsharded_values(
    tmp_path: Path,
) -> None:
    task = _task()
    task.scorer = [other(), other()]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    unsharded = eval(
        task, model="mockllm/model", log_dir=str(tmp_path / "unsharded"), display="none"
    )[0]
    log = merge_eval_log_shards(merged, task).log
    assert _metric_values(log) == _metric_values(unsharded)
    assert ("other1", "accuracy") in _metric_values(log)


@metric(scores="unreduced")
def shard_unreduced_total() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return float(sum(s.score.as_float() for s in scores))

    return compute


@scorer(metrics=[mean(), shard_unreduced_total()])
def graded() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # 3 and 6 score 0.75 in every epoch, the others 0.75 in one of two
        id = int(state.sample_id)
        return Score(value=0.75 if id % 3 == 0 or (id + state.epoch) % 2 else 0.25)

    return score


def _doubled(value: Value) -> float:
    return 2 * value_to_float()(value)


def _graded_task(epochs: Epochs | int) -> Task:
    task = _task(epochs=epochs)
    task.scorer = [graded()]
    return task


@pytest.mark.parametrize(
    "epochs",
    [
        pytest.param(2, id="default"),
        pytest.param(Epochs(1, at_least(1, value=0.5)), id="at_least-1-epoch"),
        pytest.param(Epochs(2, at_least(1, value=0.5)), id="at_least"),
        pytest.param(Epochs(2, pass_at(2, value=0.5)), id="pass_at"),
        pytest.param(Epochs(2, pass_k(2, value=0.5)), id="pass_k"),
        pytest.param(Epochs(2, mean_score(value_to_float=_doubled)), id="mean"),
        pytest.param(
            Epochs(2, [at_least(1, value=0.5), pass_at(2, value=0.5)]), id="two"
        ),
    ],
)
def test_configured_reducers_merge_with_the_workers_results(
    tmp_path: Path, epochs: Epochs | int
) -> None:
    # the log records `at_least_1`, `pass_at_2`, `mean`: not the arguments
    task = _graded_task(epochs)
    unsharded = eval(
        task, model="mockllm/model", log_dir=str(tmp_path / "unsharded"), display="none"
    )[0]
    assert unsharded.results is not None

    # fresh
    merged, shards = _paths(tmp_path / "fresh")
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, task)
    assert result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores
    assert read_eval_log(merged).reductions == unsharded.reductions

    # incremental: shard 0's samples are carried from a merge made while
    # shard 1 was running
    merged, shards = _paths(tmp_path / "incremental")
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _as_running(_run(shards, "1", task, sample_id=[4, 5, 6]), keep={(4, 1)})
    first = merge_eval_log_shards(merged, task, allow_incomplete=True).log
    assert first.status == "started" and first.results is not None
    _run(shards, "1", task, sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, task)
    assert result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores
    assert read_eval_log(merged).reductions == unsharded.reductions


def _replace_member(location: str, name: str, data: bytes | None) -> None:
    """Replace (or, with `None`, remove) a member of a log, keeping the rest."""
    path = local_path(location)
    with zipfile.ZipFile(path) as src:
        members = [(i, src.read(i)) for i in src.infolist() if i.filename != name]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, member in members:
            dst.writestr(info.filename, member)
        if data is not None:
            dst.writestr(name, data)


@solver
def _solver_scored() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.scores = {"simple": Score(value=1)}
        return state

    return solve


@pytest.mark.parametrize(
    "declared,metrics",
    [
        # no scorer: the task's metrics apply to the solver's score
        (False, [mean()]),
        # no scorer or task metrics: the workers record accuracy and stderr
        (False, None),
        (True, None),
    ],
    ids=["task-metrics", "recorded-defaults", "beside-a-scorer"],
)
def test_a_solver_set_score_is_refused(
    tmp_path: Path, declared: bool, metrics: list[Any] | None
) -> None:
    task = _task(solver=_solver_scored())
    if not declared:
        task.scorer = None
    task.metrics = metrics
    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    log = _run(shards, "1", task, sample_id=[4, 5, 6])
    if not declared and metrics is None:
        assert log.results is not None
        [score] = log.results.scores
        assert set(score.metrics) == {"accuracy", "stderr"}
    before = _files(shards)
    with pytest.raises(
        ShardSetError,
        match="Sample '1' has the score 'simple'.* cannot merge solver-set scores",
    ):
        merge_eval_log_shards(merged, task)
    assert not os.path.exists(merged) and _files(shards) == before


async def _metadata_score(state: TaskState, target: Target) -> Score:
    """The dictionary in the sample's metadata, in its key order."""
    return Score(value=dict(state.metadata["value"]))


@scorer(metrics=[{"*": [mean()]}])
def keyed() -> Scorer:
    return _metadata_score


def _keyed_task(values: dict[int, Any]) -> Task:
    return Task(
        dataset=[
            Sample(id=id, input=f"question {id}", metadata={"value": value})
            for id, value in values.items()
        ],
        solver=generate(),
        scorer=keyed(),
        name=TASK,
    )


def _metric_values(log: EvalLog) -> dict[tuple[str, str], float]:
    assert log.results is not None
    return {
        (score.name, name): metric.value
        for score in log.results.scores
        for name, metric in score.metrics.items()
    }


@pytest.mark.parametrize("incremental", [False, True], ids=["first", "incremental"])
def test_dictionary_scores_merge_to_the_unsharded_values_in_another_order(
    tmp_path: Path, incremental: bool
) -> None:
    # ids 2 and 10 merge as "10", "2", the reverse of the run's order
    values = {2: {"alpha": 1, "beta": 0}, 10: {"beta": 1, "alpha": 1}}
    unsharded = eval(
        _keyed_task(values),
        model="mockllm/model",
        log_dir=str(tmp_path / "unsharded"),
        display="none",
    )[0]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", _keyed_task(values), sample_id=[2])
    if incremental:
        merge_eval_log_shards(merged, _keyed_task(values), allow_incomplete=True)
    _run(shards, "1", _keyed_task(values), sample_id=[10])
    log = merge_eval_log_shards(merged, _keyed_task(values)).log
    assert _metric_values(log) == _metric_values(unsharded)
    assert _metric_values(log) == {("alpha", "mean"): 1.0, ("beta", "mean"): 0.5}


@pytest.mark.parametrize("snapshot", ["startup", "unscored"])
def test_a_merge_holding_no_scores_has_no_scored_samples(
    tmp_path: Path, failing: set[int], snapshot: str
) -> None:
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    task.solver = _flaky()
    merged, shards = _paths(tmp_path)
    if snapshot == "startup":
        # a running shard that has flushed no sample yet
        _as_running(_run(shards, "0", task, sample_id=[1, 2]), keep=set())
    else:
        # a failed shard holding a sample that errored before scoring
        failing.add(1)
        _run(shards, "0", task, sample_id=[1])
    header = merge_eval_log_shards(merged, task, allow_incomplete=True).log
    assert header.status == ("started" if snapshot == "startup" else "error")
    assert header.results is not None and header.results.scores[0].scored_samples == 0
    held = _keys(merged)
    assert held == (set() if snapshot == "startup" else {("1", 1), ("1", 2)})


@metric(name="shard_converted")
class ShardConverted(MetricProtocol):
    """A class metric whose constructor takes a converter."""

    def __init__(self, to_float: ValueToFloat = value_to_float()) -> None:
        self.to_float = to_float

    def __call__(self, scores: list[SampleScore]) -> Value:
        return {"converted": self.to_float(CORRECT)}


class Mode(enum.Enum):
    LOW = 1
    HIGH = 2


class Label(str, enum.Enum):
    ARS = "ARS"
    ORS = "ORS"


class Level(enum.IntEnum):
    ONE = 1
    TWO = 2


class Perm(enum.IntFlag):
    R = 4
    W = 2


class Colour(enum.Flag):
    RED = enum.auto()
    BLUE = enum.auto()


@metric(name="shard_enums")
def shard_enums(
    mode: Mode, label: Label, level: Level, perm: Perm, colour: Colour | None = None
) -> Metric:
    """A metric that tells its enum options from the values it was given."""

    def compute(scores: list[SampleScore]) -> Value:
        return (
            float(mode is Mode.HIGH)
            + 2 * float(label is Label.ARS)
            + 4 * float(level is Level.TWO)
            + 8 * float(isinstance(perm, Perm) and perm == Perm.R | Perm.W)
            + 16 * float(colour is Colour.BLUE)
        )

    return compute


@metric(name="shard_metric_map")
def shard_metric_map(by_name: dict[str, Metric]) -> Metric:
    """A metric given registered metrics in a dictionary."""

    def compute(scores: list[SampleScore]) -> Value:
        return sum(
            cast(float, cast(MetricProtocol, m)(scores)) for m in by_name.values()
        )

    return compute


@metric(name="shard_mean_keys")
def shard_mean_keys(
    keys: list[str],
    weight: float,
    excluded_sample_ids: list[str] | None = None,
) -> Metric:
    """A metric with plain list options."""

    def compute(scores: list[SampleScore]) -> Value:
        values = [
            weight * float(score.score.as_dict()[key] or 0)
            for score in scores
            if str(score.sample_id) not in (excluded_sample_ids or [])
            for key in keys
        ]
        # the progress display can compute metrics before any non-excluded
        # sample completes
        if not values:
            return float("nan")
        return sum(values) / len(values)

    return compute


async def _verdict(state: TaskState, target: Target) -> Score:
    index = state.metadata["index"]
    verdict = CORRECT if index % 2 else INCORRECT
    return Score(value={"verdict": verdict, "points": index / 2})


@scorer(
    metrics=[
        aggregate("points", mean()),
        grouped(aggregate("points", mean()), "group"),
        aggregate("verdict", accuracy()),
        # options a log records lossily: converters, metrics in a dictionary,
        # enum members
        aggregate("verdict", mean(), to_float=value_to_float(correct=2)),
        grouped(
            aggregate("verdict", mean(to_float=value_to_float(correct=2))), "group"
        ),
        ShardConverted(to_float=value_to_float(correct=2)),
        shard_metric_map(by_name={"points": aggregate("points", mean())}),
        shard_enums(Mode.HIGH, Label.ARS, Level.TWO, Perm.R | Perm.W, Colour.BLUE),
        shard_mean_keys(["points"], 2.0, excluded_sample_ids=["1"]),
    ]
)
def verdicts() -> Scorer:
    return _verdict


async def _unscored(state: TaskState, target: Target) -> Score:
    return Score.unscored()


@scorer(metrics=[mean()])
def unscored() -> Scorer:
    return _unscored


async def _ratings(state: TaskState, target: Target) -> Score:
    return Score(value=list(state.metadata["ratings"]))


async def _label(state: TaskState, target: Target) -> Score:
    return Score(value=CORRECT if state.metadata["index"] % 2 else INCORRECT)


@scorer(metrics=[frequency(categories=[CORRECT, INCORRECT, "P"])])
def labels() -> Scorer:
    return _label


@scorer(metrics=[krippendorff_alpha(level="ordinal")])
def ratings() -> Scorer:
    return _ratings


def _verdict_task(metrics: list[Any] | None = None, scored: bool = True) -> Task:
    """Six samples scored by `verdicts()`, or with `metrics` in its place.

    With `scored=False`, every sample is unscored.
    """
    if metrics is None:
        scorers = [verdicts(), ratings(), match(), labels()]
    else:
        scorers = [verdicts() if scored else unscored()]
    return Task(
        dataset=[
            Sample(
                id=i,
                input=f"question {i}",
                target=MATCH if i % 2 else "something else",
                metadata={
                    "index": i,
                    "group": "odd" if i % 2 else "even",
                    "ratings": [i % 3, (i + i // 3) % 3],
                },
            )
            for i in range(1, 7)
        ],
        solver=generate(),
        scorer=scorers,
        metrics=metrics,
        name=TASK,
    )


def test_metrics_with_options_merge_to_the_unsharded_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsharded = eval(
        _verdict_task(),
        model="mockllm/model",
        log_dir=str(tmp_path / "unsharded"),
        display="none",
    )[0]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", _verdict_task(), sample_id=[1, 2, 3])
    assert merge_eval_log_shards(merged, _verdict_task(), allow_incomplete=True).written
    _run(shards, "1", _verdict_task(), sample_id=[4, 5, 6])
    log = _merge_on("trio", monkeypatch, merged, _verdict_task()).log
    expected = _metric_values(unsharded)
    assert _metric_values(log) == pytest.approx(expected)
    # each enum option reached the metric as its member
    assert expected[("verdicts", "shard_enums")] == 31
    # samples 2 to 6, points index / 2, weighted 2
    assert expected[("verdicts", "shard_mean_keys")] == 4.0
    assert expected[("verdicts", "shard_metric_map")] == 1.75
    assert expected[("labels", "P")] == 0.0
    assert ("ratings", "krippendorff_alpha") in expected


def test_metrics_survive_progress_before_a_non_excluded_sample_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    display_fn = run_module.update_metrics_display_fn

    def every_sample(*args: Any, **kwargs: Any) -> Callable[..., None]:
        # a fresh display function per call computes at once, without the
        # display's throttling interval
        return lambda *update: display_fn(*args, **kwargs)(*update)

    monkeypatch.setattr(run_module, "update_metrics_display_fn", every_sample)
    # one sample at a time, so the progress display computes metrics over
    # sample 1 alone, which `shard_mean_keys` excludes
    log = _run(str(tmp_path), "0", _verdict_task(), sample_id=[1, 2], max_samples=1)
    assert log.status == "success"
    # sample 2, points 1.0, weighted 2
    assert _metric_values(log)[("verdicts", "shard_mean_keys")] == 2.0


async def _group_score(state: TaskState, target: Target) -> Score:
    return Score(value=state.metadata["value"])


@scorer(metrics=[grouped(mean(), "group", all=False)])
def group_valued() -> Scorer:
    return _group_score


def _group_task(groups: dict[int, Any]) -> Task:
    """Sample `id` scores `id - 1`, in the group its metadata names."""
    return Task(
        dataset=[
            Sample(
                id=id, input=f"question {id}", metadata={"group": g, "value": id - 1}
            )
            for id, g in groups.items()
        ],
        solver=generate(),
        scorer=group_valued(),
        name=TASK,
    )


@pytest.mark.parametrize("kind", ["tuple-list", "strings"])
def test_merged_metrics_see_metadata_as_stored_in_the_log(
    tmp_path: Path, kind: str
) -> None:
    # decision: Ransom, 2026-10-29: merge equality is over the JSON values a
    # log stores; a tuple and a list are stored alike, so their groups merge
    groups: dict[int, Any] = (
        {1: ("a", "b"), 2: ["a", "b"]} if kind == "tuple-list" else {1: "x", 2: "y"}
    )
    native = eval(
        _group_task(groups),
        model="mockllm/model",
        log_dir=str(tmp_path / "unsharded"),
        display="none",
    )[0]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", _group_task(groups), sample_id=[1])
    _run(shards, "1", _group_task(groups), sample_id=[2])
    log = merge_eval_log_shards(merged, _group_task(groups)).log
    if kind == "tuple-list":
        assert _metric_values(native) == {
            ("group_valued", "('a', 'b')"): 0.0,
            ("group_valued", "['a', 'b']"): 1.0,
        }
        assert _metric_values(log) == {("group_valued", "['a', 'b']"): 0.5}
    else:
        assert _metric_values(log) == _metric_values(native)
        assert _metric_values(log) == {
            ("group_valued", "x"): 0.0,
            ("group_valued", "y"): 1.0,
        }


@metric(name="shard_tuple_values", scores="unreduced")
def shard_tuple_values() -> Metric:
    """How many scores hold a tuple value (unreduced: reduction makes a list)."""

    def compute(scores: list[SampleScore]) -> Value:
        return float(sum(isinstance(s.score.value, tuple) for s in scores))

    return compute


@metric(name="shard_tuple_metadata")
def shard_tuple_metadata() -> Metric:
    """How many scores hold a tuple in their metadata."""

    def compute(scores: list[SampleScore]) -> Value:
        return float(
            sum(isinstance((s.score.metadata or {}).get("pair"), tuple) for s in scores)
        )

    return compute


async def _pair_score(state: TaskState, target: Target) -> Score:
    pair = tuple if state.metadata["kind"] == "tuple" else list
    return Score(value=pair([1, 2]), metadata={"pair": pair(["a", "b"])})


@scorer(metrics=[shard_tuple_values(), shard_tuple_metadata()])
def paired() -> Scorer:
    return _pair_score


def _paired_task(kind: str) -> Task:
    return Task(
        dataset=[
            Sample(id=id, input=f"question {id}", metadata={"kind": kind})
            for id in (1, 2)
        ],
        solver=generate(),
        scorer=paired(),
        name=TASK,
    )


@pytest.mark.parametrize("kind", ["tuple", "list"])
def test_merged_metrics_see_scores_as_stored_in_the_log(
    tmp_path: Path, kind: str
) -> None:
    # decision: Ransom, 2026-10-29, extended 2026-11-02: merged metrics see
    # Score.value and Score.metadata as the log stores them, where a tuple
    # is a list
    native = eval(
        _paired_task(kind),
        model="mockllm/model",
        log_dir=str(tmp_path / "unsharded"),
        display="none",
    )[0]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", _paired_task(kind), sample_id=[1])
    _run(shards, "1", _paired_task(kind), sample_id=[2])
    log = merge_eval_log_shards(merged, _paired_task(kind)).log
    stored = {
        ("paired", "shard_tuple_values"): 0.0,
        ("paired", "shard_tuple_metadata"): 0.0,
    }
    assert _metric_values(log) == stored
    if kind == "tuple":
        assert _metric_values(native) == {
            ("paired", "shard_tuple_values"): 2.0,
            ("paired", "shard_tuple_metadata"): 2.0,
        }
    else:
        assert _metric_values(native) == stored


def _check_invalidated(merged: str, expected: bool) -> None:
    from inspect_ai._eval.evalset import all_evals_succeeded

    log = read_eval_log(merged)
    assert log.samples is not None
    assert log.invalidated == expected
    assert any(s.invalidation is not None for s in log.samples) == expected
    assert all_evals_succeeded([log]) == (not expected)


def test_merged_invalidated_follows_the_merged_samples(tmp_path: Path) -> None:
    from inspect_ai.log import ProvenanceData, invalidate_samples

    def invalidated(log: EvalLog) -> None:
        full = read_eval_log(log.location)
        assert full.samples is not None
        out = invalidate_samples(
            full, [full.samples[0].uuid or ""], ProvenanceData(author="test")
        )
        write_eval_log(out, log.location)

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    invalidated(_run(shards, "1", sample_id=[4, 5, 6]))
    # fresh merge of an invalidated shard sample
    assert merge_eval_log_shards(merged, _task()).log.invalidated
    _check_invalidated(merged, True)
    # a replacement without the last invalidated sample clears the flag
    _run(shards, "1", sample_id=[4, 5, 6])
    assert not merge_eval_log_shards(merged, _task()).log.invalidated
    _check_invalidated(merged, False)
    # an invalidated replacement in an incremental merge sets it
    invalidated(_run(shards, "1", sample_id=[4, 5, 6]))
    assert merge_eval_log_shards(merged, _task()).log.invalidated
    _check_invalidated(merged, True)


def test_merge_of_limit_range_shards(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", limit=(0, 3))
    _run(shards, "1", limit=(3, 6))
    result = merge_eval_log_shards(merged, _task(), sample_count=6)
    assert result.log.status == "success"
    assert result.log.eval.shards is not None
    assert result.log.eval.shards.selection == "count"
    assert result.log.eval.shards.sample_count == 6
    assert result.log.eval.config.limit is None
    assert _keys(merged) == {(str(i), 1) for i in range(1, 7)}


def test_merge_of_an_incomplete_set_raises_and_writes_nothing(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    with pytest.raises(ShardSetIncomplete) as raised:
        merge_eval_log_shards(merged, _task(), sample_ids=[1, 2, 3, 4, 5])
    assert raised.value.status == "started"
    assert raised.value.missing == [4, 5]
    assert raised.value.running == [] and raised.value.failed == []
    assert not os.path.exists(merged)

    result = merge_eval_log_shards(
        merged, _task(), sample_ids=[1, 2, 3, 4, 5], allow_incomplete=True
    )
    assert result.log.status == "started"
    assert result.log.eval.dataset.sample_ids == [1, 2, 3, 4, 5]
    # an unchanged call without allow_incomplete still raises
    with pytest.raises(ShardSetIncomplete):
        merge_eval_log_shards(merged, _task())


def test_merge_status_from_running_and_failed_shards(
    tmp_path: Path, failing: set[int]
) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(solver=_flaky())
    running = _run(shards, "0", task, sample_id=[1, 2])
    _as_running(running)
    failing.add(4)
    failed = _run(shards, "1", task, sample_id=[3, 4])
    assert failed.status == "error"
    failing.clear()
    _run(shards, "2", task, sample_id=[5, 6])

    with pytest.raises(ShardSetIncomplete) as raised:
        merge_eval_log_shards(merged, task)
    assert raised.value.status == "error"
    assert raised.value.running == ["0"] and raised.value.failed == ["1"]

    result = merge_eval_log_shards(merged, task, allow_incomplete=True)
    header = result.log
    assert header.status == "error"
    assert header.error is not None and "failed on 4" in header.error.message
    assert header.eval.shards is not None
    ledger = header.eval.shards.ledger
    assert [e.status for e in ledger] == ["started", "error", "success"]
    assert ledger[1].error == header.error
    assert header.stats.completed_at == ""

    # re-running the failed shard in its directory clears the error
    _run(shards, "1", task, sample_id=[3, 4])
    header = merge_eval_log_shards(merged, task, allow_incomplete=True).log
    assert header.status == "started" and header.error is None
    assert header.eval.shards is not None
    assert header.eval.shards.ledger[1].log != ledger[1].log

    # the cancelled status counts as failed too
    _rewrite(running, lambda log: setattr(log, "status", "cancelled"))
    header = merge_eval_log_shards(merged, task, allow_incomplete=True).log
    assert header.status == "error"


def test_merge_of_a_drained_success_shard_stays_started(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    drained = _run(shards, "1", sample_id=[4, 5, 6])

    def drain(log: EvalLog) -> None:
        assert log.samples is not None
        log.samples = [s for s in log.samples if s.id != 6]

    _rewrite(drained, drain)
    with pytest.raises(ShardSetIncomplete) as raised:
        merge_eval_log_shards(merged, _task(), sample_ids=list(range(1, 7)))
    assert raised.value.status == "started" and raised.value.missing == [6]
    # without a selection, the dataset size decides
    with pytest.raises(ShardSetIncomplete):
        merge_eval_log_shards(merged, _task())


# ids whose sample a drain cancels as it starts (`_MATERIALIZING`), and ids
# whose sample stamps a drain while it runs, so the samples still queued are
# abandoned (`_DRAINING`); module state, as for `_FAILING`
_MATERIALIZING: set[int] = set()
_DRAINING: set[int] = set()


def _drain(eval_id: str) -> None:
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    assert state is not None and state.task_cancel is not None
    state.task_cancel.request("drain")


@solver
def _drainable() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        from inspect_ai.log._samples import sample_active

        if state.sample_id in _MATERIALIZING:
            # the drain's self-interrupt is delivered at this checkpoint
            await anyio.sleep(10)
        if state.sample_id in _DRAINING:
            active = sample_active()
            assert active is not None
            _drain(active.eval_id)
        return await generate(state)

    return solve


@pytest.fixture
def drains(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Stamp a drain as each `_MATERIALIZING` sample starts.

    As in `test_drain_resolution_cancels_materializing_sample`: after the
    sample's queue-exit check, so the drain resolves it as cancelled.
    """
    from anyio.abc import TaskGroup

    from inspect_ai.log._samples import ActiveSample

    original = ActiveSample.start

    def start(self: ActiveSample, tg: TaskGroup) -> None:
        if self.sample.id in _MATERIALIZING:
            _drain(self.eval_id)
        original(self, tg)

    monkeypatch.setattr(ActiveSample, "start", start)
    yield
    _MATERIALIZING.clear()
    _DRAINING.clear()


def _drained_task() -> Task:
    return _task(samples=4, solver=_drainable())


def _run_drained(shards: str, k: str, sample_id: list[int]) -> EvalLog:
    """Run shard `k` one sample at a time, so the drain finds earlier ones done."""
    return _run(shards, k, _drained_task(), sample_id=sample_id, max_samples=1)


def _cancelled_while_starting(shards: str) -> EvalLog:
    """Shard 1 for ids 3 and 4, with 4 cancelled by a drain as it starts."""
    _MATERIALIZING.add(4)
    log = _run_drained(shards, "1", [3, 4])
    _MATERIALIZING.clear()
    assert log.status == "success" and log.samples is not None
    assert sorted(s.id for s in log.samples) == [3, 4]
    assert log.results is not None and log.results.logged_samples == 1
    return log


def _merge_on(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
    merged: str,
    task: Task,
    **kwargs: Any,
) -> ShardMergeResult:
    """Merge with the async API on `backend` (the drain producers run on asyncio)."""
    from inspect_ai.log import merge_eval_log_shards_async

    with monkeypatch.context() as patched:
        patched.setenv("INSPECT_ASYNC_BACKEND", backend)
        return anyio.run(
            functools.partial(merge_eval_log_shards_async, merged, task, **kwargs),
            backend=backend,
        )


def test_a_shard_whose_only_sample_a_drain_cancelled_is_refused(
    tmp_path: Path, drains: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    merged, shards = _paths(tmp_path)
    # a drain as the only sample starts: no sample scored, so no results and
    # no count, but the sample's error shows the cancellation
    _MATERIALIZING.add(1)
    cancelled = _run_drained(shards, "0", [1])
    _MATERIALIZING.clear()
    assert cancelled.status == "success" and cancelled.results is None
    _run_drained(shards, "1", [2, 3, 4])
    before = _files(str(tmp_path))
    unresolved = "holds 1 samples but resolved only 0"
    with pytest.raises(ShardSetError, match=unresolved):
        merge_eval_log_shards(merged, _task())
    with pytest.raises(ShardSetError, match=unresolved):
        _merge_on("trio", monkeypatch, merged, _task())
    assert _files(str(tmp_path)) == before


@pytest.mark.parametrize("merge", ["fresh", "incremental"])
def test_a_shard_holding_a_sample_cancelled_by_a_drain_is_refused(
    tmp_path: Path, drains: None, monkeypatch: pytest.MonkeyPatch, merge: str
) -> None:
    merged, shards = _paths(tmp_path)
    _run_drained(shards, "0", [1, 2])
    if merge == "incremental":
        # a drain that abandoned queued sample 4 leaves the set started
        _DRAINING.add(3)
        queued = _run_drained(shards, "1", [3, 4])
        _DRAINING.clear()
        assert queued.samples is not None and [s.id for s in queued.samples] == [3]
        assert queued.results is not None and queued.results.logged_samples == 1
        result = merge_eval_log_shards(merged, _task(), allow_incomplete=True)
        assert result.written and result.log.status == "started"
    _cancelled_while_starting(shards)
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="holds 2 samples but resolved only 1"):
        merge_eval_log_shards(merged, _task())
    with pytest.raises(ShardSetError, match="holds 2 samples but resolved only 1"):
        _merge_on("trio", monkeypatch, merged, _task())
    assert _files(str(tmp_path)) == before


@pytest.mark.parametrize("case", ["errored", "queued_drain"])
def test_errored_samples_and_queued_drains_merge(
    tmp_path: Path, failing: set[int], drains: None, case: str
) -> None:
    merged, shards = _paths(tmp_path)
    if case == "errored":
        task = _task(samples=4, solver=_flaky())
        _run(shards, "0", task, sample_id=[1, 2], fail_on_error=False)
        failing.add(4)
        errored = _run(shards, "1", task, sample_id=[3, 4], fail_on_error=False)
        assert errored.status == "success" and errored.results is not None
        assert errored.results.logged_samples is None
    else:
        task = _drained_task()
        _run_drained(shards, "0", [1, 2])
        _DRAINING.add(3)
        _run_drained(shards, "1", [3, 4])
        _DRAINING.clear()
        header = merge_eval_log_shards(merged, task, allow_incomplete=True).log
        assert header.status == "started"
        assert _keys(merged) == {("1", 1), ("2", 1), ("3", 1)}
        _run_drained(shards, "1", [3, 4])
    result = merge_eval_log_shards(merged, task)
    assert result.written
    assert result.log.status == "success"
    assert _keys(merged) == {(str(i), 1) for i in range(1, 5)}


def test_merge_keeps_exactly_the_records_a_running_shard_holds(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(epochs=2)
    running = _run(shards, "0", task, sample_id=[1])
    _as_running(running, keep={(1, 1)})
    other = _run(shards, "1", task, sample_id=[2])
    header = merge_eval_log_shards(
        merged, task, sample_ids=[1, 2], allow_incomplete=True
    ).log
    assert header.eval.shards is not None
    assert header.eval.shards.ledger[0].samples == 1
    assert _keys(merged) == {("1", 1), ("2", 1), ("2", 2)}

    # another shard changes; the running one is carried as it was
    _rewrite(other, lambda log: None)
    header = merge_eval_log_shards(merged, task, allow_incomplete=True).log
    assert header.status == "started"
    assert _keys(merged) == {("1", 1), ("2", 1), ("2", 2)}


def test_merge_refuses_two_shards_selecting_one_id(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    _run(shards, "1", sample_id=[2, 3])
    with pytest.raises(ShardSetError, match="both select sample '2'"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert not os.path.exists(merged)


# shard directory names other than digits; `prefix\\0` would read as shard `0`
_NOT_NUMBERS = ["a", "1#tag", "prefix\\0"]


@pytest.mark.parametrize("merge", ["fresh", "existing"])
@pytest.mark.parametrize("form", ["path", "file_uri"])
@pytest.mark.parametrize("name", _NOT_NUMBERS)
def test_a_shard_directory_not_named_with_digits_is_refused(
    tmp_path: Path, name: str, form: str, merge: str
) -> None:
    from inspect_ai._util.file import to_uri

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5])
    if merge == "existing":
        result = merge_eval_log_shards(merged, _task(), sample_ids=[1, 2, 3, 4, 5])
        assert result.log.status == "success"
    # a worker for the last sample, in a directory not named with digits
    _run(shards, name, sample_id=[6])
    target = to_uri(merged) if form == "file_uri" else merged
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="must be named with digits only"):
        merge_eval_log_shards(target, _task(), sample_ids=list(range(1, 7)))
    assert _files(str(tmp_path)) == before


def test_a_ledger_recording_a_shard_twice_is_refused(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged, _task())

    def duplicate(header: dict[str, Any]) -> None:
        ledger = header["eval"]["shards"]["ledger"]
        ledger.append(ledger[0])

    _edit_header(merged, duplicate)
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="records a shard more than once"):
        merge_eval_log_shards(merged, _task())
    assert _files(str(tmp_path)) == before


def test_a_ledger_recording_an_attempt_name_with_a_backslash_is_refused(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged, _task())

    def backslash(header: dict[str, Any]) -> None:
        entry = header["eval"]["shards"]["ledger"][0]
        entry["log"] = f"prefix\\{entry['log']}"

    _edit_header(merged, backslash)
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="a name with a backslash"):
        merge_eval_log_shards(merged, _task())
    assert _files(str(tmp_path)) == before


# a file name pattern whose names `_name` would read as `worker.eval`, losing
# the timestamp that orders a shard's attempts
_BACKSLASH_PATTERN = "{task}\\worker"
_OLDER = "2026-01-01T00-00-00-00-00"


def _backslash_attempts(
    shards: str, monkeypatch: pytest.MonkeyPatch, move: Callable[[str, str], None]
) -> str:
    """Shard 0 with two dated attempts and shard 1, named by `_BACKSLASH_PATTERN`.

    Returns the newer attempt of shard 0.
    """
    with monkeypatch.context() as patched:
        patched.setenv("INSPECT_EVAL_LOG_FILE_PATTERN", _BACKSLASH_PATTERN)
        older = _run(shards, "0", sample_id=[1, 2, 3])
        directory, _, name = older.location.rpartition("/")
        assert name.endswith(f"_{TASK}\\worker.eval")
        # an earlier date, so the two attempts' names differ
        move(older.location, f"{directory}/{_OLDER}_{name.split('_', 1)[1]}")
        newer = _run(shards, "0", sample_id=[1, 2, 3])
        _run(shards, "1", sample_id=[4, 5, 6])
    return newer.location


def _merge_unchecked(monkeypatch: pytest.MonkeyPatch, merged: str) -> None:
    """Merge as a merge without the attempt-name check would.

    Backslashed names all read as `worker.eval`, with no timestamp, so their
    attempts also tie in attempt order; that check is skipped too.
    """
    from inspect_ai.log._shards import _api

    with monkeypatch.context() as patched:
        patched.setattr(_api, "check_attempt_names", lambda shards: None, raising=False)
        patched.setattr(
            _api, "check_current_unambiguous", lambda shards: None, raising=False
        )
        assert merge_eval_log_shards(merged, _task()).log.status == "success"


_BACKSLASH = "its file name contains a backslash"


@pytest.mark.parametrize("state", ["fresh", "unchanged", "removed"])
@pytest.mark.parametrize("form", ["path", "file_uri"])
def test_attempt_names_with_a_backslash_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str, state: str
) -> None:
    from inspect_ai._util.file import to_uri

    merged, shards = _paths(tmp_path)
    newer = _backslash_attempts(shards, monkeypatch, os.rename)
    if state != "fresh":
        _merge_unchecked(monkeypatch, merged)
    if state == "removed":
        # what an interrupted deletion leaves: the older attempt is current
        os.remove(newer)
    target = to_uri(merged) if form == "file_uri" else merged
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match=_BACKSLASH):
        merge_eval_log_shards(target, _task())
    assert _files(str(tmp_path)) == before


def test_distinct_shard_names_with_the_same_number_merge(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "00", sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, _task())
    assert result.written
    assert result.log.status == "success" and result.log.eval.shards is not None
    assert [e.shard for e in result.log.eval.shards.ledger] == ["0", "00"]


def test_merge_records_and_reads_back_each_selection_form(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    header = merge_eval_log_shards(
        merged, _task(), sample_ids=["2", 1, 3], allow_incomplete=True
    ).log
    assert header.eval.shards is not None
    assert header.eval.shards.selection == "ids"
    assert header.eval.dataset.sample_ids == ["2", 1, 3]
    # a later pass without a selection uses the recorded one
    with pytest.raises(ShardSetIncomplete) as raised:
        merge_eval_log_shards(merged, _task())
    assert raised.value.missing == [3]

    result = merge_eval_log_shards(merged, _task(), sample_count=2)
    assert result.written and result.log.status == "success"
    assert result.log.eval.shards is not None
    assert result.log.eval.shards.selection == "count"
    assert result.log.eval.shards.sample_count == 2
    assert result.log.eval.dataset.sample_ids == [1, 2]
    assert not merge_eval_log_shards(merged, _task()).written

    with pytest.raises(ShardSetIncomplete):
        merge_eval_log_shards(merged, _task(), sample_count=3)


def test_selection_digest_ignores_order_and_id_type() -> None:
    assert selection_digest([1, 2, "3"]) == selection_digest(["3", "2", 1, 1])
    assert selection_digest([1, 2]) != selection_digest([1, 2, 3])
    assert len(selection_digest([])) == 64


class _ScannedKeys(list[SampleRecordKey]):
    """Planned records that count the elements read and refuse a list scan."""

    reads = 0

    def __iter__(self) -> Iterator[SampleRecordKey]:
        for key in super().__iter__():
            self.reads += 1
            yield key

    def __contains__(self, key: object) -> bool:
        raise AssertionError("a membership test scanned the planned records")


@pytest.mark.parametrize("missing", [False, True], ids=["complete", "one-missing"])
def test_status_planning_reads_the_records_a_bounded_number_of_times(
    missing: bool,
) -> None:
    ids, epochs = 2000, 5
    keys = _ScannedKeys(
        SampleRecordKey(str(id), epoch)
        for id in range(1, ids + 1)
        for epoch in range(1, epochs + 1)
        if not (missing and id == 1000 and epoch == 3)
    )
    entry = EvalShardEntry(
        shard="0",
        log="worker.eval",
        status="success",
        samples=len(keys),
        selected=ids,
        selection_digest=selection_digest(list(range(1, ids + 1))),
        size=1,
    )
    selection = Selection("ids", ids=list(range(1, ids + 1)))
    status = plan_status([entry], keys, selection, epochs, ids)
    assert status.status == ("started" if missing else "success")
    assert status.missing == ([1000] if missing else [])
    assert keys.reads <= 2 * len(keys)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("samples/1_epoch_1.json", ("1", 1)),
        ("samples/group/item_epoch_12.json", ("group/item", 12)),
        ("samples/a_epoch_b_epoch_3.json", ("a_epoch_b", 3)),
        ("samples/1_epoch_01.json", None),
        ("samples/1_epoch_x.json", None),
        ("samples/1_epoch_1/shell.json", None),
        ("summaries.json", None),
    ],
)
def test_parse_sample_member(name: str, expected: tuple[str, int] | None) -> None:
    assert parse_sample_member(name) == expected


def test_merged_header_carries_no_per_sample_list_but_sample_ids(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(epochs=3, samples=100)
    for k in range(4):
        _run(shards, str(k), task, sample_id=list(range(k * 25 + 1, k * 25 + 26)))
    header = merge_eval_log_shards(merged, task, sample_ids=list(range(1, 101))).log
    assert header.eval.config.sample_id is None
    with zipfile.ZipFile(merged) as zf:
        merged_header = zf.read("header.json")
    with zipfile.ZipFile(next(Path(f"{shards}/0").glob("*.eval"))) as zf:
        shard_header = zf.read("header.json")
    ids_text = json.dumps(list(range(1, 101)), separators=(",", ":"))
    assert merged_header.count(b'"sample_ids"') == 1
    # a shard's header plus the merged selection and a bound per shard
    assert len(merged_header) <= len(shard_header) + len(ids_text) + 4 * 2000


def _edit_header(location: str, change: Callable[[dict[str, Any]], None]) -> None:
    """Edit a shard's `header.json` in place, keeping every other member."""
    path = local_path(location)
    with zipfile.ZipFile(path) as src:
        members = [(info, src.read(info)) for info in src.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in members:
            if info.filename == "header.json":
                header = json.loads(data)
                change(header)
                data = json.dumps(header).encode()
            dst.writestr(info.filename, data)


def _remove_member(location: str, name: str) -> None:
    _replace_member(location, name, None)


@pytest.mark.parametrize(
    "other,detail",
    [
        ({"model": "mockllm/other"}, "task identifier"),
        ({"task": _task(samples=7)}, "dataset size"),
        ({"task": _task(epochs=2)}, "epochs"),
    ],
)
def test_merge_refuses_shards_of_different_runs(
    tmp_path: Path, other: dict[str, Any], detail: str
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    eval(
        other.get("task", _task()),
        model=other.get("model", "mockllm/model"),
        log_dir=f"{shards}/1",
        display="none",
        sample_id=[3, 4],
    )
    with pytest.raises(ShardSetError, match=detail):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert not os.path.exists(merged)


def test_merge_refuses_a_scorer_change_that_keeps_the_identifier(
    tmp_path: Path,
) -> None:
    from inspect_ai.scorer import includes

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    other = _task()
    other.scorer = [includes()]
    _run(shards, "1", other, sample_id=[3, 4])
    with pytest.raises(ShardSetError, match="scorers"):
        merge_eval_log_shards(merged, other, allow_incomplete=True)


def _mismatched(field: str) -> Task:
    """A task like `_task()` that differs from it in `field`."""
    if field == "task name":
        return task_with(_task(), name="another_task")
    if field == "scorers":
        changed = _task()
        changed.scorer = [other()]
        return changed
    if field == "scorer metrics":
        return Task(
            dataset=_task().dataset,
            solver=generate(),
            scorer=match(),
            metrics=[mean()],
            name=TASK,
        )
    if field == "epochs":
        return _task(epochs=2)
    return _task(epochs=Epochs(1, "max"))


_MISMATCHES = ["task name", "scorers", "scorer metrics", "epochs", "epoch reducers"]


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("merge", ["fresh", "incremental", "unchanged", "no-shards"])
@pytest.mark.parametrize(
    "field", _MISMATCHES, ids=[f.replace(" ", "-") for f in _MISMATCHES]
)
def test_a_task_that_differs_from_the_shards_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    merge: str,
    backend: str,
) -> None:
    import shutil

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    if merge == "incremental":
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    _run(shards, "1", sample_id=[4, 5, 6])
    if merge in ("unchanged", "no-shards"):
        merge_eval_log_shards(merged, _task())
    if merge == "no-shards":
        shutil.rmtree(shards)
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match=f"in its {field} "):
        _merge_on(backend, monkeypatch, merged, _mismatched(field))
    assert _files(str(tmp_path)) == before


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("task", [f"custom_task.py@{TASK}", None], ids=["spec", "none"])
def test_a_task_that_is_not_a_task_object_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task: Any, backend: str
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    before = _files(str(tmp_path))
    with monkeypatch.context() as patched:
        _refuse_storage(patched)
        with pytest.raises(TypeError, match="must be the Task the shards ran"):
            _merge_on(backend, monkeypatch, merged, task)
        if backend == "asyncio":
            with pytest.raises(TypeError, match="must be the Task the shards ran"):
                merge_eval_log_shards(merged, task)
    assert _files(str(tmp_path)) == before


def test_merge_refuses_a_different_reducer_and_a_newer_format(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", _task(epochs=Epochs(2, "mean")), sample_id=[1])
    second = _run(shards, "1", _task(epochs=Epochs(2, "max")), sample_id=[2])
    with pytest.raises(ShardSetError, match="epochs reducer"):
        merge_eval_log_shards(
            merged, _task(epochs=Epochs(2, "mean")), allow_incomplete=True
        )
    os.remove(second.location)
    third = _run(shards, "1", _task(epochs=Epochs(2, "mean")), sample_id=[2])
    _edit_header(third.location, lambda h: h.update(version=99))
    with pytest.raises(ShardSetError, match="newer"):
        merge_eval_log_shards(
            merged, _task(epochs=Epochs(2, "mean")), allow_incomplete=True
        )


def test_merge_refuses_a_chunked_sample(tmp_path: Path) -> None:
    from inspect_ai.log._recorders.chunked import convert_eval_logs_to_chunked

    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    converted = tmp_path / "converted"
    convert_eval_logs_to_chunked(log.location, str(converted))
    os.replace(next(converted.glob("*.eval")), log.location)
    with pytest.raises(ShardSetError, match="chunked"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)


def test_merge_accepts_an_id_containing_a_slash(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    task = Task(
        dataset=[Sample(id="group/item", input="q", target=MATCH)],
        scorer=match(),
        name=TASK,
    )
    _run(shards, "0", task)
    result = merge_eval_log_shards(merged, task)
    assert result.log.status == "success"
    assert _members(merged) == ["samples/group/item_epoch_1.json"]


def test_merge_refuses_stray_logs_and_an_ordinary_log(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    stray = f"{shards}/{Path(log.location).name}"
    Path(stray).write_bytes(Path(log.location).read_bytes())
    with pytest.raises(ShardSetError, match="not shard attempts"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    os.remove(stray)

    Path(merged).write_bytes(Path(log.location).read_bytes())
    before = Path(merged).read_bytes()
    with pytest.raises(ShardSetError, match="ordinary log"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert Path(merged).read_bytes() == before


def test_merge_refuses_a_shard_without_a_recorded_selection(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    _edit_header(log.location, lambda h: h["eval"]["dataset"].pop("sample_ids"))
    with pytest.raises(ShardSetError, match="records no sample selection"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)


def test_merge_refuses_a_shard_holding_samples_outside_its_selection(
    tmp_path: Path,
) -> None:
    # what a shard of a task that adds samples while it runs looks like
    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    _edit_header(log.location, lambda h: h["eval"]["dataset"].update(sample_ids=[1]))
    with pytest.raises(ShardSetError, match="outside its recorded selection"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)


def test_merge_refuses_a_new_attempt_with_a_different_selection(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    first = _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    second = _run(shards, "0", sample_id=[1, 2, 3])
    with pytest.raises(ShardSetError) as raised:
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    message = str(raised.value)
    assert Path(first.location).name in message
    assert Path(second.location).name in message
    assert "own shard directory" in message

    os.remove(merged)
    result = merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert _keys(merged) == {("1", 1), ("2", 1), ("3", 1)}
    assert result.log.eval.shards is not None
    assert result.log.eval.shards.ledger[0].log == Path(second.location).name


def test_merge_refuses_a_new_shard_whose_selection_meets_a_carried_record(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    _run(shards, "1", sample_id=[2, 3])
    with pytest.raises(ShardSetError, match="already merged"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)


def test_merge_refuses_a_merged_log_changed_outside_the_merge(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    other = _run(shards, "1", sample_id=[3, 4])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    _remove_member(merged, "samples/1_epoch_1.json")
    # a pass over unchanged shards
    with pytest.raises(ShardSetError, match="changed outside the merge"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    # and one where another shard changed
    _rewrite(other, lambda log: None)
    with pytest.raises(ShardSetError, match="changed outside the merge"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)


def test_overlap_without_shared_records_is_refused_once_a_shard_is_read_again(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(epochs=1)
    first = _run(shards, "0", task, sample_id=[1, 2, 3])
    _as_running(first, keep={(1, 1)})
    merge_eval_log_shards(merged, task, allow_incomplete=True)
    # a new shard selecting 3, which shard 0 selects but does not hold yet
    _run(shards, "1", task, sample_id=[3, 4])
    merge_eval_log_shards(merged, task, allow_incomplete=True)
    # a fresh merge of the same shards refuses at once
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    import shutil

    shutil.copytree(shards, _paths(fresh)[1], copy_function=shutil.copy2)
    with pytest.raises(ShardSetError, match="both select"):
        merge_eval_log_shards(_paths(fresh)[0], task, allow_incomplete=True)
    # and the incremental one does when shard 0 is read again
    _rewrite(first, lambda log: None)
    with pytest.raises(ShardSetError, match="selected by shard 0|both select"):
        merge_eval_log_shards(merged, task, allow_incomplete=True)


def test_incremental_merge_reads_only_changed_shards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merged, shards = _paths(tmp_path)
    growing = _run(shards, "0", sample_id=[1, 2, 3])
    full = read_eval_log(growing.location)
    _as_running(growing, keep={(1, 1), (2, 1)})
    steady = _run(shards, "1", sample_id=[4, 5, 6])
    first = merge_eval_log_shards(merged, _task(), allow_incomplete=True).log
    assert _keys(merged) == {(str(i), 1) for i in (1, 2, 4, 5, 6)}

    opened: list[str] = []
    member_reads: list[tuple[str, str]] = []
    init = AsyncZipReader.__init__
    read_member = AsyncZipReader.read_member_fully

    def spy_init(
        self: AsyncZipReader, fs: Any, filename: str, *a: Any, **k: Any
    ) -> None:
        opened.append(filename)
        init(self, fs, filename, *a, **k)

    open_member = AsyncZipReader.open_member_raw

    async def spy_read(self: AsyncZipReader, member: Any) -> bytes:
        name = member if isinstance(member, str) else member.filename
        member_reads.append((self._filename, name))
        return await read_member(self, member)

    async def spy_open(self: AsyncZipReader, member: Any) -> Any:
        name = member if isinstance(member, str) else member.filename
        member_reads.append((self._filename, name))
        return await open_member(self, member)

    monkeypatch.setattr(AsyncZipReader, "__init__", spy_init)
    monkeypatch.setattr(AsyncZipReader, "read_member_fully", spy_read)
    monkeypatch.setattr(AsyncZipReader, "open_member_raw", spy_open)

    # nothing changed: nothing written, no shard opened
    result = merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert not result.written
    assert opened == [merged]

    # the growing shard gains a sample and edits one it already held
    def grow(log: EvalLog) -> None:
        assert log.samples is not None
        log.status = "started"
        log.samples = [s for s in log.samples if s.id in (1, 2, 3)]
        scores = log.samples[0].scores
        assert scores is not None
        scores["match"].explanation = "edited in the shard"

    grow(full)
    write_eval_log(full, growing.location)
    opened.clear()
    result = merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert result.written
    assert growing.location in opened and steady.location not in opened
    sample_reads = [name for file, name in member_reads if file == growing.location]
    assert {n for n in sample_reads if n.startswith("samples/")} == {
        f"samples/{i}_epoch_1.json" for i in (1, 2, 3)
    }
    assert _keys(merged) == {(str(i), 1) for i in range(1, 7)}
    samples = read_eval_log(merged).samples
    assert samples is not None and samples[0].scores is not None
    assert samples[0].scores["match"].explanation == "edited in the shard"
    header = result.log
    assert (header.eval.eval_id, header.eval.run_id, header.eval.task_id) == (
        first.eval.eval_id,
        first.eval.run_id,
        first.eval.task_id,
    )


def test_a_new_attempt_replaces_its_shards_records(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    retry = _run(shards, "0", sample_id=[1, 2, 3])
    _as_running(retry, keep={(1, 1)})
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert _keys(merged) == {("1", 1)}


def test_vanished_shards_are_refused_and_a_removed_companion_keeps_the_log(
    tmp_path: Path,
) -> None:
    import shutil

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged, _task(), sample_ids=list(range(1, 7)))
    before = Path(merged).read_bytes()
    shutil.rmtree(f"{shards}/1")
    with pytest.raises(ShardSetError, match="vanished.*1"):
        merge_eval_log_shards(merged, _task())
    assert Path(merged).read_bytes() == before

    shutil.rmtree(shards)
    result = merge_eval_log_shards(merged, _task())
    assert not result.written and result.log.status == "success"
    assert Path(merged).read_bytes() == before
    with pytest.raises(ShardSetError, match="can no longer change"):
        merge_eval_log_shards(merged, _task(), sample_ids=[1, 2])
    assert not merge_eval_log_shards(
        merged, _task(), sample_ids=list(range(1, 7))
    ).written


def test_an_added_shard_returns_a_success_log_to_started(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    _run(shards, "1", sample_id=[3, 4])
    first = merge_eval_log_shards(merged, _task(), sample_ids=[1, 2, 3, 4]).log
    assert first.status == "success"
    added = _run(shards, "2", sample_id=[5])
    _as_running(added)
    header = merge_eval_log_shards(
        merged, _task(), sample_ids=[1, 2, 3, 4, 5], allow_incomplete=True
    ).log
    assert header.status == "started"
    assert header.eval.eval_id == first.eval.eval_id
    # the recorded selection is narrower than the shards' when it is not widened
    _rewrite(added, lambda log: setattr(log, "status", "success"))
    with pytest.raises(ShardSelectionError) as raised:
        merge_eval_log_shards(merged, _task(), sample_ids=[1, 2, 3, 4])
    assert raised.value.outside == ["5"]
    assert "narrower" in str(raised.value)
    with pytest.raises(ShardSelectionError) as raised:
        merge_eval_log_shards(merged, _task(), sample_count=3)
    assert raised.value.outside is None


def test_merge_refuses_a_hand_deleted_current_attempt(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    current = _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    os.remove(current.location)
    with pytest.raises(ShardSetError, match="older than the attempt last merged"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)


def _fresh_merge(tmp_path: Path, shards: str, **kwargs: Any) -> tuple[EvalLog, str]:
    """Merge a copy of `shards` (mtimes kept) with no merged log."""
    import shutil

    root = tmp_path / f"fresh{len(list(tmp_path.glob('fresh*')))}"
    root.mkdir()
    fresh_merged, fresh_shards = _paths(root)
    shutil.copytree(shards, fresh_shards, copy_function=shutil.copy2)
    return merge_eval_log_shards(fresh_merged, _task(), **kwargs).log, fresh_merged


def _comparable(header: EvalLog) -> dict[str, Any]:
    return header.model_dump(
        exclude={"eval": {"eval_id", "run_id", "created"}, "location": True}
    )


def test_incremental_merges_equal_fresh_merges(
    tmp_path: Path, failing: set[int]
) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(solver=_flaky())

    def check() -> None:
        incremental = merge_eval_log_shards(merged, task, allow_incomplete=True).log
        fresh, fresh_merged = _fresh_merge(tmp_path, shards, allow_incomplete=True)
        assert _comparable(incremental) == _comparable(fresh)
        assert _members(merged) == _members(fresh_merged)

    _run(shards, "1", task, sample_id=[3, 4])
    _run(shards, "2", task, sample_id=[5, 6])
    check()
    # replace one shard's attempt
    _run(shards, "2", task, sample_id=[5, 6])
    check()
    # add a shard that sorts before the template
    _run(shards, "0", task, sample_id=[1, 2])
    check()
    # shard 0 fails, then 1 fails, then 0 recovers
    failing.add(1)
    _run(shards, "0", task, sample_id=[1, 2])
    check()
    failing.add(3)
    _run(shards, "1", task, sample_id=[3, 4])
    check()
    failing.clear()
    _run(shards, "0", task, sample_id=[1, 2])
    check()
    header = merge_eval_log_shards(merged, task, allow_incomplete=True).log
    assert header.status == "error"
    assert header.error is not None and "failed on 3" in header.error.message


def test_shard_directories_without_an_attempt_are_not_shards(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "1", sample_id=[1, 2, 3])
    _run(shards, "4", sample_id=[4, 5, 6])
    first = merge_eval_log_shards(merged, _task()).log
    for path in [
        f"{shards}/0/scans/scan_id=x/rows.parquet",
        f"{shards}/2/.buffer/x/segment.0.zip",
        f"{shards}/3/x.checkpoints/1",
    ]:
        _touch(Path(path))
    second = merge_eval_log_shards(merged, _task())
    assert not second.written
    assert first.eval.shards is not None
    assert [e.shard for e in first.eval.shards.ledger] == ["1", "4"]
    fresh, _ = _fresh_merge(tmp_path, shards)
    assert _comparable(fresh) == _comparable(second.log)


def test_a_directory_that_gains_an_attempt_becomes_the_template(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _touch(Path(f"{shards}/0/scans/scan_id=x/rows.parquet"))
    _run(shards, "1", sample_id=[3, 4])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    _run(shards, "0", sample_id=[1, 2])
    header = merge_eval_log_shards(merged, _task(), allow_incomplete=True).log
    assert header.eval.shards is not None
    assert header.eval.shards.ledger[0].shard == "0"
    fresh, _ = _fresh_merge(tmp_path, shards, allow_incomplete=True)
    assert _comparable(fresh) == _comparable(header)


@pytest.mark.parametrize(
    "pattern,parsed",
    [
        (None, True),
        ("{task}_{model}_{id}", True),
        ("{task}", False),
        ("{id}_{task}", False),
        ("{model}_{task}", False),
    ],
)
def test_merged_task_id_follows_the_file_name_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pattern: str | None, parsed: bool
) -> None:
    import shortuuid

    from inspect_ai._util.log_layout import eval_log_name

    if pattern is not None:
        monkeypatch.setenv("INSPECT_EVAL_LOG_FILE_PATTERN", pattern)
    name = eval_log_name(
        task=TASK,
        task_id=RUN_ID,
        created="2026-10-16T10:00:00+00:00",
        model="mockllm/model",
    )
    shards = f"{tmp_path}/{name}.shards"
    _run(shards, "0", sample_id=[1, 2])
    merged = f"{tmp_path}/{name}.eval"
    task_id = merge_eval_log_shards(
        merged, _task(), allow_incomplete=True
    ).log.eval.task_id
    assert task_id == (RUN_ID if parsed else shortuuid.uuid(name=name))
    os.remove(merged)
    assert (
        merge_eval_log_shards(merged, _task(), allow_incomplete=True).log.eval.task_id
        == task_id
    )


def test_merged_log_edits_are_kept(tmp_path: Path) -> None:
    from inspect_ai.log import ProvenanceData, TagsEdit, edit_eval_log

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    other = _run(shards, "1", sample_id=[3, 4])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    log = read_eval_log(merged)
    edited = edit_eval_log(
        log, [TagsEdit(tags_add=["kept"])], ProvenanceData(author="test")
    )
    write_eval_log(edited, merged)
    _rewrite(other, lambda log: None)
    header = merge_eval_log_shards(merged, _task(), allow_incomplete=True).log
    assert header.tags == ["kept"]


def test_eval_retry_refuses_an_id_or_count_selected_merged_log(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, _task(), sample_ids=[1, 2, 3], allow_incomplete=True)
    with pytest.raises(ValueError, match=f"{NAME}.eval.*sample ids"):
        eval_retry(merged, log_dir=str(tmp_path / "retry"), display="none")
    merge_eval_log_shards(merged, _task(), sample_count=3, allow_incomplete=True)
    with pytest.raises(ValueError, match="count"):
        eval_retry(merged, log_dir=str(tmp_path / "retry"), display="none")
    assert not (tmp_path / "retry").exists()


@task
def shardy() -> Task:
    return _task()


def test_eval_retry_of_an_unselected_merged_log_runs_the_missing_samples(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", shardy(), sample_id=[1, 2, 3])
    header = merge_eval_log_shards(merged, shardy(), allow_incomplete=True).log
    assert header.status == "started"
    assert header.eval.shards is not None and header.eval.shards.selection == "none"
    prior = {s.id: s.uuid for s in read_eval_log(merged).samples or []}

    retried = eval_retry(merged, log_dir=str(tmp_path / "retry"), display="none")[0]
    assert retried.status == "success"
    assert retried.samples is not None
    assert sorted(s.id for s in retried.samples) == [1, 2, 3, 4, 5, 6]
    assert {s.id: s.uuid for s in retried.samples if s.id in prior} == prior


def _files(root: str) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in Path(root).rglob("*")
        if path.is_file()
    }


def test_a_vanished_shard_under_an_incomplete_log_is_refused(tmp_path: Path) -> None:
    import shutil

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5])
    merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    shutil.rmtree(f"{shards}/1")
    with pytest.raises(ShardSetError, match="vanished"):
        merge_eval_log_shards(merged, _task())
    assert os.path.exists(f"{shards}/0")


def test_a_held_merge_lock_is_reported(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    lock = tmp_path / f"{NAME}.merge.lock"
    lock.write_text('{"pid": 1, "host": "elsewhere"}')
    with pytest.raises(WriteConflictError, match="elsewhere"):
        merge_eval_log_shards(merged, _task(), allow_incomplete=True)
    assert not os.path.exists(merged) and lock.exists()


def _pause_publish(monkeypatch: pytest.MonkeyPatch) -> tuple[anyio.Event, anyio.Event]:
    """Pause the next publish until `release` is set; `reached` is set on arrival."""
    from inspect_ai.log._shards._publish import publish

    reached, release = anyio.Event(), anyio.Event()
    paused = [False]

    async def pausing(*args: Any, **kwargs: Any) -> str | None:
        if not paused[0]:
            paused[0] = True
            reached.set()
            await release.wait()
        return await publish(*args, **kwargs)

    monkeypatch.setattr("inspect_ai.log._shards._api.publish", pausing)
    return reached, release


@pytest.fixture
def two_shards(tmp_path: Path) -> tuple[str, str]:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    return merged, shards


async def test_a_local_merge_overlapping_another_is_refused(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = two_shards
    reached, release = _pause_publish(monkeypatch)
    results: list[Any] = []

    async def first() -> None:
        results.append(await merge_eval_log_shards_async(merged, _task()))

    async with anyio.create_task_group() as tg:
        tg.start_soon(first)
        with anyio.fail_after(30):
            await reached.wait()
        with pytest.raises(WriteConflictError, match="merge.lock"):
            await merge_eval_log_shards_async(merged, _task())
        release.set()
    assert results[0].written
    assert not os.path.exists(merged.replace(".eval", ".merge.lock"))


@pytest.mark.parametrize("form", ["path", "file-uri", "shards-dir"])
async def test_a_merged_log_that_is_a_symbolic_link_is_refused(
    two_shards: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    form: str,
) -> None:
    from inspect_ai._util.file import to_uri
    from inspect_ai.log import merge_eval_log_shards_async

    merged, shards = two_shards
    # another name for the run: its lock would not be the target's
    alias, alias_shards = _paths(tmp_path / "alias")
    os.mkdir(tmp_path / "alias")
    os.symlink(merged, alias)
    os.symlink(shards, alias_shards)
    location = {"path": alias, "file-uri": to_uri(alias), "shards-dir": alias_shards}[
        form
    ]
    reached, release = _pause_publish(monkeypatch)
    results: list[Any] = []

    async def first() -> None:
        results.append(await merge_eval_log_shards_async(merged, _task()))

    async with anyio.create_task_group() as tg:
        tg.start_soon(first)
        with anyio.fail_after(30):
            await reached.wait()
        # the target is not written yet: the link dangles
        before = _files(str(tmp_path))
        with pytest.raises(ShardSetError, match="symbolic link"):
            await merge_eval_log_shards_async(location, _task())
        assert _files(str(tmp_path)) == before
        release.set()
    assert results[0].written
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="symbolic link"):
        await merge_eval_log_shards_async(location, _task())
    assert _files(str(tmp_path)) == before
    assert os.path.islink(alias) and _keys(merged) == {(str(i), 1) for i in range(1, 7)}


async def test_a_cancelled_merge_leaves_no_lock_or_temp_files(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, shards = two_shards
    before = _files(str(tmp_path))
    reached, _ = _pause_publish(monkeypatch)
    async with anyio.create_task_group() as tg:
        tg.start_soon(merge_eval_log_shards_async, merged, _task())
        with anyio.fail_after(30):
            await reached.wait()
        tg.cancel_scope.cancel()
    assert _files(str(tmp_path)) == before


@pytest.mark.parametrize("cancels", [1, 2])
def test_a_cancelled_publish_finishes_before_a_later_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancels: int
) -> None:
    import asyncio
    import shutil
    import threading

    from inspect_ai.log import merge_eval_log_shards_async
    from inspect_ai.log._shards import _publish

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    # a newer attempt of shard 1, held back until the first merge is cancelled
    newer = local_path(_run(shards, "1", sample_id=[4, 5, 6]).location)
    staged = tmp_path / "staged.eval"
    shutil.move(newer, staged)

    copying, release, written = threading.Event(), threading.Event(), []
    replace = _publish._replace_local

    def paused(path: str, source: Any) -> None:
        first = not copying.is_set()
        if first:
            copying.set()
            assert release.wait(30)
        try:
            replace(path, source)
        finally:
            written.append(first)

    monkeypatch.setattr(_publish, "_replace_local", paused)
    waiting = _waiting_for_owned_workers(monkeypatch)

    async def scenario() -> tuple[bool, bytes]:
        merge = asyncio.ensure_future(merge_eval_log_shards_async(merged, _task()))
        assert await asyncio.to_thread(copying.wait, 30)
        merge.cancel()
        if cancels == 2:
            # a second delivery, once the first has reached the wait
            assert await asyncio.to_thread(waiting.wait, 30)
            merge.cancel()
        # the cancelled merge must hold its lock until its worker has written
        done, _ = await asyncio.wait({merge}, timeout=0.5)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await merge
        while not written:
            await asyncio.sleep(0.01)
        if done:
            # it returned while its worker wrote: a later merge could be
            # overwritten by the worker
            return True, b""
        shutil.move(staged, newer)
        assert (await merge_eval_log_shards_async(merged, _task())).written
        return False, Path(merged).read_bytes()

    returned_early, retried = asyncio.run(scenario())
    assert not returned_early, "the cancelled merge returned before its worker"
    # no worker of the cancelled merge is left to overwrite the later merge
    assert written == [True, False]
    assert Path(merged).read_bytes() == retried


def _waiting_for_owned_workers(monkeypatch: pytest.MonkeyPatch) -> Any:
    """An event set when a cancelled `run_owned` starts waiting for its worker."""
    import threading

    from inspect_ai.log._shards import _owned

    waiting = threading.Event()
    finish = _owned._finish

    async def entered(finished: threading.Event) -> None:
        waiting.set()
        await finish(finished)

    monkeypatch.setattr(_owned, "_finish", entered)
    return waiting


async def test_run_owned_returns_the_result_and_raises_the_error() -> None:
    from inspect_ai.log._shards._owned import run_owned

    def fail() -> None:
        raise ValueError("worker failed")

    assert await run_owned(lambda: 42) == 42
    with pytest.raises(ValueError, match="worker failed"):
        await run_owned(fail)


async def test_run_owned_never_runs_work_cancelled_before_it_starts() -> None:
    import threading

    from inspect_ai.log._shards._owned import run_owned

    limiter = anyio.to_thread.current_default_thread_limiter()
    tokens = limiter.total_tokens
    limiter.total_tokens = 1
    try:
        busy, release, ran = threading.Event(), threading.Event(), []

        def block() -> None:
            busy.set()
            release.wait(30)

        async with anyio.create_task_group() as tg:
            tg.start_soon(anyio.to_thread.run_sync, block)
            await anyio.to_thread.run_sync(
                busy.wait, 30, limiter=anyio.CapacityLimiter(1)
            )
            with anyio.CancelScope() as scope:
                scope.cancel()
                # waits for the busy limiter, so the work never starts
                await run_owned(lambda: ran.append(True))
            release.set()
        # the limiter is free again: work left queued would have run by now
        await anyio.to_thread.run_sync(lambda: None)
    finally:
        limiter.total_tokens = tokens
    assert ran == []


async def test_run_owned_finishes_started_work_under_a_cancel_scope() -> None:
    import threading

    from inspect_ai.log._shards._owned import run_owned

    started, release, done, after = threading.Event(), threading.Event(), [], []

    def work() -> None:
        started.set()
        release.wait(30)
        done.append(True)

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as tg:

            async def cancel() -> None:
                await anyio.to_thread.run_sync(started.wait, 30)
                scope.cancel()
                release.set()

            tg.start_soon(cancel)
            await run_owned(work)
            after.append(True)
    assert done == [True]
    # the cancellation is raised once the work has finished
    assert after == [] and scope.cancelled_caught


async def test_run_owned_raises_a_deadline_that_passed_during_the_work() -> None:
    import threading

    from inspect_ai.log._shards._owned import run_owned

    started, release, done = threading.Event(), threading.Event(), []

    def work() -> None:
        started.set()
        release.wait(30)
        done.append(True)

    with pytest.raises(TimeoutError):
        with anyio.fail_after(30) as deadline:
            async with anyio.create_task_group() as tg:

                async def expire() -> None:
                    await anyio.to_thread.run_sync(started.wait, 30)
                    deadline.deadline = anyio.current_time()
                    release.set()

                tg.start_soon(expire)
                await run_owned(work)
    assert done == [True]


def test_run_owned_waits_through_repeated_native_cancellations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import threading

    from inspect_ai.log._shards._owned import run_owned

    waiting = _waiting_for_owned_workers(monkeypatch)
    started, release, done = threading.Event(), threading.Event(), []

    def work() -> str:
        started.set()
        release.wait(30)
        done.append(True)
        return "written"

    async def scenario() -> bool:
        owned = asyncio.ensure_future(run_owned(work))
        assert await asyncio.to_thread(started.wait, 30)
        owned.cancel()
        assert await asyncio.to_thread(waiting.wait, 30)
        returned = False
        for _ in range(3):
            owned.cancel()
            finished, _ = await asyncio.wait({owned}, timeout=0.2)
            returned = returned or bool(finished)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await owned
        return returned

    assert not asyncio.run(scenario()), "returned before its worker finished"
    assert done == [True]


@pytest.mark.parametrize("exists", [False, True], ids=["create", "replace"])
@pytest.mark.parametrize("cancel", ["none", "scope", "native", "native-repeated"])
def test_an_s3_publish_keeps_its_source_until_its_read_finishes(
    monkeypatch: pytest.MonkeyPatch, s3_root: str, exists: bool, cancel: str
) -> None:
    import asyncio
    import tempfile
    import threading

    from inspect_ai.log._shards._publish import publish

    key = f"{s3_root}/{NAME}.eval"
    merged = f"s3://test-bucket/{key}"
    etag = None
    if exists:
        put = boto3.client("s3").put_object(Bucket="test-bucket", Key=key, Body=b"old")
        etag = put["ETag"].strip('"')
    reading, release, read_done = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    read_errors: list[BaseException] = []

    class PausedSource:
        """The merge's temporary file, its first read paused."""

        def __init__(self, file: Any) -> None:
            self._file = file

        def __getattr__(self, name: str) -> Any:
            return getattr(self._file, name)

        def read(self, size: int = -1) -> bytes:
            first = not reading.is_set()
            if first:
                reading.set()
                assert release.wait(30)
            try:
                return cast(bytes, self._file.read(size))
            except BaseException as ex:
                read_errors.append(ex)
                raise
            finally:
                if first:
                    read_done.set()

    waiting = _waiting_for_owned_workers(monkeypatch)
    # whether the source was still being read when the caller closed it
    closed_during_read: list[bool] = []

    async def run_publish() -> str | None:
        async with AsyncFilesystem() as fs:
            with tempfile.TemporaryFile() as file:
                file.write(b"merged")
                source = cast(BinaryIO, PausedSource(file))
                try:
                    return await publish(fs, merged, source, etag=etag, exists=exists)
                finally:
                    closed_during_read.append(not read_done.is_set())

    async def scenario() -> bool:
        if cancel == "scope":
            after: list[bool] = []
            with anyio.CancelScope() as scope:
                async with anyio.create_task_group() as tg:

                    async def interrupt() -> None:
                        await anyio.to_thread.run_sync(reading.wait, 30)
                        scope.cancel()
                        release.set()

                    tg.start_soon(interrupt)
                    await run_publish()
                    after.append(True)
            assert scope.cancelled_caught and after == []
            return False
        task = asyncio.ensure_future(run_publish())
        assert await asyncio.to_thread(reading.wait, 30)
        if cancel == "none":
            release.set()
            assert await task
            return False
        task.cancel()
        if cancel == "native-repeated":
            assert await asyncio.to_thread(waiting.wait, 30)
            for _ in range(3):
                task.cancel()
        # the cancelled publish must keep its source until the read finishes
        done, _ = await asyncio.wait({task}, timeout=0.5)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(read_done.wait, 30)
        return bool(done)

    assert not asyncio.run(scenario()), "the publish returned before its read"
    assert closed_during_read == [False] and read_errors == []
    if cancel == "none":
        body = boto3.client("s3").get_object(Bucket="test-bucket", Key=key)["Body"]
        assert body.read() == b"merged"


async def test_owned_reads_refuse_a_read_after_release() -> None:
    import io

    from inspect_ai.log._shards._owned import OwnedReads

    reads = OwnedReads(io.BytesIO(b"merged"))
    assert reads.read(3) == b"mer"
    await reads.release()
    with pytest.raises(ValueError, match="released"):
        reads.read()


def test_merge_thread_calls_go_through_run_owned() -> None:
    import re

    from inspect_ai.log import _shards

    # direct thread dispatch outside the helper that owns it
    dispatch = re.compile(
        r"to_thread|run_sync|run_in_executor|threading\.Thread|ThreadPoolExecutor"
    )
    found = [
        f"{path.name}:{number}"
        for path in sorted(Path(_shards.__file__).parent.glob("*.py"))
        if path.name != "_owned.py"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if dispatch.search(line)
    ]
    assert found == []


def _crc_failures(
    monkeypatch: pytest.MonkeyPatch,
    shards: str,
    failures: int,
    error: Exception,
    member: str = "samples/",
) -> list[str]:
    """Fail the first `failures` reads of `member` from a shard with `error`.

    Whole reads (headers) and streamed reads (samples) are both counted.
    """
    calls: list[str] = []

    def failing(read: Callable[..., Any]) -> Callable[..., Any]:
        async def call(self: AsyncZipReader, member_: Any) -> Any:
            name = member_ if isinstance(member_, str) else member_.filename
            if self._filename.startswith(shards) and name.startswith(member):
                calls.append(name)
                if len(calls) <= failures:
                    raise error
            return await read(self, member_)

        return call

    for method in ["read_member_fully", "open_member_raw"]:
        monkeypatch.setattr(
            AsyncZipReader, method, failing(getattr(AsyncZipReader, method))
        )
    return calls


@pytest.mark.parametrize(
    "member,error",
    [
        ("header.json", ZipCrcError("torn")),
        ("samples/", _client_error("InvalidRange")),
        ("samples/", _client_error("AccessDenied")),
    ],
)
def test_a_failed_shard_read_fails_the_merge_with_its_error(
    two_shards: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    member: str,
    error: Exception,
) -> None:
    merged, shards = two_shards
    calls = _crc_failures(monkeypatch, shards, 100, error, member)
    with pytest.raises(type(error)) as raised:
        merge_eval_log_shards(merged, _task())
    assert raised.value is error
    # header reads of the two shards run concurrently; sample reads one by one
    assert 1 <= len(calls) <= (2 if member == "header.json" else 1)
    assert not os.path.exists(merged)


def test_a_shard_sample_that_does_not_validate_fails_at_once(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    merged, shards = two_shards
    shard = str(next(Path(f"{shards}/0").glob("*.eval")))
    path = local_path(shard)
    with zipfile.ZipFile(path) as src:
        members = [(i, src.read(i)) for i in src.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in members:
            if info.filename == "samples/1_epoch_1.json":
                data = json.dumps({"id": 1, "epoch": "not an int"}).encode()
            dst.writestr(info.filename, data)
    calls = _crc_failures(monkeypatch, shards, 0, ZipCrcError("unused"))
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        merge_eval_log_shards(merged, _task())
    assert len(calls) == 1
    assert not os.path.exists(merged)


_UNSUPPORTED = "supports local paths, file:// URIs and s3:// URLs only"

_UNSUPPORTED_ROOTS = [
    "az://container/logs",
    "abfs://container@account.dfs.core.windows.net/logs",
    "abfss://container@account.dfs.core.windows.net/logs",
    "gs://bucket/logs",
    "webhdfs://user@namenode:9870/logs",
    "memory://{uuid}/logs",
    "hdfs://namenode/logs",
    "sftp://host/logs",
    # fsspec reads data: as a protocol without slashes
    "data:text/plain,worker",
    # fsspec strips these prefixes; native path operations keep them
    "file:/tmp/logs",
    "local:/tmp/logs",
    "simplecache::s3://test-bucket/logs",
    "file:///tmp/cache::memory://bucket/logs",
    "s3://test-bucket/cache::memory://bucket/logs",
    # decodes to file:///tmp/cache::memory://bucket/logs
    "file:///tmp/cache%3A%3Amemory%3A//bucket/logs",
]


def _refuse_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on any fsspec filesystem construction or S3 client creation."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("storage was accessed")

    monkeypatch.setattr("fsspec.core.url_to_fs", refuse)
    monkeypatch.setattr("fsspec.filesystem", refuse)
    monkeypatch.setattr(AsyncFilesystem, "s3_client", refuse)
    monkeypatch.setattr(AsyncFilesystem, "s3_client_async", refuse)


def _memory_objects(root: str) -> dict[str, bytes]:
    from inspect_ai._util.file import filesystem

    memory = filesystem(root).fs
    prefix = memory._strip_protocol(root)
    return {
        path: data.getvalue()
        for path, data in memory.store.items()
        if path.startswith(prefix)
    }


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize(
    "root",
    _UNSUPPORTED_ROOTS,
    ids=[r.split(":")[0] for r in _UNSUPPORTED_ROOTS[:-3]]
    + ["file-chain", "s3-chain", "encoded-file-chain"],
)
def test_a_merge_of_unsupported_storage_is_refused_before_any_io(
    monkeypatch: pytest.MonkeyPatch, root: str, backend: str
) -> None:
    import shortuuid

    from inspect_ai._util.file import filesystem

    root = root.format(uuid=shortuuid.uuid())
    merged, shards = _paths(root)
    before: dict[str, bytes] = {}
    if root.startswith("memory://"):
        memory = filesystem(root).fs
        for name in ["0/a.eval", "1/b.eval", "1/b.checkpoints/1/data"]:
            memory.pipe(f"{shards}/{name}", b"x")
        memory.pipe(merged, b"x")
        before = _memory_objects(root)
    with monkeypatch.context() as patched:
        _refuse_storage(patched)
        for location in (merged, shards, f"{root}.eval"):
            with pytest.raises(ValueError, match=_UNSUPPORTED):
                _merge_on(backend, monkeypatch, location, _task())
            if backend == "asyncio":
                with pytest.raises(ValueError, match=_UNSUPPORTED):
                    merge_eval_log_shards(location, _task())
    if root.startswith("memory://"):
        assert before and _memory_objects(root) == before


@pytest.mark.parametrize(
    "location,used",
    [
        ("/tmp/logs/run.eval", "/tmp/logs/run.eval"),
        ("logs/run.eval", "logs/run.eval"),
        ("file:///tmp/logs/run.eval", "/tmp/logs/run.eval"),
        ("s3://test-bucket/logs/run.eval", "s3://test-bucket/logs/run.eval"),
        ("C:\\logs\\run.eval", "C:\\logs\\run.eval"),
        ("C:/logs/run.eval", "C:/logs/run.eval"),
        (
            "logs/2026-09-30T10:30:00+00:00_task.eval",
            "logs/2026-09-30T10:30:00+00:00_task.eval",
        ),
        ("./run:1.eval", "./run:1.eval"),
        ("/tmp/logs:a/run:1.eval", "/tmp/logs:a/run:1.eval"),
        # decoded once: encoded spaces, a literal percent sequence, a colon
        ("file:///tmp/my%20logs/run.eval", "/tmp/my logs/run.eval"),
        ("file:///tmp/run%252D1.eval", "/tmp/run%2D1.eval"),
        ("/tmp/run%2D1.eval", "/tmp/run%2D1.eval"),
        ("file:///tmp/run%3A1.eval", "/tmp/run:1.eval"),
    ],
)
def test_supported_locations_are_accepted(location: str, used: str) -> None:
    from inspect_ai.log._shards._publish import supported_location

    # a local path is made absolute against the working directory
    if not used.startswith("s3://"):
        used = os.path.join(os.getcwd(), used)
    assert supported_location(location) == used


@pytest.mark.parametrize(
    "location",
    ["run:1.eval", "file:/tmp/run.eval", "local:/tmp/run.eval", "C:run.eval"],
)
def test_a_relative_path_with_a_name_prefix_is_refused(location: str) -> None:
    from inspect_ai.log._shards._publish import supported_location

    with pytest.raises(ValueError, match=_UNSUPPORTED):
        supported_location(location)


def _s3_keys(prefix: str) -> list[str]:
    client = boto3.client("s3")
    pages = client.get_paginator("list_objects_v2").paginate(
        Bucket="test-bucket", Prefix=prefix
    )
    return sorted(obj["Key"] for page in pages for obj in page.get("Contents", []))


@pytest.fixture
def s3_root(mock_s3: None) -> str:
    """A prefix of its own: the moto bucket outlives each test."""
    import shortuuid

    return f"logs-{shortuuid.uuid()}"


@pytest.fixture
def s3_shards(s3_root: str) -> tuple[str, str]:
    merged, shards = _paths(f"s3://test-bucket/{s3_root}")
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    return merged, shards


def test_merge_on_s3(s3_shards: tuple[str, str], s3_root: str) -> None:
    merged, shards = s3_shards
    first = merge_eval_log_shards(merged, _task())
    assert first.written and first.log.status == "success"
    assert first.log.eval.shards is not None
    assert all(e.etag for e in first.log.eval.shards.ledger)
    assert not merge_eval_log_shards(merged, _task()).written

    def change(k: str) -> None:
        # rewrite the shard's attempt in place: a re-run within the same
        # second could tie with it in attempt order
        [key] = [
            key
            for key in _s3_keys(f"{s3_root}/{NAME}.shards/{k}/")
            if key.endswith(".eval")
        ]
        log = read_eval_log(f"s3://test-bucket/{key}")
        assert log.samples is not None
        for sample in log.samples:
            sample.metadata["changed"] = True
        write_eval_log(log, f"s3://test-bucket/{key}")

    # a changed shard is merged again, carrying the other
    change("1")
    second = merge_eval_log_shards(merged, _task())
    assert second.written and second.log.eval.eval_id == first.log.eval.eval_id
    log = read_eval_log(merged)
    assert sorted(s.id for s in log.samples or []) == [1, 2, 3, 4, 5, 6]

    # nothing changed since: nothing is written
    assert not merge_eval_log_shards(merged, _task()).written


async def test_concurrent_first_merges_on_s3_publish_once(
    s3_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    reached, release = _pause_publish(monkeypatch)
    failures: list[BaseException] = []

    async def first() -> None:
        try:
            await merge_eval_log_shards_async(merged, _task())
        except WriteConflictError as ex:
            failures.append(ex)

    async with anyio.create_task_group() as tg:
        tg.start_soon(first)
        with anyio.fail_after(30):
            await reached.wait()
        winner = await merge_eval_log_shards_async(merged, _task())
        release.set()
    assert len(failures) == 1
    header = await read_eval_log_async(merged, header_only=True)
    assert header.eval.eval_id == winner.log.eval.eval_id


async def test_an_older_snapshot_published_after_a_newer_one_is_refused_on_s3(
    s3_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, shards = s3_shards
    await merge_eval_log_shards_async(merged, _task(), sample_ids=[1, 2, 3, 4, 5, 6])
    reached, release = _pause_publish(monkeypatch)
    failures: list[BaseException] = []

    async def stale() -> None:
        try:
            await merge_eval_log_shards_async(merged, _task(), sample_count=6)
        except WriteConflictError as ex:
            failures.append(ex)

    async with anyio.create_task_group() as tg:
        tg.start_soon(stale)
        with anyio.fail_after(30):
            await reached.wait()
        await merge_eval_log_shards_async(
            merged, _task(), sample_ids=[6, 5, 4, 3, 2, 1, 7], allow_incomplete=True
        )
        release.set()
    assert len(failures) == 1
    header = await read_eval_log_async(merged, header_only=True)
    assert header.eval.shards is not None and header.eval.shards.selection == "ids"
    # a re-run merges cleanly
    result = await merge_eval_log_shards_async(merged, _task(), sample_count=6)
    assert result.written and result.log.status == "success"


async def test_a_merge_whose_log_was_removed_meanwhile_is_refused_on_s3(
    s3_shards: tuple[str, str], s3_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    await merge_eval_log_shards_async(merged, _task())
    reached, release = _pause_publish(monkeypatch)
    failures: list[BaseException] = []

    async def merge() -> None:
        try:
            await merge_eval_log_shards_async(merged, _task(), sample_count=6)
        except WriteConflictError as ex:
            failures.append(ex)

    async with anyio.create_task_group() as tg:
        tg.start_soon(merge)
        with anyio.fail_after(30):
            await reached.wait()
        try:
            boto3.client("s3").delete_object(
                Bucket="test-bucket", Key=f"{s3_root}/{NAME}.eval"
            )
        finally:
            release.set()
    assert len(failures) == 1
    assert f"{s3_root}/{NAME}.eval" not in _s3_keys(f"{s3_root}/")


def test_merge_refuses_a_recovered_shards_directory_name(tmp_path: Path) -> None:
    import shutil

    _, shards = _paths(tmp_path)
    neighbour = _run(shards, "0", sample_id=[1, 2, 3])
    recovered = f"{tmp_path}/{NAME}-recovered.shards"
    shutil.copytree(shards, recovered)
    before = _files(str(tmp_path))
    with pytest.raises(ValueError, match=f"{NAME}.shards"):
        merge_eval_log_shards(recovered, _task())
    assert _files(str(tmp_path)) == before
    assert os.path.exists(neighbour.location)


# characters a file:// URI encodes or a URL parser reads specially
_RESERVED = "sp ace%20d#ir?x"


def test_merge_of_a_local_file_uri_with_reserved_characters(tmp_path: Path) -> None:
    from inspect_ai._util.file import to_uri

    root = tmp_path / _RESERVED
    merged, shards = _paths(root)
    _run(shards, "0", sample_id=[1, 2, 3])
    uri = to_uri(merged)
    result = merge_eval_log_shards(uri, _task(), allow_incomplete=True)
    assert result.written and result.log.location == uri
    assert _keys(merged) == {("1", 1), ("2", 1), ("3", 1)}
    _run(shards, "1", sample_id=[4, 5, 6])
    result = merge_eval_log_shards(to_uri(shards), _task())
    assert result.written
    assert read_eval_log(merged, header_only=True).status == "success"


def _merge_parts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    write: str,
    run: Callable[[str, str, list[int]], EvalLog],
    task: Task,
    first: Task | None = None,
) -> Callable[[], ShardMergeResult]:
    """Run shard 0, merge it first when `write` is incremental, run shard 1.

    Returns the final merge, for the test to run (with `first`, or `task`,
    for the first merge).
    """
    merged, shards = _paths(tmp_path)
    run(shards, "0", [1, 2, 3])
    if write == "incremental":
        _merge_on(backend, monkeypatch, merged, first or task, allow_incomplete=True)
    run(shards, "1", [4, 5, 6])
    return lambda: _merge_on(backend, monkeypatch, merged, task)


def _fresh_native(tmp_path: Path, task: Task, **kwargs: Any) -> EvalLog:
    return read_eval_log(
        eval(
            task,
            model="mockllm/model",
            log_dir=str(tmp_path / "native"),
            display="none",
            **kwargs,
        )[0].location
    )


_REDUCERS: dict[str, list[str] | None] = {"implicit": None, "disabled": []}


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("write", ["fresh", "incremental"])
@pytest.mark.parametrize("given", list(_REDUCERS))
@pytest.mark.parametrize("ran", list(_REDUCERS))
def test_an_implicit_reducer_and_disabled_reduction_do_not_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ran: str,
    given: str,
    write: str,
    backend: str,
) -> None:
    def task(state: str) -> Task:
        return _graded_task(Epochs(2, _REDUCERS[state]))

    merge = _merge_parts(
        tmp_path,
        monkeypatch,
        backend,
        write,
        lambda shards, k, ids: _run(shards, k, task(ran), sample_id=ids),
        task(given),
        first=task(ran),
    )
    if ran != given:
        before = _files(str(tmp_path))
        with pytest.raises(ShardSetError, match="in its epoch reducers "):
            merge()
        assert _files(str(tmp_path)) == before
        return
    merged = read_eval_log(merge().log.location)
    native = _fresh_native(tmp_path, task(ran))
    assert merged.results is not None and native.results is not None
    assert _metric_values(merged) == _metric_values(native)
    assert [s.scored_samples for s in merged.results.scores] == [
        s.scored_samples for s in native.results.scores
    ]
    assert merged.reductions == native.reductions
    assert (merged.reductions == []) == (ran == "disabled")


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("write", ["fresh", "incremental"])
@pytest.mark.parametrize("recipe", ["kept", "bare"])
@pytest.mark.parametrize("reducer", ["max", "at_least", "disabled"])
def test_an_epochs_override_merges_with_the_task_s_reducer_kept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reducer: str,
    recipe: str,
    write: str,
    backend: str,
) -> None:
    reducers: dict[str, Any] = {
        "max": "max",
        "at_least": at_least(1, value=0.5),
        "disabled": [],
    }
    task = _graded_task(Epochs(2, reducers[reducer]))
    # the workers ran with eval(epochs=3), which keeps the task's reducer
    merging = task_with(
        _graded_task(Epochs(2, reducers[reducer])),
        epochs=Epochs(3, task.epochs_reducer) if recipe == "kept" else 3,
    )
    merge = _merge_parts(
        tmp_path,
        monkeypatch,
        backend,
        write,
        lambda shards, k, ids: _run(shards, k, task, sample_id=ids, epochs=3),
        merging,
        first=task_with(
            _graded_task(Epochs(2, reducers[reducer])),
            epochs=Epochs(3, task.epochs_reducer),
        ),
    )
    if recipe == "bare":
        # task_with(task, epochs=3) resets the reducer to the default
        before = _files(str(tmp_path))
        with pytest.raises(ShardSetError, match="in its epoch reducers "):
            merge()
        assert _files(str(tmp_path)) == before
        return
    merged = read_eval_log(merge().log.location)
    native = _fresh_native(tmp_path, task, epochs=3)
    assert merged.eval.config.epochs == native.eval.config.epochs == 3
    assert _metric_values(merged) == _metric_values(native)
    assert merged.reductions == native.reductions


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("write", ["fresh", "incremental"])
def test_an_unscored_run_merges_to_a_native_unscored_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: str, backend: str
) -> None:
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    merge = _merge_parts(
        tmp_path,
        monkeypatch,
        backend,
        write,
        lambda shards, k, ids: _run(shards, k, task, sample_id=ids, score=False),
        task,
    )
    result = merge()
    assert result.log.status == "success"
    merged = read_eval_log(result.log.location)
    native = _fresh_native(tmp_path, task, score=False)
    assert merged.results is not None and native.results is not None
    assert merged.results.scores == native.results.scores == []
    assert (merged.results.total_samples, merged.results.completed_samples) == (
        native.results.total_samples,
        native.results.completed_samples,
    )
    assert merged.reductions is None and native.reductions is None
    # the declared scorers are kept, as a native unscored log keeps them
    assert merged.eval.scorers == native.eval.scorers


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("write", ["fresh", "incremental"])
@pytest.mark.parametrize("first", ["scored", "unscored"])
def test_shards_that_ran_with_and_without_scoring_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    write: str,
    backend: str,
) -> None:
    def run(shards: str, k: str, ids: list[int]) -> EvalLog:
        scored = (k == "0") == (first == "scored")
        return _run(shards, k, sample_id=ids, score=scored)

    merge = _merge_parts(tmp_path, monkeypatch, backend, write, run, _task())
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="did not run with the same scoring"):
        merge()
    assert _files(str(tmp_path)) == before


@contextlib.contextmanager
def _fake_hf_loaders(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """The Hugging Face provider on `test_hf.py`'s fake dependencies.

    Yields the keyword arguments of every `from_pretrained` call.
    """
    import importlib.util
    from unittest.mock import MagicMock

    spec = importlib.util.spec_from_file_location(
        "shards_test_hf", Path(__file__).parents[1] / "model/providers/test_hf.py"
    )
    assert spec is not None and spec.loader is not None
    test_hf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(test_hf)
    calls: list[Any] = []

    class Loader:
        @staticmethod
        def from_pretrained(*args: Any, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return MagicMock()

    with test_hf._hf_provider_with_fake_deps(
        monkeypatch, AutoModelForCausalLM=Loader, AutoTokenizer=Loader
    ):
        yield calls


_TRUSTED = {"trust_remote_code": True}
_HF = "hf/org/remote-code-model"
# what the shard headers record in place of the mockllm model they ran
_RECORDED: dict[str, dict[str, Any]] = {
    "openai": {
        "model": "openai/gpt-4o",
        "model_roles": {
            "grader": {"model": "openai/gpt-4o-mini"},
            "panel": [{"model": "openai/gpt-4o"}, {"model": "openai/gpt-4o-mini"}],
        },
    },
    "hf-model-args": {"model": _HF, "model_args": _TRUSTED},
    "hf-role-args": {
        "model_roles": {
            "grader": {"model": _HF, "args": _TRUSTED},
            "panel": [{"model": _HF, "args": _TRUSTED}],
        }
    },
}


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("write", ["fresh", "incremental"])
@pytest.mark.parametrize("recorded", list(_RECORDED))
def test_a_merge_builds_no_model_from_the_shard_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recorded: str,
    write: str,
    backend: str,
) -> None:
    from inspect_ai.model import ModelAPI

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    merged, shards = _paths(tmp_path)
    constructed: list[str] = []
    construct = ModelAPI.__init__

    def spy(self: ModelAPI, model_name: str, *args: Any, **kwargs: Any) -> None:
        constructed.append(model_name)
        construct(self, model_name, *args, **kwargs)

    def shard(k: str, ids: list[int]) -> None:
        log = _run(shards, k, sample_id=ids)
        _edit_header(log.location, lambda h: h["eval"].update(_RECORDED[recorded]))

    def merge(**kwargs: Any) -> ShardMergeResult:
        with monkeypatch.context() as watched, _fake_hf_loaders(watched) as loaded:
            watched.setattr(ModelAPI, "__init__", spy)
            # no memoized model from another test stands in for a construction
            watched.setattr("inspect_ai.model._model._models", {})
            result = _merge_on(backend, watched, merged, _task(), **kwargs)
        assert constructed == [] and loaded == []
        return result

    shard("0", [1, 2, 3])
    if write == "incremental":
        merge(allow_incomplete=True)
    shard("1", [4, 5, 6])
    result = merge()
    assert result.written and result.log.status == "success"
    native = _fresh_native(tmp_path, _task())
    assert _metric_values(result.log) == _metric_values(native)


@metric
def shard_caller_model() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return 1.0 if get_model().name == "ambient" else 0.0

    return compute


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("write", ["fresh", "incremental"])
def test_a_metric_that_needs_a_model_uses_the_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: str, backend: str
) -> None:
    from contextvars import copy_context

    from inspect_ai.model._model import active_model_context_var

    task = Task(
        dataset=_task().dataset,
        solver=generate(),
        scorer=match(),
        metrics=[shard_caller_model()],
        name=TASK,
    )

    def merge_without_a_model(merge: Callable[[], ShardMergeResult]) -> Any:
        def run() -> ShardMergeResult:
            active_model_context_var.set(None)
            return merge()

        return copy_context().run(run)

    merged, shards = _paths(tmp_path)
    monkeypatch.delenv("INSPECT_EVAL_MODEL", raising=False)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    if write == "incremental":
        # the metric runs with the caller's model, not the shards' mockllm/model
        with monkeypatch.context() as caller:
            caller.setenv("INSPECT_EVAL_MODEL", "mockllm/ambient")
            result = merge_without_a_model(
                lambda: _merge_on(
                    backend, monkeypatch, merged, task, allow_incomplete=True
                )
            )
        assert _metric_values(result.log) == {("match", "shard_caller_model"): 1.0}
    _run(shards, "1", task, sample_id=[4, 5, 6])
    before = _files(str(tmp_path))
    with pytest.raises(ValueError, match="No model specified"):
        merge_without_a_model(lambda: _merge_on(backend, monkeypatch, merged, task))
    assert _files(str(tmp_path)) == before


def test_score_names_from_the_log_never_load_files(tmp_path: Path) -> None:
    evil = tmp_path / "evil.py"
    marker = tmp_path / "imported"
    evil.write_text(f"open({str(marker)!r}, 'w').close()\n")
    # a file-qualified scorer spec, and an existing file without '@'
    keys = [f"{evil}@evil_scorer", str(evil)]

    @solver
    def file_named_scores() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            state.scores = {key: Score(value=1) for key in keys}
            return state

        return solve

    task = _task(solver=file_named_scores())
    merged, shards = _paths(tmp_path / "logs")
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    # the shard runs themselves resolve these names as eval always has
    marker.unlink(missing_ok=True)

    with pytest.raises(ShardSetError, match="cannot merge solver-set scores"):
        merge_eval_log_shards(merged, task)
    assert not marker.exists()


@pytest.mark.parametrize("suffix", [".shards", ".eval"])
def test_merge_refuses_an_encoded_recovered_name(tmp_path: Path, suffix: str) -> None:
    import shutil

    from inspect_ai._util.file import to_uri

    _, shards = _paths(tmp_path)
    neighbour = _run(shards, "0", sample_id=[1, 2, 3])
    recovered = f"{tmp_path}/{NAME}-recovered.shards"
    shutil.copytree(shards, recovered)
    before = _files(str(tmp_path))
    encoded = to_uri(f"{tmp_path}/{NAME}") + "%2Drecovered" + suffix
    with pytest.raises(ValueError, match="recovered"):
        merge_eval_log_shards(encoded, _task())
    assert _files(str(tmp_path)) == before
    assert os.path.exists(neighbour.location)


def test_merge_paths_keep_literal_percent_signs() -> None:
    from inspect_ai.log._shards._api import merge_paths

    paths = merge_paths("/logs/run%2Drecovered.eval")
    assert paths.merged == "/logs/run%2Drecovered.eval"
    assert paths.shards_dir == "/logs/run%2Drecovered.shards"
    s3 = merge_paths("s3://bucket/run%2Drecovered.shards/")
    assert s3.location == "s3://bucket/run%2Drecovered.eval"
    with pytest.raises(ValueError, match="recovered"):
        merge_paths("file:///logs/run%2Drecovered.eval")


_LOCAL_FORMS = ["tilde", "relative", "dot", "absolute", "file-uri"]


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize("state", ["fresh", "ordinary"])
@pytest.mark.parametrize("form", _LOCAL_FORMS)
def test_a_local_location_is_one_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    form: str,
    state: str,
    backend: str,
) -> None:
    import shutil

    from inspect_ai._util.file import to_uri

    cwd, home = tmp_path / "cwd", tmp_path / "home"
    # `~` here is a literal directory name, as native file operations read it
    directory = cwd / ("~" if form == "tilde" else "") / "logs"
    merged, shards = _paths(directory)
    first = _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    home.mkdir()
    if state == "ordinary":
        Path(merged).write_bytes(Path(first.location).read_bytes())
        # the same shards where an expanded `~` would read them, and no merged log
        shutil.copytree(directory, home / "logs")
        os.remove(home / "logs" / f"{NAME}.eval")
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: f"{home}{path[1:]}" if path.startswith("~") else path,
    )
    location = {
        "tilde": f"~/logs/{NAME}.eval",
        "relative": f"logs/{NAME}.eval",
        "dot": f"./logs/{NAME}.eval",
        "absolute": merged,
        "file-uri": to_uri(merged),
    }[form]
    before, home_before = _files(str(directory)), _files(str(home))
    if state == "ordinary":
        with pytest.raises(ShardSetError, match="ordinary log"):
            _merge_on(backend, monkeypatch, location, _task())
        assert _files(str(directory)) == before
    else:
        assert _merge_on(backend, monkeypatch, location, _task()).written
        assert _keys(merged) == {(str(i), 1) for i in range(1, 7)}
    assert _files(str(home)) == home_before


def _s3_copy(source: str, target: str) -> None:
    """Copy every key under the prefix `source` to the same key under `target`."""
    client = boto3.client("s3")
    for key in _s3_keys(source):
        client.copy_object(
            Bucket="test-bucket",
            Key=target + key[len(source) :],
            CopySource={"Bucket": "test-bucket", "Key": key},
        )


def _s3_objects(prefix: str) -> dict[str, bytes]:
    client = boto3.client("s3")
    return {
        key: client.get_object(Bucket="test-bucket", Key=key)["Body"].read()
        for key in _s3_keys(prefix)
    }


@pytest.mark.parametrize("delete", [False, True], ids=["merge", "delete"])
@pytest.mark.parametrize(
    "target",
    [
        "{root}/{name}#tag.eval",
        "{root}/{name}#tag.shards",
        "{root}/dir#tag/{name}.eval",
        "{root}/{name}?tag.eval",
        "/{root}/{name}.eval",
    ],
    ids=["name", "shards", "parent", "query", "leading-slash"],
)
def test_s3_locations_s3_would_read_as_another_key_are_refused(
    s3_shards: tuple[str, str], s3_root: str, target: str, delete: bool
) -> None:
    from inspect_ai._util.asyncfiles import s3_bucket_and_key

    location = target.format(root=s3_root, name=NAME)
    companion = location.removesuffix(".eval").removesuffix(".shards") + ".shards"
    _s3_copy(f"{s3_root}/{NAME}.shards/", f"{companion}/")
    # what S3 would read instead (for the leading slash, the ordinary
    # companion): another shard set, with an unrelated object that must survive
    _, read_as = s3_bucket_and_key(f"s3://test-bucket/{companion}")
    if read_as != f"{s3_root}/{NAME}.shards":
        _s3_copy(f"{s3_root}/{NAME}.shards/", f"{read_as}/")
    boto3.client("s3").put_object(
        Bucket="test-bucket", Key=f"{read_as}/keep.txt", Body=b"keep"
    )
    roots = [f"{s3_root}/", f"/{s3_root}/"]
    before = [_s3_objects(root) for root in roots]
    with pytest.raises(ValueError, match="S3 would read it as"):
        merge_eval_log_shards(f"s3://test-bucket/{location}", _task())
    assert [_s3_objects(root) for root in roots] == before


def test_a_literal_percent_sign_in_an_s3_name_merges(
    s3_shards: tuple[str, str], s3_root: str
) -> None:
    _s3_copy(f"{s3_root}/{NAME}.shards/", f"{s3_root}/{NAME}%23tag.shards/")
    merged = f"s3://test-bucket/{s3_root}/{NAME}%23tag.eval"
    result = merge_eval_log_shards(merged, _task())
    assert result.written
    assert result.log.status == "success"
    assert f"{s3_root}/{NAME}%23tag.eval" in _s3_keys(f"{s3_root}/")


@pytest.mark.parametrize(
    "child", ["0#tag", "0/worker#tag.eval"], ids=["dir", "attempt"]
)
async def test_s3_shard_paths_s3_would_read_as_another_key_are_refused(
    s3_shards: tuple[str, str], s3_root: str, child: str
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    shards = f"{s3_root}/{NAME}.shards"
    [attempt] = [k for k in _s3_keys(f"{shards}/1/") if k.endswith(".eval")]
    client = boto3.client("s3")
    if child == "0#tag":
        # shard 0 under a directory S3 would list as `0`
        _s3_copy(f"{shards}/0/", f"{shards}/0#tag/")
    else:
        # an attempt S3 would read as the non-log object `worker`, which holds
        # another shard's samples
        source = {"Bucket": "test-bucket", "Key": attempt}
        client.copy_object(
            Bucket="test-bucket", Key=f"{shards}/{child}", CopySource=source
        )
        client.copy_object(
            Bucket="test-bucket", Key=f"{shards}/0/worker", CopySource=source
        )
    before = _s3_objects(f"{s3_root}/")
    with pytest.raises(ShardSetError, match="S3 would read it as"):
        await merge_eval_log_shards_async(merged, _task())
    assert _s3_objects(f"{s3_root}/") == before


_NOT_DIRECTLY = "is not a file or directory directly in it"


@pytest.mark.parametrize("merge", ["unchanged", "fresh"])
@pytest.mark.parametrize(
    "hidden,match",
    [
        ("1#tag/worker.eval", "S3 would read it as"),
        ("1?tag/worker.eval", "S3 would read it as"),
        ("/worker.eval", _NOT_DIRECTLY),
        ("//worker.eval", _NOT_DIRECTLY),
        ("0//worker.eval", _NOT_DIRECTLY),
    ],
    ids=["fragment", "query", "root-empty", "root-empty-twice", "shard-empty"],
)
async def test_an_s3_worker_the_listing_would_hide_is_refused(
    s3_shards: tuple[str, str], s3_root: str, hidden: str, match: str, merge: str
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    shards = f"{s3_root}/{NAME}.shards"
    [attempt] = [k for k in _s3_keys(f"{shards}/1/") if k.endswith(".eval")]
    held = f"{s3_root}/held/worker.eval"
    client = boto3.client("s3")
    client.copy_object(
        Bucket="test-bucket",
        Key=held,
        CopySource={"Bucket": "test-bucket", "Key": attempt},
    )
    client.delete_object(Bucket="test-bucket", Key=attempt)
    if merge == "unchanged":
        result = await merge_eval_log_shards_async(
            merged, _task(), sample_ids=[1, 2, 3]
        )
        assert result.written and result.log.status == "success"
    # shard 1's unmerged worker, under a key the listing would drop: a
    # directory S3 would list as the absent `1`, or an empty path component
    # that lists as the directory listed
    client.copy_object(
        Bucket="test-bucket",
        Key=f"{shards}/{hidden}",
        CopySource={"Bucket": "test-bucket", "Key": held},
    )
    client.delete_object(Bucket="test-bucket", Key=held)
    before = _s3_objects(f"{s3_root}/")
    with pytest.raises(ShardSetError, match=match):
        await merge_eval_log_shards_async(merged, _task(), sample_ids=[1, 2, 3])
    assert _s3_objects(f"{s3_root}/") == before


@pytest.mark.parametrize("state", ["fresh", "existing"])
def test_attempts_that_tie_as_latest_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    merged, shards = _paths(tmp_path)
    first = _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    directory = Path(local_path(first.location)).parent
    older = directory / f"{T1}_{TASK}_a.eval"
    os.rename(local_path(first.location), older)
    if state == "existing":
        assert merge_eval_log_shards(merged, _task()).written
    second = _run(shards, "0", sample_id=[1, 2, 3])
    newer = directory / f"{T1}_{TASK}_z.eval"
    os.rename(local_path(second.location), newer)
    # one name timestamp and one mtime, as S3 LastModified values can tie
    for path in (older, newer):
        os.utime(path, (1_700_000_000, 1_700_000_000))
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="sort as equally recent"):
        merge_eval_log_shards(merged, _task())
    with pytest.raises(ShardSetError, match="sort as equally recent"):
        _merge_on("trio", monkeypatch, merged, _task())
    assert _files(str(tmp_path)) == before


@pytest.mark.parametrize("state", ["fresh", "unchanged", "removed"])
def test_s3_attempt_names_with_a_backslash_are_refused(
    s3_root: str, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    client = boto3.client("s3")

    def move(source: str, destination: str) -> None:
        prefix = "s3://test-bucket/"
        client.copy_object(
            Bucket="test-bucket",
            Key=destination.removeprefix(prefix),
            CopySource={"Bucket": "test-bucket", "Key": source.removeprefix(prefix)},
        )
        client.delete_object(Bucket="test-bucket", Key=source.removeprefix(prefix))

    merged, shards = _paths(f"s3://test-bucket/{s3_root}")
    newer = _backslash_attempts(shards, monkeypatch, move)
    if state != "fresh":
        _merge_unchecked(monkeypatch, merged)
    if state == "removed":
        client.delete_object(
            Bucket="test-bucket", Key=newer.removeprefix("s3://test-bucket/")
        )
    before = _s3_objects(f"{s3_root}/")
    with pytest.raises(ShardSetError, match=_BACKSLASH):
        merge_eval_log_shards(merged, _task())
    assert _s3_objects(f"{s3_root}/") == before


def test_a_literal_percent_sign_in_an_s3_attempt_name_merges(
    s3_shards: tuple[str, str], s3_root: str
) -> None:
    merged, _ = s3_shards
    shards = f"{s3_root}/{NAME}.shards"
    [attempt] = [k for k in _s3_keys(f"{shards}/0/") if k.endswith(".eval")]
    client = boto3.client("s3")
    client.copy_object(
        Bucket="test-bucket",
        Key=f"{shards}/0/worker%23tag.eval",
        CopySource={"Bucket": "test-bucket", "Key": attempt},
    )
    client.delete_object(Bucket="test-bucket", Key=attempt)
    result = merge_eval_log_shards(merged, _task())
    assert result.written
    assert result.log.status == "success" and result.log.eval.shards is not None
    assert result.log.eval.shards.ledger[0].log == "worker%23tag.eval"


@pytest.mark.parametrize("merge", ["fresh", "existing"])
@pytest.mark.parametrize(
    "name,match",
    [
        ("a", "must be named with digits only"),
        ("1#tag", "S3 would read it as"),
        ("prefix\\0", "must be named with digits only"),
    ],
)
def test_an_s3_shard_directory_not_named_with_digits_is_refused(
    s3_shards: tuple[str, str], s3_root: str, name: str, match: str, merge: str
) -> None:
    merged, _ = s3_shards
    shards = f"{s3_root}/{NAME}.shards"
    [attempt] = [k for k in _s3_keys(f"{shards}/1/") if k.endswith(".eval")]
    held = f"{s3_root}/held/worker.eval"
    client = boto3.client("s3")
    client.copy_object(
        Bucket="test-bucket",
        Key=held,
        CopySource={"Bucket": "test-bucket", "Key": attempt},
    )
    client.delete_object(Bucket="test-bucket", Key=attempt)
    if merge == "existing":
        result = merge_eval_log_shards(merged, _task(), sample_ids=[1, 2, 3])
        assert result.log.status == "success"
    # shard 1's worker, in a directory not named with digits
    client.copy_object(
        Bucket="test-bucket",
        Key=f"{shards}/{name}/worker.eval",
        CopySource={"Bucket": "test-bucket", "Key": held},
    )
    client.delete_object(Bucket="test-bucket", Key=held)
    before = _s3_objects(f"{s3_root}/")
    with pytest.raises(ShardSetError, match=match):
        merge_eval_log_shards(merged, _task(), sample_ids=list(range(1, 7)))
    assert _s3_objects(f"{s3_root}/") == before


@metric(scores="unreduced")
def shard_scorer_identity() -> Metric:
    """Counts the raw scores that name `identity_scored` as their scorer."""

    def compute(scores: list[SampleScore]) -> float:
        return float(sum(1 for s in scores if s.scorer == "identity_scored"))

    return compute


@scorer(metrics=[mean(), shard_scorer_identity()])
def identity_scored() -> Scorer:
    return graded()


@pytest.mark.parametrize(
    "epochs,scorers",
    [
        pytest.param(Epochs(2, at_least(1, value=0.5)), 1, id="reduced"),
        pytest.param(Epochs(2, []), 1, id="reduction-disabled"),
    ],
)
def test_raw_scores_keep_their_declared_scorer(
    tmp_path: Path, epochs: Epochs, scorers: int
) -> None:
    task = _graded_task(epochs)
    task.scorer = [identity_scored() for _ in range(scorers)]
    unsharded = eval(
        task, model="mockllm/model", log_dir=str(tmp_path / "unsharded"), display="none"
    )[0]
    assert unsharded.results is not None
    identity = [
        m.value
        for s in unsharded.results.scores
        for m in s.metrics.values()
        if m.name.endswith("shard_scorer_identity")
    ]
    assert identity and all(value == 12 for value in identity)

    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    first = merge_eval_log_shards(merged, task).log
    assert first.results is not None
    assert first.results.scores == unsharded.results.scores
    # incremental: shard 0's samples are carried
    _run(shards, "1", task, sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, task)
    assert result.written
    assert result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores


@solver
def _regrouped() -> Solver:
    """Changes every sample's `group` metadata, then fails the `_FAILING` ids."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.metadata["group"] = "joined"
        if state.sample_id in _FAILING:
            raise RuntimeError(f"failed on {state.sample_id}")
        return state

    return solve


@metric(scores="unreduced")
def shard_group_a() -> Metric:
    """Counts the raw scores whose sample metadata has group `A`."""

    def compute(scores: list[SampleScore]) -> float:
        return float(
            sum(1 for s in scores if (s.sample_metadata or {}).get("group") == "A")
        )

    return compute


@scorer(metrics=[grouped(accuracy(), "group"), shard_group_a()])
def grouped_scored() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=CORRECT if int(state.sample_id) % 2 else INCORRECT)

    return score


@task
def shard_regrouped() -> Task:
    return Task(
        dataset=[
            Sample(id=i, input="q", metadata={"group": group})
            for i, group in enumerate("AABABB", start=1)
        ],
        solver=_regrouped(),
        scorer=grouped_scored(),
        epochs=Epochs(2, at_least(1, value=0.5)),
    )


@pytest.mark.parametrize("reused", [False, True])
def test_declared_metrics_take_the_dataset_metadata(
    tmp_path: Path, failing: set[int], reused: bool
) -> None:
    unsharded = eval(
        shard_regrouped(),
        model="mockllm/model",
        log_dir=str(tmp_path / "unsharded"),
        display="none",
    )[0]
    assert unsharded.results is not None
    # grouped by the dataset's groups, not the solver's
    metrics = {
        m.name: m.value for s in unsharded.results.scores for m in s.metrics.values()
    }
    assert metrics["A"] == pytest.approx(1 / 3)
    assert metrics["shard_group_a"] == 6

    merged, shards = _paths(tmp_path)
    _run(shards, "0", shard_regrouped(), sample_id=[1, 2, 3])
    if reused:
        # the retry reuses samples 4 and 5 and runs 6 again
        failing.add(6)
        first = _run(shards, "1", shard_regrouped(), sample_id=[4, 5, 6])
        failing.clear()
        eval_retry(first, log_dir=f"{shards}/1", display="none")
    else:
        _run(shards, "1", shard_regrouped(), sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, shard_regrouped())
    assert result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores


def test_a_declared_score_without_a_sample_init_event_is_refused(
    tmp_path: Path,
) -> None:
    from inspect_ai.event import SampleInitEvent

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    log = _run(shards, "1", sample_id=[4, 5, 6])
    full = read_eval_log(log.location)
    assert full.samples is not None
    for sample in full.samples:
        if sample.id == 5:
            sample.events = [
                e for e in sample.events if not isinstance(e, SampleInitEvent)
            ]
    write_eval_log(full)
    before = _files(shards)
    with pytest.raises(ShardSetError, match="Sample '5' has no sample_init event"):
        merge_eval_log_shards(merged, _task())
    assert not os.path.exists(merged) and _files(shards) == before


# Streaming recomputation: the merge parses each sample member as it streams
# past, keeping only its metric inputs, so peak memory does not follow the
# size of a sample's transcript.

_MiB = 1024 * 1024


@solver
def _chatty(events: int, repeated: bool) -> Solver:
    """Logs `events` info events of 32 KiB of text each.

    The text is random, or with `repeated` one random block repeated with a
    different prefix, which compresses far beyond the reads' chunk size.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        import base64

        from inspect_ai.log import transcript

        block = base64.b64encode(os.urandom(24 * 1024)).decode()
        for i in range(events):
            if not repeated:
                block = base64.b64encode(os.urandom(24 * 1024)).decode()
            transcript().info(f"{i}:{block}")
        return await generate(state)

    return solve


def _merge_peak(merged: str, task: Task) -> tuple[ShardMergeResult, int]:
    """Merge, returning the result and the merge's peak traced memory."""
    import tracemalloc

    tracemalloc.start()
    try:
        result = merge_eval_log_shards(merged, task)
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("data", ["random", "repeated"])
@pytest.mark.parametrize("writer", ["zstd", "deflate"])
@pytest.mark.parametrize("write", ["fresh", "incremental"])
def test_merge_peak_memory_does_not_grow_with_transcript_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, write: str, writer: str, data: str
) -> None:
    if writer == "deflate":
        # a compressor that returns its output as it goes, so that the
        # measurement is of the merge's reading and parsing alone
        monkeypatch.setattr(
            "inspect_ai.log._shards._write.zipfile_compress_kwargs",
            {"compression": zipfile.ZIP_DEFLATED},
        )
    peaks, compressed = {}, {}
    for events in [100, 400]:
        task = _task(samples=2, solver=_chatty(events, data == "repeated"))
        merged, shards = _paths(tmp_path / str(events))
        _run(shards, "0", task, sample_id=[1])
        _run(shards, "1", task, sample_id=[2])
        if write == "incremental":
            # sample 1 is carried from the merged log, sample 2 read again
            merge_eval_log_shards(merged, task)
            _run(shards, "1", task, sample_id=[2])
        result, peaks[events] = _merge_peak(merged, task)
        assert result.written
        assert result.log.results is not None
        assert result.log.results.scores[0].metrics["accuracy"].value == 0.5
        with zipfile.ZipFile(local_path(merged)) as zf:
            member = zf.getinfo("samples/2_epoch_1.json")
        assert member.file_size > events * 32 * 1024
        compressed[events] = member.compress_size
    # sample members of about 3 and 13 MiB; parsing them whole took 4.5 times
    # their size. The recorder's multi-threaded zstd compressor returns most
    # of a member's compressed bytes only when the member is closed. Carried
    # members (incremental) are read back in the writer's compression.
    bound = _MiB if writer == "deflate" else compressed[400] + _MiB
    assert peaks[400] - peaks[100] < bound, (peaks, compressed)


_SEEN_SCORE_METADATA: list[dict[str, Any] | None] = []


@metric(name="shard_score_metadata")
def shard_score_metadata() -> Metric:
    """Records the score metadata it is given."""

    def compute(scores: list[SampleScore]) -> float:
        _SEEN_SCORE_METADATA.extend(s.score.metadata for s in scores)
        return float(len(scores))

    return compute


@scorer(metrics=[shard_score_metadata()])
def blob_scored(size: int) -> Scorer:
    """Scores with `size` bytes of incompressible text in the score metadata."""

    async def score(state: TaskState, target: Target) -> Score:
        import base64

        blob = base64.b64encode(os.urandom(size * 3 // 4)).decode()
        return Score(value=1, metadata={"blob": blob})

    return score


def test_merge_peak_memory_grows_with_the_retained_score_metadata(
    tmp_path: Path,
) -> None:
    peaks = {}
    for size in [1024, 256 * 1024]:
        task = _task(samples=6)
        task.scorer = [blob_scored(size)]
        merged, shards = _paths(tmp_path / str(size))
        _run(shards, "0", task, sample_id=[1, 2, 3])
        _run(shards, "1", task, sample_id=[4, 5, 6])
        _SEEN_SCORE_METADATA.clear()
        _, peaks[size] = _merge_peak(merged, task)
        # the metric is given the score metadata as the log stores it
        samples = read_eval_log(merged).samples
        assert samples is not None
        stored = [s.scores["blob_scored"].metadata for s in samples if s.scores]
        assert _SEEN_SCORE_METADATA == stored
    # six scores of 256 KiB more each are retained as metric inputs (the
    # summaries keep thinned score metadata)
    retained = 6 * (256 - 1) * 1024
    assert retained <= peaks[256 * 1024] - peaks[1024] < 3 * retained + _MiB, peaks


_SEEN_SAMPLE_METADATA: list[dict[str, Any] | None] = []


@metric(name="shard_sample_metadata")
def shard_sample_metadata() -> Metric:
    """Records the sample metadata it is given."""

    def compute(scores: list[SampleScore]) -> float:
        _SEEN_SAMPLE_METADATA.extend(s.sample_metadata for s in scores)
        return float(len(scores))

    return compute


@scorer(metrics=[shard_sample_metadata()])
def big_metadata_scored() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1)

    return score


def test_a_sample_the_streaming_parser_refuses_is_parsed_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log._shards import _write

    # an integer too large for the streaming parser, in the dataset metadata
    big = 2**70
    task = _task(samples=4)
    task.scorer = [big_metadata_scored()]
    assert task.dataset[2].metadata is not None
    task.dataset[2].metadata["big"] = big
    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2])
    _run(shards, "1", task, sample_id=[3, 4])
    whole: list[int | str] = []
    parse_whole = _write._parse_whole

    def spy(data: bytes) -> Any:
        parsed = parse_whole(data)
        whole.append(parsed.fields["id"])
        return parsed

    monkeypatch.setattr(_write, "_parse_whole", spy)
    _SEEN_SAMPLE_METADATA.clear()
    result = merge_eval_log_shards(merged, task)
    assert result.written
    assert whole == [3]
    assert _SEEN_SAMPLE_METADATA == [{"index": i} for i in (1, 2)] + [
        {"index": 3, "big": big},
        {"index": 4},
    ]
    samples = read_eval_log(merged).samples
    assert samples is not None and [s.id for s in samples] == [1, 2, 3, 4]


@pytest.mark.parametrize("field", ["score", "transcript"])
def test_a_sample_member_with_a_deprecated_field_is_refused(
    tmp_path: Path, field: str
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    log = _run(shards, "1", sample_id=[4, 5, 6])
    name = "samples/5_epoch_1.json"
    with zipfile.ZipFile(local_path(log.location)) as zf:
        sample = json.loads(zf.read(name))
    # the fields of log files from before `scores` and `events`
    if field == "score":
        sample["score"] = sample.pop("scores")["match"]
    else:
        sample["transcript"] = {"events": sample.pop("events"), "content": {}}
    _replace_member(log.location, name, json.dumps(sample).encode())
    before = _files(shards)
    with pytest.raises(
        ShardSetError,
        match=rf"samples/5_epoch_1.json has the deprecated fields \['{field}'\]",
    ):
        merge_eval_log_shards(merged, _task())
    assert not os.path.exists(merged) and _files(shards) == before


@pytest.mark.parametrize("where", ["sample", "event", "sample, parsed whole"])
def test_a_sample_member_with_a_dotted_key_where_events_are_read_is_refused(
    tmp_path: Path, where: str
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    log = _run(shards, "1", sample_id=[4, 5, 6])
    name = "samples/5_epoch_1.json"
    with zipfile.ZipFile(local_path(log.location)) as zf:
        sample = json.loads(zf.read(name))
    # each key's events would read as false initial metadata
    poison = {"metadata": {"poison": 1}}
    if where == "event":
        init = next(e for e in sample["events"] if e["event"] == "sample_init")
        key = "sample.metadata"
        init[key] = poison["metadata"]
    else:
        key = "events.item"
        sample[key] = {"event": "sample_init", "sample": poison}
        if where == "sample, parsed whole":
            # an integer only a whole parse reads
            sample["future_optional"] = 2**70
    _replace_member(log.location, name, json.dumps(sample).encode())
    before = _files(shards)
    with pytest.raises(
        ShardSetError, match=rf"samples/5_epoch_1.json has the keys \['{key}'\]"
    ):
        merge_eval_log_shards(merged, _task())
    assert not os.path.exists(merged) and _files(shards) == before


def test_sample_fields_a_later_inspect_adds_are_skipped_and_kept(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    first = _run(shards, "0", sample_id=[1, 2, 3])
    second = _run(shards, "1", sample_id=[4, 5, 6])
    # sample 5's field also holds an integer only a whole parse reads
    added = {2: {"future": [1, 2]}, 5: {"future": 2**70}}
    for log, sample_id in [(first, 2), (second, 5)]:
        name = f"samples/{sample_id}_epoch_1.json"
        with zipfile.ZipFile(local_path(log.location)) as zf:
            sample = json.loads(zf.read(name))
        sample["future_optional"] = added[sample_id]
        _replace_member(log.location, name, json.dumps(sample).encode())

    def merged_fields() -> dict[int, Any]:
        with zipfile.ZipFile(local_path(merged)) as zf:
            return {
                i: json.loads(zf.read(f"samples/{i}_epoch_1.json")).get(
                    "future_optional"
                )
                for i in range(1, 7)
            }

    expected = {i: added.get(i) for i in range(1, 7)}
    result = merge_eval_log_shards(merged, _task())
    assert result.written and merged_fields() == expected
    assert result.log.results is not None
    accuracy = result.log.results.scores[0].metrics["accuracy"].value
    # shard 1 is run again: sample 2 is carried from the merged log
    _run(shards, "1", sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, _task())
    assert result.written
    assert merged_fields() == {**expected, 5: None}
    assert result.log.results is not None
    assert result.log.results.scores[0].metrics["accuracy"].value == accuracy


@pytest.mark.parametrize("crc", ["matches", "differs"])
def test_sample_copies_are_released_after_the_merge(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch, crc: str
) -> None:
    import gc
    import weakref

    from inspect_ai.log._shards import _write

    merged, shards = two_shards
    copies: list[weakref.ref[Any]] = []
    init = _write._SampleCopy.__init__

    def spy(self: Any, *args: Any) -> None:
        init(self, *args)
        copies.append(weakref.ref(self))

    monkeypatch.setattr(_write._SampleCopy, "__init__", spy)
    if crc == "differs":

        def torn(*args: Any) -> None:
            raise ZipCrcError("torn")

        monkeypatch.setattr(_write, "_check_crc", torn)
        with pytest.raises(ZipCrcError):
            merge_eval_log_shards(merged, _task())
        gc.collect()
        assert copies
        # the error's traceback holds the frame holding a copy for as long as
        # anything holds the error; the copy has closed its member
        for ref in copies:
            copy = ref()
            assert copy is None or copy._pieces.writer.closed
    else:
        # with no reference cycle, reference counting alone frees each copy,
        # with or without an explicit close
        monkeypatch.setattr(_write._SampleCopy, "close", lambda self: None)
        gc.disable()
        try:
            merge_eval_log_shards(merged, _task())
            freed = [copy() is None for copy in copies]
        finally:
            gc.enable()
        assert freed and all(freed)


def test_a_sample_member_with_an_incomplete_deflate_stream_fails_the_merge(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    log = _run(shards, "1", sample_id=[4, 5, 6])
    name = "samples/5_epoch_1.json"
    path = local_path(log.location)
    # rewrite the shard deflated, then clear the member's final-block bit: its
    # output and CRC-32 are unchanged, but the stream never ends
    with zipfile.ZipFile(path) as zf:
        sample = zf.read(name)
    _replace_member(log.location, name, sample)
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(name)
    content = bytearray(Path(path).read_bytes())
    header = info.header_offset
    name_length = int.from_bytes(content[header + 26 : header + 28], "little")
    extra_length = int.from_bytes(content[header + 28 : header + 30], "little")
    data = header + 30 + name_length + extra_length
    assert content[data] & 1
    content[data] &= 0xFE
    Path(path).write_bytes(bytes(content))
    with pytest.raises(zlib.error, match="incomplete or truncated stream"):
        merge_eval_log_shards(merged, _task())
    assert not os.path.exists(merged)


async def test_a_cancelled_read_still_closes_the_sample_input(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._util import asyncfiles
    from inspect_ai.log import merge_eval_log_shards_async

    merged, shards = two_shards
    stream_class = asyncfiles._AnyIOFileByteReceiveStream
    streams: list[Any] = []
    receive = stream_class.receive
    cancelled: list[bool] = []

    async def merge() -> None:
        with anyio.CancelScope() as scope:

            async def cancelled_receive(self: Any, max_bytes: int = 65536) -> bytes:
                chunk = await receive(self, max_bytes)
                if self._filename.startswith(local_path(shards)):
                    # the file is open: cancel the read that opened it
                    streams.append(self)
                    scope.cancel()
                    await anyio.lowlevel.checkpoint()
                return chunk

            monkeypatch.setattr(stream_class, "receive", cancelled_receive)
            await merge_eval_log_shards_async(merged, _task())
        cancelled.append(scope.cancelled_caught)

    async with anyio.create_task_group() as tg:
        tg.start_soon(merge)
    assert cancelled == [True]
    # the close completed: the stream let go of its file
    assert streams and all(stream._file is None for stream in streams)
    assert not os.path.exists(merged)


@pytest.mark.parametrize("stop", ["error", "cancelled"])
async def test_a_sample_copy_whose_input_fails_to_open_is_freed(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    import gc
    import weakref

    from inspect_ai.log import merge_eval_log_shards_async
    from inspect_ai.log._shards import _write

    merged, shards = two_shards
    copies: list[weakref.ref[Any]] = []
    init = _write._SampleCopy.__init__

    def spy(self: Any, *args: Any) -> None:
        init(self, *args)
        copies.append(weakref.ref(self))

    monkeypatch.setattr(_write._SampleCopy, "__init__", spy)
    # collection must not depend on an explicit close
    monkeypatch.setattr(_write._SampleCopy, "close", lambda self: None)

    cancelled: list[bool] = []

    async def merge() -> None:
        # run as a task of its own, which drops the error that stopped the merge
        with anyio.CancelScope() as scope:

            async def open_member_raw(self: AsyncZipReader, member: Any) -> Any:
                if stop == "error":
                    raise OSError("open failed")
                scope.cancel()
                await anyio.lowlevel.checkpoint()

            monkeypatch.setattr(AsyncZipReader, "open_member_raw", open_member_raw)
            if stop == "error":
                with pytest.raises(OSError, match="open failed"):
                    await merge_eval_log_shards_async(merged, _task())
            else:
                await merge_eval_log_shards_async(merged, _task())
        cancelled.append(scope.cancelled_caught)

    async with anyio.create_task_group() as tg:
        tg.start_soon(merge)
    assert cancelled == [stop == "cancelled"]
    gc.collect()
    assert copies and all(copy() is None for copy in copies)
    assert not os.path.exists(merged)


@pytest.mark.parametrize("stop", ["error", "cancelled"])
async def test_a_sample_copy_that_stops_closes_its_input_first(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async
    from inspect_ai.log._shards import _write

    merged, shards = two_shards
    inputs: list[dict[str, bool]] = []
    read_file_bytes = AsyncFilesystem.read_file_bytes

    async def spy(self: AsyncFilesystem, *args: Any, **kwargs: Any) -> Any:
        stream = await read_file_bytes(self, *args, **kwargs)
        state = {"closed": False}
        aclose = stream.aclose

        async def close() -> None:
            state["closed"] = True
            await aclose()

        monkeypatch.setattr(stream, "aclose", close)
        inputs.append(state)
        return stream

    monkeypatch.setattr(AsyncFilesystem, "read_file_bytes", spy)
    with anyio.CancelScope() as scope:

        def write(self: Any, data: bytes) -> None:
            if stop == "error":
                raise RuntimeError("write failed")
            anyio.from_thread.run_sync(scope.cancel)

        monkeypatch.setattr(_write._SampleCopy, "write", write)
        if stop == "error":
            with pytest.raises(RuntimeError, match="write failed"):
                await merge_eval_log_shards_async(merged, _task())
        else:
            await merge_eval_log_shards_async(merged, _task())
    assert scope.cancelled_caught == (stop == "cancelled")
    assert inputs and all(state["closed"] for state in inputs)
    assert not os.path.exists(merged)


@pytest.mark.parametrize("stop", ["error", "cancelled"])
async def test_a_sample_copy_that_stops_closes_its_output_in_a_worker(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    import threading

    from inspect_ai.log import merge_eval_log_shards_async
    from inspect_ai.log._shards import _write

    merged, shards = two_shards
    loop_thread = threading.get_ident()
    copies: list[Any] = []
    closes: list[int] = []
    init = _write._SampleCopy.__init__
    close = _write._SampleCopy.close

    def init_spy(self: Any, *args: Any) -> None:
        init(self, *args)
        copies.append(self)

    def output_open(copy: Any) -> bool:
        writer = copy._pieces.writer
        return writer is not None and not writer.closed

    def close_spy(self: Any) -> None:
        if output_open(self):
            closes.append(threading.get_ident())
        close(self)

    monkeypatch.setattr(_write._SampleCopy, "__init__", init_spy)
    monkeypatch.setattr(_write._SampleCopy, "close", close_spy)
    with anyio.CancelScope() as scope:
        if stop == "error":

            def torn(*args: Any) -> None:
                raise ZipCrcError("torn")

            monkeypatch.setattr(_write, "_check_crc", torn)
            with pytest.raises(ZipCrcError):
                await merge_eval_log_shards_async(merged, _task())
        else:
            write = _write._SampleCopy.write

            def cancelling_write(self: Any, data: bytes) -> None:
                write(self, data)
                anyio.from_thread.run_sync(scope.cancel)

            monkeypatch.setattr(_write._SampleCopy, "write", cancelling_write)
            await merge_eval_log_shards_async(merged, _task())
    assert scope.cancelled_caught == (stop == "cancelled")
    # the copy that stopped had opened its output member and closed it
    assert len(copies) == 1 and not output_open(copies[0])
    assert closes and loop_thread not in closes
    assert not os.path.exists(merged)


def test_a_sample_member_that_does_not_match_its_crc_fails_the_merge(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    log = _run(shards, "1", sample_id=[4, 5, 6])
    name = "samples/5_epoch_1.json"
    path = local_path(log.location)
    with zipfile.ZipFile(path) as zf:
        sample = json.loads(zf.read(name))
    sample["future_optional"] = "a" * 64
    _replace_member(log.location, name, json.dumps(sample).encode())
    # rewrite it stored, then change its bytes after the CRC was recorded
    with zipfile.ZipFile(path) as src:
        members = [(i.filename, src.read(i)) for i in src.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as dst:
        for member, data in members:
            dst.writestr(member, data)
    content = Path(path).read_bytes()
    assert content.count(b"a" * 64) == 1
    Path(path).write_bytes(content.replace(b"a" * 64, b"b" * 64))
    with pytest.raises(ZipCrcError, match="samples/5_epoch_1.json"):
        merge_eval_log_shards(merged, _task())
    assert not os.path.exists(merged)
