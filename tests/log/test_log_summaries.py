from os.path import dirname, join
from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, read_eval_log_sample_summaries

file = Path(__file__)


def test_sample_summaries() -> None:
    logs = list_eval_logs(
        join(dirname(file), "test_list_logs"), formats=["eval", "json"]
    )

    for log in logs:
        summaries = read_eval_log_sample_summaries(log)
        assert len(summaries) > 0


def test_sample_summaries_thin_metadata() -> None:
    task = Task(
        dataset=[
            Sample(input="Say hello.", metadata={"dict": dict(), "long": "a" * 2000})
        ]
    )
    log = eval(task, model="mockllm/model")[0]

    summaries = read_eval_log_sample_summaries(log.location)
    assert len(summaries) > 0
    assert "dict" not in summaries[0].metadata
    assert len(summaries[0].metadata["long"]) <= 1024
