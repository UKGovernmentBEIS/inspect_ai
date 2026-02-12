"""Tests for Docker compatibility functionality in sandbox environments."""

import pytest

from inspect_ai.util._sandbox.compose import (
    ComposeConfig,
    ComposeService,
    is_docker_compatible_config,
    is_docker_compatible_sandbox_type,
    is_dockerfile,
)
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentSpec,
    deserialize_sandbox_specific_config,
)
from inspect_ai.util._sandbox.registry import sandboxenv

# --- Test fixtures: mock sandbox environments ---


@sandboxenv(name="mock_docker_compatible")
class MockDockerCompatibleSandbox(SandboxEnvironment):
    """Mock sandbox that explicitly declares docker compatibility."""

    @classmethod
    def config_files(cls) -> list[str]:
        return ["custom.yaml"]

    @classmethod
    def is_docker_compatible(cls) -> bool:
        return True

    async def exec(self, cmd, **kwargs):
        raise NotImplementedError

    async def write_file(self, file, contents):
        raise NotImplementedError

    async def read_file(self, file, text=True):
        raise NotImplementedError

    @classmethod
    async def sample_cleanup(cls, task_name, config, environments, interrupted):
        pass


@sandboxenv(name="mock_not_docker_compatible")
class MockNotDockerCompatibleSandbox(SandboxEnvironment):
    """Mock sandbox that explicitly declares it is NOT docker compatible."""

    @classmethod
    def config_files(cls) -> list[str]:
        return ["custom.yaml"]

    @classmethod
    def is_docker_compatible(cls) -> bool:
        return False

    async def exec(self, cmd, **kwargs):
        raise NotImplementedError

    async def write_file(self, file, contents):
        raise NotImplementedError

    async def read_file(self, file, text=True):
        raise NotImplementedError

    @classmethod
    async def sample_cleanup(cls, task_name, config, environments, interrupted):
        pass


@sandboxenv(name="mock_compose_implicit")
class MockComposeImplicitSandbox(SandboxEnvironment):
    """Mock sandbox with compose.yaml in config_files (implicitly docker compatible)."""

    @classmethod
    def config_files(cls) -> list[str]:
        return ["compose.yaml", "custom.yaml"]

    async def exec(self, cmd, **kwargs):
        raise NotImplementedError

    async def write_file(self, file, contents):
        raise NotImplementedError

    async def read_file(self, file, text=True):
        raise NotImplementedError

    @classmethod
    async def sample_cleanup(cls, task_name, config, environments, interrupted):
        pass


@sandboxenv(name="mock_no_compose")
class MockNoComposeSandbox(SandboxEnvironment):
    """Mock sandbox without compose.yaml in config_files (implicitly NOT compatible)."""

    @classmethod
    def config_files(cls) -> list[str]:
        return ["custom.yaml"]

    async def exec(self, cmd, **kwargs):
        raise NotImplementedError

    async def write_file(self, file, contents):
        raise NotImplementedError

    async def read_file(self, file, text=True):
        raise NotImplementedError

    @classmethod
    async def sample_cleanup(cls, task_name, config, environments, interrupted):
        pass


# --- Tests for is_docker_compatible() default behavior ---


class TestSandboxEnvironmentIsDockerCompatible:
    """Test the is_docker_compatible() method on SandboxEnvironment."""

    def test_explicit_docker_compatible_true(self):
        """Sandbox explicitly returning True should be docker compatible."""
        assert MockDockerCompatibleSandbox.is_docker_compatible() is True

    def test_explicit_docker_compatible_false(self):
        """Sandbox explicitly returning False should NOT be docker compatible."""
        assert MockNotDockerCompatibleSandbox.is_docker_compatible() is False

    def test_implicit_compatible_via_compose_yaml(self):
        """Sandbox with compose.yaml in config_files should be implicitly compatible."""
        assert MockComposeImplicitSandbox.is_docker_compatible() is True

    def test_implicit_not_compatible_no_compose(self):
        """Sandbox without compose.yaml in config_files should NOT be compatible."""
        assert MockNoComposeSandbox.is_docker_compatible() is False


# --- Tests for is_docker_compatible_config() ---


class TestIsDockerCompatibleConfig:
    """Test the is_docker_compatible_config() function."""

    @pytest.mark.parametrize(
        "config",
        [
            "Dockerfile",
            "/path/to/Dockerfile",
            "name.Dockerfile",
            "/path/to/name.Dockerfile",
            "Dockerfile.custom",
            "/path/to/Dockerfile.custom",
        ],
    )
    def test_dockerfile_paths_are_compatible(self, config: str):
        """Dockerfile paths should be docker compatible."""
        assert is_docker_compatible_config(config) is True

    @pytest.mark.parametrize(
        "config",
        [
            "compose.yaml",
            "compose.yml",
            "docker-compose.yaml",
            "docker-compose.yml",
            "/path/to/compose.yaml",
            "/path/to/docker-compose.yaml",
            ".compose.yaml",
            "foo-compose.yaml",
            "/path/to/my-project-compose.yaml",
        ],
    )
    def test_compose_yaml_paths_are_compatible(self, config: str):
        """Compose YAML paths should be docker compatible."""
        assert is_docker_compatible_config(config) is True

    def test_compose_config_instance_is_compatible(self):
        """ComposeConfig instances should be docker compatible."""
        config = ComposeConfig(
            services={"default": ComposeService(image="ubuntu")},
        )
        assert is_docker_compatible_config(config) is True

    @pytest.mark.parametrize(
        "config",
        [
            "custom.yaml",
            "/path/to/config.json",
            "settings.toml",
            "mycompose.yaml",  # no separator before "compose"
            "compose-foo.yaml",  # compose not at end
        ],
    )
    def test_non_docker_configs_are_not_compatible(self, config: str):
        """Non-docker config paths should NOT be docker compatible."""
        assert is_docker_compatible_config(config) is False

    def test_none_config_is_not_compatible(self):
        """None config should NOT be docker compatible."""
        assert is_docker_compatible_config(None) is False

    def test_non_compose_basemodel_is_not_compatible(self) -> None:
        """Non-ComposeConfig BaseModel should NOT be docker compatible."""
        from pydantic import BaseModel

        class CustomConfig(BaseModel):
            value: str

        config = CustomConfig(value="test")
        assert is_docker_compatible_config(config) is False


# --- Tests for is_docker_compatible_sandbox_type() ---


class TestIsDockerCompatibleSandboxType:
    """Test the is_docker_compatible_sandbox_type() function."""

    def test_with_class_explicit_compatible(self):
        """Should return True for class that explicitly declares compatibility."""
        assert is_docker_compatible_sandbox_type(MockDockerCompatibleSandbox) is True

    def test_with_class_explicit_not_compatible(self):
        """Should return False for class that explicitly declares incompatibility."""
        assert (
            is_docker_compatible_sandbox_type(MockNotDockerCompatibleSandbox) is False
        )

    def test_with_class_implicit_compatible(self):
        """Should return True for class with compose.yaml in config_files."""
        assert is_docker_compatible_sandbox_type(MockComposeImplicitSandbox) is True

    def test_with_class_implicit_not_compatible(self):
        """Should return False for class without compose.yaml in config_files."""
        assert is_docker_compatible_sandbox_type(MockNoComposeSandbox) is False

    def test_with_string_explicit_compatible(self):
        """Should return True for string name of compatible sandbox."""
        assert is_docker_compatible_sandbox_type("mock_docker_compatible") is True

    def test_with_string_explicit_not_compatible(self):
        """Should return False for string name of incompatible sandbox."""
        assert is_docker_compatible_sandbox_type("mock_not_docker_compatible") is False

    def test_with_string_implicit_compatible(self):
        """Should return True for string name with compose.yaml in config_files."""
        assert is_docker_compatible_sandbox_type("mock_compose_implicit") is True

    def test_with_string_implicit_not_compatible(self):
        """Should return False for string name without compose.yaml."""
        assert is_docker_compatible_sandbox_type("mock_no_compose") is False

    def test_with_builtin_docker_sandbox(self):
        """Built-in docker sandbox should be docker compatible."""
        assert is_docker_compatible_sandbox_type("docker") is True

    def test_with_invalid_string_raises_error(self):
        """Should raise ValueError for unknown sandbox type."""
        with pytest.raises(ValueError, match="not recognized"):
            is_docker_compatible_sandbox_type("nonexistent_sandbox_type")


# --- Tests for is_dockerfile() with various input types ---


class TestIsDockerfileTypeGuard:
    """Test is_dockerfile() TypeGuard behavior with various input types."""

    def test_with_valid_dockerfile_string(self):
        """Should return True for valid Dockerfile paths."""
        assert is_dockerfile("Dockerfile") is True
        assert is_dockerfile("/path/to/Dockerfile") is True

    def test_with_non_dockerfile_string(self):
        """Should return False for non-Dockerfile paths."""
        assert is_dockerfile("compose.yaml") is False

    def test_with_none(self):
        """Should return False for None."""
        assert is_dockerfile(None) is False

    def test_with_non_string(self):
        """Should return False for non-string types."""
        assert is_dockerfile(123) is False
        assert is_dockerfile(["Dockerfile"]) is False
        assert is_dockerfile({"path": "Dockerfile"}) is False


# --- Integration tests for resolve_sandbox() ---


class TestResolveSandboxDockerCompatibility:
    """Test resolve_sandbox() behavior with docker-compatible configs."""

    @pytest.mark.asyncio
    async def test_sample_compose_yaml_forwarded_to_docker_compatible_task(self):
        """Sample's compose.yaml config should be used when task sandbox is docker-compatible."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        # Task uses docker-compatible sandbox with its own config
        task_sandbox = SandboxEnvironmentSpec(
            "mock_docker_compatible", "task-config.yaml"
        )

        # Sample has compose.yaml config (docker-compatible)
        sample = Sample(
            input="test",
            sandbox=("docker", "compose.yaml"),  # sample's compose.yaml
        )

        result = await resolve_sandbox(task_sandbox, sample)

        # Sample's compose.yaml should be forwarded because task sandbox is docker-compatible
        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config == "compose.yaml"

    @pytest.mark.asyncio
    async def test_sample_dockerfile_forwarded_to_docker_compatible_task(self):
        """Sample's Dockerfile config should be used when task sandbox is docker-compatible."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        task_sandbox = SandboxEnvironmentSpec(
            "mock_docker_compatible", "task-config.yaml"
        )
        sample = Sample(
            input="test",
            sandbox=("docker", "Dockerfile"),
        )

        result = await resolve_sandbox(task_sandbox, sample)

        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config == "Dockerfile"

    @pytest.mark.asyncio
    async def test_sample_compose_config_forwarded_to_docker_compatible_task(self):
        """Sample's ComposeConfig should be used when task sandbox is docker-compatible."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        task_sandbox = SandboxEnvironmentSpec(
            "mock_docker_compatible", "task-config.yaml"
        )

        compose_config = ComposeConfig(
            services={"default": ComposeService(image="python:3.11")},
        )
        sample = Sample(
            input="test",
            sandbox=SandboxEnvironmentSpec("docker", compose_config),
        )

        result = await resolve_sandbox(task_sandbox, sample)

        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config == compose_config

    @pytest.mark.asyncio
    async def test_sample_compose_not_forwarded_to_non_docker_compatible_task(self):
        """Sample's compose.yaml should NOT be forwarded when task sandbox is NOT docker-compatible."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        # Task uses non-docker-compatible sandbox
        task_sandbox = SandboxEnvironmentSpec(
            "mock_not_docker_compatible", "task-config.yaml"
        )
        sample = Sample(
            input="test",
            sandbox=("docker", "compose.yaml"),
        )

        result = await resolve_sandbox(task_sandbox, sample)

        # Task's config should be used, not sample's compose.yaml
        assert result is not None
        assert result.type == "mock_not_docker_compatible"
        assert result.config == "task-config.yaml"

    @pytest.mark.asyncio
    async def test_sample_non_docker_config_not_forwarded(self):
        """Sample's non-docker config should NOT be forwarded even to docker-compatible task."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        task_sandbox = SandboxEnvironmentSpec(
            "mock_docker_compatible", "task-config.yaml"
        )
        sample = Sample(
            input="test",
            sandbox=("other_provider", "custom.yaml"),  # not docker-compatible config
        )

        result = await resolve_sandbox(task_sandbox, sample)

        # Task's config should be used, not sample's non-docker config
        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config == "task-config.yaml"

    @pytest.mark.asyncio
    async def test_same_type_config_always_forwarded(self):
        """Sample config should be forwarded when types match, regardless of docker compatibility."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        # Both task and sample use same type
        task_sandbox = SandboxEnvironmentSpec(
            "mock_not_docker_compatible", "task-config.yaml"
        )
        sample = Sample(
            input="test",
            sandbox=("mock_not_docker_compatible", "sample-config.yaml"),
        )

        result = await resolve_sandbox(task_sandbox, sample)

        # Sample's config should be used because types match
        assert result is not None
        assert result.type == "mock_not_docker_compatible"
        assert result.config == "sample-config.yaml"

    @pytest.mark.asyncio
    async def test_no_sample_sandbox_uses_task_sandbox(self):
        """When sample has no sandbox, task sandbox should be used."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        task_sandbox = SandboxEnvironmentSpec(
            "mock_docker_compatible", "task-config.yaml"
        )
        sample = Sample(input="test")  # no sandbox

        result = await resolve_sandbox(task_sandbox, sample)

        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config == "task-config.yaml"

    @pytest.mark.asyncio
    async def test_no_task_sandbox_uses_sample_sandbox(self):
        """When task has no sandbox, sample sandbox should be used."""
        from inspect_ai._eval.task.sandbox import resolve_sandbox
        from inspect_ai.dataset import Sample

        sample = Sample(
            input="test",
            sandbox=("mock_docker_compatible", "sample-config.yaml"),
        )

        result = await resolve_sandbox(None, sample)

        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config == "sample-config.yaml"


# --- Integration tests for resolve_task_sandbox() ---


class TestResolveTaskSandboxDockerCompatibility:
    """Test resolve_task_sandbox() behavior with docker-compatible configs."""

    def test_task_compose_forwarded_to_docker_compatible_override(self, tmp_path):
        """Task's compose.yaml should be forwarded when override sandbox is docker-compatible with no config."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        # Create a task with compose.yaml config (use None for dataset to get a dummy sample)
        task = Task(
            dataset=None,
            sandbox=("docker", "compose.yaml"),
        )
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        # Override with docker-compatible sandbox (no config)
        result = resolve_task_sandbox(task, "mock_docker_compatible")

        assert result is not None
        assert result.type == "mock_docker_compatible"
        # config path gets resolved to absolute path
        assert result.config is not None
        assert "compose.yaml" in result.config

    def test_task_dockerfile_forwarded_to_docker_compatible_override(self, tmp_path):
        """Task's Dockerfile should be forwarded when override sandbox is docker-compatible with no config."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        task = Task(
            dataset=None,
            sandbox=("docker", "Dockerfile"),
        )
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        result = resolve_task_sandbox(task, "mock_docker_compatible")

        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config is not None
        assert "Dockerfile" in result.config

    def test_task_compose_not_forwarded_to_non_docker_compatible_override(
        self, tmp_path
    ):
        """Task's compose.yaml should NOT be forwarded when override sandbox is NOT docker-compatible."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        task = Task(
            dataset=None,
            sandbox=("docker", "compose.yaml"),
        )
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        # Override with non-docker-compatible sandbox (no config)
        result = resolve_task_sandbox(task, "mock_not_docker_compatible")

        assert result is not None
        assert result.type == "mock_not_docker_compatible"
        # Config should NOT be forwarded
        assert result.config is None

    def test_task_non_docker_config_not_forwarded(self, tmp_path):
        """Task's non-docker config should NOT be forwarded even to docker-compatible override."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        task = Task(
            dataset=None,
            sandbox=("other", "custom.yaml"),  # not docker-compatible config
        )
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        result = resolve_task_sandbox(task, "mock_docker_compatible")

        assert result is not None
        assert result.type == "mock_docker_compatible"
        # Non-docker config should NOT be forwarded
        assert result.config is None

    def test_override_with_config_not_overridden(self, tmp_path):
        """Override sandbox with its own config should NOT use task's config."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        task = Task(
            dataset=None,
            sandbox=("docker", "compose.yaml"),
        )
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        # Override with its own config
        override = SandboxEnvironmentSpec(
            "mock_docker_compatible", "override-config.yaml"
        )

        result = resolve_task_sandbox(task, override)

        assert result is not None
        assert result.type == "mock_docker_compatible"
        # Override's config should be used (path resolved)
        assert result.config is not None
        assert "override-config.yaml" in result.config

    def test_compose_config_object_forwarded(self, tmp_path):
        """ComposeConfig object should be forwarded to docker-compatible override."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        compose_config = ComposeConfig(
            services={"default": ComposeService(image="python:3.11")},
        )
        task = Task(
            dataset=None,
            sandbox=SandboxEnvironmentSpec("docker", compose_config),
        )
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        result = resolve_task_sandbox(task, "mock_docker_compatible")

        assert result is not None
        assert result.type == "mock_docker_compatible"
        # ComposeConfig should be forwarded
        assert result.config == compose_config

    def test_no_task_sandbox_uses_override(self, tmp_path):
        """When task has no sandbox, override should be used as-is."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        task = Task(dataset=None)  # no sandbox
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        result = resolve_task_sandbox(task, "mock_docker_compatible")

        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config is None

    def test_no_override_uses_task_sandbox(self, tmp_path):
        """When there is no override, task sandbox should be used."""
        from inspect_ai._eval.loader import resolve_task_sandbox
        from inspect_ai._eval.task.constants import TASK_RUN_DIR_ATTR
        from inspect_ai._eval.task.task import Task

        task = Task(
            dataset=None,
            sandbox=("mock_docker_compatible", "task-config.yaml"),
        )
        setattr(task, TASK_RUN_DIR_ATTR, str(tmp_path))

        result = resolve_task_sandbox(task, None)

        assert result is not None
        assert result.type == "mock_docker_compatible"
        assert result.config is not None
        assert "task-config.yaml" in result.config


# --- Tests for deserialize_sandbox_specific_config() ---


class TestDeserializeSandboxSpecificConfig:
    """Test auto-deserialization of ComposeConfig for docker-compatible providers."""

    def test_compose_config_auto_deserialized_for_docker_compatible(self):
        """ComposeConfig dict should auto-deserialize for docker-compatible providers."""
        config_dict = {
            "services": {"default": {"image": "python:3.11"}},
        }
        result = deserialize_sandbox_specific_config(
            "mock_docker_compatible", config_dict
        )
        assert isinstance(result, ComposeConfig)
        assert "default" in result.services

    def test_non_compose_config_falls_through_to_config_deserialize(self):
        """Non-ComposeConfig dict should fall through to provider's config_deserialize."""
        config_dict = {"not_services": "something"}
        # MockDockerCompatibleSandbox doesn't implement config_deserialize,
        # so this should raise NotImplementedError
        with pytest.raises(NotImplementedError):
            deserialize_sandbox_specific_config("mock_docker_compatible", config_dict)

    def test_non_docker_compatible_uses_config_deserialize(self):
        """Non-docker-compatible providers should use config_deserialize even for compose-like dicts."""
        config_dict = {
            "services": {"default": {"image": "python:3.11"}},
        }
        # MockNotDockerCompatibleSandbox doesn't implement config_deserialize
        with pytest.raises(NotImplementedError):
            deserialize_sandbox_specific_config(
                "mock_not_docker_compatible", config_dict
            )

    def test_docker_provider_still_works(self):
        """Built-in docker provider should still deserialize ComposeConfig correctly."""
        config_dict = {
            "services": {"default": {"image": "ubuntu:latest"}},
        }
        result = deserialize_sandbox_specific_config("docker", config_dict)
        assert isinstance(result, ComposeConfig)
        assert "default" in result.services
