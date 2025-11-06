from typing import Any

from typing_extensions import override

from pydantic import BaseModel

from ..registry import sandboxenv
from .docker import DockerSandboxEnvironment

class DockerReuseConfig(BaseModel, frozen=True):
    reuse : str

@sandboxenv(name="docker.reuse")
class DockerReuseSandboxEnvironment(DockerSandboxEnvironment):
    @override
    @classmethod
    def is_reuse_sandbox(cls) -> bool:
        return True

    @override
    @classmethod
    def get_compose_project_name(cls, config, task_name) -> str:
        return config.reuse

    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        return DockerReuseConfig(reuse=config["reuse"])
