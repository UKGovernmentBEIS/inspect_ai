import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Task, eval, eval_retry, eval_set, task, task_with
from inspect_ai._eval.eval_set_manifest import INSPECT_EVAL_SET_CAPTURE, EvalSetCapture
from inspect_ai._eval.eval_set_overrides import INSPECT_EVAL_SET_OVERRIDES
from inspect_ai._sentinel._context import active_sentinel
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalConfig, EvalLog, read_eval_log
from inspect_ai.solver import Generate, Solver, TaskState, solver

try:
    from inspect_sentinel import (
        BeforeToolCall,
        Context,
        ControlProtocol,
        Decision,
        Monitor,
        Observation,
        monitor,
        protocol,
    )
except ImportError:
    pytest.skip("inspect_sentinel is not installed", allow_module_level=True)


@monitor
def d2_suspicion(score: float = 0.5) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        return Observation.score(score)

    return check


@protocol
def d2_rule(reason: str = "no") -> ControlProtocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.reject(reason)

    return decide


@solver
def record_sentinel() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        root = active_sentinel()
        state.metadata["sentinel"] = (
            registry_info(root).name if root is not None else None
        )
        return state

    return solve


def sentinel_task(sentinel: Any = None) -> Task:
    return Task(
        dataset=[Sample(input="x", target="y")],
        solver=record_sentinel(),
        sentinel=sentinel,
    )


def active_root(log: EvalLog) -> str | None:
    assert log.status == "success", log.error
    assert log.samples
    return log.samples[0].metadata["sentinel"]


RULE_CONFIG = [{"name": "d2_rule", "params": {"reason": "no"}}]


def test_task_sentinel_is_recorded_and_active() -> None:
    log = eval(sentinel_task(d2_rule(reason="no")), model="mockllm/model")[0]
    assert log.eval.config.sentinel == RULE_CONFIG
    assert active_root(log) == "inspect_sentinel/concurrent"


def test_no_sentinel_leaves_the_config_empty() -> None:
    log = eval(sentinel_task(), model="mockllm/model")[0]
    assert log.eval.config.sentinel is None
    assert active_root(log) is None


def test_monitors_only_resolve_to_observe() -> None:
    log = eval(
        sentinel_task({"watch": d2_suspicion(score=0.2)}), model="mockllm/model"
    )[0]
    assert log.eval.config.sentinel == {
        "watch": {"name": "d2_suspicion", "params": {"score": 0.2}}
    }
    assert active_root(log) == "inspect_sentinel/observe"


def test_task_with_sets_and_clears_the_sentinel() -> None:
    log = eval(task_with(sentinel_task(), sentinel=RULE_CONFIG), model="mockllm/model")[
        0
    ]
    assert log.eval.config.sentinel == RULE_CONFIG
    log = eval(
        task_with(sentinel_task(d2_rule()), sentinel=None), model="mockllm/model"
    )[0]
    assert log.eval.config.sentinel is None
    assert active_root(log) is None


def test_eval_sentinel_overrides_the_task() -> None:
    log = eval(
        sentinel_task(d2_rule(reason="task")),
        model="mockllm/model",
        sentinel=[d2_suspicion(score=0.7)],
    )[0]
    assert log.eval.config.sentinel == [
        {"name": "d2_suspicion", "params": {"score": 0.7}}
    ]
    assert active_root(log) == "inspect_sentinel/observe"


def test_config_file_and_registered_name(tmp_path: Path) -> None:
    config = tmp_path / "sentinel.yaml"
    config.write_text(
        "sentinel:\n  block:\n    name: d2_rule\n    params:\n      reason: file\n"
    )
    log = eval(sentinel_task(), model="mockllm/model", sentinel=str(config))[0]
    assert log.eval.config.sentinel == {
        "block": {"name": "d2_rule", "params": {"reason": "file"}}
    }

    log = eval(sentinel_task(), model="mockllm/model", sentinel="d2_rule")[0]
    assert log.eval.config.sentinel == [{"name": "d2_rule", "params": {}}]


def test_nested_config_round_trips_through_the_log(tmp_path: Path) -> None:
    config = [
        {
            "name": "threshold",
            "params": {"reject_at": 0.8},
            "monitors": [{"name": "d2_suspicion", "params": {"score": 0.9}}],
        }
    ]
    log = eval(
        sentinel_task(), model="mockllm/model", sentinel=config, log_dir=str(tmp_path)
    )[0]
    recorded = log.eval.config.sentinel
    assert isinstance(recorded, list)
    assert recorded[0]["name"] == "threshold"
    assert recorded[0]["monitors"] == config[0]["monitors"]

    read = read_eval_log(log.location)
    assert read.eval.config.sentinel == recorded
    assert (
        EvalConfig.model_validate_json(read.eval.config.model_dump_json()).sentinel
        == recorded
    )


@solver
def fail_once(marker: str) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if not Path(marker).exists():
            Path(marker).touch()
            raise RuntimeError("first attempt fails")
        return state

    return solve


@task
def d2_retry_task(marker: str) -> Task:
    return Task(
        dataset=[Sample(input="x", target="y")],
        solver=[fail_once(marker), record_sentinel()],
    )


def test_eval_retry_rebuilds_the_sentinel(tmp_path: Path) -> None:
    log = eval(
        d2_retry_task(str(tmp_path / "marker")),
        model="mockllm/model",
        sentinel={"block": d2_rule(reason="retry")},
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "error"
    retried = eval_retry(log, log_dir=str(tmp_path))[0]
    assert retried.eval.config.sentinel == {
        "block": {"name": "d2_rule", "params": {"reason": "retry"}}
    }
    assert active_root(retried) == "inspect_sentinel/concurrent"


def test_eval_set_sentinel(tmp_path: Path) -> None:
    success, logs = eval_set(
        sentinel_task(),
        log_dir=str(tmp_path),
        model="mockllm/model",
        sentinel=RULE_CONFIG,
    )
    assert success
    log = read_eval_log(logs[0].location)
    assert log.eval.config.sentinel == RULE_CONFIG
    assert active_root(log) == "inspect_sentinel/concurrent"


def test_eval_set_bad_config_fails_before_running(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a registered monitor or protocol"):
        eval_set(
            sentinel_task(),
            log_dir=str(tmp_path / "logs"),
            model="mockllm/model",
            sentinel=[{"name": "d2_missing"}],
        )
    assert not (tmp_path / "logs").exists() or not list(
        (tmp_path / "logs").glob("*.eval")
    )


def test_capture_applies_and_validates_the_sentinel_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "manifest.json"
    overrides = tmp_path / "overrides.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest))
    monkeypatch.setenv(INSPECT_EVAL_SET_OVERRIDES, str(overrides))

    overrides.write_text(json.dumps({"sentinel": [{"name": "d2_missing"}]}))
    with pytest.raises(ValueError, match="not a registered monitor or protocol"):
        eval_set(
            sentinel_task(),
            log_dir=str(tmp_path / "logs"),
            model="mockllm/model",
            sentinel=RULE_CONFIG,
        )
    assert not manifest.exists()

    overrides.write_text(json.dumps({"sentinel": RULE_CONFIG}))
    with pytest.raises(SystemExit):
        eval_set(sentinel_task(), log_dir=str(tmp_path / "logs"), model="mockllm/model")
    capture = EvalSetCapture.model_validate_json(manifest.read_bytes())
    assert capture.overrides is not None
    assert capture.overrides.sentinel == RULE_CONFIG


ran = False


@solver
def mark_ran() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        global ran
        ran = True
        return state

    return solve


@pytest.mark.parametrize(
    "sentinel,error,match",
    [
        ([{"name": "d2_missing"}], ValueError, "not a registered monitor or protocol"),
        ([{"name": "d2_rule", "params": {"bogus": 1}}], TypeError, "sentinel\\[0\\]"),
        ("no_such_file.yaml", ValueError, "neither a config file"),
        ([], ValueError, "at least one monitor or protocol"),
        (42, TypeError, "sentinel must be"),
    ],
)
def test_bad_config_fails_at_eval_start(
    sentinel: Any, error: type[Exception], match: str, tmp_path: Path
) -> None:
    global ran
    ran = False
    with pytest.raises(error, match=match):
        eval(
            Task(dataset=[Sample(input="x")], solver=mark_ran()),
            model="mockllm/model",
            sentinel=sentinel,
            log_dir=str(tmp_path),
        )
    assert not ran
    assert not list(tmp_path.glob("*.eval"))


def test_bad_task_config_fails_at_construction() -> None:
    with pytest.raises(ValueError, match="not a registered monitor or protocol"):
        sentinel_task([{"name": "d2_missing"}])


def test_mixed_constructed_and_config_is_rejected() -> None:
    with pytest.raises(TypeError, match="mixes"):
        sentinel_task([d2_rule(), {"name": "d2_rule"}])


def test_missing_package_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "inspect_sentinel._integration", None)
    with pytest.raises(
        PrerequisiteError, match="requires the inspect_sentinel package"
    ):
        sentinel_task(RULE_CONFIG)
    with pytest.raises(
        PrerequisiteError, match="requires the inspect_sentinel package"
    ):
        eval(sentinel_task(), model="mockllm/model", sentinel="d2_rule")
    log = eval(sentinel_task(), model="mockllm/model")[0]
    assert active_root(log) is None


def test_log_with_sentinel_loads_without_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = eval(
        sentinel_task(RULE_CONFIG), model="mockllm/model", log_dir=str(tmp_path)
    )[0]
    monkeypatch.setitem(sys.modules, "inspect_sentinel._integration", None)
    assert read_eval_log(log.location).eval.config.sentinel == RULE_CONFIG


CLI_TASK = """
from inspect_ai import Task, task
from inspect_ai._eval.eval_set_manifest import INSPECT_EVAL_SET_CAPTURE, EvalSetCapture
from inspect_ai._eval.eval_set_overrides import INSPECT_EVAL_SET_OVERRIDES
from inspect_ai._sentinel._context import active_sentinel
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver
from inspect_sentinel import BeforeToolCall, ControlProtocol, Decision, protocol


@protocol
def cli_rule(reason: str = "no") -> ControlProtocol:
    async def decide(context, step: BeforeToolCall) -> Decision | None:
        return Decision.reject(reason)

    return decide


@solver
def record_sentinel():
    async def solve(state, generate):
        root = active_sentinel()
        state.metadata["sentinel"] = registry_info(root).name if root else None
        return state

    return solve


@task
def cli_task():
    return Task(dataset=[Sample(input="x", target="y")], solver=record_sentinel())
"""


@pytest.mark.parametrize("via", ["option", "env"])
def test_cli_sentinel(tmp_path: Path, via: str) -> None:
    (tmp_path / "cli_task.py").write_text(CLI_TASK)
    (tmp_path / "sentinel.yaml").write_text(
        "sentinel:\n  - name: cli_rule\n    params:\n      reason: cli\n"
    )
    args = ["--sentinel", "sentinel.yaml"] if via == "option" else []
    env = {"INSPECT_EVAL_SENTINEL": "sentinel.yaml"} if via == "env" else {}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "inspect_ai._cli.main",
            "eval",
            "cli_task.py",
            "--model",
            "mockllm/model",
            "--log-dir",
            "logs",
            "--display",
            "none",
            *args,
        ],
        cwd=tmp_path,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    [log_file] = list((tmp_path / "logs").glob("*.eval"))
    log = read_eval_log(str(log_file))
    assert log.eval.config.sentinel == [
        {"name": "cli_rule", "params": {"reason": "cli"}}
    ]
    assert active_root(log) == "inspect_sentinel/concurrent"
