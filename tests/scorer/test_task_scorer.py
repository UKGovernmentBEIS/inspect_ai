from inspect_ai import eval
from inspect_ai._eval.task.task import Task
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset._sources.csv import csv_dataset
from inspect_ai.scorer._answer import answer
from inspect_ai.scorer._classification import f1
from inspect_ai.scorer._metrics import accuracy, mean
from inspect_ai.scorer._metrics.std import bootstrap_stderr


def test_task_with_metrics():
    task = Task(scorer=f1(), metrics=[mean(), bootstrap_stderr()])

    # ensure that metrics themselves remain unchanged
    assert registry_info(task.metrics[0]).name == "inspect_ai/mean"
    assert registry_info(task.metrics[1]).name == "inspect_ai/bootstrap_stderr"
    assert task.scorer is not None

    # ensure that the task metrics are correctly applied to the scorer
    info = registry_info(task.scorer[0])
    assert registry_info(info.metadata["metrics"][0]).name == "inspect_ai/mean"

    info = registry_info(task.scorer[0])
    assert (
        registry_info(info.metadata["metrics"][1]).name == "inspect_ai/bootstrap_stderr"
    )

    # modify the task and ensure that the new metrics remain unchanged
    task.scorer.append(answer("word"))
    assert len(task.scorer) == 2
    info = registry_info(task.scorer[1])
    assert registry_info(info.metadata["metrics"][0]).name == "inspect_ai/accuracy"
    assert registry_info(info.metadata["metrics"][1]).name == "inspect_ai/stderr"


def test_task_score_results():
    task = Task(
        dataset=csv_dataset("tests/dataset/test_dataset/samples-md.csv"),
        scorer=f1(),
        metrics=[accuracy()],
    )

    # confirm the mean result is computed
    log = eval(task, model="mockllm/model", sandbox=False)
    assert len(log[0].results.scores) == 1
    assert len(log[0].results.scores[0].metrics) == 1
    assert "accuracy" in log[0].results.scores[0].metrics
    assert "mean" not in log[0].results.scores[0].metrics
    assert "stderr" not in log[0].results.scores[0].metrics


def test_score_results():
    task = Task(
        dataset=csv_dataset("tests/dataset/test_dataset/samples-md.csv"),
        scorer=f1(),
    )

    # confirm the mean result is computed
    log = eval(task, model="mockllm/model")
    assert len(log[0].results.scores) == 1
    assert len(log[0].results.scores[0].metrics) == 2
    assert "mean" in log[0].results.scores[0].metrics
    assert "stderr" in log[0].results.scores[0].metrics


def test_added_scores():
    task = Task(
        dataset=csv_dataset("tests/dataset/test_dataset/samples-md.csv"),
        scorer=f1(),
        metrics=[accuracy()],
    )
    task.scorer.append(answer("line"))

    log = eval(task, model="mockllm/model")
    assert len(log[0].results.scores) == 2
    assert len(log[0].results.scores[0].metrics) == 1
    assert "accuracy" in log[0].results.scores[0].metrics
    assert "mean" not in log[0].results.scores[0].metrics
    assert "stderr" not in log[0].results.scores[0].metrics

    assert len(log[0].results.scores[1].metrics) == 2
    assert "accuracy" in log[0].results.scores[1].metrics
    assert "stderr" in log[0].results.scores[1].metrics
