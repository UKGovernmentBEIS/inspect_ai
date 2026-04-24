# Inspect Checkpointing — Working Design

> Status: design in progress. Not ready for implementation.

## Context

Long-horizon evals can run for days or weeks. Today, if an eval fails before completing, in-progress sample work is lost. Checkpointing persists the in-flight state of each sample periodically so that on failure the eval can be resumed from the most recent checkpoint — per individual sample. Individual samples themselves may run for days to weeks, so resume must be **mid-sample**, not merely sample-level.

Checkpoint + resume is **phase 1 of a broader long-horizon eval feature stream**. Later phases will build on the same foundation (e.g., human-in-the-loop intervention during a running eval).

## Principles

-   **Mid-sample resume.** Resume picks up an individual sample from its latest checkpoint, not from the start of the sample.
-   **Provider-agnostic mechanism.** One filesystem-based mechanism covers all sandbox providers; no provider-native snapshots.
-   **Cooperative with the agent.** Checkpoint/resume only works when the agent participates. Inspect cannot determine on its own whether a given agent's logic will behave correctly after restoration — the agent is the one that knows whether its state is in the messages, the store, and the sandbox (resumable) vs. in in-memory Python state that won't survive a crash (not resumable). For this reason, checkpointing is enabled **by the agent**, configured on the agent's constructor (not on `Task(...)`), and resume-safe behavior is the agent's responsibility.
-   **The `.eval` log is the source of truth** for eval identity, config, sample inputs, and completed-sample records. The checkpoints directory holds only in-flight state.
-   **Resumption is accomplished through `inspect eval retry`,** layering on existing retry infrastructure. No new command or flag.
-   **Resumption inherits retry's rehydration.** Whatever retry can reconstruct — eval config from the log, task identity, sample inputs, dynamic tasks via eval-set — resumption gets for free. Checkpointing adds no new bundling or reification machinery; it extends retry's sample source to also deliver *partial* samples.

## Non-goals

-   **In-memory sandbox/process state.** We checkpoint the agent's **home directory** inside the sandbox — not running processes, open sockets, RAM, or anything outside the home dir (`/tmp`, `/workspace`, `/opt/...`, system-level state). Home-directory- only is a deliberate scoping choice for v1; see §4a.
-   **Provider-native snapshot mechanisms** (Modal memory/VM snapshots, Docker commit, VM image snapshots). Not in Phase 1.
-   **Tracking or replaying external side-effects across resume.** If an agent made external API calls between the last checkpoint and the crash, those side-effects may re-execute on resume. Tool authors are responsible for tolerating this (typically via idempotent tools). *Reality doesn't have a fork command.*
-   **Mid-tool-call checkpointing.** Checkpoints fire only at turn boundaries. A long-running tool call (e.g., a 10-minute subprocess) blocks the next checkpoint until the call returns. We do not interrupt tools to snapshot.

## 1. Data layout

For an eval log `foo.eval`, checkpoints live in a sibling directory `foo.eval.checkpoints/` (default location; overridable to `s3://` or any fsspec-supported URL). The log records the canonical checkpoints directory location.

```         
logs/
  foo.eval                                   # existing eval log
  foo.eval.checkpoints/                      # sibling dir (default)
    manifest.json                            # minimal header:
                                             #   eval_id (to pair with log),
                                             #   layout version,
                                             #   engine = "restic",
                                             #   restic repo password
    <sample-id>__<epoch>[_<retry>]/          # one subtree per attempt.
                                             #   <epoch>: inspect's existing
                                             #   per-sample multi-pass concept.
                                             #   _<retry>: appended only when
                                             #   sample-level retries are
                                             #   enabled (another existing
                                             #   inspect concept).
      sandboxes/                             # sandbox state (see §4)
        <sandbox-name-1>/                    # restic repo for sandbox 1
          config data/ index/ snapshots/ keys/ locks/
        <sandbox-name-2>/                    # restic repo for sandbox 2
          ...
      checkpoints/
        <checkpoint-id>/                     # one subdir per checkpoint
          metadata.json                      # seq, trigger, turn #,
                                             #   created-at, status
          context.json                       # messages + condensed events +
                                             #   events_data (messages/calls
                                             #   pools)
          store.json                         # Store key/values
          sandbox-refs.json                  # { <sandbox-name>: <snapshot-id> }
        <checkpoint-id>/
          ...
    <sample-id>__<epoch>[_<retry>]/
      ...
```

Inspect already supports both multiple **epochs** per sample (an
existing feature — multi-pass evaluation of the same sample) and
sample-level **retries** (re-running a sample after a transient
failure within the same eval run). Each epoch and each retry is a
distinct attempt with its own checkpoint subtree; checkpoints from
one attempt are not shared with or consulted by another.

## 2. Configuration surface

A checkpointing-aware agent accepts an optional **`CheckpointConfig`** on its constructor — for example, `react(checkpoint=CheckpointConfig(...))`. When `None` (or omitted), checkpointing is disabled. The policy is selected on the config; the options are listed below.

All policies fire at turn boundaries only; an agent is never interrupted mid-turn, and in-flight tool calls are never paused to checkpoint.

-   **None** — checkpointing disabled.
-   **Time-based** — approximately every N seconds/minutes; fires at the next turn boundary after the interval elapses (effective interval ≥ N).
-   **Turn-based** — every N agent turns.
-   **Manual** — agent-triggered via an inspect-provided Python function (e.g. `from inspect_ai import checkpoint; await checkpoint(...)`). Not a model-callable tool — this is a programmatic hook for agent authors, not a prompt-engineering surface for the model.

## 3. Built-in support and primitives

Inspect provides checkpointing support at two layers:

-   **Built-in React agent.** The React agent accepts an optional `CheckpointConfig` and supports all policies out of the box. It serves as the reference consumer of the underlying primitives.
-   **Primitives for custom agents.** Custom agents follow the same pattern: accept a `CheckpointConfig` parameter and delegate to inspect-provided primitives — capture state, write checkpoint, restore from checkpoint, policy hooks — rather than reimplementing the machinery. The agent author does **not** track policy state (time elapsed, turns since last checkpoint); inspect's helpers consume the `CheckpointConfig` and fire a checkpoint when the policy says to. The boilerplate to add checkpoint support to a custom agent is minimal.

## 4. Sandbox snapshotting

### 4a. Scope

The agent's **home directory** inside the sandbox — typically `$HOME`, which is `/root` for inspect's default sandbox user. Fixed path per container convention; not configurable in v1. Anything the agent writes outside this path (`/tmp`, `/workspace`, `/opt/...`) is not captured and will not be restored on resume.

### 4b. Engine: restic

[Restic](https://restic.net) is the engine choice. Rationale:

-   Single static Go binary, cross-platform — clean for sandbox injection with no runtime dependencies. BSD 2-Clause license.
-   Content-defined chunking + SHA-256 content addressing gives strong cross-snapshot and cross-file deduplication: each checkpoint only stores new blobs.
-   Snapshots are independent; no explicit baseline artifact needed.
-   Native S3 and fsspec-compatible backends.
-   Repository format is a stable public API within a major version.

See Appendix A for a fuller characteristics summary and Appendix B for the egress protocol.

### 4c. Repository and snapshot scoping

-   **One restic repo per sandbox** Repos live at peer level to `checkpoints/` — at `<sample-id>__<epoch>[_<retry>]/sandboxes/<sandbox-name>/` — rather than nested under each checkpoint subdir, because restic's unit of storage is a repository and individual checkpoints are *snapshots within* a repository.
-   **Snapshots correlate 1:1 with checkpoint ids.** Every checkpoint id has a corresponding snapshot in every active sandbox's repo. The per-checkpoint `sandbox-refs.json` maps `<sandbox-name>` → snapshot id, and the snapshot is **tagged** with the checkpoint id (via restic's `--tag`) so the correlation is recoverable from restic alone if the sidecar is lost.

### 4d. Injection

The restic binary must be injected into the sandbox image — it runs inside the sandbox to enumerate and snapshot the home directory. Implemented by adding it to the existing sandbox-tools injection pipeline (`src/inspect_sandbox_tools/`).

### 4e. Egress

**Host-mediated copy-out.** Restic writes to a sandbox-local staging path; inspect copies the data out via the standard sandbox exec/copy API to the configured checkpoint destination (local filesystem or `s3://`). Works uniformly across destinations; **no storage credentials are ever plumbed into the sandbox.** Egress protocol sketch in Appendix B.

### 4f. Encryption

Restic mandates encryption. Inspect **auto-generates** a random password per repo at checkpoint-creation time and stores it in `manifest.json` alongside the repo reference. Encryption is effectively nominal — anyone with access to the checkpoint directory has the key — but operational burden on customers is zero. Customers requiring real at-rest encryption should place the checkpoint directory on an encrypted volume or bucket. A future user-provided-password mode can be added without breaking the auto-generate default.

## 5. Context-window serialization

Messages and events use the same **condensed representation** as inside a `.eval` log which avoids the O(N²) serialization cost. Each checkpoint writes a single `context.json` containing:

-   Events in condensed form (with `input_refs` / `call_refs`).
-   Deduplication pools (`events_data` with `messages` and `calls`).

Reuses `condense_sample()` / `resolve_sample_events_data()` from `src/inspect_ai/log/_pool.py` and `_condense.py`. Not a `.eval` file; no zip coupling.

`store.json` is a separate file containing the sample's `Store` key/value state.

## 6. Resumption

### 6a. User-facing command

```         
inspect eval retry <log-file>
```

No new command or flag. Checkpoint-aware resume layers onto the existing `inspect eval retry` pathway. Eval-set retries receive the same integration; both are v1 commitments.

### 6b. Retry machinery

Inspect has two complementary retry pathways:

-   **`inspect eval retry <log-file>`** — reads the log, reifies the eval config from it, re-runs. Works well for standard cases; weaker for dynamic tasks.
-   **Eval-set retry** — re-loads tasks fully in-memory, computes task identifiers as a hash of task parameters, matches in-memory tasks against log-directory entries. Handles dynamic tasks.

Both paths resolve into the same core abstraction — a **sample source** that provides fully resolved samples so the harness avoids recomputation. The harness consults the sample source when a sample starts; if the source returns a sample, the harness acts as if that sample had completed normally.

Three task states already handled by the retry code:

1.  Fully complete → skipped.
2.  Partially complete → married with sample source.
3.  New → run normally.

### 6c. Sample-source extension

Today sample source returns *complete* samples or nothing. We extend it to also return *partial* samples when a checkpoint exists for a sample that didn't complete. The harness's existing three-state handling then covers checkpointed samples without reinventing retry logic.

Identity and completion discovery come from the log plus existing retry infrastructure. The checkpoints directory is a sidecar the sample source consults; its location is recorded in the log's manifest (sibling by default).

### 6d. Division of labor on restore

The **harness** performs the full restoration before the agent runs:

1.  Restore the sandbox from the corresponding restic snapshot.
2.  Rehydrate the context window (messages + events) into ambient inspect state.
3.  Rehydrate the `Store` into ambient inspect state.
4.  Invoke the agent with `resume=True`.

The **agent** does not re-open the checkpoint, does not re-materialize the sandbox, and does not re-parse stored state.

## 7. Agent protocol changes

Checkpointing adds a **single** optional parameter to the agent protocol:

``` python
resume: Literal[True] | None
```

On a resume, Inspect invokes the agent with `resume=True` for the first (and likely only) call after restoration. On a normal, non-resumed run, the parameter is `None` (or omitted).

**What `resume=True` guarantees:**

-   **Sandbox.** The home directory has been restored. Agents continue to use it via the normal sandbox API.
-   **Messages.** The sample's message history has been restored into inspect's internal state and will be passed to this first call via the `AgentState`.
-   **Events.** The sample's event history has been restored into inspect's internal state. Events are inspect-internal bookkeeping that rolls into the final `.eval` log; they do not flow through the agent input.
-   **Store.** The sample's `Store` has been restored into the ambient context (`store_as`, etc.). Agents read from it normally.

**What the agent does with it:**

-   Skip one-shot setup that has already happened (system-prompt assembly, initial tool probing, sandbox scaffolding).
-   Optionally take a different first-turn path ("figure out where you left off and continue").
-   Avoid double-recording state that is already present in the rehydrated messages/events.

Handling `resume=True` is not strictly required — an agent that ignores the parameter will still run against the restored state. In practice, though, most agents will want to handle it, for the reasons listed above. The built-in React agent does.

## 8. Lifecycle and observability

### 8a. CheckpointEvent

Each checkpoint attempt emits a structured `CheckpointEvent` into the normal event stream, carrying at minimum: `seq`, `trigger` (time/turn/manual), outcome (success/failure), duration, on-disk size, and — on failure — the error. Events are part of the `.eval` log, so checkpoint history is preserved in the normal log. No dedicated checkpoint journal file in v1.

### 8b. TUI surface

The inspect TUI shows a small indicator while a checkpoint is running and the last-checkpoint timestamp.

### 8c. Checkpoint-attempt failures

A failed checkpoint attempt (disk full, sandbox exec error, restic error, etc.) logs a warning. The eval continues until the configured tolerance for *consecutive* failures is exceeded; on the next policy fire it retries. Tolerance is set on the checkpoint config as a non-negative integer N — the eval fails after N consecutive failed attempts. (Setting 0 makes any checkpoint failure fatal.) When the tolerance is omitted, it is unlimited (the default). A successful checkpoint resets the counter.

Rationale for unlimited as the default: durability is a nicety, not a correctness requirement; failing a long-horizon eval over transient hiccups would be worse than the loss it's meant to prevent. The ceiling lets strict callers bound that tradeoff.

Known risk under the unlimited default: a customer not monitoring the event stream could believe they have recent checkpoints when they don't. The TUI indicator and event-stream visibility make this visible in practice; setting a finite tolerance gives a hard signal instead.

### 8d. Retention

-   **On successful eval completion (default):** delete the `foo.eval.checkpoints/` tree.
-   **Opt-in "retain forever":** a configuration option keeps the checkpoint directory after success. CLI/config surface TBD.
-   **During the eval:** all checkpoints are retained. We do not collapse, merge, or prune older checkpoints into the head. Rationale: preserves the option of resuming from an arbitrary non-head checkpoint (a future capability). Practically: no `restic forget` / `restic prune` on active repos.

## 9. Open questions

-   **Retention granularity: eval-complete vs. sample-complete.** §8d says checkpoints are deleted "on successful eval completion." Open: should a sample's checkpoint subtree instead be deleted (or at least eligible for deletion) as soon as *that sample* completes successfully, rather than waiting for the whole eval to finish? Eval-complete is simpler and keeps everything available until the run is done; sample-complete reclaims space sooner and scales better for evals with many long-running samples. Interacts with retain-forever (which would presumably still hold things until eval end).
-   **Checkpoint atomicity.** How do we guarantee a checkpoint is either fully written or ignored on resume after a mid-write crash? Deferred.
-   **Checkpoint-id naming.** Monotonic seq, UUID, or timestamp? Monotonic reads most naturally for humans.
-   **Engine commitment.** Restic is strongly preferred but not formally committed. Alternatives (borg, kopia, rsync-based, custom) remain theoretically on the table.

## Appendix A — Restic characteristics

Notes from a scan of restic's documentation.

**Good fits:**

-   Single static Go binary, cross-platform (Linux/macOS/Windows/\*BSD). BSD 2-Clause license.
-   Native S3 backend (plus Azure, GCS, B2, SFTP, REST server, rclone, local).
-   Content-defined chunking (Rabin fingerprints, 512 KiB–8 MiB blobs, \~1 MiB avg) + SHA-256 content addressing. Strong deduplication across snapshots and across files.
-   No explicit diff chain. Snapshots reference trees by hash; shared content dedups automatically. Every snapshot is independent and restorable standalone.
-   Repository format is a stable public API within a major version.
-   JSON output on `backup`, `snapshots`, etc.
-   Repo v2 supports zstd compression.
-   `check`, `forget`, `prune` commands give integrity verification and retention-policy tooling out of the box.

**Caveats:**

-   **Mandatory encryption** (AES-256-CTR + Poly1305-AES, password-derived master key). Not optional, even for local non-sensitive repos. See §4f for password handling.
-   **Locking model.** At most one process can hold an exclusive lock on a repository. Drives the per-sandbox-repo decision in §1c.
-   Pack files are already a bundle (deduplication-aware). An outer tar around restic's output is likely redundant for size but may still help egress round-trip count when copying many pack files.

## Appendix B — Restic egress protocol (design sketch)

Concrete design for the host-mediated egress path in §4e. Written against Docker specifically (using `docker cp` as the copy-out primitive); generalizes to any sandbox provider by substituting inspect's standard sandbox exec/copy API for `docker cp`. Starting point for implementation, not yet end-to-end validated.

### Overview

A network-isolated Docker container maintains a local restic repository for checkpoint snapshots. After each snapshot, incremental changes are egressed to a host-side mirror repository via `docker cp`. The host-side repo is a valid restic repository usable for restore, check, and prune operations.

### Key property: append-only repository

With normal `restic backup` operations (no `prune`, `forget`, or `rebuild-index` inside the container), the repo is effectively append-only:

-   `data/` pack files — immutable, content-addressed.
-   `snapshots/` — immutable, content-addressed.
-   `index/` — new files added; occasional consolidation may delete superseded index files (harmless — mirror accumulates a superset).
-   `config`, `keys/` — written at init, never modified.
-   `locks/` — transient, excluded from egress.

Because filenames are content hashes, filename-level presence checks suffice to identify new files; no content comparison needed.

### Protocol

Each snapshot cycle:

1.  **Host → Container:** "Take snapshot, egress sequence N."
2.  **Container:** Runs `restic backup`, waits for lock release.
3.  **Container:** Diffs current repo contents against an egress manifest (list of filenames previously egressed) to find new files.
4.  **Container:** Creates `/tmp/egress-N.tar` containing new files in order: `data/` first, then `index/`, then `snapshots/`. Returns tarball path and file list.
5.  **Host:** `docker cp`s the tarball out, extracts into the host repo.
6.  **Host:** Verifies integrity (minimum: `restic -r /host/repo snapshots` succeeds).
7.  **Host → Container:** "Commit N."
8.  **Container:** Updates manifest, deletes tarball.

### Design decisions

-   **Manifest-based diff, not mtime-based.** Container maintains a sorted list of already-egressed filenames. Robust to clock skew, container restarts, and partial failures.
-   **Two-phase commit on the manifest.** Container does not advance its manifest until the host confirms successful extraction. Prevents state divergence if egress fails between tar creation and host extraction.
-   **Ordered tar contents** (`data/` → `index/` → `snapshots/`). The host repo is valid at every intermediate state. A crashed extraction leaves the mirror missing the newest snapshot, never with a dangling snapshot referencing missing data.
-   **Tarball lives outside the repo** (`/tmp/`) to keep the repo directory clean.
-   **No `prune` / `forget` inside the container.** These break the append-only property. Run them on the host-side mirror instead, accepting that the container repo grows monotonically until the container is torn down.

### Open question (scoped to this appendix)

Container lifecycle — if ephemeral across snapshots, the manifest must live in the repo or be passed in by the host each cycle. If long-lived, it can be container-local state.