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
import copy
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from functools import partial
from logging import getLogger
from pathlib import Path
from typing import Any, TypeVar

import anyio
from pydantic import BaseModel, JsonValue, TypeAdapter

from inspect_ai._util._async import tg_collect
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

from ._sandbox_restic import egress_sandbox, run_sandbox_backup
from .checkpointer import (
    Checkpointer,
    ResumeCheckpoint,
)
from .config import ResolvedCheckpointConfig
from .hydrate import HydrationResult, hydrate
from .layout import SnapshotInfo, host_context, write_sidecar
from .triggers import CheckpointTriggerKind

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
        # Deep-copy the configured trigger so each session has its own
        # state. The user's config (Sample/Task/eval) may be shared
        # across many samples; the trigger holds per-session state
        # (turn counter, time of last fire) and would otherwise mix
        # between samples.
        self._trigger = copy.deepcopy(config.trigger)
        # `checkpoint N` span open across the agent's current
        # work-between-fires window. Owned across `span_session()`'s
        # enter/exit and rotated inside `_fire()`.
        self._current_span_cm: AbstractAsyncContextManager[None] | None = None
        # Persisted across fires: each fire processes only the new event slice
        # and appends to these accumulators. Safe because checkpoints fire at
        # turn boundaries, after which prior events are immutable.
        # On resume, hydrate seeds the pools (and `_events_consumed` to the
        # transcript-event count of pushed history) so the next fire writes
        # a snapshot containing old + new events.
        self._condensed_events: list[Event] = list(hydration.host.condensed_events)
        self._msg_pool: list[ChatMessage] = list(hydration.host.msg_pool)
        self._msg_index: dict[str, int] = _build_msg_index(self._msg_pool)
        self._call_pool: list[JsonValue] = list(hydration.host.call_pool)
        self._call_index: dict[str, int] = _build_call_index(self._call_pool)
        self._events_consumed = len(self._condensed_events)

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

        await write_sidecar(
            sample_checkpoints_dir=self._sample_checkpoints_dir,
            checkpoint_id=next_checkpoint_id,
            trigger=trigger,
            turn=self._turn,
            host=host_info,
            sandboxes=sandbox_infos,
            duration_ms=duration_ms,
        )

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
        new = events[self._events_consumed :]
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


def _snapshot_info(summary: ResticBackupSummary) -> SnapshotInfo:
    return SnapshotInfo(
        snapshot_id=summary.snapshot_id,
        size_bytes=summary.data_added_packed,
        duration_ms=int(summary.total_duration * 1000),
    )
