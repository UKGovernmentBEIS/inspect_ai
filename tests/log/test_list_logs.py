from os.path import dirname, join
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_asyncio

from inspect_ai.log import list_eval_logs, list_eval_logs_async

file = Path(__file__)

log_dir = join(dirname(file), "test_list_logs")

ignored_files = ["ignore.json"]


def test_list_logs():
    logs = list_eval_logs(log_dir, formats=["eval", "json"])
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def test_list_logs_async_filter():
    logs = await list_eval_logs_async(
        log_dir, formats=["eval", "json"], filter=lambda log: True
    )
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)


async def test_list_logs_async_header_fallback():
    # custom.eval has a non-conforming filename, so its task/task_id must be
    # resolved by reading the log header — verify this works on both backends
    # (under trio a sync header read would silently degrade to empty fields)
    logs = await list_eval_logs_async(log_dir, formats=["eval", "json"])
    custom = next(log for log in logs if log.name.endswith("custom.eval"))
    assert custom.task == "input_task"
    assert custom.task_id == "hxs4q9azL3ySGkjJirypKZ"


async def test_list_logs_unfiltered_in_async_context():
    # unfiltered sync listing is backend-agnostic (the trio guard is filter-only)
    logs = list_eval_logs(log_dir, formats=["eval", "json"])
    assert len(logs) == 3


@skip_if_asyncio
async def test_list_logs_filter_trio_guard():
    with pytest.raises(RuntimeError, match="list_eval_logs_async"):
        list_eval_logs(log_dir, formats=["eval", "json"], filter=lambda log: True)
