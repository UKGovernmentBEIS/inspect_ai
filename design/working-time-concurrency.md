# Working time under concurrency within a sample

Status: proposed, 2026-10-01; rewritten 2026-10-07 around Ransom's decision
of that date (see "Decision"). Issue: none. Author: agent (Claude), reviewed
by Codex; see the PR.

## Why

`working_limit` limits "only the time spent working (as opposed to retrying
in response to rate limits or waiting on other shared resources)"
(`docs/_working_limits.md`). Working time is wall-clock time since the
sample started minus waiting time. Evaluators use `working_limit` as a
backstop, so it must not fail open. On `main` it does fail open whenever a
sample runs model requests concurrently: through parallel tool calls,
sub-agents, `background()` workers, or a sandboxed agent's requests through
the agent bridge.

Measured on `main` at 0321960a92. The setup was one sample, a fake provider
behind the real retry loop, and the calls made from a custom solver:

| Scenario | Wall clock | Logged `working_time` |
| --- | --- | --- |
| 4 concurrent `generate()` calls, each failing twice (0.1 s attempts, 2 s backoff) and then succeeding | 4.32 s | **−12.53 s** |
| `concurrency("k", 1)` held for 3 s by one task while a sibling waits for it | 3.01 s | 0.004 s |
| The same 2 s request twice with `cache=True` (the second is a cache hit) | 2.01 s | **4.01 s** |

**Negative working time is the bug this design fixes.** Retry backoff, the
hard-pause hold, and the after-call reconciliation for failed attempts are
each credited as a separate amount per call
(`src/inspect_ai/model/_retry.py:67`, `src/inspect_ai/_control/pause.py:704`,
`src/inspect_ai/model/_model.py:1749`). Concurrent calls in one sample add
their credits together, so waiting time exceeds wall-clock time and working
time goes negative. A negative balance is a debt the limit must work off
before it can trip. While overlapping retries continue, the limit cannot
trip at all. The values already reach consumers: METR's hawk clamps
`working_time` to zero before storing it (`inspect-action` at 564a080f:
`hawk/core/importer/eval/converter.py:252`, with a non-negative check
constraint at `hawk/core/db/models.py:265`). The cache-hit row is a smaller
bug in the same reconciliation, which adds the original call's time on a
hit.

The second row shows today's semaphore merging. One waiting task counts as
the whole sample waiting. This design keeps that behaviour, extends it to
every wait, and accepts its cost (see "Accepted limitations").

## Decision

Ransom, 2026-10-07, after maintainer feedback:

> If Inspect knows of anything waiting, the time counts as waiting time;
> otherwise it counts as working time.

This replaces the options from the 2026-10-06 revision (see "Alternatives
considered"). These earlier decisions still stand:

- **On by default.** This is a bug fix, so there is no opt-in mode and no
  legacy switch.
- **Human waits count as waiting.**
- **Credited retry time has no cap.** The docs recommend setting
  `time_limit` alongside `working_limit`.

`working_limit` stays a first-class feature. Inspect's maintainers use it as
a backstop in their evals, and METR relies on it.

## The rule

At each instant, the sample is **waiting** if at least one known wait is
open anywhere in the sample. Otherwise it is **working**.

- Waiting time is the length of the **union** of all known wait intervals.
  Overlapping waits are merged, never added, so `0 ≤ working_time ≤
  total_time` always holds. That removes the negative values and the double
  counting.
- Whatever else the sample is doing during a known wait is not charged
  (see "Accepted limitations").

### Known waits

These are the waits Inspect credits today, plus human waits and the batch
queue:

| Known wait | Where the span opens and closes |
| --- | --- |
| `concurrency()` semaphore wait, including max sandboxes and max subprocesses | `sample_waiting_for()` (`src/inspect_ai/_util/working.py:76`), around the acquire |
| Model connection-slot wait, including the adaptive limiter | `ConnectionSlot.acquire` (`_model.py:799`) |
| Retry backoff sleep (`generate`, `compact`, `count_tokens`) | a tenacity `sleep=` wrapper in `model_retry_config()` (`_retry.py`), installed when `report_waiting_time` is not `None`, so batch admin loops stay excluded |
| Retried model attempts and provider-SDK retries | closed intervals added when known (see "Model attempts") |
| Hard-pause hold, and the slot reacquire after it | `wait_generate_dispatch` (`pause.py:627`) |
| Tool approval and review, by a human or a model approver | the approver call in `src/inspect_ai/approval/_apply.py:50` and `src/inspect_ai/review/_apply.py:59` (see "Approvals and limit suspension") |
| Human input | `awaiting_human("question")` (`src/inspect_ai/util/_input/request.py:53`) |
| Batch request in the batcher's local queue, until its batch is submitted | `Batcher.generate_for_request` (`src/inspect_ai/model/_providers/util/batch.py:102`), with a `submitted` event the batcher sets on submission and before delivering any result or error |
| `report_sample_waiting_time(seconds)`, the private helper | the interval `[now - seconds, now]` (see "Compatibility") |

### Model attempts

Today, a successful `generate` credits `total_time - reported_waiting_time -
output.time` after it returns (`_model.py:1749`). That covers failed
attempts and the provider SDK's own retries. A call that ends in an error
credits nothing for its attempts. A cache hit produces a negative credit.

Under the rule:

- **A successful attempt is working time.** It is not a wait, even while it
  runs.
- **A retried attempt is a known wait.** A retried attempt is one the retry
  policy classified as retryable (tenacity's `after` callback, which runs
  only for retryable outcomes and before the stop check). When it fails,
  its interval `[attempt start, attempt end]` is added to the wait set.
  This keeps today's documented exclusion of "unsuccessful model
  generations". It also credits retryable attempts in a call that
  eventually runs out of retries, which today are charged.
- **SDK-internal retries are a known wait.** When an attempt succeeds, the
  part of it before `attempt end - call.time` is added as a wait interval:
  the SDK's failed requests and sleeps before its last request. Providers
  that record no `call.time` (`azureai`, `grok`) credit nothing here, as
  today.
- **The reconciliation is removed.** Both of its parts are now intervals.
  Cache hits open no attempt and credit nothing.

These intervals are added after the fact, so the sample keeps a short list
of closed wait intervals. Intervals that end before the start of the oldest
generate call still in flight are folded into a running total. The list
therefore holds only the intervals that may still overlap a later
addition.

### Approvals and limit suspension

The approval and review dispatch already turn off two limits temporarily,
so that an approver's or reviewer's own model calls are not charged to the
agent. `apply_tool_approval` wraps the approver call in
`suspend_token_limit()` and `suspend_turn_limit()`
(`src/inspect_ai/approval/_apply.py:50`; both helpers are defined at
`src/inspect_ai/util/_limit.py:644` and `:814`), and the reviewer call does
the same (`src/inspect_ai/review/_apply.py:59`). Working time has no such
switch today, so time spent in an approver counts as the agent working.

The design adds `suspend_working_limit()` next to the other two helpers. It
is a context manager that opens a known wait for its block, so the time
counts as waiting both for `working_limit` and for the logged
`working_time`. The approval and review dispatch use it alongside the two
existing helpers. A human approval is then waiting, whichever surface
answers it. A model monitor's approval time is not charged to the agent,
just as its tokens are not. Like the other known waits, the suspension
covers the whole sample while it is open (see "Accepted limitations").

### Scoped `working_limit()` and enforcement

- **Scoped limits.** A `working_limit()` node records the sample's working
  time when it is entered. Its `usage` is the current working time minus
  that value. The per-node `_waiting_time` ledger and `record_waiting_time()`
  go. A scoped limit therefore sees the same waits as the sample. Outside a
  running sample there is no clock, and a scoped limit measures wall-clock
  time.
- **Monitor.** `monitor_working_limit` checks the root node once a second,
  as today. An open wait span stops the clock in real time, so neither the
  backoff's credit in advance nor the pause gate's 0.5 s credit ticks are
  needed. The pause tick loop stays, because it also bounds how long an
  escape takes.
- **Model-event guard.** The guard that skips the check during an active
  model event never fires (it reads a ContextVar set only in the
  generating task; `src/inspect_ai/util/_limit.py:930`), and it is
  removed. An attempt in flight is charged until it is known to have been
  retried, as it is today.
- **Event times.** `working_start` and the tool and subtask durations keep
  today's formulas (`_call_tools.py:503`, `:631`; `_subtask.py:128`,
  `:139`) over the new reading. A retroactive interval can reduce a reading
  slightly, as today's reconciliation does, so the durations are clamped to
  `[0, elapsed]`.

### Resume accounting

Today the checkpoint code keeps three things apart
(`src/inspect_ai/util/_checkpoint/sample_runtime.py:98`, `:179`), and the
design keeps that separation:

- Event offsets are cumulative.
- Logged durations cover only the current attempt.
- Prior usage counts toward enforcement only on a normal resume.

`P_wall` and `P_work` are the prior attempts' wall time and working time.
`A(t)` is the current attempt's working time, measured from the sample
clock's start. That start comes before the checkpointer awaits hydration
(`checkpointer_impl.py:136`). `E` is `A` at the moment the root node is
entered.

| Quantity | Formula |
| --- | --- |
| `working_start` of events | `P_work + A(t)` |
| Logged `EvalSample.working_time` | `A(end)` |
| Root node `usage`, normal resume (`check=True`) | `P_work + (A(t) - E)` |
| Root node `usage`, scoring resume (`check=False`) | `A(t) - E` |
| Dump `sample_elapsed` (new key) | `P_wall` plus this attempt's elapsed time, measured from the sample clock's start |
| Dump `working_elapsed` / `working_waiting` | `P_work + A(t)` / `sample_elapsed - working_elapsed` |

The new `sample_elapsed` key is needed because `time_elapsed` comes from the
time-limit node, and restore resets that node's origin after hydration
(`sample_runtime.py:170`). It therefore misses the time an attempt spends
before restore. With 5 s from earlier attempts, 10 s before restore and 2 s
after, it reads 7 instead of 17.

Restore reads values in this order:

- **`P_wall`** is `sample_elapsed` if present. Otherwise it is
  `time_elapsed`. Otherwise it is `working_elapsed + working_waiting`.
  Otherwise it is 0.
- **`P_work`** is `working_elapsed`, clamped to `[0, P_wall]`. Today's
  snapshots can hold negative values.

`time_elapsed` and `time_limit` enforcement are unchanged. Older versions
ignore the new key.

## Accepted limitations

The rule undercounts working time whenever other work runs during a known
wait, and it does not try to detect that work:

- **One wait stops the clock for everything.** A sample (or a model,
  through parallel tool calls or sub-agents) that keeps one known wait open
  is not charged for its other work during that wait. Examples are a
  background call stuck in backoff, a task queued on a semaphore, a request
  waiting for a connection slot its own other requests hold, and a model
  approver running beside other work.
- **Unseen work during a wait is free.** This covers a background process
  started through a sandbox exec tool, a sandboxed CLI agent's local
  commands, and an in-process agent library's own `asyncio.gather()`.
- **Provoked retries lengthen credited time.** A sample can provoke
  retryable failures, such as timeouts on very long outputs or some request
  errors the retry policy retries (quota 429s on OpenAI-compatible
  providers, `src/inspect_ai/model/_openai.py:1539`; some Anthropic 400s,
  `src/inspect_ai/model/_providers/anthropic.py:1835`). Wall-clock run time
  then grows without a cap, unless `time_limit` or the call's `timeout`
  and `max_retries` are set.

These cases are mostly multi-agent and concurrent. The design accepts
them: `working_limit` is a backstop, and the earlier attempts to account
for concurrency precisely were too complex for that role. `time_limit`
remains the bound on real run time, and the docs say so.

## Usage

Searched 2026-10-06. Private usage (AISI, METR's runs through hawk, labs)
is not visible to these searches.

- **inspect_evals** (checkout at 9080b5e9f, 2026-10-05): 1 of 133 evals sets
  `working_limit` (`swe_lancer`, sandboxed). 14 files set `time_limit` and
  26 set `message_limit`.
- **GitHub code search.** Queries were `working_limit language:python` (659
  matches), `working-limit` (1,344) and `working_time inspect_ai` (912),
  reading the first 100 results of each. After removing Inspect and its
  vendored copies, about 15 real public users remain, 11 of them
  sandboxed:
  - control-arena, caisi-cyber-evals, cyber-task-horizons and inspect-swe
    baselines;
  - openbench `livemcpbench`, a2ui, and AgentHarm and SOSBench runners;
  - METR's `inspect-agents` human approver, which credits approval waits
    through the private `report_sample_waiting_time`.
- **Reported by the maintainers:** `working_limit` is used as a backstop in
  every one of the lead maintainer's evals, and METR has used it widely.
- **Consumers of the logged `working_time`:**
  - Inspect's samples and events dataframes;
  - the viewer's sample activity panel and transcript timing;
  - inspect_scout;
  - hawk's `working_time_seconds` column;
  - public analysis scripts.

  They all read a float in seconds, and none depends on how the waiting
  part is computed.

## Compatibility

No migration is required, and there is no schema change other than the
`sample_elapsed` checkpoint key.

- **Concurrent samples get correct values.** Samples with concurrent
  retries, holds or reconciliations no longer report negative or inflated
  waiting, so `working_limit` can trip where it never did before.
- **Sequential samples barely change.** Human approval, model-approver and
  human-input time is now credited. Retryable attempts in a call that runs
  out of retries are now credited. Cache hits no longer add time.
- **`report_sample_waiting_time(seconds)`** keeps its signature. It now
  adds the interval `[now - seconds, now]` instead of a separate amount.
  METR's approver reports the time since its last report every second, so
  its calls merge with the native approval span instead of adding to it,
  and it keeps working.
- **Downstream readers** keep working: field names and types are
  unchanged.
- **Docs and changelog.** `docs/_working_limits.md` lists the known waits
  and the accepted limitations, and recommends `time_limit` as the
  real-time bound. A CHANGELOG entry says working time can no longer go
  negative and that concurrent waits are merged.

## Testing

All async tests run under both backends (`--runtrio` before the PR).
Fake-clock tests inject `now` through `init_sample_working_time` and patch
the backoff sleep's `_sleep` indirection. Their fake `ModelAPI` attempts
block on `anyio.Event`s, so ordering is fixed.

- **Interval set** (`tests/util/test_limit_working.py`). Covers union,
  retroactive insertion, and folding of old intervals. Seeded random
  sequences check that `0 ≤ working ≤ elapsed`.
- **Samples** (`tests/test_sample_limits.py`):
  - the three measured scenarios: concurrent retries give `working_time ≥
    0` and waiting equal to the union, a semaphore waiter merges, and a
    cache hit adds nothing;
  - a retryable attempt in a call that runs out of retries is credited;
  - an SDK-internal retry is split using a fake `call.time`;
  - `suspend_working_limit()` around an approver, and human input;
  - the batch queue;
  - scoped limits use deltas.
- **Pause** (`tests/_control/test_pause.py`). Hold credit happens without
  ticks, and two parked calls merge.
- **`report_sample_waiting_time`** merges with an overlapping native span.
- **Checkpoints** (`tests/checkpoint/test_sample_runtime.py`):
  - normal, scoring and consecutive resumes;
  - 10 s of hydration delay before restore (the `sample_elapsed` example);
  - an old snapshot with a negative `working_elapsed`;
  - payloads without `sample_elapsed` or `time_elapsed`.

## Implementation plan

1. **`src/inspect_ai/_util/working.py`.** Replace the waiting ledger with
   an open-span counter plus the interval set. Add the `sample_wait()`
   helper, reinterpret `report_sample_waiting_time` as an interval, and add
   the `now` and `_sleep` indirections.
2. **`src/inspect_ai/util/_limit.py`.** Scoped nodes use deltas. Add
   `suspend_working_limit()` (exported from `inspect_ai.util`). Remove
   `record_waiting_time` and the dead model-event guard. Use it in
   `approval/_apply.py` and `review/_apply.py`, and use `sample_wait()` in
   `awaiting_human`.
3. **`model/_retry.py`, `model/_model.py`, `_control/pause.py`.** Add the
   backoff sleep span and the `after` callback for retried attempts, record
   the SDK-retry split, and remove the reconciliation and the pause credit
   ticks. Add the batch `submitted` event in `model/_providers/util/batch.py`.
4. **`_eval/task/run.py` and `util/_checkpoint/sample_runtime.py`.** Use the
   logged value and add the resume formulas with `sample_elapsed`. Clamp
   event durations in `_call_tools.py` and `_subtask.py`.
5. **Docs, CHANGELOG and the tests above.**

## Alternatives considered

Each was rejected as too complex or too restrictive for a backstop feature,
in line with maintainer feedback that earlier, more precise attempts were
too risky.

- **Lanes with provisional attempts** (the first revisions of this design).
  Per-task waiting states and in-flight attempts resolved by outcome would
  stop one wait from crediting other work. The cost is lanes at every fork
  site, pending segments and event probes.
- **Credit only sure waits in eligible samples** (2026-10-06 option A). No
  credit with a sandbox or an in-process `agent_bridge()`, any concurrent
  region charged, an in-flight attempt outranking a wait, and a warning for
  samples that get no credit. This closes the gaming routes, but it turns
  `working_limit` into `time_limit` for most real users (sandboxed
  agents), and those users depend on rate-limit and semaphore credit.
- **Working time equals wall-clock time** (2026-10-06 option B), with
  `working_limit` deprecated. This is the simplest choice, but it drops the
  credit that makes the feature useful (max-sandboxes and rate-limit
  waits), and that loss distorts results.
- **Opt-in new accounting with the old as default.** The old accounting is
  the bug.
- **Clamping today's sums to wall-clock time.** This hides negative values
  but keeps the double counting.

## Open questions

1. **Add a public `suspend_working_limit()`?** I recommend yes. It is
   small, mirrors `suspend_token_limit()` and `suspend_turn_limit()`, and
   gives code like METR's approver a public way to mark time as waiting.
   The alternative is to keep it internal and wrap approvals with the
   private `sample_wait()` helper.

## Not this design

- Precise accounting under concurrency, such as per-task or per-region
  credit (see "Alternatives considered").
- A breakdown of waiting time by cause in the log.
- Making request-attributable errors non-retryable in provider retry
  policies.
