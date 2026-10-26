"""The sentinel sidecars a task's agent calls go through, found by probing each model's proxy."""

from collections.abc import Awaitable, Callable, Hashable
from contextvars import ContextVar
from logging import getLogger
from typing import Any, Generic, NamedTuple, TypeVar
from weakref import WeakValueDictionary

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai.model._model import Model, ModelAPI
from inspect_ai.util._store import Store

from .._config import SentinelProxy
from ._endpoint import (
    CALL_TIMEOUT,
    SentinelProxyError,
    Sidecar,
    SidecarCallError,
    probe,
    proxy_client,
)

REGISTRATION_REFUSED = -32001

END_SAMPLE_TIMEOUT = 10.0

UNKNOWN_SAMPLE = -32002
METHOD_NOT_FOUND = -32601

MONITOR_STATE_COPY = "sentinel_sidecar:monitor_state"
"""The sample store's marker of the latest copy of monitor state from the sidecars: whether it succeeded, and why not."""

logger = getLogger(__name__)

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
        # the sidecars each sample's calls went through, by the sample's uuid
        self._through: dict[str, dict[str, Sidecar]] = {}

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

    def called_through(self, sample_uuid: str, sidecar: Sidecar) -> None:
        """Note that a sample's call went through a sidecar, which is told when the sample ends."""
        self._through.setdefault(sample_uuid, {})[sidecar.origin] = sidecar

    async def end_sample(self, sample_uuid: str) -> None:
        """Tell each sidecar a sample's calls went through that the sample has ended, after its final scoring, so it drops what it keeps for the sample.

        A sidecar that can't be told drops the sample once no request has named it for its run expiry, so a failure is logged and not raised.
        """
        for sidecar in self._through.pop(sample_uuid, {}).values():
            with anyio.move_on_after(END_SAMPLE_TIMEOUT):
                try:
                    await sidecar.call("end_sample", {"sample_uuid": sample_uuid})
                except SidecarCallError as ex:
                    logger.warning(
                        f"The sentinel sidecar at {sidecar.origin} couldn't be told the sample {sample_uuid} ended: {ex}"
                    )

    async def copy_monitor_state(self, sample_uuid: str, store: Store) -> None:
        """Copy the monitor state each sidecar the sample's calls went through keeps into the sample store, before Inspect's scorers read it.

        Inside Inspect, a monitor's state is in the sample store, where a scorer can read it; through a sidecar, it is kept by the sidecar. After the copy, a marker in the sample store says whether it succeeded, so a scorer never reads a failed copy as a sample in which nothing was flagged.
        """
        through = self._through.get(sample_uuid)
        if not through:
            return
        copied: dict[str, Any] = {}
        failed: str | None = None
        for sidecar in through.values():
            with anyio.move_on_after(CALL_TIMEOUT) as scope:
                try:
                    result = await sidecar.call(
                        "sample_result", {"sample_uuid": sample_uuid}
                    )
                    copied.update(result.get("store") or {})
                except SidecarCallError as ex:
                    failed = _copy_failure(sidecar, ex)
            if scope.cancel_called:
                failed = (
                    f"the sentinel sidecar at {sidecar.origin} didn't answer in time"
                )
        for key, value in copied.items():
            store.set(key, value)
        store.set(
            MONITOR_STATE_COPY,
            {"copied": failed is None, "reason": failed},
        )

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


def _copy_failure(sidecar: Sidecar, ex: SidecarCallError) -> str:
    if ex.code == UNKNOWN_SAMPLE:
        return f"the sentinel sidecar at {sidecar.origin} holds nothing for the sample"
    if ex.code == METHOD_NOT_FOUND:
        return f"the sentinel sidecar at {sidecar.origin} doesn't send results (--no-eval-results)"
    return f"the sentinel sidecar at {sidecar.origin} couldn't be asked: {ex}"


_task_sidecars: ContextVar[TaskSidecars | None] = ContextVar(
    "task_sidecars", default=None
)

# by eval, for interim scoring, which runs outside the task's context
_eval_sidecars: "WeakValueDictionary[str, TaskSidecars]" = WeakValueDictionary()


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
    _eval_sidecars[facts.eval_id] = sidecars


def task_sidecars(eval_id: str | None = None) -> TaskSidecars | None:
    """The sidecars of the current task, or of an eval's task by its id."""
    if eval_id is not None:
        return _eval_sidecars.get(eval_id)
    return _task_sidecars.get()
