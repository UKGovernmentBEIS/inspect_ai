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

-   **In-memory sandbox/process state.** We checkpoint configured directories inside each sandbox — not running processes, open sockets, RAM, or any path outside the configured set. Path selection is agent-specific and declared on the agent's `CheckpointConfig` (§2, §4a).
-   **Provider-native snapshot mechanisms** (Modal memory/VM snapshots, Docker commit, VM image snapshots). Not in Phase 1.
-   **Tracking or replaying external side-effects across resume.** If an agent made external API calls between the last checkpoint and the crash, those side-effects may re-execute on resume. Tool authors are responsible for tolerating this (typically via idempotent tools). *Reality doesn't have a fork command.*
-   **Mid-tool-call checkpointing (not initially).** For Phase 1, checkpoints fire only at turn boundaries. A long-running tool call (e.g., a 10-minute subprocess) blocks the next checkpoint until the call returns. We do not interrupt tools to snapshot. Mid-tool-call checkpointing is planned for a later phase.

## 1. Data layout

For an eval log `foo.eval`, checkpoints live by default in a sibling directory `foo.checkpoints/` (`.eval` is stripped from the basename before the `.checkpoints` suffix is appended). The parent root is overridable via `CheckpointConfig.checkpoints_dir` (any fsspec-resolvable path: local, `s3://`, etc.) — the per-eval subdir name is unchanged. The log records the canonical checkpoints directory location.

```         
logs/
  foo.eval                                   # existing eval log
  foo.checkpoints/                           # sibling dir (default;
                                             #   parent overridable via
                                             #   CheckpointConfig.checkpoints_dir).
    manifest.json                            # eval-level header:
                                             #   eval_id (pairs with log),
                                             #   layout version,
                                             #   engine = "restic",
                                             #   restic password
    <sample-id>__<epoch>[_<retry>]/          # one subtree per attempt.
                                             #   <epoch>: inspect's existing
                                             #   per-sample multi-pass concept.
                                             #   _<retry>: appended only when
                                             #   sample-level retries are
                                             #   enabled (another existing
                                             #   inspect concept).
      ckpt-00001.json                        # per-checkpoint sidecar
      ckpt-00002.json                        #   (plaintext index;
      ...                                    #    sidecar write is the
                                             #    commit point — see §4d).
      host/                                  # restic repo: host state.
                                             #   each snapshot contains
                                             #   context.json + store.json
                                             #   (see §5).
        config data/ index/ snapshots/ keys/ locks/
      sandboxes/
        <sandbox-name-1>/                    # restic repo: sandbox 1's
                                             #   configured paths (§4a).
          config data/ index/ snapshots/ keys/ locks/
        <sandbox-name-2>/                    # restic repo: sandbox 2's
                                             #   configured paths.
          ...
    <sample-id>__<epoch>[_<retry>]/
      ...
```

A **checkpoint** is identified by an ordinal integer (1, 2, 3, …) chosen by inspect at write time. Each per-checkpoint sidecar (`ckpt-NNNNN.json`, zero-padded for lexical sort) carries the customer-facing metadata and references into the restic repos:

```json
{
  "checkpoint_id": 42,
  "trigger": "time",
  "turn": 137,
  "created_at": "2026-04-26T14:23:11Z",
  "duration_ms": 842,
  "size_bytes": 1834291,
  "host": {
    "snapshot_id": "<restic snapshot id>",
    "size_bytes": 1612345,
    "duration_ms": 720
  },
  "sandboxes": {
    "default": {
      "snapshot_id": "<restic snapshot id>",
      "size_bytes": 110234,
      "duration_ms": 95
    },
    "tools": {
      "snapshot_id": "<restic snapshot id>",
      "size_bytes": 111712,
      "duration_ms": 87
    }
  }
}
```

Each per-repo entry (`host` and the values in `sandboxes`) is a
`SnapshotInfo` record carrying the restic snapshot id plus that
backup's incremental size (`data_added_packed` from restic's summary)
and elapsed time. The top-level `size_bytes` is the rolled-up total.

Listing checkpoints for an attempt is `ls <attempt>/ckpt-*.json` — no restic invocation needed. Restic snapshots are also tagged with the ordinal as a debugging aid / fallback if a sidecar is lost; the sidecar is the authoritative index.

Inspect already supports both multiple **epochs** per sample (an
existing feature — multi-pass evaluation of the same sample) and
sample-level **retries** (re-running a sample after a transient
failure within the same eval run). Each epoch and each retry is a
distinct attempt with its own checkpoint subtree; checkpoints from
one attempt are not shared with or consulted by another.

## 2. Configuration surface

A checkpointing-aware agent accepts an optional **`CheckpointConfig`** on its constructor — for example, `react(checkpoint=CheckpointConfig(...))`. When `None` (or omitted), checkpointing is disabled.

```python
@dataclass
class TimeInterval:
    every: timedelta              # wall-clock time between checkpoints

@dataclass
class TurnInterval:
    every: int                    # agent turns between checkpoints

@dataclass
class TokenInterval:
    every: int                    # tokens generated between checkpoints

@dataclass
class CostInterval:
    every: float                  # USD between checkpoints

@dataclass
class BudgetPercent:
    budget: Literal["token", "cost", "time", "working"]
    percent: float                # e.g. 10.0 → every 10% of the named budget

CheckpointTrigger = (
    TimeInterval         # every N of wall-clock time
    | TurnInterval       # every N agent turns
    | TokenInterval      # every N tokens generated
    | CostInterval       # every $N spent
    | BudgetPercent      # at percentage milestones of a named budget
    | Literal["manual"]  # agent-triggered via await checkpoint()
)

@dataclass
class Retention:
    after_eval: Literal["delete", "retain"] = "delete"
    """What to do with the checkpoint directory after the eval completes
    successfully. "delete" (default) removes it; "retain" keeps it for
    later inspection or replay. See §8d."""

class CheckpointConfig:
    trigger: CheckpointTrigger
    """Checkpoint trigger. All triggers fire at the next turn boundary
    after the trigger condition is reached. See bullets below."""

    checkpoints_dir: str | None = None
    """Override the parent root under which the eval checkpoints dir
    lands. None (default) = sibling of the eval log file. When set,
    inspect places <log-base>.checkpoints/ under this root. Any
    fsspec-resolvable path (s3://, local, etc.). See §1."""

    sandbox_paths: dict[str, list[str]] = {}
    """Per-sandbox-name list of absolute paths to capture inside the sandbox.
    Empty/omitted = host-only checkpointing (no sandbox repos). See §4a."""

    max_consecutive_failures: int | None = None
    """If set, the sample fails after N consecutive failed checkpoint attempts.
    None = unlimited tolerance (default). 0 = any failure is fatal. See §8c."""

    retention: Retention = Retention()
    """Controls when checkpoint data is deleted. See §8d."""
```

All triggers fire at turn boundaries only; an agent is never interrupted mid-turn, and in-flight tool calls are never paused to checkpoint. To disable checkpointing, omit the ``CheckpointConfig`` (or pass ``None`` to a checkpointing-aware agent).

-   **Time-based** (`trigger=TimeInterval(every=timedelta(minutes=15))`) — approximately every N seconds/minutes of wall-clock time; fires at the next turn boundary after the interval elapses (effective interval ≥ N).
-   **Turn-based** (`trigger=TurnInterval(every=5)`) — every N agent turns.
-   **Token-based** (`trigger=TokenInterval(every=100_000)`) — every N tokens generated.
-   **Cost-based** (`trigger=CostInterval(every=5.00)`) — every $N of model spend.
-   **Budget-percentage** (`trigger=BudgetPercent(budget="cost", percent=10)`) — fires at percentage milestones of one of inspect's configured limits. `budget` is one of `"token"`, `"cost"`, `"time"` (wall-clock from `time_limit`), `"working"` (agent-active from `working_limit`); `percent` is the step size (e.g. `10` → fires at 10%, 20%, …). Requires the corresponding `*_limit` to be set on the task or sample.
-   **Manual** (`trigger="manual"`) — agent-triggered via an inspect-provided Python function (e.g. `from inspect_ai import checkpoint; await checkpoint(...)`). Not a model-callable tool — this is a programmatic hook for agent authors, not a prompt-engineering surface for the model.

### Sandbox paths

The config also specifies which directories inside each sandbox are captured, as a per-sandbox-name map of absolute paths:

```python
CheckpointConfig(
    ...,
    sandbox_paths={
        "default": ["/root", "/workspace"],
        "tools":   ["/opt/agent-state"],
    },
)
```

Each entry maps a sandbox name (the dict key returned by `sample_init`) to a list of paths inside that sandbox. Restic snapshots all paths for a given sandbox in a single backup invocation; cross-path dedup is automatic (§4a, §4d).

There is **no implicit default**. Path selection is agent-specific:

-   Native Python agents (e.g. the built-in React agent) typically declare an empty `sandbox_paths` — their state lives in messages and `Store`, both captured by the host repo. No sandbox repo is created in this case.
-   **Sandbox CLI agents** (Claude Code, Codex CLI, Gemini CLI) typically declare multiple paths: the agent's home directory, the project working directory, and any tool-specific state directories.

If a sandbox name returned by `sample_init` does not appear in `sandbox_paths`, no sandbox repo is created for it.

## 3. Built-in support and primitives

Inspect provides checkpointing support at two layers:

-   **Built-in React agent.** The React agent accepts an optional `CheckpointConfig` and supports all policies out of the box. It serves as the reference consumer of the underlying primitives.
-   **Primitives for custom agents.** Custom agents follow the same pattern: accept a `CheckpointConfig` parameter and delegate to inspect-provided primitives — capture state, write checkpoint, restore from checkpoint, policy hooks — rather than reimplementing the machinery. The agent author does **not** track policy state (time elapsed, turns since last checkpoint); inspect's helpers consume the `CheckpointConfig` and fire a checkpoint when the policy says to. The boilerplate to add checkpoint support to a custom agent is minimal.

## 4. Snapshotting

### 4a. Scope

**Sandbox repos** capture a list of paths inside each sandbox, configured per-sandbox-name on the agent's `CheckpointConfig` (§2). Restic backs up all configured paths in a single snapshot per cycle; cross-path CDC dedup is automatic. Anything outside the configured paths is not captured and will not be restored on resume.

The right paths are agent-specific. Native Python agents typically need none — their state lives in messages and `Store`, both captured by the host repo. **Sandbox CLI agents** (Claude Code, Codex CLI, Gemini CLI, etc.) typically need several directories: the agent's home directory, the project working directory (often `/workspace`), and any tool-state directories the agent writes to. Agent authors are expected to declare the paths their agent actually depends on.

**Host repo** captures a small per-attempt host-local working tree containing exactly two files (`context.json`, `store.json`) — see §5.

### 4b. Engine: restic

[Restic](https://restic.net) is the engine choice. Rationale:

-   Single static Go binary, cross-platform — clean for sandbox injection with no runtime dependencies. BSD 2-Clause license.
-   Content-defined chunking + SHA-256 content addressing gives strong cross-snapshot and cross-file deduplication: each checkpoint only stores new blobs.
-   Snapshots are independent; no explicit baseline artifact needed.
-   Native S3 and fsspec-compatible backends.
-   Repository format is a stable public API within a major version.

See Appendix A for a fuller characteristics summary and Appendix B for the egress protocol.

### 4c. Acquisition

Restic is a foreign Go binary, not built from inspect's source. Inspect fetches it from upstream on first use and caches a decompressed copy locally. The same resolver serves both **sandbox** (injected into sandbox containers per §4e) and **host** (used directly by the eval process for the host repo).

**Pinned version, single source of truth.** A restic version is pinned in `restic_version.txt` alongside the existing `sandbox_tools_version.txt`. The file holds just the version string (e.g. `0.18.1`). The same version is used everywhere — host resolver, sandbox injection, the prefetch CLI. Restic's repo format is stable within a major version, but pinning the exact version on both sides removes any compatibility ambiguity.

**Filename convention.** Inspect uses restic's own published filenames verbatim. Given a pinned version *V* (e.g. `0.18.1`), the supported platforms are:

-   `restic_{V}_linux_amd64.bz2` — covers most sandboxes and linux hosts.
-   `restic_{V}_linux_arm64.bz2` — covers arm sandboxes and graviton-class linux hosts.
-   `restic_{V}_darwin_amd64.bz2` — intel mac hosts.
-   `restic_{V}_darwin_arm64.bz2` — apple silicon mac hosts.
-   `restic_{V}_windows_amd64.zip` — windows hosts.

Linux and darwin binaries are bzip2-compressed; windows ships as a zip archive containing a single `.exe`. The resolver handles both formats. The download URL follows the same naming: `https://github.com/restic/restic/releases/download/v{V}/restic_{V}_{os}_{arch}.{bz2|zip}`.

**Runtime resolution.** Two-tier:

1.  **Decompressed cache hit** — look up `restic_{V}_{os}_{arch}` (with `.exe` suffix on windows) in inspect's user cache directory: `$XDG_CACHE_HOME/inspect/bin/` (or `~/.cache/inspect/bin/` if unset) on linux/macOS, `%LOCALAPPDATA%\inspect\bin\` on windows. Hot path: subsequent runs skip both decompression and download.
2.  **Download** — on cache miss, fetch the appropriate `.bz2`/`.zip` from restic's GitHub releases, verify SHA256, decompress, and write the resulting executable to the cache. Subsequent runs are tier-1 hits.

The cache holds only decompressed binaries and lives in the user cache directory rather than the package install directory. This keeps the cache writable in all install scenarios (including read-only system Python installs) and lets it persist across `pip uninstall` / reinstall cycles. The host process uses the resolver to obtain restic for host-repo writes; the sandbox-tools injection code uses it to obtain the linux-arch binary it copies into the sandbox.

**Pre-download CLI.** A CLI command pre-warms the cache so a checkpointed eval starts without waiting for downloads:

```bash
inspect download restic        # every supported platform
```

The command always fetches every supported platform (~36 MB compressed total) — selectivity isn't worth the configuration complexity at this size, and a complete cache means any sandbox arch is ready regardless of which one a sample ends up using. Idempotent: per-platform output indicates "downloaded" or "already cached," then a summary table shows the cache state. Recommended for offline / air-gapped environments, CI runners that want predictable startup, and any time you need a guarantee that checkpointing won't pause on a download at start time.

**Verification.** SHA256 in v1; restic publishes `SHA256SUMS` per release. GPG verification against restic's signing key is a future enhancement.

**macOS Gatekeeper.** macOS attaches a `com.apple.quarantine` extended attribute to files downloaded by browsers (Safari, Chrome) and similar UI tools; Gatekeeper checks quarantined binaries against Apple notarization and blocks unnotarized binaries with a modal dialog. Restic is unsigned and unnotarized, so manually downloading and decompressing a `restic_*.bz2` via a browser will trigger Gatekeeper on first execution.

**Programmatic downloads via Python's stdlib do not set the quarantine xattr.** Inspect's resolver (`urllib.request` + `bz2`/`zipfile`) produces executable binaries that run without prompting. The user-visible Gatekeeper failure is limited to users who manually stage a browser-downloaded binary into a path the resolver picks up (e.g. via an override env var). The download pattern (linux/darwin shown; windows uses `zipfile` instead of `bz2`):

```python
import bz2
import shutil
import stat
import urllib.request
from pathlib import Path

VERSION = "0.18.1"
OS_ARCH = "darwin_arm64"  # or linux_amd64, linux_arm64, darwin_amd64
URL = f"https://github.com/restic/restic/releases/download/v{VERSION}/restic_{VERSION}_{OS_ARCH}.bz2"

compressed = Path(f"restic_{VERSION}_{OS_ARCH}.bz2")
binary = Path(f"restic_{VERSION}_{OS_ARCH}")

urllib.request.urlretrieve(URL, compressed)
with bz2.open(compressed, "rb") as src, open(binary, "wb") as dst:
    shutil.copyfileobj(src, dst)
binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
```

### 4d. Repository and snapshot scoping

-   **N+1 restic repos per attempt:** one `host/` repo plus one `sandboxes/<sandbox-name>/` repo per active sandbox. Every repo lives **at the destination** — there is no separate "active" or "mirror" concept. The path to a repo on disk (or in s3) *is* the repo.
-   **Snapshots correlate 1:1 with checkpoint ids.** For every committed checkpoint, the host repo and each sandbox repo contain a snapshot tagged with the checkpoint's ordinal. The per-checkpoint sidecar (§1) is the authoritative mapping from checkpoint id to restic snapshot ids; restic tags are a debugging aid / fallback.
-   **Commit point = atomic sidecar write.** Each cycle: write all sandbox snapshots, write the host snapshot, then atomically write `ckpt-NNNNN.json` (single-object PUT on s3; write-temp-then-rename on local). A checkpoint is visible to resume only when its sidecar exists. Crashed cycles leave tagged-but-unreferenced restic snapshots — orphan garbage, recoverable but not visible.

### 4e. Injection

The restic binary must be injected into the sandbox image — it runs inside the sandbox to enumerate and snapshot the configured paths. Implemented by extending the existing sandbox-tools injection mechanism (`src/inspect_sandbox_tools/`) to also inject the linux-arch restic binary obtained via §4c at a root-only path inside the sandbox (see §4h for the privilege model; e.g., `/opt/restic`).

### 4f. Egress

**Sandbox repos** are populated indirectly. Restic running inside the sandbox writes new pack files into a transient in-sandbox **egress buffer** (no storage creds in the sandbox). After each snapshot, inspect ships the new pack files out via the standard sandbox exec/copy API and appends them to the sandbox repo at the destination (local filesystem or `s3://`). Works uniformly across destinations. Protocol sketch in Appendix B.

**Host repo** has no egress step. The host process holds storage creds and uses restic's native backend (local FS, S3, GCS, …) to write directly to the destination.

### 4g. Encryption

Restic mandates encryption. Inspect **auto-generates** a random password per eval at checkpoint-directory creation time and stores it in `manifest.json`. The same password is used for every repo (host + each sandbox) under that eval; §4h covers how the password reaches sandbox-side restic without being persisted in the sandbox. Encryption is effectively nominal — anyone with access to the checkpoint directory has the key — but operational burden on customers is zero. Customers requiring real at-rest encryption should place the checkpoint directory on an encrypted volume or bucket. A future user-provided-password mode can be added without breaking the auto-generate default.

### 4h. Sandbox privilege model

All checkpoint operations inside a sandbox run as **root**, and all sandbox-side state related to checkpointing lives in directories owned by and accessible only to root. A non-root user in the sandbox — including the agent, when it runs as a non-root user — sees no evidence of the restic binary, the egress buffer, or any in-flight checkpoint state.

-   **Restic binary** at `/opt/restic`, owned by root, mode `0700`. Non-root users cannot execute it or even stat it.
-   **Egress buffer** at a root-only path (e.g. `/var/lib/inspect/checkpoints/`, mode `0700`). Non-root users cannot list, read, or write inside it. The transient egress tarball produced by Appendix B's protocol lives in a sibling root-only staging path, not in `/tmp`.
-   **All sandbox `exec` calls** issued by inspect for checkpoint creation — `restic backup`, egress tarball construction, manifest updates, all subsequent egress steps — run as root via the sandbox provider's standard "run as user" mechanism on `exec`.
-   **The restic password is never persisted in the sandbox.** It is passed in via the environment of each `exec` call that invokes restic (`RESTIC_PASSWORD`) and lives only for the duration of that process. The file-based alternatives (`RESTIC_PASSWORD_FILE`, `RESTIC_PASSWORD_COMMAND` reading a stored secret) are deliberately not used.

Rationale: hiding the checkpoint mechanism from the agent prevents an adversarial or buggy agent from interfering with state capture, avoids any possibility of the agent reasoning about its own checkpoint state in unhelpful ways, and keeps the snapshot transparent to whatever the agent is doing.

## 5. Host snapshot contents

Each host-repo snapshot contains exactly two files, sourced from a host-local working tree at checkpoint time:

-   **`context.json`** — messages and events in the same **condensed representation** used inside a `.eval` log (avoids the O(N²) serialization cost). Carries events in condensed form (with `input_refs` / `call_refs`) and deduplication pools (`events_data` with `messages` and `calls`). Reuses `condense_sample()` / `resolve_sample_events_data()` from `src/inspect_ai/log/_pool.py` and `_condense.py`. Not a `.eval` file; no zip coupling.
-   **`store.json`** — the sample's `Store` key/value state.

Customer-facing checkpoint metadata (trigger, turn, duration, sandbox snapshot ids, etc.) lives in the per-checkpoint sidecar at the attempt root (§1), not inside the snapshot.

The host working tree is host-local and ephemeral (not at the destination). Restic needs a real local-filesystem source path even when the destination is on s3; the working tree is overwritten in place each cycle.

**Working-tree location.** Working trees live under
`inspect_cache_dir("checkpoints")/<log-basename>/<sample-id>__<epoch>[_<retry>]/`,
where `<log-basename>` is the eval log file name with its `.eval`
suffix stripped. The per-attempt subtree mirrors the per-attempt
subtree of the destination `<log>.eval.checkpoints/` directory — same
shape, different root — so a working tree and its destination repo
are trivially correlated. Caching under `inspect_cache_dir` keeps the
working tree writable in all install scenarios (matching the §4c
restic-binary cache rationale) and survives across `pip install`
cycles. The working tree is overwritten in place each cycle and
cleaned up on attempt completion.

```
$XDG_CACHE_HOME/inspect_ai/checkpoints/      # working-tree root
  <log-basename>/                            # one per eval log
    <sample-id>__<epoch>[_<retry>]/          # one per attempt;
                                             #   shape mirrors §1.
      context.json
      store.json
```

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

1.  Read the chosen `ckpt-NNNNN.json` sidecar → host snapshot id + per-sandbox snapshot ids.
2.  Restore each sandbox from its tagged snapshot in the sandbox repo.
3.  Restore the host snapshot to a local working dir; parse `context.json` and `store.json`.
4.  Rehydrate the context window (messages + events) into ambient inspect state.
5.  Rehydrate the `Store` into ambient inspect state.
6.  Invoke the agent with `resume=True`.

The **agent** does not re-open the checkpoint, does not re-materialize the sandbox, and does not re-parse stored state.

## 7. Resume signaling

Checkpointing exposes the resume signal in two places:

-   **The agent's `resume` parameter** — for the agent function specifically (§7a).
-   **`TaskState.resumed`** — for any code with access to `TaskState`: solvers, scorers, tool implementations, hooks (§7b).

### 7a. Agent parameter

Checkpointing adds a single optional parameter to the agent protocol:

``` python
resume: Literal[True] | None
```

On a resume, Inspect invokes the agent with `resume=True` for the first (and likely only) call after restoration. On a normal, non-resumed run, the parameter is `None` (or omitted).

**What `resume=True` guarantees:**

-   **Sandbox.** The configured paths have been restored. Agents continue to use them via the normal sandbox API.
-   **Messages.** The sample's message history has been restored into inspect's internal state and will be passed to this first call via the `AgentState`.
-   **Events.** The sample's event history has been restored into inspect's internal state. Events are inspect-internal bookkeeping that rolls into the final `.eval` log; they do not flow through the agent input.
-   **Store.** The sample's `Store` has been restored into the ambient context (`store_as`, etc.). Agents read from it normally.

**What the agent does with it:**

-   Skip one-shot setup that has already happened (system-prompt assembly, initial tool probing, sandbox scaffolding).
-   Optionally take a different first-turn path ("figure out where you left off and continue").
-   Avoid double-recording state that is already present in the rehydrated messages/events.

Handling `resume=True` is not strictly required — an agent that ignores the parameter will still run against the restored state. In practice, though, most agents will want to handle it, for the reasons listed above. The built-in React agent does.

### 7b. TaskState attribute

`TaskState` gains a boolean attribute exposing the same signal to non-agent code:

```python
class TaskState:
    ...
    resumed: bool  # True when this sample was restored from a checkpoint
```

The flag is `True` for the entire lifetime of a resumed sample, not just the first call. Solvers, scorers, tool implementations, and hooks can read it to skip one-shot setup or take resume-aware paths the same way the agent uses its `resume` parameter.

## 8. Lifecycle and observability

### 8a. CheckpointEvent

Each checkpoint attempt emits a structured `CheckpointEvent` into the normal event stream, carrying at minimum: `checkpoint_id`, `trigger` (time/turn/manual), outcome (success/failure), duration, on-disk size, and — on failure — the error. Events are part of the `.eval` log, so checkpoint history is preserved in the normal log. No dedicated checkpoint journal file in v1.

### 8b. TUI surface

The inspect TUI shows a small indicator while a checkpoint is running and the last-checkpoint timestamp.

### 8c. Checkpoint-attempt failures

A failed checkpoint attempt (disk full, sandbox exec error, restic error, etc.) is logged as a warning. **Failed attempts are not retried in the moment** — the next attempt fires on the next policy boundary. The policy cadence is itself the retry; there is no per-attempt retry count.

`max_consecutive_failures` (§2) controls when the *sample* should give up on checkpointing entirely:

-   **Omitted (default):** unlimited. The sample keeps running no matter how many checkpoints fail in a row.
-   **`N` (positive integer):** the sample tolerates up to N failed checkpoints in a row and fails on the (N+1)th.
-   **`0`:** any single failure is fatal — strict mode.

A successful checkpoint resets the count. A failed sample is then handled by inspect's normal sample-error machinery (`fail_on_error`, `retry_on_error`, etc.) — depending on those settings, the eval may continue with other samples, retry the sample, or stop outright.

Rationale for unlimited as the default: durability is a nicety, not a correctness requirement; failing a long-horizon sample over transient hiccups would be worse than the loss it's meant to prevent. The ceiling lets strict callers bound that tradeoff.

Known risk under the unlimited default: a customer not monitoring the event stream could believe they have recent checkpoints when they don't. The TUI indicator and event-stream visibility make this visible in practice; setting a finite tolerance gives a hard signal instead.

### 8d. Retention

-   **On successful eval completion (default):** delete the `foo.eval.checkpoints/` tree.
-   **Opt-in "retain forever":** a configuration option keeps the checkpoint directory after success. CLI/config surface TBD.
-   **During the eval:** all checkpoints are retained. We do not collapse, merge, or prune older checkpoints into the head. Rationale: preserves the option of resuming from an arbitrary non-head checkpoint (a future capability). Practically: no `restic forget` / `restic prune` on active repos.

### 8e. Pre-checkpoint hook

Inspect's `Hooks` API gains a new lifecycle method fired immediately before each checkpoint cycle begins:

```python
class Hooks:
    ...
    async def on_checkpoint_start(self, data: CheckpointStart) -> None:
        """Called immediately before a checkpoint is created. The `data`
        argument carries the trigger that fired this checkpoint."""
        ...
```

Subclass `Hooks`, decorate with `@hooks`, and override the method. Sits alongside the existing `on_run_start` / `on_task_start` / `on_sample_start` hooks; same registration and discovery mechanism.

Useful for flushing in-memory agent state to disk so it is captured by the snapshot, notifying external monitoring at checkpoint boundaries, or pausing background work that shouldn't be mid-flight when restic enumerates the working tree.

## 9. Open questions

-   **Retention granularity: eval-complete vs. sample-complete.** §8d says checkpoints are deleted "on successful eval completion." Open: should a sample's checkpoint subtree instead be deleted (or at least eligible for deletion) as soon as *that sample* completes successfully, rather than waiting for the whole eval to finish? Eval-complete is simpler and keeps everything available until the run is done; sample-complete reclaims space sooner and scales better for evals with many long-running samples. Interacts with retain-forever (which would presumably still hold things until eval end).
-   **Engine commitment.** Restic is strongly preferred but not formally committed. The case is stronger now that it's used on both halves (host repo + sandbox repos); alternatives (borg, kopia, rsync-based, custom) remain theoretically on the table.

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

-   **Mandatory encryption** (AES-256-CTR + Poly1305-AES, password-derived master key). Not optional, even for local non-sensitive repos. See §4g for password handling.
-   **Locking model.** At most one process can hold an exclusive lock on a repository. Drives the per-sandbox-repo decision in §4d.
-   Pack files are already a bundle (deduplication-aware). An outer tar around restic's output is likely redundant for size but may still help egress round-trip count when copying many pack files.

## Appendix B — Sandbox egress protocol (design sketch)

Concrete design for §4f, by which sandbox-side restic produces pack files inside the sandbox and inspect ships them into the sandbox repo at the destination. Written against Docker specifically (using `docker cp` as the copy-out primitive); generalizes to any sandbox provider by substituting inspect's standard sandbox exec/copy API for `docker cp`. Starting point for implementation, not yet end-to-end validated.

### Overview

Inside each sandbox, restic writes pack files into a transient **egress buffer** at a fixed path. After each snapshot, new pack files are egressed via `docker cp` and appended to the sandbox repo at the destination. The buffer is not a persistent repo from the design's perspective — it's a holding area for pack files awaiting shipment. The destination repo is the only restic repository that appears in the layout (§1).

### Key property: append-only writes

With normal `restic backup` operations inside the sandbox (no `prune`, `forget`, or `rebuild-index`), egressed content is append-only at the destination:

-   `data/` pack files — immutable, content-addressed.
-   `snapshots/` — immutable, content-addressed.
-   `index/` — new files added; occasional consolidation may delete superseded index files (harmless — destination accumulates a superset).
-   `config`, `keys/` — written at buffer init, never modified.
-   `locks/` — transient, excluded from egress.

Because filenames are content hashes, filename-level presence checks suffice to identify new files; no content comparison needed.

### Protocol

Each snapshot cycle:

1.  **Host → Container:** "Take snapshot, egress sequence N."
2.  **Container:** Runs `restic backup`, waits for lock release.
3.  **Container:** Diffs current buffer contents against an egress manifest (list of filenames previously egressed) to find new files.
4.  **Container:** Creates `egress-N.tar` in a root-only staging path (see §4h) containing new files in order: `data/` first, then `index/`, then `snapshots/`. Returns tarball path and file list.
5.  **Host:** `docker cp`s the tarball out, extracts into the destination's sandbox repo.
6.  **Host:** Verifies integrity (minimum: `restic -r <destination> snapshots` succeeds).
7.  **Host → Container:** "Commit N."
8.  **Container:** Updates manifest, deletes tarball.

### Design decisions

-   **Manifest-based diff, not mtime-based.** Container maintains a sorted list of already-egressed filenames. Robust to clock skew, container restarts, and partial failures.
-   **Two-phase commit on the manifest.** Container does not advance its manifest until the host confirms successful extraction. Prevents state divergence if egress fails between tar creation and host extraction.
-   **Ordered tar contents** (`data/` → `index/` → `snapshots/`). The destination is valid at every intermediate state. A crashed extraction leaves the destination missing the newest snapshot, never with a dangling snapshot referencing missing data.
-   **Tarball lives outside the buffer** (in a sibling root-only staging path; see §4h) to keep the buffer directory clean.
-   **No `prune` / `forget` inside the container.** These break the append-only property. Run them on the destination instead, accepting that the in-sandbox buffer grows monotonically until the container is torn down.

### Open question (scoped to this appendix)

Container lifecycle — if ephemeral across snapshots, the manifest must live in the buffer or be passed in by the host each cycle. If long-lived, it can be container-local state.