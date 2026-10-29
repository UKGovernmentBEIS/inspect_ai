# Seeded Retry Attempt Logs

## Overview

A retry attempt (an in-process task retry, an eval-set pass, or
`eval-retry`) reuses the samples a prior attempt of the task completed.
Before the attempt does any work, its log is seeded from the prior log: the
prior `.eval` is copied whole into the attempt's temp zip, opened in append
mode, and restricted to the attempt's planned samples. The attempt's log
therefore holds every selected prior record from its first flush. The reuse
sweep reads each planned sample's record back from that local copy and
reuses it, carries its error history into a re-run, or runs it fresh; a
re-run appends a superseding member under the same name. Whatever ends the
attempt (error, cancellation, Ctrl-C, success), its log is complete, and a
hard kill leaves either no file or a complete one. A prior in another format
or held in memory is re-logged sample by sample before `log_start` instead.

The code is `ZipLogFile.seed_from_prior_log()` in
[`eval.py`](../src/inspect_ai/log/_recorders/eval.py), `Recorder.log_seed()`
in [`recorder.py`](../src/inspect_ai/log/_recorders/recorder.py),
`TaskLogger.seed_from_prior()` in
[`log.py`](../src/inspect_ai/_eval/task/log.py), and `task_run()` and
`run_sample()` in [`run.py`](../src/inspect_ai/_eval/task/run.py). On S3 the
seeded first flush copies the prior's bytes server-side; see
[`s3-incremental-log-flush.md`](s3-incremental-log-flush.md#the-seeded-start-flush).

## Self-contained logs

> **Every log file stays self-contained, and the newest log for a task stays
> the whole truth about that task.** A retry never re-runs a sample that a
> prior attempt of the same task completed cleanly, however the attempts in
> between ended.

A retry attempt takes its source from exactly one prior log: the newest log
for the task in eval-set, the failed attempt's log for an in-process retry,
or the named log for `eval-retry`. If an attempt's log could ever be a
strict subset of its prior (as when prior samples are copied in one at a
time, interleaved with live work, and the attempt errors part way), that
log would become the task's newest, the next attempt would re-run every
completed sample missing from it, and retry cleanup would delete the older
log that held them. Seeding before any work runs makes the attempt's log a
superset of the prior at every instant.

Out of scope: how eval-set selects the source (newest log per task), the
meaning of `retry_cleanup`, and the per-attempt log identity (one log file
with its own `eval_id` per attempt).

## Seeding the log

### When the seed runs

`eval_log_sample_source()` sets `EvalSampleSource.seed` (a `SeedSource` of
the prior location or in-memory samples, the `classify` resolver, and the
prior's epoch count) only when the prior passes the reuse eligibility
checks: a shuffled dataset needs sample ids, and the dataset size must
match (or have grown, with stable ids). An ineligible prior warns and gives
no reuse.

`task_run()` seeds when the source carries a seed and sample logging is on.
It runs after the retry-abandoned check and before anything that needs
unwinding: the checkpoint startup copy, the paged sample store, the display
row and `log_start`. A seed failure therefore fails the attempt with no
destination written. The abandoned check is repeated after the seed, since
the copy can take minutes and an abandon landing meanwhile would otherwise
be honoured only after the `log_start` flush had uploaded the seeded log.

The seed is restricted to a `keep` set of `(id, epoch)` keys:

- a planned task: its sliced sample ids × epochs;
- a dynamic feed without a limit: every prior key that matches the
  explicit sample-id filter, with an epoch within the attempt's epoch
  count, or above both that count and the prior's (epochs only an explicit
  `enqueue_sample(..., epoch=)` can produce). Epochs above the attempt's
  count but within the prior's (a retry with fewer epochs) are left out
  up front; when the feed explicitly admits such an epoch,
  `TaskLogger.seed_added_samples()` copies its prior record before it is
  dispatched;
- a limited dynamic feed: its sliced initial plan. As the feed admits more
  samples under the limit, `TaskLogger.seed_added_samples()` copies their
  prior records before they are dispatched, skipping keys this attempt has
  already recorded.

`TaskLogger.seed_from_prior()` calls `Recorder.log_seed()` and sets
`prior_seeded`. A prior log that no longer exists leaves the attempt
unseeded with a warning (every planned sample runs fresh), since a retry
with the same missing source could never do better. Any other failure
propagates and fails the attempt.

### Copy, validate, adopt

`EvalRecorder.log_seed()` takes this path for a `.eval` prior location and
otherwise defers to the base re-log (below). `ZipLogFile.seed_from_prior_log()`
runs after `init()` and before `start()`:

1. **Copy** the prior into a fresh anonymous temp file, outside `_lock` (a
   long download must not stall the recorder's other lock users). The copy
   is `AsyncFilesystem.read_file_into()`: S3 streams in bounded memory on
   both backends (asyncio writes a byte stream inline; trio copies in a
   worker thread, checking cancellation between chunks); a local file is
   copied in a worker thread; GCS and Azure are read synchronously on the
   event loop one chunk at a time with a checkpoint between chunks, since
   remote fsspec work must not run in a worker thread. Transient failures
   are retried three times with jittered exponential backoff; a missing
   prior raises `FileNotFoundError` at once.
2. **Validate and read the summaries** by opening the copy in read mode,
   which raises `BadZipFile` for a corrupt or truncated copy (append mode
   would treat it as an empty archive and seed nothing). The summaries are
   `summaries.json` if present, else the journal in index order, deduped,
   then filtered to `keep` by generated member name: these are the kept
   summaries.
3. **Rewrite if needed** (see Restricted seeds).
4. **Swap** under `_lock`. The handle `init()` opened is an append-mode
   `ZipFile` over an empty file, whose close (also from `__del__`) writes
   an end record at offset 0; it is closed explicitly over the old file
   before the copy replaces it, so nothing writes over the copied bytes.
   Then `_open()` parses the copied central directory.
5. **Prune** from the central directory: `header.json`, `summaries.json`,
   `reductions.json`, `_journal/start.json`, every journaled config update
   and summary, and every `samples/*` member not named by a kept summary.
   Otherwise an in-progress read of the new log would return the prior's
   header and eval_id. Names are generated from `(id, epoch)` and compared,
   never parsed: `samples/1_epoch_1.json` does not say whether the id was
   `1` or `"1"`, and an id containing `_epoch_` cannot be split back.
6. **Rewrite the summaries journal** as one member,
   `_journal/summaries/1.json`, listing exactly the kept summaries
   (serialized and deflated in a worker thread under `_lock`), and
   re-journal any config updates recorded since `init()`. Readers take the
   highest journal index present, so restarting at 1 is consistent. The
   prior's batched journal files are pruned rather than kept because a
   batch could list a pruned key next to kept ones.
7. **Register** the kept member names in `_local_sample_names`, the set
   `buffered_sample()` serves from the local zip.

The seed runs from `task_run()` rather than `TaskLogger.init()` because
`init()` runs in the dispatcher (for every task up front, or for an
in-process retry), where a failure would take the whole run down, and so
that a run with many queued tasks does not download every prior log at
startup.

### Restricted seeds and dead bytes

Excluded sample bodies never reach the destination, not even as
unreferenced bytes: central-directory pruning alone would leave excluded
transcripts recoverable from the file. Before adopting the copy,
`zip_needs_rewrite()` walks the members' exact local-header extents and
requires a rewrite when the archive holds a sample member outside the kept
set, or bytes no member accounts for (pruned or superseded members a prior
non-success attempt carried), or a layout it cannot verify (a data
descriptor, an unexpected header). A rewrite (`compact_zip()`) copies only
the kept live members into a fresh file. A failure or cancellation of that
rewrite fails the seed; it never falls back to the unfiltered copy.

A copy that needs no rewrite is adopted byte for byte. The prior's own
metadata members then stay as unreferenced bytes until compaction.

### Other formats and in-memory priors

`eval-retry` may name a log format that differs from the prior's, and
`eval_retry()` accepts a loaded `EvalLog`. A byte copy is valid only
between `.eval` files, so the base `Recorder.log_seed()` (which
`JSONRecorder` inherits) re-logs each kept sample through
`log_sample(write_through=True)` before `log_start`. The recorder loads the
prior once per attempt into a `SeedSamples` index (keys in source order; a
`.eval` prior keeps a shared zip reader, a `.json` or in-memory prior keeps
its bodies), under a lock so concurrent first callers load it once. Keys
match in string form, as the recorders name a sample's record (`1` and
`"1"` are one record, `"001"` another). `.eval` bodies are read in batches
of eight, bounding both concurrent reads and retained bodies; a checkpoint
between samples keeps the seed cancellable and lets sibling tasks run.
Samples keep their images as the prior recorded them, matching the byte
copy. `JSONRecorder.log_sample()` supersedes an existing record for the
same `(str(id), epoch)`, the `.eval` readers' rule. The index and its
filesystem clients are released at finish, discard and task exit.

## The reuse sweep

When the log is seeded, `run_sample()` reads each planned key's record from
this attempt's own log (`TaskLogger.read_prior_sample()`, at most four
reads at once, since every planned sample starts at once and the recorder
serializes the reads on its lock) and resolves it with `seed.classify`:

- **clean** (`error` and `invalidation` both unset): reused. The reporter
  gets the sample's scores and metadata from the full body, and
  `note_reused_sample()` counts it as this attempt's result. Nothing is
  written.
- **errored or cancelled**: resumes from this attempt's checkpoint for the
  sample when one exists. Otherwise it runs fresh as a `PreviousError`, so
  the re-run's `error_retries` continues the prior's history of genuine
  failures (a cancellation is not counted as one).
- **invalidated**: an `InvalidatedPrior`; never resumes. The re-run starts
  fresh and discards the sample's copied checkpoint.
- **absent**: checkpoint resume if one exists, else a fresh run.

The body is read rather than the summary because summaries are thinned when
validated (long score fields and metadata shortened), which would change
metric grouping and persist truncated values in `reductions.json`, and
because a summary carries no invalidation state.

When the log is not seeded (sample logging off, or the prior log gone), the
sweep looks each key up in the prior source, at most 25 lookups at once,
and a clean sample is re-logged with `complete_sample(flush=True)` when
sample logging is on.

The one remaining per-sample remote step in a seeded sweep is the
checkpoint resume probe (and the delete before a fresh run) against this
attempt's checkpoint directory, at most 25 at once.

Seeded records are not counted as this attempt's resolutions when seeded:
`samples_logged` and `samples_completed` count a reused record when the
sweep accepts it and a re-run when it completes. Otherwise a drain that
abandoned a seeded errored sample's re-run would read as complete, and a
later pass would never re-run it.

## Reading seeded records

`ZipLogFile.buffered_sample()` serves, in order: a buffered whole sample;
a member in `_local_sample_names` (a seeded record or a write-through
re-log), read from the local zip, whose last member under the name wins so
a re-run supersedes the seeded record; an event-less streaming sample.
The local read decompresses in a worker thread while `_lock` is held (the
same contention a flush imposes); validation and the read-time resolution
every log read applies run afterwards, outside the lock. When the control
channel excludes fields, the member is streamed through the same selective
JSON parser as the on-disk reader, so excluded fields are never built.
`TaskLogger.read_sample()`'s fallback therefore never needs the destination
for a seeded sample.

## Live listings withhold unresolved seeded records

A seeded log holds the prior attempt's errored or cancelled record for a
key whose re-run is running or still queued. Shown as is, it would hide
the running row or list a waiting sample as `error`.

`TaskLogger` records every seeded key (`_seeded_pending`) and drops a key
when the sweep accepts its record or a completion for it lands. The live
listing source (`TaskLogger.sample_summaries()`) and the whole-sample read
behind `ctl` error detail, requeue and cancel (`TaskLogger.read_sample()`)
withhold pending keys, so such a sample reads as running or pending, and
requeue and cancel see it as not yet at the queue (see
[`ctl/queued-sample-cancel.md`](ctl/queued-sample-cancel.md)). An
invalidated record, clean to the summary, stays withheld until its re-run
completes. Once the eval finishes the on-disk log is read, where an
unresolved seeded record is the sample's final one.

A dynamic feed's seeded keys that it never re-injects are never resolved.
At a natural success (the attempt realized its whole plan, nothing
abandoned) `TaskLogger.log_finish()` passes them to `Recorder.log_prune()`,
which drops their members and summaries, so the success log describes this
attempt's plan. A graceful resolution that abandoned queued samples, and a
non-success finish, keep them: the next attempt reuses them.

## Compaction at a successful finish

At a successful `log_finish`, `ZipLogFile.compact()` rewrites the temp zip
with only the live members when dead bytes are at least 10% of the member
area. Dead bytes are measured from the file (the member area minus the live
members' local headers and data), not tracked, so bytes a prior non-success
attempt carried count too. A fresh eval measures none. The rewrite runs in
a worker thread and checks cancellation between chunks. A failure or
cancellation reopens the original file and restores the live member set
from the writer's in-memory directory (a finish-time prune not yet written
to disk would otherwise come back); a failure warns and keeps the
uncompacted, still correct, log. Non-success finishes do not compact.

## The next attempt's source

An in-process retry (`run_task_retry_attempts()`) decides from the
attempt's `TaskLogger` state, with no filesystem probe on the dispatcher's
loop:

- **finished**: the attempt's log.
- **unfinished, destination written** (a later flush or `log_finish`
  failed): also the attempt's log, through the same
  `eval_log_sample_source()` with its checkpoint directory. It holds the
  seeded prior set plus every flushed completion under a `started` header,
  a superset of every earlier log. `reinit()` releases the recorder entry
  and buffer database and leaves the file in place.
- **nothing written** (the seed or the `log_start` flush failed): the same
  source the attempt ran with.

Eval-set selects the newest log per task, so an attempt that wrote nothing
leaves the older log as the source. An abandoned attempt's destination
holds the prior set and nothing new, and its discard removes it.

With `retry_cleanup`, eval-set removes each task's older logs, including
older `started` logs: every log is seeded from its prior, so an older log
holds nothing the newest lacks. A `started` log is removed, with its sample
buffer, only when its run id is one of the `eval()` calls this eval-set
invocation made, and only once that buffer has finished shutting down;
nothing on disk shows that another process has stopped writing one, so
`started` logs from other runs stay.

## Crash recovery

After the `log_start` flush the destination holds the prior set, so
buffer-database recovery of a crashed attempt yields a superset of the
prior. Recovery must not mistake an inherited record for one this attempt
flushed: a seeded errored sample whose re-run completed (or was running)
only in the buffer would otherwise recover as the old failure.
`_superseded_by_buffer()` in
[`_recover/_api.py`](../src/inspect_ai/log/_recover/_api.py) lets a buffer
entry win when it started after the log's record for that key ended (its
completion, or for a recovered interruption its start); otherwise the log's
record stays authoritative, as does a record either side cannot date. The
comparison spans
attempts, so it assumes their clocks agree to within the gap between the
prior finishing and the retry starting; `seed_from_prior()` warns when this
clock reads earlier than the prior's latest record. Under undetected skew
the inherited record wins.

## Failure behaviour

| When | Outcome |
|---|---|
| error, cancel, terminate or Ctrl-C after the seed | `log_finish` writes a complete error or cancelled log; the next attempt seeds from it and re-runs only what still needs running |
| the prior log cannot be read | the seed fails before `log_start`; no file; the next attempt uses the same source (in-process) or the older log (eval-set). No sample ran, so no error history is lost |
| the prior log is gone | the attempt runs unseeded, every planned sample fresh |
| the prior log is corrupt | validation fails the attempt like a read failure |
| hard kill during the seed | no destination file |
| hard kill after the `log_start` flush | the destination holds the prior set plus later flushes; recovery yields a superset of the prior |
| `log_finish` fails after earlier flushes | the `started` destination is the next source; only completions since the last flush re-run |
| compaction fails | warning; the uncompacted log is written |
| a destination flush fails | warning, stale-timer retry, `log_finish` as backstop; a failure at `log_start` fails the attempt early, as for a fresh eval |

## Trade-offs

1. **Live samples start after the seed download.** For a multi-GB prior on
   a slow link that is tens of seconds to minutes of startup per attempt.
   Total work to reach a destination holding the prior set is lower than
   copying sample by sample (see Performance); what changes is that live
   work no longer overlaps the read.
2. **Dead bytes between attempts.** A non-success attempt's log carries
   the prior's superseded metadata and the prior records of re-run
   samples, bounded by the re-run set; compaction at the successful finish
   reclaims them, and retry cleanup removes the intermediate logs.
3. **A `log_images=False` retry of a `log_images=True` log keeps the prior
   samples' images**, since they are copied, not condensed.
4. **The first flush carries the whole prior set.** On S3 under asyncio it
   is composed from the prior object; elsewhere it uploads the seeded log.
5. **A dynamic feed's unplanned prior records stay until a natural
   success**, and remain in a non-success log or a graceful resolution's
   success log, where the next pass reuses them. A limited feed cannot
   know its later selections, so it seeds only its initial plan and each
   admitted batch; an interrupted limited retry keeps the batches fully
   copied, and a cancelled admission keeps only the records copied so far
   and does not dispatch the batch.
6. **A `log_finish` failure after earlier flushes leaves a `started` log as
   the task's newest.** It lacks only the header (status, task-level error,
   stats, results), and `started` is accurate for an attempt still running
   when its write failed. Finalizing the header would be another write to
   storage that has just failed.

## Performance

**Method.** A react-agent task on `mockllm/model` whose `custom_outputs`
returns `run_cmd` tool calls for a fixed number of turns and then `submit`,
with pseudo-random prose so zstd does not collapse the log. The last 5% of
samples raise once (a marker file per sample id) with
`continue_on_fail=True`, so the first attempt ends `error`. A prime phase
(`eval_set(retry_attempts=0)`) writes the first log; the timed retry is a
second `eval_set` in a fresh process on a copy of that log directory, whose
re-runs use 2-turn transcripts so the timing isolates reuse. Shape **A** is
500 samples × 80 turns (≈250 KB each, ≈119 MB log, 25 re-runs); shape **B**
is 50 samples × 400 turns (≈4 MB each, ≈195 MB log, 3 re-runs). Trace logs
(`Log Write` actions) split writes from the rest. Profile in process: the
`-m cProfile` wrapper changes the task's identity.

**Result**, against copying prior samples one at a time (read, condense,
re-serialize, recompress, re-log): on local disk reuse took about a third of
the time on both shapes (A: 9.4 s against 24.9 s retry wall; B: 6.4 s
against 15.8 s), with first-attempt time and log sizes unchanged. On S3 from
an office link (≈11 MB/s) the whole-file download costs about what the
per-sample work saves on A and wins on B, where samples are larger;
in-region the download takes a second or two. Write costs on S3 are in
[`s3-incremental-log-flush.md`](s3-incremental-log-flush.md#performance).

## Decisions

- 2026-09-03: every log file stays self-contained, and the newest log for
  a task is the whole truth about it. A retry does not depend on more than
  one file; chaining the retry source across a task's logs is rejected
  (decision: Ransom, 2026-09-03).
- 2026-09-03: seed the attempt's log from the prior log before any work,
  as described here, with the in-process retry keeping its source when the
  attempt wrote nothing and a bounded retry of the download (decision:
  Ransom, 2026-09-03).
- 2026-09-08: an unfinished attempt whose destination was written keeps
  its `started` log, and that log is the next attempt's source. Sample
  progress outranks the header it lacks (decision: Ransom, 2026-09-08).

## Alternatives considered

- **A2: concurrent seed.** Live samples start while the seed downloads,
  with destination writes held until it lands. If the seed fails after live
  samples complete, the attempt must drop their results or write a partial
  log. Kept as a follow-up if startup latency proves a problem.
- **Copy prior samples one at a time, interleaved with live work** (a lazy
  reuse sweep, with destination writes held until the sweep settles and a
  teardown carry-forward of errored records). Leaves the subset window
  open on every graceful error, and does per-sample remote reads, parsing
  and recompression.
- **B: copy only the planned entries' raw bytes before `log_start`.** One
  range read per entry for the same bytes as one download, plus a
  hand-written raw zip writer.
- **C: server-side copy of the prior log to the destination at start.**
  The first whole flush overwrites it, and the copy carries the prior's
  `header.json` (its `eval_id` and status) until rewritten. On S3 the
  composed start flush gets the server-side copy without either problem.
- **D: finish the copy at teardown.** Runs a download under the Ctrl-C
  shield, and fails for the same reason when the trigger was a prior-read
  failure.
- **E: write no log for an attempt whose copy has not settled.** Loses the
  errored attempt's record and its live results; only its source-reuse
  rule for an attempt that wrote nothing is kept.
- **F: one log per task across attempts.** Changes attempt identity for the
  viewer, listings, registry and `--no-retry-cleanup`.
- **G: chain the retry source across a task's logs.** Rejected by the
  2026-09-03 decision: a retry would depend on a set of files with a
  precedence rule every consumer must know.
- **Discard a partial `started` destination and fall back to the prior
  source.** Tidier log directory, but re-runs the attempt's flushed
  completions; rejected by the 2026-09-08 decision.
- **An explicit seeded-members journal for recovery.** Exact, but a new
  member family that grows with re-runs × seeded records, to cover a rare
  case the timestamps already decide.

## Compatibility

- **Stored format.** None new. Duplicate member names resolving to the last
  entry, and unreferenced bytes after a directory prune, are existing
  `.eval` conventions every reader follows.
- **Older priors.** Seeded samples keep their original schema version;
  readers already handle mixed-version members. The new attempt's
  `_journal/start.json` supersedes the prior's.
- **Ids.** Sample records match by `(str(id), epoch)` in every recorder, so
  an id a loader changes between integer and string form still matches.
- **Retry cleanup** removes older `started` logs this eval-set invocation
  wrote, as it removes other older logs; `retry_cleanup=False` keeps
  attempt history.
- **Public API and CLI.** None.

## Security

- **Excluded samples.** A restricted seed physically removes excluded
  sample bodies before the first destination write, so a `sample_id` or
  `limit` subset never publishes excluded transcripts as recoverable bytes.
- **Prior log contents.** The copy is validated as a zip before adoption;
  member names are generated from `(id, epoch)` and compared, never parsed
  from the archive. Retrying a log runs code and settings it names, so
  retry only trusted logs (see
  [`malicious-log-code-execution.md`](malicious-log-code-execution.md));
  the seed adds no new path from log contents to code.

## Not this design

- **A2, the concurrent seed**, if startup latency is a demonstrated
  problem, with the rule that a seed failure after live work discards the
  attempt.
- **Prune attachments at compaction** for `log_images=False` retries of
  `log_images=True` logs (trade-off 3).
- **`eval-retry` seeding from a directory's newest same-task log** rather
  than only the named file.
- **F, one log per task**, if per-attempt log identity is ever judged more
  cost than value.
