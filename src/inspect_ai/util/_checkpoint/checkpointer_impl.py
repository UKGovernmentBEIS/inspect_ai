"""Active checkpoint-session implementation (heavy).

Contains the on-disk write path: fires checkpoints, runs restic backups
(host + sandboxes), writes per-checkpoint sidecars. Imports the parts
of ``inspect_ai`` that ultimately reach ``solver._task_state`` and
``dataset.Sample``, so this module must *not* be imported during
initial inspect_ai package load — only at sample-run time, via the
``_CheckpointerSetup`` async ctx mgr that the harness stashes on
:class:`ActiveSample`.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
)
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from functools import partial
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, JsonValue, TypeAdapter

from inspect_ai._util._async import tg_collect
from inspect_ai._util.file import write_text_atomic
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.trace import trace_action
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.event._event import Event
from inspect_ai.event._info import InfoEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.log._transcript_store import TranscriptEventStore
from inspect_ai.model._assistant_internal import (
    dump_sample_assistant_internal,
    init_sample_assistant_internal,
)
from inspect_ai.solver._task_state import sample_state
from inspect_ai.util._restic import (
    ResticBackupSummary,
    list_changed_files,
    run_backup,
)
from inspect_ai.util._sandbox.context import sandbox
from inspect_ai.util._span import SpanRotationScope
from inspect_ai.util._store import Store, store_jsonable

from ._host_egress import host_egress
from ._layout.host_context import (
    AGENT_STATE,
    ASSISTANT_INTERNAL,
    ATTACHMENTS,
    EVENTS,
    EVENTS_DATA,
    STORE,
)
from ._layout.sample_checkpoints_dir import (
    _list_checkpoint_ids,
    write_checkpoint_file,
)
from ._layout.schemas import Checkpoint, SnapshotDetails
from ._layout.staging_dir import sandbox_repo_dir
from ._sandbox_restic import egress_sandbox, run_sandbox_backup
from ._triggers import CheckpointTriggerKind, create_trigger
from .checkpointer import (
    Checkpointer,
    ResumeCheckpoint,
)
from .config import MAX_LISTED_FILES, ResolvedCheckpointConfig
from .hydrate import HydrationResult, hydrate
from .sandbox_paths import SandboxBackupPaths

logger = getLogger(__name__)

T = TypeVar("T")

CHECKPOINT_TRANSCRIPT_STORE = "checkpoint_transcript.sqlite"

# JSON-primitive Python types; these round-trip identically through
# `json.dumps`/`json.loads`, so `track()` can return them on resume
# without a TypeAdapter.
_JSON_PRIMITIVE_TYPES: tuple[type, ...] = (int, float, str, bool, type(None))


class _CheckpointerSetup(AbstractAsyncContextManager[Checkpointer]):
    """Pre-entry phase — stashes inputs; runs the I/O on ``__aenter__``.

    Lives on :class:`ActiveSample`. Its ``__aenter__`` performs the
    on-disk + sandbox setup and constructs a fully-formed
    :class:`_EnteredCheckpointer`. The instance is cached so re-entry
    within the same sample reuses the same live checkpointer rather
    than redoing the I/O.
    """

    def __init__(
        self,
        *,
        config: ResolvedCheckpointConfig,
        log_location: str,
        sample_id: int | str,
        epoch: int,
        resume_checkpoint: ResumeCheckpoint | None = None,
    ) -> None:
        self._config = config
        self._log_location = log_location
        self._sample_id = sample_id
        self._epoch = epoch
        self._resume_checkpoint = resume_checkpoint
        self._cached: _EnteredCheckpointer | None = None
        self._reset_transcript_store_on_next_enter = True
        # One-shot finalize gate. The first clean cm exit fires the
        # "agent_complete" checkpoint; subsequent ``__aexit__`` calls
        # (e.g. a hook re-entering ``checkpointer()`` after the agent
        # returned) are no-ops.
        self._finalized = False

    async def __aenter__(self) -> Checkpointer:
        if self._cached is not None:
            return self._cached
        result = await hydrate(
            config=self._config,
            log_location=self._log_location,
            sample_id=self._sample_id,
            epoch=self._epoch,
            resume_checkpoint=self._resume_checkpoint,
        )
        if result.host.assistant_internal is not None:
            init_sample_assistant_internal(result.host.assistant_internal)
        reset_transcript_store = self._reset_transcript_store_on_next_enter
        self._cached = _EnteredCheckpointer(
            config=self._config,
            hydration=result,
            resume_checkpoint=self._resume_checkpoint,
            reset_transcript_store=reset_transcript_store,
        )
        self._reset_transcript_store_on_next_enter = False
        return self._cached

    async def __aexit__(self, *exc: object) -> None:
        # `exc[0]` is the propagating exception type (or None on a clean exit),
        # per the context-manager protocol.
        exc_type = exc[0] if exc else None
        # Fire a final "agent_complete" checkpoint iff:
        #
        # - the cm was actually entered (hydrate ran),
        # - no exception is propagating through the exit (agent didn't
        #   raise / cancel / hit a limit),
        # - this isn't the scoring-phase resume short-circuit (the
        #   latest checkpoint is already ``agent_complete``), and
        # - we haven't already finalized (idempotent across multiple
        #   ``async with checkpointer():`` blocks in the same sample).
        if (
            self._cached is None
            or exc_type is not None
            or self._cached.attempt == "resume_for_scoring"
            or self._finalized
        ):
            return
        self._finalized = True
        cp = self._cached
        await cp._fire("agent_complete", final=True)

    def current(self) -> Checkpointer | None:
        return self._cached

    def close(self) -> None:
        if self._cached is not None:
            self._cached.close()
            self._cached = None


class CheckpointFailureLimitExceeded(RuntimeError):
    """Raised when a sample exceeds ``max_consecutive_failures``.

    Chains the underlying fire error via ``__cause__`` (``raise ... from``).
    Propagates to the agent loop, where inspect's normal sample-error
    machinery (``fail_on_error`` / ``retry_on_error``) handles it like
    any other ``Exception``.
    """


class _EnteredCheckpointer:
    """Fully-formed agent-facing checkpointer.

    Constructed by :class:`_CheckpointerSetup.__aenter__` once the
    on-disk + sandbox dependencies are in place. No lifecycle methods
    and no Optional state — the agent uses :meth:`tick`,
    :meth:`checkpoint`, :meth:`track`, and :attr:`attempt` directly.
    """

    def __init__(
        self,
        *,
        config: ResolvedCheckpointConfig,
        hydration: HydrationResult,
        resume_checkpoint: ResumeCheckpoint | None,
        reset_transcript_store: bool,
    ) -> None:
        self._config = config
        self._sample_checkpoints_dir = hydration.sample_checkpoints_dir
        self._sample_staging_dir = hydration.sample_staging_dir
        self._sample_root = hydration.sample_root
        self._context_dir = hydration.context_dir
        self._host_restic = hydration.host_restic
        self._host_repo = hydration.host_repo
        self._restic_password = hydration.restic_password
        self._sandbox_backup_paths = hydration.sandbox_backup_paths
        self._resume_checkpoint = resume_checkpoint
        self._agent_state: dict[str, Any] = (
            hydration.host.agent_state if hydration.host.agent_state is not None else {}
        )
        # Sync per-session state — turn counters, callbacks, pools.
        self._on_checkpoint_callbacks: dict[str, Callable[[], Any]] = {}
        self._turn = 0
        # Consecutive failed-fire count, against `max_consecutive_failures`.
        # Reset to 0 on any successful fire. Fresh (0) per session, so a
        # resumed attempt starts with a clean tolerance budget.
        self._consecutive_failures = 0
        # Build the concrete trigger for this session. The user's
        # config carries a frozen-dataclass spec (immutable, safely
        # shared across many samples); per-session mutable state lives
        # on the trigger instance returned by ``create_trigger``.
        self._trigger = create_trigger(config.trigger)
        # `checkpoint N` span open across the agent's current
        # work-between-fires window. Opened/closed across `span_session()`'s
        # enter/exit and rotated inside `_fire()`. A rotation scope (not
        # `span()`) because fires can run in tasks spawned after the session
        # opened (e.g. sandbox bridge RPC handlers): the scope's shared cell
        # makes the rotation visible to those tasks' events.
        self._span_scope = SpanRotationScope(type="checkpoint")
        # Keep checkpoint transcript state outside the live Transcript. The
        # live transcript may evict old events in bounded mode; this store is
        # seeded once, then updated by subscription so each checkpoint can
        # export complete host-context event files.
        self._transcript_store = TranscriptEventStore(
            Path(self._context_dir) / CHECKPOINT_TRANSCRIPT_STORE,
            reset=reset_transcript_store,
        )
        self._transcript_subscription: Callable[[], None] | None = None
        self._closed = False
        self._transcript_seeded = False
        self._ensure_transcript_subscription()
        self._seed_transcript_store(hydration)

    def close(self) -> None:
        if self._closed:
            return
        if self._transcript_subscription is not None:
            self._transcript_subscription()
            self._transcript_subscription = None
        self._transcript_store.close()
        self._closed = True

    @property
    def attempt(self) -> Literal["initial", "resume", "resume_for_scoring"]:
        if self._resume_checkpoint is None:
            return "initial"
        return self._resume_checkpoint.attempt

    async def tick(self) -> None:
        self._turn += 1
        fire = self._trigger.tick()
        if fire is not None:
            await self._fire(fire.kind, metadata=fire.metadata)

    async def checkpoint(self) -> None:
        await self._fire("manual")

    @contextlib.asynccontextmanager
    async def span_session(self) -> AsyncIterator[None]:
        await self._span_scope.open(await self._next_span_name())
        try:
            yield
        finally:
            await self._span_scope.close()

    async def _next_span_name(self) -> str:
        # Span name matches the checkpoint id this span will fire
        # under (1-indexed, same as `ckpt-NNNNN.json`). Fresh run opens
        # `checkpoint 1`; on resume of an attempt with M prior commits,
        # opens `checkpoint M+1`. A sample that ends without firing
        # leaves an unclosed span at whatever id was about to fire next.
        next_id = await _scan_next_checkpoint_id(self._sample_root)
        return f"checkpoint {next_id}"

    def track(
        self,
        key: str,
        callback: Callable[[], T],
        initial_value: T,
        *,
        value_type: type[T] | None = None,
    ) -> T:
        if key in self._on_checkpoint_callbacks:
            raise ValueError(
                f"track already registered for key {key!r}; keys must be unique"
            )
        if (
            value_type is None
            and not isinstance(initial_value, BaseModel)
            and not isinstance(initial_value, _JSON_PRIMITIVE_TYPES)
        ):
            raise TypeError(
                f"track({key!r}): initial_value of type "
                f"{type(initial_value).__name__} requires a `value_type` "
                "because its JSON round-trip is lossy. Single BaseModel "
                "instances and JSON primitives (int, float, str, bool, "
                "None) are auto-handled."
            )
        self._on_checkpoint_callbacks[key] = callback
        if key in self._agent_state:
            raw = self._agent_state.pop(key)
            if value_type is not None:
                return TypeAdapter(value_type).validate_python(raw)
            if isinstance(initial_value, BaseModel):
                # Auto-handle the single-model case — the instance's runtime
                # class is unambiguous, no caller help needed.
                return type(initial_value).model_validate(raw)
            # Primitive — saved type must still match. Catches schema drift
            # (e.g. agent code changed the tracked value's type since the
            # last fire) before the agent gets a wrong-shaped value back.
            if not isinstance(raw, type(initial_value)):
                raise TypeError(
                    f"track({key!r}): saved value is "
                    f"{type(raw).__name__}, expected "
                    f"{type(initial_value).__name__}"
                )
            value: T = raw
            return value
        return initial_value

    async def _fire(
        self,
        trigger: CheckpointTriggerKind,
        *,
        metadata: dict[str, JsonValue] | None = None,
        final: bool = False,
    ) -> None:
        """Fire a checkpoint, enforcing ``max_consecutive_failures``.

        Wraps :meth:`_fire_once` so a failed attempt is *non-fatal by
        default* (working.md §8d): the failure is recorded and the
        sample keeps running. ``max_consecutive_failures`` bounds the
        tolerance — ``None`` = unlimited (default), ``N`` = fail on the
        (N+1)th consecutive failure, ``0`` = any failure is fatal. A
        successful fire resets the count. On breach we re-raise so the
        sample fails through inspect's normal sample-error machinery.

        ``final=True`` signals this is the harness-driven
        "agent_complete" fire at solver exit — :meth:`_fire_once`
        skips opening the next checkpoint span (no more agent work
        will land in it).
        """
        try:
            await self._fire_once(trigger, metadata=metadata, final=final)
        except Exception as err:
            self._consecutive_failures += 1
            self._record_fire_failure(trigger, err)
            max_failures = self._config.max_consecutive_failures
            if max_failures is not None and self._consecutive_failures > max_failures:
                raise CheckpointFailureLimitExceeded(
                    f"checkpoint failed {self._consecutive_failures} consecutive "
                    f"time(s) (max_consecutive_failures={max_failures})"
                ) from err
        else:
            self._consecutive_failures = 0

    def _record_fire_failure(
        self, trigger: CheckpointTriggerKind, err: Exception
    ) -> None:
        """Record a failed checkpoint attempt (working.md §8d).

        Emits a durable, structured ``InfoEvent`` into the transcript
        (queryable by ``source="checkpoint"``) and logs a warning for
        operator/stderr visibility. Used for tolerated failures *and*
        the threshold-breaching one (recorded before the re-raise; the
        raise itself becomes the sample's ``ErrorEvent``).
        """
        transcript()._event(
            InfoEvent(
                source="checkpoint",
                data={
                    "event": "checkpoint_failed",
                    "trigger": trigger,
                    "turn": self._turn,
                    "consecutive_failures": self._consecutive_failures,
                    "error": f"{type(err).__name__}: {err}",
                },
            )
        )
        logger.warning(
            "Checkpoint attempt failed (trigger=%s, turn=%s, consecutive=%s): %s",
            trigger,
            self._turn,
            self._consecutive_failures,
            err,
        )

    async def _fire_once(
        self,
        trigger: CheckpointTriggerKind,
        *,
        metadata: dict[str, JsonValue] | None = None,
        final: bool = False,
    ) -> None:
        # Phase 3 (in progress): writes placeholder host context, runs
        # restic backups (host + sandboxes in parallel), then writes
        # the per-checkpoint file.
        cycle_start = time.monotonic()

        # Checkpoint file numbering continues from any checkpoint files
        # already present in the dir (incl. those FS-copied from a prior
        # eval on resume). Scanned per-fire rather than tracked in
        # memory so the count naturally bridges resumed runs without an
        # explicit handoff.
        next_checkpoint_id = await _scan_next_checkpoint_id(self._sample_root)

        # Wrap the whole fire in a trace action so an in-progress fire is
        # observable live (`inspect trace anomalies` Running Actions) and a
        # hung/cancelled/errored fire is surfaced as an anomaly. The action
        # lives here (not in `_fire`) so the error/cancel record is emitted
        # before `_fire`'s `max_consecutive_failures` handling sees it.
        with trace_action(
            logger,
            "Checkpoint",
            f"fire {_restic_tag(next_checkpoint_id)} (trigger={trigger})",
        ):
            # Close `checkpoint N` *before* `write_host_context` so the
            # ``SpanEndEvent`` lands in this checkpoint's ``events.json`` —
            # the persisted snapshot must show the span closing within it.
            await self._span_scope.end_span()
            try:
                state = sample_state()
                if not state:
                    raise RuntimeError("Checkpointer must find sample state")
                await self._write_host_context(
                    self._context_dir,
                    state.store,
                )

                # Host + each sandbox (backup → egress) in parallel. The
                # backup-then-egress pair for a given sandbox is sequential
                # (egress diffs against what backup just wrote), but the pairs
                # are independent across sandboxes and from the host backup.
                # `tg_collect` takes thunks (zero-arg callables) so coroutines
                # are only created at task-group start time.
                sandbox_items = list(self._sandbox_backup_paths.items())
                backup_funcs: list[Callable[[], Awaitable[ResticBackupSummary]]] = [
                    partial(self._backup_host, next_checkpoint_id),
                    *[
                        partial(
                            self._backup_and_egress_sandbox,
                            name,
                            spec,
                            next_checkpoint_id,
                        )
                        for name, spec in sandbox_items
                    ],
                ]
                summaries = await tg_collect(backup_funcs)
                host_info = _snapshot_info(summaries[0])
                sandbox_summaries = [
                    (name, summary)
                    for (name, _), summary in zip(sandbox_items, summaries[1:])
                ]

                # List each sandbox snapshot's added/changed files (capped at
                # MAX_LISTED_FILES). Diffs host-side against the
                # already-egressed repos in parallel, so the in-sandbox
                # exec-output limit is never hit.
                file_lists: list[tuple[list[str] | None, int]] = await tg_collect(
                    [
                        partial(
                            list_changed_files,
                            self._host_restic,
                            sandbox_repo_dir(self._sample_root, name),
                            self._restic_password,
                            summary.snapshot_id,
                            MAX_LISTED_FILES,
                        )
                        for name, summary in sandbox_summaries
                    ]
                )

                sandbox_infos = {
                    name: _snapshot_info(
                        summary, files=files, additional_files=extra or None
                    )
                    for (name, summary), (files, extra) in zip(
                        sandbox_summaries, file_lists
                    )
                }

                # Cycle duration measured up to the checkpoint file write — the
                # write itself is the commit point, so its cost lands on the
                # next cycle's clock if anywhere.
                duration_ms = int((time.monotonic() - cycle_start) * 1000)

                checkpoint = Checkpoint(
                    checkpoint_id=next_checkpoint_id,
                    trigger=trigger,
                    trigger_metadata=metadata,
                    turn=self._turn,
                    created_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    size_bytes=host_info.size_bytes
                    + sum(s.size_bytes for s in sandbox_infos.values()),
                    host=host_info,
                    sandboxes=sandbox_infos,
                )

                await write_checkpoint_file(
                    sample_checkpoints_dir=self._sample_root,
                    checkpoint=checkpoint,
                )

                # Remote destination: ship the new staging-dir files (restic
                # repo additions + checkpoint file) to the destination. The
                # checkpoint file is shipped last in the safe order — its
                # arrival at the destination is the remote commit point.
                if self._sample_staging_dir is not None:
                    await host_egress(
                        staging_dir=self._sample_staging_dir,
                        destination_dir=self._sample_checkpoints_dir,
                    )

                # Emit the CheckpointEvent now that the checkpoint file is
                # committed (locally and, when remote, at the destination too).
                # By construction the event is NOT in this fire's events.json
                # (already written above); it IS captured in the next fire's
                # events.json. On resume, hydrate synthesizes the trailing
                # event from the latest checkpoint file (working.md §8a).
                transcript()._event(CheckpointEvent.from_details(checkpoint))

            finally:
                # Reopen even if checkpointing fails after closing the prior
                # span; subsequent agent events should stay nested under a
                # checkpoint span. Skip on the harness-driven final fire —
                # there is no more agent work to land in another span — and
                # when no span session is active (fires driven outside
                # `span_session()`, e.g. in tests).
                if not final and self._span_scope.is_open:
                    await self._span_scope.begin_span(await self._next_span_name())

    async def _write_host_context(
        self,
        context_dir: str,
        store: Store,
    ) -> None:
        """Write the host context snapshot files.

        Transcript events, pools, and attachments are already accumulated in
        ``self._transcript_store`` via seeding and subscription. This method
        composes the checkpoint-owned Store / tracked agent state files with
        transcript-owned event files.
        """
        agent_state = (
            {key: cb() for key, cb in self._on_checkpoint_callbacks.items()}
            if self._on_checkpoint_callbacks
            else None
        )
        context_path = Path(context_dir)
        write_text_atomic(
            context_path / STORE,
            to_json_str_safe(store_jsonable(store)),
        )
        if agent_state is not None:
            write_text_atomic(
                context_path / AGENT_STATE,
                to_json_str_safe(agent_state),
            )
        assistant_internal = dump_sample_assistant_internal()
        if assistant_internal is not None:
            write_text_atomic(
                context_path / ASSISTANT_INTERNAL,
                to_json_str_safe(assistant_internal),
            )
        self._transcript_store.write_transcript_files(
            events_path=context_path / EVENTS,
            events_data_path=context_path / EVENTS_DATA,
            attachments_path=context_path / ATTACHMENTS,
        )

    def _seed_transcript_store(self, hydration: HydrationResult) -> None:
        if self._transcript_seeded:
            return
        ts = transcript()
        try:
            attachments = ts.attachments
            attachment_lookup = self._attachment_lookup(attachments)
            self._transcript_store.merge_message_pool(hydration.host.msg_pool)
            self._transcript_store.merge_call_pool(hydration.host.call_pool)
            seeded_event_ids: set[str] = set()
            if hydration.host.condensed_events:
                for event in hydration.host.condensed_events:
                    if event.uuid is None:
                        continue
                    seeded_event_ids.add(event.uuid)
                    if not self._transcript_store.has_event(event.uuid):
                        self._transcript_store.merge_event(event, attachment_lookup)
            history = ts.history
            if history.resident_events_truncated:
                history_provider = history.provider
                if history_provider is None:
                    raise RuntimeError(
                        "Cannot seed transcript events from a truncated Transcript. "
                        "Create the checkpointer before bounded transcript eviction starts."
                    )
                history_provider.export_transcript_events(self._transcript_store)
            else:
                for event in history.resident_events:
                    if event.uuid in seeded_event_ids:
                        continue
                    self._transcript_store.merge_event(event, attachment_lookup)
            self._transcript_store.merge_attachments(attachments)
            self._transcript_seeded = True
        except Exception:
            self.close()
            raise

    def _ensure_transcript_subscription(self) -> None:
        if self._transcript_subscription is not None:
            return
        self._transcript_subscription = transcript()._subscribe(
            self._track_transcript_event
        )

    def _track_transcript_event(self, event: Event) -> None:
        self._transcript_store.merge_event(
            event, self._attachment_lookup(transcript().attachments)
        )

    def _attachment_lookup(
        self, attachments: Mapping[str, str]
    ) -> Callable[[str], str | None]:
        return lambda ref: (
            self._transcript_store.attachment(ref) or attachments.get(ref)
        )

    async def _backup_host(self, checkpoint_id: int) -> ResticBackupSummary:
        return await run_backup(
            self._host_restic,
            self._host_repo,
            self._restic_password,
            self._context_dir,
            _restic_tag(checkpoint_id),
        )

    async def _backup_and_egress_sandbox(
        self, name: str, spec: SandboxBackupPaths, checkpoint_id: int
    ) -> ResticBackupSummary:
        env = sandbox(name)
        tag = _restic_tag(checkpoint_id)
        summary = await run_sandbox_backup(
            env, self._restic_password, spec.include, tag, exclude=spec.exclude
        )
        dest_repo = sandbox_repo_dir(self._sample_root, name)
        await egress_sandbox(
            env,
            dest_repo=dest_repo,
            password=self._restic_password,
            host_restic=self._host_restic,
            tag=tag,
            snapshot_id=summary.snapshot_id,
        )
        return summary


async def _scan_next_checkpoint_id(sample_root: str) -> int:
    """Return the next checkpoint file ordinal for this sample.

    Walks the sample root for ``ckpt-NNNNN.json`` filenames and returns
    ``max(N) + 1`` — or 1 if none exist yet. Used by ``_fire`` so the
    count continues across resume without an explicit handoff through
    ``_hydrate``.
    """
    ids = await _list_checkpoint_ids(sample_root)
    next_id = (max(ids) + 1) if ids else 1
    return next_id


def _restic_tag(checkpoint_id: int) -> str:
    """Format the restic ``--tag`` for a checkpoint's snapshots.

    Matches the checkpoint file's ``ckpt-NNNNN`` prefix, so a tag and a
    checkpoint file share the same N for the same checkpoint.
    """
    return f"ckpt-{checkpoint_id:05d}"


def _snapshot_info(
    summary: ResticBackupSummary,
    files: list[str] | None = None,
    additional_files: int | None = None,
) -> SnapshotDetails:
    return SnapshotDetails(
        snapshot_id=summary.snapshot_id,
        size_bytes=summary.data_added_packed,
        duration_ms=int(summary.total_duration * 1000),
        files=files,
        additional_files=additional_files,
    )
