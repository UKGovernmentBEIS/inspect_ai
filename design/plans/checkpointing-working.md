# Inspect Checkpointing — Plan Outline (WIP)

> Status: outline in progress. Not ready for implementation. Details captured from ongoing design conversation.

## Context

Long-horizon evals can run for days or weeks. Today, if an eval fails before
completing, all in-progress work is lost. Checkpointing persists the in-flight
state of each sample periodically so that on failure the eval can be resumed
from the most recent checkpoint — per individual sample — rather than
restarted. Individual samples themselves may take days-to-weeks, so resumption
must be **mid-sample**, not merely sample-level.

Checkpoint + resume is **phase 1 of a broader long-horizon eval feature
stream**. Later phases (TBD, out of scope here) will build on top of this
foundation — e.g., **human intervention** mid-eval (pause, inspect, edit
state, resume), and likely other long-horizon-oriented capabilities.
We're starting with checkpointing because it is an obvious, self-contained,
and independently valuable first step.

## Artifacts to produce

Three distinct artifacts, three audiences, three lifespans:

1. **Customer-facing design doc.** Fresh narrative pass (not a cleanup
   of this working doc — cleanup leaks internal framing). Audience:
   potential customers and broader team, for validation that the plan
   addresses real needs and is practical. Shape:
   - Problem & motivation
   - UX walkthrough (enable → run → crash → resume)
   - Scope + explicit non-goals (consolidated, not scattered)
   - Operational model (where data lives, retention defaults,
     destination options)
   - Customer-visible constraints / requirements imposed on them
     (tool idempotency expectation, restic injected into sandbox
     image, home-dir scope, inspect-version pinning implications for
     resume)
   - Known limitations / gotchas (cold-start window, external
     side-effect replay, etc.)
   - Explicit validation asks — the questions we most want customer
     input on
   - Heavily summarize the engine discussion (customers care it works
     on their sandbox + storage, not which backup tool we picked).
   - Be honest about decided vs. being-validated.
   - Likely lives at `design/checkpointing.md`.
2. **Internal working/design doc.** *This document.* Decision history,
   unresolved questions, parked notes, appendices, contradictions.
   Audience: us + implementers. Preserves the trail. Stays at
   `design/plans/checkpointing-working.md`.
3. **Implementation plan.** *Deferred until after customer validation*,
   because validation outcomes will move the ground. Writing an impl
   plan now encodes decisions that may change.

Suggested sequencing:

1. Finish a couple more interview rounds to firm up items that would
   otherwise be noisy TBDs in the customer doc (or accept them as
   validation asks).
2. Draft the customer doc as a new file, iterate on shape.
3. After customer feedback, write the implementation plan.

## 0. Principal requirements / invariants

- **Resume is `inspect eval retry`.** *(Reversed.)* Following JJ's
  design conversation, checkpoint resume builds on Inspect's existing
  retry infrastructure rather than a new `--resume` flag. The command
  is `inspect eval retry <log-file>`; the `.eval` log is the
  authoritative entry point, and the log records where the sibling
  checkpoints directory lives. **Both the log and the checkpoints
  directory are required** to resume. This is the inverse of the
  previous (now-abandoned) "checkpoint folder alone is sufficient"
  invariant — a log file already carries completed-sample records
  natively, so trying to make the checkpoints dir stand alone was
  solving a problem we don't have.
  Consequences:
  - `manifest.json` records identity and the canonical checkpoints
    directory location (path or URL); it no longer needs to fully
    reconstruct the eval in isolation, because the `.eval` log holds
    the authoritative eval spec.
  - The context-window portion of each checkpoint stores messages and
    events in full (not as offsets into the `.eval` log) so that a
    partially-completed sample can be fully rehydrated. Completed
    samples live in the `.eval` log and do *not* require checkpoint
    entries.
  - Each sample's checkpoint subtree carries its sample input so a
    resume's sample-source extension can deliver the partial sample
    without re-reading the dataset.
  - "Reuse `.eval` log serialization" means: **same on-disk schemas
    (Pydantic/JSON), different container** — messages and events are
    written as separate files inside the checkpoint dir (likely
    `messages.jsonl` and `events.jsonl`) using the same schemas used
    inside a `.eval` log. No zip coupling.
  - Task/agent/tool code bundling is **not required**. The customer's
    invocation environment (cwd + Python env + inspect install)
    provides it, as with any retry. The log records inspect version
    and task identity; existing retry code handles mismatch detection.
  - Inspect runtime itself is *not* bundled.

- **Checkpoint-attempt failures are non-fatal.** If a checkpoint attempt
  fails (egress error, disk full, sandbox exec error, restic error, …),
  inspect **logs a warning and continues the eval**. Retry on the next
  policy fire. Rationale: checkpoint durability is a nicety, not a
  correctness requirement; failing a multi-day eval because one
  checkpoint couldn't be written would be worse than the loss it's
  meant to prevent. Implications: users monitoring long-horizon evals
  should surface checkpoint-failure warnings prominently; silent
  checkpoint failure leading to a false sense of durability is a known
  risk being accepted by this policy.

## 1. Checkpoint data layout

- For an eval log `foo.eval`, checkpoints default to a sibling directory
  `foo.eval.checkpoints/` co-located with the log.
- Location is **overridable**, including to `s3://` (and any `filesystem()`-
  backed URL).
- Contents are organized per-sample, with non-sandbox checkpoint data in a
  per-checkpoint subdir, and sandbox-state data stored out-of-band as one
  restic repository per named sandbox (see §1b below for the sketch).
- **Per-sample containment is a first-class principle.** Every sample (×
  epoch) gets its own isolated subtree under `samples/<sample-id>__<epoch>/`,
  containing that sample's `sample.json`, its sandbox repo(s), and its
  checkpoint subdirs. No sample's data is commingled with another's.
  Consequences:
  - Concurrent samples write to disjoint paths — no coordination required.
  - A sample that completes successfully before others can have its
    subtree cleaned up (or retained) independently.
  - Resume/discovery walks `samples/*/sample.json` and treats each as
    independent; per-sample failures don't block other samples from
    resuming.

### Per-checkpoint contents

1. **Eval/sample summary metadata** — identifying info for the sample/epoch,
   checkpoint sequence, trigger reason, timestamps, etc.
2. **Context window** — messages + events from the trajectory executed so far.
3. **Sandbox state** — see §1a.
4. **Store** — the sample's `Store` key/value state (agent-accessible state
   beyond messages).

Explicit non-goals:

- **In-memory** sandbox/process state. Checkpoints do not capture running
  processes, open sockets, or in-RAM data inside the sandbox.
- **Sandbox-provider-specific checkpointing.** We will not use provider-native
  snapshot mechanisms (e.g., Modal's memory/VM snapshots, Docker commit,
  etc.) — at least not initially. The goal is a single provider-agnostic
  mechanism that works across all sandbox providers via the injected backup
  tool operating on the home-dir filesystem.
- **Tracking / replaying external side-effects across resume.** If a sample
  called an external API, sent an email, charged a card, etc., between the
  last checkpoint and the crash, resuming will **re-execute** (or skip, or
  confuse) that side-effect. We make no attempt to track, replay, or
  compensate. *Reality doesn't have a fork command.* Sample authors are
  responsible for tolerating this (e.g., via idempotent tools).

### 1a. Sandbox state — scope & approach

- Scope: the **agent's home directory** inside the sandbox (filesystem
  contents), not in-memory state.
  - Path is a **fixed path per container convention** (e.g. `$HOME`,
    typically `/root` for inspect's default sandbox user). Not
    configurable in v1. Anything the agent writes outside that path
    (e.g. `/tmp`, `/workspace`, `/opt/...`) is **not captured** by
    checkpointing. Document this clearly to customers — it's a
    significant contract.
- Expected approach: **incremental / diff-based** snapshots. Each checkpoint
  stores a diff against the previous checkpoint rather than a full copy.
- Design reference: standard backup-system architecture (changed-file detection
  + efficient diff storage) is already good at this; we should mirror that
  design rather than invent one.
- **Candidate technology:** [restic](https://restic.net) — content-addressed,
  deduplicating, supports multiple backends including S3. Leading candidate
  but not yet committed; alternatives remain open.
- **Sandbox injection requirement:** whichever tool is chosen (restic or
  alternative) must be **injected into the sandbox** — it needs to run inside
  the sandbox to enumerate/snapshot the home dir. Implies adding it to the
  existing sandbox-tools injection pipeline
  (`src/inspect_sandbox_tools/`).
- **Egress of checkpoint data.** The backup tool runs *inside* the sandbox,
  but checkpoint data must land in the configured checkpoint location on the
  **host-visible** filesystem (local sibling dir, or `s3://`, etc.). Two
  shapes to consider:
  - *Direct backend write* — the tool writes straight to the checkpoint
    destination (e.g., restic's S3 backend) from inside the sandbox. Fast
    path when destination is remote; requires credential plumbing into the
    sandbox.
  - *Host-mediated egress* — the tool writes to a sandbox-local staging
    path, then inspect copies the data out via the sandbox exec/copy API to
    the checkpoint destination. Works uniformly for local and remote
    destinations; adds a copy step.
  - Decision (direct vs. mediated, or both) is open — see Unresolved
    Questions.

### 1b. Proposed folder layout sketch

Assumes restic as backup engine; adjust if engine changes.

```
logs/
  foo.eval                                   # existing eval log (unchanged)
  foo.eval.checkpoints/                      # sibling dir (default location)
    manifest.json                            # eval-level header:
                                             #   eval id, task id, config hash,
                                             #   inspect version, engine = "restic",
                                             #   layout version, created-at
    samples/
      <sample-id>__<epoch>/                  # one dir per (sample, epoch)
        sample.json                          # sample-level metadata +
                                             #   checkpoint index: ordered list
                                             #   of checkpoint ids w/ triggers,
                                             #   timestamps, statuses
        sandboxes/                           # out-of-band sandbox state
          <sandbox-name-1>/                  # restic repo for sandbox 1
            config data/ index/ snapshots/ keys/ locks/
          <sandbox-name-2>/                  # restic repo for sandbox 2
            ...
        checkpoints/
          <checkpoint-id>/                   # one subdir per checkpoint
            metadata.json                    # seq, trigger (time/turn/manual),
                                             #   turn #, created-at, status
            messages.jsonl                   # context window / events
            store.json                       # Store key/values
            sandbox-refs.json                # { <sandbox-name>: <restic-snap-id> }
          <checkpoint-id>/
            ...
```

Shape notes:

- `manifest.json` is the canonical discovery/resumption entrypoint: a
  resume operation loads it first, verifies compatibility with the eval
  being rerun, then walks `samples/<id>__<epoch>/sample.json` to find
  the latest completed checkpoint per sample.
- **Sandbox state is out-of-band.** `sandboxes/<name>/` is a restic repo;
  `checkpoints/<id>/sandbox-refs.json` carries the snapshot id(s) that
  are "the sandbox state for *this* checkpoint." This decouples restic's
  repo-scoped snapshot model from our per-checkpoint folder model.
- **Snapshots correlate 1:1 with checkpoint ids.** Although sandbox repos
  live at peer level to `checkpoints/` (structural out-of-band), *every*
  checkpoint id has a corresponding snapshot in *every* sandbox repo that
  was active at that checkpoint. The per-checkpoint `sandbox-refs.json`
  maps `<sandbox-name>` → snapshot id, and the snapshot is **tagged**
  with the checkpoint id (via restic's `--tag` on `backup`) so the
  correlation is recoverable even if the sidecar is lost/corrupted.
  Consequences:
  - Retention of a checkpoint id implies retention of its snapshot in
    each sandbox repo; discarding a checkpoint id implies pruning the
    matching tagged snapshot(s).
  - Discovery/repair: walking `restic snapshots --tag <checkpoint-id>`
    recovers the checkpoint↔snapshot mapping without relying on the
    sidecar.
- **Per-sandbox repos** (not one shared repo) to sidestep restic's
  single-exclusive-lock constraint and to keep snapshot sets scoped.
  Cross-sandbox dedup is lost; cross-checkpoint dedup within a single
  sandbox is preserved (which is the common-case win).
- `<sample-id>__<epoch>` chosen so epoch retries are separate trees and
  don't clobber each other.
- `<checkpoint-id>` naming: open — monotonic seq (`0001`, `0002`), UUID,
  or timestamp-based. Monotonic seq reads most naturally for humans.
- `messages.jsonl` vs. reusing the existing `.eval` event serialization
  is still unresolved (see Unresolved Questions).

### 1c. Retention

- **On successful eval completion (default):** delete the
  `foo.eval.checkpoints/` tree.
- **Caller opt-in:** a configuration option to **retain forever**
  (checkpoints survive successful completion and are not garbage
  collected by inspect). CLI/config surface TBD.
- **During the eval:** all checkpoints must be **retained** — do *not*
  collapse, merge, or prune older checkpoints into the head. Rationale:
  although the immediate use case is "resume from head after crash," a
  future capability will allow resuming from an **arbitrary non-head
  checkpoint** (e.g., "rewind and branch" workflows). Collapsing is
  incompatible with that. Practically: do not run `restic forget` /
  `restic prune` on active checkpoint repos.
- Retention policy between "delete on success" and "retain forever"
  (e.g., keep last N, keep on failure only, time-based expiry) —
  remains open. See Unresolved Questions.

## 2. Configuration — checkpoint granularity

Inspect will offer multiple affordances, selectable per eval.
**All policies fire at turn boundaries only** (see §2c); an agent is
never interrupted mid-turn, and in-flight tool calls are never
paused to checkpoint:

- **None** — checkpointing disabled.
- **Time-based** — approximately every N seconds/minutes; fires at
  the next turn boundary after the interval elapses (so the effective
  interval is ≥ N, not exactly N).
- **Turn-based** — every N agent turns.
- **Manual** — agent-triggered explicitly from within its own logic, via
  an **inspect-provided Python function** (e.g.
  `from inspect_ai import checkpoint; await checkpoint(...)`). Agent
  code calls it directly; we do *not* expose a model-callable tool for
  checkpointing (no prompt-engineering surface for the model to decide
  on its own when to checkpoint).

### 2b. Where checkpoint config is declared

- **Primary surface: a parameter on the built-in agent's constructor**
  (e.g. `react(checkpoint=TimeCheckpoint(minutes=30))`).
- Rationale for *not* putting it on `Task(...)`: a `Task`-level field
  would imply every solver supports checkpointing, which is not true.
  Attaching it to the agent keeps the contract honest — only agents
  that actually implement the resume protocol advertise the option.
- CLI / global-config overrides: deferred. Not required for v1.

### 2a. Built-in React agent integration

- Inspect's built-in **React agent** will support checkpointing out of the
  box — at minimum **time-based** and **turn-based** modes.
- Implementation must be **layered**: the underlying checkpointing primitives
  (capture state, write checkpoint, restore from checkpoint, trigger hooks
  for time/turn/manual) are exposed as reusable building blocks so authors
  of **custom agent loops** can wire checkpointing into their own agents
  without reimplementing the machinery.
- React agent becomes the reference consumer of these primitives.

### 2c. When a checkpoint fires relative to the agent loop

- **Baseline (v1): between turns only.** Policy checks happen at turn
  boundaries; the snapshot runs while the agent is not executing.
  Gives simple atomicity, no in-flight tool calls to reason about.
  A "every N minutes" time policy effectively means "at the next turn
  boundary after N minutes have elapsed since the last checkpoint."
- No forced snapshot at sample start. The first policy-driven
  checkpoint *is* the first snapshot; it will be a fuller backup than
  subsequent deltas, which is expected. (Rationale: the customer's
  policy interval already expresses the acceptable loss window; a
  zero-point snapshot doesn't narrow that window — it just adds cost.)
- Open question (deferred, tracked in Unresolved Questions): should
  we *also* support firing mid-tool-call for agents running very long
  tool executions? Current instinct: no.

### 2d. Observability

- Emit a structured **`CheckpointEvent`** into the normal event stream
  on each attempt, carrying at minimum: `seq`, `trigger`
  (time/turn/manual/initial), outcome (success/failure), duration,
  on-disk size, and — on failure — the error.
- Surface checkpoint activity in the **inspect TUI** (small indicator
  while a checkpoint is running; last-checkpoint timestamp visible).
- Because events are part of the `.eval` log, checkpoint history is
  preserved in the normal log. No dedicated checkpoint journal file
  in v1.

## 3. Resumption

### 3a. Implementation-facing

**Division of labor.** The **harness** (inspect) is responsible for
performing the full restoration before the agent is called:

1. Restore the sandbox(es) from the corresponding restic snapshot(s).
2. Rehydrate the context window (messages + events) from the checkpoint.
3. Rehydrate the `Store`.
4. Invoke the agent with an input object that already contains the
   restored messages/events/store, **plus a new `is_resuming=True`
   signal**.

The **agent** does not re-open the checkpoint, does not re-materialize
the sandbox, and does not re-parse stored state. It simply runs — but
with enough information to know it was restored rather than started
fresh. Agents that don't care can ignore `is_resuming`; agents (like
the built-in React agent) that *do* care use it to skip one-shot setup
that has already happened (e.g., system-prompt assembly, initial tool
probing), avoid double-recording state, choose different resume-aware
branches, etc.

**Protocol implication (narrowed).** On reflection, we likely do **not**
need to broaden the agent input with new data-carrying fields:

- **Messages** are already passed to the agent today.
- **Events** are inspect-internal bookkeeping (they roll up into the
  final `.eval` log). The harness restores them into ambient inspect
  state on resume; they don't need to flow through the agent input.
- **Store** is accessed via ambient/global context (`store_as`, etc.),
  not via the agent input parameter. The harness restores the store
  into that ambient context; agents read from it normally.
- **Sandbox** is restored in-place by the harness before the agent
  runs; agents use it via the normal sandbox API.

**Therefore:** the only *new* addition to the agent protocol strictly
required for resume is a **single `is_resuming` boolean**. Any broader
"agent protocol broadening" conversation is orthogonal to checkpointing
and can be pursued (or not) on its own merits.

### 3b. User-facing

```
inspect eval retry <log-file>
```

No new command or flag. Checkpoint-aware resume layers onto the
existing `inspect eval retry` pathway. Eval-set retries receive the
same integration (not "much later" — both are v1 commitments).

### 3c. How resume plugs into inspect's retry machinery

Inspect already has two complementary retry pathways (per JJ's
design note):

- **`inspect eval retry <log-file>`** — reads the log, reifies the
  eval config from it, re-runs. Works well for standard cases.
  Struggles with dynamic tasks ("fever-dream" scenarios) that
  reify poorly from a log.
- **Eval-set retry** — re-loads tasks fully in-memory, computes
  task identifiers as a hash of task parameters, matches in-memory
  tasks against log-directory entries. Handles dynamic tasks.

Both paths resolve into the same core concept — a **sample source**
that provides fully resolved samples so the harness avoids
recomputation. The harness consults the sample source when a sample
starts; if the source returns a sample, the harness acts as if that
sample had completed normally.

Three task states already handled by the retry code:

1. Fully complete task → skipped.
2. Partially complete task → married with sample source.
3. New task → run normally.

**Checkpoint integration is an extension of sample source.** Today
sample source returns *complete* samples or nothing. We extend it to
return *partial* samples when a checkpoint exists for a sample that
didn't complete. The harness's existing three-state handling then
covers checkpointed samples without reinventing retry logic.

Identity and completion discovery come from the log + existing retry
infrastructure. The checkpoints directory is a sidecar the sample
source consults — its location is recorded in the log's manifest
(sibling by default).

**Note on dynamic tasks.** For evals with dynamic task generation,
the eval-set retry path is the correct fit; `inspect eval retry` is
weaker there. Checkpoint integration goes on both paths in v1.
(Internal note, not exposed to customers in the customer-facing
doc.)

## Design notes (parked)

### Agent vs. solver protocol

- Today: a solver receives full `TaskState` (including `Store`); an
  **agent** has a narrower protocol so it can be used as tool OR solver.
- Initially assumed this feature would force broadening the agent input
  to carry `{messages, events, store, …}`. On reflection it does not:
  events and store are restored by the harness into ambient inspect
  state, and messages already flow to agents today. See §3a.
- The only new addition strictly required by checkpointing is an
  `is_resuming` boolean on the agent call.
- Broader "agent protocol ↔ solver `TaskState`" alignment remains a
  valid separate discussion, but is **not on the critical path** for
  checkpointing.

## Appendix A — Restic egress protocol (design sketch)


Concrete design for the host-mediated egress path chosen in §1a.
Written against Docker specifically (using `docker cp` as the
copy-out primitive); generalizes to any sandbox provider by
substituting inspect's standard sandbox exec/copy API for
`docker cp`. Included here verbatim as a starting point for the
implementation plan — not yet validated end-to-end.

### Overview

A network-isolated Docker container maintains a local restic repository
for checkpoint snapshots. After each snapshot, incremental changes are
egressed to a host-side mirror repository via `docker cp`. The
host-side repo is a valid restic repository usable for restore, check,
and prune operations.

### Key property: append-only repository

With normal `restic backup` operations (no `prune`, `forget`, or
`rebuild-index` inside the container), the repo is effectively
append-only:

- `data/` pack files — immutable, content-addressed
- `snapshots/` — immutable, content-addressed
- `index/` — new files added; occasional consolidation may delete
  superseded index files (harmless, mirror accumulates a superset)
- `config`, `keys/` — written at init, never modified
- `locks/` — transient, excluded from egress

Because filenames are content hashes, filename-level presence checks
suffice to identify new files — no content comparison needed.

### Egress protocol

The host drives snapshots via commands into the container. Each cycle:

1. **Host → Container:** "Take snapshot, egress sequence N."
2. **Container:** Runs `restic backup`, waits for lock release.
3. **Container:** Diffs current repo contents against an egress
   manifest (list of filenames previously egressed) to find new files.
4. **Container:** Creates `/tmp/egress-N.tar` containing new files in
   order: `data/` first, then `index/`, then `snapshots/`. Returns
   tarball path and file list.
5. **Host:** `docker cp`s the tarball out, extracts into the host
   repo.
6. **Host:** Verifies integrity (minimum:
   `restic -r /host/repo snapshots` succeeds).
7. **Host → Container:** "Commit N."
8. **Container:** Updates manifest, deletes tarball.

### Design decisions

- **Manifest-based diff, not mtime-based.** Container maintains a
  sorted list of already-egressed filenames. Robust to clock skew,
  container restarts, partial failures.
- **Two-phase commit on the manifest.** Container does not advance
  its manifest until the host confirms successful extraction.
  Prevents state divergence if egress fails between tar creation and
  host extraction.
- **Ordered tar contents.** `data/` → `index/` → `snapshots/`
  ordering means the host repo is valid at every intermediate state.
  A crashed extraction leaves the mirror missing the newest snapshot,
  never with a dangling snapshot referencing missing data.
- **Tarball lives outside the repo.** Written to `/tmp/` to keep
  the repo directory clean.
- **No `prune`/`forget` inside the container.** These break the
  append-only property. Run them on the host-side mirror instead,
  accepting that the container repo grows monotonically until the
  container is torn down.

### Open question (scoped to this appendix)

Container lifecycle — if ephemeral across snapshots, the manifest must
live in the repo or be passed in by the host each cycle. If
long-lived, it can be container-local state.

## Appendix B — Restic characteristics relevant to this design

Notes from a scan of restic's docs (`restic.net`, GitHub README, design doc).
Captured to inform — not commit to — the engine decision.

**Good fits:**

- **Single static Go binary, cross-platform** (Linux/macOS/Windows/*BSD).
  Clean fit for injection into arbitrary sandbox images with no runtime
  dependencies. BSD 2-Clause license — permissive.
- **Native S3 backend** (plus Azure, GCS, B2, SFTP, REST server, rclone,
  local). Directly satisfies the "`s3://` overridable destination"
  requirement, and supports a direct-backend-write egress path from inside
  the sandbox (credentials → env vars).
- **Content-defined chunking (Rabin fingerprints, 512 KiB–8 MiB blobs,
  ~1 MiB avg) + SHA-256 content addressing.** Strong deduplication across
  snapshots and across files — only changed blobs are uploaded on each
  subsequent backup. This is exactly the "changed-file detection + efficient
  diff storage" behavior we want.
- **No explicit diff chain.** Snapshots reference trees by hash; shared
  content dedups automatically. There is no "baseline snapshot" that
  subsequent snapshots are deltas *against* — each snapshot is logically
  independent and restorable standalone. This largely **answers the
  "baseline checkpoint?" unresolved question**: with restic, you simply take
  a snapshot; the first one stores everything, subsequent ones only store
  new blobs, and any snapshot can be restored without the others.
- **Repository format is a stable public API** within a major version
  (semver promise) — safe long-term dependency.
- **JSON output** on `backup`, `snapshots`, etc. — scriptable from inspect.
- **Repo v2 supports zstd compression.**
- **`check`, `forget`, `prune`** give us integrity verification and
  retention-policy tooling out of the box.

**Caveats / decisions forced on us:**

- **Mandatory encryption** (AES-256-CTR + Poly1305-AES, password-derived
  master key). We must manage a repo password per checkpoint repo. Open:
  is that password random-per-eval (stored where?), fixed/known, or derived?
  Encryption is not optional — even for local, non-sensitive repos.
- **Locking model.** "At most one process can have an exclusive lock on
  the repository." Parallel reads/writes are supported with care, but
  concurrent `backup` operations from multiple samples against the **same
  repo** need careful handling. Natural resolution: **one repo per sample**
  (i.e., each checkpoint subdir tree corresponds to a per-sample restic
  repo). Revisit — shared repo would deduplicate across samples, which
  could be a meaningful win at scale.
- **Pack files are already bundled** (the pack format is internal
  deduplication-aware bundling). An outer tar around restic's output is
  likely redundant for size but may still help egress round-trip count
  when copying many pack files out via sandbox exec.
- **Repository layout** is a directory of subdirs (`data/`, `index/`,
  `snapshots/`, `keys/`, `locks/`, `config/`) — maps cleanly to a
  `foo.eval.checkpoints/<sample-id>/` directory per sample, with each
  "checkpoint" being a **snapshot within that repo** rather than its own
  subdirectory. This is a model shift from the "one subdirectory per
  checkpoint" layout originally sketched — worth discussing.

**Model-shift implication (important):**

If we adopt restic, the originally-sketched layout
(`foo.eval.checkpoints/<checkpoint-id>/`) does not map cleanly. Restic's
unit of storage is the *repository*, and individual checkpoints are
*snapshots within* the repository (addressed by snapshot ID, not by
directory). The natural mapping becomes:

```
foo.eval.checkpoints/
  <sample-id>/              # a restic repository
    config data/ index/ snapshots/ keys/ locks/
    # individual checkpoints = restic snapshots inside this repo
```

Plus a sidecar per sample (or per checkpoint) carrying the **non-sandbox**
checkpoint contents (metadata, context window, store), which restic does
not handle. Options for that sidecar: separate files alongside the
repo, or included in the snapshot by backing up an additional directory
that contains the serialized non-sandbox state. Decide later.

**Sandbox checkpoint data stored out-of-band.** Because restic's unit of
storage is a repository (not a per-checkpoint folder), **sandbox-state
checkpoints must live out-of-band from the per-checkpoint subdirectory
hierarchy**. A per-checkpoint subdir naturally holds the non-sandbox
contents (metadata, context window, store) and a *reference* to the
corresponding restic snapshot id(s); the actual backup data lives
alongside in the restic repo(s).

**Multiple sandboxes per sample/eval.** Some evals use many sandboxes per
sample (multiple named `SandboxEnvironment`s). Checkpointing must retain
state for **each** sandbox. Likely mapping:

```
foo.eval.checkpoints/
  <sample-id>/
    sandboxes/
      <sandbox-name-1>/    # restic repo for sandbox 1
      <sandbox-name-2>/    # restic repo for sandbox 2
      ...
    checkpoints/
      <checkpoint-id>/
        metadata.json
        messages.json / events.*
        store.json
        sandbox-refs.json  # { <sandbox-name>: <restic-snapshot-id> }
```

Exact shape TBD, but the key constraints are: (a) one restic repo per
sandbox (to avoid cross-sandbox lock contention and keep snapshot sets
scoped), and (b) each checkpoint record references the snapshot id(s)
that correspond to it, across all sandboxes it needed to capture.

## Unresolved questions

### Open

- **Sandbox startup sequencing on resume.** Sandboxes today are spun
  up on demand (first use within a sample, not at sample start). On
  resume, if we eagerly restore every sandbox home dir before the
  agent runs, we force every sandbox to exist before its natural
  first-demand point — which changes lifecycle semantics and may spin
  up sandboxes a resumed agent never uses (wasteful) or spin them up
  in a different order than the original run (semantically subtle).
  Alternative: **defer home-dir restoration until the sandbox is
  demanded**, matching current lifecycle. That means the agent's
  `resume=True` contract needs to say "sandboxes *will be* restored
  on-demand" rather than "sandboxes *are* restored." Need to
  investigate how sandbox startup is currently triggered and whether
  a restore-on-first-use hook fits cleanly. Likely the right v1
  answer, but confirm.


(user-facing resumption UX — resolved, see below)
- **Checkpoint retention (intermediate policies).** Baseline resolved in
  §1c: default = delete on successful eval completion, opt-in retain-
  forever, all intra-eval checkpoints retained (no collapsing). Remaining
  open questions: do we want intermediate policies (keep last N, keep on
  failure only, time-based expiry)? Per-eval vs. global configuration?
- **Diff/backup engine.** Restic is the current front-runner (see §1a and
  Appendix B). Alternatives still open (borg, kopia, rsync-based, custom).
  Decision criteria: S3 backend support, dedup efficiency, static-binary
  injectability into sandbox, licensing.
- **Checkpoint atomicity.** How do we guarantee a checkpoint is either
  fully written or ignored on resume (crash mid-checkpoint)? *(Deferred.)*
- **Scope of checkpointed state beyond the four items above** — does it
  also need: active subtasks, RNG/seed state, token/cost counters,
  tool-local state? (Current position: probably not, but revisit.)
- **Concurrency within a single sample.** Multiple sandboxes per sample
  snapshotting at the same checkpoint id — serialize or allow parallel?
  (Cross-sample concurrency is already naturally isolated by per-sample
  sandboxes.)
- **Checkpoint egress path** — resolved: **host-mediated copy-out**. Restic
  runs inside the sandbox and writes to a sandbox-local staging path;
  inspect copies the data out via the sandbox exec/copy API to the
  configured checkpoint destination (local or remote). No credentials
  plumbed into sandboxes. See §1a.
- **First-checkpoint latency** — resolved (reversed): **no forced
  sample-start snapshot.** The user's configured policy interval
  already expresses the loss window they can afford; taking an extra
  zero-point snapshot doesn't narrow that window, it just adds cost.
  The first policy-driven checkpoint is the first snapshot (fatter
  than subsequent deltas, which is expected and acceptable). No
  decaying-interval or separate initial sub-policy.
(hermetic task-code bundling — resolved, see below)
- **Firing checkpoints mid-tool-call.** §2c baseline fires only between
  turns. Open whether to also support firing during long tool
  executions (e.g. a 10-minute subprocess). Instinct: no. Needs own
  discussion later.
- **Checkpoint storage granularity / bundling.** Each per-checkpoint
  subdirectory could be materialized as many individual files, or bundled
  as a single archive (tar/zip). Bundling may be significantly more
  efficient for (a) egress from sandbox (one copy-out vs. many), and
  (b) S3 destinations (one PUT vs. many round-trips, fewer object-count
  costs). Downsides: partial reads become harder; atomicity semantics
  change; interacts with restic's own packfile format (which is already
  a bundle — may make an outer tar redundant *or* may still be a win
  when copying many restic pack files out). Decide after measuring.

### Resolved / set aside

- **Serialization reuse** — resolved: **same on-disk schemas, different
  container.** Messages and events use the same Pydantic/JSON schemas
  as inside a `.eval` log but are written as separate files (likely
  `messages.jsonl`, `events.jsonl`) in each checkpoint dir. No zip
  coupling; checkpoints are not `.eval` files.
- **Restic repo password management** — resolved: inspect
  auto-generates a random password per repo at checkpoint-creation
  time and stores it in `manifest.json` alongside the repo reference.
  Encryption is effectively nominal (anyone with access to the
  checkpoint dir has the key), but zero operational burden on
  customers. Customers wanting real encryption at rest should put
  `foo.eval.checkpoints/` on an encrypted volume / bucket. A future
  user-provided-password mode can be added without breaking the
  auto-generate default.
- **Sandbox home-dir scope** — resolved: fixed path per container
  convention (`$HOME`, typically `/root`). Not configurable in v1.
  Anything outside this path is not captured. Document prominently.
- **Observability** — resolved: `CheckpointEvent` in the normal event
  stream + TUI indicator. No separate journal file in v1.
- **Configuration surface** — resolved: parameter on the agent
  constructor (e.g. `react(checkpoint=...)`). Not on `Task(...)`.
  CLI/global overrides deferred.
- **User-facing resume UX** — resolved (reversed): `inspect eval retry
  <log-file>`. Layers onto existing retry infrastructure rather than
  adding a new command/flag. Eval-set retries receive the same
  integration. See §3.
- **Completed samples on resume** — resolved by the retry-based
  model: completed-sample records live in the `.eval` log as today;
  the retry path already handles them (fully-complete → skipped).
  Checkpoints only hold partial-sample state.
- **Sample source extension** — v1 work item, not an open question:
  extend inspect's existing sample-source abstraction to return
  *partial* samples (in addition to complete / none). See §3c.
- **Hermetic task-code bundling** — resolved: **not required.** This
  was never load-bearing and is fully subsumed by using existing retry
  infrastructure — retry already assumes the user's code/env is
  present, as with any retry today.
- **Sandbox provider coverage** — resolved: the home-dir + injected
  backup tool approach is **provider-agnostic by design**. All providers
  are covered with no per-provider implementation work. This is a core
  motivation for the approach.
- **Non-determinism on resume** — resolved as an **explicit non-goal**
  (moved to §1 non-goals).
- **Repo-per-sample vs. shared repo** — resolved: repos are necessarily
  per-sandbox (and therefore per-sample), because restic runs *inside*
  the sandbox and sandboxes are per-sample. Cross-sample dedup via a
  shared repo is not viable without cross-sandbox coordination.
- **Initial/baseline sandbox checkpoint (baseline-for-diffs framing)** —
  resolved: restic's content-addressing means no explicit baseline
  artifact is required; every snapshot is standalone. (See also
  "First-checkpoint latency" above — also resolved: no forced
  sample-start snapshot.)
- **Non-sandbox checkpoint contents layout** — resolved by §1b sketch:
  lives in `samples/<id>__<epoch>/checkpoints/<checkpoint-id>/`
  alongside `sandbox-refs.json`.
