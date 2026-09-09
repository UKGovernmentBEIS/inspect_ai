# Making every retry attempt's log complete: seeding the attempt from the prior log

Design for [meridianlabs-ai/inspect_ai#420](https://github.com/meridianlabs-ai/inspect_ai/issues/420)
(upstream [UKGovernmentBEIS/inspect_ai#5213](https://github.com/UKGovernmentBEIS/inspect_ai/issues/5213)).
Third design in this area. The two it replaces — the reuse-sweep
write-through and settle flush (#117, `design/retry-reused-sample-flush.md`)
and the destination-write hold for the hard-kill variant (#240 / upstream
#4933, `design/retry-deferred-destination-log.md`) — were removed from
`design/` when this landed; their mechanisms are gone from the code and the
problem history below covers what they addressed. Read them from git history
if the interim reasoning is needed.

This revision supersedes an earlier draft that proposed chaining the retry
sample source across a task's older logs. Review feedback (ransomr): log files
are self-contained today, and a retry that depends on more than one file
introduces a new cross-file concept with its own hazards. The constraint
adopted here is therefore:

> **Every log file stays self-contained, and the newest log for a task stays
> the whole truth about that task.** The fix must make a retry attempt's log
> complete no matter how the attempt ends — not teach readers to look past an
> incomplete one.

Chaining is retained below as one of the compared options, for the record.

## Problem

A retry attempt seeds itself from exactly one prior log. Every planned
`(id, epoch)` is looked up in that log by the reuse sweep in `run_sample`
(`_eval/task/run.py`): a clean completed sample is read from the prior log,
parsed, condensed, re-serialized and re-logged into the new attempt with
`write_through=True`; an errored one seeds `PreviousError` history; anything
else runs live. Live samples do not wait for the sweep, and the sweep's body
reads are bounded to 25 at a time, so on a large prior log on remote storage
the sweep can run for minutes while live samples are already executing.

If the attempt *errors* while the sweep is still running — a live sample fails
and `fail_on_error` tears the task down, a `TerminateTaskError` from
`inspect ctl`, a Ctrl-C, or the prior-log read itself raising a transport
error out of `read_from_file` — `task_run`'s terminal branches call
`finish_task_log`, which writes whatever the sweep had re-logged so far plus
the live results. That log is a legitimate error/cancelled record of the
attempt, and it is now the task's newest log. It is also missing every prior
completed sample the sweep never reached.

The next attempt then uses only that partial log:

- eval_set (`retry_immediate=False`) picks the newest log per task by mtime
  in `latest_completed_task_eval_logs` (`_eval/evalset.py`) and builds the
  source from it in `as_previous_tasks` → `resolve_previous_task`
  (`_eval/loader.py`).
- The in-process retry (`retry_immediate=True`, or `eval(retry_attempts=)`)
  builds the source directly from `options.logger.location` — the attempt
  that just errored — in `run_task_retry_attempts` (`_eval/run.py`), the
  loop that drives `_run_task` once per attempt.

Both paths re-run from scratch every sample that completed in the older log
but is absent from the newer one. In the production incident that was 34 of
47 samples (25 of them cost-capped). With the default `retry_cleanup=True`
the older log is deleted at the start of the next pass
(`list_latest_eval_logs(..., cleanup_older=retry_cleanup)` removes every
non-`started` log that isn't the newest), so the completed results are gone
before the retry even starts — duplicated spend becomes permanent loss.

### Why #4933 doesn't cover this

That fix enforces "no destination write until the reuse sweep settles", so a
hard kill mid-sweep leaves no file and the next retry naturally falls back to
the older log. `TaskLogger.log_finish` is deliberately exempt: it is the
attempt's own terminal record and must always land. The graceful-error path
therefore still produces a newest log with a partial reused set. The #240
design filed this as an accepted "bounded re-spend, no data loss" trade-off;
the incident shows the bound is the whole prior log and, with cleanup on, it
*is* data loss.

The `carry_forward_unlogged_samples` teardown step doesn't help either: it
re-logs only samples with prior *error* history (`PreviousError`), probing
`error_history_ids()` — never clean completed samples — and it was
deliberately narrowed to that set because probing every planned sample at
teardown stalled Ctrl-C shutdown of large remote retries for minutes.

### The root cause, restated

The prior log's completed samples are copied into the new attempt **lazily,
one sample at a time, interleaved with live work**, so there is always a
window in which the new attempt's log is a strict subset of the prior one.
Every option below either closes that window (copy everything up front, or
finish the copy before finalizing), or stops the subset log from becoming the
newest log (write nothing, or look past it).

## Facts the options build on

- **The recorder is a local temp zip, copied whole on every flush.**
  `ZipLogFile` (`log/_recorders/eval.py`) appends every entry to an anonymous
  local temp file opened with `ZipFile(mode="a")`; `flush()` copies the
  entire temp zip to the destination (atomic rename locally, streaming
  multipart upload on S3). There is no incremental/append write to the
  destination — a flush always rewrites the whole file. So anything the
  attempt's log is to contain must be in the temp zip; a server-side copy of
  the prior log to the destination alone cannot survive the first flush.
- **Duplicate member names already mean "supersede".** `_zip_writestr`
  deliberately appends a second member under the same name for a requeued
  sample's re-run (and for re-logging with `log_init(clean=False)`), and
  every reader resolves a name to its *last* entry: `_read_log`,
  `_read_log_from_bytes`, `_rewrite_eval_zip_with_new_header`,
  `_dedupe_summaries`, and `AsyncZipReader`'s `CentralDirectory.entry()`
  (`_by_name` is a dict comprehension over entries in order). Production
  logs already contain such duplicates, so this is an existing format
  contract, not a new one.
- **A zip's central directory can drop entries cheaply.**
  `_replace_eval_header_in_place` removes `header.json` from
  `ZipFile.filelist`/`NameToInfo` before appending a fresh one; the old
  bytes become unreferenced ("dead bytes") but the file stays valid. This
  is the accepted local-edit idiom for `.eval` files.
- **Raw member bytes are readable without decompression.**
  `AsyncZipReader.open_member_raw` streams a member's compressed bytes.
  Python's `zipfile` has no public API to *write* pre-compressed bytes, so a
  raw entry copy needs either a small hand-rolled local-header writer or a
  decompress+recompress round trip (`_rewrite_eval_zip_with_new_header`
  already does the latter for remote header-only writes).
- **Whole-file reads are the fast path for remote logs.**
  `EvalRecorder.read_log` downloads a remote `.eval` to a temp file before
  reading it, precisely "to eliminate the possibility of hundreds of small
  fetches from the zip file streams". The reuse sweep today is exactly that
  hundreds-of-small-fetches pattern, plus a JSON parse, condense, re-serialize
  and recompress per sample.
- **The #4933 hold existed when this was designed.**
  `TaskLogger.hold_destination_writes()` deferred every destination write
  until `reuse_sweep_settled()`, with `log_finish` the only exempt write.
  The implementation removed the hold, the reuse-sweep countdown and the
  settle flush: seeding before `log_start` makes the invariant they enforced
  hold by construction. `write_through` on `Recorder.log_sample` survives as
  the path the seed's cross-format and in-memory fallback uses, and
  `ZipLogFile.destination_written` still gates the eager config-update flush
  so a retune before `log_start`'s flush cannot create an empty newest log.

## Goal

> **A retry never re-runs a sample that a prior attempt of the same task
> completed cleanly, regardless of how the intervening attempt ended — and
> every log file remains self-contained.**

Non-goals: changing how eval_set selects the retry source (newest log per
task), changing `retry_cleanup` semantics, or changing the per-attempt log
identity (one log file with its own `eval_id` per attempt).

## Options

### A. Seed the attempt's temp zip from the prior log's bytes (recommended)

Before the attempt does any work, copy the prior `.eval` **as a file** into
the new attempt's `ZipLogFile._temp_file` — one streamed download for S3/GCS,
one local file copy otherwise — and open it in append mode. The attempt then
starts with every prior sample entry already in its log, byte for byte, with
zero per-sample reads, no JSON parsing, no condense, no recompression. Its
own work appends on top:

- Samples that need re-running (errored, invalidated, absent, or planned
  keys with no prior entry) run live and append a superseding entry under
  the same member name — the existing duplicate-name contract.
- `_journal/start.json` for the new attempt is appended (supersedes the
  prior's); `header.json`, `summaries.json`, `reductions.json` are written
  at `log_finish` as today.
- The reuse "sweep" collapses to bookkeeping plus one **local** body read
  per key: for each planned key, consult the seeded summaries (already in
  memory — `log_init` reads the prior summaries today for `clean=False`) to
  decide clean / errored / absent, then read the body from the local seeded
  zip — never from the remote prior log — to feed the reporter (clean), seed
  `PreviousError` (errored), or serve scanner resume and a dynamic
  `SampleSource` feed's `sample_complete`. The summaries alone cannot feed
  the reporter: `EvalSampleSummary.thin_data` is an after-validator, so every
  persisted summary row has `Score.answer`/`explanation`/`reason` shortened
  to ~1k characters and `Score.metadata` plus the sample `metadata` run
  through `thin_metadata` (long values replaced with a placeholder string).
  Building `SampleScore` from that would change `grouped()` group assignment
  for metadata keys that get thinned, hand custom metrics placeholder
  `Score.metadata`, and persist truncated fields into `reductions.json` for
  reused samples — differing from their own bodies in the same file. The
  local read costs a decompress plus `model_validate`; the remote range
  read, condense, re-serialize and recompress that dominate today's sweep
  are gone.
- **Invalidation is decided from the body.** `EvalSampleSummary` has no
  invalidation field: `invalidate_samples` (`log/_edit.py`) sets
  `EvalSample.invalidation` on the body and `EvalLog.invalidated` on the
  header, and `EvalSample.summary()` emits neither. So the summaries alone
  cannot tell an invalidated sample from a clean one. Since every planned
  key's body is read from the local seeded zip anyway (the reporter needs
  the full-size scores), the sweep applies the same body-level test
  `run_sample` applies today — `error is None and invalidation is None` —
  to the local copy; no header read or separate invalidation scan is
  needed. (An earlier revision of this design gated a body scan on the
  prior header's `invalidated` flag; that was only worthwhile while clean
  samples were meant to skip the body read.)

At seed time a few entries are pruned from the central directory (dead bytes,
not rewritten): the prior `header.json`, `summaries.json`, `reductions.json`
and `_journal/config_updates/*` (otherwise an in-progress read of the new log
would return the prior attempt's finished header and eval_id — readers prefer
`header.json` when present), and sample entries for keys outside this
attempt's plan (a `sample_id`/`limit` subset or reduced epoch count; a
dynamic-feed task has no upfront plan and keeps everything, pruning the
records it never consults at a natural success instead — see trade-off 5).
The prior's
journal summary files (`_journal/summaries/N.json`) are pruned too and
replaced by a single fresh journal member holding the kept summaries.
Member-level pruning cannot do this for them: a flush batches every sample
it carries into one journal file, so a pruned key's row would otherwise
survive in a batch alongside kept keys, and until `summaries.json` lands at
finish every in-progress reader takes the journal path of
`_read_all_summaries_async` (the viewer sample list,
`read_eval_log_sample_summaries`, the ctl summaries surface) and would list
samples whose bodies are gone — a body read for one raises `IndexError`.
Rewriting the journal is local CPU over small records.

Two sub-variants:

- **A1 — sequential (recommended first).** `task_run` awaits the seed
  before `log_start`. The hold from #4933 and the settle flush from #117
  become unnecessary: `log_start`'s immediate flush uploads the seeded zip,
  so the destination exists from the first seconds of the attempt *and*
  already holds the complete prior set. Live samples start after the seed
  lands. Startup latency = one whole-file download; see Trade-offs for why
  that is not slower than today's sweep, just front-loaded.
- **A2 — concurrent.** Live samples start immediately while the seed
  streams in; the existing hold defers destination writes until the seed
  lands, and temp-zip writes (streaming completions, write-throughs) await a
  `seeded` event. Preserves today's "live samples don't wait", but reopens
  a hard case: if the seed *fails* after live samples have completed, the
  attempt must either drop those live results and write nothing, or write a
  partial log — the very state this design exists to prevent. A1 has no
  such case because nothing runs before the seed lands. A2 is a follow-up
  only if A1's startup latency proves to be a problem in practice.

What A removes: the `write_through` re-log path in `run_sample`, the
`_ReuseSweepCountdown` settle flush, the destination-write hold (A1), the
`carry_forward_unlogged_samples` teardown step (errored prior records are
already in the seeded zip), and the remote per-sample read machinery
(`AsyncZipReader` sharing, the 25-way read throttle, the presence probe and
its failure cap). The `EvalSampleSource` abstraction stays for the
eligibility decision and for in-memory sources, but its file-backed path reads
the local seeded zip.

What A adds: a `Recorder.log_seed(eval, prior, keep)` hook whose base
implementation re-logs the kept samples of a prior log (a location or
in-memory samples) through `log_sample(write_through=True)` — the path an
in-memory prior log, a prior in a different format (`eval_retry(...,
log_format=...)` allows a `.eval` prior to be retried into a `.json` attempt
and vice versa, and a byte copy is only valid same-format) and the `.json`
recorder (whole-log-in-memory anyway) all take — and which `EvalRecorder`
overrides for a `.eval` prior with `ZipLogFile.seed_from_prior_log` (copy
the prior file into a fresh temp zip, open in append mode, prune, rewrite
the summaries journal); a `seed` field on `EvalSampleSource` that carries
the prior location (or samples) once the eligibility checks pass so
`task_run` can seed the log before `log_start`; and a **compaction** step at
a successful `log_finish` that rewrites the temp zip without dead bytes (see
below).

**Dead bytes and compaction.** Each attempt's seeded zip carries the prior
attempt's superseded metadata entries plus, once re-run samples complete,
their prior records. Over `k` attempts the final log accumulates `k` stale
copies of the re-run samples' transcripts — bounded (re-run samples are the
errored ones) but real. Compaction at a *successful* finish — the log's last
write — drops every unreferenced member before the final flush. It is local
CPU only (the temp zip is a local file): either a raw member copy if it can be
done against documented `zipfile` surface, or the decompress+recompress
rewrite that `_rewrite_eval_zip_with_new_header` already uses, run in a
worker thread. Non-success finishes skip compaction (their logs are
short-lived retry seeds and `retry_cleanup` removes them), so the cost is
paid once per task. A size heuristic (compact only when dead bytes exceed some
fraction of the file) keeps it a no-op for a fresh eval.

### B. Eager entry-level copy (pre-pass) with raw member copy

Same "copy first, then work" shape as A, but copy only the planned sample
entries from the prior log, raw (compressed) bytes via `open_member_raw`
straight into the temp zip, before `log_start`. Skips unplanned entries and
the prior's metadata, so there are no dead bytes and no pruning. Costs one
range request per entry (as today) but no parse/serialize/recompress, and
needs a raw *write* into the temp zip, which `zipfile` doesn't expose — a
hand-rolled local-header writer over `zipfile` internals (`fp`, `start_dir`,
`filelist`), or a decompress+recompress round trip that gives back most of
the CPU saving. For a prior log whose sample entries are contiguous (they
always are — an attempt writes them in order), the union of those ranges *is*
the file, so B's N range reads fetch the same bytes as A's single download
with more requests and more code. B is A with pruning done at copy time
instead of at compaction time; not worth the separate machinery.

### C. Filesystem-level copy of the prior log to the new destination

Copy the prior log to the attempt's destination path at attempt start (S3
`CopyObject` is server-side and fast; local reflink/copy), then run the lazy
sweep as today. The destination immediately holds the complete prior set.
Two problems make this not fit the recorder:

- The very first flush overwrites the destination with the temp zip, which
  holds only what the sweep has reached — the copy is undone. Keeping it
  would require holding *every* write including `log_finish` until the
  sweep settles, and on an unsettled finish merging the temp zip into the
  copy — download, append, upload — which is A with extra steps.
- The copied file carries the prior attempt's `header.json` (its `eval_id`,
  status, results) under a new filename. Until rewritten it reads as a
  finished duplicate of the prior attempt: eval_set groups it into the same
  task, the control channel's summaries memo and `EvalState` registry are
  keyed by `eval_id`, and the viewer lists two identical finished logs.
  Rewriting the header on S3 (`_write_log_s3(header_only=True)`) downloads
  the whole body anyway.

A server-side copy only saves the download if the bytes are never needed
locally, and the recorder's flush model needs them. Rejected.

### D. Complete the sweep at teardown (the issue's first suggestion), made efficient

Keep the lazy sweep; at a non-success finish with an unsettled sweep, copy
the planned prior entries the sweep never reached into the temp zip before
`log_finish` writes. Done as a *whole-file download plus raw copy of the
missing names* it is a single request rather than the per-sample probing that
stalled Ctrl-C before, and only names absent from the temp zip are copied, so
no attempt-written entry is superseded. Still rejected as the primary
mechanism: (a) the work runs inside teardown, under the Ctrl-C cancellation
shield, at the worst possible moment — a slow or hung storage backend turns
"the attempt errored" into "shutdown hangs for the length of a download";
(b) when the trigger is the prior-log read failing, the copy fails for the
same reason and the partial log is written anyway. A pays the same download
up front, where a failure is cheap (nothing has run yet) and a slow download
delays a start rather than a shutdown.

### E. Don't finalize a partial attempt (write nothing when the sweep hasn't settled)

Extend the #4933 hold to `log_finish`: if the attempt ends before its sweep
settled, discard the temp zip and write no destination file, mirroring the
hard-kill shape. The next retry then sees the older, complete log. Requires
one more change: the in-process retry branch in `run_task_retry_attempts`
must not build its source from a location with no file (today that degrades
to no reuse), but reuse `options.sample_source` — the same source the failed
attempt ran with.
A sub-variant (E2) writes the log after all if it holds live clean
completions the older log lacks, discarding only when there is nothing to
lose.

Cheapest option that fully fixes the reported bug, and every log it does
write is complete. Costs: the errored attempt leaves no log (its error is in
the console and trace only — a post-mortem regression for exactly the
attempts operators most want to inspect); live results and `error_retries`
increments accrued during the sweep window are lost (E2 narrows this to
the increments); and it leaves the slow per-sample sweep in place. Worth
keeping in view as the **minimal interim fix** if A is judged too large for
one PR; A makes it unnecessary.

### F. One log per task across attempts (append into the prior log in place)

Have the retry attempt reopen the prior attempt's *own* log — same path, same
`eval_id`, same `created` — via `log_init(clean=False)`, and write into it.
This is how `score --overwrite` re-logs into an existing file. There is only
ever one log per task, so newest-by-mtime selection and `retry_cleanup` have
nothing to choose between. On a remote filesystem it still needs the whole
prior log in the temp zip (the flush model above), so its cost is A's; what
it adds is a contract change: attempts stop being distinct logs (the viewer,
`inspect log list`, bundles, `EvalState` retry-pending marks and
`eval_set_id`/`run_id` bookkeeping all assume one `eval_id` per attempt), the
attempt's own error record replaces the prior's instead of standing beside
it, and `--no-retry-cleanup` (keep failed attempts for inspection) loses its
meaning. Too broad for this bug. Noted because A makes F a small step later
if one log per task is ever wanted.

### G. Chain the retry sample source across the task's logs (previous draft)

Give `eval_log_sample_source` a `fallback`; eval_set hands every same-task log
(mtime-ordered) to the retry; a key absent from the newest log falls through
to older ones; `retry_cleanup` deletes an older log only once the newest holds
every key it does. Heals every shape including ones not yet anticipated, and
uses the partial attempt's live results. Deferred per review: it makes a
retry depend on a *set* of files with a precedence rule (newest record wins,
absence falls through) that every future consumer of the retry source has to
know about; it changes `retry_cleanup` from "one log per task after a pass" to
"until superseded", visible to bundles, viewer listings and scripts; it adds
summaries reads to pass start; and it grows `PreviousTask`. All of that is
machinery to *tolerate* an incomplete newest log, where A stops the
incomplete log from existing.

### H. Complementary: harden the two triggers

Independent of the mechanism chosen:

- **Delay task teardown until the sweep settles.** When a live sample's
  error trips `fail_on_error` while the seed reuse sweep is still running,
  let the sweep finish (it is bounded and already in flight) before the task
  group is cancelled. Removes the incident's trigger for the common case but
  not Ctrl-C, `ctl` terminate or read failures. Under A the sweep is
  summary bookkeeping plus local body reads with no remote I/O, so it
  settles in seconds rather than minutes, and even an unsettled teardown
  writes a complete log because the seeded zip already holds every prior
  record. This falls out for free.
- **Prior-log read failures should not produce a partial log.** Today a
  transport error escaping `read_from_file` fails the whole attempt with
  whatever was copied so far. Under A there is one read (the seed) and it
  happens before anything is written, so a failure leaves no file; add a
  bounded retry with backoff around the download so a storage blip doesn't
  burn a retry attempt.

## Comparison

| | Logs self-contained | Fixes all teardown shapes | Startup cost | Teardown cost | Prior-log reads | Contract changes | Machinery |
|---|---|---|---|---|---|---|---|
| **A1 seed (sequential)** | yes | yes, by construction | one whole-file download before live start | none (compaction on success only) | 1 | none (dead-bytes idiom already used) | **removes** hold, settle flush, carry-forward, read throttle, probe |
| A2 seed (concurrent) | yes | yes, except seed-failure-after-live-work (must discard) | none (overlapped) | awaits seed | 1 | none | keeps hold; adds seeded-event gating |
| B raw entry copy | yes | yes | N range reads before live start | none | N | none | adds raw zip writer |
| C server-side copy | yes | no (first flush undoes it) | fast copy | merge on unsettled finish | N + full download | `eval_id` duplication until header rewrite | adds merge path |
| D complete at teardown | yes | no (read failure → partial) | none | whole-file download under Ctrl-C shield | N + 1 | none | keeps everything, adds teardown copy |
| E write nothing if unsettled | yes | yes (by omission) | none | none | N | attempt leaves no log; lost live results | small; `run_task_retry_attempts` source reuse |
| F one log per task | yes | yes | A's | none | 1 | attempt identity, cleanup, viewer, registry | A's + identity plumbing |
| G chain sources | **no** | yes | summaries reads per multi-log task | none | N per link | cleanup rule, `PreviousTask`, retry precedence | adds fallback chain |

## Recommendation

**A1, plus the `run_task_retry_attempts` source-reuse change from E for the
seed-failure path, plus H's download retry.** It is the only option that both satisfies
the self-contained-logs constraint and makes the invariant structural rather
than a race: after the seed, the attempt's log is a superset of the prior
log at every instant, so *any* finish — error, cancel, terminate, Ctrl-C,
success — writes a complete log, and any hard kill leaves either no file or a
complete one. It replaces hundreds of small remote reads with one streamed
download, drops the per-sample parse/condense/serialize/compress work
entirely, and lets three pieces of retry-specific machinery (hold, settle
flush, carry-forward) be deleted rather than extended.

## Mechanism (A1)

### `ZipLogFile.seed_from_prior_log(prior_log, keep)`

```
async def seed_from_prior_log(
    self, prior_log: str, keep: set[tuple[int | str, int]] | None
) -> None
```

Reached through `Recorder.log_seed(eval, prior, keep)`, which
`EvalRecorder` overrides for a `.eval` prior location and otherwise defers
to the base re-log. The parameter is `prior_log`, not `seed_from`, because
`ZipLogFile` already has a "seeded" notion:
`_destination_seeded` records that `init()` was opened over an *existing
destination* (`score --overwrite` re-logging into a file), and `discard()`
uses it to decide whether the destination is ours to remove. A prior-log
seed is the opposite shape — a fresh destination whose temp zip starts from
another file — and `discard()` must still remove that destination. Keeping
the names distinct keeps the two rules from being confused there.

The seed runs *after* `init()`, from `task_run` (see below), because that
is where a seed failure has the right blast radius: it is an attempt
failure — no log written, the retry keeps its source — rather than a
failure of `TaskLogger.init`, which runs in the dispatcher (up front for
every task in `eval_run`, or inside `run_one` for an in-process retry) and
would take the whole run down. It also means a run with many queued tasks
does not download every prior log at startup. `init()` has already opened
an append-mode `ZipFile` over the empty temp file, and **the copy must not
land under such a handle**: `ZipFile(mode="a")` over an empty file sets
`_didModify = True` and `start_dir = 0`, so its `close()` seeks to offset 0
and writes an end-of-central-directory record over the first bytes of
whatever is there — and dropping the handle without `close()` does not
avoid this, `ZipFile.__del__` calls `close()`. The seed therefore copies
into a *fresh* temp file, and only once the copy is complete and validated
closes the original handle *explicitly* (its end record lands in the old,
still-empty file), swaps the temp file, and opens a new handle over the
copy; nothing can write over the copied bytes. Any
`_journal/config_updates/*` members `init()` had written (inherited
process-scoped retunes) stay in the old file and are re-journaled into the
new one. Steps 1 and 2 run *outside* `_lock` — a multi-GB download must not
stall the recorder's other lock users (a control-channel summaries poll, a
config update) — and the swap onward under it:

1. **Copy bytes** into a fresh anonymous `tempfile.TemporaryFile()`. Being
   unlinked, it has no path `AsyncFilesystem.get_file(remote, local_path)`
   could target; the seed instead pumps the bytes into the open file object
   via `AsyncFilesystem.read_file_into` (a local file copies in a worker
   thread). For S3 that is
   `AsyncFilesystem.read_file_bytes(prior_log, 0, None)` — a
   `ByteReceiveStream`: the body stream on asyncio (constant memory, never
   blocks the loop), the whole object read in a worker thread under trio
   (`to_thread` over `s3_read_file_bytes`; loop free, memory not bounded).
   Every other remote backend (GCS/Azure) has no async client and cannot
   be read in a worker thread either (the fsspec rule in AGENTS.md), so it
   is read synchronously *on the event loop*, one `_SEED_COPY_CHUNK_SIZE`
   chunk at a time with an `anyio.lowlevel.checkpoint()` between chunks:
   each stall is bounded by one chunk's fetch rather than the whole
   download (which is what `read_file_bytes` would do for those backends,
   and what `read_log`'s `fs.get_file` download does today —
   meridianlabs-ai/inspect_ai#460 moves it onto the same helper). Transient
   failures are
   retried with the same `tenacity.AsyncRetrying` idiom the S3 put retry
   uses (`SEED_COPY_ATTEMPTS`, jittered exponential backoff); a missing
   prior raises `FileNotFoundError` at once. A failure closes the fresh
   file and re-raises; the live log is untouched (see Failure analysis).
2. **Validate and read the summaries** in a worker thread by opening the
   copy in *read* mode: unlike append mode, which treats anything that is
   not a zip as an empty archive to append to (a corrupt or truncated copy
   would silently seed nothing), `ZipFile(mode="r")` raises `BadZipFile`.
   `AsyncZipReader` reads by path through `AsyncFilesystem` and so, like
   `get_file` in step 1, cannot target the anonymous file; reading the
   summaries from the prior log's remote location instead would spend range
   reads on bytes that are already local. The summaries readers are
   async-only (`_read_all_summaries_async`, `_read_summary_counter`), so a
   small sync counterpart over `ZipFile`, `_read_all_summaries(zip)`, is
   added with the same contract: `summaries.json` if present, else the
   journal members in index order (via the shared `_sorted_journal_entries`
   the config-update journal reader also uses), then `_dedupe_summaries`.
   The result is filtered to `keep` by generated member name (every summary
   when `keep` is `None`); these are the **kept summaries** the following
   steps work from.
3. **Swap and open in append mode**: close the handle `init()` opened,
   replace `_temp_file` with the copy, `_open()` — which parses the copied
   central directory into `filelist`/`NameToInfo`; over a *valid* zip,
   append mode leaves `_didModify = False` and permits reads.
4. **Prune** from `filelist`/`NameToInfo`: `header.json`, `summaries.json`,
   `reductions.json`, `_journal/start.json`, `_journal/config_updates/*`,
   every `_journal/summaries/*`, and every `samples/*` member whose name is
   not in `{_sample_filename(s.id, s.epoch) for s in kept summaries}`.
   Names are generated and compared, never parsed: `_sample_filename`
   interpolates the id as a plain string, so `samples/1_epoch_1.json` does
   not say whether the id was `1` or `"1"`, and a string id containing
   `_epoch_` cannot be split back. A body member with no summary row is
   pruned too — `lookup` could not classify it. Dead bytes only; no
   rewrite. (The prior's `start.json` is pruned rather than left to be
   superseded so no stale eval_id member lingers; the new attempt's
   `start()` writes its own.)
5. **Rewrite the summaries journal**: set `_summaries` to the kept
   summaries, `_summary_counter = 1`, and append them as
   `_journal/summaries/1.json`. `_read_summary_counter` takes the maximum
   index present, so pruning the prior journal and starting at 1 is
   consistent for every reader. That one member holds the whole kept list
   (tens of MB of JSON for a prior with tens of thousands of samples), so
   it is serialized and deflated in a worker thread with `_lock` held, as
   `buffered_sample` reads and `compact` rewrites are, rather than
   stalling the loop for the other tasks in the process. Nothing goes into
   `_samples` or `_streaming_samples`. Then re-journal the config updates
   recorded before the seed.
6. Register the kept member names in `_local_sample_names` (the set
   `buffered_sample` serves from the local zip) and the pruned members'
   compressed size in `_pruned_bytes` for the compaction heuristic.

`buffered_sample(id, epoch)` gains a tier between `_samples` and
`_streaming_samples`: a member registered in `_local_sample_names` (a
seeded record, or a write-through re-log) is read from the local zip with
`self._zip.read(name)` (reading is permitted in append mode), which
resolves to the freshest member under that name — a re-run's superseding
record wins, as for every zip reader. That is a synchronous decompress of a
whole sample body, so it runs in `anyio.to_thread.run_sync` — the temp file
is local, so the fsspec rule does not apply — while `_lock` is held, exactly
as a flush holds it. The event loop stays free; concurrent sample writes
wait on the lock for the read's duration, which is the same contention a
flush imposes today. Parsing, validation and the read-time resolution every
log read applies (`resolve_sample_events_data`, `rebind_sample_timelines`)
run in a worker thread after the lock is released, so a sample served from
the recorder's local copy and one read from the destination look alike.
`TaskLogger.read_sample`'s disk fallback therefore never needs the
destination for a seeded sample; when the control channel asks it to
exclude fields it drops them from the whole record rather than parsing
selectively as the disk read does. Live samples' flushed members stay on
the disk path (its `exclude_fields` streaming serves the control channel's
event-page reads). The write-through path no longer retains an event-less
copy in `_streaming_samples`: the local-zip tier is consulted before it and
always has the member.

**Cross-format and in-memory seeds.** `eval_retry(..., log_format=...)` can
name a format that differs from the prior log's, so `EvalRecorder.log_seed`
copies bytes only when the prior is a `.eval` location and otherwise defers
to the base `Recorder.log_seed`, which `JSONRecorder` inherits outright: it
reads the prior (`read_eval_log_async`, or the in-memory samples of an
`EvalLog` source — `eval_retry` on a loaded log, `log_info=None`) and
writes each kept sample through `log_sample(write_through=True)` before
`log_start`, today's write-through done sequentially up front, keeping
images as the prior recorded them so both paths agree.
`JSONRecorder.log_sample` supersedes an existing record for the same
`(id, epoch)` (rather than appending a duplicate; an index of logged keys
keeps the common append O(1)) so a seeded errored record is replaced by
its re-run, matching the `.eval` readers' rule. Rejecting a format mismatch
instead would break a retry that works today, so the fallback is the only
acceptable behaviour; it is slower than the byte copy but no slower than
today's sweep.

### `task_run` seeds the log before `log_start`

`EvalSampleSource` is a `NamedTuple` of callables, so nothing downstream can
tell from `options.sample_source` whether the source is file-backed, whether
it passed eligibility, or where the prior log lives. `eval_log_sample_source`
therefore sets a `seed: SeedSource | None` field, where `SeedSource` is a
small `NamedTuple` of `source: str | list[EvalSample]` (the prior log file,
or an in-memory prior log's samples) and `classify`, the resolver described
under the sweep below. It is set only *after* the shuffle-without-ids and
dataset-size checks pass (the branches that warn and return the no-reuse
source leave it `None`), so eligibility is decided once, where it is
decided today. `error_history_ids` and `prior_exists` are gone from the
tuple: the carry-forward and the presence probe they served are deleted.

`task_run` calls `logger.seed_from_prior(seed.source, keep)` when the
source carries a seed and sample logging is on (with `log_samples=False`
nothing is seeded, as nothing is re-logged today, and the sweep falls back
to `lookup`), after the retry-abandoned check and before anything that
needs unwinding — the paged sample store, the display row, `log_start` — so
a seed failure escapes with nothing to clean up and no destination written.
The abandoned check is repeated right after the seed: the copy can run for
minutes on a large remote prior, and an abandon landing during it would
otherwise be honoured only by the pre-`register_eval` backstop, after the
checkpoint copy and the `log_start` flush had uploaded the whole seeded log
for the dispatcher's discard to remove. Either path ends in that discard,
which closes the seeded temp file.
`keep` is the plan `task_run` has just sliced (`sample_ids × range(1,
epochs+1)`; `None` for a dynamic-feed task). `TaskLogger.seed_from_prior`
asks the recorder to `log_seed` and sets `prior_seeded`; a prior log that
no longer exists (`FileNotFoundError`) leaves the attempt unseeded with a
warning rather than failing it — the sweep's own `lookup` degrades the same
way for a missing log, and failing would burn every remaining retry on the
same absent source. Seeded records are *not* counted as this attempt's
resolutions at seed time: `samples_logged` (the count a graceful drain or
cancel stamps as `results.logged_samples`) and `samples_completed` count a
reused record when the sweep accepts it (`note_reused_sample`) and a re-run
when it completes. Counting seeded keys up front would let a drain that
abandoned a seeded errored sample's re-run read complete, so a later
eval-set pass would never re-run it — its only record being the prior
attempt's error. `hold_destination_writes()` no longer exists; `log_start`
flushes immediately as a fresh eval does, and that first flush carries the
complete prior set.

### The reuse sweep becomes bookkeeping

`run_sample`'s `sample_source` branch, when `logger.prior_seeded`:

- `logger.read_prior_sample(id, epoch)` reads the key's record from this
  attempt's own log (the `buffered_sample` tier above; an absent key costs
  no remote read) — bounded to a few concurrent reads, since every planned
  sample's `run_sample` starts at once and the recorder serializes the reads
  on its lock, behind which a control-channel listing or a live completion
  would otherwise queue for the whole sweep — and `seed.classify(id, epoch,
  sample)` resolves it with the same rule `lookup` applies to a record read
  from the prior source:
  clean (`error is None and invalidation is None`) → the sample; errored →
  `PreviousError` (seeded from the body's `error_retries`; the summary's
  `retries` count is not enough); invalidated/absent → checkpoint resume or
  fresh run, as today. For a clean sample the reporter is fed
  `SampleScore(score=..., sample_metadata=sample.metadata)` from the full
  body, exactly as today (the summary's scores and metadata are thinned at
  validation, see Options A), and `logger.note_reused_sample` does the
  bookkeeping `complete_sample` used to — nothing is re-logged or written
  through. The re-run's completion appends a superseding member.
- When the log was not seeded (sample logging off, a missing prior, or no
  eligible prior) the branch is today's: `lookup` against the prior source,
  and a clean sample is re-logged with `complete_sample(flush=True)` when
  sample logging is on — counted toward the flush threshold like a live
  completion, since the quiet list and settle flush that used to drain
  `flush=False` re-logs are gone.
- The read throttle, the presence probe, `_ReuseSweepCountdown`, the settle
  flush, the quiet pending list and `carry_forward_unlogged_samples` (with
  its `_finish_task_log` call) are deleted: no remote body read happens in
  the sweep, nothing is written through during it, and an unreached errored
  key's prior record is already in the seeded zip, which is exactly what
  carry-forward re-logged. The one remaining per-sample remote step in the
  sweep is the checkpoint resume probe (and the delete for a fresh run) that
  every non-clean prior takes against this attempt's checkpoint dir, bounded
  by `checkpoint_probe_limit` (`CHECKPOINT_PROBE_CONCURRENCY`); on a remote
  checkpoint store it sets the length of the window before a re-run is
  queued.

### The control channel's samples listing

`current_sample_summaries` merges the recorder's summaries with
`active_samples`, letting a terminal record supersede a running row (the
sample finished between the two reads) and synthesizing `pending` rows for
planned keys with no record. A seeded log would break both: the recorder
now holds the prior attempt's errored (or cancelled) record for a key whose
re-run is live or still queued, so without a guard the stale record hides
the running row (`inspect ctl sample list` shows `error` with no `retries`)
or renders a sample merely waiting its turn as `error` — counted in the
histogram and listed by `inspect ctl sample errors` triage — where before
seeding it read `pending`.

The fix is at the source rather than in the merge. `TaskLogger` records
every seeded key at seed time and drops a key when the sweep accepts its
clean record (`note_reused_sample`) or a completion for it lands
(`complete_sample`, the re-run superseding the prior record); `log_finish`
and `reinit` clear the set. `TaskLogger.sample_summaries` — the live
source `register_eval` hands the control channel — withholds summaries
whose key is still in that set, so an unresolved seeded record is simply
absent: its sample reads `running` from `active_samples` or `pending` from
the plan, exactly as before seeding. No timestamp comparison is involved
(the seeded stamps were written by another process, possibly on another
machine's clock). A clean seeded record surfaces the moment the sweep
accepts it; an invalidated one — clean to the summary, re-run by the
sweep — stays withheld until its re-run completes; and once the eval
finishes the live source is gone and the listing reads the on-disk log,
where a seeded error whose re-run a drain abandoned is the sample's final
record. `TaskLogger.read_sample` — the whole-sample read behind
`sample_error_detail`, `ctl sample requeue` and `ctl sample cancel` —
withholds the same keys, so a sample awaiting its re-run resolves as
"planned, not yet at the queue" (a 409 for requeue and cancel, see
`design/ctl/queued-sample-cancel.md`) rather than as a terminal record
that requeue would run a second time and cancel would report as already
finished.

Dynamically fed tasks seed with no plan (`keep=None`); a seeded key the
feed never re-injects is never resolved, so it stays out of the live
listing until the eval finishes. At a natural success — the attempt
realized its whole plan, nothing abandoned — `TaskLogger.log_finish`
(`prune_unplanned`) hands the still-pending keys to `Recorder.log_prune`,
which drops their members and summaries before the finish is written: the
success log describes this attempt's plan, not the prior's. A graceful
resolution (score/error/drain) abandoned queued samples whose seeded records
the next pass reuses, and a non-success log is the next attempt's seed, so
neither prunes (see trade-off 5).

### Compaction at successful finish

In `EvalRecorder.log_finish` when `status == "success"` and dead bytes
exceed `COMPACT_DEAD_BYTES_FRACTION` (10%) of the member area: rewrite the
temp zip keeping only the referenced members — referenced per the writer's
in-memory central directory, since `ZipFile.close` rewrites the on-disk one
only after a write and a finish-time prune with nothing buffered behind it
would otherwise be undone by the copy — in a worker thread (local
file, CPU-bound), using the decompress+recompress loop from
`_rewrite_eval_zip_with_new_header` (`zipfile` has no documented raw-copy
surface). Then write `summaries.json`/`reductions.json`/`header.json` and
flush as today. A fresh eval has no dead bytes and skips this; a retry that
re-ran only a few small samples tolerates their stale copies rather than
paying a full rewrite for them.

Dead bytes are *measured*, not tracked: the member area (offset 0 to the
`ZipFile`'s `start_dir`, where the central directory is written at close)
minus the live members' local headers and compressed data. Tracking only
what this attempt pruned and superseded would miss what the prior log
carried: an errored attempt never compacts, so its own pruned and
superseded bytes ride along in every later attempt's byte copy, unreferenced
by the copied central directory. A multi-attempt chain would then
under-trigger compaction at the final success. The local header is
reconstructed as `FileHeader(zip64=True)`, exact for the streamed members
(`force_zip64`) and 20 bytes over for `writestr` members, so the measure
errs toward *not* compacting.

### `run_task_retry_attempts`: the retry's source is the newest record on disk

The retry branch decides without I/O (a filesystem probe would block the
dispatcher's loop on a remote log dir and could itself fail transiently),
from two flags the logger already tracks: `TaskLogger.finished` (the
attempt's `log_finish` completed) and `TaskLogger.destination_written`
(some flush reached the destination, `log_start`'s at least).

- **Finished**: the retry's source is the attempt's log, as today.
- **Unfinished, destination written** (a later flush or `log_finish`
  failed): the destination holds the complete prior set (the seed landed
  with `log_start`'s flush) plus every live completion a later flush
  carried, under a `started` header. It is a superset of every earlier log,
  so it is the retry's source too — the same `eval_log_sample_source` over
  the attempt's location, checkpoint dir included, so the flushed samples'
  checkpointed progress resumes as well. `TaskLogger.reinit` releases what
  the attempt left open (the recorder entry with its temp zip, the buffer
  db) and leaves the destination in place.
- **Unfinished, nothing written** (the seed or `log_start`'s flush failed):
  no file. The retry keeps `options.sample_source`, the same prior. Today
  that case degrades to no reuse; this is the E change, and A needs it for
  the seed-failure path (the seed raises inside `task_run`, which
  `_run_task` already converts into an errored `EvalLog` without a file,
  the same path a failed `log_start` flush takes). eval_set with
  `retry_immediate=False` needs nothing: no file means the next pass
  selects the older log.

Sample progress outranks header information, which is why a written
`started` destination is kept and used rather than discarded. It lacks only
what `log_finish` writes — status, the task-level error, stats, results —
and `started` is the accurate status for an attempt that was still running
when its write failed. The retry-cleanup sweep never deletes `started`
logs, so should every later attempt also fail to write, this file stands as
the task's newest log: an interrupted log carrying every sample the task
has completed, which the next eval_set pass seeds from. An earlier draft
discarded it (as `TaskLogger.discard` does for an abandoned attempt's
destination) and fell back to the prior source, keeping the log dir tidier
at the cost of re-running the attempt's flushed completions; that trades
the wrong way (trade-off 6). Finalizing the header instead would be another
write to storage that has just failed. The abandoned-attempt discard is a
different case: that destination holds the prior set and nothing new, so
the finished prior log it was copied from is the better record and the
`started` copy is removed.

### Seed download retry (H)

Wrap the download in a bounded retry with backoff (three attempts, say)
before raising. A persistent failure fails the attempt without a log; the
warning names the prior log and the error.

## Failure analysis

- **Graceful error / cancel / terminate / Ctrl-C at any point after the
  seed** (the issue): the temp zip holds every prior entry plus this
  attempt's completions; `log_finish` writes a complete error/cancelled log.
  The next attempt seeds from it and re-runs only what still needs running.
  Both `retry_immediate` values, and `eval(retry_attempts=)`, take the same
  path.
- **Prior-log read fails** (the issue's second trigger): the seed fails
  before `log_start`; no destination file; the retry reuses the prior source
  (in-process) or re-selects the older log (eval_set pass). No sample runs
  in the failed attempt, so no `error_retries` history is lost. A prior
  log that has *disappeared* is the exception: the attempt runs unseeded
  (every planned sample fresh) rather than failing, since a retry with the
  same missing source could never do better.
- **Prior log corrupt**: the copy is validated as a zip before it is
  adopted, so a truncated or damaged prior fails the attempt like a read
  failure instead of silently seeding nothing.
- **Hard kill during the seed**: no destination file (nothing flushed yet).
  Same outcome as #4933 today.
- **Hard kill after `log_start`'s flush**: the destination holds the
  complete prior set plus whatever later flushes carried. Buffer-db recovery
  discovers the `started` log again (reversing #4933's trade-off 2) and the
  recovered log is a superset of the prior — recovery no longer "cements the
  loss".
- **`log_finish` fails after earlier flushes**: the destination holds the
  complete prior set plus the flushed completions under a `started` header,
  and the retry seeds from it (see the `run_task_retry_attempts` section).
  Only completions since the last flush are re-run.
- **Compaction fails**: warn and flush the uncompacted zip (correct, just
  larger). Never let compaction fail a successful finish.
- **Destination flush fails**: unchanged from today (warning, stale-timer
  retry, `log_finish` backstop). The failure surfaces at `log_start`
  again, as for a fresh eval — restoring the fail-fast #4933 traded away.

## Trade-offs (accepted)

1. **Live samples start after the seed download instead of immediately.**
   Today's sweep reads the same bytes as N throttled range requests, parses
   and re-serializes each sample, and then uploads the whole temp zip at
   settle; the seed reads them as one streamed GET and skips the per-sample
   CPU. Total work to reach "destination holds the complete prior set" is
   lower; what moves is that live work no longer overlaps the read. For a
   multi-GB prior log on a slow link that is tens of seconds to a few
   minutes of startup delay per attempt. If that matters in practice, A2
   restores the overlap at the cost of the seed-failure-after-live-work
   rule (discard and write nothing). The download streams in constant
   memory on S3 under asyncio and for local files, and chunk by chunk for
   the non-S3 remote backends (GCS, Azure); S3 under trio buffers the whole
   prior log in memory (in a worker thread), as `read_log` does for it
   today (see step 1 of the mechanism). For the non-S3 remote backends the
   chunked read is synchronous fsspec I/O *on the event loop* — `to_thread`
   over a remote fsspec filesystem is ruled out (AGENTS.md) and no async
   GCS/Azure path exists — so every sibling task's samples and the control
   server stall for each chunk's fetch, with a checkpoint between chunks
   letting other work interleave; over a multi-GB download that is many
   short stalls rather than one for the whole file, comparable to the
   sweep's per-sample range reads this replaces.
2. **Dead bytes between attempts.** A non-success attempt's log carries the
   prior's superseded metadata and, for re-run samples, their prior records,
   plus whatever dead bytes the prior log itself carried (its non-success
   finish never compacted). Bounded by the errored/invalidated set per
   attempt; reclaimed by compaction at the successful finish, which measures
   the inherited dead bytes too; the intermediate logs are removed by
   `retry_cleanup` anyway.
3. **`log_images=False` on a retry of a `log_images=True` prior log keeps the
   prior samples' images**: they are copied as bytes, not condensed. Today's
   re-log strips them. Edge case; the alternative (parse and re-log those
   samples) reintroduces the per-sample path for one flag. Accept and
   document; a follow-up could prune attachments at compaction.
4. **The first flush is the size of the prior log.** Today the settle flush
   is the same size, so this is a timing change, not a cost change; and
   every later flush already rewrites the whole file.
5. **Unplanned prior entries in a dynamic-feed retry linger until the
   finish.** With no upfront plan there is nothing to prune against at the
   seed, so the attempt carries every prior record; the ones the feed never
   re-injects stay out of the live listing (never consulted) and are
   dropped at a natural successful finish (`Recorder.log_prune`, keyed by
   what is still in `_seeded_pending`), so the success log holds only this
   attempt's plan. They remain in a non-success log (the next attempt's
   seed) and in a graceful resolution's success log (its abandoned samples
   re-run in the next pass, reusing them). Compaction, which only reclaims
   unreferenced bytes, does not remove live members on its own.
6. **A `log_finish` failure after earlier flushes leaves a `started` log as
   the task's newest.** The retry's source is that partial destination (the
   prior set plus this attempt's flushed completions, so no completed
   sample on disk is re-run), and the file stays until retry cleanup, which
   never removes `started` logs, so it outlives the run. What it lacks is
   the header only (status, task-level error, stats, results), and
   `started` is the accurate status for an attempt still running when its
   write failed. Completions between the last flush and the failed finish
   were never on disk and are re-run under any design. Chosen over
   discarding the file and falling back to the prior source (an earlier
   draft), which kept the log dir tidier by re-running finished work. If
   the partial file is unreadable in the same outage, the next attempt's
   seed fails as for any prior-read failure (see the failure analysis).
   Removing older `started` logs in the cleanup sweep, which would take
   this file with it, is meridianlabs-ai/inspect_ai#459.

## Edge cases

- **Fresh eval / no sample source**: no seed; byte-for-byte unchanged.
- **Ineligible prior log** (shuffled without ids, dataset size changed): the
  existing warnings fire, no seed, no reuse — as today.
- **`sample_id` / `limit` subset, or fewer epochs than the prior**: unplanned
  keys pruned at seed; the log holds exactly the plan (plus dead bytes until
  compaction). More epochs than the prior: new epochs are absent keys and
  run live.
- **Invalidated sample in the prior**: its record is seeded (so an
  in-progress read shows it); the sweep's local body read sees
  `invalidation`, so the summary's clean `error` does not mask it; it
  re-runs, and the re-run supersedes it. The log-level `invalidated` flag
  comes from the new header.
- **Requeue within the attempt**: unchanged — a requeued re-run appends a
  superseding member as it does today; compaction treats it like any other
  superseded entry.
- **`eval-retry` on a named log file**: seeds from that file by byte copy
  when its format matches the attempt's `log_format`; otherwise (`.eval`
  prior into a `.json` attempt or vice versa) the in-memory write-through
  path runs before `log_start`. On an in-memory `EvalLog`: the same
  sequential write-through.
- **Explicit `resume=` log in eval_set**: seeds from it; nothing else
  changes.
- **JSON logs**: the generic `Recorder.log_seed` re-logs the prior's kept
  samples into the in-memory log; compaction is a no-op (the writer emits
  one document).
- **Checkpoints**: orthogonal to the seed. The retry startup copy
  (`copy_resume_payloads`, `design/checkpoint-snapshot-strategy.md` §4.5)
  replicates the prior attempt's sample checkpoint dirs into this attempt's
  own eval checkpoints dir before `log_start` — after the seed, so a copy
  failure discards the seeded temp zip with the attempt and a seed failure
  copies nothing — and `run_sample` resolves resume for every non-clean
  prior against this attempt's dir (an invalidated prior's copied dir is
  deleted; a fresh run starts from an empty one).
- **Prior log written by an older Inspect version**: the seed is a byte
  copy, so the samples keep their original schema version; readers already
  handle mixed-version members (the format has always been append-only).
  `_journal/start.json`'s `version` is superseded by the new attempt's.
- **Two attempts finishing within the same second on S3**: unchanged —
  newest-by-mtime selection has the same ambiguity today, and both
  candidate logs are now complete, so the worst case is choosing the one
  with one fewer live result.

## Testing

Unit (`tests/log/test_task_log.py` and a recorder test module):

- `EvalRecorder.log_seed` / `ZipLogFile.seed_from_prior_log`: the seeded
  temp zip contains every kept prior sample member and its member bytes are
  the prior log's (no end-of-central-directory record written over them);
  pruned names are absent from the central directory but the file stays
  valid; pruning is by generated member name, so a prior holding a string id
  containing `_epoch_` keeps exactly the planned keys and an int/str id
  mismatch still matches; the seed reads both a `summaries.json` prior and a
  journal-only `started` prior; the journal holds exactly one member listing
  the kept keys, so an in-progress `read_eval_log_sample_summaries` over the
  seeded log lists no pruned key; `buffered_sample` serves a seeded key from
  the local zip; `start()` after seed makes an in-progress read return the
  *new* start record, not the prior header; a re-run's completion supersedes
  the seeded member for every reader; compaction removes dead bytes and the
  compacted log round-trips through `read_eval_log`, including dead bytes
  inherited from an errored prior's own seed; a missing prior raises
  and leaves the log usable, a transient copy failure is retried; config
  updates journaled before the seed survive it; `discard()` after a
  prior-log seed removes the attempt's destination (the
  `_destination_seeded` rule does not apply); a `.json` prior is declined.
- `seed.classify`: a clean record is returned as-is, an errored one yields
  `PreviousError`, an invalidated or absent one yields `None`.
- Cross-format: a `.eval` prior retried with `log_format="json"` and a
  `.json` prior retried with `log_format="eval"` both reuse every clean
  sample through the write-through fallback.
- `TaskLogger.seed_from_prior` (`tests/log/test_task_log.py`): seeded and
  re-logged (cross-format, in-memory) seeds alike leave `samples_logged`
  and `samples_completed` at zero until the sweep accepts a record or a
  re-run completes, `read_prior_sample` serves
  them locally, `note_reused_sample` counts a completion, `log_start`
  creates the destination containing the prior set, and a missing prior
  raises before any destination write; `eval_log_sample_source` sets `seed`
  only when the eligibility checks pass (shuffled-without-ids and
  size-mismatch priors yield `None`) (`tests/test_eval.py`).
- Live listing source (`tests/log/test_task_log.py`): after the seed
  `sample_summaries` withholds every seeded record while `read_prior_sample`
  still serves them to the sweep and `read_sample` (the per-sample
  directives' read) withholds them too; a record surfaces when the sweep accepts
  it (`note_reused_sample`) or its re-run completes (`complete_sample`, the
  listed row being the re-run's), an unresolved errored record stays
  withheld, and after `log_finish` the source is gone and the on-disk log
  holds the unresolved record as the sample's final one.

Eval-level (`tests/test_eval_set.py`):

- The issue's repro, parametrized over `retry_immediate`: attempt 1
  completes s1–s3 and errors on s4; attempt 2 errors on s4 again; every
  attempt's log holds `{s1, s2, s3, s4}`, s1–s3 run exactly once overall,
  and the final log carries s4's two-entry error history.
- Seed failure: the prior log copy raises on attempt 2; no log file is
  written for attempt 2 and attempt 3 reuses s1–s3.
- Hard kill after the seed, before `log_start` (subprocess `SIGKILL` from
  the crash harness): no destination file; the next eval_set run reuses
  everything.
- Same repro with `eval(task_retry_attempts=1)` (no eval_set) for the
  `run_task_retry_attempts` path.

Run the async tests with `--runtrio` as well.

## Follow-ups (out of scope)

- **A2 (concurrent seed)** if A1's startup latency is a demonstrated problem,
  with the rule that a seed failure after live work discards the attempt.
- **Attachment pruning at compaction** for `log_images=False` retries of
  `log_images=True` logs (trade-off 3).
- **`eval-retry` seeding from a directory's newest same-task log** rather
  than only the named file.
- **F (one log per task)** becomes a small increment on A if per-attempt log
  identity is ever judged more cost than value.
- **Retry cleanup of older `started` logs.** The sweep keeps every
  `started` log for post-mortem debugging, a rule from before seeding, when
  an interrupted attempt's log could hold samples no other log had. Every
  finished attempt's log is now a superset of the `started` logs before it,
  so those hold nothing the newest log lacks and could be removed like
  errored ones; only a task's newest log ever needs recovery. Tracked as
  meridianlabs-ai/inspect_ai#459.
