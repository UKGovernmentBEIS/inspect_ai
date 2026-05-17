"""Per-sample checkpoint hydration.

``_hydrate`` is called from ``_CheckpointerSetup.__aenter__`` to set up the
on-disk + in-sandbox state for the sample's checkpointer and return
everything :class:`_EnteredCheckpointer` needs at construction.

For fresh samples (no :class:`ResumeCheckpoint`) ``_hydrate`` mints a
password and inits empty restic repos (host + each sandbox). For
resumed samples it FS-copies the old sample checkpoints dir into the
new one, restic-restores the latest snapshot into the new sample
working dir, ingresses each sandbox repo back into its container and
restores in-container state, loads ``agent_state.json``, and pushes
restored events/attachments/store into the live framework state.

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

import glob
import json
import shutil
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import anyio
from pydantic import JsonValue

from inspect_ai._util._async import tg_collect
from inspect_ai._util.file import local_path
from inspect_ai.event._event import Event
from inspect_ai.log._transcript import transcript
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.solver._task_state import sample_state
from inspect_ai.util._restic import init_repo, resolve_restic, restore_repo
from inspect_ai.util._restic.ops import restic_env
from inspect_ai.util._sandbox.context import sandbox

from ._sandbox_restic import ingress_sandbox, init_sandbox_repo, inject_restic
from .checkpointer import ResumeCheckpoint
from .config import ResolvedCheckpointConfig
from .layout import (
    ensure_sample_checkpoints_dir,
    ensure_sample_json,
    ensure_sample_working_dir,
    eval_checkpoints_dir,
    host_context,
    scan_latest_committed_id,
)


@dataclass
class _HostHydrationResult:
    """Returned by ``_hydrate_host``; consumed by ``_hydrate`` orchestrator.

    Fields are populated from the restored ``<working_dir>/*.json`` files
    on resume; left at their fresh-run defaults otherwise.
    """

    agent_state: dict[str, Any] | None = None
    """From ``agent_state.json`` — values returned by ``track()`` on resume."""

    condensed_events: list[Event] = field(default_factory=list)
    """From ``events.json`` — seeds ``_EnteredCheckpointer._condensed_events``
    so the next fire writes a cumulative snapshot."""

    msg_pool: list[ChatMessage] = field(default_factory=list)
    """From ``events_data.json[messages]`` — seeds the dedup pool."""

    call_pool: list[JsonValue] = field(default_factory=list)
    """From ``events_data.json[calls]`` — seeds the dedup pool."""


@dataclass
class HydrationResult:
    """Everything ``_EnteredCheckpointer`` needs at construction."""

    sample_checkpoints_dir: str
    sample_working_dir: str
    host_restic: Path
    host_repo: str
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
    print(
        f"[hydrate] start sample={sample_id} epoch={epoch} mode={'resume' if resume_checkpoint else 'fresh'}"
    )
    if resume_checkpoint:
        print(f"[hydrate]   resume from {resume_checkpoint.sample_checkpoints_dir}")

    # Phase 1: synchronous prologue. After this completes, every Phase 2
    # function can read the password from <new sample dir>/sample.json
    # and reach restic on the host.
    new_eval_checkpoints_dir = eval_checkpoints_dir(
        log_location, config.checkpoints_location
    )
    new_sample_checkpoints_dir = await ensure_sample_checkpoints_dir(
        new_eval_checkpoints_dir, sample_id, epoch
    )
    print(f"[hydrate] sample_checkpoints_dir={new_sample_checkpoints_dir}")
    sample_working_dir = await ensure_sample_working_dir(log_location, sample_id, epoch)
    print(f"[hydrate] sample_working_dir={sample_working_dir}")
    if resume_checkpoint:
        # Bring the cross-cutting bits over first so `ensure_sample_json`
        # reads the inherited password instead of minting a fresh one,
        # and so the sidecar count continues from the prior run.
        await anyio.to_thread.run_sync(
            _fs_copy_cross_cutting,
            resume_checkpoint.sample_checkpoints_dir,
            new_sample_checkpoints_dir,
        )
    sample_state = await ensure_sample_json(new_sample_checkpoints_dir)
    print(f"[hydrate] restic_password={sample_state.restic_password[:8]}...")
    host_restic = await resolve_restic()
    host_repo = f"{new_sample_checkpoints_dir}/host"

    # On resume, find the highest committed checkpoint id (sidecars are
    # the source of truth — see ``CheckpointSidecar`` design notes). Any
    # restic snapshot tagged ``ckpt-NNNNN`` with N > this id is an orphan
    # from an interrupted fire that completed its backup but never wrote
    # its sidecar; ``_hydrate_host`` / ``_hydrate_sandbox`` drop those
    # below so ``restic restore latest`` picks the committed snapshot.
    latest_committed_id: int | None = None
    if resume_checkpoint:
        latest_committed_id = await anyio.to_thread.run_sync(
            scan_latest_committed_id, new_sample_checkpoints_dir
        )
        print(f"[hydrate] latest committed sidecar id: {latest_committed_id}")

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
            restic_password=sample_state.restic_password,
            sample_working_dir=sample_working_dir,
            latest_committed_id=latest_committed_id,
        )

    print("[hydrate] phase-2 host + sandboxes start (parallel)")
    async with anyio.create_task_group() as tg:
        tg.start_soon(_run_host)
        tg.start_soon(
            _hydrate_sandboxes,
            resume_checkpoint,
            config.sandbox_paths or {},
            sample_state.restic_password,
            new_sample_checkpoints_dir,
            host_restic,
            latest_committed_id,
        )
    assert host_result is not None  # task group ran _run_host to completion
    print("[hydrate] phase-2 host + sandboxes done")
    print(f"[hydrate] complete sample={sample_id} epoch={epoch}")

    return HydrationResult(
        sample_checkpoints_dir=new_sample_checkpoints_dir,
        sample_working_dir=sample_working_dir,
        host_restic=host_restic,
        host_repo=host_repo,
        restic_password=sample_state.restic_password,
        host=host_result,
    )


async def _hydrate_host(
    *,
    resume: ResumeCheckpoint | None,
    host_restic: Path,
    host_repo: str,
    restic_password: str,
    sample_working_dir: str,
    latest_committed_id: int | None,
) -> _HostHydrationResult:
    if resume is None:
        print(f"[hydrate.host] fresh init at {host_repo}")
        await init_repo(host_restic, host_repo, restic_password)
        print("[hydrate.host] fresh init done")
        return _HostHydrationResult()

    # Resume: FS-copy the old host repo into the new one (preserves
    # snapshot IDs and password), drop any orphan snapshots beyond the
    # latest committed sidecar, restic-restore the latest snapshot into
    # the new sample working dir, then load the JSON files and push
    # framework state into the live Transcript + Store.
    print(
        f"[hydrate.host] resume: FS-copy {resume.sample_checkpoints_dir}/host"
        f" -> {host_repo}"
    )
    await anyio.to_thread.run_sync(
        partial(
            _fs_copy_repo,
            resume.sample_checkpoints_dir,
            "host",
            host_repo,
            label="host",
        )
    )
    if latest_committed_id is not None:
        dropped = await _drop_orphan_snapshots(
            host_restic, host_repo, restic_password, latest_committed_id
        )
        if dropped:
            print(
                f"[hydrate.host] dropped {len(dropped)} orphan snapshot(s): {dropped}"
            )
    print(f"[hydrate.host] restic restore latest -> {sample_working_dir}")
    await restore_repo(host_restic, host_repo, restic_password, sample_working_dir)
    print("[hydrate.host] load + push framework state")
    sample_checkpoints_dir = str(Path(host_repo).parent)
    result = await anyio.to_thread.run_sync(
        partial(
            _load_and_push_host_state,
            sample_working_dir,
            sample_checkpoints_dir,
            latest_committed_id,
        )
    )
    print(
        f"[hydrate.host] resume done: "
        f"events={len(result.condensed_events)} "
        f"msgs={len(result.msg_pool)} "
        f"calls={len(result.call_pool)} "
        f"agent_state={'yes' if result.agent_state else 'no'}"
    )
    return result


async def _hydrate_sandboxes(
    resume: ResumeCheckpoint | None,
    sandbox_paths: dict[str, list[str]],
    restic_password: str,
    new_sample_checkpoints_dir: str,
    host_restic: Path,
    latest_committed_id: int | None,
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
                new_sample_checkpoints_dir=new_sample_checkpoints_dir,
                host_restic=host_restic,
                latest_committed_id=latest_committed_id,
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
    new_sample_checkpoints_dir: str,
    host_restic: Path,
    latest_committed_id: int | None,
) -> None:
    env = sandbox(name)
    print(f"[hydrate.sandbox:{name}] inject restic")
    await inject_restic(env)
    if resume is None:
        print(f"[hydrate.sandbox:{name}] fresh init in-container repo")
        await init_sandbox_repo(env, restic_password)
        print(f"[hydrate.sandbox:{name}] fresh init done")
        return

    # Resume: FS-copy the old host-side sandbox repo into the new sample
    # checkpoints dir, drop any orphan snapshots beyond the latest
    # committed sidecar (so the in-container ingress restores the
    # committed snapshot, not a torn-fire orphan), then ingress it into
    # the container (which also runs restic-restore to put files at
    # their original paths).
    new_host_side_repo = f"{new_sample_checkpoints_dir}/sandboxes/{name}"
    print(
        f"[hydrate.sandbox:{name}] resume: FS-copy"
        f" {resume.sample_checkpoints_dir}/sandboxes/{name} -> {new_host_side_repo}"
    )
    await anyio.to_thread.run_sync(
        partial(
            _fs_copy_repo,
            resume.sample_checkpoints_dir,
            f"sandboxes/{name}",
            new_host_side_repo,
            label=f"sandbox {name!r}",
        )
    )
    if latest_committed_id is not None:
        dropped = await _drop_orphan_snapshots(
            host_restic, new_host_side_repo, restic_password, latest_committed_id
        )
        if dropped:
            print(
                f"[hydrate.sandbox:{name}] dropped {len(dropped)} orphan "
                f"snapshot(s): {dropped}"
            )
    print(
        f"[hydrate.sandbox:{name}] ingress into container + restic restore"
        f" (paths={paths})"
    )
    await ingress_sandbox(env, new_host_side_repo, restic_password)
    print(f"[hydrate.sandbox:{name}] resume done")


async def _drop_orphan_snapshots(
    restic: Path, repo: str, password: str, latest_id: int
) -> list[str]:
    """Forget restic snapshots tagged ``ckpt-NNNNN`` where NNNNN > latest_id.

    A fire that completed its restic backup but was interrupted before
    ``write_sidecar`` leaves an orphan snapshot in the repo with no
    corresponding ``ckpt-NNNNN.json`` to acknowledge it. On resume we
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


def _fs_copy_cross_cutting(old_sample_dir: str, new_sample_dir: str) -> None:
    """Copy `sample.json` and `ckpt-*.json` from old sample dir to new.

    Cross-cutting in the sense that neither belongs exclusively to the
    host or to any sandbox — they live at the top of the sample
    checkpoints dir alongside the per-domain subtrees.
    """
    old = Path(local_path(old_sample_dir))
    new = Path(local_path(new_sample_dir))
    src_sample_json = old / "sample.json"
    if src_sample_json.exists():
        shutil.copy(src_sample_json, new / "sample.json")
        print(f"[hydrate.copy] sample.json: {src_sample_json} -> {new / 'sample.json'}")
    sidecars = glob.glob(str(old / "ckpt-*.json"))
    for sidecar in sidecars:
        shutil.copy(sidecar, new / Path(sidecar).name)
    print(f"[hydrate.copy] sidecars copied: {len(sidecars)}")


def _fs_copy_repo(
    old_sample_dir: str, subpath: str, new_repo: str, *, label: str
) -> None:
    """Recursively copy a restic repo subtree from old sample dir to new.

    ``subpath`` is the per-domain path under the old sample checkpoints
    dir (``"host"`` or ``"sandboxes/<name>"``). ``label`` is a short
    descriptor used only for the diagnostic print line.
    """
    src = Path(local_path(old_sample_dir)) / subpath
    if not src.is_dir():
        raise RuntimeError(
            f"resume: expected {label} repo at {src}, but it doesn't exist"
        )
    file_count = sum(1 for entry in src.rglob("*") if entry.is_file())
    shutil.copytree(src, new_repo, dirs_exist_ok=True)
    print(f"[hydrate.copy] {label} repo: {src} -> {new_repo} ({file_count} files)")


def _load_and_push_host_state(
    sample_working_dir: str,
    sample_checkpoints_dir: str,
    latest_committed_id: int | None,
) -> _HostHydrationResult:
    """Read the restored host context and push framework state.

    Loads via :mod:`host_context`, pushes events/attachments/store into
    the live ``Transcript`` and ``Store`` (so the agent's continued run
    sees the cumulative history), and returns the parts the agent-facing
    :class:`_EnteredCheckpointer` needs at construction:

    - ``agent_state`` — for ``track()`` to return persisted values.
    - ``condensed_events``, ``msg_pool``, ``call_pool`` — seeds for the
      checkpointer's pools so the next fire writes a cumulative snapshot.

    Validates the loaded events against expected resume invariants
    (checkpoint span structure, sidecar parity) so a broken resume
    fails loudly here rather than cascading into the agent loop.
    """
    ctx = host_context.read(local_path(sample_working_dir))

    print(
        f"[hydrate.host] loaded: events={len(ctx.condensed_events)} "
        f"msgs={len(ctx.msg_pool)} calls={len(ctx.call_pool)} "
        f"attachments={len(ctx.attachments)} store_keys={len(ctx.store)} "
        f"agent_state={'yes' if ctx.agent_state else 'no'}"
    )

    # Push framework-owned state into the live transcript + store so the
    # agent's continued run appends to (rather than replaces) the prior
    # history. Direct mutation of the internal lists bypasses
    # ``_process_event`` — the events are already in their condensed,
    # attachment-ref form and must not be reprocessed. The persisted
    # `condensed_events` is already span-only (the writer's accumulator
    # only ever captured events from the first `span_begin: checkpoint`
    # onward), so we push it through as-is.
    ts = transcript()
    pre = [_event_label(e) for e in ts._events]
    restored = [_event_label(e) for e in ctx.condensed_events]
    print(f"[hydrate.host] pre-hydration transcript.events (n={len(pre)}): {pre}")
    print(f"[hydrate.host] restored events to push (n={len(restored)}): {restored}")
    ts._events.extend(ctx.condensed_events)
    ts._attachments.update(ctx.attachments)
    state = sample_state()
    if state is None:
        raise RuntimeError("_hydrate_host: no active sample state to populate Store")
    for key, value in ctx.store.items():
        state.store.set(key, value)
    print(
        f"[hydrate.host] pushed: transcript.events={len(ts._events)} "
        f"transcript.attachments={len(ts._attachments)} "
        f"store_keys={len(list(state.store.keys()))}"
    )

    _validate_resume_state(
        ctx.condensed_events, sample_checkpoints_dir, latest_committed_id
    )

    return _HostHydrationResult(
        agent_state=ctx.agent_state,
        condensed_events=ctx.condensed_events,
        msg_pool=ctx.msg_pool,
        call_pool=ctx.call_pool,
    )


def _validate_resume_state(
    events: list[Event],
    sample_checkpoints_dir: str,
    latest_committed_id: int | None,
) -> None:
    """Sanity-check the loaded events for the expected resume shape.

    Invariants checked (all raise ``RuntimeError`` on failure):

    - ``events.json`` is non-empty and starts with
      ``span_begin name="checkpoint 1" type="checkpoint"``.
    - Last event is a ``span_end`` (the most recent fire closed its
      span at the top of ``_fire`` before writing the snapshot).
    - Checkpoint span names are sequential (``checkpoint 1``, ``2``,
      …, ``N``).
    - Each checkpoint ``span_begin`` is paired with a matching
      ``span_end`` (by ``id``).
    - The number of checkpoint spans equals ``latest_committed_id``
      (the highest cleanly-parsing sidecar id — the true commit point).

    Console-prints a readable summary either way so the resume flow
    is easy to follow.
    """
    print("[hydrate.validate] === resume sanity check ===")

    sample_dir = Path(local_path(sample_checkpoints_dir))
    sidecars = sorted(p.name for p in sample_dir.glob("ckpt-*.json"))
    print(
        f"[hydrate.validate] sidecars in {sample_dir.name}/ "
        f"(n={len(sidecars)}, latest committed id={latest_committed_id}): "
        f"{sidecars}"
    )
    print(f"[hydrate.validate] events.json event count: {len(events)}")

    # Walk events: collect checkpoint span_begin's and all span_end's
    # (span_end has no type attr — pair by id).
    begins: list[tuple[int, str, str]] = []  # (idx, name, id)
    end_by_id: dict[str, int] = {}
    for i, e in enumerate(events):
        if e.event == "span_begin" and getattr(e, "type", None) == "checkpoint":
            begins.append((i, getattr(e, "name", ""), getattr(e, "id", "")))
        elif e.event == "span_end":
            id_ = getattr(e, "id", None)
            if id_ is not None:
                end_by_id[id_] = i

    print(f"[hydrate.validate] checkpoint span_begin events (n={len(begins)}):")
    for idx, name, id_ in begins:
        end_idx = end_by_id.get(id_)
        end_str = f"span_end@{end_idx}" if end_idx is not None else "UNPAIRED"
        print(f"  [{idx:4d}] name={name!r:18} id={id_:8} -> {end_str}")

    # --- assertions ---
    if not events:
        raise RuntimeError("[hydrate.validate] events.json is empty")
    if not begins:
        raise RuntimeError("[hydrate.validate] no checkpoint span_begin events found")

    first = events[0]
    first_name = getattr(first, "name", None)
    first_type = getattr(first, "type", None)
    if not (
        first.event == "span_begin"
        and first_type == "checkpoint"
        and first_name == "checkpoint 1"
    ):
        raise RuntimeError(
            f"[hydrate.validate] events[0] not 'span_begin checkpoint 1': "
            f"{_event_label(first)}"
        )

    last = events[-1]
    if last.event != "span_end":
        raise RuntimeError(
            f"[hydrate.validate] events[-1] not 'span_end': {_event_label(last)}"
        )

    expected_names = [f"checkpoint {i + 1}" for i in range(len(begins))]
    actual_names = [name for _, name, _ in begins]
    if actual_names != expected_names:
        raise RuntimeError(
            f"[hydrate.validate] checkpoint span names not sequential. "
            f"expected {expected_names}, got {actual_names}"
        )

    unpaired = [(idx, name, id_) for idx, name, id_ in begins if id_ not in end_by_id]
    if unpaired:
        raise RuntimeError(
            f"[hydrate.validate] {len(unpaired)} unpaired checkpoint "
            f"span_begin(s): {unpaired}"
        )

    expected_span_count = latest_committed_id if latest_committed_id is not None else 0
    if expected_span_count != len(begins):
        raise RuntimeError(
            f"[hydrate.validate] expected {expected_span_count} checkpoint "
            f"spans (per latest committed id {latest_committed_id}), got "
            f"{len(begins)}"
        )

    if len(sidecars) != len(begins):
        raise RuntimeError(
            f"[hydrate.validate] sidecar count ({len(sidecars)}) != "
            f"checkpoint span count ({len(begins)})"
        )

    print("[hydrate.validate] ✓ resume sanity checks passed")
    print(
        f"[hydrate.validate] === ready for checkpoint {len(begins) + 1} "
        f"(prior: {len(begins)}) ==="
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
