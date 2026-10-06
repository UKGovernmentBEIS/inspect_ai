# Retunable `max_samples` under adaptive connections

Design for meridianlabs-ai/inspect_ai#325: `inspect ctl config` should be able
to change `--max-samples` even when a task is using adaptive connection
concurrency.

> **Status: implemented.** Landed alongside this doc; the view shapes ship
> as typed wire envelopes (`AdaptiveMaxSamplesView` in `_control/views.py`,
> added after this doc was written).

## Problem

Adaptive connections are on by default. On that path a task's sample
concurrency is not a user setpoint: `create_sample_semaphore`
(`src/inspect_ai/_eval/task/run.py`) builds a `DynamicSampleLimiter`
(`src/inspect_ai/util/_concurrency.py`) that follows the model's
`AdaptiveConcurrencyController` to `controller.concurrency + BUFFER`
(BUFFER=5). The modify-limits directive (`src/inspect_ai/_control/limits.py`,
`task_limits`) therefore reports `max_samples` as **not adjustable** and a
`ctl config --max-samples N` request warns and applies nothing:

```
max_samples is not adjustable for this task (it uses adaptive connection
concurrency, or ran no samples in this process).
```

The only mid-run lever today is `--max-connections`, which retunes the
controller's scaling ceiling — but that conflates model-API concurrency with
sample concurrency. The operator scenarios that motivate this issue are
exactly the ones where the two must move independently:

- Sample-side resource pressure (sandboxes, host memory, disk, external
  services used by solvers/scorers) requires clamping how many samples run at
  once *without* throttling the model API, which is serving fine.
- Conversely, an operator may want more in-flight samples than
  `controller.concurrency + 5` so that sample setup (sandbox startup, dataset
  fetch) overlaps generate time — a bigger slack than the fixed BUFFER.
- The parked-limiter case (see `design/adaptive-concurrency.md`, the
  "Future work — tasks whose generates bypass the primary model" paragraph
  under "Sample-concurrency coupling"): when generates flow through a
  different model than the task's primary (model roles, agent bridge), the
  primary controller exists — created eagerly at run startup
  (`ensure_model_controller`, `_eval/run.py`) — and the limiter adopts it,
  but it never scales because its model isn't generating, so sample
  concurrency sits at `start + BUFFER` forever. The case is only indirectly
  visible today (healthy controllers, stalled sample throughput); the
  directive's "no matching connection controller" warning fires only in
  narrower variants (a connection key changed after limiter creation, the
  no-model sentinel in tests). A retunable `max_samples` gives the operator
  an immediate unblock in every variant.

At launch time an explicit `--max-samples` already wins silently over
adaptive (it builds a static `ResizableLimiter`). The gap is only that the
same decision cannot be made *mid-run*.

## Design

Give `DynamicSampleLimiter` a **pin/override** mode, retuned through the
existing `max_samples` knob:

- `inspect ctl config <task> --max-samples N` pins sample concurrency at
  exactly `N`. The limiter stops following the controller; its capacity is
  `N` (no BUFFER added — like launch-time `--max-samples`, it is an exact
  user setpoint).
- `inspect ctl config <task> --max-samples clear` removes the pin and
  resumes tracking: the limiter catches back up to
  `controller.concurrency + BUFFER` (or its initial `min(start, max) +
  BUFFER` if no controller has been adopted).

Chosen because it makes the mid-run semantics identical to the launch-time
precedence rule ("explicit `max_samples` wins silently over adaptive"), and
because `clear` mirrors the override knobs the directive already carries
(`--time-limit clear`, `--timeout clear`, …) — one keyword, one mental model
for "restore what launch config would have done".

The adaptive *controller* is untouched: it keeps governing model-API
concurrency and remains retunable via `--max-connections`. Pinning only
decouples the sample follower from it, exactly as launch-time
`--max-samples` does.

Lowering the pin below the in-flight count blocks new acquires until holders
drain — never preempts — the same semantics every other limiter knob has
(`anyio.CapacityLimiter` accepts `total_tokens` below `borrowed_tokens`).

### Why mutate in place (not swap the semaphore)

The task captures its sample semaphore object once per attempt
(`create_sample_semaphore` → the `async with sample_semaphore:` sites), and
in-flight samples must release into the same `CapacityLimiter` they acquired
from. Replacing the registry entry with a `ResizableLimiter` would leave the
running task acquiring on the old object. So the override is a mode *of* the
existing `DynamicSampleLimiter`, applied through the task-semaphore registry
(`task_sample_semaphore(task_id)`), which also means it survives in-process
retries for free (the registry is task-scoped, shared across attempts).

## Implementation plan

### 1. `src/inspect_ai/util/_concurrency.py` — `DynamicSampleLimiter`

- Store the initial capacity (`self._initial = min(start, max) + BUFFER`) so
  a clear with no adopted controller can restore it.
- Add `override: int | None` (read property) and a setter/method
  `set_override(value: int | None)`:
  - `int` → record it and set `self._limiter.total_tokens = value`.
  - `None` → drop it and re-sync: call `_on_controller_change()` when a
    controller is adopted, else restore `self._initial`.
- Guard `_on_controller_change`: return early while an override is set, so a
  controller scale event (or a `set_max` retune) cannot stomp the pin. On
  clear, the catch-up call re-reads the live controller, so no scale event is
  lost — the limiter lands wherever the controller currently is.
- Add `limit` (`total_tokens`) and `in_use` (`borrowed_tokens`) properties so
  the directive's view can report the live numbers (today only
  `total_tokens` exists, and `ResizableLimiter` already exposes
  `limit`/`in_use` — matching names lets the view code treat both shapes
  uniformly).

No locking: like every retune in this subsystem, all of this runs on the
eval's single event-loop thread (see AGENTS.md "No speculative locks").

### 2. `src/inspect_ai/_control/limits.py` — `task_limits`

- Widen the knob: `max_samples: int | Literal["clear"] | None`.
- Apply branch (currently `ResizableLimiter`-only) gains a
  `DynamicSampleLimiter` arm, implemented as a single-knob call to
  `_apply_override_knobs` (same file) rather than respelling its contract
  inline: a one-entry `values` mapping with `get_override`/`set_override`
  callbacks onto `semaphore.override` / `semaphore.set_override`,
  `config="eval"`, and the directive's existing `dry_run` / `requested` /
  `applied` plumbing. The helper already owns exactly the semantics this
  knob needs — an `int` sets the override, `"clear"` removes it, a set
  matching the active override and a clear with no override active both
  record nothing, and a record's `previous=None` means "no prior override"
  (the recording layer fills it from the log's launch config, which for an
  adaptive task is launch `max_samples=None`; that is honest). Its
  docstring gives the rationale for reusing it: these semantics "live here
  so they cannot drift apart". One behavioral note: on a no-op clear the
  helper still calls `set_override(None)` — for an unpinned tracking
  limiter the §1 clear path makes that a harmless re-sync. Only the two
  warning branches below (static-limiter `clear`, pre-adoption
  suppression) stay outside the helper.
- `"clear"` against a static `ResizableLimiter` task warns rather than
  applies: the static path's launch value is a derivation
  (`max_connections` fallback chain in `create_sample_semaphore`), not a
  stored override, and there is nothing pinned to release. Warning text:
  `"max_samples is a fixed setpoint for this task (pass an integer to change
  it; 'clear' only unpins a task using adaptive connections)"`. This keeps
  the fail-soft convention (combined PATCHes still apply their other knobs).
- The existing not-adjustable warning shrinks to the genuinely
  non-adjustable case (reused-log task / ran no samples in this process —
  `semaphore is None`).
- Suppress the "adaptive but no matching controller" warning while an
  override is pinned — concurrency is no longer stuck at the initial value,
  it is user-set (and the fix for the stuck case *is* this knob). Note the
  suppression only matters in the narrow no-adoption variants; in the
  common roles/bridge case the warning never fired to begin with (the
  limiter adopts the idle primary controller — see the problem statement).
- View: the `DynamicSampleLimiter` case moves from
  `{"adjustable": False, "tracks_adaptive": True}` to

  ```json
  {"limit": 25, "in_use": 18, "adjustable": true,
   "tracks_adaptive": true, "override": null}
  ```

  with `override` set to the pinned value when active. `tracks_adaptive`
  stays (it tells the renderer/agents what `clear` returns to);
  `adjustable` flipping to `true` is what unblocks callers. The static
  view stays as-is — the absence of `tracks_adaptive` already means
  static, and adding the key there would churn renderer and tests for no
  information.
- Docstrings: module docstring's "On the adaptive-connections path
  `max_samples` isn't a user setpoint … reported as not adjustable"
  paragraph and the `task_limits` docstring both need rewriting to describe
  pin/clear.

### 3. `src/inspect_ai/_control/server.py` — `PATCH /tasks/{task_id}/config`

- Change the `max_samples` query param from `int | None` to `str | None`
  and parse it with a single-knob use of `_parse_override_knobs` (it
  already implements int/`"clear"`/reject parsing with the friendly
  error-keyed 400). Two parity gaps mean the helper cannot be reused
  unmodified; parameterize its bounds so this knob's floor and ceiling
  both live in the parser (one rejection, one message):
  - The helper's default floor is 0 — a real value for the retry/limit
    override knobs it serves (`--max-retries 0` = fail after the first
    attempt) — so it has no `IntRange(min=1)`-equivalent rejection to
    inherit, and its floor cannot simply be raised without breaking those
    knobs. Add a `minimum` parameter (default 0) and pass `minimum=1` for
    `max_samples`: 0 must 400 at the wire, because let through it reaches
    the apply layer, where the static path's `ResizableLimiter.limit`
    (`_concurrency.py`) raises on `< 1` — an unhandled 500, not the clean
    400 the test plan expects — and the adaptive path's underlying
    `CapacityLimiter` would accept 0 outright (anyio's floor is `>= 0`),
    silently blocking all new sample acquires; `set_override` guards
    `>= 1` itself so that misuse raises rather than wedging. (Routing
    the parsed int through the shared `_limits_below_one` check instead
    would also work, but then the negative-value rejection from the
    parser and the zero rejection from `_limits_below_one` would disagree
    on the knob's floor.)
  - The helper *requires* a `maximum` argument
    (`MAX_GENERATE_CONFIG_OVERRIDE` / `MAX_SAMPLE_LIMIT_OVERRIDE`), while
    this knob has no upper bound (see Bounds). Make `maximum` optional
    (`int | None`, `None` = unbounded) — signature-only for the existing
    callers.
- `GET` is unchanged (the view shape change flows through `task_limits`).
- The process-level `/config` endpoints don't carry `max_samples`; no
  change.

### 4. `src/inspect_ai/_cli/ctl/_config.py` — the `config` command

- `--max-samples` option type moves from `click.IntRange(min=1)` to an
  int-or-`clear` param type — but not the existing `_INT_OR_CLEAR`
  instance as-is: `_IntOrClearType` accepts 0 (which must keep failing
  client-side, as `IntRange(min=1)` does today) and caps values at
  `MAX_GENERATE_CONFIG_OVERRIDE`, an upper bound this knob does not have
  (see Bounds). Parameterize `_IntOrClearType` with `minimum` / optional
  `maximum` constructor args (defaults preserving the current instance's
  behavior) and add a min-1, no-maximum instance for this option. Help
  text becomes e.g.
  `"[task] Max samples to run concurrently — under adaptive connections
  this pins sample concurrency ('clear' resumes tracking the controller)."`
- Signature/plumbing: `max_samples: int | Literal["clear"] | None` through
  `_run_config` and the request layer (mirror how `time_limit` flows).
- `_applied_knob_names` currently decides whether `--max-samples` landed
  from the view's `adjustable` flag alone, and this design breaks that
  adjustable-implies-applied equivalence in one corner: `clear` against a
  static-`ResizableLimiter` task warns and applies nothing, yet its view
  still reports `adjustable: true` — so the no-live-buffer hard error's
  "other knobs were still applied" tail would name a knob that only
  warned. Count a `clear` as applied only when the view also shows
  `tracks_adaptive` (integer sets keep the plain `adjustable` check).
- Command docstring gains a sentence on pin/clear.

### 5. `src/inspect_ai/_cli/ctl/_render.py` — human rendering

The `max_samples` block currently has three arms (adjustable / tracks
adaptive / no limiter). It becomes:

- static adjustable (unchanged): `max samples [task]: 10 (7 in use)`
- adaptive, tracking: `max samples [task]: 25 (18 in use, tracking adaptive
  connections — set to pin)`
- adaptive, pinned: `max samples [task]: 8 (8 in use, pinned — 'clear'
  resumes adaptive tracking)`
- no live limiter (unchanged): `not adjustable (no live sample limiter)`

Note the arm discriminator changes: the current block keys the static arm
on `adjustable` first, but under the new view the tracking/pinned arms
also carry `adjustable: true` — a minimal diff that keeps the `adjustable`
check first and appends arms after it would silently render adaptive tasks
with the static arm. Branch on `tracks_adaptive` (then `override`) first,
or make the static arm condition `adjustable` and not `tracks_adaptive`.
The §7 renderer tests cover this.

Dry-run `→ requested` arrows come from the existing `_target` helper and
work once the view carries `limit`.

### 6. Docs and design notes

- `docs/control-channel.qmd` knob table: replace "(not applicable under
  adaptive connections …)" with the pin/clear behavior.
- `docs/options.qmd` row for `--max-samples` already says "retunable
  mid-run via inspect ctl config" — now true unconditionally; no change
  needed beyond a check.
- `design/adaptive-concurrency.md`: update the `DynamicSampleLimiter`
  material and the "Future work — tasks whose generates bypass the primary
  model" paragraph under "Sample-concurrency coupling" (the parked-limiter
  case now has an operator remedy).
- `design/ctl/control-channel.md`: update the phase-3 `max_samples`
  description.
- `CHANGELOG.md` (`## Unreleased`): e.g. "inspect ctl config can now change
  max_samples for tasks using adaptive connections (pass 'clear' to resume
  adaptive tracking)."

### 7. Tests

- `tests/util/test_adaptive_concurrency.py` (limiter unit tests):
  - pin ignores subsequent controller scale changes and `set_max` retunes;
  - clear resumes tracking and catches up to the controller's current limit;
  - clear with no adopted controller restores `initial`;
  - pin applied before controller adoption sticks (adoption while pinned
    must not overwrite the pin);
  - `in_use`/`limit` report borrowed/total tokens.
- `tests/_control/test_limits.py` (directive tests):
  - set under adaptive → applied, view shows
    `adjustable/tracks_adaptive/override/limit/in_use`, `ConfigValueChange`
    recorded with honest `previous`; re-send of same value records nothing;
  - `clear` → override removed, `cleared=True` recorded; no-op clear
    records nothing;
  - `clear` on a static-limiter task → warning, other knobs still apply;
  - dry-run reports `requested` without applying;
  - the no-matching-controller warning is suppressed while pinned;
  - override survives an in-process retry (registry reuse).
- `tests/_control/test_ctl.py` (server/CLI):
  - PATCH with `max_samples=clear` parses; `max_samples=0` and garbage 400
    (0 must fail at the wire, not as a 500 from the apply layer);
  - the CLI option rejects 0 client-side (as `IntRange(min=1)` does today)
    and accepts values above `MAX_GENERATE_CONFIG_OVERRIDE`;
  - renderer output for tracking vs pinned.

## Behavior details and edge cases

- **Retries.** In-process (immediate) retries reuse the task's semaphore, so
  a pin survives them — same as existing `max_samples` retunes on the static
  path. Legacy batch-mode eval-set retries run as separate `eval()` calls
  that reset the registry, so they revert to launch config; that is the
  documented behavior for every retunable limit today and is unchanged.
- **Pin vs `--max-connections`.** While pinned, a `--max-connections` retune
  still moves the controller (API concurrency) but does not move sample
  concurrency; after `clear`, tracking resumes against whatever the
  controller now says. This is the point of the feature and must be stated
  in the docs.
- **Raising above the controller.** A pin higher than
  `controller.concurrency + BUFFER` is allowed (more setup overlap; excess
  samples queue on the connection limiter, exactly like launch-time
  `max_samples > max_connections` on the static path).
- **Bounds.** `< 1` rejected at the server boundary, with the apply layer
  guarding too (`ResizableLimiter.limit` and
  `DynamicSampleLimiter.set_override` both raise on `< 1` — anyio's
  `CapacityLimiter` itself accepts 0, which would silently block all
  acquires); no upper bound, matching the static knob.
- **Recording fan-out.** `max_samples` is task-scoped, so the record lands
  only in that task's log via the existing `record_config_changes`
  task-changes path; no metadata stamp needed (unlike filtered
  `max_connections`).
- **Type generation.** The config views are untyped JSON (`Any` returns) —
  no OpenAPI/ts-mono regeneration is needed.

## Alternatives considered

- **Cap semantics** — treat the retuned value as a ceiling,
  `total_tokens = min(controller.concurrency + BUFFER, N)`, so adaptive can
  still shrink below it. Rejected: it diverges from what `max_samples` means
  at launch (a pin), creates a second live influence to render and reason
  about, and the shrink-below case adds nothing — a pinned limiter above the
  controller's limit just queues samples on the connection limiter, which is
  already the static path's behavior. A cap could be layered later as a
  separate knob if a concrete need appears.
- **Swap in a `ResizableLimiter` on retune** — rejected; see "Why mutate in
  place".
- **Status quo (`--max-connections` only)** — rejected; it cannot decouple
  sample concurrency from API concurrency, which is the whole ask.
- **Also changing launch-time behavior** — out of scope; launch semantics
  already support an explicit `max_samples` and are unchanged.

## Rollout

Single PR touching the six areas above plus tests and CHANGELOG. No public
Python API changes (`task_limits` is internal to `_control`).

**Version skew** (policy: `design/ctl/control-channel.md`, "Version skew"):

- Old CLI → new server: fine. The wire change (string-typed `max_samples`
  accepting `clear`) is backward-compatible for existing integer callers —
  an integer still parses, and the new server's manual parse 400s garbage
  with the friendly error-keyed JSON body, matching the other override
  knobs.
- New CLI `--max-samples clear` → old server: the old route declares
  `max_samples` as `int | None`, so FastAPI rejects `clear` with a **422**
  (detail-keyed validation body). That is fail-loud — nothing silently
  no-ops — so no `CONTROL_API_VERSION` bump is needed per the
  control-channel convention. It does bypass both of the CLI's friendly
  error paths (`_request_json` special-cases the error-keyed 400 and the
  missing-route 404; a 422 falls through to `raise_for_status()`), so the
  operator sees a bare `Failed to set …: Client error '422 Unprocessable
  Entity' …` with no older-inspect hint. Accepted as-is: the supported
  pairing is matched CLI/server versions, the failure is loud and names
  the failed request, and teaching the CLI that 422 means "older inspect"
  would misdiagnose any future legitimate validation 422 from a current
  server as skew.
