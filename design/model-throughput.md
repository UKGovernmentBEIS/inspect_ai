# Per-model throughput reporting under HTTP retries

Status: implemented (registry: `src/inspect_ai/model/_throughput.py`;
endpoint: `GET /models/throughput`; CLI: `inspect ctl model throughput`)

Issue: [meridianlabs-ai/inspect_ai#235](https://github.com/meridianlabs-ai/inspect_ai/issues/235)

## Problem

When a run hits sustained HTTP retries (429s, provider brownouts), the
operator's real question is not "how many retries have happened?" but "what
throughput am I actually getting, and is it worth waiting?" Today there is no
way to answer that:

- The task display footer shows a single process-global retry counter
  (`HTTP retries: N` from `task_http_retries()` in
  `src/inspect_ai/_display/core/footer.py`) — a cumulative count with no
  rate, no per-model attribution, and no relation to tokens produced.
- `inspect trace http` shows individual request/retry lines
  (`-> model retry 3 (retrying in 20 seconds) [RateLimitError 429]`) but nothing an
  operator can integrate into "output tokens per second right now".
- `inspect ctl task` shows per-eval `total_tokens` and `http_retries`
  rollups (`_control/state.py:_build_summary`), but not per model, not as a
  rate, and only per task — not across the run.

The concrete failure mode (from the originating Slack thread): an operator
watching a heavily-throttled run cannot tell whether effective throughput is
5% or 80% of normal, so they wait far longer than they would if they knew —
when the right move was to switch to a smaller run or a different API key.

## Goals

- Measure **effective throughput per model** — headline metric: **output
  tokens per second over a recent window** — aggregated **across all
  samples and tasks in the run** (i.e. per process, which is what "a run"
  is: `eval_set` with `retry_immediate` executes as one `eval()` call).
- Alongside the rate, report the context needed to interpret it: retry
  counts by kind (`rate_limit` vs `transient`), seconds of backoff incurred,
  the rate at which scheduled backoff is accumulating relative to
  wall-clock, and how many samples currently have a generate sleeping in a
  retry wait.
- Surface it where the issue asks:
  - `inspect ctl` — a new per-model endpoint + CLI view (primary surface,
    machine- and human-readable, pollable by watchdogs).
  - the trace file — so `inspect trace http` sessions and post-mortems can
    gauge throughput, not just count retries.
  - the live task display footer — a glanceable aggregate.

## Non-goals

- **In-flight token progress** (tokens streamed mid-generate). That is layer
  2 of `design/ctl/generate-progress.md` (`report_active_model_progress()`),
  with reserved `tokens`/`last_progress_at` slots already in the ctl
  activity view. This design counts tokens only at generate completion; the
  two compose later (a completed-call rate plus in-flight streaming deltas)
  but neither depends on the other.
- Cost-per-second or cost-based throttling advice.
- Cross-process aggregation (an `eval-set` level aggregate is explicitly
  "Later" in `design/ctl/control-channel.md`). Each process reports its own
  registry; the `ctl` CLI already fans out per process.
- Automatic remediation (switching keys, shrinking runs). This design gives
  the operator the signal; acting on it stays manual (or in user scripts
  polling the new endpoint).

## Current state (what exists to build on)

Retry accounting today, all fed from `report_http_retry()` in
`src/inspect_ai/_util/retry.py`:

1. `_http_retries_count` — process-global scalar, **never reset**, rendered
   in every display mode's footer. Not keyed by model.
2. `ModelEvent.retries` — per-generation count in the transcript, via
   `report_active_sample_retry()` (`log/_samples.py`).
3. `ActiveSample.http_retries` → `EvalState.http_retries` rollup, summed
   into the `ctl task` row (`_control/state.py`).

Retry *wait* is tracked per active sample (`ActiveSampleRetryWait` in
`log/_samples.py`: model, attempt, started_at, deadline — set from
`model_retry_config()`'s `on_before_sleep` in `model/_retry.py`) and shows
up in the ctl sample activity view as `type: "retry_wait"`. Backoff time is
also folded into sample waiting time (`_util/working.py`) but only as an
undifferentiated total.

Token accounting: `record_and_check_model_usage()` (`model/_model.py`)
accumulates `ModelUsage` into per-sample and per-task-run ContextVar dicts
keyed by `provider/model`, flushed to `EvalStats.model_usage`. There is a
per-eval scalar `EvalState.total_tokens` for ctl, but **no process-level
per-model accumulation and no rate anywhere** (grep for
tokens-per-second/throughput finds nothing).

Precedents this design follows:

- Process registries keyed by model already exist: adaptive concurrency
  controllers (`util/_concurrency.py`, exposed via `GET /config` →
  `adaptive`) and model pause gates (`_control/pause.py`, `_model_gates`).
- `reset_run_registries()` (`_control/eval_state.py`) is *the* documented
  reset point for per-run process state ("add new resets here, not at the
  call sites"). Note the cautionary precedent: `_http_retries_count` is
  never reset, so in a keep-alive or test process it accumulates across
  runs — the new registry must not repeat that.
- ctl endpoint rules: the "cheap shoveling" invariant
  (`design/ctl/control-channel.md`) and the future-endpoint checklist
  (`design/ctl/endpoint-cost-audit.md` §"Guidance for future endpoints").

## Design

### 1. Throughput registry (`src/inspect_ai/model/_throughput.py`)

A process-global registry keyed by full model name (`provider/model`, same
key as `model_usage`; see §2 "Key discipline" for how each feed obtains
this key), holding one `ModelThroughput` record per model:

```python
@dataclass
class ModelThroughput:
    # cumulative since run start
    requests: int = 0                  # successful generates recorded
    output_tokens: int = 0
    total_tokens: int = 0
    retries_rate_limit: int = 0
    retries_transient: int = 0
    retry_wait_seconds: float = 0.0    # backoff scheduled (sum of sleeps)
    first_activity: datetime | None = None   # wall-clock (for the envelope)
    last_activity: datetime | None = None
    # rolling window: fixed-size ring of time buckets
    buckets: TokenBuckets = field(default_factory=TokenBuckets)
    # scheduled backoff (start, end) intervals on the monotonic clock,
    # kept out of the ring — see below
    backoff_intervals: list[BackoffInterval] = field(default_factory=list)
```

`TokenBuckets` is a fixed-length ring (e.g. 60 buckets × 10 s = a 10-minute
horizon) where each bucket accumulates `{output_tokens, total_tokens,
requests, retries}` for its 10-second slice. Bucket indexing uses the
monotonic clock; writes are O(1) (index by `monotonic() // 10`). Slots are
epoch-tagged rather than zeroed on advance: each slot stores the absolute
bucket epoch it was last written in, a write resets a slot whose stored
epoch differs from the current one, and reads sum only slots whose epoch
falls inside the requested window — so a gap in traffic longer than the
horizon can't leak a previous lap's counts into a window sum (zero-on-
advance would, since nothing advances the ring during a write gap). Reads
sum at most 60 small structs per model. This bounds memory to a constant
per model regardless of request rate — a per-request deque would grow with
throughput, which is exactly the case we care about.

Scheduled backoff deliberately stays **out of the ring**. Sleeps reach 30
minutes (`wait_exponential_jitter(initial=3, max=30*60)` in
`model/_retry.py`) — attributing one to its schedule-time bucket would
swamp any window containing its start, but pre-writing it into the buckets
covering `[now, now + s]` fights the ring's slot reuse: a future bucket is
physically the same slot as one of the oldest past buckets, so the
pre-write either destroys counts still inside the horizon or is itself
destroyed when the current lap writes to that slot. Instead each model
keeps a short list of scheduled-backoff `(start, end)` intervals
(`BackoffInterval`, a NamedTuple): `record_retry_wait` appends one — O(1)
— and prunes intervals that ended more than a horizon ago (triggered by an
expired head *or* a doubling size threshold, so one long head sleep can't
block pruning of the short waits appended behind it); reads compute window
backoff-seconds as the sum of each interval's overlap with
`[now − window, now]`. The list stays within 2× the intervals still in
backoff or recently ended inside the horizon — concurrency-bound, not
request-rate-bound. Rates over any window ≤ the horizon are computed at
read time (window sum ÷ window seconds, clamped to
time-since-first-activity so a fresh run doesn't report an artificially
diluted rate).

No lock: writes and reads happen on the eval's single event loop thread
(control-server handlers included), per the repo's no-speculative-locks
rule; individual bucket updates don't span awaits.

Module API:

```python
def record_generate(model: str, usage: ModelUsage) -> None: ...
def record_retry(model: str, kind: RetryKind) -> None: ...
def record_retry_wait(model: str, wait_seconds: float) -> None: ...
def throughput_snapshot(window: int = 60) -> dict[str, ModelThroughputView]: ...
def init_model_throughput() -> None: ...   # clears the registry
```

`init_model_throughput()` is wired into `reset_run_registries()`
(`_control/eval_state.py`) so keep-alive processes and test suites start
each run clean.

`ModelThroughputView` (the read-side snapshot) adds the derived fields:
`output_tokens_per_second`, `requests_per_minute`, `retries_per_minute`,
`backoff_ratio` (window backoff-seconds from the interval overlap ÷ window
seconds — scheduled backoff per wall-clock second, summed across concurrent
generates, so it exceeds 1.0 whenever more than one generate is backing
off at once;
`backoff_ratio ÷ retry_waits_active ≈ 1` means the affected generates are
spending essentially all their time asleep), and `retry_waits_active`
(count of active samples whose current generate is sleeping in a retry
wait, derived by scanning active samples' `retry_wait` fields and matching
on the qualified-name field stamped alongside the display name, per §2 —
bounded by sample count, cheap; `ActiveSample.retry_wait` is a single
shared slot per sample, so parallel generates within one sample count as
one; the record is cleared only when the whole retried call resolves, so
the scan filters on the record's deadline — a record whose sleep already
elapsed means the next attempt is generating, not backing off).

### 2. Instrumentation points

None of the feeds add work on the hot path beyond an O(1) registry update.

**Key discipline.** The registry key is the qualified `provider/model`
string, but only the token feed naturally holds it
(`record_and_check_model_usage` computes `f"{model}"` as its dict key). The
other feeds hold the provider-*stripped* name: `get_model()` strips the
prefix before constructing the `ModelAPI`, so `ModelAPI.model_name` — and
everything derived from it (`model_retry_config()`'s strings, `HttpHooks`
construction sites, `ActiveSampleRetryWait.model`) — is bare. Feeding the
registry those strings would split every model into two rows (tokens under
`anthropic/claude-sonnet-5`; retries, backoff, and active waits under
`claude-sonnet-5`), divorcing `backoff_ratio`/`retries_per_minute` from the
tok/s they contextualize. Normalizing at the registry boundary can't repair
this (two providers can serve the same bare name), so the qualified key is
threaded explicitly — and every *displayed* string stays bare, leaving
existing trace retry lines and the ctl `retry_wait` activity view unchanged:

- `get_model()` stamps the qualified name onto the constructed `ModelAPI`
  (a `qualified_model_name` attribute, `None`-defaulted on the base class,
  set right after construction) — the same `provider/model` string that
  `Model.__str__`/`ModelName` derive. Every feed reads the stamp
  (`self.api.qualified_model_name` from the `Model` layer): `str(self)`
  routes through `ModelName` → registry info, which raises for a
  hand-constructed `ModelAPI` (built outside `get_model()`, as tests do),
  so the stamp — `None` when absent, leaving those retries unattributed —
  is the one safe source.
- `model_retry_config()` — and its batcher wrapper
  `batch_admin_retry_config()` — gain an optional
  `qualified_model_name: str | None` parameter beside the existing
  display-oriented `model_name`; `Model`'s three call sites (generate,
  compact, count_tokens) and the batchers pass the stamp.

- **Tokens** — `record_and_check_model_usage()` (`model/_model.py`) calls
  `record_generate(model, usage)` next to the existing `set_model_usage`
  calls, with the qualified key it already computes. Scope notes:
  - *Cache hits are already excluded.* The cache-hit path returns before
    the usage-recording call (`_model.py` ~L1344 early return; cached usage
    goes through `emit_model_cache_usage` instead), which is the behavior
    we want — a cache read consumes no provider capacity, and counting it
    would inflate "provider throughput" exactly when the operator is
    deciding whether the provider is usable. No gating is needed; add a
    regression test so a future refactor doesn't start counting hits.
  - `compact` calls flow through the same function and are counted: they
    consume provider capacity and produce usage. `count_tokens` does *not*
    (it returns a bare `int` with no `ModelUsage`), so its successful calls
    contribute no tokens while its 429s still increment retry counts — a
    small asymmetry to note in the endpoint docs; count_tokens traffic is
    negligible in practice.
- **Retry counts** — `report_http_retry()` (`_util/retry.py`) gains an
  optional `model: str | None = None` parameter (always the qualified name)
  and forwards to `record_retry()` when set. Four call sites pass it:
  - `Model.should_retry` (`model/_model.py`) — passes the stamped
    `qualified_model_name` (see above).
  - the `_retry_predicate` path for batchers (`model/_retry.py`) — passes
    the `qualified_model_name` threaded into `model_retry_config()`.
  - `HttpHooks.update_request_time` (`_providers/util/hooks.py`) — hooks
    are constructed in provider `__init__`s, *before* `get_model()` stamps
    the instance, so `HttpHooks` takes the owning `ModelAPI` (or a lazy
    accessor) and reads `qualified_model_name` at report time, falling
    back to unattributed when absent.
  - chatapi's `_log_and_report_before_sleep`
    (`_providers/util/chatapi.py`) — the *sole* reporter for
    chatapi-internal retries (its count-once-per-episode `before_sleep`
    fires even when attempt 2 succeeds, which `Model.should_retry` never
    sees), so omitting it would leave chatapi-provider 429s invisible to
    the registry. `chat_api_request` gains the qualified name alongside
    the bare `model_name` it already threads for logging.

  Sites without model context (e.g. `_util/asyncfiles.py`, which isn't
  model traffic at all) keep counting only toward the legacy global scalar.
  The existing double-count protections (chatapi's once-per-episode timing,
  the `_retry_predicate` handling for batchers) are unchanged — this
  parameter rides the existing single funnel rather than adding a second
  one.
- **Retry wait** — `model_retry_config()`'s `on_before_sleep`
  (`model/_retry.py`) calls `record_retry_wait(qualified_model_name,
  rs.upcoming_sleep)` alongside the existing
  `report_active_sample_retry_wait()`. (Unlike that per-sample record, it
  is *not* gated on `report_retry_wait` — a batcher admin-op backoff is no
  sample's wait, but it is still the model's scheduled backoff.) chatapi's
  `before_sleep` records its upcoming sleep too, for the same reason it
  reports the retry (above): the chatapi-internal tenacity loop's sleep is
  invisible to the outer retry loop, so skipping it would leave
  chatapi-internal backoff out of `backoff_ratio`/cumulative backoff.
  `report_active_sample_retry_wait()` in turn stamps the qualified
  name into a new `ActiveSampleRetryWait.qualified_model` field so the
  `retry_waits_active` scan (§1) matches registry keys — the existing
  `model` field, and what the ctl activity view displays, stays bare. This
  is scheduled backoff; SDK-internal waits invisible to tenacity are
  already reconciled into sample waiting time and are out of scope for the
  per-model figure (noted in the endpoint docs so the `backoff_ratio`
  isn't over-read).

### 3. ctl surface (primary)

**Endpoint**: `GET /models/throughput?window=60` — process scope (per the
three-scopes URL rule; it sits beside `POST /models/pause`). Response
envelope:

```json
{
  "as_of": "2026-08-18T21:00:00+00:00",
  "window_seconds": 60,
  "models": [
    {
      "model": "anthropic/claude-sonnet-5",
      "window_seconds": 60,
      "output_tokens_per_second": 41.7,
      "requests_per_minute": 12.0,
      "retries_per_minute": 33.0,
      "backoff_ratio": 11.2,
      "retry_waits_active": 14,
      "cumulative": {
        "requests": 4310, "output_tokens": 5210044, "total_tokens": 9422108,
        "retries": {"rate_limit": 812, "transient": 9},
        "retry_wait_seconds": 14208.5,
        "first_activity_at": "...", "last_activity_at": "..."
      }
    }
  ]
}
```

`window` is a declared, FastAPI-type-validated query param (malformed →
422) clamped server-side to the bucket horizon; strict unknown-param
rejection (`_control/strict.py`) deliberately doesn't apply to GETs, per
the "GETs stay tolerant" policy in `design/ctl/control-channel.md`. The
envelope `window_seconds` is that requested (clamped) window; each model
row carries its *effective* `window_seconds` — further clamped to
time-since-first-activity — so a consumer recovering counts from rates
(rate × window) isn't misled for a model younger than the window.
Cheap-shoveling compliance: everything is materialized at write time; the
read is a bounded sum over ≤ 60 buckets × (number of models), a
concurrency-bounded pass over each model's backoff intervals, plus one
bounded pass over active samples for `retry_waits_active`. No storage
reads, no unbounded rows. Per the version-skew rules in
`design/ctl/control-channel.md`, a new endpoint needs **no**
`CONTROL_API_VERSION` bump; the CLI passes `not_found_missing_route` so a
404 from an older server renders with the documented "older inspect —
restart the eval" guidance rather than as an error.

**CLI**: `inspect ctl model throughput [--window SECONDS] [--json]`,
following the existing `_NounGroup` / `_json_option` / `_render_table`
conventions in `_cli/ctl.py`. No `--terse`: that flag is scoped to the
task-scoped mutation verbs, and pure views ignore it (the full block *is*
the requested output, per `design/ctl/control-channel.md`). Human table
(one row per model):

```
model                          out tok/s   req/min   retries/min   in backoff   backoff (cum)
anthropic/claude-sonnet-5           41.7      12.0          33.0           14          3h 57m
openai/gpt-5                       310.2      45.0           0.0            0               –
```

The `ctl task` row also gains a per-task `tokens_per_second` derived from
data it already has (`EvalState.total_tokens` deltas are *not* windowed, so
this is computed as cumulative tokens ÷ elapsed — and named
`tokens_per_second`, not `output_…`, because the task summary tracks only
*total* tokens). This is a cheap additive field (no bump; older CLIs
ignore it), rendered by newer CLIs as a `tok/s` table column under the
same only-when-something-to-report rule as `refusals`/`http_retries` —
blank, not 0, when a row's (older) server doesn't report the key, per the
blank-≠-0 convention. It answers "which of my parallel tasks is starved?"
without a second call.

### 4. Trace surface

Two additions, both landing in the trace file unconditionally and (with one
caveat below) appearing under `inspect trace http`:

1. **Enrich the retry line.** `log_model_retry()` (`model/_model.py`)
   appends a throughput snippet to the message it already logs:

   ```
   -> claude-sonnet-5 retry 7 (retrying in 34 seconds) [RateLimitError 429] [42 out-tok/s, 14 in backoff]
   ```

   The displayed name stays bare, as today (`log_model_retry` receives
   `self.api.model_name`); the registry snapshot behind the snippet is
   looked up by the qualified key threaded per §2. This directly answers
   the issue's "hard to gauge throughput" while watching retries scroll
   by — every retry line carries the current window rate. Snapshot cost is
   trivial — a single-model bucket sum, plus the "in backoff" count from
   the active-sample scan, which is memoized for ~1s precisely because this
   caller is unthrottled and fires when active samples peak — and the line
   only changes when a retry is already happening.

   Caveat: `log_model_retry` escalates the line to `WARNING` when the
   upcoming sleep is ≥ 20 minutes (`_model.py`), and `inspect trace http`
   filters by *exact* level — so retry lines for the heaviest-throttle
   sleeps (backoff caps at 30 minutes) carry the snippet but surface via
   `inspect trace dump`, not `inspect trace http`. The periodic
   `[Throughput]` line below is unaffected (always logged at `HTTP`).

2. **Periodic snapshot line.** A lightweight run-scoped reporter task,
   started on the eval run's task group in `_eval/run.py` — run-scoped, so
   it is cancelled with the run and quiet between runs; the control server
   itself is entered at a wider scope (`_eval/eval.py`, and per eval-set in
   `_eval/evalset.py`, where under keep-alive it outlives individual runs),
   and the reporter deliberately does not share that lifetime. There is no
   existing run-scoped periodic-task helper, so this is a small new loop.
   It emits one `[Throughput]` line per model per interval (60 s), logged
   at the `HTTP` level directly via `logger.log(HTTP, ...)` — not
   `trace_message()`, which logs at `TRACE`, one notch below, and would not
   appear under `inspect trace http` — and *only when that model had a
   retry in the interval*, so quiet runs add zero trace noise. This gives
   post-mortems a coarse time series (`inspect trace dump --filter
   throughput`) without a new storage mechanism.

### 5. Live display footer

The retry counter reaches displays via two paths: `task_counters()`
(`_display/core/footer.py`) feeds the rich and textual footers, while the
plain and log displays call `task_http_retries_str()` directly. Add an
aggregate output-rate counter beside the retry count on both paths, shown
when any retries have occurred this run:

```
HTTP retries: 821  out tok/s: 352
```

Aggregate (summed across models) keeps the footer glanceable; per-model
detail is ctl's job. Gating on retries-observed avoids adding a noisy
number to healthy runs — and the gate reads the new per-run registry, not
the never-reset `_http_retries_count` scalar, so a keep-alive process's
second run starts quiet. The footer is already `@throttle(1)`d, and the
snapshot is O(models), so render cost is negligible.

## What this changes for the operator

During a throttled run: the footer shows the effective aggregate rate; one
`inspect ctl model throughput` call shows, per model across every
sample/task in the run, the recent output-token rate, how much scheduled
backoff is accumulating per wall-clock second, and how many samples have a
generate sleeping right now — the "wait vs. switch" decision inputs. After
the fact, retry lines in the trace carry the rate at the moment of each
retry, and periodic `[Throughput]` lines give a coarse series. Watchdog
scripts poll the JSON endpoint (e.g. alert when
`output_tokens_per_second` stays below a floor, or `backoff_ratio ≈
retry_waits_active`, for 10 minutes).

## Testing

- Unit tests for `TokenBuckets` (epoch tagging — a slot reused after a
  write gap must not leak the previous lap's counts into a window sum —
  window sums, clamping to first-activity), backoff-interval overlap
  (partial overlap with the window, pruning past the horizon, the
  size-threshold prune behind a long-lived head), and registry reset —
  pure functions of an injected clock, no model calls.
- `mockllm`-based test that a generate records into the registry, and a
  regression test that a cache hit does not (guarding the existing
  early-return bypass), extending existing usage-recording tests.
- Retry-path test extending `tests/model/test_chatapi_retry.py` /
  hooks tests: forced 429s increment the right model's `rate_limit` bucket
  and `retry_wait_seconds`, and don't double-count through the chatapi
  sub-layer.
- Control-channel test for `GET /models/throughput` (envelope shape,
  malformed `window` rejected with 422 by FastAPI type validation — strict
  unknown-param rejection deliberately doesn't apply to GETs, per section
  3 — and the empty-registry response) alongside existing server
  tests, plus a CLI rendering test following `_cli/ctl.py` test patterns.
- Reset test: two sequential `eval()`s in one process (keep-alive shape)
  don't leak the first run's throughput into the second.

## Phasing

1. **Registry + instrumentation + ctl endpoint/CLI** — the core of the
   issue's ask; independently shippable and immediately scriptable.
2. **Trace enrichment** (retry-line snippet + periodic snapshot).
3. **Footer aggregate** + `ctl task` per-task rate field.

## Open questions

- **Headline window default**: 60 s reacts fast but is noisy for
  low-request-rate models; 300 s is smoother. Proposal: default 60 s with
  `?window=` up to the 600 s horizon, and report `requests` in the window so
  consumers can judge significance.
- **Should batch-mode (batcher) token flow be split out?** Batched
  generates record usage on completion in bursts, which makes short-window
  rates spiky. Initial answer: no split; document the caveat and let the
  larger window smooth it.
- **Roles**: per-role (in addition to per-model) breakdown mirrors
  `role_usage` and is cheap to add later; omitted initially to keep the
  endpoint small.
- **Hooks**: a `ModelThroughputData` hook emission was considered and
  dropped — `ModelUsageData` + `ModelRetry` hooks already carry the raw
  events, so external telemetry can compute its own rates.
