# Deferring a retry attempt's destination log until the reuse sweep settles

Design for [meridianlabs-ai/inspect_ai#240](https://github.com/meridianlabs-ai/inspect_ai/issues/240).
Builds on the reuse-sweep settle-flush machinery from
[retry-reused-sample-flush.md](retry-reused-sample-flush.md).

## Problem

A retry attempt (eval_set retry, in-process task retry, or `eval-retry`)
today touches the destination log in this order:

1. `TaskLogger.log_start` flushes immediately (`_eval/task/log.py`) —
   the destination `.eval` is created containing only `_journal/start.json`,
   before any sample work runs.
2. The reuse sweep re-logs the prior attempt's completed samples with
   `write_through=True`: they land in the recorder's **local temp zip**
   (`ZipLogFile._temp_file`, an anonymous `tempfile.TemporaryFile()`), not
   the destination.
3. The reuse-sweep settle flush (`reuse_sweep_settled`, fired by
   `_ReuseSweepCountdown`) — or any earlier flush trigger — copies the temp
   zip to the destination.

A hard kill (crash, OOM, machine loss) between (1) and (3) leaves the
destination with the newest mtime and zero samples, and the temp zip dies
with the process. Every retry builds its sample source from exactly one log —
the latest per task (`latest_completed_task_eval_logs`, mtime-sorted) — so
the next retry chains off the crashed attempt's empty log, finds nothing to
reuse, and re-runs every sample, including completed ones. Buffer-DB
recovery doesn't help: reused samples never get buffer rows (the quiet
re-log path skips `start_sample`), so the `-recovered.eval` it produces
carries only live in-flight samples — and, being newest, it *becomes* the
retry source, cementing the loss. With the default `retry_cleanup=True` the
prior log holding the completed samples is deleted when the set eventually
succeeds, turning duplicated spend into permanent data loss.

## Approach

Enforce one invariant:

> **A retry attempt performs no destination write until its seed reuse
> sweep has settled.**

The attempt's first destination write is then the settle flush, which by
construction contains `start.json` plus **every** reused sample: each
`run_sample` writes its reused sample through to the temp zip *before*
settling its countdown slot (the write-through in `complete_sample` is
awaited inside the `try`; `settle_one()` runs in the `finally`), and the
settle flush fires only after the last slot settles — so when it copies the
whole temp zip, the reused set is complete. Therefore:

- **Crash before the first write** → no destination file at all. The next
  retry's `latest_completed_task_eval_logs` never sees the attempt and
  naturally falls back to the previous attempt's log with its completed
  samples. Reuse intact.
- **Crash after** → the destination already contains the complete reused
  set. Reuse intact.
- **Crash during** collapses into before/after on the main backends: local
  writes go through `atomic_write` (temp + rename), S3 through a multipart
  upload that either completes or leaves no object. (Pre-existing exposures
  shared by every flush, unchanged here: a non-atomic fsspec backend could
  leave a partial file, and local intermediate flushes run
  `atomic_write(fsync=False)` — atomic against process death, but power or
  machine loss can still surface a renamed-but-unsynced flush as a partial
  file.)

### Why gate *all* destination writes, not just `log_start`'s flush

Any mid-sweep destination write reopens the window with a partial reused
set: a fast live completion reaching the `flush_buffer` threshold, the 60s
stale-flush timer, an operator's `inspect ctl task log-flush`, or a ctl
config retune (`EvalRecorder.log_config_update` pushes its journal entry
eagerly once `start.json` is written). A crash after any of those leaves a
newest log missing whatever the sweep hadn't re-logged yet — the same bug,
probabilistically narrower. Gating everything makes the guarantee absolute
rather than a race.

The complete inventory of destination-write paths during a task run:

1. `TaskLogger.log_start` — the immediate `recorder.flush` after
   `recorder.log_start`.
2. `TaskLogger._flush_pending_samples` — shared by the threshold flush, the
   stale-flush timer, `flush_samples()` (ctl `log-flush`), and the settle
   flush itself.
3. `EvalRecorder.log_config_update` — the eager `log.flush(fsync=False)`.
4. `Recorder.log_finish` — the final write (must **not** be gated: it is
   the attempt's own terminal record, and its temp zip already holds all
   write-throughs).

(Other `recorder.flush` callers — the score CLI, `log/_convert.py`, the
recovery writer — operate their own recorder instances outside a task run
and are untouched.)

## Mechanism

### `TaskLogger` hold

New state `TaskLogger._destination_hold: bool` (default `False`) with a
method to set it (e.g. `hold_destination_writes()`).

- **Set**: `task_run` calls it immediately before `logger.log_start(...)`
  when `options.sample_source is not None and store_len * epochs > 0` — a
  retry attempt with a non-empty seed. Fresh evals are completely
  unchanged: the log file still appears at `log_start` (fail-fast on an
  unwritable log dir, immediate viewer visibility). A zero-seed
  SampleSource-driven task also skips the hold — its "sweep" is open-ended
  (samples injected over time), so there is no early settle event to key
  the release to, and holding indefinitely would be worse than today.
- **`log_start`**: skip the immediate `recorder.flush` while held.
  `recorder.log_start` still runs, so `start.json` is journaled into the
  temp zip and rides out with the first flush.
- **`_flush_pending_samples`**: under `_flush_lock`, immediately after the
  `_finished` check, return 0 while held — before `recorder.flush` and
  before any bookkeeping, so nothing is drained, no buffer-db rows are
  removed, and the pending lists stay intact for the settle flush to drain.
  Checking under the lock means a caller already awaiting the lock when the
  hold is released proceeds normally. A stale-timer or threshold fire that
  no-ops here is harmless: the settle flush drains everything, and a
  failed settle flush afterward is covered by the existing retry paths —
  `flush_quiet_retry` arms the stale timer for quiet samples, the
  `0 < len(flush_pending) < flush_buffer` predicate arms it for live ones,
  and when live pending has already reached `flush_buffer` (outside that
  predicate) the next completion's `>=` threshold check retries the flush,
  with `log_finish` as the final backstop. Nothing is stranded.
- **Release**: in `reuse_sweep_settled` (whose semantics become "the reuse
  sweep settled" rather than "flush quiet samples if any"). Synchronously
  clear the hold, then schedule the background flush when `flush_quiet` is
  non-empty **or the hold was set** — the destination must be created at
  settle even when nothing was reused (prior log empty or unreadable,
  `log_samples=False`), to restore the "running log exists on disk"
  property as early as possible. The empty-pending case needs
  `_flush_pending_samples` to proceed with both lists empty: add a
  `force: bool = False` parameter that skips the empty early-return
  (`recorder.flush` on an empty buffer just writes the temp zip —
  `start.json` plus any write-throughs — which is exactly the point).
  Later settle firings (a dynamic feed's `add()`/settle cycles) see the
  hold already cleared and take today's path.
- **`reinit()`**: reset `_destination_hold = False`. The in-process retry
  re-enters `task_run` with a fresh `sample_source`, which re-sets it.
- **`log_finish`**: unaffected. This also covers `run_samples=False`
  (immediate `log_finish("started")` creates the destination), teardown
  before settle, and graceful mid-sweep errors — the attempt's own record
  always lands.

### Recorder change: config-update eager flush keys off "destination written"

`EvalRecorder.log_config_update` currently flushes when
`log.log_start is not None` (skipping only the pre-`log_start` inherited
snapshot). Change the condition to "the destination has been written at
least once": `ZipLogFile` tracks `_destination_written: bool`, set by a
successful `flush()` and initialized `True` when `log_init(clean=False)`
found an existing file (re-logging into an existing log, e.g.
`score --overwrite`). For normal runs this is equivalent — `log_start`'s
immediate flush precedes any registered-eval retune. For held runs the
update is journaled into the temp zip and reaches the destination with the
settle flush. No `Recorder` ABC signature change; `JSONRecorder` (which
never eager-flushes updates) is untouched.

### `TaskLogger.read_sample` disk fallback

While held the destination doesn't exist, so the fallback
`read_eval_log_sample_async(self.location, ...)` raises
`FileNotFoundError` instead of today's `IndexError` (a start-only zip with
no such member). Catch `FileNotFoundError` alongside `IndexError` and
return `None`. (The retry sample source's `read_from_file` already handles
`FileNotFoundError` for a missing prior log — no change needed there.)

### Missing-file errors on S3

The two handlers above cover local paths only: on S3,
`AsyncFilesystem`'s read paths surface a raw botocore `ClientError`
(NoSuchKey) for a missing object — only `exists()` interprets 404. The
design makes "log file absent" a routine state (during the hold, and for a
crashed attempt's location consulted by the next retry), so the read layer
must normalize: map NoSuchKey/404 to `FileNotFoundError` in
`AsyncFilesystem`'s read path (or equivalently broaden the catches at
`read_sample`, `read_from_file`, and the reuse presence probe). Without
this, a ctl per-sample read during the hold on an S3 log dir would error
instead of returning `None`, and a no-file retry source on S3 would raise
per-lookup instead of degrading to no-reuse.

## Crash and failure analysis

- **Kill before the settle flush** (the issue's window): no destination
  file. Next eval_set pass lists only the prior attempt's error log →
  full reuse. The crashed process's buffer db is orphaned (its location has
  no file), which the existing dead-pid sweep
  (`cleanup_sample_buffer_databases`, 3-day threshold) collects.
- **Kill after**: destination holds the complete reused set → reuse works.
- **Settle flush write failure (no crash)**: hold already released; the
  existing warning + retry machinery applies (`flush_quiet_retry` arms the
  stale timer for quiet samples; live pending samples arm it via the
  settle-flush `except` re-arm). If nothing was pending at all, the
  destination is created by the next natural flush or `log_finish`. One
  behavior shift: a retry attempt no longer fails fast at `log_start` on an
  unwritable destination — the failure surfaces at the settle flush
  (warning) or `log_finish` (error). Fresh evals keep fail-fast.
- **Graceful error mid-sweep** (exception, not a kill): `log_finish` writes
  an error log that may contain a partial reused set (cancelled lookups
  never re-logged). Pre-existing behavior, unchanged: the next retry reuses
  the partial set and re-runs the rest — bounded re-spend, no data loss.

## Trade-offs (accepted)

1. **Delayed on-disk visibility of retry attempts.** The attempt's log file
   appears at sweep settle — typically seconds, bounded by the sweep
   (minutes for a large remote prior log, serialized by the 25-way reuse
   read throttle) — instead of at `log_start`. Affects `inspect view`'s
   file listing and anything else listing the log dir. `inspect ctl` task
   listing is unaffected (registry-based via `register_eval`). Fresh evals
   unaffected.
2. **Buffer-db recovery can't see a mid-sweep crash.** Recovery discovery
   keys off `status == "started"` log files; with no file, live samples
   that completed into the buffer db during the sweep window aren't
   recoverable and will re-run. Today they *are* recoverable — but the
   recovered log becomes the newest log *without* the reused set, actively
   cementing the larger loss (the repro's `-recovered.eval` with only
   sample 4). Net: trades a few mid-sweep live completions (re-run, window
   bounded by sweep duration) for the whole reused set (previously lost
   outright). A future extension could teach recovery to discover orphaned
   buffer dbs directly rather than via started logs.
3. **Mid-sweep sample checkpoints are orphaned by a mid-sweep crash.**
   Checkpoint dirs are keyed off the log file's basename
   (`eval_checkpoints_dir.py`), and a retry consults the *source log's*
   checkpoints dir. Today the crashed attempt is the retry source, so
   checkpoints written by its live samples resume; under the design the
   attempt leaves no file, the retry chains to the previous attempt, and
   the crashed attempt's checkpoints are silently unused — orphaned
   outright, since log basenames embed `created` to the second
   (`_log_file_key`) and a post-crash retry is a new invocation with a
   later `created`, so it never recomputes the crashed attempt's basename
   (the filename bump only matters for same-second collisions, which
   cannot follow a hard kill — the process is dead). Bounded by the
   same sweep window as trade-off 2, but checkpoints can represent more
   progress than buffer rows; a follow-up could widen checkpoint lookup to
   sibling attempt basenames.
4. **`inspect ctl task log-flush` during the hold returns 0** and writes
   nothing. The hold is short and the settle flush is already scheduled;
   document in the `flush_samples()` docstring.
5. **Config retunes during the hold** reach the destination at settle
   rather than eagerly (they were already journal-only before `log_start`).
6. **`debug_errors=True` mid-sweep exceptions leave no file**: that mode
   re-raises without `log_finish`, so a held attempt leaves nothing where
   today a start-only log aids post-mortem. Debug-mode only; the buffer db
   (and `.checkpoints` dir, when configured) still carry the state.
7. **Shared-log filestore vs. concurrent sweeps.** A mid-sweep crash's
   `log_shared` filestore directory is *collected*, not orphaned: the
   log-dir sweep (`cleanup_sample_buffer_filestores`) removes a buffer dir
   whose sibling `.eval` is missing, and under the design the crashed
   attempt leaves no file — an improvement over today, where the crashed
   attempt's `started` log (never removed, its status never updated)
   shields the dir indefinitely. The hazard runs the other way: while a
   live attempt is held, its filestore dir likewise has no sibling
   `.eval`, so a concurrent process finishing an eval into the same log
   dir (`cleanup_sample_buffers` at end of run) sees it as debris and
   deletes it mid-run. That exposure is pre-existing — the filestore is
   created eagerly when the `TaskLogger` is constructed, so a task queued
   behind `--max-tasks` already sits in this window arbitrarily long
   before `log_start`'s flush — but the design extends it to
   actively-running retry attempts; a mitigation could have the sweep
   skip filestore dirs with recent write activity.

## Alternatives considered

- **Chain lookback** (the issue's second direction: consult older logs when
  the latest is missing samples). Heals more shapes (including partial
  logs) but changes retry semantics from "latest log is authoritative" to a
  multi-log merge, with invalidation/epoch/config-change hazards across
  attempts — and the empty log still wins mtime selection for every other
  consumer (recovery, cleanup, viewer). Deferral prevents the bad state
  from existing at all; lookback could still be layered on later as
  resilience.
- **Keep `retry_cleanup` from deleting un-carried-forward logs** (the
  issue's third direction). An orthogonal safety net for manual recovery;
  out of scope here.
- **Blocking reuse pre-pass before `log_start`** (resolve all lookups, then
  create the log). Same guarantee, but delays live-sample start by the full
  sweep and restructures the per-sample reuse closures — rejected for the
  same reasons as in the settle-flush design.
- **Gate only `log_start`'s flush.** Smallest diff, but any mid-sweep flush
  trigger reopens the window with a partial reused set (see above).

## Edge cases

- **Fresh eval / no sample source**: no hold; behavior byte-for-byte
  unchanged.
- **Nothing reused** (prior log empty or unreadable, all lookups miss):
  settle fires with `flush_quiet` empty; the forced settle flush still
  creates the destination.
- **`log_samples=False`**: reuse path never calls `complete_sample`; same
  as "nothing reused".
- **`run_samples=False`**: hold may be set but `log_finish("started")`
  runs immediately and writes the destination.
- **Zero-seed dynamic task** (`store_len * epochs == 0` with a sample
  source): no hold (see above); unchanged.
- **Dynamic feeds injecting before the seed settles**: a completion-driven
  SampleSource regenerates follow-ups from reused completions *during* the
  sweep, and each injection raises the countdown (`add()`). The hold spans
  only the cascade already counted when the countdown first reaches zero,
  not the whole transitive cascade: a reused sample settles its slot in
  `run_sample`'s `finally` *before* its follow-ups are handed to the feed,
  so the last seed sample's settle can release the hold while follow-up
  reuse is still being injected. That's the safe direction — the seed
  reused set is complete at that point, which is what the invariant needs —
  and the residual partial window for injected reuse is the pre-existing
  one below. The hold therefore stays bounded by the seed sweep.
- **Dynamic feeds adding samples post-settle**: injected reuse re-logs
  flush via later `add()`/settle cycles — unchanged; the residual
  partial-window for injected reuse is pre-existing and much narrower.
- **Within-attempt requeues**: skip `settle_one` (existing); a requeued
  completion is a normal `flush=True` completion — while held it queues and
  drains at settle.
- **Filename reuse**: a post-crash retry embeds its own later `created` in
  the log basename (see trade-off 3), so it computes a different path from
  the crashed no-file attempt regardless of
  `_bump_created_past_existing_logs` (which bumps only past *existing*
  files and only matters for same-second collisions) — nothing to collide
  with either way; buffer dbs are pid-suffixed. The in-process retry *can*
  hit the same-second no-file case (a held attempt whose `log_finish` also
  failed leaves no file, and a `reinit()` landing on the same second
  recomputes the identical path and recorder key since the bump only sees
  existing files) — benign: `reinit()` already resets the buffer db for
  repeated locations, the recorder's data entry is overwritten, and there
  is no file on disk to collide with. (A narrower version exists today
  when `log_start`'s flush itself fails.)
- **JSON recorder**: gating lives in `TaskLogger`, so `.json` logs get the
  same deferral; `JSONRecorder.log_config_update` never eager-flushes.
- **In-process retry / `eval-retry`**: both go through `task_run` with a
  `sample_source`, so the same hold applies. The in-process retry builds
  its source from `options.logger.location` *before* `reinit()` repoints
  the logger; normally the prior attempt's error log exists there
  (`log_finish` wrote it). It can be missing when the log write itself
  failed — `_run_task` converts a failed `log_finish` into a synthetic
  errored `EvalLog` that still gets retried — in which case the source
  finds no file and degrades to checkpoint-fallback/no-reuse, which
  `read_from_file` and the presence probe already handle via their
  `FileNotFoundError` paths (S3 needs the error-mapping fix above). Today
  that scenario usually leaves a start-only file; under the design a held
  attempt may leave none — same degradation, one step earlier.

## Testing

Unit tests (`tests/log/test_task_log.py`):

- Held `log_start` creates no destination file; after release the first
  flush produces a log containing `start.json`.
- `_flush_pending_samples` returns 0 and drains nothing while held
  (pending lists and buffer-db rows intact); `flush_samples()` (ctl path)
  likewise returns 0 with no file created.
- Settle release: `reuse_sweep_settled` clears the hold and flushes even
  with an empty quiet list (destination created); with quiet samples
  pending, the created destination contains them.
- A config update recorded while held writes no destination; the update is
  present in the log after the settle flush.
- `reinit()` resets the hold.
- Fresh eval (no hold): destination exists immediately after `log_start`.
- `read_sample` disk fallback returns `None` (not an exception) when the
  destination doesn't exist.
- S3 missing-object reads surface as `FileNotFoundError` (moto-backed test
  of the `AsyncFilesystem` mapping), so the absent-log paths degrade the
  same way on S3 log dirs.

Eval-level test (nearest existing retry test file):

- Retry attempt with one reused + one blocked live sample: the destination
  file is absent until the sweep settles, and its first on-disk version
  already contains the reused sample.
- Crash simulation mirroring the issue's repro (subprocess killed via
  `os._exit` at the settle flush): the next eval_set run re-runs only the
  originally-failed sample, and the completed samples survive into the
  final log.
