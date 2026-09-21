# Eval sharding with per-worker log files

Status: design direction chosen, last revised 2026-09-21. Phase 1 compared
the options (now under "Alternatives not taken"); the phased direction below
was agreed by Ransom and JJ Allaire on 2026-09-18 and refined by Ransom on
2026-09-21, including the shard layout: shards live in a companion directory
beside the merged log, `<dir>/<name>.shards/<k>/`, mirroring sandbox
checkpointing's `<name>.checkpoints/` (Ransom, 2026-09-21). The first
implementation ships no launcher: merging is done through a Python API, a
CLI command, or `eval_set()` at startup (Ransom, 2026-09-21). No API
signatures or implementation plan yet; those are the next document. Open
decisions are listed under "Open questions".
Issue: https://github.com/meridianlabs-ai/inspect_ai/issues/509.
Author: agent (Claude), reviewed by Codex; see the PR.

## Why

Users split a task's samples across workers (down to one sample per machine)
so a large or slow task finishes in wall-clock time a single process cannot
reach. Inspect already lets a worker run a subset of a task's samples:
`eval(sample_id=...)` and `eval(limit=(start, end))` slice the dataset, and an
eval-set worker in selection mode can be handed a different `sample_id` or
`limit` override (`src/inspect_ai/_eval/eval_set_overrides.py:207-220`). What
is missing is the other half: each worker writes its own `.eval` file, and
nothing in Inspect knows that those files are pieces of one task. Every
reader treats a shard as a complete, independent eval:

- **Viewer.** The log listing is one row per file (`LogHandle` in
  `src/inspect_ai/_view/common.py:101-120`), so a task sharded 50 ways shows
  as 50 rows named for the same task, each with its own accuracy over its own
  samples.
- **Metrics.** `results.scores[].metrics` in each shard header are computed
  over that shard's samples only. Anything that is not a plain mean
  (`stderr`, bootstrap CIs, grouped metrics, reducers over epochs) has no
  whole-task value anywhere on disk.
- **Python API.** `read_eval_log`, `read_eval_log_sample_summaries` and
  `read_eval_log_samples` take one file (`src/inspect_ai/log/_file.py:539`,
  `:982`, `:1037`). `evals_df` produces one row per shard; `samples_df`
  happens to work because it concatenates samples across the logs it is given
  (verified: two 3-sample shards give 2 eval rows and 6 sample rows).
- **Eval sets.** `task_identifier` ignores `sample_id` and `limit`
  (`src/inspect_ai/_eval/evalset.py:2058`), so all shards of a task have the
  same identifier while each carries a fresh `task_id`. The pairing and
  completeness logic then misbehaves in both directions (see "Current
  behaviour"): without a selector it re-runs the task from one shard and
  orphans the rest; with a selector whose count matches the shard size it
  declares every shard complete, including shards holding other samples.
- **Scout and downstream tools** see N transcript sources for one task, with
  N sets of eval metadata.

## Goals and constraints

Goals:

- A user or runner can shard one task's samples across processes and
  machines, each writing its own log, without hand-rolled post-processing.
- Inspect's readers (Python log API, dataframes, viewer, eval-set
  bookkeeping, Scout) see one canonical log per task with one set of
  whole-task results.
- Old, unsharded logs keep working unchanged, and a shard is still a valid
  `.eval` file that today's tooling can open on its own.

Constraints and decisions that shape the design:

- **Self-contained logs, relaxed for sharded output only.** The #420 design
  adopted the constraint that *every log file stays self-contained, and the
  newest log for a task stays the whole truth about that task*
  (`design/retry-seeded-attempt-log.md:19`). Decision (Ransom, 2026-09-18):
  this feature may relax it, and it continues to hold in every other case.
  The boundary of the relaxation is the `<name>.shards/` companion directory (Ransom,
  2026-09-21): a file outside such a directory is an ordinary log, and
  copying a shard out of it makes it an ordinary partial log. Unsharded logs
  and the retry rule keep today's semantics.
- **Readers are many and some have no server.** The viewer parses `.eval`
  zips in the browser via byte-range requests (`/log-bytes/{log}`,
  `src/inspect_ai/_view/fastapi_server.py:258`; the client's
  `remoteLogFile.ts` reads `header.json`, `summaries.json` and
  `samples/*.json` from the zip's central directory itself). The same client
  runs inside VS Code and in static bundles written by `bundle_log_dir`
  (`src/inspect_ai/log/_bundle.py:79`), where there is no Python at read
  time. The browser client can only ever read stored results
  (`remoteLogFile.ts:420-429`).
- **Whole-task results need Python, the metric code, and trust.**
  `eval_results` (`src/inspect_ai/_eval/task/results.py:90`) takes sample
  scores plus scorer, metric and reducer definitions that the header records
  only by *name*: `metric_from_log` instantiates registered Python metrics
  (`src/inspect_ai/_eval/score.py:590`), and `resolve_scorers_info` falls
  back to importing the header's `task_file` when a metric name is not
  registered (`score.py:653-665`). Today scoring, metric recomputation
  (`recompute_metrics`, `src/inspect_ai/log/_metric.py:39-41`, and by default
  `edit_score`, `src/inspect_ai/log/_score.py:146-147`) and recovery
  (`src/inspect_ai/log/_recover/_write.py:270-285`) can load task code, and
  recovery also runs during eval-set resume and eval retry
  (`_eval/evalset.py:1494`, `_eval/eval.py:1697-1708`). Ordinary log reads
  deserialize stored results. Decision (Ransom, 2026-09-21): the merged log
  is created only by a trusted Python step, never by a reader.
- **Summaries are a lossy input for recomputation.** `EvalSampleSummary`
  keeps score *values* but truncates score `answer`, `explanation`, `reason`
  and metadata and thins sample metadata (`thin_data`,
  `src/inspect_ai/log/_log.py:371-400`; `thin_metadata`,
  `src/inspect_ai/log/_util.py:147`), while metrics receive the full
  `SampleScore` including `sample_metadata` (`scorer/_metric.py:245-254`;
  `results.py:601`). A custom metric reading anything but `value` computes a
  different number from summaries than from samples (an answer-length metric
  returned 2000 from the sample and 3 from its summary). Decision (Ransom and
  JJ Allaire, 2026-09-18): the merge recomputes from full samples.
- **An external runner protocol already exists.** Capture and selection mode
  (`src/inspect_ai/_eval/eval_set_manifest.py`,
  `src/inspect_ai/_eval/eval_set_selection.py`; PRs #5076, #5134, #5147,
  2026-08) let a runner enumerate an eval set and launch one worker per task
  into a shared log directory, with per-worker `log_dir`, `sample_id` and
  `limit` overrides. Its invariant is one task, one log
  (`eval_set_selection.py:16-18`); sample sharding is the case it excludes,
  and the runner is the natural launcher for the design below.

Non-goals for this document: API signatures, exhaustive edge cases, an
implementation plan.

## Current behaviour

Verified by reading the code at e4b8ad59d8 and by running a six-sample mock
task twice with `--sample-id s0,s1,s2` and `--sample-id s3,s4,s5` into one
log directory, then running `inspect eval-set` over that directory.

**Slicing.** `slice_dataset` (`src/inspect_ai/_eval/task/util.py:143`) applies
`limit` (int or `(start, end)` tuple) or `sample_id` (ids, `task:id`
selectors, `fnmatch` patterns). `eval()` forbids `sample_id` together with
`limit` or `sample_shuffle` (`src/inspect_ai/_eval/eval.py:906-910`). Both
selectors choose whole samples; every epoch of a chosen sample runs in the
same process.

**What a shard records.** `TaskLogger.__init__`
(`src/inspect_ai/_eval/task/log.py:242-308`) writes `dataset.samples` = the
full dataset size (6 in the spike), `dataset.sample_ids` = the sliced ids,
`config.sample_id` / `config.limit` as passed, and `results.total_samples` =
sliced count × epochs. A plain `--limit 3` run records exactly the same
shape: nothing in the header marks a shard as an intentional piece of a
whole.

**Identity.** Each `eval()` resolution mints a fresh `task_id`
(`ResolvedTask.id = uuid()`, `src/inspect_ai/_eval/loader.py:112`); only a
retry through `as_previous_tasks` reuses one (`loader.py:359`,
`evalset.py:1464`). The log file name is `{created}_{task}_{task_id}.eval`
(`src/inspect_ai/log/_recorders/file.py:157-175`). The two spike shards had
distinct `task_id`, `run_id` and `eval_id` values.

**Log file layout.** A `.eval` file is a zip with `header.json`,
`samples/{id}_epoch_{n}.json`, `summaries.json`, `reductions.json` and a
`_journal/` written mid-run (`src/inspect_ai/log/_recorders/eval.py:111-120`,
`:2005`). `log_finish` (`eval.py:304-372`) writes the consolidated summaries,
reductions and header last. Readers dedupe summaries by `(id, epoch)`, last
row wins (`eval.py:1920`). A running log has no `header.json`; Python readers
synthesise one from `_journal/start.json` (`eval.py:1867`) and read
summaries from `_journal/summaries/*`, as the viewer client and recovery do.

**Listing.** Every enumerator funnels through one filter,
`_filter_log_files` via `log_files_from_ls` and its async variant
(`_file.py:1118-1163`): `list_eval_logs` and `list_eval_logs_async`
(`_file.py:147,256,274,305,317`), the dataframe directory expansion
(`analysis/_dataframe/util.py:108`), `convert_eval_logs` (`_convert.py:105`),
`bundle_log_dir` (`_bundle.py:12`), and, through `list_eval_logs_async` and
`list_eval_logs`, the viewer server's `/logs` and `/log-files`
(`_view/common.py:150-175`, `fastapi_server.py:360-407`) and the eval-set
directory scan (`evalset.py:1043`). The filter keeps files by extension only
and skips no directory; it sees full paths but not the listed root. The
`.buffer` directory beside the logs (`sample_buffer_dir`,
`_recorders/buffer/filestore.py:662`) is invisible only because it holds no
`.eval` files.

**Eval sets over shards** (spike results):

- `validate_eval_set_prerequisites` (`evalset.py:1986`) accepts both shard
  logs, because both map to the task's identifier.
- `latest_completed_task_eval_logs` (`evalset.py:1939`) groups by `task_id`,
  so the shards are two separate entries, never compared or cleaned against
  each other;
  with `retry_cleanup=True` (the default) it deletes every non-`started` log
  sharing a `task_id` except the newest (`evalset.py:1962-1975`).
- `log_samples_complete` (`evalset.py:1837`) compares counts, not ids. With
  no selector, planned 6 ≠ 3 for both shards, so both are incomplete;
  `as_previous_tasks` pairs the task with the *first* log carrying its
  identifier (`evalset.py:1483-1489`) and re-runs from that shard. Observed:
  a new 6-sample log under the first shard's `task_id` (3 reused, 3 re-run),
  the second shard left as an orphan that `eval-set.json` does not list.
- With `--sample-id s0,s1,s2`, planned 3 = 3 for both shards, so the shard
  holding `s3,s4,s5` is also classified complete and the set finishes with
  nothing run (a latent bug independent of sharding, see "Not this design").

**Selection mode today.** A runner can launch N workers of one task with N
different `sample_id` overrides; `_selected_eval_set_tasks`
(`evalset.py:1629-1696`) only rejects an identifier that matches zero or more
than one *resolved task*. Each worker writes a distinct file, so nothing
collides; the result is the unrecognised-shards state above.

## Design

### Phased plan

Decision (Ransom and JJ Allaire, 2026-09-18): three steps, each shippable on
its own.

- **Step 1.** Shards are written as separate `.eval` files under the
  merged log's companion directory, `<dir>/<name>.shards/<k>/`, and merged
  into the canonical log `<dir>/<name>.eval` by a trusted, incremental merge
  exposed as a Python API and a new CLI command, and run by `eval_set()` at
  startup. Inspect ships no launcher in the first implementation (Ransom,
  2026-09-21): whoever starts the workers, a runner such as JJ's harness or
  a shell script, calls the API or the CLI when its workers finish, or
  leaves the merge to the next `eval_set()` over the directory. Fully
  opt-in.
  While shards run, what is missing is the whole-task rollup, not
  per-sample liveness: each shard is a normal in-progress log with its own
  sample buffer, listed and shown live by the viewer as today (Step 1 adds
  no listing exclusion; see "Listing").
- **Step 2.** Live whole-task metrics during the run: a periodic rollup of
  shard headers and summaries into a stored rollup (Ransom,
  2026-09-18), or, now that the merge is incremental, the merge itself run on
  a timer. Which of the two, or neither, is an open question. JJ Allaire:
  Step 2 may be skipped if Step 3 is imminent.
- **Step 3.** Targeted live-view improvements for the scenarios that want to
  be more live than the merge (`inspect ctl`, the running-sample viewer). The
  directory convention plus the merged log's provenance field let the viewer
  collapse a merged log's shards into one row and show per-shard metrics without routing
  sample reads across files. The three-host constraint and per-member read
  authorization still apply.

### Shard layout: a companion directory beside the merged log

Decision (Ransom, 2026-09-21): no marker in the shard header; the layout is
the marker, and it mirrors sandbox checkpointing. The merged (canonical) log
is `<dir>/<name>.eval`. Its shards live in the sibling directory
`<dir>/<name>.shards/`, one subdirectory per shard, `<name>.shards/<k>/`,
where `<k>` is a number assigned by the launcher. Sandbox checkpointing
places a log's companion at `<name>.checkpoints/` by the same rule: strip
`.eval` from the basename, append a dotted suffix (`log_basename` and
`eval_checkpoints_dir`,
`src/inspect_ai/util/_checkpoint/_layout/eval_checkpoints_dir.py`). A `.eval`
file under a `*.shards/` directory is a shard of the log named by that
directory; a file anywhere else is an ordinary log; copying a shard out of
its directory makes it an ordinary partial log.

- **The name is the identity.** There is no separate identifier: the shards
  of `<name>.eval` are the `.eval` files under `<name>.shards/`, and the
  merge's idempotence lookup is a name derivation in both directions (`<name>.shards/` implies
  `<name>.eval`, and `<name>.eval` implies `<name>.shards/`). Nothing else is
  written into `<name>.shards/` by the design: no manifest or index file
  (decision: Ransom, 2026-09-21). The intended selection the merge checks
  completeness against is a parameter of the merge, supplied by whoever
  calls it (see "Completeness"), and after the first merge it is carried by
  the merged log's provenance field.
- **Writer surface.** Workers run with `--log-dir <dir>/<name>.shards/<k>/`
  (`eval(log_dir=...)`, `inspect eval --log-dir`, or the selection protocol's
  per-worker `log_dir` override, `eval_set_overrides.py:164`). The recorder
  names the shard's `.eval` file inside as today
  (`{created}_{task}_{task_id}.eval`, `_recorders/file.py:157-175`), and the
  shard's `.buffer` lands beside it, so `inspect view --log-dir
  <dir>/<name>.shards/<k>/` (or `<dir>/<name>.shards/`) shows the shards
  live. Nothing else in the writer changes. Shards keep distinct `task_id`s,
  as every `eval()` mints today, and never share one, because
  `latest_completed_task_eval_logs` treats same-`task_id` logs as retry
  attempts and deletes all but the newest under `retry_cleanup`.
- **The launcher mints `<name>`.** This is the departure from today, where
  the recorder mints the log file name at eval start from the eval's
  `created` time and `task_id`. The launcher chooses `<name>` before any
  worker starts, because the workers' `log_dir` depends on it. `<name>`
  should have the same `{created}_{task}_{id}` shape as a log file name
  (honouring `INSPECT_EVAL_LOG_FILE_PATTERN`), so the merged log lists and
  sorts like any other and `EvalLogInfo` parses its task and task id from
  the file name as it does today (`_file.py:1178-1250`): `{created}` is the
  launcher's mint time, `{task}` the task's display name, and `{id}` a
  freshly minted task id that the merge stamps as the merged log's
  `eval.task_id`, so file name and header agree; it is unrelated to the
  shards' own `task_id`s. The merged log's `eval_id` is minted at the first
  merge and preserved by later passes, so incremental merges present as one
  log to `evals_df` and the viewer. The name-building logic in
  `FileRecorder._log_file_key` takes an `EvalSpec`; the launcher has none
  yet, so the builder is factored to take the name, id and time directly.
- **Single owner of the suffix rule.** `log_basename` is today the single
  owner of the `.eval` and `-recovered` stripping that both the durable
  `<name>.checkpoints/` directory and the ephemeral working directory
  derive from. Shards should reuse it rather than mirror it, with a sibling
  `eval_shards_dir(log_location, override_root)` next to
  `eval_checkpoints_dir`. Because `log/` must not depend on
  `util/_checkpoint/`, the two functions and `log_basename` move to a neutral
  module (under `_util/` or beside `log/_file.py`) that the checkpoint
  package imports; the rule keeps one owner and gains a second caller.
- **`-recovered`.** `log_basename` strips `-recovered`, so a recovered merged
  log `<name>-recovered.eval` maps to the same companion `<name>.shards/`.
  In practice a `started` merged log is re-merged, not recovered (see
  "Eval-set integration"), so this mapping matters for the CLI case where a
  user has run `inspect log recover` by hand. A recovered *shard*
  (`<shard>-recovered.eval` written beside the original inside `<k>/`) makes
  its directory hold two files for one shard; the merge treats the files in
  one `<k>/` as attempts of the same shard and takes the newest, the same
  rule `eval_set()` applies to retry attempts, rather than refusing them as
  overlapping members.
- **Override root.** Checkpointing's `checkpoints_location` moves only the
  parent: the companion lands at `<override>/<name>.checkpoints/` with the
  per-eval name unchanged (`eval_checkpoints_dir`; `checkpoints_location`,
  `util/_checkpoint/config.py:165,234`). A `shards_location` override in the
  same style would place shards at `<root>/<name>.shards/<k>/`, which is how
  JJ's harness would keep its per-shard prefixes separate from the log
  directory. It costs symmetry: with an override the merge cannot derive the
  shard root from `<name>.eval` alone, so the root must reach it as a merge
  parameter for the first merge and from the merged log's provenance field
  after that. Whether this is Step 1 or later is open question 5.

### Listing: no exclusion in Step 1

Decision (Ransom, 2026-09-21): Step 1 adds no listing exclusion. Shards
under `<name>.shards/<k>/` are listed as ordinary partial logs beside the
merged log by every enumerator, exactly as unrecognised shards are listed
today. The merged log is plainly a rollup that may lag the shards, and the
parent view is never blank: a sharded run shows its running shards from the
first byte, and one more row once the first merge lands.

Why not hide them: any exclusion rule, unconditional or conditional on the
merged log existing, creates a state where the merged log is stale (new
samples in a shard, or a shard added later, not yet merged) and the ongoing
work is invisible from the parent view. That confusion is worse than the
clutter it removes. The layout makes deferral safe: shards sit under
`*.shards/` from their first write, so an exclusion added later is one
change in the shared filter (`_filter_log_files`, which every enumerator
passes through; see "Current behaviour"), with no files to move and no
compatibility break. The candidate rule, if it is ever wanted, is "a file is
excluded when its path relative to the listed root contains a component
ending in `.shards`", keyed on the suffix so a user directory named `shards`
is unaffected; open question 1 records it as deferred.

What listing shards beside the merged log costs, stated so the affected
tools are pointed at merged logs:

- **Viewer.** N shard rows plus one merged row per task, the clutter the
  issue started from, but with the whole-task row present the shard rows
  are extra, not wrong. Pointing the viewer at the merged log, or deleting
  shards after a verified merge (the explicit option under "Shard
  disposition"), clears it.
- **`evals_df`.** Dedupes by `eval_id` (`analysis/_dataframe/evals/table.py:160`)
  and the merged log has its own, so a directory of sharded runs gives N+1
  rows per task. Filter on the provenance field, which only merged logs
  carry, or pass merged logs explicitly; a helper for that is a later
  nicety.
- **`samples_df`.** Unaffected: it dedupes on sample `uuid`
  (`analysis/_dataframe/samples/table.py:365,430`) and the merge copies
  samples with their uuids, so no sample is doubled.
- **Scout and other downstream readers** that do not dedupe by sample
  `uuid` see each merged sample twice unless pointed at merged logs. This is
  the one correctness cost and the first reason to revisit the exclusion.
- **`eval_set()`** is unaffected because it skips shards itself (see
  "Eval-set integration"); that skip is required for correctness regardless
  of the general listing decision.

Shards are found for merging by a dedicated scan of `<name>.shards/*/`,
never through the listing.

### The merge

The merge is the only writer of the merged log and the only place metrics
are recomputed.

**Ownership.** Decision (Ransom, 2026-09-18, refined 2026-09-21): the merge
belongs to whoever launches the workers, but Inspect ships no launcher in
the first implementation. Step 1 therefore provides the merge as a Python
API and a CLI command (names are phase 2) plus the `eval_set()`-startup
merge, and the external launcher calls one of them: one process launches the
workers, watches for the shard logs to complete, and calls the merge. That
matches the external-runner protocol, whose runner already owns the
directory's eval-set metadata and knows when each worker exits, and it is
the process most likely to have the task's code importable. Inspect itself
does nothing at end of run; a launcher that forgets, or dies before the
merge, is covered by the `eval_set()`-startup merge and by running the CLI
by hand. The merge is built idempotent and
deterministic (the output is `<name>.eval` for the companion `<name>.shards/`
and nothing else, "merge whatever is new"), so a worker can also be told to
attempt the merge on exit and a duplicate
attempt is harmless; the distributed model is thus a configuration, not a
different design. A create-if-absent conditional write is not available
uniformly (Inspect's S3 writer supports `IfMatch` replacement of a known
ETag, `_recorders/eval.py:753-761`, S3-only through boto), so idempotence,
not a lock, is what makes concurrent attempts safe: two writers producing
byte-equivalent output to one key is tolerated by S3's per-object atomic put
and by a local atomic rename.

**Trust.** Confirmed (Ransom, 2026-09-21): the merged log is created only by
a trusted Python step (the Python API or CLI, called by the launcher or by
hand, or `eval_set()` at startup). The viewer, `list_eval_logs` and the dataframe layer never create or
recompute it. Recomputation needs the task's metric code importable: a
runner or an `eval_set()` process has it; a CLI merge from a laptop may not,
and then `resolve_scorers_info`'s `task_file` fallback imports log-named code
exactly as recovery does today. The merge records which of the two it did
and fails rather than store metrics from a lossy input (open question 3 on
whether the CLI should require an opt-in for the fallback).

**Membership validation, strict.** Membership is by location, so a stray `.eval`
file in the directory is a candidate member. Before combining, every member
must agree on task identifier, `task_version`, model, plan and config with
the selectors (`sample_id`, `limit`, `sample_shuffle`) excluded from the
comparison, and epochs; `(id, epoch)` sets must be disjoint. The merge
refuses on any mismatch rather than skipping the odd file.

**Completeness.** The merged log is `started` (a non-`success` status) until
every shard is `success` and the union of members equals the intended
`(id, epoch)` selection; then `success`. The intended selection is a merge
parameter, not a file: headers alone cannot supply it for a subset run (each
shard records only its own `dataset.sample_ids`, and `dataset.samples` is
the full dataset size), and every caller of the merge already knows it. The
launcher assigned the ids, so it passes them when it calls the merge API or
CLI at the end of its run, and again, enlarged, when it adds shards later. `eval_set()` computes the
selection from the task's dataset and selectors, as `log_samples_complete`
does today. The CLI merge takes an id list or a count as an option. After
the first merge the merged log's provenance field records the selection it
merged against, so any later merge, by any caller, reads it from there. A
first merge with no selection supplied is complete only for a whole-dataset
run (the union's size equals `dataset.samples`); otherwise it writes
`started`, or refuses, per the rule below. `eval_set()` already classifies any
non-`success` log as incomplete (`evalset.py:1837-1860`), so it never treats
an incomplete merged log as done. The merge refuses to write a `success` log
over an incomplete shard set and, unless told to, refuses an incomplete
shard set altogether; when told to (the startup and periodic cases), it writes the
`started` log (Ransom and JJ Allaire, 2026-09-18).

**Provenance and ledger: a new header field.** Decision (Ransom,
2026-09-21): the merged log carries a new typed `EvalSpec` field (not
`eval.metadata`) holding the shards' provenance and the merge ledger: the
companion directory (derivable from the name, recorded so a moved or renamed
merged log still says where it came from, and the override root when
`shards_location` is in use), the intended selection last merged against,
and one entry per shard `<k>` with its file name, `eval_id`, the number of
samples merged from it, its status at merge time, and its mtime or ETag. The
merged log's
own `samples/` members are the set of merged `(id, epoch)` samples. With
this, a fully merged `success` shard is skipped without opening it, a grown
shard is re-read only for the members the merged log lacks, and the ledger
travels with the log: deleting the merged log correctly forces a merge from
scratch, and the merged log stays the whole truth for `<name>`. The field
is absent on unsharded logs. It is a public log-schema change: the JSON
schema and the `ts-mono` generated types change even though the viewer
ignores the field until Step 3, so Step 1 needs a coordinated `ts-mono`
landing (`.agents/skills/land-ts-mono/SKILL.md`). Shard headers are
unchanged.

**Incremental merge.** Decision (Ransom, 2026-09-21): the merge merges once
and then pulls in additional samples from shards that are still running or
have grown, and additional shards added later.

- *Reading running shards.* A running shard has no `header.json`; the merge
  reads it as every Python reader does, synthesising the header from
  `_journal/start.json` and summaries from `_journal/summaries/*`. Flushed
  samples are ordinary `samples/` members; samples still in the shard's
  buffer database are not visible and arrive at a later merge, so the
  shard's `log_buffer` flush cadence bounds staleness. Per-shard metrics in
  a running shard are not final, which does not matter because the merge
  recomputes over the union.
- *Conflicts.* A retried shard can re-run a sample the merge already holds.
  Newest wins, matching the retry rule that the newest attempt is the truth:
  "newest" by the shard's `created` time, with the sample's `completed_at`
  as the tie-break within a shard. The merged log's dedupe by `(id, epoch)`
  handles the replacement mechanically (later member of the same name wins),
  and the sample `uuid` changes with the re-run, so `samples_df` sees only
  the surviving copy. Two *different* shards both holding the same
  `(id, epoch)` in one pass, neither superseding the other, is a disjointness
  violation and the merge refuses. Newest-wins is a recommendation (open
  question 2).
- *Adding shards.* Adding shards later changes the intended selection. The
  launcher passes the enlarged selection to the next merge, and the merged
  field records the selection it last merged against. A shard set that grows
  after the merged log reached `success` makes that log incomplete again, so
  the next merge returns it to `started` until the new shards land, and says
  so in its output.
- *Cost shape.* Baseline: each pass rewrites the merged zip in full, because
  `zipfile` has no raw member copy and its append mode exists only for local
  files (`_replace_eval_header_in_place`, `eval.py:568-590`; the S3 path
  rewrites, `_rewrite_eval_zip_with_new_header`, `:592`). So each pass costs
  the merged log's size plus the new members, and k passes rewrite roughly k
  times the final size; on S3 that is a download and upload per pass.
  Optimisation for large logs on S3: server-side composition with
  `UploadPartCopy`, copying byte ranges of shard members straight from the
  shard objects into the merged object, with the merged central directory
  built locally and uploaded as the last part. Constraints: parts other than
  the last must be at least 5 MiB, so small members must be batched into
  contiguous ranges; shard zips interleave `_journal/` members among
  `samples/`, so ranges are not contiguous across a shard and journal bytes
  either ride along as dead bytes or force more parts; local-file member
  offsets must be recomputed for the new central directory. Baseline first;
  composition when measured merges of large logs justify it. Inspect already
  has a multipart upload helper to build on (`_util/asyncfiles.py:240`).
- *Triggers.* The Python API, the CLI that wraps it and the
  `eval_set()`-startup merge are the same operation: "merge whatever is new", idempotent, deterministic,
  keyed on the merged log's basename (given either `<name>.eval` or
  `<name>.shards/` it finds the other), safe to run at any time and any
  number of times.

**Shard disposition.** Merged shards stay in `<name>.shards/`, listed
beside the merged log (see "Listing"), until the merged log is verified;
delete is an explicit option, never the default, and also the way to clear
the extra rows once a run is done, because it is the one choice that cannot
be undone after a bad merge (Ransom, 2026-09-18, restated under the companion
layout). This is the second difference from checkpoints, whose retention
default is to delete the companion on success (`retention:
Literal["delete", "retain"] = "delete"`, `util/_checkpoint/config.py:233`);
shards flip the default because re-merge after a merge bug and adding shards later
both need the shards to still exist. No move is needed. For reference, an
S3 move would be a server-side copy plus a delete, one API round trip per
shard, not a transfer through the client.

### Eval-set integration

`eval_set()` startup scans for `*.shards/` companions in the log directory
and runs the incremental merge for each before any pairing, at the point
where it lists the directory today (`evalset.py:1043-1060`). The merged log
`<name>.eval` then takes part in pairing as an ordinary log; shards
themselves are skipped by pairing and completeness through `eval_set()`'s
own path-based skip of anything under a `*.shards/` component. That skip is
required regardless of the general listing decision, or today's
misbehaviour (first-matching pairing, count-based completeness) returns;
`retry_cleanup` would leave shards alone in any case, since each has its
own `task_id`. Two hazards: a `started`
merged log must be recognised by its provenance field and re-merged, not
handed to `_recover_crashed_log` (`evalset.py:1512`) as a crashed log; and
`log_samples_complete` must not classify a merged log by count alone once the
field is present. Upside: merging an incomplete shard set at startup into a `started`
log turns a sharded run into an ordinary resume; the missing samples are
re-run by the normal retry path, unsharded unless the runner re-shards them.

### Notes for harnesses

- Harnesses that stage logs on local disk and upload at the end (JJ's
  benchmark harness proposal): `--log-shared` syncs the sample buffer into a
  `.buffer` directory inside the log directory itself (`filestore.py:662`,
  `_recorders/buffer/database.py:286-289`), so with a local staging
  directory it publishes nothing a remote viewer can reach; there is no live
  visibility during the run; and a shard is lost if the instance dies before
  the upload. Writing `--log-dir` straight to the shared
  `<dir>/<name>.shards/<k>/` prefix restores all three. A harness that wants
  its shard prefixes elsewhere than beside the merged log would use the
  `shards_location` override (open question 5).
- `limit` and `sample_id` are mutually exclusive in `eval()`
  (`eval.py:907`), so a harness that shards a *subset* of a dataset must
  resolve the subset to ids first and hand each worker its `sample_id` list.
- Runner protocols that already watch workers (the capture/selection runner,
  `inspect_steward` per `eval_set_manifest.py`) own the merge by setting each
  worker's `log_dir` and calling the merge API or CLI when the workers exit;
  Inspect does not merge at end of run on its own in the first
  implementation.

## Open questions

Decisions Ransom has not yet made, each with the recommendation the design
assumes.

1. **Listing exclusion (deferred).** Step 1 has none (Ransom, 2026-09-21;
   see "Listing"). If experience shows the extra rows or downstream double
   counting matter, the candidates are a rule keyed on a `.shards` path
   component below the listed root (any depth versus direct child) and a
   variant that hides shards only once the merged log exists; every variant
   hides ongoing work behind a stale merged log, which is why none ships
   first.
2. **Conflict policy.** Newest wins when a retried shard re-runs an already
   merged sample (recommended, matching the retry rule) versus refusing.
3. **CLI merge and the `task_file` fallback.** Whether a CLI merge may follow
   `resolve_scorers_info`'s fallback to import the log's `task_file` when the
   metric code is not installed, as recovery does today, or must require an
   explicit opt-in. Recommendation: allow it with a visible notice, since the
   CLI is run deliberately on a directory the user chose, and revisit with
   the general policy under "Not this design".
4. **Step 2's place.** Now that the merge is incremental there are two routes
   to live whole-task metrics: the summaries-only rollup (cheap per tick, a
   value-only approximation that must be labelled as such) or the
   incremental merge on a timer (exact, a merged-zip rewrite per tick,
   reducible by S3 composition). Whether Step 2 remains a separate step,
   becomes "run the merge on a timer", or is skipped for Step 3.
5. **`shards_location` override: Step 1 or later.** The checkpoint-style
   override (`<root>/<name>.shards/<k>/`) is how JJ's harness would keep
   per-shard prefixes away from the log directory. It is cheap to add to the
   layout helper, but it breaks name-only derivation: the merge must then
   learn the root as a merge parameter on the first merge. Recommendation:
   Step 1, with the root recorded in the merged log's provenance field, so
   a later CLI merge given only `<name>.eval` still finds the shards.
6. **Forming `<name>`.** The design assumes the `{created}_{task}_{id}` log
   file shape, with `{id}` a freshly minted task id that becomes the merged
   log's `eval.task_id`, and a stable `eval_id` minted at the first merge.
   Confirm, or choose a different shape for launcher-minted names.

## Compatibility

- The new `EvalSpec` provenance field changes `EvalSpec`, the JSON schema, the
  generated TypeScript types and any exhaustive `model_fields` enumeration;
  Step 1 needs a coordinated `ts-mono` landing. Shard headers and unsharded
  logs are unchanged; the field is absent on them.
- Old Inspect versions read a merged log as an ordinary log: `EvalSpec` sets
  no extra-field policy (`_log.py:1120`), so pydantic's default drops the
  unknown field on read. They list shards as N ordinary partial logs beside
  the merged log, exactly as current versions do in Step 1.
- If a listing exclusion is added later, it is one change in
  `_filter_log_files` that every enumerator inherits (callers would pass the
  listed root); no files move. `<name>.checkpoints/` directories need no
  rule either way, since they hold no `.eval` files.
- `log_basename` moves from `util/_checkpoint/_layout/` to a neutral module
  so `log/` can use it without depending on the checkpoint package; the
  checkpoint helper keeps calling it, so its behaviour is unchanged.
- The launcher-minted `<name>` keeps the `{created}_{task}_{id}` shape, so
  `EvalLogInfo` parses the merged log's task and task id from its file name
  as for any other log.
- Eval-set completeness stops comparing counts for a log carrying the
  provenance field and treats a `started` merged log as a re-merge target,
  not a crashed log.
- `.json` format logs are deprecated; sharding is `.eval`-only.

## Security

Log headers, file names and sample JSON are already untrusted inputs to the
existing readers and go through `filesystem()`/`local_path()` and the same
Pydantic models. New boundaries:

- **Membership by location.** Anything placed in `<name>.shards/` is a
  candidate member; strict validation is the defence against a stray or
  hostile file, and the merge refuses rather than skips. The name
  derivation between `<name>.eval` and `<name>.shards/` is a string rule on
  a basename, not a pointer read from a file, so it introduces no new path
  input; the override root (open question 5) does, and is validated like
  any other configured location.
- **The intended selection** reaches the merge as a parameter or from the
  merged log's own header, never from a separate file in the shard
  directory, so the directory holds only `.eval` files and their buffers.
- **Recomputation executes code the log names.** The merge is the only place
  metrics are recomputed, and it runs only as a trusted Python step (the
  API or CLI called by the launcher or by hand, `eval_set()` startup); no
  reader path (viewer server,
  `read_eval_log`, `evals_df`) recomputes or follows the `task_file`
  fallback. Open question 3 covers the CLI's use of that fallback.
- **Listing shards beside the merged log** changes no authorization: every
  file, shard or merged, is authorized per file as today (`_validate_read`).

## Testing

- Merge tests over mock-model shards like the spike, in `tests/log/` and
  `tests/test_eval_set.py`, all local: merge a complete shard set; refuse an
  incomplete one unless told to emit `started`; recomputed metrics equal an unsharded
  run's for a built-in metric and for a custom metric that reads `answer`;
  a stray non-matching `.eval` in the shard directory refused; two overlapping shards
  refused.
- Incremental tests: merge, grow a shard, merge again and see only the new
  members added; add a shard and see the status return to `started`; a
  retried sample replaced by the newer copy; a fully merged shard not
  reopened.
- Listing tests: shards under `<name>.shards/<k>/` listed by
  `list_eval_logs`, `evals_df` and the viewer listing beside the merged log;
  `samples_df` over the directory yields each sample once; `eval_set()`
  startup over the directory pairs only the merged log.
- Layout tests: `<name>.eval` and `<name>.shards/` derive each other in both
  directions through the shared `log_basename`; `<name>-recovered.eval` maps
  to `<name>.shards/`; the checkpoint helper's results are unchanged after
  the move; two files in one `<k>/` (original plus `-recovered`) are treated
  as attempts of one shard, newest taken.
- Eval-set tests: startup over an incomplete shard set produces a `started` merged
  log that the set then resumes; `retry_cleanup` leaves shards alone; a
  `started` merged log is re-merged, not recovered.
- A test that no reader path imports a header-named `task_file`.
- Provenance field round-trip, and a check that unsharded logs and a log
  directory without any `*.shards/` companion are unaffected.

## Alternatives not taken

Kept for the record and as the rationale for the design above.

- **Readers understand shards as one logical log (Option B in full).** Keep
  shards as the durable format and teach `list_eval_logs`, `read_eval_log`,
  the dataframes, eval-set bookkeeping, Scout and the TypeScript client in
  three hosts to present a set of shards as one `EvalLog`, routing sample reads to
  the shard holding each `(id, epoch)`. Better live visibility than any step
  of the phased plan; significant changes across every reader; and metric
  computation hard to get right because whole-task metrics need
  user-defined Python that readers, and never browsers, would have to run
  (B1), or a stored aggregate that is Step 1's merge in another form (B2).
  Kept as the reference the phased plan is measured against; Step 3 takes
  the slice of it that needs no sample routing.
- **A sharded log as a directory with a manifest (Option C).** A
  `ShardedEvalRecorder` handling a directory location holding shards and a
  `manifest.json` with whole-task results. One location per task, but a new
  on-disk format every consumer must learn, unreadable by old versions,
  weak directory semantics on S3, and still a finaliser to own. The chosen
  design keeps the directory idea only as a marker and produces an ordinary
  `.eval` as the canonical log.
- **Workers write into one shared log (Option D).** Appending to one zip from
  many processes is not safe and S3 has no append; a per-sample object
  prefix multiplies object counts and needs a third reader. Not viable.
- **Distributed merge ownership.** The last worker to finish lists the shards
  and merges. No launcher dependency and the merge lands as soon as the last
  shard does, but two near-simultaneous finishers can both see a complete
  shard set, the largest transfer lands on an arbitrary worker at the end of a
  one-sample-per-machine job, and every worker must have the metric code.
  Retained as a configuration of the idempotent merge, not as the default.
- **A shard marker in the header.** A new `EvalSpec` field on every shard
  naming the merged log, index, count and intended selection. Rejected
  (2026-09-21) in favour of the directory convention: the header field would
  have changed every shard's schema, needed a writer-side surface on
  `eval()` and the CLI, and let a shard carry its membership out of its
  directory, which is exactly what the relaxation boundary should prevent.
  Re-using `task_id` as the marker was never viable because `retry_cleanup`
  would delete shards as stale retry attempts.
- **Provenance in `eval.metadata`.** No schema change and no `ts-mono`
  landing for Step 1, but a user-owned namespace: the entry would sit beside
  the user's own metadata in `evals_df` columns and rely on a reserved key.
  Rejected (Ransom, 2026-09-21) for a typed field.
- **A separate ledger file** in `<name>.shards/` for the incremental merge.
  Cheaper to update than a header, but a second source of truth that can
  drift from the merged log (a rebuilt or copied merged log carries no
  ledger). Rejected for the in-log field.
- **`<log_dir>/shards/<group>/` as the shard directory.** The first
  directory convention (Ransom, 2026-09-21, morning), superseded the same
  day by the companion layout. It needed a separate identifier for the shard set, a listing rule
  keyed on a bare `shards` component that could collide with a user
  directory of that name, and gave the merge no name-only way to find its
  output; the companion layout derives everything from `<name>` and reuses
  the checkpoint suffix rule.
- **`<name>.eval/shards/<k>/` (shards inside a directory named like the
  log).** Rejected (Ransom, 2026-09-21): a file and a directory cannot share
  a name on a local filesystem, so the merged log and its shard directory
  could not coexist, and a directory ending in `.eval` invites tools to treat
  it as a log.
- **Moving or deleting shards after the merge.** A move to an archive prefix
  was the 2026-09-18 decision under the header-marker design; the companion
  layout makes it unnecessary. Deleting by default loses re-merge after
  a merge bug and could remove a shard still writing. A file-name convention
  to hide shards would constrain every shard's name for the sake of the
  listing.
- **Recomputing from summaries.** Cheap and enough for built-in metrics over
  `value`, but wrong for custom metrics that read other fields (see
  "Constraints"). Rejected for the merge; still the basis of the Step 2
  rollup variant, labelled as an approximation.
- **A launcher-written manifest in `<name>.shards/`** holding the intended
  selection, task identity and override root. Dropped (Ransom, 2026-09-21):
  every caller of the merge already knows the intended selection (the
  launcher assigned the ids, `eval_set()` derives it from the task, the CLI
  takes it as an option) and the merged log's provenance field carries it
  after the first merge, so the file would serve only a first CLI merge on a
  subset run by someone other than the launcher. That case writes `started`
  or takes the selection on the command line. Reconsider if such merges turn
  out to be common.
- **Shard count as the completeness input.** Proves N `success` shards exist
  and relies on disjointness for coverage; kept only as the CLI's cheaper
  option beside an id list, since it cannot name missing samples.
- **A listing exclusion in Step 1** (a `.shards` path-component rule at any
  depth or direct child, or one conditional on the merged log existing).
  Deferred (Ransom, 2026-09-21): every variant creates a state where a stale
  merged log hides ongoing work in the shards; see "Listing" and open
  question 1.
- **A periodic full merge as originally rejected (2026-09-18).** The
  objections were a full rewrite per tick, reading running shards through
  their journals, and needing a `started` status. The incremental-merge
  decision answers the last two and keeps the first as the recorded cost
  shape; the rewrite cost is why the summaries rollup remains a candidate
  for Step 2 (open question 4).

## Not this design

- `log_samples_complete` classifies a log complete by count, so a `--limit 3`
  or other-shard log satisfies a different 3-id `--sample-id` request
  (verified in the spike). Worth an issue on its own.
- An eval set over a directory containing unrecognised shards (partial logs
  outside any `*.shards/` companion, or written by an older version) re-runs
  the task from the first matching log and orphans the others. A clearer
  error would help.
- Per-epoch sharding (running one epoch of a sample on one worker) is not
  expressible with `sample_id`/`limit` and is out of scope.
- `resolve_scorers_info` imports a log's `task_file` to find unregistered
  metrics (`score.py:653-665`). That is today's behaviour for `inspect score`,
  the public `recompute_metrics` and `edit_score`, and recovery including
  recovery triggered during eval-set resume and eval retry, on any log;
  whether those operations should require an opt-in before importing
  log-named code is a separate question (open question 3 is the merge's
  slice of it).
- `EvalDataset.samples` records the full dataset size while `sample_ids` is
  the slice; the pair is the only present hint that a log is partial and its
  documentation could say so.
