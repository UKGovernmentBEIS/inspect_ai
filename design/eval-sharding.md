# Eval sharding

## Overview

A large eval can be split across workers that each run a disjoint subset of
one task's samples and write their own ordinary `.eval` log, a *shard*, into
a numbered directory of a companion `<name>.shards/` beside the log the run
ends up as. A trusted merge, run through a Python API or the `inspect log
merge-shards` command, validates the shards, combines the newest log of each
shard directory into the canonical `<name>.eval`, computes whole-task
results with the task the caller passes, and records in the merged log which
shard logs it holds. The merge is incremental: a later call reads only the
shards that changed and writes nothing when none did. Overlapping merges are
refused rather than allowed to regress the log. On request the merge deletes
the companion once the merged log is complete. The viewer hides shards that
a finished merged log covers, and `eval_set()` refuses a log directory that
holds shards.

## Why

Users split a task's samples across processes or machines, down to one
sample per machine, so a large or slow task finishes in wall-clock time one
process cannot reach. `eval(sample_id=...)` and `eval(limit=...)` already
let each worker run a slice, but each worker writes its own log, and on
their own those logs read as independent evals: the viewer shows one row
per worker, each header's metrics cover only that worker's samples (so
`stderr`, bootstrap intervals, grouped metrics and epoch reductions have no
whole-task value anywhere), `evals_df` gives a row per worker, and eval sets
would pair the slices as retries of one task and misjudge their
completeness. Sharding gives those logs a place and a merge, so readers see
one canonical log per task with one set of whole-task results, while each
shard stays a valid `.eval` file any tool can open on its own.

## How it works

User documentation: [Sharding](../docs/sharding.qmd) (layout, merging,
removing shards, the command, limitations) and "Sharded Tasks" in
[Eval Sets](../docs/eval-sets.qmd).

### Layout

The merged log is `<dir>/<name>.eval`. Its shards live in the sibling
directory `<dir>/<name>.shards/`, one numbered subdirectory per shard,
`<name>.shards/<k>/`, where `<k>` is one or more ASCII digits assigned by
whoever launches the workers. Workers run with `--log-dir
<dir>/<name>.shards/<k>/`; the recorder names each shard log as it names
any log, and its sample buffer lands beside it, so `inspect view` shows
shards live. The layout is the only marker: shard headers carry nothing new,
and no manifest or index file is written into the companion (decisions:
Ransom, 2026-09-21). It mirrors sandbox checkpointing's
`<name>.checkpoints/`.

- **The name is the identity.** `<name>.eval` and `<name>.shards/` derive
  each other by a string rule on the basename. `src/inspect_ai/_util/log_layout.py`
  owns the rule for both companions (`log_basename`, `eval_shards_dir`,
  `eval_log_for_shards_dir`, `eval_checkpoints_dir`,
  `merged_log_candidates_for_shard`); a `<name>-recovered.eval` maps to the
  same companion as `<name>.eval`. Tests: `tests/log/test_log_filename.py`.
- **The launcher mints `<name>`** before any worker starts, since the
  workers' log directory depends on it, in the same `{created}_{task}_{id}`
  shape as a log file name, so the merged log lists and sorts like any other
  (decision: Ransom, 2026-09-21). `eval_log_name` builds that name without
  an `EvalSpec`, honouring `INSPECT_EVAL_LOG_FILE_PATTERN`.
- **Attempts.** Several `.eval` files in one `<k>/` are attempts of the same
  shard (a retry, or a recovered log beside its original); the newest is the
  *current attempt* and is the one merged. Newest is by the `{created}`
  timestamp in the file name, then a `-recovered` file after its original,
  then modification time (`attempt_sort_key`). It is not mtime-first, as
  eval-set retries are ordered, because a running older attempt's mtime
  moves on every flush.
- **What is a shard.** A `.eval` file directly in a `<k>/` is a shard
  attempt. A log directly in the companion, a log in a dot-directory of the
  companion, and a `.json` log in a `<k>/` are stray files, which the merge
  refuses. A log nested deeper (in a shard's `scans/`, say, including a
  companion nested there) is an ordinary log (decision: Ransom, 2026-10-05).
  `is_shard_path` states the rule, and `list_shard_set` lists exactly those
  files, so every consumer agrees on which files are shards.
- **No override root.** Shards always live beside the merged log; there is
  no `shards_location` setting (decision: Ransom, 2026-09-21).

The self-contained-logs rule of
[`retry-seeded-attempt-log.md`](retry-seeded-attempt-log.md) (every log is
the whole truth about its task) is relaxed for files inside a companion
only (decision: Ransom, 2026-09-18). Copying a shard out of its companion
makes it an ordinary partial log.

What the launcher must do (numbered directories, a fixed, disjoint
selection per directory by `--sample-id` or a `--limit` range, the same
task, arguments, model, scorers and epochs from the same working
directory, `.eval` format, no backslashes in shard file names) is listed
in [Sharding, "Layout"](../docs/sharding.qmd). Tasks that add samples while
they run (a `SampleSource`) cannot be sharded: their header records only
the seed selection.

### Entry points

The merge is `merge_eval_log_shards` and `merge_eval_log_shards_async` in
`inspect_ai.log` (`src/inspect_ai/log/_shards/_api.py`), with the errors
`ShardSetError`, its subclass `ShardSelectionError`, and
`ShardSetIncomplete` (`_errors.py`). Inspect ships no launcher: whoever
starts the workers (a runner, a harness, a shell script) calls the API or
the command when its workers finish, and a launcher that forgets or dies is
covered by running the command by hand (decision: Ransom, 2026-09-21).
Inspect does nothing at the end of a run on its own.

The call takes the merged log or its companion, the `Task` the shards ran,
an optional intended selection (exact ids or a count), `allow_incomplete`
and `delete_shards`. Its docstring and [Sharding,
"Merging"](../docs/sharding.qmd) give each parameter and error. The merge
supports local paths, `file://` URIs and `s3://` URLs and refuses every
other form, including chained and percent-encoded chained URLs and relative
paths whose first component holds a colon, as text before any I/O
(`supported_location` in `_publish.py`; decisions: Ransom, 2026-10-30 and
2026-11-03): other fsspec backends differ in how they list, name and
version objects, and each needs its own support. A `file://` URI is decoded
once, and a local location becomes one absolute path that every read, the
lock and publication use (decision: Ransom, 2026-11-04). A
`<name>-recovered.eval` argument is refused, so one companion never gets
two merged logs.

### One pass

Every call runs one pass, under the overlap guard ("Overlapping merges"):

1. Read the merged log's header and central directory, if it exists. A
   `<name>.eval` without the ledger field is an ordinary log, and the merge
   refuses to overwrite it: a merge never replaces a log it did not write.
2. List the companion with `list_shard_set` and classify each shard by its
   current attempt against its ledger entry: *unchanged* (same file name and
   ETag, or same size and mtime where either side has no ETag), *changed*,
   *new*, or *vanished* (a ledger entry whose `<k>/` has no attempt left). A
   `<k>/` holding only ancillary entries is not a shard.
3. Read only changed and new shards (central directory, header and
   summaries; a running attempt's header and summaries come from its
   journal, as every Python reader takes them), and validate ("Validation").
4. Plan the sample set, the status and the header from the ledger, the
   merged log's own members and the attempts read.
5. Write only when there is no merged log, a shard is changed or new, or the
   intended selection differs from the recorded one. Otherwise return the
   existing header with `written=False`.
6. When writing, build the merged zip in a local temporary file, computing
   the results over every merged sample, and publish it.

A steady-state pass over unchanged shards therefore costs one listing of
the companion plus the merged log's header and central directory, which is
what makes repeated merges of a run with hundreds of shards cheap.

When the user has removed the whole companion, the pass finds no attempt
and returns the merged log as recorded, after matching the task against
the merged header; a supplied selection must then equal the recorded one,
since nothing is left to merge it against. With neither a merged log nor a
shard attempt, the call raises `FileNotFoundError`.

### Validation

Membership is by location, so a stray or hostile file in the companion is a
candidate member; the merge refuses rather than skips (decision: Ransom,
2026-09-21). Across the current attempts (and, for unchanged shards, the
merged header built from them), `check_headers` in `_plan.py` requires:

- equal `task_identifier`, computed with the running Inspect's identifier
  version. It covers task file, name, arguments, model, solver plan,
  generate config, model arguments and roles, task version and limits while
  ignoring the dataset selectors, and it is what `eval_set()` pairs logs
  by. Because `task_file` is relative to the working directory, workers must
  start from the same directory relative to the task file; the error says so
  when only the task file differs;
- equal scorers, metrics and dataset size, which the identifier does not
  cover and which decide the results and the whole-dataset completeness
  rule;
- equal epochs and epoch reducer, which the identifier also leaves out;
- an equal log format version, no newer than the running Inspect writes.

Further checks, each refusing with `ShardSetError` before anything is
written:

- every directory directly in the companion is named with digits only, and
  no attempt file name contains a backslash (decisions: Ransom, 2026-10-29;
  the file name orders attempts and keys the ledger, and odd names are not
  supported one at a time);
- no stray file, no chunked-shape sample (the merge copies monolith members
  only), and no two attempts of one shard that sort as equally recent;
- no attempt holds samples it did not resolve (a drain or sample cancel
  keeps a cancelled sample's transcript but leaves it out of
  `results.logged_samples`, so counting it would complete the set
  falsely; `check_resolved`);
- no attempt regression (a current attempt older than the one the ledger
  records, which happens only when the recorded attempt was deleted) and no
  vanished shard while other attempts remain. Both mean shard files were
  deleted by hand, and merging the remainder would drop or replace merged
  samples with obsolete ones;
- every read attempt records its selection (`eval.dataset.sample_ids`) and
  holds only ids within it; a changed shard's selection is the one merged
  before (by digest); the read selections are pairwise disjoint; and the
  merged records each read shard owned number exactly its ledger count
  (`check_reads`);
- the merged log's records number the sum of the ledger counts
  (`check_ledger_count`), so a merged log changed outside the merge is
  refused with the advice to delete it and rebuild from the shards;
- the selection, given or recorded, covers every held id
  (`ShardSelectionError` names the ids outside it).

Messages name the offending files and the field that differs.

### The sample set

The merged log holds, for each shard, exactly the records (`(id, epoch)`
keys) its current attempt holds. When a shard's current attempt changes (it
grew, or a newer attempt appeared in `<k>/`), all of that shard's records
are taken from the new attempt and any it lacks are dropped; this is
"newest wins" applied per shard (decision: Ransom, 2026-09-21), and the
same rule ctl log-dir mode uses, so the two never disagree about what a
shard contributes.

The ledger lists no keys. A pass attributes records by id: the merged
records whose ids fall in the selection of a shard read in this pass are
*dropped*, the rest are *carried* from the merged log, and every record each
read attempt holds is *taken*. This is exact because a shard selects whole
samples, so each id belongs to the one shard that selected it; the digest
check keeps a changed shard's selection fixed, and the count checks make
the dropped records exactly that shard's previous ones. So an incremental
pass plans the same records as a fresh merge of the same companion, which
is what makes the merge idempotent and deterministic. Overlapping
selections break the launcher's contract: a fresh merge refuses any
overlap, and an incremental pass refuses one as soon as a record falls in
the intersection.

Consequences, stated in the docs: deleting one `<k>/` by hand makes later
merges refuse until the rest of the companion is deleted or the files are
restored; a new attempt in an existing `<k>/` that selects different
samples is refused until it moves to its own `<k>/` or the merged log is
deleted and rebuilt. Header edits to the merged log (tags, metadata) are
carried to every later pass; a sample edited in the merged log survives
until its shard changes; `invalidated` follows the merged samples.

### Status

- `error` when any current attempt is `error` or `cancelled`. Its completed
  samples are still merged, and the merged log's `error` is the first
  failing shard's in shard order (decision: Ransom, 2026-09-21), so nothing
  looks like it is still running. A rerun in the same `<k>/` supersedes the
  failure.
- `success` when every current attempt is `success` and the records are
  exactly the selection's ids times every epoch.
- `started` otherwise: shards still running, or samples missing.

The intended selection is a merge parameter, not a file: shard headers
cannot supply it for a subset run, and the launcher that assigned the ids
knows it. Given as ids or a count, it is recorded in the merged log and
reused by later merges; without one, a first merge is complete only when the
shards hold the whole dataset. An incomplete outcome raises
`ShardSetIncomplete` (with the status it would write, the missing ids, and
the running and failed shards) and writes nothing, unless `allow_incomplete`
asks for the `started` or `error` log (decision: Ransom and JJ Allaire,
2026-09-18). Shards added after a `success` merge return the merged log to
`started` until they finish.

A shard whose task stopped samples or epochs early finishes `success`
without records for them, so its set is incomplete for its original
selection; the merged results carry no early-stopping summary. A fractional
`fail_on_error` threshold is evaluated per shard, not over the whole task.

### The merged log

The merged log is an ordinary finished `.eval` file: sample members,
`summaries.json`, `reductions.json` and `header.json`, never a journal,
whatever its status, so readers never take the running-log path for it.
`build_header` in `_plan.py` takes every field from the template shard (the
first shard in shard order) except:

- `eval_id`, `run_id` and `created`, minted at the first merge and carried
  after, so incremental passes present as one log;
- `task_id`, from `merged_log_task_id` in `log_layout.py`: the id in
  `<name>`'s `{id}` slot when the file name pattern lets it be read back,
  else a name-based UUID of `<name>`. It is stable across passes and when a
  merged log is rebuilt from a leftover companion, but only while
  `INSPECT_EVAL_LOG_FILE_PATTERN` is unchanged (decision: Ransom,
  2026-10-13: the pattern is almost certain never to change);
- `eval_set_id` when the shards share one;
- `dataset.sample_ids`, the selection merged against; `config.sample_id`
  and `config.limit` are unset;
- `results` and the reductions ("Results"), and `stats` summed from the
  ledger (earliest start, latest completion, usage added per model and
  role);
- `log_updates` carried from the existing merged log;
- `eval.shards`, the ledger.

**The ledger** is the typed `EvalSpec.shards` field, `EvalShards` holding
`EvalShardEntry` records (`src/inspect_ai/log/_log.py`), rather than
`eval.metadata`, which is the user's namespace (decision: Ransom,
2026-09-21). It records the form of the selection (`ids`, `count` or
`none`, with the count; the ids are `dataset.sample_ids`) and one entry per
shard with an attempt, in shard order: the current attempt's file name,
status and error, the records it held, the size and digest of its
selection, its `eval_set_id`, statistics and usage, and its size, ETag and
mtime as read. That is everything a later pass needs from a shard it does
not reopen, so stats and errors are recomputed from entries and replacing
one shard's attempt replaces exactly its contribution. The ledger is a
fixed set of fields per shard and nothing per sample, and it records no
companion location and no shard `eval_id` (decisions: Ransom, 2026-09-29):
the companion is derived from the name, and a recorded location goes stale
when the log moves. Its presence is how `eval_retry` and ctl log-dir mode
recognise a merged log. It is absent on shards and unsharded logs. Tests:
`tests/log/test_eval_log.py`.

**Members.** Sample members are copied in the compression the shard (or the
previous merged log) used, raw, under names rebuilt from each key rather
than copied from a source directory, so a crafted member name cannot place
data under another key (`RawMemberWriter` in `src/inspect_ai/_util/zipfile.py`).
A changed shard's member whose CRC and size equal the merged log's copy is
taken from the merged log. Each sample is decompressed once, as it streams,
and parsed include-only (`_SampleParse` in `_write.py`): only its id, epoch,
scores, error, invalidation and its `sample_init` event's metadata are
built, so peak memory follows the largest single JSON value rather than the
largest transcript. What the merge does keep in full is every sample's
scores, because metrics take all of them at once and recomputing from less
is the lossy input it rules out (decision: Ransom and JJ Allaire,
2026-09-18: recompute from full samples, not summaries, which truncate
score answers, explanations and metadata). The merge never builds an
`EvalLog` holding samples.

### Results

The merge computes results only with the `Task` the caller passes, and
never rebuilds a metric, reducer or scorer from what a log records
(decision: Ransom, 2026-11-03): a log records metric and reducer options
lossily (a function by its name, a reducer without its arguments), while
the caller's task is the code that ran. It takes a built `Task`, not a spec
(decision: Ransom, 2026-11-04): a task factory runs in a construction
context (the incoming model, generate config and roles, before the task's
own overrides) that the logs do not record, so a reloaded spec can build
different metrics under the same names.

Before writing, `check_task_matches` (`_write.py`) compares the task with
what the shards recorded, by name only: task name, scorer names in order,
metric names, number of epochs and epoch reducer names. Options are not
compared; passing the task the shards ran is the caller's responsibility.
For shards run with `--epochs N`, the docs give the `task_with` recipe that
keeps the task's reducer.

The results are `eval_results` over all merged samples, as the task runner
computes them, in the caller's model context: the merge builds no model
from the shards' recorded model, base URL, model arguments or roles
(decision: Ransom, 2026-11-04). The metric inputs are those of a fresh,
unsharded run (decision: Ransom, 2026-10-27): each score sees the sample's
dataset metadata as its `sample_init` event recorded it, not metadata a
solver changed, and the scorer's unqualified name. It follows that:

- a sample with scores but no `sample_init` event (logged without events)
  is refused;
- a score whose key no declared scorer produced (set by a solver) is
  refused, because a fresh run and a retry pass it to metrics differently
  (decision: Ransom, 2026-10-28);
- shards run without scoring merge to a log with no scorer results, as an
  unscored run does, and a set mixing scored and unscored samples is
  refused;
- metrics see values in their stored JSON form, so a tuple is a list and a
  datetime a string; the merge does not detect or recover such types
  (decisions: Ransom, 2026-10-29 and 2026-11-02);
- metrics run over samples in sample id order (ids as text), then epoch, so
  an order-dependent metric equals an unsharded run of the same samples in
  that order (decision: Ransom, 2026-10-29).

Native `eval_retry` builds reused samples' metric inputs differently (final
metadata, stored score key); the merge follows the fresh run and leaves
retry unchanged (decision: Ransom, 2026-10-27). The merged log is an
ordinary log to `recompute_metrics()`, `score()` and `edit_score()`.

### Overlapping merges

Two merges overlapping while shards grow could publish a valid but
regressed log, and two overlapping first merges would each mint an
`eval_id`. Callers serialise merges, one merger at a time per merged log,
and compare-and-swap publication turns a broken contract into a refused
publish (decision: Ransom, 2026-09-22). There is no lock protocol for
remote storage. `_publish.py` holds the guards:

- **Local.** The merge holds an exclusive lock file, `<name>.merge.lock`,
  beside the merged log for the whole call (`acquire_exclusive_lock` in
  `src/inspect_ai/_util/file.py`), recording host, process and start time.
  A held lock raises `WriteConflictError`. A lock left by a crashed merge is
  reported, never overridden: the user checks the named process has stopped
  and deletes it. A merged log that is a symbolic link is refused, since the
  lock would sit beside the link while publication replaced its target.
  Publication is an atomic replace. The lock does not exclude a viewer edit
  of the merged log during a merge.
- **S3.** No lock. The merged log is downloaded only when a pass writes,
  in ranges pinned to the ETag read at the start (`get_file_if_match`), and
  published with `IfMatch` on that ETag, or `IfNoneMatch: *` for a first
  merge, on a single or multipart upload (`write_file_conditional` in
  `src/inspect_ai/_util/asyncfiles.py`), with `head_object` pre-checks for
  backends that ignore the conditions. A refused or pre-check-failed
  publish raises `WriteConflictError` and aborts the upload. The final call
  goes through a client with SDK retries off, because a retried request
  that had in fact succeeded would be refused by its own condition. A
  publish that fails without a response, or is cancelled after it was sent,
  may or may not have landed; the error propagates as is, and rerunning is
  safe because a landed publish matches its shards and the rerun writes
  nothing. Tests: `tests/util/test_asyncfiles.py`, `tests/util/test_file.py`.

### Reads, cancellation and threads

A running shard's object is replaced on every flush, so a member read
after its central directory can land in a newer object. Every shard read
verifies each member's CRC (`AsyncZipReader(verify_crc=True)`), so such a
read fails rather than returning mixed bytes. The merge does not retry: any
error reading a shard fails the merge before anything is published, and
running it again reads the shards anew (decision: Ransom, 2026-10-21).
Merging after the workers have exited is the supported use.

Cancellation before publication leaves the merged log and shards
untouched, with temporary files and the lock released. Every worker thread
the merge starts, local deletes included, goes through `run_owned`
(`_owned.py`; decisions: Ransom, 2026-11-02 and 2026-11-03), which waits
for started work before an exception or cancellation propagates, so a
directly cancelled asyncio task cannot release the lock under a thread that
is still writing. The S3 upload's own reads of the temporary file go
through `OwnedReads` for the same reason. `test_merge_thread_calls_go_through_run_owned`
fails on any other thread dispatch in the package. Reads and deletes run
with bounded concurrency in one `AsyncFilesystem` scope.

### Deleting shards

The merge deletes nothing unless asked (decision: Ransom, 2026-11-03):
deletion is the one step that cannot be undone after a bad merge, and
re-merging after a merge bug or adding shards later both need the shards.
With `delete_shards=True` (`--delete-shards`), the merge deletes the
companion once the pass has left a `success` merged log; an incomplete set
raises and deletes nothing (decision: Ransom, 2026-11-19), and the option
cannot be combined with `allow_incomplete`. A call that returns with the
option has deleted the shards; every way of not deleting raises. The
typical use is to merge, check the merged log, then merge again with the
option, which writes nothing and deletes. `src/inspect_ai/log/_shards/_delete.py`
holds deletion; the merge owns it and no other code path deletes a
companion. Docs: [Sharding, "Removing shards"](../docs/sharding.qmd).

Guarantees:

- **Only what was listed.** One recursive listing under the merge's lock,
  before the pass, fixes the set: locally every entry, not following
  symbolic links; on S3 every object under the companion's prefix with its
  trailing `/`, directory markers included, each passing the S3 name check.
  Entries are deleted by name, never by prefix; a link is removed as a link;
  a companion that is itself a link is refused. A name written after the
  listing is merged by the pass and left in place.
- **Current attempts last.** Every other entry is deleted before any
  shard's current attempt, so an interrupted deletion leaves each shard
  with its recorded current attempt or none and never makes an older
  attempt current.
- **Confirmed.** A final listing must find the companion empty, or the call
  raises naming what is left.
- **Finishable.** Running the same merge with the option again finishes an
  interrupted deletion: a deleting call accepts a companion whose only
  differences from the ledger are shards with no attempt left, provided the
  stored status is `success`, the selection is unchanged and every remaining
  shard matches the ledger. No in-progress marker is written. A plain merge
  still refuses such a companion as vanished shards.

The option requires a quiescent run: no workers, log edits, scoring or
other merges of the run from the first deleting call until one returns
(decision: Ransom, 2026-11-19). Enforcing it would need every log writer to
share a lock or conditional protocol with deletion, which none has; a
concurrent writer's work can be lost, as with removal by hand. The user can
still delete the companion by hand; a partial hand removal is finished by
hand.

### The merge command

`inspect log merge-shards LOG --task TASK` (`src/inspect_ai/_cli/log_merge_shards.py`)
lets a shell launcher merge without a Python step. It takes one `LOG` and
`--json` (decisions: Ransom, 2026-10-21). It builds the task as `inspect
eval` builds it, through eval's own task resolution (`eval_init`,
`eval_resolve_tasks`), from the subset of eval's options that build a task:
task arguments and task config, model, base URL, model arguments and
config, model roles, and epochs and epoch reducer. Those options are shared
decorators in `src/inspect_ai/_cli/eval.py` (`model_options`,
`model_role_option`, `task_args_options`, `epochs_options`,
`parse_epochs_options`), so they mean and parse what they do under `inspect
eval` and read the same environment variables. The model and roles stay
active, so they are also the model context the merge's metrics run in.

- The task is always the one named on the command line, never the logs'
  `task_file` (decision: Ransom, 2026-11-04). `--task`, the selection
  options, `--allow-incomplete`, `--delete-shards` and `--json` are read
  only from the command line, so the environment cannot supply the task or
  the selection.
- The generate config is the default; generation options are not accepted
  (decision: Ransom, 2026-11-05). No surveyed task factory reads the
  generate config when built.
- `--model-spec` and `--run-config` are not accepted, and their environment
  variables are refused because they would change the task; the docs say
  how to translate a run launched with them into flags, and why `inspect
  log export-config` of a shard log is not a substitute.
- `--sample-id` takes exact ids, not patterns. Ids are matched as text, and
  the merged log records each with the shards' typed id.

The report, the `--json` object and the error envelope (its `kind` values
classify the failure by phase and exception type, so an error in the task's
own code never reads as a merge refusal) are documented in [Sharding, "The
merge command"](../docs/sharding.qmd). Every failure exits 1 with no bare
click exit in the module, under one failure boundary; with `--json`, all
other output, including the task's own, goes to stderr. Tests:
`tests/log/test_shards.py`.

### Eval sets and `eval_retry`

`eval_set()` does not merge shards and refuses a log directory that holds
any (decision: Ransom with JJ Allaire, 2026-11-18). No caller needs a merge
at startup, and an eval-set retry would run samples outside a launcher's
per-instance placement; without the refusal, pairing would treat shard
attempts as retries of one task with count-based completeness. Before
pairing, viewer or scan output, or any run, `_refuse_shard_companions` in
`src/inspect_ai/_eval/evalset.py` checks the names in the listing the eval
set already makes and raises `PrerequisiteError` when a listed log's parent
directory is all digits under a `*.shards` directory, or is a `*.shards`
directory. It reads only each name's last path components, so it opens
nothing and reads no shard header, and it is deliberately broader than
`is_shard_path`: it also refuses an eval set run on a companion or a shard
directory itself. `log_dir_allow_dirty` does not bypass it. The message
gives the workflow: merge, retry incomplete shards in their own `<k>/` with
the same selection, run unselected samples as new shards, merge again, then
move the companion out or delete it with `--delete-shards`. Selection
(worker) mode never scans the directory and is unaffected. Tests:
`tests/test_eval_set.py`.

`eval_retry` of a merged log is supported only when it was merged with no
selection (`none`), whose selection is the whole dataset, so an ordinary
retry runs exactly the right samples (decision: Ransom, 2026-09-29). For an
id or count selection it raises before any sample runs and says to re-run
the incomplete shards and merge again: a retry selects with normalised
patterns, not exact ids, and a count names no ids.

### Viewer listing

The shared log listing excludes nothing, so `list_eval_logs`, `evals_df`
and other enumerators list shards as ordinary partial logs beside the
merged log. The viewer's listings hide a shard once a finished merged log
covers it (decision: JJ Allaire, 2026-09-27, revising Ransom's 2026-09-21
deferral): the view server's `/logs` and `/log-files`, the `listing.json`
`write_log_listing` writes, and `inspect view bundle`, which also leaves
covered shards out of the bundle. The rule (`filter_merged_shards` in
`src/inspect_ai/log/_shard_listing.py`) hides a shard when its merged log
is in the same listing, has status `success`, and is strictly newer than
the shard by mtime. A shard written after the merge, a tie (S3 mtimes have
one-second resolution), and every shard of a `started`, `error`,
`cancelled` or unreadable merged log stay visible, so ongoing work is never
hidden. The rule keys on the layout and status only, not the ledger, so it
works for any merger that writes after reading its shards and publishes
`success` only when every shard has finished. The view server reads only
the headers of merged logs newer than one of their shards, caches each
status by mtime and size, checks the access policy before reading, and
sends full rather than incremental `/log-files` responses while hiding can
change. `inspect view --show-shards` and
`write_log_listing(hide_merged_shards=False)` turn it off. Tests:
`tests/_view/test_view_server.py`.

The viewer's `/log-delete` deletes only the requested file (decision:
Ransom, 2026-09-24). Deleting a merged log there leaves its companion, the
viewer lists its shards again, and the next merge rebuilds the log.

### Code shared with ctl log-dir mode

[`ctl/log-dir-mode.md`](ctl/log-dir-mode.md) reads the same layout
read-only, and the two share one implementation of each rule, so they
agree on which files are shards, which attempt is current and which
records a shard contributes:

- the name rules and `merged_log_task_id` (`src/inspect_ai/_util/log_layout.py`),
  so ctl gives a shard set with no merged log yet the `task_id` the merge
  will give it;
- the walk, `list_shard_set`, `attempt_sort_key` and `is_shard_path`
  (`src/inspect_ai/log/_shards/_walk.py`, tests in
  `tests/log/test_shards.py`). The merge alone passes `numeric_shards`;
  ctl keeps discovering other directories as shard rows and descends
  `unlisted_dirs` to list logs nested in ancillary directories. Both refuse
  names that S3 would read as another key (`check_s3_location`) and
  listing entries that are not a name directly in the directory listed;
- `AsyncFilesystem.list_dir` and the CRC-checked `AsyncZipReader`;
- the ledger, from which ctl takes totals and, for a complete merge whose
  shards are unchanged, its task rows.

## Guarantees and limits

The merge guarantees that:

- the merged log is written only by the merge, a trusted Python step; no
  reader path (viewer server, `read_eval_log`, dataframes, ctl) creates it
  or recomputes metrics (decision: Ransom, 2026-09-21);
- it holds exactly the current attempts' records, with ids owned by one
  shard each, and an incremental pass and a fresh merge of the same
  companion produce the same records, ledger and results;
- it is `success` only when every current attempt is `success` and the
  records are exactly the selection times every epoch;
- an overlapping merge is refused on local storage and S3 rather than
  regressing the log, and a refused or failed merge publishes nothing;
- a merge never overwrites a log it did not write, and refuses a merged log
  changed outside it;
- deletion removes only what its listing found, current attempts last, and
  is finished by rerunning.

Limits, each in [Sharding, "Limitations"](../docs/sharding.qmd) or its
sections: storage other than local and S3 is refused; a merge overlapping a
running worker can fail with a read error and needs a rerun; a lock left by
a crashed local merge must be deleted by hand; the merged `task_id` survives a rebuild only under an unchanged file
name pattern; equally recent attempts are refused; S3 names holding `#`,
`?`, control characters or a leading `/` are refused; a local merged log
that is a symbolic link is refused; zstd frames the viewer cannot decode
are copied as is; per-shard scan results and checkpoints stay in their
`<k>/` and go with the companion; a viewer delete leaves the companion.

## Alternatives considered

- **Readers that present a set of shards as one log** in Python, the
  dataframes, eval sets, Scout and the browser client in three hosts.
  Better live visibility, but changes in every reader, and whole-task
  metrics need user Python that a browser cannot run. Kept as the
  reference for later live-view work.
- **A sharded log as a directory with a manifest.** A new on-disk format
  every consumer and old version must learn; the merged `.eval` keeps
  readers unchanged.
- **Workers writing one shared log.** A zip cannot be appended from many
  processes, and S3 has no append.
- **Workers merging on exit.** No launcher dependency, but two finishers
  overlap, the largest transfer lands on an arbitrary worker, and every
  worker needs the metric code.
- **A shard marker in each header**, or reusing `task_id` as the marker.
  The marker would change every shard's schema and let membership leave
  its directory; a shared `task_id` makes retry cleanup delete shards as
  stale attempts (decision: Ransom, 2026-09-21, for the layout).
- **Provenance in `eval.metadata`, or a separate ledger file.** The first
  sits in the user's namespace; the second is a second source of truth that
  drifts from the merged log.
- **Exact keys, or each shard's ids, in the ledger.** Per-sample data in a
  header every listing parses; attribution by id needs a count and a digest
  (decision: Ransom, 2026-09-29).
- **Recomputing from summaries.** Wrong for metrics that read answers,
  explanations or metadata.
- **Rebuilding the task, metrics or model from the logs**, in the API or
  the command. The construction context is not recorded, and it would
  import code and build providers a log names (decisions: Ransom,
  2026-11-03 and 2026-11-04).
- **Restarting a pass on a torn read.** Merging after workers exit needs
  none (decision: Ransom, 2026-10-21).
- **A pattern-independent merged `task_id`.** Survives a file name pattern
  change, which is not expected to happen (decision: Ransom, 2026-10-13).
- **Merging at `eval_set()` startup**, then resuming as an ordinary retry.
  Built and cut: no caller needs it, and the retry runs samples outside a
  launcher's placement (decision: Ransom with JJ Allaire, 2026-11-18).
- **An unconditional listing exclusion** keyed on `.shards` or on the merged
  log existing. A stale merged log would hide ongoing work; the viewer rule
  adds status and mtime conditions.
- **A viewer delete cascade** with per-member authorization. Not taken with
  Step 1's no-viewer-change decision (Ransom, 2026-09-24).
- **Deleting by default, by prefix, or of incomplete runs**, or a separate
  delete function that needs no task. Default deletion loses re-merge;
  prefix deletion removes unlisted names and gives no order; deleting an
  incomplete set freezes it; a separate entry point needs its own lock and
  error handling, which the merge has.
- **Enforcing quiescence for deletion** with conditional deletes. Narrows
  but cannot close the windows while other writers rewrite logs outside the
  merge's lock.
- **The full `inspect eval` option set on the command**, pairing by
  `task_identifier`. The user would repeat options the merge never uses.

## Compatibility

- **Opt-in by layout.** Logs, directories and callers that do not use
  `<name>.shards/` behave as before, except the `eval_set()` refusal of a
  directory holding shard logs.
- **Stored format.** `EvalSpec.shards` is optional and absent on every log
  but a merged log; shard headers are unchanged. It is in the JSON schema
  and the viewer's generated types, which the viewer does not read. Older
  Inspect versions drop the field on read and treat a merged log as an
  ordinary log; an old version that rewrites a merged log makes an ordinary
  log, which the merge then refuses to overwrite, and an old `eval_retry`
  retries any merged log over the whole dataset.
- **Enumerators other than the viewer** list shards beside the merged log.
  `evals_df` gives an extra row per shard; `samples_df` dedupes by sample
  `uuid`, but a directory read also returns superseded attempts' samples.
  Pass merged logs explicitly for the whole-task view.
- **Shards that are not supported:** `.json` logs, chunked-shape samples,
  `SampleSource` tasks and logs without a recorded selection.

## Security

- **Untrusted input.** Shard headers, summaries, sample members, names in
  the companion and the merged log itself are written by processes that may
  run agent code, or by anyone who can write the log directory. They go
  through the existing models and zip readers. Paths come from listed names
  by fixed rules; the ledger never locates anything; member names are
  rebuilt from keys. Strict validation refuses a stray or hostile file.
- **Code execution.** The merge is a read operation in the trust model of
  [`malicious-log-code-execution.md`](malicious-log-code-execution.md): it
  runs only the `Task` the caller passes, imports nothing a log names,
  builds no model provider from log values, and refuses a score no declared
  scorer produced (decision: Ransom, 2026-11-04). It has no `trust_log`
  parameter; opting in with one is the consistent extension if a metric
  needs the shards' model. The command builds the task from its own
  command line only.
- **Deletion** stays inside the companion: local walks do not follow links,
  links are removed as links, a linked companion is refused, S3 listings
  are confined to the companion's prefix with its trailing `/`, and every
  S3 name passes the name check before anything is written or deleted. The
  ledger decides whether deletion runs, never what it deletes. Deletion
  uses the caller's credentials and consults no access policy; the viewer,
  which has one, deletes no companion.
- **Viewer.** Shard hiding checks the access policy before reading a merged
  log's header, and a merged log the requester may not read hides nothing.
- **Resource use.** A hostile shard can make a merge expensive, as the same
  file makes `read_eval_log` expensive. Memory is bounded by the largest
  JSON value and all samples' scores, not transcripts.
- **Lock file.** Its contents are informational and never parsed for a
  decision.

## Not this design

- **Live whole-task metrics during a run.** Either a periodic rollup of
  shard summaries (cheap, value-only, labelled as an approximation) or the
  incremental merge on a timer (exact, a merged-zip rewrite per tick). Not
  decided whether to build either before live-view work.
- **Live-view support for shards:** collapsing a merged log's shards into
  one viewer row, per-shard metrics in the viewer, and the running-sample
  viewer.
- **A viewer delete of a merged log that also removes its companion**, with
  per-member authorization.
- **S3 server-side composition** (`UploadPartCopy`) of the merged log,
  for very large logs.
- **A lossless metric-input cache** in the merged log, to avoid reading
  carried samples on every writing pass.
- **A stale-lock check** for local merges (a same-host dead process).
- **Other storage backends** for the merge (GCS, Azure).
- **Chunked-shape samples** in shards, once the recorder writes them.
- **An exact-key sample selection** for `eval_retry` and `--sample-id`,
  which would let `eval_retry` take id- and count-selected merged logs.
- **Eval-style selectors on the merge command** (`--limit` ranges,
  `--sample-id` patterns), expanded against the task's dataset.
- **A directory-wide merge**, and a delete without a task.
- **`--model-spec` and `--run-config` on the merge command**, and a
  `--generate-config` option if a task factory needs one.
- **An `evals_df` column for `eval.shards`** and a helper that selects
  merged logs, and extending the listing exclusion beyond the viewer.
- **Relocating per-shard scan results and checkpoints** to the merged log's
  locations, so scanner resume can reuse worker rows; and deleting a
  merged log's `<name>.checkpoints/` (meridianlabs-ai/inspect_ai#582).
- **Coordination between deletion and other log writers**, should
  concurrent cleanup need to be safe.
- **Per-epoch sharding**, which `sample_id` and `limit` cannot express.
- **Count-based eval-set completeness:** `log_samples_complete` compares
  counts, so a log of other samples with the same count satisfies a
  `--sample-id` request.
- **Sanitising control characters** in log-derived names that `inspect
  log` commands print.
- `seed_from_prior_log` keeps unknown zip members, so any future extra
  member would be copied into seeded retries.
