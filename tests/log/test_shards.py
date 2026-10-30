import functools
import json
import os
import sys
import zipfile
from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path
from typing import Any

import anyio
import boto3
import pytest
from test_helpers.utils import skip_if_asyncio

from inspect_ai import Epochs, Task, eval, eval_retry, task
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
    edit_score,
    merge_eval_log_shards,
    read_eval_log,
    read_eval_log_async,
    write_eval_log,
)
from inspect_ai.log._file import is_log_file
from inspect_ai.log._log import EvalMetricDefinition
from inspect_ai.log._shards._plan import parse_sample_member, selection_digest
from inspect_ai.log._shards._walk import (
    ShardDir,
    ShardSetListing,
    attempt_sort_key,
    is_shard_path,
    list_shard_set,
)
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Metric,
    SampleScore,
    Score,
    Scorer,
    Target,
    Value,
    accuracy,
    at_least,
    grouped,
    match,
    mean,
    mean_score,
    metric,
    pass_at,
    pass_k,
    scorer,
    value_to_float,
)
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
        merge_eval_log_shards(recovered)
    assert not os.path.exists(recovered) and not os.path.exists(merged)

    merge_eval_log_shards(merged, allow_incomplete=True)
    before = Path(merged).read_bytes()
    with pytest.raises(ValueError, match="recovered"):
        merge_eval_log_shards(recovered)
    assert not os.path.exists(recovered)
    assert Path(merged).read_bytes() == before


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"sample_ids": []}, "non-empty"),
        ({"sample_count": 0}, "at least 1"),
        ({"sample_ids": [1], "sample_count": 1}, "at most one"),
        ({"allow_incomplete": True, "delete_shards": True}, "delete_shards"),
    ],
)
def test_merge_refuses_invalid_arguments(
    tmp_path: Path, kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        merge_eval_log_shards(_paths(tmp_path)[0], **kwargs)


def test_merge_with_neither_log_nor_shards_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        merge_eval_log_shards(_paths(tmp_path)[0])


def test_merge_of_sample_id_shards_matches_an_unsharded_run(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(epochs=Epochs(2, "mean"))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    unsharded = eval(
        task, model="mockllm/model", log_dir=str(tmp_path / "unsharded"), display="none"
    )[0]

    result = merge_eval_log_shards(f"{shards}/")
    assert result.written and not result.shards_deleted
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

    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.shards_deleted and result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores
    [declared] = [s for s in result.log.results.scores if "accuracy" in s.metrics]
    assert declared.metrics["accuracy"].value == pytest.approx(4 / 6)
    assert declared.scored_samples == 6


def test_a_scorer_declared_twice_is_refused(tmp_path: Path) -> None:
    task = _task()
    task.scorer = [other(), other()]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    before = _files(shards)
    with pytest.raises(ShardSetError, match="other more than once"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert not os.path.exists(merged) and _files(shards) == before


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
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.shards_deleted and result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores
    assert read_eval_log(merged).reductions == unsharded.reductions

    # incremental: shard 0's samples are carried from a merge made while
    # shard 1 was running
    merged, shards = _paths(tmp_path / "incremental")
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _as_running(_run(shards, "1", task, sample_id=[4, 5, 6]), keep={(4, 1)})
    first = merge_eval_log_shards(merged, allow_incomplete=True).log
    assert first.status == "started"
    reduced = not isinstance(epochs, int)
    assert (first.results is None) == reduced
    _run(shards, "1", task, sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.shards_deleted and result.log.results is not None
    assert result.log.results.scores == unsharded.results.scores
    assert read_eval_log(merged).reductions == unsharded.reductions


def test_a_cold_reducer_named_like_built_in_shorthand_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai._util import registry

    monkeypatch.chdir(tmp_path)
    _run_task_file(_SHORTHAND_REDUCER_TASK)
    # as in a fresh process; recreated, `pass_at_1` would be pass_at(k=1)
    monkeypatch.delitem(registry._registry, "score_reducer:pass_at_1")
    header = merge_eval_log_shards(f"{NAME}.eval", delete_shards=True).log
    assert header.results is not None
    assert header.results.scores[0].metrics["mean"].value == 1.0
    reductions = read_eval_log(f"{NAME}.eval").reductions
    assert reductions is not None and reductions[0].reducer == "pass_at_1"
    assert [s.value for s in reductions[0].samples] == [1.0] * 4


_SHORTHAND_REDUCER_TASK = f"""
from inspect_ai import Epochs, Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, ScoreReducer, Target, mean, score_reducer, scorer
from inspect_ai.solver import TaskState


@score_reducer(name="pass_at_1")
def first_epoch() -> ScoreReducer:
    def reduce(scores: list[Score]) -> Score:
        return scores[0]

    return reduce


@scorer(metrics=[mean()])
def by_epoch():
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1.0 if state.epoch == 1 else 0.0)

    return score


@task
def {TASK}() -> Task:
    return Task(
        dataset=[Sample(id=i, input="q") for i in range(1, 5)],
        scorer=by_epoch(),
        epochs=Epochs(2, first_epoch()),
    )
"""


@pytest.mark.parametrize("incomplete", [False, True])
@pytest.mark.parametrize(
    "case", ["no_reductions", "recovered", "recovered_untimestamped", "edited"]
)
def test_a_reduction_the_merge_cannot_take_from_its_shard_is_refused(
    tmp_path: Path, case: str, incomplete: bool
) -> None:
    import shutil

    from inspect_ai.scorer import ScoreEdit

    merged, shards = _paths(tmp_path)
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    shard = _run(shards, "0", task, sample_id=[1, 2, 3])
    other = _run(shards, "1", task, sample_id=[4, 5, 6])
    if incomplete:
        # a running shard's samples alone would leave the log without results
        _as_running(other, keep={(4, 1)})
    if case == "no_reductions":
        _remove_member(shard.location, "reductions.json")
    elif case == "recovered":
        # recovery recomputes reductions with reducers recreated by name
        shutil.copy2(
            local_path(shard.location), shard.location[:-5] + "-recovered.eval"
        )
    elif case == "recovered_untimestamped":
        # the shard's only attempt, under a name with no timestamp
        os.rename(local_path(shard.location), f"{shards}/0/worker-recovered.eval")
    else:
        _rewrite(
            shard,
            lambda log: edit_score(log, 1, "graded", ScoreEdit(value=0.25), epoch=1),
        )
    before = _files(shards)
    message = "was edited" if case == "edited" else "no epoch reduction .*at_least_1"
    with pytest.raises(ShardSetError, match=message) as raised:
        if incomplete:
            merge_eval_log_shards(merged, allow_incomplete=True)
        else:
            merge_eval_log_shards(merged, delete_shards=True)
    assert ("recovered log" in str(raised.value)) == case.startswith("recovered")
    assert not os.path.exists(merged)
    assert _files(shards) == before


def test_epoch_reducers_sharing_a_name_are_refused(tmp_path: Path) -> None:
    # both are recorded as `at_least_1`
    task = _graded_task(Epochs(2, [at_least(1, value=0.5), at_least(1)]))
    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    before = _files(shards)
    with pytest.raises(ShardSetError, match="name at_least_1 more than once"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert not os.path.exists(merged)
    assert _files(shards) == before


def _edit_bypassing_the_writer_check(merged: str) -> None:
    """Edit a score in a merged log whose shards exist, as an outside writer could.

    `edit_score()` refuses such a log (see the writer tests below); one read
    without its `location` is not checked, which leaves the merge's own
    edit-history check as the backstop.
    """
    from inspect_ai.scorer import ScoreEdit

    log = read_eval_log(merged)
    log.location = ""
    # edit_score recomputes the reductions with reducers recreated by name
    edit_score(log, 1, "graded", ScoreEdit(value=0.25), epoch=1)
    write_eval_log(log, merged)


def test_an_edited_carried_score_refuses_the_next_merge(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    _edit_bypassing_the_writer_check(merged)
    before = Path(merged).read_bytes()

    _run(shards, "1", task, sample_id=[4, 5, 6])
    with pytest.raises(ShardSetError, match=f"sample '1' in {merged} was edited"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert Path(merged).read_bytes() == before
    assert len(list(Path(shards).glob("*/*.eval"))) == 3


@pytest.mark.parametrize("remnant", ["unchanged", "interrupted"])
def test_an_edited_score_refuses_deleting_unchanged_shards(
    tmp_path: Path, remnant: str
) -> None:
    import shutil

    merged, shards = _paths(tmp_path)
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    _edit_bypassing_the_writer_check(merged)
    if remnant == "interrupted":
        # what an interrupted deletion leaves
        shutil.rmtree(f"{shards}/1")
    before = Path(merged).read_bytes(), _files(shards)

    with pytest.raises(ShardSetError, match="was edited.*shards were not deleted"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert (Path(merged).read_bytes(), _files(shards)) == before
    if remnant == "unchanged":
        # without deletion, a merge with nothing to do still returns the log
        assert not merge_eval_log_shards(merged).written


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


@pytest.mark.parametrize("damage", ["absent", "empty", "partial"])
@pytest.mark.parametrize("remnant", ["unchanged", "interrupted"])
def test_missing_retained_reductions_refuse_deleting_shards(
    tmp_path: Path, remnant: str, damage: str
) -> None:
    import shutil

    merged, shards = _paths(tmp_path)
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    with zipfile.ZipFile(merged) as zf:
        reductions = json.loads(zf.read("reductions.json"))
    if damage == "absent":
        _remove_member(merged, "reductions.json")
    elif damage == "empty":
        _replace_member(merged, "reductions.json", b"[]")
    else:
        reductions[0]["samples"] = reductions[0]["samples"][1:]
        _replace_member(merged, "reductions.json", json.dumps(reductions).encode())
    if remnant == "interrupted":
        shutil.rmtree(f"{shards}/1")
    before = Path(merged).read_bytes(), _files(shards)

    with pytest.raises(
        ShardSetError, match="no epoch reduction .*shards were not deleted"
    ):
        merge_eval_log_shards(merged, delete_shards=True)
    assert (Path(merged).read_bytes(), _files(shards)) == before


# armed while a test merges: an unreduced metric that must not run
_GUARD_ARMED: list[bool] = []


@metric(scores="unreduced")
def shard_unreduced_guard() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        if _GUARD_ARMED:
            raise AssertionError("an unreduced metric ran on partial data")
        return float(len(scores))

    return compute


def test_a_running_shard_without_reductions_computes_no_metrics(
    tmp_path: Path,
) -> None:
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    task.scorer = [graded_guarded()]
    merged, shards = _paths(tmp_path)
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _as_running(_run(shards, "1", task, sample_id=[4, 5, 6]), keep={(4, 1)})
    _GUARD_ARMED.append(True)
    try:
        header = merge_eval_log_shards(merged, allow_incomplete=True).log
    finally:
        _GUARD_ARMED.clear()
    assert header.status == "started" and header.results is None
    assert _keys(merged) == {(str(i), e) for i in (1, 2, 3) for e in (1, 2)} | {
        ("4", 1)
    }


@scorer(metrics=[mean(), shard_unreduced_guard()])
def graded_guarded() -> Scorer:
    return graded()


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
        match="Sample '1' .* has the score 'simple'.* cannot merge solver-set scores",
    ):
        merge_eval_log_shards(merged, delete_shards=True)
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
        merge_eval_log_shards(merged, allow_incomplete=True)
    _run(shards, "1", _keyed_task(values), sample_id=[10])
    log = merge_eval_log_shards(merged, delete_shards=True).log
    assert _metric_values(log) == _metric_values(unsharded)
    assert _metric_values(log) == {("alpha", "mean"): 1.0, ("beta", "mean"): 0.5}


@pytest.mark.parametrize("snapshot", ["startup", "unscored"])
def test_a_merge_holding_no_scores_needs_no_recorded_reductions(
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
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
    assert header.status == ("started" if snapshot == "startup" else "error")
    assert header.results is not None and header.results.scores[0].scored_samples == 0
    held = _keys(merged)
    assert held == (set() if snapshot == "startup" else {("1", 1), ("1", 2)})


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
    assert merge_eval_log_shards(merged).log.invalidated
    _check_invalidated(merged, True)
    # a replacement without the last invalidated sample clears the flag
    _run(shards, "1", sample_id=[4, 5, 6])
    assert not merge_eval_log_shards(merged).log.invalidated
    _check_invalidated(merged, False)
    # an invalidated replacement in an incremental merge sets it
    invalidated(_run(shards, "1", sample_id=[4, 5, 6]))
    assert merge_eval_log_shards(merged).log.invalidated
    _check_invalidated(merged, True)


def test_merge_of_limit_range_shards(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", limit=(0, 3))
    _run(shards, "1", limit=(3, 6))
    result = merge_eval_log_shards(merged, sample_count=6)
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
        merge_eval_log_shards(merged, sample_ids=[1, 2, 3, 4, 5])
    assert raised.value.status == "started"
    assert raised.value.missing == [4, 5]
    assert raised.value.running == [] and raised.value.failed == []
    assert not os.path.exists(merged)

    result = merge_eval_log_shards(
        merged, sample_ids=[1, 2, 3, 4, 5], allow_incomplete=True
    )
    assert result.log.status == "started"
    assert result.log.eval.dataset.sample_ids == [1, 2, 3, 4, 5]
    # an unchanged call without allow_incomplete still raises
    with pytest.raises(ShardSetIncomplete):
        merge_eval_log_shards(merged)


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
        merge_eval_log_shards(merged)
    assert raised.value.status == "error"
    assert raised.value.running == ["0"] and raised.value.failed == ["1"]

    result = merge_eval_log_shards(merged, allow_incomplete=True)
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
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
    assert header.status == "started" and header.error is None
    assert header.eval.shards is not None
    assert header.eval.shards.ledger[1].log != ledger[1].log

    # the cancelled status counts as failed too
    _rewrite(running, lambda log: setattr(log, "status", "cancelled"))
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
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
        merge_eval_log_shards(merged, sample_ids=list(range(1, 7)))
    assert raised.value.status == "started" and raised.value.missing == [6]
    # without a selection, the dataset size decides
    with pytest.raises(ShardSetIncomplete):
        merge_eval_log_shards(merged)


# ids whose sample a drain cancels as it starts (`_MATERIALIZING`), and ids
# whose sample stamps a drain while it runs, so the samples still queued are
# abandoned (`_DRAINING`); module state, as for `_FAILING`
_MATERIALIZING: set[int] = set()
_DRAINING: set[int] = set()


def _drain(eval_id: str) -> None:
    from inspect_ai._control.eval_state import get_eval_state

    state = get_eval_state(eval_id)
    assert state is not None and state.task_cancel is not None
    state.task_cancel.cancel_task("drain")


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
    backend: str, monkeypatch: pytest.MonkeyPatch, merged: str, **kwargs: Any
) -> ShardMergeResult:
    """Merge with the async API on `backend` (the drain producers run on asyncio)."""
    from inspect_ai.log import merge_eval_log_shards_async

    with monkeypatch.context() as patched:
        patched.setenv("INSPECT_ASYNC_BACKEND", backend)
        return anyio.run(
            functools.partial(merge_eval_log_shards_async, merged, **kwargs),
            backend=backend,
        )


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
        result = merge_eval_log_shards(merged, allow_incomplete=True)
        assert result.written and result.log.status == "started"
    _cancelled_while_starting(shards)
    before = _files(str(tmp_path))
    for delete in (False, True):
        with pytest.raises(ShardSetError, match="holds 2 samples but resolved only 1"):
            merge_eval_log_shards(merged, delete_shards=delete)
        with pytest.raises(ShardSetError, match="holds 2 samples but resolved only 1"):
            _merge_on("trio", monkeypatch, merged, delete_shards=delete)
    assert _files(str(tmp_path)) == before


@pytest.mark.parametrize("remnant", ["unchanged", "interrupted"])
def test_deleting_merged_attempts_rechecks_their_resolved_count(
    tmp_path: Path, drains: None, monkeypatch: pytest.MonkeyPatch, remnant: str
) -> None:
    import shutil

    from inspect_ai.log._shards import _api

    merged, shards = _paths(tmp_path)
    _run_drained(shards, "0", [1, 2])
    _cancelled_while_starting(shards)
    # a merged log whose ledger holds the attempt, as one merged without the
    # check would
    with monkeypatch.context() as patched:
        patched.setattr(_api, "check_resolved", lambda *args: None, raising=False)
        assert merge_eval_log_shards(merged).log.status == "success"
    if remnant == "interrupted":
        shutil.rmtree(f"{shards}/0")
    before = _files(str(tmp_path))
    with pytest.raises(ShardSetError, match="holds 2 samples but resolved only 1"):
        merge_eval_log_shards(merged, delete_shards=True)
    with pytest.raises(ShardSetError, match="holds 2 samples but resolved only 1"):
        _merge_on("trio", monkeypatch, merged, delete_shards=True)
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
        _run_drained(shards, "0", [1, 2])
        _DRAINING.add(3)
        _run_drained(shards, "1", [3, 4])
        _DRAINING.clear()
        header = merge_eval_log_shards(merged, allow_incomplete=True).log
        assert header.status == "started"
        assert _keys(merged) == {("1", 1), ("2", 1), ("3", 1)}
        _run_drained(shards, "1", [3, 4])
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.written and result.shards_deleted
    assert result.log.status == "success"
    assert _keys(merged) == {(str(i), 1) for i in range(1, 5)}


def test_merge_keeps_exactly_the_records_a_running_shard_holds(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(epochs=2)
    running = _run(shards, "0", task, sample_id=[1])
    _as_running(running, keep={(1, 1)})
    other = _run(shards, "1", task, sample_id=[2])
    header = merge_eval_log_shards(merged, sample_ids=[1, 2], allow_incomplete=True).log
    assert header.eval.shards is not None
    assert header.eval.shards.ledger[0].samples == 1
    assert _keys(merged) == {("1", 1), ("2", 1), ("2", 2)}

    # another shard changes; the running one is carried as it was
    _rewrite(other, lambda log: None)
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
    assert header.status == "started"
    assert _keys(merged) == {("1", 1), ("2", 1), ("2", 2)}


def test_merge_refuses_two_shards_selecting_one_id(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    _run(shards, "1", sample_id=[2, 3])
    with pytest.raises(ShardSetError, match="both select sample '2'"):
        merge_eval_log_shards(merged, allow_incomplete=True)
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
        result = merge_eval_log_shards(merged, sample_ids=[1, 2, 3, 4, 5])
        assert result.log.status == "success"
    # a worker for the last sample, in a directory not named with digits
    _run(shards, name, sample_id=[6])
    target = to_uri(merged) if form == "file_uri" else merged
    before = _files(str(tmp_path))
    for delete in (False, True):
        with pytest.raises(ShardSetError, match="must be named with digits only"):
            merge_eval_log_shards(
                target, sample_ids=list(range(1, 7)), delete_shards=delete
            )
    assert _files(str(tmp_path)) == before


def test_a_ledger_recording_a_shard_twice_is_refused(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)

    def duplicate(header: dict[str, Any]) -> None:
        ledger = header["eval"]["shards"]["ledger"]
        ledger.append(ledger[0])

    _edit_header(merged, duplicate)
    before = _files(str(tmp_path))
    for delete in (False, True):
        with pytest.raises(ShardSetError, match="records a shard more than once"):
            merge_eval_log_shards(merged, delete_shards=delete)
    assert _files(str(tmp_path)) == before


def test_a_ledger_recording_an_attempt_name_with_a_backslash_is_refused(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)

    def backslash(header: dict[str, Any]) -> None:
        entry = header["eval"]["shards"]["ledger"][0]
        entry["log"] = f"prefix\\{entry['log']}"

    _edit_header(merged, backslash)
    before = _files(str(tmp_path))
    for delete in (False, True):
        with pytest.raises(ShardSetError, match="a name with a backslash"):
            merge_eval_log_shards(merged, delete_shards=delete)
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
    """Merge as a merge without the attempt-name check would."""
    from inspect_ai.log._shards import _api

    with monkeypatch.context() as patched:
        patched.setattr(_api, "check_attempt_names", lambda shards: None, raising=False)
        assert merge_eval_log_shards(merged).log.status == "success"


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
    for delete in (False, True):
        with pytest.raises(ShardSetError, match=_BACKSLASH):
            merge_eval_log_shards(target, delete_shards=delete)
    assert _files(str(tmp_path)) == before


def test_distinct_shard_names_with_the_same_number_merge(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "00", sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.written and result.shards_deleted
    assert result.log.status == "success" and result.log.eval.shards is not None
    assert [e.shard for e in result.log.eval.shards.ledger] == ["0", "00"]


def test_merge_records_and_reads_back_each_selection_form(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    header = merge_eval_log_shards(
        merged, sample_ids=["2", 1, 3], allow_incomplete=True
    ).log
    assert header.eval.shards is not None
    assert header.eval.shards.selection == "ids"
    assert header.eval.dataset.sample_ids == ["2", 1, 3]
    # a later pass without a selection uses the recorded one
    with pytest.raises(ShardSetIncomplete) as raised:
        merge_eval_log_shards(merged)
    assert raised.value.missing == [3]

    result = merge_eval_log_shards(merged, sample_count=2)
    assert result.written and result.log.status == "success"
    assert result.log.eval.shards is not None
    assert result.log.eval.shards.selection == "count"
    assert result.log.eval.shards.sample_count == 2
    assert result.log.eval.dataset.sample_ids == [1, 2]
    assert not merge_eval_log_shards(merged).written

    with pytest.raises(ShardSetIncomplete):
        merge_eval_log_shards(merged, sample_count=3)


def test_selection_digest_ignores_order_and_id_type() -> None:
    assert selection_digest([1, 2, "3"]) == selection_digest(["3", "2", 1, 1])
    assert selection_digest([1, 2]) != selection_digest([1, 2, 3])
    assert len(selection_digest([])) == 64


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
    header = merge_eval_log_shards(merged, sample_ids=list(range(1, 101))).log
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
        merge_eval_log_shards(merged, allow_incomplete=True)
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
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_merge_refuses_a_different_reducer_and_a_newer_format(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", _task(epochs=Epochs(2, "mean")), sample_id=[1])
    second = _run(shards, "1", _task(epochs=Epochs(2, "max")), sample_id=[2])
    with pytest.raises(ShardSetError, match="epochs reducer"):
        merge_eval_log_shards(merged, allow_incomplete=True)
    os.remove(second.location)
    third = _run(shards, "1", _task(epochs=Epochs(2, "mean")), sample_id=[2])
    _edit_header(third.location, lambda h: h.update(version=99))
    with pytest.raises(ShardSetError, match="newer"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_merge_refuses_a_chunked_sample(tmp_path: Path) -> None:
    from inspect_ai.log._recorders.chunked import convert_eval_logs_to_chunked

    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    converted = tmp_path / "converted"
    convert_eval_logs_to_chunked(log.location, str(converted))
    os.replace(next(converted.glob("*.eval")), log.location)
    with pytest.raises(ShardSetError, match="chunked"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_merge_accepts_an_id_containing_a_slash(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    task = Task(
        dataset=[Sample(id="group/item", input="q", target=MATCH)],
        scorer=match(),
        name=TASK,
    )
    _run(shards, "0", task)
    result = merge_eval_log_shards(merged)
    assert result.log.status == "success"
    assert _members(merged) == ["samples/group/item_epoch_1.json"]


def test_merge_refuses_stray_logs_and_an_ordinary_log(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    stray = f"{shards}/{Path(log.location).name}"
    Path(stray).write_bytes(Path(log.location).read_bytes())
    with pytest.raises(ShardSetError, match="not shard attempts"):
        merge_eval_log_shards(merged, allow_incomplete=True)
    os.remove(stray)

    Path(merged).write_bytes(Path(log.location).read_bytes())
    before = Path(merged).read_bytes()
    with pytest.raises(ShardSetError, match="ordinary log"):
        merge_eval_log_shards(merged, allow_incomplete=True)
    assert Path(merged).read_bytes() == before


def test_merge_refuses_a_shard_without_a_recorded_selection(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    _edit_header(log.location, lambda h: h["eval"]["dataset"].pop("sample_ids"))
    with pytest.raises(ShardSetError, match="records no sample selection"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_merge_refuses_a_shard_holding_samples_outside_its_selection(
    tmp_path: Path,
) -> None:
    # what a shard of a task that adds samples while it runs looks like
    merged, shards = _paths(tmp_path)
    log = _run(shards, "0", sample_id=[1, 2])
    _edit_header(log.location, lambda h: h["eval"]["dataset"].update(sample_ids=[1]))
    with pytest.raises(ShardSetError, match="outside its recorded selection"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_merge_refuses_a_new_attempt_with_a_different_selection(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    first = _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, allow_incomplete=True)
    second = _run(shards, "0", sample_id=[1, 2, 3])
    with pytest.raises(ShardSetError) as raised:
        merge_eval_log_shards(merged, allow_incomplete=True)
    message = str(raised.value)
    assert Path(first.location).name in message
    assert Path(second.location).name in message
    assert "own shard directory" in message

    os.remove(merged)
    result = merge_eval_log_shards(merged, allow_incomplete=True)
    assert _keys(merged) == {("1", 1), ("2", 1), ("3", 1)}
    assert result.log.eval.shards is not None
    assert result.log.eval.shards.ledger[0].log == Path(second.location).name


def test_merge_refuses_a_new_shard_whose_selection_meets_a_carried_record(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, allow_incomplete=True)
    _run(shards, "1", sample_id=[2, 3])
    with pytest.raises(ShardSetError, match="already merged"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_merge_refuses_a_merged_log_changed_outside_the_merge(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    other = _run(shards, "1", sample_id=[3, 4])
    merge_eval_log_shards(merged, allow_incomplete=True)
    _remove_member(merged, "samples/1_epoch_1.json")
    # a pass over unchanged shards
    with pytest.raises(ShardSetError, match="changed outside the merge"):
        merge_eval_log_shards(merged, allow_incomplete=True)
    # and one where another shard changed
    _rewrite(other, lambda log: None)
    with pytest.raises(ShardSetError, match="changed outside the merge"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_overlap_without_shared_records_is_refused_once_a_shard_is_read_again(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    task = _task(epochs=1)
    first = _run(shards, "0", task, sample_id=[1, 2, 3])
    _as_running(first, keep={(1, 1)})
    merge_eval_log_shards(merged, allow_incomplete=True)
    # a new shard selecting 3, which shard 0 selects but does not hold yet
    _run(shards, "1", task, sample_id=[3, 4])
    merge_eval_log_shards(merged, allow_incomplete=True)
    # a fresh merge of the same shards refuses at once
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    import shutil

    shutil.copytree(shards, _paths(fresh)[1], copy_function=shutil.copy2)
    with pytest.raises(ShardSetError, match="both select"):
        merge_eval_log_shards(_paths(fresh)[0], allow_incomplete=True)
    # and the incremental one does when shard 0 is read again
    _rewrite(first, lambda log: None)
    with pytest.raises(ShardSetError, match="selected by shard 0|both select"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def test_incremental_merge_reads_only_changed_shards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merged, shards = _paths(tmp_path)
    growing = _run(shards, "0", sample_id=[1, 2, 3])
    full = read_eval_log(growing.location)
    _as_running(growing, keep={(1, 1), (2, 1)})
    steady = _run(shards, "1", sample_id=[4, 5, 6])
    first = merge_eval_log_shards(merged, allow_incomplete=True).log
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

    async def spy_read(self: AsyncZipReader, member: Any) -> bytes:
        name = member if isinstance(member, str) else member.filename
        member_reads.append((self._filename, name))
        return await read_member(self, member)

    monkeypatch.setattr(AsyncZipReader, "__init__", spy_init)
    monkeypatch.setattr(AsyncZipReader, "read_member_fully", spy_read)

    # nothing changed: nothing written, no shard opened
    result = merge_eval_log_shards(merged, allow_incomplete=True)
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
    result = merge_eval_log_shards(merged, allow_incomplete=True)
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
    merge_eval_log_shards(merged, allow_incomplete=True)
    retry = _run(shards, "0", sample_id=[1, 2, 3])
    _as_running(retry, keep={(1, 1)})
    merge_eval_log_shards(merged, allow_incomplete=True)
    assert _keys(merged) == {("1", 1)}


def test_vanished_shards_are_refused_and_a_removed_companion_keeps_the_log(
    tmp_path: Path,
) -> None:
    import shutil

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged, sample_ids=list(range(1, 7)))
    before = Path(merged).read_bytes()
    shutil.rmtree(f"{shards}/1")
    with pytest.raises(ShardSetError, match="vanished.*1"):
        merge_eval_log_shards(merged)
    assert Path(merged).read_bytes() == before

    shutil.rmtree(shards)
    result = merge_eval_log_shards(merged)
    assert not result.written and result.log.status == "success"
    assert Path(merged).read_bytes() == before
    with pytest.raises(ShardSetError, match="can no longer change"):
        merge_eval_log_shards(merged, sample_ids=[1, 2])
    assert not merge_eval_log_shards(merged, sample_ids=list(range(1, 7))).written


def test_an_added_shard_returns_a_success_log_to_started(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    _run(shards, "1", sample_id=[3, 4])
    first = merge_eval_log_shards(merged, sample_ids=[1, 2, 3, 4]).log
    assert first.status == "success"
    added = _run(shards, "2", sample_id=[5])
    _as_running(added)
    header = merge_eval_log_shards(
        merged, sample_ids=[1, 2, 3, 4, 5], allow_incomplete=True
    ).log
    assert header.status == "started"
    assert header.eval.eval_id == first.eval.eval_id
    # the recorded selection is narrower than the shards' when it is not widened
    _rewrite(added, lambda log: setattr(log, "status", "success"))
    with pytest.raises(ShardSelectionError) as raised:
        merge_eval_log_shards(merged, sample_ids=[1, 2, 3, 4])
    assert raised.value.outside == ["5"]
    assert "narrower" in str(raised.value)
    with pytest.raises(ShardSelectionError) as raised:
        merge_eval_log_shards(merged, sample_count=3)
    assert raised.value.outside is None


def test_merge_refuses_a_hand_deleted_current_attempt(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    current = _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, allow_incomplete=True)
    os.remove(current.location)
    with pytest.raises(ShardSetError, match="older than the attempt last merged"):
        merge_eval_log_shards(merged, allow_incomplete=True)


def _fresh_merge(tmp_path: Path, shards: str, **kwargs: Any) -> tuple[EvalLog, str]:
    """Merge a copy of `shards` (mtimes kept) with no merged log."""
    import shutil

    root = tmp_path / f"fresh{len(list(tmp_path.glob('fresh*')))}"
    root.mkdir()
    fresh_merged, fresh_shards = _paths(root)
    shutil.copytree(shards, fresh_shards, copy_function=shutil.copy2)
    return merge_eval_log_shards(fresh_merged, **kwargs).log, fresh_merged


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
        incremental = merge_eval_log_shards(merged, allow_incomplete=True).log
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
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
    assert header.status == "error"
    assert header.error is not None and "failed on 3" in header.error.message


def test_shard_directories_without_an_attempt_are_not_shards(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "1", sample_id=[1, 2, 3])
    _run(shards, "4", sample_id=[4, 5, 6])
    first = merge_eval_log_shards(merged).log
    for path in [
        f"{shards}/0/scans/scan_id=x/rows.parquet",
        f"{shards}/2/.buffer/x/segment.0.zip",
        f"{shards}/3/x.checkpoints/1",
    ]:
        _touch(Path(path))
    second = merge_eval_log_shards(merged)
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
    merge_eval_log_shards(merged, allow_incomplete=True)
    _run(shards, "0", sample_id=[1, 2])
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
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
    task_id = merge_eval_log_shards(merged, allow_incomplete=True).log.eval.task_id
    assert task_id == (RUN_ID if parsed else shortuuid.uuid(name=name))
    os.remove(merged)
    assert (
        merge_eval_log_shards(merged, allow_incomplete=True).log.eval.task_id == task_id
    )


def test_merged_log_edits_are_kept(tmp_path: Path) -> None:
    from inspect_ai.log import ProvenanceData, TagsEdit, edit_eval_log

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    other = _run(shards, "1", sample_id=[3, 4])
    merge_eval_log_shards(merged, allow_incomplete=True)
    log = read_eval_log(merged)
    edited = edit_eval_log(
        log, [TagsEdit(tags_add=["kept"])], ProvenanceData(author="test")
    )
    write_eval_log(edited, merged)
    _rewrite(other, lambda log: None)
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
    assert header.tags == ["kept"]


def test_eval_retry_refuses_an_id_or_count_selected_merged_log(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2])
    merge_eval_log_shards(merged, sample_ids=[1, 2, 3], allow_incomplete=True)
    with pytest.raises(ValueError, match=f"{NAME}.eval.*sample ids"):
        eval_retry(merged, log_dir=str(tmp_path / "retry"), display="none")
    merge_eval_log_shards(merged, sample_count=3, allow_incomplete=True)
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
    header = merge_eval_log_shards(merged, allow_incomplete=True).log
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


def test_delete_shards_deletes_the_whole_shards_directory(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    failed = _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    for other in (
        "1/.buffer/x/segment.0.zip",
        f"0/{Path(failed.location).stem}.checkpoints/1/data",
        "0/scans/scan_id=x/rows.parquet",
        "notes.txt",
    ):
        _touch(Path(f"{shards}/{other}"))

    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.written and result.shards_deleted
    assert result.log.status == "success"
    assert not os.path.exists(shards)
    again = merge_eval_log_shards(merged)
    assert not again.written and again.log.status == "success"
    # an unchanged call with delete_shards verifies and returns
    assert merge_eval_log_shards(merged, delete_shards=True).shards_deleted


def test_delete_shards_on_an_existing_success_log(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    before = Path(merged).read_bytes()
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert not result.written and result.shards_deleted
    assert not os.path.exists(shards)
    assert Path(merged).read_bytes() == before


def test_delete_shards_refuses_an_incomplete_set(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    with pytest.raises(ShardSetIncomplete):
        merge_eval_log_shards(merged, delete_shards=True)
    assert len(_files(shards)) == 1


def test_an_interrupted_delete_is_refused_until_it_is_finished(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    current = _run(shards, "0", sample_id=[1, 2, 3])
    b = _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    before = Path(merged).read_bytes()

    # what an interrupted deletion can leave: shard 0 without its merged
    # attempt but with an older one, shard 1 with only its checkpoints
    os.remove(current.location)
    os.remove(b.location)
    _touch(Path(f"{shards}/1/{Path(b.location).stem}.checkpoints/1/data"))
    with pytest.raises(ShardSetError, match="older than the attempt last merged"):
        merge_eval_log_shards(merged)
    with pytest.raises(ShardSetError, match="can no longer change"):
        merge_eval_log_shards(merged, sample_count=6, delete_shards=True)
    assert Path(merged).read_bytes() == before

    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.shards_deleted and not result.written
    assert Path(merged).read_bytes() == before
    assert not os.path.exists(shards)


def test_delete_shards_refuses_a_new_attempt_beside_an_interrupted_delete(
    tmp_path: Path,
) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    b = _run(shards, "1", sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    os.remove(b.location)
    _run(shards, "0", sample_id=[1, 2, 3])
    with pytest.raises(ShardSetError, match="vanished"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert os.path.exists(f"{shards}/0")


def test_a_vanished_shard_under_an_incomplete_log_is_refused(tmp_path: Path) -> None:
    import shutil

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _run(shards, "1", sample_id=[4, 5])
    merge_eval_log_shards(merged, allow_incomplete=True)
    shutil.rmtree(f"{shards}/1")
    with pytest.raises(ShardSetError, match="vanished"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert os.path.exists(f"{shards}/0")


def test_remove_shards_dir_with_the_log(tmp_path: Path) -> None:
    from inspect_ai.log._shards._delete import remove_shards_dir

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    merge_eval_log_shards(merged, allow_incomplete=True)
    anyio.run(lambda: remove_shards_dir(merged, include_log=True))
    assert not os.path.exists(merged) and not os.path.exists(shards)


def test_a_held_merge_lock_is_reported(tmp_path: Path) -> None:
    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    lock = tmp_path / f"{NAME}.merge.lock"
    lock.write_text('{"pid": 1, "host": "elsewhere"}')
    with pytest.raises(WriteConflictError, match="elsewhere"):
        merge_eval_log_shards(merged, allow_incomplete=True)
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
        results.append(await merge_eval_log_shards_async(merged))

    async with anyio.create_task_group() as tg:
        tg.start_soon(first)
        with anyio.fail_after(30):
            await reached.wait()
        with pytest.raises(WriteConflictError, match="merge.lock"):
            await merge_eval_log_shards_async(merged)
        release.set()
    assert results[0].written
    assert not os.path.exists(merged.replace(".eval", ".merge.lock"))


async def test_a_cancelled_merge_leaves_no_lock_or_temp_files(
    two_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, shards = two_shards
    before = _files(str(tmp_path))
    reached, _ = _pause_publish(monkeypatch)
    async with anyio.create_task_group() as tg:
        tg.start_soon(merge_eval_log_shards_async, merged)
        with anyio.fail_after(30):
            await reached.wait()
        tg.cancel_scope.cancel()
    assert _files(str(tmp_path)) == before


def _crc_failures(
    monkeypatch: pytest.MonkeyPatch,
    shards: str,
    failures: int,
    error: Exception,
    member: str = "samples/",
) -> list[str]:
    """Fail the first `failures` reads of `member` from a shard with `error`."""
    calls: list[str] = []
    read_member = AsyncZipReader.read_member_fully

    async def failing(self: AsyncZipReader, member_: Any) -> bytes:
        name = member_ if isinstance(member_, str) else member_.filename
        if self._filename.startswith(shards) and name.startswith(member):
            calls.append(name)
            if len(calls) <= failures:
                raise error
        return await read_member(self, member_)

    monkeypatch.setattr(AsyncZipReader, "read_member_fully", failing)
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
        merge_eval_log_shards(merged)
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
        merge_eval_log_shards(merged)
    assert len(calls) == 1
    assert not os.path.exists(merged)


def _run_task_file(source: str) -> None:
    """Run the task in `source` as two shards from the current directory."""
    Path("custom_task.py").write_text(source)
    for k, ids in (("0", [1, 2]), ("1", [3, 4])):
        eval(
            "custom_task.py",
            model="mockllm/model",
            log_dir=f"{NAME}.shards/{k}",
            display="none",
            sample_id=ids,
        )


@pytest.mark.parametrize(
    "source,registry_key,named",
    [
        ("scorer_metric", "metric:shard_custom_count", "Metric 'shard_custom_count'"),
        ("wrapped_metric", "metric:shard_custom_inner", "Metric 'shard_custom_inner'"),
    ],
)
def test_an_unregistered_metric_is_refused_until_imported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    registry_key: str,
    named: str,
) -> None:
    import runpy

    from inspect_ai._util import registry

    monkeypatch.chdir(tmp_path)
    _run_task_file(_CUSTOM_TASKS[source])
    # as in a fresh process: the merge never imports the recorded task file
    monkeypatch.delitem(registry._registry, registry_key)
    with pytest.raises(LookupError, match=named) as raised:
        merge_eval_log_shards(f"{NAME}.eval")
    assert "Import the module that defines it" in str(raised.value)
    assert not os.path.exists(f"{NAME}.eval")
    assert registry_key not in registry._registry

    # the caller imports the module that defines it, and the same merge works
    runpy.run_path("custom_task.py")
    header = merge_eval_log_shards(f"{NAME}.eval").log
    assert header.status == "success" and header.results is not None


_SHADOWING_TASK = f"""
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Metric, SampleScore, match, metric


@metric(name="mean")
def shard_shadowing_mean() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return 7.0

    return compute


@task
def {TASK}() -> Task:
    return Task(
        dataset=[Sample(id=i, input="q", target="x") for i in range(1, 5)],
        scorer=match(),
        metrics=[shard_shadowing_mean()],
    )
"""


@pytest.mark.parametrize("incremental", [False, True], ids=["first", "incremental"])
def test_a_custom_metric_with_a_builtin_name_is_refused_until_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, incremental: bool
) -> None:
    import runpy

    from inspect_ai._util import registry

    # the task file registers `mean`; keep it out of later tests
    monkeypatch.setattr(registry, "_registry", dict(registry._registry))
    monkeypatch.chdir(tmp_path)
    Path("custom_task.py").write_text(_SHADOWING_TASK)
    merged, shards = _paths(".")

    def run(k: str, ids: list[int]) -> None:
        eval(
            "custom_task.py",
            model="mockllm/model",
            log_dir=f"{shards}/{k}",
            display="none",
            sample_id=ids,
        )

    run("0", [1, 2])
    if incremental:
        merge_eval_log_shards(merged, allow_incomplete=True)
    run("1", [3, 4])
    header = read_eval_log(next(Path(f"{shards}/1").glob("*.eval")), header_only=True)
    assert header.eval.scorers is not None
    metrics = header.eval.scorers[0].metrics
    assert metrics == [EvalMetricDefinition(name="mean", options={})]

    # as in a fresh process, where `mean` would resolve to `inspect_ai/mean`
    monkeypatch.delitem(registry._registry, "metric:mean")
    before = _files(".")
    with pytest.raises(LookupError, match="Metric 'mean' is not registered"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert _files(".") == before
    assert os.path.exists(merged) == incremental

    runpy.run_path("custom_task.py")
    log = merge_eval_log_shards(merged, delete_shards=True).log
    assert log.results is not None
    assert log.results.scores[0].metrics["mean"].value == 7.0


@metric(name="shard_pkg/shard_qualified")
def shard_qualified() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return 7.0

    return compute


@pytest.mark.parametrize("qualified", [mean, shard_qualified])
def test_builtin_and_package_qualified_metrics_merge(
    tmp_path: Path, qualified: Callable[[], Metric]
) -> None:
    merged, shards = _paths(tmp_path)
    task = Task(
        dataset=[Sample(id=i, input="q", target="x") for i in range(1, 5)],
        scorer=match(),
        metrics=[qualified()],
        name=TASK,
    )
    _run(shards, "0", task, sample_id=[1, 2])
    _run(shards, "1", task, sample_id=[3, 4])
    header = read_eval_log(next(Path(f"{shards}/1").glob("*.eval")), header_only=True)
    assert header.eval.scorers is not None
    metrics = header.eval.scorers[0].metrics
    assert isinstance(metrics, list) and isinstance(metrics[0], EvalMetricDefinition)
    assert "/" in metrics[0].name
    unsharded = eval(
        task, model="mockllm/model", log_dir=str(tmp_path / "u"), display="none"
    )[0]
    log = merge_eval_log_shards(merged, delete_shards=True).log
    assert log.results is not None and unsharded.results is not None
    assert log.results.scores[0].metrics == unsharded.results.scores[0].metrics


_CUSTOM_TASKS = {
    "scorer_metric": f"""
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Metric, SampleScore, match, metric


@metric
def shard_custom_count() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return float(len(scores))

    return compute


@task
def {TASK}() -> Task:
    return Task(
        dataset=[Sample(id=i, input="q", target="x") for i in range(1, 5)],
        scorer=match(),
        metrics=[shard_custom_count()],
    )
""",
    "wrapped_metric": f"""
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Metric, SampleScore, grouped, match, metric


@metric
def shard_custom_inner() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        return float(len(scores))

    return compute


@task
def {TASK}() -> Task:
    # the custom metric is only inside a registered wrapper's options
    return Task(
        dataset=[
            Sample(id=i, input="q", target="x", metadata={{"group": i % 2}})
            for i in range(1, 5)
        ],
        scorer=match(),
        metrics=[grouped(shard_custom_inner(), "group")],
    )
""",
}


def test_metrics_nested_in_wrappers_are_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from inspect_ai._util import registry
    from inspect_ai._util.registry import registry_params
    from inspect_ai.log._shards._write import _check_embedded
    from inspect_ai.scorer import Metric, SampleScore, aggregate, grouped, metric

    @metric
    def shard_custom_nested() -> Metric:
        def compute(scores: list[SampleScore]) -> float:
            return 0.0

        return compute

    options = registry_params(grouped(aggregate("k", shard_custom_nested()), "g"))
    _check_embedded(options)
    monkeypatch.delitem(registry._registry, "metric:shard_custom_nested")
    with pytest.raises(LookupError, match="Metric 'shard_custom_nested'"):
        _check_embedded(options)


@pytest.mark.parametrize(
    "name", ["run*", "run[1]", "lo*s/run"], ids=["*", "[]", "parent"]
)
def test_s3_deletion_refuses_glob_characters(s3_root: str, name: str) -> None:
    from inspect_ai.log._shards._delete import remove_shards_dir

    client = boto3.client("s3")
    root = f"s3://test-bucket/{s3_root}"
    targets = [f"{name}.shards/0/a.eval", f"{name}.eval"]
    neighbours = ["run1.shards/0/a.eval", "run1.eval"]
    neighbours += ["logs/run1.shards/0/a.eval", "logs/run1.eval"]
    for key in targets + neighbours:
        client.put_object(Bucket="test-bucket", Key=f"{s3_root}/{key}", Body=b"x")
    before = _s3_keys(f"{s3_root}/")

    with pytest.raises(ValueError, match="glob character"):
        anyio.run(lambda: remove_shards_dir(f"{root}/{name}.eval", include_log=True))
    with pytest.raises(ValueError, match="glob character"):
        merge_eval_log_shards(f"{root}/{name}.eval", delete_shards=True)
    assert _s3_keys(f"{s3_root}/") == before


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
    "simplecache::s3://test-bucket/logs",
]


def _refuse_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on any fsspec filesystem construction (every non-S3 storage call)."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("storage was accessed")

    monkeypatch.setattr("fsspec.core.url_to_fs", refuse)
    monkeypatch.setattr("fsspec.filesystem", refuse)


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
    "root", _UNSUPPORTED_ROOTS, ids=[r.split(":")[0] for r in _UNSUPPORTED_ROOTS]
)
def test_a_merge_of_unsupported_storage_is_refused_before_any_io(
    monkeypatch: pytest.MonkeyPatch, root: str, backend: str
) -> None:
    import shortuuid

    from inspect_ai._util.file import filesystem
    from inspect_ai.log._shards._delete import remove_shards_dir

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
        for location in (merged, shards):
            for delete in (False, True):
                with pytest.raises(ValueError, match=_UNSUPPORTED):
                    _merge_on(backend, monkeypatch, location, delete_shards=delete)
                if backend == "asyncio":
                    with pytest.raises(ValueError, match=_UNSUPPORTED):
                        merge_eval_log_shards(location, delete_shards=delete)
        with pytest.raises(ValueError, match=_UNSUPPORTED):
            anyio.run(
                functools.partial(remove_shards_dir, merged, include_log=True),
                backend=backend,
            )
    if root.startswith("memory://"):
        assert before and _memory_objects(root) == before


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
    first = merge_eval_log_shards(merged)
    assert first.written and first.log.status == "success"
    assert first.log.eval.shards is not None
    assert all(e.etag for e in first.log.eval.shards.ledger)
    assert not merge_eval_log_shards(merged).written

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
    second = merge_eval_log_shards(merged)
    assert second.written and second.log.eval.eval_id == first.log.eval.eval_id
    log = read_eval_log(merged)
    assert sorted(s.id for s in log.samples or []) == [1, 2, 3, 4, 5, 6]

    # a call that writes, verifies the published object and deletes
    change("0")
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.written and result.shards_deleted
    assert _s3_keys(f"{s3_root}/") == [f"{s3_root}/{NAME}.eval"]
    assert not merge_eval_log_shards(merged).written


async def test_concurrent_first_merges_on_s3_publish_once(
    s3_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    reached, release = _pause_publish(monkeypatch)
    failures: list[BaseException] = []

    async def first() -> None:
        try:
            await merge_eval_log_shards_async(merged)
        except WriteConflictError as ex:
            failures.append(ex)

    async with anyio.create_task_group() as tg:
        tg.start_soon(first)
        with anyio.fail_after(30):
            await reached.wait()
        winner = await merge_eval_log_shards_async(merged)
        release.set()
    assert len(failures) == 1
    header = await read_eval_log_async(merged, header_only=True)
    assert header.eval.eval_id == winner.log.eval.eval_id


async def test_an_older_snapshot_published_after_a_newer_one_is_refused_on_s3(
    s3_shards: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, shards = s3_shards
    await merge_eval_log_shards_async(merged, sample_ids=[1, 2, 3, 4, 5, 6])
    reached, release = _pause_publish(monkeypatch)
    failures: list[BaseException] = []

    async def stale() -> None:
        try:
            await merge_eval_log_shards_async(merged, sample_count=6)
        except WriteConflictError as ex:
            failures.append(ex)

    async with anyio.create_task_group() as tg:
        tg.start_soon(stale)
        with anyio.fail_after(30):
            await reached.wait()
        await merge_eval_log_shards_async(
            merged, sample_ids=[6, 5, 4, 3, 2, 1, 7], allow_incomplete=True
        )
        release.set()
    assert len(failures) == 1
    header = await read_eval_log_async(merged, header_only=True)
    assert header.eval.shards is not None and header.eval.shards.selection == "ids"
    # a re-run merges cleanly
    result = await merge_eval_log_shards_async(merged, sample_count=6)
    assert result.written and result.log.status == "success"


async def test_a_merge_whose_log_was_removed_meanwhile_is_refused_on_s3(
    s3_shards: tuple[str, str], s3_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async
    from inspect_ai.log._shards._delete import remove_shards_dir

    merged, shards = s3_shards
    await merge_eval_log_shards_async(merged)
    reached, release = _pause_publish(monkeypatch)
    failures: list[BaseException] = []

    async def merge() -> None:
        try:
            await merge_eval_log_shards_async(merged, sample_count=6)
        except WriteConflictError as ex:
            failures.append(ex)

    async with anyio.create_task_group() as tg:
        tg.start_soon(merge)
        with anyio.fail_after(30):
            await reached.wait()
        try:
            await remove_shards_dir(merged, include_log=True)
        finally:
            release.set()
    assert len(failures) == 1
    assert _s3_keys(f"{s3_root}/") == []


def test_an_interrupted_delete_on_s3_is_finished_by_a_rerun(
    s3_shards: tuple[str, str], s3_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    merged, shards = s3_shards
    merge_eval_log_shards(merged)
    b = next(k for k in _s3_keys(f"{s3_root}/{NAME}.shards/1/") if k.endswith(".eval"))

    from inspect_ai.log._shards import _delete

    def failing_delete(s3: Any, bucket: str, keys: list[str]) -> None:
        raise OSError(f"injected failure deleting {keys[0]}")

    monkeypatch.setattr(_delete, "_delete_s3_keys", failing_delete)
    with pytest.raises(OSError, match="injected failure"):
        merge_eval_log_shards(merged, delete_shards=True)
    monkeypatch.undo()
    assert b in _s3_keys(f"{s3_root}/")
    assert merge_eval_log_shards(merged, delete_shards=True).shards_deleted
    assert _s3_keys(f"{s3_root}/") == [f"{s3_root}/{NAME}.eval"]


def test_merge_refuses_a_recovered_shards_directory_name(tmp_path: Path) -> None:
    import shutil

    _, shards = _paths(tmp_path)
    neighbour = _run(shards, "0", sample_id=[1, 2, 3])
    recovered = f"{tmp_path}/{NAME}-recovered.shards"
    shutil.copytree(shards, recovered)
    before = _files(str(tmp_path))
    with pytest.raises(ValueError, match=f"{NAME}.shards"):
        merge_eval_log_shards(recovered, delete_shards=True)
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
    result = merge_eval_log_shards(uri, allow_incomplete=True)
    assert result.written and result.log.location == uri
    assert _keys(merged) == {("1", 1), ("2", 1), ("3", 1)}
    _run(shards, "1", sample_id=[4, 5, 6])
    result = merge_eval_log_shards(to_uri(shards), delete_shards=True)
    assert result.written and result.shards_deleted
    assert read_eval_log(merged, header_only=True).status == "success"
    assert not os.path.exists(shards)


def test_delete_shards_keeps_exact_names_with_reserved_characters(
    tmp_path: Path,
) -> None:
    root = tmp_path / _RESERVED
    merged, shards = _paths(root)
    old = _run(shards, "0", sample_id=[1, 2, 3])
    current = _run(shards, "0", sample_id=[1, 2, 3])
    # a literal %20, # and ? in an older attempt's name and a buffer's name
    literal = f"{os.path.dirname(old.location)}/{T0}_lit%20na#me?.eval"
    os.replace(old.location, literal)
    _touch(Path(f"{shards}/0/.buffer/a%20b/seg#1?.zip"))
    # neighbours whose names are the decoded forms are kept
    neighbours = [
        tmp_path / "sp ace d#ir?x" / "keep.eval",
        Path(
            f"{shards}/0/{T0}_lit na#me?.eval".replace(f"{NAME}.shards", "other.shards")
        ),
    ]
    for path in neighbours:
        _touch(path)
    result = merge_eval_log_shards(merged, sample_ids=[1, 2, 3], delete_shards=True)
    assert result.shards_deleted
    assert not os.path.exists(shards)
    assert not os.path.exists(literal) and not os.path.exists(current.location)
    assert all(path.exists() for path in neighbours)


@pytest.mark.parametrize("fail", [False, True])
def test_cli_json_stdout_holds_only_the_object_when_metric_code_prints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    from click.testing import CliRunner

    from inspect_ai._cli.log import log_command

    monkeypatch.chdir(tmp_path)
    _run_task_file(_NOISY_TASK)
    if fail:
        monkeypatch.setenv("SHARD_NOISY_FAIL", "1")
    result = CliRunner().invoke(log_command, ["merge-shards", f"{NAME}.eval", "--json"])
    assert result.exit_code == (1 if fail else 0), result.output
    output = json.loads(result.stdout)
    if fail:
        assert output["error"]["type"] == "ValueError"
    else:
        assert output["status"] == "success"
    assert "metric noise" in result.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="uses the C library's printf")
@pytest.mark.parametrize("fail", [False, True])
def test_cli_json_stdout_holds_only_the_object_in_a_real_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    import subprocess

    monkeypatch.chdir(tmp_path)
    _run_task_file(_NATIVE_TASK)
    Path("merge.py").write_text(
        "import runpy\n"
        "runpy.run_path('custom_task.py')\n"
        "from inspect_ai._cli.log import log_command\n"
        f"log_command.main(['merge-shards', '{NAME}.eval', '--json'])\n"
    )
    # a legacy hook makes startup print a banner, which must not reach stdout
    Path("key_hook.py").write_text("def override(var, value):\n    return None\n")
    env = {
        **os.environ,
        "SHARD_NATIVE_PRINT": "1",
        "INSPECT_API_KEY_OVERRIDE": "key_hook.override",
    }
    if fail:
        env["SHARD_NATIVE_FAIL"] = "1"
    # a real process: the C library buffers printf output to a pipe
    result = subprocess.run(
        [sys.executable, "merge.py"], capture_output=True, text=True, env=env
    )
    assert result.returncode == (1 if fail else 0), result.stderr
    output = json.loads(result.stdout)
    if fail:
        assert output["error"]["type"] == "ValueError"
    else:
        assert output["status"] == "success"
    assert "native noise" in result.stderr
    assert "api key override enabled" in result.stderr


_NATIVE_TASK = f"""
import ctypes
import os

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Metric, SampleScore, match, metric


@metric
def shard_native_count() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        if os.environ.get("SHARD_NATIVE_PRINT"):
            ctypes.CDLL(None).printf(b"native noise\\n")
        if os.environ.get("SHARD_NATIVE_FAIL"):
            raise ValueError("metric failed")
        return float(len(scores))

    return compute


@task
def {TASK}() -> Task:
    return Task(
        dataset=[Sample(id=i, input="q", target="x") for i in range(1, 5)],
        scorer=match(),
        metrics=[shard_native_count()],
    )
"""


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
        merge_eval_log_shards(merged)
    assert not marker.exists()


def test_cli_json_reports_an_unregistered_metric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from click.testing import CliRunner

    from inspect_ai._cli.log import log_command
    from inspect_ai._util import registry

    monkeypatch.chdir(tmp_path)
    _run_task_file(_CUSTOM_TASKS["scorer_metric"])
    monkeypatch.delitem(registry._registry, "metric:shard_custom_count")
    text = CliRunner().invoke(log_command, ["merge-shards", f"{NAME}.eval"])
    assert text.exit_code == 1 and "shard_custom_count" in text.stderr
    result = CliRunner().invoke(log_command, ["merge-shards", f"{NAME}.eval", "--json"])
    assert result.exit_code == 1, result.output
    error = json.loads(result.stdout)["error"]
    assert error["type"] == "LookupError"
    assert "shard_custom_count" in error["message"]
    assert not os.path.exists(f"{NAME}.eval")


_NOISY_TASK = f"""
import os

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Metric, SampleScore, match, metric


@metric
def shard_noisy_count() -> Metric:
    def compute(scores: list[SampleScore]) -> float:
        print("metric noise")
        if os.environ.get("SHARD_NOISY_FAIL"):
            raise ValueError("metric failed")
        return float(len(scores))

    return compute


@task
def {TASK}() -> Task:
    return Task(
        dataset=[Sample(id=i, input="q", target="x") for i in range(1, 5)],
        scorer=match(),
        metrics=[shard_noisy_count()],
    )
"""


async def test_delete_shards_on_s3_deletes_folder_markers(
    s3_shards: tuple[str, str], s3_root: str
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    client = boto3.client("s3")
    markers = [
        f"{s3_root}/{NAME}.shards/",
        f"{s3_root}/{NAME}.shards/0/",
        f"{s3_root}/{NAME}.shards/1/x.checkpoints/",
    ]

    def put_markers() -> None:
        for key in markers:
            client.put_object(Bucket="test-bucket", Key=key, Body=b"")

    put_markers()
    result = await merge_eval_log_shards_async(merged, delete_shards=True)
    assert result.shards_deleted
    assert _s3_keys(f"{s3_root}/") == [f"{s3_root}/{NAME}.eval"]
    # a remnant of markers only, then a repeated call
    put_markers()
    for _ in range(2):
        result = await merge_eval_log_shards_async(merged, delete_shards=True)
        assert result.shards_deleted and not result.written
        assert _s3_keys(f"{s3_root}/") == [f"{s3_root}/{NAME}.eval"]


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
        merge_eval_log_shards(encoded, delete_shards=True)
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


def _write_with(writer: str, log: EvalLog) -> None:
    """Run one of the writers that recreate epoch reducers on `log`."""
    import functools

    from inspect_ai import score_async
    from inspect_ai._cli.score import score as cli_score
    from inspect_ai._eval.score import ScoreAction
    from inspect_ai.log import recompute_metrics
    from inspect_ai.scorer import ScoreEdit

    if writer == "recompute_metrics":
        recompute_metrics(log)
    elif writer in ("score_overwrite", "score_append"):
        action: ScoreAction = "overwrite" if writer == "score_overwrite" else "append"
        anyio.run(functools.partial(score_async, log, [graded()], action=action))
    elif writer == "edit_score":
        edit_score(log, 1, "graded", ScoreEdit(value=0.25), epoch=1)
    elif writer == "edit_score_only":
        edit_score(
            log, 1, "graded", ScoreEdit(value=0.25), epoch=1, recompute_metrics=False
        )
    else:
        # `inspect score --overwrite --stream`: refused before it writes
        assert log.location is not None
        anyio.run(
            functools.partial(
                cli_score,
                log_dir=str(Path(log.location).parent),
                log_file=log.location,
                scorer=None,
                s=None,
                metric=None,
                overwrite=True,
                action="overwrite",
                log_level=None,
                stream=True,
            )
        )


@pytest.mark.parametrize(
    "writer",
    ["recompute_metrics", "score_overwrite", "score_append", "edit_score", "cli"],
)
def test_writers_refuse_a_merged_log_whose_shards_exist(
    tmp_path: Path, writer: str
) -> None:
    merged, shards = _paths(tmp_path)
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    before = Path(merged).read_bytes(), _files(shards)

    log = read_eval_log(merged)
    with pytest.raises(ShardSetError, match="shards that still exist"):
        _write_with(writer, log)
    assert (Path(merged).read_bytes(), _files(shards)) == before

    # once the merge has deleted the shards, the same call is allowed
    assert merge_eval_log_shards(merged, delete_shards=True).shards_deleted
    _write_with(writer, read_eval_log(merged))


@pytest.mark.parametrize("writer", ["recompute_metrics", "edit_score"])
def test_writers_leave_ordinary_logs_alone(tmp_path: Path, writer: str) -> None:
    log = _run(str(tmp_path), "0", _graded_task(Epochs(2, at_least(1, value=0.5))))
    _write_with(writer, read_eval_log(log.location))


@pytest.mark.parametrize(
    "writer", ["recompute_metrics", "edit_score", "edit_score_only"]
)
def test_writers_refuse_when_the_shards_cannot_be_inspected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, writer: str
) -> None:
    from inspect_ai._util.file import filesystem

    merged, shards = _paths(tmp_path)
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    merge_eval_log_shards(merged)
    log = read_eval_log(merged)
    before = Path(merged).read_bytes(), _files(shards), log.model_dump_json()

    def denied(self: Any, path: str, **kwargs: Any) -> Any:
        raise PermissionError(f"denied: {path}")

    # fsspec's exists() returns False on this error
    with monkeypatch.context() as patched:
        patched.setattr(type(filesystem(shards).fs), "info", denied)
        with pytest.raises(PermissionError, match="denied"):
            _write_with(writer, log)
    assert (Path(merged).read_bytes(), _files(shards), log.model_dump_json()) == before

    # genuine absence: once the merge has deleted the shards, the same call runs
    assert merge_eval_log_shards(merged, delete_shards=True).shards_deleted
    _write_with(writer, read_eval_log(merged))


@pytest.mark.parametrize(
    "left",
    ["object", "root-marker", "shard-marker", "checkpoint-marker", "object-reported"],
)
async def test_a_partial_remote_delete_is_reported_and_finished_by_a_rerun(
    s3_shards: tuple[str, str],
    s3_root: str,
    monkeypatch: pytest.MonkeyPatch,
    left: str,
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    client = boto3.client("s3")
    shards = f"{s3_root}/{NAME}.shards"
    markers = [f"{shards}/", f"{shards}/0/", f"{shards}/1/x.checkpoints/"]
    for key in markers:
        client.put_object(Bucket="test-bucket", Key=key, Body=b"")
    await merge_eval_log_shards_async(merged)
    merged_key = f"{s3_root}/{NAME}.eval"
    before = client.get_object(Bucket="test-bucket", Key=merged_key)["Body"].read()
    worker = next(k for k in _s3_keys(f"{shards}/1/") if k.endswith(".eval"))
    kept = {
        "object": worker,
        "root-marker": markers[0],
        "shard-marker": markers[1],
        "checkpoint-marker": markers[2],
        "object-reported": worker,
    }[left]
    reported = left == "object-reported"

    class Denying:
        """A client whose DeleteObjects leaves `kept`, reporting it or not."""

        def __init__(self, client: Any) -> None:
            self._client = client

        def __getattr__(self, name: str) -> Any:
            return getattr(self._client, name)

        def delete_objects(self, Bucket: str, Delete: dict[str, Any]) -> Any:
            objects = [o for o in Delete["Objects"] if o["Key"] != kept]
            response = self._client.delete_objects(
                Bucket=Bucket, Delete={**Delete, "Objects": objects}
            )
            if reported and len(objects) < len(Delete["Objects"]):
                error = {"Key": kept, "Code": "AccessDenied", "Message": "denied"}
                response["Errors"] = [error]
            return response

    s3_client = AsyncFilesystem.s3_client
    monkeypatch.setattr(
        AsyncFilesystem, "s3_client", lambda self: Denying(s3_client(self))
    )
    match = "AccessDenied" if reported else "left objects behind"
    with pytest.raises(ShardSetError, match=match) as refused:
        await merge_eval_log_shards_async(merged, delete_shards=True)
    monkeypatch.undo()
    assert kept in str(refused.value)
    assert _s3_keys(f"{s3_root}/") == sorted([merged_key, kept])
    assert (
        client.get_object(Bucket="test-bucket", Key=merged_key)["Body"].read() == before
    )
    result = await merge_eval_log_shards_async(merged, delete_shards=True)
    assert result.shards_deleted and not result.written
    assert _s3_keys(f"{s3_root}/") == [merged_key]


@skip_if_asyncio
async def test_s3_shards_are_deleted_under_a_configured_trio_backend(
    s3_shards: tuple[str, str], s3_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    # set after the workers ran, as a Trio program's merge would see it
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", "trio")
    result = await merge_eval_log_shards_async(merged, delete_shards=True)
    assert result.written and result.shards_deleted
    assert _s3_keys(f"{s3_root}/") == [f"{s3_root}/{NAME}.eval"]


@skip_if_asyncio
async def test_sync_writers_check_s3_shards_under_a_configured_trio_backend(
    s3_shards: tuple[str, str], s3_root: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async, recompute_metrics
    from inspect_ai.scorer import ScoreEdit

    merged, _ = s3_shards
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", "trio")
    client = boto3.client("s3")

    async def merged_log() -> EvalLog:
        # read from bytes: the S3 log reader builds s3fs, which a configured
        # Trio backend refuses
        key = f"{s3_root}/{NAME}.eval"
        body = client.get_object(Bucket="test-bucket", Key=key)["Body"].read()
        log = await read_eval_log_async(BytesIO(body))
        log.location = merged
        return log

    def write(writer: str, log: EvalLog) -> None:
        if writer == "recompute_metrics":
            recompute_metrics(log)
        else:
            edit = ScoreEdit(value="I")
            recompute = writer == "edit_score"
            edit_score(log, 1, "match", edit, recompute_metrics=recompute, epoch=1)

    writers = ["recompute_metrics", "edit_score", "edit_score_only"]
    await merge_eval_log_shards_async(merged)
    for writer in writers:
        with pytest.raises(ShardSetError, match="shards that still exist"):
            write(writer, await merged_log())
    result = await merge_eval_log_shards_async(merged, delete_shards=True)
    assert result.shards_deleted
    for writer in writers:
        write(writer, await merged_log())


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
        merge_eval_log_shards(f"s3://test-bucket/{location}", delete_shards=delete)
    assert [_s3_objects(root) for root in roots] == before


def test_a_literal_percent_sign_in_an_s3_name_merges(
    s3_shards: tuple[str, str], s3_root: str
) -> None:
    _s3_copy(f"{s3_root}/{NAME}.shards/", f"{s3_root}/{NAME}%23tag.shards/")
    merged = f"s3://test-bucket/{s3_root}/{NAME}%23tag.eval"
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.written and result.shards_deleted
    assert result.log.status == "success"
    assert not _s3_keys(f"{s3_root}/{NAME}%23tag.shards/")
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
        await merge_eval_log_shards_async(merged, delete_shards=True)
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
        result = await merge_eval_log_shards_async(merged, sample_ids=[1, 2, 3])
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
    for delete in (False, True):
        with pytest.raises(ShardSetError, match=match):
            await merge_eval_log_shards_async(
                merged, sample_ids=[1, 2, 3], delete_shards=delete
            )
    assert _s3_objects(f"{s3_root}/") == before


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
    for delete in (False, True):
        with pytest.raises(ShardSetError, match=_BACKSLASH):
            merge_eval_log_shards(merged, delete_shards=delete)
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
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.written and result.shards_deleted
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
        result = merge_eval_log_shards(merged, sample_ids=[1, 2, 3])
        assert result.log.status == "success"
    # shard 1's worker, in a directory not named with digits
    client.copy_object(
        Bucket="test-bucket",
        Key=f"{shards}/{name}/worker.eval",
        CopySource={"Bucket": "test-bucket", "Key": held},
    )
    client.delete_object(Bucket="test-bucket", Key=held)
    before = _s3_objects(f"{s3_root}/")
    for delete in (False, True):
        with pytest.raises(ShardSetError, match=match):
            merge_eval_log_shards(
                merged, sample_ids=list(range(1, 7)), delete_shards=delete
            )
    assert _s3_objects(f"{s3_root}/") == before


def _merged_at(s3_shards: tuple[str, str], s3_root: str, name: str) -> EvalLog:
    """The merged log of `s3_shards`, located at `name` with its shards copied beside it."""
    merged, _ = s3_shards
    log = merge_eval_log_shards(merged).log
    _s3_copy(f"{s3_root}/{NAME}.shards/", f"{s3_root}/{name}.shards/")
    full = read_eval_log(merged)
    full.location = f"s3://test-bucket/{s3_root}/{name}.eval"
    assert log.eval.shards is not None and full.eval.shards is not None
    return full


@pytest.mark.parametrize("backend", ["asyncio", "trio"])
@pytest.mark.parametrize(
    "name,match",
    [(f"{NAME}#tag", "S3 would read it as"), (f"{NAME}%23tag", "still exist")],
    ids=["fragment", "literal-percent"],
)
def test_s3_writer_guards_refuse_a_location_s3_would_read_as_another_key(
    s3_shards: tuple[str, str],
    s3_root: str,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    match: str,
    backend: str,
) -> None:
    from inspect_ai.log._shards._live import (
        check_shards_merged,
        check_shards_merged_async,
    )

    log = _merged_at(s3_shards, s3_root, name)
    monkeypatch.setenv("INSPECT_ASYNC_BACKEND", backend)
    with pytest.raises(ShardSetError, match=match):
        anyio.run(check_shards_merged_async, log, "rescore", backend=backend)
    with pytest.raises(ShardSetError, match=match):
        check_shards_merged(log, "rescore")


@pytest.mark.parametrize(
    "writer", ["recompute_metrics", "edit_score", "edit_score_only", "score"]
)
def test_s3_writers_refuse_a_location_s3_would_read_as_another_key(
    s3_shards: tuple[str, str], s3_root: str, writer: str
) -> None:
    from inspect_ai import score
    from inspect_ai.log import recompute_metrics
    from inspect_ai.scorer import ScoreEdit

    log = _merged_at(s3_shards, s3_root, f"{NAME}#tag")
    before = log.model_dump_json(), _s3_objects(f"{s3_root}/")
    with pytest.raises(ShardSetError, match="S3 would read it as"):
        if writer == "recompute_metrics":
            recompute_metrics(log)
        elif writer == "score":
            score(log, [match()], action="overwrite")
        else:
            edit = ScoreEdit(value="I")
            recompute = writer == "edit_score"
            edit_score(log, 1, "match", edit, recompute_metrics=recompute, epoch=1)
    assert (log.model_dump_json(), _s3_objects(f"{s3_root}/")) == before


async def test_a_sibling_prefix_is_not_a_remnant_of_a_remote_delete(
    s3_shards: tuple[str, str], s3_root: str
) -> None:
    from inspect_ai.log import merge_eval_log_shards_async

    merged, _ = s3_shards
    client = boto3.client("s3")
    sibling = [f"{s3_root}/{NAME}.shards-other/", f"{s3_root}/{NAME}.shards-other/x"]
    for key in sibling:
        client.put_object(Bucket="test-bucket", Key=key, Body=b"")
    result = await merge_eval_log_shards_async(merged, delete_shards=True)
    assert result.shards_deleted
    assert _s3_keys(f"{s3_root}/") == sorted([f"{s3_root}/{NAME}.eval", *sibling])


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
    first = merge_eval_log_shards(merged).log
    assert first.results is not None
    assert first.results.scores == unsharded.results.scores
    # incremental: shard 0's samples are carried
    _run(shards, "1", task, sample_id=[4, 5, 6])
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.written and result.shards_deleted
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
    result = merge_eval_log_shards(merged, delete_shards=True)
    assert result.shards_deleted and result.log.results is not None
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
    with pytest.raises(ShardSetError, match="Sample '5' .* has no sample_init event"):
        merge_eval_log_shards(merged, delete_shards=True)
    assert not os.path.exists(merged) and _files(shards) == before


def test_writer_refusal_of_an_incomplete_merge_says_how_to_finish(
    tmp_path: Path,
) -> None:
    from inspect_ai.log import recompute_metrics

    merged, shards = _paths(tmp_path)
    _run(shards, "0", sample_id=[1, 2, 3])
    _as_running(_run(shards, "1", sample_id=[4, 5, 6]), keep={(4, 1)})
    merge_eval_log_shards(merged, allow_incomplete=True)
    with pytest.raises(
        ShardSetError, match="incomplete \\(started\\): re-run the incomplete shards"
    ):
        recompute_metrics(read_eval_log(merged))


def test_each_writer_checks_for_shards_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inspect_ai.log._shards import _live

    merged, shards = _paths(tmp_path)
    task = _graded_task(Epochs(2, at_least(1, value=0.5)))
    _run(shards, "0", task, sample_id=[1, 2, 3])
    _run(shards, "1", task, sample_id=[4, 5, 6])
    merge_eval_log_shards(merged, delete_shards=True)

    checks: list[str] = []
    shards_dir = _live._shards_dir

    def counted(log: EvalLog) -> str | None:
        checks.append(log.location)
        return shards_dir(log)

    monkeypatch.setattr(_live, "_shards_dir", counted)
    for writer in ["edit_score", "cli"]:
        checks.clear()
        _write_with(writer, read_eval_log(merged))
        assert len(checks) == 1, writer
