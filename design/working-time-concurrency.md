# Working time under concurrency within a sample

Status: proposed, 2026-10-01. Issue: none (design requested directly by
Ransom). Author: agent (Claude), reviewed by Codex; see the PR.

## Why

`working_limit` is documented as limiting "only the time spent working (as
opposed to retrying in response to rate limits or waiting on other shared
resources)" (`docs/_working_limits.md`). It is computed as wall-clock time
since the sample started minus accumulated waiting time. The waiting ledger
was designed for a sample that does one thing at a time. Samples now run
model requests concurrently: parallel tool calls, sub-agents, `background()`
workers, and sandboxed agents (Claude Code, Codex CLI and others) whose
requests come in through the sandbox agent bridge. Under that concurrency the
ledger is wrong in both directions.

Measured on `main` at 0321960a92, with a fake provider and the real retry
loop (one sample, `mockllm` as the eval model, the calls made from a custom
solver):

| Scenario | Wall clock | Logged `working_time` |
| --- | --- | --- |
| 4 concurrent `generate()` calls, each failing twice (0.1 s attempts, 2 s backoff) and then succeeding | 4.32 s | **−12.53 s** |
| `concurrency("k", 1)` held for 3 s by one task while a sibling waits for it | 3.01 s | **0.004 s** |
| The same 2 s request twice with `cache=True` (the second is a cache hit) | 2.01 s | **4.01 s** |
| One 4 s request under `working_limit=1` | 1.01 s | limit hit at 1.0 s, mid-request |

The consequences:

1. **Waiting can exceed wall-clock time.** Retry backoff and
   provider-internal retry time are added per call. Concurrent calls in one
   sample add their waits together, so working time stops or goes negative,
   and `working_limit` never trips.
2. **One waiting task stops the whole sample's clock.** Semaphore waits are
   merged so that the sample counts as waiting whenever at least one of its
   tasks waits, even while other tasks in the sample are doing work. A sample
   that always keeps one request queued, or one background call backing off,
   gets its other work for free. A sample can arrange this without help:
   enough concurrent requests of its own fill the connection pool, and its
   next request waits for a slot that the sample itself holds.
3. **Retries extend real run time past the limit.** Time spent on retried
   attempts is excluded from working time. A sample whose requests keep
   failing in retryable ways (timeouts on very long outputs, provider errors
   on oversized input) runs far past `working_limit` in wall-clock time. With
   (1) and (2), its other work can also go uncharged while it does.

The cache-hit row is a separate defect in the same reconciliation code (a
negative "waiting" credit); it is fixed by the same change. The last row
shows that enforcement already charges a request while it is in flight. This
design keeps that behaviour (see "Enforcement").

## Goals and non-goals

Goals:

- One definition of working time and waiting time that holds under
  concurrency within a sample. Working time never exceeds wall-clock time,
  the sample's reported (settled) working time never decreases, and one
  waiting task does not stop the clock while other work that Inspect can
  observe proceeds. Work Inspect cannot observe is the boundary in the
  last non-goal.
- One accounting model that covers every source of waiting: semaphore and
  connection-slot waits, retry backoff, provider-internal retries,
  rate-limit waits, batch waits, hard-pause holds, human approval and human
  input, and checkpoint/resume.
- A stated rule for retries the sample itself can cause, and for whether any
  cap applies.
- Scoped `working_limit()` nodes (sub-agents) measured over their own work,
  not their siblings'.
- Deterministic tests for every worked example.
- Existing evals keep their current numbers unless their authors opt in.

Non-goals:

- Token and cost limits, and reserving tokens for in-flight concurrent
  requests (out of scope per the task).
- Changing `time_limit`: it stays a wall-clock deadline.
- Attributing an event's duration to its own lane rather than to the
  sample. Event durations are made interval-correct (see "Event
  durations"), but they still measure the whole sample's working time
  during the event (see "Not this design").
- Making Inspect see concurrency it does not create, such as an agent
  library's own `asyncio.gather()` or local work inside a sandboxed agent
  beside its model requests. The design states what happens there
  (examples 12 and 13): such work can go uncharged while every request
  Inspect sees is waiting, so consequence (2) is fixed only for
  concurrency Inspect observes. Whether that boundary is acceptable is open
  question 4.

## Current behaviour

### Two ledgers

Waiting time is kept twice:

- **Sample ledger** (`SampleTiming` in `src/inspect_ai/_util/working.py:10`)
  is held in the `_sample_timing` ContextVar (`working.py:51`).
  `init_sample_working_time()` creates it when the sample's clocks start
  (`src/inspect_ai/_eval/task/run.py:2667`). `sample_working_time()`
  (`working.py:32`) is `time.monotonic() - start_time - waiting_time`. It sets
  every event's `working_start` (`src/inspect_ai/event/_base.py:26`) and the
  logged `EvalSample.working_time`, which is `total_time -
  sample_waiting_time()` (`run.py:3411`). Tool and subtask events compute
  their own `working_time` as elapsed time minus the change in the sample's
  waiting time while they ran (`src/inspect_ai/model/_call_tools.py:503`,
  `:631`; `src/inspect_ai/util/_subtask.py:128`, `:139`), so they also count
  waits from concurrent siblings.
- **Limit ledger** (`_WorkingLimit` in `src/inspect_ai/util/_limit.py:1471`).
  Each node has `usage = anyio.current_time() - _start_time - _waiting_time`.
  `record_waiting_time()` (`_limit.py:884`) credits the leaf node in the
  *reporting task's* context and every ancestor. The sample's root node is
  entered at `run.py:2691`. `monitor_working_limit()` (`_limit.py:904`)
  checks the root once a second and ends the sample when it is over the
  limit. `sample_limits().working` exposes the root to agents
  (`_limit.py:246`).

`report_sample_waiting_time()` (`working.py:41`) feeds both ledgers. The two
use different clocks (`time.monotonic()` and `anyio.current_time()`). The
two are the same under asyncio but not under trio.

### Sources of waiting and how each is reported

| Source | Where | How it reaches the ledgers |
| --- | --- | --- |
| `concurrency()` semaphore wait (sandboxes, subprocesses, web search, user code) | `src/inspect_ai/util/_concurrency.py:410` → `sample_waiting_for()` (`working.py:76`) | Merged: the time during which at least one task in the sample is waiting (`concurrent_wait_count`), reported once when the last waiter leaves (`_end_sample_wait`, `working.py:106`) |
| Model connection-slot wait, including the adaptive limiter after it shrinks on 429s | `ConnectionSlot.acquire` (`src/inspect_ai/model/_model.py:799`) → `sample_waiting()` (`working.py:57`) | Merged, as above |
| Retry backoff (`generate`, `compact`, `count_tokens`) | tenacity `before_sleep` → `on_before_sleep` (`src/inspect_ai/model/_retry.py:63`) | Direct: the whole upcoming sleep is credited *before* it starts (`_retry.py:67`), per call, added across calls |
| Failed attempts and provider-SDK retries inside a successful `generate` | `_generate` reconciliation (`_model.py:1749`) | Direct, after success: `total_time - reported_waiting_time - model_output.time`, per call, added across calls |
| Hard-pause hold of a generate or compact attempt, and the slot reacquire after it | `wait_generate_dispatch` (`src/inspect_ai/_control/pause.py:627`) | Direct, every 0.5 s while parked (`pause.py:556`, `:704`, `:712`), per call, added across calls |

Everything else counts as working time:

- **Human approval** (`src/inspect_ai/approval/_human/approver.py:53`) and
  **human input** (`src/inspect_ai/util/_input/request.py:53`). Both are
  marked with `awaiting_human()` (`src/inspect_ai/log/_samples.py:369`),
  which only updates the control channel's status.
- **Batch mode.** `call.time` comes from `HttpHooks.end_request()`
  (`src/inspect_ai/model/_providers/util/hooks.py:88`), which measures from
  `start_request()`. The batch path never sends the HTTP request through the
  hooks, so `call.time` covers the whole batch round trip. That includes the
  wait in the batcher's local queue (`batch.py:102`; a partly filled batch
  waits up to `send_delay`, default 15 s, and a full one waits for a free
  in-flight batch slot). The reconciliation therefore credits almost nothing.
- **Attempts in a `generate` call that ends in an error.** No reconciliation
  runs, so their in-flight time is charged.
- **Providers that record no `call.time`.** Examples are `azureai` and
  `grok` (gRPC). `output.time` falls back to the whole attempt
  (`_model.py:1669`), so internal retries are charged. The docs already say
  so.
- **The human agent's session.** It runs in sandbox execs and service
  requests. Its own task clock (`agent/_human/commands/clock.py`) is separate
  and unchanged.
- **Soft pause.** It holds samples before their clocks start, so it does not
  affect them (`design/ctl/pause-resume.md`).

### Defects visible in the code

- **Summing.** Direct reports are added per call. `design/ctl/pause-resume.md`
  already notes "simultaneous backoffs double-credit identically today" and
  names "a sample-level overlap guard" as follow-up work. This design is
  that follow-up.
- **Merging is too generous.** "At least one task waiting" counts the whole
  sample as waiting (measured above).
- **Merged spans go to the wrong scoped limit.** A merged span is reported
  from the context of the task whose wait ended last. A scoped
  `working_limit()` in that task gets the whole merged span, even when most
  of the span came from a sibling outside its scope.
- **Cache hits add working time.** A cache hit returns the stored output
  with the original call's `time`, so the reconciliation reports
  `total_time - 0 - original_time`. That is negative, and it increases
  working time by the original request's duration (measured above).
- **The monitor's model-event guard never fires.** `monitor_working_limit`
  skips its check "if there is an active model event"
  (`_limit.py:930`). `_active_model_event` is a ContextVar set in the
  generating task (`log/_samples.py:735`). The monitor runs in its own task,
  started before any model call, so it never sees one. The experiment above
  confirms this: the limit fires mid-request.
- **The default timing object is shared.** The `_sample_timing` default is
  one module-level `SampleTiming()`, so waits reported outside a sample
  change that shared object.

### Checkpoint and resume

`dump_sample_runtime()` (`src/inspect_ai/util/_checkpoint/sample_runtime.py:13`)
stores the root node's `usage` and `_waiting_time` as `working_elapsed` and
`working_waiting`. Restore moves the root node's origin back
(`sample_runtime.py:190`) and moves the sample ledger's origin back by the
prior working time (`:202`). As a result, `working_start` keeps rising across
attempts, while the logged `working_time` covers only the current attempt.

## Design

### Meaning

**Working time** is the wall-clock time during which the sample is making
progress or could be. **Waiting time** is the wall-clock time during which
the sample can make no progress because everything it is doing is held back
by something outside it. That covers shared-capacity limits, provider rate
limits and failures, operator pauses and a person it is waiting on. Waiting
time is a subset of the sample's timeline, so:

- `working_time + waiting_time = wall-clock time`, and both are
  non-negative. `working_time ≤ total_time` always holds.
- Each instant counts as one or the other, once. Concurrent waits never add
  up.

**`time_limit` and `working_limit`.** `time_limit` bounds real run time. It
is the backstop for everything this accounting credits, including retries
the sample may have caused. `working_limit` bounds the time the sample
spends working, so it is useful only when it is below `time_limit`.
Evaluators who want both a fair budget under contention and a bound on real
run time set both.

### Lanes

A sample's concurrent work runs in **lanes**. A lane is a line of work that,
when not waiting, is presumed to be working. The sample's main task is the
root lane. Inspect's own fork points give each child its own lane. Where a
parent blocks on its children, the parent's lane is marked **joined** for
that time (see "Fork and join sites").

At any instant each lane is in one of four states. They are evaluated in
this order:

| Lane state | Condition |
| --- | --- |
| waiting | at least one wait span is open in the lane |
| in flight | no wait open, and at least one model attempt open |
| idle | joined, with no wait or attempt open |
| active | anything else |

A joined lane is never active, but its own waits and attempts still count.
This matters when a parent makes its own model call while its children run,
for example host-side calls inside a sandbox-bridge body.

**The rule.** For one scope (the sample, or one scoped `working_limit()`),
an instant is classified from the lanes in that scope:

1. If any lane is **active**, the instant is working.
2. Otherwise, if any lane is **in flight**, the instant is provisional. It
   becomes working if any of the attempts open at that instant turns out
   productive, and waiting if none does (see "Model attempts").
3. Otherwise, if any lane is **waiting**, the instant is waiting.
4. Otherwise (no lanes, or only idle ones), the instant is working.

Rule 4 covers a sandboxed agent between requests: Inspect sees no work but
the agent is doing its own, so the instant is charged.

Within one lane the state is a union: one open wait makes the lane waiting.
Concurrency that Inspect does not create, such as an agent library's
`asyncio.gather()` or a user's own task group, stays inside the caller's
lane. It therefore falls back to today's merged behaviour (consequence (2)
remains for it) but never to summing (consequence (1) is gone everywhere).
When the untracked children are simply awaited by a parent that does
nothing else, which is the common shape (for example `call_tool_task` under
`run_one` at `_call_tools.py:611`, or the task `subtask()` creates through
`tg_collect` at `src/inspect_ai/util/_subtask.py:154`), the union is the
correct answer.

A sandboxed agent behind the bridge is the other unobserved case. Its
requests reach the host as lanes, but its local work (shell commands, builds,
its own tool loop) does not. While at least one of its requests is waiting
and none is in flight, the instant is waiting, even if the agent is running
a long local command at the time (example 12).

### Worked examples

Times are seconds from the sample's start. "Today" is the measured or
code-derived result on `main`; "Proposed" is the result under this design.

| # | Scenario | Today | Proposed |
| --- | --- | --- | --- |
| 1 | Four lanes (`collect`), each: attempt 0.1 fails (retryable), backoff 2, attempt 0.1 fails, backoff 2, attempt 0.1 succeeds. Wall 4.3 | working −12.5 | All lanes in flight or waiting throughout; the failed attempts resolve as waiting, so the only productive time is the final 0.1 s. Working 0.1, waiting 4.2 |
| 2a | Lane A holds `concurrency("k",1)` doing work for 3 s; lane B waits on it | working 0.0 | A is active throughout. Working 3.0 |
| 2b | Main lane works for 600 s; a `background()` lane's monitor call is rate-limited the whole time | working ≈ 0 | Main lane active. Working 600 |
| 2c | Sample fires 11 sub-agent requests at a 10-slot pool; one waits 30 s for a slot | 30 s credited | 10 lanes in flight and all succeed. Working 30 |
| 3a | A sandboxed agent re-sends a request that the provider rejects with 400 (not retried by Inspect), 20 times at 1 s each | charged 20 (no reconciliation on failure) | Charged 20: each attempt resolves as productive (non-retryable) |
| 3b | A request whose 300 s attempts keep timing out (retried), with nothing else running | backoff credited, and the failed attempts too if the call eventually succeeds; wall clock unbounded without `timeout` or `time_limit` | All credited (retryable, no other lane active). The bound is `time_limit` and the call's `timeout` and `max_retries`. No new cap (see "Retries the sample can cause") |
| 3c | As 3b, while another lane runs sandbox commands through Inspect | timeout credited, the other lane's work free | The other lane is active, so working. Retries give no free time to work Inspect observes |
| 3d | A request-attributable error that the provider's policy still retries: an OpenAI-compatible provider's `insufficient_quota` 429, an Anthropic 400 whose body contains "overloaded", or a 401 under an API-key override hook; retried until `max_retries` is exhausted | backoff credited; attempts charged (the call ends in an error, so no reconciliation) | attempts and backoff credited, including the last attempt, because credit follows the retry policy (see "Retries the sample can cause") |
| 4 | One attempt 0–10 s succeeds; `call.time` = 4 (SDK retried internally before the last HTTP request) | 6 s credited after success | 0–6 waiting, 6–10 working |
| 5 | A cache hit after a 2 s original call | working +2 | No attempt opened. The hit costs only its local time |
| 6 | Lane A attempt 0–10 fails (retryable); lane B attempt 5–15 succeeds | A's 10 s credited via reconciliation, if A's call later succeeds | 0–5 waiting, 5–15 working |
| 7 | `collect()` parent joined; both children back off 0–20, then both run | 40 credited (two backoffs, summed) | 0–20 waiting; then working |
| 8 | Sandbox agent bridge: no request in flight 0–5; one request backing off 5–25; one in flight 25–30 while another backs off | 25 credited: 20, plus the second request's 5 s backoff while the other was in flight | 0–5 working (rule 4), 5–25 waiting, 25–30 working if the in-flight attempt succeeds |
| 9 | Parallel sub-agents A and B, each inside its own `working_limit(60)`; A backs off while B works | Sample: A's backoff credited, B's work free. A's limit: own backoff credited | Sample: working. A's scope: waiting. B's scope: working |
| 10 | `pause --now`: every lane's generate parked for 120 s | 120 s per parked call, summed | 120 waiting, with no incremental credit needed (the open spans stop the clock) |
| 11 | One lane awaits human approval for 300 s, with nothing else running | charged 300 | 300 waiting |
| 12 | Sandbox agent bridge: one request backs off 0–60 while the agent runs a 60 s build inside the sandbox | 60 credited (the backoff) | 60 waiting: the build is not visible to Inspect and goes uncharged (open question 4) |
| 13 | An agent library run in-process issues two requests with its own `asyncio.gather()`: one backs off 0–60, the other is in flight 0–60 and succeeds | 60 credited (the backoff) | both share the caller's lane, which is waiting while either waits: 60 waiting, the in-flight work uncharged (open question 4) |

### Classification of each source

| Source | Proposed |
| --- | --- |
| `concurrency()` semaphore wait | wait span on the waiting lane; holding the semaphore is active |
| Model connection-slot wait, including the adaptive limiter | wait span |
| Retry backoff sleep (`generate`, `compact`, `count_tokens`) | wait span around the actual sleep. Cancelling mid-sleep credits only the time slept |
| A `generate` attempt in flight | in flight; resolved by outcome (see "Model attempts") |
| Retried (retryable) `generate` attempt | resolved fully non-productive: waiting unless another lane was active |
| Non-retryable failure, cancellation, or an attempt never resolved | resolved productive: charged |
| Provider-SDK retries inside a successful attempt | the part before `end - call.time` is non-productive, the rest productive |
| `compact` and `count_tokens` attempts | active (charged), as today. Only their backoff is a wait |
| Cache hit | no attempt; local work |
| Hard-pause hold, and the slot reacquire after it | wait span |
| Batch request in the batcher's local queue, until its batch is submitted | wait span |
| Submitted batch request at the provider | in flight, as for any attempt (productive on success, as today) |
| Human approval and human input (`awaiting_human`) | wait span |
| Human agent session | active, as today |
| Rate-limit waits | these are the backoff and adaptive-slot waits above; no separate mechanism |
| Checkpoint/resume | prior working and waiting carried as offsets (see below) |

**Retries the sample can cause.** Credit follows the retry policy exactly:
an attempt is credited when `Model.should_retry()` (`_model.py:1765`, the
predicate behind `retry_if_exception` at `_retry.py:127` and `:170`) says
to retry it, and charged otherwise. The accountant does not second-guess
that policy. Most request-attributable errors are not retried and are
therefore charged: 4xx validation errors, context length, refusals and
`content_filter`. A loop that re-sends such requests is charged in full,
whether the loop is in a sandboxed agent, in the bridge's `retry_refusals`,
or in the solver.

The policy does retry some errors that the request can cause, and those
attempts are credited:

- **Quota exhaustion on OpenAI-compatible providers.** `openai_classify_retry()`
  classifies every `RateLimitError` and HTTP 429 as `rate_limit`
  (`src/inspect_ai/model/_openai.py:1539`), including `insufficient_quota`.
  `OpenAIAPI.should_retry()` skips quota errors only by matching the
  message "You exceeded your current quota"
  (`src/inspect_ai/model/_providers/openai.py:704`), and
  `OpenAICompatibleAPI` (`openai_compatible.py:412`) has no such check.
- **Some Anthropic 400s.** A body containing "overloaded" or "internal
  server error", and a 400 for truncated JSON, are retried as transient
  (`src/inspect_ai/model/_providers/anthropic.py:1835`).
- **401 under an API-key override hook.** `Model.should_retry()` retries an
  authentication failure when a hook overrides API keys (`_model.py:1825`).

These attempts are credited even when the retries run out and the call
fails, because tenacity's `after` callback runs before the stop check
(example 3d). Today they are charged in that case, since no reconciliation
runs when the call ends in an error. This design does not change the retry
policy; making these errors non-retryable is separate work (see "Not this
design").

Retryable failures the sample can provoke (timeouts on very long outputs,
provider errors on unusual input) cannot be told apart from infrastructure
failures with any reliability, and the documented contract credits
"unsuccessful model generations". This design keeps crediting them, with two
limits:

- under the lane rule they are credited only when nothing else that Inspect
  observes in the sample is active, so they cannot buy free time for
  observed work. Work Inspect does not observe is the boundary in examples
  12 and 13; and
- the real run time they add is bounded only by settings the evaluator
  chooses: the sample's `time_limit`, and the call's `timeout` and
  `max_retries`. All three are optional, and the retry stop condition is
  checked only after an attempt returns (`_retry.py:147`). With none of
  them set, a sample can retry indefinitely today and under this design.

No new cap is added. An optional cap is open question 3.

### The accountant: `WorkingClock`

New class in `src/inspect_ai/_util/working.py`. One instance per scope. All
methods are synchronous; they are called only from the event loop thread.
No lock is needed, because the calls do not interleave between `await`
points (AGENTS.md, "No speculative locks"); the class docstring says so.

```python
LaneId = int
AttemptId = int

@dataclass
class _LaneState:
    waits: int = 0                     # open wait spans in this lane
    attempts: set[AttemptId] = field(default_factory=set)
    joined: int = 0                    # nesting depth of lane_joined()

class _Pending(NamedTuple):
    start: float
    end: float
    attempts: frozenset[AttemptId]     # attempts open during [start, end)

class WorkingClock:
    def __init__(self, now: Callable[[], float], lanes: Iterable[LaneId] = ()) -> None: ...

    # lane membership
    def add_lane(self, lane: LaneId) -> None: ...
    def remove_lane(self, lane: LaneId) -> None: ...
    def join(self, lane: LaneId) -> None: ...
    def unjoin(self, lane: LaneId) -> None: ...

    # activity
    def begin_wait(self, lane: LaneId) -> None: ...
    def end_wait(self, lane: LaneId) -> None: ...
    def begin_attempt(self, lane: LaneId, attempt: AttemptId) -> None: ...
    def end_attempt(self, lane: LaneId, attempt: AttemptId) -> None: ...
    def resolve_attempt(self, attempt: AttemptId, productive_from: float) -> None: ...

    # readings
    def working_time(self) -> float: ...          # upper bound: provisional counted as working
    def settled_working_time(self) -> float: ...  # lower bound: provisional excluded
    def elapsed(self) -> float: ...
    def restore(self, prior_working: float, prior_waiting: float) -> None: ...
    def close(self, at: float | None = None) -> None: ...  # resolves leftovers as productive, freezes
```

State: `_lanes: dict[LaneId, _LaneState]`, `_mark` (start of the open
segment), `_working` and `_waiting` (settled seconds), `_pending:
list[_Pending]`, plus `_prior_working` and `_prior_waiting` from a
checkpoint.

**Advancing.** Every mutating method first calls `_advance(now())`. That
closes the segment `[_mark, now)` with the classification of the state
*before* the change:

- working adds to `_working`;
- waiting adds to `_waiting`;
- provisional appends `_Pending(_mark, now, open_attempts)`, merged with
  the last entry when it is contiguous and has the same attempt set.

Then `_mark = now`. Classification walks `_lanes` with the rule above and
returns `"working"`, `"waiting"` or the frozenset of attempts open in
in-flight lanes. A scope has a handful of lanes, so the walk is cheap.
Counters are an optimisation the implementer may add.

**Model attempts.** `end_attempt` removes the attempt from its lane when the
provider call returns or raises. `resolve_attempt` can come later, once the
retry policy has decided. `productive_from` is:

| Outcome | `productive_from` |
| --- | --- |
| success | `max(attempt_start, attempt_end - output.time)` (`output.time` is `call.time` when the provider recorded one, else the attempt's duration) |
| retryable failure | `attempt_end` (nothing productive) |
| non-retryable failure, cancellation, or still unresolved at `close()` | `attempt_start` (all productive) |

Resolving attempt `a` rewrites each pending segment that contains `a`.
Segments are split at `productive_from` when needed:

- the part at or after `productive_from` is settled as working;
- the part before it has `a` removed from its attempt set; if the set is
  then empty, that part is settled as waiting, and otherwise it stays
  pending.

The pending list holds only the segments that overlap unresolved attempts.
Its length grows with the transitions that happen while any attempt is
unresolved, so one long attempt beside many short ones can build a long
list. To keep resolution cheap, the clock also keeps an index from each
unresolved attempt to its pending segments, so resolving an attempt touches
only the segments that contain it. Segments leave the list as soon as their
attempt sets are empty. A stress test (see "Testing") puts a number on the
cost.

**Readings.**

- `working_time() = _prior_working + _working + Σ pending + (now - _mark if
  the open segment is not waiting)`. This is an upper bound and is used for
  limit enforcement.
- `settled_working_time()` is the same with pending and provisional time
  left out. It is a lower bound. It never decreases, because pending time
  can only resolve to working (an increase) or to waiting (no change).
  It sets `working_start`, so event start times stay monotonic. It is
  not used for event durations, because a difference of two settled
  readings can include earlier work that resolved during the event (see
  "Event durations").
- After `close()` nothing is pending and the two readings are equal. The
  logged value is therefore exact.

### Event durations

`ToolEvent.working_time` and `SubtaskEvent.working_time` are durations: the
working time inside the event's own interval. A difference of two sample
readings cannot give that, because a provisional segment from before the
event can resolve during it. For example, an attempt runs 0–6 and succeeds;
a tool runs 5–6. The settled reading goes from 0 to 6 during the tool, so
the difference would charge 6 seconds to a 1-second tool.

Event durations therefore use **probes** on the sample clock:

```python
class WorkingProbe:
    def working_time(self) -> float: ...   # working time within [opened, now)
    def close(self) -> float: ...          # idempotent: detaches on first call, returns the frozen value

def open_working_probe() -> WorkingProbe | None:  # concurrent mode only
```

- Opening a probe calls `_advance(now)`, so the next segment starts at the
  probe's start time.
- Every segment the clock closes while the probe is open adds its length to
  the probe if it is working or provisional, and nothing if it is waiting.
  A probe therefore sees only time inside its own interval and can never
  exceed the event's elapsed time.
- Provisional time counts as working, as it does for enforcement. A probe
  is not reduced when a provisional segment later resolves as waiting. The
  duration is an upper bound restricted to the event's interval, which is
  the conservative choice.
- The first `close()` adds the open segment up to now (unless it is
  waiting), removes the probe from the clock and freezes the value. Later
  calls return the frozen value and do nothing else, so the normal
  completion path and a cleanup path can both call it safely.

**Ownership and cleanup.** An open probe adds work to every segment
transition and accumulates time until it is closed, so every probe has one
owner that closes it on every exit, including exceptions and cancellation.
Unfinished events are logged as they are today; only the probe's
lifetime is specified here.

- **Subtasks** (`src/inspect_ai/util/_subtask.py`). The probe is opened at
  the baseline (`:128`) and closed in a `finally` around the `await
  func(...)` (`:135`). The completion path (`:139`) reads the frozen value.
  A subtask that raises, whose exception the solver catches before carrying
  on, or that is cancelled leaves no probe behind.
- **Tool stages** (`src/inspect_ai/model/_call_tools.py`). The stage owns a
  dict of its probes. Probes are opened at the baselines (`:503`) only for
  calls that will execute: skipped calls (`:546`) open none and keep
  `waiting_time=0`. The completion sites (`:591`, `:631`, `:699`, `:787`)
  close their call's probe. A `try/finally` around the whole stage,
  including the outer task group (`:728`), closes every probe still open.
  The existing `except Exception` at `:739` does not catch cancellation,
  which is why the cleanup is a `finally`.
- **Backstop.** The sample clock's `close()` detaches any probe still open
  and logs a warning once per sample, so a missed cleanup costs accuracy
  but cannot grow without bound. The tests assert that the warning never
  fires.

The producers pass `waiting_time = elapsed - probe.close()` to the existing
setters, so `ToolEvent._set_result()` (`src/inspect_ai/event/_tool.py:107`)
and the event schema do not change. In legacy mode these sites keep today's
`sample_waiting_time()` deltas. A probe costs one list entry on the sample
clock while it is open.

### Scopes: the sample and scoped `working_limit()`

Every place that needs working time owns a `WorkingClock`. The sample owns
one in `SampleTiming.clock`, and every `_WorkingLimit` node opened in
concurrent mode owns one. The **scope chain** of a context is the clocks of
the working-limit nodes from `working_limit_tree.get()` up to the root,
followed by the sample's clock. Every lane, wait and attempt event is
applied to each clock in the chain captured when the event begins. A wait's
end and an attempt's resolution go to the same clocks as its begin, even if
a node has since closed: a closed clock ignores events.

- `_WorkingLimit.__enter__` (concurrent mode) creates its clock with the
  current lane, which is executing and therefore active. Lanes forked
  inside the node register with it, because the child's context inherits
  the node. The node's `usage` is `clock.working_time()`, and its `__exit__`
  closes the clock.
- A scoped limit therefore measures the work of the lanes inside its scope.
  It is not charged for a sibling's work (example 9), and merged spans no
  longer go to whichever task finished last.
- The monitor checks the root node, as today. Scoped nodes are checked at
  `check_working_limit()` call sites, as today.

### Fork and join sites

Two context managers in `working.py`:

```python
@asynccontextmanager
async def work_lane() -> AsyncIterator[None]:
    """Run the enclosed block in a new lane registered with the current scope chain."""

@contextmanager
def lane_joined() -> Iterator[None]:
    """Mark the current lane joined (it cannot be active) while the block runs."""
```

`work_lane()` sets the `_lane` ContextVar in the child task. The root lane is
set by `init_sample_working_time()`. Lane ids come from an
`itertools.count()` on the `SampleTiming`. Sites:

| Site | Change |
| --- | --- |
| `collect()` (`src/inspect_ai/util/_collect.py:36`) | each `run_task` in `work_lane()`; the task group inside `lane_joined()` |
| `fork()` with a list of solvers (`src/inspect_ai/solver/_fork.py:48`) | each partial passed to `tg_collect` wrapped so that `solver_subtask` runs in `work_lane()`; the `tg_collect` inside `lane_joined()`. The wrapping is in `fork()`'s list branch, not in `solver_subtask` itself |
| `fork()` with a single solver (`_fork.py:45`) | no change: `solver_subtask` runs in the caller's lane, so the caller's lane carries the child's waits (the task that `subtask()` creates inherits that lane) |
| Parallel tool-call stages (`_call_tools.py:728`) | each `run_one` in `work_lane()`; the stage's outer task group inside `lane_joined()` |
| `background()` (`src/inspect_ai/util/_background.py:81`) | `run` in `work_lane()`; the caller is *not* joined (it keeps working) |
| Deep agent `agent_wait` (`src/inspect_ai/agent/_deepagent/lifecycle_tools.py:306`) | both wait modes inside `lane_joined()` (the parent blocks on background lanes) |
| Sandbox service request handler (`SandboxService._handle_request_tracked`, `src/inspect_ai/util/_sandbox/service.py:397`) | each request in `work_lane()`. This covers bridged model requests and bridged host tools; the human agent's commands get lanes too and stay active |
| `sandbox_agent_bridge()` body (`src/inspect_ai/agent/_bridge/sandbox/bridge.py:244`) | `yield bridge` inside `lane_joined()`: the solver lane hands its work to the sandboxed agent |

Outside a running sample (the default `SampleTiming`, which has no clock),
every helper does nothing.

### Instrumentation of each waiting source

Helpers in `working.py`. Each checks the sample's accounting mode, so the
call sites stay the same in both modes:

```python
@contextmanager
def sample_wait() -> Iterator[None]:
    """Open a wait span on the current lane (concurrent mode; no-op in legacy)."""

def begin_model_attempt() -> ModelAttempt | None:
    """Open an attempt on the current lane (concurrent mode only)."""

class ModelAttempt:
    def end(self) -> None: ...                     # provider call returned or raised
    def succeeded(self, output_time: float | None) -> None: ...
    def retryable_failure(self) -> None: ...
    def charge(self) -> None: ...                  # non-retryable / cancelled / leftover; idempotent
```

- `sample_waiting()` and `sample_waiting_for()` keep their legacy merging in
  legacy mode and become `sample_wait()` spans in concurrent mode.
- `report_sample_waiting_time()` and `record_waiting_time()` become no-ops in
  concurrent mode. A lump credit cannot be placed on the timeline, so no
  concurrent-mode code calls them. The generate closure, the pause gate's
  incremental credits and the reconciliation all stay unchanged as the
  legacy path.
- **Backoff.** `model_retry_config()` gains a tenacity `sleep=` callable that
  wraps `anyio.sleep` in `sample_wait()`. It is installed whenever
  `report_waiting_time` is not `None`, so batch admin loops (which pass
  `None`) still record nothing. `ModelRetryConfig` gains the `sleep` key.
- **Attempts.** In `Model._generate`'s inner `generate()`, the attempt opens
  at `time_start` (`_model.py:1560`) and `ModelAttempt.end()` runs in the
  existing `finally`. Cache hits return before this point and open no
  attempt. `succeeded(output.time)` runs after `output.time` is set
  (`_model.py:1669`). `model_retry_config()` gains an optional
  `after_retryable` callback passed as tenacity `after=`, which tenacity
  runs only when the retry predicate returned true and before the stop
  check. `_generate` passes one that calls `retryable_failure()` on the
  current attempt. A `finally` around the whole retry call calls `charge()`
  on any attempt still unresolved: the exception escaped because it was not
  retryable, or the call was cancelled.
- **Hard pause.** `wait_generate_dispatch` (`pause.py:627`) wraps the park
  loop and the reacquire in `sample_wait()`. The 0.5 s incremental credits
  remain for legacy mode. The tick loop stays, because it also bounds how
  long an escape takes.
- **Human waits.** `ActiveSample.awaiting_human()` (`log/_samples.py:369`)
  opens `sample_wait()` for its duration.
- **Batch local queue.** `BatchRequest` gains `submitted: anyio.Event`. The
  batcher sets it once the request's batch is accepted by the provider, and
  also before delivering any result or error, so a waiter can never block
  past its result. `generate_for_request` (`batch.py:102`) awaits it inside
  `sample_wait()` before awaiting the result.

### Enforcement and the monitor

The root node's `usage` is the upper-bound `working_time()`. An attempt in
flight is charged until it resolves, as it is today (the fourth row of the
"Why" table). A retryable failure is credited back when it resolves, so
`usage` can fall at that point, as it does today when the reconciliation
runs. The monitor and the `check_working_limit()` call sites are unchanged.
Open wait spans stop the clock in real time, so a wait no longer needs to be
credited in advance or in ticks to keep the monitor from firing during it.
That is why backoff and hold spans are simple context managers here.

### Checkpoint and resume

The payload keys stay the same (`working_elapsed`, `working_waiting`).

- `dump_sample_runtime()` writes the root clock's `working_time()` and
  `elapsed() - working_time()` in concurrent mode, and the node fields in
  legacy mode.
- `restore_sample_runtime()` always gives the sample clock the prior
  working time as `_prior_working`, so `sample_working_time()` and
  `working_start` keep rising (today's line `:202` does the same for both
  resume kinds). Only with `check=True` does it also call
  `root.clock.restore(prior_working, prior_waiting)` before the limit
  checks, matching today's `:190`.
- The logged `working_time` stays attempt-local: `settled_working_time()`
  minus `_prior_working`.
- A `resume_for_scoring` restore arms nothing, as today.
- The mode is read from the eval config, which a resume reuses, so both
  attempts use the same accounting.

### Configuration: opt-in, legacy by default

The new accounting changes when `working_limit` trips, so it changes eval
trajectories. Following the rule that such changes apply only under
explicit configuration (decision: Ransom, 2026-09-15), it is selected by a
new option:

```python
working_time_accounting: Literal["legacy", "concurrent"] | None = None  # None means "legacy"
```

- **Surfaces.** The option is accepted wherever `working_limit` is accepted,
  with the same precedence (eval overrides task): `Task(...)`,
  `task_with()`, `eval()`, `eval_async()`, `eval_set()`, CLI
  `--working-time-accounting` on `inspect eval` and `inspect eval-set`.
- **Recording.** It is stored as an optional field on `EvalConfig`
  (`src/inspect_ai/log/_log.py:94`). `eval_retry()` reads it back the way it
  reads `working_limit` (`src/inspect_ai/_eval/eval.py:1819`).
- **Task identity.** In `eval_set_overrides.py` it is listed in
  `NOT_OVERRIDABLE` as "part of task identity". It joins the task-identifier
  hash only when it is not `None`, so existing identifiers do not change.
- **Mode lookup.** `init_sample_working_time(start, accounting)` stores the
  resolved mode on `SampleTiming`, and every helper reads it there.
- **Legacy mode** runs today's code paths unchanged. Its numbers are
  today's, including the defects listed above. The new helpers are no-ops.
- **Concurrent mode** runs only the new paths. The legacy reporters are
  no-ops.

Each instrumented site calls both kinds of helper, and exactly one kind acts.
Removing legacy mode later means deleting the legacy reporters and the mode
check. The alternative of making concurrent the default is an open question
below.

### Clock source

Every `WorkingClock` in a sample uses `SampleTiming.now`, which is
`time.monotonic` in production. That removes the mismatch between
`time.monotonic()` and `anyio.current_time()` in concurrent mode. Tests
inject a fake clock through `init_sample_working_time(..., now=fake)` and
patch the backoff sleep's module-level `_sleep` indirection to advance the
fake clock. The `_sample_timing` default stays as it is, so legacy readers
outside a sample behave as today. The default object has no clock
(`clock is None`), so every concurrent-mode helper does nothing outside a
sample.

### Cancellation and errors

- Wait spans and lanes are context managers, so cancellation closes them.
- Attempts are always resolved: by the outcome hooks, otherwise by the
  `finally` around the retry call (`charge()`), and otherwise by `close()` at
  sample end.
- A clock event for a lane the clock does not know (an accounting bug, for
  example an unbalanced join) logs a warning once per sample and is
  ignored, because an accounting bug must not fail a sample. A test covers
  this behaviour, and the wiring tests assert that no such warning is
  logged.
- The sample clock's origin is the `start_time` passed to
  `init_sample_working_time()` (`run.py:2667`), the same instant `total_time`
  is measured from. `create_eval_sample` closes it with `close(at=end)`, at
  the instant it computes `total_time`, so the logged `working_time ≤
  total_time` holds exactly. In concurrent mode the logged value is the
  sample clock's attempt-local settled working time, not `total_time -
  sample_waiting_time()`.

## Alternatives considered

- **Merge everything (waiting when at least one task waits).** Extending
  today's semaphore merging to retries and holds fixes summing
  (consequence 1) with no lanes. It leaves consequence 2 in place and can
  be used to stop the clock deliberately (examples 2b and 2c), and a limit
  that can be pushed to zero is not a limit. It is what untracked
  concurrency falls back to.
- **Sum per task (today's retry path), clamped to wall clock.** This is a
  one-line fix for negative values, but a sample with two lanes reaches the
  clamp twice as fast. It hides the bug rather than defining a meaning.
- **Proportional sharing (the clock runs at the fraction of lanes not
  waiting).** It is closer to the critical path in fork-join shapes, where
  the "any active" rule over-charges a little: if child A backs off while
  child B works and A then works, both stretches are charged, although
  without contention they would have overlapped. It needs the same lanes, makes every number
  depend on the lane count, and a sample can change its count with idle
  lanes. The over-charge in "any active" is bounded by work that really
  ran, and a limit should err toward charging.
- **Charge every failed attempt (no provisional state).** This is much
  simpler: no pending segments, and the strongest answer to consequence 3.
  It breaks the documented contract ("unsuccessful model generations" are
  excluded) and would charge infrastructure stalls. The stream-idle-timeout
  design cites 16% of calls hanging against a 600 s timeout, which would be
  charged to every sample that met them. Rejected as the default. It could
  be added later as a third mode.
- **Infer lanes from task identity instead of fork sites.** anyio has no
  portable way to learn when a task exits (asyncio's done callbacks have no
  trio equivalent), so tasks could never be removed from the active set.
- **Lane-less "every open model call waiting" rule.** Treat the sample as
  waiting when every open model call is in a waiting phase, and ignore
  other work. No fork-site changes are needed, but a sandbox exec or tool
  running beside a backing-off call is free (example 2b with a tool
  instead of a model call), which is consequence 2 again.
- **One sample-wide clock for scoped limits (`usage` = change in sample
  working time).** No per-node clocks are needed, but parallel sub-agents
  are charged for each other's work (example 9), which is a regression from
  today's per-context crediting.
- **Default-on with no legacy mode.** This gives one code path and fixes
  every eval. It changes results for existing evals that set
  `working_limit` and use concurrency, approval or caching, with nothing
  for their authors to opt out of. Offered as the alternative in the open
  questions.

## Compatibility and migration

No migration is required. Legacy mode is the default and reproduces today's
behaviour. Evals that opt in see the following.

- **Reported `working_time`** (`EvalSample.working_time`, the samples
  dataframe `working_time` column, the viewer). It is never negative and
  never above `total_time`. It is higher where concurrency used to stop the
  clock or sum waits, and lower where cache hits used to add time. It
  excludes human approval and input waits and batch local-queue time.
- **`working_limit` enforcement and `sample_limits().working.usage`** follow
  the same numbers. Agents that read the remaining working time see
  consistent values.
- **Events.** `working_start` is now monotonic and is based on the settled
  reading. Tool and subtask `working_time` come from probes: the sample's
  working time inside the event's interval, counting provisional time as
  working. They exclude only waits during which the sample could make no
  progress, not every concurrent sibling wait, and never exceed the
  event's elapsed time. The events dataframe `working_time` column and the
  viewer's tool and subtask views show these values unchanged in form.
  `ModelEvent.working_time` (`output.time`) is unchanged.
- **Scoped `working_limit()`** measures its own lanes. Code relying on a
  sibling's waits being credited to it sees more charged time.
- **Log schema.** There is one new optional `EvalConfig` field,
  `working_time_accounting`. Older readers ignore unknown fields, because
  pydantic's default is `extra="ignore"` and `EvalConfig` does not change
  it. The viewer's generated TypeScript types change, which needs a
  coordinated `ts-mono` update (`.agents/skills/land-ts-mono/SKILL.md`).
  There is no viewer UI change.
- **Dataframes.** `working_time_accounting` is added to the eval columns
  next to `working_limit` (`src/inspect_ai/analysis/_dataframe/evals/columns.py:121`),
  so analyses can separate the two kinds of numbers.
- **Older Inspect versions.** An older version reads a concurrent-mode log
  and ignores the field. Running `eval_retry()` or an eval set's retry on
  that log with an older version silently uses legacy accounting. Supported
  boundary: the mode is honoured only by versions that know the field; the
  docs say so next to the option.
- **Downstream projections.** `inspect_flow` (task/log projections such as
  `_runner/task_log.py`) and `inspect-action` (its log importer) do not
  carry the new field. Legacy runs are unaffected. For opted-in logs,
  reconstruction in those tools loses the mode until they add it (see "Not
  this design").
- **Checkpoints.** The payload keys and their meanings are unchanged, so
  snapshots restore across versions. A snapshot from a legacy run resumed
  under the same config stays legacy.
- **Eval sets.** The task identifier changes only for tasks that set the
  option.
- **Private APIs.** `report_sample_waiting_time`, `record_waiting_time`,
  `sample_waiting` and `sample_waiting_for` keep their signatures. Satellite
  repos (`inspect_swe`, `inspect_evals`, `inspect_flow`, `inspect_scout`,
  `inspect-action`) do not use them; checked by grep on 2026-10-01.
- **Docs.** `docs/_working_limits.md` and `docs/setting-limits.qmd` describe
  both modes. The CHANGELOG entry is part of the implementation PR.

## Security

No untrusted content reaches the new code. The accountant receives only
timestamps, lane ids and attempt ids that Inspect generates, plus
`output.time`, a float a provider adapter derives from its own timers. Two
inputs can be influenced:

- **Timing from the model or sandboxed agent.** The sample can choose how
  many concurrent requests it sends, how long its outputs are and which
  requests fail. That is the gaming surface this design narrows: requests
  never sum, a saturated pool is charged, non-retryable errors are charged,
  and retryable failures are credited only when nothing else that Inspect
  observes is active. Three things remain:
  - a lone lane whose retryable failures the sample provokes, bounded only
    by `time_limit` and the per-call `timeout` and `max_retries` when the
    evaluator sets them;
  - request-attributable errors that the provider's retry policy retries
    (example 3d);
  - work Inspect does not observe: a sandboxed agent can keep one request
    backing off while it runs local commands, and an in-process agent
    library can run work beside a waiting request in the same lane
    (examples 12 and 13). That work goes uncharged. Open question 4 asks
    whether this boundary is acceptable.
- **`output.time` from a provider.** A wrong value only moves the split
  inside one attempt, and `productive_from` is clamped to the attempt's own
  interval.

Bridge request handlers get lanes from host-side code
(`_handle_request_tracked`). A sandboxed agent cannot create lanes except by
sending requests, and each request's lane lasts only while it is handled.

## Testing

All async tests run under both backends (`--runtrio` before the PR). Pure
clock tests use a fake `now`. Integration tests patch
`inspect_ai._util.working`'s `_now` and `_sleep`, and use a fake `ModelAPI`
whose attempts block on `anyio.Event`s set by the test, so the order of
events is fixed and no test waits on a sleep.

**`WorkingClock` unit tests** go in `tests/util/test_limit_working.py`, the
existing file for working-limit behaviour. There is one test per worked
example, driven by a scripted sequence of `(time, event)`, asserting
`working_time()`, `settled_working_time()` and `elapsed()`:

- examples 1, 2a, 2b, 2c, 3a, 3b, 3c, 3d, 4, 5, 6, 7, 8, 10, 11, 12 and
  13, as in the table (12 and 13 assert the documented boundary: the
  unobserved work is credited as waiting);
- example 9: one clock for the sample and one for each scoped node, fed
  through the scope-chain helper;
- probes: an attempt running 0–6 that resolves as successful during a tool
  probe opened at 5 and closed at 6 gives the probe 1 second, not 6; the
  same check for a subtask probe; a probe never exceeds its elapsed time;
  a second `close()` returns the frozen value and changes nothing;
- a stress case: one attempt open for 600 s while 10,000 short attempts in
  other lanes start, end and resolve, asserting the pending list is empty
  once everything resolves and recording the time per resolution against a
  fixed budget, so the cost of the pending index is measured;
- a provisional segment split by a successful attempt's `productive_from`,
  and one that straddles two attempts resolving in either order;
- a joined lane with its own wait counted (the bridge body's host call), and
  a joined lane with nothing open ignored;
- invariants over 500 seeded random event sequences: `0 ≤ working ≤ elapsed`,
  `settled ≤ working`, `settled` non-decreasing, and after `close()`,
  `settled == working` and `working + waiting == elapsed`;
- `restore()` offsets and `close()` resolving leftover attempts as charged;
- an unknown-lane event warns and is ignored, without raising.

**Wiring tests in concurrent mode** go in `tests/test_sample_limits.py`.
Each runs one sample with `working_time_accounting="concurrent"` and a fake
clock, and asserts `sample_working_time()` captured in the solver and the
logged `working_time`:

- four `collect()`ed calls with two retryable failures each (example 1):
  working time equals the productive attempt time, and waiting equals the
  rest of the wall clock;
- the `concurrency()` holder and waiter (example 2a), and a `background()`
  call stuck in backoff beside a working main lane (example 2b), with a
  `working_limit` that trips at the expected fake time;
- a non-retryable failure caught and re-sent by the solver, charged
  (example 3a);
- classification-driven credit (example 3d), using real SDK exception
  objects through the providers' own `should_retry`: an
  `OpenAICompatibleAPI` `insufficient_quota` 429 and an Anthropic 400 whose
  body contains "overloaded" are credited, including the final attempt
  when `max_retries` runs out; an OpenAI 400 is charged;
- a tool event and a subtask event that start while an older attempt in
  another lane is in flight and end after it resolves: their
  `working_time` covers only their own interval;
- probe cleanup, asserting the sample clock holds no open probes afterwards
  and the backstop warning never fires: a subtask that raises and whose
  exception the solver catches, three times in a row; a cancelled subtask;
  a stage with fail-fast skipped calls; and a stage cancelled while its
  calls run;
- an SDK-internal retry split using a fake `call.time` (example 4), and a
  cache hit (example 5);
- `pause --now` held by the gate test helpers in `tests/_control/test_pause.py`
  (example 10, added there);
- human approval through a test approver that blocks on an event
  (example 11);
- scoped `working_limit()` around two parallel tool calls (example 9),
  using `execute_tools` with two tools;
- cancellation mid-backoff and mid-attempt: spans close, the attempt is
  charged, and no pending segments are left;
- checkpoint round trip in `tests/checkpoint/test_sample_runtime.py`: dump
  under concurrent mode, restore, and check that `working_start` keeps
  rising and the logged `working_time` is attempt-local.

**Legacy-mode regression tests.** The same first three scenarios run in
legacy mode and assert today's numbers within tolerance, including the
negative working time in example 1. The existing working-limit, pause,
concurrency and checkpoint tests run unchanged.

**Fork-site tests.** These are spy tests asserting that a new lane is
registered and unregistered, and the parent joined, for `collect()`,
`fork()` with a list of solvers, parallel tool stages, `background()`, the deep agent's
`agent_wait`, and `SandboxService._handle_request_tracked`. A separate
test runs `fork(state, solver)` with a single solver whose `generate` backs
off, and asserts that no lane is added, the caller's lane is waiting during
the backoff, and the sample's working time does not grow. The service is
driven with a fake sandbox, as in the existing non-Docker tests in
`tests/util/sandbox/test_sandbox_service.py`, so no Docker is needed. The
`sandbox_agent_bridge()` join is covered by one Docker-gated slow test in
`tests/agent/`, which runs a sandboxed client issuing two concurrent
requests, one of which backs off. It is marked `slow`, so PR CI skips it and
the scheduled slow-test runs include it.

**Batch.** A unit test of the `Batcher` with a fake provider checks that
`submitted` is set on submission and also on a creation failure, and that
the local-queue wait is credited.

**Config plumbing.** `tests/test_eval.py` checks the option flows from
`Task` and `eval()` into `EvalConfig` and back through `eval_retry`.
`tests/test_task_identifier_version.py` checks the identifier is unchanged
when the option is unset and changes when it is set. The eval-set override
test checks the `NOT_OVERRIDABLE` entry.

## Implementation plan

Each step is one PR, or one commit if they ship together. Steps 1 to 4 have
no effect until step 5 makes the option reachable.

1. **Accountant.** `WorkingClock`, `_LaneState`, `_Pending`, the lane and
   wait helpers, `ModelAttempt`, mode and clock on `SampleTiming`, and the
   `now` and `_sleep` indirections, all in
   `src/inspect_ai/_util/working.py`. Unit tests in
   `tests/util/test_limit_working.py`.
2. **Scopes.** `_WorkingLimit` owns a clock in concurrent mode, the
   scope-chain helper, and the no-op legacy reporters in concurrent mode
   (`src/inspect_ai/util/_limit.py`). Checkpoint dump and restore
   (`src/inspect_ai/util/_checkpoint/sample_runtime.py`). Sample clock
   close and the logged value (`src/inspect_ai/_eval/task/run.py`). Tests in
   `tests/util/test_limit_working.py` and
   `tests/checkpoint/test_sample_runtime.py`.
3. **Sources.** Backoff `sleep` and `after_retryable`
   (`src/inspect_ai/model/_retry.py`); attempts in `Model._generate`
   (`src/inspect_ai/model/_model.py`); the hard-pause span
   (`src/inspect_ai/_control/pause.py`); `awaiting_human`
   (`src/inspect_ai/log/_samples.py`); the batch `submitted` event
   (`src/inspect_ai/model/_providers/util/batch.py`, plus any batcher that
   builds `BatchRequest` itself); event probes in the tool-stage producers
   (`src/inspect_ai/model/_call_tools.py`) and subtasks
   (`src/inspect_ai/util/_subtask.py`). Wiring tests, including the
   classification and probe tests.
4. **Lanes.** `collect()` (`src/inspect_ai/util/_collect.py`), the list
   branch of `fork()` (`src/inspect_ai/solver/_fork.py`), parallel tool stages
   (`src/inspect_ai/model/_call_tools.py`), `background()`
   (`src/inspect_ai/util/_background.py`), deep agent `agent_wait`
   (`src/inspect_ai/agent/_deepagent/lifecycle_tools.py`),
   `SandboxService._handle_request_tracked`
   (`src/inspect_ai/util/_sandbox/service.py`), and the
   `sandbox_agent_bridge()` join
   (`src/inspect_ai/agent/_bridge/sandbox/bridge.py`). Fork-site tests and
   the slow bridge test.
5. **Option.** `working_time_accounting` on `Task` and `task_with`
   (`src/inspect_ai/_eval/task/task.py`); `eval`, `eval_async` and
   `eval_retry` (`src/inspect_ai/_eval/eval.py`); `eval_set`
   (`src/inspect_ai/_eval/evalset.py`) and `NOT_OVERRIDABLE`
   (`src/inspect_ai/_eval/eval_set_overrides.py`); resolution into the
   eval config (`src/inspect_ai/_eval/run.py`, next to `working_limit`); the
   CLI (`src/inspect_ai/_cli/eval.py`); `EvalConfig`
   (`src/inspect_ai/log/_log.py`); the task identifier; the dataframe
   column (`src/inspect_ai/analysis/_dataframe/evals/columns.py`); passing
   it to `init_sample_working_time` (`run.py`); the regenerated OpenAPI and
   TypeScript types through `land-ts-mono`; docs (`docs/_working_limits.md`,
   `docs/setting-limits.qmd`) and the CHANGELOG. Config plumbing tests.

## Open questions

1. **Opt-in or default-on?** Settled by the standing rule that changes to
   eval behaviour need explicit configuration (decision: Ransom,
   2026-09-15): opt-in, as designed. Default-on would need that decision
   changed. It would remove step 5's option plumbing and the dual helpers,
   at the cost of changed results for existing evals that set
   `working_limit` and use concurrency, human approval or caching. A later
   release could flip the default once the new mode has been used.
2. **Should human approval and human input count as waiting?** I recommend
   yes, as designed. The sample is blocked on a person, which is the same
   kind of wait as an operator's `pause --now`, and that is already
   credited. This applies only in concurrent mode. The alternative is to
   keep charging them, so a slow approver uses up the sample's budget.
3. **Should credited retry time have a cap, including when `time_limit`,
   `timeout` and `max_retries` are all unset?** I recommend no cap. Under
   the lane rule a sample cannot turn retries into free time for work
   Inspect observes. Those three settings bound the wall clock only when
   the evaluator sets them, and the retry stop check runs only after an
   attempt returns, so with none set a sample can retry indefinitely, today
   and under this design. A cap, for example credited retry time at most
   equal to `working_limit`, would add a setting whose value nobody can
   choose well, and would charge infrastructure outages to samples. The
   alternative to a cap is documentation: recommend `time_limit` alongside
   `working_limit`. If a cap is wanted, the accountant supports it directly
   (a per-scope counter of credited attempt time).
4. **Is accounting limited to concurrency Inspect observes acceptable?**
   Inspect sees the lanes it creates and the requests a sandboxed agent
   sends through the bridge. It does not see a sandboxed agent's local work
   or an in-process agent library's own task group. Options:
   - (a) As designed: the bridge body is joined, and unobserved work beside
     a waiting request goes uncharged (examples 12 and 13). Bridged agents
     keep credit for rate-limit waits, which is what `working_limit` is
     for. The cost is that consequence (2) remains for unobserved work.
   - (b) Charge unobserved work conservatively: leave the bridge body's
     lane active, so a bridged agent's request waits are never credited.
     This makes the limit impossible to game but charges every rate-limit
     wait to bridged agents, a regression from today's legacy credit for
     the main users of the bridge.
   - (c) A middle option, such as crediting a bridged agent's waits only
     after a grace period: arbitrary, and still guesses about work Inspect
     cannot see.

   I recommend (a), with the boundary documented next to the option. The
   in-process case is the same choice. It falls back to today's merged
   behaviour without the summing, and (b) has no equivalent there short of
   charging every wait in such a lane.

## Not this design

- Remove or fix `monitor_working_limit`'s model-event guard (`_limit.py:930`),
  which never fires. Concurrent mode does not need it, and legacy mode's
  behaviour is what was measured.
- Per-event attribution: tool and subtask events could report their own
  lane's working time instead of the sample's change, and a lane-level
  clock would allow it.
- Break down waiting time by cause (backoff, slot, hold, human, batch) in
  `EvalSample`, for analysis and the viewer.
- Lanes for untracked concurrency in agent libraries used through the
  in-process `agent_bridge()` (for example an OpenAI Agents SDK `gather`),
  and for `tg_collect` uses outside `fork()` (multi-scorer, internal
  utilities).
- Default wall-clock backstop when `working_limit` is set without
  `time_limit`.
- Make request-attributable errors non-retryable in the provider retry
  policies: OpenAI-compatible `insufficient_quota` 429s, and Anthropic 400s
  matched by body text (example 3d). This changes retry behaviour for every
  eval, not only accounting.
- Carry `working_time_accounting` through `inspect_flow`'s task/log
  projections and `inspect-action`'s log importer.
- `compact()` and `count_tokens()` failed attempts are charged in both
  modes. Crediting them like `generate` attempts is a small follow-up.
- Make `time_limit` and `working_limit` share one clock source in legacy
  mode (asyncio and trio currently differ).
- The shared default `SampleTiming` object that legacy reporters change
  outside a sample. Legacy mode keeps it, and concurrent mode never uses
  it.
