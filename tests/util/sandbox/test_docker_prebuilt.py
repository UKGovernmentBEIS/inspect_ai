from typing import Any

import pytest

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util import ExecResult
from inspect_ai.util._sandbox.docker import compose as compose_module
from inspect_ai.util._sandbox.docker import docker as docker_module
from inspect_ai.util._sandbox.docker.compose import compose_verify_prebuilt_images
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._sandbox.environment import (
    sandbox_prebuilt,
    set_sandbox_prebuilt,
)


def compose_project(config: str | None = "/tmp/compose.yaml") -> ComposeProject:
    return ComposeProject(
        name="inspect-test", config=config, sample_id=None, epoch=None, env=None
    )


def stub_image_exists(monkeypatch: pytest.MonkeyPatch, local_images: set[str]) -> None:
    async def fake_exists(image: str) -> bool:
        return image in local_images

    monkeypatch.setattr(compose_module, "docker_image_exists_locally", fake_exists)


async def test_verify_prebuilt_images_passes_when_images_exist(monkeypatch):
    stub_image_exists(monkeypatch, {"built-image"})

    await compose_verify_prebuilt_images(
        compose_project(),
        {
            "built": {"build": ".", "image": "built-image"},
            "pulled": {"image": "pulled-image"},
        },
    )


async def test_verify_prebuilt_images_missing_image(monkeypatch):
    stub_image_exists(monkeypatch, set())

    with pytest.raises(PrerequisiteError) as excinfo:
        await compose_verify_prebuilt_images(
            compose_project(), {"built": {"build": ".", "image": "built-image"}}
        )
    assert "not present in the Docker image store" in str(excinfo.value)
    assert "built (built-image)" in str(excinfo.value)


async def test_verify_prebuilt_images_unnamed_service(monkeypatch):
    stub_image_exists(monkeypatch, set())

    with pytest.raises(PrerequisiteError) as excinfo:
        await compose_verify_prebuilt_images(
            compose_project(), {"unnamed": {"build": "."}}
        )
    assert "Add an explicit 'image' name" in str(excinfo.value)
    assert "unnamed" in str(excinfo.value)


async def test_verify_prebuilt_images_missing_x_local_image(monkeypatch):
    stub_image_exists(monkeypatch, set())

    with pytest.raises(PrerequisiteError) as excinfo:
        await compose_verify_prebuilt_images(
            compose_project(),
            {"local": {"image": "local-image", "x-local": True}},
        )
    assert "not present in the Docker image store" in str(excinfo.value)
    assert "local (local-image)" in str(excinfo.value)


async def test_verify_prebuilt_images_treats_x_local_false_as_pulled(monkeypatch):
    stub_image_exists(monkeypatch, set())

    await compose_verify_prebuilt_images(
        compose_project(),
        {"local": {"image": "local-image", "x-local": False}},
    )


async def test_verify_prebuilt_images_passes_x_local_image_present(monkeypatch):
    stub_image_exists(monkeypatch, {"local-image"})

    await compose_verify_prebuilt_images(
        compose_project(),
        {"local": {"image": "local-image", "x-local": True}},
    )


async def test_verify_prebuilt_images_ignores_services_without_build(monkeypatch):
    stub_image_exists(monkeypatch, set())

    await compose_verify_prebuilt_images(
        compose_project(), {"pulled": {"image": "pulled-image"}}
    )


async def test_verify_prebuilt_images_reports_both_problems(monkeypatch):
    stub_image_exists(monkeypatch, set())

    with pytest.raises(PrerequisiteError) as excinfo:
        await compose_verify_prebuilt_images(
            compose_project(),
            {
                "unnamed": {"build": "."},
                "built": {"build": ".", "image": "built-image"},
            },
        )
    message = str(excinfo.value)
    assert "unnamed" in message
    assert "built (built-image)" in message
    assert ". Additionally, these services' images" in message


async def test_verify_prebuilt_images_auto_compose_message(monkeypatch):
    stub_image_exists(monkeypatch, set())

    with pytest.raises(PrerequisiteError) as excinfo:
        await compose_verify_prebuilt_images(
            compose_project(config="/some/dir/.compose.yaml"),
            {"default": {"build": "."}},
        )
    assert "does not name an 'image'" in str(excinfo.value)


class TaskInitStubs:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        services: dict[str, dict[str, Any]],
        prebuilt: bool,
        internal_images_built: bool = True,
    ) -> None:
        self.calls: list[str] = []
        project = compose_project()

        async def fake_create(cls: Any, name: str, config: Any) -> ComposeProject:
            return project

        async def fake_validate_prereqs() -> None:
            pass

        async def fake_cleanup_shutdown(cleanup: bool) -> None:
            pass

        async def fake_compose_services(project: ComposeProject) -> dict[str, Any]:
            return services

        def record(call: str) -> Any:
            async def fake(*args: Any, **kwargs: Any) -> None:
                self.calls.append(call)

            return fake

        async def fake_internal_built(image: str) -> bool:
            return internal_images_built

        monkeypatch.setattr(ComposeProject, "create", classmethod(fake_create))
        monkeypatch.setattr(docker_module, "validate_prereqs", fake_validate_prereqs)
        monkeypatch.setattr(docker_module, "project_cleanup_startup", lambda: None)
        monkeypatch.setattr(
            docker_module, "project_record_auto_compose", lambda project: None
        )
        monkeypatch.setattr(
            docker_module, "project_cleanup_shutdown", fake_cleanup_shutdown
        )
        monkeypatch.setattr(docker_module, "compose_services", fake_compose_services)
        monkeypatch.setattr(docker_module, "compose_build", record("build"))
        monkeypatch.setattr(
            docker_module, "compose_cleanup_images", record("cleanup_images")
        )
        monkeypatch.setattr(
            docker_module, "compose_verify_prebuilt_images", record("verify")
        )
        monkeypatch.setattr(
            docker_module, "build_internal_image", record("build_internal")
        )
        monkeypatch.setattr(
            docker_module, "is_internal_image_built", fake_internal_built
        )
        monkeypatch.setattr(docker_module, "sandbox_prebuilt", lambda: prebuilt)


async def test_task_init_prebuilt_skips_build(monkeypatch):
    stubs = TaskInitStubs(
        monkeypatch, {"built": {"build": ".", "image": "built-image"}}, prebuilt=True
    )

    await DockerSandboxEnvironment.task_init("startup", None)

    assert stubs.calls == ["verify"]


async def test_task_init_builds_when_not_prebuilt(monkeypatch):
    stubs = TaskInitStubs(
        monkeypatch, {"built": {"build": ".", "image": "built-image"}}, prebuilt=False
    )

    await DockerSandboxEnvironment.task_init("startup", None)

    assert stubs.calls == ["build", "cleanup_images"]


async def test_task_init_prebuilt_internal_image_present(monkeypatch):
    stubs = TaskInitStubs(
        monkeypatch,
        {"default": {"image": "inspect-computer-tool"}},
        prebuilt=True,
        internal_images_built=True,
    )

    await DockerSandboxEnvironment.task_init("startup", None)

    assert stubs.calls == ["verify"]


async def test_task_init_prebuilt_internal_image_missing(monkeypatch):
    TaskInitStubs(
        monkeypatch,
        {"default": {"image": "inspect-computer-tool"}},
        prebuilt=True,
        internal_images_built=False,
    )

    with pytest.raises(PrerequisiteError) as excinfo:
        await DockerSandboxEnvironment.task_init("startup", None)
    assert "inspect-computer-tool" in str(excinfo.value)


def stub_pull_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_exists(image: str) -> bool:
        return False

    async def fake_pull(service: str, project: ComposeProject) -> ExecResult[str]:
        return ExecResult(success=False, returncode=1, stdout="", stderr="")

    monkeypatch.setattr(docker_module, "docker_image_exists_locally", fake_exists)
    monkeypatch.setattr(docker_module, "compose_pull", fake_pull)


async def test_task_init_prebuilt_pull_failure_raises(monkeypatch):
    TaskInitStubs(monkeypatch, {"pulled": {"image": "remote-image"}}, prebuilt=True)
    stub_pull_failure(monkeypatch)

    with pytest.raises(PrerequisiteError) as excinfo:
        await DockerSandboxEnvironment.task_init("startup", None)
    assert "remote-image" in str(excinfo.value)
    assert "could not be pulled" in str(excinfo.value)


async def test_task_init_pulls_x_local_false_service(monkeypatch):
    TaskInitStubs(
        monkeypatch,
        {"pulled": {"image": "remote-image", "x-local": False}},
        prebuilt=True,
    )
    stub_pull_failure(monkeypatch)

    with pytest.raises(PrerequisiteError) as excinfo:
        await DockerSandboxEnvironment.task_init("startup", None)
    assert "could not be pulled" in str(excinfo.value)


async def test_task_init_pull_failure_logs_when_not_prebuilt(monkeypatch):
    stubs = TaskInitStubs(
        monkeypatch, {"pulled": {"image": "remote-image"}}, prebuilt=False
    )
    stub_pull_failure(monkeypatch)

    await DockerSandboxEnvironment.task_init("startup", None)

    assert stubs.calls == ["build", "cleanup_images"]


async def test_task_init_builds_internal_image_when_not_prebuilt(monkeypatch):
    stubs = TaskInitStubs(
        monkeypatch,
        {"default": {"image": "inspect-computer-tool"}},
        prebuilt=False,
    )

    await DockerSandboxEnvironment.task_init("startup", None)

    assert stubs.calls == ["build", "cleanup_images", "build_internal"]


def test_sandbox_prebuilt_contextvar():
    assert sandbox_prebuilt() is False
    set_sandbox_prebuilt(True)
    try:
        assert sandbox_prebuilt() is True
    finally:
        set_sandbox_prebuilt(False)
