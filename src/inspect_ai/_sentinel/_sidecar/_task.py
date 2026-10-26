"""The sentinel sidecars a task's agent calls go through, found by probing each model's proxy."""

from contextvars import ContextVar

import anyio

from inspect_ai.model._model import Model, ModelAPI

from .._config import SentinelProxy
from ._endpoint import (
    SentinelProxyError,
    Sidecar,
    probe,
    proxy_client,
)

_NOT_PROBED = (
    "its base URL was not set, or its provider's calls aren't ones a sidecar reads"
)


class TaskSidecars:
    """The sidecars of one task's endpoints, each probed once per endpoint and credentials.

    Models are shared between tasks, so what is found lives with the task, not with the model.
    """

    def __init__(self, mode: SentinelProxy) -> None:
        self.mode: SentinelProxy = mode
        self._found: dict[tuple[str, str | None], Sidecar | str] = {}
        self._probing: dict[tuple[str, str | None], anyio.Event] = {}

    async def start(self, model: Model) -> None:
        """Probe the endpoint of the task's assigned model, before any sample runs.

        Raises:
            SentinelProxyError: If the mode is `required` and no sidecar Inspect supports answered, or a sidecar answered that Inspect can't work with.
        """
        found = await self._probe(model.api)
        if self.mode == "required" and not isinstance(found, Sidecar):
            raise SentinelProxyError(
                f"A sentinel sidecar is required (--sentinel-proxy required), and none was found for {model}: {found}."
            )

    async def sidecar(self, api: ModelAPI) -> Sidecar | None:
        """The sidecar behind a model's endpoint, probing it the first time it is asked of."""
        found = await self._probe(api)
        return found if isinstance(found, Sidecar) else None

    async def _probe(self, api: ModelAPI) -> Sidecar | str:
        client = proxy_client(api)
        if client is None:
            return _NOT_PROBED
        key = (client.base_url, api.api_key)
        if key in self._found:
            return self._found[key]

        # samples asking at once wait for the first probe, rather than each probing
        probing = self._probing.get(key)
        if probing is not None:
            await probing.wait()
            return self._found.get(key, _NOT_PROBED)
        self._probing[key] = anyio.Event()
        try:
            self._found[key] = await probe(client)
        finally:
            self._probing.pop(key).set()
        return self._found[key]


_task_sidecars: ContextVar[TaskSidecars | None] = ContextVar(
    "task_sidecars", default=None
)


async def init_task_sidecars(mode: SentinelProxy | None, model: Model) -> None:
    """Find the sidecar behind the task's assigned model, for the samples the task runs.

    Raises:
        SentinelProxyError: If the task can't run with the sidecars it finds.
    """
    if mode == "off":
        _task_sidecars.set(None)
        return
    sidecars = TaskSidecars(mode or "auto")
    await sidecars.start(model)
    _task_sidecars.set(sidecars)


def task_sidecars() -> TaskSidecars | None:
    return _task_sidecars.get()
