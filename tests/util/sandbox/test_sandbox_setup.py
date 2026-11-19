import asyncio
import os
import sys
from contextvars import ContextVar, copy_context
from pathlib import Path
from typing import Any, ClassVar, Literal, NamedTuple, overload

import anyio
import pytest
from pydantic import BaseModel
from test_helpers.utils import skip_if_no_docker, skip_if_trio

from inspect_ai import SampleSource, Task, enqueue_sample, eval, eval_async
from inspect_ai._eval.loader import resolve_task_sandbox
from inspect_ai._eval.run import SandboxManager
from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
from inspect_ai._eval.task.sandbox import TaskSandboxEnvironment
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalConfig, EvalSample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, includes
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver
from inspect_ai.util import (
    ComposeBuild,
    ComposeConfig,
    ComposeService,
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    is_dockerfile,
    sandbox,
    sandboxenv,
    subprocess,
)
from inspect_ai.util._sandbox.context import init_sandbox_environments_sample
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import sandbox_prebuilt
from inspect_ai.util._sandbox.paths import resolve_config_paths
from inspect_ai.util._sandbox.setup import current_task_init_env

SANDBOX_SETUP_FILE = (Path(__file__).parent / "sandbox_setup.sh").as_posix()
SANDBOX_SETUP_ERROR_FILE = (Path(__file__).parent / "sandbox_setup_error.sh").as_posix()
SANDBOX_SETUP_SYMLINK_FILE = (
    Path(__file__).parent / "sandbox_setup_symlink.sh"
).as_posix()

with open(SANDBOX_SETUP_FILE, "r") as f:
    sandbox_setup = f.read()

SUCCESS = "FOUND"
NOT_FOUND = "MISSING"


@solver
def check_file(expected_content: str | None = None) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        """
        Check if a file exists, and if it contains the expected_content.

        Returns SUCCESS if the file exists with expected content. Otherwise
        returns NOT_FOUND if file is missing or the mismatched set of strings
        if expected_content doesn't match actual content.
        """
        try:
            value = await sandbox().read_file(state.metadata["file"])
            # Strip before comparing values to avoid trailing newline mismatches
            if not expected_content or expected_content.strip() == value.strip():
                completion = SUCCESS
            else:
                # Unexpected contents,
                completion = f"{repr(value)} != {repr(expected_content)}"
        except FileNotFoundError:
            completion = NOT_FOUND

        state.output = ModelOutput.from_content("mockllm/model", completion)

        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_setup():
    def sample(file: str, target: str, setup: str) -> Sample:
        return Sample(
            input=f"Does the file '{file}' exist? Answer {SUCCESS} or {NOT_FOUND}",
            target=target,
            metadata={"file": file},
            setup=setup,
        )

    dataset = [
        sample("foo.txt", SUCCESS, sandbox_setup),
        sample("bar.txt", NOT_FOUND, sandbox_setup),
        sample("foo.txt", SUCCESS, SANDBOX_SETUP_FILE),
        sample("bar.txt", NOT_FOUND, SANDBOX_SETUP_FILE),
    ]

    task = Task(
        dataset=dataset,
        solver=check_file(),
        scorer=includes(),
        sandbox="docker",
    )

    log = eval(task, model="mockllm/model")[0]

    assert log.samples
    for sample in log.samples:
        assert sample.scores["includes"].value == CORRECT


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_setup_symlink():
    def sample(file: str, target: str, setup: str) -> Sample:
        return Sample(
            input=f"Does the file '{file}' exist? Answer {SUCCESS} or {NOT_FOUND}",
            target=target,
            metadata={"file": file},
            setup=setup,
        )

    dataset = [
        sample("link_simple", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("link_dot_slash", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/link_up_one", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/inner/link_up_two", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("link_absolute", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("missing_simple", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("missing_dot_slash", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/missing_up_one", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/inner/missing_up_two", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("missing_absolute", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
    ]

    task = Task(
        dataset=dataset,
        solver=check_file(expected_content="hello world"),
        scorer=includes(),
        sandbox="docker",
    )

    log = eval(task, model="mockllm/model")[0]

    assert log.samples
    for sample in log.samples:
        assert sample.scores["includes"].value == CORRECT, (
            f"Failure for '{sample.metadata['file']}': {sample.scores['includes'].answer}'"
        )


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_setup_fail_on_error():
    task = Task(
        dataset=[
            Sample(input="Say hello.", setup=SANDBOX_SETUP_ERROR_FILE),
            Sample(input="Say hello.", setup=SANDBOX_SETUP_FILE),
        ],
        sandbox="docker",
    )

    # fail_on_error=True (entire eval fails)
    log = eval(task, model="mockllm/model", fail_on_error=True)[0]
    assert log.status == "error"

    # fail_on_error=False (sample fails not entire eval)
    log = eval(task, model="mockllm/model", fail_on_error=False)[0]
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].error
    assert not log.samples[1].error

    # fail_on_error=True, continue_on_fail=True (entire eval fails, but all samples are evaluated)
    log = eval(task, model="mockllm/model", fail_on_error=True, continue_on_fail=True)[
        0
    ]
    assert log.status == "error"
    assert log.samples
    assert log.samples[0].error
    assert not log.samples[1].error


class HangingSetupSandbox(SandboxEnvironment):
    """Sandbox whose ``exec`` blocks until the sample is cancelled.

    ``sample_init`` records the environment it creates in ``created``; ``exec``
    sets ``started`` and then waits forever, so a test can cancel from inside the
    setup-script phase; ``sample_cleanup`` crosses a cancellation checkpoint, as
    a real provider's cleanup does, and then records its ``environments`` and
    ``interrupted`` arguments in ``cleanups``. A test calls ``reset()`` first
    (inside the event loop, as it creates an ``anyio.Event``).
    """

    started: ClassVar[anyio.Event]
    created: ClassVar[list[SandboxEnvironment]]
    cleanups: ClassVar[list[tuple[dict[str, SandboxEnvironment], bool]]]

    @classmethod
    def reset(cls) -> None:
        cls.started = anyio.Event()
        cls.created = []
        cls.cleanups = []

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        environment = cls()
        cls.created.append(environment)
        return {"default": environment}

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        await anyio.lowlevel.checkpoint()
        cls.cleanups.append((environments, interrupted))

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.started.set()
        await anyio.sleep_forever()
        raise AssertionError("sleep_forever() returned")

    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        pass

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, *, user: str | None = None
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], *, user: str | None = None
    ) -> bytes: ...

    async def read_file(
        self, file: str, text: bool = True, *, user: str | None = None
    ) -> str | bytes:
        raise NotImplementedError


class HangingCopySandbox(HangingSetupSandbox):
    """Variant whose ``write_file`` blocks, to cancel from inside the file-copy phase."""

    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        self.started.set()
        await anyio.sleep_forever()


@pytest.mark.parametrize(
    ("sandbox_type", "files"),
    [
        pytest.param(HangingSetupSandbox, {}, id="setup-script"),
        pytest.param(HangingCopySandbox, {"file.txt": b"contents"}, id="file-copy"),
    ],
)
async def test_sandbox_setup_cancelled_cleans_up_sample(
    sandbox_type: type[HangingSetupSandbox], files: dict[str, bytes]
) -> None:
    """Cancelling a sample during file copy or its setup script still tears its sandbox down.

    Cancellation is not an ``Exception``, so it must get its own cleanup path in
    ``init_sandbox_environments_sample``: the caller only cleans up environments
    it was handed, and init never returns them when it is cancelled. That
    cleanup must also be shielded, or the cancellation that triggered it would
    interrupt it at its first checkpoint.
    """
    sandbox_type.reset()

    async def cancel_once_setup_started(scope: anyio.CancelScope) -> None:
        await sandbox_type.started.wait()
        scope.cancel()

    async with anyio.create_task_group() as tg:
        tg.start_soon(cancel_once_setup_started, tg.cancel_scope)
        with pytest.raises(anyio.get_cancelled_exc_class()):
            await init_sandbox_environments_sample(
                sandboxenv_type=sandbox_type,
                task_name="task",
                config=None,
                files=files,
                setup=b"#!/usr/bin/env bash\n\ntrue\n",
                metadata={},
            )

    assert len(sandbox_type.created) == 1
    assert sandbox_type.cleanups == [({"default": sandbox_type.created[0]}, True)]


def test_is_dockerfile():
    assert is_dockerfile("/path/to/Dockerfile")
    assert is_dockerfile("/path/to/name.Dockerfile")
    assert is_dockerfile("/path/to/Dockerfile.name")
    assert not is_dockerfile("/path/to/Dockerfile-name")
    assert not is_dockerfile("/path/to/Dockerfile_name")
    assert not is_dockerfile("/path/to/name-Dockerfile")
    assert not is_dockerfile("/path/to/name_Dockerfile")
    assert not is_dockerfile("/path/to/docker-compose.yaml")
    assert not is_dockerfile("/path/to/not_a_dockerfile.txt")


# --- setup runs in the launch directory, with the process's own environment ---

PROBE_VAR = "INSPECT_TEST_SETUP_PROBE"


class ProbeCall(NamedTuple):
    hook: str
    config: SandboxEnvironmentConfigType | None
    cwd: str
    environ_value: str | None
    init_env: dict[str, str]
    subprocess_cwd: str | None


class ProbeState:
    """What the probe providers saw, shared by both probe classes."""

    calls: ClassVar[list[ProbeCall]] = []
    task_init_environment_result: ClassVar[dict[str, str]] = {}
    block_config: ClassVar[str | None] = None
    task_init_started: ClassVar[anyio.Event]
    task_init_release: ClassVar[anyio.Event]

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.task_init_environment_result = {}
        cls.block_config = None
        cls.task_init_started = anyio.Event()
        cls.task_init_release = anyio.Event()

    @classmethod
    def hooks(cls, hook: str) -> list[ProbeCall]:
        return [call for call in cls.calls if call.hook == hook]


async def _probe(
    hook: str, config: SandboxEnvironmentConfigType | None, *, run: bool = False
) -> None:
    subprocess_cwd: str | None = None
    if run:
        result = await subprocess(
            [sys.executable, "-c", "import os; print(os.getcwd())"]
        )
        assert result.success, result.stderr
        subprocess_cwd = result.stdout.strip()
    ProbeState.calls.append(
        ProbeCall(
            hook=hook,
            config=config,
            cwd=os.getcwd(),
            environ_value=os.environ.get(PROBE_VAR),
            init_env=current_task_init_env(),
            subprocess_cwd=subprocess_cwd,
        )
    )


async def _probe_task_init(config: SandboxEnvironmentConfigType | None) -> None:
    await _probe("task_init", config, run=True)
    if config is not None and config == ProbeState.block_config:
        ProbeState.task_init_started.set()
        await ProbeState.task_init_release.wait()
        await _probe("task_init_resumed", config)


class ProbeEnvironment(HangingSetupSandbox):
    """A sample environment whose commands succeed at once."""

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        return ExecResult(success=True, returncode=0, stdout="", stderr="")


@sandboxenv(name="setup_probe")
class SetupProbeSandbox(ProbeEnvironment):
    """Records the directory, environment and config each lifecycle hook sees."""

    @classmethod
    def config_files(cls) -> list[str]:
        return ["compose.yaml"]

    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        await _probe("task_init_environment", config)
        return dict(ProbeState.task_init_environment_result)

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        await _probe_task_init(config)

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        await _probe("sample_init", config)
        return {"default": ProbeEnvironment()}

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        await _probe("task_cleanup", config, run=True)


@sandboxenv(name="setup_probe_docker")
class DockerSetupProbeSandbox(DockerSandboxEnvironment):
    """A Docker subclass, so the variables its task_init_environment returns are allowed."""

    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        return await SetupProbeSandbox.task_init_environment(config, metadata)

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        await _probe_task_init(config)

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        return await SetupProbeSandbox.sample_init(task_name, config, metadata)

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        await _probe("task_cleanup", config)


class Dirs(NamedTuple):
    launch: Path
    task: Path


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dirs:
    """A launch directory (the working directory) and a separate task directory."""
    launch = (tmp_path / "launch").resolve()
    task_dir = (tmp_path / "task").resolve()
    launch.mkdir()
    task_dir.mkdir()
    monkeypatch.chdir(launch)
    monkeypatch.delenv(PROBE_VAR, raising=False)
    ProbeState.reset()
    return Dirs(launch=launch, task=task_dir)


def _task_in(directory: Path, **kwargs: Any) -> Task:
    task = Task(name="probe_task", **kwargs)
    setattr(task, TASK_RUN_DIR_ATTR, directory.as_posix())
    return task


def _same_dir(path: str | None, directory: Path) -> bool:
    return path is not None and Path(path).resolve() == directory.resolve()


async def test_setup_runs_in_the_launch_directory(dirs: Dirs) -> None:
    """task_init_environment, task_init and task_cleanup run where the eval was launched."""
    task = _task_in(
        dirs.task, dataset=[Sample(input="x")], sandbox=("setup_probe", "inline")
    )

    with anyio.fail_after(60):
        [log] = await eval_async(task, model="mockllm/model")

    assert log.status == "success", log.error
    hooks = ["task_init_environment", "task_init", "sample_init", "task_cleanup"]
    for hook in hooks:
        [call] = ProbeState.hooks(hook)
        assert _same_dir(call.cwd, dirs.launch), (hook, call.cwd)
    for hook in ["task_init", "task_cleanup"]:
        [call] = ProbeState.hooks(hook)
        assert _same_dir(call.subprocess_cwd, dirs.launch), (hook, call)
    assert _same_dir(os.getcwd(), dirs.launch)


async def test_running_sample_keeps_directory_and_environment_during_setup(
    dirs: Dirs,
) -> None:
    """A sample running while another configuration's task_init awaits sees no change.

    The added sample's configuration is set up while the seed sample runs.
    Its task_init_environment variables reach task_init through the setup
    state, not through os.environ.
    """
    ProbeState.task_init_environment_result = {PROBE_VAR: "from-setup"}
    ProbeState.block_config = "added"
    observed: dict[str, str | None] = {}

    @solver
    def add_and_observe() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == "seed":
                enqueue_sample(
                    [
                        Sample(
                            id="added",
                            input="added",
                            sandbox=SandboxEnvironmentSpec(
                                "setup_probe_docker", "added"
                            ),
                        )
                    ]
                )
                with anyio.fail_after(30):
                    await ProbeState.task_init_started.wait()
                observed["cwd"] = os.getcwd()
                observed["environ"] = os.environ.get(PROBE_VAR)
                ProbeState.task_init_release.set()
            return state

        return solve

    task = _task_in(
        dirs.task,
        dataset=SampleSource.from_samples([Sample(id="seed", input="seed")]),
        solver=add_and_observe(),
    )

    with anyio.fail_after(60):
        [log] = await eval_async(task, model="mockllm/model")

    assert log.status == "success", log.error
    assert _same_dir(observed["cwd"], dirs.launch)
    assert observed["environ"] is None
    for hook in ["task_init", "task_init_resumed"]:
        [call] = ProbeState.hooks(hook)
        assert _same_dir(call.cwd, dirs.launch), hook
        assert call.environ_value is None
        assert call.init_env == {PROBE_VAR: "from-setup"}
    assert PROBE_VAR not in os.environ


async def test_non_docker_task_init_environment_is_refused(dirs: Dirs) -> None:
    """A provider outside Docker's class family cannot return task_init variables."""
    ProbeState.task_init_environment_result = {PROBE_VAR: "1"}
    task = _task_in(
        dirs.task, dataset=[Sample(input="x")], sandbox=("setup_probe", "inline")
    )

    with anyio.fail_after(60):
        with pytest.raises(PrerequisiteError, match="task_init_environment"):
            await eval_async(task, model="mockllm/model")

    assert ProbeState.hooks("task_init") == []
    assert PROBE_VAR not in os.environ


async def test_empty_task_init_environment_sets_up(dirs: Dirs) -> None:
    """The default (no variables) is unaffected by the refusal."""
    task = _task_in(
        dirs.task, dataset=[Sample(input="x")], sandbox=("setup_probe", "inline")
    )

    with anyio.fail_after(60):
        [log] = await eval_async(task, model="mockllm/model")

    assert log.status == "success", log.error
    [call] = ProbeState.hooks("task_init")
    assert call.init_env == {}


async def test_task_inline_json_config_reaches_task_init_unchanged(
    dirs: Dirs,
) -> None:
    config = '{"image": "python:3.12"}'
    task = _task_in(
        dirs.task, dataset=[Sample(input="x")], sandbox=("setup_probe", config)
    )

    with anyio.fail_after(60):
        [log] = await eval_async(task, model="mockllm/model")

    assert log.status == "success", log.error
    assert [c.config for c in ProbeState.hooks("task_init")] == [config]
    assert [c.config for c in ProbeState.hooks("sample_init")] == [config]


async def test_task_config_only_in_launch_directory_resolves_there(
    dirs: Dirs,
) -> None:
    """A task's relative config missing under the task directory is left relative."""
    (dirs.launch / "compose.yaml").write_text("launch")
    task = _task_in(
        dirs.task,
        dataset=[Sample(input="x")],
        sandbox=("setup_probe", "compose.yaml"),
    )

    with anyio.fail_after(60):
        [log] = await eval_async(task, model="mockllm/model")

    assert log.status == "success", log.error
    [call] = ProbeState.hooks("task_init")
    assert call.config == "compose.yaml"
    assert (Path(call.cwd) / "compose.yaml").read_text() == "launch"


@pytest.mark.parametrize("route", ["seed", "added"])
async def test_sample_configs_resolve_against_the_task_directory(
    dirs: Dirs, route: str
) -> None:
    """Relative sample configs reach task_init and sample_init as task-directory paths.

    Each directory holds a different `Dockerfile` and `compose.yaml`. A
    `ComposeConfig` build context (`"."`, or omitted) becomes the task
    directory; a relative compose file becomes the task directory's file,
    whose contents are unchanged. Covered for a seed sample and for samples
    a `SampleSource` adds while the task runs.
    """
    for directory in dirs:
        (directory / "Dockerfile").write_text(f"FROM {directory.name}\n")
        (directory / "compose.yaml").write_text(f"name: {directory.name}\n")

    def compose(build: str | ComposeBuild) -> ComposeConfig:
        return ComposeConfig(services={"default": ComposeService(build=build)})

    configs: list[SandboxEnvironmentConfigType] = [
        compose("."),
        compose(ComposeBuild()),
        compose(ComposeBuild(dockerfile="Dockerfile")),
        "compose.yaml",
    ]
    samples = [
        Sample(
            id=f"s{i}",
            input="x",
            sandbox=SandboxEnvironmentSpec("setup_probe", config),
        )
        for i, config in enumerate(configs)
    ]

    dataset: Any
    if route == "seed":
        dataset = samples
    else:

        async def add_all(sample: EvalSample) -> list[Sample] | None:
            return samples if sample.id == "seed" else None

        dataset = SampleSource.from_samples(
            [Sample(id="seed", input="seed")], sample_complete=add_all
        )

    task = _task_in(dirs.task, dataset=dataset)
    with anyio.fail_after(60):
        [log] = await eval_async(task, model="mockllm/model")
    assert log.status == "success", log.error

    task_dir = dirs.task.as_posix()
    expected: list[SandboxEnvironmentConfigType] = [
        compose(task_dir),
        compose(ComposeBuild(context=task_dir)),
        compose(ComposeBuild(context=task_dir, dockerfile="Dockerfile")),
        (dirs.task / "compose.yaml").as_posix(),
    ]
    for hook in ["task_init", "sample_init"]:
        received = [c.config for c in ProbeState.hooks(hook)]
        assert sorted(map(repr, received)) == sorted(map(repr, expected)), hook
    assert (dirs.task / "compose.yaml").read_text() == "name: task\n"


# --- resolve_config_paths ------------------------------------------------------


def test_resolve_config_paths_strings(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "Dockerfile").write_text("")
    task_dir = tmp_path.as_posix()

    assert resolve_config_paths("compose.yaml", task_dir) == f"{task_dir}/compose.yaml"
    assert (
        resolve_config_paths("sub/Dockerfile", task_dir) == f"{task_dir}/sub/Dockerfile"
    )
    assert (
        resolve_config_paths("./sub/../compose.yaml", task_dir)
        == f"{task_dir}/sub/../compose.yaml"
    )
    for unchanged in [
        "missing.yaml",
        '{"image": "python:3.12"}',
        "s3://bucket/compose.yaml",
        "https://example.com/compose.yaml",
        "/absolute/compose.yaml",
        "x" * 5000,
        None,
    ]:
        assert resolve_config_paths(unchanged, task_dir) == unchanged


def test_resolve_config_paths_follows_directory_symlinks_before_dot_dot(
    tmp_path: Path,
) -> None:
    task_dir, real_dir = tmp_path / "task", tmp_path / "real"
    task_dir.mkdir()
    (real_dir / "child").mkdir(parents=True)
    (task_dir / "link").symlink_to(real_dir / "child", target_is_directory=True)
    (real_dir / "compose.yaml").write_text("intended configuration")
    (task_dir / "compose.yaml").write_text("wrong configuration")
    (real_dir / "ctx").mkdir()
    (real_dir / "ctx" / "Dockerfile").write_text("intended context")

    task = Task(dataset=None, sandbox=("docker", "link/../compose.yaml"))
    setattr(task, TASK_RUN_DIR_ATTR, str(task_dir))
    resolved = resolve_task_sandbox(task, None)
    assert resolved is not None and isinstance(resolved.config, str)
    assert Path(resolved.config).read_text() == "intended configuration"

    compose = resolve_config_paths(
        ComposeConfig(
            services={
                "default": ComposeService(build=ComposeBuild(context="link/../ctx"))
            }
        ),
        task_dir.as_posix(),
    )
    assert isinstance(compose, ComposeConfig)
    build = compose.services["default"].build
    assert isinstance(build, ComposeBuild) and build.context is not None
    assert (Path(build.context) / "Dockerfile").read_text() == "intended context"


def test_resolve_config_paths_does_not_depend_on_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "compose.yaml").write_text("")
    launch = tmp_path / "launch"
    launch.mkdir()
    (launch / "other.yaml").write_text("")
    monkeypatch.chdir(launch)

    assert resolve_config_paths("compose.yaml", task_dir.as_posix()) == (
        f"{task_dir.as_posix()}/compose.yaml"
    )
    assert resolve_config_paths("other.yaml", task_dir.as_posix()) == "other.yaml"


def test_resolve_config_paths_compose_build_contexts(tmp_path: Path) -> None:
    (tmp_path / "ctx").mkdir()
    task_dir = tmp_path.as_posix()
    config = ComposeConfig(
        services={
            "dot": ComposeService(build="."),
            "string": ComposeService(build="ctx"),
            "missing": ComposeService(build="missing"),
            "url": ComposeService(build="https://github.com/org/repo.git"),
            "context": ComposeService(build=ComposeBuild(context="ctx")),
            "omitted": ComposeService(build=ComposeBuild()),
            "dockerfile": ComposeService(
                build=ComposeBuild(dockerfile="Dockerfile.dev")
            ),
            "absolute": ComposeService(build=ComposeBuild(context="/abs/ctx")),
            "image": ComposeService(image="python:3.12"),
        }
    )
    before = config.model_dump()

    resolved = resolve_config_paths(config, task_dir)

    assert isinstance(resolved, ComposeConfig)
    services = resolved.services
    assert services["dot"].build == task_dir
    assert services["string"].build == f"{task_dir}/ctx"
    assert services["missing"].build == "missing"
    assert services["url"].build == "https://github.com/org/repo.git"
    assert services["context"].build == ComposeBuild(context=f"{task_dir}/ctx")
    assert services["omitted"].build == ComposeBuild(context=task_dir)
    assert services["dockerfile"].build == ComposeBuild(
        context=task_dir, dockerfile="Dockerfile.dev"
    )
    assert services["absolute"].build == ComposeBuild(context="/abs/ctx")
    assert services["image"] == config.services["image"]
    # the caller's config is not modified
    assert config.model_dump() == before


def test_resolve_config_paths_leaves_other_configs(tmp_path: Path) -> None:
    images_only = ComposeConfig(
        services={"default": ComposeService(image="python:3.12")}
    )
    assert resolve_config_paths(images_only, tmp_path.as_posix()) is images_only
    missing_dir = (tmp_path / "missing").as_posix()
    omitted = ComposeConfig(services={"default": ComposeService(build=ComposeBuild())})
    assert resolve_config_paths(omitted, missing_dir) is omitted

    class Custom(BaseModel):
        path: str = "compose.yaml"

    custom = Custom()
    (tmp_path / "compose.yaml").write_text("")
    assert resolve_config_paths(custom, tmp_path.as_posix()) is custom


# frozen so specs embedding it stay hashable (sandbox startup sets them)
class _BindingsConfig(BaseModel, frozen=True):
    name: str
    fail: bool = False


class _SharedManager:
    """A k8s-style object that task_init gets or creates."""


# E2B-style state: each task_init rebinds a fresh list and run id
_running: ContextVar[list[str]] = ContextVar("_running")
_run_id: ContextVar[str] = ContextVar("_run_id")
# k8s-style state: the first task_init creates it, later ones reuse it
_manager: ContextVar[_SharedManager] = ContextVar("_manager")

_bindings_calls: list[dict[str, Any]] = []

# events a test coordinates the provider with, created inside the event loop
_bindings_events: dict[str, anyio.Event] = {}


def _bindings_event(name: str) -> anyio.Event:
    if name not in _bindings_events:
        _bindings_events[name] = anyio.Event()
    return _bindings_events[name]


def _record_call(call: str, config: SandboxEnvironmentConfigType | None) -> None:
    assert isinstance(config, _BindingsConfig)
    running = _running.get(None)
    _bindings_calls.append(
        {
            "call": call,
            "config": config.name,
            "run_id": _run_id.get(None),
            "running": running,
            "running_items": list(running) if running is not None else None,
            "manager": _manager.get(None),
            "prebuilt": sandbox_prebuilt(),
        }
    )


def _calls(call: str, config: str | None = None) -> list[dict[str, Any]]:
    return [
        c
        for c in _bindings_calls
        if c["call"] == call and (config is None or c["config"] == config)
    ]


@sandboxenv(name="setup_bindings")
class _BindingsSandbox(SandboxEnvironment):
    """Provider that keeps its state in `ContextVar`s bound by `task_init`."""

    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return _BindingsConfig(**config)

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        _record_call("task_init", config)
        assert isinstance(config, _BindingsConfig)
        if _manager.get(None) is None:
            _manager.set(_SharedManager())
        _running.set([])
        _run_id.set(config.name)
        if config.fail:
            raise RuntimeError(f"task_init failed for {config.name}")
        if config.name in _bindings_events:
            # a test waiting for this setup to return
            _bindings_events[config.name].set()
        if config.name == "CancelledInside":
            # a cancellation raised inside task_init, not by cancelling its caller
            future = asyncio.get_running_loop().create_future()
            future.cancel()
            await future
        if config.name == "Blocked":
            _bindings_event("blocked_init_entered").set()
            with anyio.fail_after(10):
                await _bindings_event("sample_started").wait()

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        _record_call("sample_init", config)
        assert isinstance(config, _BindingsConfig)
        if metadata.get("__sample_id__") == "sample_started":
            _bindings_event("sample_started").set()
        # raises LookupError when task_init's binding is not visible, as E2B does
        _running.get().append(config.name)
        return {"default": _BindingsSandbox()}

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        _record_call("sample_cleanup", config)

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        _record_call("task_cleanup", config)

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        raise NotImplementedError

    async def write_file(
        self, file: str, contents: str | bytes, *, user: str | None = None
    ) -> None:
        raise NotImplementedError

    @overload
    async def read_file(
        self, file: str, text: Literal[True] = True, *, user: str | None = None
    ) -> str: ...

    @overload
    async def read_file(
        self, file: str, text: Literal[False], *, user: str | None = None
    ) -> bytes: ...

    async def read_file(
        self, file: str, text: bool = True, *, user: str | None = None
    ) -> str | bytes:
        raise NotImplementedError


def _bindings_spec(name: str, fail: bool = False) -> SandboxEnvironmentSpec:
    return SandboxEnvironmentSpec(
        "setup_bindings", _BindingsConfig(name=name, fail=fail)
    )


def test_setup_bindings_per_configuration() -> None:
    """Each configuration's samples and task_cleanup see its own task_init's bindings."""
    _bindings_calls.clear()
    log = eval(
        Task(
            dataset=[
                Sample(id=1, input="a", sandbox=_bindings_spec("A")),
                Sample(id=2, input="b", sandbox=_bindings_spec("B")),
            ],
            solver=[generate()],
        ),
        model="mockllm/model",
        display="none",
    )[0]
    assert log.status == "success", log.error

    for name in ["A", "B"]:
        for call in ["sample_init", "sample_cleanup", "task_cleanup"]:
            [record] = _calls(call, name)
            assert record["run_id"] == name, (call, record)
        # the list the samples appended to is the one task_cleanup sees
        [sample_init] = _calls("sample_init", name)
        [task_cleanup] = _calls("task_cleanup", name)
        assert sample_init["running"] is task_cleanup["running"]
        assert task_cleanup["running_items"] == [name]

    # a get-or-create object made by the first task_init reaches every
    # configuration's samples and cleanup
    first_init, second_init = _calls("task_init")
    assert first_init["manager"] is None
    shared = second_init["manager"]
    assert isinstance(shared, _SharedManager)
    assert {
        id(c["manager"])
        for c in _bindings_calls
        if c["call"] in ["sample_init", "sample_cleanup", "task_cleanup"]
    } == {id(shared)}


def test_setup_bindings_empty_sample_source_seed() -> None:
    """Samples of a SampleSource with no seed see the bindings of task_init run by its feeder."""
    _bindings_calls.clear()

    class _Source(SampleSource):
        def __init__(self) -> None:
            self._produced = False

        async def next_samples(self) -> list[Sample] | None:
            if not self._produced:
                self._produced = True
                return [Sample(input="added")]
            return None

    log = eval(
        Task(dataset=_Source(), solver=[generate()], sandbox=_bindings_spec("E")),
        model="mockllm/model",
        display="none",
        sandbox_prebuilt=True,
    )[0]
    assert log.status == "success", log.error
    assert log.samples and not log.samples[0].error, log.samples
    [task_init] = _calls("task_init", "E")
    [sample_init] = _calls("sample_init", "E")
    assert sample_init["run_id"] == "E"
    # the run's --sandbox-prebuilt flag reaches the feeder's setup and the sample
    assert task_init["prebuilt"] and sample_init["prebuilt"]
    [task_cleanup] = _calls("task_cleanup", "E")
    assert task_cleanup["running_items"] == ["E"]


async def test_setup_bindings_failed_task_init(tmp_path: Path) -> None:
    """A failed task_init's bindings reach no later setup, and it gets no task_cleanup."""
    _bindings_calls.clear()
    failed = TaskSandboxEnvironment(_bindings_spec("F", fail=True), str(tmp_path), ())
    ok = TaskSandboxEnvironment(_bindings_spec("A"), str(tmp_path), ())

    manager = SandboxManager(EvalConfig(), cleanup=True, launch_dir=str(tmp_path))
    manager.open()
    try:
        with pytest.raises(RuntimeError, match="task_init failed for F"):
            await manager._start_sandboxenvs({failed})
        await manager._start_sandboxenvs({ok})
    finally:
        await manager.shutdown()

    [init_a] = _calls("task_init", "A")
    assert init_a["run_id"] is None
    assert init_a["manager"] is None
    assert [c["config"] for c in _calls("task_cleanup")] == ["A"]
    # setup binds nothing in the caller's context
    assert _run_id.get(None) is None


@skip_if_trio
async def test_setup_bindings_cancellation_inside_task_init_raises(
    tmp_path: Path,
) -> None:
    """A cancellation raised inside task_init propagates and registers nothing."""
    _bindings_calls.clear()
    _bindings_events.clear()
    spec = _bindings_spec("CancelledInside")
    manager = SandboxManager(EvalConfig(), cleanup=True, launch_dir=str(tmp_path))
    manager.open()
    try:
        with pytest.raises(asyncio.CancelledError):
            await manager._start_sandboxenvs(
                {TaskSandboxEnvironment(spec, str(tmp_path), ())}
            )
    finally:
        await manager.shutdown()

    assert _calls("task_cleanup") == []
    assert copy_context().run(_apply_and_get_run_id, manager, spec, tmp_path) is None


def _apply_and_get_run_id(
    manager: SandboxManager, spec: SandboxEnvironmentSpec, task_dir: Path
) -> str | None:
    manager.bindings.apply(spec, str(task_dir))
    return _run_id.get(None)


async def test_setup_bindings_cancel_after_task_init_keeps_cleanup(
    tmp_path: Path,
) -> None:
    """A cancellation that arrives as task_init returns still registers its task_cleanup."""
    _bindings_calls.clear()
    _bindings_events.clear()
    returned = _bindings_event("C")
    manager = SandboxManager(EvalConfig(), cleanup=True, launch_dir=str(tmp_path))
    manager.open()
    try:
        async with anyio.create_task_group() as tg:

            async def cancel_when_task_init_returns() -> None:
                await returned.wait()
                tg.cancel_scope.cancel()

            tg.start_soon(cancel_when_task_init_returns)
            await manager._start_sandboxenvs(
                {TaskSandboxEnvironment(_bindings_spec("C"), str(tmp_path), ())}
            )
    finally:
        await manager.shutdown()

    assert returned.is_set()
    [task_cleanup] = _calls("task_cleanup")
    assert task_cleanup["config"] == "C"
    assert task_cleanup["run_id"] == "C"


def test_setup_bindings_sample_starts_during_other_task_setup(tmp_path: Path) -> None:
    """A sample of a task not loaded from a file finds its bindings while another setup is in its task directory."""
    _bindings_calls.clear()
    _bindings_events.clear()
    other_dir = tmp_path / "other"
    other_dir.mkdir()

    class _Later(SampleSource):
        """Adds a sample once the other task's setup has changed directory."""

        def __init__(self) -> None:
            self._produced = False

        def initial_samples(self) -> list[Sample]:
            return [Sample(id=1, input="seed")]

        async def next_samples(self) -> list[Sample] | None:
            if self._produced:
                return None
            self._produced = True
            with anyio.fail_after(10):
                await _bindings_event("blocked_init_entered").wait()
            return [Sample(id="sample_started", input="later")]

    class _Blocked(SampleSource):
        """Adds a sample whose configuration's setup blocks in its directory."""

        def __init__(self) -> None:
            self._produced = False

        async def next_samples(self) -> list[Sample] | None:
            if self._produced:
                return None
            self._produced = True
            return [Sample(input="blocked")]

    later = Task(
        name="later", dataset=_Later(), solver=[generate()], sandbox=_bindings_spec("A")
    )
    blocked = Task(
        name="blocked",
        dataset=_Blocked(),
        solver=[generate()],
        sandbox=_bindings_spec("Blocked"),
    )
    setattr(blocked, TASK_RUN_DIR_ATTR, other_dir.as_posix())

    logs = eval([later, blocked], model="mockllm/model", display="none", max_tasks=2)
    assert [log.status for log in logs] == ["success", "success"], [
        log.error for log in logs
    ]
    later_init = [c for c in _calls("sample_init", "A")]
    assert len(later_init) == 2
    assert all(c["run_id"] == "A" for c in later_init), later_init


async def test_setup_bindings_sample_keeps_own_binding(tmp_path: Path) -> None:
    """Applying a configuration's bindings keeps a value the sample bound itself."""
    _bindings_calls.clear()
    spec = _bindings_spec("A")
    manager = SandboxManager(EvalConfig(), cleanup=True, launch_dir=str(tmp_path))
    manager.open()
    try:
        await manager._start_sandboxenvs(
            {TaskSandboxEnvironment(spec, str(tmp_path), ())}
        )

        def sample() -> tuple[str | None, list[str] | None]:
            _run_id.set("own")
            manager.bindings.apply(spec, str(tmp_path))
            return _run_id.get(None), _running.get(None)

        def other_task_dir() -> str | None:
            manager.bindings.apply(spec, str(tmp_path / "other"))
            return _run_id.get(None)

        run_id, running = copy_context().run(sample)
        assert run_id == "own"
        assert running == []
        assert copy_context().run(other_task_dir) is None
    finally:
        await manager.shutdown()


if __name__ == "__main__":
    test_docker_sandbox_setup()
