import pytest
from pydantic import ValidationError

from inspect_ai._eval.task.hf import (
    HFFieldSpec,
    HFScorer,
    HFSolver,
    HFTask,
    _record_to_sample_hf,
    _sanitize_choices,
    _sanitize_target,
    parse_task_spec,
)


@pytest.mark.parametrize(
    "task_spec,expected_repo_id,expected_name",
    [
        ("org/repo", "org/repo", None),
        ("org/repo/task1", "org/repo", "task1"),
        ("user/repo/name", "user/repo", "name"),
    ],
)
def test_parse_task_spec(task_spec, expected_repo_id, expected_name):
    repo_id, name = parse_task_spec(task_spec)
    assert repo_id == expected_repo_id
    assert name == expected_name


def test_parse_task_spec_invalid():
    with pytest.raises(ValueError, match="Expected 2 or 3 components"):
        parse_task_spec("invalid")


@pytest.mark.parametrize(
    "record,target,expected",
    [
        ({"answer": "B"}, "answer", "B"),
        ({"label": 0}, "label", "A"),
        ({"label": 1}, "label", "B"),
        ({"label": 25}, "label", "Z"),
        ({"value": "test"}, "literal:test", "test"),
        ({"value": "ignore"}, "literal:custom", "custom"),
    ],
)
def test_sanitize_target(record, target, expected):
    result = _sanitize_target(record, target)
    assert result == expected


@pytest.mark.parametrize(
    "record,choices,expected",
    [
        ({"a": "A", "b": "B"}, None, None),
        ({"choices": ["A", "B", "C"]}, "choices", ["A", "B", "C"]),
        ({"a": "A", "b": "B"}, ["a", "b"], ["A", "B"]),
        ({"x": "X", "y": "Y", "z": "Z"}, ["x", "z"], ["X", "Z"]),
    ],
)
def test_sanitize_choices(record, choices, expected):
    result = _sanitize_choices(record, choices)
    assert result == expected


def test_record_to_sample_hf_basic():
    record = {"question": "What is 2+2?", "answer": "4"}
    field_spec = HFFieldSpec(input="question", target="answer")
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "What is 2+2?"
    assert sample.target == "4"


def test_record_to_sample_hf_with_choices():
    record = {"q": "Pick one", "options": ["A", "B", "C"], "correct": 0}
    field_spec = HFFieldSpec(input="q", target="correct", choices="options")
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "Pick one"
    assert sample.target == "A"
    assert sample.choices == ["A", "B", "C"]


def test_record_to_sample_hf_with_metadata():
    record = {"input": "test", "target": "yes", "meta1": "val1", "meta2": "val2"}
    field_spec = HFFieldSpec(
        input="input", target="target", metadata=["meta1", "meta2"]
    )
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "test"
    assert sample.target == "yes"
    assert sample.metadata == {"meta1": "val1", "meta2": "val2"}


def test_record_to_sample_hf_with_literal_target():
    record = {"input": "test"}
    field_spec = HFFieldSpec(input="input", target="literal:fixed_answer")
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "test"
    assert sample.target == "fixed_answer"


# --- HFSolver validation tests ---


@pytest.mark.parametrize(
    "solver_name",
    [
        "prompt_template",
        "system_message",
        "user_message",
        "chain_of_thought",
        "use_tools",
        "generate",
        "self_critique",
        "multiple_choice",
    ],
)
def test_hf_solver_valid_names(solver_name):
    solver = HFSolver(name=solver_name)
    assert solver.name == solver_name
    assert solver.args == {}


def test_hf_solver_with_args():
    solver = HFSolver(name="prompt_template", args={"template": "Hello {input}"})
    assert solver.name == "prompt_template"
    assert solver.args == {"template": "Hello {input}"}


def test_hf_solver_invalid_name():
    with pytest.raises(ValidationError, match="Input should be"):
        HFSolver(name="invalid_solver")


# --- HFScorer validation tests ---


@pytest.mark.parametrize(
    "scorer_name",
    [
        "includes",
        "match",
        "pattern",
        "answer",
        "exact",
        "f1",
        "model_graded_qa",
        "model_graded_fact",
        "choice",
    ],
)
def test_hf_scorer_valid_names(scorer_name):
    scorer = HFScorer(name=scorer_name)
    assert scorer.name == scorer_name
    assert scorer.args == {}


def test_hf_scorer_with_args():
    scorer = HFScorer(name="model_graded_qa", args={"template": "custom"})
    assert scorer.name == "model_graded_qa"
    assert scorer.args == {"template": "custom"}


def test_hf_scorer_invalid_name():
    with pytest.raises(ValidationError, match="Input should be"):
        HFScorer(name="invalid_scorer")


# --- HFTask validation tests ---


def _valid_task_config():
    """Helper to create a minimal valid task configuration."""
    return {
        "field_spec": {"input": "question", "target": "answer"},
        "solvers": [{"name": "generate"}],
        "scorers": [{"name": "match"}],
    }


def test_hf_task_valid_minimal():
    config = _valid_task_config()
    task = HFTask.model_validate(config)
    assert task.config == "default"
    assert task.split == "test"
    assert task.epochs == 1
    assert len(task.solvers) == 1
    assert len(task.scorers) == 1


def test_hf_task_valid_full():
    config = {
        "id": "my_task",
        "config": "custom_config",
        "split": "train",
        "field_spec": {"input": "q", "target": "a", "choices": "opts"},
        "epochs": 3,
        "epoch_reducer": "mode",
        "solvers": [
            {"name": "system_message", "args": {"system_message": "Be helpful"}},
            {"name": "generate"},
        ],
        "scorers": [{"name": "choice"}],
    }
    task = HFTask.model_validate(config)
    assert task.id == "my_task"
    assert task.config == "custom_config"
    assert task.split == "train"
    assert task.epochs == 3
    assert task.epoch_reducer == "mode"
    assert len(task.solvers) == 2
    assert len(task.scorers) == 1


def test_hf_task_missing_solvers():
    config = {
        "field_spec": {"input": "question", "target": "answer"},
        "scorers": [{"name": "match"}],
    }
    with pytest.raises(ValidationError, match="solvers"):
        HFTask.model_validate(config)


def test_hf_task_missing_scorers():
    config = {
        "field_spec": {"input": "question", "target": "answer"},
        "solvers": [{"name": "generate"}],
    }
    with pytest.raises(ValidationError, match="scorers"):
        HFTask.model_validate(config)


def test_hf_task_empty_solvers():
    config = {
        "field_spec": {"input": "question", "target": "answer"},
        "solvers": [],
        "scorers": [{"name": "match"}],
    }
    with pytest.raises(ValidationError, match="at least 1"):
        HFTask.model_validate(config)


def test_hf_task_empty_scorers():
    config = {
        "field_spec": {"input": "question", "target": "answer"},
        "solvers": [{"name": "generate"}],
        "scorers": [],
    }
    with pytest.raises(ValidationError, match="at least 1"):
        HFTask.model_validate(config)


def test_hf_task_invalid_solver_name():
    config = {
        "field_spec": {"input": "question", "target": "answer"},
        "solvers": [{"name": "not_a_real_solver"}],
        "scorers": [{"name": "match"}],
    }
    with pytest.raises(ValidationError, match="Input should be"):
        HFTask.model_validate(config)


def test_hf_task_invalid_scorer_name():
    config = {
        "field_spec": {"input": "question", "target": "answer"},
        "solvers": [{"name": "generate"}],
        "scorers": [{"name": "not_a_real_scorer"}],
    }
    with pytest.raises(ValidationError, match="Input should be"):
        HFTask.model_validate(config)


def test_hf_task_rejects_extra_fields():
    config = _valid_task_config()
    config["unknown_field"] = "value"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HFTask.model_validate(config)


# --- epoch_reducer validation tests ---


@pytest.mark.parametrize(
    "epoch_reducer",
    [
        "max",
        "mode",
        "median",
        "mean",
        "pass_at_1",
        "pass_at_5",
        "pass_at_100",
        "at_least_1",
        "at_least_2",
        "at_least_10",
    ],
)
def test_hf_task_valid_epoch_reducer(epoch_reducer):
    config = _valid_task_config()
    config["epoch_reducer"] = epoch_reducer
    task = HFTask.model_validate(config)
    assert task.epoch_reducer == epoch_reducer


@pytest.mark.parametrize(
    "epoch_reducer",
    [
        "invalid",
        "pass_at",
        "pass_at_",
        "at_least",
        "at_least_",
        "majority",
        "average",
        "pass_at_abc",
        "at_least_xyz",
    ],
)
def test_hf_task_invalid_epoch_reducer(epoch_reducer):
    config = _valid_task_config()
    config["epoch_reducer"] = epoch_reducer
    with pytest.raises(ValidationError, match="epoch_reducer"):
        HFTask.model_validate(config)


def test_hf_task_epoch_reducer_none_is_valid():
    config = _valid_task_config()
    # epoch_reducer not specified (None) should be valid
    task = HFTask.model_validate(config)
    assert task.epoch_reducer is None


# --- epochs validation tests ---


def test_hf_task_epochs_minimum():
    config = _valid_task_config()
    config["epochs"] = 0
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        HFTask.model_validate(config)


def test_hf_task_epochs_negative():
    config = _valid_task_config()
    config["epochs"] = -1
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        HFTask.model_validate(config)
