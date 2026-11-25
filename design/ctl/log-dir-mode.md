# Read-only log mode for `inspect ctl` (`--log-dir`)

## Overview

`inspect ctl --log-dir <dir>` answers ctl's read commands (`task list`,
`sample list`, `sample errors` and the per-sample reads) from a log
directory, local or on S3, instead of from a running eval process. It walks
the directory once, groups logs into logical tasks (retries folded
together, a sharded run's shards shown as one task), and reads each sample
from the newest source that holds it: a finished log, a running log's
journal, or a shared sample buffer written with `--log-shared`. A local
cache makes repeated polls read only what changed. The mode never writes to
the directory, never runs task code, and is not offered on commands that
change a running eval.

## Why

`inspect ctl` observes a running eval through the eval process's control
server, an AF_UNIX socket found through per-process discovery files, which
is reachable only from the same machine and user
([`security.md`](security.md), "Access model"). A sharded run puts each
shard on its own machine, down to one sample per machine
([`../eval-sharding.md`](../eval-sharding.md)). The operator, or the agent
driving the run, sits on another host, often behind networking rules that
let it read the shared log bucket and nothing else, so it has no live ctl
view of the run.

What the operator can reach is the log directory. Every worker writes its
`.eval` log there, flushed as samples complete, and with `--log-shared` it
also syncs its running samples to a `.buffer/` directory beside the log.
That is enough to answer what a monitoring agent asks most often (which
shards are running, finished or failed; how many samples are done; which
samples errored and why; what a sample did), a little behind the live
process and with no network path to the workers. The mode serves sharded
and unsharded directories alike, and is sized for a run of about 300 shards
on S3.

## How it works

User documentation: [Reading a Log
Directory](../../docs/control-channel.qmd#reading-a-log-directory) (the
commands, the extra fields, the error kinds, freshness and polling).

The mode is split between the CLI, which owns the option, the banner, the
envelopes and error mapping (`src/inspect_ai/_cli/ctl/_log_dir.py`), and a
reader package that builds the control API's row and envelope shapes from
logs (`src/inspect_ai/_control/log_dir/`: `walk.py`, `snapshot.py`,
`select.py`, `consistency.py`, `buffer.py`, `samples.py`, `cache.py`). The
reader imports nothing that starts a server. Its tests are in
`tests/_control/test_log_dir.py`; the CLI contract's are in
`tests/_control/test_ctl.py`.

### CLI surface

`--log-dir` is an option of each command the mode serves, written after the
command like every other ctl option and like `--log-dir` on `inspect eval`,
`eval-set` and `log list` (decision: Ransom, 2026-09-24). The user docs give
the command forms.

- It takes a directory in any form Inspect reads (plain path, `file://`,
  `s3://`, other fsspec URLs). The given directory is the walk's root,
  whatever it is: pointed at a `<name>.shards/` companion or one `<k>/`,
  the mode lists that directory's logs as ordinary logs.
- One shared decorator (`_log_dir_option` in `_group.py`) adds it to `task
  list` and the six sample reads, so their help and behaviour cannot
  drift. Every other command lacks it, so `--log-dir` there is click's
  usage error (no `--json` envelope), and a command added later fails
  closed until it is implemented and decorated (decision: Ransom,
  2026-09-24). The bare nouns (`task`, `sample`) take it as they take their
  `list` verb's other options.
- It has no environment-variable mirror: a left-over variable would
  silently switch ctl from live processes to stale logs.
- `task list --shards` turns shard aggregation off: every `<name>.shards/`
  is walked as an ordinary directory, nested ones included, so each shard,
  the merged log and any stray `.eval` log is an ordinary row (`.json` logs
  stay in `unreadable`). The
  human output then leaves out the errored-samples footer, since a merged
  log's row holds its shards' samples and a sum over the rows would count
  them twice. In live mode `--shards` is accepted and does nothing
  (decision: Ransom, 2026-10-13).
- Human output starts with one stderr line naming the directory, the mode
  and its usual lag, worded as cadences, not bounds (`_log_dir.py`).

### Command inventory

| Command | With `--log-dir` |
|---|---|
| `task list` | Served; live-only fields are null ("Task rows"). |
| `sample list`, `sample errors` | Served; running rows have no activity fields, and `--active-since` is `unsupported` ("Sample rows"). |
| `sample show` | Served; a buffer row shows its manifest summary, without error history. |
| `sample events` | Served; a buffer row's events run up to the last buffer sync. |
| `sample messages`, `sample store` | Served for samples in the log; `unsupported` for a buffer row (decision: Ransom, 2026-09-23). |
| Every other command | No `--log-dir` option. |

The commands without the option are the mutations (cancel, pause, resume,
drain, requeue, scoring, log flush, keep and release, model pause and
resume) and the reads whose state exists only in the live process: `task
score --status` and `sample score --status` (pass state in memory), `process
list` (there are no processes), `sample agent list` (a live sample's
addressable agents), `process anomalies` (trace files on the
worker hosts), `model throughput` (an in-memory registry) and `config` (live
limiter and override state).

### Structured errors in the mode

Every failure goes through the `--json` error envelope
([`control-channel.md`](control-channel.md), the agent output contract).
The mode adds two values to the closed `kind` vocabulary, raised only under
`--log-dir` (`_ErrorKind` in `src/inspect_ai/_cli/ctl/_failure.py`):

- `unsupported`: an option (`--active-since`) or a read of one target
  (messages or store of a buffer row; a task known only from `.json` or
  stray logs) the logs cannot serve. The message names the reason and, for
  a buffer row, the `sample events --type model` command that shows its
  model calls. `exception` and `status` are null.
- `storage_error`: reading the directory failed, other than by absence,
  with an error the mapper recognizes (an `OSError` or a botocore error):
  permissions, credentials, throttling or transport; a log that kept
  changing under a read, or segments that kept disappearing, after the
  bounded re-reads ("Reading a member consistently"); or a name in a shard
  set that S3 would read as another key (the shared walk's
  `ShardSetError`). `status` is an S3 error's HTTP status when there is
  one. It is separate from `connect_error`, to which ctl maps every other
  `OSError`, because a missing object must not read as "the process is
  gone". A backend whose SDK raises its own exception types rather than
  `OSError` (Azure's, for one) fails as `internal`.

Existing kinds keep their meanings. A missing local directory or S3
bucket, a
selector with no match, a sample that has not started (or runs without a
shared buffer), and a log removed during the read are `not_found`. An S3
prefix holding no objects lists as an empty directory, as S3 has no
directories, so it gives no rows rather than `not_found`. Over a
directory that holds no task, the sample reads return their empty
result (an empty list or page, or null for `sample show`) before resolving a
selector, so an unmatched selector there exits 0 rather than
`not_found`. An
ambiguous selector is `ambiguous` through the same `_resolve_target_eval`
as live mode, run over the mode's rows; so is a sample key two shards hold.
A log that exists but does not parse, or a manifest or buffered events
that do not, are `invalid_response` for a single-target read. List reads
never fail on one bad log: they report it in `unreadable` with
`incomplete: true` on the row and the envelope, warn on stderr, and count
nothing from it. Both hold for the read and validation failures the reader
expects (`READ_FAILURES` in `snapshot.py`); an unexpected exception while
validating a malformed log can fail the whole command (`internal`) rather
than one log. `_fail_from`
in `_log_dir.py` holds the mapping; `test_cli_per_sample_failures_map_to_error_kinds`
and the `test_log_dir_*` contract tests in `test_ctl.py` check it.

### What the log directory holds while a run is live

The mode depends on how a worker writes, which it does not change:

- **The `.eval` log.** A running log has `_journal/start.json`, the
  `_journal/summaries/<n>.json` members the recorder has published
  (`src/inspect_ai/log/_recorders/eval.py`; a flush can add several), and
  no `header.json`; readers build its header from the start record and read
  every published summaries member. `header.json` and
  `summaries.json` are written when it finishes. Each flush replaces the
  whole object (on S3, a new ETag), so a completed sample reaches the log
  when its batch fills or the recorder's stale-flush timer fires, plus the
  upload (`src/inspect_ai/_eval/task/log.py`).
- **The shared sample buffer.** Only with `--log-shared`: the worker
  copies its local buffer database to `<log dir>/.buffer/<log stem>/` at
  most once per `log_shared` interval. `manifest.json` is rewritten on
  every sync and holds one row per sample still in the database, with its
  summary and its segment list; each sync adds a `segment.<n>.zip` with the
  rows added since (`src/inspect_ai/log/_recorders/buffer/`). A sample
  enters the manifest when it starts, with its start-time summary (no token
  or message progress until it completes). Rows are removed by sample key,
  by a flush, a discarded attempt or a requeue. **The flush handoff:** the worker writes the log before dropping
  the flushed rows, so a sample that leaves this way is already in the log
  when that write is published. A local intermediate write skipped on a
  file-in-use error (`write_local_snapshot` in
  `src/inspect_ai/log/_recorders/file.py`) still drops the rows, so the
  flushed record is in neither the log nor the buffer until a later write
  succeeds; readers see the key's earlier logged record if it has one
  (a requeue or seeded retry), otherwise `pending` or missing.
  **A discarded attempt:** a sample-level retry (`retry_on_error`), or a
  retry an interrupt turned into an abandoned attempt, removes the
  attempt's rows without logging it (`src/inspect_ai/_eval/task/run.py`), and a
  sync that races a removal leaves that sample out of its manifest. A
  retried key reappears with its new attempt on a later sync; an abandoned
  one is never logged. **A requeue** ([`sample-requeue.md`](sample-requeue.md))
  removes the prior attempt's rows before the re-run starts, while the
  prior record may still be waiting for its flush, and that flush later
  removes rows by the same key, the re-run's live row included
  (`src/inspect_ai/_eval/task/run.py`, `src/inspect_ai/_eval/task/log.py`).
  So a requeued key can read `pending` or absent until its prior record is
  published, and can then show that earlier record while the re-run is
  still active.
- **Cleanup.** A normal finish deletes the buffer. A hard-killed worker
  leaves its log `started` and its buffer in place, so a crashed worker
  cannot be told from a running one by status alone.
- **The recorded selection is a seed.** A log records the sliced dataset's
  ids (`eval.dataset.sample_ids`) at start, but a `SampleSource` can admit
  further samples without updating it, and older logs record no ids. Only a
  finished log counts every admitted sample: `EvalLog.total_samples`, and
  `results.total_samples` as the eval writes it. Rescoring with `inspect
  score` can replace `results` with counts over the samples present in the
  log, leaving only `EvalLog.total_samples` as the admitted count.
- **One key can have an older record in the log and a newer attempt in the
  buffer**, after a seeded retry re-runs a key it inherited or an
  in-process requeue re-runs a flushed key. Recovery resolves this by
  timestamps (`sample_record_time` in `src/inspect_ai/log/_recover/_api.py`),
  and so does this mode. Until a newer attempt's row is published (while
  the key waits to re-run, or throughout a run without a shared buffer),
  a seeded retry's inherited record is the key's state, and it can be
  terminal: an inherited error counts in `errored`, not `unfinished`.

### Walking the directory

`walk_log_dir` (`walk.py`) lists the directory without paging through
buffer segments or checkpoint objects, whose counts grow with run age:

- **One delimited listing per directory visited**, through
  `AsyncFilesystem.list_dir`, returning files and subdirectories together
  with size, mtime and (on S3) ETag. Locally it does not follow directory
  symlinks, so a symlink loop cannot hang the walk. Listings run
  concurrently up to a fixed cap (`walk.py`).
- **Buffer and checkpoint contents are never paged through.** `.buffer/`
  and `*.checkpoints/` are not listed: a buffer's presence in a directory's
  listing is recorded on the logs beside it, and a log's manifest path is
  derived as `.buffer/<stem>/manifest.json`. Every other subdirectory
  outside a companion is descended, as `list_eval_logs` recurses, so an
  eval-set directory or a directory of runs works.
- **Companions.** With shard aggregation (the default; `task list
  --shards` walks every `<name>.shards/` as an ordinary directory, "CLI
  surface"), the first `<name>.shards/` on each path below the root is
  a companion, listed by the shared `list_shard_set`
  (`src/inspect_ai/log/_shards/_walk.py`; [`eval-sharding.md`](../eval-sharding.md),
  "Layout" and "Code shared with ctl log-dir mode"): the companion and each
  `<k>/` in it, a directory named with digits only. For each `<k>/` it
  returns the `.eval` attempts and whether it has a `.buffer/`. The
  companion's stray entries (a log directly in it, a `.json` log in a
  `<k>/`, and any other directory directly in it, a dot-directory
  included, which is not listed) are reported in `unreadable`, never as
  rows or attempts (`test_stray_and_nested_logs_in_a_companion`); a
  second companion for a task id is reported as a whole, without its
  stray entries ("Logical tasks"). The
  merged log beside the companion, `<name>.eval` (matched by
  `merged_log_name`, which strips only `.eval`), belongs to the shard set
  rather than being an ordinary log. A `<name>-recovered.eval` beside it is
  an ordinary log, although checkpoints map it to `<name>.checkpoints/`
  (decision: Ransom, 2026-11-23; [`eval-sharding.md`](../eval-sharding.md),
  "Layout"; `test_a_recovered_log_beside_a_shard_set_is_an_ordinary_log`).
- **Nothing below a `<k>/` is listed** under shard aggregation. A shard's `scans/`, its
  `*.checkpoints/` and any companion nested there are not walked, so a log
  nested below a `<k>/` is not shown from a root above the companion; to
  see it, point `--log-dir` at the directory that holds it (decision:
  Ransom, 2026-11-23, superseding 2026-10-05;
  `test_the_walk_lists_shard_directories_once_and_no_deeper`). The merge
  lists the same entries, so ctl and the merge agree on which files are
  shard attempts and which entries are stray; the merge refuses a
  companion with stray entries, where ctl reports them.
- **`.eval` only.** `.json` logs are reported in `unreadable`
  (`_JSON_LOG_REASON` in `snapshot.py`): the format is deprecated, its
  reads are whole-file parses, and sharding is `.eval`-only.

### Logical tasks

The walk's logs are grouped into logical tasks, the rows of `task list`
(`index_log_dir` in `snapshot.py`). Each logical task has one or more
*attempts* and one *current* attempt, whose data the row and the sample
reads use. Attempts are grouped by the task id in their headers, so the
index reads the plan (central directory and header) of every ordinary
log, superseded attempts included, but no sample summaries or manifests;
those are read afterwards for current attempts only.

**Attempt order.** "Newest" is the shared `attempt_sort_key`: the
`{created}` timestamp prefix of the file name, then a `-recovered` copy
after the file it was recovered from (recovery keeps the original's prefix
and adds its buffered samples), then listing mtime. Names with no
timestamp sort by mtime alone, before timestamped ones. Mtime comes last
because a running older attempt's mtime moves on every flush.

**Unsharded logs.** Every other `.eval` file is an attempt of the logical
task identified by its header's `task_id`. Retries and `-recovered` copies
share it, and the newest attempt is current, as live `/tasks` folds
attempts by `task_id`.

**Sharded runs.** A companion whose listing has an attempt in at least one
`<k>/` is a shard set; one with none (only `scans/` or `.buffer/` objects
left after attempts were removed by hand) is dropped before grouping, its
merged log becomes an ordinary log and its stray entries are still
reported. The merge likewise treats such a companion as gone when it has
no stray entries, and refuses it when it has some. Nothing below its
`<k>/` directories is walked either. In a shard set:

- The shards are the `<k>/` directories with at least one `.eval` attempt,
  in shard order, and each shard's member is its newest attempt. Older
  attempts are superseded and not read, the merge's newest-wins rule. A
  `<k>/` with no attempt is not a shard and adds nothing
  (`test_a_shard_directory_with_no_attempt_is_not_a_shard`).
- The merged log is `<name>.eval`, when present. A recovered copy of it,
  `<name>-recovered.eval`, records the set's task id, so it is read as an
  unsharded log and becomes a newer attempt of the set's task (below).
- While the merged log or the first shard can be read, the set has the
  merge's task id (`merged_log_task_id`, shared with the merge) under any
  file name pattern, so it folds with a retry of its merged log
  (`test_a_shard_set_keeps_the_merges_task_id_with_or_without_its_log`).
  Without a readable merged log the id is computed with the current file
  name pattern, so this holds only while `INSPECT_EVAL_LOG_FILE_PATTERN` is
  the one the merge used, the merge's own condition
  ([`eval-sharding.md`](../eval-sharding.md), "The merged log").
- A task id has at most one shard set, the first companion by path. A
  second companion with the same task id contributes no sample state and is
  listed in the row's `unreadable` (decision: Ransom, 2026-10-13).

**A shard set and an ordinary log of its task.** Any unsharded log with a
shard set's task id is current over the set: an `eval_retry` of its
merged log, a recovered copy of it, or a copy `inspect score` wrote of it,
for example (shards keep their own task ids). Both fold into one logical
task, the shard set as its oldest attempt, so the unsharded log is current
whatever the file names say, and while it is, later progress in the
shards is not shown. A retry's `{created}`
follows the merged header's, minted at the merge, and can sort before the
launcher-minted merged log's name. The superseded shard set counts in
`attempts` and contributes no sample state, and the row's `shards` is null
as for any unsharded current attempt (decision: Ransom, 2026-10-13).

Only a logical task's current attempt contributes sample state. Finding
which set is duplicate or superseded needs each set's task id, so it may
read a skipped set's headers (`_add_shard_sets` and its tests hold the
read sequence).

**A merged log whose companion is gone** (shards deleted after a merge) is
an ordinary unsharded attempt.

**Unreadable logs.** An unreadable log the index needs is reported, never
dropped. One exception: a shard read only to find the task id of a set
that contributes no samples (one an unsharded attempt supersedes, or a
second set for a task id) is not reported when it fails. An unreadable current shard member belongs to its shard set by its directory, whatever
its file name, and blocks its task's per-sample reads
(`test_an_unreadable_shard_marks_the_row_and_blocks_sample_reads`).
Attributing an unreadable ordinary log to a task is best effort: it reads
the task name and id from fixed slots of the file name
(`_try_parse_filename`), not from the configured file name pattern. When
it names a readable task the log is listed on that task and can block its
per-sample reads; it can also miss the task, or name a wrong one, which
then appears as a task known only from unreadable logs; since selection
prefers an id match to a name match, its inferred id can take a selector
meant for a real task
(`test_an_unreadable_newer_attempt_blocks_per_sample_reads`,
`test_cli_a_task_whose_only_log_is_unreadable_reports_its_failure`).

**Identity.** For a shard set, `task`, `model`, `solver` and `epochs` come
from the first readable shard (else the merged log); `eval_id` and `run_id`
from the merged log, else null (each shard has its own); `log_location` is
the merged log, else the companion. The merge refuses shards that differ in
task identity; this mode only reports, so a shard whose task, model or
epochs differ from the first is counted in `shards.mismatched`
(`identity_row`, `_shards_block`).

**Selection and routing.** `_resolve_target_eval` runs over identity rows
built from the index alone (`_identity_rows`), so target resolution reads
no summaries or manifests. Every attempt of a `task_id` is in one row, so a
full task id resolves to exactly one row. Shards are not separately
selectable: the sample commands always aggregate, and `--shards` rows are
for `task list` only. An unmerged shard set has no `eval_id`, so every row
carries an additive `log_target` naming its logical task within the root
(`shards:<companion path relative to the root>`, `log:<task_id>`, or
`unreadable:<task_id>`); the sample commands pass the resolved row to the
reader, which looks the task up by it in the invocation's index, so the
directory is walked once per invocation
(`test_cli_two_shard_sets_route_by_their_targets`).

### Sample identity and source selection

One function decides where every sample key's current record is, and
`task list` counts, `sample list` rows and the per-sample reads all call it,
so they cannot disagree (`select.py`).

**Keys.** A sample key is `(str(id), epoch)`, the readers' deduplication
key. A logical task's key set is the union over its current members (one
log, or one current attempt per shard) of the recorded selection
(`dataset.sample_ids` times `epochs`, when recorded), the keys of the
member's summaries (`summaries.json`, or a running log's journal), and the
keys of its manifest rows (`known_keys`). Samples a `SampleSource` adds
enter the set when their summaries or manifest rows appear.

**Candidates within one member.** A *log record* is the member's summary
for the key (last row wins). A *buffer row* is its manifest row, running or
completed but not yet flushed. The buffer row wins when there is no log
record, or when it started after the log record's `sample_record_time`
(completion, else start): recovery's rule, which covers a seeded retry
re-running an inherited key and a requeue re-running a flushed one.
Otherwise the log record wins (`member_candidate`). For a requeue both
timestamps come from one worker; a seeded retry's inherited record was
written by the prior attempt, so the comparison shares recovery's
clock-skew limit.

**Selection** (`select_source`). A key with candidates in more than one
member (overlapping shards) is a `conflict`: members come from different
hosts, so no timestamps are compared across them. A key with one member's
candidate is `log` or `buffer`. A key with none (recorded but not started,
or started with no shared buffer) is `pending`. `log` and `buffer` map to a
status through the live row builder (`_summary_from_eval_sample_summary`):
a running buffer row is `running`, a completed one takes its summary's
terminal status.

**Totals.** The only total ctl treats as authoritative is a finished
unsharded current log's `results.total_samples` (`authoritative_total`,
`totals`). With one, `samples.total` is that total (or the known-key count
when larger, which is then not final) and `pending_unlisted` is the pending
samples it counts that no record names. Otherwise `samples.total` is the
known-key count, a lower bound: a running log, a finished log without
`results`, and every shard set report a lower bound, since shards that
have not started are not in the directory and ctl does not read the merged
log's recorded selection ("The merged log"). Recorded ids do not matter
here: a finished log that records none still has an authoritative total.

As the eval writes it, `results.total_samples` counts every admitted
sample, dynamically admitted ones included. After a rescore that replaced
`results` with counts over the logged samples, it counts only those, and
ctl, which does not read `EvalLog.total_samples`, reports that smaller
total as final: admitted samples that never reached the log and are not in
the recorded selection (a drained or cancelled run's queued samples, keys a
`SampleSource` admitted) are then counted nowhere, and `unfinished` can
read 0 for an incomplete run.

### Reading a member consistently

A member's log and its manifest are separate objects written at different
times, and the log itself is replaced on every flush. The mode assembles
each member's view so that a torn read never becomes missing or pending
data (`read_member` in `snapshot.py`, `consistency.py`):

- **The log is observed after the manifest.** For a running member that may
  have a shared buffer (its header has `log_shared` and the walk saw a
  `.buffer/` beside it), the manifest is read first, then the log's current
  version is checked with one metadata request (`log_version`); the plan's
  central directory is reused only if it came from that version. Because
  the flush handoff writes a sample to the log before dropping it from the
  manifest, a key the manifest held that left it by a published flush is
  reported from the manifest, the log, or both, never as pending or
  missing; a later key appears on the next poll. The guarantee depends only
  on reads made in the invocation, so concurrent pollers and stale or lost
  cache entries can cost extra reads but cannot weaken it
  (`test_a_key_flushed_after_the_plan_read_is_read_from_the_log`,
  `test_a_key_admitted_to_the_manifest_of_an_unchanged_log_is_found`).
  It relies on the version check being fresh and identifying the log's
  content, as it does for local and S3 logs. Other fsspec backends answer
  it from whatever metadata they report (Azure can answer from its listing
  cache), so within one invocation they can keep a stale view of a log and
  miss a key flushed after it. Members with no manifest have no second
  object to order against. A skipped local write ("What the log directory
  holds while a run is live") withholds the latest record until a later
  write succeeds: the key reads as its earlier logged record if it has one,
  otherwise `pending` or missing.
- **A retried key can drop out between syncs.** A key whose attempt was
  discarded for a sample-level retry is in neither object until a sync
  publishes its new attempt ("What the log directory holds while a run is
  live"). Until then it reads as the log's earlier record of the key if
  there is one, `pending` if only the recorded selection names it, and is
  absent otherwise, although an earlier poll may have shown it running.
- **Mixed versions.** A central-directory read and a member read are
  separate range requests. On S3 the central directory's own reads are
  pinned to one object version. Every member read, whole or streamed, is
  checked against the central directory's CRC-32. A CRC mismatch, a changed
  object under a pinned read, or a decompression or parse error re-reads
  the central directory and the member a bounded number of times
  (`read_consistently` in `consistency.py`); bytes that pass their CRC
  check and still do not validate are an unparsable log, not a torn read. A
  sample read through a fresh central directory re-reads the sample's
  summary from that version too, so the two never describe different
  records.
- **The manifest.** A manifest that does not parse is re-read the same
  bounded number of times, then handled as "When the re-reads are exhausted"
  below says (the filestore in
  `src/inspect_ai/log/_recorders/buffer/` owns how a sync publishes it). A manifest
  that is gone reads as no manifest, and the log read after it then serves
  the flushed samples. A segment that is gone during an events read (the
  worker deleted its buffer after the final flush) sends the read back to
  source selection, manifest then log, so a sample flushed meanwhile is
  served from the log (`test_a_segment_removed_mid_read_re_selects_the_flushed_record`).
- **When the re-reads are exhausted**, list reads keep the other members
  and report the member in `unreadable`. Per-sample reads fail naming the
  object: `storage_error` when it kept changing, `invalid_response` when
  consistent bytes kept failing to parse ("Structured errors in the
  mode").
- **Per-sample reads use the invocation's member views.** Before
  answering, a per-sample read reads every current member's view as a list
  read does, and fails with a member's error rather than answer while any
  member that might hold the key is unread (`_locate` in `samples.py`). A
  member's view is as fresh as the rules above make it: only a member with
  a manifest has its log's version checked against the plan the index
  read. For any other running member, a flush after the index read can go
  unseen within the invocation, so a key flushed then can read `pending` or
  `not_found` until the next invocation.

### Task rows

A log-dir task row has every key of a live row, so existing parsers keep
working (`task_row` in `snapshot.py`;
`test_finished_log_row_has_every_live_key_and_counts`). Over the current
attempt:

| Key | Log-dir value |
|---|---|
| `run_id`, `eval_id`, `task`, `task_id`, `model`, `solver`, `epochs`, `log_location` | From the plans ("Logical tasks"). |
| `status` | `running` if any current member is `started`, or could not be read and may be; else `completed`. |
| `started_at` | The earliest sample start seen (each holder of a conflicted key included), else the earliest member's `created`. |
| `completed_at` | The latest member completion when none is running, else null. |
| `samples.total` | "Totals" above. |
| `samples.completed`, `errored`, `cancelled` | Keys whose selected record has that status. |
| `samples.in_flight` | Keys selected as running buffer rows; null unless every running member's manifest was read. |
| `samples.queued` | Null: dispatch state is not in the logs. |
| `total_tokens`, `total_messages`, `tokens_per_second` | Sums over the selected summaries, and their rate; running samples add nothing until they complete, because their buffer summary is the start snapshot. |
| `attempts` | The task's attempts, unreadable ones included (a shard set counts as one). |
| Live-only fields (`paused`, `quiesced`, `held`, `resolving`, `refusals`, `http_retries`, `keep_alive`, `pid`, `socket_path`, ...) | Null (`paused_models` an empty list). |

Additive keys, present on every log-dir row: `source` (`"log_dir"`),
`log_target`, `current_attempt` (`"log"` or `"shards"`), `updated_at` (the
latest of the current members' listed log mtimes and the Last-Modified of
the manifests read; with `status: running`, a long-quiet `updated_at` is
the only sign a worker died, and the human output flags rows quiet past a
fixed threshold, `_print_quiet_footer`), `live_samples` (`buffer`, `none`
or `partial`: whether every, no or some running member's running samples
are visible), `shards` (null unless the current attempt is a shard set:
counts of shards by log status, `overlapping` and `mismatched`), and
`incomplete` and `unreadable`. `samples` gains `conflicted` (keys held by
more than one shard, counted in no status), `unfinished` (`total` minus the
terminal and conflicted counts, never negative because `total` is at least
the known-key count), `total_final` and `pending_unlisted`. The human
output adds a note that a sharded task's totals cover only the shards found
so far.

### Sample rows

`sample list` and `sample errors` build one row per key from its selected
record with the live row builder, then apply the live filters, sort, cap
and `--content` gating (`sample_listing` in `snapshot.py`). Differences
from live:

- Pending rows come from known keys with no record; pending samples counted
  only by an authoritative total add to `counts.pending` without rows.
  There are no `queued` rows.
- Running rows have `activity`, `events`, `interrupt` and `last_activity_at`
  null and zero usage (the start snapshot).
- A conflicted key yields one row per shard holding it, each with that
  shard's status and `conflict: true`. `counts` counts distinct keys and
  leaves conflicted keys out, and the envelope gains `conflicted`. The human
  footer of a capped listing counts the conflict rows, and also the
  pending samples an authoritative total counts without rows, so its "of
  N" is the number of rows `--all` returns only when there are none of
  those (`test_overlapping_shards_are_conflicts`,
  `test_cli_capped_sample_list_counts_conflict_rows`).
- Rows add `shard` (`<k>` or null), `log_location` (the member log holding
  the chosen record, to hand to `inspect log` commands) and `conflict`; the
  envelope adds `conflicted`, `incomplete` and `unreadable`.
- **`--active-since` is `unsupported`.** Callers feed the previous
  listing's `as_of` back as the next lower bound, and the filter compares
  sample activity times; a sample that completes before one poll but
  reaches the log only after it would carry a time older than the next
  bound and never be returned.

### Per-sample reads

`sample show`, `events`, `messages` and `store` resolve the task, locate the
key in the members' views ("Reading a member consistently") and act on the
selection (`samples.py`):

- **`log`**: the sample member is read with the field exclusions the live
  terminal paths use (the events read takes the whole member) and built
  into the same envelope through the shared projection and paging code
  (`page_events`, `page_messages`, `page_store` and the terminal sample
  detail, shared with the live routes;
  `test_per_sample_reads_equal_the_live_terminal_envelopes`).
- **`buffer`**: `sample show` returns the manifest summary (no
  `error_retries`; the error message under `--content`). `sample events`
  reads every segment the manifest lists for the sample and rebuilds its
  events with recovery's `reconstruct_events`, since pooled references can
  point into earlier segments; the page is `done` only for a completed row.
  Its cursor nonce is prefixed with `buffer:` and names the attempt's
  start, so when the record moves to the log, or to another attempt, an old
  cursor is foreign and the read restarts at 0: duplicates, never gaps
  (`test_a_retry_attempts_cursor_restarts_on_the_next_attempt`). `sample
  messages` and `sample store` fail `unsupported` (decision: Ransom,
  2026-09-23): the buffer holds no message list, and ctl does not read the
  final-store sidecar a completed row may have. The message says whether
  the sample is still running or waiting for its flush.
- **`pending`**: `not_found`, saying the sample has not started, or that it
  may be running without a shared buffer and `--log-shared` would show it.
- **`conflict`**: `ambiguous`, naming each log holding the key so the caller
  can read them with `inspect log` commands.

### The merged log

ctl finds shard sets by the layout and takes sample state from the shards,
which are current to their last flush while the merged log exists only
after a merge and lags them. It reads the merged log's plan only (central
directory and header): for the shard set's task id and the row's `eval_id`,
`run_id` and `log_location`. It does not read the merged log's samples or
summaries, or the `eval.shards` ledger, and it never recomputes whole-task
metrics, which need the trusted merge
([`eval-sharding.md`](../eval-sharding.md), "Results"). A merged log that
is the current attempt (its companion gone, or an attempt-less companion)
is an ordinary log, read like any other.

### Cache

A local, per-user cache makes a steady-state poll cost a listing plus reads
of what changed (`cache.py`):

- **Location.** One file per log, keyed by the log's URI, in an owner-only
  directory under `inspect_data_dir("ctl")` ([user
  docs](../../docs/control-channel.qmd#reading-a-log-directory)).
- **What is cached.** A log's plan, with the version it was read from (the
  S3 ETag, or a local stat), recorded only when the log did not change
  during the read. A finished log's plan is reused while the listing
  reports that version, and its parsed summaries with it. A running log's
  central directory is read on every poll; its header and each parsed
  journal member are reused while the fresh central directory lists the
  member unchanged, so a poll costs the central directory plus the journal
  members added since. Manifests, sample members and segments are not
  cached.
- **Pure performance.** Every cached value is keyed by a finished log's
  version or by the CRC-32 and size of the member it came from, and entries
  are stored only from reads that passed their consistency checks, so
  every cached value describes a validated version of its source, and while
  the sources do not change the cache changes what is fetched, never what
  is returned
  (`test_cli_cache_entries_change_what_is_fetched_never_what_is_returned`).
  When a finished log is rewritten during an invocation (a rescore, say), a
  warm read keeps the version the listing accepted at indexing, where an
  uncached read can advance to the rewrite; both are real versions.
  Concurrent pollers may overwrite each other's entries in either order;
  every surviving entry describes a real version of its log.
- **Writes** are atomic, once per log per invocation, into the existing
  directory, which a write never recreates. Any cache failure turns the
  cache off for the rest of the invocation and never changes output
  (`test_after_a_cache_failure_a_replaced_log_is_read_as_uncached`,
  `test_cli_cache_entries_change_what_is_fetched_never_what_is_returned`).
- **Backends.** Only local and S3 logs are cached: only their version names
  their content. Other backends' metadata can stay the same across a
  rewrite, so their logs are read in full on every poll
  (`test_a_same_size_azure_rewrite_is_read_again`).
- **Bounds.** Least-recently-used entries are pruned above a fixed size
  limit.
- **Limits.** Other local users or processes tampering with the cache
  directory are out of scope; a cache operation that fails on another
  Inspect version's journal layout falls back to an uncached read.

### Cost

On S3, with reads issued concurrently on one `AsyncFilesystem`:

- **The walk** costs one LIST per directory visited (per 1,000 entries):
  `N + 2` for a sharded run of `N` shards (the root, the companion, each
  `<k>/`), whatever the workers wrote in their `<k>/` (buffers,
  checkpoints, scan results). `task list --shards` walks the companion as
  ordinary directories, so it also lists what lies below each `<k>/`
  other than buffers and checkpoints.
  A recursive listing would page through every segment object, about
  100,000 keys after an hour of 300 shards syncing every 10 seconds.
- **A finished log**, read cold, costs its central directory,
  `header.json` and `summaries.json`; warm and unchanged, nothing beyond
  the listing.
- **A running log** costs its central directory on every poll plus the
  journal members added since; with a shared buffer, its manifest and one
  HEAD to check the log's version.
- **Superseded ordinary attempts** cost their plan, which grouping needs
  ("Logical tasks"): nothing when finished and warm, a central directory
  per poll while still `started`, so accumulated retries add to every
  poll.
- **A per-sample read** costs the same key refresh as a list read of its
  task, plus the sample member (and its central directory when not already
  read this invocation) and, for a buffer row, one GET per listed segment. A logged sample's events are re-read and
  parsed on every page invocation, on the caller's machine rather than on
  an eval's event loop.

For the target case, 300 one-sample shards with `--log-shared`, a cold list
read is 302 LISTs and about 1,200 GETs and HEADs while every shard runs, or
900 GETs once all have finished; a warm read of a finished, unchanged run
is 302 LISTs and nothing else; a warm read while every shard runs is 302
LISTs, 600 small GETs (central directory and manifest) and 300 HEADs. Tests
assert these formulas with a request counter on `mock_s3`
(`test_s3_walk_of_a_shard_set_lists_each_shard_once`,
`test_s3_request_counts_for_list_and_sample_reads`,
`test_s3_request_counts_for_buffer_reads`,
`test_s3_request_counts_with_the_cache_for_finished_logs`,
`test_s3_request_counts_with_the_cache_for_running_logs`). Data is no
fresher than the workers' flush and sync cadences; the user docs give the
polling guidance, weighing request cost against seeing each buffer sync.

### Code shared with live mode and the merge

- With live ctl: the selector resolution, row builder, status vocabulary,
  filters, sort and cap (`src/inspect_ai/_control/state.py`), and the
  events, messages and store paging (`page_events` in `events.py`,
  `page_messages` in `messages.py`, `page_store` in `store.py`), which the
  live routes call too. The CLI branches at its existing fetch seams in
  `_fetch.py`, `_task.py` and `_sample_read.py`, so rendering, resolution
  and envelopes are the live ones.
- With the sharding merge: the layout name rules and `merged_log_task_id`
  (`log_layout.py`), the shard-set walk and attempt order
  (`log/_shards/_walk.py`), the delimited listing and the CRC-checked zip
  reader ([`eval-sharding.md`](../eval-sharding.md), "Code shared with ctl
  log-dir mode"). Both take a shard to be a `<k>/` named with digits only;
  the merge refuses a companion's stray entries, which ctl reports in
  `unreadable`.
- With the sample buffer and recovery: the `Manifest` model and the pure
  segment parsing and merging of `SampleBufferFilestore`
  (`segment_sample_data`, `merge_sample_data`), and recovery's
  `sample_record_time` and `reconstruct_events`. The reader does its own
  I/O through `AsyncFilesystem` (`buffer.py`), because the filestore's
  readers use synchronous fsspec I/O, which cannot run in a worker thread on
  a remote filesystem.

## Guarantees and limits

- **Read-only, no code.** No supported command changes the directory's
  files, bytes or mtimes (`test_read_only_commands_leave_the_directory_unchanged`,
  `test_cli_read_only_over_a_shard_set`,
  `test_cli_buffer_reads_leave_the_directory_unchanged`), and none resolves
  scorers or imports task code (`test_cli_never_resolves_scorers_or_imports_task_code`).
- **Fails closed.** The commands carrying `--log-dir` are exactly the
  served set, and every other leaf command rejects it as a usage error
  before any storage or discovery call
  (`test_log_dir_option_is_on_exactly_the_log_dir_commands`,
  `test_other_commands_reject_log_dir_as_a_usage_error`, parametrized over
  the command tree).
- **One source per key.** Every read reports the same record for a key, also
  while a re-run attempt runs, completes and is flushed
  (`test_every_read_follows_a_re_run_key_through_its_attempt`).
- **No key lost to a torn read.** On local and S3 logs, a key that leaves
  the manifest through a published flush is reported from the manifest or
  the log, never as pending or missing (a skipped local intermediate write
  withholds the latest record until a later write succeeds, showing an
  earlier logged record or none); a mid-read replacement is re-read, and an exhausted
  re-read is reported, never turned into missing data
  (`test_read_consistently_retries_torn_reads_then_succeeds`,
  `test_exhausted_re_reads_fail_the_read_and_mark_list_reads_incomplete`,
  `test_s3_a_log_replaced_during_a_large_central_directory_read`).
- **The cache affects cost only** while the sources are stable: a finished
  log rewritten during an invocation can be reported at its indexed
  version when warm and at the rewrite when cold, each a validated version
  ("Cache"). Steady-state polls read only what changed ("Cost").
- **Agreement with the merge** on which files are shard attempts and which
  entries in a companion are stray, through the shared walk, and on the
  task id of a shard set with no readable merged log while its first shard
  is readable and the file name pattern is unchanged ("Walking the
  directory", "Logical tasks").
- **Limits.** Data lags the workers by their flush and sync cadences, which
  are not bounds: a failed upload, a stopped worker or a retuned
  `log_shared` stretches them, and nothing records a heartbeat. Without
  `--log-shared`, running samples are invisible. A running sample shows no
  token or message progress until it completes. A crashed worker's log
  stays `started`; only `updated_at` hints at it. A key retrying after an
  error drops back to its earlier record, `pending` or absent until a sync
  publishes its new attempt; a requeued key can read `pending` or absent,
  or show its earlier record, while its re-run is active, and a seeded
  retry's inherited record, an error included, stands until a newer
  attempt is published ("What the log directory holds while a run is
  live"). A sharded task's total is a lower bound; a
  rescored finished log's total can count only its logged
  samples and still read final ("Totals"). The mode shows no whole-task
  metrics, for sharded or unsharded tasks. Messages and store of a buffer
  row, and `--active-since`, are unsupported. `.json` logs are not read.

## Alternatives considered

- **Relay or proxy the control channel** (socket forwarding, a TCP bridge,
  an outbound relay). Full live semantics, mutations included, but the
  premise is that the operator cannot reach the workers, and a relay is new
  networked infrastructure needing the authenticated remote attach
  [`security.md`](security.md) leaves for later ("Future hardening"). It
  also multiplies the fan-out: 300 relayed connections per poll. This mode
  does not preclude it; mutations need it.
- **Workers push a status object to storage** every N seconds. Fresher,
  with live-only fields and a heartbeat that tells a crashed worker from a
  running one, but a new writer and persisted format on every worker,
  largely duplicating the buffer manifest, and the sharding layout keeps
  companions to `.eval` files and their buffers. The natural next step if
  crash detection or running-sample progress prove to matter.
- **Transparent fallback** to logs when no live server is found. A silent
  switch from live to stale semantics, and with no process ctl cannot know
  which directory to read.
- **A root option on the `ctl` group** (`inspect ctl --log-dir <dir> task
  list`), with a structured `unsupported` for every other command. Every
  other ctl option and `--log-dir` elsewhere in Inspect go after the
  command, and a usage error is the
  ordinary answer to an option a command does not take (decision: Ransom,
  2026-09-24).
- **Reuse `list_eval_logs` and `read_eval_log_headers`.** Fine for a small
  local directory, but on S3 the recursive listing pages through every
  buffer segment and checkpoint object, and the header read fetches every
  file on every poll. The zip readers underneath are reused.
- **A recursive listing**, cheaper early in a run (one or two pages instead
  of `N + 2` LISTs). Its cost grows with run age and sync frequency; the
  delimited walk's only with shard count.
- **Descend below a `<k>/`** (`scans/` and other ancillary directories),
  listing nested logs as ordinary logs, to agree with `eval_set()` on the
  same root, at two LISTs per shard for one scan's output. Dropped
  (decision: Ransom, 2026-11-23, superseding 2026-10-05): `eval_set()` now
  refuses a directory that holds shards, so there is nothing to agree with.
- **Read only the merged log.** One file, with whole-task metrics, but it
  exists only after a merge and lags the shards during the window this
  mode serves.
- **Roll up whole-task metrics from shard summaries.** Lossy for custom
  metrics, needs metric code, and duplicates the trusted merge.
- **Read the local SQLite buffer when present**, as the viewer does. It
  exists only on the worker host, where the live control channel is the
  better tool, and opening a live writer's database from a second process
  adds locking concerns.
- **Take a finished shard set's `task list` row from the merged log's
  summaries when the merged log's shard ledger shows it covers the listed
  shards.** Dropped (decision: Ransom, 2026-11-23): one reader path for the
  row is worth about 900 small GETs on the first cold `task list` of a
  300-shard run, which the warm cache avoids afterwards.
- **Messages for buffer rows** rebuilt from buffered model events (what
  `inspect log recover` produces). Every segment of the sample on every
  call; `sample events --type model` is the pointer the `unsupported` error
  gives (decision: Ransom, 2026-09-23).
- **Per-shard rows by default.** A 300-row default would flood an agent's
  context; one logical row per run is the default and `--shards` lists the
  shards (decisions: Ransom, 2026-09-23 and 2026-10-13).

## Compatibility

- **CLI.** `--log-dir` on `task list` and the six sample reads, and `task
  list --shards` (a no-op in live mode). Other commands reject `--log-dir`
  as a usage error. Live-mode behaviour, envelopes and exit codes are
  unchanged.
- **`--json` contract.** The closed `kind` vocabulary includes
  `unsupported` and `storage_error`, raised only in the mode. Rows have
  every live key (live-only values null) plus the additive keys above.
  A consumer that treats a null `in_flight` as zero would under-report,
  which `unfinished` and `live_samples` exist to prevent; `total_final` and
  `pending_unlisted` say when `total` is a lower bound. A consumer polling
  with `--active-since` gets `unsupported` and must poll full listings.
- **Control API.** Unchanged: the mode talks to no server.
- **Stored formats.** None written. Logs written by older versions read as
  they do through the log readers; manifests with bare segment ids (written
  before segment cursors) are read through the filestore's segment-id
  helper.
- **Viewer and generated types.** Unaffected.
- **Local state.** The cache directory under `inspect_data_dir("ctl")`,
  safe to delete at any time.

## Security

The mode reads a directory the user names, with the user's own storage
credentials. The content threat model of [`security.md`](security.md)
applies with a different transport:

- **Untrusted content reaches the CLI as before.** Sample summaries, error
  messages, events, messages, store values and the file and directory names
  in the log directory are agent-influenced or writable by anyone who can
  write the bucket. They go through the same projections, the
  metadata-only default with `--content`/`--full` opt-ins, and the same
  sanitizing output for human rendering, shard and file names included
  (`test_cli_human_output_sanitizes_hostile_file_names`). A suggested
  command built from a log's task id or the directory (the `sample events`
  hint, the `sample errors` footer) is given only when every argument is
  printable, otherwise with placeholders (`_command_hint`;
  [`security.md`](security.md)).
- **No code execution.** The mode never recomputes metrics, never resolves
  scorers or imports a header-named task file, never runs recovery and
  never merges. Stored per-sample scores are shown as stored; whole-task
  metrics are not shown.
- **Read-only.** Nothing is written to the log directory: no buffer cleanup,
  no recovery output, no merge. Buffer objects are read through
  `AsyncFilesystem` only. Local writes go only to the owner-only cache
  directory.
- **Paths come from the listing, not from content.** Manifest and segment
  paths are derived from listed names by fixed rules
  (`.buffer/<stem>/manifest.json`, `segment.<n>.zip` from the manifest's
  integer segment ids). The merged log is matched by name to a listed
  companion; nothing recorded in a log locates a file. The local walk does not
  follow directory symlinks, and a name in a shard set that S3 would read
  as another key is refused.
- **Hostile or oversized inputs** cost memory and bandwidth on the caller's
  machine, as the same files do for the log readers and the viewer; list
  reads parse only headers, summaries and manifests. Nothing runs on an
  eval's event loop.
- **Access.** No listener, socket or network path. Anyone who can read the
  directory could already read everything the mode shows. Limiting
  `--log-dir` to the read commands is not a security boundary (the mode has
  no write path); it keeps a mutation from ever running against a
  directory.
- **Cache.** Owner-only (a write never recreates a deleted directory),
  keyed by URI and version, and re-parsed through the same models on read. A same-user attacker who
  can edit it is out of scope, as for the discovery directory.

## Not this design

- **A `merged` block and a shard set's total from the merged header.** The
  merged log's header, which ctl already reads for the task id, records its
  status, merged sample count and stored whole-task metrics, and the
  intended selection it merged against (an id list or a count). A row
  could show them as of the merged log's mtime and, when the merge
  recorded an id list or a count (not `selection: none`), use it as the
  shard set's authoritative total (an id list would also make shards that
  have not started enumerable as pending rows). Cheap, optional, and not
  built.
- `sample store` for a completed buffer row could read the row's
  final-store sidecar (`SampleBufferFilestore.read_sample_store`, which
  recovery uses); today it is `unsupported`, and its message says the store
  is not in the shared buffer.
- Reading `EvalLog.total_samples` for a finished log would keep a rescored
  log's total at its admitted count ("Totals").
- A sample-level retry's key drops out of the published state until the
  next sync; keeping the discarded attempt's row until its successor is
  synced would close the gap for every buffer reader.
- `AsyncZipReader` reads a fixed-size suffix to find every central directory,
  which dominates the bytes of reading many small logs (the viewer and
  header reads pay it too); a smaller first read with a fallback would cut
  it.
- `list_eval_logs_async` on S3 pages through every `.buffer` segment and
  checkpoint object under a directory (the viewer's listing pays this for
  any directory with `--log-shared` runs); a delimited walk like this one
  would bound it.
- `SampleBufferFilestore` reads through synchronous fsspec, so this reader
  keeps its own async I/O around the shared parsing helpers; an
  async-capable filestore would give the viewer and this mode one reader.
- `SampleBufferFilestore.running_tasks` works only on local directories,
  although shared buffers exist mainly for remote ones.
- A running sample's buffer summary is its start snapshot, so no reader,
  the viewer included, sees its token or message progress until it
  completes; a periodic summary refresh in the buffer would fix it for every
  reader.
- Manifest reads are unconditional (`read_manifest` in `buffer.py`);
  `If-None-Match` revalidation would make an unchanged running shard's
  manifest read a 304.
- A crashed worker's log stays `started` forever; a heartbeat in the buffer
  manifest, or the status-push alternative above, would let every reader
  tell crashed from running.
- A degraded `config` view from a log's launch `EvalConfig` and persisted
  `ConfigUpdate` records.
- A publication-keyed delta for `sample list` (a watermark over log and
  manifest changes rather than sample times), which would make
  `--active-since`-style polling safe against flush delay.
- Member reads pinned to the central directory's ETag in `AsyncZipReader`,
  which would turn a mid-read replacement into an explicit error for every
  reader instead of relying on the CRC check.
