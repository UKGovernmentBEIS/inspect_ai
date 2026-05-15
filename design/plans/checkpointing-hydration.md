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

- **Per-sample restic password.** Each sample's `host/` and
  `sandboxes/<name>/` repos are encrypted under a password local to
  that sample, stored in `<sample-id>__<epoch>/sample.json`. The
  password is preserved across retries of the same sample via the
  FS copy at resume (§3a). There is no eval-level shared secret.
  Populations 2 and 3 in the same retry eval do not interact — each
  sample carries its own password.
- **FS-level copy, not `restic copy`.** Resumed samples copy the old
  sample checkpoints dir into the new one at the filesystem level.
  Snapshot IDs are preserved (no re-encryption), copied sidecars
  remain self-consistent, and the new sample continues writing into
  the same repos.
- **Each subsystem hydrates its own state.** `Transcript`, `Store`,
  and `Checkpointer`-private state (agent-state dict from `track()`)
  each get populated by the same `_hydrate_*` call chain. The
  checkpointer subsystem owns hydration because it owns the on-disk
  format and the restic infrastructure.
- **Maximum parallelism.** Host and sandbox hydration are independent;
  per-sandbox hydration is independent across sandboxes. Both axes
  run concurrently via `tg_collect`.

## 1. Data layout changes

Two changes relative to [§1 of the working design](./checkpointing-working.md):

```
logs/
  foo.checkpoints/
    <sample-id>__<epoch>/
      sample.json          # NEW: { "restic_password": "..." }
      ckpt-00001.json      # (unchanged) sidecar; references into host + sandboxes
      ...
      host/                # (unchanged) restic repo
      sandboxes/<name>/    # (unchanged) restic repo
```

- **`sample.json`** — peer of the sidecars; one per sample subtree.
  Contains the restic password used to encrypt that sample's `host/`
  and `sandboxes/<name>/` repos. Written once at first checkpoint
  setup; never rewritten.
- **No eval-level `manifest.json`.** The eval-level manifest is
  removed. Eval-wide identity verification is moved to the sample
  checkpoints dir (or dropped entirely; see §6).

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
  ├─ Phase 1: synchronous prologue (paths, dirs, sample.json, restic binary)
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

- Compute paths (`eval_checkpoints_dir`, `new_sample_checkpoints_dir`, `sample_working_dir`).
- `mkdir` the dirs (with parents).
- Make `<new_sample_checkpoints_dir>/sample.json` exist at the new location:
  - **Fresh**: generate a fresh restic password; write `sample.json`.
  - **Resume**: FS-copy `<old_sample_checkpoints_dir>/sample.json` →
    `<new_sample_checkpoints_dir>/sample.json`. Also FS-copy
    `<old_sample_checkpoints_dir>/ckpt-*.json` → `<new_sample_checkpoints_dir>/`.
- `resolve_restic()` to find the host restic binary.

Phase 2 — parallel domain hydration via `tg_collect`:

- `_hydrate_host(resume, ...)`
- `_hydrate_sandboxes(resume, ...)`

After both complete, `_hydrate` returns a `_HydrationResult` carrying
whatever the agent-facing `_EnteredCheckpointer` needs at construction
(agent-state dict from `_hydrate_host`; anything else surfaced by
implementation).

### 3b. `_hydrate_host`

Reads the restic password from `<new_sample_checkpoints_dir>/sample.json`. (No
password parameter — Phase 1 guarantees the file exists.)

**Fresh**: `init_host_repo(<new_sample_checkpoints_dir>/host, password)`.

**Resume**:

- FS-copy `<old_sample_checkpoints_dir>/host/` → `<new_sample_checkpoints_dir>/host/` (entire
  repo: all snapshots, indexes, keys, locks, data).
- Restic-restore the latest snapshot in the new host repo →
  `<sample_working_dir>/`. Result: `events.json`, `events_data.json`,
  `attachments.json`, `store.json`, optionally `agent_state.json`
  on disk in the sample working dir.
- Load `agent_state.json` (if present) into a `dict[str, Any]` for
  return to `_EnteredCheckpointer`. Used by `track()` to return
  persisted values.
- Push `events.json` content into the live `Transcript`.
- Push `attachments.json` content into the live `Transcript`.
- Push `store.json` content into the `Store`.

After this completes, the framework-owned state (`Transcript`, `Store`)
contains the cumulative pre-resume history. The agent's continued run
appends forward to that.

### 3c. `_hydrate_sandbox` (per sandbox)

Runs once per sandbox declared in `config.sandbox_paths`. All sandboxes
hydrate in parallel.

Reads the restic password from `<new_sample_checkpoints_dir>/sample.json`.

Common to both flows: `inject_restic(env)` (installs the restic binary
inside the sandbox container).

**Fresh**: `init_sandbox_repo(env, password)`.

**Resume**:

- FS-copy `<old_sample_checkpoints_dir>/sandboxes/<name>/` →
  `<new_sample_checkpoints_dir>/sandboxes/<name>/`.
- FS-copy that data *into the sandbox container* at the standard
  in-container restic repo location. The container's in-repo path is
  used for both restore *and* subsequent forward backups — the same
  repo carries the old history forward.
- Restic-restore the latest snapshot inside the container → the paths
  declared in `config.sandbox_paths[<name>]`.

## 4. Sequence in `__aenter__`

```python
async def __aenter__(self) -> Checkpointer:
    if self._cached is not None:
        return self._cached

    result = await _hydrate(self._resume_checkpoint, ...)
    self._cached = _EnteredCheckpointer(
        config=self._config,
        sample_checkpoints_dir=result.sample_checkpoints_dir,
        sample_working_dir=result.sample_working_dir,
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
fire time by scanning `<new_sample_checkpoints_dir>/ckpt-*.json` and using
`max(ids) + 1`. Because Phase 1 FS-copies the old sidecars into the
new dir, the count continues from where the prior run left off
without any explicit handoff through `_hydrate`.

## 6. Open edges

Items deliberately deferred to implementation time:

- **Error handling on resume.** If `<old_sample_checkpoints_dir>/sample.json` is
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
- **`condense_*` pools across resume.** `_EnteredCheckpointer`'s
  `_msg_pool`, `_call_pool`, `_condensed_events`, `_events_consumed`
  start empty on a resumed sample. Because `_hydrate_host` pushes the
  old transcript events into the live `Transcript`, the next
  `_fire()` re-processes them from scratch through `condense_*` and
  the snapshot output is cumulative. This is more work per fire than
  carrying the pools forward, but keeps `_EnteredCheckpointer`'s
  surface unchanged.
