from inspect_ai.model import modelapi

from .toolenv.podman import PodmanToolEnvironment  # noqa: F401


@modelapi(name="custom")
def custom():
    # delayed import allows us to only resolve the imports in
    # .modelapi.custom when the modelapi is referenced (helpful
    # if the modelapi provider has dependencies we don't want to
    # require unless the provider is actually used)
    from .modelapi.custom import CustomModelAPI

    return CustomModelAPI
