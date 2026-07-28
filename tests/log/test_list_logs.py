from os.path import dirname, join
from pathlib import Path

import anyio
import pytest

from inspect_ai.log import list_eval_logs, list_eval_logs_async

file = Path(__file__)

log_dir = join(dirname(file), "test_list_logs")

ignored_files = ["ignore.json"]


def test_list_logs():
    logs = list_eval_logs(log_dir, formats=["eval", "json"])
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def _check_list_logs_async_filter() -> None:
    logs = await list_eval_logs_async(
        log_dir, formats=["eval", "json"], filter=lambda log: True
    )
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def test_list_logs_async_filter():
    await _check_list_logs_async_filter()


async def _check_list_logs_async_header_fallback() -> None:
    # custom.eval has a non-conforming filename, so its task/task_id must be
    # resolved by reading the log header — verify this works on both backends
    # (under trio a sync header read would silently degrade to empty fields)
    logs = await list_eval_logs_async(log_dir, formats=["eval", "json"])
    custom = next(log for log in logs if log.name.endswith("custom.eval"))
    assert custom.task == "input_task"
    assert custom.task_id == "hxs4q9azL3ySGkjJirypKZ"


async def test_list_logs_async_header_fallback():
    await _check_list_logs_async_header_fallback()


async def test_list_logs_unfiltered_in_async_context():
    # unfiltered sync listing is backend-agnostic (the trio guard is filter-only)
    logs = list_eval_logs(log_dir, formats=["eval", "json"])
    assert len(logs) == 3


# NOTE: The trio tests below use anyio.run(backend="trio") directly so the
# trio paths run on regular CI, which has no --runtrio leg (see the NOTE
# above the trio tests in test_eval_log.py).


def test_list_logs_filter_trio_guard():
    async def check() -> None:
        with pytest.raises(RuntimeError, match="list_eval_logs_async"):
            list_eval_logs(log_dir, formats=["eval", "json"], filter=lambda log: True)

    anyio.run(check, backend="trio")


def test_list_logs_async_filter_trio():
    anyio.run(_check_list_logs_async_filter, backend="trio")


def test_list_logs_async_header_fallback_trio():
    anyio.run(_check_list_logs_async_header_fallback, backend="trio")
