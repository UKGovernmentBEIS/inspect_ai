"""The sentinel sidecars a task's agent calls go through, found by probing each model's proxy."""

from collections.abc import Awaitable, Callable, Hashable
from contextvars import ContextVar
from dataclasses import replace
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

REGISTRATION_TIMEOUT = CALL_TIMEOUT
"""How long a request waits for the sidecar to hold its sample's registration, in seconds, all told: for a registration that is on its way, for the sidecar's answer, and for the task to be registered again where the sidecar lost it. The request holds its model's connection meanwhile, so the limit is on the clock, where a call's own is on each read of its answer."""

FALLBACK_RESERVE = 5.0
"""How long before a deadline each later client a sidecar may be reached through is asked as well, in seconds, and no more than half the deadline for all of them. A client that stalls then leaves the others time to try."""

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
        self._registrations: dict[str, dict[tuple[str, int], AttemptRegistration]] = {}
        # the eval's id and token for each sidecar, by its origin: models with
        # other credentials reach the same sidecar, which keeps one token for
        # the eval
        self._access: dict[str, EvalAccess] = {}
        # the models each attempt at a sample called with no sidecar behind
        # them, by the sample's uuid, so each is noted in its transcript once
        self._unjudged: dict[str, set[tuple[int, str]]] = {}
        # the attempts at each sample whose monitor state a sidecar said it
        # lost, by the sample's uuid
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

    def attempt_registration(
        self, sidecar: Sidecar, sample: SampleFacts, sample_uuid: str, attempt: int
    ) -> "AttemptRegistration":
        """An attempt's registration of its sample at a sidecar, which each request of the attempt makes sure of as it is sent.

        The sample's facts are taken here, as the attempt's first call through the sidecar is prepared, and nothing is sent. Every later call of the attempt gets the same registration, so what is sent again is what was first taken, as a sample's input and metadata may have changed since.
        """
        registrations = self._registrations.setdefault(sample_uuid, {})
        registration = registrations.get((sidecar.origin, attempt))
        if registration is None:
            registration = registrations[(sidecar.origin, attempt)] = (
                AttemptRegistration(
                    self,
                    sidecar.origin,
                    sidecar.access,
                    sample.sample_id,
                    {
                        "task": self.facts.task,
                        "sample_uuid": sample_uuid,
                        "sample_id": sample.sample_id,
                        "sample_description": sample.sample_description,
                        "sample_input": to_jsonable_python(
                            sample.sample_input, exclude_none=True
                        ),
                        "metadata": to_jsonable_python(sample.metadata),
                    },
                )
            )
        return registration

    def lost_monitor_state(self, sample_uuid: str, attempt_number: int) -> None:
        """Note that a sidecar said it lost an attempt's sample partway through, so the attempt's monitor state is never copied: what the sidecar holds for it began afresh.

        A sidecar can say so before the eval finds it restarted: it answers that it holds no sample it had accepted, or no record of a call it was required to judge. A restart the eval finds itself needs no note here.
        """
        self._lost.setdefault(sample_uuid, set()).add(attempt_number)

    def note_unjudged(self, sample_uuid: str, attempt_number: int, model: str) -> bool:
        """Note that an attempt at a sample called a model with no sidecar behind it; whether this is the attempt's first such call to the model."""
        noted = self._unjudged.setdefault(sample_uuid, set())
        if (attempt_number, model) in noted:
            return False
        noted.add((attempt_number, model))
        return True

    async def end_sample(self, sample_uuid: str, tell: bool = True) -> None:
        """Tell each sidecar that was sent a registration of the sample that the sample has ended, after its final scoring, so it drops what it keeps for the sample.

        Such a sidecar may hold the sample's facts, whether or not a request of the sample followed, or the registration's answer arrived. A sidecar the sample only prepared calls for was sent nothing of the sample, and isn't told it ended.

        A sidecar that can't be told drops the sample once no request has named it for its run expiry, so a failure is logged and not raised.

        Args:
            sample_uuid: The sample's uuid.
            tell: Whether to tell the sidecars. A cancelled sample's teardown can't be interrupted, so it doesn't wait on a sidecar that may not answer, and the sidecars drop the sample at its run expiry.
        """
        # each sidecar once, through whichever of the sample's clients
        # still reaches it
        origins = dict.fromkeys(
            origin for origin, _ in self._registrations.get(sample_uuid, {})
        )
        through = {origin: self._clients(sample_uuid, origin) for origin in origins}
        self._registrations.pop(sample_uuid, None)
        self._unjudged.pop(sample_uuid, None)
        self._lost.pop(sample_uuid, None)
        if not tell:
            return
        for origin, clients in through.items():
            if not clients:
                continue
            with anyio.move_on_after(END_SAMPLE_TIMEOUT):
                try:
                    await _call_through_any(
                        clients,
                        "end_sample",
                        # the task finds the registration the sample's run is
                        # counted in, which a sidecar frees its facts from
                        {"sample_uuid": sample_uuid, "task": self.facts.task},
                        END_SAMPLE_TIMEOUT,
                    )
                except SidecarCallError as ex:
                    logger.warning(
                        f"The sentinel sidecar at {origin} couldn't be told the sample {sample_uuid} ended: {ex}"
                    )

    async def copy_monitor_state(
        self, sample_uuid: str, attempt_number: int, store: Store
    ) -> None:
        """Copy the monitor state each sidecar a request of the attempt was sent through keeps into the sample store, before Inspect's scorers read it.

        Inside Inspect, a monitor's state is in the sample store, where a scorer can read it; through a sidecar, it is kept by the sidecar. After the copy, a marker in the sample store says whether it succeeded, so a scorer never reads a failed copy as a sample in which nothing was flagged.

        A sidecar only an earlier attempt sent through is left out: it still keeps that attempt's monitor state, and a retry starts with an empty sample store, as in Inspect's own process. So is one no request of the attempt was sent through, as when a solver cancels a call that waits for a connection, or for its sample's registration: the sidecar judged nothing of the attempt, and there is nothing to copy.

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
                    result = await _call_through_any(
                        self._clients(sample_uuid, sidecar.origin, first=sidecar),
                        "sample_result",
                        {"sample_uuid": sample_uuid},
                        CALL_TIMEOUT,
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
        # Asked again, as a restart may have been found while the sidecars
        # answered, as by another sample: what one answered may then have
        # begun afresh.
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
        restarted = any(
            registration.restarted_since_first_request()
            for (_, attempt), registration in self._registrations.get(
                sample_uuid, {}
            ).items()
            if attempt == attempt_number
        )
        if restarted or attempt_number in self._lost.get(sample_uuid, set()):
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
        # the sidecars a request of the attempt was sent through: one only an
        # earlier attempt sent through still keeps that attempt's monitor state
        return [
            registration.latest_request.through
            for (_, attempt), registration in self._registrations.get(
                sample_uuid, {}
            ).items()
            if attempt == attempt_number and registration.latest_request is not None
        ]

    def _clients(
        self, sample_uuid: str, origin: str, first: Sidecar | None = None
    ) -> list[Sidecar]:
        # The sidecar at an origin, as each client that may reach it does:
        # each model has a client of its own, which may be closed since. None
        # if the sample sent the sidecar nothing. The likeliest to reach it
        # still come first: `first`, then the latest of the sample's attempts
        # to send a request, then every client the sample sent it anything
        # through, the latest first, then the clients the sample never used:
        # those the task found the sidecar through, and those its other
        # samples in progress use. One client is one way to the sidecar,
        # whichever call it was taken for.
        registrations = [
            registration
            for (at, _), registration in self._registrations.get(
                sample_uuid, {}
            ).items()
            if at == origin
        ]
        latest_first = list(reversed(registrations))
        used = [
            sent.through
            for registration in latest_first
            for sent in reversed(registration.registrations)
        ]
        if not used:
            return []
        clients: list[Sidecar] = []
        for sidecar in [
            first,
            *(
                registration.latest_request.through
                for registration in latest_first
                if registration.latest_request is not None
            ),
            *used,
            *(found for found in self._found.kept() if isinstance(found, Sidecar)),
            *(
                sent.through
                for others in self._registrations.values()
                for registration in others.values()
                for sent in registration.registrations
            ),
        ]:
            if (
                sidecar is not None
                and sidecar.origin == origin
                and all(sidecar.client is not known.client for known in clients)
            ):
                clients.append(sidecar)
        return clients

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
        if isinstance(found, Sidecar) and found.client is not client.sdk:
            # Another client with the same address and key: a second model
            # of the service, or a client that replaced one since closed.
            # The probe's answer holds for it, and it shares the eval's
            # access to the sidecar. Only the client differs, so each
            # model's calls to the sidecar go through its own. Nothing is
            # kept of it here: a sample may bring a client and close it.
            found = replace(found, client=client.sdk)
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
        self, sidecar: Sidecar, unless_begun_since: int | None = None
    ) -> bool:
        # Registers the task, and says whether it did. The first registration
        # sends the eval's token, as does one sent again after its answer was
        # lost; a later one is signed with it, and sends it only when the
        # sidecar answers that it lost it. With `unless_begun_since`, nothing
        # is sent if another caller began a registration since that many had
        # begun: one finding of a lost task is one registration.
        facts = self.facts
        access = sidecar.access
        assert access is not None
        async with access.lock:
            if (
                unless_begun_since is not None
                and access.registrations_begun != unless_begun_since
            ):
                return False
            # Counted before it is sent: the sidecar may take a registration
            # whose answer never arrives, and a sample's registration sent
            # before it is then for a registration the sidecar replaced.
            access.registrations_begun += 1
            params: dict[str, Any] = {
                "eval_id": facts.eval_id,
                "task": facts.task,
                "task_description": facts.task_description,
                "metadata": to_jsonable_python(facts.metadata),
                "sample_ids": facts.sample_ids,
                "epochs": facts.epochs,
            }
            try:
                if not access.registered:
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
                        # restart, so it is sent the one the eval holds. A
                        # task's registration that expired alone is taken
                        # signed, and isn't a restart.
                        access.restarts_found += 1
                        await sidecar.call(
                            "register_task", {**params, "token": access.token}
                        )
                access.registered = True
            except SidecarCallError as ex:
                self._registration_failed(sidecar, ex)
            return True

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


class _Held(NamedTuple):
    """A sample's registration the sidecar answered."""

    fixed: bool
    """Whether the sidecar's admin registered the task beforehand."""
    registrations_begun: int
    """The eval's `registrations_begun` for the sidecar when the sample's registration was sent, which it counts for."""


class Sent(NamedTuple):
    """Something an attempt sent a sidecar, as things stood when it was sent. It never changes: what is asked of the attempt later, at scoring and when its sample ends, is read from it."""

    through: Sidecar
    """The sidecar, as the client that carried it reaches it. A model has a client of its own."""
    restarts_found: int
    """How many restarts of the sidecar the eval had found: which run of the sidecar it was sent to."""


class AttemptRegistration:
    """One attempt's registration of its sample at a sidecar: the facts it registers, and whether the sidecar holds them.

    Every request of the attempt through the sidecar makes sure of the registration as it is sent, with `ensure_registered()`: an attempt's first send, a retry, a resend and a fetch alike. Nothing else sends a sample's registration.

    Two things happen for the attempt at the sidecar, each recorded as it happens in a `Sent` that never changes: its registration is made sure of through a client, and a request of it is sent through one (`record_request()`). What is asked of the attempt later is read from those records: which clients may reach the sidecar, whether the sidecar judged anything of it, and whether the sidecar restarted since it began to.

    The attempt's models may reach the sidecar with different credentials, each through a client of its own, and share the one registration. So it belongs to the sidecar's origin, and each request makes sure of it through its own model's client.
    """

    def __init__(
        self,
        sidecars: TaskSidecars,
        origin: str,
        access: EvalAccess | None,
        sample_id: str | int,
        params: dict[str, Any],
    ) -> None:
        self.origin = origin
        self.params = params
        """The sample's facts as the attempt's first call took them, which every send of the registration repeats."""
        self._sidecars = sidecars
        self._access = access
        self._sample_id = sample_id
        # one send at a time for the attempt
        self._lock = anyio.Lock()
        self._held: _Held | None = None
        self.registrations: list[Sent] = []
        """The attempt's registration as each client made sure of it, the latest last, one for each client.

        Recorded as the registration is sent, or found held, and before its answer: once the sidecar was sent the registration it may hold the sample's facts, whatever came of it. So it is told when the sample ends, through any of these clients that still reaches it.
        """
        self.first_request: Sent | None = None
        """The first request of the attempt to be sent through the sidecar, or None before any was.

        The sidecar judges the attempt from then. If the eval has found a restart of the sidecar since, the sidecar lost what it had judged.
        """
        self.latest_request: Sent | None = None
        """The latest request of the attempt to be sent through the sidecar, or None before any was.

        Only once a request is sent can the sidecar have judged anything of the attempt, and hold monitor state of it, which it is asked for through this client first. A registration alone doesn't make it so: a call cancelled while its registration was on its way sent no request.
        """

    async def ensure_registered(self, sidecar: Sidecar) -> bool:
        """Send the sample's facts to the sidecar unless it holds them, as a request of the attempt is sent.

        The sidecar holds a sample's facts under the task's registration, and frees them when the last run that named the sample ends. So a sample's registration counts only for the registration of the task it was sent to: once the eval has begun to register the task again, as for another sample that found it lost, the sample's is sent again. A registration of the task that is on its way is waited for first, as the sidecar may take a sample's registration before it and lose it to it. And a sample's registration that such a registration overlapped is sent again.

        A sidecar that no longer keeps the task, as after it restarted or the registration expired, has the task registered again first, once for all the samples that find it lost.

        This closes the overlaps the eval knows of. A registration of the task can still begin after this returns and before the request reaches the sidecar, as when the sidecar restarts in between and another sample finds it, and only the sidecar can refuse a request it holds no facts for.

        Args:
            sidecar: The sidecar as the model whose request is being sent reaches it, with that model's client and credentials.

        Returns:
            Whether the sidecar's admin registered the task beforehand, in its tasks folder. Such a sidecar takes only the samples the folder holds, so a sample it later says it can't place was never accepted, rather than lost.

        Raises:
            SentinelProxyError: If the sidecar couldn't take the sample, or no longer kept the task and couldn't register it again, or didn't within `REGISTRATION_TIMEOUT`.
            SampleRefusedError: If the sidecar takes only the samples the task's registration names, and this isn't one.
        """
        with anyio.move_on_after(REGISTRATION_TIMEOUT):
            return await self._send_unless_held(sidecar)
        raise SentinelProxyError(
            f"The sentinel sidecar at {sidecar.origin} didn't register the sample {self._sample_id!r} of the task {self._sidecars.facts.task!r} within {REGISTRATION_TIMEOUT:g} seconds."
        )

    async def _send_unless_held(self, sidecar: Sidecar) -> bool:
        access = self._access
        assert access is not None
        # One at a time for the attempt: its calls made at once wait for the
        # one that sends, and a registration that raised is tried again by
        # the next.
        async with self._lock:
            registered_again = False
            while True:
                await access.wait_for_registration()
                # from here the sidecar is sent the attempt's registration,
                # or holds it already
                self.registrations = [
                    known
                    for known in self.registrations
                    if known.through.client is not sidecar.client
                ] + [Sent(sidecar, access.restarts_found)]
                begun = access.registrations_begun
                held = self._held
                if held is not None and held.registrations_begun == begun:
                    break
                try:
                    result = await sidecar.eval_call(
                        "complete_registration", self.params
                    )
                except SidecarCallError as ex:
                    if ex.code == UNKNOWN_TASK and not registered_again:
                        # A sidecar that lost the task, or the eval's token,
                        # as after a restart, takes it again. Registering
                        # again changes nothing for a sidecar that still
                        # keeps it, and another sample that already did so
                        # is not repeated.
                        registered_again = await self._sidecars._register(
                            sidecar, unless_begun_since=begun
                        )
                        continue
                    self._refused(sidecar, ex)
                if access.registrations_begun == begun:
                    held = self._held = _Held(result.get("fixed") is True, begun)
                    break
                # a registration of the task began while this was on its way,
                # and the sidecar may have taken it after: sent again
            return held.fixed

    def record_request(self, sidecar: Sidecar) -> None:
        """Record that a request of the attempt is being sent through the sidecar, its registration made sure of.

        Args:
            sidecar: The sidecar as the model whose request is being sent reaches it.
        """
        access = self._access
        assert access is not None
        self.latest_request = Sent(sidecar, access.restarts_found)
        if self.first_request is None:
            self.first_request = self.latest_request

    def restarted_since_first_request(self) -> bool:
        """Whether the sidecar was found to have restarted since a request of the attempt was first sent to it, so it lost what it had judged of the attempt.

        An attempt that has sent the sidecar no request lost nothing, and neither did one whose first request found the restart: all the sidecar judges of it comes after.
        """
        access = self._access
        return (
            access is not None
            and self.first_request is not None
            and access.restarts_found != self.first_request.restarts_found
        )

    def _refused(self, sidecar: Sidecar, ex: SidecarCallError) -> NoReturn:
        task = self._sidecars.facts.task
        if ex.code == UNAUTHORIZED:
            raise SentinelProxyError(_unauthorized(sidecar, ex)) from ex
        if ex.code == REGISTRATION_REFUSED:
            # the sidecar takes only the samples the task's registration
            # names, and would refuse this one again: never retried
            raise SampleRefusedError(
                f"The sentinel sidecar at {sidecar.origin} takes only the samples the task's registration names, and the sample {self._sample_id!r} of the task {task!r} isn't one: {ex}"
            ) from ex
        raise SentinelProxyError(
            f"The sentinel sidecar at {sidecar.origin} couldn't register the sample {self._sample_id!r} of the task {task!r}: {ex}"
        ) from ex


class _Once(Generic[T]):
    # each key's work runs once: callers asking meanwhile wait for it, and
    # work that raised, or whose result `keep` turns down, is tried again by
    # the next caller
    def __init__(self) -> None:
        self._done: dict[Hashable, T] = {}
        self._running: dict[Hashable, anyio.Event] = {}

    def kept(self) -> list[T]:
        """The results kept so far, in the order their work finished."""
        return list(self._done.values())

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


async def _call_through_any(
    clients: list[Sidecar], method: str, params: dict[str, Any], within: float
) -> dict[str, Any]:
    """Call a method of a sidecar for the eval through its clients, and take the first answer the sidecar gives.

    A sidecar is reached through each model's own client, and a model's client can be closed, or stall, while its sample runs on. The eval signs its calls whichever client carries them, so any that still reaches the sidecar will do, in whatever order the clients were used and closed.

    The first client is asked alone at first. Each later one is asked as well once the one before it can't reach the sidecar, or `FALLBACK_RESERVE` before the deadline for each client still to come. A client already asked is left to finish: one that is slow to answer keeps the whole deadline, and one that stalls doesn't use it up. A sidecar that answers was reached, with an error too, and its first answer is the call's. Two clients may both reach it, so this is only for a method that can be called again: reading a sample's monitor state, and ending a sample, which has no effect the second time.

    Args:
        clients: The sidecar, as each client reaches it, the likeliest to reach it first. At least one.
        method: The method of the endpoint for evals.
        params: The method's params.
        within: The caller's deadline for the whole call, in seconds, which the caller enforces itself.

    Raises:
        SidecarCallError: If the sidecar answered with an error, or no client reached it.
    """
    if len(clients) == 1:
        return await clients[0].eval_call(method, params)
    later = len(clients) - 1
    reserve = min(FALLBACK_RESERVE, within / (2 * later))
    deadline = anyio.current_time() + within
    answers: list[dict[str, Any] | SidecarCallError] = []
    unreached: list[SidecarCallError] = []

    async def ask(sidecar: Sidecar, unreachable: anyio.Event) -> None:
        answer: dict[str, Any] | SidecarCallError
        try:
            answer = await sidecar.eval_call(method, params)
        except SidecarCallError as ex:
            if ex.code is None:
                unreached.append(ex)
                unreachable.set()
                return
            answer = ex
        answers.append(answer)
        asking.cancel_scope.cancel()

    async with anyio.create_task_group() as asking:
        for index, sidecar in enumerate(clients):
            unreachable = anyio.Event()
            asking.start_soon(ask, sidecar, unreachable)
            if index < later:
                with anyio.CancelScope(deadline=deadline - reserve * (later - index)):
                    await unreachable.wait()
    if not answers:
        raise unreached[-1]
    # raised here, outside the task group, so it arrives on its own
    if isinstance(answers[0], SidecarCallError):
        raise answers[0]
    return answers[0]


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
