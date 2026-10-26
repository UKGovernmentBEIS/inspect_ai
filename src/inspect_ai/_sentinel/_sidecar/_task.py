"""The sentinel sidecars a task's agent calls go through, found by probing each model's proxy."""

from collections.abc import Awaitable, Callable, Hashable
from contextvars import ContextVar
from typing import Any, Generic, NamedTuple, TypeVar

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai.model._model import Model, ModelAPI

from .._config import SentinelProxy
from ._endpoint import (
    SentinelProxyError,
    Sidecar,
    SidecarCallError,
    probe,
    proxy_client,
)

REGISTRATION_REFUSED = -32001

_NOT_PROBED = (
    "its base URL was not set, or its provider's calls aren't ones a sidecar reads"
)

T = TypeVar("T")


class TaskFacts(NamedTuple):
    """What a task registers with each sidecar its agent calls go through."""

    eval_id: str
    task: str
    task_description: str | None
    metadata: dict[str, Any]
    sample_ids: list[str | int]
    epochs: int


class SampleFacts(NamedTuple):
    """What a sample registers with each sidecar its agent calls go through, as its sentinel is given it in process."""

    sample_id: str | int
    sample_description: str | None
    sample_input: Any
    metadata: dict[str, Any]


class TaskSidecars:
    """The sidecars of one task's endpoints, each probed and registered once per endpoint and credentials.

    Models are shared between tasks, so what is found lives with the task, not with the model.
    """

    def __init__(self, mode: SentinelProxy, facts: TaskFacts) -> None:
        self.mode: SentinelProxy = mode
        self.facts = facts
        self._found = _Once[Sidecar | str]()
        self._completed = _Once[None]()

    async def start(self, model: Model) -> None:
        """Probe the endpoint of the task's assigned model, and register the task with a sidecar found there, before any sample runs.

        Raises:
            SentinelProxyError: If the mode is `required` and no sidecar Inspect supports answered, a sidecar answered that Inspect can't work with, or the task couldn't be registered.
        """
        found = await self._probe(model.api)
        if self.mode == "required" and not isinstance(found, Sidecar):
            raise SentinelProxyError(
                f"A sentinel sidecar is required (--sentinel-proxy required), and none was found for {model}: {found}."
            )

    async def sidecar(self, api: ModelAPI) -> Sidecar | None:
        """The sidecar behind a model's endpoint, probing it and registering the task the first time it is asked of."""
        found = await self._probe(api)
        return found if isinstance(found, Sidecar) else None

    async def complete_registration(
        self, sidecar: Sidecar, sample: SampleFacts
    ) -> None:
        """Send a sample's facts to a sidecar, once for the sample whatever its epochs, before the sidecar judges any of its calls.

        Raises:
            SentinelProxyError: If the sidecar couldn't take the sample.
        """

        async def complete() -> None:
            params = {
                "eval_id": self.facts.eval_id,
                "task": self.facts.task,
                "sample_id": sample.sample_id,
                "sample_description": sample.sample_description,
                "sample_input": to_jsonable_python(
                    sample.sample_input, exclude_none=True
                ),
                "metadata": to_jsonable_python(sample.metadata),
            }
            try:
                await sidecar.call("complete_registration", params)
            except SidecarCallError as ex:
                raise SentinelProxyError(
                    f"The sentinel sidecar at {sidecar.origin} couldn't register the sample {sample.sample_id!r} of the task {self.facts.task!r}: {ex}"
                ) from ex

        await self._completed.run((sidecar.origin, sample.sample_id), complete)

    async def _probe(self, api: ModelAPI) -> Sidecar | str:
        client = proxy_client(api)
        if client is None:
            return _NOT_PROBED

        async def probe_and_register() -> Sidecar | str:
            found = await probe(client)
            if isinstance(found, Sidecar):
                await self._register(found)
            return found

        return await self._found.run((client.base_url, api.api_key), probe_and_register)

    async def _register(self, sidecar: Sidecar) -> None:
        facts = self.facts
        params = {
            "eval_id": facts.eval_id,
            "task": facts.task,
            "task_description": facts.task_description,
            "metadata": to_jsonable_python(facts.metadata),
            "sample_ids": facts.sample_ids,
            "epochs": facts.epochs,
        }
        try:
            await sidecar.call("register_task", params)
        except SidecarCallError as ex:
            if ex.code == REGISTRATION_REFUSED:
                raise SentinelProxyError(
                    f"The sentinel sidecar at {sidecar.origin} runs only the tasks its admin registered, and the task {facts.task!r} isn't one."
                ) from ex
            raise SentinelProxyError(
                f"The sentinel sidecar at {sidecar.origin} couldn't register the task {facts.task!r}: {ex}"
            ) from ex


class _Once(Generic[T]):
    # each key's work runs once: callers asking meanwhile wait for it, and
    # work that raised is tried again by the next caller
    def __init__(self) -> None:
        self._done: dict[Hashable, T] = {}
        self._running: dict[Hashable, anyio.Event] = {}

    async def run(self, key: Hashable, work: Callable[[], Awaitable[T]]) -> T:
        while key not in self._done:
            running = self._running.get(key)
            if running is not None:
                await running.wait()
                continue
            self._running[key] = anyio.Event()
            try:
                self._done[key] = await work()
            finally:
                self._running.pop(key).set()
        return self._done[key]


_task_sidecars: ContextVar[TaskSidecars | None] = ContextVar(
    "task_sidecars", default=None
)


async def init_task_sidecars(
    mode: SentinelProxy | None, model: Model, facts: TaskFacts
) -> None:
    """Find the sidecar behind the task's assigned model, and register the task with it, for the samples the task runs.

    Raises:
        SentinelProxyError: If the task can't run with the sidecars it finds.
    """
    if mode == "off":
        _task_sidecars.set(None)
        return
    sidecars = TaskSidecars(mode or "auto", facts)
    await sidecars.start(model)
    _task_sidecars.set(sidecars)


def task_sidecars() -> TaskSidecars | None:
    return _task_sidecars.get()
