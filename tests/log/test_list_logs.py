from os.path import dirname, join
from pathlib import Path

from inspect_ai.log import list_eval_logs

file = Path(__file__)

ignored_files = ["ignore.json"]


def test_list_logs():
    logs = list_eval_logs(
        join(dirname(file), "test_list_logs"), formats=["eval", "json"]
    )
    names = [log.name for log in logs]

    assert len(logs) == 3
    assert all(file not in names for file in ignored_files)
