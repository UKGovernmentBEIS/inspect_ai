import inspect
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

from inspect_ai import (
    Task,
    eval,
    eval_async,
    eval_retry,
    eval_set,
    task,
    task_with,
)
from inspect_ai._display.core.config import task_config_str
from inspect_ai._display.core.display import TaskProfile
from inspect_ai._eval.eval_set_manifest import INSPECT_EVAL_SET_CAPTURE, EvalSetCapture
from inspect_ai._eval.eval_set_overrides import INSPECT_EVAL_SET_OVERRIDES
from inspect_ai._sentinel._context import active_sentinel
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.event import SentinelEvent, SpanBeginEvent, ToolEvent
from inspect_ai.log import (
    EvalConfig,
    EvalLog,
    SentinelConfig,
    SentinelEntry,
    read_eval_log,
)
from inspect_ai.model import (
    ChatMessageAssistant,
    GenerateConfig,
    ModelOutput,
    get_model,
)
from inspect_ai.model._call_tools import execute_tools
from inspect_ai.model._model import ModelName
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import Tool, ToolCall, tool

try:
    from inspect_sentinel import (
        BeforeToolCall,
        Context,
        Decision,
        Monitor,
        Observation,
        Protocol,
        monitor,
        observe_only,
        protocol,
        threshold,
    )
except ImportError:
    pytest.skip("inspect_sentinel is not installed", allow_module_level=True)


@monitor
def d2_suspicion(score: float = 0.5) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        return Observation.score(score)

    return check


@protocol
def d2_rule(reason: str = "no") -> Protocol:
    async def decide(context: Context, step: BeforeToolCall) -> Decision | None:
        return Decision.reject(reason)

    return decide


@tool
def addition() -> Tool:
    async def execute(x: int, y: int) -> str:
        """Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.
        """
        return str(x + y)

    return execute


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


def config_data(log: EvalLog) -> Any:
    assert log.eval.config.sentinel is not None
    return log.eval.config.sentinel.model_dump()


def test_task_sentinel_is_recorded_and_active() -> None:
    log = eval(sentinel_task(d2_rule(reason="no")), model="mockllm/model")[0]
    assert config_data(log) == {"name": "d2_rule", "params": {"reason": "no"}}
    assert active_root(log) == "d2_rule"


def test_no_sentinel_leaves_the_config_empty() -> None:
    task = Task(
        dataset=[Sample(input="x", target="y")],
        solver=[record_sentinel(), use_tools(addition()), generate()],
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                "mockllm/model", tool_name="addition", tool_arguments={"x": 1, "y": 2}
            ),
            ModelOutput.from_content("mockllm/model", content="done"),
        ],
        memoize=False,
    )
    log = eval(task, model=model)[0]
    assert log.eval.config.sentinel is None
    assert active_root(log) is None
    assert log.samples
    events = log.samples[0].events
    assert [e.result for e in events if isinstance(e, ToolEvent)] == ["3"]
    assert not any(isinstance(e, SentinelEvent) for e in events)
    assert not any(
        isinstance(e, SpanBeginEvent) and e.type == "sentinel" for e in events
    )


def test_observe_only_records_monitors_with_nothing_acting() -> None:
    log = eval(
        sentinel_task(observe_only({"watch": d2_suspicion(score=0.2)})),
        model="mockllm/model",
    )[0]
    assert config_data(log) == {
        "name": "observe_only",
        "params": {},
        "monitors": {"watch": {"name": "d2_suspicion", "params": {"score": 0.2}}},
    }
    assert active_root(log) == "inspect_sentinel/observe_only"


@pytest.mark.parametrize(
    "sentinel",
    [
        lambda: d2_suspicion(),
        lambda: {"watch": d2_suspicion()},
        lambda: [{"name": "d2_suspicion"}],
        lambda: "d2_suspicion",
    ],
)
def test_monitors_alone_fail_at_task_construction(
    sentinel: Callable[[], Any],
) -> None:
    with pytest.raises(ValueError, match=r"only monitors: .*observe_only\(\)"):
        sentinel_task(sentinel())


def test_task_with_sets_and_clears_the_sentinel() -> None:
    log = eval(task_with(sentinel_task(), sentinel=RULE_CONFIG), model="mockllm/model")[
        0
    ]
    assert config_data(log) == RULE_CONFIG
    log = eval(
        task_with(sentinel_task(d2_rule()), sentinel=None), model="mockllm/model"
    )[0]
    assert log.eval.config.sentinel is None
    assert active_root(log) is None


def test_eval_sentinel_overrides_the_task() -> None:
    log = eval(
        sentinel_task(d2_rule(reason="task")),
        model="mockllm/model",
        sentinel=[d2_suspicion(score=0.7), d2_rule(reason="eval")],
    )[0]
    assert config_data(log) == [
        {"name": "d2_suspicion", "params": {"score": 0.7}},
        {"name": "d2_rule", "params": {"reason": "eval"}},
    ]
    assert active_root(log) == "inspect_sentinel/concurrent"


def test_config_file_and_registered_name(tmp_path: Path) -> None:
    config = tmp_path / "sentinel.yaml"
    config.write_text(
        "sentinel:\n  block:\n    name: d2_rule\n    params:\n      reason: file\n"
    )
    log = eval(sentinel_task(), model="mockllm/model", sentinel=str(config))[0]
    assert config_data(log) == {
        "block": {"name": "d2_rule", "params": {"reason": "file"}}
    }

    log = eval(sentinel_task(), model="mockllm/model", sentinel="d2_rule")[0]
    assert config_data(log) == {"name": "d2_rule", "params": {}}
    assert active_root(log) == "d2_rule"


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
    assert config_data(log) == config

    read = read_eval_log(log.location)
    assert read.eval.config.sentinel == recorded
    assert (
        EvalConfig.model_validate_json(read.eval.config.model_dump_json()).sentinel
        == recorded
    )


@monitor(version=3)
def d2_versioned(score: float = 0.5) -> Monitor:
    async def check(context: Context, step: BeforeToolCall) -> Observation | None:
        return Observation.score(score)

    return check


def test_entry_version_is_a_field_not_nested() -> None:
    entry = SentinelEntry.model_validate(
        {"name": "threshold", "version": 2, "monitors": [{"name": "d2_suspicion"}]}
    )
    assert entry.version == 2
    assert list(entry.nested) == ["monitors"]
    assert entry.model_dump() == {
        "name": "threshold",
        "params": {},
        "version": 2,
        "monitors": [{"name": "d2_suspicion", "params": {}}],
    }


def test_entry_without_version_omits_it() -> None:
    entry = SentinelEntry.model_validate({"name": "d2_rule"})
    assert entry.version is None
    assert "version" not in entry.model_dump()
    assert "version" not in entry.model_dump_json()


@pytest.mark.parametrize("version", [True, "3", 3.0])
def test_entry_version_must_be_an_int(version: object) -> None:
    with pytest.raises(ValidationError):
        SentinelEntry.model_validate({"name": "d2_rule", "version": version})


@pytest.mark.parametrize(
    "config",
    [
        [],
        {},
        {"name": "threshold", "monitors": []},
        {"name": "threshold", "monitors": {}},
    ],
)
def test_empty_layer_is_rejected(config: Any) -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        SentinelConfig.model_validate(config)


@pytest.mark.parametrize("fn", [eval, eval_async, eval_set])
def test_eval_type_hints_resolve(fn: Callable[..., Any]) -> None:
    assert "sentinel" in get_type_hints(fn)


def test_entry_meta_round_trips_and_is_not_nested() -> None:
    data = {
        "name": "threshold",
        "params": {},
        "meta": {"added": {"later": [1, "two", None]}},
        "monitors": [{"name": "d2_suspicion", "params": {}}],
    }
    entry = SentinelEntry.model_validate(data)
    assert entry.meta == {"added": {"later": [1, "two", None]}}
    assert list(entry.nested) == ["monitors"]
    assert entry.model_dump() == data
    assert SentinelEntry.model_validate_json(entry.model_dump_json()) == entry


def test_entry_without_meta_omits_it() -> None:
    entry = SentinelEntry.model_validate({"name": "d2_rule"})
    assert entry.meta is None
    assert "meta" not in entry.model_dump()
    assert "meta" not in entry.model_dump_json()


def test_log_config_without_version_loads() -> None:
    config = EvalConfig.model_validate_json(
        json.dumps({"sentinel": [{"name": "d2_rule", "params": {"reason": "no"}}]})
    )
    assert config.sentinel is not None
    assert config.sentinel.model_dump() == RULE_CONFIG


def test_version_round_trips_through_the_log(tmp_path: Path) -> None:
    log = eval(
        sentinel_task([d2_versioned(score=0.1), d2_rule(reason="no")]),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )[0]
    expected = [
        {"name": "d2_versioned", "params": {"score": 0.1}, "version": 3},
        *RULE_CONFIG,
    ]
    assert config_data(log) == expected
    read = read_eval_log(log.location)
    assert read.eval.config.sentinel == log.eval.config.sentinel
    assert config_data(read) == expected


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
    assert config_data(retried) == {
        "block": {"name": "d2_rule", "params": {"reason": "retry"}}
    }
    assert active_root(retried) == "inspect_sentinel/concurrent"


@solver
def call_addition() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state.messages.append(
            ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(id="c1", function="addition", arguments={"x": 1, "y": 1})
                ],
            )
        )
        result = await execute_tools(state.messages, [addition()])
        state.messages.extend(result.messages)
        return state

    return solve


@task
def d2_lone_root_task(marker: str) -> Task:
    return Task(
        dataset=[Sample(input="x", target="y")],
        solver=[call_addition(), fail_once(marker)],
        sentinel=threshold(d2_suspicion(score=0.9), reject_at=0.5),
    )


def sentinel_paths(log: EvalLog) -> list[tuple[str, str]]:
    assert log.samples
    return [
        (e.factory, e.path)
        for e in log.samples[0].events
        if isinstance(e, SentinelEvent)
    ]


def test_eval_retry_records_a_lone_roots_paths_as_the_first_run_did(
    tmp_path: Path,
) -> None:
    log = eval(
        d2_lone_root_task(str(tmp_path / "marker")),
        model="mockllm/model",
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "error"
    recorded = log.eval.config.sentinel
    assert isinstance(recorded, SentinelConfig)
    assert isinstance(recorded.root, SentinelEntry)
    assert recorded.root.name == "threshold"
    retried = eval_retry(log, log_dir=str(tmp_path))[0]
    assert retried.status == "success", retried.error
    expected = [("d2_suspicion", "d2_suspicion"), ("inspect_sentinel/threshold", "")]
    assert sentinel_paths(log) == expected
    assert sentinel_paths(retried) == expected


def test_eval_set_sentinel(tmp_path: Path) -> None:
    success, logs = eval_set(
        sentinel_task(),
        log_dir=str(tmp_path),
        model="mockllm/model",
        sentinel=RULE_CONFIG,
    )
    assert success
    log = read_eval_log(logs[0].location)
    assert config_data(log) == RULE_CONFIG
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
    assert capture.overrides.sentinel == SentinelConfig.model_validate(RULE_CONFIG)


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
        ("d2_suspicion", ValueError, "observe_only"),
        ([{"name": "d2_suspicion"}], ValueError, "observe_only"),
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
    with pytest.raises(PrerequisiteError) as raised:
        sentinel_task(RULE_CONFIG)
    message = str(raised.value.message)
    assert "pip install inspect-sentinel" in message
    with pytest.raises(
        PrerequisiteError, match="requires the inspect_sentinel package"
    ):
        eval(sentinel_task(), model="mockllm/model", sentinel="d2_rule")
    log = eval(sentinel_task(), model="mockllm/model")[0]
    assert active_root(log) is None


@pytest.mark.parametrize(
    "config,shown",
    [
        ({"name": "d2_rule", "params": {"reason": "no"}}, "d2_rule"),
        ([{"name": "d2_rule"}, {"name": "d2_suspicion"}], "d2_rule,d2_suspicion"),
        ({"first": {"name": "d2_rule"}, "second": {"name": "d2_rule"}}, "first,second"),
    ],
)
def test_task_header_shows_the_sentinel_names(config: Any, shown: str) -> None:
    profile = TaskProfile(
        name="task",
        file=None,
        model=ModelName("mockllm/model"),
        agent=None,
        dataset="(samples)",
        scorer="accuracy",
        samples=1,
        steps=1,
        eval_config=EvalConfig(sentinel=SentinelConfig.model_validate(config)),
        task_args={},
        generate_config=GenerateConfig(),
        tags=None,
        log_location="x",
        task_id="id",
        task_cancel=None,
    )
    assert f"sentinel: {shown}," in task_config_str(profile)


def test_log_with_sentinel_loads_without_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = eval(
        sentinel_task(RULE_CONFIG), model="mockllm/model", log_dir=str(tmp_path)
    )[0]
    monkeypatch.setitem(sys.modules, "inspect_sentinel._integration", None)
    assert config_data(read_eval_log(log.location)) == RULE_CONFIG


CLI_TASK = """
from inspect_ai import Task, task
from inspect_ai._eval.eval_set_manifest import INSPECT_EVAL_SET_CAPTURE, EvalSetCapture
from inspect_ai._eval.eval_set_overrides import INSPECT_EVAL_SET_OVERRIDES
from inspect_ai._sentinel._context import active_sentinel
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver
from inspect_sentinel import BeforeToolCall, Decision, Protocol, protocol


@protocol
def cli_rule(reason: str = "no") -> Protocol:
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
    assert config_data(log) == [{"name": "cli_rule", "params": {"reason": "cli"}}]
    assert active_root(log) == "inspect_sentinel/concurrent"


@pytest.mark.parametrize("fn", [Task.__init__, eval, eval_async, eval_set])
def test_sentinel_is_the_last_positional_parameter(fn: Callable[..., Any]) -> None:
    # added after the other parameters, so it must not shift their positions
    names = [
        p.name
        for p in inspect.signature(fn).parameters.values()
        if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    ]
    assert names[-1] == "sentinel"
