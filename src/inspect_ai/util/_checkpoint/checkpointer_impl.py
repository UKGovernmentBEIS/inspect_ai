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
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from functools import partial
from logging import getLogger
from pathlib import Path
from typing import Any, TypeVar

import anyio
from pydantic import BaseModel, JsonValue, TypeAdapter

from inspect_ai._util._async import tg_collect
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.event._event import Event
from inspect_ai.log._pool import (
    _build_call_index,
    _build_msg_index,
    condense_model_event_calls,
    condense_model_event_inputs,
)
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.solver._task_state import sample_state
from inspect_ai.util._restic import ResticBackupSummary, run_backup
from inspect_ai.util._sandbox.context import sandbox
from inspect_ai.util._span import span
from inspect_ai.util._store import Store, store_jsonable

from ._layout import CheckpointDetails, SnapshotDetails, host_context, write_sidecar
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
        self._cached = _EnteredCheckpointer(
            config=self._config,
            hydration=result,
            resume_checkpoint=self._resume_checkpoint,
        )
        return self._cached

    async def __aexit__(self, *exc: object) -> None:
        return None


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
        # Persisted across fires: each fire processes only the new event slice
        # and appends to these accumulators. Safe because checkpoints fire at
        # turn boundaries, after which prior events are immutable.
        #
        # The accumulator + `_events_consumed` exist for performance — the
        # next condense uses the prior pool as a starting point rather than
        # re-walking the full transcript each fire. Revisit if profiling
        # later shows the from-scratch alternative is fine at expected scale.
        #
        # `_events_consumed` is set lazily by the first `_open_next_span()`
        # call to the transcript index where that first `span_begin:
        # checkpoint` will land — so pre-first-span setup events (system
        # message, sample init chatter) never enter the accumulator, and
        # the persisted snapshot contains only checkpoint spans + contents.
        # On resume, hydrate seeds the pools and pushes prior span content
        # into the transcript; the lazy init then captures the index of the
        # new `span_begin checkpoint M+1` so the next fire's slice is just
        # the new span.
        self._condensed_events: list[Event] = list(hydration.host.condensed_events)
        self._msg_pool: list[ChatMessage] = list(hydration.host.msg_pool)
        self._msg_index: dict[str, int] = _build_msg_index(self._msg_pool)
        self._call_pool: list[JsonValue] = list(hydration.host.call_pool)
        self._call_index: dict[str, int] = _build_call_index(self._call_pool)
        self._events_consumed: int | None = None

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
        # First-span lazy init for `_events_consumed`: capture the
        # transcript index where the about-to-open `span_begin` will land
        # so the persisted snapshot starts at the first checkpoint span.
        if self._events_consumed is None:
            self._events_consumed = len(transcript().events)
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
            raw = self._agent_state[key]
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

        state = sample_state()
        if not state:
            raise RuntimeError("Checkpointer must find sample state")
        ts = transcript()
        await self._write_host_context(
            self._sample_working_dir,
            ts.events,
            ts.attachments,
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
                    self._backup_and_egress_sandbox, name, paths, next_checkpoint_id
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

        # Sidecar is committed; open the next `checkpoint N+1` span so
        # subsequent agent events nest under it.
        await self._open_next_span()

    async def _write_host_context(
        self,
        sample_working_dir: str,
        events: Sequence[Event],
        attachments: Mapping[str, str],
        store: Store,
    ) -> None:
        """Write the host context across up to five files.

        - ``events.json`` — condensed events; ModelEvent inputs / calls
          replaced with refs into the pools below.
        - ``events_data.json`` — ``{messages, calls}`` dedup pools.
        - ``attachments.json`` — hash → original-content pool that
          ``ModelEvent.call`` refs (`attachment://<hash>`) point into.
          Captured live by ``Transcript._process_event``; serialized
          here so the snapshot is self-contained.
        - ``store.json`` — Store key/value as a single JSON object.
        - ``agent_state.json`` — agent-defined property bag, written
          only when the agent registered at least one callback via
          :meth:`Checkpointer.track`. Each registered key becomes a
          top-level field in the dict. The agent's conversation
          messages typically live here (e.g. under the ``"messages"``
          key) — the protocol no longer privileges them as a top-level
          file. Presence on disk signals opt-in.
        """
        # Pool ModelEvent input + call messages — the big O(N²) redundancy.
        # We process only the new event slice each fire and append to the
        # accumulators on the session, so total hashing work is O(N) over a
        # sample rather than O(N) per fire. Safe because checkpoints fire at
        # turn boundaries, after which prior events are immutable.
        # Attachments come pre-extracted on the transcript (call payloads
        # >100 chars are rewritten to attachment:// refs as events flow in,
        # with originals in transcript.attachments) — we persist that pool
        # here so resume can resolve the refs.
        # `_events_consumed` is set lazily by the first `_open_next_span()`,
        # which runs in `span_session().__aenter__()` before any fire can
        # happen — so it's guaranteed non-None here.
        assert self._events_consumed is not None
        # Filter the new slice: persisted events.json contains only events
        # inside checkpoint / prior_run spans (inclusive of begin/end) plus
        # CheckpointEvents. Stray events that land between checkpoint spans
        # (e.g. `sandbox:exec` / `sandbox:read_file` emitted by restic
        # operations during the fire's backup phase) stay in the live
        # transcript but don't get persisted. See working.md §5.
        new = _filter_persisted_events(events[self._events_consumed :])
        if new:
            cond, self._msg_index, new_msgs = condense_model_event_inputs(
                new, len(self._msg_pool), self._msg_index
            )
            self._msg_pool.extend(m for _, m in new_msgs)
            cond, self._call_index, new_calls = condense_model_event_calls(
                cond, len(self._call_pool), self._call_index
            )
            self._call_pool.extend(c for _, c in new_calls)
            self._condensed_events.extend(cond)
        # Advance regardless of whether the filtered slice was empty:
        # this fire's events have been consumed from the live transcript's
        # perspective even if none made it into the persisted snapshot.
        self._events_consumed = len(events)
        agent_state = (
            {key: cb() for key, cb in self._on_checkpoint_callbacks.items()}
            if self._on_checkpoint_callbacks
            else None
        )
        await host_context.write(
            sample_working_dir,
            host_context.HostContext(
                condensed_events=self._condensed_events,
                msg_pool=self._msg_pool,
                call_pool=self._call_pool,
                attachments=dict(attachments),
                store=store_jsonable(store),
                agent_state=agent_state,
            ),
        )

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


def _filter_persisted_events(events: Sequence[Event]) -> list[Event]:
    r"""Keep only events that belong in the persisted ``events.json``.

    Three things pass through:

    - Events inside a ``type="checkpoint"`` span (inclusive of the
      span_begin/span_end).
    - Events inside a ``type="prior_run"`` span (inclusive).
    - ``CheckpointEvent``\ s, even when between checkpoint spans.

    Everything else is dropped — in practice the ``sandbox:exec`` and
    ``sandbox:read_file`` events emitted by restic operations during
    the fire's backup phase, which land in the live transcript between
    ``span_end checkpoint N`` and ``span_begin checkpoint N+1``. They
    stay in the live transcript (visible in ``inspect view`` of the
    running eval) but don't get persisted.
    """
    result: list[Event] = []
    # Track currently-open tracked-span ids. Depth = len(tracked_open_ids).
    # We track checkpoint + prior_run spans; everything inside (including
    # nested non-tracked spans like bash/tool) is kept.
    tracked_open_ids: set[str] = set()
    for e in events:
        if e.event == "span_begin":
            type_ = getattr(e, "type", None)
            if type_ in ("checkpoint", "prior_run"):
                tracked_open_ids.add(e.id)
                result.append(e)
            elif tracked_open_ids:
                # Nested non-tracked span inside a tracked one — keep.
                result.append(e)
            # else: stray span_begin outside any tracked span — drop.
        elif e.event == "span_end":
            id_ = getattr(e, "id", None)
            if id_ in tracked_open_ids:
                tracked_open_ids.discard(id_)
                result.append(e)
            elif tracked_open_ids:
                # Inner span_end inside a tracked span — keep.
                result.append(e)
            # else: stray span_end outside any tracked span — drop.
        elif e.event == "checkpoint":
            # CheckpointEvent — always keep, whether inside a tracked
            # span or not (in practice it lands between checkpoint spans).
            result.append(e)
        elif tracked_open_ids:
            # Inside a tracked span — keep.
            result.append(e)
        # else: stray event outside any tracked span — drop.
    return result
