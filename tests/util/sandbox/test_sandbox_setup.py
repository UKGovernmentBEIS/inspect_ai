import os
import sys
from pathlib import Path
from typing import Any, ClassVar, Literal, NamedTuple, overload

import anyio
import pytest
from pydantic import BaseModel
from test_helpers.utils import skip_if_no_docker

from inspect_ai import SampleSource, Task, enqueue_sample, eval, eval_async
from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalSample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, includes
from inspect_ai.solver import Generate, Solver, TaskState, solver
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
        == f"{task_dir}/compose.yaml"
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


if __name__ == "__main__":
    test_docker_sandbox_setup()
