# Agent Checkpointing – Inspect

## Overview

Evaluations that run for hours (or even days) can take advantage of [checkpointing](https://en.wikipedia.org/wiki/Application_checkpointing) for resilience against unexpected termination (infrastructure failure, running out of memory, etc.). When enabled, Inspect’s checkpointing periodically persists the state of each sample so the evaluation can be resumed mid-sample from its most recent checkpoint.

Checkpointing works by saving three classes of data at a specified interval:

1.  The current state of the main agent (e.g. messages, compaction, etc.).
2.  Filesystem state within sandboxes (home + other configured directories).
3.  The store and event history of the sample.

Checkpointing does not save arbitrary in-memory process state, running tools, or other external side effects.

When Inspect retries a failed sample, checkpointed data is automatically restored and the sample continued from where it left off. Note that checkpointing needs explicit support in agent scaffolds. Built-in agents like [react()](./reference/inspect_ai.agent.html.md#react) and [deepagent()](./reference/inspect_ai.agent.html.md#deepagent) support checkpointing natively, see the section below on [Custom Agents](#custom-agents) for details on how to add checkpointing to your own agents.

## Configuration

To enable checkpointing for an evaluation, use the `--checkpoint` CLI option. For example:

``` bash
# checkpoint with default trigger (every 5 turns)
inspect eval arc.py --checkpoint

# shorthand triggers
inspect eval arc.py --checkpoint=turn:10
1inspect eval arc.py --checkpoint=time:15m

# pass a yaml or json config file
inspect eval arc.py --checkpoint=checkpoint.yaml
```

1  
Time-value suffixes are `s`, `m`, `h`, `d` (case-insensitive); a bare integer is seconds.

Or from Python:

``` python
from inspect_ai import eval
from inspect_ai.util import CheckpointConfig, TurnInterval

eval(
    "arc.py", model="openai/gpt-5",
    checkpoint=CheckpointConfig(
        trigger=TurnInterval(every=10)
    )
)
```

TODO: Task and sample level configuration

## Triggers

## Enabling Checkpointing

Checkpointing can be configured at any of three layers — **sample**, **task**, or **eval / CLI**. The layers are merged per-field at sample-run time, with precedence **eval \> sample \> task** (see [Configuration Layers](#configuration-layers)). When unset at every layer, checkpointing is disabled.

### Eval / CLI layer

Pass the `--checkpoint` CLI option or `checkpoint=...` to [eval()](./reference/inspect_ai.html.md#eval). The `--checkpoint` option supports several formats:

``` bash
# Enable with the default trigger (every 5 turns)
inspect eval arc.py --model openai/gpt-4o --checkpoint

# Shorthand triggers
inspect eval arc.py --model openai/gpt-4o --checkpoint=turn:10
inspect eval arc.py --model openai/gpt-4o --checkpoint=time:15m
inspect eval arc.py --model openai/gpt-4o --checkpoint=manual

# Pass a YAML or JSON config file
inspect eval arc.py --model openai/gpt-4o --checkpoint=checkpoint.yaml
```

Time-value suffixes are `s`, `m`, `h`, `d` (case-insensitive); a bare integer is seconds.

Or from Python:

``` python
from inspect_ai import eval
from inspect_ai.util import CheckpointConfig, TurnInterval

eval("arc.py", model="openai/gpt-4o", checkpoint=CheckpointConfig(
    trigger=TurnInterval(every=10),
))
```

### Task layer

A task can declare its own default checkpoint policy, which applies whenever the eval/CLI layer doesn’t override it:

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

An individual sample can specialize the task’s default — e.g. when one sample needs an extra directory captured that the rest of the task’s samples don’t. Sample-layer configs use `CheckpointSampleConfig`, which omits the eval-wide fields (`checkpoints_location`, `retention`) that a sample physically cannot influence:

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

Note that `sandbox_paths` is replaced whole-dict, not merged per-key — to add a path on top of the task’s default, redeclare the full list (see [Configuration Layers](#configuration-layers)).

## Triggers

A trigger decides *when* a checkpoint fires. All triggers fire at the next **turn boundary** after the trigger condition is reached — agents are never interrupted mid-turn, and in-flight tool calls are never paused to checkpoint.

| Trigger | Description |
|----|----|
| `TurnInterval(every=N)` | Fire every N agent turns. |
| `TimeInterval(every=timedelta(...))` | Fire after approximately N seconds/minutes of wall-clock time has elapsed since the last fire. Effective interval is `≥ N` because firing waits for the next turn boundary. |
| `TokenInterval(every=N)` | Fire each time the sample’s running total token usage crosses another N-token boundary. Sample total tokens are read from `sample_total_tokens()`. |
| `Manual()` | Never fires automatically. The agent (or another caller) requests a checkpoint with `await cp.checkpoint()`. |

Additional trigger types — including cost-based and budget-percentage triggers that fire at percentage milestones of a sample’s `token_limit` / `cost_limit` / `time_limit` / `working_limit` — are planned but not yet runtime-supported.

## Configuration

`CheckpointConfig` is the full configuration object. All fields default to `None` so that partial configs can be layered (see [Configuration Layers](#configuration-layers) below).

| Field | Description |
|----|----|
| `trigger` | The trigger that decides when to fire. Required (must be set at some layer). |
| `sandbox_paths` | Per-sandbox-name map of absolute paths inside the sandbox to capture. Empty/omitted = host-only checkpointing (no sandbox repos). See [Sandbox Paths](#sandbox-paths) below. |
| `checkpoints_location` | Override the parent directory under which the per-eval checkpoint dir lands. Defaults to a sibling of the eval log file. Any fsspec-resolvable path (`s3://`, `gs://`, local, …). Settable only at the task or eval layer. |
| `max_consecutive_failures` | If set, fail the sample after N consecutive failed checkpoint attempts. `None` (default) = unlimited tolerance; `0` = any single failure is fatal. |
| `retention` | `Retention(after_eval="delete" \| "retain")`. `"delete"` (default) removes the checkpoint directory on successful eval completion; `"retain"` keeps it. Settable only at the task or eval layer. |

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

When more than one of the sample / task / eval layers supplies a config, Inspect merges them **per-field** at sample-run time. Each layer’s fields default to `None`; the highest-priority layer with a non-`None` value wins per field. Precedence is **eval \> sample \> task** — sample beats task because the task defines an agent’s standard policy for *all* of its samples and an individual sample specializes it; eval/CLI is always highest because it’s the operator’s run-time override.

`sandbox_paths` is treated as a single whole-dict value, not key-wise merged. To add a path to one sandbox while inheriting others, the higher-priority layer must redeclare the full map.

If at least one layer supplies a config but no layer sets a `trigger`, merge raises a `ValueError`.

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

There is **no implicit default** — path selection is agent-specific:

- **Native Python agents** (e.g. the built-in React agent) typically declare an empty `sandbox_paths`. Their state lives in messages and [Store](./reference/inspect_ai.util.html.md#store), both already captured by Inspect’s host-side snapshot. No sandbox repo is created in this case.
- **Sandbox CLI agents** (Claude Code, Codex CLI, Gemini CLI, …) typically declare multiple paths: the agent’s home directory, the project working directory (often `/workspace`), and any tool-state directories.

If a sandbox name returned by `sample_init` does not appear in `sandbox_paths`, no sandbox repo is created for it. Anything outside the configured paths is not captured and will not be restored on resume.

## Checkpoint Flow

When checkpointing is enabled, each sample proceeds as follows:

1.  **Tick.** At each agent turn boundary, the agent calls `cp.tick()` (or the built-in agent does so on its behalf). The trigger decides whether this tick is a checkpoint moment.

2.  **Capture.** When the trigger fires, Inspect writes the host-side context files (messages, events, attachments, [Store](./reference/inspect_ai.util.html.md#store), and any agent-tracked state) and runs `restic backup` on the host repo and each configured sandbox path set in parallel.

3.  **Record.** Inspect writes a `ckpt-NNNNN.json` checkpoint file at the per-sample root. A checkpoint is available for resumption only once this file is in place.

4.  **Emit.** A structured `CheckpointEvent` is emitted into the normal event stream (and into the `.eval` log) carrying the trigger, turn, duration, snapshot ids, and size.

Crashed cycles that didn’t reach step 3 leave orphan snapshots with no checkpoint file; resume discards them automatically.

## Resuming

Resume uses Inspect’s existing retry pathway — no new command or flag:

``` bash
inspect eval retry <log-file>
```

Or from Python:

``` python
from inspect_ai import eval_retry

eval_retry("<log-file>")
```

This works for both `inspect eval retry` / [eval_retry()](./reference/inspect_ai.html.md#eval_retry) and eval-set retry. Inspect locates the checkpoint directory (sibling of the log file by default; the log records the canonical location if `checkpoints_location` was overridden), restores each sample’s most recent committed checkpoint, and continues. If a sample has no checkpoint, it starts over from the beginning; if it had completed, it is skipped.

On resume, the following is restored before the agent runs:

- **Sandbox.** The configured sandbox paths are restored into a fresh sandbox container.
- **Messages, events, store, attachments.** Inspect’s internal per-sample state is rehydrated. The rehydrated events appear under a synthesized `prior_run` span in the new `.eval` log.
- **Agent-tracked state.** Any values the agent registered with `cp.track(...)` (see below).

The agent can read `cp.attempt` to discover whether this is a fresh run, a resume, or a scoring-phase resume (see [Scoring-Phase Resume](#scoring-phase-resume) below).

### Scoring-Phase Resume

When the agent completes cleanly but a later phase crashes (typically scoring), retry can skip the agent entirely and re-run scoring against the agent’s final state. The mechanism is automatic:

1.  On clean agent exit, Inspect fires a final “agent_complete” checkpoint and marks `solver_done` on the per-sample `sample.json` manifest.
2.  If anything crashes after that (a scorer, the eval process), the next `inspect eval retry` reads the marker and tags the sample as `Attempt.RETRY_FOR_SCORING`.
3.  The agent enters its checkpointer session, restores tracked state (messages, output, …), reads `cp.attempt == Attempt.RETRY_FOR_SCORING`, and returns immediately — no model calls, no tool calls.
4.  Scoring runs against the restored state.

The built-in React agent handles this automatically. Custom agents that don’t add the `Attempt.RETRY_FOR_SCORING` branch will re-run their loop on retry (graceful degradation).

## Custom Agents

A custom agent participates in checkpointing by entering a `Checkpointer()` session and calling `tick()` at each turn boundary. The harness installs the resolved `CheckpointConfig` into an ambient context before the agent runs, so the agent does **not** receive or thread a config — `checkpointer()` is zero-argument.

The key affordance is **`cp.track`**, which gives the agent a single-call way to declare “this variable is important state — capture it at each checkpoint and restore it for me on retry.” On a fresh run, `track` returns the `initial_value` the agent passes in. On a retry of the same sample, `track` returns whatever the registered callback captured at the most recent checkpoint of the prior run — so the agent’s important state comes back automatically and the agent picks up where it left off, without any custom save/load code:

``` python
from inspect_ai.util import Attempt, checkpointer

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

        # Scoring-phase resume: agent already finished in the prior
        # attempt — tracked state is restored above, return so scoring
        # can re-run without redoing the loop.
        if cp.attempt == Attempt.RETRY_FOR_SCORING:
            return state

        # On a fresh start, perform one-shot setup. (On a mid-agent
        # retry the prior run already did this, so skip.)
        if cp.attempt == Attempt.INITIAL:
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
| `cp.attempt` | Enum: `Attempt.INITIAL` (fresh), `Attempt.RETRY` (mid-agent resume), or `Attempt.RETRY_FOR_SCORING` (agent completed in the prior attempt — restore tracked state and return). Stable for the lifetime of the session. |
| `await cp.tick()` | Turn-boundary signal; may fire a checkpoint depending on the trigger. |
| `await cp.checkpoint()` | Force a fire regardless of trigger (used by `Manual()`). |
| `cp.track(key, callback, initial_value, *, value_type=None)` | Declare a piece of agent state worth persisting. `callback` is invoked at every checkpoint fire to capture the current value; the method returns the value captured at the most recent prior checkpoint on a retry, or `initial_value` on a fresh run. Each `key` may be tracked only once per session. |

`cp.track` is generic over the value type. Single Pydantic models and JSON primitives are auto-handled; for other shapes (collections, generics, dataclasses, lists of models) pass `value_type=...`.

When no `CheckpointConfig` is installed (checkpointing disabled), the session is a no-op: `tick()` does nothing, `track()` always returns `initial_value`, `attempt` is `Attempt.INITIAL`.

## Details and Limitations

- **Turn-boundary granularity only.** A long-running tool call (e.g. a 10-minute subprocess) blocks the next checkpoint until the call returns. Mid-tool-call checkpointing is planned for a later phase.

- **Filesystem state only.** Anything outside `sandbox_paths` is not captured. In-memory process state inside the sandbox (running daemons, open sockets, RAM) is lost on resume. The agent is responsible for tolerating this.

- **External side-effects may re-execute.** If a tool call completed between the last checkpoint and a crash, Inspect cannot un-do its real-world side-effects. Idempotent tools are strongly recommended for checkpointed evals.

- **Works across all sandbox providers.** Checkpointing uses a single filesystem-based mechanism ([restic](https://restic.net) for content-addressed deduplicated snapshots) that works uniformly across Docker, Modal, Kubernetes, and any other sandbox provider — no provider-native snapshot machinery required.

- **Restic binary.** On first use, Inspect fetches a pinned restic binary from upstream and caches it. For offline / air-gapped environments, pre-warm the cache with `inspect download restic`.

- **Encryption.** Inspect auto-generates a random restic password per sample and stores it alongside the checkpoint repos. This is operational encryption only — anyone with read access to the checkpoint directory has the key. Place the checkpoint directory on an encrypted volume or bucket if at-rest encryption is required.

- **Failure tolerance.** A failed checkpoint attempt records an [InfoEvent](./reference/inspect_ai.event.html.md#infoevent) (`source="checkpoint"`) and logs a warning, but by default the sample keeps running — durability is treated as a nicety, not a correctness requirement. Set `max_consecutive_failures=N` to bound this, or `0` for strict mode.
