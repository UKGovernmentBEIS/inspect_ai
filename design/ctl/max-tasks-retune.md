# Runtime-tunable `max_tasks` (`inspect ctl config --max-tasks`)

> **Status: implemented** (override + handle registry in `_control/max_tasks.py`; dispatcher read in `_eval/run.py`; directive/view in `_control/limits.py`; wire in `_control/server.py`; CLI in `_cli/ctl.py`). Companion to [`control-channel.md`](control-channel.md), which owns the control-channel architecture this knob rides on. Originating issue: meridianlabs-ai/inspect_ai#218.

`inspect ctl config` can retune most of a running eval's concurrency limits
mid-flight — `max_samples`, `max_connections`, `max_sandboxes`,
`max_subprocesses`, any named `concurrency()` key — but not `max_tasks`, the
cap on concurrently-running (task × model) units. For an eval-set of many
small-to-medium tasks, `max_tasks` is often the binding constraint: the
operator watches the adaptive-connections view report controllers sitting
far below their ceiling and has no lever to feed them more work short of
cancelling and relaunching. The issue asks for exactly that lever —
"increase it when we realised we're not maxing out connection limits" —
plus, ideally, an adaptive mode that raises it automatically (see Future
work).

## Scenario

An eval-set of 40 tasks launches with the default `max_tasks`
(`max(len(models), 10)`). Each task tops out at a modest sample concurrency
(small dataset, or samples serialized by sandbox startup), so the 10
running tasks together hold far fewer connections than the provider allows.
Today: `inspect ctl config` shows the adaptive controllers cruising at a
fraction of `max_connections`, but the only fix is to cancel the run and
relaunch with `--max-tasks 25` — forfeiting in-flight work and re-running
warmup. With this design: `inspect ctl config --max-tasks 25 --reason
"connections underused"`, and the dispatcher starts 15 more tasks
immediately. The change is recorded in each affected eval log
(who / when / old → new / why), like every other retune.

The consumers are the control channel's usual two: humans at a shell, and
watchdog agents driving eval workflows — an agent that already watches
`ctl config --json` for controller headroom can close the loop itself once
the knob exists (`control-channel.md` scenario 2 is this shape).

## Why it's launch-fixed today

`max_tasks` resolves to a plain int before the run starts, then travels as
an immutable local the whole way down:

1. **Resolution** (`_eval/eval.py`): an explicit `max_tasks` is used
   directly; unset, it defaults to the distinct-model count when > 1, else
   `None`; conversation display forces 1. `eval_set` defaults it to
   `max(len(models), 10)` before calling `eval()`. Finally
   `parallel = max_tasks if max_tasks is not None else 1`.
2. **Batch shape** (`run_batches` in `_eval/eval.py`): all pending tasks go
   to one `eval_run` batch. With `parallel == 1` the batch is ordered
   sequence-major (all of task N's model fan-outs before task N+1), which —
   combined with the dispatcher's queue-order tie-break — preserves
   sequence grouping at the launch limit while keeping the whole queue
   visible to one dispatcher. (Historically `parallel == 1` ran a fresh
   `eval_run` per sequence group, which hid the queue from the dispatcher —
   see "The `parallel == 1` batch shape" under edge cases.)
3. **Dispatch** (`run_task_retry_attempts` in `_eval/run.py`): the
   dispatcher admits work with `while not cancelled and in_flight <
   parallel and pending:`, where `parallel` is a function parameter — no
   registry, no semaphore, nothing a control-server directive can reach.

Contrast with `max_samples`, which is backed by a `ResizableLimiter` in a
task-keyed registry that `_control/limits.py` can find and resize. The
task dispatcher predates the control channel and was never given an
equivalent handle. That's the gap this design closes.

One thing we get for free: the dispatcher already re-evaluates dispatch on
demand. It waits on a `Wake` that is registered as a dispatch waker
(`add_dispatch_waker` in `_control/pause.py`) so that pause/resume can poke
it. A `max_tasks` change can fire the same wakers and the loop re-reads its
limit — no new wakeup machinery.

## Design

### Semantics

- **Raising** takes effect immediately: the dispatch wakers fire, the
  dispatcher re-evaluates, and pending tasks start (model-balanced, pause
  latches respected — `pick_balanced`'s model-balancing and pause
  filtering apply as before) up to the new limit.
  Raising beyond `in_flight + pending` changes nothing until more tasks
  arrive (an enqueued task, a `TaskSource` batch, a queued retry); the
  view reports both numbers so an operator can see that.
- **Lowering never preempts** — the invariant every other limiter knob
  keeps. In-flight tasks run to completion; the dispatcher just doesn't
  start new ones until `in_flight` drains below the new limit. The view's
  `in_flight` may exceed `limit` in the interim, exactly like a lowered
  `max_samples`.
- **Floor is 1.** `max_tasks 0` would be a disguised pause with worse
  reporting; `inspect ctl process pause` is the real spelling for "stop
  dispatching", and it's reversible and labeled. (Same reasoning that gives
  `max_connections` a floor of 1.)
- **`clear` restores launch config**, like the retry knobs (see next
  section).

### An override layer, not a limiter

The natural-looking implementation — swap the `parallel` int for a
`ResizableLimiter` like `max_samples` — fits badly twice over:

- The dispatcher is a select loop, not a blocking acquire: on each wake it
  must re-check the pause latches, model balance, and the feed before
  deciding whether to start anything. A semaphore acquire has nowhere to
  sit without restructuring the loop.
- A limiter would be owned by one `run_task_retry_attempts` invocation, but
  dispatchers can be recreated within a run: tasks added via `enqueue_task`
  drive successive `run_batches` iterations (each a fresh `eval_run`), the
  `parallel == 1` path runs a fresh `eval_run` per `TaskSource` batch, and
  an eval-set in legacy `retry_immediate=False` mode re-invokes `eval()`
  per retry pass. (With `parallel > 1` a `TaskSource` feeds a single
  long-lived dispatcher via `TaskInjection`, but the other paths are
  real.) A per-dispatcher limiter silently reverts the operator's retune
  at the next dispatcher boundary.

Instead, model it on the retry knobs (`timeout` / `attempt_timeout` /
`max_retries` in `model/_generate_overrides.py`): a **process-global
override read at the point of use**. Concretely, in a small module (in
`_control`, alongside `pause.py`, which `_eval/run.py` already imports
from):

- `max_tasks_override() -> int | None` / `set_max_tasks_override(value:
  int | None)` — module-level state; setting it fires
  `fire_dispatch_wakers()`.
- A **live-dispatcher handle registry**: `run_task_retry_attempts`
  registers a handle at start (and removes it in its `finally`) exposing
  its launch `parallel`, current `in_flight`, and `len(pending)` — the
  view's data source. Registered/removed alongside the existing
  `add_dispatch_waker(wake.set)` call, so lifetime management is already
  correct there.

The dispatcher's admission check reads the effective limit each iteration:
the override when one is set (an explicit `is not None` check — `or` would
misread a hypothetical 0, see the floor below), launch `parallel`
otherwise. Every dispatcher in the process reads the same override, so a
retune survives dispatcher boundaries; `clear` returns every dispatcher to
its own launch value.

**Lifetime follows the retry-override precedent exactly**: the override is
reset at the outermost run boundary via `reset_run_registries()`
(`_control/eval_state.py` — whose docstring instructs that new run-scoped
state registers its reset there), so a later, unrelated `eval()` in the
same script starts from its own launch config. And that boundary is
`eval_set()`-aware — nested `eval()` calls skip the reset (the
`eval_set_id is None` gate) — which is precisely what makes the override
survive an eval-set's legacy `retry_immediate=False` passes: they are
nested calls within one run, not new runs.

### CLI and wire surface

Per the `ctl config` contract ("any `inspect eval` launch flag that can be
retuned while the eval runs is settable here, under the same spelling"):

```
inspect ctl config --max-tasks 25 [--reason ...] [--dry-run]
inspect ctl config --max-tasks clear
```

- **Scope: process** — one dispatcher pool per process, shared by every
  task. `_KNOB_SCOPE["max_tasks"] = "process"` is the only per-knob entry
  needed: new knobs are never version-gated (strict servers 400 unknown
  mutation params, per the skew policy in `inspect_ai._control`; the
  per-knob `_KNOB_SINCE` version table is retired). The existing
  `knob_values`/`_KNOB_SCOPE` key-parity assertion picks the entry up.
- **Value domain**: integer ≥ 1, or the keyword `clear` — a
  min-1 variant of the `_IntOrClearType` pattern the retry knobs use (they
  allow 0; `max_tasks` must not, per Semantics).
- **Wire**: `max_tasks` as an optional query param on `PATCH /config`,
  and — like the other process-scoped knobs — riding
  `GET`/`PATCH /tasks/{task_id}/config` too, parsed server-side like the
  retry knobs (string, to admit `clear`). The ≥ 1 floor must be enforced
  in that server-side parse, not just by the CLI type: `_parse_retry_knobs`
  admits 0 and the string-typed param can't ride `_limits_below_one` at the
  route declaration, so without an explicit check a raw-API caller could
  set 0 — which the admission check would read as a bogus limit (or, with
  an `or`-composed read, silently ignore). Once parsed, though, the int
  should be passed through `_limits_below_one` rather than a bespoke floor
  check, so the error shape (`max_tasks must be >= 1 (got 0)`) matches the
  int-typed knobs. Both GET views include the knob.
- **View** (both endpoints):

  ```json
  "max_tasks": {
    "limit": 25,          // effective: override ?? launch
    "launch": 10,         // the launch-resolved parallel
    "override": 25,       // null when no override is set
    "in_flight": 10,
    "pending": 30,
    "adjustable": true
  }
  ```

  `adjustable` is always `true`, following the retry-override precedent
  ("the store always exists"): a set lands in the override layer
  unconditionally and governs every future dispatch decision in the run —
  which is exactly right for the windows where no dispatcher is live (a
  batch still in startup — sandbox image pulls can run for minutes before
  `run_task_retry_attempts` registers its handle — or a `parallel == 1`
  run blocked in `TaskSource.next_tasks()` between batches). The legacy
  `retry_wait` sleep between batch-mode passes is *not* such a window: the
  control server binds per-`eval()` pass (and `--ctl-server=keep` is
  rejected with `retry_immediate=False`), so no set can land during it —
  the override's relevance to legacy mode is only that a set made *during*
  a pass survives to later passes. Skip-and-warn semantics (the
  `max_sandboxes` no-limiter pattern) would silently drop a retune landing
  in the live windows.
  `launch` / `in_flight` / `pending` are `null` with no live dispatcher,
  and the CLI notes "no task dispatcher is live — applies to task dispatch
  later in this run" so a parked or finishing process isn't misread as
  actively rebalancing.

- **Human rendering**: one line in the `ctl config` output's process
  section, e.g. `max_tasks 25 (10 in flight, 30 pending) [process]
  (launch: 10)`.

### Log recording

An applied change records a `ConfigValueChange(config="eval",
name="max_tasks", value=..., previous=...)` through the existing
`record_config_changes` path — it fans out to every live task log and
folds against the log's launch `EvalConfig.max_tasks` (which already
exists in the log schema, so no schema change). `clear` records
`cleared=True` with the removed override as `previous`, matching the retry
knobs. No-op re-sends record nothing.

One wrinkle the fold inherits: a run launched without `max_tasks` records
`EvalConfig.max_tasks = None` even though the resolved dispatch limit is a
concrete number (1, or the model count). A first retune's record then
fills `previous` from launch config as null, while the view's `launch`
reports the resolved value. Since `previous` comes from the dispatcher
handle's pre-change effective limit whenever one is live, the null only
appears in the no-live-dispatcher window; acceptable for v1 (the launch
value is recoverable from the log's config either way), but the
implementation should prefer the handle's value when available.

### Interactions and edge cases

- **Pause latches**: orthogonal and composable. A paused task stays held
  regardless of headroom (`pick_balanced` filters it out); raising
  `max_tasks` on a fully paused run dispatches nothing until resume — and
  resume's waker re-evaluates against the raised limit.
- **The `parallel == 1` batch shape**: originally `run_batches` carved a
  fresh `eval_run` per sequence group at launch, so a retune could never
  reach the queued groups — each dispatcher held one group with nothing
  pending (`in_flight: 1, pending: 0` while a dozen tasks waited in
  `eval.py`'s loop). The design initially accepted that as a carve-out on
  the theory that eval-set (default `max_tasks` 10) is where the knob
  matters; in practice, launching an eval-set with an explicit
  `max_tasks=1` and raising it mid-run is exactly the motivating scenario,
  and it was dead on arrival. `run_batches` now hands the dispatcher one
  sequence-major batch: at the launch limit the dispatcher's queue-order
  tie-break preserves sequence grouping (all of task N's model fan-outs
  before task N+1 — pinned by
  `test_initial_tasks_parallel1_preserves_sequence_grouping`), and a raise
  starts queued tasks immediately, intentionally trading the ordering
  guarantee for the concurrency the operator asked for. Costs accepted
  with the unification: all task logs are created (and sandbox `task_init`
  runs) at batch start rather than per task, matching the `parallel > 1`
  path; rich/plain display renders one aggregate results table at the end
  instead of per-task increments; and retry ordering at `max_tasks=1`
  changes — a failed task's retry attempt previously ran within its own
  sequence group's dispatcher before the next group started, whereas now
  it re-queues at the tail of the unified queue and runs after all later
  sequence groups (execution order only; results stay keyed and sorted by
  index).
- **Conversation display** forces `max_tasks = 1` at launch because the
  display renders one task's conversation. v1 does not special-case it:
  conversation runs are foreground/interactive and not the retune
  audience. If it proves a footgun, the handle can advertise
  `adjustable: false` for conversation display later without a wire
  change.
- **Sandbox pressure**: more concurrent tasks means more concurrent
  sandbox startups. `max_sandboxes` (already retunable, process-scoped)
  remains the guard rail; the docs for `--max-tasks` should cross-reference
  it.
- **Eval-set task retries**: queued retry attempts are pending tasks in
  the same dispatcher, so they benefit from (and count against) the raised
  limit like any other pending task.
- **Add-task** (`inspect ctl task add`, meridianlabs-ai/inspect_ai#222,
  planned): injected tasks enter the same dispatcher via the feed, so they
  respect (and benefit from) the live limit like any other pending task —
  no special casing needed. The add-task design originally pre-started
  `parallel` workers at session start, which a live `max_tasks` invalidates
  (a fixed pool can't honor a raise above its size);
  [`control-channel.md`](control-channel.md)'s add-task section now keeps
  the spawn-per-admitted-task dispatcher shape this design relies on.

## Future work: adaptive `max_tasks`

The issue's second ask — "adaptive setting that just runs more when it
realises we are underusing the connection limits" — is deliberately not in
v1, for reasons that don't apply to the existing adaptive sample
concurrency:

- **Task startup is expensive and uncancellable-in-spirit** (dataset load,
  sandbox fleet startup, log creation). An adaptive controller that
  overshoots on samples wastes a little; one that overshoots on tasks
  commits real resources that only drain when the task finishes.
- **The signal is per-model, the actuator is per-process.** Adaptive
  controllers report headroom per model; tasks bind to models unevenly, so
  "which task to add for this controller's headroom" is a scheduling
  question, not a threshold.
- **Within-task underuse is already handled**: on the adaptive path,
  sample concurrency tracks the controller (`DynamicSampleLimiter`), so a
  running task already grows into available connections. `max_tasks`
  headroom matters when *task count* is the binding constraint — which is
  better observed than guessed.

The manual knob is the enabling primitive either way: once it exists, a
watchdog agent (or a small script) can implement the adaptive policy
today — poll `ctl config --json`, and when the adaptive view shows
sustained headroom (`in_use` well under `max` across controllers) with
`pending > 0`, raise `--max-tasks` with a `--reason`. If a native
controller later proves worthwhile, it should follow the
`DynamicSampleLimiter` precedent: the knob then reports `adjustable:
false, tracks_adaptive: true` and the ceiling moves to a bound the
controller respects.

## Implementation plan

1. **Override + handle registry** (`_control/max_tasks.py` or folded into
   an existing `_control` module): override get/set (set fires
   `fire_dispatch_wakers()`), dispatcher-handle register/remove/read —
   and the override's reset registered in `reset_run_registries()`
   (`_control/eval_state.py`), per that function's add-resets-here
   contract, so it clears at the outermost run boundary like the retry
   overrides.
2. **Dispatcher** (`_eval/run.py`): read the effective limit in the
   admission check each iteration; register the handle next to the
   existing waker registration, remove in the same `finally`.
3. **Directive** (`_control/limits.py`): `max_tasks` knob + view in
   `process_limits` and `task_limits` (process-scoped, like
   `max_connections`); record via `_record_retune`-style logic with
   `clear` handling borrowed from the retry knobs.
4. **Server** (`_control/server.py`): `max_tasks` param on both `PATCH`
   routes (parsed like the retry knobs to admit `clear`, with the parsed
   int floored via `_limits_below_one` — see CLI and wire surface),
   included in both `GET` views.
5. **CLI** (`_cli/ctl.py`): `--max-tasks` option (int ≥ 1 or `clear`),
   `_KNOB_SCOPE` entry, `knob_values` wiring,
   `_exec_limits` pass-through, human rendering.
6. **Schema/type regeneration**: none needed — the repo's OpenAPI spec
   (`src/inspect_ai/_view/inspect-openapi.json`, generated from
   `view_server_app()` by `src/inspect_ai/_view/schema.py`) covers
   view-server routes only; the control-server config routes are not in it.
7. **Tests**: raise mid-run starts pending tasks (and wakes a waiting
   dispatcher); lower never preempts; floor-1 validation (CLI and wire);
   `clear` restores launch; override survives a dispatcher boundary but
   resets at the outermost run boundary; view fields
   (launch/override/in-flight/pending, nulls with no live dispatcher);
   log record round-trip (`config_updates`); knob-table parity (existing
   test).
