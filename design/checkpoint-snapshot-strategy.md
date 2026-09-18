# Checkpointing: pluggable sandbox snapshot strategies

> **Implementation status.** Phase 1 (the Protocol boundary,
> `ResticIncrementalStrategy`) and the core of Phase 2 (the `archive`
> strategy, per-sandbox strategy selection via `SandboxSnapshotConfig`
> values of `sandbox_paths` in the Python API and the
> `--checkpoint` YAML, and the §4.7 strategy pin) are implemented in
> `src/inspect_ai/util/_checkpoint/_snapshot/`. Mid-run retention
> (§4.4, `keep_last`) is designed but not yet offered — self-contained
> archives make it possible, and it lands as an additive
> `ArchiveSnapshots` field plus an `apply_retention` Protocol method
> once its policy questions (cross-sandbox coupling of effective
> retention, failure handling, who may set it) are settled. Deliberate
> deviations from the target state below, all forward-compatible:
>
> 1. **Shipping stays in core host egress for now.** Strategies write
>    into their storage area under the sample root inside
>    `snapshot()`; for remote destinations `host_egress` still ships
>    the storage area (catch-all tier, before `ckpt-*.json`) — the
>    same durability ordering as the pre-extraction restic behavior.
>    Moving shipping inside `snapshot()` lands with the §8 sink-style
>    streaming write.
> 2. **The archive copy-out stages the complete archive in-sandbox**
>    (root-only area), then chunk-copies it out via per-chunk `dd` +
>    `read_file`. Chunking limits host buffering when the sandbox follows
>    the protocol; it does not bound staging inside `read_file`. Transient
>    sandbox disk equals the archive size plus one chunk. The §8
>    detached-producer pipeline (two-chunk sandbox disk bound) is the
>    compatible follow-up; §8 point (d)'s cross-fire isolation reduces
>    to deleting the staging root at `snapshot()` start, since no
>    detached producer exists yet.
> 3. **`SnapshotDetails.strategy` rides as an `extra="allow"` field**
>    rather than a declared schema field (same absent ⇒
>    `restic-incremental` rule): declaring it would change the
>    generated public event schema / viewer types.
> 4. **`discard_orphans` receives the committed snapshot records**
>    (`Sequence[CommittedSnapshot]`, one per committed checkpoint that
>    records this sandbox) rather than a bare `latest_committed_id`.
>    The sandbox writes into its own restic repo, so "orphan" for the
>    restic strategy means *any* snapshot no committed checkpoint
>    records — not just ids past the latest — and the strategy must
>    raise if the latest committed record's snapshot is absent from the
>    adopted storage area. `restore` restores the recorded
>    `ref.snapshot_id`, whose receipt was checked during egress. A
>    sandbox with no committed record is a hard error at hydration
>    (nothing in its storage area can be vouched for), not a fallback
>    to `latest`.
>    The shared chunked copy-out (`_checkpoint/_copy.py`, capped by
>    `SnapshotContext.max_snapshot_bytes` from
>    `CheckpointConfig.max_sandbox_snapshot_bytes`) landed with this
>    change; both strategies use it.
> 5. **`restore` takes this attempt's `SandboxBackupPaths`** and is
>    scoped to them: `restore(env, paths, ref, ctx)`. The snapshot is
>    listed on the host before any byte enters the sandbox (`restic ls
>    --json` against the adopted repo; `tarfile` over the stored
>    archive) and refused if any node lies outside `paths.include`
>    (directories on the way to a root excepted), is a device, fifo or
>    socket, is a hard link out of scope, or is a regular file carrying
>    a setuid, setgid or sticky bit (`_checkpoint/_restore_scope.py`;
>    directory sticky/setgid bits carry no privilege and are kept, so
>    `/tmp` or a `g+s` shared dir can be a root). For the archive the
>    host's `tarfile` and the image's `tar` must also agree on member
>    boundaries: the raw header stream is scanned alongside `tarfile`
>    and refused on a PAX, sparse, device or fifo header (`tarfile`
>    consumes a PAX header without listing it), a repeated GNU long
>    header or one claiming more than 64 KiB (which `tarfile` would
>    read into memory whole), members carrying PAX records are refused,
>    only zero padding may follow the last parsed member, and
>    a `find` over the roots after extraction fails the restore on any
>    special file or device node the sandbox's tar produced anyway.
>    Each root is then restored individually (`restic restore
>    <id>:<parent> --target <parent> --include /<name> --include-xattr
>    user.*`; `tar -x -- <root>`) so nothing above a root is written or
>    has its metadata restored, and no `security.*`/`system.*` extended
>    attribute (file capabilities, ACLs) is reapplied. `snapshot()` records
>    `paths.include` as a `roots` extra on `SnapshotDetails`; a recorded
>    set that differs from this attempt's is an error naming both. For
>    an auto-included home dir the core re-owns everything restored
>    under it to the home dir's owner; configured `sandbox_paths` keep
>    recorded ownership (the documented residual).
>
> Strategy selection is accepted at every config layer — sample, task,
> and eval: `sandbox_paths` values are `list[str] |
> SandboxSnapshotConfig` on both `CheckpointSampleConfig` and its
> subclass `CheckpointConfig`. The strategy suits the workload's data,
> and the workload is sample-specific (one sample trains a large model,
> another does a coding exercise), so capture configuration — paths and
> strategy — is sample-settable; only the eval-wide storage policy
> (`checkpoints_location`, `retention`) is task/eval-only. Because
> `CheckpointSampleConfig` is recorded in the log schema (via
> `Sample.checkpoint`), the strategy config types are part of the
> generated viewer types (coordinated `ts-mono` regeneration).

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
| Remote shipping | `_host_egress.host_egress`: manifest-diff the staging dir, ship in restic-aware safe order (`config`/`keys` → `data` → `index` → `snapshots` → catch-all (everything unmatched) → `restic-config.json` → `ckpt-*.json` last) |
| Resume | retry startup copy (`_resume_copy.copy_resume_payloads`, before the new log exists) → `hydrate._hydrate_sandbox` (resume set): `forget_unrecorded_snapshots` (keep exactly the snapshots committed checkpoints record; the latest committed one must be present) → `ingress_sandbox` (tar repo into container, `restic restore <recorded snapshot id> --target /`) |
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
    tooling and staging must be root-only to protect against an
    unprivileged agent; sandbox root can access them. Transfer checks
    do not authenticate sandbox-supplied state. Secrets reach the
    sandbox only via per-exec environment variables.
    """

    async def setup(self, env: SandboxEnvironment, ctx: SnapshotContext) -> None:
        """Provision a new sandbox instance (fresh sample *and* resume).

        Called before any other method that touches the sandbox: inject
        tooling (for restic, this is where the restic binary is
        installed into the sandbox — today's `inject_restic`); when
        `ctx.resuming` is false, also initialize fresh strategy state
        (restic: `init_sandbox_repo`).
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

    async def discard_orphans(
        self, committed: Sequence[CommittedSnapshot], ctx: SnapshotContext
    ) -> None:
        """Drop every snapshot not recorded in `committed`; raise if the
        latest committed record's snapshot is absent."""

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
| `discard_orphans` | `_drop_orphan_snapshots` (now `forget_unrecorded_snapshots`, keyed on the committed records rather than a latest id) |
| `apply_retention` | *(new — restic no-op until generation rotation)* |
| `cleanup` | eval-end retention delete, scoped to the storage area *(net-new enforcement — the `retention` option is defined in `config.py` today but nothing reads it outside config resolution; no eval-end delete exists yet)* |

Core call order on resume: `setup` → `discard_orphans` → `restore`.
The strategy's storage area is already in the sample root by then: the
retry startup copy (`_resume_copy`) replicated the retried attempt's
whole sample dir, storage areas included, before this attempt's log
existed (§4.5).
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
this with the two-phase egress manifest; the archive strategy with
per-snapshot staging subdirs and stale-producer cleanup, §8 point d),
and must be invisible after resume once `discard_orphans` runs.
Strategy exceptions propagate to
`_fire`, where `max_consecutive_failures` decides whether the sample
continues — strategies raise with context, never swallow.

### 4.3 Restore into a fresh sandbox

`restore()` receives a *fresh* sandbox (same image/config, none of the
agent's runtime state) and must leave the captured paths byte-identical
to capture time, with original absolute paths, ownership, and modes.
It may assume `setup` and `discard_orphans` ran first, and that its
storage area holds the prior attempt's state (§4.5).

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
exists; the deferred `reference` sketch (§7.3) would have nothing to
delete). The initial policy is minimal:

```python
@dataclass(frozen=True)
class SnapshotRetention:
    keep_last: int | None = None   # None = keep everything
```

Room to grow (keep-every-Nth, size budget) without touching the
Protocol, since the policy object is the extension point. The existing
eval-end `retention: "delete" | "retain"` is unchanged and maps to
`cleanup()`.

### 4.5 Storage areas travel verbatim

The core, not the strategy, carries strategy state across retry
attempts. At retry startup — before the new attempt's log is first
written — `_resume_copy.copy_resume_payloads` replicates every sample
dir of the attempt being retried into the new attempt's eval
checkpoints dir, storage areas included, as opaque file trees. A
retry's log is its checkpoint commit point: a copy that fails or is
interrupted leaves no log, the next retry sources the newest log that
exists, and every sample dir reachable from a log is complete (nothing
reads a dir while it is being copied, so the copy itself needs no
internal ordering). Consequences for a strategy:

- It never copies prior-attempt state itself; by the time `setup`
  runs on resume, its storage area already holds what the prior
  attempt captured. Everything a restore needs must therefore live
  inside the storage area.
- For a remote destination the storage area was copied there verbatim
  before `discard_orphans` ran against the local staging copy; the core
  mirrors the removal at the destination by deleting whatever the pull
  brought in that the discard removed, so a stale orphan does not ride
  forward on every later retry.
- Retained snapshots are durable at this attempt's destination before
  any agent work runs, by construction: the startup copy put them
  there.

### 4.6 Security requirements (Protocol docstring, normative)

The sandbox controls the state it supplies, including repository files
and metadata. Host checks constrain transfer size and paths, prevent
replacement of existing restic repository files, and tie resume to a
recorded snapshot when one exists. They do not establish that a snapshot
faithfully captures the sandbox or that its contents are recent or truthful.

File-list agreement, newly received snapshot ids, and expected tags enforce
transfer protocol consistency. A compromised sandbox can satisfy these
checks with fabricated state. Content-addressed filenames bind names to
bytes, not to an authentic capture. Root-only paths and per-exec secrets
protect against an unprivileged agent, not one controlling sandbox root.

Implementation requirements:

- Tooling placed inside the sandbox lives under a root-only (0700)
  path whose *parent* is unlistable by an unprivileged agent (the
  `/root/.cache/inspect` pattern), streamed in via root `sh` stdin so
  bytes never touch an agent-readable temp path.
- Any in-sandbox staging must sit inside that area and be excluded
  from the strategy's own capture.
- Bytes read out of the sandbox are attacker-controlled: host-side
  handling must never extract them onto the host filesystem without
  path-safety (`tarfile filter="data"`; see `_extract_tar`), and never
  execute or parse them with anything less than full distrust.
- Restic egress limits header reads to 64 KiB per archive member before
  tarfile processes them, including chained extension headers and sparse
  maps. Ordinary file contents stream separately under the extraction
  byte cap. Archives with larger metadata fail the checkpoint attempt.
- Secrets reach the sandbox only via per-exec environment variables
  (`env=` on `exec`), never persisted to sandbox disk.
- All in-sandbox execution runs as `user="root"`; output must respect
  `MAX_EXEC_OUTPUT_SIZE` (suppress progress streams — see
  `run_sandbox_backup`'s `--quiet` note).
- A restore writes as root into a fresh sandbox from data the resume
  source supplied, so it is scoped to this attempt's resolved capture
  roots and structurally validated on the host before any byte enters
  the sandbox (implementation-status item 5; `_restore_scope`). The
  resume source is not authenticated; structural validation is the
  whole defense. The validation is lexical, and the restoring tool
  resolves paths through what the fresh image already has, so on
  resume the core deletes every symlink the image ships under a root
  before the strategy's `setup` places anything in the sandbox
  (`_restore_scope.remove_existing_symlinks`); the strategy's own
  tooling under `/root/.cache/inspect` is inside the root when the
  default user is root, so a later pass would sever it. The snapshot
  recreates the links it holds.

**Earlier checkpoints survive a later transfer.**

*Guarantee.* A later transfer cannot make an earlier committed snapshot
unrestorable and cannot alter its restored contents. It is not authenticity
of the sandbox's state: an agent that controls sandbox root holds the
repository key and can mint validly-encrypted indexes, trees and snapshots,
and its own current capture is already whatever it chooses. What it can no
longer do is reach back and break or corrupt a checkpoint an earlier fire
committed.

*Why the reach-back surface is only index files (and keys).* Content
addressing keeps a committed repository file's *bytes* immutable — the
egress verifies every file's name is the SHA-256 of its contents and never
overwrites an accepted file — but a later transfer can still *add* a new,
correctly-named file, since any bytes can be shipped under their matching
name. Every repository file except an index is content-addressed and
self-contained, and restic reads a pack only where an index sends it, so a
new file can change what an earlier snapshot restores to only by changing
where restic looks for one of its blobs — which only index files do (plus
key files, which decide whether the repository opens at all; those are
refused after the first cycle). Both demonstrated attacks are index attacks:
a *malformed* `index/<sha256>` makes restic abort while loading indexes
(`MasterIndex.Load` returns the first decode error) and so blocks restoring
*every* snapshot, including earlier committed ones; a *valid* index that
maps an accepted blob to an attacker-supplied `data` pack, or re-describes it
with an understated length, leaves an earlier snapshot's restore silently
wrong (verified against restic 0.18.1: plain `check`/`ls` report no error and
the restore succeeds with the wrong bytes).

*Containment rule.* Each new index file is loaded by restic's own index
decoder on the host — `restic list blobs` on a throwaway view of config,
keys and that one index file — and the `type:id` blobs restic prints for it
may not include any that an accepted index already locates. An honest
`restic backup` never violates this: it deduplicates against the existing
index, so it never re-stores an indexed blob (verified against restic 0.18.1
for a second backup after a first, and for a backup following an interrupted
one). The key is `type:id`, not the id alone, because restic looks blobs up
by `(type, id)`: an entry for `data:X` cannot redirect a lookup of `tree:X`,
and a file whose content is exactly a tree's JSON gives a data blob with a
tree blob's id. What each accepted index locates is kept in a host-side
memo, a SQLite file at `restic/index-memos/<sha256(sandbox)>.sqlite` (a
directory no sandbox name can claim, with a fixed-length basename), a cache
of `list blobs` output per index healed on every fire against the index
files actually present: entries whose file is gone are dropped, files it
does not know are listed by restic (one process per missing index, on a view
of config, keys and that file; normally none; every one of them on this
code's first fire over an existing repo, after a resume, or after a memo
schema bump, which discards the old file), anything unreadable is discarded
and rebuilt. A fire touches only the rows it names, so memo work is
O(increment); the file grows with the accepted blob count but is never read
or rewritten whole.

*No pack rule.* Earlier rounds also required a new index to reference only
this transfer's packs (or accepted packs no accepted index covered, the
residue a hard kill leaves). That half carried none of the guarantee, and
`list blobs` prints no pack ids, so it is gone. restic reads a pack only at
the offsets its own index entries give for a requested blob id; a
new-index entry that points a *new* blob id at an accepted pack, a new pack
or a pack that never arrived affects lookups of that new blob only, which is
the new snapshot's own business. Entries for *accepted* blob ids are what
reach back, and that is the blob half, which `list blobs` covers completely.
Honest backups never reference foreign packs anyway, so nothing honest is
newly permitted; the residue allowance and the memo's `packs` table went
with the rule (`test_egress_accepts_index_referencing_missing_pack`: the
earlier checkpoint restores, the new one fails at restore time).

*restic is the decoder.* `list blobs` (`cmd/restic/cmd_list.go`, v0.18.1)
calls `index.ForAllIndexes` (`internal/repository/index/index_parallel.go`),
which decrypts each index file and runs `DecodeIndex`
(`internal/repository/index/index.go`) on it, returning the first error,
and prints `<type> <id>` for every entry (`Index.Each`). That is the decode
every reader uses — `MasterIndex.Load` calls `ForAllIndexes` too — but
`list` does not go through `Repository.LoadIndex`
(`internal/repository/repository.go`), which adds exactly one check on top
of the load: a version-1 repository may hold no compressed blob entry
("index uses feature not supported by repository version 1"). Review round
10 showed the gap: in a version-1 repo an index with `uncompressed_length`
entries passes `list blobs` and blocks every restore. So the first cycle's
`config` must declare repository version 2 (`restic cat config` on the
view, one process, once per sandbox, `_check_repository_version`); both the
sandbox and the host `restic init` use restic's default, which is 2, so
this refuses nothing honest, and a version-1 repo could only be shipped by
the sandbox itself (`test_egress_refuses_a_version_1_repository`, which
also demonstrates the gap on a version-1 repo against 0.18.1). With that,
an index restic cannot decode fails the command before publish (an
undecryptable file; a malformed one, which would otherwise abort index
loading for the whole repository and block *every* restore), an index
whose offset or length exceeds `math.MaxUint32` panics *this* process
(`Index.store`) instead of a later restore's, and the blob ids come from
the authority itself. That panic, though, races restic's own exit: the
decode runs in an `errgroup` worker whose deferred bookkeeping lets
`ParallelList` return while the panic unwinds, so `list blobs` exits 2 with
the crash on stderr or, having printed nothing, exits 0 first — about a
third of runs on linux/amd64 (where the branch's CI caught it), never in
ten on darwin/arm64. Either way that index's entries are never printed,
because the callback runs only after `DecodeIndex` returns. So an index
file whose listing is empty is refused: an honest `restic backup` never
writes an index file with no entries (an unchanged re-backup writes no
index file at all; `Flush` skips empty ones), and an empty listing means
restic did not finish decoding the file. Verified against restic 0.18.1:
the output is one lowercase `<type> <id>` line per entry, a blob two index
files both map prints twice (the host dedupes), `list` accepts
`--no-lock`/`--no-cache`, an undecodable index exits 1, the oversize offset
exits 2 with a Go panic on stderr or 0 with nothing printed (both refused),
and a view holding no packs is fine because `list blobs` reads none. The host
normalises rather than validates (split lines, lowercase the hex, refuse a
line that is not `data|tree <64 hex>`, which restic never prints for a
loaded index): whatever restic accepts, egress accepts — unknown fields,
which Go's decoder ignores; an uppercase id, which restic prints back in
lowercase so containment compares canonical spellings
(`test_egress_follows_restic_on_hostile_index_shapes`). Earlier rounds
re-implemented restic's decoder as a strict host parser with an allowlist
and representation rules; that duplication, which review round 8 showed is
hard to keep faithful and every restic upgrade puts at risk, is gone, and
with it the "restic upgrade adding an index field fails honest transfers
closed" behaviour: a new field is loaded by the new restic and accepted.

*The two restic invocations per fire, and why each is there.* Both run on
throwaway views — config and keys plus, per view, one new index file, or
every accepted snapshot file and the new ones (hard links to the inodes the
accepted repo holds or will hold; copies where links are unsupported) — and
concurrently, since they are independent, so the wall-time floor is one key
derivation. One view per new index rather than one for all, because `list
blobs` prints the union and the memo records blobs per index so that a
dropped index file releases exactly its own; the index views are listed one
at a time in one worker beside the snapshot worker, so however many index
files a transfer carries, at most two restic processes run at once (a fire
normally writes one index; the first cycle adds one `cat config` in the
snapshot worker).

1. `restic list blobs --no-lock --no-cache`, one per new index file, before
   publish. Kept: restic's own index decoder is the authority on whether the
   index loads, and its output is the only source of the new index's blob
   ids, which the containment rule needs; containment is what carries the
   guarantee.
2. `restic snapshots --json --no-lock --no-cache`, before publish (moved
   from after publish on the accepted repository; decision: Ransom,
   2026-09-18, option A of review round 8's B2). The checks are the ones
   the after listing did: listed ids minus the ids of snapshot files
   present before the transfer must equal the shipped snapshot files, and
   the reported id must be among them with exactly the expected tag. A new
   snapshot restic cannot load is missing from the listing; one it loads
   but cannot encode makes restic print no JSON at all; either fails here
   and nothing is published. This is what closes B2: nothing unverified is
   ever placed under `snapshots/`, so the loadable-but-unlistable residual
   class no longer exists. What is given up: restic itself no longer reads
   the accepted repository after publish. The view is hard links to the
   same inodes the accepted repo will hold, so restic's reading of the view
   before publish is the same statement about those bytes; the remaining
   mistake class — files not landing where the view had them — is covered
   by a host-side stat after publish (`_verify_published`: every written
   file is a regular file of the staged size at its published path; a
   failure unwinds the fire's files). O(increment files), no restic.

*The three the whole-repository design ran, and why they are not needed.*

- *The before listing* (`restic snapshots --json` before the transfer)
  supplied replay detection and the baseline for the after-diff. Both are
  file-name questions: a snapshot id is the name of its file under
  `snapshots/`, and the egress already scans the accepted repository's
  files and has verified every accepted file's name is the hash of its
  bytes. Replay: the reported id (full or prefix) must match no snapshot
  file already present — stricter than the listing, which showed only
  loadable snapshots. The diff baseline is that same file set. The old
  "lost snapshot" check is gone: egress never modifies or removes an
  accepted snapshot file. A pre-existing unloadable snapshot file is in the
  before set and skipped by restic in the view listing, so it falls out of
  the arithmetic with no false positive. Residual: none.
- *`restic check --read-data` on the view* read every pack the new indexes
  reference and checked each blob's hash and length. With containment
  holding, every blob an earlier snapshot references is still located
  exactly where its own accepted index put it, in an accepted pack that is
  never overwritten, and restic reads a pack only where the index sends it,
  so a garbage new pack, an understated length or a missing pack can affect
  only blobs the new snapshot's trees reference — the sandbox's own capture,
  which this design does not authenticate. What `check` still provided was
  restic's own authority that the new index *loads*; `list blobs` now
  supplies exactly that. Residual: the new snapshot's own bytes are not
  verified at fire time (below).
- *`restic cat snapshot <id>` on the view* decoded each new snapshot file
  before publish. It stays removed because the pre-publish listing now
  covers it: a snapshot file restic cannot load is absent from the view's
  listing, and one it loads but cannot encode empties the listing, so both
  are refused before publish, with one process for all new snapshots
  instead of one per snapshot. One restic fact found while verifying, kept
  as an explicit guard: restic 0.18.1's `Repository.LoadUnpacked` slices the
  16-byte nonce off a snapshot file without a length check and *panics* on
  a file shorter than 16 bytes (exit 2). The view listing would refuse such
  a file too, but the egress refuses at extraction any `snapshots/` member
  shorter than 32 bytes — restic's nonce-plus-MAC overhead, the least any
  encrypted restic file can be (`_MIN_SNAPSHOT_FILE_BYTES`) — so the panic
  never enters the validation path.

*B2, the loadable-but-unlistable snapshot (review round 8), and why it is
closed.* Not every loadable snapshot file is listable: Go's RFC 3339 parser
accepts a zone offset hour of exactly 24 (`hr > 24` is its range test) that
`Time.MarshalJSON` then refuses, and restic 0.18.1 encodes `snapshots
--json` as one array, so with such a file present the listing prints
nothing and exits 0 (`error printing snapshots` on stderr), while
`snapshots --json <id>`, a `--tag`-filtered listing, the table listing and
`ls`/`restore` by id all still work (verified). Under the after-publish
listing, this fire's own check caught it, but a hard kill between publish
and the unwind left the file under `snapshots/`, after which every later
fire's listing and resume's `forget_unrecorded_snapshots` (a full
`snapshots --json`) failed while it existed — not inert. With the listing
before publish the file is refused on the view and is never published, so
the class is gone (`test_egress_rejects_snapshot_restic_loads_but_cannot_encode`:
refused with the accepted repo unchanged, a following honest fire commits,
`forget_unrecorded_snapshots` works throughout).

*Hard-kill residual.* A hard kill during publish leaves a prefix of this
fire's validated files — packs before indexes before snapshots — so every
earlier snapshot stays restorable, and the next fire re-ships the rest
idempotently or resume drops the unrecorded snapshot. Every snapshot file
that reaches `snapshots/` was listed on the view first, so the only
snapshot residue a kill can leave is a file that listed. An unloadable
`snapshots/` file can arise only outside the egress (planted on the host);
restic skips one with a warning, the view listing's arithmetic ignores it,
and it is left in place (`test_unloadable_snapshot_file_in_accepted_repo_is_inert`).

*View.* One throwaway view holds config, keys, the new index files, the
accepted snapshot files and the new snapshot files — a handful of small
files plus O(fires) snapshot files of about 1 KiB. The lazy builder
(256-file slices) and the copy fallback for filesystems without hard links
(exFAT/FAT, some CIFS/NFS mounts; plain copies for the view,
copy-to-`.partial`-then-rename for the accepted repo) are kept as tested.

*Cost.* Per fire: two restic processes run concurrently (each paying
restic's ~0.45 s scrypt key derivation, which restic calibrates at key
creation and does not let a caller lower — the same process count as before
this PR, now with a one-derivation wall-time floor), plus SQLite memo work
proportional to the increment, plus hard-linking a handful of files and
O(fires) snapshot files, plus a stat of each written file after publish
(O(increment files), no restic). Nothing proportional to repository bytes
or increment bytes beyond the tar copy-out and extraction that predate this
PR; the one O(repository files) step, the accepted repo's file listing used
for the re-ship and replay checks, also predates it.
Measured with the real `egress_sandbox` (restic 0.18.1, Apple M4 Max, local
SSD, 50 MB increments of 70% incompressible / 30% text, 40 fires):

| fire | accepted repo | egress wall |
|---|---|---|
| 1 | 0.03 GB | 0.69 s |
| 20 | 0.70 GB | 0.70 s |
| 40 | 1.40 GB | 0.71 s |

All 40 fires fell in 0.68–0.76 s; least-squares slope 0.02 s/GB, noise (the
two processes in sequence measured 1.21–1.26 s on the same host; `list
blobs` costs the same as the `cat index` it replaced).

*Guarantee, restated.* A later transfer cannot make an earlier committed
snapshot unrestorable or alter its restored contents because: earlier files
are never overwritten; the repository is version 2, so restic's index
decoder is its whole index-loading check; every new index file is one that
decoder loads; no blob an accepted index locates is located by a new index;
every new snapshot file was listed by restic before it was published; and
no new key file is accepted after the first cycle.

*What is given up relative to the earlier designs — decisions (Ransom,
2026-09-18), not open questions.*

- Accepted packs are not re-read on each fire, so host-side bit rot or
  tampering with accepted files surfaces at restore, not at fire time.
- Containment permits garbage new pack contents and wrong lengths for new
  blobs: a sandbox that ships garbage for its own blobs, or understates
  their lengths, gets a committed checkpoint that fails or restores wrong
  bytes at restore time, indistinguishable from an honest sandbox with a
  wrecked filesystem, while earlier history stays intact
  (`test_egress_accepts_garbage_pack_under_a_new_blob_id`,
  `test_egress_accepts_understated_length_on_new_blobs`; aimed at an
  accepted blob the same shapes are rejected by containment).
- Repository version 1 is refused at the first cycle (implementer, review
  round 10): nothing honest creates it, and accepting it would need a
  per-fire process that goes through `Repository.LoadIndex`.
- Unloadable snapshot residue (a file restic skips) is retained as
  harmless. (The earlier "a restic upgrade that adds an index field fails
  honest transfers closed until the strict parser is updated" went with the
  parser: restic is the decoder, so a new restic's new field is accepted.)
- restic itself no longer reads the accepted repository after publish; the
  view listing before publish plus the stat check after stand in for it,
  as above.

### 4.7 Strategy identity is recorded and pinned

Resume must never run one strategy over another strategy's data, and a
strategy change between attempts must surface as an error, never be
applied silently (allowing new snapshots to switch strategies
mid-lineage would leave a sample's checkpoint history half-and-half,
with retention and restore semantics straddling two implementations). Two
persisted records enforce this:

- **Per snapshot:** each `SnapshotDetails` written into a checkpoint
  file records its `strategy` name, so every checkpoint file is
  self-describing. Absent field ⇒ `"restic-incremental"` (pre-change
  checkpoint dirs).
- **Per sample — the pin:** at fresh-sample hydration the core writes
  the pin file (sandbox name → strategy name) at
  `restic/snapshot-strategies.json` in the sample checkpoints dir
  (placement rationale in §5), shipped with the other core-owned
  files. On resume the pin rides across attempts with the retry
  startup copy (alongside `restic-config.json` and the `ckpt-*.json`
  files — see `_resume_copy`), so every attempt's dir carries it no
  matter how many retries preceded — without that carry-over, the
  second retry of a non-default-strategy sample would find no pin and
  the absent-file default would turn into a spurious mismatch error.
  Writing at fresh hydration means the pin is present in every dir a
  retry can actually resume from: resume only happens when a committed
  `ckpt-*.json` parses (`scan_latest_committed_checkpoint` gates it), so a
  zero-commit attempt's dir is never read — its retry re-runs fresh
  and writes its own pin. For remote destinations this claim needs one
  stated ordering requirement: **the pin ships no later than the first
  `ckpt-*.json`** — i.e. before the checkpoint-file tier in the safe
  order. A fresh sample with a remote destination ships nothing at
  hydration end (the retry startup copy, not hydrate, populates a
  resumed sample's destination), so the
  pin first travels with fire 1's egress; if it shipped after the
  checkpoint file, a crash in that window would leave a resumable dir
  (has `ckpt-00001.json`) with no pin, and the absent-file default
  would produce exactly the spurious mismatch error the pin exists to
  rule out. Today's `_safe_order` happens to give the right order (the
  pin matches no named tier and the catch-all bucket ships before the
  `ckpt-*.json` tier), but since §4.7's guarantees rest on this
  crash-window ordering, it is a requirement here — not something
  inherited by accident. Absent file ⇒ `"restic-incremental"` for
  every sandbox (pre-pin dirs).

On resume/retry the core compares the pin against the currently
configured strategies *before* instantiating anything. Any mismatch is
a **hard error** naming the sandbox, the pinned strategy, and the
configured one, with the remedy stated (restore the original
configuration and resume, or start a fresh eval). A pinned strategy
name unknown to the current build errors the same way, as does a
configured sandbox with no pin entry — the sandbox set changed between
attempts, which would otherwise surface only as a downstream restore
failure (no storage area to restore from); the pin check turns it
into the same clear, named error. The mirror case — a pin entry whose
sandbox is absent from this attempt's configuration (removed, or
opted out via an empty `sandbox_paths` entry) — hard-errors too:
today that state is silently lossy (the sandbox is simply not
hydrated and its captured state dropped), and §4.7's goal is that a
changed sandbox set surfaces as a clear error in either direction,
with the same remedy stated. One path into the mirror case involves
no config change at all: `resolve_sandbox_backup_paths` skips an
auto-home sandbox with a warning when its home dir cannot be
resolved, so a sandbox pinned by attempt 1 can drop out of the
effective backup map on retry simply because resolution flaked. That
skip-with-warning is fine for a sandbox that was never captured, but
for a *pinned* sandbox it hard-errors like the other mirror cases —
the alternative is exactly the silent data loss this section exists
to prevent — with its own message naming home-dir resolution as the
cause (the config-change remedy would misdiagnose it) and its own
remedy: resume again (resolution failures are typically transient),
or configure the sandbox's paths explicitly in `sandbox_paths` so
resolution is no longer in the loop. Strategy
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
  `sandboxes/default/archive/ckpt-00007.tar.zst`; `.tar.gz` under the
  gzip fallback). The core maps
  strategy → storage area in one place (`_layout`); strategies never
  compute sample-dir paths themselves.
- `restic/host/` and `restic-config.json` remain core-owned (host
  context capture); the per-sample secret in `restic-config.json`
  doubles as the generic capture secret handed to strategies via
  `SnapshotContext`.
- The §4.7 pin (from Phase 2) is core-owned and lives at
  `restic/snapshot-strategies.json`, beside `restic-config.json`. A
  strategy-agnostic file under `restic/` is deliberate: `restic/` is
  already the home of core-owned per-sample files (the host repo, the
  config) rather than restic-strategy state. The retry startup copy
  (`_resume_copy`) replicates the whole sample dir, so the pin needs no
  carry-over of its own.

## 6. Configuration

Phase 1 changes nothing: `sandbox_paths: dict[str, list[str]]` keeps
its exact semantics (auto-home default, empty list opts out) and maps
to a single path group under the default strategy.

Phase 2 extends the *values* of `sandbox_paths`: each entry is either
a bare path list (no strategy opinion — the default applies unless
another layer selects one) or a `SandboxSnapshotConfig` selecting
the strategy for that sandbox.
Phase 3 adds per-path-group routing by admitting a list of groups as
the value:

```python
CheckpointConfig(
    sandbox_paths={
        "default": [
            PathGroup(paths=["/home/user"]),                 # default strategy (restic)
            PathGroup(paths=["/data"],
                      strategy=ArchiveSnapshots(retention=SnapshotRetention(keep_last=2))),
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
- **One option, richer values.** There is a single `sandbox_paths`
  option; a bare path list is shorthand for
  `SandboxSnapshotConfig(paths=...)` with no strategy opinion. (An
  earlier draft had a separate, mutually-exclusive `sandbox_snapshots`
  option; maintainer review folded it into `sandbox_paths`.)
- **Strategy selection merges independently of the paths dict.**
  `sandbox_paths` itself merges as a whole-dict value across layers
  (eval > sample > task), but the `strategy` values resolve
  per-sandbox across the same layers, regardless of which layer won
  the paths dict. Otherwise a higher layer's paths-only override
  would silently reset a lower-selected strategy to the default —
  precisely the storage blowup the archive strategy exists to
  prevent. Resetting a strategy therefore requires a higher layer to
  select one explicitly.
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

## 7. Concrete strategies

### 7.1 `restic-incremental` (Phase 1)

Today's code nearly verbatim, plus absorbing the destination shipping
of `restic/sandboxes/<name>/**` (safe order preserved: `config`/`keys`
→ `data` → `index` → `snapshots`) and the `list_changed_files` step.
`apply_retention` is a documented no-op until generation rotation
(Phase 4). Best choice when most files are stable across checkpoints.

### 7.2 `archive` (Phase 2)

One complete tar per checkpoint — compressed with zstd when available
in the sandbox, falling back to gzip (present in effectively every
image, busybox included), so the archive is always compressed —
streamed from the sandbox to
`sandboxes/<name>/archive/ckpt-NNNNN.tar.{zst,gz}` at the destination —
never fully buffered on the host, with only transient staging inside
the sandbox (chunks during capture, §8; the staged archive during
restore).

- `setup`: verify `tar` and the hash tool `restore`'s verify step
  needs (`sha256sum`) exist — both are in effectively every image, and
  probing both here means a missing tool fails at provisioning rather
  than at first restore; probe for zstd and record which compressor
  (zstd or the gzip fallback) this sandbox will use. Nothing injected.
- `snapshot`: in-sandbox root `tar -c` of the include paths (with
  excludes), streamed out (§8), hashed in flight (`content_sha256`
  recorded in details), shipped via the §8 sink-style streaming write
  (the existing `AsyncFilesystem.write_file_streaming` takes a
  complete source, which a chunk-at-a-time producer cannot supply).
  `size_bytes` = archive size.
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
  archive size. When the sandbox follows the protocol, a digest mismatch
  stops extraction. A compromised sandbox can bypass that check. The
  archive remains opaque on the host: copy-out caps accepted bytes and checks
  agreement with the sandbox-reported digest, without authenticating
  the archive contents. Extraction happens *inside* the sandbox.
- `discard_orphans` / `apply_retention`: delete one file per
  checkpoint. This is the strategy where mid-run reclamation is
  trivial, which is the point.

### 7.3 Deferred: `reference` (sketch only, not scheduled)

For large files that are re-downloadable or reproducible (model
weights, datasets): store only a manifest. **Deferred until someone
asks for it** — it earns nothing until a real user has re-fetchable
data, and the interface work it would validate (near-zero-cost
snapshots, restore that does network work inside the sandbox) can be
paper-checked against the Protocol without building it. The sketch is
kept here as a future strategy so the config surface (§6) and the
"storage cost near zero" corner stay in view:

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

`egress_sandbox` carried a TODO (since retired by the shared
`_checkpoint/_copy.py` primitive): `read_file` on a single big
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
  write, and deletes it. The handoff protocol must be explicit on
  four points, because `content_sha256` is minted host-side over the
  bytes actually read — a torn read of a partially written chunk would
  produce a corrupt archive whose recorded hash *matches*, passing
  restore's verification and failing only at `tar -x` (or not at all):
  **(a) chunk completeness** — the producer writes each chunk to a
  temp name and `mv`s it to its final name (rename is atomic within
  the staging dir), and the host keys only off final names, so a chunk
  that exists is complete; **(b) end of stream** — after the pipe
  drains the producer writes a done-marker file carrying the total
  chunk count, so the host can distinguish "finished" from "slow";
  **(c) producer failure** — the done-marker also carries the `tar`
  pipeline's exit status, and the host treats a nonzero status — or a
  producer that stops making progress without ever writing the marker
  (a liveness timeout) — as a failed `snapshot()`, raising rather than
  waiting forever on a detached producer that died mid-stream;
  **(d) cross-fire isolation** — an *interrupted* `snapshot()` leaves
  residue that a shared staging area would let corrupt the next fire's
  stream: unshipped final-named chunks, possibly a stale done-marker,
  and a detached producer still alive, blocked on the backpressure
  gate — the moment the next fire's host loop deletes the chunk name
  the old producer was gated on, it unblocks and emits stale chunks
  under final names the new stream hasn't reached yet, and since the
  hash is minted host-side over whatever bytes get read, the
  interleaved archive *passes* restore verification. So each snapshot
  stages in its own subdirectory (keyed by `checkpoint_id`, which also
  namespaces the done-marker), and `snapshot()` begins by killing any
  prior producer still running and deleting stale staging subdirs —
  this is how the archive strategy meets §4.2's requirement that an
  interrupted fire not break the next one on the same live sample.
  Note the subdir keying alone does not isolate exactly this case: an
  interrupted fire never commits its checkpoint file, and the core
  *reuses* the id (`_scan_next_checkpoint_id`), so the retried fire
  stages in the *same* subdirectory that holds the residue — the
  kill-then-delete preamble is the load-bearing mechanism there, not
  belt-and-braces. Its order matters too: kill the producer *before*
  deleting its subdir, since deleting first releases the backpressure
  gate and lets the still-live producer write into the recreated
  directory.
  The backpressure gating bounds sandbox disk to about two chunks
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
  kill mid-`snapshot()` then fire again on the same live sample — the
  second fire succeeds and both checkpoints restore byte-identical
  (§4.2 residue isolation, §8 point d);
  `discard_orphans` removes exactly the uncommitted tail;
  retention under `keep_last=1` honors the floor (latest committed
  always restorable) and removes thinned checkpoints' files from the
  destination before their data (§4.4); retry under a different
  configured strategy fails with the §4.7 pin error; pin carry-over —
  fresh sample under a non-default strategy, retry 1, then retry 2
  under the same config resumes cleanly with no spurious mismatch
  (this is the only scenario that catches a pin the startup copy
  failed to carry: every single-resume scenario resumes from the
  fresh attempt's dir, which has the pin from fresh hydration);
  agent-invisibility
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

**Phase 3 — Per-path-group routing.** List-of-group `sandbox_paths`
values with
disjointness validation, core-owned fan-out of one strategy instance
per (sandbox, group), multi-group checkpoint schema and the per-group
pin form (§6). Gate on a
concrete user; the seam is designed now so nothing in Phases 1–2
blocks it.

**Phase 4 — Restic generation rotation.** The restic strategy's answer
to `apply_retention`: periodically start a fresh repo generation
(`.../gen-K/`), take one full backup into it, and delete the previous
generation wholesale once a checkpoint committed against the new one —
reclaiming space without ever running `restic prune` (whose pack-file
rewrites the ship-once egress protocol cannot tolerate). Pure
implementation work inside one strategy; no interface change, which is
itself a test that the Phase 1 boundary was drawn correctly.

Deliberately unscheduled: the `reference` strategy (sketched in §7.3,
deferred until someone asks for it) and provider-native snapshots
(ZFS, `docker commit`, volume snapshots). The Protocol leaves room —
it receives the `SandboxEnvironment`, assumes nothing about file-level
capture, and uses opaque snapshot ids — but is not designed around
them.

## 11. Risks

- **Designing around restic's shape.** The discipline is §4: the
  contract speaks only in observable guarantees (durable on return,
  restore into a fresh sandbox, retention floor, agent invisibility)
  and no restic vocabulary. The concrete check: if `archive` (Phase 2)
  implements without contortions and generation rotation (Phase 4)
  needs no interface change, the boundary is right. Phase 2 is
  deliberately scheduled early as the falsifier; the deferred
  `reference` sketch (§7.3) serves as a paper check for the
  near-zero-storage corner.
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
