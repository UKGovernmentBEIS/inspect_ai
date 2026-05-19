import subprocess
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.log._config import eval_log_to_run_config_dict
from inspect_ai.log._file import list_eval_logs, read_eval_log
from inspect_ai.log._log import EvalConfig, EvalDataset, EvalLog, EvalSpec
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.solver import SolverSpec, solver
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


def _make_log(sandbox: SandboxEnvironmentSpec | None = None) -> EvalLog:
    return EvalLog(
        eval=EvalSpec(
            task="test_task",
            model="mockllm/model",
            created="2024-01-01T00:00:00Z",
            dataset=EvalDataset(),
            config=EvalConfig(),
            sandbox=sandbox,
        )
    )


@solver
def config_test_solver(shape: str = "square", size: int = 1):
    async def solve(state, generate):
        return state

    return solve


@task
def config_test_task(color: str = "red", count: int = 1) -> Task:
    return Task(
        dataset=[Sample(input="input", target="target")],
        solver=config_test_solver(),
        model_roles={"grader": get_model(role="grader")},
    )


def test_eval_log_to_run_config_dict() -> None:
    grader = get_model(
        "mockllm/model",
        config=GenerateConfig(temperature=0.5, max_tokens=1000),
    )
    log = eval(
        config_test_task,
        model="mockllm/model",
        model_roles={"grader": grader},
        task_args={"color": "blue"},
        max_tokens=256,
        temperature=0.7,
        limit=1,
    )[0]

    d = eval_log_to_run_config_dict(log)

    assert d["task"]["task"].endswith("config_test_task")
    assert d["task"]["args"] == {"color": "blue", "count": 1}
    assert d["model"]["model"] == "mockllm/model"
    assert d["generate_config"]["temperature"] == 0.7
    assert d["generate_config"]["max_tokens"] == 256
    assert d["model_roles"]["grader"]["model"] == "mockllm/model"
    assert d["model_roles"]["grader"]["config"]["temperature"] == 0.5
    assert d["model_roles"]["grader"]["config"]["max_tokens"] == 1000
    assert d["eval_config"]["limit"] == 1


def test_eval_log_to_run_config_dict_solver_override() -> None:
    log = eval(
        config_test_task,
        model="mockllm/model",
        solver=SolverSpec(
            "config_test_solver",
            args={"shape": "circle", "size": 1},
            args_passed={"shape": "circle"},
        ),
        limit=1,
    )[0]

    d = eval_log_to_run_config_dict(log)

    assert d["solver"]["solver"] == "config_test_solver"
    assert d["solver"]["args"] == {"shape": "circle", "size": 1}


def test_eval_log_run_config_round_trip() -> None:
    """Round-trip: eval → export-config → re-eval produces the same effective configuration."""
    grader = get_model(
        "mockllm/model",
        config=GenerateConfig(temperature=0.3, max_tokens=500),
    )
    log1 = eval(
        config_test_task,
        model="mockllm/model",
        model_roles={"grader": grader},
        task_args={"color": "blue"},
        temperature=0.7,
        max_tokens=256,
        seed=42,
        limit=1,
    )[0]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        run_config = tmp_path / "run.yaml"
        log_dir = tmp_path / "logs"

        d = eval_log_to_run_config_dict(log1)
        run_config.write_text(yaml.dump(d, default_flow_style=False, sort_keys=False))

        subprocess.run(
            [
                "inspect",
                "eval",
                "--run-config",
                run_config.as_posix(),
                "--log-dir",
                log_dir.as_posix(),
            ],
            check=True,
        )

        log2 = read_eval_log(list_eval_logs(log_dir.as_posix())[0])

    assert log2.eval.task == log1.eval.task
    assert log2.eval.model == log1.eval.model
    assert log2.plan.config.temperature == log1.plan.config.temperature
    assert log2.plan.config.max_tokens == log1.plan.config.max_tokens
    assert log2.plan.config.seed == log1.plan.config.seed
    assert log2.eval.config.limit == log1.eval.config.limit
    assert log2.eval.model_roles is not None
    assert log2.eval.model_roles["grader"].model == "mockllm/model"
    assert log2.eval.model_roles["grader"].config.temperature == 0.3
    assert log2.eval.model_roles["grader"].config.max_tokens == 500


def test_sandbox_string_config() -> None:
    log = _make_log(SandboxEnvironmentSpec(type="docker", config="compose.yaml"))
    d = eval_log_to_run_config_dict(log)
    assert d["sandbox"] == "docker:compose.yaml"


def test_sandbox_no_config() -> None:
    log = _make_log(SandboxEnvironmentSpec(type="local"))
    d = eval_log_to_run_config_dict(log)
    assert d["sandbox"] == "local"


def test_sandbox_basemodel_config(capsys) -> None:
    class DockerConfig(BaseModel):
        image: str
        memory: str = "2g"

    log = _make_log(
        SandboxEnvironmentSpec(type="docker", config=DockerConfig(image="ubuntu"))
    )
    d = eval_log_to_run_config_dict(log)

    assert d["sandbox"] == "docker"
    assert "DockerConfig" in capsys.readouterr().err
