import subprocess
import tempfile
from pathlib import Path

from inspect_ai import Task, eval, task
from inspect_ai.log import EvalLog
from inspect_ai.log._file import list_eval_logs, read_eval_log
from inspect_ai.model import get_model
from inspect_ai.solver import solver


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
