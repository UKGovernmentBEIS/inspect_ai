# Initializing-Window Sample Cancel (`inspect ctl sample cancel` of a sample past the queue, not yet started)

> **Status: proposed.** Originating issue: meridianlabs-ai/inspect_ai#289. Follow-up to
> [`queued-sample-cancel.md`](queued-sample-cancel.md) (issue #113), whose "the
> initializing window" section deferred this, and built on the start-time self-interrupt
> that [`task-drain.md`](task-drain.md) (issue #96) landed for exactly this window. No new
> endpoint, params, or `CONTROL_API_VERSION` bump — this extends the semantics of the
> shipped `POST /evals/<id>/sample/cancel` route.

After #113, one state of a sample remains uncancellable from `inspect ctl sample cancel`:
**initializing** — past the sample semaphore, `ActiveSample` registered, `started is None`.
The route answers a truthful, retryable 409 ("initializing … retry once it is running").
The 409 assumed the window is short. It isn't always: sandbox provisioning (a k8s cold
start, an image pull) can hold a sample in initialization for minutes, and the operator
is left polling. This design makes the window cancellable, cooperatively.

## The window, as the code stands after #113 and #96

`_task_run_sample_attempt` (`_eval/task/run.py`) runs a sample through these stages once
it acquires the semaphore:

1. **Queue exit.** `queue_hooks.exit()` stamps the run *departed*; the cancel-before-start
   discard and the task-cancel abandon checks run here.
2. **`await create_sample_state(...)`.** The run is departed but has no `ActiveSample` yet
   — the *blind window* the queued-cancel design named. `cancel_sample` reaches
   `_planned_but_unqueued`, reads the departed stamp, and answers the initializing 409.
3. **`async with active_sample(...)`.** The `ActiveSample` is created (after a brief
   `await sandbox_connections()`) and appended to `active_samples()` with `started=None`,
   `tg=None`. From here the sample is visible to `find_active_sample`.
4. **Early stopping.** `early_stopping.schedule_sample` may halt the sample before it
   starts (recorded `completed`, returns).
5. **Init span.** The realtime row opens early when the sample has media to
   materialize (otherwise just before the task group), `materialize_sample_input` (media
   download), `TaskState` build, `emit_sample_init`, then **`async with sandboxenv_cm`** —
   the `max_sandboxes` wait and the sandbox provisioning — and `sandbox_connections`. This
   is where the minutes go.
6. **Start.** Inside the sample's task group, `active.start(tg)` sets `started`/`tg`, and
   immediately after it the **start-time self-check** reads `task_cancel.cancel_type`: a
   stamped `"drain"` interrupts the sample with `"cancel"`, a stamped `"score"`/`"error"`
   interrupts with that resolution (downgrading `error` to `score` when the sample fails
   on error — the task-level gate iterates every registered sample, initializing ones
   included, but a sample still in stage 2 is invisible to it). This is the hook the
   issue named.
7. The plan runs.

Two facts shape the design. First, **everything slow sits inside the `ActiveSample`'s
lifetime** (stage 5): the blind window of stage 2 holds only dataset materialization, so a
per-sample intent carried on the `ActiveSample` covers the whole operator-visible wait,
and stage 2 can keep its retryable 409. Second, **`ActiveSample.interrupt` already
stamps before it fires**: it sets `_interrupt_action`, fires the terminal event, and only
*then* raises `RuntimeError` when `tg is None`. The control channel and the TUI guard on
`started`, but one caller does not: ACP's `inspect/cancel_sample` acts on any *bound*
sample, and the ACP session is opened inside `active_sample()` before the yield — so an
observe-only `inspect/attach` to an initializing sample followed by `inspect/cancel_sample`
reaches the half-stamp today. The `RuntimeError` propagates out of the handler while the
stamp silently persists: `terminal` reads true, the retry predicate is suppressed, and
nothing ever fires it — the plan runs normally with a stale intent, and an attempt that
later errors with retries remaining is abandoned as cancelled. A latent bug, and the
clearest evidence that the intent slot already exists; only the firing needs a task
group. This design turns the dangling stamp into a real deferred interrupt.

## Semantics

The initializing row of the `sample/cancel` decision table changes; every other row in
[`queued-sample-cancel.md`](queued-sample-cancel.md) stands:

| State | `action=cancel` | `action=score\|error` |
|---|---|---|
| **initializing** (`ActiveSample`, `started is None`, no intent stamped) | **applied — deferred interrupt**: the intent is stamped now and fires as the sample starts; `changed: true`, with a `reason` saying the sample will resolve when it finishes initializing | **applied the same way** — `score`/`error` resolve at start exactly as the task-level self-check resolves them in this window; `error` is gated by `fails_on_error` as on a running sample (the `ActiveSample` is registered, so the gate sees it — no start-time downgrade is needed, unlike the task-level blind spot) |
| initializing, **intent already stamped** | `changed: false` no-op — "cancel already requested (`<action>`)" | same no-op (first resolution wins) |
| **departed, not yet registered** (stage 2) | 409 — unchanged, retryable; reworded to say the sample has left the queue but is not yet registered | 409 — same |
| running / queued / terminal / unknown | unchanged | unchanged |

Notes:

- **Outcome at start is the graceful-resolution outcome, not the queued-cancel one.** A
  deferred `cancel` resolves as an operator cancel does today: a cancelled record in the
  log (transcript holds the init events), an `operator` `SampleLimitEvent`, not counted as
  an error, re-runnable by `eval-retry` or `sample requeue`. `score` scores the empty
  state with an `operator` limit; `error` records an operator error. This is
  log-*visible*, unlike a cancel-before-start — the same boundary the drain design
  already draws: past the queue, a sample is resolved rather than expunged.
- **The sandbox is fully built, then torn down normally.** Cancellation fires only after
  `sandboxenv_cm` has entered and `active.start(tg)` has run, so the sandbox context's
  `__aexit__` (shielded when the sample's own cancel was caught) cleans up as it does for
  any interrupted sample. Nothing half-built is abandoned — which is why this must be
  cooperative rather than an external teardown (Alternatives).
- **All three actions are accepted, not just `cancel`.** The queued rows reject
  `score|error` because a queued sample will never log a record; an initializing sample
  will, and the task-level machinery already resolves this very window with `score` and
  `error`. Rejecting them here would be an arbitrary asymmetry. (A cancel-only variant is
  a one-line gate if maintainers prefer the smaller surface — Alternatives.)
- **Repeat is a no-op, unlike the running row.** Re-interrupting a *running* sample
  re-fires its cancel scope (a real action — the runner reads the live action when it
  handles the interrupt); re-stamping an intent does nothing, so the honest answer is
  `changed: false` naming the pending action. The intent is not overwritable — first
  resolution wins, the same rule the task-cancel sweep applies to samples with
  `interrupt_action` set. `dry_run` reports every row without stamping.
- **Idempotence across the start boundary.** Once the deferred interrupt fires, the
  sample is in its (shielded) logging window with `interrupt_action` set and `completed`
  unset — the same state a running sample's cancel leaves it in — so a repeat lands on the
  running row's answer until the record is readable, then on the ordinary already-terminal
  no-op.

## Mechanism: the intent *is* `interrupt_action`, deferred

`ActiveSample._interrupt_action` is already the per-sample intent everywhere except the
firing: `ActiveSample.terminal` reads it (interim scoring stops touching the sample); the
task-cancel sweep skips samples that carry one (first resolution wins); the runner's retry
predicate requires it unset (`active.interrupt_action is None`), so a stamped intent
suppresses a sample-level retry; and the drain-window branch resolves an errored attempt
carrying one as *cancelled, absent from the log*. So the design adds no second slot:

1. **`ActiveSample.interrupt(action)` defers when `tg is None`.** It stamps
   `_interrupt_action` and fires the terminal event as today, then *returns* instead of
   raising; `_fire_on_interrupt` and the scope cancel run when the interrupt actually
   fires, so a binder (the live ACP session) sees the same sequence it sees for a running
   sample. Contract: "interrupt now if the sample has started, otherwise as it starts".
   The `RuntimeError` was a programming-error guard for a state no caller reached; the
   deferral makes the state meaningful instead.
2. **The start-time self-check consults the per-sample intent first — and exclusively.**
   Immediately after `active.start(tg)`: if `active.interrupt_action` is set, call
   `active.interrupt(active.interrupt_action)` — now with a task group, it fires — and
   **skip** the `task_cancel.cancel_type` branches (an `elif`, not a fall-through). This
   matters: the task-level branches call `active.interrupt(resolution)` too, and the
   runner handles the *live* `interrupt_action`, so falling through would let a task
   `score` overwrite a per-sample `cancel`. Per-sample-wins matches the sweep's rule (a
   task-level stamp never overwrites a sample's own intent), so the start-time check and
   the sweep agree on precedence.
3. **`cancel_sample` merges the initializing case into the active row.** With an
   `ActiveSample` found and `completed is None`: `started is None` **and** an intent
   already stamped → the repeat no-op (scoped to the initializing case — the running row
   keeps re-interrupting with `changed: true`, as today); `action == "error" and
   fails_on_error` → the existing gate; otherwise `sample.interrupt(action)` (fires now or
   defers) and `CancelSampleChanged`, which gains an optional `reason` carrying the
   deferral note when `started is None` (the CLI renders it after "Cancelled …").
   `_initializing_reject` keeps only its `_planned_but_unqueued` caller (the
   departed-stamp blind window of stage 2) and is reworded for it; the un-requeue
   departed 409 (`pending_departed`) is the same window for a re-run and keeps its answer
   — once the re-run's `ActiveSample` registers, the active row catches it first and the
   deferred interrupt applies.
4. **Read surface (additive, ships with this).** Live sample rows render an initializing
   sample as `queued` today (`_active_sample_summary`), so without a field a deferred
   `changed: true` is invisible: a sandbox init that never completes would leave the
   operator with no poller-visible evidence the cancel is pending (only a repeat cancel's
   "already requested" no-op). Live rows therefore gain `interrupt: <action> | null` (the
   pending action, whatever its origin — a running sample inside its logging window
   reports it too), and `ctl sample list` renders a marker. Purely additive — an older CLI
   ignores it, an older server omits it. Distinguishing `initializing` from `queued` in
   the status vocabulary is a pre-existing conflation and out of scope here.

## Failure modes and edges worth naming

- **Init fails after the intent is stamped, retries remaining.** The retry predicate
  requires `interrupt_action is None`, so the attempt takes the existing drain-window
  branch: resolved as cancelled, absent from the log, buffered events removed,
  `queue_hooks.abandon()` stamps the key so it renders `cancelled`. For a `cancel` intent
  this is exactly the asked outcome; for `score`/`error` the outcome is cancelled rather
  than scored/errored — acceptable (an init failure leaves nothing to score) and named
  here so nobody hunts it as a bug.
- **Init fails, no retries remaining.** `handle_error` records the error (or scores it
  under `score_on_error`); the error wins over the intent, exactly as an interrupt racing
  a genuine error does on a running sample.
- **Early stopping halts the sample after the intent is stamped** (stage 4). The sample
  records `completed` and returns before start; the intent is moot. Same shape as a halt
  racing a running interrupt.
- **Task-level stamp after a per-sample intent.** The sweep skips the sample; at start
  the per-sample intent fires first. A `drain` stamped after a per-sample `score` intent
  therefore *scores* that sample — the operator's explicit per-sample choice wins, per the
  shipped "operator targeting one sample wins" rule.
- **Per-sample intent after a task-level stamp.** Today the task stamp is invisible to
  the sample resolver in this window (the sweep only touches started samples). The
  resolver stamps the intent; at start it wins over the task stamp. Same rule as above.
- **Abort (`task cancel`) with an intent pending.** The task group tears down and the
  sandbox context exits as it does for any externally cancelled initializing sample
  today; the intent is irrelevant.
- **Hard pause.** Not reachable — the sample has made no generate call.
- **Interim scoring** already excludes `started is None` samples, and `terminal` becomes
  true at the stamp, so an observer never binds to a sample about to be interrupted.
- **ACP `inspect/cancel_sample` and the TUI cancel buttons** call the same
  `interrupt()`. The TUI guards on `started`, so it is unchanged. ACP does not (see "The
  window" above): an `inspect/cancel_sample` on an observe-only-attached initializing
  sample today raises out of the handler and leaves a dangling stamp; with the deferral
  it becomes a real deferred cancel that fires at start — the latent bug is fixed as a
  side effect, and the ACP handler needs a test for exactly this case.
- **Version skew.** No new params. New CLI → old server: the initializing 409 as today.
  Old CLI → new server: a better answer to the same request (the `reason` is simply not
  rendered).
- **Crash honesty.** The intent is in-memory like all control-channel state; a process
  that dies mid-init recovers from the log, where the sample is (correctly) absent.

## Alternatives considered

- **External teardown — a cancel scope around initialization.** Rejected: cancelling
  mid-`sandboxenv_cm` entry abandons half-built sandbox state (the shielded `__aexit__`
  exists precisely because cleanup must run to completion), and the cooperative
  self-check is what the task-level machinery already uses for this window. Waiting for
  init to finish costs the operator nothing they weren't already paying.
- **Cancel-only (reject `score|error` while initializing).** A smaller table, but
  inconsistent with the task-level self-check that already applies `score`/`error` here,
  and scoring the empty state is a legitimate "record this sample and complete the eval"
  outcome. Rejected; trivially re-imposable if wanted.
- **A separate `pending_interrupt` field.** A second slot that the sweep, the retry
  predicate, `terminal`, and the drain-window branch would each have to learn; the
  existing slot already carries the right semantics everywhere except the firing.
  Rejected.
- **Making the stage-2 blind window cancellable too.** It holds no slow work (dataset
  materialization and a `sandbox_connections()` read), and covering it needs a third
  stamp on the run object plus a check between `create_sample_state` and registration.
  Not worth it; the retryable 409 stands.

## Implementation sketch (blast radius)

- `log/_samples.py`: `ActiveSample.interrupt` defers when `tg is None` (docstring updated
  to the "now or at start" contract); `_fire_on_interrupt` moves to fire time.
- `_eval/task/run.py`: the start-time self-check reads `active.interrupt_action` before
  `task_cancel.cancel_type`, fires it, and skips the task-level branches when it does.
- `_control/cancel.py`: the active row absorbs the initializing case (repeat no-op scoped
  to `started is None`, fails-on-error gate, deferred interrupt, `reason` on
  `CancelSampleChanged`); `_initializing_reject` reworded for the not-yet-registered
  window only; module and function docstrings.
- `_control/state.py`: additive `interrupt` field on live sample rows.
- `_cli/ctl/_sample.py`: render the deferral `reason` and the listing marker.
- Docs: `docs/control-channel.qmd` (the two sentences describing the blind window);
  `queued-sample-cancel.md` table row and section pointer; `control-channel.md`
  `sample/cancel` bullet; CHANGELOG.
- Tests: route-level (initializing × three actions, repeat no-op, fails-on-error gate,
  dry-run; departed-but-unregistered still 409); runner-level end-to-end with a sandbox
  stub that sleeps in `sample_init` — cancel mid-init → cancelled record, not an error,
  sandbox cleanup ran, counters `cancelled + 1` and `terminal == total`; init failure
  after an intent with retries remaining → the abandoned-as-cancelled path; per-sample
  intent precedence over a later task-level stamp (the task branch must not overwrite
  it at start); ACP `inspect/cancel_sample` on an observe-only-attached *initializing*
  sample → deferred cancel that fires at start (and the running case unchanged); run the
  runner tests under `--runtrio`.
