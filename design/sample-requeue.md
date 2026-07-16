# Sample Requeue (`inspect ctl sample requeue`)

> **Status: proposed** (design only — no implementation yet). Companion to [`control-channel.md`](control-channel.md), which owns the control-channel architecture and pins this directive's surface (the phase-3 endpoint table, "Other directives", and the CLI hierarchy); this doc owns the requeue semantics and the eval-runner changes it needs. Originating issue: meridianlabs-ai/inspect_ai#97.

`inspect ctl` can cancel a running sample and (via the eval-set retry loop or `inspect eval-retry`) re-run failures *between* attempts — but there is no way to re-run one failed sample *inside* the attempt that is still running. An operator or watchdog who sees a sample die to a transient infrastructure error (a sandbox that failed to start, a provider incident that outlived the retry budget, a mistaken `sample cancel`) today either waits for the whole task to finish and retries the attempt, or accepts the loss. **Requeue** re-adds one errored/cancelled sample to the live run: it goes to the back of the sample queue and re-runs under the task's normal machinery, and the run's final log and counters reflect the fresh outcome.

Requeue is also a building block other roadmap items are waiting on: hard pause (interrupt-and-requeue in-flight samples, meridianlabs-ai/inspect_ai#103) consumes it directly, and the injectable sample scheduler it introduces is the same enabler the dynamic-sample work (meridianlabs-ai/inspect_ai#36) needs.

## Scenarios

- **Transient failure, live run.** A sample errors after exhausting `retry_on_error` during a provider incident; the rest of the run is healthy. Requeue it once the incident passes — no need to wait for the task to finish and ride the eval-set retry (which re-runs at attempt granularity and, for a standalone `inspect eval`, doesn't exist at all).
- **Undo a cancel.** An operator (or confused agent) cancelled the wrong sample with `ctl sample cancel`. Requeue restores it; a checkpointed solver resumes from its checkpoint rather than starting over.
- **Watchdog remediation.** A scripted watchdog detects samples that errored for a known-transient reason (a specific exception class in `sample errors --json`) and requeues them, keeping the run converging without human attention.
- **Hard pause (future, #103).** `pause --now` = interrupt in-flight samples as cancelled + requeue them, so resume re-runs them. Pause/resume v1 (quiesce) shipped without it; requeue is the missing half.

## Surface

Exactly as pinned by `control-channel.md` (endpoint table and "Other directives"):

- **`POST /evals/<id>/sample/requeue?sample_id=<sid>&epoch=<n>[&dry_run=true]`** — attempt-scoped like `sample/cancel` (the sample belongs to one attempt's log). Sample addressing is by **query param**, never a path segment (sample ids may contain `/`, `?`, `#`). `epoch` **fails closed**: it is required, and omitting it is a 400 — the same rule as `sample/cancel`, because a defaulted epoch resolves to a *different sample* and must never be mutated silently. All params are individual scalar query params so the strict-mutations dependency (`_control/strict.py`) derives the allowed set correctly.
- **CLI: `inspect ctl sample requeue TASK SID [EPOCH] [--dry-run] [--json]`.** `TASK` resolves by the standard selector (id prefix, then name) to the latest attempt client-side. `EPOCH` is required whenever the task runs more than one epoch (mutation selector rule; the client-side gate reads the task summary's `epochs` field, exactly as `sample cancel` does at `_cli/ctl.py`'s `_run_sample_cancel`). `--json` returns the uniform mutation envelope `{target, applied, dry_run, detail}` via `_mutation_envelope`, with the resolved `{task_id, task, sample_id, epoch}` echoed in `target`.
- **No `CONTROL_API_VERSION` bump.** New route: an older server answers with the stock `{"detail": "Not Found"}` 404, distinguishable from a handler's `{"error": ...}` entity 404, so the CLI passes a `_REQUEUE_ROUTE_MISSING` message to `_request_json(..., not_found_missing_route=...)` and reports "older inspect — restart the eval" definitively. No `_KNOB_SINCE` entry (that table is for pre-strict PATCH-config knobs only).
- **Security.** First-class phase-3 mutation: rides the phase-3 hardening (SO_PEERCRED UID check, self-targeting guard — meridianlabs-ai/inspect_ai#99) when that lands.

## Semantics: which states are requeueable

The decision table, by the sample's current status (the `state.py` derivation: running / completed / error / cancelled / pending / queued):

| Prior state | Result | Why |
|---|---|---|
| `error` (terminal) | **applied** (`changed: true`) | The headline case. |
| `cancelled` (terminal) | **applied** (`changed: true`) | Includes operator `sample cancel --action cancel` and hard-pause interrupts. |
| `queued` / `running` / `pending` | **no-op** (`changed: false`, status in `detail`) | The desired end state — "this sample runs (again) to a fresh outcome" — is already scheduled or in progress. This is what makes double-requeue safe (below). `pending` covers both never-started samples and cancelled-with-retry-coming. |
| `completed` | **409 error** | Out of scope: re-running or re-scoring a successful sample is #91's territory (interim/re-scoring) and `eval-retry` + invalidation's territory post-hoc. An error rather than `changed: false` because the desired end state will *not* come to pass — a success-shaped no-op would mislead a retrying agent. |
| unknown `(sample_id, epoch)` | **404** (`{"error": ...}`) | Handler 404 (carries the `error` key), per the control-server convention. |
| task finished / fanout drained | **409 error** | "Task already finished — re-run failures with `inspect eval-retry` (or re-invoke `inspect eval-set`)." See the acceptance window below. |
| task cancel in flight (`TaskCancel.cancel_type` set) or drain stamped | **409 error** | The queue-exit checks would abandon the re-run as `cancelled` anyway; accepting would be a lie. |
| between attempts (`EvalState.retry_pending`) | **409 error** | The queued task retry re-runs failed samples anyway; the error says so ("retry pending — the sample will re-run when the retry attempt starts"). Same honesty rule as `task cancel`'s between-attempts 409. |

**Idempotence is the headline constraint** (agent shape constraint 4 in `control-channel.md`: "`requeue_sample` called twice must not double-queue"). Two mechanisms deliver it:

1. **A pending-requeue set.** The accept path records `(sample_id, epoch)` in a per-attempt set *synchronously* (before any await), and the re-run removes it when it records its terminal outcome. A repeat requeue checks the set first → `changed: false`. This closes the window between accept and the re-run's `ActiveSample` appearing in `active_samples` (the re-run coroutine is `start_soon`ed, so it hasn't necessarily run to its first await when the directive returns) — without it, a fast double-call could double-queue.
2. **The status table above.** Once the re-run is visible (queued/running), the ordinary status check reports `changed: false`; after it terminates, the set is clear and the sample is genuinely requeueable again (a re-requeue after a second failure is legitimate, not a bug).

Everything runs on the eval's single loop and the accept path has no await between check and enqueue, so there is no race window (the same argument as task-cancel's stamp-then-interrupt).

**`--dry-run`** reports what would be re-run without mutating: the resolved target, its current status and prior error (message + retry count), the attempt number the re-run would be, and whether a checkpoint resume is available. All the reject rows above report their error under dry-run too, so an agent can probe safely.

## Attempt identity: fresh uuid, seeded error history

The re-run is shaped like a **single-sample task-level retry**, not like an in-process `retry_on_error` recursion:

- **Fresh sample uuid.** The re-run's `TaskState` mints a new uuid (pass `sample_uuid=None` to `create_sample_state`), as the task-retry reuse path does. The uuid-reuse in `task_run_sample`'s retry recursion exists to tie together the attempts of *one* `task_run_sample` call; requeue starts a new call.
- **Seeded error history.** The prior terminal record seeds the re-run exactly as `eval_log_sample_source` seeds a task retry: read the prior `EvalSample` (from the buffer/recorder — it's the same record `sample_error_detail` serves), then `_resume_or_seed_retry` semantics — a checkpointed sample resumes from its checkpoint (`ResumeCheckpoint`), an errored one carries `previous_attempt_errors = _seed_error_retries(prior)` (prior `error_retries` + the terminal error, **cancellations skipped** — a cancellation is not a genuine error, per the established rule). So `sample show` reports the full retry history across the requeue, and `retries` counts stay coherent.
- **Fresh `retry_on_error` budget.** The re-run gets `config.retry_on_error` again with `error_retries=[]`, prior attempts riding in `previous_attempt_errors` — identical to a task-level retry. This also answers #103's open question for the requeue path: interrupted/requeued attempts do **not** consume the sample-level retry budget.

**Why this makes the events cursor just work.** The cursor's attempt nonce is `{uuid or "sid:epoch"}:{len(error_retries)}` (`_control/events.py`, `_attempt_nonce`). A fresh uuid changes the nonce unconditionally, so a cursor from the failed attempt no longer matches and the server signals a reset (restarts from offset 0) instead of silently applying a stale index — the design doc's stated requirement. The alternative (reuse the uuid, rely on the attempt count growing) is subtly broken for **cancelled** samples: `_seed_error_retries` deliberately skips cancellations, so the attempt count would *not* grow, the nonce would collide with the prior attempt's, and a stale cursor would silently serve the new attempt's events under the old attempt's index. Fresh uuid closes that hole structurally, and spares the accept path from having to recover the old uuid at all.

## Counter, log, and results reconciliation

The prior attempt already bumped a terminal bucket in `EvalState`, may have a terminal record in the log/buffer, and returned a result into the task's in-memory results. All three must re-bucket coherently (the counters, not the listing, are authoritative for totals — `total` never changes; the sample re-occupies its planned slot):

- **Counters.** A new `record_sample_requeued(eval_id, prior_status)` in `_control/eval_state.py` decrements the prior bucket (`errored` or `cancelled`, chosen by the prior record's status) under the registry lock, called synchronously in the accept path. The re-run bumps a bucket again at its own terminal outcome, so `terminal == total` holds at the end. Cumulative usage (`total_tokens` / `total_messages`) is **not** rolled back — the prior attempt's spend was real. `finalize_eval`'s shortfall folding still reconciles the edge where the re-run is torn down without recording (e.g. an abort while it is parked at the semaphore): the decrement left `terminal == total - 1`, and the fold adds the missing 1 to `cancelled`.
- **Fail-on-error accounting.** If the prior attempt was an *error*, the accept path decrements `SampleErrorHandler.error_count` (the requeue capability closes over the handler), so the end-of-task `_should_eval_fail` evaluation reflects final outcomes; a re-run that errors again re-increments through the normal path. A cancelled prior attempt never counted, so nothing to decrement. Note the population of requeueable errors is naturally limited: under strict `fail_on_error=True` a sample error tears the task down at the moment it becomes final (the handler re-raises), so errored-but-still-running states arise with `fail_on_error=False`, an uncrossed fractional/absolute threshold, or `continue_on_fail` / `score_on_error` — decrementing can never "un-fire" a raise, only correct the final tally.
- **Log records.** Samples are keyed by `(id, epoch)` everywhere in the recorder (buffer rows, summary dedup, and the zip member `{id}_epoch_{epoch}.json`) — the uuid is not a log key — so the re-run's `log_sample` cleanly **supersedes** the prior terminal record, exactly as task-retry re-logging already relies on. At re-run start, `logger.remove_sample(id, epoch)` drops the prior attempt's buffered events (the same call the retry recursion makes at `task/run.py`).
- **In-memory results / metrics.** Task metrics are computed from the fanout's returned score dicts, *not* re-read from the log — so the scheduler (below) collects results into a dict keyed by `(sample_index, epoch)` instead of a positional list, and a requeued sample's fresh result **replaces** its prior entry. Without this, the log would show the new outcome while the metrics reflected the old one.
- **Listing coherence.** Between accept and the re-run's first log write, the merge in `state.py` would let the prior *flushed* terminal summary supersede the fresh queued/running row (the "terminal supersedes still-running" rule exists for the post-scoring logging window). The status derivation consults the pending-requeue set: for a key in the set, the active row wins (and a not-yet-active key renders `pending`). The `sample show` read echoes the requeue in its history so a wrongly-targeted requeue is visible in an agent's context.
- **Eval-set interaction.** Falls out of the accounting: a requeued-and-now-successful sample no longer counts toward the error threshold, so a task that ends clean is not retried by the eval-set; a task that still crosses the threshold retries as usual, and the retry's sample source sees the *superseded* (fresh) records.

## Runner mechanics: the injectable sample scheduler

This is the real eval-runner change, and the reason requeue is one of the "bigger" phase-3 directives.

**Today there is no live sample queue.** `task_run` fans out every `(sample_index, epoch)` as a coroutine up front via `tg_collect([...])` (`_eval/task/run.py:775`), all parked at the sample semaphore; the "queue" is emergent from the semaphore, and the task group is created and drained inside `task_run` with a fixed member list. The issue's guess that `task add`'s "always the scheduler path" work is the enabler is close but not exact: that scheduler is the **task**-level queue (`run_multiple`'s dispatch loop in `_eval/run.py`); requeue needs the **sample**-level fanout inside one task to become injectable. Different layer, same wiring pattern (a state-registered capability invoked from the route on the eval's loop). What *is* genuinely shared: the injectable sample scheduler is the enabler the dynamic-sample work (#36) needs too, so it should be built as a small reusable unit, not a requeue special case.

**Design: replace the one-shot `tg_collect` with a `SampleScheduler`** owned by `task_run`:

- A task group that starts all initial `run_sample(sample_index, epoch)` coroutines (unchanged behavior), each wrapped to write its result into the keyed results dict and decrement an `outstanding` counter.
- A **dispatcher coroutine inside the same group** (the `_Wake` + pending-list pattern `run_multiple` already uses; a route must not `start_soon` into a nursery it isn't inside — the same constraint the add-task design notes) that drains a pending-requeue list and `start_soon`s a re-run per accepted entry.
- **Close condition:** `outstanding == 0` and the pending list is empty → the dispatcher exits, the group drains, `task_run` proceeds to metrics/reduction exactly as today. Single-loop synchronicity makes accept-vs-close race-free: the accept path checks `outstanding > 0` and increments it with no intervening await, so a dispatcher woken by the last decrement observes the increment.
- The re-run coroutine is `run_sample` itself, parameterized to seed from the prior terminal record (the `previous_sample` handling `run_sample` already does for a sample source) — it acquires the semaphore like any sample, so it goes to the **back of the queue**, honors `max_samples` retunes, holds at the pause gate (`design/pause-resume.md` — a requeue while paused is accepted and runs on resume, which is exactly what hard pause wants), and hits the stamped `cancel_type` / drain checks at queue exit.

**Acceptance window = while the scheduler is open.** Once the last outstanding sample finishes, the group drains and the task completes; a requeue after that is the 409 above. This deliberately forecloses "requeue the *last* failure after everything else finished" — holding the task open speculatively would be the add-task park problem, and the post-hoc path (`eval-retry` / eval-set re-invocation) already covers it. If real demand appears for a hold-open window, that's a compose-with-`--ctl-server=keep` follow-up (the add-task restart path relaunches a scheduler session; a requeue-into-parked-run could ride the same machinery), not v1.

**Wiring.** Mirrors `TaskCancel`: `task_run` registers a `SampleRequeue` handle on the process-global `EvalState` at `register_eval` (alongside `live` and `task_cancel`), closing over the scheduler, the `SampleErrorHandler`, and the sample store (for `sample_id → sample_index` resolution). The route handler (`_control/server.py`) validates params, resolves the attempt, and invokes the handle; the resolver lives in `_control/requeue.py` shaped like `cancel.py`'s `cancel_sample` (reuse `find_active_sample` for the running/queued check and `sample_error_detail` for the terminal read). The handle is attempt-scoped and detached on retry like `live`, so a requeue aimed at a superseded attempt's `eval_id` gets the between-attempts 409 rather than mutating a dead attempt.

## Failure modes and edges worth naming

- **Requeue accepted, then task cancelled.** The re-run is abandoned at the queue-exit check (`cancelled` in the counters) or torn down by the abort; `finalize_eval` reconciles either way (above). No stuck counters.
- **Requeue accepted, process dies before the re-run finishes.** The log's `(id, epoch)` record is whatever was last written — possibly the *prior* terminal record (the buffer events were removed at re-run start, but the flushed record is only superseded when the re-run logs). Crash recovery and eval-set re-invocation then treat the sample by that record, which is correct-if-stale: the requeue intent is in-memory only, like every control-channel intent (the pause design's "crash honesty" rule).
- **Repeat requeue storms** (a retrying agent): bounded by idempotence — every repeat lands in the pending-set / already-queued rows. There is deliberately no requeue *count limit*: each requeue requires the previous re-run to have reached a terminal state first, so a loop requires a deliberate caller each round.
- **`sample list` truncation:** a requeued sample re-enters the running/queued sort tier, so it surfaces at the head of the capped listing rather than hiding in the terminal tail.

## Alternatives considered

- **Reuse the in-process retry recursion (reuse uuid, decrement `retry_on_error`).** The recursion only exists inside a still-running `task_run_sample` call; the prior attempt has already returned. Modeling requeue as attempt N+1 of the old chain also burns operator requeues against the sample's retry budget and (for cancelled samples) collides the cursor nonce — all three argue for the task-retry shape chosen above.
- **Mint a new epoch / new `(id, epoch)` identity for the re-run.** Would preserve the failed attempt's log record verbatim — but it breaks the sample's identity everywhere (planned-sample sets, epoch reducers, listing keys), double-counts the sample in `total`, and diverges from what task-level retries already do (supersede by `(id, epoch)`). The prior attempt's history is preserved where history lives: `error_retries` on the fresh record.
- **Route through `eval-retry` semantics (finish the task, retry failures).** Already exists; the entire point of requeue is intervening *without* waiting for the attempt boundary (and standalone `inspect eval` has no in-run attempt loop at all).
- **A task-level `requeue-failed` fan-out verb** ("requeue everything errored"). Rejected for v1 per the no-fan-out-mutations convention — shell composition covers it: `ctl sample errors TASK --json | jq ... | xargs -n1 ... ctl sample requeue TASK ...`. If demand appears, it's a multi-target selector design, not a special verb.
- **Persist requeue intent** (survive a crash). Rejected for the same reason pause state isn't persisted: durability belongs to the log/recovery layer, and a restarted process re-running failures is already the eval-set/`eval-retry` contract.

## Open questions

1. **Scan interplay.** `run_sample` short-circuits reused samples through `resume_scan_previous_sample`; a requeued sample re-runs its scanners naturally, but whether scan accounting needs the same decrement treatment as the error counter should be checked at implementation time.
2. **Display.** Should the task display's progress bar regress when a terminal sample re-enters the queue (progress was already ticked)? Probably freeze rather than regress (the `progress()` tick was task-total-scoped); decide with the implementation.
3. **`sample cancel` of a queued re-run.** Today still-queued samples reject per-sample cancel ("only a running sample can be cancelled"). A requeued-then-regretted sample therefore can't be un-requeued until it starts. Acceptable for v1 (its worst case is one wasted re-run); a queued-sample cancel is a separate, pre-existing gap.

## Implementation sketch (blast radius)

- `_eval/task/run.py`: `tg_collect` fanout → `SampleScheduler` (task group + dispatcher + keyed results dict + outstanding counter); `run_sample` gains the seed-from-prior-record path for requeues; register the `SampleRequeue` handle.
- `_control/eval_state.py`: `record_sample_requeued` (bucket decrement), `sample_requeue` handle field, pending-requeue set exposure for the status derivation.
- `_control/requeue.py` (new, shaped like `cancel.py`): the resolver with the decision table above.
- `_control/server.py`: the route (`epoch` fail-closed 400, action-free, `dry_run`), result → HTTP mapping per `sample_cancel`'s precedent.
- `_control/state.py`: pending-requeue awareness in the merge/status derivation.
- `_cli/ctl.py`: `sample requeue` verb (client-side epoch gate, `_mutation_envelope`, `_REQUEUE_ROUTE_MISSING`).
- Tests: route-level decision table, idempotence (double-requeue), counter reconciliation (errored → success and errored → errored-again), cursor reset across a requeue, metrics replacement, cancel/drain/pause interplay.
