"""Per-sample checkpoint hydration.

``_hydrate`` is called from ``_CheckpointerSetup.__aenter__`` to set up the
on-disk + in-sandbox state for the sample's checkpointer and return
everything :class:`_EnteredCheckpointer` needs at construction.

For fresh samples (no :class:`ResumeCheckpoint`) ``_hydrate`` mints a
password and inits empty restic repos (host + each sandbox). For
resumed samples it copies the old sample checkpoints dir into the
new sample root, restic-restores the latest snapshot into the new
context subdir, ingresses each sandbox repo back into its container
and restores in-container state, loads ``agent_state.json``, and
pushes restored events/attachments/store into the live framework
state.

Sample-root selection:

- Local destination → sample root = sample checkpoints dir; no
  staging dir.
- Remote destination → sample root = sample staging dir (host-local);
  host egress (out of scope here) ships state to the remote sample
  checkpoints dir at fire time.

Structure (see ``design/plans/checkpointing-hydration.md`` §3):

- ``_hydrate`` (orchestrator): Phase 1 prologue (paths / dirs /
  ``sample.json`` / restic binary), then Phase 2 with ``_hydrate_host``
  and ``_hydrate_sandboxes`` in parallel.
- ``_hydrate_host``: host repo init or restore.
- ``_hydrate_sandboxes``: dispatches ``_hydrate_sandbox`` per sandbox in
  parallel.
- ``_hydrate_sandbox``: one sandbox's repo init or restore.

This module owns *only* the I/O-and-state side of hydration. The
agent-facing :class:`_EnteredCheckpointer` is constructed by the caller
using the returned :class:`_HydrationResult`.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from functools import partial
from logging import getLogger
from pathlib import Path

import anyio
from pydantic import JsonValue
from shortuuid import uuid as shortuuid

from inspect_ai._util._async import tg_collect
from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.file import file, local_path
from inspect_ai._util.trace import trace_action, trace_message
from inspect_ai.event._checkpoint import CheckpointEvent
from inspect_ai.event._event import Event
from inspect_ai.event._pool import materialize_pooled_events
from inspect_ai.event._span import SpanBeginEvent, SpanEndEvent
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.solver._task_state import sample_state
from inspect_ai.util._restic import init_repo, resolve_restic, restore_repo
from inspect_ai.util._restic.ops import restic_env
from inspect_ai.util._sandbox.context import sandbox

from ._host_egress import seed_manifest
from ._layout import host_context
from ._layout.eval_checkpoints_dir import eval_checkpoints_dir
from ._layout.sample_checkpoints_dir import (
    ensure_restic_config,
    ensure_sample_checkpoints_dir,
    scan_latest_committed_id,
)
from ._layout.schemas import Checkpoint
from ._layout.staging_dir import (
    ensure_context_dir,
    ensure_sample_staging_dir,
    host_repo_dir,
    is_remote_destination,
    sandbox_repo_dir,
)
from ._sandbox_restic import ingress_sandbox, init_sandbox_repo, inject_restic
from .checkpointer import ResumeCheckpoint
from .config import ResolvedCheckpointConfig

logger = getLogger(__name__)
_DISABLE_ENV_VAR = "INSPECT_CHECKPOINT_VALIDATE_DISABLE"
_SYNTHETIC_RESTORED_SPAN_END_METADATA = {
    "checkpoint": {
        "synthetic": True,
        "reason": "restored_open_span",
        "timestamp_source": "last_restored_event",
    }
}


@dataclass
class _HostHydrationResult:
    """Returned by ``_hydrate_host``; consumed by ``_hydrate`` orchestrator.

    Fields are populated from the restored ``<working_dir>/*.json`` files
    on resume; left at their fresh-run defaults otherwise.
    """

    agent_state: dict[str, JsonValue] | None = None
    """From ``agent_state.json`` — values returned by ``track()`` on resume."""

    condensed_events: list[Event] = field(default_factory=list)
    """From ``events.json`` — seeds ``_EnteredCheckpointer._condensed_events``
    so the next fire writes a cumulative snapshot."""

    msg_pool: list[ChatMessage] = field(default_factory=list)
    """From ``events_data.json[messages]`` — seeds the dedup pool."""

    call_pool: list[JsonValue] = field(default_factory=list)
    """From ``events_data.json[calls]`` — seeds the dedup pool."""

    attachments: dict[str, str] = field(default_factory=dict)
    """From ``attachments.json`` — resolves ``attachment://`` refs."""

    store: dict[str, JsonValue] = field(default_factory=dict)
    """From ``store.json`` — restored into the sample Store."""


@dataclass
class HydrationResult:
    """Everything ``_EnteredCheckpointer`` needs at construction."""

    sample_checkpoints_dir: str
    """Destination — local or remote (e.g. ``s3://...``)."""

    sample_staging_dir: str | None
    """Host-local staging dir; ``None`` when destination is local."""

    sample_root: str
    """Where restic and checkpoint files are first materialized. Equals
    ``sample_checkpoints_dir`` when local, ``sample_staging_dir`` when
    remote."""

    context_dir: str
    """Per-sample context subdir — restic's backup source."""

    host_restic: Path
    host_repo: str
    """Path to the host restic repo: ``<sample_root>/restic/host/``."""

    restic_password: str
    host: _HostHydrationResult


async def hydrate(
    *,
    config: ResolvedCheckpointConfig,
    log_location: str,
    sample_id: int | str,
    epoch: int,
    resume_checkpoint: ResumeCheckpoint | None,
) -> HydrationResult:
    # "hydrate" restores prior state; a fresh sample has nothing to
    # restore — it's first-time provisioning (inject restic + init empty
    # repos). Pick the verb (and trace-action category) accordingly so
    # the log doesn't read "hydrate ... fresh". See working.md §8d notes.
    verb = "hydrate" if resume_checkpoint else "provision"
    action = "Checkpoint Hydrate" if resume_checkpoint else "Checkpoint Provision"

    # Orchestrator-level start marker (the per-step stall-prone I/O is
    # covered by the per-step trace actions below, grouped under `action`).
    trace_message(
        logger,
        "Checkpoint",
        f"{verb} start: sample={sample_id} epoch={epoch} "
        + (
            f"resume from {resume_checkpoint.sample_checkpoints_dir}"
            if resume_checkpoint
            else "fresh"
        ),
    )

    # Phase 1: synchronous prologue. After this completes, every Phase 2
    # function can read the password from <sample_root>/sample.json
    # and reach restic on the host.
    new_eval_checkpoints_dir = eval_checkpoints_dir(
        log_location, config.checkpoints_location
    )
    new_sample_checkpoints_dir = await ensure_sample_checkpoints_dir(
        new_eval_checkpoints_dir, sample_id, epoch
    )

    # Sample root: where restic + checkpoint files are first materialized.
    # Remote destination → host-local staging; local → destination directly.
    if is_remote_destination(new_sample_checkpoints_dir):
        sample_staging = await ensure_sample_staging_dir(log_location, sample_id, epoch)
        sample_root = sample_staging
    else:
        sample_staging = None
        sample_root = new_sample_checkpoints_dir

    sample_context_dir = await ensure_context_dir(sample_root)

    if resume_checkpoint:
        # Bring the cross-cutting bits over first so `ensure_restic_config`
        # reads the inherited password instead of minting a fresh one,
        # and so the checkpoint file count continues from the prior run.
        await _fs_copy_cross_cutting(
            resume_checkpoint.sample_checkpoints_dir,
            sample_root,
        )
    restic_config = await ensure_restic_config(sample_root)
    host_restic = await resolve_restic()
    host_repo = host_repo_dir(sample_root)

    # On resume, find the highest committed checkpoint id (checkpoint
    # files are the source of truth — see ``Checkpoint`` design notes).
    # Any restic snapshot tagged ``ckpt-NNNNN`` with N > this id is an
    # orphan from an interrupted fire that completed its backup but
    # never wrote its checkpoint file; ``_hydrate_host`` /
    # ``_hydrate_sandbox`` drop those below so ``restic restore latest``
    # picks the committed snapshot.
    latest_committed_id: int | None = None
    if resume_checkpoint:
        latest_committed_id = await scan_latest_committed_id(sample_root)

    # Phase 2: host + sandboxes in parallel. Host work runs alongside
    # the per-sandbox fan-out; each sandbox's work is independent of
    # the others. Using a task group directly (rather than `tg_collect`)
    # because the two branches have different return types — only the
    # host branch produces a result that flows to `_EnteredCheckpointer`.
    host_result: _HostHydrationResult | None = None

    async def _run_host() -> None:
        nonlocal host_result
        host_result = await _hydrate_host(
            resume=resume_checkpoint,
            host_restic=host_restic,
            host_repo=host_repo,
            restic_password=restic_config.restic_password,
            sample_root=sample_root,
            context_dir=sample_context_dir,
            latest_committed_id=latest_committed_id,
            action=action,
        )

    async with anyio.create_task_group() as tg:
        tg.start_soon(_run_host)
        tg.start_soon(
            _hydrate_sandboxes,
            resume_checkpoint,
            config.sandbox_paths or {},
            restic_config.restic_password,
            sample_root,
            host_restic,
            latest_committed_id,
            action,
        )
    assert host_result is not None  # task group ran _run_host to completion

    # Resume into a remote-destination staging dir: pre-populate the
    # egress manifest with every file we just downloaded from the
    # destination (everything in staging except the context subdir,
    # which is local-only restic input). Without this, the first
    # post-resume fire's host_egress diff would consider the whole
    # resume payload "new" and re-ship it.
    if resume_checkpoint and sample_staging is not None:
        await anyio.to_thread.run_sync(seed_manifest, sample_staging)

    trace_message(
        logger, "Checkpoint", f"{verb} complete: sample={sample_id} epoch={epoch}"
    )

    return HydrationResult(
        sample_checkpoints_dir=new_sample_checkpoints_dir,
        sample_staging_dir=sample_staging,
        sample_root=sample_root,
        context_dir=sample_context_dir,
        host_restic=host_restic,
        host_repo=host_repo,
        restic_password=restic_config.restic_password,
        host=host_result,
    )


async def _hydrate_host(
    *,
    resume: ResumeCheckpoint | None,
    host_restic: Path,
    host_repo: str,
    restic_password: str,
    sample_root: str,
    context_dir: str,
    latest_committed_id: int | None,
    action: str,
) -> _HostHydrationResult:
    if resume is None:
        with trace_action(logger, action, "host init"):
            await init_repo(host_restic, host_repo, restic_password)
        return _HostHydrationResult()

    # Resume: FS-copy the old host repo into the new one (preserves
    # snapshot IDs and password), drop any orphan snapshots beyond the
    # latest committed checkpoint file, restic-restore the latest
    # snapshot into the new context subdir, then load the JSON files
    # and push framework state into the live Transcript + Store.
    await _fs_copy_repo(
        resume.sample_checkpoints_dir,
        "restic/host",
        host_repo,
        label="host",
    )
    if latest_committed_id is not None:
        await _drop_orphan_snapshots(
            host_restic, host_repo, restic_password, latest_committed_id
        )
    with trace_action(logger, action, "host restore"):
        await restore_repo(host_restic, host_repo, restic_password, context_dir)
    result = await anyio.to_thread.run_sync(
        partial(
            _load_host_state,
            context_dir,
            sample_root,
            latest_committed_id,
        )
    )
    result = _push_host_state(result, sample_root, latest_committed_id)
    return result


async def _hydrate_sandboxes(
    resume: ResumeCheckpoint | None,
    sandbox_paths: dict[str, list[str]],
    restic_password: str,
    sample_root: str,
    host_restic: Path,
    latest_committed_id: int | None,
    action: str,
) -> None:
    if not sandbox_paths:
        return
    await tg_collect(
        [
            partial(
                _hydrate_sandbox,
                name=name,
                paths=paths,
                resume=resume,
                restic_password=restic_password,
                sample_root=sample_root,
                host_restic=host_restic,
                latest_committed_id=latest_committed_id,
                action=action,
            )
            for name, paths in sandbox_paths.items()
        ]
    )


async def _hydrate_sandbox(
    *,
    name: str,
    paths: list[str],
    resume: ResumeCheckpoint | None,
    restic_password: str,
    sample_root: str,
    host_restic: Path,
    latest_committed_id: int | None,
    action: str,
) -> None:
    env = sandbox(name)
    with trace_action(logger, action, f"sandbox {name} inject"):
        await inject_restic(env)
    if resume is None:
        with trace_action(logger, action, f"sandbox {name} init"):
            await init_sandbox_repo(env, restic_password)
        return

    # Resume: FS-copy the old host-side sandbox repo into the new sample
    # root, drop any orphan snapshots beyond the latest committed
    # checkpoint file (so the in-container ingress restores the
    # committed snapshot, not a torn-fire orphan), then ingress it into the
    # container (which also runs restic-restore to put files at their
    # original paths).
    new_host_side_repo = sandbox_repo_dir(sample_root, name)
    await _fs_copy_repo(
        resume.sample_checkpoints_dir,
        f"restic/sandboxes/{name}",
        new_host_side_repo,
        label=f"sandbox {name!r}",
    )
    if latest_committed_id is not None:
        await _drop_orphan_snapshots(
            host_restic, new_host_side_repo, restic_password, latest_committed_id
        )
    with trace_action(logger, action, f"sandbox {name} ingress"):
        await ingress_sandbox(env, new_host_side_repo, restic_password)


async def _drop_orphan_snapshots(
    restic: Path, repo: str, password: str, latest_id: int
) -> list[str]:
    """Forget restic snapshots tagged ``ckpt-NNNNN`` where NNNNN > latest_id.

    A fire that completed its restic backup but was interrupted before
    ``write_checkpoint_file`` leaves an orphan snapshot in the repo
    with no corresponding ``ckpt-NNNNN.json`` to acknowledge it. On resume we
    drop those so ``restic restore latest`` picks the committed
    snapshot — and so the next fire can write its tag without colliding
    with a stale tag of the same id. Returns the list of dropped tag
    names for logging.
    """
    proc = await anyio.run_process(
        [str(restic), "-r", repo, "snapshots", "--json"],
        env=restic_env(password),
        check=True,
    )
    snapshots = json.loads(proc.stdout.decode())
    orphan_ids: list[str] = []
    orphan_tags: list[str] = []
    for snap in snapshots:
        for tag in snap.get("tags") or []:
            if not tag.startswith("ckpt-"):
                continue
            try:
                n = int(tag.removeprefix("ckpt-"))
            except ValueError:
                continue
            if n > latest_id:
                orphan_ids.append(snap["short_id"])
                orphan_tags.append(tag)
                break
    if orphan_ids:
        await anyio.run_process(
            [str(restic), "-r", repo, "forget", *orphan_ids],
            env=restic_env(password),
            check=True,
        )
    return orphan_tags


async def _fs_copy_cross_cutting(old_sample_dir: str, new_sample_dir: str) -> list[str]:
    """Copy `restic-config.json` and `ckpt-*.json` from old to new sample dir.

    Cross-cutting in the sense that neither belongs exclusively to the
    host or to any sandbox — they live at the top of the sample
    checkpoints dir (the checkpoint files) and one level into
    ``restic/`` (the config) alongside the per-domain repo subtrees.

    ``old_sample_dir`` may be local or remote (e.g. ``s3://``); the new
    sample dir is always local. Returns the list of paths written,
    relative to ``new_sample_dir``.
    """
    async_fs = get_async_filesystem()
    new = Path(new_sample_dir)
    written: list[str] = []

    with trace_action(logger, "Checkpoint Hydrate", "fs-copy cross-cutting"):
        src_restic_config = f"{old_sample_dir}/restic/restic-config.json"
        if await async_fs.exists(src_restic_config):
            (new / "restic").mkdir(parents=True, exist_ok=True)
            dst = new / "restic" / "restic-config.json"
            await async_fs.get_file(src_restic_config, str(dst))
            written.append("restic/restic-config.json")

        async for uri in async_fs.iter_files(old_sample_dir, pattern="ckpt-*.json"):
            name = uri.rsplit("/", 1)[-1]
            dst = new / name
            await async_fs.get_file(uri, str(dst))
            written.append(name)
    return written


async def _fs_copy_repo(
    old_sample_dir: str, subpath: str, new_repo: str, *, label: str
) -> list[str]:
    """Recursively copy a restic repo subtree from old sample dir to new.

    ``subpath`` is the per-domain path under the old sample checkpoints
    dir (``"restic/host"`` or ``"restic/sandboxes/<name>"``). ``old_sample_dir``
    may be local or remote; ``new_repo`` is always local. ``label`` is
    a short descriptor used only for the diagnostic print line.

    Returns the list of paths written, relative to the new sample root
    (i.e. each path starts with ``subpath``). Raises if the source
    enumerated no files — S3 has no real directories, so existence is
    only knowable via "any object with this prefix?", and a valid restic
    repo always has at least one file (`config`).
    """
    async_fs = get_async_filesystem()
    src_base = f"{old_sample_dir}/{subpath}"
    new_root = Path(new_repo)
    written: list[str] = []
    # `iter_files` yields URIs verbatim-prefixed by `src_base` for S3, but
    # fsspec-normalized (absolute) for local sources — so slicing by
    # `len(src_base)` mangles local relative sources. Relativize against the
    # `/<subpath>/` repo-root boundary instead: it's the last such marker in
    # the URI (a restic repo's own tree never contains `<subpath>`), so this
    # is correct regardless of how the backend normalizes the prefix.
    marker = f"/{subpath}/"
    with trace_action(logger, "Checkpoint Hydrate", f"fs-copy {label}"):
        async for uri in async_fs.iter_files(src_base, recursive=True):
            rel = uri.rsplit(marker, 1)[-1]
            dst = new_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            await async_fs.get_file(uri, str(dst))
            written.append(f"{subpath}/{rel}")
        if not written:
            raise RuntimeError(
                f"resume: expected {label} repo at {src_base}, but no files were found"
            )
    return written


def _load_host_state(
    context_dir: str,
    sample_root: str,
    latest_committed_id: int | None,
) -> _HostHydrationResult:
    """Read restored host context and prepare resume state.

    This runs in a worker thread, so it only reads files and builds Python
    objects. It materializes pooled event refs, synthesizes the trailing
    ``CheckpointEvent`` from the latest checkpoint file, wraps prior-run spans,
    and returns the host state that the loop thread will push into Transcript,
    Store, and the checkpointer transcript store.
    """
    ctx = host_context.read(local_path(context_dir))

    # Synthesize the trailing `CheckpointEvent`. By construction
    # (working.md §8a) the event for the latest committed checkpoint
    # is never in its own `events.json` — it's emitted after that
    # fire's host context was written. Rebuild from the checkpoint
    # file (already known to parse via `scan_latest_committed_id`) so
    # the rehydrated transcript matches a live one.
    # `latest_committed_id` is `None` only in degenerate resume cases
    # that the validation below will surface; skip synthesis there.
    rehydrated_events = list(ctx.condensed_events)
    if latest_committed_id is not None:
        synthesized = _synthesize_trailing_checkpoint_event(
            sample_root, latest_committed_id
        )
        rehydrated_events.append(synthesized)

    rehydrated_events = materialize_pooled_events(
        rehydrated_events, ctx.msg_pool, ctx.call_pool
    )

    # Wrap the most-recent prior session's unwrapped checkpoint spans in
    # a new `prior_run` span before pushing — every prior
    # session ends up as a sibling wrap inside this attempt's events.
    # See `_wrap_prior_run` for the slicing + reparenting
    # mechanics.
    pushed_events = _wrap_prior_run(rehydrated_events)

    return _HostHydrationResult(
        agent_state=ctx.agent_state,
        condensed_events=pushed_events,
        msg_pool=ctx.msg_pool,
        call_pool=ctx.call_pool,
        attachments=ctx.attachments,
        store=ctx.store,
    )


def _push_host_state(
    result: _HostHydrationResult,
    sample_root: str,
    latest_committed_id: int | None,
) -> _HostHydrationResult:
    """Push restored host state into loop-owned Transcript and Store."""
    ts = transcript()
    result.condensed_events = materialize_pooled_events(
        result.condensed_events,
        result.msg_pool,
        result.call_pool,
    )
    ts._extend_restored_events(
        result.condensed_events,
        result.attachments,
        notify_subscribers=True,
    )
    state = sample_state()
    if state is None:
        raise RuntimeError("_hydrate_host: no active sample state to populate Store")
    for key, value in result.store.items():
        state.store.set(key, value)

    _validate_resume_state(result.condensed_events, sample_root, latest_committed_id)
    return result


def _wrap_prior_run(events: list[Event]) -> list[Event]:
    """Wrap the trailing unwrapped checkpoint spans in a new ``prior_run`` span.

    The "tail" is the slice of ``events`` after the last existing
    ``prior_run`` ``span_end`` (or the whole list if there are
    no prior wraps). That tail is the most-recent prior session's
    checkpoint spans, which haven't been wrapped yet — the current
    session wraps them at hydrate time.

    Top-level ``span_begin`` events in the tail (depth 0 relative to the
    new wrap — in practice the checkpoint span_begins) get their
    ``parent_id`` rewritten to point at the new wrap's id, so the span
    hierarchy reflects the new structure rather than carrying stale
    parent ids from the prior session's transcript. ``span_end`` events
    carry no ``parent_id``, so they pass through unchanged. The wrap's
    own ``parent_id`` is ``None`` (sibling at the sample root,
    alongside other prior wraps and the current session's checkpoint
    spans).

    Wrap numbering (``checkpoint restore 1``, ``2``, …) is the count
    of existing wraps plus one, so each resume adds one numbered
    sibling.

    Timing: the wrap's ``timestamp`` defaults to *now* (resume time),
    not the prior session's run time. The wrap represents the act of
    rehydrating rather than the work being rehydrated; the contained
    checkpoint spans carry their original timestamps.
    """
    prior_ids: set[str] = set()
    last_prior_end_idx = -1
    for i, e in enumerate(events):
        if isinstance(e, SpanBeginEvent) and e.type == "prior_run":
            prior_ids.add(e.id)
        elif isinstance(e, SpanEndEvent) and e.id in prior_ids:
            last_prior_end_idx = i

    head = events[: last_prior_end_idx + 1]
    tail = events[last_prior_end_idx + 1 :]

    if not tail:
        return list(head)

    next_n = len(prior_ids) + 1
    wrap_id = shortuuid()
    wrap_begin = SpanBeginEvent(
        id=wrap_id,
        parent_id=None,
        type="prior_run",
        name=f"checkpoint restore {next_n}",
    )
    wrap_end = SpanEndEvent(id=wrap_id)

    # Reparent depth-0 events in the tail so the UI nests them inside
    # the new wrap. Two cases:
    #
    # - Top-level `span_begin` (in practice each prior session's
    #   `checkpoint N` span): rewrite `parent_id` to the wrap. Their
    #   original `parent_id` points at a span from the prior attempt's
    #   transcript (e.g. `react/agent`) that doesn't exist in this
    #   attempt.
    # - Other top-level events (in practice `CheckpointEvent`s emitted
    #   between checkpoint spans): rewrite `span_id` to the wrap.
    #   Their original `span_id` came from the prior attempt's
    #   `_current_span_id` ContextVar at emit time — also stale.
    #
    # Events at depth > 0 are inside their checkpoint span; their
    # `span_id` already points at that span, which is in the tail and
    # nests under the wrap via the rewritten `parent_id`. No change
    # needed there.
    new_tail: list[Event] = []
    open_span_ids: list[str] = []
    for e in tail:
        if isinstance(e, SpanBeginEvent):
            if not open_span_ids:
                e = e.model_copy(update={"parent_id": wrap_id})
            open_span_ids.append(e.id)
        elif isinstance(e, SpanEndEvent):
            if e.id in open_span_ids:
                open_span_ids.remove(e.id)
        elif not open_span_ids:
            e = e.model_copy(update={"span_id": wrap_id})
        new_tail.append(e)

    if new_tail:
        last_restored_event = new_tail[-1]
        synthetic_ends = [
            SpanEndEvent(
                id=span_id,
                timestamp=last_restored_event.timestamp,
                working_start=last_restored_event.working_start,
                metadata=deepcopy(_SYNTHETIC_RESTORED_SPAN_END_METADATA),
            )
            for span_id in reversed(open_span_ids)
        ]
    else:
        synthetic_ends = [
            SpanEndEvent(
                id=span_id,
                metadata=deepcopy(_SYNTHETIC_RESTORED_SPAN_END_METADATA),
            )
            for span_id in reversed(open_span_ids)
        ]

    return list(head) + [wrap_begin, *new_tail, *synthetic_ends, wrap_end]


def _synthesize_trailing_checkpoint_event(
    sample_root: str, latest_committed_id: int
) -> CheckpointEvent:
    """Reconstruct the `CheckpointEvent` for the most recently committed checkpoint file.

    The live emit happens after `write_host_context` and therefore
    never lands in its own fire's `events.json`. On resume we rebuild
    the event from `ckpt-{N:05d}.json` (already validated parseable
    by `scan_latest_committed_id`) so the rehydrated transcript is
    indistinguishable from a live one — same content, same
    timestamp.
    """
    checkpoint_path = f"{sample_root}/ckpt-{latest_committed_id:05d}.json"
    with file(checkpoint_path, "r") as f:
        checkpoint = Checkpoint.model_validate_json(f.read())
    return CheckpointEvent.from_details(checkpoint).model_copy(
        update={"timestamp": checkpoint.created_at}
    )


def _validate_resume_state(
    events: list[Event],
    sample_root: str,
    latest_committed_id: int | None,
) -> None:
    """Sanity-check the loaded events for the expected resume shape.

    Invariants checked (all raise ``RuntimeError`` on failure):

    - ``events.json`` is non-empty and starts with
      ``span_begin name="checkpoint restore 1" type="prior_run"``
      (the wrap synthesized at hydrate time).
    - Last event is a ``span_end`` (either the outermost wrap's end or
      a checkpoint's end if no wraps were synthesized).
    - Checkpoint span names are sequential (``checkpoint 1``, ``2``,
      …, ``N``) across the whole event list, regardless of nesting
      depth inside ``prior_run`` wraps.
    - ``prior_run`` wrap names are sequential
      (``checkpoint restore 1``, ``2``, …, ``M``).
    - Each ``span_begin`` (checkpoint or wrap) is paired with a
      matching ``span_end`` (by ``id``).
    - The number of checkpoint spans equals ``latest_committed_id``
      (the highest cleanly-parsing checkpoint id — the true commit
      point).

    Runs by default while the checkpoint code stabilizes. Set
    ``INSPECT_CHECKPOINT_VALIDATE_DISABLE`` to skip it — a surgical escape
    hatch for tests that drive the resume push with non-resume-shaped stub
    data.
    """
    if bool(os.environ.get(_DISABLE_ENV_VAR)):
        return

    sample_dir = Path(local_path(sample_root))
    checkpoint_files = sorted(p.name for p in sample_dir.glob("ckpt-*.json"))

    # Walk events: collect checkpoint + prior_run span_begins and
    # CheckpointEvents. Generic span pairing is validated below by
    # `_validate_span_balance`.
    checkpoint_begins: list[tuple[int, str, str]] = []  # (idx, name, id)
    wrap_begins: list[tuple[int, str, str]] = []  # (idx, name, id)
    checkpoint_events: list[tuple[int, int]] = []  # (idx, checkpoint_id)
    for i, e in enumerate(events):
        if isinstance(e, SpanBeginEvent):
            if e.type == "checkpoint":
                checkpoint_begins.append((i, e.name, e.id))
            elif e.type == "prior_run":
                wrap_begins.append((i, e.name, e.id))
        elif e.event == "checkpoint":
            ckpt_id = getattr(e, "checkpoint_id", None)
            if ckpt_id is not None:
                checkpoint_events.append((i, ckpt_id))

    # --- assertions ---
    if not events:
        raise RuntimeError("[hydrate.validate] events.json is empty")
    if not checkpoint_begins:
        raise RuntimeError("[hydrate.validate] no checkpoint span_begin events found")
    if not wrap_begins:
        raise RuntimeError(
            "[hydrate.validate] no prior_run wrap found "
            "(expected at least one on resume)"
        )

    first = events[0]
    if not (
        isinstance(first, SpanBeginEvent)
        and first.type == "prior_run"
        and first.name == "checkpoint restore 1"
    ):
        raise RuntimeError(
            f"[hydrate.validate] events[0] not 'span_begin checkpoint restore 1': "
            f"{_event_label(first)}"
        )

    last = events[-1]
    if last.event != "span_end":
        raise RuntimeError(
            f"[hydrate.validate] events[-1] not 'span_end': {_event_label(last)}"
        )

    _validate_span_balance(events)

    expected_ckpt_names = [f"checkpoint {i + 1}" for i in range(len(checkpoint_begins))]
    actual_ckpt_names = [name for _, name, _ in checkpoint_begins]
    if actual_ckpt_names != expected_ckpt_names:
        raise RuntimeError(
            f"[hydrate.validate] checkpoint span names not sequential. "
            f"expected {expected_ckpt_names}, got {actual_ckpt_names}"
        )

    expected_wrap_names = [
        f"checkpoint restore {i + 1}" for i in range(len(wrap_begins))
    ]
    actual_wrap_names = [name for _, name, _ in wrap_begins]
    if actual_wrap_names != expected_wrap_names:
        raise RuntimeError(
            f"[hydrate.validate] prior_run wrap names not sequential. "
            f"expected {expected_wrap_names}, got {actual_wrap_names}"
        )

    expected_span_count = latest_committed_id if latest_committed_id is not None else 0
    if expected_span_count != len(checkpoint_begins):
        raise RuntimeError(
            f"[hydrate.validate] expected {expected_span_count} checkpoint "
            f"spans (per latest committed id {latest_committed_id}), got "
            f"{len(checkpoint_begins)}"
        )

    if len(checkpoint_files) != len(checkpoint_begins):
        raise RuntimeError(
            f"[hydrate.validate] checkpoint file count ({len(checkpoint_files)}) != "
            f"checkpoint span count ({len(checkpoint_begins)})"
        )

    if expected_span_count != len(checkpoint_events):
        raise RuntimeError(
            f"[hydrate.validate] expected {expected_span_count} CheckpointEvents "
            f"(one per committed checkpoint, with trailing one synthesized at "
            f"hydrate-time), got {len(checkpoint_events)}"
        )

    expected_event_ids = list(range(1, expected_span_count + 1))
    actual_event_ids = [ckpt_id for _, ckpt_id in checkpoint_events]
    if actual_event_ids != expected_event_ids:
        raise RuntimeError(
            f"[hydrate.validate] CheckpointEvent checkpoint_id sequence "
            f"mismatch. expected {expected_event_ids}, "
            f"got {actual_event_ids}"
        )


def _validate_span_balance(events: list[Event]) -> None:
    begin_by_id: dict[str, int] = {}
    end_by_id: dict[str, int] = {}
    for idx, event in enumerate(events):
        if isinstance(event, SpanBeginEvent):
            if event.id in begin_by_id:
                first_idx = begin_by_id[event.id]
                raise RuntimeError(
                    f"[hydrate.validate] duplicate span_begin id {event.id} at "
                    f"indexes {first_idx} and {idx}"
                )
            begin_by_id[event.id] = idx
        elif isinstance(event, SpanEndEvent):
            if event.id not in begin_by_id:
                raise RuntimeError(
                    f"[hydrate.validate] span_end at index {idx} has no "
                    f"span_begin: {event.id}"
                )
            if event.id in end_by_id:
                raise RuntimeError(
                    f"[hydrate.validate] duplicate span_end id {event.id} at "
                    f"indexes {end_by_id[event.id]} and {idx}"
                )
            end_by_id[event.id] = idx

    unclosed = [
        (idx, span_id)
        for span_id, idx in begin_by_id.items()
        if span_id not in end_by_id
    ]
    if unclosed:
        raise RuntimeError(
            f"[hydrate.validate] {len(unclosed)} unclosed span_begin event(s): "
            f"{unclosed}"
        )


def _event_label(e: Event) -> str:
    """Compact one-line label for an event (debug logging only).

    Adds a discriminator-adjacent field where one carries useful info:
    sandbox action, span name+type, tool function, model name, etc.
    """
    base = e.event
    detail: str | None = None
    if base == "sandbox":
        detail = getattr(e, "action", None)
    elif base in ("span_begin", "span_end"):
        name = getattr(e, "name", None)
        type_ = getattr(e, "type", None)
        detail = f"{name}/{type_}" if type_ else name
    elif base == "step":
        action = getattr(e, "action", None)
        type_ = getattr(e, "type", None)
        detail = f"{action}/{type_}" if type_ else action
    elif base == "tool":
        detail = getattr(e, "function", None)
    elif base == "model":
        detail = getattr(e, "model", None)
    elif base == "subtask":
        detail = getattr(e, "name", None)
    elif base in ("compaction", "sample_limit"):
        detail = getattr(e, "type", None)
    elif base == "logger":
        detail = getattr(e, "level", None)
    elif base == "score_edit":
        detail = getattr(e, "score_name", None)
    elif base == "info":
        detail = getattr(e, "source", None)
    return f"{base}:{detail}" if detail else base
