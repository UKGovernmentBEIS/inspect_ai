from os.path import dirname, join
from pathlib import Path

from inspect_ai.log import list_eval_logs
from inspect_ai.log._file import read_eval_log_sample_summaries

file = Path(__file__)


def test_sample_summaries():
    logs = list_eval_logs(
        join(dirname(file), "test_list_logs"), formats=["eval", "json"]
    )

    for log in logs:
        summaries = read_eval_log_sample_summaries(log)
        assert len(summaries) > 0
