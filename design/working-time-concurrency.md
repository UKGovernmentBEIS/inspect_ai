# Working time under concurrency within a sample

Status: proposed, 2026-10-01; revised 2026-10-06 with Ransom's decisions
(listed under "Decisions"). Issue: none. Author: agent (Claude), reviewed by
Codex; see the PR.

## Why: working time a sample is not charged for

`working_limit` is documented as limiting "only the time spent working (as
opposed to retrying in response to rate limits or waiting on other shared
resources)" (`docs/_working_limits.md`). It is computed as wall-clock time
since the sample started minus credited waiting time. A limit like this is
only worth having if the sample cannot get working time it is not charged
for. On `main` it can. A model can trigger every route below, without any
help from the eval author, by sending parallel tool calls, sub-agents or
concurrent requests from a sandboxed agent.

Measured on `main` at 0321960a92. The setup was one sample, a fake provider
behind the real retry loop, and the calls made from a custom solver:

| Scenario | Wall clock | Logged `working_time` |
| --- | --- | --- |
| 4 concurrent `generate()` calls, each failing twice (0.1 s attempts, 2 s backoff) and then succeeding | 4.32 s | **−12.53 s** |
| `concurrency("k", 1)` held for 3 s by one task while a sibling waits for it | 3.01 s | **0.004 s** |
| The same 2 s request twice with `cache=True` (the second is a cache hit) | 2.01 s | **4.01 s** |
| One 4 s request under `working_limit=1` | 1.01 s | limit hit at 1.0 s, mid-request |

The routes:

- **R1. Negative working time.** Retry backoff and the after-call
  reconciliation are credited separately for each call. When concurrent
  calls retry, their credits add up, so waiting time can exceed wall-clock
  time. Four concurrent retrying calls log −12.53 s for a 4.32 s sample.
  Once working time is negative, `working_limit` never trips, however long
  the sample runs. This is the key result. The limit can be switched off
  by the sample's own behaviour, and the values already reach downstream
  consumers: METR's hawk clamps `working_time` to zero before storing it
  (`inspect-action` at 564a080f: `hawk/core/importer/eval/converter.py:252`,
  with a non-negative check constraint at `hawk/core/db/models.py:265`).
- **R2. Keep one wait open.** Semaphore and connection-slot waits are
  merged, so the sample counts as waiting whenever any of its tasks waits.
  One background call stuck in backoff, or one task queued on a semaphore,
  stops the clock for all other work. In the second row, 3 s of
  semaphore-held work logs as 0.004 s.
- **R3. Fill its own connection pool.** A sample that sends more concurrent
  requests than `max_connections` makes its own next request wait for a
  slot that its other requests hold. That wait is credited while those
  requests do the work.
- **R4. Unseen work during a credited wait.** While any credited wait is
  open, work that Inspect cannot see is free. Examples are a background
  process started through a sandbox exec tool, a sandboxed CLI agent's
  local commands, or an in-process agent library's own `asyncio.gather()`
  (an OpenAI Agents SDK agent running two parallel tool calls through
  `agent_bridge()`).
- **R5. Stretch waits with retryable failures.** Retried attempts and the
  backoff after them are credited. A sample can provoke failures that are
  retried: timeouts on very long outputs, provider errors on unusual input,
  and some request errors the retry policy retries, such as quota 429s on
  OpenAI-compatible providers and some Anthropic 400s
  (`src/inspect_ai/model/_openai.py:1539`,
  `src/inspect_ai/model/_providers/anthropic.py:1835`). Its other work goes
  uncharged while the waits run (R2 and R4), and its wall-clock run grows.

The cache-hit row is a separate bug in the same reconciliation, which adds
the original call's time on a hit. The last row shows that enforcement
already charges a request while it is in flight.

## Decisions (Ransom, 2026-10-06)

These replace the opt-in, lane-based design of earlier revisions:

1. **Default-on.** The accounting changes for everyone; there is no opt-in
   option. The current accounting is broken (R1–R5, cache hits), so keeping
   it as the default preserves wrong results, not reproducible ones. The
   standing rule of 2026-09-15 (behaviour changes need explicit config)
   protects behaviour that is correct; it does not apply to a clock that is
   wrong.
2. **Human approval and human input are waiting** where waiting is credited
   at all (option A, samples with no sandbox).
3. **No cap on credited retry time,** even with `time_limit`, `timeout` and
   `max_retries` all unset. The docs recommend setting `time_limit` next to
   `working_limit`.
4. **Charge all time unless Inspect is sure everything is waiting.** An
   in-flight model attempt is not a sure wait, so failed and timed-out
   attempts are charged. This changes the documented contract that
   "unsuccessful model generations" are excluded.
5. **A sample with a sandbox is never credited.** A model with any exec tool
   can start a background process that keeps running during a later wait.
   Sandbox freezing is not designed.
6. **A visible in-flight model attempt makes the sample working,** even when
   a wait is open beside it.
7. **No credit while an in-process `agent_bridge()` is active,** for the same
   reason as sandboxes (R4).
8. **Document and warn.** `working_limit` is effectively `time_limit` for
   samples with a sandbox or an active `agent_bridge()`; warn when such a
   sample has a `working_limit`.
9. **No lanes.** Credit applies only when no concurrent region is open; any
   open concurrent region means all time is charged.
10. **Motivate from cheating** (the "Why" above).
11. **Consider working time = wall-clock time** as a real alternative, with
    usage data (option B below).

## Goals and non-goals

Goals:

- Close R1–R5. A sample or model cannot get working time it is not charged
  for. Working time never exceeds wall-clock time and never decreases.
- One rule for every source of waiting. The sources are semaphore and
  connection-slot waits, retry backoff, provider-internal retries,
  rate-limit waits, batch waits, hard-pause holds, human approval and
  input, and checkpoint/resume.
- Applies by default, with the change in results stated per kind of eval.
- A fair comparison with "working time is wall-clock time", including
  usage data, and a recommendation.

Non-goals:

- Token and cost limits (out of scope per the task).
- Changing `time_limit`: it stays a wall-clock deadline.
- Freezing or pausing sandboxes during waits (decision 5).
- Credit for concurrency an eval author creates in custom solver code (their
  own task groups); option A documents it as an accuracy limit.

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
  names "a sample-level overlap guard" as follow-up work. Both options
  below go further than an overlap guard.
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


## Usage of `working_limit` and `working_time`

Searched 2026-10-06. Private usage (AISI, METR's own runs through hawk,
labs) is not visible to these searches, so the counts are a lower bound on
real use and say nothing about private evals.

**inspect_evals** (local checkout at 9080b5e9f, 2026-10-05, the same as
`origin/main`; `grep -rl` over `src/`). Of 133 eval directories, 1 sets
`working_limit`: `swe_lancer` (`swe_lancer.py:140`), which is sandboxed.
For comparison, 14 files set `time_limit` and 26 set `message_limit`.

**GitHub code search** (REST `search/code`, first 100 results per query, for
`working_limit language:python` with 659 matches, `working-limit` with 1,344
matches, and `working_time inspect_ai` with 912 matches). Most matches are
Inspect itself, copies of Inspect vendored into other repos (inspect_arg,
PRInTS, ResearchGym, leaven, forks), and unrelated projects that use the same
words. What remains, after reading each file:

| Repository (public) | Use | Sandbox |
| --- | --- | --- |
| UKGovernmentBEIS/inspect_evals `swe_lancer` | `working_limit` on the task | yes (Docker) |
| UKGovernmentBEIS/control-arena (vLLM setting smoke eval; CLI) | `--working-limit` option | yes (vLLM setting); CLI pass-through |
| usnistgov/caisi-cyber-evals | README runs `--working-limit 7200` | yes (Docker) |
| lyptus-research/cyber-task-horizons-data | records `working_limit` of 1800–7200 per benchmark run | yes (cyber tasks) |
| allenai/agent-baselines (inspect-swe solvers) | README recommends `--working-limit` | yes (sandbox agent bridge) |
| AnastasiaKWei/healthy-rl | scripts pass `--working-limit 1800` | yes (`--max-sandboxes`) |
| boundary-bench, agent-glovebox | pass `working_limit` through to tasks | yes |
| malidib/alidib-ukaisi | `--working-limit 250` | yes (`local` sandbox) |
| groq/openbench `livemcpbench` | task default `working_limit=600` | none seen (react agent with MCP tools) |
| a2ui-project/a2ui | `working_limit: 350` | none seen |
| aisa-group/decomposing-eval-awareness (AgentHarm runner) | `--working-limit 600` | none (AgentHarm uses simulated tools) |
| March-7/Red-Teaming-AiFChem-Agent (SOSBench runner) | `--working-limit` (default 25) | none seen |
| compl-ai, METR hawk / inspect-action, inspect_flow | pass-through config and stored columns | depends on the task |
| epoch-research/MirrorCode, ianarawjo/evalstats | example or simulation scripts | unclear |
| METR/inspect-agents `human_approval.py` | a `human` approver that credits approval waits by calling the private `report_sample_waiting_time` | used with sandboxed agents |

Of about fifteen real users, eleven are sandboxed and four have no sandbox
that the search could see. The METR approver deserves its own line. It
exists because approval waits burn `working_limit` today. It works around
that through a private API, and it is the one concrete user found that
depends on crediting a wait in sandboxed samples (open question 2).

**Consumers of the logged `working_time`.** The value is read in these
places:

- Inspect's own samples dataframe (`analysis/_dataframe/samples/columns.py:74`)
  and events dataframe (`working_start` and `working_time`,
  `analysis/_dataframe/events/columns.py:57`).
- The viewer's sample activity panel and transcript timing
  (`ts-mono/packages/inspect-components/src/sample-activity/activityData.ts:625`,
  `:882`; `ToolEventView.tsx:132`; `SubtaskEventView.tsx:57`).
- inspect_scout's sample metadata and columns
  (`_transcript/sample_metadata.py:137`, `_transcript/log.py:115`).
- hawk's importer and database column `working_time_seconds`, clamped to
  zero (`converter.py:252`, `models.py:265`).
- inspect_flow, which stores `working_limit` only (`_runner/task_log.py:59`).
- Public analysis scripts: control-arena `analysis/_types.py`, a2ui
  `eval/a2ui_eval/shared/utils.py`, inspect-mlflow, evalanche, aiq-magnet
  and EXP-Bench utilities.

All of them read a float in seconds. None depends on how the waiting part
is computed.

## Option A: credit only sure waits in a sample with nothing else going on

This is decisions 1–9 applied together.

### The rule

At each instant a sample is either **credited** (the instant is waiting
time) or **charged** (working time). An instant is credited only when all
five conditions hold:

1. the sample has no sandbox environment;
2. no in-process `agent_bridge()` context is active;
3. no concurrent region is open;
4. no model attempt is in flight;
5. at least one sure wait is open.

Every other instant is charged. There are no lanes and no per-task state:
the sample clock keeps four counters (bridges, regions, attempts, waits) and
a flag for the sandbox.

**Sure waits** are spans during which Inspect knows the code that opened
them can make no progress:

| Sure wait | Where it opens and closes |
| --- | --- |
| Retry backoff sleep (`generate`, `compact`, `count_tokens`) | a tenacity `sleep=` wrapper around `anyio.sleep` in `model_retry_config()` (`src/inspect_ai/model/_retry.py`), installed when `report_waiting_time` is not `None`, so batch admin loops are excluded as today |
| `concurrency()` semaphore wait | `sample_waiting_for()` (`working.py:76`), around the acquire only |
| Model connection-slot wait, including the adaptive limiter | `ConnectionSlot.acquire` (`_model.py:799`) |
| Hard-pause hold and the slot reacquire after it | `wait_generate_dispatch` (`src/inspect_ai/_control/pause.py:627`) |
| Human approval and human input | `ActiveSample.awaiting_human()` (`log/_samples.py:369`) |
| Batch request in the batcher's local queue, until its batch is submitted | `Batcher.generate_for_request` (`batch.py:102`), with a `submitted` event the batcher sets on submission and before delivering any result or error |

A batch request's local-queue wait is the one sure wait inside a model
attempt. While it is open, the enclosing attempt does not count as in
flight: the span decrements the attempt counter on entry and restores it on
exit.

**Concurrent regions** are Inspect's own fork sites. A region opens when the
site starts running more than one thing at once and closes when the site
finishes:

| Site | Region |
| --- | --- |
| Parallel tool-call stage with two or more calls (`src/inspect_ai/model/_call_tools.py:728`) | around the stage's outer task group; one-call stages open none |
| `collect()` with two or more tasks (`src/inspect_ai/util/_collect.py:36`) | around the task group |
| `fork()` with a list of solvers (`src/inspect_ai/solver/_fork.py:48`) | around the `tg_collect`; a single solver (`:45`) opens none |
| `background()` (`src/inspect_ai/util/_background.py:81`) | from the start of the background task to its end; this covers deep-agent background sub-agents, which are started through `background()` (`agent/_deepagent/agent_tool.py:620`) |

A synchronous sub-agent (handoff, `as_tool`, a deep agent's foreground
sub-agent) runs inline in its caller and opens no region.

**Model attempts** are counted from the start of the provider call in
`Model._generate`'s inner `generate()` (`_model.py:1560`) to its `finally`.
Cache hits return earlier and open no attempt. Failed, timed-out and
cancelled attempts are charged like successful ones. The SDK's own retries
inside an attempt are charged too, because the attempt is in flight. The
after-call reconciliation (`_model.py:1749`) is removed.

**Sandbox and bridge.** The sandbox flag is set when the sample clock starts.
`init_sample_working_time()` runs after sandbox setup (`run.py:2667`, after
`active.sandbox_environments` is set at `:2655`), and receives
`credit_eligible = not sandbox_environments`. A `local` sandbox counts as a
sandbox. `agent_bridge()` (`src/inspect_ai/agent/_bridge/bridge.py:100`)
increments the bridge counter for its body. `sandbox_agent_bridge()` needs a
sandbox, so the sandbox flag already covers it.

### How each condition closes a route

| Route | Closed by |
| --- | --- |
| R1 negative working time | one counter-based clock per sample; credit is a subset of the timeline, so `0 ≤ working_time ≤ total_time` |
| R2 one wait kept open | condition 3: any open region, including a long-running `background()` worker, charges everything |
| R3 own connection pool full | conditions 3 and 4: the requests holding the slots are in flight inside a region |
| R4 unseen work | conditions 1 and 2: no credit with a sandbox or an active `agent_bridge()`. The remaining gap is an eval author's own task groups in custom solver code (accuracy limit) |
| R5 provoked retries | condition 4: failed attempts are charged. Only backoff sleeps between attempts are credited, and only when nothing else runs, so the sample gains wall-clock time but no uncharged work |

### Worked examples

Times are seconds. "Today" is measured or derived from the code on `main`.

| # | Scenario | Today | Option A | Option B (wall clock) |
| --- | --- | --- | --- | --- |
| 1 | 4 `collect()`ed calls, each: 0.1 attempt fails, 2 backoff, 0.1 fails, 2 backoff, 0.1 succeeds (wall 4.3) | working −12.5 | region open: working 4.3 | 4.3 |
| 2 | `collect()`: task A holds `concurrency("k",1)` for 3 s, task B waits on it | 0.0 | region: 3.0 | 3.0 |
| 3 | main loop works 600 s; a `background()` monitor's call is rate-limited throughout | ≈ 0 | background region: 600 | 600 |
| 4 | 11 parallel sub-agent calls at a 10-slot pool; one waits 30 s for a slot | 30 credited | region: charged | charged |
| 5 | sequential react agent with a sandbox `bash` tool; a background process runs during a 60 s backoff | 60 credited | sandbox: charged | charged |
| 6 | OpenAI Agents SDK through `agent_bridge()`: parallel tool calls, one agent-as-tool backing off 40 s, one Python tool computing 40 s | 40 credited | bridge active: charged | charged |
| 7 | sequential, no sandbox: one 300 s attempt times out, 30 s backoff, 10 s attempt succeeds | 330 credited (if the call succeeds) | 310 charged, 30 credited | 340 charged |
| 8 | sequential, no sandbox: a 429 followed by 120 s backoff | 120 credited | 120 credited | charged |
| 9 | two parallel sub-agents, each inside its own `working_limit(60)`; A backs off while B works | A's own backoff credited to A's limit | region: both limits charged (a regression; see "Costs") | charged |
| 10 | sequential, no sandbox: `pause --now` holds the call 120 s | 120 credited | 120 credited | charged |
| 11 | sequential, no sandbox: human approval takes 300 s | charged | 300 credited | charged |
| 12 | a cache hit after a 2 s original call | working +2 | local time only | local time only |
| 13 | a successful 10 s attempt whose SDK retried internally (`call.time` 4) | 6 credited | charged (in flight) | charged |
| 14 | custom solver with its own task group, no Inspect region: one task backs off 60 s, the other computes 60 s | 60 credited | 60 credited (accuracy limit) | charged |
| 15 | sequential, no sandbox, batch mode: 15 s in the local queue, then an hour at the provider | almost nothing credited | 15 credited, the hour charged | charged |
| 16 | any sandboxed eval (swe_lancer, cyber, inspect_swe agents) during a rate-limit storm | backoff credited | charged | charged |

### The sample clock

```python
@dataclass
class SampleClock:
    now: Callable[[], float]          # time.monotonic in production; injected in tests
    start: float
    credit_eligible: bool             # no sandbox
    bridges: int = 0
    regions: int = 0
    attempts: int = 0
    waits: int = 0
    _credited: float = 0.0
    _mark: float = 0.0                # start of the open interval
    _prior_working: float = 0.0       # checkpoint restore

    def crediting(self) -> bool:
        return (self.credit_eligible and self.bridges == 0 and self.regions == 0
                and self.attempts == 0 and self.waits > 0)

    def change(self, counter: str, delta: int) -> None:  # advance, then apply
    def working_time(self) -> float: ...   # prior + elapsed - credited - open credited interval
    def waiting_time(self) -> float: ...   # credited, including the open interval
```

Every counter change first closes the interval since `_mark`, adding it to
`_credited` if `crediting()` was true, and then applies the change. The
readings are exact at all times; nothing is provisional or settled later.
Working time never decreases, so event durations are plain differences of
`working_time()` readings, and tool and subtask events keep today's formula
with the new reading (`_call_tools.py:503`, `:631`; `_subtask.py:128`,
`:139`). No probes are needed.

The helpers in `working.py`, all of which do nothing outside a sample, are:

- `sample_wait()`, a sync context manager for a sure wait;
- `concurrent_region()`;
- `model_attempt()`, plus `suspend_attempt()` for the batch queue;
- `bridge_active()`.

`report_sample_waiting_time()` is kept as a deprecated no-op that logs one
warning per process, because METR's approver calls it (see "Compatibility").
`record_waiting_time()` and the per-node `_waiting_time` in `_WorkingLimit`
are removed. Counters are plain integers: Inspect runs on one event loop
thread, so no lock is needed (AGENTS.md, "No speculative locks").

### Scoped `working_limit()`

Per-scope clocks are not needed. Credit requires that no concurrent region
is open, so when a scope is being credited it is the only Inspect-visible
work in the sample. Its working time is then the sample's working time over
the same interval. A node therefore records `sample_clock.working_time()`
on `__enter__`, and its `usage` is the current reading minus that value.
Outside a running sample there is no clock, so a scoped `working_limit()`
measures wall-clock time. Today, retries outside a sample are credited to
the limit tree and the default timing object.

The cost is example 9. A scoped limit on a sub-agent inside a fork region
is charged for everything during the region, including its own backoff.
Today it is credited for its own waits. No public user of scoped working
limits on parallel sub-agents was found. If one appears, the fallback is a
reduced per-child model (per child: open waits, open attempts, joined) for
regions only.

### Warning for samples that get no credit

When a sample has a `working_limit` and either has a sandbox (known when
the clock starts) or enters `agent_bridge()`, Inspect logs one warning per
task, not per sample, so an eval with thousands of samples logs it once:

> working_limit applies as a wall-clock limit to samples with a sandbox (or
> an active agent_bridge()): waits are not credited for them. Consider
> time_limit.

It is keyed on the task's stable id and the reason (`sandbox` or
`agent_bridge`) and uses `warn_once`.

### Enforcement, checkpoints and events

- **Monitor.** `monitor_working_limit` checks the root node's `usage` once
  a second, as today. Waits stop the clock in real time, so neither the
  pause gate's 0.5 s credit ticks nor the backoff's credit in advance are
  needed. The pause tick loop stays, because it also bounds how long an
  escape takes. The guard that skips the check during an active model event
  never fires today (see "Current behaviour") and is removed: in-flight
  attempts are charged by rule.
- **Checkpoints.** The payload keys stay the same. `working_elapsed` is
  `working_time()` and `working_waiting` is `waiting_time()`. Restore
  seeds `_prior_working` (always) and the root node's anchor (with
  `check=True`), as today.
- **Logged values.** `EvalSample.working_time` is the clock's working time
  for the current attempt, closed at the instant `total_time` is measured,
  so `working_time ≤ total_time` holds exactly. `working_start` is the
  reading plus `_prior_working`.

### Costs accepted in option A

- Sandboxed evals (eleven of about fifteen public users) get no credit:
  their `working_limit` is a wall-clock limit checked once a second.
- Rate-limited parallel generation is charged. For example, eight
  `collect()`ed generations backing off together are charged in full.
- A `background()` worker that runs for the whole sample removes all credit
  for that sample.
- Failed and timed-out attempts, and SDK-internal retries, are charged. The
  documented "unsuccessful model generations are excluded" contract
  changes.
- Scoped limits inside regions are always charged (example 9).
- An eval author's own task groups can still hide work behind a sure wait
  (example 14).

## Option B: working time is wall-clock time

No waiting credit anywhere. `working_time == total_time` for every sample,
and `working_limit` is a wall-clock limit.

- **`working_limit` API.** Keep `working_limit` (task, eval, eval set, CLI,
  scoped `working_limit()`) working, with wall-clock semantics. Mark it
  deprecated in the docs in favour of `time_limit`, and log one notice per
  task when it is set. Removing it is a separate, later decision. It is
  part of task identity and appears in configs, inspect_flow and hawk's
  database. Its behaviour still differs slightly from `time_limit`:
  `working_limit` raises `LimitExceededError` at checks and from the
  once-a-second monitor, while `time_limit` cancels through a cancel scope
  and gives the scorer a timeout.
- **Logged `working_time`.** The field stays and equals `total_time` (on a
  resumed sample, it includes the prior attempt like `working_start`).
  Setting it to `None` would break consumers that coerce `None` to 0, such
  as hawk's `sample.working_time or 0.0`.
- **Events.** `working_start` is elapsed time since the sample started.
  Tool and subtask `working_time` are their elapsed times.
  `ModelEvent.working_time` (`output.time`) is unchanged.
- **Pause and human waits.** `pause --now` holds and human approvals burn
  `working_limit`, as they already burn `time_limit`. The pause-resume and
  interim-scoring designs (`design/ctl/pause-resume.md`,
  `design/ctl/interim-scoring.md`) promise that held time does not burn
  `working_limit`. Those notes and the control-channel docs change.
- **Checkpoints.** `working_elapsed` is elapsed time and `working_waiting`
  is 0. An older snapshot restores its `working_elapsed` as the prior
  elapsed time. That gives one resume a little extra budget, which is
  documented.
- **Code.** The waiting ledger and every reporter go. That covers the retry
  credit callback, the reconciliation, the pause credit ticks, the merging
  in `sample_waiting`/`sample_waiting_for`, `record_waiting_time` and the
  monitor guard. `report_sample_waiting_time()` stays as a deprecated no-op
  that warns once. The change is a net deletion.

## Comparison and recommendation

| | Option A (sure waits only) | Option B (wall clock) |
| --- | --- | --- |
| Closes R1–R5 | yes, except an eval author's own task groups (example 14) | yes, by construction |
| Who still gets credit | samples with no sandbox, no active `agent_bridge()` and no open region: four of about fifteen public users, and only while they run one thing at a time | nobody |
| `working_limit` meaning | "wall clock minus sure waits while idle"; equal to wall clock for sandboxed and bridged samples | wall clock everywhere |
| Pause, human waits | credited in eligible samples | charged |
| Logged `working_time` | ≤ `total_time`; equal for most samples | equal to `total_time` |
| Implementation | rewrite of the sample clock; spans at 6 wait sites; regions at 4 fork sites; attempt counting; bridge counter; sandbox flag; warning; checkpoint; about 40 tests | deletions across the same files, a deprecation notice, docs, and updated tests |
| Ongoing cost | every new fork site, wait site or agent integration must be classified correctly, or a route reopens | none |

**Recommendation: option B.** After decisions 4–9, option A's credit
survives only in samples that run one thing at a time without a sandbox
or an in-process bridge. Among public users that is four scripts or
small evals, and the eval that motivated `working_limit` (a sandboxed
agent; see the docs example, which uses `sandbox="docker"`) gets nothing.
Option A would keep a second clock with a subtle eligibility rule. Every
future concurrency feature would have to be classified against it, and
each misclassification reopens a cheating route. Option B is a net
deletion, and its one meaning is easy to state. Choose option A if fair
treatment of rate-limit waits for non-sandboxed sequential evals (examples
8, 10, 11) is worth that ongoing cost. Option A is fully specified above
so that it can be built.

## Alternatives considered

- **Lanes with provisional attempts** (earlier revisions of this design).
  Per-lane states, in-flight attempts resolved by retry outcome, pending
  segments and event probes. It closes R1–R3 for observed concurrency, but
  it leaves R4 for sandboxes and in-process libraries and needs the most
  machinery. Replaced by decisions 4 and 9.
- **Reduced per-child model** (per child: open waits, open attempts, joined)
  instead of charging whole regions. It would keep credit for example 9 and
  for rate-limited parallel generation. It is the fallback if a user who
  depends on credit under concurrency appears; none was found.
- **Opt-in new accounting with the old as default.** Dropped by decision 1:
  the old accounting is broken, not merely different.
- **A legacy escape hatch** (an option that restores today's accounting).
  Not recommended for either option. Today's accounting is the bug: it lets
  a sample turn the limit off (R1). An option that restores it would keep a
  second code path only to reproduce wrong numbers. Anyone who needs past
  numbers can pin an Inspect version.
- **Freezing sandboxes during waits.** Not assessed (decision 5).
- **Clamping today's sums to wall clock.** It fixes negative values but
  keeps R2–R5.

## Compatibility and migration

The change applies by default. There is no new option and no schema
change.

What changes, by kind of eval:

- **Sandboxed evals with `working_limit`** (swe_lancer, cyber benchmarks,
  inspect_swe agents, control-arena): under both options, rate-limit
  backoff, connection waits, hard-pause holds and human approvals are now
  charged. Samples that finished before may hit the limit. Users should
  raise `working_limit` or move to `time_limit`. The warning or notice says
  so.
- **Evals using `agent_bridge()`:** the same, while the bridge is active.
- **Non-sandboxed evals with `working_limit`:**
  - Option A: credit only while sequential. Failed attempts and SDK retries
    are charged (a contract change), human waits are credited (new), and
    cache hits no longer add time.
  - Option B: everything is charged.
- **Evals without `working_limit`:** results are unchanged. The logged
  `working_time` changes: it is never negative and never above
  `total_time`, and under option B it equals `total_time`. Event
  `working_start` values are monotonic.
- **Private API users.** METR's approver
  (`METR/inspect-agents/packages/agents/src/metr_agents/human_approval.py`)
  calls `report_sample_waiting_time`. It becomes a deprecated no-op that
  warns once, so their approval waits are charged in sandboxed samples
  (open question 2). No other satellite or public user of the private
  helpers was found.
- **Downstream readers** (dataframes, viewer, inspect_scout, hawk,
  inspect_flow) keep working: the field names and types are unchanged.
  hawk's clamp to zero becomes a no-op.

**Docs and CHANGELOG.** `docs/_working_limits.md` and
`docs/setting-limits.qmd` get the new meaning (and, for option B, the
deprecation in favour of `time_limit`). The grok note in
`docs/providers.qmd` about `working_time` and internal retries goes. The
control-channel docs on `pause --now` say whether held time burns
`working_limit`. There is one CHANGELOG line, for example "`working_limit`
now counts time as working unless a sample is only waiting (option A) /
now measures wall-clock time (option B)". It names the change in results
for sandboxed evals.

## Security

No untrusted content reaches the new code. The inputs a sample controls
are its concurrency, its outputs and which requests fail. These are the
routes R1–R5, and both options close them. Option A leaves one gap: work an
eval author's own task groups run behind a sure wait. That is the author's
own code, not something the model can trigger. Option B has no gap.

## Testing

All async tests run under both backends (`--runtrio` before the PR). Tests
inject the clock through `init_sample_working_time(..., now=fake)` and patch
the backoff sleep's `_sleep` indirection. Their fake `ModelAPI` attempts
block on `anyio.Event`s, so ordering is fixed and no test waits on a sleep.

**Option B** (the recommendation):

- `tests/test_sample_limits.py`: with retries, a semaphore wait, a cache
  hit and concurrent retrying calls, `working_time == total_time`, and
  `working_limit` trips at the wall-clock time.
- `tests/_control/test_pause.py`: the existing held-span credit tests
  change to assert that hold time is charged.
- `tests/util/test_limit_working.py`: the `record_waiting_time` tests are
  removed, and scoped `working_limit()` usage equals elapsed time.
- `report_sample_waiting_time()` is a no-op that warns once.
- The deprecation notice appears once per task.
- `tests/checkpoint/test_sample_runtime.py`: an older snapshot with
  `working_waiting > 0` restores.

**Option A:**

- Clock unit tests (`tests/util/test_limit_working.py`) for each condition
  and every worked example. Seeded random sequences check that working time
  never decreases and `0 ≤ working ≤ elapsed`.
- Wiring tests (`tests/test_sample_limits.py`) for each sure wait, each
  region site, the batch attempt suspension, the sandbox flag (`local`
  sandbox included) and the `agent_bridge()` counter.
- The warning appears once per task.
- Scoped limits use deltas.
- Checkpoint round trip.

## Implementation plan

For option B (recommended):

1. `src/inspect_ai/_util/working.py`: reduce to start time and elapsed
   time. `sample_waiting_time()` returns 0, `report_sample_waiting_time()`
   becomes a deprecated no-op with a warning, and `sample_waiting` and
   `sample_waiting_for` become pass-throughs.
2. `src/inspect_ai/util/_limit.py`: `_WorkingLimit.usage` is elapsed time.
   Remove `record_waiting_time` and the monitor's model-event guard. Add the
   once-per-task deprecation notice.
3. `src/inspect_ai/model/_model.py`, `_retry.py`,
   `src/inspect_ai/_control/pause.py`: remove the retry credit callback,
   the reconciliation and the hold credits (keep the escape tick).
4. `src/inspect_ai/_eval/task/run.py`: logged `working_time` is
   `total_time`. Update `util/_checkpoint/sample_runtime.py`, and the event
   producers in `_call_tools.py` and `_subtask.py`.
5. Docs (`_working_limits.md`, `setting-limits.qmd`, `providers.qmd`, the
   control-channel pause docs), the notes in `design/ctl/pause-resume.md`
   and `design/ctl/interim-scoring.md`, the CHANGELOG, and the tests
   above.

For option A: `SampleClock` and the helpers (`working.py`); the sure-wait
spans (`_retry.py`, `_concurrency.py` via `working.py`, `_model.py`,
`pause.py`, `log/_samples.py`, `batch.py`); attempt counting and removal of
the reconciliation (`_model.py`); regions (`_call_tools.py`, `_collect.py`,
`_fork.py`, `_background.py`); the bridge counter (`agent/_bridge/bridge.py`);
the sandbox flag and logged value (`run.py`); scoped deltas, the warning and
removal of the monitor guard (`_limit.py`); checkpoint; docs, CHANGELOG and
tests.

## Open questions

1. **Option A or option B?** I recommend B (see "Comparison and
   recommendation"). A is the choice if credit for rate-limit waits in
   non-sandboxed sequential evals is worth the extra clock and its ongoing
   upkeep.
2. **METR's human-approval credit in sandboxed samples.** METR's public
   approver reports approval waits through the private
   `report_sample_waiting_time` so that long approval deadlines do not
   burn `working_limit`. Decision 5 (option A) and option B both charge
   those waits. I recommend accepting that: the helper becomes a no-op that
   warns once, and METR moves to `time_limit` or a larger `working_limit`.
   An exception for human waits in sandboxed samples would reopen R4 for
   background processes, although only for as long as a human takes. The
   question is for Ransom because it changes a named user's behaviour.

## Not this design

- Remove `working_limit` entirely (after a deprecation period under option
  B).
- A breakdown of waiting time by cause in the log (option A).
- Credit for concurrency in eval authors' own task groups, or a reduced
  per-child model for regions.
- Making request-attributable errors (quota 429s, Anthropic 400s matched by
  body text) non-retryable in provider retry policies.
- Freezing sandboxes during waits.
