import os
from pathlib import Path

import anyio
import boto3
import pytest

from inspect_ai._util.asyncfiles import AsyncFilesystem, DirListing
from inspect_ai._util.file import FileInfo, local_path
from inspect_ai.log._file import is_log_file
from inspect_ai.log._shards._walk import (
    ShardDir,
    ShardSetListing,
    attempt_sort_key,
    is_shard_path,
    list_shard_set,
)

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
    assert {f"s3://test-bucket/{key}" for key in keys} - shard_paths == {
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
    assert listing == ShardSetListing(shards=[], stray=[])


async def test_list_shard_set_leaves_out_a_shard_removed_during_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shards_dir = tmp_path / "run.shards"
    _touch(shards_dir / "0" / f"{T1}_task_a.eval")
    _touch(shards_dir / "1" / f"{T1}_task_b.eval")
    original = AsyncFilesystem.list_dir

    async def removed(self: AsyncFilesystem, base: str) -> DirListing:
        if base.endswith("/1"):
            raise FileNotFoundError(base)
        return await original(self, base)

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

    async def gated(self: AsyncFilesystem, base: str) -> DirListing:
        nonlocal in_flight, peak
        if base == str(shards_dir):
            return await original(self, base)
        in_flight += 1
        peak = max(peak, in_flight)
        if in_flight == 32:
            full.set()
        await full.wait()
        in_flight -= 1
        return await original(self, base)

    monkeypatch.setattr(AsyncFilesystem, "list_dir", gated)
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, str(shards_dir))
    assert peak == 32
    assert len(listing.shards) == 40


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

    async def blocked(self: AsyncFilesystem, base: str) -> DirListing:
        nonlocal started, cancelled
        if base == str(shards_dir):
            return await original(self, base)
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
    assert empty == ShardSetListing(shards=[], stray=[])


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

    async def emptied(self: AsyncFilesystem, base: str) -> DirListing:
        if base == f"{shards_dir}/1":
            s3.delete_object(Bucket="test-bucket", Key=f"{prefix}/1/{T1}_task_a.eval")
        return await original(self, base)

    monkeypatch.setattr(AsyncFilesystem, "list_dir", emptied)
    async with AsyncFilesystem() as fs:
        listing = await list_shard_set(fs, shards_dir)
    assert [s.name for s in listing.shards] == ["0"]


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
