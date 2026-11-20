"""The sentinel sidecars a task's agent calls go through, found by probing each model's proxy."""

from collections.abc import Awaitable, Callable, Hashable
from contextvars import ContextVar
from dataclasses import dataclass, field
from logging import Filter, LogRecord, getLogger
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
    REDACTED,
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
        # each attempt's registration of its sample at a sidecar, by the
        # sample's uuid, then the sidecar's origin and the attempt
        self._completions: dict[str, dict[tuple[str, int], _Completion]] = {}
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
        # the attempts at each sample a request of which was sent to a
        # sidecar, by the sample's uuid, as the sidecar's origin and the attempt
        self._sent: dict[str, set[tuple[str, int]]] = {}
        # the attempts at each sample whose monitor state a sidecar lost, by
        # the sample's uuid
        self._lost: dict[str, set[int]] = {}
        # whether the task was warned that a sidecar withholds monitor state
        self._warned_withheld = False

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

        The sidecar is told the sample's uuid, and holds the sample's facts while a run that named itself is in progress: it frees them when the last has ended. So a completion counts only for the registration of the task it was sent to. Once the eval has set about registering the task again, as for another sample that found it lost, an attempt completes its registration again before its next call, or the sidecar could free the facts under it when that other sample ends. This doesn't wait for the sidecar's answer to that registration, which may never arrive. A completion sent while a registration of the task is on its way may reach the sidecar before it, and be lost to it, so it counts only for the call it was sent for: the attempt's next call sends it again, whether or not that registration is over by then. What an attempt sends again is what it first sent, as a sample's input and metadata may have changed since.

        Raises:
            SentinelProxyError: If the sidecar couldn't take the sample, or no longer kept the task and couldn't register it again.
        """

        def get_registration_change_count() -> int:
            return sidecar.access.registration_change_count if sidecar.access else 0

        async def complete(params: dict[str, Any]) -> tuple[bool, int]:
            # the registrations the sidecar took before this call, so one
            # another sample makes meanwhile isn't made again
            registered = sidecar.access.registrations if sidecar.access else None
            change_count_when_sent = get_registration_change_count()
            try:
                try:
                    result = await sidecar.eval_call("complete_registration", params)
                except SidecarCallError as ex:
                    if ex.code != UNKNOWN_TASK:
                        raise
                    # A sidecar that lost the task, or the eval's token, as
                    # after a restart, takes it again. Registering again
                    # changes nothing for a sidecar that still keeps it, and
                    # another sample that already did so is not repeated.
                    await self._register(sidecar, unless_since=registered)
                    change_count_when_sent = get_registration_change_count()
                    result = await sidecar.eval_call("complete_registration", params)
                return result.get("fixed") is True, change_count_when_sent
            except SidecarCallError as ex:
                if ex.code == UNAUTHORIZED:
                    raise SentinelProxyError(_unauthorized(sidecar, ex)) from ex
                if ex.code == REGISTRATION_REFUSED:
                    # the sidecar takes only the samples the task's registration
                    # names, and would refuse this one again: never retried
                    raise SampleRefusedError(
                        f"The sentinel sidecar at {sidecar.origin} takes only the samples the task's registration names, and the sample {sample.sample_id!r} of the task {self.facts.task!r} isn't one: {ex}"
                    ) from ex
                raise SentinelProxyError(
                    f"The sentinel sidecar at {sidecar.origin} couldn't register the sample {sample.sample_id!r} of the task {self.facts.task!r}: {ex}"
                ) from ex

        completions = self._completions.setdefault(sample_uuid, {})
        completion = completions.get((sidecar.origin, attempt))
        if completion is None:
            # serialized once, so what is sent again is what was first sent,
            # whatever the sample's input and metadata have become since
            completion = completions[(sidecar.origin, attempt)] = _Completion(
                {
                    "task": self.facts.task,
                    "sample_uuid": sample_uuid,
                    "sample_id": sample.sample_id,
                    "sample_description": sample.sample_description,
                    "sample_input": to_jsonable_python(
                        sample.sample_input, exclude_none=True
                    ),
                    "metadata": to_jsonable_python(sample.metadata),
                }
            )
        # One at a time for the attempt: its calls made at once wait for the
        # one that sends, and a completion that raised is tried again by the
        # next. It is complete for the registration of the task it was sent
        # to. A completion still on its way when the eval sets about
        # registering the task again is one the sidecar may have lost with
        # the task, so it is sent again. One sent while a registration of
        # the task was on its way is sent again by the attempt's next call.
        async with completion.lock:
            done = completion.done
            if sidecar.access is not None and sidecar.access.lock.locked():
                # A registration of the task is on its way, and the sidecar
                # may have taken it since this completion was sent, even one
                # sent while it was on its way. This doesn't wait for it.
                done = None
            while (
                done is None
                or done.change_count_when_sent != get_registration_change_count()
            ):
                done = completion.done = _Completed(*await complete(completion.params))
            return done.fixed

    def lost_monitor_state(self, sample_uuid: str, attempt_number: int) -> None:
        """Note that a sidecar lost an attempt's sample partway through, as on a restart, so the attempt's monitor state is never copied: what the sidecar holds for it began afresh."""
        self._lost.setdefault(sample_uuid, set()).add(attempt_number)

    def request_sent(
        self, sample_uuid: str, attempt_number: int, sidecar: Sidecar
    ) -> None:
        """Note that a request of an attempt at a sample is being sent to a sidecar, which may have begun judging the attempt from then on, whether or not its reply arrives."""
        self._sent.setdefault(sample_uuid, set()).add((sidecar.origin, attempt_number))

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
        self._completions.pop(sample_uuid, None)
        self._sent.pop(sample_uuid, None)
        self._unjudged.pop(sample_uuid, None)
        self._lost.pop(sample_uuid, None)
        if not tell:
            return
        for sidecar, _ in through:
            with anyio.move_on_after(END_SAMPLE_TIMEOUT):
                try:
                    await sidecar.eval_call(
                        "end_sample",
                        # the task finds the registration the sample's run is
                        # counted in, which a sidecar frees its facts from
                        {"sample_uuid": sample_uuid, "task": self.facts.task},
                    )
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
        self._raise_if_monitor_state_lost(sample_uuid, attempt_number, store)
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
        # a sidecar started with --no-eval-results withholds the state on
        # purpose, which is no failure: the sample is scored all the same
        withheld = True
        for sidecar in through:
            with anyio.move_on_after(CALL_TIMEOUT) as scope:
                try:
                    result = await sidecar.eval_call(
                        "sample_result", {"sample_uuid": sample_uuid}
                    )
                except SidecarCallError as ex:
                    failed = _copy_failure(sidecar, ex)
                    withheld = withheld and ex.code == METHOD_NOT_FOUND
                    continue

                # the answer always holds the store, if only an empty one: an
                # answer without one is a failed copy, never an empty store
                kept = result.get("store")
                if not isinstance(kept, dict):
                    failed = f"the sentinel sidecar at {sidecar.origin} answered without the sample's store"
                    withheld = False
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
                withheld = False
        # A restart may have been found while the sidecars were asked, as by
        # another sample, and the attempt have gone on since: what a sidecar
        # answered may then have begun afresh.
        self._raise_if_monitor_state_lost(sample_uuid, attempt_number, store)
        for key, value in copied.items():
            store.set(key, value)
        withheld = failed is not None and withheld
        store.set(
            MONITOR_STATE_COPY,
            {
                "copied": failed is None,
                "reason": failed,
                "withheld": withheld,
                "keys": sorted(copies | copied.keys()),
            },
        )
        if failed is None:
            return
        if withheld:
            if not self._warned_withheld:
                self._warned_withheld = True
                logger.warning(
                    f"The monitor state is withheld, so a scorer that reads it reads none: {failed}."
                )
            return
        # never scored over defaults that read as a sample in which nothing
        # was flagged: a sidecar that lost the sample, never saw it, or didn't
        # answer fails the sample instead, and says why
        raise SentinelProxyError(_not_scored(failed))

    def _raise_if_monitor_state_lost(
        self, sample_uuid: str, attempt_number: int, store: Store
    ) -> None:
        if attempt_number in self._lost.get(sample_uuid, set()):
            # what the sidecar holds began afresh after it lost the sample,
            # so it isn't the attempt's monitor state
            lost = (
                "the sentinel sidecar lost the sample partway through, as on a restart"
            )
            self.skip_monitor_state_copy(sample_uuid, attempt_number, store, lost)
            raise SentinelProxyError(_not_scored(lost))

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
        self, sidecar: Sidecar, unless_since: int | None = None
    ) -> None:
        # Registers the task. The first registration sends the eval's token,
        # as does one sent again after its answer was lost; a later one is
        # signed with it, and sends it only when the sidecar answers that it
        # lost it. With `unless_since`, a registration another caller made
        # since the sidecar had taken that many is not made again.
        facts = self.facts
        access = sidecar.access
        assert access is not None
        async with access.lock:
            if unless_since is not None and access.registrations != unless_since:
                return
            # Marked before it is sent: the sidecar may take a registration
            # whose answer never arrives, and a sample's completion sent
            # before it is then for a registration the sidecar replaced. And
            # marked again once it is over: a completion sent meanwhile may
            # have reached the sidecar first.
            access.registration_change_count += 1
            params: dict[str, Any] = {
                "eval_id": facts.eval_id,
                "task": facts.task,
                "task_description": facts.task_description,
                "metadata": to_jsonable_python(facts.metadata),
                "sample_ids": facts.sample_ids,
                "epochs": facts.epochs,
            }
            try:
                if access.registrations == 0:
                    await sidecar.call(
                        "register_task", {**params, "token": access.token}
                    )
                else:
                    try:
                        await sidecar.call(
                            "register_task",
                            {**params, **access.credentials("register_task")},
                        )
                    except SidecarCallError as ex:
                        if ex.code != UNKNOWN_TASK:
                            raise
                        # The sidecar holds no token for the eval, as after a
                        # restart, so it is sent the one the eval holds. What
                        # it lost is noted first: it may take the token and
                        # its answer never arrive, and an attempt that
                        # completes its registration while the answer is on
                        # its way began after the restart.
                        self._mark_attempts_lost(sidecar)
                        await sidecar.call(
                            "register_task", {**params, "token": access.token}
                        )
                access.registrations += 1
            except SidecarCallError as ex:
                self._registration_failed(sidecar, ex)
            finally:
                access.registration_change_count += 1

    def _mark_attempts_lost(self, sidecar: Sidecar) -> None:
        # A sidecar that lost the eval's token lost everything it held for
        # the eval with it, as on a restart: the monitor state of each attempt
        # it had begun judging. Such an attempt completes its registration
        # again and goes on, so nothing else would say what it lost. An
        # attempt is taken as begun once a request of it was sent. One that
        # had only completed its registration, as while it waits for a
        # connection, lost nothing: all the sidecar judges of it comes after.
        # A task's registration that expired alone loses none of this, and
        # isn't told apart here: the sidecar took that registration signed.
        for sample_uuid, sent in self._sent.items():
            for origin, attempt in sent:
                if origin == sidecar.origin:
                    self.lost_monitor_state(sample_uuid, attempt)

    def access(self, origin: str) -> EvalAccess | None:
        """The eval's id and token for the sidecar at an origin, or None if no model of the task found one there."""
        return self._access.get(origin)

    def _registration_failed(self, sidecar: Sidecar, ex: SidecarCallError) -> NoReturn:
        facts = self.facts
        if ex.code == UNAUTHORIZED:
            raise SentinelProxyError(_unauthorized(sidecar, ex)) from ex
        if ex.code == REGISTRATION_REFUSED:
            raise SentinelProxyError(
                f"The sentinel sidecar at {sidecar.origin} runs only the tasks its admin registered, and the task {facts.task!r} isn't one."
            ) from ex
        raise SentinelProxyError(
            f"The sentinel sidecar at {sidecar.origin} couldn't register the task {facts.task!r}: {ex}"
        ) from ex


class _Completed(NamedTuple):
    fixed: bool
    """Whether the sidecar's admin registered the task beforehand."""
    change_count_when_sent: int
    """The eval's `registration_change_count` for the sidecar when the completion was sent."""


@dataclass
class _Completion:
    """One attempt's registration of its sample at a sidecar."""

    params: dict[str, Any]
    """What the attempt first sent, as it was sent, which a later send repeats."""
    lock: anyio.Lock = field(default_factory=anyio.Lock)
    done: _Completed | None = None
    """The latest completion the sidecar took, or None before the first."""


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


def _unauthorized(sidecar: Sidecar, ex: SidecarCallError) -> str:
    return f"The sentinel sidecar at {sidecar.origin} won't take the eval's calls. Either it keeps another token for this eval, as when something else registered the eval with it first, or the clocks of Inspect's host and the sidecar's disagree by more than its timestamp window. {ex}"


def _copied_keys(store: Store) -> set[str]:
    # the keys of the sample store that earlier copies wrote
    earlier = store.get(MONITOR_STATE_COPY)
    return set(earlier.get("keys", [])) if isinstance(earlier, dict) else set()


def _not_scored(reason: str) -> str:
    return f"The sample isn't scored, as its monitor state wasn't copied from the sentinel sidecar: {reason}."


def _copy_failure(sidecar: Sidecar, ex: SidecarCallError) -> str:
    if ex.code == UNKNOWN_SAMPLE:
        return f"the sentinel sidecar at {sidecar.origin} holds nothing for the sample"
    if ex.code == METHOD_NOT_FOUND:
        return f"the sentinel sidecar at {sidecar.origin} doesn't send results (--no-eval-results)"
    return f"the sentinel sidecar at {sidecar.origin} couldn't be asked: {ex}"


_task_sidecars: ContextVar[TaskSidecars | None] = ContextVar(
    "task_sidecars", default=None
)

# by eval, for interim scoring, which runs outside the task's context, and
# for signing a model request as it is sent
_eval_sidecars: "WeakValueDictionary[str, TaskSidecars]" = WeakValueDictionary()

SDK_DEBUG_LOGGERS = ("anthropic._base_client", "openai._base_client")
"""The loggers the Anthropic and OpenAI SDKs log their requests to at debug level. The Anthropic SDK logs every request's body there, a registration's token included. The OpenAI SDK logs only the method, and is filtered too, so the token stays out if a version of it logs more."""


class _RedactEvalTokens(Filter):
    # replaces the token of every live task's eval in a record, so the debug
    # log of a registration through the SDK never holds one
    def filter(self, record: LogRecord) -> bool:
        tokens = [
            access.token
            for sidecars in list(_eval_sidecars.values())
            # copied, as a task that is probing may add to it from another
            # thread while this one logs
            for access in list(sidecars._access.values())
        ]
        if not tokens:
            return True
        message = record.getMessage()
        redacted = message
        for token in tokens:
            redacted = redacted.replace(token, REDACTED)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


_redact_eval_tokens = _RedactEvalTokens()


def _keep_eval_tokens_out_of_sdk_logs() -> None:
    # once, however many tasks start
    for name in SDK_DEBUG_LOGGERS:
        sdk_logger = getLogger(name)
        if _redact_eval_tokens not in sdk_logger.filters:
            sdk_logger.addFilter(_redact_eval_tokens)


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

    # known by its eval before it registers, so the token the registration
    # sends is kept out of the SDK's debug log
    _keep_eval_tokens_out_of_sdk_logs()
    _eval_sidecars[facts.eval_id] = sidecars

    await sidecars.start(model)
    _task_sidecars.set(sidecars)


def attempt_number(active: "ActiveSample") -> int:
    """Which attempt at its sample is running: 1, then one higher for each retry."""
    return active.retries + 1


def task_sidecars(eval_id: str | None = None) -> TaskSidecars | None:
    """The sidecars of the current task, or of an eval's task by its id."""
    if eval_id is not None:
        return _eval_sidecars.get(eval_id)
    return _task_sidecars.get()
