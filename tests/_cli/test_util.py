from dataclasses import dataclass

import pytest

from inspect_ai._cli.util import (
    parse_model_role_cli_args,
)
from inspect_ai.model import Model


@dataclass
class ModelRoleParameters:
    role_name: str
    parsed_type: type[Model] | type[str]
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class ModelRoleTestCase:
    cli_args: tuple[str, ...] | list[str] | None
    params: list[ModelRoleParameters]
    env_vars: dict[str, str] | None = None


test_cases = [
    # YAML inline format
    ModelRoleTestCase(
        cli_args=(
            "critic={model: mockllm/model, temperature: 0.2, max_tokens: 10000}",
            "grader={model: mockllm/model, temperature: 0.5, max_tokens: 1000}",
        ),
        params=[
            ModelRoleParameters(
                role_name="critic", temperature=0.2, max_tokens=10000, parsed_type=Model
            ),
            ModelRoleParameters(
                role_name="grader", temperature=0.5, max_tokens=1000, parsed_type=Model
            ),
        ],
    ),
    # JSON inline format
    ModelRoleTestCase(
        cli_args=(
            'critic={"model": "mockllm/model", "temperature": 0.2, "max_tokens": 10000}',
            'grader={"model": "mockllm/model", "temperature": 0.5, "max_tokens": 1000}',
        ),
        params=[
            ModelRoleParameters(
                role_name="critic", temperature=0.2, max_tokens=10000, parsed_type=Model
            ),
            ModelRoleParameters(
                role_name="grader", temperature=0.5, max_tokens=1000, parsed_type=Model
            ),
        ],
    ),
    # Simple key-value format
    ModelRoleTestCase(
        cli_args=("critic=mockllm/model", "grader=mockllm/model"),
        params=[
            ModelRoleParameters(role_name="critic", parsed_type=str),
            ModelRoleParameters(role_name="grader", parsed_type=str),
        ],
    ),
    # Model roles should use default model if no model is specified
    ModelRoleTestCase(
        cli_args=(
            'critic={"temperature": 0.2, "max_tokens": 10000}',
            'grader={"temperature": 0.5, "max_tokens": 1000}',
        ),
        params=[
            ModelRoleParameters(
                role_name="critic", temperature=0.2, max_tokens=10000, parsed_type=Model
            ),
            ModelRoleParameters(
                role_name="grader", temperature=0.5, max_tokens=1000, parsed_type=Model
            ),
        ],
        env_vars={"INSPECT_EVAL_MODEL": "mockllm/model"},
    ),
]


@pytest.mark.parametrize("test_case", test_cases)
def test_parse_model_role_cli_args(monkeypatch, test_case):
    if test_case.env_vars:
        [monkeypatch.setenv(key, value) for key, value in test_case.env_vars.items()]

    parsed_result = parse_model_role_cli_args(test_case.cli_args)

    for params in test_case.params:
        assert params.role_name in parsed_result
        assert isinstance(parsed_result[params.role_name], params.parsed_type)
        if params.parsed_type == Model:
            assert (
                parsed_result[params.role_name].config.temperature == params.temperature
            )
            assert (
                parsed_result[params.role_name].config.max_tokens == params.max_tokens
            )


@pytest.mark.parametrize(
    ("args", "expected_substring"),
    [
        (
            ("grader={model: mockllm/model, temperature: 0.5, max_tokens: 1000",),
            "Could not parse model role arguments",
        ),  # invalid yaml format - missing closing brace
        (
            ("grader={model: mockllm/model, temperature: oops, max_tokens: 1000}",),
            "Invalid config",
        ),  # invalid temperature value
    ],
)
def test_parse_model_role_cli_invalid_args_raises_error(args, expected_substring):
    with pytest.raises(ValueError) as e:
        parse_model_role_cli_args(args)
    assert expected_substring in str(e.value)


def test_parse_no_model_role_cli_args():
    assert parse_model_role_cli_args(None) == {}
