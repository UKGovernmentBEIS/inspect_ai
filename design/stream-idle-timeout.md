# Stream Idle Timeout — kill stalled model calls by chunk silence, not call duration

> **Status: proposed.** Originating issue: meridianlabs-ai/inspect_ai#347 (field
> report from Slack: 16% of model API calls hanging against a 600s timeout).
> Companion to [`ctl/generate-progress.md`](ctl/generate-progress.md), which
> built the per-chunk progress channel this design turns into an enforcement
> signal, and to the live-override layer in
> `src/inspect_ai/model/_generate_overrides.py`, which a phase-2 knob joins.

## Problem

A meaningful fraction of long-running model API calls hang: the provider's
streaming response stops delivering chunks (dead connection, LB black-hole,
provider-side wedge) but nothing closes the socket, so the call sits until a
coarse timeout fires. The originating report measured 16% of calls hanging
against a 600s timeout, tuned down to 300s — the 99th percentile of
*successful* calls — and asked for exactly this: "detect streaming responses
stopping and kill a streaming response with no chunk for say 15s".

Every defense we have today is scoped to the whole attempt or the whole call:

- `timeout` (`GenerateConfig`) — the total retry budget per generate call
  (tenacity `stop_after_delay` in `model_retry_config`,
  `src/inspect_ai/model/_retry.py`).
- `attempt_timeout` — a per-attempt `anyio.move_on_after` cancel scope in
  `Model._generate` (`src/inspect_ai/model/_model.py`); on expiry the attempt
  is abandoned with `AttemptTimeoutError` and retried per `max_retries`.
- Provider SDK client timeouts (e.g. the OpenAI SDK's 600s default — the
  likely source of the report's 600s figure).

All of these must be set *above the slowest healthy call*, because they can't
tell a stall from a long generation. That forces the miserable trade the
report describes: at p99 = 300s, a stalled call still wastes 300 seconds per
attempt before retrying, and the healthy 1% beyond p99 gets killed. The
signal that actually distinguishes the two cases — chunks were flowing and
stopped — operates on a ~15s time scale, an order of magnitude sharper, and
today nothing acts on it.

We already *observe* this signal. The generate-progress design gave every
streaming attempt a per-chunk heartbeat (`ModelStreamObserver._touch_progress`
stamping `last_progress_at`), and its layer 3 redefined the ctl `idle` column
as "time since last observed progress" precisely so that "streamed + stream
gone quiet → idle climbs" would be a sharp stall signal *for a human watching
`inspect ctl sample list`*. This design is the enforcement counterpart: act on
the same signal automatically — abandon the attempt and retry — instead of
waiting for an operator (or a 300s timeout) to notice.

## Goals

- **Detect a stalled streaming attempt in O(idle timeout), not O(attempt
  timeout).** A call that has streamed nothing for N seconds is abandoned and
  retried after N seconds, however long the healthy tail of generations is.
- **Reuse the existing retry semantics wholesale.** An idle-timeout expiry is
  handled exactly like `attempt_timeout` expiry: abandon the attempt, classify
  as transient, retry per `max_retries` within the `timeout` budget.
- **One provider-agnostic implementation point.** Enforcement lives in the
  model wrapper + stream observer; providers already instrumented for the
  progress channel get it for free, and no provider code learns about
  timeouts.
- **Zero effect on calls that don't stream.** Non-streamed attempts and
  uninstrumented providers never arm the timeout — the knob cannot kill a
  call that produces no chunks by design.

Non-goals:

- **Resuming a broken stream mid-response.** SSE has no cursor; recovery is a
  fresh attempt (the wrapper's existing retry), and the partial output of the
  failed attempt is discarded exactly as it is for every other failed attempt.
- **Detecting slow-but-alive generations.** A call that is producing chunks is
  healthy by this design's definition, however slow; runaway generations
  remain the domain of the ctl monitoring surface and token limits.
- **A default-on timeout.** The knob ships opt-in with no default (see Open
  questions) — a wrong default here kills healthy calls for every provider
  whose inter-chunk gaps we haven't measured.

## What exists today (the parts we build on)

- **The stream observer** (`src/inspect_ai/model/_stream.py`). One
  `ModelStreamObserver` per generate call, installed via ContextVar around
  each provider attempt; provider streaming loops report every chunk once
  through `report_model_stream_start` / `report_model_stream_progress` /
  `report_model_stream_delta`, and each report already funnels through
  `_touch_progress()`. Those call sites are, by construction, exactly the
  points where a stall-detection clock must reset. The wrapper (not
  providers) owns attempt boundaries via `begin_attempt`, which resets
  per-attempt state — so per-attempt watchdog state has an established home.
  Anthropic's loop reports a heartbeat for *every* SDK-surfaced event
  (catch-all `else: report_model_stream_progress()` in
  `_capture_compaction_from_stream`), content or not.
- **The `attempt_timeout` machinery** (`Model._generate`,
  `src/inspect_ai/model/_model.py` ~1499–1551). A cancel scope wraps
  `self.api.generate(...)`; after the call, `cancel_called` converts to
  `AttemptTimeoutError`; `Model.should_retry` classifies that as transient
  (`report_http_retry`, no adaptive scale-down — infra noise, not provider
  pushback); the exception path discards any published partial-output
  snapshot (`stream_observer.discard_partial_output()`) and completes the
  attempt's `ModelEvent` with the error; the next attempt's `begin_attempt`
  emits the `StreamRetryEvent` boundary so accumulating `on_stream` consumers
  drop the stale prefix. **Every piece of this is reused unchanged** — the
  idle timeout differs from `attempt_timeout` only in when the scope's
  deadline moves.
- **The live-override layer** (`src/inspect_ai/model/_generate_overrides.py`):
  `timeout` / `attempt_timeout` / `max_retries` are retunable mid-run via
  `inspect ctl config` because they don't affect model outputs (excluded from
  `task_identifier`). The new knob has the same safety property and the same
  incident-response use case.

## Design

### Configuration

One new field, alongside `timeout` and `attempt_timeout` in `GenerateConfig`
(`src/inspect_ai/model/_generate_config.py`), `GenerateConfigArgs`, the
`eval()` / `eval_set()` signatures, and the CLI (`--stream-idle-timeout`):

```python
stream_idle_timeout: int | None
"""Timeout (in seconds) on silence within a streaming response — if a
streaming attempt delivers no chunk for this long, the attempt is abandoned
and retried according to max_retries. Has no effect on calls that do not
stream (see provider coverage in the docs)."""
```

Like the other retry knobs it is excluded from eval-set task identity
(`_GENERATE_CONFIG_FIELDS_TO_EXCLUDE` in `src/inspect_ai/_eval/evalset.py`):
it cannot affect model outputs, only which attempts get abandoned, so a
mid-flight change can't corrupt eval-set pairing.

### Enforcement: a deadline the stream keeps pushing forward

In `Model._generate`, alongside the `attempt_timeout` scope, each attempt
opens a second `anyio.CancelScope` with `deadline = math.inf`, nested inside
the attempt-timeout scope, and hands it to the observer before the attempt
(e.g. `stream_observer.arm_stall_scope(scope, stream_idle_timeout)`; the
reference is per-attempt state, dropped in `begin_attempt` / a `finally`).
The observer then drives the deadline:

- **Arm on first `stream_started()` of the attempt**: `deadline =
  current_time() + T`. Until then the deadline is infinite, so an attempt
  that never streams — non-streaming provider, auto-streaming that chose not
  to stream, `count_tokens` / `compact` calls, batched calls — never arms and
  can never fire. This is what makes the knob safe to set globally.
- **Bump on every report** (`stream_started`, `report_progress`,
  `report_delta` — i.e. inside `_touch_progress`, which every reporting path
  already calls): `deadline = current_time() + T`, throttled to at most one
  bump per second. Setting `CancelScope.deadline` reschedules a timer handle,
  so per-chunk rescheduling is needless work; 1-second granularity is noise
  against any sane T (≥ ~15s), and the throttle matches the observer's
  existing `PARTIAL_OUTPUT_FLUSH_INTERVAL` philosophy of bounding per-chunk
  cost.
- **The scope stays armed from the first chunk until the attempt returns.**
  Deliberately no disarm-on-stream-close: providers give the observer no
  "stream closed intentionally" signal, and the windows this leaves covered
  are ones we *want* covered — an Anthropic `pause_turn` continuation issues
  a new request between streams within one attempt, and a hang there is a
  hang; the re-opened stream's `report_model_stream_start()` re-bumps the
  deadline. Post-stream local processing is microseconds and can't
  meaningfully race a ≥15s deadline.

After the attempt, the wrapper checks the *inner* scope first:

```python
if idle_scope.cancel_called:
    raise StreamIdleTimeoutError(stream_idle_timeout)
if attempt_scope.cancel_called:
    raise AttemptTimeoutError(attempt_timeout)
```

`StreamIdleTimeoutError` gets the identical `should_retry` treatment as
`AttemptTimeoutError` (transient; `report_http_retry`; adaptive controller
doesn't scale down): a stalled connection is infra noise. Everything
downstream — partial-output discard, event completion with the error, retry
boundary to `on_stream`, retry accounting against `max_retries` and the
`timeout` budget — already exists on that path and is reused without change.

Why deadline-bumping rather than a watchdog task polling `last_progress_at`:
the observer already touches per-chunk state at exactly the points that must
reset the clock, and mutating an active scope's deadline (supported by anyio)
needs no extra task, no polling interval, and no teardown. Cost is one timer
reschedule per second of active streaming.

### Interplay with the streaming decision

Setting `stream_idle_timeout` is a *request for chunks* — stall detection
cannot work without them — so it participates in provider auto-streaming
decisions exactly as `on_stream` does: `model_stream_requested()`
(`src/inspect_ai/model/_stream.py`) returns True when the active observer has
a stall scope armed-or-armable (i.e. the call's config set the knob), so
providers with an auto/unset streaming setting stream when it is set. An
explicit provider-level streaming opt-out still wins (the knob is then inert
for that provider), same precedence as `on_stream`. This does not conflict
with generate-progress's "monitoring never turns streaming on" non-goal: like
`on_stream`, this knob is an explicit caller request with real semantics, not
a passive monitoring consumer.

### Provider coverage (and its limits)

Enforcement is entirely wrapper + observer; a provider participates iff its
streaming loop reports chunks, which is precisely the progress-channel
instrumentation table in
[`ctl/generate-progress.md`](ctl/generate-progress.md): **Anthropic and
Google are covered today; SageMaker, Grok, and OpenAI-compatible are
tracked follow-ups.** On an uninstrumented provider the knob never arms —
graceful degradation, consistent with every other observer consumer, and
`attempt_timeout` remains the fallback there.

This feature changes the priority of one follow-up row: **OpenAI-compatible**
(which today calls `await stream.get_final_completion()` without iterating
events) covers the largest share of real-world usage, and hang reports
specifically. Instrumenting it — iterate the SDK stream's events reporting
bare heartbeats, then `get_final_completion()` as today, exactly as the
generate-progress table already specifies — should ship with or immediately
after this knob, or the feature silently no-ops for the users most likely to
reach for it. Heartbeats alone suffice; per-chunk token counts stay null.

Documentation must carry the coverage table: "has no effect on calls that do
not stream" is only honest if users can see which providers stream and
report.

One sensitivity note: providers' keepalive traffic resets the clock to the
extent the SDK surfaces it to the loop. Anthropic sends periodic SSE `ping`
events; if the SDK yields them to the iterator, a server that is alive but
silent (long prompt processing, server-side tool execution) keeps the clock
fresh and the timeout fires only on genuinely dead connections — the ideal
sensitivity. Whether each SDK surfaces pings (vs. swallowing them in its SSE
decoder) must be verified during implementation; where pings are swallowed,
the practical floor for T is the provider's longest legitimate inter-chunk
gap (e.g. time-to-first-token after the stream opens, which for thinking
models can be tens of seconds). This is the main reason the knob ships
without a default.

What the timeout does *not* cover: a hang before the response stream opens
(connection establishment, request upload, waiting for response headers —
`stream_started` fires only once the SDK has entered the stream). That window
belongs to `attempt_timeout` and to SDK connect timeouts; covering it here
would require arming at request start, which would false-positive every
non-streamed call. The two knobs compose: `stream_idle_timeout` for
mid-stream stalls at chunk time-scale, `attempt_timeout` as the coarse
whole-attempt backstop.

### Phase 2 — live override via `inspect ctl config`

The originating report is an incident-response story: an operator watching a
run discover calls hanging and wants to tighten the stall response *without
killing the run*. That is exactly the use case the retry-knob override layer
exists for, and the new knob qualifies by construction (excluded from task
identity, consulted at point of use). Add `stream_idle_timeout` to
`GenerateConfigOverrideField` (`src/inspect_ai/model/_generate_overrides.py`),
resolve it per attempt in `Model._generate` via `generate_config_override()`
(next to the existing `attempt_timeout` resolution, with the same batch
carve-out — batched calls never stream, so it is doubly inert there), and
plumb the `--stream-idle-timeout` knob through `inspect ctl config`
(`src/inspect_ai/_cli/ctl/_config.py`, `_knobs.py`, the control-server
routes, and `_render.py`). One semantic note for the docs: the override is
consulted when each attempt *opens*; an attempt already mid-stream keeps its
launch deadline behavior until it resolves (drain-don't-preempt, matching the
other knobs).

Phase 2 is separable and should not gate phase 1.

## Alternatives considered

- **httpx read timeouts** (per-read-operation timeout on the SDK's HTTP
  client — for a streaming response this *is* an inter-chunk timeout).
  Rejected as the mechanism: it must be configured per provider through each
  SDK's client-construction path (and some providers don't ride httpx at
  all — boto, grpc); a read timeout applies equally to *non-streamed* calls,
  where the whole body is one read, silently converting the knob back into
  the "must exceed the slowest healthy call" trade this design exists to
  escape; and the resulting exceptions surface as different SDK-wrapped types
  per provider, each needing retry classification. The observer-based
  watchdog is one implementation, one exception type, transport-agnostic,
  and streaming-only by construction.
- **A watchdog task per attempt** polling `last_progress_at` on an interval.
  Works, but adds a spawned task + teardown per generate attempt to every
  configured call; the deadline-bump approach gets the same behavior from
  state the observer already maintains. (The polling design also quantizes
  detection latency by its poll interval — the same 1s the bump throttle
  costs, so no sensitivity is gained.)
- **Tuning `attempt_timeout` down** (status quo). This is what the reporter
  did (600s → 300s) and it demonstrates the ceiling: detection latency is
  bounded below by the slowest healthy call, and the healthy tail beyond the
  chosen percentile is sacrificed. No tuning escapes that trade; only a
  signal that distinguishes stalled from slow does.
- **Provider-side maximums** (e.g. asking providers for server-side stream
  keepalive/kill semantics). Not ours to ship, and the failure mode is often
  between us and the provider (LBs, proxies) where only the client can
  observe silence.
- **Killing the call without retry** (surface an error to the sample).
  Strictly worse than retrying: a stall is transient infra noise, and the
  wrapper's retry loop exists precisely to absorb it. Callers who want
  fail-fast semantics compose `stream_idle_timeout` with `max_retries`.

## Failure modes and edge cases

- **False positives on legitimately silent streams.** The risk case is a
  provider that opens the stream, then is silent (no events, no
  SDK-surfaced pings) for longer than T while computing — e.g. long prefill
  or server-side tool execution with a quiet wire. Mitigations: opt-in knob,
  no default; docs state the floor for T is the provider's longest healthy
  inter-chunk gap; and a false positive costs one retry (with the provider
  potentially serving a prompt-cache hit on the second attempt), not a failed
  sample. The abandoned attempt's tokens are paid for twice — same cost
  profile as `attempt_timeout` today, and strictly less wasteful than the
  300s-per-stall status quo.
- **Provider-internal restarts within an attempt** (Google's
  malformed-function-call retry → `report_model_stream_restart`): the restart
  path calls into the observer, so the clock is bumped there too
  (`output_restarted` → arm/bump like any report); the replacement stream's
  own reports keep it fresh.
- **Concurrent generates in one sample**: observers (and therefore scopes)
  are per-call via ContextVar — no cross-talk, same property the progress
  channel already established.
- **Cancellation interplay**: the idle scope nests inside the
  attempt-timeout scope, which nests inside the sample's limit scopes; an
  outer cancellation (sample timeout, operator cancel) propagates through
  both inner scopes untouched (`cancel_called` is False on scopes that didn't
  fire), so the existing cancellation handling in `Model._generate` is
  unaffected.
- **`ping`-style events resetting the clock** (see provider coverage above):
  verify per SDK during implementation; where surfaced, they make the timeout
  a dead-connection detector (ideal); where swallowed, document the larger
  floor for T.

## Testing

- `tests/model/test_model_stream.py` (extend): arming only on
  `stream_started` (a non-streaming attempt with the knob set never fires);
  deadline bumps on progress/delta reports (mock clock via anyio's testing
  utilities — the autojump clock makes the timeout paths fast); bump
  throttling; fire → `StreamIdleTimeoutError` → retry with `StreamRetryEvent`
  boundary and partial-output discard; per-attempt re-arm across retries;
  interaction when both `attempt_timeout` and `stream_idle_timeout` are set
  (inner-scope precedence); both anyio backends per the conftest hook.
- `tests/test_eval.py` / config plumbing: `--stream-idle-timeout` reaches
  `GenerateConfig`; excluded from eval-set task identity.
- Phase 2: `tests/_control/test_ctl.py` override knob round-trip alongside
  the existing `attempt_timeout` override tests.
- Live-API smoke coverage rides the provider test tiers, as with the
  progress channel (recorded-response harnesses don't exercise real stream
  timing).

## Open questions

1. **Default value** — ship `None` (off) first. Revisit a conservative
   default (e.g. 120s?) only with data on real inter-chunk gap distributions
   per provider; a wrong default silently kills healthy calls, and the
   per-provider keepalive question (pings surfaced or swallowed) must be
   settled per SDK before any default is safe.
2. **Time-to-first-chunk** — should the clock also arm at request start for
   calls known to stream, covering a hang before the stream opens? Deferred:
   the wrapper doesn't know a call will stream until the provider decides,
   and `attempt_timeout` covers that window today. Revisit if field reports
   show hangs concentrated pre-stream.
3. **Separate first-chunk grace period** (a larger allowance before the first
   chunk than between chunks, since TTFT ≫ inter-chunk gap for thinking
   models)? Deferred pending evidence that one T can't serve both; would add
   a second knob's worth of surface for a tuning refinement.
4. **Naming** — `stream_idle_timeout` chosen to echo the ctl surface's
   layer-3 "idle = time since last observed progress" semantics and to make
   the streaming-only scope explicit in the name. Alternatives considered:
   `stall_timeout` (scope not explicit), `progress_timeout` (collides with
   the progress-channel vocabulary while meaning something narrower).
