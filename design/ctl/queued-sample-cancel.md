# Queued-Sample Cancel (`inspect ctl sample cancel` of a not-yet-started sample)

> **Status: implemented.** Originating issue: meridianlabs-ai/inspect_ai#113. Companion to
> [`control-channel.md`](control-channel.md) (which owns the `sample/cancel` surface) and
> [`sample-requeue.md`](sample-requeue.md) (whose resolved question 3 deferred this).
> No new endpoint, params, or `CONTROL_API_VERSION` bump — this extends the semantics of
> the shipped `POST /evals/<id>/sample/cancel` route.

Today `inspect ctl sample cancel` can only act on a *running* sample: the cancel
primitive is `ActiveSample.interrupt`, which cancels the sample's task group — and a
sample that hasn't started has no task group. Sample requeue (#97) made the gap
operator-visible: a requeued-then-regretted sample cannot be un-requeued until it starts
running, so the operator's recourse is to watch it start and then cancel it (one wasted
re-run — accepted for requeue v1). This design makes `--action cancel` work on a sample
that hasn't started yet, covering both the never-started case and the queued-re-run
(un-requeue) case.

## What "not started" means today — three flavors, three behaviors

A sample that isn't running is in one of three distinct states, and the shipped route
answers each differently (none of them well):

1. **Never started, parked at the sample semaphore** (initial fanout). No
   `ActiveSample` exists (`run_sample` enters `active_sample()` only after acquiring the
   semaphore and materializing), and no log record exists. `cancel_sample` misses on
   `find_active_sample`, then on `sample_error_detail` → the route returns **404 "not
   found"** — for a sample that is real, planned, and visible as `pending` in
   `sample list`. (The requeue resolver already distinguishes this case via
   `_is_planned`; the cancel resolver never learned to.)
2. **Initializing** — past the semaphore, mid-materialization / sandbox init: an
   `ActiveSample` exists with `started is None` (and `tg is None`, so `interrupt` would
   raise). The route returns the explicit **409** ("still queued — only a running sample
   can be cancelled"). The message says "queued" but this sample has *left* the queue;
   the genuinely-queued flavors never reach this check.
3. **A queued re-run** (post-requeue, parked at the semaphore). The dispatcher
   `start_soon`s the re-run promptly, so by cancel time it is a coroutine parked at
   `async with semaphore` inside `task_run_sample` — again no `ActiveSample`. But a
   prior terminal record *does* exist, and `sample_error_detail`'s pending-requeue
   rendering returns it as `status: "queued"` — so `cancel_sample` falls into its
   already-terminal branch and reports **`changed: false`, "sample already finished"**
   with `status: "queued"`. A success-shaped answer that contradicts itself and does
   nothing: the re-run still happens. This is the worst of the three (the 404 and 409
   at least fail loudly).

On a **retry attempt** there is a fourth look-alike: a planned sample whose
prior-attempt result is being **reused** (`run_sample` resolves reuse — the
`sample_source.lookup` at its top — before ever reaching the queue). For the whole
resolution window (which `reuse_read_throttle` can stretch on a large retry) it presents
exactly like flavor 1 — planned, no `ActiveSample`, no record in this attempt's
recorder — and gets the same 404. But unlike flavor 1 it must *stay* uncancellable: a
reuse hit re-logs the prior result and records completion on its own, without ever
passing the queue. See "Reuse in flight" under Mechanism.

There is also a fifth parked-at-the-semaphore state, which this design deliberately
*does* make cancellable: the **sample-level retry re-park**. When an attempt errors
with `retry_on_error` budget remaining, the retry recurses into `task_run_sample`
outside the original semaphore and `active_sample` contexts ("our retry will therefore
go to the back of the sample queue"), after `logger.remove_sample` has dropped the
errored attempt's buffered events. While re-parked it presents exactly like flavor 1 —
planned key, no `ActiveSample`, no record — and today gets the same 404. It is not
literally "never started", but the never-started row's semantics hold for it anyway
(the errored attempt recorded nothing terminal and logged nothing), and accepting it
mirrors the graceful drain's treatment of an interrupt landing at the retry
recursion's queue check: counted `cancelled`, absent from the log. See the table note
and the wiring requirement this adds under Mechanism.

## Semantics

The extended decision table for `sample/cancel`, by the sample's current state
(new/changed rows marked; the task-level row guards the queued rows and the
planned-but-unqueued 409 rows — see the first note below):

| State | `action=cancel` | `action=score\|error` |
|---|---|---|
| task finished / between attempts / task cancel in flight (queued + planned-but-unqueued rows) | **409** (new — mirrors requeue's task-level gates) | same |
| running (`ActiveSample`, started) | interrupt — unchanged | unchanged (score / error, with the fail-on-error gate) |
| initializing (`ActiveSample`, `started is None`) | 409 — unchanged, message reworded ("initializing", not "queued") | 409 — unchanged |
| **queued re-run** (pending-requeue key, no `ActiveSample`) | **applied — un-requeue**: the pending entry is withdrawn and the prior terminal record stands | **409** — there is no work to score and no error to record; the message names `--action cancel` (in the departed blind window, every action gets the departed 409 instead — the `--action cancel` hint would immediately 409 there) |
| **never started** (planned, *at the queue* — arrival-stamped, not departed — no `ActiveSample`, no record, fanout open) | **applied — cancelled before start**: removed from the queue, counted `cancelled`, absent from the log | **409** — same message (upgrades today's 404 to a truthful answer) |
| **not yet at the queue** (planned, no `ActiveSample`, no record, no arrival stamp — reuse resolution in flight on a retry attempt, or a seed's first tick) | **409** — "not at the queue yet (it may be reused from the prior attempt) — retry" (upgrades today's 404) | **409** — same |
| already cancelled-before-start | **`changed: false` no-op** ("already cancelled") | 409 — "was cancelled before it started" (no `--action cancel` hint, which would just point at the no-op) |
| terminal (record exists, no requeue pending) | `changed: false` no-op — unchanged | unchanged |
| unknown `(sample_id, epoch)` | 404 — unchanged | unchanged |

Notes on the table:

- **The task-level gates apply to the queued and planned-but-unqueued rows only** —
  unlike requeue, where they genuinely run first for every request. Interrupting a
  *running* sample while a task cancel is in flight stays permitted (unchanged — the
  operator explicitly targeting one sample wins, per the shipped first-resolution-wins
  rules), and a terminal record after the task finishes keeps its `changed: false`
  no-op. But accepting a queued-row cancel when a task cancel is stamped would be a
  no-op lie (the drain abandons the sample anyway) and its counter reconciliation would
  collide with the drain's own recording; between attempts / after drain there is no
  fanout to act on. And the planned-but-unqueued 409s' "retry" advice needs the gates
  too: once the task has finished (or a cancel is in flight) that advice would have no
  exit — e.g. a sample that completed under `log_samples=False` keeps its departed
  stamp and never gains a readable record. Same honesty rule, same wording style as
  requeue's `_task_level_reject`.
- **The never-started row also admits a retry re-park** (fifth state above), by
  design rather than by accident of its conditions: a sample re-parked at the
  semaphore mid-`retry_on_error` matches the row (arrival re-stamped by the recursed
  `task_run_sample` — see Wiring) and is accepted — counted `cancelled`, absent from
  the log (its buffered events were already removed). No fail-on-error reconciliation
  is needed despite the errored attempt: with retries remaining, `handle_error`
  returns the error *without* calling `sample_error()`, so the re-parked attempt never
  bumped `error_count`. Un-cancel via requeue resumes the parked retry — attempt N
  with its remaining `retry_on_error` budget — rather than starting a first run.
- **Only `--action cancel` is meaningful for a queued sample.** `score` would have
  nothing to score and `error` nothing to record; both keep rejecting (409) with a
  message that points at `--action cancel`. This also fixes flavor 1's current 404 for
  those actions into a truthful rejection — the cancel resolver gains the same
  `_is_planned` awareness the requeue resolver has.
- **Idempotence** (agent-shape constraint): repeat cancels land in the no-op rows —
  a repeated never-started cancel reports "already cancelled", a repeated un-requeue
  reports the ordinary already-terminal no-op (the pending key is gone, so the prior
  record renders terminally again). `dry_run=true` reports every row without mutating —
  including the departed 409: the un-requeue dry-run consults the same departed gate
  (read-only) the real accept enforces, so a probe never reports an accept the real
  call would refuse. Accepted rows' `reason` strings are conditional-tense under
  `dry_run` ("the requeue would be withdrawn …"), so the CLI's "Would cancel …" line —
  which interpolates the reason verbatim — never embeds a past-tense mutation.
- **Un-requeue restores the world, not a variant of it.** After an un-requeue the
  sample is exactly as if the requeue had never been accepted: the prior terminal record
  stands (it was only ever superseded when a re-run *logs*), the counters and
  fail-on-error tally are restored, and the sample is **requeueable again** — including
  re-requeuing the very same record (see the `_accepted_uuids` note below). One honest
  carve-out: if the withdrawn re-run (or a cancel-before-start) was the *last*
  outstanding work, restoring/recording the terminal bucket reaches `terminal == total`,
  which stamps `completed_at` (and clears `EvalState.sample_ids`) — the task then
  genuinely finishes as the zombie drains, and a later requeue gets the "task already
  finished" 409. That is the correct answer, not a gap; but the implementation must not
  key the cancelled-row rendering or the repeat-cancel no-op off `sample_ids`, which is
  empty by then.

## Mechanism: stamp now, discard at queue exit

A queued sample has no task group, so there is nothing to cancel *into* — but both
queued flavors share a structural fact: the parked coroutine passes a check point when
it leaves the queue (the same point where the stamped task-cancel `cancel_type` and the
drain checks already run, at the top of `task_run_sample`'s `async with semaphore`
block). The design splits the cancel into a **synchronous semantic accept** and a
**deferred mechanical discard**:

- **Accept (synchronous, on the eval's loop).** The resolver validates the row, then the
  handle mutates all observable state with no await point: sets/flags, counters,
  fail-on-error tally, progress/metrics. From this moment the sample *is* cancelled (or
  un-requeued) in every read surface. Single-loop synchronicity makes this race-free —
  the same argument as requeue's `accept` and task-cancel's stamp-then-interrupt. The
  resolver's earlier reads (`sample_error_detail` / `_full_sample`) await, so — like the
  requeue resolver, but with one more gate — it re-runs its checks synchronously right
  before mutating: the task-level gates, **and the at-the-queue check**. The queue is
  stamped at *both ends*, because a run is invisible on both sides of it:
  `task_run_sample` stamps **arrival** synchronously immediately before the semaphore
  acquire, and the queue-exit point stamps **departure** as its very first action
  after acquiring the semaphore — both on the run's own `_SampleRun` object, never a
  key (see "one run object per coroutine" under the never-started section below).
  Departure matters because a run that leaves the queue is invisible until
  its `ActiveSample` registers much later (materialization awaits sit between — the
  same blind window the task-cancel fails-on-error gate documents). Arrival matters
  because on a retry attempt a planned key may never reach the queue at all — its
  prior-attempt result may be *reused* ("Reuse in flight" below). A
  `find_active_sample` re-check alone therefore isn't enough; the never-started accept
  requires the key to be exactly *at the queue* (arrived, not departed): a
  departed-but-unregistered run gets the initializing 409, a not-yet-arrived key gets
  the retryable not-at-the-queue 409 — never a half-cancel that mutates counters for a
  run that will also terminal-record on its own. The resolver is the *single*
  validation layer: the handle mutators (`cancel_queued`, `cancel_before_start`,
  `uncancel`) assert the preconditions it just checked rather than re-branching —
  with no await between the check and the call, a second decision layer there would
  be unreachable code.
- **Discard (deferred).** The parked coroutine becomes a zombie: when it eventually
  acquires the semaphore, the queue-exit check sees the cancel stamp and returns
  immediately — no materialization, no recording (the accept already counted it), no
  result write. Until then it holds no resources beyond a parked coroutine frame; the
  one thing it briefly consumes is a semaphore slot at exit, released immediately.

**Why deferral is acceptable** (vs. tearing the coroutine down at accept): the deferral
is long exactly when it doesn't matter and short exactly when it does. While the queue
is busy, the zombie sits behind real work and delays nothing. When the cancelled sample
is the *last* outstanding work — the case where a lingering zombie would hold the task
open — the semaphore necessarily has free slots, so the zombie drains immediately and
the fanout closes. (The immediate-teardown alternative is considered and rejected
below.)

Both flavors stamp the same way — the run object — but their cancel accepts differ,
because their identities differ:

### Never-started (initial fanout): flag the key's owning run

There is **one run object per coroutine**: every run — initial seed, source add
(`SampleScheduler.add`), or requeued re-run — carries a `_SampleRun`, and the
queue-lifecycle flags (`arrived`/`departed`/`cancelled`, plus the dataset-typed id
captured at arrival) live *only* on that object. Stamping the run rather than a key
makes aliasing impossible by construction: after an un-requeue plus a fresh requeue,
a key belongs to the fresh coroutine, but the old zombie only ever stamps itself. For
the read surface, the requeue handle (`SampleRequeue`, which already owns the
analogous pending-requeue set and has exactly the right lifecycle — registered when
the fanout starts, detached on retry) keeps `current_run: dict[SampleKey,
_SampleRun]`, pointing at whichever run currently owns the key: a key-based run (seed
or source add, `prior=None`) owns its key from queue arrival on — and keeps it
forever, so a cancelled-before-start outcome outlives its coroutine (there is, and
will be, no log record to read it from) — while a re-run owns the key only from its
arrival until it goes terminal or is withdrawn, when ownership reverts to the
superseded run (see the un-requeue section below). A cancel-before-start accept flags
the owning run `cancelled`, which reads as `"parked"` until the run departs and
`"discarded"` after (the distinction matters to requeue, below). Seeds and source
adds take exactly the same path — the run object erases the old seed-vs-entry
asymmetry.

- **Counters.** Accept calls `record_sample_cancelled(eval_id)` — the sample is
  terminally cancelled from the operator's point of view, and `terminal == total`
  arithmetic holds (`finalize_eval`'s shortfall fold is unaffected: the sample is
  already terminal, so a teardown before the zombie drains adds nothing for it). The
  queue-exit discard must **not** record again — its check runs *before* the stamped
  task-cancel drain check, which would otherwise double-count via its own
  `record_sample_cancelled`. When the cancelled sample was the last outstanding work,
  this recording stamps `completed_at` and clears `sample_ids` — the same
  last-outstanding-work carve-out described under Semantics above applies.
- **Log.** Absent from the log, matching the established treatment of queued samples
  under an abort or a graceful drain (terminal in the counters, no record). The
  alternative — a synthetic cancelled `EvalSample` — is rejected below.
- **Wiring.** `run_sample` knows the key before materialization (`get_sample(index).id`
  is read at its top), so it builds one pre-bound `SampleQueueHooks` object — the
  handle, the key, and the run, with `enter()`/`exit()`/`abandon()` methods — and
  threads it into `task_run_sample`: `enter()` stamps arrival synchronously
  immediately before the semaphore acquire, and `exit()` runs at the semaphore-exit
  point beside the existing drain check. The hooks object must also be forwarded
  through the `retry_on_error` recursion (`task_run_sample` calls itself to re-park at
  the back of the queue), and the arrival stamp must overwrite a prior departure — a
  run's queue-lifecycle state cycles arrived → departed → arrived across retry
  re-parks. Without the forwarding, a re-parked sample would read as *departed* for
  its whole re-park (arrival never re-stamped after the first attempt left the queue)
  and get a permanent initializing 409 instead of being cancellable. The exit hook
  does double duty, synchronously:
  it stamps the run's departure (every run that parks, cancelled or not — this is what
  the accept-side at-the-queue check reads, so it must cover uncancelled runs too; a
  reuse hit never reaches any hook, which is exactly why accept *requires* the
  arrival stamp — "Reuse in flight" below) and returns whether this run was cancelled.
  On a cancelled hit — the departure itself flips the key's read from `"parked"` to
  `"discarded"` — fire `sample_terminal("cancelled")` (the injected-slot outcome
  bookkeeping, exactly as the drain path does — a cancelled outcome keeps the slot
  resident) and return the discard sentinel.
- **Listing / show.** Today the sample renders `pending` (planned, no record, no active
  row) — which reads as "will run", now false. The status derivation gets a
  cancelled-keys rule exactly parallel to `_pending_requeue_keys`: a key whose owning
  run is flagged renders **`cancelled`** (synthesized row, terminal fields empty), in both
  `current_sample_summaries` and `sample_error_detail`, with the same
  snapshot-after-await discipline. Neither histogram needs code of its own, but for
  different reasons: the samples listing's `counts` is tallied from the rendered rows,
  so the new row rule *is* what corrects it, while the tasks listing derives `queued`
  arithmetically from the counters, which the accept's `cancelled` bump already fixed.
  The rows echo the *dataset-typed* id (int vs str) like every other per-sample
  surface: the arrival stamp captures it (the runner passes `get_sample(index).id`),
  so the synthesis doesn't depend on recovering it from `sample_ids` — which clears at
  `completed_at`, and would flip a cancelled row's id to the route string when the
  cancel finished the eval.
- **Requeue interplay (un-cancel).** The requeue resolver's `_is_planned` branch
  currently answers "sample has not started yet — it will run without help", which
  becomes a lie for a cancelled key. New rows in the requeue table:
  - key `"parked"` → **applied — un-cancel**: clear the owning run's flag, decrement
    the counter (reusing `record_sample_requeued(eval_id, "cancelled")`, whose below-zero guard
    carries over — though the implementation should parameterize or reword its warning
    message, whose "requeue accepted a prior…" phrasing would mislead if it ever fired
    from this path). The *same* parked coroutine serves as the re-run — no new entry is
    created, so there is nothing to double-queue; the sample simply runs when it gets a
    slot, exactly as if never cancelled (for a cancelled retry re-park, "runs" means
    resuming attempt N with its remaining `retry_on_error` budget).
  - key `"discarded"` → **409**: the coroutine is gone and there is no prior record to
    seed a re-run from ("cancelled before start and already discarded — re-run with
    `inspect eval-retry`"). Spawning a fresh scheduler entry with `prior=None` would
    likely work (the store retains seed samples, and the discard's
    `sample_terminal("cancelled")` keeps an injected sample's slot resident, exactly so
    a re-run can find its data) — but it is a new accept shape (no prior record, so
    none of the staleness guard applies) serving an unproven regret window, so it is
    deferred as a follow-up rather than shipped speculatively.
- **Retry semantics fall out.** Absent from the log means an eval-set retry attempt and
  `inspect eval-retry` treat the sample as never-run and re-run it — the same
  re-runnable meaning a *recorded* cancelled sample has (error set → re-run), reached
  without fabricating a record.

### Queued re-run (un-requeue): flag the pending entry

A re-run must be flagged via its own `_SampleRun` (found through the pending-requeue
bookkeeping), never via the key's `current_run` mapping: the pending key clears at
un-requeue accept (the sample becomes requeueable again immediately), so a fresh
requeue accepted while the old zombie is still parked creates a second coroutine for
the same key — and the key by then points at the fresh run. Flagging the entry
(`_SampleRun.cancelled: bool`) cancels exactly the old coroutine, and the fresh one
runs unaffected.

Accept performs the full inverse of `SampleRequeue.accept`'s reconciliation,
synchronously:

1. **`entry.cancelled = True`.** Checked at the top of the re-run's `run_sample` (fast
   path — skips the requeue seeding side effects when the cancel lands before the
   dispatcher-started coroutine first runs) and, authoritatively, at the queue-exit
   check. **Both checks must read the entry object itself** — plumbed through
   `run_one` → `run_sample` — never a per-key handle lookup: after an un-requeue plus a
   fresh requeue, the key aliases to the *fresh* entry, and a key lookup from the old
   zombie would return it uncancelled — the zombie would then proceed through seeding
   (including `logger.remove_sample`, dropping the fresh re-run's realtime-buffer
   entry) before the exit check caught it. The pending-requeue bookkeeping keeps the
   live `_SampleRun` per pending key, so *accept* can find the entry to flag.
   The top check and the arrival stamp are separated by the seeding awaits (the
   prior's log removal and the checkpoint read), so an un-requeue can be accepted
   between them; `queue_arrive` therefore refuses a cancelled run — no arrival stamp,
   no key ownership. An owning zombie would read as a never-started row (`arrived`,
   not `cancelled` — the cancelled read is a key-based-run outcome), sending a
   follow-up cancel into `cancel_before_start`'s prior-less precondition, and its
   late arrival could steal the key from a fresh requeue. Only this path arrives
   cancelled (a cancelled key-based run discards at its queue exit and never
   re-parks), and the refused zombie still discards at the queue-exit check as
   usual.
2. **Clear the pending-requeue key, neutralize the withdrawn entry's `on_terminal`,
   and revert the key's `current_run` ownership to the superseded run.** The listing
   and `sample show` immediately revert to rendering the prior terminal record (the
   "queued" rendering keys off the pending set), and the ownership revert makes the
   withdrawn zombie unreadable by key — a normal re-run terminal does the same revert
   from `on_terminal`, so a parked re-run reaped by a teardown can't leave the key
   reading `"arrived"`. The neutralization matters in the
   fresh-requeue-while-zombie-parked scenario: `run_one` fires `on_terminal`
   unconditionally when the discarded run returns, and the callback acts on the key —
   which by then may belong to the fresh requeue, wrongly un-marking it (rendering it
   as its prior terminal record while parked, turning its repeat-requeue answer into a
   confusing `stale` 409, and making *its* un-requeue unreachable). Accept therefore
   disarms the old entry's callback when it clears the key.
3. **Remove the prior record's uuid from `_accepted_uuids`.** Otherwise a later,
   legitimate re-requeue of the same terminal record — now fully valid, since its
   re-run never happened — would be refused as `stale`. Un-requeue restores exactly the
   pre-accept guard state: the invariant that guard enforces ("each accept consumes a
   freshly-read prior") is preserved because this prior is *back to being current*.
4. **Re-increment the prior bucket** — a new `record_sample_unrequeued(eval_id,
   prior_status)` in `_control/eval_state.py`, the increment inverse of
   `record_sample_requeued` (including `_maybe_mark_finished`: if the withdrawn re-run
   was the last outstanding work, the eval may stamp `completed_at` while the zombie
   drains — the same accepted transient as the requeue design's
   "`completed_at` can precede the `outstanding` catch-up" note, and short-lived for
   the free-slots reason above). The prior status is remembered from accept, not
   re-classified.
5. **Restore the fail-on-error tally**: if the prior was an error,
   `SampleErrorHandler.error_count += 1` (undoing accept's decrement), so
   `_should_eval_fail` again reflects the standing outcome.
6. **Restore progress and the retracted score.** `on_requeue_accept` unticked the
   progress bar and popped the prior score from `progress_results`; accept now stashes
   what it popped (per pending key, on the handle), and un-requeue ticks
   `+SAMPLE_TOTAL_PROGRESS_UNITS` and re-inserts the popped entry (present only when the
   prior scored, e.g. `score_on_error`). Without this, an errored-with-score prior would
   vanish from the live metrics and the cancellation path's partial `eval_results`
   forever, while its log record still shows the score.

**Result-dict preservation.** `run_one` writes `results[(index, epoch)] = await
run_sample(...)` — a discarded run must **skip** that write (discard is signalled by a
sentinel, or by `run_one` checking `entry.cancelled`), or it would clobber the prior
attempt's keyed result (a `score_on_error` prior's score dict) with `None` and desync
metrics from the log. The rule is uniform — **a discard never writes** — which is also
correct for the never-started flavor: its key simply stays absent from the returned
plan-ordered dict, and `eval_results` runs off score dicts and ignores non-dict entries
either way. (The task-cancel drain path *does* write `None` for the queued samples it
abandons — which is in fact a narrow pre-existing bug of the same shape, not a harmless
contrast: a *requeued re-run* abandoned by a graceful `score|error` drain clobbers a
`score_on_error` prior's score dict with `None`, and the graceful path still computes
final `eval_results`, so the prior's score vanishes from metrics while its log record
keeps it. The new discard must not reuse the drain's return-`None` shape, and the
implementation should fix the drain path's requeue case to the same never-write rule
while it's in there.)

**Ordering wart, accepted:** the re-run's seeding calls `logger.remove_sample(id,
epoch)` (dropping the prior attempt's entry from the *realtime view buffer*, not the
recorder) before parking at the semaphore — usually before any cancel can land. An
un-requeued sample's prior record therefore stands in the recorder and the log, but its
realtime-buffer entry is gone for good (nothing re-inserts removed samples; the flush
cycle only ever removes). This is view-only (the control channel reads the recorder,
not the view buffer); noted so nobody hunts it as a bug.

### What stays rejected: reuse in flight (retry attempts)

On a retry attempt (`sample_source` present), every planned coroutine first resolves
whether the prior attempt's log already holds a result to reuse — `run_sample`'s reuse
branch runs *before* `task_run_sample`, and a hit re-logs the prior record
(write-through), records completion, and **returns without ever touching the queue**.
For the whole resolution window the sample satisfies the never-started row's naive
conditions — planned, no `ActiveSample`, no record in this attempt's recorder — but
accepting a cancel there would be triply wrong:

- **double count**: `record_sample_cancelled` at accept plus the reuse path's
  unconditional `record_sample_completed`, letting `_maybe_mark_finished` stamp
  `completed_at` while siblings still run;
- **"absent from the log" becomes false**: the reused record is re-logged regardless;
- **a stuck rendering**: the key stays `"parked"` forever (no queue exit ever flips it
  to `"discarded"`), so the listing shows a completed sample as `cancelled`
  indefinitely.

The arrival stamp closes this by construction: a reuse-bound key is never stamped
`queued`, so the accept's at-the-queue gate refuses it with the truthful, retryable
not-at-the-queue 409 throughout resolution *and* through the hit path's recording
awaits; once the reuse records, the key has a terminal record and lands in the ordinary
already-terminal no-op row. (That convergence assumes `log_samples=True`, the default:
the reuse hit's re-log is gated on it while `record_sample_completed` is not, so with
`log_samples=False` the key never gains a readable record and repeat cancels keep the
retryable 409 — the same permanent answer today's 404 gives, so no regression; it just
never reaches the no-op row.) A lookup **miss** (or a `ResumeCheckpoint` /
`PreviousError` seed) falls through into `task_run_sample`, stamps arrival, parks — and
is cancellable as ordinary flavor 1 from that point.

Two notes on the stamp's placement. It gates by *positive eligibility* (arrived at the
queue) rather than having the reuse path claim keys with a negative "reuse in flight"
marker: absence fails closed, so any path that completes without queueing is excluded
without having to remember to mark itself — and the same gate covers the sub-tick
window on a fresh eval between the fanout's `start_soon` and a seed coroutine's first
run (a cancel arriving a tick early gets the same retryable 409; on a fresh eval the
segment from `run_sample`'s top to the semaphore park is synchronous, so arrival is
stamped the moment each seed first runs and cancel-before-start is fully available).
And it must sit at the park point, not at `run_sample`'s top: stamped at the top, every
reuse-bound key on a retry attempt would read as queued, reintroducing the hole this
section closes.

### What stays rejected: the initializing window

Flavor 2 (past the semaphore, `ActiveSample` with `started is None`) keeps its 409,
reworded to say *initializing* rather than "queued". The sample is mid-materialization —
sandbox init may be in flight — so neither `interrupt` (no task group) nor a queue-exit
check (already exited) applies, and tearing it down externally would leak half-built
state. The window is short and self-resolving: retry the cancel once it's running. A
possible follow-up mirrors the task-cancel machinery — stamp a per-sample intent the
sample checks as it starts (the same self-interrupt hook the graceful drain uses for
this window) — but it's not needed for the queued cases this design targets.

## Failure modes and edges worth naming

- **Cancel accepted, then task cancelled / torn down before the zombie drains.**
  Never-started: already counted `cancelled`; the shortfall fold sees it as terminal and
  adds nothing; the scheduler's `finally` drain doesn't know about it (its run is never
  a dispatcher-pending entry) and needn't. Un-requeue: the bucket was restored at
  accept and the entry never runs;
  accept already disarmed the withdrawn entry's `on_terminal` (step 2), so the teardown
  drain — or `run_one`'s `finally`, if the dispatcher had started the entry — fires
  nothing for it, leaving the key (which may by now belong to a fresh requeue)
  untouched, which is the intended outcome. Coherent either way.
- **A drain abandoning an *uncancelled* queued sample stamps the key too.** The
  task-cancel drain (the queue-exit abandonment, and the drain-window abandonment of a
  suppressed retry) records the sample `cancelled` but writes no record — so without a
  stamp no read surface would ever see the outcome: the listing would keep rendering
  the key `pending`, and the departed 409 would advise "retry once it is running"
  forever. The abandon paths therefore flag the run cancelled-and-departed — read as
  `"discarded"` — via the hooks object's `abandon()`:
  the listing renders `cancelled`, and a later cancel lands on the idempotent
  "already cancelled" no-op. Re-runs need no stamp — clearing their pending key
  reverts them to their prior terminal record. The one reader this can't help is a
  sample that completed under `log_samples=False` (no record is ever written); its
  departed 409 persists until the task finishes, where the task-level gates take
  over.
- **Cancel racing the re-run's start.** If the `ActiveSample` has appeared by resolve
  time, the active row wins (same precedence as the requeue resolver): a started re-run
  is a running sample (ordinary interrupt); one mid-materialization is the initializing
  409. A run that left the queue *during the resolver's awaits* — past the exit check
  but with no `ActiveSample` yet — is caught by the departure stamp accept consults
  (see Mechanism above), so the flag only ever discards a run that hasn't left the
  queue.
- **Double-cancel storms** (a retrying agent): bounded by the no-op rows, like every
  phase-3 directive.
- **Cancel of a *pending* (not yet dispatcher-started) re-run entry.** The accept marks
  the entry; when the dispatcher later `start_soon`s it, `run_sample`'s top check
  discards before any seeding side effect. The scheduler needs no pending-list surgery.
- **Version skew.** No new params, no `CONTROL_API_VERSION` bump. New CLI → old server:
  the queued rows keep today's answers (404 / initializing 409 / the misleading
  `changed: false` for a queued re-run) — nothing the CLI can detect or fix; matched
  versions are the supported pairing, as with the listing cap. Old CLI → new server:
  strictly better answers to the same requests.
- **Early stopping** is not notified of a cancel-before-start (no
  `schedule_sample`/`complete_sample` ever fired for the sample) — consistent with the
  drain path, which doesn't notify for abandoned queued samples either.
- **Cancelling a retry re-park inherits two behaviors from the queue-check abandonment
  it mirrors** (both match an interrupt landing at the recursion's queue check today —
  consistent, just worth naming). *Hook shape*: the errored attempt fired
  `attempt_end(will_retry=True)` before re-parking, so hook consumers see a dangling
  "will retry" with no subsequent attempt start and no `sample_end`. *Usage
  accounting*: the errored attempt's real token/message spend never reaches the
  cumulative counters — nothing was recorded at the retry decision (usage accrues only
  at terminal recording), a re-parked sample has no `ActiveSample` for the live
  overlay, and the accept-side `record_sample_cancelled(eval_id)` has no `state` to
  read usage from. That contrasts with the drain-*window* path (which passes
  `_sample_usage(state)` when it abandons the same attempt a moment earlier) and with
  requeue's stance that spend "was real, not rolled back" — but closing it would mean
  threading usage into the parked stamp, new work for a rare directive.
- **Crash honesty.** Cancel intent is in-memory only, like all control-channel state: a
  process that dies before the zombie drains recovers from the log, where a
  never-started cancel is (correctly) an absent sample and an un-requeue is (correctly)
  the standing prior record.

## Alternatives considered

- **Tear the parked coroutine down at accept (per-entry `CancelScope`).** Wrap every
  fanout coroutine in a scope registered by key; accept cancels the scope and the
  semaphore wait unwinds immediately. Rejected for v1: it adds a scope registry across
  *all* planned coroutines to serve a rare directive; it is only safe while the
  coroutine is verifiably still parked (cancelling mid-materialization tears through
  sandbox init), which needs a stamped-flag handshake anyway — at which point the flag
  alone, checked at queue exit, delivers the same semantics; and the deferral it
  eliminates is harmless (free-slots argument above). If a real consumer needs prompt
  `outstanding` decrement (e.g. dynamic feeders reading queue depth), this can layer on
  later without changing the directive's surface.
- **A synthetic cancelled log record for never-started samples.** Would make the sample
  visible in the finished log. Rejected: there is no transcript, no `TaskState`, no
  uuid, and no timestamps to record honestly; the established treatment of queued
  samples (abort and graceful drain) is counters-terminal, log-absent; and absence
  already yields the right retry semantics (re-run on `eval-retry` / eval-set retry),
  identical to a recorded cancellation's.
- **A dedicated `sample unrequeue` verb.** Rejected: "cancel the thing that is queued"
  is the natural spelling and covers both flavors with one rule; the requeue design
  already framed un-requeue as a cancel of the queued re-run (resolved question 3); and
  a new route would need missing-route version handling that extending `sample/cancel`
  avoids entirely.
- **Remove the entry from the scheduler's pending list only.** Insufficient — the
  dispatcher `start_soon`s entries as they arrive, so the window in which a re-run is
  still on `SampleScheduler._pending` is a few loop iterations; the durable parked state
  is the coroutine at the semaphore, which only a queue-exit check (or scope cancel)
  reaches.
- **Keep `"discarded"` keys requeueable (a fresh `prior=None` entry).** Deferred, not
  rejected — see the `"discarded"` row above: mechanically feasible, but a new accept
  shape for an unproven regret window, and `eval-retry` covers the post-discard case.

## Implementation sketch (blast radius)

- `_control/cancel.py`: `cancel_sample` grows the queued rows — task-level gates
  (reusing/sharing requeue's `_task_level_reject`), pending-requeue key → un-requeue,
  `_is_planned` + one `SampleQueueView` snapshot → cancel-before-start /
  not-at-the-queue 409 / no-op, score|error → 409 for all queued flavors; synchronous
  gate re-check before mutating.
- `_eval/task/scheduler.py`: `_SampleRun` — one run object per coroutine (initial
  seeds, source adds, and re-runs alike) carrying the `arrived`/`departed`/`cancelled`
  flags and the captured dataset-typed id; `SampleRequeue` keeps `current_run` (key →
  owning run, reverting to the superseded run at a re-run's terminal or withdrawal),
  the per-pending-key entry/stashed-score bookkeeping, the `sample_view(...)` read
  snapshot (plus `pending_keys()`/`cancelled_keys()` for the listing derivation),
  `cancel_queued(...)` (un-requeue, disarming the withdrawn entry's `on_terminal`) and
  `cancel_before_start(...)` accepts, and `uncancel(...)` for the requeue resolver;
  `SampleQueueHooks` bundles the three runner stamp points;
  `run_one` plumbs the run through to `run_sample` and skips the result write for
  discarded runs (also fixing the drain path's `None` write for abandoned re-runs).
- `_eval/task/run.py`: queue-entry arrival stamp at the top of `task_run_sample`
  (before the semaphore acquire); queue-exit departure stamp + discard check beside the
  drain check, ordered before it; the `SampleQueueHooks` object forwarded through the
  `retry_on_error` recursion; `run_sample` top-of-function entry check (before the
  requeue seeding side effects); restore-side of `on_requeue_accept` (progress tick +
  score re-insert).
- `_control/eval_state.py`: `record_sample_unrequeued` (increment inverse of
  `record_sample_requeued`).
- `_control/requeue.py`: un-cancel and discarded rows in the decision table;
  `_is_planned` branch consults the view's cancelled state — re-snapshotted after
  the terminal read's await (a cancel-before-start accepted during `_full_sample`
  must land on the parked/discarded rows, not `_is_planned`'s "will run without
  help"; the mirror of `cancel_sample`'s post-await re-resolve).
- `_control/state.py`: cancelled-before-start keys render `cancelled` in the listing
  and `sample show` (parallel to `_pending_requeue_keys`).
- `_cli/ctl/_sample.py`: no new flags; rejection/detail wording for the new rows.
- Docs: flip `sample-requeue.md` resolved question 3 and the `control-channel.md`
  `sample/cancel` bullet to point here when this ships.
- Tests: route-level decision table (all queued flavors × three actions), un-requeue
  reconciliation (counters, error_count, progress/score restore, re-requeue of the same
  record succeeds), cancel-before-start → un-cancel → runs normally,
  cancel-before-start → discard → requeue 409, the retry-attempt reuse window (cancel
  during resolution → not-at-the-queue 409; after the reuse records → terminal no-op;
  lookup miss → cancellable once parked), source-added sample cancel-before-start,
  cancel during a `retry_on_error` re-park (counted `cancelled`, absent from the log)
  and its un-cancel (the parked coroutine resumes the retry with its remaining
  budget), drain/teardown interplay (no double-count), listing/status rendering,
  idempotence and dry-run rows.
