# Checkpointing

## Overview

Long-horizon evals can run for hours, days, or weeks. Without checkpointing, an eval that fails before completing loses all in-progress sample work. Inspect's checkpointing periodically persists the in-flight state of each sample so the eval can be resumed **mid-sample** from its most recent checkpoint via `inspect eval retry`.

Checkpointing is **cooperative with the agent**: Inspect cannot tell on its own whether a given agent's state will survive a restart, so the agent opts in to checkpointing by using Inspect's primitives. The built-in React agent cooperates unconditionally; custom agents add a few lines of boilerplate (see [Custom Agents](#custom-agents) below).

::: callout-important
Checkpointing snapshots **filesystem state** (configured paths inside each sandbox plus Inspect's per-sample message / event / store state). It does **not** snapshot in-memory process state, running tools, or external side-effects. Tool calls completed between the last checkpoint and a crash may re-execute on resume — tool authors are responsible for tolerating this (typically via idempotent tools).
:::

## Enabling Checkpointing

Checkpointing is **enabled** by a config at the **task** or **eval / CLI** layer. The **sample** layer is customize-only — it refines an already-enabled policy but never turns checkpointing on by itself, and is silently ignored when neither task nor eval enabled it. Once enabled, the layers are merged per-field at sample-run time, with precedence **eval > sample > task** (see [Configuration Layers](#configuration-layers)). When neither task nor eval supplies a config, checkpointing is disabled.

### Eval / CLI layer

Pass the `--checkpoint` CLI option or `checkpoint=...` to `eval()`. The `--checkpoint` option supports several formats:

``` bash
# Enable with the default trigger (every 500k tokens)
inspect eval arc.py --model openai/gpt-4o --checkpoint

# Shorthand triggers
inspect eval arc.py --model openai/gpt-4o --checkpoint=token:500k
inspect eval arc.py --model openai/gpt-4o --checkpoint=turn:10
inspect eval arc.py --model openai/gpt-4o --checkpoint=time:15m
inspect eval arc.py --model openai/gpt-4o --checkpoint=manual

# Pass a YAML or JSON config file
inspect eval arc.py --model openai/gpt-4o --checkpoint=checkpoint.yaml
```

Time-value suffixes are `s`, `m`, `h`, `d` and token-value suffixes are `k`, `m`, `b` (all case-insensitive). A suffix is **required** in both cases — a bare number is rejected. Token values may be fractional as long as they resolve to a whole token count (e.g. `token:1.5m`). The bare `--checkpoint` flag enables checkpointing without pinning a trigger; the concrete default (`token:500k`) is filled in per-sample only when no layer — including the sample — set one.

Or from Python:

``` python
from inspect_ai import eval
from inspect_ai.util import CheckpointConfig, TurnInterval

eval("arc.py", model="openai/gpt-4o", checkpoint=CheckpointConfig(
    trigger=TurnInterval(every=10),
))
```

Passing `checkpoint=True` is the Python-API equivalent of the bare `--checkpoint` flag — it enables checkpointing with the default trigger (every 500k tokens), deferring the trigger so a sample can still override it. `checkpoint=False` / `None` disable it. `True` is accepted anywhere a `CheckpointConfig` is (the `eval()` family, `eval_set()`, `Task`, and `task_with()`).

``` python
eval("arc.py", model="openai/gpt-4o", checkpoint=True)
```

### Task layer

A task can declare its own default checkpoint policy, which applies whenever the eval/CLI layer doesn't override it:

``` python
from inspect_ai import Task, task
from inspect_ai.util import CheckpointConfig, TimeInterval
from datetime import timedelta

@task
def my_task():
    return Task(
        dataset=...,
        solver=...,
        checkpoint=CheckpointConfig(
            trigger=TimeInterval(every=timedelta(minutes=15)),
            sandbox_paths={"default": ["/workspace"]},
        ),
    )
```

### Sample layer

An individual sample can specialize an already-enabled policy — e.g. when one sample needs an extra directory captured that the rest of the task's samples don't, or supplies its own trigger when the eval/CLI layer enabled checkpointing without pinning one. A sample config never enables checkpointing on its own; if neither task nor eval enabled it, the sample config is ignored. Sample-layer configs use `CheckpointSampleConfig`, which omits the eval-wide fields (`checkpoints_location`, `retention`) that a sample physically cannot influence:

``` python
from inspect_ai.dataset import Sample
from inspect_ai.util import CheckpointSampleConfig

Sample(
    input="...",
    target="...",
    checkpoint=CheckpointSampleConfig(
        sandbox_paths={
            "default": ["/root", "/workspace", "/var/lib/this-samples-state"],
        },
    ),
)
```

Note that `sandbox_paths` is replaced whole-dict, not merged per-key — to add a path on top of the task's default, redeclare the full list (see [Configuration Layers](#configuration-layers)).

## Triggers

A trigger decides *when* a checkpoint fires. All triggers fire at the next **turn boundary** after the trigger condition is reached — agents are never interrupted mid-turn, and in-flight tool calls are never paused to checkpoint.

| Trigger | Description |
|----|----|
| `TurnInterval(every=N)` | Fire every N agent turns. |
| `TimeInterval(every=timedelta(...))` | Fire after approximately N seconds/minutes of wall-clock time has elapsed since the last fire. Effective interval is `≥ N` because firing waits for the next turn boundary. |
| `TokenInterval(every=N)` | Fire each time the sample's running total token usage crosses another N-token boundary. Sample total tokens are read from `sample_total_tokens()`. |
| `Manual()` | Never fires automatically. The agent (or another caller) requests a checkpoint with `await cp.checkpoint()`. |

: {tbl-colwidths=\[35,65\]}

Additional trigger types — including cost-based and budget-percentage triggers that fire at percentage milestones of a sample's `token_limit` / `cost_limit` / `time_limit` / `working_limit` — are planned but not yet runtime-supported.

## Configuration

`CheckpointConfig` is the full configuration object. All fields default to `None` so that partial configs can be layered (see [Configuration Layers](#configuration-layers) below).

| Field | Description |
|----|----|
| `trigger` | The trigger that decides when to fire. When unset at every layer (while checkpointing is enabled by task/eval), defaults to `TokenInterval(every=500_000)`. |
| `sandbox_paths` | Per-sandbox-name map of absolute paths inside the sandbox to capture. Overrides the default for the named sandbox; any sandbox *not* named here falls back to capturing its default user's home directory. An empty list opts a sandbox out. See [Sandbox Paths](#sandbox-paths) below. |
| `checkpoints_location` | Override the parent directory under which the per-eval checkpoint dir lands. Defaults to a sibling of the eval log file. Any fsspec-resolvable path (`s3://`, `gs://`, local, …). Settable only at the task or eval layer. |
| `max_consecutive_failures` | If set, fail the sample after N consecutive failed checkpoint attempts. `None` (default) = unlimited tolerance; `0` = any single failure is fatal. |
| `retention` | `Retention(after_eval="delete" \| "retain")`. `"delete"` (default) removes the checkpoint directory on successful eval completion; `"retain"` keeps it. Settable only at the task or eval layer. |

: {tbl-colwidths=\[30,70\]}

A full Python example:

``` python
from datetime import timedelta
from inspect_ai.util import CheckpointConfig, Retention, TimeInterval

eval(
    "arc.py", model="openai/gpt-4o",
    checkpoint=CheckpointConfig(
        trigger=TimeInterval(every=timedelta(minutes=15)),
        sandbox_paths={"default": ["/root", "/workspace"]},
        checkpoints_location="s3://my-bucket/checkpoints",
        max_consecutive_failures=3,
        retention=Retention(after_eval="retain"),
    ),
)
```

The equivalent YAML for use with `--checkpoint=checkpoint.yaml`:

``` yaml
trigger:
  type: time
  every: 15m
sandbox_paths:
  default: ["/root", "/workspace"]
checkpoints_location: s3://my-bucket/checkpoints
max_consecutive_failures: 3
retention:
  after_eval: retain
```

### Configuration Layers

When more than one of the sample / task / eval layers supplies a config, Inspect merges them **per-field** at sample-run time. Each layer's fields default to `None`; the highest-priority layer with a non-`None` value wins per field. Precedence is **eval > sample > task** — sample beats task because the task defines an agent's standard policy for *all* of its samples and an individual sample specializes it; eval/CLI is always highest because it's the operator's run-time override.

`sandbox_paths` is treated as a single whole-dict value, not key-wise merged. To add a path to one sandbox while inheriting others, the higher-priority layer must redeclare the full map.

When checkpointing is enabled (task or eval) but no layer — including the sample — sets a `trigger`, the trigger defaults to `TokenInterval(every=500_000)` (every 500k tokens).

## Sandbox Paths

`sandbox_paths` is a map from sandbox name (the dict key returned by `sample_init`) to a list of absolute paths to capture inside that sandbox:

``` python
CheckpointConfig(
    trigger=TurnInterval(every=5),
    sandbox_paths={
        "default": ["/root", "/workspace"],
        "tools":   ["/opt/agent-state"],
    },
)
```

**Default:** every sandbox returned by `sample_init` automatically captures its **default user's home directory** — you only need `sandbox_paths` to override that default. Path selection is agent-specific:

-   **Sandbox CLI agents** (Claude Code, Codex CLI, Gemini CLI, …) keep their state under the agent's home directory, so the default captures them with no configuration. Override only to add other locations — e.g. a project working directory (`/workspace`) or a tool-state dir outside `$HOME`.
-   **Native Python agents** (e.g. the built-in React agent) keep their state in messages and `Store`, both already captured by Inspect's host-side snapshot. The home-directory backup is harmless but redundant; opt the sandbox out with an empty list (see below) to skip it.

An entry in `sandbox_paths` replaces the default for that sandbox — only the listed paths are captured. An **empty list** (`{"name": []}`) is an explicit opt-out: no sandbox repo is created for it. Anything outside the captured paths is not snapshotted and will not be restored on resume.

## Checkpoint Flow

When checkpointing is enabled, each sample proceeds as follows:

1.  **Tick.** At each agent turn boundary, the agent calls `cp.tick()` (or the built-in agent does so on its behalf). The trigger decides whether this tick is a checkpoint moment.

2.  **Capture.** When the trigger fires, Inspect writes the host-side context files (messages, events, attachments, `Store`, and any agent-tracked state) and runs `restic backup` on the host repo and each configured sandbox path set in parallel.

3.  **Record.** Inspect writes a `ckpt-NNNNN.json` checkpoint file at the per-sample root. A checkpoint is available for resumption only once this file is in place.

4.  **Emit.** A structured `CheckpointEvent` is emitted into the normal event stream (and into the `.eval` log) carrying the trigger, turn, duration, snapshot ids, and size.

Crashed cycles that didn't reach step 3 leave orphan snapshots with no checkpoint file; resume discards them automatically.

## Resuming

Resume uses Inspect's existing retry pathway — no new command or flag:

``` bash
inspect eval retry <log-file>
```

Or from Python:

``` python
from inspect_ai import eval_retry

eval_retry("<log-file>")
```

This works for both `inspect eval retry` / `eval_retry()` and eval-set retry. Inspect locates the checkpoint directory (sibling of the log file by default; the log records the canonical location if `checkpoints_location` was overridden), restores each sample's most recent committed checkpoint, and continues. If a sample has no checkpoint, it starts over from the beginning; if it had completed, it is skipped.

On resume, the following is restored before the agent runs:

-   **Sandbox.** The configured sandbox paths are restored into a fresh sandbox container.
-   **Messages, events, store, attachments.** Inspect's internal per-sample state is rehydrated. The rehydrated events appear under a synthesized `prior_run` span in the new `.eval` log.
-   **Agent-tracked state.** Any values the agent registered with `cp.track(...)` (see below).

The agent can read `cp.is_resuming` to discover that this is a resumed run and optionally skip one-shot setup that has already happened.

## Custom Agents

A custom agent participates in checkpointing by entering a `Checkpointer()` session and calling `tick()` at each turn boundary. The harness installs the resolved `CheckpointConfig` into an ambient context before the agent runs, so the agent does **not** receive or thread a config — `checkpointer()` is zero-argument.

The key affordance is **`cp.track`**, which gives the agent a single-call way to declare "this variable is important state — capture it at each checkpoint and restore it for me on retry." On a fresh run, `track` returns the `initial_value` the agent passes in. On a retry of the same sample, `track` returns whatever the registered callback captured at the most recent checkpoint of the prior run — so the agent's important state comes back automatically and the agent picks up where it left off, without any custom save/load code:

``` python
from inspect_ai.util import checkpointer

async def my_agent(state):
    async with checkpointer() as cp:
        # Each `track` call: register a callback that captures this
        # variable at every checkpoint fire, AND get back the value
        # captured at the most recent prior checkpoint (or the supplied
        # initial_value on a fresh run). One line, both directions.
        attempt_count = cp.track(
            "attempt_count",
            lambda: attempt_count,
            0,
        )
        state.messages = cp.track(
            "messages",
            lambda: state.messages,
            state.messages,
        )

        # On resume, skip one-shot setup that has already happened.
        if not cp.is_resuming:
            initialize_workspace(state)

        while not done(state):
            await cp.tick()  # may fire a checkpoint at this turn boundary
            state = await one_turn(state)

        # For Manual triggers the agent fires explicitly:
        # await cp.checkpoint()
```

The `Checkpointer` surface:

| Member | Description |
|----|----|
| `cp.is_resuming` | `True` iff this sample is being resumed from a prior checkpoint. Stable for the lifetime of the session. |
| `await cp.tick()` | Turn-boundary signal; may fire a checkpoint depending on the trigger. |
| `await cp.checkpoint()` | Force a fire regardless of trigger (used by `Manual()`). |
| `cp.track(key, callback, initial_value, *, value_type=None)` | Declare a piece of agent state worth persisting. `callback` is invoked at every checkpoint fire to capture the current value; the method returns the value captured at the most recent prior checkpoint on a retry, or `initial_value` on a fresh run. Each `key` may be tracked only once per session. |

`cp.track` is generic over the value type. Single Pydantic models and JSON primitives are auto-handled; for other shapes (collections, generics, dataclasses, lists of models) pass `value_type=...`.

When no `CheckpointConfig` is installed (checkpointing disabled), the session is a no-op: `tick()` does nothing, `track()` always returns `initial_value`, `is_resuming` is `False`.

## Details and Limitations

-   **Turn-boundary granularity only.** A long-running tool call (e.g. a 10-minute subprocess) blocks the next checkpoint until the call returns. Mid-tool-call checkpointing is planned for a later phase.

-   **Filesystem state only.** Anything outside `sandbox_paths` is not captured. In-memory process state inside the sandbox (running daemons, open sockets, RAM) is lost on resume. The agent is responsible for tolerating this.

-   **External side-effects may re-execute.** If a tool call completed between the last checkpoint and a crash, Inspect cannot un-do its real-world side-effects. Idempotent tools are strongly recommended for checkpointed evals.

-   **Works across all sandbox providers.** Checkpointing uses a single filesystem-based mechanism ([restic](https://restic.net) for content-addressed deduplicated snapshots) that works uniformly across Docker, Modal, Kubernetes, and any other sandbox provider — no provider-native snapshot machinery required.

-   **Restic binary.** On first use, Inspect fetches a pinned restic binary from upstream and caches it. For offline / air-gapped environments, pre-warm the cache with `inspect download restic`.

-   **Encryption.** Inspect auto-generates a random restic password per sample and stores it alongside the checkpoint repos. This is operational encryption only — anyone with read access to the checkpoint directory has the key. Place the checkpoint directory on an encrypted volume or bucket if at-rest encryption is required.

-   **Failure tolerance.** A failed checkpoint attempt records an `InfoEvent` (`source="checkpoint"`) and logs a warning, but by default the sample keeps running — durability is treated as a nicety, not a correctness requirement. Set `max_consecutive_failures=N` to bound this, or `0` for strict mode.
