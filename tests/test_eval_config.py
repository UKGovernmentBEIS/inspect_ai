import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner, Result
from pydantic import ValidationError

from inspect_ai import Epochs, Task, eval, task
from inspect_ai._cli.eval import (
    RunConfigInput,
    eval_command,
    eval_retry_command,
    eval_set_command,
    merge_run_config_params,
    parse_run_config,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.log import EvalConfig, EvalLog
from inspect_ai.log._file import list_eval_logs, read_eval_log
from inspect_ai.model import GenerateConfig, Model, get_model
from inspect_ai.solver import SolverSpec, solver
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


def run_eval_cli(args: list[str], env: dict[str, str | None] | None = None) -> Result:
    """Invoke `inspect eval` in-process via CliRunner.

    In-process invocation avoids the ~2s interpreter + package-import startup
    that a fresh `inspect` subprocess pays on every call. `eval_command` is the
    same click command `inspect eval` dispatches to, so CLI option parsing and
    config resolution are exercised identically.

    A value of `None` in `env` unsets that variable for the invocation (used to
    clear `INSPECT_EVAL_*` overrides that would otherwise leak in from the
    ambient environment or repo `.env`).
    """
    return CliRunner().invoke(eval_command, args, env=env)


def run_eval_retry_cli(
    args: list[str], env: dict[str, str | None] | None = None
) -> Result:
    """Invoke `inspect eval-retry` in-process via CliRunner.

    Counterpart to `run_eval_cli` for the `eval-retry` command (see that
    function for why we invoke the click command directly instead of spawning a
    subprocess).
    """
    return CliRunner().invoke(eval_retry_command, args, env=env)


def run_eval_set_cli(
    args: list[str], env: dict[str, str | None] | None = None
) -> Result:
    """Invoke `inspect eval-set` in-process via CliRunner.

    Counterpart to `run_eval_cli` for the `eval-set` command (see that function
    for why we invoke the click command directly instead of spawning a
    subprocess).
    """
    return CliRunner().invoke(eval_set_command, args, env=env)


def assert_cli_success(result: Result) -> None:
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"


def test_run_config_rejects_unknown_top_level_field():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RunConfigInput.model_validate({"unknown_field": "value"})


def test_run_config_rejects_unknown_generate_config_field():
    with pytest.raises(ValidationError, match="[Uu]nknown"):
        RunConfigInput.model_validate(
            {"generate_config": {"temperature": 0.5, "typo_field": 123}}
        )


def test_run_config_rejects_unknown_eval_config_field():
    with pytest.raises(ValidationError, match="[Uu]nknown"):
        RunConfigInput.model_validate({"eval_config": {"limit": 10, "bad_field": 1}})


@pytest.mark.parametrize(
    "config, expected",
    [
        ({}, {}),
        ({"task": None, "model": None, "solver": None, "sandbox": None}, {}),
        ({"tags": [], "metadata": {}, "model_roles": {}}, {}),
        ({"task": "task_ref"}, {"tasks": "task_ref"}),
        ({"task": {"task": "task_ref", "args": {}}}, {"tasks": "task_ref"}),
        (
            {"task": {"task": "task_ref", "args": {"value": None}}},
            {"tasks": "task_ref", "task_args": {"value": None}},
        ),
        ({"model": "mockllm/model"}, {"model": "mockllm/model"}),
        (
            {"model": {"model": "mockllm/model", "base_url": "", "args": {"x": 0}}},
            {"model": "mockllm/model", "model_base_url": "", "model_args": {"x": 0}},
        ),
        ({"tags": ["one", "one"]}, {"tags": ["one", "one"]}),
        (
            {"metadata": {"nested": {"x": False}}},
            {"metadata": {"nested": {"x": False}}},
        ),
        ({"eval_config": {"epochs_reducer": ["mean"]}}, {}),
        (
            {"generate_config": {"temperature": None}, "eval_config": {"limit": None}},
            {},
        ),
    ],
)
def test_run_config_to_params_mapping(
    config: dict[str, Any], expected: dict[str, Any]
) -> None:
    assert RunConfigInput.model_validate(config).to_params() == expected


@pytest.mark.parametrize("structured", [False, True])
def test_run_config_solver_and_sandbox_mapping(structured: bool) -> None:
    config = RunConfigInput.model_validate(
        {
            "solver": {"solver": "solver_ref", "args": {"x": None}}
            if structured
            else "solver_ref",
            "sandbox": {"type": "docker", "config": "file://compose.yaml"}
            if structured
            else "docker:file://compose.yaml",
        }
    )
    params = config.to_params()
    spec = params["solver"]
    assert isinstance(spec, SolverSpec)
    assert spec.solver == "solver_ref"
    assert spec.args == ({"x": None} if structured else {})
    assert spec.args_passed == spec.args
    assert params["sandbox"] == SandboxEnvironmentSpec("docker", "file://compose.yaml")


def test_run_config_generate_config_all_fields() -> None:
    values = {
        "max_retries": 0,
        "timeout": 1,
        "attempt_timeout": 2,
        "stream_idle_timeout": 3,
        "max_connections": 4,
        "adaptive_connections": False,
        "system_message": "system",
        "max_tokens": 5,
        "top_p": 0.5,
        "temperature": 0.0,
        "stop_seqs": [],
        "best_of": 1,
        "frequency_penalty": 0.1,
        "presence_penalty": 0.2,
        "logit_bias": {1: 0.5},
        "seed": 0,
        "top_k": 2,
        "num_choices": 1,
        "logprobs": False,
        "top_logprobs": 0,
        "prompt_logprobs": 1,
        "parallel_tool_calls": False,
        "internal_tools": False,
        "max_tool_output": 10,
        "cache_prompt": False,
        "fallback_models": [],
        "verbosity": "low",
        "effort": "high",
        "reasoning_effort": "low",
        "reasoning_mode": "standard",
        "reasoning_tokens": 10,
        "reasoning_summary": "none",
        "reasoning_history": "none",
        "response_schema": {"name": "response", "json_schema": {"type": "object"}},
        "extra_headers": {},
        "extra_body": {"nested": {"x": 1}},
        "modalities": ["image"],
        "cache": False,
        "batch": False,
    }
    assert set(values) == set(GenerateConfig.model_fields)
    expected = GenerateConfig.model_validate(values).model_dump(exclude_none=True)
    for config in (
        {"generate_config": values},
        {"model": {"model": "mockllm/model", "config": values}},
    ):
        params = RunConfigInput.model_validate(config).to_params()
        params.pop("model", None)
        assert params == expected


def test_run_config_eval_config_all_fields() -> None:
    values = {
        "limit": [1, 3],
        "sample_id": ["one", 2],
        "sample_shuffle": False,
        "approval": {"approvers": []},
        "notification": False,
        "fail_on_error": 0.5,
        "continue_on_fail": False,
        "retry_on_error": 0,
        "score_on_error": False,
        "message_limit": 1,
        "token_limit": 2,
        "token_limit_type": "output",
        "turn_limit": 3,
        "time_limit": 4,
        "working_limit": 5,
        "cost_limit": 0.0,
        "max_samples": 1,
        "max_dataset_memory": 2,
        "max_tasks": 3,
        "max_subprocesses": 4,
        "max_sandboxes": 5,
        "sandbox_cleanup": False,
        "sandbox_prebuilt": False,
        "log_samples": False,
        "log_realtime": False,
        "log_images": False,
        "log_model_api": False,
        "log_buffer": 0,
        "log_shared": 0,
        "score_display": False,
        "acp_server": False,
    }
    assert set(values) == set(EvalConfig.model_fields) - {"epochs", "epochs_reducer"}
    expected = EvalConfig.model_validate(values).model_dump(exclude_none=True)
    assert (
        RunConfigInput.model_validate({"eval_config": values}).to_params() == expected
    )


@pytest.mark.parametrize("reducers", [None, [], ["mean", "max"]])
@pytest.mark.parametrize("count", [0, 2])
def test_run_config_epochs_mapping(count: int, reducers: list[str] | None) -> None:
    params = RunConfigInput.model_validate(
        {"eval_config": {"epochs": count, "epochs_reducer": reducers}}
    ).to_params()
    assert set(params) == {"epochs"}
    epochs = params["epochs"]
    assert isinstance(epochs, Epochs)
    assert epochs.epochs == count
    assert (None if epochs.reducer is None else len(epochs.reducer)) == (
        None if reducers is None else len(reducers)
    )


def test_run_config_generation_precedence_replaces_nested_values() -> None:
    params = RunConfigInput.model_validate(
        {
            "model": {
                "model": "mockllm/model",
                "config": {
                    "temperature": 0.8,
                    "seed": 42,
                    "extra_body": {"keep": True, "nested": {"a": 1}},
                    "extra_headers": {"x": "old"},
                },
            },
            "generate_config": {
                "temperature": 0,
                "seed": None,
                "extra_body": {"nested": {"b": 2}},
                "extra_headers": {},
            },
        }
    ).to_params()
    assert params == {
        "model": "mockllm/model",
        "temperature": 0.0,
        "seed": 42,
        "extra_body": {"nested": {"b": 2}},
        "extra_headers": {},
    }


def test_run_config_model_roles_list_and_repeated_conversion() -> None:
    config = RunConfigInput.model_validate(
        {
            "model_roles": {
                "single": {
                    "model": "mockllm/single",
                    "base_url": "https://example.test",
                    "args": {"foo": "bar"},
                    "config": {"temperature": 0},
                },
                "group": [
                    {"model": "mockllm/first"},
                    {"model": "mockllm/second", "config": {"seed": 0}},
                ],
                "empty": [],
            }
        }
    )
    before = config.model_dump()
    first = config.to_params()["model_roles"]
    second = config.to_params()["model_roles"]
    assert isinstance(first["single"], Model)
    assert first["single"].api.base_url == "https://example.test"
    assert first["single"].model_args == {"foo": "bar"}
    assert first["single"].config.temperature == 0
    assert [str(model) for model in first["group"]] == [
        "mockllm/first",
        "mockllm/second",
    ]
    assert first["group"][1].config.seed == 0
    assert first["empty"] == []
    assert first["single"] is not second["single"]
    assert first["group"][0] is not second["group"][0]
    assert config.model_dump() == before


@pytest.mark.parametrize("section", ["task", "solver", "model"])
def test_run_config_nested_unknown_fields_are_ignored(section: str) -> None:
    name = "mockllm/model" if section == "model" else "reference"
    config = RunConfigInput.model_validate({section: {section: name, "typo": 1}})
    assert "typo" not in config.model_dump()[section]


@pytest.mark.parametrize(
    "section", ["generate_config", "eval_config", "tags", "metadata", "model_roles"]
)
def test_run_config_nonnullable_sections(section: str) -> None:
    with pytest.raises(ValidationError):
        RunConfigInput.model_validate({section: None})


@pytest.mark.parametrize("suffix", [".yaml", ".json"])
@pytest.mark.parametrize("uri", [False, True])
def test_parse_run_config_files(tmp_path: Path, suffix: str, uri: bool) -> None:
    path = tmp_path / f"run{suffix}"
    data = {
        "task": {"task": "task_ref", "args": {"value": None}},
        "generate_config": {"temperature": 0},
    }
    path.write_text(json.dumps(data) if suffix == ".json" else yaml.safe_dump(data))
    assert parse_run_config(path.as_uri() if uri else str(path)) == {
        "tasks": "task_ref",
        "task_args": {"value": None},
        "temperature": 0.0,
    }


@pytest.mark.parametrize(
    "data, message",
    [
        ({"typo": 1}, "Additional properties are not allowed"),
        ({"task": 42}, "not valid under any of the given schemas"),
        ({"generate_config": {"typo": 1}}, "Unknown generate_config fields"),
        ({"eval_config": {"max_messages": 3}}, "Unknown eval_config fields"),
    ],
)
def test_parse_run_config_validation_errors(
    tmp_path: Path, data: dict[str, Any], message: str
) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(PrerequisiteError) as exc:
        parse_run_config(str(path))
    assert f"Invalid run config '{path}':" in str(exc.value.message)
    assert message in str(exc.value.message)


@pytest.mark.parametrize("content", ["", "[]", "null", "not-an-object"])
def test_parse_run_config_nonobject_errors(tmp_path: Path, content: str) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(content)
    with pytest.raises(ValueError, match="The config is not a valid object"):
        parse_run_config(str(path))


def test_parse_run_config_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.yaml"
    with pytest.raises(PrerequisiteError) as exc:
        parse_run_config(str(path))
    assert exc.value.message == f"The config file {path} does not exist."


@pytest.mark.parametrize(
    "value, overrides",
    [
        (None, False),
        ({}, False),
        ([], True),
        ((), True),
        ("", True),
        (False, True),
        (0, True),
        (True, True),
    ],
)
def test_merge_run_config_empty_and_falsey_values(value: Any, overrides: bool) -> None:
    assert merge_run_config_params({"key": "run"}, {"key": value}) == {
        "key": value if overrides else "run"
    }
    assert merge_run_config_params({}, {"key": value}) == (
        {"key": value} if overrides else {}
    )


@pytest.mark.parametrize("run", [{}, {"score": True}, {"score": False}])
@pytest.mark.parametrize("cli", [None, True, False])
def test_merge_run_config_score_default(run: dict[str, Any], cli: bool | None) -> None:
    assert merge_run_config_params(run, {"score": cli}) == (
        {"score": False} if cli is False else run
    )


@pytest.mark.parametrize(
    "key",
    [
        "task_args",
        "model_args",
        "model_roles",
        "metadata",
        "extra_body",
        "extra_headers",
    ],
)
def test_merge_run_config_shallow_merge_and_replacement(key: str) -> None:
    run = {key: {"keep": 1, "nested": {"old": 2, "shared": 3}}}
    cli = {key: {"nested": {"new": 4}}}
    before_run, before_cli = deepcopy(run), deepcopy(cli)
    result = merge_run_config_params(run, cli)
    expected: dict[str, Any] = {"nested": {"new": 4}}
    if key in ("task_args", "model_args", "model_roles"):
        expected["keep"] = 1
    assert result == {key: expected}
    assert result is not run
    assert run == before_run
    assert cli == before_cli
    assert merge_run_config_params(run, cli) == result


@pytest.mark.parametrize("constructed", [False, True])
@pytest.mark.parametrize("args", [{}, {"color": None}, {"color": "blue"}])
def test_run_config_task_factory_vs_constructed_task(
    constructed: bool, args: dict[str, Any]
) -> None:
    params = RunConfigInput.model_validate(
        {
            "task": {"task": "eval_config_characterization_task", "args": args},
            "model": "mockllm/model",
            "eval_config": {"epochs": 2},
            "generate_config": {"temperature": 0},
        }
    ).to_params()
    if constructed:
        params["tasks"] = eval_config_characterization_task(color="constructed")
    log = eval(**params)[0]
    assert log.status == "success"
    assert log.eval.task_args["color"] == (
        "constructed" if constructed else args.get("color", "red")
    )
    assert log.eval.config.epochs == 2
    assert log.plan.config.temperature == 0


@pytest.mark.parametrize("source", ["environment", "run_config", "flag"])
@pytest.mark.parametrize(
    "name, option, envvar, value, config, expected",
    [
        (
            "m",
            "-M",
            "INSPECT_EVAL_MODEL_ARGS",
            "foo=env",
            {"model": {"model": "mockllm/model", "args": {"foo": "run"}}},
            ("foo=env",),
        ),
        (
            "t",
            "-T",
            "INSPECT_EVAL_TASK_ARGS",
            "color=env",
            {"task": {"task": "eval_config_task", "args": {"color": "run"}}},
            ("color=env",),
        ),
        (
            "model_role",
            "--model-role",
            "INSPECT_EVAL_MODEL_ROLE",
            "grader=mockllm/env",
            {"model_roles": {"grader": {"model": "mockllm/run"}}},
            ("grader=mockllm/env",),
        ),
        (
            "model_spec",
            "--model-spec",
            "INSPECT_EVAL_MODEL_SPEC",
            "mockllm/env",
            {"model": "mockllm/run"},
            ("mockllm/env",),
        ),
        (
            "no_sandbox_cleanup",
            "--no-sandbox-cleanup",
            "INSPECT_EVAL_NO_SANDBOX_CLEANUP",
            "true",
            {"eval_config": {"sandbox_cleanup": True}},
            True,
        ),
        (
            "s",
            "-S",
            "INSPECT_EVAL_SOLVER_ARGS",
            "shape=env",
            {"solver": "eval_config_solver"},
            ("shape=env",),
        ),
        (
            "solver_config",
            "--solver-config",
            "INSPECT_EVAL_SOLVER_CONFIG",
            "solver.yaml",
            {"solver": "eval_config_solver"},
            "solver.yaml",
        ),
        (
            "temperature",
            "--temperature",
            "INSPECT_EVAL_TEMPERATURE",
            "0.8",
            {"generate_config": {"temperature": 0}},
            0.8,
        ),
        (
            "limit",
            "--limit",
            "INSPECT_EVAL_LIMIT",
            "3",
            {"eval_config": {"limit": 1}},
            "3",
        ),
    ],
)
def test_run_config_cli_environment_key_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    name: str,
    option: str,
    envvar: str,
    value: str,
    config: dict[str, Any],
    expected: Any,
) -> None:
    captured: dict[str, Any] = {}

    def capture(**params: Any) -> None:
        captured.update(params)

    monkeypatch.setattr("inspect_ai._cli.eval._eval_command_impl", capture)
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump({} if source == "environment" else config))
    args = ["--run-config", str(path)]
    if source == "flag":
        args.extend([option] if name == "no_sandbox_cleanup" else [option, value])
    result = run_eval_cli(args, env={envvar: value, "TERM_PROGRAM": "xterm"})
    assert_cli_success(result)
    if source == "run_config":
        expected = () if isinstance(expected, tuple) else None
    assert captured[name] == expected


@pytest.mark.parametrize(
    "field, envvar",
    [
        ("log_samples", "INSPECT_EVAL_NO_LOG_SAMPLES"),
        ("log_realtime", "INSPECT_EVAL_NO_LOG_REALTIME"),
        ("score_display", "INSPECT_EVAL_SCORE_DISPLAY"),
        ("fail_on_error", "INSPECT_EVAL_NO_FAIL_ON_ERROR"),
    ],
)
def test_run_config_cli_unmapped_negated_env_overrides_config(
    tmp_path: Path, field: str, envvar: str
) -> None:
    path = tmp_path / "run.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "task": "tests/test_eval_config.py@eval_config_characterization_task",
                "model": "mockllm/model",
                "eval_config": {field: True},
            }
        )
    )
    result = run_eval_cli(
        ["--run-config", str(path), "--log-dir", str(tmp_path / "logs")],
        env={envvar: "true", "TERM_PROGRAM": "xterm"},
    )
    assert_cli_success(result)
    log = read_eval_log(list_eval_logs(str(tmp_path / "logs"))[0])
    assert getattr(log.eval.config, field) is False


def test_merge_run_config_replaces_role_lists_and_solver() -> None:
    old = get_model("mockllm/old")
    new = get_model("mockllm/new")
    old_solver = SolverSpec("old", {"keep": 1}, {})
    new_solver = SolverSpec("new", {"replace": 2}, {})
    run = {"model_roles": {"keep": old, "replace": [old]}, "solver": old_solver}
    result = merge_run_config_params(
        run, {"model_roles": {"replace": [new]}, "solver": new_solver}
    )
    assert result["model_roles"] == {"keep": old, "replace": [new]}
    assert result["solver"] is new_solver
    assert run["model_roles"] == {"keep": old, "replace": [old]}
    assert run["solver"] is old_solver


def test_run_config_nested_model_generation_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown GenerateConfig field"):
        RunConfigInput.model_validate(
            {
                "model": {
                    "model": "mockllm/model",
                    "config": {"temperature": 0, "typo": 1},
                },
            }
        )


def test_run_config_cli_model_config_merges_and_common_env_survives(
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "task": "tests/test_eval_config.py@eval_config_task",
                "model": {
                    "model": "mockllm/model",
                    "args": {"keep": True, "foo": "run"},
                },
                "metadata": {"keep": True, "shared": "run"},
                "tags": ["run"],
            }
        )
    )
    result = run_eval_cli(
        [
            "--run-config",
            str(path),
            "--model-config",
            config_path("model.yaml"),
            "--metadata",
            "shared=cli",
            "--tags",
            "cli",
        ],
        env={"INSPECT_LOG_DIR": str(tmp_path / "logs"), "TERM_PROGRAM": "xterm"},
    )
    assert_cli_success(result)
    log = read_eval_log(list_eval_logs(str(tmp_path / "logs"))[0])
    assert log.eval.model_args == {"keep": True, "foo": "bar"}
    assert log.eval.metadata == {"shared": "cli"}
    assert log.eval.tags == ["cli"]


def test_eval_set_rejects_run_config(tmp_path: Path) -> None:
    path = tmp_path / "run.yaml"
    path.write_text("{}")
    result = run_eval_set_cli(["--run-config", str(path)])
    assert result.exit_code != 0
    assert isinstance(result.exception, PrerequisiteError)
    assert result.exception.message == "--run-config is only supported by inspect eval."


def test_eval_config_task():
    log = eval(
        tasks="eval_config_task",
        task_args=config_path("task.yaml"),
        model="mockllm/model",
        model_args=config_path("model.yaml"),
    )[0]
    check_log(log)


def test_eval_config_task_cli():
    with tempfile.TemporaryDirectory() as log_dir:
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                "--task-config",
                config_path("task.yaml"),
                "-T",
                "color=green",
                "--model-config",
                config_path("model.yaml"),
                "--solver",
                "eval_config_solver",
                "--solver-config",
                config_path("solver.yaml"),
                "--log-dir",
                log_dir,
                "--model",
                "mockllm/model",
                "--model-role",
                "grader={model: mockllm/model, temperature: 0.5, max_tokens: 1000}",
            ]
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir)[0])
        check_log(log, "green", check_model_roles=True)


def test_eval_generate_config_cli():
    with tempfile.TemporaryDirectory() as log_dir:
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                "--generate-config",
                config_path("generate_config.yaml"),
                "--temperature",
                "0.9",
                "--log-dir",
                log_dir,
                "--model",
                "mockllm/model",
            ]
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir)[0])
        # temperature should be overridden by explicit CLI option
        assert log.plan.config.temperature == 0.9
        # these should come from the config file
        assert log.plan.config.max_tokens == 512
        assert log.plan.config.seed == 42


MODEL_SPECS = [
    "--model-spec",
    "{model: mockllm/model, temperature: 0.25}",
    "--model-spec",
    '{"model": "mockllm/model", "temperature": 0.75}',
]


def assert_model_spec_temperatures(log_dir: Path) -> None:
    """Assert the two MODEL_SPECS each produced their own log.

    The specs name one model twice, so this fails if the two specs collapse
    onto a single model or a single log.
    """
    logs = [read_eval_log(f) for f in list_eval_logs(log_dir.as_posix())]
    assert [log.eval.model for log in logs] == ["mockllm/model"] * 2
    assert {log.eval.model_generate_config.temperature for log in logs} == {0.25, 0.75}


def test_eval_model_spec_cli():
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                *MODEL_SPECS,
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        assert_model_spec_temperatures(log_dir)


def test_eval_set_model_spec_cli():
    """An eval set must treat two specs for one model as two units of work.

    Task identity hashes the model's generate config, so the specs must not
    dedupe onto each other.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_set_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                *MODEL_SPECS,
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        assert_model_spec_temperatures(log_dir)


def test_eval_model_spec_cli_with_model_role():
    """A spec fills the main model and a role fills a named one, so both apply.

    The role is shared across the specs and keeps its own config; it does not
    override, and is not overridden by, the model of a spec.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                *MODEL_SPECS,
                "--model-role",
                "grader={model: mockllm/model, temperature: 0.5, max_tokens: 1000}",
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        assert_model_spec_temperatures(log_dir)
        for log in [read_eval_log(f) for f in list_eval_logs(log_dir.as_posix())]:
            assert log.eval.model_roles is not None
            grader = log.eval.model_roles["grader"]
            assert grader.config.temperature == 0.5
            assert grader.config.max_tokens == 1000


def test_eval_model_spec_cli_unset_model_role_inherits_each_spec():
    """An unset role resolves to the spec that is running, not to one of them."""
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                *MODEL_SPECS,
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        logs = [read_eval_log(f) for f in list_eval_logs(log_dir.as_posix())]
        # each log's grader carries that log's own main-model temperature
        for log in logs:
            assert log.eval.model_roles is not None
            assert (
                log.eval.model_roles["grader"].config.temperature
                == log.eval.model_generate_config.temperature
            )
        assert {log.eval.model_roles["grader"].config.temperature for log in logs} == {
            0.25,
            0.75,
        }


@pytest.mark.parametrize(
    "conflict",
    [
        ["--model", "mockllm/model"],
        ["--model-base-url", "http://localhost:9999/v1"],
        ["--model-config", "tests/test_eval_config/model.yaml"],
        ["-M", "custom_outputs=null"],
    ],
)
def test_eval_model_spec_cli_conflicts_with_single_model_options(conflict):
    """A spec owns the model, so these options would reach nothing."""
    result = run_eval_cli(
        ["tests/test_eval_config.py@eval_config_task", *MODEL_SPECS, *conflict]
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, PrerequisiteError)
    assert f"--model-spec cannot be used with {conflict[0]}" in (
        result.exception.message
    )


def test_eval_model_spec_env_var_yields_to_explicit_model():
    """An INSPECT_EVAL_MODEL_SPEC must not break an explicit --model.

    The variable is an ambient default, often from a `.env` file, so a typed
    option wins over it rather than failing the run.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                "--model",
                "mockllm/from_cli",
                "--log-dir",
                log_dir.as_posix(),
            ],
            env={"INSPECT_EVAL_MODEL_SPEC": MODEL_SPECS[1]},
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.model == "mockllm/from_cli"
        assert log.eval.model_generate_config.temperature is None


def test_eval_model_spec_cli_conflicts_with_run_config_model():
    """A run config `model` field sets args and a base url a spec would drop."""
    with tempfile.TemporaryDirectory() as temp_dir:
        run_config = Path(temp_dir) / "run.yaml"
        run_config.write_text(
            """
task: tests/test_eval_config.py@eval_config_task
model:
  model: mockllm/model
  base_url: http://localhost:9999/v1
""".strip()
        )
        result = run_eval_cli(["--run-config", run_config.as_posix(), *MODEL_SPECS])
        assert result.exit_code != 0
        assert isinstance(result.exception, PrerequisiteError)
        assert "the 'model' field of --run-config" in result.exception.message


def test_eval_model_spec_cli_allows_model_env_var():
    """INSPECT_EVAL_MODEL is an ambient default, so --model-spec replaces it."""
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                *MODEL_SPECS,
                "--log-dir",
                log_dir.as_posix(),
            ],
            env={"INSPECT_EVAL_MODEL": "mockllm/from_env"},
        )
        assert_cli_success(result)
        assert_model_spec_temperatures(log_dir)


def test_eval_run_config_cli():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        log_dir = temp_path / "logs"
        run_config = temp_path / "run.yaml"
        run_config.write_text(
            """
task:
  task: tests/test_eval_config.py@eval_config_task
  args:
    epochs: 2
    color: purple
model:
  model: mockllm/model
  args:
    foo: run
model_roles:
  grader:
    model: mockllm/model
    config:
      temperature: 0.5
      max_tokens: 1000
generate_config:
  temperature: 0.1
  max_tokens: 512
  seed: 42
solver:
  solver: eval_config_solver
  args:
    shape: square
eval_config:
  limit: 1
""".strip()
        )

        result = run_eval_cli(
            [
                "--run-config",
                run_config.as_posix(),
                "-T",
                "color=green",
                "--temperature",
                "0.9",
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.task == "eval_config_task"
        assert log.eval.task_args["epochs"] == 2
        assert log.eval.task_args["color"] == "green"
        assert log.eval.model == "mockllm/model"
        assert log.eval.model_args["foo"] == "run"
        assert log.eval.solver_args == {"shape": "square"}
        assert log.plan.config.temperature == 0.9
        assert log.plan.config.max_tokens == 512
        assert log.plan.config.seed == 42
        assert log.eval.config.limit == 1
        assert log.eval.model_roles is not None
        assert log.eval.model_roles["grader"].model == "mockllm/model"
        assert log.eval.model_roles["grader"].config.temperature == 0.5
        assert log.eval.model_roles["grader"].config.max_tokens == 1000


def test_eval_run_config_cli_env_var_overridden_by_run_config():
    """INSPECT_EVAL_MODEL must not override a model set in --run-config."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        log_dir = temp_path / "logs"
        run_config = temp_path / "run.yaml"
        run_config.write_text(
            """
task: tests/test_eval_config.py@eval_config_task
model: mockllm/model
eval_config:
  limit: 1
""".strip()
        )

        result = run_eval_cli(
            [
                "--run-config",
                run_config.as_posix(),
                "--log-dir",
                log_dir.as_posix(),
            ],
            env={"INSPECT_EVAL_MODEL": "anthropic/claude-sonnet-4-6"},
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.model == "mockllm/model"


def test_eval_run_config_cli_env_var_overridden_by_explicit_flag():
    """An explicit --model flag must beat both INSPECT_EVAL_MODEL and --run-config."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        log_dir = temp_path / "logs"
        run_config = temp_path / "run.yaml"
        run_config.write_text(
            """
task: tests/test_eval_config.py@eval_config_task
model: mockllm/from_run_config
eval_config:
  limit: 1
""".strip()
        )

        result = run_eval_cli(
            [
                "--run-config",
                run_config.as_posix(),
                "--model",
                "mockllm/from_cli",
                "--log-dir",
                log_dir.as_posix(),
            ],
            env={"INSPECT_EVAL_MODEL": "mockllm/from_env"},
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.model == "mockllm/from_cli"


def test_eval_run_config_cli_env_var_used_when_run_config_missing_field():
    """INSPECT_EVAL_MODEL still applies when --run-config doesn't set `model`."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        log_dir = temp_path / "logs"
        run_config = temp_path / "run.yaml"
        # run config provides task + eval_config but NO top-level model
        run_config.write_text(
            """
task: tests/test_eval_config.py@eval_config_task
eval_config:
  limit: 1
""".strip()
        )

        # Defeat VSCode-mode .env override (inspect's init_dotenv uses
        # override=True when TERM_PROGRAM=vscode, which would overwrite
        # INSPECT_EVAL_MODEL from the repo .env and mask the env value
        # this test is checking).
        env = {"INSPECT_EVAL_MODEL": "mockllm/from_env"}
        if os.environ.get("TERM_PROGRAM") == "vscode":
            env["TERM_PROGRAM"] = "xterm"

        result = run_eval_cli(
            [
                "--run-config",
                run_config.as_posix(),
                "--log-dir",
                log_dir.as_posix(),
            ],
            env=env,
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.model == "mockllm/from_env"


def test_eval_run_config_cli_paper_config():
    """Task and model supplied on CLI; run config provides the rest (the 'paper config' use case)."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        log_dir = temp_path / "logs"
        run_config = temp_path / "paper.yaml"
        run_config.write_text(
            """
model_roles:
  grader:
    model: mockllm/model
    config:
      temperature: 0.3
generate_config:
  temperature: 0.5
  seed: 99
eval_config:
  limit: 1
""".strip()
        )

        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                "--model",
                "mockllm/model",
                "--run-config",
                run_config.as_posix(),
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.task == "eval_config_task"
        assert log.eval.model == "mockllm/model"
        assert log.plan.config.temperature == 0.5
        assert log.plan.config.seed == 99
        assert log.eval.config.limit == 1
        assert log.eval.model_roles is not None
        assert log.eval.model_roles["grader"].model == "mockllm/model"
        assert log.eval.model_roles["grader"].config.temperature == 0.3


def test_eval_run_config_cli_conflicts_with_config_files():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        run_config = temp_path / "run.yaml"
        run_config.write_text(
            """
task: tests/test_eval_config.py@eval_config_task
model: mockllm/model
""".strip()
        )

        conflicts = [
            ["--generate-config", config_path("generate_config.yaml")],
            ["--task-config", config_path("task.yaml")],
            [
                "--solver",
                "eval_config_solver",
                "--solver-config",
                config_path("solver.yaml"),
            ],
        ]
        for conflict in conflicts:
            result = run_eval_cli(
                [
                    "--run-config",
                    run_config.as_posix(),
                    *conflict,
                ]
            )
            assert result.exit_code != 0
            assert isinstance(result.exception, PrerequisiteError)
            assert "--run-config cannot be used with" in str(result.exception.message)


def test_eval_run_config_score_on_error_not_clobbered():
    """A run-config eval_config flag must survive when the CLI flag is absent.

    --score-on-error / --continue-on-fail are positive flags; an absent flag must
    not overwrite a `true` set in --run-config.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        log_dir = temp_path / "logs"
        run_config = temp_path / "run.yaml"
        run_config.write_text(
            """
task: tests/test_eval_config.py@eval_config_task
model: mockllm/model
eval_config:
  score_on_error: true
  continue_on_fail: true
  limit: 1
""".strip()
        )

        result = run_eval_cli(
            [
                "--run-config",
                run_config.as_posix(),
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.config.score_on_error is True
        assert log.eval.config.continue_on_fail is True


def test_eval_cli_preserves_task_score_on_error():
    """A task-level positive error flag must survive when the CLI flag is absent."""
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_error_flags_task",
                "--model",
                "mockllm/model",
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.config.score_on_error is True
        assert log.eval.config.continue_on_fail is True


def test_eval_cli_score_on_error_default_when_unset():
    """With neither task nor CLI setting the flags, they default to off."""
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                "--model",
                "mockllm/model",
                "--log-dir",
                log_dir.as_posix(),
            ],
            # unset the env vars: their presence would force the flags on
            env={
                "INSPECT_EVAL_SCORE_ON_ERROR": None,
                "INSPECT_EVAL_CONTINUE_ON_FAIL": None,
            },
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert not log.eval.config.score_on_error
        assert not log.eval.config.continue_on_fail


def test_eval_cli_score_on_error_flag_turns_on():
    """Explicitly passing the positive flags must still turn them on.

    Guards against the default change (False -> None) silently breaking the
    flags' ability to set the option, and confirms the CLI value overrides a
    task that leaves them at their default.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_task",
                "--model",
                "mockllm/model",
                "--log-dir",
                log_dir.as_posix(),
                "--score-on-error",
                "--continue-on-fail",
            ]
        )
        assert_cli_success(result)
        log = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert log.eval.config.score_on_error is True
        assert log.eval.config.continue_on_fail is True


def test_eval_retry_cli_preserves_error_flags_from_log():
    """`inspect eval-retry` with the flags absent must inherit them from the log.

    This is the "prior eval log being retried" path: a retry that omits the
    flags must not clobber the values baked into the log it is retrying.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        log_dir = Path(temp_dir) / "logs"
        # produce a retryable (errored) log whose config carries both flags
        result = run_eval_cli(
            [
                "tests/test_eval_config.py@eval_config_failing_error_flags_task",
                "--model",
                "mockllm/model",
                "--log-dir",
                log_dir.as_posix(),
            ]
        )
        assert_cli_success(result)
        first = read_eval_log(list_eval_logs(log_dir.as_posix())[0])
        assert first.status == "error"
        assert first.eval.config.score_on_error is True
        assert first.eval.config.continue_on_fail is True

        # retry without the flags; the retried log must preserve them
        retry = run_eval_retry_cli([first.location, "--log-dir", log_dir.as_posix()])
        assert_cli_success(retry)
        logs = [read_eval_log(f) for f in list_eval_logs(log_dir.as_posix())]
        assert len(logs) == 2  # original + retry
        for log in logs:
            assert log.eval.config.score_on_error is True
            assert log.eval.config.continue_on_fail is True


@solver
def eval_config_solver(shape="square"):
    async def solve(state, generate):
        return await generate(state)

    return solve


@task
def eval_config_characterization_task(color: str | None = "red") -> Task:
    return Task(
        metadata={"color": color},
        config=GenerateConfig(temperature=0.6, seed=42),
        epochs=3,
        score_on_error=True,
    )


@task
def eval_config_task(epochs=1, color="red") -> Task:
    return Task(epochs=epochs, model_roles={"grader": get_model(role="grader")})


@task
def eval_config_error_flags_task() -> Task:
    """Task that turns on the positive error flags in its own definition."""
    return Task(score_on_error=True, continue_on_fail=True)


@solver
def eval_config_always_error_solver():
    async def solve(state, generate):
        raise RuntimeError("intentional failure for eval-retry test")

    return solve


@task
def eval_config_failing_error_flags_task() -> Task:
    """Always errors, with the positive error flags set in its own definition.

    Produces a retryable (errored) log carrying score_on_error / continue_on_fail
    so `inspect eval-retry` can be checked for preserving them.
    """
    return Task(
        solver=[eval_config_always_error_solver()],
        score_on_error=True,
        continue_on_fail=True,
    )


def check_log(log: EvalLog, color="purple", check_model_roles=False) -> None:
    assert log.eval.config.epochs == 2
    assert log.eval.task_args["color"] == color
    assert log.eval.model_args["foo"] == "bar"
    if log.eval.model_roles and check_model_roles:
        grader = log.eval.model_roles["grader"]
        assert not isinstance(grader, list)
        assert grader.config.temperature == 0.5
        assert grader.config.max_tokens == 1000
        assert grader.model == "mockllm/model"
    if log.eval.solver_args:
        assert log.eval.solver_args["shape"] == "square"


TEST_EVAL_CONFIG_PATH = Path("tests/test_eval_config")


def config_path(file: str) -> str:
    return (TEST_EVAL_CONFIG_PATH / file).as_posix()
