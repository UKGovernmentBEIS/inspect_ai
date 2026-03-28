from inspect_ai import eval
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tasks import (
    harmactionseval,
    harmactionseval_dataset,
    load_harmactionseval_actions,
)


def test_harmactionseval_dataset_includes_calibration_sample() -> None:
    task = harmactionseval(limit=1)

    assert len(task.dataset) == 2
    assert task.dataset[0].metadata
    assert task.dataset[0].metadata["is_calibration"] is True
    assert task.dataset[1].metadata
    assert task.dataset[1].metadata["classification"] != "safe"


def test_harmactionseval_scores_harmful_action_with_retries() -> None:
    task = harmactionseval(k=2, limit=1)

    calibration = task.dataset[0].metadata
    harmful = task.dataset[1].metadata
    assert calibration
    assert harmful

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model",
                calibration["action"]["function"]["name"],
                calibration["action"]["function"]["arguments"],
            ),
            ModelOutput.from_content("mockllm/model", "I will not call the tool."),
            ModelOutput.for_tool_call(
                "mockllm/model",
                harmful["action"]["function"]["name"],
                harmful["action"]["function"]["arguments"],
            ),
        ],
    )

    [log] = eval(task, model=model)

    assert log.samples
    assert log.results
    assert log.results.scores[0].metrics["harm_at_k"].value == 1.0
    assert log.results.scores[0].metrics["safe_actions_at_k"].value == 0.0
    assert log.results.scores[0].metrics["calibration_success"].value == 1.0

    harmful_sample = log.samples[1]
    assert harmful_sample.scores

    score = harmful_sample.scores["harmactionseval"]
    assert score.value == 1
    assert score.answer == "harmful"
    assert score.metadata
    assert score.metadata["harmful_attempt"] == 2
    assert len(score.metadata["attempts"]) == 2
    assert score.metadata["attempts"][0]["tool_calls"] == []
    assert (
        score.metadata["attempts"][1]["tool_calls"][0]["function"]
        == harmful["action"]["function"]["name"]
    )


def test_harmactionseval_dataset_can_skip_calibration() -> None:
    dataset = harmactionseval_dataset(limit=1, include_calibration=False)

    assert len(dataset) == 1
    assert dataset[0].metadata
    assert dataset[0].metadata["is_calibration"] is False
    assert dataset[0].metadata["classification"] != "safe"


def test_harmactionseval_load_actions_filters_safe_rows() -> None:
    actions = load_harmactionseval_actions()

    assert actions
    assert all(action["classification"] != "safe" for action in actions)


def test_harmactionseval_scores_safe_when_tool_is_not_called() -> None:
    task = harmactionseval(k=2, limit=1, include_calibration=False)
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", "I will not call the tool."),
            ModelOutput.from_content("mockllm/model", "Still not calling the tool."),
        ],
    )

    [log] = eval(task, model=model)

    assert log.status == "success"
    assert log.results
    assert log.results.scores[0].metrics["harm_at_k"].value == 0.0
    assert log.results.scores[0].metrics["safe_actions_at_k"].value == 1.0
    assert log.results.scores[0].metrics["calibration_success"].value == 0.0

    assert log.samples
    assert log.samples[0].scores
    score = log.samples[0].scores["harmactionseval"]
    assert score.value == 0
    assert score.answer == "safe"
    assert score.metadata
    assert score.metadata["harmful_attempt"] == 0
    assert len(score.metadata["attempts"]) == 2


def test_harmactionseval_calibration_failure_marks_eval_error() -> None:
    task = harmactionseval(k=1, limit=1)
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", "No tool call.")],
    )

    [log] = eval(task, model=model)

    assert log.status == "error"
