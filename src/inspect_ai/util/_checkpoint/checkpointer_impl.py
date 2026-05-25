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
)
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from functools import partial
from logging import getLogger
from pathlib import Path
from typing import Any, TypeVar

import anyio
from pydantic import BaseModel, TypeAdapter

from inspect_ai._util._async import tg_collect
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.event._event import Event
from inspect_ai.log._transcript import transcript
from inspect_ai.solver._task_state import sample_state
from inspect_ai.util._checkpoint._transcript_store import (
    CHECKPOINT_TRANSCRIPT_STORE,
    CheckpointTranscriptStore,
)
from inspect_ai.util._restic import ResticBackupSummary, run_backup
from inspect_ai.util._sandbox.context import sandbox
from inspect_ai.util._span import span
from inspect_ai.util._store import Store, store_jsonable

from ._layout import CheckpointDetails, SnapshotDetails, write_sidecar
from ._sandbox_restic import egress_sandbox, run_sandbox_backup
from ._triggers import CheckpointTriggerKind, create_trigger
from .checkpointer import (
    Checkpointer,
    ResumeCheckpoint,
)
from .config import ResolvedCheckpointConfig
from .hydrate import HydrationResult, hydrate

logger = getLogger(__name__)

T = TypeVar("T")

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
        return None

    def close(self) -> None:
        if self._cached is not None:
            self._cached.close()
            self._cached = None


class _EnteredCheckpointer:
    """Fully-formed agent-facing checkpointer.

    Constructed by :class:`_CheckpointerSetup.__aenter__` once the
    on-disk + sandbox dependencies are in place. No lifecycle methods
    and no Optional state — the agent uses :meth:`tick`,
    :meth:`checkpoint`, :meth:`track`, and :attr:`is_resuming` directly.
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
        self._sample_working_dir = hydration.sample_working_dir
        self._host_restic = hydration.host_restic
        self._host_repo = hydration.host_repo
        self._restic_password = hydration.restic_password
        self._resume_checkpoint = resume_checkpoint
        self._agent_state: dict[str, Any] = (
            hydration.host.agent_state if hydration.host.agent_state is not None else {}
        )
        # Sync per-session state — turn counters, callbacks, pools.
        self._on_checkpoint_callbacks: dict[str, Callable[[], Any]] = {}
        self._turn = 0
        # Build the concrete trigger for this session. The user's
        # config carries a frozen-dataclass spec (immutable, safely
        # shared across many samples); per-session mutable state lives
        # on the trigger instance returned by ``create_trigger``.
        self._trigger = create_trigger(config.trigger)
        # `checkpoint N` span open across the agent's current
        # work-between-fires window. Owned across `span_session()`'s
        # enter/exit and rotated inside `_fire()`.
        self._current_span_cm: AbstractAsyncContextManager[None] | None = None
        # Keep checkpoint transcript state outside the live Transcript. The
        # live transcript may evict old events in bounded mode; this store is
        # seeded once, then updated by subscription so each checkpoint can
        # export complete host-context event files.
        self._transcript_store = CheckpointTranscriptStore(
            Path(self._sample_working_dir) / CHECKPOINT_TRANSCRIPT_STORE,
            reset=reset_transcript_store,
        )
        self._transcript_subscription: Callable[[], None] | None = None
        self._closed = False
        self._transcript_seeded = False
        self._seed_transcript_store(hydration)
        self._ensure_transcript_subscription()

    def close(self) -> None:
        if self._closed:
            return
        if self._transcript_subscription is not None:
            self._transcript_subscription()
            self._transcript_subscription = None
        self._transcript_store.close()
        self._closed = True

    @property
    def is_resuming(self) -> bool:
        return self._resume_checkpoint is not None

    async def tick(self) -> None:
        self._turn += 1
        kind = self._trigger.tick()
        if kind is not None:
            await self._fire(kind)

    async def checkpoint(self) -> None:
        await self._fire("manual")

    @contextlib.asynccontextmanager
    async def span_session(self) -> AsyncIterator[None]:
        await self._open_next_span()
        try:
            yield
        finally:
            await self._close_current_span()

    async def _open_next_span(self) -> None:
        # Span name matches the sidecar id this span will fire under
        # (1-indexed, same as `ckpt-NNNNN.json`). Fresh run opens
        # `checkpoint 1`; on resume of an attempt with M prior commits,
        # opens `checkpoint M+1`. A sample that ends without firing
        # leaves an unclosed span at whatever id was about to fire next.
        next_id = await anyio.to_thread.run_sync(
            _scan_next_checkpoint_id, self._sample_checkpoints_dir
        )
        cm = span(name=f"checkpoint {next_id}", type="checkpoint")
        await cm.__aenter__()
        self._current_span_cm = cm

    async def _close_current_span(self) -> None:
        if self._current_span_cm is None:
            return
        cm, self._current_span_cm = self._current_span_cm, None
        await cm.__aexit__(None, None, None)

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

    async def _fire(self, trigger: CheckpointTriggerKind) -> None:
        # Phase 3 (in progress): writes placeholder host context, runs
        # restic backups (host + sandboxes in parallel), then writes
        # the per-checkpoint sidecar.
        cycle_start = time.monotonic()

        # Sidecar numbering continues from any sidecars already present
        # in the dir (incl. those FS-copied from a prior eval on resume).
        # Scanned per-fire rather than tracked in memory so the count
        # naturally bridges resumed runs without an explicit handoff.
        next_checkpoint_id = await anyio.to_thread.run_sync(
            _scan_next_checkpoint_id, self._sample_checkpoints_dir
        )

        # Close `checkpoint N` *before* `write_host_context` so the
        # ``SpanEndEvent`` lands in this checkpoint's ``events.json`` —
        # the persisted snapshot must show the span closing within it.
        await self._close_current_span()
        try:
            state = sample_state()
            if not state:
                raise RuntimeError("Checkpointer must find sample state")
            await self._write_host_context(
                self._sample_working_dir,
                state.store,
            )

            # Host + each sandbox (backup → egress) in parallel. The
            # backup-then-egress pair for a given sandbox is sequential
            # (egress diffs against what backup just wrote), but the pairs
            # are independent across sandboxes and from the host backup.
            # `tg_collect` takes thunks (zero-arg callables) so coroutines
            # are only created at task-group start time.
            sandbox_items = list((self._config.sandbox_paths or {}).items())
            backup_funcs: list[Callable[[], Awaitable[ResticBackupSummary]]] = [
                partial(self._backup_host, next_checkpoint_id),
                *[
                    partial(
                        self._backup_and_egress_sandbox,
                        name,
                        paths,
                        next_checkpoint_id,
                    )
                    for name, paths in sandbox_items
                ],
            ]
            summaries = await tg_collect(backup_funcs)
            host_info = _snapshot_info(summaries[0])
            sandbox_infos = {
                name: _snapshot_info(summary)
                for (name, _), summary in zip(sandbox_items, summaries[1:])
            }

            # Cycle duration measured up to the sidecar write — the write
            # itself is the commit point, so its cost lands on the next
            # cycle's clock if anywhere.
            duration_ms = int((time.monotonic() - cycle_start) * 1000)

            sidecar = CheckpointDetails(
                checkpoint_id=next_checkpoint_id,
                trigger=trigger,
                turn=self._turn,
                created_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                size_bytes=host_info.size_bytes
                + sum(s.size_bytes for s in sandbox_infos.values()),
                host=host_info,
                sandboxes=sandbox_infos,
            )

            await write_sidecar(
                sample_checkpoints_dir=self._sample_checkpoints_dir,
                sidecar=sidecar,
            )

            # Emit the CheckpointEvent now that the sidecar is committed.
            # By construction the event is NOT in this fire's events.json
            # (already written above); it IS captured in the next fire's
            # events.json. On resume, hydrate synthesizes the trailing
            # event from the latest sidecar (working.md §8a).
            transcript()._event(CheckpointEvent.from_details(sidecar))
        finally:
            # Reopen even if checkpointing fails after closing the prior span;
            # subsequent agent events should stay nested under a checkpoint span.
            await self._open_next_span()

    async def _write_host_context(
        self,
        sample_working_dir: str,
        store: Store,
    ) -> None:
        """Write the host context snapshot files.

        Transcript events, pools, and attachments are already accumulated in
        ``self._transcript_store`` via seeding and subscription. This method only
        captures the current Store / tracked agent state and asks the transcript
        store to export a complete host context.
        """
        agent_state = (
            {key: cb() for key, cb in self._on_checkpoint_callbacks.items()}
            if self._on_checkpoint_callbacks
            else None
        )
        self._transcript_store.export_snapshot_files(
            sample_working_dir,
            store_json=store_jsonable(store),
            agent_state=agent_state,
        )

    def _seed_transcript_store(self, hydration: HydrationResult) -> None:
        if self._transcript_seeded:
            return
        ts = transcript()
        try:
            attachments = ts.attachments
            self._transcript_store.merge_message_pool(hydration.host.msg_pool)
            self._transcript_store.merge_call_pool(hydration.host.call_pool)
            seeded_event_ids: set[str] = set()
            if hydration.host.condensed_events:
                self._transcript_store.merge_events(
                    hydration.host.condensed_events, attachments
                )
                seeded_event_ids = {
                    event.uuid
                    for event in hydration.host.condensed_events
                    if event.uuid is not None
                }
            if ts.resident_events_truncated:
                history_provider = ts._history_provider
                if history_provider is None:
                    raise RuntimeError(
                        "Cannot seed checkpoint events from a truncated Transcript. "
                        "Create the checkpointer before bounded transcript eviction starts."
                    )
                history_provider.import_checkpoint_events(self._transcript_store)
            else:
                for event in ts.resident_events:
                    if event.uuid in seeded_event_ids:
                        continue
                    self._transcript_store.merge_event(event, attachments.get)
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
        self._transcript_store.merge_event(event, transcript().attachments.get)

    async def _backup_host(self, checkpoint_id: int) -> ResticBackupSummary:
        return await run_backup(
            self._host_restic,
            self._host_repo,
            self._restic_password,
            self._sample_working_dir,
            _restic_tag(checkpoint_id),
        )

    async def _backup_and_egress_sandbox(
        self, name: str, paths: list[str], checkpoint_id: int
    ) -> ResticBackupSummary:
        env = sandbox(name)
        tag = _restic_tag(checkpoint_id)
        summary = await run_sandbox_backup(env, self._restic_password, paths, tag)
        dest_repo = f"{self._sample_checkpoints_dir}/sandboxes/{name}"
        await egress_sandbox(
            env,
            dest_repo=dest_repo,
            password=self._restic_password,
            host_restic=self._host_restic,
            tag=tag,
            snapshot_id=summary.snapshot_id,
        )
        return summary


def _scan_next_checkpoint_id(sample_checkpoints_dir: str) -> int:
    """Return the next sidecar ordinal for this sample.

    Walks the sample checkpoints dir for ``ckpt-NNNNN.json`` filenames
    and returns ``max(N) + 1`` — or 1 if none exist yet. Used by
    ``_fire`` so the count continues across resume without an explicit
    handoff through ``_hydrate``.
    """
    sample_dir = Path(sample_checkpoints_dir)
    if not sample_dir.is_dir():
        return 1
    ids = [int(p.stem.removeprefix("ckpt-")) for p in sample_dir.glob("ckpt-*.json")]
    return (max(ids) + 1) if ids else 1


def _restic_tag(checkpoint_id: int) -> str:
    """Format the restic ``--tag`` for a checkpoint's snapshots.

    Matches the sidecar filename's ``ckpt-NNNNN`` prefix, so a tag and a
    sidecar share the same N for the same checkpoint.
    """
    return f"ckpt-{checkpoint_id:05d}"


def _snapshot_info(summary: ResticBackupSummary) -> SnapshotDetails:
    return SnapshotDetails(
        snapshot_id=summary.snapshot_id,
        size_bytes=summary.data_added_packed,
        duration_ms=int(summary.total_duration * 1000),
    )
