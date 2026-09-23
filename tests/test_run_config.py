import json
from pathlib import Path
from typing import Any, get_type_hints
from unittest.mock import patch

import pytest

from inspect_ai import RunConfig, Task, eval, merge_run_config_params, read_run_config
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import file
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, Model, ModelConfig, ModelRoles, get_model
from inspect_ai.model._util import resolve_model_roles


@pytest.mark.parametrize("location", ["path", "uri", "remote"])
def test_read_run_config_without_resolving_models(
    tmp_path: Path, location: str
) -> None:
    content = json.dumps(
        {
            "task": "not_installed/task",
            "solver": "not_installed/solver",
            "model": {"model": "not_installed/main"},
            "model_roles": {
                "grader": {"model": "not_installed/grader"},
                "panel": [
                    {"model": "not_installed/a"},
                    {"model": "not_installed/b"},
                ],
            },
        }
    )
    if location == "remote":
        config_file = "memory://run-config-api/run.json"
        with file(config_file, "w") as stream:
            stream.write(content)
    else:
        path = tmp_path / ("run.json" if location == "uri" else "run config.json")
        path.write_text(content)
        config_file = path.as_uri() if location == "uri" else str(path)

    with patch(
        "inspect_ai.model._model.get_model",
        side_effect=AssertionError("Models must not be instantiated"),
    ):
        config = read_run_config(config_file)
        assert isinstance(config, RunConfig)
        params = config.to_params(resolve_models=False)

    assert params["tasks"] == "not_installed/task"
    assert params["model"] == "not_installed/main"
    assert params["model_roles"] == config.model_roles
    assert isinstance(params["model_roles"]["grader"], ModelConfig)
    assert all(
        isinstance(model, ModelConfig) for model in params["model_roles"]["panel"]
    )
    assert RunConfig.model_validate_json(config.model_dump_json()) == config


def test_read_run_config_yaml(tmp_path: Path) -> None:
    path = tmp_path / "run.yaml"
    path.write_text("task: example/task\ngenerate_config:\n  temperature: 0.25\n")
    config = read_run_config(str(path))
    assert config.task == "example/task"
    assert config.generate_config.temperature == 0.25


@pytest.mark.parametrize(
    "data, message",
    [
        ({"unknown": True}, "Additional properties are not allowed"),
        ({"generate_config": {"unknown": True}}, "Unknown generate_config fields"),
        ({"eval_config": {"unknown": True}}, "Unknown eval_config fields"),
    ],
)
def test_read_run_config_validation_errors(
    tmp_path: Path, data: dict[str, Any], message: str
) -> None:
    path = tmp_path / "run.json"
    path.write_text(json.dumps(data))
    with pytest.raises(PrerequisiteError, match=message) as error:
        read_run_config(str(path))
    assert f"Invalid run config '{path}':" in str(error.value)


def test_read_run_config_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PrerequisiteError, match="does not exist"):
        read_run_config(str(tmp_path / "missing.yaml"))


def test_run_config_resolves_models_only_on_conversion() -> None:
    config = RunConfig.model_validate(
        {
            "model_roles": {
                "grader": {"model": "mockllm/grader", "config": {"temperature": 0.2}},
                "panel": [{"model": "mockllm/a"}, {"model": "mockllm/b"}],
            }
        }
    )
    params = config.to_params()
    assert isinstance(params["model_roles"]["grader"], Model)
    assert params["model_roles"]["grader"].config.temperature == 0.2
    assert all(isinstance(model, Model) for model in params["model_roles"]["panel"])
    assert isinstance(config.model_roles["grader"], ModelConfig)


def test_run_config_deferred_roles_are_independent() -> None:
    config = RunConfig.model_validate(
        {
            "model_roles": {
                "grader": {
                    "model": "mockllm/grader",
                    "config": {"temperature": 0.2},
                    "args": {"nested": {"values": [1]}},
                },
                "panel": [{"model": "mockllm/a"}, {"model": "mockllm/b"}],
            }
        }
    )
    expected = config.model_copy(deep=True).model_roles
    first = config.to_params(resolve_models=False)["model_roles"]
    second = config.to_params(resolve_models=False)["model_roles"]

    first["grader"].model = "mockllm/changed"
    first["grader"].config.temperature = 0.9
    first["grader"].args["nested"]["values"].append(2)
    first["panel"][0].config.temperature = 0.8
    first["panel"].append(ModelConfig(model="mockllm/c"))

    assert config.model_roles == expected
    assert second == expected
    second["panel"].clear()
    assert len(first["panel"]) == 3
    assert config.model_roles == expected


@pytest.mark.parametrize(
    "function, annotation, expected",
    [
        (
            "model_roles_to_model_roles_config",
            "model_roles",
            dict[str, Model | list[Model]] | None,
        ),
        (
            "model_roles_config_to_model_roles",
            "return",
            dict[str, Model | list[Model]] | None,
        ),
        ("model_to_model_config", "model", Model),
        ("model_config_to_model", "return", Model),
    ],
)
def test_model_config_helper_type_hints(
    function: str, annotation: str, expected: Any
) -> None:
    from inspect_ai.model import _model_config

    assert get_type_hints(getattr(_model_config, function))[annotation] == expected


def test_run_config_merge_public_api() -> None:
    base = {"task_args": {"a": 1, "b": 2}, "score": False, "tags": ["base"]}
    overrides = {"task_args": {"b": None}, "score": True, "tags": []}
    assert merge_run_config_params(base, overrides) == {
        "task_args": {"a": 1, "b": None},
        "score": False,
        "tags": [],
    }
    assert base == {"task_args": {"a": 1, "b": 2}, "score": False, "tags": ["base"]}
    assert overrides == {"task_args": {"b": None}, "score": True, "tags": []}


def test_model_roles_accept_deferred_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_type_hints(eval)["model_roles"] == ModelRoles | None
    # a provider get_model memoizes (mockllm never is), so a deferred config
    # that resolved to the shared instance would show up here (#4450)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = ModelConfig(model="openai/gpt-4o", config=GenerateConfig(temperature=0.2))
    roles: ModelRoles = {"grader": config, "other": config, "panel": [config]}
    resolved = resolve_model_roles(roles)
    assert resolved is not None
    grader = resolved["grader"]
    assert isinstance(grader, Model)
    assert grader.config.temperature == 0.2
    assert grader.role == "grader"
    assert resolved["grader"] is not resolved["other"]
    assert isinstance(resolved["panel"], Model)
    shared = get_model("openai/gpt-4o")
    assert shared is not grader
    assert shared.role is None


def test_run_config_deferred_models_eval_and_log(tmp_path: Path) -> None:
    config = RunConfig.model_validate(
        {
            "model": "mockllm/model",
            "model_roles": {
                "grader": {"model": "mockllm/grader", "config": {"temperature": 0.2}},
                "panel": [{"model": "mockllm/a"}, {"model": "mockllm/b"}],
            },
        }
    )
    logs = eval(
        Task(dataset=[Sample(input="Hello")]),
        **config.to_params(resolve_models=False),
        log_dir=str(tmp_path),
        display="none",
    )
    assert logs[0].status == "success"
    assert logs[0].eval.model_roles == config.model_roles


def test_run_config_cli_compatibility_imports(tmp_path: Path) -> None:
    from inspect_ai._cli.eval import (
        RunConfigInput,
        SolverInput,
        TaskInput,
        parse_run_config,
    )
    from inspect_ai._cli.eval import merge_run_config_params as cli_merge
    from inspect_ai._cli.util import parse_sandbox as cli_sandbox
    from inspect_ai._eval.run_config import SolverInput as SharedSolverInput
    from inspect_ai._eval.run_config import TaskInput as SharedTaskInput
    from inspect_ai.util._sandbox.environment import parse_sandbox

    assert RunConfigInput is RunConfig
    assert TaskInput is SharedTaskInput
    assert SolverInput is SharedSolverInput
    assert cli_merge is merge_run_config_params
    assert cli_sandbox is parse_sandbox
    path = tmp_path / "run.yaml"
    path.write_text("task: example/task\ngenerate_config:\n  temperature: 0.25\n")
    assert parse_run_config(str(path)) == read_run_config(str(path)).to_params()
