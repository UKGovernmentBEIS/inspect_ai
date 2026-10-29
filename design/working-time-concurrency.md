# Working time under concurrency within a sample

## Overview

Working time is a sample's clock time minus its waiting time, and
`working_limit` bounds it. Inspect classifies each instant of a sample by
one rule: if any known work is in progress (a model request, a sandbox
exec or a tool call that is not itself waiting), the sample is working;
otherwise, if any known wait is open (a semaphore or connection queue, a
retried model attempt or its backoff, an approval, a monitor, a person),
it is waiting; otherwise it is working. Waits that overlap count once, and
so does work, so working time always lies between zero and the elapsed
time, however many tasks in the sample run at once.

The sample keeps one timeline of closed waits and closed known work for
the whole attempt, and work still in progress on spans beside it. A
reading is the length of the waits not covered by known work. A model
attempt in flight is known work until the retry policy classifies it as
retried, when its interval becomes a wait. Work Inspect cannot see (a
background process, a sandboxed agent's own commands, an in-process
library's `gather()`) is not charged while a wait is open, so
`working_limit` is a backstop that can undercount, and `time_limit` is the
bound on real run time.

The code is in [`_util/working.py`](../src/inspect_ai/_util/working.py);
the user documentation is [`docs/_working_limits.md`](../docs/_working_limits.md),
included in [Setting limits](../docs/setting-limits.qmd).

## The rule

At each instant the sample is:

1. **working** if any known work is in progress anywhere in the sample;
2. otherwise **waiting** if at least one known wait is open anywhere in the
   sample;
3. otherwise **working**.

Waiting time is the length of the union of all known wait intervals minus
the union of all known work intervals. Overlapping waits and overlapping
work are merged, never added, so `0 ≤ working_time ≤ total_time` always
holds. Work Inspect does not see during a known wait is not charged (see
"Accepted limitations").

## Known work

| Known work | Where the span opens and closes |
| --- | --- |
| A model `generate`, `compact()` or `count_tokens()` attempt in flight | `ModelAttempts.attempt()` around the provider call in `Model._generate`, `Model.compact` and `Model.count_tokens` ([`_model.py`](../src/inspect_ai/model/_model.py)). The connection-slot or pool wait, the pause hold and the cache lookup come before it, and the backoff after it. |
| A sandbox exec | `SandboxEnvironmentProxy.exec` ([`util/_sandbox/events.py`](../src/inspect_ai/util/_sandbox/events.py)), through `sandbox_exec_work()`, except execs a task runs inside `untracked_sandbox_execs()` (below) |
| A tool call | `known_work()` around `call_tool()` in `call_tool_task` ([`model/_call_tools.py`](../src/inspect_ai/model/_call_tools.py)), including its approval and sentinel stages, and around a bridged host tool call in the sandbox agent bridge ([`agent/_bridge/sandbox/host_tool.py`](../src/inspect_ai/agent/_bridge/sandbox/host_tool.py)) |

Cache hits open no attempt. `compact()` and `count_tokens()` are model
requests made for the sample, as `generate` is, so their attempts are known
work and their retries and backoff are known waits.

`untracked_sandbox_execs()` is a task-local flag for execs that are
Inspect's own plumbing or whose work Inspect cannot see. The exclusion never
depends on a command's text, and another task's exec on the same sandbox
stays known work. It covers:

- the sandbox service's Python check and queue commands
  ([`util/_sandbox/service.py`](../src/inspect_ai/util/_sandbox/service.py));
- every exec a task runs inside the proxy's `no_events()`: `exec_remote()`'s
  polls, sandbox tools injection, and the human agent's setup and the execs
  of its service handlers, including intermediate scoring;
- every exec run inside `sandbox_agent_bridge()`'s body, such as the one
  that launches a bridged agent
  ([`agent/_bridge/sandbox/bridge.py`](../src/inspect_ai/agent/_bridge/sandbox/bridge.py)).
  The bridge's model service, started before the body, stays tracked, so a
  bridged agent's model requests are known work, and so are its bridged
  host tool calls.

### Held spans

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

### Suspensions

Work done inside a suspension is not known work. A `sample_wait()` block,
which `suspend_working_limit()`, approvals, reviews, sentinel monitors,
human input, the pause hold, the connection-slot wait and the backoff sleep
use, marks its context as suspended, and no span opens there. An approver's
or a monitor's own model calls and tool calls therefore never restart the
agent's clock. `SampleWait` objects that close from another task (the batch
queue, `sample_waiting_for()`) hold the work of the context that opened
them but suspend nothing, since no work runs inside them.

The suspension only stops new spans from opening; it does not hide the work
around it. A wait opened by a task started inside a suspension still holds
the enclosing work, so if that task outlives the suspension the enclosing
work stays held until its wait ends. Outside a running sample,
`sample_wait()` does nothing, so a sample started inside it (an `eval()`
call wrapped in `suspend_working_limit()`) is not suppressed.

## Known waits

| Known wait | Where the span opens and closes |
| --- | --- |
| `concurrency()` semaphore wait, including max sandboxes and max subprocesses | `sample_waiting_for()` ([`_util/working.py`](../src/inspect_ai/_util/working.py)), around the acquire, used by `concurrency()` ([`util/_concurrency.py`](../src/inspect_ai/util/_concurrency.py)) |
| Model connection-slot wait, including the adaptive limiter | `ConnectionSlot.acquire` ([`_model.py`](../src/inspect_ai/model/_model.py)) |
| Retry backoff sleep (`generate`, `compact`, `count_tokens`) | the tenacity `sleep=` wrapper `_sample_wait_sleep` in `model_retry_config()` ([`_retry.py`](../src/inspect_ai/model/_retry.py)), installed only when `sample_waits` is set, so batch admin loops stay excluded |
| Retried model attempts and provider-SDK retries | closed intervals added when known (see "Model attempts") |
| Hard-pause hold, and the slot reacquire after it | `wait_generate_dispatch` ([`_control/pause.py`](../src/inspect_ai/_control/pause.py)) |
| Tool approval and review, by a person or a model approver | `suspend_working_limit()` around the approver call in [`approval/_apply.py`](../src/inspect_ai/approval/_apply.py) and the reviewer call in [`review/_apply.py`](../src/inspect_ai/review/_apply.py) |
| Sentinel monitors, at all four stages (before and after the agent's model calls and tool calls) | `suspend_working_limit()` around the monitor run in `_run()` ([`_sentinel/_dispatch.py`](../src/inspect_ai/_sentinel/_dispatch.py)) |
| Waiting on a person (a question, a human approval) | `awaiting_human()` ([`log/_samples.py`](../src/inspect_ai/log/_samples.py)), around the dispatch of an input request and of the human approver |
| Batch request in the batcher's local queue, until its batch is submitted | a `SampleWait` in `Batcher.generate_for_request` ([`model/_providers/util/batch.py`](../src/inspect_ai/model/_providers/util/batch.py)), closed by the request's `on_submitted` callback, which the batcher calls on submission and before delivering any result or error |
| Code inside `suspend_working_limit()` | the block |
| `report_sample_waiting_time(seconds)`, the private helper | the interval `[now - seconds, now]` (see "Late waits") |

### `suspend_working_limit()`

`suspend_working_limit()` ([`util/_limit.py`](../src/inspect_ai/util/_limit.py),
exported from `inspect_ai.util`) opens a known wait for its block, so the
time counts as waiting both for `working_limit` and for the logged
`working_time`. Approval, review and sentinel dispatch use it beside
`suspend_token_limit()` and `suspend_turn_limit()`, so an approver's or a
monitor's time is not charged to the agent, just as its tokens and turns
are not.

Its contract differs from the token and turn suspensions, which suspend
metering only for code inside the block in the current task. Waiting is
sample-wide, so `suspend_working_limit()` marks the whole sample as waiting
while the block is open, except where known work runs in another task.
Model calls, sandbox commands and tool calls made inside the block are not
charged. Only code in the eval process can call it, not agent code in a
sandbox, and outside a running sample it has no effect. Its docstring says
so.

## Model attempts

`model_retry_config(..., sample_waits=True, attempts=...)` serves one retry
loop of `generate`, `compact()` or `count_tokens()`, with a `ModelAttempts`
holding the loop's attempts in flight.

- **An attempt in flight is known work.** Its intervals (the parts not held
  by a wait inside it, such as the batch queue) stay pending on the
  attempt until the retry loop is done with it, and are read as live work
  meanwhile. A step after the provider call (event completion, usage
  recording, telemetry) can still raise a retryable error, so the attempt
  stays reclassifiable until the retry-wrapped function returns.
- **A retried attempt is a known wait.** A retried attempt is one the retry
  policy classified as retryable: tenacity's `after` callback runs only for
  retryable outcomes, before the stop check. It adds `[attempt start, now]`
  as a wait and calls `ModelAttempts.retried()`, which drops the attempt's
  pending work. Only the part of it with no other known work becomes
  waiting. The last retryable attempt of a call that runs out of retries is
  credited the same way.
- **A successful attempt, and one that fails without a retry** (a
  non-retryable error, or a cancellation), is working time:
  `ModelAttempts.commit()` counts its pending intervals as work when the
  retry loop returns or raises.
- **SDK-internal retries are a known wait.** When a `generate` attempt
  succeeds with a positive `call.time`, the part of it before `attempt end -
  call.time` (the SDK's failed requests and sleeps before its last request)
  is added as a wait, and the attempt's pending work is trimmed to start at
  `attempt end - call.time` (`ModelAttempts.exclude_before()`); it stays
  pending until the retry loop returns. A missing `call.time` (`azureai`,
  in-process providers such as `hf`) and a zero `call.time` (SageMaker's
  placeholder, and the HTTP-hook fallback for a request id that was never
  registered) mean the request was not measured, so nothing is credited and
  the whole successful attempt is charged. `grok` times the whole call, so
  its split is empty. `compact()` and `count_tokens()` return no
  `ModelCall`, so a successful attempt of theirs is charged whole.
- **Cache hits** open no attempt and credit nothing.

## The timeline

Some waits are added after the fact: retried attempts, SDK-internal
retries, `add_sample_wait()` and `report_sample_waiting_time(seconds)`, which
can report any `[now - seconds, now]`, even when no model call is in
flight. A scalar total cannot de-duplicate a late report against what it
has already counted: histories `[0,1]` and `[1,2]` both total 1, but a
later report of `[1,3]` must bring them to 3 and to 2 respectively. Known
work can also be dropped after the fact (a retried attempt).

So `SampleTiming` keeps, for the whole attempt and with no folding, one
`_Timeline` of closed waits and closed known work: a sorted list of
disjoint segments, each recording whether a closed wait covers it and how
many spans' closed work covers it. Time in no segment has neither.
Adjacent segments with the same state are merged. Two prefix sums go with
it: the length of the waiting segments (a wait and no work), `E`, and the
length of all segments (a wait or work), `U`. Beside the timeline the
sample keeps the start time of the oldest open wait and the work spans
(`_WorkSpan`) that are open or awaiting classification.

- **Adding an interval.** It is clipped to the current attempt, from the
  sample clock's start to now. Adding a wait or work, and withdrawing work,
  are one operation: split the segments at the interval's ends, set the
  wait flag or change the work count over it, merge neighbours whose state
  is now equal, and refresh the prefix sums from the first changed segment.
  Overlapping additions only change a segment's state, so every addition,
  live or late, is de-duplicated exactly. A span's interval is added when
  the span is held or closes; an attempt's intervals wait for its
  classification.
- **Size.** Every segment boundary is an end of an added interval, so the
  timeline holds at most two segments per interval added, usually fewer.
  A sample has at most a few thousand spans, so memory is small. Prior
  attempts are carried as totals in the checkpoint (see "Resume
  accounting").
- **Readings.** The live wait is `L = [oldest open wait start, now]` while
  any known wait is open. The live work is the merged intervals of the
  open and unclassified spans, a handful at any time. For a window `J`,
  the waiting outside closed work is

  `x(J) = |E ∩ J| + |L ∩ J| - |U ∩ L ∩ J|`

  and `waiting(a, b) = x([a, b]) - Σ x(J)` over the live-work intervals `J`
  within `[a, b]`. Each term is a bisect into the timeline and a prefix-sum
  lookup, so a reading costs `O(s log n)` for `s` live spans and `n`
  segments. Working time over `[a, b]` is `(b - a) - waiting(a, b)`,
  clamped to `[0, b - a]` against float rounding. When a live span closes,
  it is added to the timeline, and every reading is unchanged at that
  instant.

### Late waits

- **Late waits and their own work.** A wait added after the fact would
  otherwise be covered by the reporting context's own work, which was
  active while the wait was not yet known: a tool calling `generate()`
  whose attempt is retried, for example, since the retried interval starts
  before the provider call. So the wait is withdrawn from the known work of
  the reporting context and the work enclosing it, as if it had held them
  while open. This holds for a wait reported from inside a suspension too
  (an approver reporting its wait): the suspension stops new work from
  opening there, but the work around it still owns its earlier time. Other
  tasks' work over the interval is kept. For this, the timeline counts how
  many spans' work covers each segment, and each span keeps the intervals
  it added. A withdrawal decrements the counts; a segment whose count
  reaches zero is waiting if a closed wait covers it, and leaves the
  timeline otherwise.
- **Late waits and finished work.** A custom call is usually reported after
  it returns, by when its model calls, sandbox commands and nested work
  have closed. So when a span's work is final (at close, or for a model
  attempt when the retry loop commits or drops it), it hands the intervals
  it counted, and those handed to it, to its parent span. Each interval
  keeps the span that counted it. The timeline is unchanged; only the
  record of which span can withdraw them moves up. A late report walks the
  same chain of spans and withdraws their handed-up intervals as well as
  their own: a tool that reports a five-second generate it just made reads
  0 working. A closed span still held by a task it started passes what it
  receives on to its parent; a span with no parent drops it, so once a
  top-level tool call has returned, a task it started can no longer
  withdraw its work, as at the sample's top level. A still-open top-level
  tool keeps what its finished operations hand it.
- **The retry loop's own waits** (a retried attempt, and an attempt's
  SDK-internal retries) pass `completed=False` and withdraw only the
  intervals counted by the spans on the reporting context's chain,
  wherever those have been handed, such as the work of an inner tool that
  returned while its background task's `generate()` was preparing an
  attempt that was then retried. The attempt's own work is dropped or
  trimmed on the attempt itself, and work that other tasks under the same
  span finished meanwhile stays charged.

## Limits and logged durations

Working time excludes the known waits not covered by known work, and every
duration and limit reads it from the one sample-wide timeline over its own
interval. The exact offsets each producer records are defined by the code
([`_util/working.py`](../src/inspect_ai/_util/working.py) and the producers
named below), not here.

- **Scoped limits.** A `working_limit()` node's `usage` is its elapsed time
  minus the sample's waiting time over the node's own interval, computed
  when it is read. It therefore lies in `[0, elapsed]` and picks up waits
  recorded after the fact, such as a retried attempt that began before the
  node was entered. Outside a running sample a scoped limit measures
  wall-clock time.
- **Monitor.** `monitor_working_limit` checks the sample's working limit
  once a second. An open wait stops the clock in real time, so no wait is
  credited in advance. The pause gate keeps a tick loop only to bound how
  long an escape from a hold takes.
- **Attempts in flight.** An attempt in flight is charged until it is known
  to have been retried, so a limit can trip during an attempt that is later
  retried.
- **Event durations.** `ToolEvent` and `SubtaskEvent` working times are the
  sample-wide working time over the event's interval
  (`sample_working_time_since()`), read when the event completes. A held
  call's interval is excluded only where no other known work covers it, so
  a tool call held for its approval while a sibling tool runs records that
  time as working, and a retried attempt classified after the event is
  published does not change it. The producers are the tool-stage paths in
  [`model/_call_tools.py`](../src/inspect_ai/model/_call_tools.py), the
  bridged host tool call and the subtask in
  [`util/_subtask.py`](../src/inspect_ai/util/_subtask.py).
- **Event offsets.** An event's `working_start` is a reading of the
  sample's working time (`sample_working_time()`), prior attempts included
  once they are restored.
- **Logged `EvalSample.working_time`** is the current attempt's elapsed
  time minus its waiting time.

## Resume accounting

A checkpoint carries the prior attempts' wall time and working time
([`util/_checkpoint/sample_runtime.py`](../src/inspect_ai/util/_checkpoint/sample_runtime.py)),
and restore adds them back:

- Event offsets include the prior attempts' working time.
- Logged durations, `EvalSample.working_time` included, cover only the
  current attempt.
- Prior working time counts toward the root `working_limit` only on a
  normal resume; a resume for scoring enforces nothing already spent.

The checkpoint stores `sample_elapsed` (wall time of every attempt, from
the sample clock's start, so it includes time spent before restore),
`working_elapsed` and `working_waiting`. Restore falls back to the fields
older checkpoints carry when `sample_elapsed` is missing, and clamps the
prior working time to `[0, prior wall time]`, since older snapshots can
hold negative values. `time_elapsed` and `time_limit` enforcement are
separate from this.

## Accepted limitations

The rule undercounts working time whenever work Inspect does not see runs
during a known wait, and it does not try to detect that work:

- **Unseen work during a wait is free.** This covers a background process
  started through a sandbox exec tool, a sandboxed CLI agent's local
  commands, an in-process agent library's own `asyncio.gather()`, and a
  solver's or scorer's own code between known work. Work is seen only when
  it goes through a model request (`generate`, `compact()`,
  `count_tokens()`), a sandbox exec or a tool call, and not when the exec
  is inside `untracked_sandbox_execs()` (see "Known work").
- **A held span hides its sibling tasks' unseen work.** A tool call that
  starts several tasks is held while any of them waits, so its other tasks'
  unseen work during that wait is free. Their known work is still charged.
- **Retry classification is late.** An attempt in flight is charged until
  the retry policy classifies it, so a `working_limit` can trip during an
  attempt that is later retried.
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
  retryable failures, such as timeouts on very long outputs or request
  errors the retry policy retries (quota 429s on OpenAI-compatible
  providers, some Anthropic 400s). Wall-clock run time then grows without
  a cap, unless `time_limit` or the call's `timeout` and `max_retries` are
  set.

These cases are mostly multi-agent and concurrent. `working_limit` is a
backstop, and precise accounting for concurrency is too complex for that
role. `time_limit` remains the bound on real run time, and the user docs
say so.

## Compatibility

- **Logged values.** `EvalSample.working_time`, `ToolEvent.working_time`,
  `SubtaskEvent.working_time` and `working_start` keep their names and
  types (a float in seconds). Their consumers (Inspect's samples and
  events dataframes, the viewer's sample activity panel and transcript
  timing, inspect_scout, and external importers) depend only on that.
  Working time is never negative and never more than the elapsed time.
- **`report_sample_waiting_time(seconds)`** is a private helper that
  external approvers use. It adds the interval `[now - seconds, now]`,
  clipped to the current attempt, so a caller that reports the time since
  its last report every second (as METR's human approver does) merges with
  the native approval wait instead of adding to it. New code should use
  `suspend_working_limit()`.
- **`suspend_working_limit()`** is public, with the sample-wide contract
  above.
- **Checkpoints.** The `sample_elapsed` key is the only addition to the
  checkpoint payload; older versions ignore it, and restore reads older
  payloads through the fallbacks described under "Resume accounting".

## Security

No parser of untrusted data is involved. The checkpoint payload is read by
`_prior_attempts()`, which keeps the prior wall time non-negative and
clamps the prior working time to `[0, prior wall time]`. Model
output and a sandboxed agent can affect working time only through timing:
by provoking retryable failures, which count as waiting, or by working
unseen while a wait is open (see "Accepted limitations"). Both lengthen the
sample's wall-clock run time, not the logged working time, so the defence
is `time_limit`, which the docs recommend alongside every `working_limit`.

## Decisions

- 2026-10-07 (decision: Ransom, after maintainer feedback): if Inspect
  knows of anything waiting, the time counts as waiting time; otherwise it
  counts as working time. The same decision kept these
  earlier choices: the accounting is a bug fix and is on by default, with
  no opt-in mode or legacy switch; human waits count as waiting; credited
  retry time has no cap, and the docs recommend setting `time_limit` beside
  `working_limit`. `working_limit` stays a first-class feature: Inspect's
  maintainers use it as a backstop in their evals, and METR relies on it.
- 2026-10-07 (decision: Ransom): `suspend_working_limit()` is public and
  exported from `inspect_ai.util`, so code like METR's approver has a public
  way to mark time as waiting. It marks the whole sample as waiting while
  open, unlike the token and turn suspensions.
- 2026-10-13 (decision: Ransom): sentinel monitor runs at all four stages
  count as waiting, as approvers and reviewers do.
- 2026-10-15 (decision: Ransom): known work is charged even while a wait is
  open elsewhere in the sample. Each instant is working if something is
  known to be working, otherwise waiting if something is known to be
  waiting, otherwise working. This supersedes the sample-wide exemption of
  other tasks' known work in the 2026-10-07 decisions, including during
  `suspend_working_limit()` and sentinel monitors.
- 2026-10-16 (decision: Ransom): `compact()` and `count_tokens()` attempts
  are known work, like `generate`. Bridged host tool calls are known work,
  like native tool calls. Execs inside `sandbox_agent_bridge()`, including
  a bridged agent's launcher, are not known work, since Inspect cannot see
  when a bridged agent is working. A late report from one tool inside an
  agent running as a tool may withdraw a sibling tool's finished work. A
  top-level tool call's work is dropped from late reports once it returns,
  since the work it holds then is mostly finished nested operations that a
  wait opened by a task outliving it would not have stopped.

## Alternatives considered

Each was rejected as too complex or too restrictive for a backstop feature,
in line with maintainer feedback that more precise accounting was too
risky.

- **Lanes with provisional attempts.** Per-task waiting states and
  in-flight attempts resolved by outcome would stop one wait from crediting
  other work. The cost is lanes at every fork site, pending segments and
  event probes.
- **Credit only sure waits in eligible samples.** No
  credit with a sandbox or an in-process `agent_bridge()`, any concurrent
  region charged, and a warning for samples that get no credit. This closes
  the gaming routes, but it turns `working_limit` into `time_limit` for most
  real users (sandboxed agents), who depend on rate-limit and semaphore
  credit.
- **Working time equals wall-clock time**, with
  `working_limit` deprecated. This is the simplest choice, but it drops the
  credit that makes the feature useful (max-sandboxes and rate-limit
  waits).
- **Summing each call's credited waits, clamped to wall-clock time.** This
  hides negative values but keeps the double counting of overlapping
  waits.
- **Opt-in accounting with summed credits as the default.** Summed credits
  are the bug.

## Not this design

- Precise accounting under concurrency, such as per-task or per-region
  credit (see "Alternatives considered").
- A breakdown of waiting time by cause in the log.
- Making request-attributable errors non-retryable in provider retry
  policies.
