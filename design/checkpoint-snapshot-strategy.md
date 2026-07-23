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
| Retention | `retention: "delete" \| "retain"` — all-or-nothing at eval end *(defined and merged in `config.py`, but not yet enforced — no eval-end delete is implemented)* |

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
        """Provision a new sandbox instance (fresh sample *and* resume).

        Called before any other method that touches the sandbox: inject
        tooling; when `ctx.resuming` is false, also initialize fresh
        strategy state.
        """

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
  generic capture secret); whether this attempt is a resume
  (`resuming`); the resolved `AsyncFilesystem`; trace/log helpers.
  Frozen per (sandbox, attempt); constructed by the core.
- **`PriorAttempt`** — the prior attempt's sample checkpoints dir
  (possibly remote) plus its storage-area prefix for this strategy.
- **`CommittedSnapshot`** — `(checkpoint_id, details)` pairs from the
  committed checkpoint files that survive the retention policy (§4.4),
  so `apply_retention` never has to re-derive commit state.
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
| `setup` | `inject_restic` (both paths) + `init_sandbox_repo` (fresh only, gated on `ctx.resuming`) |
| `snapshot` | `run_sandbox_backup` + `egress_sandbox` + the sandbox-repo tiers of `host_egress` + `list_changed_files` |
| `restore` | `ingress_sandbox` |
| `adopt` | `_fs_copy_repo` |
| `discard_orphans` | `_drop_orphan_snapshots` |
| `apply_retention` | *(new — restic no-op until generation rotation)* |
| `cleanup` | eval-end retention delete, scoped to the storage area *(net-new enforcement — the `retention` option is defined in `config.py` today but nothing reads it outside config resolution; no eval-end delete exists yet)* |

Core call order on resume: `setup` → `adopt` → `discard_orphans` →
`restore` (matching today's hydrate path, where `inject_restic` runs
before the repo copy/ingress on resume too).
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
the destination either lacks the checkpoint file (fire never happened,
as far as resume is concerned) or has it along with all data it
references. This holds for *every* checkpoint file present, not just
the latest — §4.4's retention preserves it by removing a checkpoint's
file before its data.

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

The core hands `apply_retention` a policy plus the committed-snapshot
list; the strategy translates it into whatever it can do safely.
Enforcement is checkpoint-file-first so §4.1's crash consequence keeps
holding: before invoking `apply_retention`, the core deletes the
`ckpt-*.json` files that fall outside the policy (destination copy,
then local) and passes only the surviving snapshots in `committed` — a
checkpoint file never outlives the data it references, and older
thinned checkpoints stop being advertised as resumable rather than
lingering as files whose data is gone. Hard floor: **never delete data
required to restore a snapshot in `committed`** (the policy always
retains at least the latest committed checkpoint). Weakened upper
bound, explicitly allowed: **retaining more than the policy asks is
always legal** (restic keeps everything until generation rotation
exists; `reference` has nothing to delete). The initial policy is
minimal:

```python
@dataclass(frozen=True)
class SnapshotRetention:
    keep_last: int | None = None   # None = keep everything
```

Room to grow (keep-every-Nth, size budget) without touching the
Protocol, since the policy object is the extension point. The existing
eval-end `retention: "delete" | "retain"` is unchanged and maps to
`cleanup()`.

### 4.5 Adopt may be zero-copy

`adopt` hands strategy state across retry attempts. The restic
strategy copies the prior repo (snapshot ids and password must
survive). The archive strategy may instead record prior-attempt URIs
and lazily fetch only what `restore` needs — the contract requires
only that after `adopt`, `restore`/`discard_orphans`/`snapshot` work
and guarantee 4.1 for *new* snapshots. One subtlety the contract must
state: retained snapshots must be durable at **this attempt's**
destination *before the core ships the adopted checkpoint files* (at
the end of hydration, before any agent work — a later retry reads only
this attempt's sample dir, and once those `ckpt-*.json` files land, a
crash must not leave them referencing data absent from this attempt's
destination, the state §4.1 rules out). Since the core ships
immediately after the resume call sequence returns, in practice the
data must be durable by the time `restore` returns. This is exactly
what today's hydrate-runs-`host_egress`-before-agent-work behavior
implements; strategies inherit the same obligation for their own data
— copying bounded `keep_last` archives at adopt time is the simple
compliant choice.

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
applied silently (allowing new snapshots to switch strategies mid-
lineage would leave a sample's checkpoint history half-and-half, with
retention and adopt semantics straddling two implementations). Two
persisted records enforce this:

- **Per snapshot:** each `SnapshotDetails` written into a checkpoint
  file records its `strategy` name, so every checkpoint file is
  self-describing. Absent field ⇒ `"restic-incremental"` (pre-change
  checkpoint dirs).
- **Per sample — the pin:** at fresh-sample hydration the core writes
  `snapshot-strategies.json` (sandbox name → strategy name) into the
  sample checkpoints dir, shipped with the other core-owned files. On
  resume the pin rides across attempts with the cross-cutting copy
  (alongside `restic-config.json` and the `ckpt-*.json` files in
  `_fs_copy_cross_cutting`), so every attempt's dir carries it no
  matter how many retries preceded — without that carry-over, the
  second retry of a non-default-strategy sample would find no pin and
  the absent-file default would turn into a spurious mismatch error.
  Writing at fresh hydration means the pin is present in every dir a
  retry can actually resume from: resume only happens when a committed
  `ckpt-*.json` exists (`has_sample_checkpoint` gates it), so a
  zero-commit attempt's dir is never read — its retry re-runs fresh
  and writes its own pin. Absent file ⇒ `"restic-incremental"` for
  every sandbox (pre-pin dirs).

On resume/retry the core compares the pin against the currently
configured strategies *before* instantiating anything. Any mismatch is
a **hard error** naming the sandbox, the pinned strategy, and the
configured one, with the remedy stated (restore the original
configuration and resume, or start a fresh eval). A pinned strategy
name unknown to the current build errors the same way, as does a
configured sandbox with no pin entry — the sandbox set changed between
attempts, which today surfaces only as a downstream copy failure
(`_fs_copy_repo` raising on an empty source); the pin check turns it
into the same clear, named error. Strategy
*migration* on resume is explicitly a non-goal. The result: the
strategy that starts a sample's checkpoint lineage is the strategy for
its lifetime, and a config change between attempts is a clear,
recoverable error — never a silent misparse of one strategy's bytes by
another.

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
  writes add only the optional `strategy` field to today's schema);
  Phase 3 introduces
  `Checkpoint.sandboxes[name].groups: list[SnapshotDetails]` behind
  the existing `extra="allow"` escape hatch, with single-group files
  still readable. In multi-group files the wrapper's required fields
  hold aggregates: `size_bytes` sums the groups, `duration_ms` is the
  wall-clock of the parallel fan-out, and `snapshot_id` is a
  core-minted sentinel — restore never reads the wrapper's id, routing
  is per group. The §4.7 pin gains a per-group form at the same time
  (sandbox name → per-group strategy names), since one sandbox then
  spans multiple strategies. This is the only checkpoint-schema change
  in the plan and it is deferred until a real multi-group user exists.

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
never fully buffered on the host, with only transient staging inside
the sandbox (chunks during capture, §8; the staged archive during
restore).

- `setup`: verify `tar` exists (it's in effectively every image);
  record compression availability. Nothing injected.
- `snapshot`: in-sandbox root `tar -c` of the include paths (with
  excludes), streamed out (§8), hashed in flight (`content_sha256`
  recorded in details), shipped via
  `AsyncFilesystem.write_file_streaming`. `size_bytes` = archive size.
- `restore`: fetch the archive for `ref` chunk-by-chunk via the
  copy-in counterpart of the §8 primitive — `exec` takes fully
  materialized `input` bytes, so a single stdin-stream of the whole
  archive would buffer it entirely in host RAM (and can exceed
  per-call provider limits), the copy-out problem in reverse, made the
  common case by exactly this strategy. Each chunk is appended (root
  `sh` stdin, per-exec) to a staging file inside the root-only area;
  once complete, verify the recorded hash against the staged file
  in-sandbox, then `tar -x -C /` and delete the staging file.
  Verify-then-extract costs transient sandbox disk equal to the
  archive size, but a corrupt archive is rejected before any byte
  reaches a final path. Extraction happens *inside* the sandbox, so
  untrusted-bytes handling on the host reduces to hash verification.
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
  A digest mismatch versus the configured source is a hard error by
  default (the file was mutated and is *not* reproducible — silently
  "restoring" the original later would corrupt the resumed run) with
  an opt-out to record-and-warn.
- `restore`: re-fetch inside the sandbox per the source spec, verify
  digests.
- `apply_retention`/`cleanup`: near no-ops.

## 8. Enabling infrastructure: streaming copy-out and copy-in

`egress_sandbox` already carries a TODO: `read_file` on a single big
tar peaks host RAM at tarball size and can hit per-call timeouts on
slow providers. The archive strategy makes this unavoidable, so Phase 2
builds the shared primitive both need:

- Portable baseline: a *detached* in-sandbox producer (root `sh`
  started in the background) reads the `tar` pipe in fixed-size chunks
  via a small `sh` loop (`dd`/`head -c` per chunk, accumulating short
  pipe reads up to the chunk size — **not** `split --filter`, a GNU
  coreutils extension absent from busybox and POSIX `split`, so
  unavailable on Alpine-style minimal images), writes each chunk into
  the root-only staging area, and blocks while an unshipped chunk is
  already present — the producer is backpressure-gated on the host
  deleting chunks. The host loop waits for the next chunk,
  `read_file`s it with hash accumulation, feeds it to the destination
  write, and deletes it. This bounds sandbox disk to about two chunks
  (one being produced, one being shipped) beyond the live data —
  meeting the "no staging repository inside the sandbox" goal within a
  couple of chunks' tolerance. The gating is essential: an ungated
  producer finishes chunking before the host's first `read_file` can
  run, so every chunk would exist at once and peak sandbox disk would
  equal the full archive size.
- Copy-in gets the mirror-image primitive: fetch the destination
  object chunk-by-chunk, append each chunk to a root-only in-sandbox
  file via per-exec root `sh` stdin. `exec`'s fully materialized
  `input` otherwise forces the whole payload into host RAM — the same
  problem in reverse. First consumer: the archive strategy's `restore`
  (§7.2); `ingress_sandbox` (which today streams the entire repo tar
  through one exec) migrates onto it too.
- Destination side: object stores have no append, so "streaming to
  the destination" means one long-lived streaming write (a single S3
  multipart upload) fed chunk-by-chunk.
  `AsyncFilesystem.write_file_streaming` currently takes a complete
  source, so Phase 2 adds a sink-style API (open once, write chunks,
  close) to feed it.
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
  retention under `keep_last=1` honors the floor (latest committed
  always restorable) and removes thinned checkpoints' files from the
  destination before their data (§4.4); retry under a different
  configured strategy fails with the §4.7 pin error; agent-invisibility
  (non-root `ls` of tooling/staging paths fails).
- Per-strategy unit tests for the mechanisms (manifest diffing, chunked
  copy-out and copy-in, hash verification).

## 10. Phasing plan

**Phase 1 — Extract the boundary (behavior-neutral).**
Define the Protocol, `SnapshotContext`, and supporting types; move
`_sandbox_restic/` behind `ResticIncrementalStrategy`; route
`checkpointer_impl._backup_and_egress_sandbox` and
`hydrate._hydrate_sandbox` through the Protocol; move the
sandbox-repo tiers of `host_egress` and the `list_changed_files` step
into the strategy; record `strategy` in `SnapshotDetails`; parametrize
the e2e tests and land the contract suite. On-disk layout
byte-identical; checkpoint schema backward-compatible, not identical —
new files add only the optional `strategy` field, and pre-change files
parse unchanged (absent ⇒ restic); resume from pre-change checkpoint
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
and copy-in primitives (restic egress and ingress migrate onto them),
and e2e parametrization over both strategies.
*Exit criteria: contract suite passes for archive; a retry with a
changed strategy config fails with the §4.7 pin error; a
large-high-entropy-file scenario test demonstrates bounded destination
storage under `keep_last=N` and bounded sandbox disk during capture.*

**Phase 3 — Per-path-group routing.** `sandbox_snapshots` config with
disjointness validation, core-owned fan-out of one strategy instance
per (sandbox, group), multi-group checkpoint schema and the per-group
pin form (§6). Gate on a
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
- **Streaming copy-out portability.** The chunked baseline needs only
  `sh`, `tar`, and byte-counted reads (`dd`/`head -c`) — all present
  in busybox and every mainstream image (`split --filter` was rejected
  as GNU-only) — but costs a couple of chunks of sandbox disk
  and per-chunk exec round-trips; very slow providers may need tuning.
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
