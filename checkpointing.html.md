# Agent Checkpointing – Inspect

> **NOTE:**
>
> The agent checkpointing feature described below requires the development version of Inspect. You can install the development version from GitHub with:
>
> ``` bash
> pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
> ```

## Overview

Evaluations that run for hours (or even days) can take advantage of [checkpointing](https://en.wikipedia.org/wiki/Application_checkpointing) for resilience against unexpected termination (infrastructure failure, running out of memory, etc.). When enabled, Inspect’s checkpointing periodically persists the state of each sample so the evaluation can be resumed mid-sample from its most recent checkpoint.

Checkpointing works by saving three classes of data at a specified interval:

1.  The current state of the main agent (e.g. messages, compaction, etc.).
2.  Filesystem state within sandboxes (home + other configured directories).
3.  The store and event history of the sample.

Checkpointing does not save arbitrary in-memory process state, running tools, or other external side effects.

When Inspect retries a failed sample, checkpointed data is automatically restored and the sample continued from where it left off. Note that checkpointing needs explicit support in agent scaffolds. Built-in agents like [react()](./reference/inspect_ai.agent.html.md#react) and [deepagent()](./reference/inspect_ai.agent.html.md#deepagent) support checkpointing natively, see the section below on [Custom Agents](#custom-agents) for details on how to add checkpointing to your own agents.

## Basic Usage

To enable checkpointing for an evaluation, use the `--checkpoint` CLI option. For example:

``` bash
# checkpoint using default trigger (500K tokens)
inspect eval ctf.py --checkpoint

# checkpoint using explicit triggers
inspect eval ctf.py --checkpoint=turn:3
1inspect eval ctf.py --checkpoint=time:15m
2inspect eval ctf.py --checkpoint=token:100K

# pass a yaml or json config file
inspect eval ctf.py --checkpoint=checkpoint.yaml
```

1  
Time-value suffixes are `s`, `m`, `h`, `d`

2  
Token-value suffixes are `K`, `M`, and `B`

Or from Python:

``` python
from inspect_ai import eval
from inspect_ai.util import CheckpointConfig, TurnInterval

# checkpoint using default trigger (500K tokens)
eval("ctf.py", model="openai/gpt-5", checkpoint=True)

# checkpoint every 3 turns
eval(
    "ctf.py", model="openai/gpt-5",
    checkpoint=CheckpointConfig(
        trigger=TurnInterval(every=3)
    )
)
```

> **IMPORTANT: ImportantAgent Compatibility**
>
> Note that the above example assumes that you are using a checkpointing-aware agent (e.g. the built-in [react()](./reference/inspect_ai.agent.html.md#react) and [deepagent()](./reference/inspect_ai.agent.html.md#deepagent)). You can add checkpointing to your own agents by following the recipe described in [Custom Agents](#custom-agents).

### Recovery

If a crash occurs during an evaluation that was configured for checkpointing, recovery occurs when the sample is retried. For both [eval_set()](./reference/inspect_ai.html.md#eval_set) and [eval_retry()](./reference/inspect_ai.html.md#eval_retry) this occurs automatically:

``` bash
inspect eval-set arc.py ctf.py --checkpoint # CRASH!
inspect eval-set arc.py ctf.py --checkpoint # recover

inspect eval arc.py --checkpoint             # CRASH!
inspect eval-retry logs/<log-file-name>.eval # recover
```

For incomplete samples, Inspect locates the checkpoint directory, restores each sample’s most recent committed checkpoint, and continues. The following is restored before the agent runs:

1.  Agent State: Any state values the agent registered (e.g. message or compaction history).
2.  Sandbox: The sandbox setup script is run and the configured sandbox paths are restored from backup into a fresh sandbox container.
3.  Events and Store: Inspect’s internal per-sample state is rehydrated (the events appear under a synthesized `prior_run` span in the new `.eval` log).

By default checkpoints are deleted once the eval completes successfully; use `retention="retain"` in the [CheckpointConfig](./reference/inspect_ai.util.html.md#checkpointconfig) to preserve them.

### Triggers

Checkpoints are recorded according to the configured `trigger`. All triggers fire at the next turn boundary after the trigger condition is reached. Agents are never interrupted mid-turn, and in-flight tool calls are never paused to checkpoint.

For example, here we configure an eval to checkpoint every 1M tokens:

``` python
from inspect_ai import eval
from inspect_ai.util import CheckpointConfig, TokenInterval

eval(
    "arc.py", model="openai/gpt-5",
    checkpoint=CheckpointConfig(
        trigger=TokenInterval(every=1_000_000)
    )
)
```

You can configure triggers based on turns, time, or tokens, or can alternatively specify manual only checkpointing (applicable for [Custom Agents](#custom-agents)):

| Trigger | Description |
|----|----|
| [TurnInterval](./reference/inspect_ai.util.html.md#turninterval) | Fire every N agent turns. |
| [TimeInterval](./reference/inspect_ai.util.html.md#timeinterval) | Fire after approximately N seconds/minutes of time has elapsed since the last checkpoint. |
| [TokenInterval](./reference/inspect_ai.util.html.md#tokeninterval) | Fire each time the sample’s running total token usage crosses another N-token boundary. Sample total tokens are read from `sample_total_tokens()`. |
| [Manual](./reference/inspect_ai.util.html.md#manual) | Never fires automatically. The agent (or another caller) requests a checkpoint with `await cp.checkpoint()`. |

Note that time and token intervals effectively checkpoint at `≥ N` because firing waits for the next turn boundary.

## Configuration

[CheckpointConfig](./reference/inspect_ai.util.html.md#checkpointconfig) is the full configuration object passed to the Python API (it can equivalently be passed as YAML to the CLI). All fields default to `None` so that partial configurations can be layered (see [Configuration Layers](#configuration-layers) below).

| Field | Description |
|----|----|
| `trigger` | The trigger that decides when to fire (defaults to 500K tokens). |
| `sandbox_paths` | Per-sandbox-name map of absolute paths inside the sandbox to capture. Defaults to sandbox user’s home directory. |
| `checkpoints_location` | Override the parent directory under which the per-eval checkpoint directory lands (defaults to a sibling of the eval log file). |
| `max_consecutive_failures` | If set, fail the sample after N consecutive failed checkpoint attempts. Defaults to `None` (unlimited tolerance). Specify `0` to make any single failure fatal. |
| `retention` | `"delete"` or `"retain"`. `"delete"` (default) removes the checkpoint directory on successful eval completion; `"retain"` keeps it. |

A full Python example: {.caption-top .table}

``` python
from datetime import timedelta
from inspect_ai.util import CheckpointConfig, TimeInterval

eval(
    "arc.py", model="openai/gpt-4o",
    checkpoint=CheckpointConfig(
        trigger=TimeInterval(every=timedelta(minutes=15)),
        max_consecutive_failures=3,
        retention="retain",
    ),
)
```

The equivalent YAML for use with `--checkpoint=checkpoint.yaml`:

``` yaml
trigger:
  type: time
  every: 15m
max_consecutive_failures: 3
retention: retain
```

### Task Configuration

Tasks can directly specify and enable checkpointing in the same manner that evals do (this lets you run a set of evals some of which have checkpointing and some of which don’t). For example:

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

Note that when `sandbox_paths` are specified by a [Task](./reference/inspect_ai.html.md#task) or [Sample](./reference/inspect_ai.dataset.html.md#sample) they completely override the default (which is the sandbox home directory) so you should be sure to include the home directory along with any custom paths.

### Sample Configuration

Samples can also specify checkpointing configuration, however they cannot enable checkpointing independently (this needs to be done at the task or eval level). For example:

``` python
from inspect_ai import eval
from inspect_ai.dataset import Sample
from inspect_ai.util import CheckpointSampleConfig

# specify config at the sample level
Sample(
    input="...",
    target="...",
    checkpoint=CheckpointSampleConfig(
        sandbox_paths={
            "default": ["/root", "/workspace", "/var/state"],
        },
    ),
)

# enable at the eval or task level (uses the sample config)
eval("ctf.py", model="openai/gpt-5", checkpoint=True)
```

### Configuration Layers

When more than one of the sample / task / eval layers supplies a configuration, Inspect merges them **per-field** at sample-run time. Each layer’s fields default to `None`; the highest-priority layer with a non-`None` value wins per field. Precedence is **eval \> sample \> task**. Sample beats task because the task defines an agent’s standard policy for *all* of its samples and an individual sample specializes it. Eval/CLI is always highest because it’s the operator’s run-time override.

### Sandbox Paths

`sandbox_paths` is a map of container name to paths that should be captured for that container. Sandboxes that use only a single container can use the `"default"` key to refer to that container. Note that `sandbox_paths` is treated as a single whole-dict value, not key-wise merged. To add a path to one sandbox while inheriting others, the higher-priority layer must redeclare the full map. Also, while sandbox home directories are included by default, if you specify `sandbox_paths` explicitly you must explicitly include the home directory if you want it checkpointed. An explicit empty list (e.g. `sandbox_paths={"tools": []}`) opts that sandbox out of checkpointing entirely.

Cache directories are never backed up: any `.cache` directory at any depth (`**/.cache`, including the user’s XDG cache dir) is always excluded from sandbox backups — even when you specify `sandbox_paths` explicitly. Agents should not keep state they need across a resume under a `.cache` directory.

## Checkpoint Flow

When checkpointing is enabled, each sample proceeds as follows:

1.  **Tick**: At each agent turn boundary, the agent calls `cp.tick()`. The trigger decides whether this tick is a checkpoint moment.

2.  **Capture**: When the trigger fires, Inspect writes the host-side context files (agent-tracked state, events, and store) and runs a [restic backup](https://restic.net) on the agent scaffold host and each configured sandbox path.

3.  **Record**: Inspect writes a `ckpt-NNNNN.json` checkpoint file at the per-sample root. A checkpoint is available for resumption only once this file is in place.

4.  **Emit**: A structured `CheckpointEvent` is emitted into the normal event stream (and into the `.eval` log) carrying the trigger, turn, duration, snapshot ids, and size.

Crashed cycles that didn’t reach step 3 leave orphan snapshots with no checkpoint file; resume discards them automatically.

## Custom Agents

A custom agent participates in checkpointing by entering a [checkpointer()](./reference/inspect_ai.util.html.md#checkpointer) context and calling `tick()` at each turn boundary.

The key checkpointing mechanism for agents is the `cp.track` method, which gives the agent a way to declare “this variable is important state, capture it at each checkpoint and restore it for me on retry.”

On a fresh run, `track` returns the `initial_value` the agent passes in. On a retry of the same sample, `track` returns whatever the registered callback captured at the most recent checkpoint of the prior run, so the agent’s important state comes back automatically and can pick up where it left off.

``` python
from inspect_ai.util import checkpointer

async def my_agent(state):
    async with checkpointer() as cp:
        # each `track` call: register a callback that
        # captures this variable at every checkpoint
        # fire, AND get back the value captured at the
        # most recent prior checkpoint (or the initial
        # value on a fresh run).
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

        # scoring-phase resume: agent already finished in
        # the prior attempt — tracked state is restored
        # above, return so scoring can re-run.
        if cp.attempt == "resume_for_scoring":
            return state

        # agent loop
        while True:
            # fire checkpoint as per trigger 
            await cp.tick()  
            ...

        # for manual triggers the agent fires explicitly:
        # await cp.checkpoint()
```

The [Checkpointer](./reference/inspect_ai.util.html.md#checkpointer) context has the following members:

| Member | Description |
|----|----|
| `await cp.tick()` | Turn-boundary signal; may fire a checkpoint depending on the trigger. |
| `await cp.checkpoint()` | Force a checkpoint regardless of trigger. |
| `cp.track(key, callback, initial_value, *, value_type=None)` | Declare a piece of persisted agent state. `callback` is invoked at every checkpoint fire to capture the current value; the method returns the value captured at the most recent prior checkpoint on a retry, or `initial_value` on a fresh run. |
| `cp.attempt` | `"initial"` (fresh), `"resume"` (mid-agent resume), or `"resume_for_scoring"` (agent completed in the prior attempt — restore tracked state and return). |

`cp.track()` is generic over the value type. Pydantic models and JSON primitive values are handled automatically; for other shapes (collections, generics, dataclasses, lists of models) pass `value_type=...`.

### Reaching the session from a sub-component

[checkpointer()](./reference/inspect_ai.util.html.md#checkpointer) opens a session and is entered once, by the agent that owns the loop. A sub-component that does *not* own the session — a custom `model` agent passed to [react()](./reference/inspect_ai.agent.html.md#react), a tool, or a nested helper — should not re-enter [checkpointer()](./reference/inspect_ai.util.html.md#checkpointer) (that would open a duplicate transcript span). Use `current_checkpointer()` instead, a plain accessor for the session the agent has already opened:

``` python
from inspect_ai.util import current_checkpointer

cp = current_checkpointer()
if cp is not None:
    # register the sub-component's state on the agent's session
    state = cp.track("my_state", lambda: state, state)
```

It returns `None` when called outside an active sample, or before the owning agent has opened its session.

## Limitations

Checkpointing enables restoration of the most important agent context after a crash, but has some limitations you should bear in mind when using it:

- Turn-boundary granularity only — A long-running tool call (e.g. a 10-minute subprocess) blocks the next checkpoint until the call returns.

- Filesystem state only — Anything outside `sandbox_paths` is not captured. In-memory process state inside the sandbox (running daemons, open sockets, RAM) is lost on resume. The agent is responsible for tolerating this.

- Failure tolerance — A failed checkpoint attempt records an [InfoEvent](./reference/inspect_ai.event.html.md#infoevent) (`source="checkpoint"`) and logs a warning, but by default the sample keeps running. (durability is treated as a nicety, not a correctness requirement). Set `max_consecutive_failures=N` to bound this, or `0` for strict mode.

- Restic binary — On first use, Inspect fetches a pinned [restic](https://restic.net) binary and caches it. For offline / air-gapped environments, pre-warm the cache with `inspect download restic`.
