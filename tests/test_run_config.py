import json
from pathlib import Path
from typing import Any, get_type_hints
from unittest.mock import patch

import pytest
import yaml

from inspect_ai import RunConfig, Task, eval, eval_async, read_run_config, task
from inspect_ai._eval.run_config import merge_run_config_params
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


def test_merge_run_config_params_follows_cli_precedence() -> None:
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


@task
def run_config_greeting(greeting: str = "Hello", repeats: int = 1) -> Task:
    return Task(dataset=[Sample(input=greeting) for _ in range(repeats)])


GREETING_TASK = "tests/test_run_config.py@run_config_greeting"
GREETING_CONFIG: dict[str, Any] = {
    "task": {"task": GREETING_TASK, "args": {"greeting": "Hi", "repeats": 2}},
    "model": "mockllm/model",
    "generate_config": {"temperature": 0.25},
    "eval_config": {"epochs": 2},
    "tags": ["from-file"],
}


def write_run_config(tmp_path: Path, config: dict[str, Any]) -> str:
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(config))
    return str(path)


def test_eval_run_config_applies_file(tmp_path: Path) -> None:
    log = eval(
        run_config=write_run_config(tmp_path, GREETING_CONFIG),
        log_dir=str(tmp_path),
        display="none",
    )[0]
    assert log.status == "success"
    assert log.eval.task_args == {"greeting": "Hi", "repeats": 2}
    assert log.eval.model == "mockllm/model"
    assert log.plan.config.temperature == 0.25
    assert log.eval.config.epochs == 2
    assert log.eval.tags == ["from-file"]


def test_eval_run_config_supplied_arguments_take_precedence(tmp_path: Path) -> None:
    log = eval(
        run_config=write_run_config(tmp_path, GREETING_CONFIG),
        task_args={"repeats": 3},
        temperature=0.75,
        epochs=1,
        log_dir=str(tmp_path),
        display="none",
    )[0]
    assert log.eval.task_args == {"greeting": "Hi", "repeats": 3}
    assert log.plan.config.temperature == 0.75
    assert log.eval.config.epochs == 1
    assert log.eval.tags == ["from-file"]


def test_eval_run_config_positional_task_replaces_file_task(tmp_path: Path) -> None:
    config = {
        "task": GREETING_TASK,
        "model": "mockllm/model",
        "generate_config": {"temperature": 0.25},
    }
    log = eval(
        Task(dataset=[Sample(input="positional")], name="positional"),
        run_config=write_run_config(tmp_path, config),
        log_dir=str(tmp_path),
        display="none",
    )[0]
    assert log.eval.task == "positional"
    assert log.plan.config.temperature == 0.25


async def test_eval_async_run_config(tmp_path: Path) -> None:
    logs = await eval_async(
        run_config=write_run_config(tmp_path, GREETING_CONFIG),
        log_dir=str(tmp_path),
    )
    assert logs[0].eval.task_args == {"greeting": "Hi", "repeats": 2}
    assert logs[0].eval.model == "mockllm/model"
    assert logs[0].plan.config.temperature == 0.25


@pytest.mark.parametrize("key", ["task_args", "model_args"])
def test_eval_run_config_merges_args_file_by_key(tmp_path: Path, key: str) -> None:
    args = {"greeting": "Hi", "repeats": 2}
    config = GREETING_CONFIG | {"model": {"model": "mockllm/model", "args": args}}
    args_file = tmp_path / "args.yaml"
    args_file.write_text(yaml.safe_dump({"repeats": 3}))
    supplied: dict[str, Any] = {key: str(args_file)}
    log = eval(
        run_config=write_run_config(tmp_path, config),
        log_dir=str(tmp_path),
        display="none",
        **supplied,
    )[0]
    assert getattr(log.eval, key) == {"greeting": "Hi", "repeats": 3}


def test_eval_run_config_defers_role_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the file's grader is never constructed, so its provider needs no key
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = GREETING_CONFIG | {"model_roles": {"grader": {"model": "openai/gpt-4o"}}}
    log = eval(
        run_config=write_run_config(tmp_path, config),
        model_roles={"grader": "mockllm/grader"},
        log_dir=str(tmp_path),
        display="none",
    )[0]
    assert log.status == "success"
    assert log.eval.model_roles is not None
    grader = log.eval.model_roles["grader"]
    assert isinstance(grader, ModelConfig)
    assert grader.model == "mockllm/grader"


@pytest.mark.parametrize("run_config", [None, ""])
def test_eval_without_run_config_file(tmp_path: Path, run_config: str | None) -> None:
    log = eval(
        Task(dataset=[Sample(input="Hello")]),
        model="mockllm/model",
        run_config=run_config,
        log_dir=str(tmp_path),
        display="none",
    )[0]
    assert log.status == "success"


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
