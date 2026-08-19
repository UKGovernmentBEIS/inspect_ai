# Task Drain (`inspect ctl task drain`)

> **Status: designed, not implemented.** Companion to
> [`control-channel.md`](control-channel.md) (which owns the control-channel
> architecture and reserved this directive's endpoint slot) and
> [`pause-resume.md`](pause-resume.md) (which built the stop-dispatching gate
> and deferred drain as future work). Originating issue:
> meridianlabs-ai/inspect_ai#96. Follows the cancel directives
> (`control-channel.md` "Cancel a task / a sample") and pause/resume
> (meridianlabs-ai/inspect_ai#93), whose machinery this design rides.

Drain is the missing point on the "stop a task" spectrum: stop dispatching
new samples, let in-flight samples **finish naturally** — scored on their own
terms, no interrupts — then complete the task with an ordinary terminal log.
Its neighbors, for contrast:

| Verb | Queued samples | In-flight samples | Task outcome | Reversible |
|---|---|---|---|---|
| `task pause` | held (resumable) | finish naturally | keeps running (held) | yes |
| `task drain` (this design) | abandoned | finish naturally | ordinary terminal status | no |
| `task cancel --action score\|error` | abandoned | **interrupted** with the resolution | ordinary terminal status | no |
| `task cancel` (abort) | abandoned | torn down | error status | no |

The row above drain answers "wait, then continue"; the rows below answer "stop
now, resolve in-flight work by force". Drain answers "finish with what you
have": the operator has seen enough — enough samples for the analysis, a
budget line approaching, a dataset tail not worth its cost — and wants the
work already invested to complete at full fidelity while nothing new starts.

This design also settles the two items the cancel-directives work explicitly
deferred to it (`control-channel.md`, end of "Cancel a task / a sample"):

1. **The graceful-drain cancel variant** — resolved as *subsumed*: drain
   **is** that variant, spelled as its own verb (see "One operation, one
   spelling" below). No `--action drain` is added to `task cancel`, and no
   `--force` split is needed — the existing escalation rule generalizes to an
   escalation ladder (below).
2. **Cancelling a pending eval-set retry** (a task *between attempts*, where
   `task cancel` today 409s) — resolved here for both `task cancel` and
   `task drain`: the queued retry is abandoned and the task ends with its
   last attempt's error log (see "Tasks between attempts" below).

## Mechanism: the cancel stamp, not the pause gate

The graceful cancel resolutions (`--action score|error`) already implement
drain's "stop dispatching" half. They stamp the resolution on the task's
`TaskCancel` handle (`cancel_type`), and existing machinery does the rest —
three per-sample check sites, plus the task-level completion behavior:

- **Queue exit** (`task_run_sample`, on semaphore entry): a still-queued
  sample observing a stamped graceful type abandons itself — terminal
  `cancelled` in the eval's counters, absent from the log
  (`_eval/task/run.py`, the `cancel_type in ("score", "error")` check).
- **Pause-gate escape**: `PauseGatedSemaphore`'s `escape` predicate is "any
  stamped cancel", so samples held by a pause latch wake and reach the
  queue-exit check rather than staying parked.
- **Materialization window** (after queue exit, before the sample starts):
  the sample self-checks the stamped type as it starts.
- **Task completion**: a stamped type suppresses the eval-set's in-run retry
  (`_eval/run.py` treats any graceful `cancel_type` as a user cancel), and a
  stamped score/error never fires the task's cancel scope, so the task runs
  to natural completion with an ordinary terminal status.

What makes score/error *not* drain is one extra step: after stamping, the
directive sweeps the in-flight samples with `ActiveSample.interrupt`. **Drain
is that machinery minus the sweep**: extend `CancelType` with `"drain"`,
stamp it, interrupt nothing. Queued samples abandon exactly as they do under
score/error; in-flight samples never see the directive and finish naturally;
the task completes when the last one does.

`pause-resume.md` sketched drain as "a thin composition over the pause gate
(stop dispatch + auto-resolve the task at quiesce)". The stamp turns out to
be thinner still — no new gate state, no finalize-at-quiesce hook, no
interaction with `resume` — and it inherits the cancel directives' settled
semantics (idempotence, escalation, the abandon treatment of queued samples,
retry suppression) instead of re-deriving them. The pause machinery still
contributes its escape path (held samples wake to abandon) and the dispatch
hook sites the between-attempts fix uses. See Alternatives for the full
comparison.

## One operation, one spelling: a new verb and route

The question the deferred items pose: is drain a fourth `--action` on
`task cancel`, or its own verb? Both were weighed:

**For `task cancel TASK --action drain`:** the mechanism is literally the
cancel machinery, and the `action` axis already selects how samples resolve —
`cancel` (tear down) / `error` / `score` / `drain` would order neatly by
decreasing invasiveness. One less verb; escalation and idempotence rules
already live there; a strict server 400s an unknown action value, so version
skew fails loudly with no new route.

**For `task drain TASK`:** every existing cancel action *interrupts* — the
task ends on the operator's clock (bounded by teardown or scoring). Drain
inverts that contract: the task ends on the *samples'* clock, unbounded (an
hour-long agentic sample runs for its hour). An operator or agent choosing
between "interrupt now" and "wait it out" is making the decision that
matters most at this surface, and a top-level verb puts that choice where
both discover it (`ctl task --help`); an action value buried in cancel's
flag table does not. "Drain" is also the word operators reach for — the
issue, the endpoint table, and the CLI hierarchy sketch all already say
`task drain`. And precedent: pause/resume got verbs, not cancel actions, for
the same reason (different contract, not a different resolution).

**Decision: a new verb and route** — `inspect ctl task drain TASK` /
`POST /tasks/<task-id>/drain` — implemented on the cancel stamp. The
no-alias rule keeps it to one spelling: `--action drain` does **not** exist
on `task cancel` (adding it later would create the two-names drift the CLI
conventions reject). The separate route also gives the crisp version story:
an older server answers 404 (`{"detail": "Not Found"}`), and the CLI passes
`not_found_missing_route` for the definitive "older inspect — restart the
eval" message, exactly the pause-verbs precedent. No `CONTROL_API_VERSION`
bump.

The verb-vs-mechanism split is deliberate and documented in code: the
`TaskCancelAction` type in `_control/cancel.py` already anticipated "the
task set may diverge (e.g. a future graceful-drain action)" — the *internal*
`CancelType` gains `"drain"`; the cancel directive's wire vocabulary does
not.

## CLI and HTTP surface

```
inspect ctl task drain TASK [--dry-run] [--json]
POST /tasks/<task-id>/drain?dry_run=true|false
```

- **`TASK` is required outright** — drain abandons queued samples and is not
  reversible, so it joins `task cancel` in the destructive-verb selector
  class (no sole-running-task default).
- Task-keyed like `config` / `log-flush` / `cancel` / `pause` — resolved via
  `latest_eval_for_task`, so the handle never dangles across a retry.
- Idempotent, `--dry-run`-able, `--json` with the uniform mutation envelope
  (`{target, applied, dry_run, detail}`); `detail` (and the dry-run report)
  carries the split that matters: how many in-flight samples will finish
  naturally and how many queued samples will be abandoned. Terse
  (`verb target: outcome`) rendering when stdout is not a TTY, per the
  mutation-output conventions.

## Semantics

- **In-flight samples** (started — the same `started is not None` predicate
  the cancel sweep uses) run to completion: solving, scoring, log write,
  under their original limits and config. Drain never touches them.
- **Queued samples** (parked at the sample semaphore, or held by a pause
  latch) abandon as they leave the queue: terminal `cancelled` in the
  counters, absent from the log — identical to their treatment under a
  score/error resolution, per the issue's expectation. One timing caveat:
  the abandon check runs at semaphore *entry*, so a queued sample reaches
  it only when a slot frees. Score/error frees slots immediately (the
  interrupt sweep resolves the in-flight samples); drain by definition does
  not — nothing abandons until the **first** in-flight sample finishes
  naturally, after which the queue cascades (each abandon frees a slot for
  the next waiter). An operator polling the counters may therefore see
  `queued` and `cancelled` static for as long as that first natural
  completion takes; `resolving` (see read surface) is what says the drain
  is nonetheless in effect. The mechanism is identical to score/error; the
  timing is not.
- **Samples in the materialization window** (past the queue, not yet
  started — sandbox init, sample-state creation) do not run their plan: the
  existing start-time self-check that resolves this window for score/error
  resolves a drain-stamped sample with the sample-level `cancel` interrupt —
  terminal `cancelled`, its (empty) transcript preserved in the log, not
  counted as an error. Mechanically identical to the score/error self-check
  (same `interrupt(...)` call, different action); the log-visibility
  asymmetry with queue-abandoned samples mirrors the boundary cancel already
  draws — past the queue, a sample is resolved rather than expunged. Either
  way the sample re-runs under a later explicit retry (error set → re-run).
- **Sample error retries are new work.** A sample that errors after the
  stamp with `retry_on_error` budget remaining is not re-dispatched — the
  retry re-enters the gated semaphore and abandons at the queue-exit check,
  resolving the sample as `cancelled` (counted cancelled, absent from the
  log, buffered events removed — the same treatment the cancel work settled
  for an interrupt landing in the retry-recursion window).
- **`sample requeue` is rejected** on a draining task, as on any task with a
  stamped cancel — the requeued sample would only abandon at the queue exit.
- **Task completion**: when the last in-flight sample finishes, the task
  completes naturally — results computed over the completed samples, log
  status `success` (or `error` if genuine failures crossed the fail-on-error
  threshold; drain-abandoned samples never count toward it). If nothing was
  in flight when the stamp landed, the task completes almost immediately.
- **No eval-set in-run retry**: every stamped `cancel_type` except
  `"retry"` (which requests a re-run) is a user cancel whose in-run retry
  the dispatcher suppresses; `"drain"` joins the suppressed set, inheriting
  the existing branch with zero new code.
- **The undispatched remainder stays explicitly resumable.** An explicit
  `inspect eval-retry` of the drained log works today with no new code:
  it has no status gate, and the abandoned samples are absent from the
  retry's sample source, so they run fresh while every completed sample is
  reused. Re-invoking `inspect eval-set` on the same `log_dir` needs one
  addition: its run-vs-reuse logic (`log_samples_complete`) compares
  `results.total_samples` against the dataset × epochs, and that field
  records the **planned** count — every finalize path passes
  `len(dataset) * epochs` — so a drained success log reads *complete*
  despite its absent samples, and the remainder would silently never
  re-run (the completeness check catches config drift, not partial
  execution; `completed_samples` can't stand in — it excludes errored
  samples, so consulting it would spuriously re-run legitimate
  complete-with-errors logs). The fix is an additive header count of the
  samples actually present in the log (e.g. `EvalResults.logged_samples`),
  written at finalize and preferred by `log_samples_complete` when present
  (absent on older logs → today's classification); this also repairs the
  same gap the shipped score/error resolutions already have for their
  abandoned queued samples. With that in place the issue's open question
  is settled: drain is honored for the life of the run (nothing in-process
  re-dispatches), while "go run the remainder after all" remains available
  as a deliberate later action — the same explicit/implicit split the
  per-sample cancel precedent set (the eval-set never re-runs on its own;
  an explicit retry does). Note the durability story is *stronger* than
  pause-then-kill's, not identical: a killed run leaves a non-success log
  that eval-set's status check re-runs regardless; a drained log is an
  ordinary success log, which is exactly why the completeness check needs
  the logged-samples count.

### Escalation ladder and idempotence

The shipped rule — "a plain `cancel` (abort) escalates over a pending
score/error resolution" — generalizes to an ordering by invasiveness:

```
drain  <  score / error  <  cancel (abort)
```

A request strictly *stronger* than the pending resolution applies (the stamp
is overwritten and, for score/error, the interrupt sweep runs — already-
interrupted samples keep their resolution, per the first-resolution-wins
rule; for abort, the scope fires). Anything equal or weaker is the
idempotent `changed: false` no-op, with the reason naming the pending type:

- drain on a draining task → no-op ("cancel already requested (drain)").
- drain on a pending score/error/abort → no-op (drain can't un-interrupt).
- drain (or plain cancel) on a pending **`"retry"`** stamp — the attempt
  requested a re-run and is still tearing down, before the dispatcher sets
  `retry_pending` — **applies** (`changed: true`): the directive stamps the
  retry-abandoned registry (see "Tasks between attempts") so the intent
  sticks. Inheriting the cancel skeleton's no-op here ("cancel already
  requested (retry)") would silently drop the drain — the retry then
  dispatches the whole task fresh unless the operator notices and
  re-issues, the same operator-races-the-dispatcher shape Alternatives
  rejects for the status-quo 409. A *repeat* drain/cancel landing in this
  same window consults the retry-abandoned registry first and takes the
  idempotent no-op (`changed: false`, "pending retry already abandoned") —
  the registry stamp, not the pending type, marks the intent as already
  applied, so only the first request reports the abandonment. The
  tearing-down attempt itself is
  untouched (its scope has already fired; there is nothing further to
  interrupt or overwrite). One qualification: a `"retry"` stamp is only
  honored with retry budget remaining (`run_one` gates on
  `retries_remaining > 0`, mirrored by the handle's `TaskCancel.can_retry`),
  so when `can_retry` is false no retry is coming and there is nothing to
  abandon — the honest answer is the no-op ("task already ending — retry
  request will not be honored"), not a `changed: true` claiming an
  abandonment. Score/error in this state stay the no-op —
  the attempt's samples are already resolved, mirroring their
  between-attempts rejection.
- score/error on a draining task → **escalates**: the operator decided to
  stop waiting; in-flight samples are interrupted with the resolution and
  the task still completes gracefully. This is drain's "it's taking too
  long" relief valve.
- abort on a draining task → **escalates**: teardown must always remain
  reachable (a draining task can stall on a hung sample), exactly the
  rationale for the existing escalation. This is why no `--force` flag is
  needed: force is spelled `task cancel`, and the intermediate strength is
  spelled `task cancel --action score`.
- drain on a finished task → no-op ("task already finished").
- score vs error (unordered peers): repeat with the other remains the no-op,
  as today.

The fails-on-error gate is not involved: drain resolves nothing as an error,
so it needs no `action=error`-style rejection.

### Interaction with pause

Independent intents that compose; drain does not clear latches and latches
do not block drain's stamp:

- **Drain of a (soft-)paused task**: queued samples held at the gate wake
  through the existing stamped-cancel escape and abandon; in-flight samples
  (which a soft pause never held) finish; the task completes. Consistent
  with the pause design's rule that the gate "holds starts, not terminal
  transitions" and with graceful cancel's behavior on a paused task.
- **Drain under a hard pause (`pause --now`)**: in-flight samples parked at
  the generate gate stay parked — the generate gate's escape keys on a
  per-sample interrupt (`interrupt_action`), which drain deliberately never
  stamps on an in-flight sample. (The materialization-window self-check does
  stamp one, but a sample in that window has never reached a generate call,
  so it is never the one parked at the gate.) This is correct, not
  accidental: the hard hold is an operator
  intent on *in-flight* work, and drain's contract for in-flight work is
  "don't touch". The task drains fully on `resume` (or as held samples
  resolve at their own limits). An operator who wants the drain to conclude
  resumes the relevant scope; one who wants in-flight work resolved *now*
  escalates to `--action score`, whose per-sample interrupts do pass the
  generate gate. Document the pairing in the verb's help.
- **Pause of a draining task**: the latch closes but every queued sample is
  already escaping-to-abandon and in-flight samples aren't gated by soft
  pause, so it changes nothing for this task's samples (a hard pause does
  hold its in-flight generates, as above). Allowed, idempotent, harmless.

## Tasks between attempts (`retry_pending`)

A task whose last attempt errored, with an eval-set retry queued but not
started, is today a 409 for `task cancel` ("re-issue the cancel once the
retry is running") — deferred deliberately because acting on it needs a
stop-dispatching hook at the task-dispatch layer, which pause has since
built (`pick_balanced` already consults `task_dispatch_paused`, holding
queued retries of a paused task).

**Resolution: abandon the pending retry.** The queued retry is a
`PendingTask` in the run dispatcher's queue; abandoning it means the task
ends with its last attempt's error log as the final state — the counters,
log set, and read surface all already handle that shape (it is exactly what
an exhausted retry budget produces).

- **`task cancel TASK`** (default action) on a between-attempts task:
  abandons the pending retry, `changed: true`, detail "pending retry
  abandoned — task ends with its last attempt's error log". The 409 wart
  goes away.
- **`task cancel --action score|error`** on a between-attempts task: still
  rejected (409) — there are no samples, queued or in-flight, for a
  resolution to apply to, and the task cannot reach a success log. The
  error message now points at plain `cancel` (or `drain`) instead of
  "re-issue once the retry is running".
- **`task drain TASK`** on a between-attempts task: same abandonment as
  `cancel` — the retry attempt is new dispatch, which drain forbids, and
  "finish with what you have" means the existing error log. Same
  `changed: true` and detail.
- A later `eval-set` re-invocation on the log dir re-runs the task (its
  final log is an error log), identical to an aborted task today — the
  abandon, like drain, is a this-run decision.

**Mechanics.** The directive stamps a task-id-keyed *retry-abandoned*
registry (reset at the run boundary like the pause-gate registry), clears
`EvalState.retry_pending` synchronously (and the attempt's `will_retry`
snapshot, so its cancelled samples stop rendering `pending` — see the read
surface), and fires the existing dispatch waker. Clearing `retry_pending`
at stamp time — rather than leaving it to
the dispatcher pick — makes the task read terminal on the read surface the
moment the directive returns, and closes the repeat-request window: a
second `cancel`/`drain` landing before the dispatcher's next pick sees
`completed_at` set and `retry_pending` false and takes the ordinary
idempotent no-op (`changed: false`, with the registry consulted so the
detail can say "pending retry already abandoned" rather than "task already
finished") instead of re-reporting `changed: true` for one abandonment.

One fact shapes the consume sites: the retry item is built *eagerly* —
`options.logger.reinit()` runs at retry-item construction in the
dispatcher, before the item is queued — so a queued `PendingTask` already
carries a reinitialized logger: a fresh in-memory eval entry plus a live
realtime sample-buffer database on disk (`TaskLogger.init` creates one
whenever `log_realtime` is not off). Abandoning the retry therefore always
includes a *discard* of that never-started entry (buffer-db cleanup plus
dropping the entry — the errored attempt's log on disk remains the task's
latest), wherever the abandonment lands. An implementation may instead
defer `reinit()` to attempt start (after the self-check below), leaving
nothing to discard at either site; the contract either way is that an
abandoned retry leaves no live buffer db and no phantom eval entry behind.
Two checks consume the registry for a queued item, sharing the discard:

1. **Dispatch pick** (`pick_balanced`): a pending task whose task id is
   stamped is dropped from the queue instead of dispatched (before the pause
   filter, so a paused-and-held retry is droppable too), running the discard
   on the dropped item's logger. A retry item still mid-construction
   (between `mark_eval_retry_pending` and its `pending.append`) is covered
   without a separate hook: the append fires the dispatcher wake, and the
   next pick drops it.
2. **Attempt start**: the retry attempt self-checks the stamp before
   registering its `EvalState` and abandons instead of running, with the
   same discard. This closes the pick-to-register window: a stamp landing
   after the dispatcher has dequeued the item but before the attempt
   registers must not let the retry run after the operator was told it was
   abandoned. Unlike site 1, this abandon returns through the dispatcher's
   `run_one`, and every natural return shape misfires there: a `None` log
   or a cancelled-status log reads as an external (ctrl+c) cancellation and
   ends the **whole** dispatch loop — sibling tasks and the unstarted
   eval-set queue included — raising would tear down the dispatcher task
   group, and an error-status log with no stamped type would queue another
   retry. So the contract is an explicit sentinel: `TaskRunResult` gains an
   *abandoned* marker (a dedicated field, not an overload of `log` or
   `cancel_type`), which `run_one` checks before its external-cancellation
   branch and maps to a side-effect-free finalize — release the in-flight
   slot, leave `results[item.idx]` undisturbed (it already holds the
   errored attempt's log, stored before the retry item was queued), queue
   no retry, never set the run-level `cancelled` flag.

The same registry stamp is what makes a drain/cancel stick in the earlier
window where the attempt has *requested* a retry but is still tearing down
(`cancel_type == "retry"`, before `mark_eval_retry_pending` — see the
escalation ladder). The dispatcher consumes it at its retry decision:
`run_one` consults the registry before constructing the retry item, and a
stamped task skips the construction entirely — no `retry_pending` flag, no
eager `reinit()`, so nothing to discard; the attempt's error log stands as
the task's final state, landing in `results` through the ordinary finalize
a few lines after the consult (at decision time it is still the local
`result` — for a first attempt nothing sits under that index yet — so this
path must *not* borrow site 2's leave-`results`-undisturbed contract, which
is correct only because the store has already happened by the time a queued
item is picked). A stamp landing after that
decision finds `retry_pending` set or the item queued, and falls through to
the between-attempts branch and the two consume sites above.

An earlier draft kept a fallback — a narrow 409 for the pick-to-register
window if discarding the unstarted logger entry proved thorny. Dropped: the
fallback could only ever rescue site 2 (a request context that can answer
409); site 1 runs inside the dispatcher, cannot 409, and must discard
regardless — so the discard has to be built either way, and site 2 simply
reuses it.

Everything runs on the eval's single loop, so the stamp-vs-check ordering
at each consume point is race-free; the split into multiple points exists
only because the retry decision, dispatch, and attempt start are separated
by awaits.

## Read-surface additions

- `GET /tasks` rows gain **`resolving`** (`null`, or the pending graceful
  resolution: `"drain"` / `"score"` / `"error"`). Drain's window is long by
  design — an agent polling a draining task must be able to tell "tail is
  draining" from "task is stalled", and the counters offer no early signal
  (queued samples abandon only as slots free, so `queued`/`cancelled` can
  sit static until the first natural completion — see Semantics) — and the
  same field makes a stalled score/error resolution (hung scorer) visible,
  which today's rows don't show at all. `ctl task list` renders a marker in
  the human table. Purely additive; no version bump (an older CLI ignores
  it, an older server omits it and the new CLI shows nothing).
- **`will_retry` honesty (pre-existing wart, fix alongside):** sample rows
  render a cancelled sample as `pending` ("re-run coming") when the
  attempt's `will_retry` snapshot is true. That is right for a stamped
  `"retry"` — the dispatcher re-runs exactly on that type, the case
  `will_retry` exists for — but wrong for every other stamped type:
  `"drain"`, `"score"`, `"error"`, and `"abort"` all suppress the retry, so
  a drained (or score/error-resolved) task with retry budget remaining
  shows its abandoned samples as `pending` forever. Stamping any type other
  than `"retry"` should clear the attempt's `will_retry` so they read
  `cancelled`. The retry-abandoned registry stamp clears it too — whether the
  retry was requested by a stamped `"retry"` (attempt still tearing down)
  or queued from a naturally errored attempt (no stamped type at all, the
  common between-attempts case), the abandonment means no re-run is
  coming. Small, display-only, shared with the shipped graceful cancels.

## Implementation sketch

- `CancelType` (`_display/core/display.py`) gains `"drain"`; the queue-exit
  and materialization-window checks in `_eval/task/run.py` extend from
  `("score", "error")` to include `"drain"` (the materialization self-check
  maps `"drain"` to a sample-level `"cancel"` interrupt — no fails-on-error
  downgrade needed, since a cancelled sample never counts as an error); the
  dispatcher's user-cancel branch and
  the pause-gate escape already key on "any stamped type" and need nothing.
- `_control/cancel.py`: a `drain_task(task_id, dry_run)` sibling of
  `cancel_task` — same resolution/no-op/rejection skeleton, stamps without
  sweeping; `cancel_task` gains the escalation-ladder comparison (replacing
  the score/error-only escalation special case), the pending-`"retry"`
  no-op becomes the registry stamp for drain/plain cancel (kept a no-op for
  score/error), and the between-attempts branch swaps its 409 for the
  retry-abandon path (kept 409 for score/error).
- Retry-abandoned registry (stamping also clears `retry_pending` and
  `will_retry` — amending `EvalState.retry_pending`'s "never cleared"
  docstring), the shared never-started-logger discard, and its consume
  points in `_eval/run.py`: the `pick_balanced` drop, the attempt-start
  self-check (surfaced to `run_one` as a dedicated *abandoned* field on
  `TaskRunResult`, checked before the external-cancellation branch), and
  the `run_one` retry-decision consult that skips constructing a retry item
  for a stamped task.
- Route (`POST /tasks/<task-id>/drain`) in `_control/server.py`; CLI verb in
  `_cli/ctl/_task.py` riding the shared mutation renderer with
  `not_found_missing_route`.
- Eval-set resumability: `EvalResults` gains an additive `logged_samples`
  count (samples actually present in the log), written by the finalize
  paths in `_eval/task/run.py`; `log_samples_complete`
  (`_eval/evalset.py`) prefers it over the planned `total_samples` when
  present (see Semantics — without it a drained success log reads
  complete and eval-set never re-runs the remainder).
- `GET /tasks` `resolving` field + `will_retry` clear on non-`"retry"`
  stamps; docs
  (`docs/control-channel.qmd` drain section) and CHANGELOG at
  implementation time.

## Alternatives considered

- **`--action drain` on `task cancel` (no new verb/route).** Weighed above;
  rejected for the contract inversion (interrupt-now vs wait-unbounded
  deserves top-level visibility), the operator vocabulary, and consistency
  with pause/resume getting verbs. The mechanism sharing survives the
  decision — only the spelling was at stake.
- **Drain as a pause-gate composition** (close the task gate, hold queued
  samples, finalize the task at quiesce) — the `pause-resume.md` sketch.
  Would make drain reversible until quiesce (`task resume` un-drains), but
  reversible-stop already has a verb: pause *is* drain-you-can-undo, and an
  operator who wants to think it over should pause, then drain. The
  composition costs real machinery the stamp avoids (a drain intent on the
  gate, a finalize-at-quiesce hook racing the auto-flush, `resume`
  interplay, read-surface state for held-but-doomed samples) and leaves
  queued samples in limbo (`queued` in the counters until quiesce). The
  stamp is not instant either — queued samples resolve to `cancelled` as
  slots free, starting at the first natural completion (see Semantics) —
  but each resolution is terminal rather than held, and all land strictly
  before quiesce, which is what the issue's semantics call for.
- **A `--force` flag on drain (or a drain/force split on cancel).** The
  escalation ladder makes both redundant: `--action score` is "stop waiting,
  resolve now", `task cancel` is force. Deferred item 1's "possible
  `--force` split" is thereby resolved as not needed.
- **Draining in-flight samples' *turns* (finish the current generate, then
  stop).** A different, per-sample feature (bounded-stop) with real value
  for agentic samples, but it interrupts — it belongs to the cancel/limits
  family (cf. the per-sample limit knobs), not here.
- **Acting on `retry_pending` by 409-ing until the retry starts, then
  cancelling it** (status quo). Rejected: it makes the operator race the
  dispatcher — the retry may start (and burn spend) before the re-issued
  cancel lands, and under `process pause` the retry never starts, making the
  409 a livelock ("re-issue once the retry is running" never comes true).

## Out of scope

- **Process/eval-set-scoped drain** ("drain every task and end the run").
  Draining every *running* task composes today as `process pause` (stop the
  world) plus per-task drains; the "end the run" half does not — undispatched
  eval-set tasks stay held by the pause rather than cancelled (next bullet),
  so the run quiesces without ending until a `resume` dispatches them. A
  first-class spelling belongs to the eval-set noun group (`ctl eval-set …`,
  a later phase) alongside `eval-set cancel`.
- **Not-yet-started eval-set tasks** are unaffected by a task-scoped drain
  (they have no `EvalState` to address) — holding them is `process pause`'s
  job; cancelling them outright is eval-set cancel's.
- **A drain deadline** (`--for DURATION`, auto-escalate to `--action score`
  after N minutes). An agent can compose this with two commands and a poll
  of `resolving`; build only on demonstrated demand.
