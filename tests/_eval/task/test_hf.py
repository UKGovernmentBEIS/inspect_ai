import pytest

from inspect_ai._eval.task.hf import (
    FieldSpecHF,
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
    field_spec = FieldSpecHF(input="question", target="answer")
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "What is 2+2?"
    assert sample.target == "4"


def test_record_to_sample_hf_with_choices():
    record = {"q": "Pick one", "options": ["A", "B", "C"], "correct": 0}
    field_spec = FieldSpecHF(input="q", target="correct", choices="options")
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "Pick one"
    assert sample.target == "A"
    assert sample.choices == ["A", "B", "C"]


def test_record_to_sample_hf_with_metadata():
    record = {"input": "test", "target": "yes", "meta1": "val1", "meta2": "val2"}
    field_spec = FieldSpecHF(
        input="input", target="target", metadata=["meta1", "meta2"]
    )
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "test"
    assert sample.target == "yes"
    assert sample.metadata == {"meta1": "val1", "meta2": "val2"}


def test_record_to_sample_hf_with_literal_target():
    record = {"input": "test"}
    field_spec = FieldSpecHF(input="input", target="literal:fixed_answer")
    sample = _record_to_sample_hf(record, field_spec)

    assert sample.input == "test"
    assert sample.target == "fixed_answer"
