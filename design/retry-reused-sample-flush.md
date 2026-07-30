# Draining retry-reused samples from the recorder buffer

Design for [meridianlabs-ai/inspect_ai#117](https://github.com/meridianlabs-ai/inspect_ai/issues/117).

## Problem

When a retry attempt starts, every completed sample reused from the prior
attempt is re-logged with `flush=False` (`task/run.py`, the `sample_source`
reuse path in `run_sample`). Those samples sit in the recorder buffer
(`ZipLogFile._samples`) as **full `EvalSample`s** (~1GB in the incident) until
some *other* trigger flushes — a live-sample completion (a *single* one arms
the stale-flush timer, which drains the whole buffer within 60s; enough of
them reach the `log_buffer` threshold directly), or eval finish. On a retry
whose remaining samples are long-running there are no completions, so the
timer never arms and that can be hours or never. Two concrete harms:

1. **Memory**: the full reused set stays resident, scaling with
   carried-transcript size. (The per-request re-summarization cost this
   exposed was fixed separately in #116 by precomputing summaries at buffer
   time; the resident set itself remains.)
2. **Destination durability / external readability**: the new attempt's
   on-disk log is missing all reused completed samples until the first flush.
   Worse, `inspect ctl task log-flush` is a **no-op** in this state today:
   `_flush_pending_samples` returns early when `flush_pending` is empty
   without ever calling `recorder.flush`, so even an operator explicitly
   asking for a flush can't drain reused samples unless a live sample also
   happens to be pending.

(In-process reads are *not* a gap today: `TaskLogger.read_sample` serves
buffered reused samples whole via `ZipLogFile.buffered_sample`.)

The issue suggested letting buffered-but-unregistered samples arm the
stale-flush timer. Review concern (ransomr): that still keeps everything in
memory until the timer fires, and a timer can fire too early (mid-sweep) or
too late. This design avoids the timer as the primary mechanism.

## Key observations

`ZipLogFile` already has two distinct cost tiers:

- **Cheap, local**: writing a sample into the temp-file-backed zip
  (`_zip_writestr` — what `write_buffered_samples` does at flush time). Disk,
  not RAM; no network. Anything written here survives to the destination on
  *any* later flush (a flush copies the whole temp zip).
- **Expensive**: `flush()` — copying the whole temp zip to the (possibly
  remote) destination.

The streaming-completion path (`buffer_sample_streaming`) already writes
through to the temp zip immediately and retains only an event-less copy in
memory. The reuse path can do the same.

Separately, the reuse lookup in `run_sample` runs **before** the sample
semaphore and all `run_sample` coroutines start together (`tg_collect`), so
"every planned sample has resolved its reuse check" is a well-defined, early,
deterministic event — no heuristic timer needed. (Caveat: the reuse branch
*does* touch the semaphore after re-logging, inside
`resume_scan_previous_sample` — the trigger's decrement point must sit before
that; see below.)

## Proposal

Two independent pieces; each addresses one of the harms above.

### 1. Write reused samples through to the temp zip (memory)

Add a write-through mode for re-logged completed samples:
`Recorder.log_sample(eval, sample, *, write_through: bool = False)`.

- `EvalRecorder` honors it: under `ZipLogFile._lock`, write the sample entry
  (`samples/{id}_epoch_{epoch}.json`) and a journal summary immediately
  (mirroring `buffer_sample_streaming`, including the replace-by-`(id, epoch)`
  dedupe of `_summaries` and the summary-counter journal file), and retain
  only a **condensed, event-less** copy in `_streaming_samples` so
  control-channel reads of error detail/scores keep working pre-flush
  (cleared by `flush()`, exactly like streaming samples). Nothing is appended
  to `_samples`.
- `JSONRecorder` ignores the flag (the `.json` format holds the whole log in
  memory for its lifetime by design; no regression, no benefit).
- Signature-change audit: implementers are `EvalRecorder.log_sample` and
  `JSONRecorder.log_sample`, plus the ABC (`recorder.py`) whose
  `log_sample_streaming` default forwards to it, and the mock recorder in
  `tests/log/test_task_log.py`. Direct callers outside `TaskLogger`
  (`_write_eval_log_with_recorder`, `_cli/score.py`, `_recover/_write.py`,
  and `_convert_sample` in `log/_convert.py`) keep the default and are
  unaffected. (`log/_convert.py` is a natural *future* adopter — it already
  condenses samples and flushes periodically to bound memory — but that's out
  of scope here.)

Effect: each reused sample is read → condensed → written to local disk →
dropped, instead of being **retained** for the attempt's lifetime. To bound
peak memory at burst as well (all `run_sample` coroutines start at once and
nothing throttles `sample_source.lookup` today — the whole reused set can be
mid-read simultaneously), wrap the reuse lookup+re-log region in a small
constant semaphore (e.g. 25, matching the bounded concurrency used for
summary reads in `_read_all_summaries_async`). A live sample's lookup is a
cheap miss, but a shared FIFO semaphore would still queue it behind in-flight
reused-sample body reads — in the worst case (live samples late in dataset
order behind a large reused set) approaching the same delayed-live-start
drawback that rejects the blocking pre-pass below. So keep hit/miss
determination **outside** the semaphore: on the file path, `read_from_file`
already shares one `AsyncZipReader`, whose cached `entries()` central
directory answers presence of `samples/{id}_epoch_{epoch}.json` without a
body read. Only lookups that hit (and the re-log) acquire the semaphore;
true misses — samples absent from the prior log, e.g. started-but-never-logged
(the incident scenario's long-running remainder) — proceed immediately after
the one shared central-directory fetch. Note the presence check is narrower
than "live sample": a live sample whose prior attempt **errored or was
invalidated** is a presence-*hit* (its zip entry exists; error status lives in
the sample body, and `PreviousError` seeding needs the body anyway), so those
lookups take the throttle alongside reuse hits — accepted, since errored
transcripts can be as large as completed ones and equally need bounded
concurrent residency. (The in-memory path's lookups are list scans; no
throttle needed there.)

Known trade-off: event reads for a reused sample are unavailable between
write-through and destination flush (today they're served whole from the
in-memory buffer; the event-less retained copy covers error/scores/summaries
but not events). That window lasts until the settle flush (see part 2) —
typically seconds, but bounded by the full reuse-sweep duration, which the
25-way throttle serializes into batches of remote body reads and which can
reach minutes for a large remote prior log. Reused samples have no
realtime buffer-db presence in either world — the reuse path never calls
`start_sample`, and `SampleBufferDatabase.complete_sample` is UPDATE-only, so
no row ever exists there.

A second boundary on the memory guarantee: the throttle bounds concurrent
*reads*, not downstream residency. When a scanner is configured and the prior
scan is incomplete, each reused sample's coroutine still holds the full
un-condensed body while `resume_scan_previous_sample` queues on the sample
semaphore behind long-running live samples — so in that case the entire
reused set can be resident simultaneously, unbounded by the read throttle.
This is inherent (the scan genuinely needs the body); in the incident
scenario — no scanner — the reference is dropped as soon as the re-log
completes.

Caveat: on the in-memory sample source path (`read_from_memory`, when the
caller passed the prior attempt as an already-loaded `EvalLog` object rather
than a file reference), the source closure captures `eval_log` and scans
`eval_log.samples` on every lookup, so the whole prior log stays resident for
the attempt regardless — that memory was spent by the caller loading the log
before retry even started, and the caller's own reference would keep it alive
even if the source dropped consumed samples. Part 1 still removes the
recorder's *duplicate* copy; only the halved benefit is inherent. The
incident path (retry from a log file) gets the full benefit: lookups read one
sample body at a time and nothing pins the reused set once write-through
lands it in the temp zip.

### 2. One deterministic destination flush when the reuse sweep settles

Track re-logged-but-not-yet-flushed reused samples in `TaskLogger` as a second
pending list (`flush_quiet: list[(id, epoch)]`, appended by
`_finalize_sample(flush=False)`), parallel to `flush_pending` but not counted
toward the `flush_buffer` threshold and not arming the stale-flush timer.

`_flush_pending_samples` drains both lists: proceed when either is non-empty
(this is also what makes `ctl task log-flush` work for reused samples — an
explicit operator flush, the stale timer, and a live threshold flush all pass
through here; `log_finish` does *not* — it drains the recorder buffer via its
own `recorder.log_finish` path, whose final write picks up temp-zip contents
regardless, and clears the pending lists itself). Bookkeeping mirrors the existing
tail-preserving pattern: snapshot both lists, write, then `del` each flushed
prefix; the stale-flush reschedule predicate stays keyed off `flush_pending`
only. `flush_quiet` is cleared alongside `flush_pending` in `reinit()` and
`log_finish` so a failed drain can't leak phantom pending state into the next
in-process retry attempt. `buffer_config` reports
`len(flush_pending) + len(flush_quiet)` as pending, and the count
`flush_samples()` returns (its docstring promises "the number written", and
`ctl task log-flush` surfaces it to the operator) covers samples drained from
**both** lists — implemented naively from today's `flushed = len(pending)`, a
quiet-only drain would write the whole reused set yet report 0.

**Trigger**: `task_run` creates a countdown initialized to the number of
planned `(sample, epoch)` runs. Each `run_sample` decrements it in a `finally`
around the *lookup + re-log region only* — i.e. immediately after
`complete_sample(flush=False)` returns, and **before**
`resume_scan_previous_sample` (which acquires the sample semaphore and can
block behind long-running live samples) and `sample_complete` (which awaits
the user's early-stopping hook). Live samples decrement right after their
lookup misses. The countdown has no waiter: the final decrement itself fires
the trigger — when it hits zero and `flush_quiet` is non-empty, spawn **one**
`_flush_pending_samples()` via `run_in_background` (already the pattern in
`log.py`), with the flush wrapped in a cancellation shield exactly like the
stale-timer path.

This is the "consolidate into a single write once the sweep quiets down" from
the issue, but keyed to an exact event instead of a 60s timer: it fires as
soon as the last planned sample has resolved its lookup — no earlier (no
partial-sweep flushes), no later (no idle wait), and not at all when nothing
was reused.

Teardown interaction: cancelled `run_sample`s still run their `finally`, so
on an early whole-task failure the countdown can reach zero during teardown
and fire. That's benign: the flush serializes with `log_finish` on
`_flush_lock` and becomes a no-op once `_finished` is set; if it runs first
it writes samples `log_finish` would have written anyway (shielding matches
the timer path's idiom and adds no teardown cost `log_finish`'s own final
flush wouldn't incur). Only never-started coroutines skip their `finally`, in
which case there's no waiter to strand.

Failure handling: if the settle-flush write fails, log a warning and arm the
stale-flush timer as a *retry fallback* (the same pattern as
`flush_samples()`'s `except` branch). The permit for arming with an empty
`flush_pending` must be **sticky state, not a one-shot argument**: a
threaded-through parameter would cover only the first arming — if that timer
flush also fails, the timer's own failure re-arm in
`_stale_flush_after_delay` and the `except` re-arm in `flush_samples()` both
go through the plain `0 < len(flush_pending) < flush_buffer` predicate, and
the retry chain would die after one attempt with `flush_quiet` still
populated. Instead keep a `flush_quiet_retry: bool` on `TaskLogger`: set it
whenever a flush attempt fails with `flush_quiet` non-empty, clear it
whenever `flush_quiet` fully drains (and in `reinit()`/`log_finish` alongside
the lists), and extend the arming predicate to
`(0 < len(flush_pending) < flush_buffer) or (flush_quiet_retry and
flush_quiet)`. Because the flag only turns on after a failure, the normal
path is unchanged — quiet samples still never arm the timer mid-sweep. And
because every flush path now drains `flush_quiet`, even the no-timer
worst case is strictly better than today: the next live flush, `ctl task
log-flush`, or finish picks the samples up.

### Resulting behavior on the incident scenario

165 reused samples, long-running remainder: each reused sample is written to
local disk as it's re-logged (bounded concurrent residency, never the full
set), and one destination write happens right after the last planned sample
resolves its reuse check — typically seconds into the attempt, bounded by the
sweep duration (minutes for a large remote prior log; what the countdown
avoids relative to the blocking pre-pass is delaying *live-sample start*, not
the sweep itself). The
destination log then contains all reused samples; the recorder buffer holds
no full samples; `ctl` full-sample reads fall through to disk.

## Alternatives considered

- **Broaden the stale-timer arming condition (issue's suggestion).** Simplest
  diff, but keeps the full reused set in memory until the timer fires, and
  the timer is heuristic: fires mid-sweep if the sweep takes >60s (extra
  destination writes), fires 60s late otherwise. Kept only as the
  failure-retry fallback above.
- **`flush=True` on the reuse path.** ~16 full destination rewrites at
  startup for 165 samples (threshold every 10). Rejected in the issue;
  agreed.
- **Blocking pre-pass**: resolve all reuse lookups in `task_run` before
  launching any live sample, re-log + flush once, hand `run_sample` a
  pre-resolved map. Maximally deterministic and simplifies `run_sample`, but
  delays live-sample start by the full sweep+flush duration (potentially
  minutes for a large remote prior log — today live samples start
  immediately), and restructures the reuse data flow (scores, progress,
  resume-scan are per-sample closures). The countdown gives the same single
  deterministic flush without delaying live work. Worth revisiting if the
  countdown threading proves awkward in implementation.
- **Write-through only, no explicit flush** (rely on piggyback flushes plus
  the `_flush_pending_samples` either-list change making `ctl task log-flush`
  work). Fixes memory and gives operators a manual drain, but leaves the
  *automatic* durability gap unbounded on long-running retries.

## Edge cases

- **No reused samples** (fresh eval, or nothing completed prior): countdown
  reaches zero with `flush_quiet` empty → no flush, zero overhead.
- **`run_samples=False`**: `run_sample` never runs; countdown never
  decrements; harmless (no waiter).
- **Within-attempt sample retries** (`task_run_sample` re-entry): the
  countdown decrement lives in `run_sample`, outside `task_run_sample`, so it
  runs exactly once per planned `(sample, epoch)` — no double decrement.
- **`log_samples=False`**: reuse path doesn't call `complete_sample` at all
  today; countdown still decrements; `flush_quiet` stays empty.
- **`score` re-scoring**: doesn't go through `TaskLogger.complete_sample` at
  all (`score_async` edits the log in memory; the streaming score CLI calls
  `Recorder.log_sample` directly with its own periodic flushes); untouched.
- **Epochs > 1**: countdown counts `(sample, epoch)` runs; reuse is per
  `(id, epoch)`. No change.
- **Concurrency**: write-through happens under `ZipLogFile._lock` (the same
  lock the flush's zip close/reopen takes); the settle flush and any
  concurrent threshold/ctl flush serialize on `TaskLogger._flush_lock`.
  `flush_quiet` appends all happen before the settle trigger fires (the
  trigger *is* "all reuse checks resolved"), so a concurrent earlier flush
  snapshotting part of the list leaves a remainder the settle flush drains.

## Out of scope (noted, pre-existing)

- The `sample_summaries()` duplicate-`(id, epoch)` union quirk when
  re-logging into an existing log (`log_init(clean=False)` + buffer union) —
  see the note on PR #119. Write-through actually narrows it (the journal
  summary write dedupes `_summaries` by `(id, epoch)`), but the buffered-live
  case remains as is.
- `.json` recorder memory profile (whole log in memory by design).
- The in-memory sample source retaining the prior log's samples for the
  attempt's lifetime. Affects only callers who retry from an `EvalLog` object
  they already loaded whole into memory — never retry-from-file — and the
  residency is theirs, not the recorder's (see caveat in part 1).

## Testing

- **`TaskLogger` unit tests** (`tests/log/test_task_log.py` or nearest fit):
  `flush=False` samples land in `flush_quiet`; `_flush_pending_samples`
  drains both lists (tail-preserving); `flush_samples()` (the ctl path)
  flushes when only `flush_quiet` is non-empty — the current no-op regressed —
  and returns the count of samples written across both lists;
  threshold/timer arming ignores `flush_quiet` while `flush_quiet_retry` is
  unset; failed settle-flush sets `flush_quiet_retry` and arms the retry
  timer; a second failure re-arms it (the flag is sticky, not one-shot); a
  successful drain clears the flag; `reinit()`/`log_finish` clear
  `flush_quiet` and `flush_quiet_retry`.
- **Recorder tests**: `log_sample(write_through=True)` leaves `_samples`
  empty, sample immediately present in `sample_summaries()` exactly once,
  event-less copy served by `buffered_sample()` pre-flush and gone
  post-flush, full sample readable from the destination log after flush.
- **Eval-level retry test** (nearest existing retry test file): eval with one
  completed + one long-running/blocked sample → retry → assert the new
  attempt's destination log contains the reused sample *before* the live
  sample completes, and the recorder buffer holds no full reused samples.
