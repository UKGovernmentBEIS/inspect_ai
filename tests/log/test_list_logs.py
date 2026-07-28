from os.path import dirname, join
from pathlib import Path

from inspect_ai.log import EvalLog, list_eval_logs, list_eval_logs_async

file = Path(__file__)

ignored_files = ["ignore.json"]


def log_dir() -> str:
    return join(dirname(file), "test_list_logs")


def test_list_logs():
    logs = list_eval_logs(log_dir(), formats=["eval", "json"])
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def test_list_logs_async():
    logs = await list_eval_logs_async(log_dir(), formats=["eval", "json"])
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def test_list_logs_async_matches_sync():
    sync_names = sorted(
        log.name for log in list_eval_logs(log_dir(), formats=["eval", "json"])
    )
    async_names = sorted(
        log.name
        for log in await list_eval_logs_async(log_dir(), formats=["eval", "json"])
    )

    assert async_names == sync_names


async def test_list_logs_async_filter():
    def is_eval_format(log: EvalLog) -> bool:
        return log.location.endswith(".eval")

    logs = await list_eval_logs_async(
        log_dir(), formats=["eval", "json"], filter=is_eval_format
    )

    assert len(logs) == 2
    assert all(log.name.endswith(".eval") for log in logs)


async def test_list_logs_async_filter_excludes_all():
    logs = await list_eval_logs_async(
        log_dir(), formats=["eval", "json"], filter=lambda log: False
    )

    assert logs == []


async def test_list_logs_async_missing_dir(tmp_path: Path):
    logs = await list_eval_logs_async(str(tmp_path / "does-not-exist"))

    assert logs == []
