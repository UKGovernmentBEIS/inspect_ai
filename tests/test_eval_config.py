import subprocess
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from inspect_ai import Task, eval, task
from inspect_ai._cli.eval import RunConfigInput
from inspect_ai.log import EvalLog
from inspect_ai.log._file import list_eval_logs, read_eval_log
from inspect_ai.model import get_model
from inspect_ai.solver import solver


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
        subprocess.run(
            [
                "inspect",
                "eval",
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
        log = read_eval_log(list_eval_logs(log_dir)[0])
        check_log(log, "green", check_model_roles=True)


def test_eval_generate_config_cli():
    with tempfile.TemporaryDirectory() as log_dir:
        subprocess.run(
            [
                "inspect",
                "eval",
                "tests/test_eval_config.py@eval_config_task",
                "--generate-config",
                config_path("generate_config.yaml"),
                "--temperature",
                "0.9",
                "--log-dir",
                log_dir,
                "--model",
                "mockllm/model",
            ],
            check=True,
        )
        log = read_eval_log(list_eval_logs(log_dir)[0])
        # temperature should be overridden by explicit CLI option
        assert log.plan.config.temperature == 0.9
        # these should come from the config file
        assert log.plan.config.max_tokens == 512
        assert log.plan.config.seed == 42


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

        subprocess.run(
            [
                "inspect",
                "eval",
                "--run-config",
                run_config.as_posix(),
                "-T",
                "color=green",
                "--temperature",
                "0.9",
                "--log-dir",
                log_dir.as_posix(),
            ],
            check=True,
        )
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

        subprocess.run(
            [
                "inspect",
                "eval",
                "tests/test_eval_config.py@eval_config_task",
                "--model",
                "mockllm/model",
                "--run-config",
                run_config.as_posix(),
                "--log-dir",
                log_dir.as_posix(),
            ],
            check=True,
        )
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
            ["--solver", "eval_config_solver", "--solver-config", config_path("solver.yaml")],
        ]
        for conflict in conflicts:
            result = subprocess.run(
                [
                    "inspect",
                    "eval",
                    "--run-config",
                    run_config.as_posix(),
                    *conflict,
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0
            assert "--run-config cannot be used with" in result.stdout


@solver
def eval_config_solver(shape="square"):
    async def solve(state, generate):
        return await generate(state)

    return solve


@task
def eval_config_task(epochs=1, color="red") -> Task:
    return Task(epochs=epochs, model_roles={"grader": get_model(role="grader")})


def check_log(log: EvalLog, color="purple", check_model_roles=False) -> None:
    assert log.eval.config.epochs == 2
    assert log.eval.task_args["color"] == color
    assert log.eval.model_args["foo"] == "bar"
    if log.eval.model_roles and check_model_roles:
        assert log.eval.model_roles["grader"].config.temperature == 0.5
        assert log.eval.model_roles["grader"].config.max_tokens == 1000
        assert log.eval.model_roles["grader"].model == "mockllm/model"
    if log.eval.solver_args:
        assert log.eval.solver_args["shape"] == "square"


TEST_EVAL_CONFIG_PATH = Path("tests/test_eval_config")


def config_path(file: str) -> str:
    return (TEST_EVAL_CONFIG_PATH / file).as_posix()
