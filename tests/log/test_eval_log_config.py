import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from inspect_ai import Epochs, Task, eval, task
from inspect_ai._cli.eval import RunConfigInput
from inspect_ai.dataset import Sample
from inspect_ai.log._config import eval_log_to_run_config_dict
from inspect_ai.log._file import list_eval_logs, read_eval_log
from inspect_ai.log._log import EvalConfig, EvalDataset, EvalLog, EvalSpec
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import Score, Scorer, Target, accuracy, at_least, pass_at, scorer
from inspect_ai.solver import SolverSpec, TaskState, solver
from inspect_ai.util._limit import TokenLimit
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


@scorer(metrics=[accuracy()])
def reducer_args_scorer() -> Scorer:
    plan: dict[int | str, list[str]] = {
        1: ["P", "P", "I"],
        2: ["C", "I", "I"],
        3: ["C", "P", "I"],
    }

    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=plan[state.sample_id][(state.epoch or 1) - 1])

    return score


@task
def reducer_args_task() -> Task:
    return Task(
        dataset=[Sample(input="q", id=i) for i in (1, 2, 3)],
        plan=[],
        scorer=reducer_args_scorer(),
        epochs=Epochs(3, [at_least(2, value=0.5), pass_at(1, value=0.5)]),
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
    # no epochs reducer was used, so no reducer specs are recorded or exported
    assert "epochs_reducer_specs" not in d["eval_config"]


def test_eval_log_to_run_config_dict_model_role_list() -> None:
    """A role bound to a list of models exports as a list and re-imports as one."""
    from inspect_ai._cli.eval import RunConfigInput
    from inspect_ai.model import Model

    graders = [
        get_model("mockllm/model", config=GenerateConfig(temperature=0.1)),
        get_model("mockllm/model", config=GenerateConfig(temperature=0.9)),
    ]
    log = eval(
        config_test_task,
        model="mockllm/model",
        model_roles={"grader": graders},
        limit=1,
    )[0]

    # the log stores the role as a list of model configs
    assert log.eval.model_roles is not None
    assert set(log.eval.model_roles.keys()) == {"grader"}
    assert isinstance(log.eval.model_roles["grader"], list)

    # the exported run config carries the list through
    d = eval_log_to_run_config_dict(log)
    exported = d["model_roles"]["grader"]
    assert isinstance(exported, list)
    assert [e["config"]["temperature"] for e in exported] == [0.1, 0.9]

    # and the run config parses back to a list of models for the role
    params = RunConfigInput.model_validate(
        {"model_roles": d["model_roles"]}
    ).to_params()
    parsed = params["model_roles"]["grader"]
    assert isinstance(parsed, list)
    assert all(isinstance(m, Model) for m in parsed)
    assert [m.config.temperature for m in parsed] == [0.1, 0.9]


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
    grader_config = log2.eval.model_roles["grader"]
    assert not isinstance(grader_config, list)
    assert grader_config.model == "mockllm/model"
    assert grader_config.config.temperature == 0.3
    assert grader_config.config.max_tokens == 500


def test_eval_log_run_config_round_trip_reducer_args() -> None:
    """Round-trip with non-default reducer args: the re-run keeps the arguments."""
    log1 = eval(reducer_args_task, model="mockllm/model")[0]

    def metrics_by_reducer(lg: EvalLog) -> dict[str, float]:
        assert lg.results is not None
        return {
            s.reducer: s.metrics["accuracy"].value
            for s in lg.results.scores
            if s.reducer is not None
        }

    def recorded_specs(lg: EvalLog) -> list[tuple[str, dict | None]]:
        return [(s.name, s.options) for s in lg.eval.config.epochs_reducer_specs or []]

    expected_specs = [
        ("at_least", {"k": 2, "value": 0.5}),
        ("pass_at", {"k": 1, "value": 0.5}),
    ]
    assert log1.eval.config.epochs_reducer == ["at_least_2", "pass_at_1"]
    assert recorded_specs(log1) == expected_specs
    assert metrics_by_reducer(log1) == pytest.approx(
        {"at_least_2": 2 / 3, "pass_at_1": 5 / 9}
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        run_config = tmp_path / "run.yaml"
        log_dir = tmp_path / "logs"

        d = eval_log_to_run_config_dict(log1)
        assert [
            (s["name"], s["options"]) for s in d["eval_config"]["epochs_reducer_specs"]
        ] == expected_specs
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

    assert recorded_specs(log2) == expected_specs
    assert metrics_by_reducer(log2) == metrics_by_reducer(log1)


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


def test_exported_output_token_limit_round_trips() -> None:
    """An output-only token limit survives export and run-config parsing."""
    log = eval(
        config_test_task,
        model="mockllm/model",
        token_limit=TokenLimit(tokens=1000, type="output"),
        limit=1,
    )[0]
    assert log.eval.config.token_limit == 1000
    assert log.eval.config.token_limit_type == "output"

    exported = eval_log_to_run_config_dict(log)
    assert exported["eval_config"]["token_limit"] == 1000
    assert exported["eval_config"]["token_limit_type"] == "output"

    params = RunConfigInput.model_validate(exported).to_params()
    assert params["token_limit"] == TokenLimit(tokens=1000, type="output")
    assert "token_limit_type" not in params
