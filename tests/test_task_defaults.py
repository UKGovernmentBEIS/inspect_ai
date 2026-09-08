import importlib.util
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import yaml
from click.testing import CliRunner

from inspect_ai import (
    RunConfig,
    Task,
    eval,
    eval_async,
    eval_retry,
    eval_set,
    task,
)
from inspect_ai._cli.eval import eval_command, eval_set_command
from inspect_ai._cli.list import tasks as list_tasks_command
from inspect_ai._cli.log import export_config_command
from inspect_ai._eval.list import list_tasks
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import file, filesystem, local_path
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, list_eval_logs, read_eval_log
from inspect_ai.log._config import eval_log_to_run_config_dict
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.solver import SolverSpec, generate


@dataclass
class TaskSource:
    source: Path
    config: Path
    name: str

    @property
    def spec(self) -> str:
        return f"{self.source}@{self.name}"

    @property
    def target(self) -> str:
        return self.spec

    def load(self, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Task]:
        spec = importlib.util.spec_from_file_location(self.name, self.source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, self.name, module)
        spec.loader.exec_module(module)
        return cast(Callable[..., Task], getattr(module, self.name))


@pytest.fixture(autouse=True)
def isolated_task_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    import inspect_ai._util.registry as registry

    monkeypatch.setattr(registry, "_registry", registry._registry.copy())
    for name in os.environ:
        if name.startswith("INSPECT_EVAL_"):
            monkeypatch.delenv(name)


def make_source(
    tmp_path: Path,
    config: dict[str, Any] | str | None,
    config_reference: str | None = None,
) -> TaskSource:
    """Write the standard task to a module on disk, config alongside it.

    Only for tests that need a real source file: relative default_config
    resolution, file@name CLI references, discovery, or import-time behaviour.
    Otherwise use make_task, which defines the same task in-process.
    """
    name = f"task_defaults_{uuid4().hex}"
    source = tmp_path / f"{name}.py"
    config_path = tmp_path / f"{name}.yaml"
    if config is not None:
        config_path.write_text(
            config if isinstance(config, str) else yaml.safe_dump(config)
        )
    reference = config_reference if config_reference is not None else config_path.name
    source.write_text(
        "from typing import Any\n"
        "from inspect_ai import Task, task\n"
        "from inspect_ai.dataset import Sample\n"
        "from inspect_ai.model import GenerateConfig, get_model\n"
        "from inspect_ai.solver import generate\n\n"
        f"@task(default_config={reference!r})\n"
        f"def {name}(value: Any = 'signature', keep: str = 'signature-keep', "
        "fallback: str = 'signature-fallback') -> Task:\n"
        "    return Task(\n"
        "        dataset=[Sample(id=i, input='Hello', target='Hello') for i in (1, 2)],\n"
        "        solver=generate(),\n"
        "        config=GenerateConfig(temperature=0.9, seed=91, max_tokens=32),\n"
        "        message_limit=20, token_limit=200, epochs=1,\n"
        "        model_roles={'grader': get_model('mockllm/constructor')},\n"
        "        metadata={'value': value, 'keep': keep, 'fallback': fallback},\n"
        "    )\n"
    )
    return TaskSource(source=source, config=config_path, name=name)


@dataclass
class TaskDefault:
    """A task defined in-process with an attached default config."""

    factory: Callable[..., Task]
    config: Path
    name: str

    @property
    def target(self) -> Callable[..., Task]:
        return self.factory


def make_task(
    tmp_path: Path,
    config: dict[str, Any] | str | None,
    config_reference: str | None = None,
) -> TaskDefault:
    """Same task as make_source, defined here rather than written to disk.

    Use this unless the test needs a source file: relative default_config
    resolution, file@name CLI references, discovery, or import-time behaviour.
    The config path is absolute so it does not resolve against this module.
    """
    name = f"task_defaults_{uuid4().hex}"
    config_path = tmp_path / f"{name}.yaml"
    if config is not None:
        config_path.write_text(
            config if isinstance(config, str) else yaml.safe_dump(config)
        )
    reference = config_reference if config_reference is not None else str(config_path)

    @task(name=name, default_config=reference)
    def factory(
        value: Any = "signature",
        keep: str = "signature-keep",
        fallback: str = "signature-fallback",
    ) -> Task:
        return Task(
            dataset=[Sample(id=i, input="Hello", target="Hello") for i in (1, 2)],
            solver=generate(),
            config=GenerateConfig(temperature=0.9, seed=91, max_tokens=32),
            message_limit=20,
            token_limit=200,
            epochs=1,
            model_roles={"grader": get_model("mockllm/constructor")},
            metadata={"value": value, "keep": keep, "fallback": fallback},
        )

    return TaskDefault(factory=factory, config=config_path, name=name)


def runtime_config(temperature: float = 0.2) -> dict[str, Any]:
    return {
        "generate_config": {"temperature": temperature, "max_tokens": 16},
        "eval_config": {
            "limit": 1,
            "message_limit": 8,
            "token_limit": 100,
            "epochs": 2,
        },
        "model_roles": {
            "grader": {
                "model": "mockllm/default-grader",
                "config": {"temperature": 0.3},
            }
        },
        "solver": {
            "solver": "prompt_template",
            "args": {"template": "Default: {prompt}"},
        },
    }


def run_task(
    source: TaskSource | TaskDefault, tmp_path: Path, **kwargs: Any
) -> EvalLog:
    logs = eval(
        source.target,
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        display="none",
        **kwargs,
    )
    assert len(logs) == 1
    assert logs[0].status == "success"
    return logs[0]


def run_cli(
    tmp_path: Path, args: list[str], env: dict[str, str | None] | None = None
) -> EvalLog:
    log_dir = tmp_path / f"cli-logs-{uuid4().hex}"
    result = CliRunner().invoke(
        eval_command,
        [
            *args,
            "--model",
            "mockllm/model",
            "--log-dir",
            str(log_dir),
            "--display",
            "none",
        ],
        env=env,
    )
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    logs = list_eval_logs(str(log_dir))
    assert len(logs) == 1
    log = read_eval_log(logs[0])
    assert log.status == "success"
    return log


def effective_run_config(log: EvalLog) -> dict[str, Any]:
    config = eval_log_to_run_config_dict(log)
    model_config = config["model"].pop("config", {})
    config["generate_config"] = model_config | config.get("generate_config", {})
    return config


def assert_constructor_config(log: EvalLog) -> None:
    assert log.eval.task_args == {
        "value": "signature",
        "keep": "signature-keep",
        "fallback": "signature-fallback",
    }
    assert log.plan.config.temperature == 0.9
    assert log.plan.config.max_tokens == 32
    assert log.eval.config.message_limit == 20
    assert log.eval.config.token_limit == 200
    assert log.eval.config.epochs == 1
    assert log.eval.config.limit is None
    assert log.eval.model_roles is not None
    grader = log.eval.model_roles["grader"]
    assert not isinstance(grader, list)
    assert grader.model == "mockllm/constructor"
    assert log.samples and log.samples[0].output.completion


def assert_default_config(log: EvalLog, config: Path) -> None:
    assert log.plan.config.temperature == 0.2
    assert log.plan.config.max_tokens == 16
    assert log.plan.config.seed == 91
    assert log.eval.config.limit == 1
    assert log.eval.config.message_limit == 8
    assert log.eval.config.token_limit == 100
    assert log.eval.config.epochs == 2
    assert log.eval.model == "mockllm/model"
    assert log.eval.model_roles is not None
    grader = log.eval.model_roles["grader"]
    assert not isinstance(grader, list)
    assert grader.model == "mockllm/default-grader"
    assert grader.config.temperature == 0.3
    assert log.samples and len(log.samples) == 2
    assert all(sample.messages[0].text == "Default: Hello" for sample in log.samples)
    assert (
        getattr(log.eval, "run_config_source", None)
        == f"task_default:{config.resolve()}"
    )


@pytest.mark.parametrize(
    "content", [None, "invalid: [", {"task": {"args": {"value": "file"}}}]
)
def test_default_config_is_inert_at_import_and_direct_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: dict[str, Any] | str | None,
) -> None:
    source = make_source(tmp_path, content)
    factory = source.load(monkeypatch)
    instance = factory()
    assert instance.metadata == {
        "value": "signature",
        "keep": "signature-keep",
        "fallback": "signature-fallback",
    }
    assert instance.config.temperature == 0.9
    explicit = factory(value=False)
    assert explicit.metadata is not None
    assert explicit.metadata["value"] is False


@pytest.mark.parametrize("kind", ["callable", "name", "file"])
def test_default_config_resolves_relative_to_task_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    source = make_source(tmp_path, None)
    factory = source.load(monkeypatch)
    source.config.write_text(yaml.safe_dump(runtime_config()))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / source.config.name).write_text("invalid: [")
    monkeypatch.chdir(elsewhere)
    target = (
        factory
        if kind == "callable"
        else source.name
        if kind == "name"
        else source.spec
    )
    log = eval(
        target, model="mockllm/model", log_dir=str(tmp_path / "logs"), display="none"
    )[0]
    assert log.status == "success"
    assert_default_config(log, source.config)
    persisted = read_eval_log(log.location)
    assert (
        getattr(persisted.eval, "run_config_source", None)
        == f"task_default:{source.config.resolve()}"
    )


async def test_eval_async_loads_task_default(tmp_path: Path) -> None:
    attached = make_task(tmp_path, runtime_config())
    logs = await eval_async(
        attached.factory,
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        ctl_server=False,
    )
    assert logs[0].status == "success"
    assert_default_config(logs[0], attached.config)


@pytest.mark.parametrize(
    "content",
    [None, "invalid: [", runtime_config() | {"task": {"args": {"value": "file"}}}],
)
def test_preconstructed_task_skips_entire_default(
    tmp_path: Path,
    content: dict[str, Any] | str | None,
) -> None:
    instance = make_task(tmp_path, content).factory()
    log = eval(
        instance, model="mockllm/model", log_dir=str(tmp_path / "logs"), display="none"
    )[0]
    assert log.status == "success"
    assert_constructor_config(log)
    assert getattr(log.eval, "run_config_source", None) is None


def test_run_config_accepts_task_args_without_reference() -> None:
    args = {"value": None, "keep": "file"}
    config = RunConfig.model_validate({"task": {"args": args}})
    assert config.to_params() == {"task_args": args}
    assert RunConfig.model_validate_json(config.model_dump_json()).to_params() == {
        "task_args": args
    }


@pytest.mark.parametrize(
    "config",
    [
        {"model": "mockllm/forbidden"},
        {"model": None},
        {"model": {"model": "mockllm/forbidden"}},
        {"task": "not_installed/forbidden"},
        {"task": {"task": "not_installed/forbidden", "args": {"value": "file"}}},
    ],
)
def test_task_default_rejects_model_and_task_reference(
    tmp_path: Path, config: dict[str, Any]
) -> None:
    attached = make_task(tmp_path, config)
    with pytest.raises((PrerequisiteError, ValueError)) as error:
        run_task(attached, tmp_path)
    assert "model" in str(error.value).lower() or "task" in str(error.value).lower()


def test_task_default_mismatched_task_error_names_both(tmp_path: Path) -> None:
    attached = make_task(tmp_path, {"task": "other_task"})
    with pytest.raises(ValueError) as error:
        run_task(attached, tmp_path)
    assert "other_task" in str(error.value)
    assert attached.name in str(error.value)


@pytest.mark.parametrize("form", ["string", "object"])
def test_task_default_may_name_its_own_task(tmp_path: Path, form: str) -> None:
    """A matching task reference documents the file without changing selection."""
    attached = make_task(tmp_path, None)
    config = runtime_config()
    if form == "string":
        config["task"] = attached.name
    else:
        config["task"] = {"task": attached.name, "args": {"value": "file"}}
    attached.config.write_text(yaml.safe_dump(config))
    log = run_task(attached, tmp_path)
    assert_default_config(log, attached.config)
    if form == "object":
        assert log.eval.task_args["value"] == "file"


def test_task_default_file_works_standalone_as_run_config(tmp_path: Path) -> None:
    """Naming the task lets the same file select it via --run-config.

    The task is already registered in-process, as package tasks are on import,
    so the bare registry name resolves.
    """
    config = runtime_config()
    attached = make_task(tmp_path, config)
    config["task"] = attached.name
    attached.config.write_text(yaml.safe_dump(config))
    with_default = run_task(attached, tmp_path)
    log_dir = tmp_path / "standalone"
    result = CliRunner().invoke(
        eval_command,
        [
            "--run-config",
            str(attached.config),
            "--model",
            "mockllm/model",
            "--log-dir",
            str(log_dir),
            "--display",
            "none",
        ],
    )
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    logs = list_eval_logs(str(log_dir))
    assert len(logs) == 1
    standalone = read_eval_log(logs[0])
    assert standalone.status == "success"
    # the task reference records how each run was invoked; everything the
    # file governs must match
    expected = effective_run_config(with_default)
    actual = effective_run_config(standalone)
    assert expected["task"].pop("task").endswith(attached.name)
    assert actual["task"].pop("task").endswith(attached.name)
    assert actual == expected
    assert standalone.eval.run_config_source == f"cli:{attached.config}"


@pytest.mark.parametrize(
    "content", [None, "invalid: [", {"unknown_default_field": True}]
)
def test_invalid_attached_file_is_reported_at_eval(
    tmp_path: Path, content: dict[str, Any] | str | None
) -> None:
    attached = make_task(tmp_path, content)
    with pytest.raises(
        (PrerequisiteError, ValueError, FileNotFoundError, yaml.YAMLError)
    ):
        run_task(attached, tmp_path)


@pytest.mark.parametrize("value", [None, False, 0, [], {}, "caller"])
def test_task_argument_precedence_preserves_explicit_values(
    tmp_path: Path, value: Any
) -> None:
    attached = make_task(
        tmp_path, {"task": {"args": {"value": "file", "keep": "file-keep"}}}
    )
    log = run_task(attached, tmp_path, task_args={"value": value})
    expected = {"value": value, "keep": "file-keep", "fallback": "signature-fallback"}
    assert log.eval.task_args == expected
    assert log.eval.metadata == expected


def test_task_argument_file_over_signature_fallback(tmp_path: Path) -> None:
    attached = make_task(tmp_path, {"task": {"args": {"value": "file"}}})
    log = run_task(attached, tmp_path)
    assert log.eval.task_args == {
        "value": "file",
        "keep": "signature-keep",
        "fallback": "signature-fallback",
    }


def test_eval_kwargs_override_file_and_constructor(tmp_path: Path) -> None:
    attached = make_task(tmp_path, runtime_config())
    log = run_task(
        attached,
        tmp_path,
        temperature=0,
        message_limit=5,
        epochs=1,
        model_roles={
            "grader": get_model("mockllm/caller", config=GenerateConfig(temperature=0))
        },
        solver=SolverSpec(
            "prompt_template",
            args={"template": "Caller: {prompt}"},
            args_passed={"template": "Caller: {prompt}"},
        ),
    )
    assert log.plan.config.temperature == 0
    assert log.plan.config.max_tokens == 16
    assert log.eval.config.message_limit == 5
    assert log.eval.config.token_limit == 100
    assert log.eval.config.epochs == 1
    assert log.eval.model_roles is not None
    grader = log.eval.model_roles["grader"]
    assert not isinstance(grader, list)
    assert grader.model == "mockllm/caller"
    assert grader.config.temperature == 0
    assert log.samples and log.samples[0].messages[0].text == "Caller: Hello"


@pytest.mark.parametrize("override", ["flag", "environment"])
def test_cli_and_environment_override_task_default(
    tmp_path: Path, override: str
) -> None:
    source = make_source(tmp_path, runtime_config())
    args = [source.spec]
    env: dict[str, str | None] | None = None
    if override == "flag":
        args.extend(["--temperature", "0", "--message-limit", "5"])
    else:
        env = {"INSPECT_EVAL_TEMPERATURE": "0", "INSPECT_EVAL_MESSAGE_LIMIT": "5"}
    log = run_cli(tmp_path, args, env)
    assert log.plan.config.temperature == 0
    assert log.eval.config.message_limit == 5
    assert log.plan.config.max_tokens == 16
    assert log.eval.config.token_limit == 100
    assert (
        getattr(log.eval, "run_config_source", None)
        == f"task_default:{source.config.resolve()}"
    )


@pytest.mark.parametrize("interface", ["api", "cli"])
@pytest.mark.parametrize("content", [None, "invalid: [", runtime_config()])
def test_opt_out_skips_entire_default(
    tmp_path: Path, interface: str, content: dict[str, Any] | str | None
) -> None:
    source = make_source(tmp_path, content)
    log = (
        run_task(source, tmp_path, default_config=False)
        if interface == "api"
        else run_cli(tmp_path, [source.spec, "--no-default-config"])
    )
    assert_constructor_config(log)
    assert getattr(log.eval, "run_config_source", None) is None


@pytest.mark.parametrize("content", [None, "invalid: [", runtime_config()])
@pytest.mark.parametrize("replacement", [{}, {"generate_config": {"temperature": 0.4}}])
def test_explicit_run_config_replaces_attached_default(
    tmp_path: Path, content: dict[str, Any] | str | None, replacement: dict[str, Any]
) -> None:
    source = make_source(tmp_path, content)
    path = tmp_path / "explicit.yaml"
    path.write_text(yaml.safe_dump(replacement))
    log = run_cli(tmp_path, [source.spec, "--run-config", str(path)])
    assert log.plan.config.temperature == replacement.get("generate_config", {}).get(
        "temperature", 0.9
    )
    assert log.plan.config.max_tokens == 32
    assert log.eval.config.message_limit == 20
    assert log.eval.config.token_limit == 200
    assert log.eval.config.epochs == 1
    assert log.eval.config.limit is None
    assert getattr(log.eval, "run_config_source", None) == f"cli:{path}"


@pytest.mark.parametrize("interface", ["eval", "eval_set"])
def test_two_tasks_have_isolated_defaults(tmp_path: Path, interface: str) -> None:
    first = make_task(tmp_path, runtime_config())
    second_config = runtime_config(0.7)
    second_config["eval_config"] = {
        "limit": 2,
        "message_limit": 12,
        "token_limit": 150,
        "epochs": 1,
    }
    second_config["model_roles"] = {"grader": {"model": "mockllm/second"}}
    second_config["solver"] = {
        "solver": "system_message",
        "args": {"template": "Second"},
    }
    second = make_task(tmp_path, second_config)
    kwargs: dict[str, Any] = {
        "model": "mockllm/model",
        "log_dir": str(tmp_path / "logs"),
        "display": "none",
    }
    if interface == "eval_set":
        success, logs = eval_set(
            [first.factory, second.factory], retry_attempts=0, **kwargs
        )
        assert success
    else:
        logs = eval([first.factory, second.factory], **kwargs)
    assert len(logs) == 2
    by_name = {log.eval.task: read_eval_log(log.location) for log in logs}
    assert_default_config(by_name[first.name], first.config)
    other = by_name[second.name]
    assert other.status == "success"
    assert other.plan.config.temperature == 0.7
    assert other.eval.config.limit == 2
    assert other.eval.config.message_limit == 12
    assert other.eval.config.token_limit == 150
    assert other.eval.config.epochs == 1
    assert other.eval.model_roles is not None
    grader = other.eval.model_roles["grader"]
    assert not isinstance(grader, list)
    assert grader.model == "mockllm/second"
    assert other.samples and all(
        sample.messages[0].text == "Second" for sample in other.samples
    )
    assert (
        getattr(other.eval, "run_config_source", None)
        == f"task_default:{second.config.resolve()}"
    )


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_export_config_replay_is_independent_of_attached_file(
    tmp_path: Path, change: str
) -> None:
    attached = make_task(tmp_path, runtime_config())
    original = run_task(attached, tmp_path)
    exported = tmp_path / "exported.yaml"
    result = CliRunner().invoke(
        export_config_command, [original.location, "--output", str(exported)]
    )
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    if change == "modify":
        attached.config.write_text(yaml.safe_dump(runtime_config(0.8)))
    else:
        attached.config.unlink()
    replay = run_cli(tmp_path, ["--run-config", str(exported)])
    assert effective_run_config(replay) == effective_run_config(original)
    assert getattr(replay.eval, "run_config_source", None) == f"cli:{exported}"
    assert_default_config(original, attached.config)


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_retry_uses_logged_configuration_not_attached_file(
    tmp_path: Path, change: str
) -> None:
    attached = make_task(tmp_path, runtime_config())
    original = run_task(attached, tmp_path)
    if change == "modify":
        attached.config.write_text(yaml.safe_dump(runtime_config(0.8)))
    else:
        attached.config.unlink()
    retried = eval_retry(
        original.location, log_dir=str(tmp_path / "retry"), display="none"
    )[0]
    assert retried.status == "success"
    assert effective_run_config(retried) == effective_run_config(original)
    assert_default_config(original, attached.config)


@pytest.mark.parametrize("changed_field", ["task_args", "temperature", "token_limit"])
def test_eval_set_reuses_logs_and_selects_changed_defaults(
    tmp_path: Path, changed_field: str
) -> None:
    config = runtime_config()
    config["task"] = {"args": {"value": "first"}}
    attached = make_task(tmp_path, config)
    kwargs: dict[str, Any] = {
        "model": "mockllm/model",
        "log_dir": str(tmp_path / "set"),
        "display": "none",
        "retry_attempts": 0,
        "log_dir_allow_dirty": True,
    }
    success, first = eval_set(attached.factory, **kwargs)
    assert success and len(first) == 1
    success, reused = eval_set(attached.factory, **kwargs)
    assert success and len(reused) == 1
    assert local_path(reused[0].location) == local_path(first[0].location)
    assert len(list_eval_logs(kwargs["log_dir"])) == 1
    if changed_field == "task_args":
        config["task"]["args"]["value"] = "second"
    elif changed_field == "temperature":
        config["generate_config"]["temperature"] = 0.8
    else:
        config["eval_config"]["token_limit"] = 150
    attached.config.write_text(yaml.safe_dump(config))
    success, changed = eval_set(attached.factory, **kwargs)
    assert success and len(changed) == 1
    assert local_path(changed[0].location) != local_path(first[0].location)
    assert len(list_eval_logs(kwargs["log_dir"])) == 2
    assert changed[0].eval.task_args["value"] == config["task"]["args"]["value"]
    assert (
        changed[0].plan.config.temperature == config["generate_config"]["temperature"]
    )
    assert changed[0].eval.config.token_limit == config["eval_config"]["token_limit"]


@pytest.mark.parametrize("location", ["absolute", "file_uri", "memory"])
def test_attached_config_filesystem_locations(tmp_path: Path, location: str) -> None:
    path = tmp_path / "default config.yaml"
    reference = (
        f"memory://task-defaults-{uuid4().hex}/defaults.yaml"
        if location == "memory"
        else path.as_uri()
        if location == "file_uri"
        else str(path)
    )
    with file(reference, "w") as stream:
        stream.write(yaml.safe_dump({"generate_config": {"temperature": 0.2}}))
    try:
        attached = make_task(tmp_path, None, config_reference=reference)
        log = run_task(attached, tmp_path)
        assert log.plan.config.temperature == 0.2
        assert log.plan.config.seed == 91
    finally:
        if location == "memory":
            filesystem(reference).rm(reference)


def test_task_default_discovery_does_not_read_file(tmp_path: Path) -> None:
    source = make_source(tmp_path, "invalid: [")
    # list_tasks globs relative to root_dir (the cwd for the CLI)
    discovered = list_tasks([source.source.name], absolute=True, root_dir=tmp_path)
    assert len(discovered) == 1
    assert discovered[0].default_config == source.config.name
    # the CLI's root_dir default binds the import-time cwd, so chdir does not
    # reach it; address the file relative to that directory instead
    relative = os.path.relpath(source.source, Path.cwd())
    result = CliRunner().invoke(list_tasks_command, [relative, "--json"])
    assert result.exit_code == 0, result.output
    assert (
        json.loads(result.output)[0]["attribs"]["default_config"] == source.config.name
    )


def test_task_default_notice_is_displayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect_ai._display.core.active as active_mod

    # the display is created once per process, so an earlier eval in this
    # module would otherwise leave a non-plain display in place
    monkeypatch.setattr(active_mod, "_active_display", None)
    source = make_source(tmp_path, {"generate_config": {"temperature": 0.2}})
    result = CliRunner().invoke(
        eval_command,
        [
            source.spec,
            "--model",
            "mockllm/model",
            "--log-dir",
            str(tmp_path / "logs"),
            "--display",
            "plain",
        ],
    )
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    assert f"default config: {source.config.name}" in result.output
    assert "--no-default-config" in result.output


@pytest.mark.parametrize(
    "file_selection, override, expected",
    [
        ({"sample_id": [1]}, {"limit": 2}, {"limit": 2, "sample_id": None}),
        (
            {"sample_id": [1]},
            {"sample_shuffle": 7},
            {"sample_shuffle": 7, "sample_id": None},
        ),
        (
            {"limit": 1, "sample_shuffle": 7},
            {"sample_id": [2]},
            {"limit": None, "sample_shuffle": None, "sample_id": [2]},
        ),
    ],
)
def test_explicit_sample_selection_replaces_file_selection(
    tmp_path: Path,
    file_selection: dict[str, Any],
    override: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    """limit/sample_shuffle and sample_id are one setting, not three.

    Merging them field by field would let a file sample_id survive an explicit
    limit and silently win in slice_dataset.
    """
    attached = make_task(tmp_path, {"eval_config": file_selection})
    log = run_task(attached, tmp_path, **override)
    for key, value in expected.items():
        assert getattr(log.eval.config, key) == value, key
    assert log.samples is not None
    if "sample_id" in override:
        assert [s.id for s in log.samples] == override["sample_id"]
    else:
        assert len(log.samples) == 2


def test_eval_set_reuses_log_when_file_sets_shuffle_and_caller_limits(
    tmp_path: Path,
) -> None:
    attached = make_task(tmp_path, {"eval_config": {"sample_shuffle": 42}})
    kwargs: dict[str, Any] = {
        "model": "mockllm/model",
        "log_dir": str(tmp_path / "set"),
        "display": "none",
        "retry_attempts": 0,
        "limit": 1,
    }
    success, first = eval_set(attached.factory, **kwargs)
    assert success and first[0].eval.config.sample_shuffle == 42
    success, again = eval_set(attached.factory, **kwargs)
    assert success
    assert local_path(again[0].location) == local_path(first[0].location)
    assert len(list_eval_logs(kwargs["log_dir"])) == 1


def test_eval_set_capture_counts_samples_with_file_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attached = make_task(tmp_path, {"eval_config": {"limit": 1, "epochs": 2}})
    capture = tmp_path / "capture.json"
    monkeypatch.setenv("INSPECT_EVAL_SET_CAPTURE", str(capture))
    with pytest.raises(SystemExit):
        eval_set(
            attached.factory,
            model="mockllm/model",
            log_dir=str(tmp_path / "set"),
            display="none",
            retry_attempts=0,
        )
    manifest = json.loads(capture.read_text())
    assert [entry["samples"] for entry in manifest["tasks"]] == [1]
    assert [entry["epochs"] for entry in manifest["tasks"]] == [2]


def test_unscoped_resolution_drops_run_wide_defaults(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Unscoped resolution must not record run-wide settings as applied.

    eval_resolve_tasks alone (the Inspect Flow path) has no run to agree
    run-wide settings for.
    """
    from inspect_ai._eval.eval import eval_resolve_tasks

    attached = make_task(
        tmp_path, {"eval_config": {"max_tasks": 7, "log_samples": False, "limit": 1}}
    )
    resolved, _ = eval_resolve_tasks(
        attached.factory,
        {},
        [get_model("mockllm/model")],
        None,
        GenerateConfig(),
        None,
        None,
        None,
    )
    assert "max_tasks" not in resolved[0].run_config
    assert "log_samples" not in resolved[0].run_config
    assert resolved[0].run_config["limit"] == 1
    assert "max_tasks" in caplog.text and attached.config.name in caplog.text
    log = eval(resolved, log_dir=str(tmp_path / "logs"), display="none")[0]
    assert log.eval.config.max_tasks is None
    assert log.eval.config.log_samples is not False
    assert log.eval.config.limit == 1
    assert log.samples is not None and len(log.samples) == 1


@pytest.mark.parametrize("disabled", [False, True])
def test_task_default_eval_set_cli(tmp_path: Path, disabled: bool) -> None:
    source = make_source(tmp_path, None if disabled else runtime_config())
    args = [
        source.spec,
        "--model",
        "mockllm/model",
        "--log-dir",
        str(tmp_path / "logs"),
        "--display",
        "none",
        "--retry-attempts",
        "0",
    ]
    if disabled:
        args.append("--no-default-config")
    result = CliRunner().invoke(eval_set_command, args)
    assert result.exit_code == 0, f"{result.output}\n{result.exception}"
    logs = list_eval_logs(str(tmp_path / "logs"))
    assert len(logs) == 1
    log = read_eval_log(logs[0])
    if disabled:
        assert_constructor_config(log)
    else:
        assert_default_config(log, source.config)


def test_old_eval_spec_without_run_config_source() -> None:
    from inspect_ai.log import EvalConfig, EvalDataset, EvalSpec

    old = {
        "created": "2026-01-01T00:00:00Z",
        "task": "old_task",
        "model": "mockllm/model",
        "dataset": EvalDataset().model_dump(),
        "config": EvalConfig().model_dump(),
    }
    spec = EvalSpec.model_validate(old)
    assert spec.run_config_source is None
    assert "run_config_source" not in spec.model_dump(exclude_none=True)
