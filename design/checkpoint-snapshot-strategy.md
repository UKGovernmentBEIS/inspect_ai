# Checkpointing: pluggable sandbox snapshot strategies

Design and phasing plan for meridianlabs-ai/inspect_ai#143 (upstream
UKGovernmentBEIS/inspect_ai#4601): make sandbox state capture pluggable
via a `SandboxSnapshotStrategy` interface, so evals whose sandbox data
is dominated by large, high-entropy, frequently-rewritten files (training
state, database files, encrypted containers) aren't forced through
restic's incremental model — where every checkpoint stores roughly the
full dataset again and space can never be reclaimed mid-run.

## 1. Scope

**In scope** — everything sandbox-side:

- Provisioning of capture tooling inside the sandbox (fresh and
  resumed samples alike).
- Per-fire capture of sandbox paths and shipping to the destination.
- Resume: materializing a committed snapshot into a fresh sandbox.
- Retry handoff: carrying strategy state from a prior attempt's sample
  checkpoints dir into the new attempt.
- Orphan discard (snapshots from fires that never committed).
- Mid-run storage retention and end-of-eval cleanup of strategy data.

**Out of scope** — unchanged:

- Host-context capture (`context/` → host restic repo). It is small,
  uniform JSON with high inter-checkpoint overlap — restic's best case.
  It stays inlined in `checkpointer_impl` / `hydrate`; the host restic
  binary remains a dependency even when every sandbox uses a
  non-restic strategy.
- The commit protocol: `ckpt-NNNNN.json` written by the core remains
  the commit point, locally and (shipped last) at the destination.
- Triggers, spans, transcript store, `track()`, resume event
  rehydration/validation.

## 2. The boundary, as it exists today

The interface already exists in the code, inlined at two call sites:

| Lifecycle moment | Today's code |
| --- | --- |
| Fresh sample | `hydrate._hydrate_sandbox` (resume=None): `inject_restic(env)` → `init_sandbox_repo(env, password)` |
| Fire | `checkpointer_impl._backup_and_egress_sandbox`: `run_sandbox_backup(env, ...)` → `egress_sandbox(env, dest_repo=sandbox_repo_dir(sample_root, name), ...)`; then `_fire_once` runs `list_changed_files` host-side and records a `SnapshotDetails` per sandbox |
| Remote shipping | `_host_egress.host_egress`: manifest-diff the staging dir, ship in restic-aware safe order (`config`/`keys` → `data` → `index` → `snapshots` → `restic-config.json` → `ckpt-*.json` last) |
| Resume | `hydrate._hydrate_sandbox` (resume set): `_fs_copy_repo` (old sample dir → new sample root) → `_drop_orphan_snapshots` → `ingress_sandbox` (tar repo into container, `restic restore latest --target /`) |
| Retention | `retention: "delete" \| "retain"` — all-or-nothing at eval end *(defined and documented in config, but enforcement is not yet implemented — no eval-end delete exists in the code today)* |

Two pieces of restic knowledge currently leak outside this boundary and
must move inside it:

1. **`_host_egress._safe_order`** understands restic repo structure
   (tiers for `data`/`index`/`snapshots`). Under the new design each
   strategy ships its own data to the destination *inside*
   `snapshot()`; core host egress ships only core-owned files (host
   repo, `restic-config.json`, `ckpt-*.json`).
2. **`list_changed_files`** (the per-checkpoint file listing in
   `_fire_once`) diffs against the egressed restic repo. It becomes an
   implementation detail of the restic strategy, folded into what
   `snapshot()` returns; strategies that cannot cheaply list files
   return `files=None`.

## 3. Interface

Location: new subpackage `src/inspect_ai/util/_checkpoint/_snapshot/`,
with `_sandbox_restic/` becoming its first implementation.

```python
class SandboxSnapshotStrategy(Protocol):
    """Captures and restores one sandbox's bulk state for checkpointing.

    Contract (see §4 for the guarantees each method must honor):
    tooling placed in the sandbox must be root-only and invisible to
    the agent; bytes read out of the sandbox are untrusted; secrets
    reach the sandbox only via per-exec environment variables.
    """

    async def setup(self, env: SandboxEnvironment, ctx: SnapshotContext) -> None:
        """Every attempt: inject tooling; init fresh state unless resuming."""

    async def snapshot(
        self,
        env: SandboxEnvironment,
        paths: SandboxBackupPaths,
        checkpoint_id: int,
        ctx: SnapshotContext,
    ) -> SnapshotDetails:
        """Capture `paths`. Durable at the destination on return (§4.1)."""

    async def restore(
        self, env: SandboxEnvironment, ref: SnapshotDetails, ctx: SnapshotContext
    ) -> None:
        """Materialize the snapshot `ref` into a fresh sandbox."""

    async def adopt(self, prior: PriorAttempt, ctx: SnapshotContext) -> None:
        """Carry strategy state from a prior attempt into this one (§4.5)."""

    async def discard_orphans(
        self, latest_committed_id: int, ctx: SnapshotContext
    ) -> None:
        """Drop snapshots with checkpoint_id > latest_committed_id."""

    async def apply_retention(
        self,
        policy: SnapshotRetention,
        committed: list[CommittedSnapshot],
        ctx: SnapshotContext,
    ) -> None:
        """Reclaim storage per `policy`, best-effort (§4.4)."""

    async def cleanup(self, ctx: SnapshotContext) -> None:
        """Delete all strategy data (eval-end `retention="delete"`)."""
```

Supporting types:

- **`SnapshotContext`** — what the core provides to every call:
  sandbox name; the strategy's *storage area* (a host-local directory
  under the sample root and the corresponding destination URI prefix,
  owned entirely by the strategy — the core never reads inside it);
  the per-sample secret (today's restic password, reusable as a
  generic capture secret); the resolved `AsyncFilesystem`; whether
  this attempt is resuming (`resuming: bool`, so `setup` knows to
  initialize fresh state or leave it for `adopt`); trace/log
  helpers. Frozen per (sandbox, attempt); constructed by the core.
- **`PriorAttempt`** — the prior attempt's sample checkpoints dir
  (possibly remote) plus its storage-area prefix for this strategy.
- **`CommittedSnapshot`** — `(checkpoint_id, details)` pairs from
  committed checkpoint files, so `apply_retention` never has to
  re-derive commit state.
- **`SnapshotDetails`** — already `extra="allow"`; gains an optional
  `strategy: str` field (absent ⇒ `"restic-incremental"`, for
  compatibility with existing checkpoint dirs). `snapshot_id` is
  redefined as an **opaque string minted by the strategy** — the core
  stores it in the checkpoint file and hands it back verbatim to
  `restore()`. `size_bytes` is pinned down as **bytes added to the
  destination by this snapshot** (delta; restic's
  `data_added_packed`). Strategies whose snapshots are self-contained
  (archive) report the same number and may add `total_bytes` as an
  extra field.

Call-site mapping (extraction, not redesign):

| Protocol method | Extracted from |
| --- | --- |
| `setup` | `inject_restic` (every attempt) + `init_sandbox_repo` (fresh only) |
| `snapshot` | `run_sandbox_backup` + `egress_sandbox` + the sandbox-repo tiers of `host_egress` + `list_changed_files` |
| `restore` | `ingress_sandbox` |
| `adopt` | `_fs_copy_repo` |
| `discard_orphans` | `_drop_orphan_snapshots` |
| `apply_retention` | *(new — restic no-op until generation rotation)* |
| `cleanup` | *(net-new — the eval-end `retention: "delete"` option is documented today but unenforced; `cleanup` becomes its implementation point, scoped to the storage area)* |

Core call order: fresh sample, `setup` alone; resume, `setup` →
`adopt` → `discard_orphans` → `restore`. `setup` runs on *both* paths
because in-sandbox tooling must exist before `restore` executes it —
matching today's code, where `inject_restic` runs before the
fresh/resume branch in `_hydrate_sandbox`.
Per fire: `snapshot` (parallel across sandboxes, alongside the host
backup, via `tg_collect` exactly as today) → core writes the
checkpoint file → core ships core-owned files → `apply_retention`.

## 4. Interface guarantees

These are implicit in the restic code today; they become the Protocol's
documented contract, in restic-free vocabulary.

### 4.1 Durable before commit

When `snapshot()` returns, everything needed to restore that snapshot
already exists at the **destination** (the sample checkpoints dir,
which may be `s3://...`). Shipping happens inside the strategy — the
restic-specific upload ordering in `host_egress` moves into the restic
strategy. The core's commit point is unchanged: `ckpt-NNNNN.json` is
written (and, for remote destinations, shipped last) only after every
strategy's `snapshot()` has returned. Consequence: at any crash point,
the **latest committed checkpoint** at the destination is fully
restorable — its checkpoint file is either absent (the fire never
happened, as far as resume is concerned) or present along with all
data it references. The guarantee is deliberately scoped to the
latest: §4.4 retention may later reclaim data referenced by *older*
checkpoint files, which remain at the destination as history.

### 4.2 Interruption tolerance

A fire can be cancelled or killed at any `await`. A strategy must
tolerate this: partial state from an interrupted `snapshot()` must not
break the *next* `snapshot()` on the same live sample (restic achieves
this with the two-phase egress manifest), and must be invisible after
resume once `discard_orphans` runs. Strategy exceptions propagate to
`_fire`, where `max_consecutive_failures` decides whether the sample
continues — strategies raise with context, never swallow.

### 4.3 Restore into a fresh sandbox

`restore()` receives a *fresh* sandbox (same image/config, none of the
agent's runtime state) and must leave the captured paths byte-identical
to capture time, with original absolute paths, ownership, and modes.
It may assume `setup`, `adopt`, and `discard_orphans` ran first.

### 4.4 Retention is a policy, not delete commands

The core hands `apply_retention` a policy plus the full committed-
snapshot list; the strategy translates it into whatever it can do
safely. Hard floor: **never delete data required to restore the latest
committed checkpoint.** Weakened upper bound, explicitly allowed:
**retaining more than the policy asks is always legal** (restic keeps
everything until generation rotation exists; `reference` has nothing
to delete). The initial policy is minimal:

```python
@dataclass(frozen=True)
class SnapshotRetention:
    keep_last: int | None = None   # None = keep everything
```

Thinning under `keep_last` deletes snapshot data for older *committed*
checkpoints while their `ckpt-*.json` files remain at the destination
(still useful as history and metadata). This is deliberate, and is why
§4.1's restorability guarantee is scoped to the latest committed
checkpoint: resume only ever targets the latest, and any future
resume-from-an-older-checkpoint feature (or tooling that reads older
checkpoint files) must treat their snapshot data as potentially
reclaimed.

Room to grow (keep-every-Nth, size budget) without touching the
Protocol, since the policy object is the extension point. The existing
eval-end `retention: "delete" | "retain"` is unchanged and maps to
`cleanup()`.

### 4.5 Adopt may be zero-copy locally — never at the destination

`adopt` hands strategy state across retry attempts. The restic
strategy copies the prior repo (snapshot ids and password must
survive). Other strategies may skip local materialization — fetching
bytes only when `restore` needs them — but one obligation cannot be
deferred: by the time `adopt()` returns, every snapshot the strategy
retains (at minimum, whatever is required to restore the latest
committed checkpoint) must be durable at **this attempt's**
destination. The deadline is adopt-return, not the next commit: the
core ships the adopted `ckpt-*.json` files to this attempt's
destination when hydration completes (today's `host_egress` before any
agent work), and from that moment §4.1 must hold — deferring
durability would leave a crash window where committed checkpoint files
sit at the destination while the data they reference exists only in
the prior attempt's dir, which the *next* retry never reads. Copying
the bounded `keep_last` archives at adopt time is the simple compliant
choice; a destination-to-destination server-side copy satisfies it
without pulling bytes through the host. After `adopt`,
`restore`/`discard_orphans`/`snapshot` must work and guarantee §4.1
for *new* snapshots.

### 4.6 Security requirements (Protocol docstring, normative)

Copied from the restic implementation's hard-won properties:

- Tooling placed inside the sandbox lives under a root-only (0700)
  path whose *parent* is unlistable by the agent (the
  `/root/.cache/inspect` pattern), streamed in via root `sh` stdin so
  bytes never touch an agent-readable temp path.
- Any in-sandbox staging must sit inside that area and be excluded
  from the strategy's own capture.
- Bytes read out of the sandbox are attacker-controlled: host-side
  handling must never extract them onto the host filesystem without
  path-safety (`tarfile filter="data"`; see `_extract_tar`), and never
  execute or parse them with anything less than full distrust.
- Secrets reach the sandbox only via per-exec environment variables
  (`env=` on `exec`), never persisted to sandbox disk.
- All in-sandbox execution runs as `user="root"`; output must respect
  `MAX_EXEC_OUTPUT_SIZE` (suppress progress streams — see
  `run_sandbox_backup`'s `--quiet` note).

### 4.7 Strategy identity is recorded and pinned

Resume must never run one strategy over another strategy's data, and a
strategy change between attempts must surface as an error, never be
applied silently. Two persisted records enforce this:

- **Per snapshot:** each `SnapshotDetails` written into a checkpoint
  file records its `strategy` name, so every checkpoint file is
  self-describing. Absent field ⇒ `"restic-incremental"` (pre-change
  checkpoint dirs).
- **Per sample — the pin:** at fresh-sample hydration the core writes
  `snapshot-strategies.json` (sandbox name → strategy name) into the
  sample checkpoints dir, shipped with the other core-owned files. The
  pin exists from before the first fire, so it protects even attempts
  that die before any checkpoint commits. Absent file ⇒
  `"restic-incremental"` for every sandbox (pre-pin dirs).

On resume/retry the core compares the pin against the currently
configured strategies *before* instantiating anything. Any mismatch is
a **hard error** naming the sandbox, the pinned strategy, and the
configured one, with the remedy stated (restore the original
configuration and resume, or start a fresh eval). A pinned strategy
name the current version doesn't know errors the same way. Strategy
*migration* on resume is explicitly a non-goal. The result: the
strategy that starts a sample's checkpoint lineage is the strategy for
its lifetime, and a config change between attempts is a clear,
recoverable error — never a silent misparse of one strategy's bytes by
another, and never a lineage left half-and-half.

## 5. Storage layout

Today: `restic/host/`, `restic/sandboxes/<name>/`,
`restic/restic-config.json`, `ckpt-*.json`, `context/`.

- The restic strategy keeps `restic/sandboxes/<name>/` **verbatim** as
  its storage area, so existing checkpoint dirs resume unchanged and
  Phase 1 is byte-identical on disk.
- New strategies get `sandboxes/<name>/<strategy>/` (e.g.
  `sandboxes/default/archive/ckpt-00007.tar.zst`). The core maps
  strategy → storage area in one place (`_layout`); strategies never
  compute sample-dir paths themselves.
- `restic/host/` and `restic-config.json` remain core-owned (host
  context capture); the per-sample secret in `restic-config.json`
  doubles as the generic capture secret handed to strategies via
  `SnapshotContext`.
- `snapshot-strategies.json` (the §4.7 pin, from Phase 2) is
  core-owned and sits beside `restic-config.json`.

## 6. Configuration

Phase 1 changes nothing: `sandbox_paths: dict[str, list[str]]` keeps
its exact semantics (auto-home default, empty list opts out) and maps
to a single path group under the default strategy.

Phase 2 adds strategy selection per sandbox; Phase 3 adds per-path-group
routing:

```python
CheckpointConfig(
    sandbox_snapshots={
        "default": [
            PathGroup(paths=["/home/user"]),                 # default strategy (restic)
            PathGroup(paths=["/data"],
                      strategy=ArchiveSnapshots(retention=SnapshotRetention(keep_last=2))),
            PathGroup(paths=["/models"],
                      strategy=ReferenceSnapshots(sources=...)),
        ]
    }
)
```

Decisions embedded there:

- **Strategy configs are dataclasses, not strings** — each strategy
  has its own knobs (compression, retention, source manifests).
  Referencing by registry name can come later for third-party
  strategies; the initial registry is internal.
- **Composite routing is core-owned, not a strategy.** The core
  instantiates one strategy instance per (sandbox, group) and fans out
  `snapshot()` calls; there is no "strategy containing strategies" to
  design. Groups within a sandbox must be disjoint (validated at
  config resolution — overlap would double-capture and make restore
  order significant).
- `sandbox_paths` and `sandbox_snapshots` are mutually exclusive per
  merge layer; `sandbox_paths` remains the simple spelling
  indefinitely.
- Checkpoint schema for multi-group: `Checkpoint.sandboxes[name]`
  stays a single `SnapshotDetails` while there is one group (Phase 1–2
  writes are schema-identical to today); Phase 3 introduces
  `Checkpoint.sandboxes[name].groups: list[SnapshotDetails]` behind
  the existing `extra="allow"` escape hatch, with single-group files
  still readable. This is the only schema change in the plan and it is
  deferred until a real multi-group user exists.

## 7. The three concrete strategies

### 7.1 `restic-incremental` (Phase 1)

Today's code nearly verbatim, plus absorbing the destination shipping
of `restic/sandboxes/<name>/**` (safe order preserved: `config`/`keys`
→ `data` → `index` → `snapshots`) and the `list_changed_files` step.
`apply_retention` is a documented no-op until generation rotation
(Phase 5). Best choice when most files are stable across checkpoints.

### 7.2 `archive` (Phase 2)

One complete tar (zstd if available in the sandbox, else uncompressed)
per checkpoint, streamed from the sandbox to
`sandboxes/<name>/archive/ckpt-NNNNN.tar[.zst]` at the destination —
never stored inside the sandbox and never fully buffered on the host.

- `setup`: verify `tar` exists (it's in effectively every image);
  record compression availability. Nothing injected.
- `snapshot`: in-sandbox root `tar -c` of the include paths (with
  excludes), streamed out (§8), hashed in flight (`content_sha256`
  recorded in details), shipped via
  `AsyncFilesystem.write_file_streaming`. `size_bytes` = archive size.
- `restore`: fetch the archive for `ref`, verify the recorded hash,
  stream into the sandbox via root `sh` stdin, `tar -x -C /`.
  Extraction happens *inside* the sandbox, so untrusted-bytes handling
  on the host reduces to hash verification.
- `adopt`: copy the retained archives (bounded by `keep_last`) from
  the prior attempt's dir — the simple choice compliant with §4.5.
- `discard_orphans` / `apply_retention`: delete one file per
  checkpoint. This is the strategy where mid-run reclamation is
  trivial, which is the point.

### 7.3 `reference` (Phase 4)

For large files that are re-downloadable or reproducible (model
weights, datasets): store only a manifest.

- Config maps path patterns to source specs (URI + expected digest, or
  a re-derivation command).
- `snapshot`: hash the matched files in-sandbox (root `sha256sum`),
  write a small manifest JSON to the storage area. `size_bytes` ≈ 0.
  A digest mismatch versus the configured source is detected here and
  is a hard error by default (the file was mutated and is *not*
  reproducible — silently "restoring" the original on resume would
  corrupt the run) with an opt-out to record-and-warn.
- `restore`: re-fetch inside the sandbox per the source spec, verify
  digests against the manifest.
- `apply_retention`/`cleanup`: near no-ops.

## 8. Enabling infrastructure: streaming copy-out

`egress_sandbox` already carries a TODO: `read_file` on a single big
tar peaks host RAM at tarball size and can hit per-call timeouts on
slow providers. The archive strategy makes this unavoidable, so Phase 2
builds the shared primitive both need:

- Portable baseline: an in-sandbox producer runs `tar ... | split -b
  <chunk>` into the root-only staging area **with backpressure** — the
  producer pauses while the staging area holds a full window of chunks
  and resumes as the host deletes shipped ones (portably, a `split
  --filter` wrapper that blocks until its chunk file is removed). The
  host loops: `read_file` the next chunk, accumulate the hash, feed
  the bytes to the destination write, delete the chunk. Backpressure
  is what delivers the disk bound — sandbox disk peaks at the window
  (a couple of chunks) beyond the live data. Without it, `tar | split`
  as a single exec completes before the host's first `read_file` can
  run, staging the entire archive and reproducing today's
  full-tarball peak.
- The destination side is one long-lived streaming upload fed
  chunk-by-chunk — S3 has no append — so the primitive needs an
  async-iterator-fed variant of `AsyncFilesystem.write_file_streaming`
  (today it takes a complete readable source).
- Providers whose `exec` can stream stdout may later plug in true
  streaming; the primitive's interface (async byte iterator out of a
  sandbox command) leaves room without contract changes.

The restic strategy's egress adopts the same primitive, retiring the
TODO.

## 9. Testing

- **Parametrize the existing e2e suite** (`tests/checkpoint/`) over
  strategies via a fixture param — Phase 1 with the single restic
  value proves the harness; Phase 2 adds `archive` and inherits every
  scenario (fire, resume, kill-mid-fire via the existing
  `resume_kill_harness`, remote destination via the existing S3/moto
  tests).
- **Contract test suite** runnable against any strategy:
  snapshot→restore roundtrip fidelity (content, paths, ownership,
  modes); durable-before-commit (destination inspected between
  `snapshot()` return and checkpoint-file write); kill during
  `snapshot()` then resume lands on the last committed checkpoint;
  `discard_orphans` removes exactly the uncommitted tail;
  `apply_retention` honors the floor (latest committed always
  restorable) under `keep_last=1`; retry under a different configured
  strategy fails with the §4.7 pin error; agent-invisibility (non-root
  `ls` of tooling/staging paths fails).
- Per-strategy unit tests for the mechanisms (manifest diffing, chunked
  copy-out, hash verification).

## 10. Phasing plan

**Phase 1 — Extract the boundary (behavior-neutral).**
Define the Protocol, `SnapshotContext`, and supporting types; move
`_sandbox_restic/` behind `ResticIncrementalStrategy`; route
`checkpointer_impl._backup_and_egress_sandbox` and
`hydrate._hydrate_sandbox` through the Protocol; move the
sandbox-repo tiers of `host_egress` and the `list_changed_files` step
into the strategy; record `strategy` in `SnapshotDetails`; parametrize
the e2e tests and land the contract suite. On-disk layout and
checkpoint schema byte-identical; resume from pre-change checkpoint
dirs covered by a compat test. The one ordering change: sandbox data
reaches a remote destination *before* the local checkpoint-file write
instead of after — strictly safer, same safe order overall.
*Exit criteria: full existing suite green (local + S3 destinations,
kill/resume harnesses) with no test assertions weakened.*

**Phase 2 — `archive` strategy + retention policy + streaming
copy-out.** The maximally different implementation that pressure-tests
the interface, directly serving the large-rewritten-data scenario.
Adds `SnapshotRetention`, per-sandbox strategy selection in config,
the §4.7 strategy pin (`snapshot-strategies.json` written at fresh
hydration, checked on resume/retry), the chunked/streaming copy-out
primitive (restic egress migrates onto it), and e2e parametrization
over both strategies.
*Exit criteria: contract suite passes for archive; a retry with a
changed strategy config fails with the §4.7 pin error; a
large-high-entropy-file scenario test demonstrates bounded destination
storage under `keep_last=N` and bounded sandbox disk during capture.*

**Phase 3 — Per-path-group routing.** `sandbox_snapshots` config with
disjointness validation, core-owned fan-out of one strategy instance
per (sandbox, group), multi-group checkpoint schema (§6). Gate on a
concrete user; the seam is designed now so nothing in Phases 1–2
blocks it.

**Phase 4 — `reference` strategy.** Manifest + re-fetch + verify, per
§7.3. Exercises the "storage cost near zero" corner of the interface
(snapshot writes almost nothing; restore does network work inside the
sandbox).

**Phase 5 — Restic generation rotation.** The restic strategy's answer
to `apply_retention`: periodically start a fresh repo generation
(`.../gen-K/`), take one full backup into it, and delete the previous
generation wholesale once a checkpoint committed against the new one —
reclaiming space without ever running `restic prune` (whose pack-file
rewrites the ship-once egress protocol cannot tolerate). Pure
implementation work inside one strategy; no interface change, which is
itself a test that the Phase 1 boundary was drawn correctly.

Deliberately unscheduled: provider-native snapshots (ZFS, `docker
commit`, volume snapshots). The Protocol leaves room — it receives the
`SandboxEnvironment`, assumes nothing about file-level capture, and
uses opaque snapshot ids — but is not designed around them.

## 11. Risks

- **Designing around restic's shape.** The discipline is §4: the
  contract speaks only in observable guarantees (durable on return,
  restore into a fresh sandbox, retention floor, agent invisibility)
  and no restic vocabulary. The concrete check: if `archive` (Phase 2)
  and `reference` (Phase 4) implement without contortions and
  generation rotation (Phase 5) needs no interface change, the
  boundary is right. Phase 2 is deliberately scheduled early as the
  falsifier.
- **Streaming copy-out portability.** The `split`-based baseline works
  on any POSIX sandbox but costs a bounded window of chunks of sandbox
  disk and per-chunk exec round-trips; very slow providers may need
  tuning.
  Mitigation: chunk size configurable; primitive isolated so
  provider-native streaming can replace it transparently.
- **Schema drift.** Only Phase 3 touches the checkpoint file schema;
  `extra="allow"` plus the `strategy`-absent-⇒-restic rule keeps old
  dirs resumable throughout. The compat test in Phase 1 pins this.
- **Retry-across-config-changes.** §4.7's pin (`snapshot-strategies.json`
  plus per-snapshot identity) turns a mid-eval-set strategy change
  from silent corruption into a clear, recoverable error — restore the
  original configuration and resume; strategy *migration* on resume is
  explicitly a non-goal.
