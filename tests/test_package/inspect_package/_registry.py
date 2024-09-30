from inspect_ai.model import modelapi
from inspect_ai.util import sandboxenv

from .solvers.cot import cot  # noqa: F401

# delayed import for the model and sandbox allows us to only resolve the imports
# when they are actually requeasted (so that we don't end up requiring all
# of their dependencies when this package's entry points are loaded)


@modelapi(name="custom")
def custom():
    from .modelapi.custom import CustomModelAPI

    return CustomModelAPI


@sandboxenv(name="podman")
def podman():
    from .sandboxenv.podman import PodmanSandboxEnvironment

    return PodmanSandboxEnvironment
