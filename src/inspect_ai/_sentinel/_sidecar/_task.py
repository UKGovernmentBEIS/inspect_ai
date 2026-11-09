"""The sentinel sidecars a task's agent calls go through, found by probing each model's proxy."""

from collections.abc import Awaitable, Callable, Hashable
from contextvars import ContextVar
from logging import getLogger
from typing import TYPE_CHECKING, Any, Generic, NamedTuple, NoReturn, TypeVar
from weakref import WeakValueDictionary

import anyio
from pydantic_core import to_jsonable_python

from inspect_ai._util.exception import SampleRefusedError
from inspect_ai.model._model import Model, ModelAPI
from inspect_ai.util._store import Store

from .._config import SentinelProxy
from ._endpoint import (
    CALL_TIMEOUT,
    UNAUTHORIZED,
    EvalAccess,
    NoSidecar,
    SentinelProxyError,
    Sidecar,
    SidecarCallError,
    probe,
    proxy_client,
)

if TYPE_CHECKING:
    from inspect_ai.log._samples import ActiveSample

REGISTRATION_REFUSED = -32001

END_SAMPLE_TIMEOUT = 10.0

UNKNOWN_SAMPLE = -32002
UNKNOWN_TASK = -32009
METHOD_NOT_FOUND = -32601

MONITOR_STATE_COPY = "sentinel_sidecar:monitor_state"
"""The sample store's marker of the latest copy of monitor state from the sidecars: whether it succeeded, and why not."""

logger = getLogger(__name__)

_NOT_PROBED = NoSidecar(
    "its base URL was not set, or its provider's calls aren't ones a sidecar reads",
    definite=True,
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

    def __init__(
        self, mode: SentinelProxy, facts: TaskFacts, in_process_sentinel: bool = False
    ) -> None:
        self.mode: SentinelProxy = mode
        self.facts = facts
        self.in_process_sentinel = in_process_sentinel
        """Whether the task also has a sentinel inside Inspect, whose monitor state a copy must never overwrite."""
        self._found = _Once[Sidecar | NoSidecar]()
        # the endpoints whose probe couldn't tell, warned of once
        self._warned: set[str] = set()
        self._completed = _Once[bool]()
        # the eval's id and token for each sidecar, by its origin: models with
        # other credentials reach the same sidecar, which keeps one token for
        # the eval
        self._access: dict[str, EvalAccess] = {}
        # the sidecars each sample's calls went through, by the sample's uuid,
        # with the attempt that last called each
        self._through: dict[str, dict[str, tuple[Sidecar, int]]] = {}
        # the models each attempt at a sample called with no sidecar behind
        # them, by the sample's uuid, so each is noted in its transcript once
        self._unjudged: dict[str, set[tuple[int, str]]] = {}
        # the attempts at each sample whose monitor state a sidecar lost, by
        # the sample's uuid
        self._lost: dict[str, set[int]] = {}

    async def start(self, model: Model) -> None:
        """Probe the endpoint of the task's assigned model, and register the task with a sidecar found there, before any sample runs.

        Raises:
            SentinelProxyError: If the mode is `required` and no sidecar Inspect supports answered, a sidecar answered that Inspect can't work with, or the task couldn't be registered.
        """
        found = await self._probe(model.api)
        if self.mode == "required" and not isinstance(found, Sidecar):
            raise SentinelProxyError(
                f"A sentinel sidecar is required (--sentinel-proxy required), and none was found for {model}: {found.reason}."
            )

    async def sidecar(self, api: ModelAPI) -> Sidecar | None:
        """The sidecar behind a model's endpoint, probing it and registering the task the first time it is asked of."""
        found = await self._probe(api)
        return found if isinstance(found, Sidecar) else None

    async def complete_registration(
        self, sidecar: Sidecar, sample: SampleFacts, sample_uuid: str, attempt: int
    ) -> bool:
        """Send a sample's facts to a sidecar before the sidecar judges any of its calls, once for each epoch's attempt at the sample.

        Returns:
            Whether the sidecar's admin registered the task beforehand, in its tasks folder. Such a sidecar takes only the samples the folder holds, so a sample it later says it can't place was never accepted, rather than lost.

        A sidecar that no longer keeps the task's registration, as after it restarted or the registration expired, has the task registered again first. Each epoch and each retry of a sample completes its registration again, so a later one finds a sidecar that has lost the task, rather than being judged without the task's facts or refused.

        Raises:
            SentinelProxyError: If the sidecar couldn't take the sample, or no longer kept the task and couldn't register it again.
        """

        async def complete() -> bool:
            params = {
                "task": self.facts.task,
                "sample_id": sample.sample_id,
                "sample_description": sample.sample_description,
                "sample_input": to_jsonable_python(
                    sample.sample_input, exclude_none=True
                ),
                "metadata": to_jsonable_python(sample.metadata),
            }
            try:
                presented = sidecar.access.token if sidecar.access else None
                try:
                    result = await sidecar.eval_call("complete_registration", params)
                except SidecarCallError as ex:
                    if ex.code != UNKNOWN_TASK:
                        raise
                    # A sidecar that lost the task, or the eval's token, as
                    # after a restart, takes it again. Registering again
                    # changes nothing for a sidecar that still keeps it, and
                    # another sample that already did so is not repeated.
                    await self._register(sidecar, unless_since=presented)
                    result = await sidecar.eval_call("complete_registration", params)
                return result.get("fixed") is True
            except SidecarCallError as ex:
                if ex.code == UNAUTHORIZED:
                    raise SentinelProxyError(_unauthorized(sidecar)) from ex
                if ex.code == REGISTRATION_REFUSED:
                    # the sidecar takes only the samples the task's registration
                    # names, and would refuse this one again: never retried
                    raise SampleRefusedError(
                        f"The sentinel sidecar at {sidecar.origin} takes only the samples the task's registration names, and the sample {sample.sample_id!r} of the task {self.facts.task!r} isn't one: {ex}"
                    ) from ex
                raise SentinelProxyError(
                    f"The sentinel sidecar at {sidecar.origin} couldn't register the sample {sample.sample_id!r} of the task {self.facts.task!r}: {ex}"
                ) from ex

        return await self._completed.run(
            (sidecar.origin, sample_uuid, attempt), complete
        )

    def lost_monitor_state(self, sample_uuid: str, attempt_number: int) -> None:
        """Note that a sidecar lost an attempt's sample partway through, as on a restart, so the attempt's monitor state is never copied: what the sidecar holds for it began afresh."""
        self._lost.setdefault(sample_uuid, set()).add(attempt_number)

    def note_unjudged(self, sample_uuid: str, attempt_number: int, model: str) -> bool:
        """Note that an attempt at a sample called a model with no sidecar behind it; whether this is the attempt's first such call to the model."""
        noted = self._unjudged.setdefault(sample_uuid, set())
        if (attempt_number, model) in noted:
            return False
        noted.add((attempt_number, model))
        return True

    def called_through(
        self, sample_uuid: str, attempt_number: int, sidecar: Sidecar
    ) -> None:
        """Note that a call of an attempt at a sample went through a sidecar, which is told when the sample ends."""
        self._through.setdefault(sample_uuid, {})[sidecar.origin] = (
            sidecar,
            attempt_number,
        )

    async def end_sample(self, sample_uuid: str, tell: bool = True) -> None:
        """Tell each sidecar a sample's calls went through that the sample has ended, after its final scoring, so it drops what it keeps for the sample.

        A sidecar that can't be told drops the sample once no request has named it for its run expiry, so a failure is logged and not raised.

        Args:
            sample_uuid: The sample's uuid.
            tell: Whether to tell the sidecars. A cancelled sample's teardown can't be interrupted, so it doesn't wait on a sidecar that may not answer, and the sidecars drop the sample at its run expiry.
        """
        through = self._through.pop(sample_uuid, {}).values()
        self._unjudged.pop(sample_uuid, None)
        self._lost.pop(sample_uuid, None)
        if not tell:
            return
        for sidecar, _ in through:
            with anyio.move_on_after(END_SAMPLE_TIMEOUT):
                try:
                    await sidecar.eval_call("end_sample", {"sample_uuid": sample_uuid})
                except SidecarCallError as ex:
                    logger.warning(
                        f"The sentinel sidecar at {sidecar.origin} couldn't be told the sample {sample_uuid} ended: {ex}"
                    )

    async def copy_monitor_state(
        self, sample_uuid: str, attempt_number: int, store: Store
    ) -> None:
        """Copy the monitor state each sidecar the attempt's calls went through keeps into the sample store, before Inspect's scorers read it.

        Inside Inspect, a monitor's state is in the sample store, where a scorer can read it; through a sidecar, it is kept by the sidecar. After the copy, a marker in the sample store says whether it succeeded, so a scorer never reads a failed copy as a sample in which nothing was flagged.

        A sidecar only an earlier attempt called is left out: it still keeps that attempt's monitor state, and a retry starts with an empty sample store, as in Inspect's own process.

        An attempt whose sample a sidecar lost partway through, as on a restart, isn't copied: the marker says its monitor state was lost, since what the sidecar holds began afresh.

        Two sentinels keeping one key fail the sample, since which one a scorer reads can't be told: two sidecars, or a sidecar and a sentinel inside Inspect. A key is taken for the sentinel inside Inspect's only when the task has one. A scorer that reads monitor state with `store_as()` before the sidecar has written any puts the model's defaults into the sample store, which the copy would otherwise take for another sentinel's state. With both kinds of sentinel on one task, such a key the sentinel inside Inspect doesn't keep still fails the sample.
        """
        through = self._attempt_sidecars(sample_uuid, attempt_number)
        if not through:
            return
        if attempt_number in self._lost.get(sample_uuid, set()):
            # what the sidecar holds began afresh after it lost the sample,
            # so it isn't the attempt's monitor state
            self.skip_monitor_state_copy(
                sample_uuid,
                attempt_number,
                store,
                "the sentinel sidecar lost the sample partway through, as on a restart",
            )
            return
        # the keys earlier copies wrote: any other key of the sample store
        # the copy would overwrite is a sentinel's inside Inspect
        copies = _copied_keys(store)
        # until the copy finishes: a copy cut short, as by the scoring's
        # deadline, still says the monitor state is missing
        store.set(
            MONITOR_STATE_COPY,
            {
                "copied": False,
                "reason": "the copy from the sidecar didn't finish",
                "keys": sorted(copies),
            },
        )
        copied: dict[str, Any] = {}
        written_by: dict[str, str] = {}
        failed: str | None = None
        for sidecar in through:
            with anyio.move_on_after(CALL_TIMEOUT) as scope:
                try:
                    result = await sidecar.eval_call(
                        "sample_result", {"sample_uuid": sample_uuid}
                    )
                except SidecarCallError as ex:
                    failed = _copy_failure(sidecar, ex)
                    continue

                # the answer always holds the store, if only an empty one: an
                # answer without one is a failed copy, never an empty store
                kept = result.get("store")
                if not isinstance(kept, dict):
                    failed = f"the sentinel sidecar at {sidecar.origin} answered without the sample's store"
                    continue

                for key, value in kept.items():
                    # which sentinel a scorer reads can't be told, and a
                    # sentinel inside Inspect would carry on from the copy
                    conflict = None
                    if key in written_by:
                        conflict = f"The sentinels in the sidecars at {written_by[key]} and {sidecar.origin} both keep {key!r} for the sample."
                    elif (
                        self.in_process_sentinel and key in store and key not in copies
                    ):
                        conflict = f"The sentinel inside Inspect and the one in the sidecar at {sidecar.origin} both keep {key!r} for the sample."
                    if conflict is not None:
                        store.set(
                            MONITOR_STATE_COPY,
                            {
                                "copied": False,
                                "reason": conflict,
                                "keys": sorted(copies),
                            },
                        )
                        raise SentinelProxyError(conflict)
                    written_by[key] = sidecar.origin
                    copied[key] = value
            if scope.cancel_called:
                failed = (
                    f"the sentinel sidecar at {sidecar.origin} didn't answer in time"
                )
        for key, value in copied.items():
            store.set(key, value)
        store.set(
            MONITOR_STATE_COPY,
            {
                "copied": failed is None,
                "reason": failed,
                "keys": sorted(copies | copied.keys()),
            },
        )

    def skip_monitor_state_copy(
        self, sample_uuid: str, attempt_number: int, store: Store, reason: str
    ) -> None:
        """Mark the monitor state of an attempt whose calls went through a sidecar as not copied, without asking the sidecar, so a scorer that reads the sample later never takes it for a sample in which nothing was flagged."""
        if self._attempt_sidecars(sample_uuid, attempt_number):
            store.set(
                MONITOR_STATE_COPY,
                {
                    "copied": False,
                    "reason": reason,
                    "keys": sorted(_copied_keys(store)),
                },
            )

    def _attempt_sidecars(self, sample_uuid: str, attempt_number: int) -> list[Sidecar]:
        # the sidecars the attempt's calls went through: one only an earlier
        # attempt called still keeps that attempt's monitor state
        return [
            sidecar
            for sidecar, called_in in self._through.get(sample_uuid, {}).values()
            if called_in == attempt_number
        ]

    async def _probe(self, api: ModelAPI) -> Sidecar | NoSidecar:
        client = await proxy_client(api)
        if client is None:
            return _NOT_PROBED

        async def probe_and_register() -> Sidecar | NoSidecar:
            found = await probe(client)
            if isinstance(found, Sidecar):
                found.access = self._access.setdefault(
                    found.origin, EvalAccess(self.facts.eval_id)
                )
                await self._register(found)
            return found

        # a definite answer holds for the task; one that couldn't tell is
        # asked again on the next call, so a failure at task start doesn't
        # leave a sidecar unused for the whole task
        found = await self._found.run(
            (client.base_url, api.api_key),
            probe_and_register,
            keep=lambda found: isinstance(found, Sidecar) or found.definite,
        )
        if isinstance(found, NoSidecar) and not found.definite:
            if self.mode == "auto" and client.base_url not in self._warned:
                self._warned.add(client.base_url)
                logger.warning(
                    f"No sentinel sidecar is used for this call, as {found.reason}. The endpoint is probed again on the next call."
                )
            else:
                logger.debug(f"Probing for a sentinel sidecar failed: {found.reason}")
        return found

    async def _register(
        self, sidecar: Sidecar, unless_since: str | None = None
    ) -> None:
        # Registers the task, presenting the token the eval holds for the
        # sidecar, and keeps the one it gives back: the same, or a new one
        # from a sidecar that kept none. With `unless_since`, a registration
        # that another caller already made since that token was presented is
        # not made again.
        facts = self.facts
        access = sidecar.access
        assert access is not None
        async with access.lock:
            if unless_since is not None and access.token != unless_since:
                return
            params: dict[str, Any] = {
                "eval_id": facts.eval_id,
                "task": facts.task,
                "task_description": facts.task_description,
                "metadata": to_jsonable_python(facts.metadata),
                "sample_ids": facts.sample_ids,
                "epochs": facts.epochs,
            }
            # the token the sidecar gave the eval, or at first the one the eval
            # made, which the sidecar keeps: so this registration can be sent
            # again if its answer is lost
            params["token"] = (
                access.token if access.token is not None else access.chosen
            )
            try:
                result = await sidecar.call("register_task", params)
            except SidecarCallError as ex:
                self._registration_failed(sidecar, ex)
            token = result.get("token")
            if not isinstance(token, str):
                raise SentinelProxyError(
                    f"The sentinel sidecar at {sidecar.origin} registered the task {facts.task!r} without giving the eval a token, so it can't be asked what it decided."
                )
            access.token = token

    def _registration_failed(self, sidecar: Sidecar, ex: SidecarCallError) -> NoReturn:
        facts = self.facts
        if ex.code == UNAUTHORIZED:
            raise SentinelProxyError(_unauthorized(sidecar)) from ex
        if ex.code == REGISTRATION_REFUSED:
            raise SentinelProxyError(
                f"The sentinel sidecar at {sidecar.origin} runs only the tasks its admin registered, and the task {facts.task!r} isn't one."
            ) from ex
        raise SentinelProxyError(
            f"The sentinel sidecar at {sidecar.origin} couldn't register the task {facts.task!r}: {ex}"
        ) from ex


class _Once(Generic[T]):
    # each key's work runs once: callers asking meanwhile wait for it, and
    # work that raised, or whose result `keep` turns down, is tried again by
    # the next caller
    def __init__(self) -> None:
        self._done: dict[Hashable, T] = {}
        self._running: dict[Hashable, anyio.Event] = {}

    async def run(
        self,
        key: Hashable,
        work: Callable[[], Awaitable[T]],
        keep: Callable[[T], bool] = lambda result: True,
    ) -> T:
        while key not in self._done:
            running = self._running.get(key)
            if running is not None:
                await running.wait()
                continue
            self._running[key] = anyio.Event()
            try:
                result = await work()
                if not keep(result):
                    return result
                self._done[key] = result
            finally:
                self._running.pop(key).set()
        return self._done[key]


def _unauthorized(sidecar: Sidecar) -> str:
    return f"The sentinel sidecar at {sidecar.origin} keeps another token for this eval, so it won't take the eval's calls: something else registered the eval with it first."


def _copied_keys(store: Store) -> set[str]:
    # the keys of the sample store that earlier copies wrote
    earlier = store.get(MONITOR_STATE_COPY)
    return set(earlier.get("keys", [])) if isinstance(earlier, dict) else set()


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
    mode: SentinelProxy | None,
    model: Model,
    facts: TaskFacts,
    in_process_sentinel: bool = False,
) -> None:
    """Find the sidecar behind the task's assigned model, and register the task with it, for the samples the task runs.

    Args:
        mode: Whether to look for a sidecar, and whether one is required.
        model: The task's assigned model.
        facts: What the task registers with each sidecar.
        in_process_sentinel: Whether the task also has a sentinel inside Inspect, whose monitor state a copy from a sidecar must never overwrite.

    Raises:
        SentinelProxyError: If the task can't run with the sidecars it finds.
    """
    # nothing is looked for unless the eval asks: no probe, and no sidecar
    # code runs for the task
    if mode is None or mode == "off":
        _task_sidecars.set(None)
        return
    sidecars = TaskSidecars(mode, facts, in_process_sentinel)
    await sidecars.start(model)
    _task_sidecars.set(sidecars)
    _eval_sidecars[facts.eval_id] = sidecars


def attempt_number(active: "ActiveSample") -> int:
    """Which attempt at its sample is running: 1, then one higher for each retry."""
    return active.retries + 1


def task_sidecars(eval_id: str | None = None) -> TaskSidecars | None:
    """The sidecars of the current task, or of an eval's task by its id."""
    if eval_id is not None:
        return _eval_sidecars.get(eval_id)
    return _task_sidecars.get()
