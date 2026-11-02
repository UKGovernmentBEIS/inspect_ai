"""Tests for ComposeConfig support in Docker sandbox."""

import json
import os
from pathlib import Path
from typing import Any

import anyio
import pytest
import yaml
from test_helpers.utils import skip_if_no_docker

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util import (
    ComposeConfig,
    ComposeService,
    ComposeVolumeMount,
    ExecResult,
)
from inspect_ai.util._sandbox.docker import compose as compose_module
from inspect_ai.util._sandbox.docker import docker as docker_module
from inspect_ai.util._sandbox.docker import mounts as mounts_module
from inspect_ai.util._sandbox.docker import prereqs as prereqs_module
from inspect_ai.util._sandbox.docker.compose import (
    compose_down,
    compose_exec,
    compose_services,
    compose_up,
)
from inspect_ai.util._sandbox.docker.config import (
    auto_compose_dir,
    is_auto_compose_file,
)
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.mounts import validate_compose_mounts
from inspect_ai.util._sandbox.docker.util import ComposeProject, task_project_name


@skip_if_no_docker
async def test_compose_project_create_with_compose_config(request) -> None:
    """Test that ComposeProject.create() accepts ComposeConfig objects."""
    task_name = f"{__name__}_{request.node.name}"

    config = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    project = await ComposeProject.create(
        name=task_name,
        config=config,
    )

    try:
        # Verify the project was created with a valid config path
        assert project.config is not None
        # Auto-compose files are now stored in the central directory
        assert is_auto_compose_file(project.config)
        assert Path(project.config).parent == auto_compose_dir()
        assert project.config.endswith(".yaml")
        assert os.path.exists(project.config)

        # Verify the generated YAML contains expected content
        with open(project.config, "r") as f:
            content = f.read()
            assert "python:3.12-bookworm" in content
            assert "tail -f /dev/null" in content
    finally:
        # Clean up the auto-generated compose file
        if project.config and os.path.exists(project.config):
            os.unlink(project.config)


RELATIVE_MOUNTS = [
    "./data:/data",
    ".:/workspace",
    "../data:/data:ro",
    ComposeVolumeMount(type="bind", source="data", target="/data"),
    ComposeVolumeMount(type="bind", source="./data", target="/data", read_only=True),
]

ACCEPTED_MOUNTS = [
    "/host/data:/data:ro",
    "~/data:/data:ro",
    "named:/data",
    "/data",
    "${DATA_DIR}:/data:ro",
    "C:${HOMEPATH}:/data:ro",
    ComposeVolumeMount(
        type="bind", source="/host/data", target="/data", read_only=True
    ),
    ComposeVolumeMount(type="bind", source="${DATA_DIR}/data", target="/data"),
    ComposeVolumeMount(type="bind", source="C:${HOMEPATH}", target="/data"),
    ComposeVolumeMount(type="volume", source="named", target="/data"),
    ComposeVolumeMount(type="tmpfs", target="/scratch"),
]


def _compose_config(**service: Any) -> ComposeConfig:
    return ComposeConfig(
        services={"default": ComposeService(image="alpine", **service)}
    )


@pytest.mark.parametrize("mount", RELATIVE_MOUNTS, ids=repr)
async def test_compose_config_rejects_relative_bind_sources(
    mount: str | ComposeVolumeMount,
) -> None:
    name = task_project_name("test-relative-mount")
    with pytest.raises(PrerequisiteError, match="uses a relative host path") as ex:
        await ComposeProject.create(name=name, config=_compose_config(volumes=[mount]))
    assert "Docker service 'default' mount" in str(ex.value)
    assert 'Path(__file__).parent / "data"' in str(ex.value)
    assert not (auto_compose_dir() / f"{name}.yaml").exists()


@pytest.mark.parametrize("env_file", [".env", "task.env", ["/host/.env", "./task.env"]])
async def test_compose_config_rejects_relative_env_files(
    env_file: str | list[str],
) -> None:
    name = task_project_name("test-relative-env-file")
    with pytest.raises(PrerequisiteError, match="env_file '.*' uses a relative host"):
        await ComposeProject.create(
            name=name, config=_compose_config(env_file=env_file)
        )
    assert not (auto_compose_dir() / f"{name}.yaml").exists()


@pytest.mark.parametrize("mount", ACCEPTED_MOUNTS, ids=repr)
async def test_compose_config_accepts_absolute_and_managed_mounts(
    mount: str | ComposeVolumeMount,
) -> None:
    config = _compose_config(volumes=[mount], env_file="/host/.env")
    project = await ComposeProject.create(
        name=task_project_name("test-absolute-mount"), config=config
    )
    try:
        assert project.config and os.path.exists(project.config)
    finally:
        if project.config:
            os.unlink(project.config)


async def test_mount_validation_rejects_sources_in_auto_compose_dir(
    read_only_bind: dict[str, Any],
) -> None:
    source = (auto_compose_dir() / "data").as_posix()
    read_only_bind["services"]["default"]["volumes"][0]["source"] = source
    with pytest.raises(PrerequisiteError, match="resolves into Inspect's generated"):
        await validate_compose_mounts(read_only_bind, "inspect-test")


async def test_mount_validation_rejects_auto_compose_dir_despite_opt_in(
    read_only_bind: dict[str, Any],
) -> None:
    read_only_bind["x-inspect_docker_sandbox"] = {
        "unsafe_allow_writable_host_mounts": True
    }
    read_only_bind["services"]["default"]["volumes"][0]["source"] = (
        auto_compose_dir().as_posix()
    )
    with pytest.raises(PrerequisiteError, match="resolves into Inspect's generated"):
        await validate_compose_mounts(read_only_bind, "inspect-test")


@skip_if_no_docker
async def test_mount_validation_rejects_interpolated_relative_source() -> None:
    config = _compose_config(volumes=["${DATA_DIR}:/data:ro"])
    project = await ComposeProject.create(
        name=task_project_name("test-interpolated-mount"),
        config=config,
        env={"DATA_DIR": "./data"},
    )
    try:
        with pytest.raises(
            PrerequisiteError, match="resolves into Inspect's generated"
        ):
            await compose_services(project)
    finally:
        if project.config:
            os.unlink(project.config)


async def test_mount_validation_allows_binds_elsewhere_in_data_dir(
    read_only_bind: dict[str, Any], mount_daemon: dict[str, Any]
) -> None:
    source = (inspect_data_dir(None) / "traces").as_posix()
    read_only_bind["services"]["default"]["volumes"][0]["source"] = source
    await validate_compose_mounts(read_only_bind, "inspect-test")


@pytest.fixture
def mount_daemon(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    info: dict[str, Any] = {
        "ServerVersion": "25.0.0",
        "KernelVersion": "5.12.0-test",
        "DefaultRuntime": "runc",
        "Runtimes": {
            "runc": {
                "status": {
                    "org.opencontainers.runtime-spec.features": json.dumps(
                        {"mountOptions": ["rro"]}
                    )
                }
            }
        },
    }

    async def docker_info(args: list[str], **kwargs: Any) -> ExecResult[str]:
        stdout = (
            json.dumps({"version": info.get("ComposeVersion", "2.24.0")})
            if args[:3] == ["docker", "compose", "version"]
            else json.dumps(info)
        )
        return ExecResult(success=True, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(mounts_module, "subprocess", docker_info)
    monkeypatch.setattr(prereqs_module, "subprocess", docker_info)
    return info


@pytest.mark.parametrize("settings", [None, True, "true", []])
async def test_invalid_host_mount_settings_explain_yaml(settings: Any) -> None:
    with pytest.raises(PrerequisiteError, match="Put its options underneath") as ex:
        await validate_compose_mounts(
            {"x-inspect_docker_sandbox": settings, "services": {"default": {}}},
            "inspect-test",
        )
    assert (
        "x-inspect_docker_sandbox:\n  unsafe_allow_writable_host_mounts: false"
        in str(ex.value)
    )


@pytest.mark.parametrize("allow", [None, "true", "false", 1, 0, "${ALLOW:-true}"])
async def test_host_mount_opt_in_requires_boolean(allow: Any) -> None:
    with pytest.raises(PrerequisiteError, match="literal boolean"):
        await validate_compose_mounts(
            {
                "x-inspect_docker_sandbox": {
                    "unsafe_allow_writable_host_mounts": allow
                },
                "services": {"default": {}},
            },
            "inspect-test",
        )


@pytest.mark.parametrize("opt_in", [False, True])
async def test_host_mount_opt_in_applies_to_every_service(opt_in: bool) -> None:
    config = {
        "x-inspect_docker_sandbox": {"unsafe_allow_writable_host_mounts": opt_in},
        "services": {
            "default": {},
            "writer": {
                "read_only": True,
                "volumes": [{"type": "bind", "source": "/host", "target": "/output"}],
            },
        },
    }
    if opt_in:
        await validate_compose_mounts(config, "inspect-test")
    else:
        with pytest.raises(
            PrerequisiteError, match="writer.*?/host -> /output.*?writable host bind"
        ):
            await validate_compose_mounts(config, "inspect-test")


@pytest.mark.parametrize(
    "volume",
    [
        {
            "driver": "local",
            "driver_opts": {"type": "none", "o": "bind", "device": "/host"},
        },
        {"external": True, "name": "existing"},
        {"name": "shared"},
        {"driver": "custom"},
    ],
)
@pytest.mark.parametrize("read_only", [False, True])
async def test_unverifiable_volumes_rejected(
    volume: dict[str, Any], read_only: bool
) -> None:
    with pytest.raises(
        PrerequisiteError, match="volume host access cannot be verified"
    ):
        await validate_compose_mounts(
            {
                "services": {
                    "default": {
                        "volumes": [
                            {
                                "type": "volume",
                                "source": "data",
                                "target": "/data",
                                "read_only": read_only,
                            }
                        ]
                    }
                },
                "volumes": {"data": volume},
            },
            "inspect-test",
        )


@pytest.mark.parametrize(
    "service",
    [
        {"volumes_from": ["container:existing:ro"]},
        {"volumes_from": ["writer"]},
        {"volume_driver": "custom"},
    ],
)
async def test_indirect_mounts_rejected(service: dict[str, Any]) -> None:
    with pytest.raises(PrerequisiteError, match="cannot be verified"):
        await validate_compose_mounts(
            {"services": {"default": service}}, "inspect-test"
        )


async def test_managed_volumes_supported_without_daemon() -> None:
    await validate_compose_mounts(
        {
            "services": {
                "default": {
                    "volumes": [
                        {"type": "volume", "source": "data", "target": "/data"},
                        {"type": "volume", "target": "/anonymous"},
                        {"type": "tmpfs", "target": "/tmp"},
                    ]
                }
            },
            "volumes": {"data": {"name": "inspect-test_data", "driver": "local"}},
        },
        "inspect-test",
    )


@pytest.fixture
def read_only_bind() -> dict[str, Any]:
    return {
        "services": {
            "default": {
                "volumes": [
                    {
                        "type": "bind",
                        "source": "/host",
                        "target": "/input",
                        "read_only": True,
                    }
                ]
            }
        }
    }


@pytest.mark.parametrize(
    "bind", [{}, {"recursive": "readonly"}, {"recursive": "disabled"}]
)
async def test_read_only_binds_supported(
    bind: dict[str, str], read_only_bind: dict[str, Any], mount_daemon: dict[str, Any]
) -> None:
    read_only_bind["services"]["default"]["volumes"][0]["bind"] = bind
    await validate_compose_mounts(read_only_bind, "inspect-test")


@pytest.mark.parametrize(
    "bind",
    [{"recursive": "writable"}, {"propagation": "rshared"}, {"propagation": "rslave"}],
)
async def test_read_only_binds_reject_writable_submounts(
    bind: dict[str, str], read_only_bind: dict[str, Any]
) -> None:
    read_only_bind["services"]["default"]["volumes"][0]["bind"] = bind
    with pytest.raises(PrerequisiteError, match="writable submounts"):
        await validate_compose_mounts(read_only_bind, "inspect-test")


@pytest.mark.parametrize(
    "unsupported, expected_diagnostic",
    [
        (
            {"ServerVersion": "24.0.6"},
            "Detected Docker Engine: 24.0.6 (unsupported)",
        ),
        (
            {"KernelVersion": "5.11.0"},
            "Detected Linux kernel: 5.11.0 (unsupported)",
        ),
        (
            {"KernelVersion": "unknown"},
            "Detected Linux kernel: unknown (unsupported)",
        ),
        ({"Runtimes": {}}, "runc (recursive read-only unsupported)"),
        ({"DefaultRuntime": "custom"}, "custom (recursive read-only unsupported)"),
    ],
)
async def test_read_only_binds_require_recursive_support(
    unsupported: dict[str, Any],
    expected_diagnostic: str,
    read_only_bind: dict[str, Any],
    mount_daemon: dict[str, Any],
) -> None:
    mount_daemon.update(unsupported)
    with pytest.raises(PrerequisiteError, match="supporting recursive read-only") as ex:
        await validate_compose_mounts(read_only_bind, "inspect-test")
    error = str(ex.value)
    assert expected_diagnostic in error
    assert f"Detected Docker Engine: {mount_daemon['ServerVersion']}" in error
    assert f"Detected Linux kernel: {mount_daemon['KernelVersion']}" in error
    assert f"Detected runtimes: {mount_daemon['DefaultRuntime']}" in error


async def test_read_only_binds_reject_legacy_compose_api(
    read_only_bind: dict[str, Any], mount_daemon: dict[str, Any]
) -> None:
    mount_daemon["ComposeVersion"] = "2.23.3"
    with pytest.raises(
        PrerequisiteError,
        match=r"Read-only host sharing requires Docker Compose >= 2\.24\.0",
    ):
        await validate_compose_mounts(read_only_bind, "inspect-test")


@pytest.mark.parametrize("api_version", ["1.43", "unknown"])
async def test_read_only_binds_reject_legacy_api_override(
    api_version: str,
    read_only_bind: dict[str, Any],
    mount_daemon: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_API_VERSION", api_version)
    with pytest.raises(
        PrerequisiteError, match="DOCKER_API_VERSION must be 1.44 or newer"
    ):
        await validate_compose_mounts(read_only_bind, "inspect-test")


async def test_read_only_binds_accept_supported_api_override(
    read_only_bind: dict[str, Any],
    mount_daemon: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOCKER_API_VERSION", "1.44")
    await validate_compose_mounts(read_only_bind, "inspect-test")


@pytest.mark.parametrize(
    "privileges",
    [
        {"privileged": True},
        {"cap_add": ["SYS_ADMIN"]},
        {"cap_add": ["CAP_SYS_ADMIN"]},
        {"cap_add": ["ALL"]},
    ],
)
@pytest.mark.parametrize("kind", ["bind", "configs", "secrets"])
async def test_read_only_host_binds_reject_remount_privileges(
    privileges: dict[str, Any], read_only_bind: dict[str, Any], kind: str
) -> None:
    if kind != "bind":
        read_only_bind["services"]["default"] = {kind: [{"source": "input"}]}
    read_only_bind["services"]["default"].update(privileges)
    with pytest.raises(PrerequisiteError, match="remounting host binds writable"):
        await validate_compose_mounts(read_only_bind, "inspect-test")
    read_only_bind["x-inspect_docker_sandbox"] = {
        "unsafe_allow_writable_host_mounts": True
    }
    await validate_compose_mounts(read_only_bind, "inspect-test")


@skip_if_no_docker
@pytest.mark.parametrize("allow", [True, False, "${ALLOW:-true}"])
async def test_compose_resolved_mount_opt_in(allow: bool | str, tmp_path: Path) -> None:
    config = ComposeConfig.model_validate(
        {
            "x-inspect_docker_sandbox": {"unsafe_allow_writable_host_mounts": allow},
            "services": {
                "default": {"image": "alpine", "volumes": [f"{tmp_path}:/host"]}
            },
        }
    )
    project = await ComposeProject.create(
        name=task_project_name("mount-opt-in"), config=config
    )
    try:
        if allow is True:
            assert "default" in await compose_services(project)
        else:
            with pytest.raises(PrerequisiteError):
                await compose_services(project)
    finally:
        assert project.config is not None
        Path(project.config).unlink()


@skip_if_no_docker
async def test_mount_policy_uses_resolved_sample_metadata(
    tmp_path: Path, mount_daemon: dict[str, Any]
) -> None:
    config = tmp_path / "compose.yaml"
    config.write_text(
        "services:\n  default:\n    image: alpine\n    volumes:\n      - ./data:/data:${SAMPLE_METADATA_MOUNT_MODE:-ro}\n"
    )
    for mode in ["ro", "rw"]:
        project = await ComposeProject.create(
            name="inspect-sample-mount",
            config=str(config),
            env={"SAMPLE_METADATA_MOUNT_MODE": mode},
        )
        if mode == "ro":
            assert "default" in await compose_services(project)
        else:
            with pytest.raises(PrerequisiteError, match="writable host bind"):
                await compose_services(project)


async def test_mount_validation_cancellation_cleans_up(
    tmp_path: Path, read_only_bind: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = anyio.Event()
    cleaned: list[ComposeProject] = []

    async def compose_config(*args: Any, **kwargs: Any) -> ExecResult[str]:
        assert args[0] == ["config"]
        return ExecResult(
            success=True, returncode=0, stdout=yaml.safe_dump(read_only_bind), stderr=""
        )

    async def docker_info(*args: Any, **kwargs: Any) -> ExecResult[str]:
        ready.set()
        await anyio.sleep_forever()
        raise AssertionError("cancelled validation returned")

    async def cleanup(project: ComposeProject, quiet: bool) -> None:
        cleaned.append(project)

    monkeypatch.setattr(compose_module, "compose_command", compose_config)
    monkeypatch.setattr(mounts_module, "subprocess", docker_info)
    monkeypatch.setattr(docker_module, "project_cleanup", cleanup)
    monkeypatch.setattr(docker_module, "project_startup", lambda project: None)
    config = tmp_path / "compose.yaml"
    config.write_text(yaml.safe_dump(read_only_bind))

    with anyio.CancelScope() as scope:

        async def cancel_when_validating() -> None:
            await ready.wait()
            scope.cancel()

        async with anyio.create_task_group() as tg:
            tg.start_soon(cancel_when_validating)
            await DockerSandboxEnvironment.sample_init("cancel-mount", str(config), {})
    assert scope.cancel_called
    assert len(cleaned) == 1


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("attack", ["compose", "symlink"])
async def test_host_mount_attacks_require_opt_in(attack: str, tmp_path: Path) -> None:
    """Reproduce both reports using only temporary host files and containers."""
    root = tmp_path.resolve()
    exposed = root / "exposed"
    exposed.mkdir()
    private = root / "private"
    private.mkdir()
    (private / "sentinel").write_text("private")
    (exposed / "data").mkdir()
    config_file = exposed / "compose.yaml"
    config: dict[str, Any] = {
        "services": {
            "default": {
                "image": "aisiuk/inspect-tool-support",
                "command": ["sleep", "infinity"],
                "network_mode": "none",
                "volumes": [f"{exposed}:/host", f"{exposed / 'data'}:/data:ro"],
            }
        }
    }
    config_file.write_text(yaml.safe_dump(config))
    rejected = await ComposeProject.create(
        name=task_project_name("blocked-mount"), config=str(config_file)
    )
    with pytest.raises(PrerequisiteError, match="writable host bind"):
        await compose_services(rejected)
    assert (private / "sentinel").read_text() == "private"

    config["x-inspect_docker_sandbox"] = {"unsafe_allow_writable_host_mounts": True}
    config_file.write_text(yaml.safe_dump(config))
    first = await ComposeProject.create(
        name=task_project_name("unsafe-mount"), config=str(config_file)
    )
    second = await ComposeProject.create(
        name=task_project_name("later-mount"), config=str(config_file)
    )
    try:
        await compose_up(first, await compose_services(first))
        if attack == "compose":
            modified = {
                **config,
                "services": {
                    "default": {
                        **config["services"]["default"],
                        "volumes": [f"{private}:/data:ro"],
                    }
                },
            }
            result = await compose_exec(
                ["-T", "default", "sh", "-c", "cat > /host/compose.yaml"],
                project=first,
                timeout=30,
                input=yaml.safe_dump(modified),
            )
        else:
            result = await compose_exec(
                [
                    "-T",
                    "default",
                    "sh",
                    "-c",
                    'rmdir /host/data && ln -s "$1" /host/data',
                    "sh",
                    str(private),
                ],
                project=first,
                timeout=30,
            )
        assert result.success, result.stderr
        await compose_up(second, await compose_services(second))
        result = await compose_exec(
            ["-T", "default", "cat", "/data/sentinel"], project=second, timeout=30
        )
        assert result.success, result.stderr
        assert result.stdout == "private"
    finally:
        await compose_down(second)
        await compose_down(first)


@skip_if_no_docker
@pytest.mark.slow
async def test_read_only_host_and_managed_volume_runtime(tmp_path: Path) -> None:
    (tmp_path / "sentinel").write_text("input")
    config = ComposeConfig.model_validate(
        {
            "services": {
                "default": {
                    "image": "aisiuk/inspect-tool-support",
                    "command": ["sleep", "infinity"],
                    "network_mode": "none",
                    "volumes": [f"{tmp_path.resolve()}:/input:ro", "output:/output"],
                }
            },
            "volumes": {"output": {}},
        }
    )
    project = await ComposeProject.create(
        name=task_project_name("safe-mounts"), config=config
    )
    try:
        await compose_up(project, await compose_services(project))
        result = await compose_exec(
            ["-T", "default", "cat", "/input/sentinel"], project=project, timeout=30
        )
        assert result.success and result.stdout == "input"
        result = await compose_exec(
            ["-T", "default", "touch", "/input/new"], project=project, timeout=30
        )
        assert not result.success
        assert not (tmp_path / "new").exists()
        result = await compose_exec(
            ["-T", "default", "touch", "/output/new"], project=project, timeout=30
        )
        assert result.success, result.stderr
    finally:
        await compose_down(project)
        assert project.config is not None
        Path(project.config).unlink()


@skip_if_no_docker
@pytest.mark.slow
async def test_docker_sandbox_with_compose_config(request) -> None:
    """Test that DockerSandboxEnvironment works with ComposeConfig objects."""
    task_name = f"{__name__}_{request.node.name}"

    config = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    await DockerSandboxEnvironment.task_init(task_name=task_name, config=config)
    envs_dict = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=config, metadata={}
    )

    try:
        sandbox_env = envs_dict["default"]

        # Verify we can execute commands in the sandbox
        result = await sandbox_env.exec(["echo", "hello"])
        assert result.success
        assert result.stdout.strip() == "hello"
    finally:
        await DockerSandboxEnvironment.sample_cleanup(
            task_name=task_name,
            config=config,
            environments=envs_dict,
            interrupted=False,
        )
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=config, cleanup=True
        )


@skip_if_no_docker
async def test_compose_config_hashable():
    """Test that ComposeConfig is hashable and can be used in sets."""
    config1 = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    config2 = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    config3 = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.13-bookworm",  # Different image
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    # Test hashability
    hash1 = hash(config1)
    hash2 = hash(config2)
    hash3 = hash(config3)

    # Same content should have same hash
    assert hash1 == hash2
    # Different content should have different hash
    assert hash1 != hash3

    # Test equality
    assert config1 == config2
    assert config1 != config3

    # Test use in set
    config_set = {config1, config2, config3}
    assert len(config_set) == 2  # config1 and config2 are equal


@skip_if_no_docker
async def test_compose_config_with_extensions(request) -> None:
    """Test that ComposeConfig preserves x- extension fields."""
    task_name = f"{__name__}_{request.node.name}"

    # Create a ComposeService with x-default extension
    service = ComposeService(
        image="python:3.12-bookworm",
        init=True,
        command="tail -f /dev/null",
        network_mode="none",
        **{"x-default": True},  # type: ignore
    )

    config = ComposeConfig(services={"myservice": service})
    project = await ComposeProject.create(name=task_name, config=config)

    try:
        # Verify the generated YAML contains the x-default extension
        # The field is serialized with its alias "x-default" due to by_alias=True
        with open(project.config, "r") as f:  # type: ignore
            content = f.read()
            # Check that x-default is present
            assert "x-default: true" in content
    finally:
        if project.config and os.path.exists(project.config):
            os.unlink(project.config)
