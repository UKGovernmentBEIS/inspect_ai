"""Docker sandbox lifecycle: who owns the cleanup registry, and when it clears.

A static dataset runs `task_init` in the run's own context before any sample
starts, so the samples and the final `task_cleanup` inherit whatever it set.
Samples a `SampleSource` adds are different: their `task_init` runs in the
feeder task, a sibling of the samples, so state it *binds* there is invisible
to them. The registry therefore lives on the `SandboxManager`'s lifecycle
scope, opened before any task of the batch starts, and every provider hook
mutates that shared object.

The Docker daemon is stubbed at the compose-command layer; compose files are
generated and removed for real (in an isolated auto-compose directory).
"""

import os
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from test_helpers.utils import skip_if_no_docker

from inspect_ai import (
    SampleSource,
    Task,
    TaskSource,
    enqueue_sample,
    eval,
    eval_async,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver
from inspect_ai.util import (
    ComposeConfig,
    ComposeService,
    ExecResult,
    SandboxEnvironmentSpec,
)
from inspect_ai.util._display import init_display_type
from inspect_ai.util._sandbox.docker import cleanup as cleanup_module
from inspect_ai.util._sandbox.docker import config as config_module
from inspect_ai.util._sandbox.docker import docker as docker_module
from inspect_ai.util._sandbox.docker.cleanup import cleanup_state
from inspect_ai.util._sandbox.docker.config import auto_compose_dir
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._sandbox.environment import SandboxEnvironmentConfigType
from inspect_ai.util._sandbox.lifecycle import (
    sandbox_lifecycle_scope,
    sandbox_lifecycle_state,
)

GENERIC_IMAGE = "aisiuk/inspect-tool-support"


class FakeDocker:
    """The provider's Docker daemon, stubbed at the compose-command layer.

    Compose files are still generated and removed by the real code; the
    containers behind them are a set of project names. `events` records each
    `up` / `down` as ``"<op>:<sample_id>"`` (the startup project has no
    sample, so only per-sample projects appear there).
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.events: list[str] = []
        self.running: set[str] = set()
        self.reported: list[str] = []
        self.fail_build_contexts: set[str] = set()
        self.on_build_failure: list[Any] = []
        self.on_build: list[Any] = []
        data_dir = tmp_path.resolve() / "inspect-data"

        def fake_data_dir(subdir: str | None) -> Path:
            path = data_dir / subdir if subdir else data_dir
            path.mkdir(parents=True, exist_ok=True)
            return path

        async def validate_prereqs() -> None:
            pass

        async def compose_services(project: ComposeProject) -> dict[str, Any]:
            assert project.config is not None and Path(project.config).exists()
            with open(project.config) as f:
                services: dict[str, Any] = yaml.safe_load(f)["services"]
            return services

        async def compose_build(
            project: ComposeProject, capture_output: bool = False
        ) -> None:
            for hook in self.on_build:
                await hook(project)
            services = await compose_services(project)
            for service in services.values():
                build = service.get("build")
                context = build.get("context") if isinstance(build, dict) else build
                if context in self.fail_build_contexts:
                    self.events.append("build-failed")
                    for hook in self.on_build_failure:
                        hook()
                    raise PrerequisiteError("fake build failure")

        async def compose_cleanup_images(
            project: ComposeProject, *, cwd: str | None = None, timeout: int | None
        ) -> None:
            pass

        async def image_exists_locally(image: str) -> bool:
            return True

        async def compose_up(
            project: ComposeProject, services: dict[str, Any]
        ) -> ExecResult[str]:
            self.running.add(project.name)
            self.events.append(f"up:{project.sample_id}")
            return ExecResult(success=True, returncode=0, stdout="", stderr="")

        async def compose_check_running(
            services: list[str], project: ComposeProject
        ) -> list[str]:
            return services if project.name in self.running else []

        async def container_working_dir(
            service: str, project: ComposeProject, default: str = "/"
        ) -> str:
            return default

        async def get_ports_info(container: str) -> None:
            return None

        async def compose_down(project: ComposeProject, quiet: bool = True) -> None:
            self.running.discard(project.name)
            self.events.append(f"down:{project.sample_id}")

        def containers(project: ComposeProject) -> list[dict[str, Any]]:
            if project.name in self.running:
                return [{"Name": f"{project.name}-default-1", "Service": "default"}]
            return []

        async def compose_ps(
            project: ComposeProject, status: str | None = None, all: bool = False
        ) -> list[dict[str, Any]]:
            # the "not yet cleaned up" report's lookup (cleanup.py)
            self.reported.append(f"ps:{project.sample_id}")
            return containers(project)

        async def connection_ps(
            project: ComposeProject, status: str | None = None, all: bool = False
        ) -> list[dict[str, Any]]:
            # connection()'s lookup (docker.py), not a cleanup report
            return containers(project)

        monkeypatch.setattr(config_module, "inspect_data_dir", fake_data_dir)
        monkeypatch.setattr(docker_module, "validate_prereqs", validate_prereqs)
        monkeypatch.setattr(docker_module, "compose_services", compose_services)
        monkeypatch.setattr(docker_module, "compose_build", compose_build)
        monkeypatch.setattr(
            docker_module, "compose_cleanup_images", compose_cleanup_images
        )
        monkeypatch.setattr(
            docker_module, "docker_image_exists_locally", image_exists_locally
        )
        monkeypatch.setattr(docker_module, "compose_up", compose_up)
        monkeypatch.setattr(
            docker_module, "compose_check_running", compose_check_running
        )
        monkeypatch.setattr(
            docker_module, "container_working_dir", container_working_dir
        )
        monkeypatch.setattr(cleanup_module, "compose_down", compose_down)
        monkeypatch.setattr(cleanup_module, "compose_ps", compose_ps)
        # connection() (called when a sample's sandbox events are logged)
        # queries the daemon through docker.py's own import of compose_ps and
        # then inspects the container it reports
        monkeypatch.setattr(docker_module, "compose_ps", connection_ps)
        monkeypatch.setattr(docker_module, "get_ports_info", get_ports_info)

    def generated_files(self) -> list[str]:
        return sorted(p.name for p in auto_compose_dir().glob("*.yaml"))

    def downs(self) -> list[str]:
        return [e for e in self.events if e.startswith("down:")]


@pytest.fixture
def fake_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeDocker:
    # a working directory with no compose file or Dockerfile, so a bare
    # `sandbox="docker"` resolves to the generated generic compose file
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    init_display_type("none")
    return FakeDocker(monkeypatch, tmp_path)


def write_dockerfile(directory: Path) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    dockerfile = directory / "Dockerfile"
    dockerfile.write_text("FROM scratch\n")
    return dockerfile.as_posix()


def write_compose_file(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "default": {"image": GENERIC_IMAGE, "command": "tail -f /dev/null"}
                }
            }
        )
    )
    return path.resolve().as_posix()


def compose_config() -> ComposeConfig:
    return ComposeConfig(
        services={
            "default": ComposeService(image=GENERIC_IMAGE, command="tail -f /dev/null")
        }
    )


async def run_lifecycle(
    fake: FakeDocker,
    config: SandboxEnvironmentConfigType | None,
    *,
    cleanup: bool = True,
    interrupted: bool = False,
    on_started: Any = None,
) -> None:
    """Drive `task_init` from a feeder task and `sample_init` from a sibling.

    Mirrors the dynamic dispatcher's shape: the feeder and the sample are
    siblings under one task group, and neither can see a ContextVar the other
    binds. The caller's context then runs `task_cleanup`, as the run does.
    """
    started = anyio.Event()

    async def feeder() -> None:
        await DockerSandboxEnvironment.task_init("startup", config)
        started.set()

    async def sample() -> None:
        await started.wait()
        environments = await DockerSandboxEnvironment.sample_init("sample", config, {})
        if on_started is not None:
            on_started()
        await DockerSandboxEnvironment.sample_cleanup(
            "sample", config, environments, interrupted
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(feeder)
        tg.start_soon(sample)

    await DockerSandboxEnvironment.task_cleanup("shutdown", config, cleanup)


# -- provider level ------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", ["generic", "dockerfile", "compose_config", "explicit", "legacy"]
)
async def test_late_task_init_shares_the_scope_registry(
    fake_docker: FakeDocker, tmp_path: Path, kind: str
) -> None:
    """Every supported config family is cleaned when task_init ran in a sibling.

    Before the registry moved onto the scope, a bare `sandbox="docker"` (or a
    Dockerfile / ComposeConfig) failed in `sample_init` with a `LookupError`
    on the auto-compose ContextVar, and an explicit compose file leaked the
    startup registrations. Explicit compose files are never removed; a
    legacy `.compose.yaml` in the working directory still is.
    """
    config: SandboxEnvironmentConfigType | None
    legacy: Path | None = None
    generated = 2  # startup project + sample project
    if kind == "generic":
        config = None
    elif kind == "dockerfile":
        config = write_dockerfile(tmp_path / "image")
    elif kind == "compose_config":
        config = compose_config()
    elif kind == "explicit":
        config = write_compose_file(tmp_path / "explicit" / "compose.yaml")
        generated = 0
    else:
        legacy = Path(write_compose_file(Path(os.getcwd()) / ".compose.yaml"))
        config = None
        generated = 0

    registered: list[int] = []

    def on_started() -> None:
        registered.append(len(cleanup_state().auto_compose_files))

    with sandbox_lifecycle_scope():
        await run_lifecycle(fake_docker, config, on_started=on_started)
        assert cleanup_state().running_projects == []
        assert cleanup_state().auto_compose_files == set()

    # the startup and sample files were both registered while the sample ran,
    # and all of them are gone after shutdown
    assert registered == [generated if kind != "legacy" else 1]
    assert fake_docker.events == ["up:None", "down:None"]
    assert fake_docker.generated_files() == []
    if kind == "explicit":
        assert isinstance(config, str) and Path(config).exists()
    if kind == "legacy":
        assert legacy is not None and not legacy.exists()


@pytest.mark.parametrize("cleanup", [True, False])
async def test_shutdown_releases_the_registry(
    fake_docker: FakeDocker, cleanup: bool
) -> None:
    """An interrupted sample's project is cleaned (or reported) at shutdown.

    With cleanup on it is brought down; with `--no-sandbox-cleanup` it is
    reported for `inspect sandbox cleanup docker` and left running. Either
    way the registry releases it and its compose files, so nothing is
    retained for a later batch to clean twice or report again.
    """
    with sandbox_lifecycle_scope():
        await run_lifecycle(fake_docker, None, cleanup=cleanup, interrupted=True)
        assert cleanup_state().running_projects == []
        assert cleanup_state().auto_compose_files == set()

        # a second task_cleanup (a second Docker config) has nothing to do
        await DockerSandboxEnvironment.task_cleanup("shutdown", None, cleanup)

    if cleanup:
        assert fake_docker.events == ["up:None", "down:None"]
        assert fake_docker.reported == []
    else:
        assert fake_docker.events == ["up:None"]
        assert fake_docker.reported == ["ps:None"]
        assert len(fake_docker.running) == 1
    assert fake_docker.generated_files() == []


async def test_repeated_task_init_preserves_registered_resources(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    """A second config's task_init keeps the first config's startup file registered.

    `task_init` used to rebind the registry, so the first startup compose file
    was forgotten and leaked.
    """
    dockerfile = write_dockerfile(tmp_path / "image")
    with sandbox_lifecycle_scope():
        await DockerSandboxEnvironment.task_init("startup", None)
        assert len(cleanup_state().auto_compose_files) == 1
        await DockerSandboxEnvironment.task_init("startup", dockerfile)
        assert len(cleanup_state().auto_compose_files) == 2
        assert len(fake_docker.generated_files()) == 2

        await DockerSandboxEnvironment.task_cleanup("shutdown", None, True)
        assert cleanup_state().auto_compose_files == set()
    assert fake_docker.generated_files() == []


async def test_failed_task_init_releases_only_its_own_resources(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    """A late config failing startup leaves the live sample and the batch cleanup alone.

    The failure removes the startup compose file it generated and nothing
    else: the running project of an earlier config stays up and registered,
    its startup file stays registered, and the final `task_cleanup` still
    brings everything down.
    """
    failing = write_dockerfile(tmp_path / "failing")
    fake_docker.fail_build_contexts.add((tmp_path / "failing").resolve().as_posix())

    with sandbox_lifecycle_scope():
        await DockerSandboxEnvironment.task_init("startup", None)
        environments = await DockerSandboxEnvironment.sample_init("sample", None, {})
        assert len(cleanup_state().running_projects) == 1
        assert len(fake_docker.generated_files()) == 2

        with pytest.raises(PrerequisiteError, match="fake build failure"):
            await DockerSandboxEnvironment.task_init("startup", failing)

        # only the failed startup's file is gone; the live sample is untouched
        assert len(cleanup_state().running_projects) == 1
        assert len(cleanup_state().auto_compose_files) == 2
        assert len(fake_docker.generated_files()) == 2
        assert fake_docker.downs() == []

        await DockerSandboxEnvironment.sample_cleanup(
            "sample", None, environments, True
        )
        await DockerSandboxEnvironment.task_cleanup("shutdown", None, True)
        assert cleanup_state().running_projects == []

    assert fake_docker.downs() == ["down:None"]
    assert fake_docker.generated_files() == []


@pytest.mark.parametrize("failure", ["error", "cancel"])
@pytest.mark.parametrize("shared", ["legacy", "central"])
async def test_failed_task_init_keeps_a_shared_compose_file(
    fake_docker: FakeDocker, shared: str, failure: str
) -> None:
    """A failed or cancelled task_init never removes a compose file another owner registered.

    A legacy `.compose.yaml` in the working directory, or a path in the
    auto-compose directory reused by another configuration, is one file for
    every project of that path. When a second initialization of it (another
    configuration of the same file) fails or is cancelled mid-build, the file
    the live sample's `compose` commands name stays on disk and registered,
    and the batch's final cleanup removes it as usual.
    """
    config: SandboxEnvironmentConfigType | None
    if shared == "legacy":
        path = write_compose_file(Path(os.getcwd()) / ".compose.yaml")
        config = None
    else:
        path = write_compose_file(auto_compose_dir() / "shared.yaml")
        config = path

    with sandbox_lifecycle_scope():
        await DockerSandboxEnvironment.task_init("startup", config)
        environments = await DockerSandboxEnvironment.sample_init("sample", config, {})
        assert cleanup_state().auto_compose_files == {path}

        entered = anyio.Event()

        async def fail_or_block(project: ComposeProject) -> None:
            entered.set()
            if failure == "error":
                raise PrerequisiteError("fake build failure")
            await anyio.sleep_forever()

        fake_docker.on_build.append(fail_or_block)
        if failure == "error":
            with pytest.raises(PrerequisiteError, match="fake build failure"):
                await DockerSandboxEnvironment.task_init("startup", config)
        else:
            async with anyio.create_task_group() as tg:
                tg.start_soon(DockerSandboxEnvironment.task_init, "startup", config)
                await entered.wait()
                tg.cancel_scope.cancel()
        fake_docker.on_build.clear()

        # the live sample's file is intact, still registered, and its project
        # is still running
        assert Path(path).exists()
        assert cleanup_state().auto_compose_files == {path}
        assert len(cleanup_state().running_projects) == 1
        assert fake_docker.downs() == []

        await DockerSandboxEnvironment.sample_cleanup(
            "sample", config, environments, False
        )
        await DockerSandboxEnvironment.task_cleanup("shutdown", config, True)

    assert fake_docker.events == ["up:None", "down:None"]
    assert not Path(path).exists()
    assert fake_docker.generated_files() == []


async def test_direct_provider_use_without_a_scope(fake_docker: FakeDocker) -> None:
    """The provider driven directly (no SandboxManager) still cleans up after itself."""
    assert sandbox_lifecycle_state() is None
    await DockerSandboxEnvironment.task_init("startup", None)
    environments = await DockerSandboxEnvironment.sample_init("sample", None, {})
    await DockerSandboxEnvironment.sample_cleanup("sample", None, environments, False)
    await DockerSandboxEnvironment.task_cleanup("shutdown", None, True)

    assert fake_docker.events == ["up:None", "down:None"]
    assert fake_docker.generated_files() == []
    assert cleanup_state().running_projects == []
    assert cleanup_state().auto_compose_files == set()


async def test_direct_provider_lifecycles_in_child_tasks_are_independent(
    fake_docker: FakeDocker,
) -> None:
    """Concurrent direct lifecycles in child tasks never share a registry.

    A parent that has driven the provider directly leaves its (finished)
    registry bound in the context its children inherit. Each child's
    `task_init` binds its own, so one child's `task_cleanup` brings down only
    its own container and leaves the other child's container and compose file
    alone.
    """
    # the parent's own lifecycle, which the children inherit the binding of
    await DockerSandboxEnvironment.task_init("startup", None)
    parent = await DockerSandboxEnvironment.sample_init("parent", None, {})
    await DockerSandboxEnvironment.sample_cleanup("parent", None, parent, False)
    await DockerSandboxEnvironment.task_cleanup("shutdown", None, True)

    b_up = anyio.Event()
    a_cleaned = anyio.Event()
    observed: list[tuple[bool, bool, int]] = []

    async def lifecycle_a() -> None:
        await DockerSandboxEnvironment.task_init("startup", None)
        environments = await DockerSandboxEnvironment.sample_init("a", None, {})
        await b_up.wait()
        await DockerSandboxEnvironment.sample_cleanup("a", None, environments, False)
        await DockerSandboxEnvironment.task_cleanup("shutdown", None, True)
        a_cleaned.set()

    async def lifecycle_b() -> None:
        await DockerSandboxEnvironment.task_init("startup", None)
        environments = await DockerSandboxEnvironment.sample_init("b", None, {})
        project = environments["default"].as_type(DockerSandboxEnvironment)._project
        b_up.set()
        await a_cleaned.wait()
        # b's container and compose file survived a's cleanup
        assert project.config is not None
        observed.append(
            (
                project.name in fake_docker.running,
                Path(project.config).exists(),
                len(cleanup_state().running_projects),
            )
        )
        await DockerSandboxEnvironment.sample_cleanup("b", None, environments, False)
        await DockerSandboxEnvironment.task_cleanup("shutdown", None, True)

    async with anyio.create_task_group() as tg:
        tg.start_soon(lifecycle_a)
        tg.start_soon(lifecycle_b)

    assert observed == [(True, True, 1)]
    assert fake_docker.downs() == ["down:None"] * 3
    assert fake_docker.running == set()
    assert fake_docker.generated_files() == []


# -- eval level -----------------------------------------------------------------


def _sample_errors(log: EvalLog) -> list[str]:
    return [str(s.error.message) for s in (log.samples or []) if s.error is not None]


class _AddOne(SampleSource):
    """Empty seed; one sample added by the requested route."""

    def __init__(self, route: str, added: Sample) -> None:
        self.route = route
        self.added = added
        self._produced = False

    def initial_samples(self) -> list[Sample]:
        return [] if self.route != "sample_complete" else [Sample(input="seed")]

    async def next_samples(self) -> list[Sample] | None:
        if self._produced:
            return None
        self._produced = True
        if self.route == "next_samples":
            return [self.added]
        if self.route == "enqueue_sample":
            enqueue_sample([self.added])
        return []

    async def sample_complete(self, sample: EvalSample) -> list[Sample] | None:
        if self.route == "sample_complete" and sample.input == "seed":
            return [self.added]
        return None


@pytest.mark.parametrize("route", ["next_samples", "enqueue_sample", "sample_complete"])
async def test_docker_sample_added_to_a_task_without_docker_samples(
    fake_docker: FakeDocker, route: str
) -> None:
    """The first Docker sample of a task may arrive from the source, not the seed.

    An empty seed with `sandbox="docker"` (`next_samples` / `enqueue_sample`
    routes), or a seed without a sandbox whose completion adds a Docker
    sample (`sample_complete` route), runs `task_init` in the feeder task.
    The added sample must start, and everything must be cleaned at the end.
    """
    if route == "sample_complete":
        added = Sample(input="added", sandbox="docker")
        task = Task(dataset=_AddOne(route, added), solver=[generate()], name="t")
    else:
        added = Sample(input="added")
        task = Task(
            dataset=_AddOne(route, added),
            solver=[generate()],
            sandbox="docker",
            name="t",
        )

    logs = await eval_async(task, model="mockllm/model")

    assert logs[0].status == "success", logs[0].error
    assert _sample_errors(logs[0]) == []
    assert sorted(str(s.input) for s in (logs[0].samples or [])) == sorted(
        ["added"] + (["seed"] if route == "sample_complete" else [])
    )
    added_id = added.id
    assert fake_docker.events == [f"up:{added_id}", f"down:{added_id}"]
    assert fake_docker.generated_files() == []
    assert sandbox_lifecycle_state() is None


async def test_late_docker_config_keeps_earlier_startup_resources(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    """A config first seen in an added sample is started without losing the seed's.

    Both startup compose files (seed config, added config) and both sample
    projects are cleaned at the end of the run.
    """
    dockerfile = write_dockerfile(tmp_path / "image")
    late = Sample(
        id="late", input="late", sandbox=SandboxEnvironmentSpec("docker", dockerfile)
    )

    async def on_complete(sample: EvalSample) -> list[Sample] | None:
        return [late] if sample.id == "seed" else None

    source = SampleSource.from_samples(
        [Sample(id="seed", input="seed")], sample_complete=on_complete
    )
    logs = await eval_async(
        Task(dataset=source, solver=[generate()], sandbox="docker", name="t"),
        model="mockllm/model",
    )

    assert logs[0].status == "success", logs[0].error
    assert _sample_errors(logs[0]) == []
    assert sorted(fake_docker.events) == [
        "down:late",
        "down:seed",
        "up:late",
        "up:seed",
    ]
    assert fake_docker.generated_files() == []


async def test_failed_late_config_leaves_live_sample_running(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    """A late config failing `task_init` does not bring down live samples.

    The seed sample is running when the added sample's Dockerfile fails to
    build: at that moment its project is still registered and up. The
    failure fails the task, and the batch's final cleanup — not the failed
    startup — brings the interrupted seed sample's project down.
    """
    failing_dir = tmp_path / "failing"
    failing = write_dockerfile(failing_dir)
    fake_docker.fail_build_contexts.add(failing_dir.resolve().as_posix())

    at_failure: list[Any] = []

    def observe() -> None:
        # runs in the feeder task: the registry it sees is the batch's
        at_failure.append(
            (
                [p.sample_id for p in cleanup_state().running_projects],
                list(fake_docker.downs()),
            )
        )

    fake_docker.on_build_failure.append(observe)
    build_failed = anyio.Event()

    @solver(name="hold_until_failure")
    def hold_until_failure() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_sample(
                [
                    Sample(
                        id="late",
                        input="late",
                        sandbox=SandboxEnvironmentSpec("docker", failing),
                    )
                ]
            )
            with anyio.move_on_after(30):
                await build_failed.wait()
            return state

        return solve

    fake_docker.on_build_failure.append(build_failed.set)

    source = SampleSource.from_samples([Sample(id="seed", input="seed")])
    logs = await eval_async(
        Task(dataset=source, solver=hold_until_failure(), sandbox="docker", name="t"),
        model="mockllm/model",
    )

    assert logs[0].status == "error"
    assert logs[0].error is not None and "fake build failure" in logs[0].error.message
    assert at_failure == [(["seed"], [])]
    assert fake_docker.downs() == ["down:seed"]
    assert fake_docker.generated_files() == []


async def test_sequential_batches_have_independent_cleanup_state(
    fake_docker: FakeDocker,
) -> None:
    """Two TaskSource batches in one run each clean their own Docker resources.

    With one model, batches run as sequential `eval_run` calls in the same
    task, so the second must not inherit the first's registry or its
    "already cleaned" status. The second batch's sample is cancelled
    mid-run (an operator task cancel), so its cleanup is the deferred kind
    that only the batch's final `task_cleanup` performs.
    """
    from inspect_ai._control.cancel import cancel_task as ctl_cancel_task
    from inspect_ai._control.eval_state import get_eval_states

    @solver(name="cancel_own_task")
    def cancel_own_task() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            task_id = next(s.task_id for s in get_eval_states() if s.task == "second")
            result = ctl_cancel_task(task_id, action="cancel")
            assert result is not None and result["ok"] is True
            await anyio.sleep(10)
            return state

        return solve

    def dynamic_task(name: str, solver: Solver) -> Task:
        return Task(
            dataset=_AddOne("next_samples", Sample(id=name, input=name)),
            solver=solver,
            sandbox="docker",
            name=name,
        )

    class _TwoBatches(TaskSource):
        def __init__(self) -> None:
            self._produced = False

        def initial_tasks(self) -> list[Task]:
            return [dynamic_task("first", generate())]

        async def next_tasks(self) -> list[Task] | None:
            if self._produced:
                return None
            self._produced = True
            return [dynamic_task("second", cancel_own_task())]

    logs = await eval_async(tasks=_TwoBatches(), model="mockllm/model")

    assert [log.status for log in logs] == ["success", "error"]
    assert logs[1].error is not None and "cancelled" in logs[1].error.message
    assert fake_docker.events == [
        "up:first",
        "down:first",
        "up:second",
        "down:second",
    ]
    assert fake_docker.generated_files() == []
    assert sandbox_lifecycle_state() is None


async def test_independent_evaluations_do_not_share_cleanup_state(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    """A later eval never cleans up (or re-reports) an earlier eval's containers.

    The first eval keeps its container (`sandbox_cleanup=False`) and reports
    it once; the second eval's cleanup brings down only its own project.
    Before the registry had an owner, the process-wide default list carried
    the first eval's project into the second eval's cleanup.
    """
    compose_file = write_compose_file(tmp_path / "explicit" / "compose.yaml")

    def dynamic_task(name: str) -> Task:
        return Task(
            dataset=_AddOne("next_samples", Sample(id=name, input=name)),
            solver=[generate()],
            sandbox=SandboxEnvironmentSpec("docker", compose_file),
            name=name,
        )

    first = await eval_async(
        dynamic_task("first"), model="mockllm/model", sandbox_cleanup=False
    )
    assert first[0].status == "success", first[0].error
    assert fake_docker.events == ["up:first"]
    assert fake_docker.reported == ["ps:first"]

    second = await eval_async(dynamic_task("second"), model="mockllm/model")
    assert second[0].status == "success", second[0].error
    assert fake_docker.events == ["up:first", "up:second", "down:second"]
    assert fake_docker.reported == ["ps:first"]
    assert Path(compose_file).exists()
    assert fake_docker.generated_files() == []


# -- real Docker ----------------------------------------------------------------


@skip_if_no_docker
@pytest.mark.slow
def test_docker_empty_seed_sample_source() -> None:
    """An empty-seed SampleSource task with `sandbox="docker"` runs its added sample."""
    source = _AddOne("next_samples", Sample(input="added"))
    logs = eval(
        Task(dataset=source, solver=[generate()], sandbox="docker", name="t"),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "success", logs[0].error
    assert _sample_errors(logs[0]) == []
    assert [str(s.input) for s in (logs[0].samples or [])] == ["added"]
