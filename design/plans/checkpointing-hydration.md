# Inspect Checkpointing — Resume Hydration Design

> Companion to [checkpointing-working.md](./checkpointing-working.md). The
> top-level design doc covers checkpoint *writing*; this doc covers
> checkpoint *reading on resume* — what `Checkpointer.__aenter__` does
> on the retry side of the loop.

## Context

A retried eval (`inspect eval-retry <log>`) produces a brand-new eval log
with its own `eval_id` and its own sibling `<new-log-base>.checkpoints/`
directory. Three sample populations end up in that retry eval:

1. **Completed-in-old**: read from the old log as `EvalSample`, copied
   verbatim into the new log via `logger.complete_sample(...)`. Never
   reaches `Checkpointer.__aenter__`.
2. **Resumed**: incomplete in the old eval but had at least one
   checkpoint. The sample source returns a `ResumeCheckpoint` carrying
   the old sample checkpoints dir. The agent's
   `async with checkpointer():` must yield a `Checkpointer` whose
   visible state continues the old story.
3. **Fresh-in-retry**: incomplete in the old eval with no checkpoint
   (e.g., errored before any checkpoint fired), or newly added to the
   dataset since the original eval. No `ResumeCheckpoint`. Runs as a
   fresh sample inside the retry eval.

The goal: when the retry finally completes, the new eval log and its
eval checkpoints dir together tell the whole story — earlier retries'
sample checkpoints dirs can be discarded.

## Principles

- **Per-sample restic password.** Each sample's `restic/host/` and
  `restic/sandboxes/<name>/` repos are encrypted under a password
  local to that sample, stored in
  `<sample-id>__<epoch>/restic/restic-config.json`. The password is
  preserved across retries of the same sample via the FS copy at
  resume (§3a). There is no eval-level shared secret. Populations 2
  and 3 in the same retry eval do not interact — each sample carries
  its own password.
- **FS-level copy, not `restic copy`.** Resumed samples copy the old
  sample checkpoints dir into the new one at the filesystem level.
  Snapshot IDs are preserved (no re-encryption), copied checkpoint
  files remain self-consistent, and the new sample continues writing into
  the same repos.
- **Each subsystem hydrates its own state.** `Transcript`, `Store`,
  and `Checkpointer`-private state (agent-state dict from `track()`)
  each get populated by the same `_hydrate_*` call chain. The
  checkpointer subsystem owns hydration because it owns the on-disk
  format and the restic infrastructure.
- **Maximum parallelism.** Host and sandbox hydration are independent;
  per-sandbox hydration is independent across sandboxes. Both axes
  run concurrently via `tg_collect`.

## 1. Data layout

The on-disk layout is fully described in [§1 of the working
design](./checkpointing-working.md#1-data-layout). The hydration
flow specifically uses:

```
logs/
  foo.checkpoints/
    <sample-id>__<epoch>/
      ckpt-00001.json              # checkpoint file; references into host + sandboxes
      ...
      restic/
        restic-config.json         # { "restic_password": "..." }
        host/                      # restic repo
        sandboxes/<name>/          # restic repo
      context/                     # restic input (host context files)
```

`restic/restic-config.json` is the per-sample state file: one per
sample subtree, containing the restic password used to encrypt that
sample's `restic/host/` and `restic/sandboxes/<name>/` repos. Written
once at first checkpoint setup; never rewritten. There is no
eval-level manifest — each sample is independent. On retry, the
password rides forward to the new sample dir via the FS copy at
resume (§3a), so the new dir's repos unlock with the same password.

## 2. Resume info

A single dataclass on the sample boundary signals "this sample is being
resumed":

```python
@dataclass
class ResumeCheckpoint:
    sample_checkpoints_dir: str  # path to <old-eval>.checkpoints/<sample>__<epoch>
```

`ResumeCheckpoint | None` is threaded into `active_sample(...)` and into
the `_Checkpointer` constructor for every sample. The eval-level
inheritance problem doesn't exist (per-sample passwords) — fresh
samples in a retry eval simply pass `None` and mint their own password
without any awareness of the surrounding retry.

## 3. Hydration function structure

`_Checkpointer.__aenter__` delegates the entirety of its I/O to a
`_hydrate` function. The structure:

```
_hydrate(resume: ResumeCheckpoint | None) -> _HydrationResult
  ├─ Phase 1: synchronous prologue (paths, dirs, restic-config.json, restic binary)
  └─ Phase 2: parallel domain hydration
       ├─ _hydrate_host(resume, ...) -> _HostHydrationResult
       └─ _hydrate_sandboxes(resume, ...):
            └─ _hydrate_sandbox(name, paths, resume, ...)   # per sandbox, parallel
```

Each function takes `resume: ResumeCheckpoint | None` and branches
internally on fresh vs. resume. No "is this a retry" flag travels
separately.

### 3a. `_hydrate` (orchestrator)

Phase 1 — synchronous prologue, completes before Phase 2 begins:

- Compute paths (`eval_checkpoints_dir`, `sample_checkpoints_dir`,
  `sample_staging_dir` if the destination is remote, `sample_root`,
  `context_dir`).
- `mkdir` the dirs (with parents).
- Make `<sample_root>/restic/restic-config.json` exist:
  - **Fresh**: generate a fresh restic password; write
    `restic-config.json` (mkdir `restic/` first).
  - **Resume**: FS-copy
    `<old_sample_checkpoints_dir>/restic/restic-config.json` →
    `<sample_root>/restic/restic-config.json` (mkdir `restic/` first).
    Also FS-copy `<old_sample_checkpoints_dir>/ckpt-*.json` →
    `<sample_root>/`.
- `resolve_restic()` to find the host restic binary.
- **On resume only**: compute `latest_committed_id` = highest checkpoint
  id whose `ckpt-NNNNN.json` parses cleanly as a `Checkpoint`
  (`scan_latest_committed_id` walks the FS-copied checkpoint files
  high→low, returning the first that parses). Checkpoint files are the
  source of truth for what's committed; the value flows into Phase 2 so
  each domain can drop orphan restic snapshots tagged `ckpt-NNNNN` with
  N > latest_committed_id (snapshots written by a fire that completed
  its backup but never wrote its checkpoint file — see working.md §4d).

Phase 2 — parallel domain hydration via `tg_collect`:

- `_hydrate_host(resume, latest_committed_id, ...)`
- `_hydrate_sandboxes(resume, latest_committed_id, ...)`

After both complete, `_hydrate` returns a `_HydrationResult` carrying
whatever the agent-facing `_EnteredCheckpointer` needs at construction
(agent-state dict and the seeded condensed-events / msg-pool /
call-pool accumulators from `_hydrate_host`; anything else surfaced
by implementation).

### 3b. `_hydrate_host`

Reads the restic password from
`<sample_root>/restic/restic-config.json`. (No password parameter —
Phase 1 guarantees the file exists.)

**Fresh**: `init_repo(<sample_root>/restic/host, password)`.

**Resume**:

- FS-copy `<old_sample_checkpoints_dir>/restic/host/` →
  `<sample_root>/restic/host/` (entire repo: all snapshots, indexes,
  keys, locks, data).
- **Drop orphan snapshots.** `restic snapshots --json` against the new
  host repo; any snapshot tagged `ckpt-NNNNN` with N >
  `latest_committed_id` is forgotten (`restic forget <id>...`). After
  this, `restic restore latest` is guaranteed to pick the committed
  snapshot. The orphan packs stay on disk (no prune) — restic dedup
  means a future fire-N+1 backup shares blocks with the orphan
  rather than bloating the repo.
- Restic-restore the (now-latest) snapshot in the new host repo →
  `<sample_root>/context/`. Result: `events.json`,
  `events_data.json`, `attachments.json`, `store.json`, optionally
  `agent_state.json` on disk in the context subdir.
- Load `agent_state.json` (if present) into a `dict[str, Any]` for
  return to `_EnteredCheckpointer`. Used by `track()` to return
  persisted values.
- **Synthesize the trailing `CheckpointEvent`.** By construction
  (working.md §8a) the event for the most recently committed
  checkpoint is never in its own `events.json` — it's emitted after
  that fire's host context was written. Hydrate reads
  `ckpt-{latest_committed_id:05d}.json` (already known to parse via
  `scan_latest_committed_id`) into a `Checkpoint`,
  constructs `CheckpointEvent.from_details(checkpoint)`, overrides
  `timestamp` with `checkpoint.created_at`, and appends to the read
  events. The result is indistinguishable from a live emit.
- **Wrap rehydrated events in a `prior_run` span.** The events read
  from `events.json` contain the prior session's checkpoint spans
  (and possibly older `prior_run` wraps from earlier resumes — see
  §3b1). Hydrate slices the events after the last existing
  `prior_run` `span_end` (or the whole list if none) and wraps that
  tail in a new `prior_run N` span synthesized at resume time. Each
  resume adds exactly one new sibling wrap; the result after R
  resumes is R sibling `prior_run` spans followed by the current
  session's flat checkpoint spans.
- Push the wrapped events into the live `Transcript` (`ts._events.extend`,
  bypassing `_process_event` — the events are already in
  attachment-ref form and must not be reprocessed).
- Push `attachments.json` content into the live `Transcript`.
- Push `store.json` content into the `Store`.
- Seed the agent-facing checkpointer's accumulators (`_condensed_events`,
  `_msg_pool`, `_call_pool`) from the wrapped events / pools so the
  next fire writes a cumulative snapshot (old wrap + new spans). The
  per-fire condensing is incremental — `_events_consumed` is set
  lazily on the first `_open_next_span()` call to the transcript
  index where `span_begin checkpoint M+1` is about to land, so
  pre-first-span new-attempt setup events never enter the accumulator
  and `events.json` stays span-only (see working.md §5).
- **Validate.** `_validate_resume_state` raises `RuntimeError` if any
  resume invariant fails: events non-empty; `events[0]` is
  `span_begin name="checkpoint restore 1" type="prior_run"`; `events[-1]` is
  a `span_end`; checkpoint span names sequential
  `checkpoint 1..N`; `prior_run` wrap names sequential
  `checkpoint restore 1..M`; every `span_begin` pairs with a matching
  `span_end` by id; count of checkpoint spans equals
  `latest_committed_id`; checkpoint file listing matches that count;
  count of `CheckpointEvent`s equals `latest_committed_id` (one per
  committed checkpoint, including the synthesized trailing one);
  `CheckpointEvent` `checkpoint_id`s are sequential `1..N`.

After this completes, the framework-owned state (`Transcript`, `Store`)
contains the cumulative pre-resume history. The agent's continued run
appends forward to that.

#### 3b1. `prior_run` wrap mechanics

The wrap is a `SpanBeginEvent` + `SpanEndEvent` pair synthesized at
resume time with a fresh `shortuuid()` id and `parent_id=None` (the
wrap is a top-level sibling at the sample root). Numbering is
`f"checkpoint restore {next_n}"` where `next_n` is the count of existing
`prior_run` wraps in the read events plus 1.

Depth-0 `span_begin` events in the wrapped tail (in practice the
checkpoint span_begins) get `parent_id` rewritten to the new wrap's
id so the span hierarchy reflects the new structure rather than
carrying stale parent ids from the prior attempt's transcript.
`span_end` carries no `parent_id`, so it passes through unchanged.

The wrap's `timestamp` is the resume-time creation moment (default
for `BaseEvent`), not the prior session's run time — the wrap
represents the act of rehydrating, not the work being rehydrated.
The contained checkpoint spans keep their original timestamps.

### 3c. `_hydrate_sandbox` (per sandbox)

Runs once per sandbox declared in `config.sandbox_paths`. All sandboxes
hydrate in parallel.

Reads the restic password from `<sample_root>/restic/restic-config.json`.

Common to both flows: `inject_restic(env)` (installs the restic binary
inside the sandbox container).

**Fresh**: `init_sandbox_repo(env, password)`.

**Resume**:

- FS-copy `<old_sample_checkpoints_dir>/restic/sandboxes/<name>/` →
  `<sample_root>/restic/sandboxes/<name>/`.
- **Drop orphan snapshots** from the host-side sandbox repo (same
  rule as §3b: forget any snapshot tagged `ckpt-NNNNN` with N >
  `latest_committed_id`). Performed on the host-side copy *before*
  ingress so the in-container repo never sees the orphan packs.
- `ingress_sandbox(env, src_repo, password)`: tar the host-side
  repo's contents in memory, stream the tarball via stdin to a root
  `sh` invocation inside the container that extracts into
  `/opt/inspect-restic/repo`, then invoke the injected restic to
  `restic restore latest --target /` so the configured
  `sandbox_paths` are restored at their original absolute paths. The
  in-container repo is the same one that subsequent forward backups
  write to.
- Seed the in-container egress manifest by listing every file in the
  newly-extracted repo into `egress-manifest.txt` — the next fire's
  egress diff treats the inherited snapshots as already-shipped.

## 4. Sequence in `__aenter__`

```python
async def __aenter__(self) -> Checkpointer:
    if self._cached is not None:
        return self._cached

    result = await _hydrate(self._resume_checkpoint, ...)
    self._cached = _EnteredCheckpointer(
        config=self._config,
        sample_checkpoints_dir=result.sample_checkpoints_dir,
        sample_staging_dir=result.sample_staging_dir,
        sample_root=result.sample_root,
        context_dir=result.context_dir,
        host_restic=result.host_restic,
        host_repo=result.host_repo,
        restic_password=result.restic_password,
        resume_checkpoint=self._resume_checkpoint,
        agent_state=result.agent_state,   # None when fresh
    )
    return self._cached
```

The cache check makes second entry within the same sample a no-op —
`_hydrate` and its restic / FS / framework-state side effects do not
re-run.

## 5. Checkpoint numbering on resume

`_next_checkpoint_id` is **not** part of hydration. It's computed at
fire time by scanning `<sample_root>/ckpt-*.json` and using
`max(ids) + 1`. Because Phase 1 FS-copies the old checkpoint files
into the new dir, the count continues from where the checkpoint restore left off
without any explicit handoff through `_hydrate`.

## 6. Open edges

Items deliberately deferred to implementation time:

- **Error handling on resume.** If
  `<old_sample_checkpoints_dir>/restic/restic-config.json` is
  missing/corrupt, the FS copy partial-fails, or the restic restore
  fails, the default should be loud failure (raise from `_hydrate`;
  propagate from `__aenter__`). Silent fallback to fresh hides bugs
  and corrupts the "whole story" premise.
- **Cross-eval dir collision check.** The dropped eval-level manifest
  used to verify `eval_id` against the active eval, guarding against
  two evals landing in the same eval checkpoints dir via a shared
  `checkpoints_location` (i.e. the same evals checkpoints dir). In
  practice the per-eval log name embeds the eval_id UUID and is the
  source of the eval checkpoints dir name, so collision requires
  reusing a log filename — not a real scenario. Leaving the check out
  unless a concrete need emerges.
- **Orphan-snapshot semantics on a multi-fire crash.** Today's rule
  is "drop everything beyond the latest committed checkpoint file." A
  single fire interrupted between backup and checkpoint file leaves
  one orphan;
  multiple consecutive bad fires would leave a contiguous range, all
  dropped. If a future failure mode produces non-contiguous orphans,
  the rule still works (it's a tag-threshold, not a contiguity
  check), but worth confirming once we see real production data.
- **Pool pruning across resume.** Pools (`_msg_pool`, `_call_pool`)
  are seeded from `ctx.msg_pool` / `ctx.call_pool` verbatim — including
  entries referenced only by events that are now hidden inside a
  `prior_run` wrap. Pool bloat across many resumes is bounded by the
  total content size, not the number of resumes (content-addressed
  dedup), but a future tidy-up could prune entries unreferenced by
  the seeded condensed events.
