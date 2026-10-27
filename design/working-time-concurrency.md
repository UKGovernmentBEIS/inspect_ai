# Working time under concurrency within a sample

Status: accepted and implemented, 2026-10-07; known work added
2026-10-15. Proposed 2026-10-01; rewritten 2026-10-07 around Ransom's
decision of that date, and revised 2026-10-15 around his decision of that
date (see "Decision"). Issue: none. Author: agent (Claude), reviewed by
Codex; see the PRs.

## Overview

Working time is clock time minus waiting time. The 2026-10-07 rule made
every known wait (backoff, a semaphore queue, an approval) stop the clock
for the whole sample, so one wait made all other work in the sample free.
The 2026-10-15 revision adds known work: while a model request, a sandbox
exec or a tool call is in progress and not itself waiting, the sample is
working, whatever waits are open elsewhere. Known work removes the first
accepted limitation ("One wait stops the clock for everything") for the
work Inspect can see. Work it cannot see (a background process, a
sandboxed agent's own commands, an in-process library's `gather()`) stays
free during a wait.

The sample keeps known work beside the waits, on one timeline that
records for each stretch of time whether a closed wait covers it and how
many spans' closed work does. A reading is the length of the waits not covered by known work,
so it still lies in `[0, elapsed]`. A model attempt in flight is known work
until the retry policy classifies it as retried, when its interval becomes
a wait again, as before.

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

The second row shows the semaphore merging on `main` at the time. The
2026-10-07 rule made one semaphore wait pause the whole sample. The
2026-10-15 rule charges any concurrent known work (see "Known work" and
"Accepted limitations").

## Decision

Ransom, 2026-10-15 (decision: Ransom, 2026-10-15): improve working-time
accounting so that known work is charged even while a wait is open
elsewhere in the sample. Each instant is classified as:

> 1. If something is known to be working, the instant is working.
> 2. Otherwise, if something is known to be waiting, the instant is
>    waiting.
> 3. Otherwise, working.

This builds on Ransom's decision of 2026-10-07, after maintainer feedback,
which is rules 2 and 3:

> If Inspect knows of anything waiting, the time counts as waiting time;
> otherwise it counts as working time.

That decision replaced the options from the 2026-10-06 revision (see
"Alternatives considered"). These earlier decisions still stand:

- **On by default.** This is a bug fix, so there is no opt-in mode and no
  legacy switch.
- **Human waits count as waiting.**
- **Credited retry time has no cap.** The docs recommend setting
  `time_limit` alongside `working_limit`.

`working_limit` stays a first-class feature. Inspect's maintainers use it as
a backstop in their evals, and METR relies on it.

## The rule

At each instant, the sample is **working** if any known work is in
progress anywhere in the sample. Otherwise it is **waiting** if at least
one known wait is open anywhere in the sample. Otherwise it is
**working**.

- Waiting time is the length of the **union** of all known wait intervals
  minus the **union** of all known work intervals. Overlapping waits and
  overlapping work are merged, never added, so `0 ≤ working_time ≤
  total_time` always holds. That removes the negative values and the
  double counting.
- Work Inspect does not see during a known wait is not charged (see
  "Accepted limitations").

### Known work

| Known work | Where the span opens and closes |
| --- | --- |
| A model `generate`, `compact()` or `count_tokens()` attempt in flight | `ModelAttempts.attempt()` around the provider call in `Model._generate`, `Model.compact` and `Model.count_tokens` (`_model.py`), from just before `api.generate`, `api.compact` or `api.count_tokens` to its return. The connection-slot or pool wait, the pause hold and the cache lookup come before it, and the backoff after it. |
| A sandbox exec | `SandboxEnvironmentProxy.exec` (`util/_sandbox/events.py`), except Inspect's own plumbing: the sandbox service's setup and queue commands, and commands a task runs inside the proxy's `no_events()` (`exec_remote`'s polls, sandbox tools injection, the human agent's setup and the execs of its service handlers, including intermediate scoring), and execs run inside `sandbox_agent_bridge()`, such as the one that launches a bridged agent (decision: Ransom, 2026-10-16: Inspect cannot see when a bridged agent is working). That code runs its execs inside `untracked_sandbox_execs()`, a task-local flag, so the exclusion never depends on a command's text, and another task's exec on the same sandbox stays known work. |
| A tool call | `call_tool()` in `call_tool_task` (`model/_call_tools.py`), including its approval and sentinel stages, and a bridged host tool call in the sandbox agent bridge's service (`agent/_bridge/sandbox/service.py`) |

Cache hits open no attempt. `compact()` and `count_tokens()` are model
requests made for the sample, as `generate` is (decision: Ransom,
2026-10-16), so their attempts are known work and their retries and backoff
are known waits.

Known work excludes the waits inside it. A span is **held** while a wait or
a nested span is open in its own task context, which includes the tasks it
starts (they inherit the context). A held span is not working; the inner
wait or work accounts for that time. So a tool call whose sandbox exec is
queued on `max_subprocesses`, or that waits for its approval, is waiting
for that part, and a tool call that runs a sub-agent's model call is
charged as that attempt, which can later become a wait.

A span holds its parent while it is open, and after it closes for as long
as something in a task it started still holds it. So a task that outlives
the span that started it (a `background()` worker, or a background agent
dispatched by a tool that has returned) still holds the open work above
it.

Work done inside a suspension is not known work. A `sample_wait()` block,
which is what `suspend_working_limit()`, approvals, reviews, sentinel
monitors, human input, the pause hold, the connection-slot wait and the
backoff sleep use, marks its context as suspended, and no span opens there.
An approver's or a monitor's own model calls and tool calls therefore never
restart the agent's clock. `SampleWait` objects that close from another
task (the batch queue, `sample_waiting_for()`) hold the work of the context
that opened them but suspend nothing, since no work runs inside them.

The suspension only stops new spans from opening; it does not hide the work
around it. A wait opened by a task started inside a suspension still holds
the enclosing work, so if that task outlives the suspension the enclosing
work stays held until its wait ends. Outside a running sample,
`sample_wait()` does nothing, so a sample started inside it (an `eval()`
call wrapped in `suspend_working_limit()`) is not suppressed.

### Known waits

These are the waits Inspect credits today, plus human waits and the batch
queue:

| Known wait | Where the span opens and closes |
| --- | --- |
| `concurrency()` semaphore wait, including max sandboxes and max subprocesses | `sample_waiting_for()` (`src/inspect_ai/_util/working.py:692`), around the acquire |
| Model connection-slot wait, including the adaptive limiter | `ConnectionSlot.acquire` (`_model.py:799`) |
| Retry backoff sleep (`generate`, `compact`, `count_tokens`) | a tenacity `sleep=` wrapper in `model_retry_config()` (`_retry.py`), installed when `sample_waits` is set (it replaces the `report_waiting_time` callback), so batch admin loops stay excluded |
| Retried model attempts and provider-SDK retries | closed intervals added when known (see "Model attempts") |
| Hard-pause hold, and the slot reacquire after it | `wait_generate_dispatch` (`pause.py:627`) |
| Tool approval and review, by a human or a model approver | the approver call in `src/inspect_ai/approval/_apply.py:50` and `src/inspect_ai/review/_apply.py:59` (see "Approvals and limit suspension") |
| Sentinel monitors, at all four stages (before and after the agent's model calls and tool calls) | the monitor run in `_run()` in `src/inspect_ai/_sentinel/_dispatch.py` (see "Approvals and limit suspension") |
| Human input | `awaiting_human("question")` (`src/inspect_ai/util/_input/request.py:53`) |
| Batch request in the batcher's local queue, until its batch is submitted | `Batcher.generate_for_request` (`src/inspect_ai/model/_providers/util/batch.py:102`), with an `on_submitted` callback the batcher calls on submission and before delivering any result or error |
| `report_sample_waiting_time(seconds)`, the private helper | the interval `[now - seconds, now]` (see "Compatibility") |

### Model attempts

Today, a successful `generate` credits `total_time - reported_waiting_time -
output.time` after it returns (`_model.py:1749`). That covers failed
attempts and the provider SDK's own retries. A call that ends in an error
credits nothing for its attempts. A cache hit produces a negative credit.

Under the rule:

- **An attempt in flight is known work.** Its intervals (the parts not held
  by a wait inside it, such as the batch queue) are kept on the attempt
  until the retry loop is done with it, and read as live work meanwhile.
  A step after the provider call (event completion, usage recording,
  telemetry) can still raise a retryable error, so the attempt stays
  reclassifiable until the retry-wrapped function returns.
- **A successful attempt is working time.** Its intervals are added to the
  work set when the retry loop returns.
- **A retried attempt is a known wait.** A retried attempt is one the retry
  policy classified as retryable (tenacity's `after` callback, which runs
  only for retryable outcomes and before the stop check). When it fails,
  its intervals are dropped from known work and its interval `[attempt
  start, attempt end]` is added to the wait set. Only the part of it with
  no other known work becomes waiting. This keeps today's documented
  exclusion of "unsuccessful model generations". It also credits retryable
  attempts in a call that eventually runs out of retries, which today are
  charged.
- **An attempt that fails without a retry** (a non-retryable error, or a
  cancellation) is working time: the model call adds its intervals to
  the work set when the retry loop exits.
- **SDK-internal retries are a known wait.** When an attempt succeeds, the
  part of it before `attempt end - call.time` is added as a wait interval:
  the SDK's failed requests and sleeps before its last request. The split
  needs a positive `call.time`; the attempt's pending known work is trimmed
  to start at `attempt end - call.time`, and stays pending until the retry
  loop returns. A missing `call.time` (`azureai`, in-process
  providers such as `hf`) and a zero `call.time` (SageMaker's placeholder,
  and the HTTP-hook fallback for a request id that was never registered)
  mean the request was not measured, so nothing is credited and the whole
  successful attempt is charged. `grok` times the whole call, so its split
  is empty. `compact()` and `count_tokens()` return no `ModelCall`, so a
  successful attempt of theirs is charged whole too.
- **The reconciliation is removed.** Both of its parts are now intervals.
  Cache hits open no attempt and credit nothing.

### The interval set

Some waits are added after the fact: retried attempts, SDK-internal
retries, and `report_sample_waiting_time(seconds)`. That helper can report
any `[now - seconds, now]`, even when no model call is in flight. For
example, EXP-Bench reports a whole custom call's wait after it returns, and
METR's approver reports every second while a native approval wait may be
open. A scalar total cannot de-duplicate a late report against what it has
already counted: histories `[0,1]` and `[1,2]` both total 1, but a later
report of `[1,3]` must bring them to 3 and to 2 respectively.

The same holds for known work, which can be dropped after the fact (a
retried attempt). So the sample keeps, for the whole attempt and with no
folding, one timeline of closed waits and closed known work: a sorted list
of disjoint segments, each recording whether a closed wait covers it and
how many spans' closed work covers it. Time in no segment has neither.
Adjacent segments with the same state are merged. Two prefix sums go with
it: the length of the waiting segments (a wait and no work), `E`, and the
length of all segments (a wait or work), `U`. Beside the timeline the
sample keeps the start time of the oldest open wait and the work spans
that are open or awaiting classification:

- **Adding an interval.** It is clipped to the current attempt, from the
  sample clock's start to now. Adding a wait or work, and withdrawing work,
  are one operation: split the segments at the interval's ends, set the
  wait flag or change the work count over it, merge neighbours whose state
  is now equal, and refresh the prefix sums from the first changed segment.
  Overlapping additions only change a segment's state, so every addition,
  live or late, is de-duplicated exactly. A span's interval is added when
  the span is held or closes; an attempt's intervals wait for its
  classification.
- **Late waits and their own work.** A wait added after the fact
  (`add_sample_wait`, `report_sample_waiting_time`, a retried attempt in the
  retry loop) would otherwise be covered by the reporting context's own
  work, which was active while the wait was not yet known: a tool calling
  `generate()` whose attempt is retried, for example, since the retried
  interval starts before the provider call. So the wait is
  withdrawn from the known work of the reporting context and the work
  enclosing it, as if it had held them while open. This holds for a wait
  reported from inside a suspension too (an approver reporting its wait):
  the suspension stops new work from opening there, but the work around it
  still owns its earlier time. Other tasks' work over the interval is
  kept. For this, the timeline counts how many spans' work covers each
  segment, and each span keeps the intervals it added. A withdrawal
  decrements the counts; a segment whose count reaches zero is waiting if
  a closed wait covers it, and leaves the timeline otherwise.
- **Late waits and finished work.** A custom call is usually reported after
  it returns, by when its model calls, sandbox commands and nested work
  have closed. So when a span's work is final (at close, or for a model
  attempt when the retry loop commits or drops it), it hands the intervals
  it counted, and those handed to it, to its parent span. Each interval
  keeps the span that counted it. The timeline is unchanged; only the
  record of which span can withdraw them moves up. A late report walks the same chain
  of spans and withdraws their handed-up intervals as well as their own: a
  tool that reports a five-second generate it just made reads 0 working.
  A closed span still held by a task it started passes what it receives on
  to its parent; a span with no parent drops it, so once a top-level tool
  call has returned, a task it started can no longer withdraw its work,
  as at the sample's top level. A still-open top-level tool keeps what its
  finished operations hand it. The retry loop's own waits (a retried
  attempt, and an attempt's SDK-internal retries) withdraw only the
  intervals counted by the spans on the reporting context's chain, wherever
  those have been handed, such as the work of an inner tool that returned
  while its background task's `generate()` was preparing an attempt that
  was then retried. The
  attempt's own work is dropped or trimmed on the attempt itself, and work
  that other tasks under the same span finished meanwhile stays charged.
- **Size.** Every segment boundary is an end of an added interval, so the
  timeline holds at most two segments per interval added, usually fewer,
  because segments with equal state merge. A sample has at most a few
  thousand spans, so memory is small. Prior attempts are carried as totals
  in the checkpoint (see "Resume accounting").
- **Readings.** The live wait is `L = [oldest open wait start, now]` while
  any known wait is open. The live work is the merged intervals of the
  open and unclassified spans, a handful at any time. For a window `J`,
  the waiting outside closed work is

  `x(J) = |E ∩ J| + |L ∩ J| - |U ∩ L ∩ J|`

  where `E` is the waiting segments and `U` all segments, and
  `waiting(a, b) = x([a, b]) - Σ x(J)` over the live-work intervals `J`
  within `[a, b]`. Each term is a bisect into the timeline and a prefix-sum
  lookup, so a reading costs `O(s log n)` for `s` live spans and `n`
  segments. Working time over `[a, b]` is `(b - a) - waiting(a, b)` and
  always lies in `[0, b - a]`. When a live span closes, it is added to the
  timeline, and every reading is unchanged at that instant.

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
just as its tokens are not. Sentinel monitors are treated the same way:
`_run()` in `src/inspect_ai/_sentinel/_dispatch.py`, which runs the
monitors at every stage, uses `suspend_working_limit()` alongside the token
and turn suspensions. Like the other known waits, the suspension covers the
whole sample while it is open, except where known work runs elsewhere in
the sample. Model calls and tool calls made inside the suspension are not
known work (see "Known work").

### Scoped `working_limit()` and enforcement

- **Scoped limits.** A `working_limit()` node keeps its own start time
  (and end time, once exited), as today (`util/_limit.py:1480`). Its
  `usage` is `(end_or_now - start) - waiting(start, end_or_now)`: the waits
  inside the node's own interval, computed when it is read. A reading
  difference saved at entry would be wrong. Suppose an attempt runs 0–8, a
  scope starts at 5, and the attempt is then classified as retried, which
  adds `[0, 8]`. At 10 the sample's working time is 2 and the value saved
  at entry is 5, so the difference would be −3. The interval formula gives
  `5 - 3 = 2`, which is correct. Usage therefore always lies in
  `[0, elapsed]` and picks up late additions. The per-node `_waiting_time`
  ledger and `record_waiting_time()` go. Outside a running sample there is
  no clock, and a scoped limit measures wall-clock time.
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
- **Event durations.** Tool and subtask durations use the same interval
  formula. Each producer keeps its start time on the sample clock instead
  of a waiting baseline, and sets the event's working time from
  `sample_working_time_since(start)`, which reads elapsed and waiting time
  over one window, so the result lies in `[0, now - start]`.
  `ToolEvent._set_result` takes that `working_time` directly
  (`src/inspect_ai/event/_tool.py`). The producers are the tool-stage
  baselines and every completion and cancellation path in
  `src/inspect_ai/model/_call_tools.py`, and the subtask in
  `src/inspect_ai/util/_subtask.py`, which sets `SubtaskEvent.working_time`
  the same way. An event's duration
  uses the waits and work known when the event completes. A retried attempt
  classified after that does not change an event that is already
  published; this is a stated approximation of the heuristic. A tool
  event's own call is known work, so its duration counts as working except
  where the call itself was held.
  `working_start` is the sample's working time at the event's creation,
  as today.

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

The rule undercounts working time whenever work Inspect does not see runs
during a known wait, and it does not try to detect that work:

- **Unseen work during a wait is free.** This covers a background process
  started through a sandbox exec tool, a sandboxed CLI agent's local
  commands, an in-process agent library's own `asyncio.gather()`, and a
  solver's or scorer's own code between known work. Work is seen only when
  it goes through a model request (`generate`, `compact()`,
  `count_tokens()`), a sandbox exec or a tool call. A sandboxed agent's
  model requests through the agent bridge are generate calls and so are
  known work, and its bridged host tool calls are tool calls. The exec
  that launches it is not, and neither is any other exec the solver runs
  inside `sandbox_agent_bridge()`: the bridge's body runs inside
  `untracked_sandbox_execs()`, while its model service, started before the
  body, stays tracked.
- **A held span hides its sibling tasks' unseen work.** A tool call that
  starts several tasks is held while any of them waits, so its other tasks'
  unseen work during that wait is free. Their known work is still charged.
- **Retry classification is late.** An attempt in flight is charged until
  the retry policy classifies it, so a `working_limit` can trip during an
  attempt that is later retried. This was already the case before known
  work.
- **A late report withdraws the finished work of a whole span.** Work that
  finished under any span on the reporting context's chain is withdrawn
  over the reported interval, including that of subtasks a tool started
  and of sibling tool calls inside an agent running as a tool, although a
  wait opened at the time would not have stopped them. At the sample's
  top level there is no span, so a late report after a top-level generate
  or exec withdraws nothing, and a top-level tool call's work is dropped
  from late reports once it returns. Callers that report a custom call's
  wait should wrap the call in `sample_wait()` where they can.
- **Provoked retries lengthen credited time.** A sample can provoke
  retryable failures, such as timeouts on very long outputs or some request
  errors the retry policy retries (quota 429s on OpenAI-compatible
  providers, `src/inspect_ai/model/_openai.py:1539`; some Anthropic 400s,
  `src/inspect_ai/model/_providers/anthropic.py:1835`). Wall-clock run time
  then grows without a cap, unless `time_limit` or the call's `timeout`
  and `max_retries` are set.

The first limitation of the 2026-10-07 rule, "one wait stops the clock
for everything", is removed for known work by the 2026-10-15 revision.
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
- **Known work (2026-10-15).** Samples that run model calls, sandbox
  execs or tool calls while a wait is open elsewhere get more working time,
  up to what the old rule hid, so a `working_limit` can trip sooner. No
  sample gets less working time: known work only removes waiting.
  `suspend_working_limit()` no longer makes other tasks' known work free.
- **Sequential samples barely change.** Human approval, model-approver and
  human-input time is now credited. Retryable attempts in a call that runs
  out of retries are now credited. Cache hits no longer add time.
- **`report_sample_waiting_time(seconds)`** keeps its signature. It now
  adds the interval `[now - seconds, now]`, clipped to the current attempt,
  instead of a separate amount. Because the merged set is kept for the
  whole attempt, a late report that overlaps waits already counted is
  de-duplicated exactly, and the union guarantee holds.
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

- **Interval set** (`tests/util/test_limit_working.py`):
  - union and retroactive insertion, and clipping to the attempt;
  - `waiting(a, b)` intersection, including an open span;
  - seeded random sequences checking that `0 ≤ working ≤ elapsed` and that
    every window's working time lies in `[0, b - a]`;
  - late overlap: a `report_sample_waiting_time` interval overlapping an
    already-closed native wait, and the `[0,1]`/`[1,2]` then `[1,3]` case,
    giving totals 3 and 2;
  - closed intervals added while a span is still open:
    - a native wait open over `[0, 2]` with a private report of `[1, 2]`
      (METR's approver reporting every second inside the native approval
      span) reads waiting 2 and working 0 over `[0, 2]`, and working 0
      over a scope window `[1, 2]`, before the span closes;
    - a retried attempt classified while a sibling's backoff span is open
      counts the overlap once;
    - in both cases, closing the open span leaves every reading
      unchanged.
- **Samples** (`tests/test_sample_limits.py`):
  - the three measured scenarios: concurrent retries give `working_time ≥
    0` and waiting equal to the union, a semaphore waiter merges, and a
    cache hit adds nothing;
  - a retryable attempt in a call that runs out of retries is credited;
  - an SDK-internal retry is split using a fake `call.time`;
  - `suspend_working_limit()` around an approver, and human input;
  - the batch queue;
  - a scope that starts while a later-retried attempt is in flight: the
    attempt runs 0–8 and is classified at 8, and the scope starts at 5. At
    10 the scope's usage is 2 and lies within its elapsed time, and a
    scoped limit of 1 trips;
  - a subtask that straddles a retroactive interval reports the waits
    inside its own interval only, and a tool that completes before the
    classification keeps its published duration.
- **Pause** (`tests/_control/test_pause.py`). Hold credit happens without
  ticks, and two parked calls merge.
- **`report_sample_waiting_time`** merges with an overlapping native span.
- **Checkpoints** (`tests/checkpoint/test_sample_runtime.py`):
  - normal, scoring and consecutive resumes;
  - 10 s of hydration delay before restore (the `sample_elapsed` example);
  - an old snapshot with a negative `working_elapsed`;
  - payloads without `sample_elapsed` or `time_elapsed`.
- **Known work** (2026-10-15). Fake-clock tests in
  `tests/util/test_limit_working.py`:
  - known work in one task overrides a wait in another;
  - a wait in the work's own context, or a task it started, holds it;
  - model calls and tool calls inside `suspend_working_limit()` are not
    known work;
  - an attempt classified as retried (through the real retry config) while
    a sibling tool call ran: only the part with no other known work becomes
    waiting; a successful attempt is charged from `attempt end -
    call.time`; a tool's nested attempt that is retried makes that part of
    the tool a wait;
  - a late wait reported inside a tool is withdrawn from that tool's work
    and its enclosing tool's work, but not from a sibling's, including when
    it is reported from inside `sample_wait()` or `suspend_working_limit()`
    and covers time before the suspension started;
  - a late wait reported inside a tool after a generate, a sandbox exec or
    nested known work there has returned withdraws it, live, closed and in
    scoped usage, through both report helpers, while an independent
    sibling's work over part of the interval stays charged; work finishing
    under a closed span reaches the open span above it; at the top level a
    late report withdraws nothing, nor does one from a task a top-level
    tool started after the tool returned; and the retry loop's waits (a
    retried attempt, SDK-internal retries) leave work another task finished
    under the same tool charged but withdraw the work of an inner tool that
    returned during the attempt (a generate's work before its provider
    call, with and without a sibling; the same readings for
    `count_tokens()` and `compact()`, whose attempt holds the inner tool);
  - a `count_tokens()` or `compact()` attempt through the real `Model`
    methods: a successful one beside another task's open wait is working,
    and a retried one is waiting, also inside a tool, which is not charged
    for it; scoped usage agrees;
  - a task that outlives the inner tool that started it still holds the
    outer tool, for waits and retried model attempts, and a wait that
    outlasts its span keeps the span above held;
  - a task started inside a tool's suspension that waits past the
    suspension's end (in `sample_wait()`, a `SampleWait` or
    `sample_waiting_for()`, ended or cancelled) keeps the tool held;
  - a suspension entered outside a sample does not suppress the known work
    of a sample started inside it;
  - an exec on a sandbox while another task runs inside its `no_events()`
    is still known work, an exec whose arguments name the services
    directory is known work, and execs inside `untracked_sandbox_execs()`
    are not;
  - a bridged agent launched by one blocking exec inside
    `sandbox_agent_bridge()` (the real bridge, with its sandbox and model
    service transport stubbed), beside another task's open wait, whose
    model request fails, backs off and succeeds reads the failed attempt
    and backoff as waiting and the successful request as working, live and
    closed and in scoped usage; the same exec outside a bridge is known
    work, and a launch through the real `exec_remote()` start and poll
    calls is not;
  - a bridged host tool call through the bridge service's `call_tool` is
    known work beside another task's open wait, and a wait inside it is
    waiting;
  - seeded random sequences of nested spans (including contexts of closed
    spans), waits (some opened by a task started inside a suspension),
    late waits reported from inside work (some from inside a suspension,
    some withdrawing finished work and some not), attempts classified both
    ways and scoped limits, with a reference that hands each span's work to
    its parent when it is final and drops it at a span with no parent,
    checked against a brute-force
    evaluation of the rule, with every reading and scope in bounds and
    unchanged when everything closes.

  Sample tests in `tests/test_sample_limits.py`: a tool call or a
  successful generate, `count_tokens()` or `compact()` beside a call in
  retry backoff is working; a task
  queued on a semaphore while its holder generates is working; a model
  approver's generate leaves an idle agent waiting; `count_tokens()` and
  `compact()` retries inside a tool are waiting; an attempt whose provider
  call succeeded but whose usage telemetry then failed and was retried is
  waiting, with and without a measured `call.time`; a local sandbox exec
  beside a wait is working; a sandbox exec queued for a
  `max_subprocesses` slot is waiting; a tool that reports its finished
  generate as a wait, through either helper, is not charged for it in the
  tool event or the sample; and, in Docker, a bridged agent launched by a
  blocking exec whose chat completion is retried once gets the failed
  attempt and backoff as waiting. The lone-wait cases above are unchanged.

## Implementation plan

1. **`src/inspect_ai/_util/working.py`.** Replace the waiting ledger with
   an open-span counter plus the merged interval set for the attempt, with
   `waiting(a, b)`. Add the `sample_wait()`
   helper, reinterpret `report_sample_waiting_time` as an interval, and add
   the `now` and `_sleep` indirections.
2. **`src/inspect_ai/util/_limit.py`.** Scoped nodes use deltas. Add
   `suspend_working_limit()` (exported from `inspect_ai.util`). Remove
   `record_waiting_time` and the dead model-event guard. Use it in
   `approval/_apply.py`, `review/_apply.py` and the sentinel monitor run in
   `_sentinel/_dispatch.py`, and use `sample_wait()` in `awaiting_human`.
3. **`model/_retry.py`, `model/_model.py`, `_control/pause.py`.** Add the
   backoff sleep span and the `after` callback for retried attempts, record
   the SDK-retry split, and remove the reconciliation and the pause credit
   ticks. Add the batch `submitted` event in `model/_providers/util/batch.py`.
4. **`_eval/task/run.py` and `util/_checkpoint/sample_runtime.py`.** Use the
   logged value and add the resume formulas with `sample_elapsed`. Switch
   the event producers in `_call_tools.py` and `_subtask.py` to
   `sample_working_time_since(start)`.
5. **Docs, CHANGELOG and the tests above.**

Known work (2026-10-15) replaces the wait set with the timeline of waits
and work, and adds `known_work()` and
`ModelAttempts` to `_util/working.py`, the attempt span to
`Model._generate`, `Model.compact`, `Model.count_tokens` and the retry
config's `after` callback, and the spans in
`SandboxEnvironmentProxy.exec`, `_call_tools.py` and the bridge's host tool
service.

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

## Decisions on earlier open questions

The sample-wide exemption of other tasks' known work in these earlier
decisions was superseded on 2026-10-15; their known work is now charged.

1. **`suspend_working_limit()` is public.** Ransom, 2026-10-07: it is
   exported from `inspect_ai.util`, so code like METR's approver has a
   public way to mark time as waiting. Its contract differs from
   `suspend_token_limit()` and `suspend_turn_limit()`, which suspend
   metering only for code inside the block in the current task.
   `suspend_working_limit()` marks the whole sample as waiting while the
   block is open, because waiting is sample-wide under the union rule;
   since 2026-10-15, other tasks' known work during the block is charged.
   Its docstring says so. Only code in
   the eval process can call it, not agent code in a sandbox.
2. **Sentinel monitors count as waiting.** Ransom, 2026-10-13: monitor
   runs at all four sentinel stages count as waiting, as approvers and
   reviewers do. The cost is the same as for approvals: while a monitor
   runs, other work in the sample is not charged.
3. **Known work scope.** Ransom, 2026-10-16: `compact()` and
   `count_tokens()` attempts are known work, like `generate`; bridged host
   tool calls stay known work, like native tool calls; a late report from
   one tool inside an agent running as a tool may withdraw a sibling tool's
   finished work (see "Accepted limitations"); and a top-level tool call's
   work is dropped from late reports once it returns, since the work it
   holds then is mostly finished nested operations that a wait opened by a
   task outliving it would not have stopped. Execs inside
   `sandbox_agent_bridge()`, including a bridged agent's launcher, are not
   known work, since Inspect cannot see when a bridged agent is working.

## Not this design

- Precise accounting under concurrency, such as per-task or per-region
  credit (see "Alternatives considered").
- A breakdown of waiting time by cause in the log.
- Making request-attributable errors non-retryable in provider retry
  policies.
