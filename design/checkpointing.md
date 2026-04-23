# Inspect Checkpointing — Design for Review

> **Status:** Draft for customer feedback. We are sharing this with selected
> frontier and research-lab partners to validate (1) that we're solving the
> right problem, (2) that the proposed mechanism fits your operational
> reality, and (3) what we may be missing. Nothing below is final.

## TL;DR

We propose adding **checkpointing and resume** to Inspect so that long-
running evals — individual samples that may run for hours, days, or weeks —
can survive crashes, infrastructure blips, and operator cancellations
without losing all of their prior work.

- The inspect harness periodically checkpoints a sample's in-flight state:
  conversation history and events, the sample's `Store`, and a snapshot of
  each of the agent's sandboxes (home directory only).
- Checkpoints are stored in a sibling directory to the `.eval` log (default
  `foo.eval.checkpoints/`), overridable to `s3://` or any
  fsspec-supported URL.
- On failure, the customer re-runs the eval with
  `--resume <checkpoints-path>`.
  Inspect restores each incomplete sample from its latest checkpoint and
  the agent continues from where it left off.
- Checkpointing is **opt-in** and configured on the agent
  (`react(checkpoint=...)` for the built-in React agent). We will also
  expose the underlying primitives so teams writing their own agent loops
  can wire checkpointing into them.
- This is **Phase 1 of a broader long-horizon eval feature stream**; later
  phases will build on the same foundation (e.g., human-in-the-loop
  intervention during a running eval).

We'd especially like your input on the sections marked **Validation Asks**
at the end.

## Why we're doing this

Long-horizon agent evaluations are increasingly common. Today, if any part of
the run fails — a machine reboot, a network partition, a bug in a tool, an OOM —
the affected sample restarts from turn 1. When a single sample has been running
for a week, a transient failure in hour 160 throws away 160 hours of agent work.

Inspect already handles retries and partial `.eval` log writes cleanly
for *sample-level* failures in short evals. What's missing is **mid-sample
durability**: the ability to pick up an individual sample where it
left off, rather than re-running it from turn 1.

## What a customer sees

### Enabling checkpointing

For the built-in React agent:

```python
from inspect_ai.agent import react
from inspect_ai import checkpoint_time, checkpoint_turns

agent = react(
    tools=[...],
    checkpoint=checkpoint_time(minutes=30),  # or checkpoint_turns(n=5)
)
```

Supported policies:

- **Time-based** — approximately every N minutes. Checkpoints are
  always taken at turn boundaries, never mid-turn; a time-based
  policy fires at the next turn boundary after N minutes have
  elapsed since the last checkpoint.
- **Turn-based** — every N agent turns.
- **Manual** — the agent decides when to checkpoint, by calling
  `await checkpoint()` from its own code. (Not a model-callable tool —
  this is a programmatic hook for agent authors.) Manual triggers
  still run at turn boundaries.
- **Off** — checkpointing disabled; current behavior.

Regardless of policy, checkpoints are taken **between turns**. An
agent is never interrupted mid-turn (and in particular, in-flight
tool calls are never paused to take a checkpoint).

If you write your own agent loop, you call the same primitives the React
agent uses. We'll document this path alongside the React agent
integration.

### Running an eval

Unchanged. `inspect eval my_task.py --model openai/gpt-...` runs as
today and produces the usual `.eval` log. Checkpoints accumulate in a
sibling directory:

```
logs/
  2026-04-22T14-30-45_my-task_abc123.eval
  2026-04-22T14-30-45_my-task_abc123.eval.checkpoints/
    ...
```

The checkpoint directory location is overridable (for example, to an
`s3://` bucket shared by your team's runs).

### Observing checkpoints

Each checkpoint attempt emits a structured `CheckpointEvent` into the
same event stream as all other inspect events, so it appears in the log
and in any downstream tooling you have built on inspect events. The
inspect TUI shows a small indicator while a checkpoint is running and
when the last successful checkpoint happened.

If a checkpoint attempt fails (disk full, sandbox exec error, S3 hiccup),
inspect **logs a warning and continues the eval**. A failed checkpoint
is not a failed eval — it just means durability was not advanced for
that attempt. The next policy fire will try again.

### Resuming after a crash

After a crash or cancellation, the customer resumes with:

```
inspect eval --resume logs/2026-04-22T14-30-45_my-task_abc123.eval.checkpoints/
```

The `--resume` argument is the **only** input needed. All eval
parameters — task, model, dataset, config — are read from the
checkpoint manifest. Passing additional flags (task path, `--model`,
etc.) alongside `--resume` is an error in v1.

For each sample that had not completed:

1. Inspect restores the sandbox from the latest checkpoint.
2. Inspect rehydrates the conversation history and events.
3. Inspect rehydrates the sample's `Store`.
4. The agent is invoked with the restored state and a new `resume`
   signal (see below).

Samples that had already completed successfully are not re-run. A resume
from a mid-sample crash lands the agent back at (approximately) the last
checkpoint it had written, with its full conversation, events, and
sandbox state intact.

#### The `resume` parameter on the agent protocol

Because many customers write their own agents or extend the built-in
React agent, the contract the agent sees on resume is worth calling
out explicitly.

We plan to add an **optional `resume: Literal[True] | None`** parameter
to the agent protocol. On a resume, Inspect invokes the agent with
`resume=True` for the first (and likely only) call after restoration.
On a normal, non-resumed run, the parameter is `None` (or omitted) and
agents that don't care can ignore it entirely.

What `resume=True` *guarantees to the agent*:

- The sandbox home directory has been restored from the latest
  checkpoint.
- Messages and events have been rehydrated into the ambient inspect
  state.
- The sample's `Store` has been rehydrated.

What the agent uses it for:

- Skip one-shot setup that already happened (system prompt assembly,
  initial tool probing, sandbox scaffolding, etc.).
- Optionally take a different first-turn path (e.g., "figure out where
  you left off and continue").
- Avoid double-recording state that is already present in the
  rehydrated messages/events.

Agents that do not implement `resume` awareness will still work —
they just won't take any resume-specific behavior and will re-run
their normal entry flow against the restored state. For most agents
this is acceptable; for the built-in React agent, `resume=True`
handling is part of the implementation.

### Retention

- **Default:** if the eval completes successfully, the checkpoint
  directory is deleted.
- **Opt-in "retain forever":** a configuration option keeps the
  checkpoint directory after success. We expect research and audit use
  cases where customers want to examine or replay an eval's trajectory
  even after it ran successfully.
- **During the eval:** all checkpoints are retained. We do not collapse
  or prune older checkpoints into the latest one. This preserves the
  option of resuming from an *arbitrary* past checkpoint — a capability
  we intend to expose in a later phase.

## How it works (at a glance)

You don't need to know this to use the feature. Included here for
technical reviewers.

### The four things we checkpoint

Each checkpoint contains:

1. **Sample metadata** — identifying information, checkpoint sequence,
   what triggered it, timestamps.
2. **Conversation + events** — the messages and structured events that
   have accumulated in the sample's trajectory so far, stored using the
   same schemas Inspect already uses inside `.eval` logs.
3. **Sandbox home-directory state** — a filesystem snapshot of
   `$HOME` inside each of the sample's sandboxes. (Samples may have
   one or many sandboxes; the mechanism applies independently to each.
   For brevity, the rest of this document uses *the sandbox* in the
   singular.)
4. **Store** — the sample's `Store` key/value state.

We intentionally do **not** checkpoint in-memory process state
(running processes, open sockets, RAM). See non-goals below.

### Sandbox snapshots

Sandbox state is checkpointed using a backup tool
([restic](https://restic.net), currently) injected into the sandbox
image. Restic is:

- A single static Go binary — clean to inject into arbitrary sandbox
  images.
- Content-addressed and deduplicating, so each additional checkpoint
  only stores the files that have changed since the prior checkpoint.
- Compatible with local-filesystem and S3 backends, plus several
  others.

Each sandbox gets its own restic repository inside the checkpoint
directory. When a checkpoint fires, inspect triggers a `restic backup`
inside the sandbox, then copies the resulting repository data out of the
sandbox to the configured checkpoint destination (host filesystem or
S3). **No storage credentials are ever plumbed into the sandbox.** The
copy-out step is performed by inspect using the standard sandbox
exec/copy API.

### Sandbox scope

Checkpoints include the contents of `$HOME` (typically `/root` in
Inspect's default sandbox user). This is the scope we see agents using
in practice today.

Anything an agent writes outside `$HOME` — `/tmp`, `/workspace`,
`/opt/<custom>`, system-level configuration changes — is **not
checkpointed** and will not be restored on resume. If your agents rely on
state outside `$HOME`, this is something we want to hear about (see
Validation Asks).

### Provider-agnostic

Because we use a filesystem-level backup tool injected into the
sandbox, checkpointing works the same way across **all** Inspect
sandbox providers: Docker, local, Kubernetes, Modal, and any future
provider. We explicitly chose not to use provider-specific snapshot
mechanisms (Modal memory snapshots, Docker commit, VM image snapshots)
so that a single, well-understood mechanism covers every deployment.

### Resume semantics

Resume is keyed on an **explicit pointer** — the path passed to
`--resume`. Inspect does not attempt to auto-detect that "this is the
same eval as last time"; each `inspect eval` invocation still produces
a new, independent log file unless you resume explicitly. This keeps
the resume contract simple and predictable, and avoids surprising
side-effects on unrelated re-runs. More ergonomic discovery flows can
be layered on later without breaking this.

## Scope and non-goals

### In scope for Phase 1

- Durability against crashes, OOMs, reboots, infrastructure blips,
  and operator cancellations during long-running samples.
- Mid-sample resume — an agent picks up where the most recent
  checkpoint left off.
- Resume across all supported sandbox providers.
- Local and S3 destinations for checkpoint data.
- Time-based, turn-based, and agent manually triggered checkpoint policies.
- Built-in integration with the React agent. Building-block primitives
  exposed for custom agent loops.

### Explicit non-goals

These are deliberate. We would like your confirmation that they are the
right tradeoffs for your use cases.

1. **No in-memory state checkpointing.** We checkpoint the sandbox filesystem,
   not running processes, open sockets, or RAM. Agents that rely on
   long-lived in-memory state inside the sandbox (rather than
   persisting it to disk) will not restore that state on resume.
2. **No provider-specific checkpointing.** We use a single
   filesystem-based mechanism across all sandbox providers. We will
   not, in Phase 1, use Modal memory snapshots, Docker commit, or
   analogous provider-native mechanisms, even if they would be faster
   for a specific provider.
3. **No tracking or replay of external side-effects.** If an agent
   made an external API call (posted to Slack, charged a card, wrote
   to an external database) between the last checkpoint and the
   crash, on resume that side-effect may be re-executed,
   double-executed, or appear inconsistent with the restored state.
   *Reality doesn't have a fork command.* Tool authors are responsible
   for tolerating this — typically via idempotent tools.
4. **No hermetic bundling of task/agent/tool source code.** The
   checkpoint does not carry your Python code, your dependency tree,
   or the Inspect runtime. Resume assumes you are running from the
   same code and environment (or a compatible one); the manifest
   records identity and version information so mismatches can be
   detected.
5. **No special handling of the first-checkpoint loss window.** If
   your policy is "every 30 minutes" and you crash 28 minutes in, you
   lose those 28 minutes of progress since sample start. This is
   consistent with the loss-window contract the policy already
   expresses; we don't take an extra zero-point snapshot to try to
   narrow it.

## Known limitations and gotchas

Things we want you to be aware of that follow from the design:

- **External-system side-effects.** As above. Tools that post to
  external systems, charge money, create irreversible artifacts, etc.,
  will not be "unwound" by resume. Make them idempotent or
  resume-aware.
- **Silent checkpoint failures in theory.** Checkpoint attempt failures
  are non-fatal by design (we don't want a full-disk condition to kill
  a week-long eval). A customer not monitoring the event stream could
  believe they have recent checkpoints when they don't. The TUI
  indicator and event-stream visibility should make this visible in
  practice.
- **Checkpoint size and egress cost.** Each checkpoint incurs a
  restic-backup invocation inside the sandbox plus a copy-out of the
  changed-data delta. For sandboxes with very large home directories
  or frequent large file changes, this can dominate. Restic's
  deduplication helps substantially.
- **Sandbox home-dir scope.** Per above — `$HOME` only.
- **Encryption is nominal.** Restic requires encryption; we
  auto-generate and store the password next to the repository. Anyone
  with access to the checkpoint directory has effective access to its
  contents. If you need real at-rest encryption, place the checkpoint
  directory on an encrypted volume or an encrypted S3 bucket.

## Validation asks

These are the specific things we'd most like your input on.

### 1. Does the problem framing match your pain?

- Are long-horizon sample failures the right thing to be solving?
- What sample durations are you actually running? (We are designing
  for hours-to-weeks per sample. If your envelope is materially
  different, we want to know.)
- Is mid-sample resume the right primitive, or do you need something
  different (e.g., branching, checkpoint-and-fork for exploration)?

### 2. Does the approach fit your operational reality?

- Can you accept a backup tool (restic) being injected into your
  sandbox images? Any organizational, licensing, or security
  constraints there?
- Does your storage backend fit (local FS or S3, via fsspec)? Are
  there other backends (GCS, Azure, internal artifact stores) we need
  to prioritize?

### 3. Sandbox scope — is `$HOME` sufficient?

This is the single design choice most likely to not match a given
team's setup. We'd like to confirm:

- Do your agents write meaningful state *outside* `$HOME` (e.g., to
  `/tmp`, `/workspace`, `/opt/<project>`, or the root filesystem)? If
  so, where, and would you expect us to checkpoint it?
- Are there files under `$HOME` you would explicitly want *excluded*
  from checkpoints (large caches, credentials)?

### 4. Confirm the non-goals

Please specifically confirm that the explicit non-goals in the
*Scope and non-goals* section above are acceptable for your use cases:

- In-memory process state **out** of scope.
- Provider-native snapshot mechanisms **out** of scope for Phase 1.
- External side-effect tracking/replay **out** of scope; tool
  idempotency is on you.
- Hermetic code bundling **out** of scope; resume assumes a compatible
  code/env.
- First-checkpoint loss window bounded only by your policy interval.

If any of these are dealbreakers, we want to know before we build.

### 5. Nominal encryption — can this work for you?

Restic mandates encryption. Our plan is to **auto-generate** a random
password per repository and store it next to the repo (in the
manifest). That gives the checkpoint dir zero operational burden —
customers don't manage keys — but means encryption is effectively
nominal: anyone with access to the checkpoint dir has effective access
to its contents. Customers needing real at-rest encryption are
expected to place the checkpoint dir on an encrypted volume or bucket.

**Can this work for you? How would you change it?**

Alternative we've considered:

- **Customer-supplied password** via env var / secrets manager.
  Tradeoff: real encryption, but losing the password loses the
  checkpoint entirely, and you now have a secret to manage per-eval.

### 6. Mid-tool-call checkpointing — needed?

Our plan is to take checkpoints **only at turn boundaries**. An agent
that is inside a long-running tool call (a 30-minute training step, an
hour-long data download, a multi-hour subprocess) will not be
interrupted to checkpoint; the next checkpoint waits for the tool call
to return. Our instinct is that this is the right tradeoff — mid-tool
snapshotting is substantially more complex (quiescing sandbox writes,
reasoning about partial filesystem state, resuming an in-flight tool)
and the common case is tolerated by idempotent/resumable tools.

We'd like to validate this:

- Do your agents routinely make tool calls long enough that this
  limitation would matter? What durations?
- If yes, what does an acceptable story look like — mid-tool
  checkpointing, tool-level resumability as a customer responsibility,
  or something else?

### 7. What are we missing?

Open-ended: what constraints, use cases, or failure modes are not
represented in this design? We're especially interested in hearing
about operational environments (air-gapped deployments, regulated
workloads, unusual sandbox providers) that might stress the proposed
approach in ways we haven't anticipated.

## Status and next steps

This is a design draft. Implementation has not begun. Based on your
feedback we will:

1. Revise the design where gaps or mismatches are identified.
2. Publish a concrete implementation plan and target timeline.
3. Begin phased implementation, starting with the mechanism (restic
   injection, sandbox snapshot/restore, harness orchestration) and
   layering in React-agent integration and CLI resume.

Please direct feedback to [TODO: contact / channel / issue tracker].
