# Adaptive Connections

Internals of the adaptive model-connection concurrency subsystem: the per-model
controller that discovers a provider's sustainable request concurrency at
runtime, the identity scheme that keeps controllers apart, the sample-concurrency
limiter that follows them, and the control-channel hooks that observe and retune
them mid-flight. User-facing docs live in `docs/parallelism.qmd`; the control
channel itself is `design/control-channel.md`. All code paths below are in
`src/inspect_ai/util/_concurrency.py` unless noted.

## Why

A fixed `--max-connections` forces the user to guess a provider's rate limit:
too low wastes throughput, too high burns time in 429 retry loops. Adaptive
connections (default-on) replaces the guess with a feedback loop — start
conservatively, grow while the provider accepts the load, cut when it pushes
back — so throughput converges near the real limit without configuration.

## The three objects

| object | role | lifetime / scope |
|---|---|---|
| `AdaptiveConcurrency` | pydantic *config*: `min` / `start` / `max` bounds plus tuning knobs (`cooldown_seconds`, `decrease_factor`, `scale_up_percent`). Accepts `"min-max"` / `"min-start-max"` string shorthand. Defaults `10 / 20 / 100`. | plain data; copied by each consumer (see [Bounds ownership](#bounds-ownership)) |
| `AdaptiveConcurrencyController` | the algorithm: wraps an `anyio.CapacityLimiter` gating actual model API calls and moves its limit from retry/success feedback | one per (provider, account) — process-global, in the concurrency registry, created lazily on the model's first `generate()` |
| `DynamicSampleLimiter` | per-task sample-concurrency follower: keeps "how many samples run at once" proportional to the model's live connection limit | one per task, created by `create_sample_semaphore` (`_eval/task/run.py`) |

## When adaptive is active

`adaptive_active(adaptive_connections, max_connections, batch)` is the single
predicate, used by `Model._connection_concurrency`, `create_sample_semaphore`,
and eval-set's adaptive check. Precedence (all silent):

- **Explicit `max_connections` wins** — a deliberate static setting is honored
  (static semaphore path, no controller).
- **Batch mode wins** — batch APIs run on a separate quota and the batch
  worker's background-task ContextVars can't propagate retry/success signals
  back to awaiting generates, so adaptive accounting would be wrong anyway.
- `adaptive_connections=False` is the explicit opt-out; `None` (default),
  `True`, an int (max shorthand), and a full `AdaptiveConcurrency` all enable.

## The controller algorithm

Slow start + AIMD, driven only by feedback that says something about the rate
limit:

- **Slow start**: until the first rate-limit signal, each clean *round* doubles
  the limit (capped at `max`). A round is `max(current_limit,
  ROUND_SIZE_FLOOR=4)` consecutive clean successes.
- **Steady state**: after the first cut, a clean round adds
  `max(1, round(limit * scale_up_percent))` (default 5%), rounded up to a
  "nice" number (multiples of 5 above 10), capped at `max`.
- **Cut**: a rate-limit retry multiplies by `decrease_factor` (default 0.8),
  rounded down to a nice number, floored at `min`. Cuts are debounced by a
  cooldown (default 15s, extended by the server's `Retry-After` /
  `x-ratelimit-reset-*` when larger) — one rate-limit *episode* produces many
  retries but at most one cut.
- **Saturation gate**: a round only counts toward growth if peak in-flight
  reached `SATURATION_THRESHOLD=0.8` of the current limit (tracked by
  `_SaturationTrackingLimiter` on each acquire). Without this, a trickle of
  successes would grow a limit the workload never actually exercised, banking
  untested headroom that blows up when work surges.
- Successes arriving *during* a cooldown are discarded entirely — they were
  in flight before the cut and say nothing about the new lower limit.

Every change is appended to a bounded history (`HISTORY_LIMIT=200`) as
`LimitChangeRecord = (timestamp, name, old, new, reason)` with reason
`slow_start` / `steady_state_up` / `rate_limit` / `manual` (see
[Control channel](#control-channel-interactions)).

### Signal flow

The controller lives *outside* the request path; signals reach it via
ContextVars set by `Model._connection_concurrency` for the duration of each
generate (`_model.py`):

- `report_http_retry(kind, retry_after)` (`_util/retry.py`) — called by the
  retry machinery and provider SDK hooks. `kind="rate_limit"` (429s and
  provider equivalents, classified per-provider via `ModelAPI.should_retry`'s
  `RetryDecision`) calls `notify_retry` → possible cut. `kind="transient"`
  (5xx, timeouts) only sets `_request_had_retry` — pausing scale-up (the
  eventual success won't count) without shrinking.
- On a completed generate (`_model.py` ~1300), `notify_success()` fires only if
  the logical request had **no retries and was not a cache hit** — cache hits
  don't exercise the rate limit, and successful-after-retry is neutral.

## Identity: keys vs names

The concurrency registry stores entries by **key**; the controller's **name**
is only a display string, and the two must not be conflated:

- key = `model_concurrency_key(api)` = `Model{ProviderClass}:{connection_key()}`
  (`_model.py`). Providers scope `connection_key()` by *account* (e.g. the
  initial API key), because rate limits are per-account. The provider-class
  prefix keeps `openai/gpt-5` and `azureai/gpt-5` apart even when their
  connection keys coincide.
- name = `str(ModelName(model))`, e.g. `"openai/gpt-4"`.

So two `get_model("openai/gpt-4")` on different API keys create **two
controllers with the same name and different keys** — correct, since each
account discovers its own limit. The registry additionally suffixes storage
keys with `#adaptive` / `#static` so an adaptive and a static context for the
same key coexist (preserving the "explicit `max_connections` wins" rule).

Each controller carries its registry key as `controller.key` (stamped by the
registry at creation; defaults to `name` for direct construction in tests).
Anything that needs to find *a specific model's* controller matches on `key`.
Display names are for humans — the `ctl limits --model` filter matches names
because a human types them.

## Sample-concurrency coupling

Samples do expensive setup (sandboxes, state) before generating, so
`create_sample_semaphore` (`_eval/task/run.py`) prevents starting far more
samples than the model can serve:

- explicit `--max-samples` → static `ResizableLimiter` (a user setpoint).
- adaptive path → `DynamicSampleLimiter(resolved_config,
  model_concurrency_key(model.api))`: starts at `min(start, max) + BUFFER`
  (BUFFER=5) and follows **its own model's controller** to
  `controller.concurrency + BUFFER` via the controller's observer callback
  (subscribing to the matching controller whether it already exists or is
  created later, via the module-level controller-created hook — the controller
  usually appears on the model's first generate, after the limiter is built).
- otherwise → static `ResizableLimiter` sized from `max_connections` /
  provider default.

**The key scoping is load-bearing.** Controllers are process-global, and a
process routinely hosts several: eval-set sibling tasks, grader/scorer models,
the same model on another account. The limiter reads the *live* controller
state (so a mid-flight ceiling retune propagates — see below) but only from
the controller registered under its own model's connection-pool key; an
unscoped derivation would let a grader model's higher ceiling start far more
samples than the task's model can serve. Both sides compute the key with the
same `model_concurrency_key` helper so they cannot drift, and because the
registry coalesces on key, at most one controller ever matches.

If the controller never materializes under the expected key, the limiter just
stays at `start + BUFFER` — conservative and bounded. (`create_sample_semaphore`
leans on this when no `ModelAPI` is available — tests only — by passing a
`"<no-model>"` sentinel key that matches nothing.)

Sample semaphores (all three paths) are **task-scoped, not attempt-scoped**:
`create_sample_semaphore` keeps a task_id-keyed registry
(`_task_sample_semaphores`, reset per run by `init_concurrency`) and an
in-run (immediate) task retry reuses its predecessor's semaphore — legacy
batch-mode retries (`retry_immediate=False`) run as separate `eval()` calls,
each resetting the registry (required: the limiters are event-loop-bound),
so those revert to config. This makes a
mid-flight `ctl limits --max-samples` retune survive a retry (the runtime
setpoint wins over re-deriving from config — in-process retries share their
config anyway) and makes a retune against a superseded attempt's eval_id land
on the limiter the live attempt drains from — consistent with how the other
retunable limits (controllers, sandbox limiters) already persist across
retries via their own process-global registries.

### Bounds ownership

Three `AdaptiveConcurrency` objects exist per adaptive task and none is
shared: the controller `model_copy()`s the config it's given (callers can pass
one instance to several controllers; sharing would leak a `set_max` retune of
one controller into another's ceiling), and the `DynamicSampleLimiter` gets a
separate `resolve_adaptive()` result but treats it as initial-value-only —
runtime truth is always the live controller. The controller's private copy is
the single authority for the bounds at runtime.

## Control-channel interactions

See `design/control-channel.md` ("Adaptive connections" sections) for the
endpoint/CLI surface. The couplings that live on this side:

- **View**: the `/limits` view reports each controller's live `concurrency`,
  exact `in_use` (read from `borrowed_tokens`, not derived — the derivation
  under-reports after a shrink below in-flight), `min`/`max` bounds, and
  recent history.
- **Retune**: `set_max(new_max)` moves the ceiling. Lowering clamps the live
  limit down immediately (blocking new acquires until in-flight drains — never
  preempting) and records a `manual` history entry; raising only lifts the
  ceiling and lets the algorithm climb there on its own. The sample limiter
  follows both through the observer chain, because it reads live controller
  state rather than any snapshot.
- **Log capture**: `collect_eval_data` (`_eval/task/log.py`) copies controller
  history into `EvalStats.connection_limit_history`, whose schema enum covers
  only the adaptive reasons — `manual` entries are skipped there (they're an
  external override, not an adaptive-scaling decision) and stay visible live
  via `ctl limits`.

## Lifecycle

`init_concurrency()` (called per eval run from `_eval/context.py`) replaces
the registry — dropping all controllers and their observer lists — and clears
the module-level controller-created observers and the sandbox-limiter
registry. Controllers and limiters therefore never outlive a run; nothing
unsubscribes individually.
