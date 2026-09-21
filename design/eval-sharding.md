# Eval sharding with per-worker log files: options and trade-offs

Status: options analysis with a chosen phased direction, last revised
2026-09-21. The options are kept whole for comparison; "Direction" records
the phased plan Ransom and JJ Allaire agreed on 2026-09-18 (Step 1: opt-in
merge of shard files into one canonical log; Step 2: periodic
header-and-summary rollup; Step 3: targeted live-view improvements).
Decisions recorded: the #420 self-contained-log constraint is relaxed for
sharded output only (Ransom, 2026-09-18); the end-of-run merge is
launcher-owned by default, built idempotent and deterministic (Ransom,
2026-09-18); no shard marker in the log header, the directory convention
`<log_dir>/shards/<group>/` is the marker (Ransom, 2026-09-21); the merge is
incremental, merging once and then pulling in new samples and new shards
(Ransom, 2026-09-21); the merged log is created only by a trusted Python
step, never by a reader (Ransom, 2026-09-21); merged shards stay in the
excluded `shards/` tree, with delete as an explicit option (Ransom,
2026-09-18, restated under the directory convention). No API signatures or
implementation plan yet; that is phase 2.
Issue: https://github.com/meridianlabs-ai/inspect_ai/issues/509.
Author: agent (Claude), reviewed by Codex; see the PR.

## Why

Users split a task's samples across workers (down to one sample per machine)
so a large or slow task finishes in wall-clock time a single process cannot
reach. Inspect already lets a worker run a subset of a task's samples:
`eval(sample_id=...)` and `eval(limit=(start, end))` slice the dataset, and
every eval-set worker in selection mode can be handed a different `sample_id`
or `limit` override (`src/inspect_ai/_eval/eval_set_overrides.py:207-220`).
What is missing is the other half: each worker writes its own `.eval` file, and
nothing in Inspect knows that those files are pieces of one task. Every reader
treats a shard as a complete, independent eval:

- **Viewer.** The log listing is one row per file (`LogHandle` in
  `src/inspect_ai/_view/common.py:101-120`), so a task sharded 50 ways shows as
  50 rows named for the same task, each with its own accuracy over its own
  samples. There is no whole-task view.
- **Metrics.** `results.scores[].metrics` in each shard header are computed over
  that shard's samples only. Anything that is not a plain mean (`stderr`,
  bootstrap CIs, grouped metrics, reducers over epochs) has no whole-task
  value anywhere on disk.
- **Python API.** `read_eval_log`, `read_eval_log_sample_summaries` and
  `read_eval_log_samples` take one file (`src/inspect_ai/log/_file.py:539`,
  `:982`, `:1037`). `evals_df` produces one row per shard; `samples_df`
  happens to work because it concatenates samples across whatever logs it is
  given (verified: two 3-sample shards give 2 eval rows and 6 sample rows).
- **Eval sets.** `task_identifier` ignores `sample_id` and `limit`
  (`src/inspect_ai/_eval/evalset.py:2058`), so all shards of a task have the
  same identifier while each carries a fresh `task_id`. The pairing and
  completeness logic then misbehaves in both directions (see "Current
  behaviour" for the verified runs): without a selector it re-runs the task
  from one shard and orphans the rest; with a selector whose count matches
  the shard size it declares every shard complete, including shards holding
  other samples.
- **Scout and downstream tools** see N transcripts sources for one task, with
  N sets of eval metadata.

The issue's framing is the Scout analogy: a directory of parquet files reads
the same as one compacted file. This document lays out the ways Inspect could
get an equivalent property for eval logs and what each costs.

## Goals and constraints

Goals:

- A user or runner can shard one task's samples across processes and machines,
  each writing its own log, without hand-rolled post-processing.
- Inspect's readers (Python log API, dataframes, viewer, eval-set bookkeeping,
  Scout) can treat the shards of one task as one logical task with one set of
  whole-task results.
- Old, unsharded logs keep working unchanged, and a shard is still a valid
  `.eval` file that today's tooling can open on its own.

Constraints and context that shape the options:

- **Self-contained logs, relaxed for sharded output only.** The #420 design
  adopted, on Ransom's review feedback, the constraint that *every log file
  stays self-contained, and the newest log for a task stays the whole truth
  about that task* (`design/retry-seeded-attempt-log.md:19`). A logical log
  spread over files is exactly the cross-file concept that constraint
  rejected for retries. **Decision (Ransom, 2026-09-18):** this feature may
  relax the constraint, and the constraint continues to hold in every case
  other than this sharding. So an option may make readers look across the
  shards of one marked group, but every unsharded log stays self-contained
  and the newest-log-is-the-truth rule for retries stays as it is; whatever
  grouping an option adds must be keyed on an explicit marker, never
  inferred for ordinary logs. Under the direction chosen on 2026-09-21 that
  marker is the directory convention `<log_dir>/shards/<group>/`: a file
  outside such a directory is an ordinary log, and copying a shard out of it
  makes it an ordinary partial log. That is the intended boundary of the
  relaxation. The decision opens B and C; it does not prefer
  them over A, which never needed the relaxation.
- **Readers are many and some have no server.** The viewer parses `.eval` zips
  in the browser via byte-range requests (`/log-bytes/{log}` in
  `src/inspect_ai/_view/fastapi_server.py:258`; the client's
  `remoteLogFile.ts` reads `header.json`, `summaries.json` and
  `samples/*.json` from the zip's central directory itself). The same client
  runs inside VS Code and in static bundles written by `bundle_log_dir`
  (`src/inspect_ai/log/_bundle.py:79`), where there is no Python at read time.
  Whatever the on-disk shape is, the TypeScript client in the `ts-mono`
  submodule has to understand it.
- **An external runner protocol already exists.** Capture and selection mode
  (`src/inspect_ai/_eval/eval_set_manifest.py`,
  `src/inspect_ai/_eval/eval_set_selection.py`, landed 2026-08, PRs #5076,
  #5134, #5147) let a runner enumerate an eval set and launch one worker per
  task into a shared flat log directory, with per-worker `sample_id`/`limit`
  overrides. Its stated invariant is one task, one log: "A selection must
  therefore name each task at most once — one task means one log"
  (`eval_set_selection.py:16-18`). Sample sharding is the case that invariant
  excludes, so the protocol is the natural home for shard orchestration and
  also the thing most directly changed by it.
- **Whole-task results need Python, the metric code, and trust.** Shard
  headers hold per-shard metrics only; the whole-task values have to be
  computed somewhere. `eval_results`
  (`src/inspect_ai/_eval/task/results.py:90`) takes sample scores plus the
  scorer, metric and reducer definitions, which the header records only by
  *name*: `metric_from_log` instantiates registered Python metrics
  (`src/inspect_ai/_eval/score.py:590`), and `resolve_scorers_info` falls
  back to importing the header's `task_file` when a metric name is not in the
  registry (`score.py:653-665`, via `load_file_tasks`). So recomputation
  (a) requires a Python process with the eval's metric code installed or
  importable, and (b) is a trust boundary: a reader that recomputes
  automatically would import code named by the log it is reading. Today
  scoring, metric recomputation (`recompute_metrics`,
  `src/inspect_ai/log/_metric.py:39-41`, and by default `edit_score`,
  `src/inspect_ai/log/_score.py:146-147`) and recovery
  (`src/inspect_ai/log/_recover/_write.py:270-285`) can load task code, and
  recovery also runs opportunistically during eval-set resume and eval retry
  (`_eval/evalset.py:1494`, `_eval/eval.py:1697-1708`). Ordinary log reads
  deserialize stored results, and the browser client can only ever read
  stored results (`remoteLogFile.ts:420-429`). Any option therefore has to
  say *where* aggregation runs (a trusted Python step whose output is stored)
  and what a reader without Python or without the code can show (stored
  per-shard results, sample counts, and nothing that needs a metric
  function).
- **Summaries are a lossy input for recomputation.** `EvalSampleSummary`
  keeps score *values* intact but truncates score `answer`, `explanation`,
  `reason` and metadata, and thins sample metadata
  (`EvalSampleSummary.thin_data`, `src/inspect_ai/log/_log.py:371-400`;
  `thin_metadata`, `src/inspect_ai/log/_util.py:147`). Metrics receive the
  full `SampleScore` including `sample_metadata`
  (`src/inspect_ai/scorer/_metric.py:245-254`; `results.py:601`), so a
  custom metric that reads anything but `value` computes a different number
  from summaries than from samples (the reviewer's probe: an answer-length
  metric returned 2000 from the sample and 3 from its summary). Built-in
  metrics over `value` (`accuracy`, `mean`, `stderr`, bootstrap) and reducers
  over values are safe; general metric support needs full sample reads, as
  recovery does (`_recover/_write.py:162-177`), which on remote storage is
  the whole group's sample bytes rather than N small `summaries.json` reads.

Non-goals for this document: API signatures, exhaustive edge cases, an
implementation plan. Those are phase 2. The options analysis below is kept
whole; the phased direction chosen on 2026-09-18 is recorded in "Direction"
after the key questions.

## Current behaviour

Verified by reading the code at e4b8ad59d8 and by running a six-sample mock
task twice with `--sample-id s0,s1,s2` and `--sample-id s3,s4,s5` into one log
directory, then running `inspect eval-set` over that directory.

**Slicing.** `slice_dataset` (`src/inspect_ai/_eval/task/util.py:143`) applies
`limit` (int or `(start, end)` tuple) or `sample_id` (ids, `task:id` selectors,
`fnmatch` patterns). `eval()` forbids `sample_id` together with `limit` or
`sample_shuffle` (`src/inspect_ai/_eval/eval.py:906-910`). Both selectors
choose whole samples; every epoch of a chosen sample runs in the same process.

**What a shard records.** `TaskLogger.__init__`
(`src/inspect_ai/_eval/task/log.py:242-308`) writes into the header
`dataset.samples` = the full dataset size (6 in the spike),
`dataset.sample_ids` = the sliced ids (`['s0','s1','s2']`), `config.sample_id`
/ `config.limit` as passed, and `results.total_samples` = sliced count ×
epochs (3). So a shard header does say it covers 3 of 6 samples, but a plain
`--limit 3` run says exactly the same thing: nothing marks a shard as an
intentional piece of a whole.

**Identity.** Each `eval()` resolution mints a fresh `task_id`
(`ResolvedTask.id = uuid()`, `src/inspect_ai/_eval/loader.py:112`); only a
retry through `as_previous_tasks` reuses one (`loader.py:359`,
`evalset.py:1464`). Each run mints a fresh `run_id` and `eval_id`. The log
file name is `{created}_{task}_{task_id}.eval`
(`src/inspect_ai/log/_recorders/file.py:157-175`). The two spike shards had
distinct `task_id`, `run_id` and `eval_id` values and no field in common that
a reader could use to group them other than the task identifier fields.

**Log file layout.** A `.eval` file is a zip with `header.json`,
`samples/{id}_epoch_{n}.json`, `summaries.json`, `reductions.json` and a
`_journal/` written mid-run (`src/inspect_ai/log/_recorders/eval.py:111-120`,
`:2005`). `log_finish` (`eval.py:304-372`) writes the consolidated summaries,
reductions and header last. Readers dedupe summaries by `(id, epoch)`, last
row wins (`eval.py:1920`).

**Reading.** `read_eval_log` dispatches on the location's extension to a
recorder (`_file.py:581-657`); `read_eval_log_samples` iterates
`dataset.sample_ids × epochs` of one file and raises unless the log is a
`success` (`_file.py:1037-1103`). `list_eval_logs` returns `EvalLogInfo`
records with `task` and `task_id` parsed from the file name
(`_file.py:107`, `:1178-1250`). `resolve_logs` in the dataframe layer turns a
directory into that list (`src/inspect_ai/analysis/_dataframe/util.py:51`);
`samples_df` reads each log's `summaries.json`
(`analysis/_dataframe/samples/table.py:331-338`).

**Viewer.** `/logs` and `/log-files` (`fastapi_server.py:360-407`) return one
`LogHandle` per file with `task` and `task_id`; the client keeps that
granularity (`task_id` is used only to drop a pending row once its file
appears, `apps/inspect/src/app/log-list/grid/useLogListData.ts:35-46`). Live
sample data comes from a per-log sample buffer keyed by the log file
(`/pending-samples`, `fastapi_server.py:507`; `sample_buffer(location)` in
`src/inspect_ai/log/_recorders/buffer/buffer.py:10`).

**Eval sets over shards** (spike results):

- `validate_eval_set_prerequisites` (`evalset.py:1986`) accepts both shard
  logs, because both map to the task's identifier.
- `latest_completed_task_eval_logs` (`evalset.py:1939`) groups by `task_id`,
  so the shards are two groups, never compared or cleaned against each other.
- `log_samples_complete` (`evalset.py:1837`) compares counts, not ids:
  `samples_selected(dataset, limit, sample_id)` against
  `results.total_samples`. With no selector, planned 6 ≠ 3 for both shards, so
  both are incomplete; `as_previous_tasks` pairs the task with the *first* log
  carrying its identifier and re-runs it from that shard. Observed: a new
  6-sample log under the first shard's `task_id` (3 reused, 3 re-run), the
  second shard left in place as an orphan that `eval-set.json` does not list.
- With `--sample-id s0,s1,s2`, planned 3 = 3 for both shards, so the shard
  holding `s3,s4,s5` is also classified complete and the set finishes with
  nothing run. That is a latent bug independent of sharding (a `--limit 3`
  log would be accepted for a different `--sample-id` of size 3), filed under
  "Not this design".

**Selection mode today.** A runner can already launch N workers of one task
with N different `sample_id` overrides; `_selected_eval_set_tasks`
(`evalset.py:1629-1696`) only rejects an identifier that matches zero or more
than one *resolved task*, not the same task named across N selection files.
Each worker writes a distinct file (fresh `task_id`), so nothing collides. The
result is exactly the unrecognised-shards state described above.

## Options

All options share two pieces of groundwork, listed once here rather than
repeated:

- **A shard marker in the header.** Something must say "this log is shard *k*
  of a group *g* covering ids *S* of a task whose full selection is *T*".
  Candidates are a new `EvalSpec` field (say `shard` with a group id, index,
  count and the group's intended sample selection), or re-using an existing
  id. Re-using `task_id` is tempting because `EvalLogInfo` and the viewer
  already carry it, but `latest_completed_task_eval_logs` treats same-`task_id`
  logs as retry attempts of one another and *deletes* all but the newest when
  `retry_cleanup=True` (`evalset.py:1962-1975`), so shards sharing a `task_id`
  would be destroyed by the first eval-set pass. A new field is the safe
  in-header choice and the options below were compared assuming one; it is a
  public log-schema change (JSON schema, generated TypeScript types,
  `EvalSpec` consumers). **Superseded for the chosen direction (Ransom,
  2026-09-21):** the marker is a directory convention, not a header field;
  see "Direction". The analysis stays as the rationale for why a shared
  `task_id` was never an option.
- **Whole-task results computation.** Every option needs to compute results
  over the union of shards' scores, and per "Constraints" that is a Python
  step that needs the metric code and trusts the log's header. The options
  differ in *when* it runs, *who* runs it, and *where the answer lives*:
  once, by a trusted aggregator, stored for every reader (A, C's manifest),
  or per read by a Python reader that has the code (B without a stored
  result). Readers that cannot run it, which is the browser client in all
  three hosts, can show only stored values. Whether the input is summaries
  (cheap, value-only metrics) or full samples (lossless, expensive on remote
  storage) is a separate cost every option pays.
- **Group membership validation.** Before combining, an aggregator or reader
  must check that members really are shards of one task: same task
  identifier, same `task_version`, model, plan and config, disjoint id sets
  that together equal the group's intended selection, and equal epochs. A
  reused group id that skipped this check would yield plausible metrics over
  incompatible samples. The exact rule is a phase-2 decision; the cost is
  common to all options.
- **Writer-side surface.** Whoever stamps the marker needs a way to say it:
  the external runner through the selection document, and, if ordinary
  `eval()` and `inspect eval` callers are in scope, a parameter or flag on
  those. This surface is the same for every option and is separate from who
  runs any merge or finalisation step (see "Who orchestrates"). Under the
  directory convention chosen on 2026-09-21 this surface already exists:
  `--log-dir` (and the selection protocol's per-worker `log_dir` override,
  `eval_set_overrides.py:164`) is the whole of it.

### Option A: merge shards into one canonical log after the run

A library function and CLI (`inspect log merge`, or a `--merge` step in the
runner) reads the shards of a group, writes one ordinary `.eval` containing
the union of samples, the union of summaries, recomputed `results` and
`reductions`, aggregated `stats` (min start, max finish, summed usage), and a
header whose `dataset.sample_ids` is the union in dataset order and whose
`config.sample_id`/`limit` describe the group's selection. Shards can then be
deleted or kept beside it. The shard marker also records provenance in the
merged header (which shards, their `eval_id`s).

- **Advantages.** No reader changes, **provided the shards leave the tree
  readers list** (deleted, or moved to an archive prefix outside the
  recursively listed log directory) or readers are pointed at the merged
  file explicitly. Under that condition the viewer, `read_eval_log*`,
  dataframes, Scout, `inspect score`, log editing and eval-set matching all
  see one normal log with stored whole-task results. Aggregation runs
  exactly once, in the merge, which is a trusted Python step run by the
  runner or user who owns the eval and has its metric code, so no reader
  ever recomputes or imports log-named code. Needs no relaxation of the
  self-contained-log constraint: the merged log *is* the whole truth, and
  shards are ordinary partial logs until they are merged away. Old Inspect
  versions can open the output. Smallest surface; most of the work
  is in one module and mirrors what `recover_eval_log` already does
  (combine sample sources, recompute results).
- **Disadvantages.** Someone must run the merge after the last shard
  finishes, so it needs an owner (see "Who orchestrates" below). No
  whole-task view while shards are still running or if a shard fails and is
  never retried. If shards must stay beside the merged file in the same
  listed directory, the zero-change claim fails: `list_eval_logs` lists every
  file (`_file.py:146`), dataframe directory expansion recurses over them
  (`analysis/_dataframe/util.py:93-109`), `evals_df` dedupes by `eval_id`
  only (`analysis/_dataframe/evals/table.py:160`), the viewer lists per file
  and eval-set pairing still meets the shard logs (the reviewer's probe with
  two shards plus their merge gave three listed files and three eval rows;
  `samples_df` alone collapses on sample `uuid`). Hiding retained shards
  then costs listing, dataframe, viewer and eval-set changes, which is a
  slice of Option B. Storage is doubled until shards are deleted; the merge
  rewrites every sample member (Python's `zipfile` has no raw member copy),
  which for very large logs on remote storage is a full download and upload
  per merge. Retry of a failed shard is a retry of *that shard's* log, then a
  re-merge.
- **Complexity.** Small to medium. Merge module, CLI, schema field, tests.
- **Compatibility.** Additive: new header field, new CLI/API. Nothing
  existing changes meaning.
- **Risks.** A merged log that silently omits a missing shard would present a
  partial task as complete; the merge must refuse unless the group is whole
  (all indices present, every `success`, id sets disjoint and equal to the
  intended selection) or be told explicitly to produce a partial result with
  a non-`success` status. Order of samples in the merged log and the
  interaction with `reductions`/epoch reducers need care but follow existing
  code.

### Option B: readers understand a shard group as one logical log

Keep the shards as the durable format. Teach readers to group logs by the
shard marker and present the group as one `EvalLog`: `list_eval_logs` returns
one entry per group, `read_eval_log` of a group routes sample reads to the
shard holding each `(id, epoch)`, summaries are concatenated, and whole-task
`results` come either from recomputation in a Python reader (B1) or from a
stored group results object written by a trusted aggregator (B2). The
viewer's TypeScript client groups the listing and routes sample reads the
same way but only ever reads stored results; eval-set completeness reasons
over the union.

- **Advantages.** No post-run step for *samples*: a group is readable as a
  unit as soon as any shard has flushed, and no second copy of the data is
  kept. A partial view of a sharded task (its samples, summaries and
  per-shard metrics) exists during the run, which fits the "one sample per
  machine" case where the last shard may be hours behind the first. Closest
  to the Scout analogy in the issue.
- **Disadvantages.** Touches every reader: the Python log API (a log
  "location" becomes a group, which breaks `EvalLog.location: str`,
  `write_eval_log`, log editing, `inspect log dump/convert`, header-only
  reads that assume one central directory), the dataframe layer, eval-set
  pairing and cleanup, Scout's eval-log transcript reader, and the
  TypeScript client in every host (server, VS Code, static bundle, which has
  no server to synthesise anything). **Whole-task metrics are not free of a
  post-run step.** Per "Constraints" they need Python plus the metric code,
  so B has two sub-variants: (B1) a Python reader recomputes on each group
  read using metric code that is already installed and trusted in the
  reader's process, with the `task_file` fallback disabled per "Security",
  which means `read_eval_log` and `evals_df` start executing metric code and
  fail on a group whose metrics are not installed, and the browser client
  still cannot show whole-task metrics in any host; or (B2) a trusted
  aggregation step (the last shard to finish, or the runner) writes a stored
  results object for the group, which is Option A's post-run step and
  ownership question with a different output file. Without B2 a browser
  reader shows per-shard metrics and sample counts only.
  Relies on the sharding-only relaxation of the self-contained-log constraint
  (decision above): grouping must be keyed strictly on the shard marker so
  unsharded logs keep today's semantics, and the "newest log is the truth"
  rule for retries has to be restated for a group whose members are retried
  individually.
- **Complexity.** Large. Two codebases (Python and `ts-mono`), a
  cross-repo release, and a new concept in the public API.
- **Compatibility.** Old readers see N independent logs (no worse than
  today). New readers see one; anything keyed on file name or `EvalLogInfo`
  changes shape. Scout's transcript source for eval logs would need to
  adopt the grouping to avoid N-fold eval metadata.
- **Risks.** Partial groups: what a reader shows while shards are missing,
  failed, or being retried, and how it avoids presenting a partial mean as
  the task's accuracy. Performance on remote storage: a group read is N
  header reads plus N summary reads before anything renders. Highest chance
  of long-tail bugs because the number of consumers is large and some are
  outside this repo.

### Option C: a sharded log is a directory with a manifest

Introduce a directory form of a log: `{created}_{task}_{id}.eval.d/` (name to
be chosen) holding `manifest.json` and the shard `.eval` files, with a
`ShardedEvalRecorder` handling the location in the recorder layer so
`read_eval_log*` and `list_eval_logs` see one location (`EvalLogInfo.type`
already allows `"directory"`, `_file.py:57`). Workers write ordinary `.eval`
shards into the directory; a finalise step writes `manifest.json` with the
whole-task results, and readers never recompute (before the manifest exists
they see the shards' stored per-shard results).

- **Advantages.** One location per task, so the Python API's "a log is a
  location" model survives and the recorder abstraction contains the
  change. Grouping is explicit on disk rather than inferred from headers.
  Shards remain valid `.eval` files. Whole-task results are written once by
  the trusted finaliser (into the manifest) and read cheaply by every reader,
  including the browser client; readers never recompute. Before the manifest
  exists a reader has only the shards' stored per-shard results, the same
  limit as B without B2.
- **Disadvantages.** A new on-disk format that every consumer must learn,
  including the TypeScript client and Scout; old Inspect versions cannot
  open the directory as a log at all (they would list the shards inside it
  as N logs if they recurse, or nothing). Uses the sharding-only relaxation
  of the self-contained-log constraint, contained to one directory: the
  directory is the unit of truth, its member files are not, and files
  outside a marked directory keep today's semantics. Directories are a weak
  concept on S3 (listing cost, no atomic finalise). Still needs a finaliser to write the
  manifest, so it has Option A's orchestration question plus Option B's
  reader work in the viewer.
- **Complexity.** Large. Recorder, listing, viewer client, Scout, plus the
  finaliser.
- **Compatibility.** A format addition rather than a change, but a
  breaking one for any reader that has not been updated.
- **Risks.** Same partial-group questions as B, plus format-versioning of
  the manifest and directory naming collisions with the current flat
  listing.

### Option D: workers write into one shared log

Shards append to a single `.eval`, or write per-sample objects into a shared
prefix that mirrors the zip layout (`samples/{id}_epoch_{n}.json` as objects)
with a finaliser writing header and summaries.

- **Assessment.** Appending to one zip from many processes is not safe, and
  S3 has no append, so the single-file variant is not viable. The exploded
  prefix variant is Option C with per-sample objects instead of per-shard
  zips: it removes the merge cost but multiplies object count (listing and
  small-object costs on S3, no compression across samples), gives the viewer
  a third reader to implement, and keeps the finaliser. Listed for
  completeness; not recommended for further comparison unless the per-shard
  zip merge cost in A turns out to dominate.

### Who orchestrates (orthogonal to A–D)

Any option with a post-run step (A's merge, C's finalise) needs an owner:

1. **The external runner** (selection protocol). The runner already knows
   when every worker has exited; it stamps the shard marker (under the chosen
   direction, by setting each worker's `log_dir`) via the selection
   document and runs the merge/finalise. Fits the existing division of labour
   ("the runner is the sole writer of the directory's eval-set metadata").
   Costs a selection schema version bump and a change to the one-task-one-log
   invariant.
2. **`eval_set()` itself.** Teach the in-process eval set to run a task's
   shards (as separate `eval()` calls or subprocesses) and merge at the end.
   Only helps single-machine sharding, which is not the issue's case.
3. **The user, via CLI.** `inspect log merge <dir-or-files>` run by hand or
   from a job script. Simplest to ship; least automatic.

Option B has no post-run step for samples but, per its B2 variant, needs one
for whole-task metrics unless readers recompute; its marker is stamped by
the same writer-side surface every option needs, by the runner (1) or by the
user through `eval()`/CLI (3). Ownership of the merge or finalise step and
exposure of shard identity to ordinary callers are separate questions, and
each of A, B and C can be served by either owner.

## Comparison

| | A: merge after run | B: readers group shards | C: directory + manifest | D: shared log |
|---|---|---|---|---|
| Reader changes | none if shards leave the listed tree; listing/dataframe/viewer/eval-set changes if shards stay beside the merge | Python API, dataframes, eval-set, viewer TS (3 hosts), Scout | recorder layer, listing, viewer TS, Scout | as C plus a third reader |
| Writer changes | shard marker | shard marker | shard marker, directory layout | new writer |
| Post-run step | merge (owner needed) | none for samples; B2 aggregation (owner needed) for whole-task metrics | finalise (owner needed) | finalise |
| Whole-task samples during run | no | yes (partial) | yes | yes |
| Whole-task metrics during run | no | B1: Python readers with the code only; B2: after aggregation | after finalise | after finalise |
| Who runs metric code | merger (trusted, once) | B1: every Python reader; B2: aggregator | finaliser | finaliser |
| Browser client shows whole-task metrics | yes (stored) | B2 only (stored) | yes once manifest exists | yes once finalised |
| Old readers open the result | yes | shards only | no | no |
| Self-contained-log constraint (relaxation allowed for sharded output only, Ransom 2026-09-18) | not needed | uses it: cross-file group keyed on the marker | uses it: cross-file group inside one directory | uses it: shared file or prefix |
| Storage | 2× until shards deleted | 1× | 1× | 1× |
| Where results live | merged header | B1 recomputed per read; B2 stored group results | manifest | header |
| Complexity | S–M | L | L | L |
| Main risk | partial merge presented as whole; shards left in the listed tree | partial-group semantics across many consumers; readers importing log-named code (B1) | format adoption, S3 directory semantics | S3 object counts, concurrency |

Recompute input applies to every column: summaries suffice only for metrics
and reducers over score `value`; anything else needs full sample reads.

## Key questions to choose

The questions are kept as asked, with the answers recorded where a decision
has been made. Dates and deciders are on each answer.

1. **Is a post-run merge acceptable, or must a sharded task read as one log
   while shards are still running?** Answered (Ransom and JJ Allaire,
   2026-09-18): a post-run merge is acceptable, phased. Step 1 ships the
   merge alone (Option A); a during-run whole-task view arrives as Step 2
   (periodic rollup of headers and summaries) and Step 3 (targeted live-view
   work). See "Direction".
2. **Does the #420 self-contained-log constraint apply here?** Answered
   (Ransom, 2026-09-18): the constraint may be relaxed for this sharding and
   continues to hold in every other case. B and C are therefore open on this
   axis; A remains the option that needs no relaxation. Any chosen grouping
   must be keyed on an explicit marker so unsharded logs and retries keep
   today's semantics; since 2026-09-21 that marker is the `shards/<group>/`
   directory convention (question 5).
3. **Who owns the merge or finalise step, and is shard identity exposed to
   ordinary callers?** Two independent decisions.
   (a) Ownership of the end-of-run merge: answered (Ransom, 2026-09-18):
   launcher-owned by default, with the merge built idempotent and
   deterministic so the distributed model is a configuration rather than a
   different design. The comparison under "Direction" is the rationale.
   (b) Exposure: dissolved by the directory convention (Ransom, 2026-09-21).
   Shard identity is the log directory, so
   `inspect eval --log-dir <dir>/shards/<group>/` (or `eval(log_dir=...)`,
   or the selection protocol's per-worker `log_dir` override) is the whole
   writer surface, for runner and shell-script users alike. The group's
   intended selection is supplied to the merge separately (see "Completeness
   input" under Step 1).
4. **Is the viewer in scope for the first implementation?** Answered (Ransom
   and JJ Allaire, 2026-09-18): no. Step 1 needs no viewer behaviour change;
   the viewer sees an ordinary merged log and, while shards run, ordinary
   per-shard logs. With the directory convention (2026-09-21) no header
   field is needed, so the `ts-mono` generated types do not change in Step 1
   as long as provenance lives in `eval.metadata` (see Step 1 requirements);
   the viewer server does pick up the shared listing exclusion. Viewer work
   is Step 3.
5. **Shard identity.** Answered (Ransom, 2026-09-21, revising the
   2026-09-18 answer of a new `EvalSpec` field): the directory convention
   `<log_dir>/shards/<group>/` is the marker; nothing is added to the shard
   header. Shards keep distinct `task_id`s and never share one, because of
   the `retry_cleanup` deletion hazard. Provenance for the *merged* log lives
   in the existing `eval.metadata` dict under a reserved key for Step 1,
   with a typed field as a later option (comparison under Step 1).
6. **Partial groups.** Answered (Ransom and JJ Allaire, 2026-09-18) for the
   merge: it refuses a partial group unless explicitly told to emit a log
   with a non-`success` status, which then acts as an ordinary resumable
   log. Partial-group *display* in readers is a Step 3 question.
7. **Recompute input and metric support.** Answered (Ransom and JJ Allaire,
   2026-09-18): the merge recomputes from full samples, as recovery does,
   not from summaries; correctness is contained to the merging process,
   which must have the task's metric code importable. Step 2's rollup, which
   reads summaries, is therefore a live approximation with a value-only
   guarantee, not the recorded result (see Step 2).

## Direction (phase 2 entry)

Decision (Ransom and JJ Allaire, 2026-09-18): proceed in three steps, each
shippable on its own, with Option B in full kept as the comparison
alternative. This section records the direction and the requirements the
options analysis attaches to it. It does not fix API signatures or an
implementation plan; those are the next document.

### Step 1: separate shard files, merged into one canonical log (Option A)

Shards are ordinary `.eval` files written into `<log_dir>/shards/<group>/`,
and are merged into one canonical log in `<log_dir>` at three triggers: at
eval end (the launcher's end, see ownership below), at `eval_set()` startup,
and by a new CLI command. The whole feature is opt-in: a run that does not
write under `shards/` is untouched, so Step 1 can ship alone.

**The directory convention is the marker (Ransom, 2026-09-21).** No field is
added to the shard header. A `.eval` file under a `shards/<group>/`
directory is a shard of that group; a file anywhere else is an ordinary log;
copying a shard out of its directory makes it an ordinary partial log. That
boundary is exactly the sharding-only relaxation of the self-contained-log
constraint. Consequences:

- *Writer surface.* Shard identity is the log directory, so `--log-dir`
  (`eval(log_dir=...)`, `inspect eval --log-dir`, or the selection
  protocol's per-worker `log_dir` override, `eval_set_overrides.py:164`) is
  the whole writer surface; key question 3(b) dissolves. Nothing else in the
  writer changes: the shard's sample buffer lands beside it
  (`shards/<group>/.buffer`, `sample_buffer_dir`, `filestore.py:662`), so
  `inspect view --log-dir <dir>/shards/<group>/` shows the shards live. One
  caveat: an ordinary `eval_set()` (not a selection-mode worker) pointed at
  a shard directory would write its own `eval-set.json`, `logs.json` and
  `.eval-set-id` there; the merge ignores non-`.eval` files, but sharding is
  meant for `eval()` and selection-mode workers, not nested eval sets.
- *No `ts-mono` landing for Step 1.* The earlier requirement for a
  coordinated `ts-mono` landing came from a header field. With the
  convention it drops, provided the merged log's provenance goes into the
  existing `eval.metadata` dict (`EvalSpec.metadata: dict[str, Any] | None`,
  `_log.py:1097`) rather than a new field. Comparison: `eval.metadata` needs
  no schema change and ships with Step 1 alone, but it is a user-owned
  namespace (task and eval `metadata=`), so the merge writes under a
  reserved key and the entry surfaces in `evals_df` metadata columns beside
  the user's; a typed field is cleaner and viewer-readable but costs the
  JSON schema, the generated TypeScript types and a `ts-mono` landing.
  Recommendation: `eval.metadata` under a reserved key for Step 1; promote
  to a typed field if and when Step 3 needs the viewer to read it.
- *The listing exclusion is load-bearing.* Shards live in `shards/` from
  their first byte, so every enumerator must skip that tree or the shards
  appear as N logs while running: `list_eval_logs` and
  `list_eval_logs_async`, the dataframe directory expansion, the viewer
  server's `/logs` and `/log-files`, `bundle_log_dir`, `convert_eval_logs`,
  and `eval_set()`'s directory scan. All of them funnel through one filter,
  `_filter_log_files` via `log_files_from_ls` and its async variant
  (`_file.py:1118-1163`; callers at `_file.py:147,256,274,305,317`,
  `analysis/_dataframe/util.py:108`, `_convert.py:105`, `_bundle.py:12`;
  the viewer and `eval_set()` reach it through `list_eval_logs_async` and
  `list_eval_logs`), so the exclusion has one home. The filter sees full
  paths but not the listed root, and the rule must be stated in terms of
  the root to be safe. Two candidate rules: (i) *direct child*: exclude
  files whose path relative to the listed root starts with the component
  `shards`; precise, hides nothing else, but a viewer or `evals_df` pointed
  at a *parent* of the log directory (the common `inspect view --log-dir
  ./logs` over many run directories) would list every run's shards; (ii)
  *any depth below the root*: exclude files whose path relative to the
  listed root contains a component named exactly `shards`; covers the
  parent-listing case, and hides a user's unrelated directory only if it is
  literally named `shards` and holds `.eval` files (those files stay
  readable by direct path and by listing that directory itself, since the
  rule is relative to the root). Recommendation: (ii), with the root
  threaded into the filter so listing `<dir>/shards/<group>/` directly still
  shows the shards. Shards are found for merging by a dedicated scan of
  `<log_dir>/shards/*/`, never through the listing.
- *Group validation is strict.* Membership is by location, so a stray
  `.eval` file in the directory is a candidate member. The merge checks
  every member: same task identifier, `task_version`, model, plan and config
  with the selectors (`sample_id`, `limit`, `sample_shuffle`) excluded from
  the comparison, equal epochs, disjoint `(id, epoch)` sets, and refuses on
  any mismatch rather than skipping the odd file.
- *Completeness input.* Headers cannot say whether a group is complete when
  the group is a subset of the dataset: each shard records only its own
  `dataset.sample_ids`, and `dataset.samples` is the full dataset size. Two
  inputs: (a) a small group file written by the launcher into
  `shards/<group>/` (say `group.json`) with the intended `(id, epoch)`
  selection, or the shard count when ids are not known, plus the task
  identity it expects; (b) a count or id list passed to the merge (CLI
  argument or `eval_set()` parameter). Comparison: ids let the merge name
  the missing samples, which is what the non-`success` resume path needs,
  and detect a wrong member; a shard count only proves that N `success`
  shards exist and relies on disjointness for coverage. JJ's harness
  already knows the shard count and, having assigned the ids, knows those
  too. Recommendation: (a), a group file with the intended selection,
  written before the workers start and re-read by every merge (it is also
  how group growth is expressed, see "Incremental merge"); (b) as the CLI
  override for hand-driven cases; the whole-dataset case needs neither,
  since the union's size can be checked against `dataset.samples`.

What is lost while shards are running is the whole-task rollup only, not
per-sample liveness. Each shard is a normal in-progress log, so a viewer
pointed at the shard directory lists it, shows its samples as they complete,
and the running-sample view works through the per-shard sample buffer
(`/pending-samples`, `fastapi_server.py:507`). What no reader has until the
merge is one row and one set of metrics for the task; with the incremental
merge below, a `started` merged log can provide that during the run too.

Note for harnesses that stage logs on local disk and upload at the end (JJ's
benchmark harness proposal): `--log-shared` syncs the sample buffer into a
`.buffer` directory inside the log directory itself (`filestore.py:662`,
`database.py:286-289`), so with a local staging directory it publishes
nothing a remote viewer can reach; there is no live visibility during the
run; and a shard is lost if the instance dies before the upload. Writing
`--log-dir` straight to the shared `shards/<group>/` prefix restores all
three. Also, `limit` and `sample_id` are mutually exclusive in `eval()`
(`eval.py:907`), so a harness that shards a *subset* of a dataset must
resolve the subset to ids first and hand each worker its `sample_id` list.

Requirements and open points Step 1 carries from the options analysis:

- **Shard disposition after the merge.** Under the header-marker design the
  question was where merged shards go, because shards beside the merged log
  break "no reader changes": `list_eval_logs` recurses over every `.eval`
  file (`_file.py:146`), `evals_df` dedupes by `eval_id` only
  (`analysis/_dataframe/evals/table.py:160`), and the viewer lists per file.
  Three dispositions were compared: (i) *delete*, which loses re-merge after
  a merge bug and could delete a shard still writing; (ii) *archive prefix*
  hidden by a listing exclusion; (iii) a *file-name convention*. Ransom
  chose (ii) on 2026-09-18. Under the directory convention (2026-09-21) the
  shards are already in the excluded tree from their first write, so no move
  is needed: they stay in `shards/<group>/` until the merged log is
  verified, and delete is offered as an explicit option. The earlier text
  overstated the cost of a move: on S3 a move is a server-side copy plus a
  delete, one API round trip per shard, not a transfer of the data through
  the client (a single `CopyObject` up to 5 GB; larger objects need a
  multipart copy). Deleting by default remains the one choice that cannot
  be undone after a bad merge.
- **Eval-set bookkeeping is shard-aware.** Today completeness compares
  counts (`evalset.py:1837`), pairing takes the first log with a matching
  identifier (`evalset.py:1483-1489`), and `retry_cleanup` (on by default)
  deletes every non-`started` log sharing a `task_id` except the newest
  (`evalset.py:1962-1975`). Shards keep distinct `task_id`s, never a shared
  one, and are invisible to these paths because they live under `shards/`.
  `eval_set()` startup scans `shards/*/` and runs the incremental merge
  before any pairing, at the point where it lists the directory today
  (`evalset.py:1043-1060`); the merged log then takes part in pairing as an
  ordinary log. Two hazards: a `started` merged log must be recognised by
  its provenance and re-merged, not handed to `_recover_crashed_log`
  (`evalset.py:1512`) as a crashed log; and `retry_cleanup` must not delete
  an older merged log while a newer resume log for the same task exists
  before the resume has completed, which is today's rule and fine. Upside:
  merging a partial group at startup into a non-`success` log turns a
  sharded run into an ordinary resume; the missing samples are re-run by
  the normal retry path, unsharded unless the runner re-shards them.
- **Metric correctness, contained to the merger.** The merge recomputes
  results from full samples, as recovery does
  (`_recover/_write.py:162-177`), not from summaries. It needs the task's
  metric code importable: a runner or an `eval_set()` process has it; a CLI
  merge from a laptop may not, and then `resolve_scorers_info`'s `task_file`
  fallback imports log-named code exactly as recovery does today
  (`score.py:653-665`). The merge must say clearly which of the two it did,
  and fail rather than store metrics computed from a lossy input.
- **The merge is trusted (confirmed, Ransom, 2026-09-21).** The merged log
  is created only by a trusted Python step: the launcher at end of run,
  `eval_set()` at startup, or the CLI. No reader creates or recomputes it:
  the viewer, `list_eval_logs` and the dataframe layer read what the merge
  stored and never run metric code or import a `task_file` on a reader path.

### Who owns the end-of-run merge (decided; comparison kept as rationale)

Ransom asked for this to be explored and then confirmed the recommendation
below (2026-09-18). Two owners are viable; both are compared against the
other two triggers and against runner protocols that already watch workers,
and the comparison stands as the rationale for the decision.

**Launcher-owned.** One process launches the workers, watches for the shard
logs to complete, and merges. Advantages: a single, race-free owner; it
matches the external-runner owner in "Who orchestrates" and the selection
protocol's existing division of labour (the runner already owns the
directory's eval-set metadata and knows when each worker exits); the merger
is the process most likely to have the task's code importable; no worker
pays the merge cost. Disadvantage: a single point of failure. If the
launcher dies between the last worker finishing and the merge, no merged log
exists; the `eval_set()`-startup merge is the recovery path, and the CLI
merge is the manual one. "At eval end" in this model means the launcher's
end, which is also the natural point when one process ran the shards itself.

**Distributed.** Each worker, on finishing, lists the group and merges if it
sees every shard complete. Advantages: no launcher dependency, and the merge
happens as soon as the last shard lands. Disadvantages: two near-simultaneous
finishers can both observe a complete group, so the merge must be idempotent
and deterministic (output name derived from the group id, refuse if it
already exists) rather than lock-based, because a create-if-absent
conditional write is not available uniformly: Inspect's own S3 writer
supports `IfMatch` for replacing an object with a known ETag
(`_recorders/eval.py:753-761`), not create-if-absent, and only for S3
through boto, not through fsspec. With a deterministic merge the residual
race is two writers producing byte-equivalent output to one key, which S3's
per-object atomic put and a local atomic rename both tolerate. In a
one-sample-per-machine job the last worker downloads the whole task's
samples to merge them, which puts the largest transfer on an arbitrary
worker at the end of the job. It also needs every worker to have the task's
metric code, which workers do.

**Against the other triggers.** The `eval_set()`-startup merge is the safety
net for both owners: whichever owner fails to merge, the next `eval_set()`
over the directory merges or excludes the shards before pairing. The CLI
merge serves users without a runner and repairs any state by hand. Runner
protocols that already watch workers (the capture/selection runner,
`inspect_steward` per `eval_set_manifest.py`) get launcher-owned merging
for free, since they already sit where the launcher would.

**Decision (Ransom, 2026-09-18).** Launcher-owned as the default, with the
merge itself built idempotent and deterministic so that the distributed
model is a configuration rather than a different design: a worker can be
told to attempt the merge on exit, and a duplicate attempt is harmless. The
reasoning: the runner protocol already has a single watching owner, the
launcher is the process with the task's code and the whole-group view, and
its failure mode is covered by the startup merge, whereas the distributed
model's failure mode (two merges, or a worker without the code) has to be
designed away in every deployment. With the incremental merge (below), the
launcher merge and the `eval_set()`-startup merge are the same operation,
"merge whatever is new", idempotent and keyed on the group directory; the
launcher may run it more than once during the run, and startup runs it once
more before pairing.

### Incremental merge (decided; design explored)

**Decision (Ransom, 2026-09-21).** Merging must support merging once and then
pulling in additional samples from the shards (shards still running, or
grown since the last merge) and additional shards added to the group later.
The merge therefore needs a way to track what it has already merged. The
points below explore the shape and end in recommendations; they are design
positions, not API.

- **Where the ledger lives.** Two candidates. (i) *In the merged log
  itself*: its own `samples/` members are the set of merged `(id, epoch)`
  samples, and per-shard high-water marks (shard file name, shard
  `eval_id`, samples-merged count, the shard's status at merge time, its
  mtime or ETag) live in the merged header's provenance entry
  (`eval.metadata`, see Step 1), so a fully merged, `success` shard is
  skipped without opening it and a grown shard is re-read only for the
  members the merged log lacks. (ii) *A separate ledger file* in
  `shards/<group>/`, which is cheaper to update than a header (no zip
  rewrite for the ledger alone) but creates a second source of truth that
  can drift from the merged log (a merged log rebuilt after a bug, or copied
  elsewhere, carries no ledger). Weighed against the rule that the merged
  log is the whole truth for the group, (i) wins: the ledger travels with
  the log, deleting the merged log correctly forces a merge from scratch,
  and the header is rewritten by every merge anyway. Recommendation: (i).
- **Reading in-progress shards.** A shard still running has no
  `header.json`; Python readers already synthesise the header from
  `_journal/start.json` (`_recorders/eval.py:1867`) and read summaries from
  `_journal/summaries/*` (`_read_all_summaries_async`), exactly as the
  viewer's client does (`remoteLogFile.ts:329-411`) and as recovery does.
  Flushed samples are ordinary `samples/` members; samples still in the
  shard's buffer database are not visible and arrive at a later merge, so
  the shard's `log_buffer` flush cadence bounds how stale a merge can be.
  Per-shard metrics in a running shard are not final, which does not matter
  because the merge recomputes over the union.
- **Merged log status while the group is incomplete.** `started` (a
  non-`success` status) until every shard is `success` and the union of
  members equals the intended selection; then `success`. `eval_set()`
  already classifies any non-`success` log as incomplete
  (`evalset.py:1837-1860`), so it never treats an incomplete merged log as
  done. The startup path must recognise a `started` merged log by its
  provenance and re-merge rather than recover it (Step 1, eval-set
  bookkeeping).
- **Conflicts.** A retried shard can re-run a sample the merge already holds.
  Recommendation: newest wins, matching the retry rule that the newest
  attempt is the truth; "newest" by the shard's `created` time, with the
  sample's `completed_at` as the tie-break within a shard. The merged log's
  dedupe by `(id, epoch)` handles the replacement mechanically (later
  member of the same name wins, `_dedupe_summaries`, `eval.py:1920`), and
  the sample `uuid` changes with the re-run, so `samples_df` sees only the
  surviving copy. Two *different* shards both holding the same `(id, epoch)`
  in the same merge pass, neither superseding the other, is a disjointness
  violation and the merge refuses (Step 1, group validation).
- **Group growth.** Adding shards later changes the intended selection. The
  group file (Step 1, completeness input) is the authority: the launcher
  rewrites it, every merge re-reads it, and the merged header records the
  selection it last merged against. A group that grows after the merged log
  reached `success` makes that log incomplete again, so the next merge
  returns it to `started` until the new shards land; the merge must allow
  that transition and say so in its output.
- **Cost shape.** Baseline: each incremental merge rewrites the merged zip in
  full, because `zipfile` has no raw member copy and its append mode exists
  only for local files (`_replace_eval_header_in_place`, `eval.py:568-590`;
  the S3 path rewrites, `_rewrite_eval_zip_with_new_header`, `:592`). So
  each pass costs the merged log's size plus the new members, and k passes
  over a run rewrite roughly k times the final size; on S3 that is a
  download and upload per pass. Optimisation for large logs on S3:
  server-side composition with `UploadPartCopy`, copying byte ranges of
  shard members straight from the shard objects into the merged object, with
  the merged central directory built locally and uploaded as the last part.
  Constraints: parts other than the last must be at least 5 MiB, so small
  members must be batched into contiguous ranges; shard zips interleave
  `_journal/` members among `samples/`, so ranges are not contiguous across
  a shard and the journal bytes either ride along as dead bytes or force
  more parts; and local-file member offsets must be recomputed for the new
  central directory. Baseline first; composition when measured merges of
  large logs justify it. Inspect already has a multipart upload helper
  (`_util/asyncfiles.py:240`) to build on.
- **Triggers.** The launcher merge and the `eval_set()`-startup merge both
  become "merge whatever is new": idempotent, deterministic, keyed on the
  group directory, safe to run at any time and any number of times. The CLI
  is the same operation invoked by hand.

### Step 2: periodic rollup while the eval runs

Recorded decision (Ransom, 2026-09-18): a periodic rollup of shard headers
and summaries into a stored group results object (Option B2, in its light
form: no sample merging, only the stored whole-task results), so the viewer
can show live whole-task metrics while shards run, with samples merged at
the end by Step 1's merge.

The 2026-09-18 rationale against a periodic *full* merge was: `zipfile` has
no raw member copy, so every pass rewrites every sample, which on S3 is a
download and upload per tick and quadratic over the run; it would read
in-progress shards through their journals; and its output would need a
`started` status so `eval_set()` never treats it as complete. The
2026-09-21 incremental-merge decision answers the last two (journal reads
are how every reader already reads a running log; `started` is the merged
log's status until the group is complete) and leaves the first as the cost
shape recorded above. So there are now two routes to live whole-task
metrics, and Step 2's place should be re-checked: (a) the summaries-only
rollup, cheap per tick but a value-only approximation per key question 7,
labelled as such and never mistaken for the merge's recorded results; (b)
running the incremental merge periodically, which produces exact metrics in
a `started` merged log at the cost of a merged-zip rewrite per tick,
acceptable for moderate log sizes and reducible by S3 composition. Open
point for Ransom: whether Step 2 remains a separate step or becomes "run the
incremental merge on a timer" once Step 1 lands. JJ Allaire: Step 2 may be
skipped if Step 3 is imminent.

### Step 3: targeted live-view improvements

Live-view work for the high-value scenarios that want to be more live than
the merge allows (`inspect ctl`, the running-sample viewer, and similar). A
slice of Option B: the `shards/<group>/` directory convention plus the merged
log's provenance let the viewer collapse the rows of one group and show
per-shard metrics, without routing sample reads across files. The listing
exclusion means a viewer pointed at the log directory does not see shards
at all today; Step 3 decides whether it should show a group as one row with
live per-shard detail, which is the point where promoting provenance from
`eval.metadata` to a typed field (Step 1) becomes worth its `ts-mono` cost. The three-host constraint
(server, VS Code, static bundle) and per-member read authorization from
"Security" still apply to whatever this step touches.

### Alternative kept for comparison: Option B in full

Readers understand shard groups as one logical log. Better live visibility
than any of the steps above, at the cost of significant changes across the
Python API, the dataframe layer, eval-set bookkeeping, Scout and the
TypeScript client in three hosts, and with metric computation hard to get
right because whole-task metrics need user-defined Python that readers, and
never browsers, would have to run. Kept as the reference the phased plan is
measured against.

## Compatibility notes (at options level)

- As compared, all options added a header field, which would change
  `EvalSpec`, the JSON schema, the generated TypeScript types and any
  exhaustive `model_fields` enumeration. The chosen direction (2026-09-21)
  adds none: the marker is the `shards/<group>/` directory convention, and
  merged-log provenance goes into the existing `eval.metadata` dict under a
  reserved key. Old Inspect versions read a merged log as an ordinary log
  and, lacking the listing exclusion, list shards as N ordinary partial
  logs, which is today's behaviour.
- A adds an API/CLI and, under the directory convention, one listing rule
  (files under a `shards` component below the listed root are skipped) that
  every enumerator inherits through `_filter_log_files`. B changes what
  `list_eval_logs`, `EvalLogInfo` and the viewer listing mean for sharded
  directories. C adds a location kind old versions cannot read.
- `.json` format logs are deprecated; every option can be `.eval`-only.
- Eval-set completeness (`log_samples_complete`) must in all options stop
  comparing counts when a group is present (a `shards/` directory or a
  merged log's provenance), either by treating a merged
  log as the task's log (A) or by reasoning over the union (B, C).

## Security (at options level)

The new code reads log headers, file names and, in C, a manifest naming other
files. Headers and file names are already untrusted inputs to the existing
readers and go through `filesystem()`/`local_path()`; sample JSON from shards
is parsed by the same Pydantic models as today.

Two boundaries are new:

- **Recomputation executes code the log names.** `resolve_scorers_info`
  imports the header's `task_file` when a metric is not registered
  (`score.py:653-665`), and `metric_from_log` instantiates whatever the
  registry holds under the header's metric names. Today scoring, metric
  recomputation (including score edits, which recompute by default) and
  recovery can load task code this way, and recovery can also run during
  eval-set resume and eval retry rather than only as a chosen command;
  ordinary log reads deserialize stored results. An option in which an
  ordinary reader recomputes group results (B1)
  would make `read_eval_log`, `evals_df` or the viewer server import code
  named by a received log. Aggregation should run only where the log's code
  is trusted, which is the merger (A), aggregator (B2) or finaliser (C), and
  any reader-side recompute must not follow the `task_file` fallback.
- **Manifests and groups resolve other files.** C's manifest is a new pointer
  type and must be constrained to entries inside its own directory; B's
  grouping resolves members from headers. In the viewer both must apply the
  per-file `_validate_read` authorization to each member, not only to the
  group entry.

Under the chosen direction (2026-09-21) the boundaries are these: membership
is by location, so anything placed in `shards/<group>/` is a candidate
member and the merge's strict validation is the defence against a stray or
hostile file (it refuses, it does not skip); the group file in that
directory is untrusted input to the merge and is parsed with a strict model;
the merge is the only writer of the merged log and runs only as a trusted
Python step (launcher, `eval_set()` startup, CLI), never from a reader path;
the listing exclusion hides shards from enumeration but grants nothing, and
a viewer listing `shards/<group>/` directly is authorized per file as today.

## Testing (at options level)

- A: unit tests over mock-model shards like the spike (merge whole group,
  refuse partial group, recomputed metrics equal an unsharded run's for a
  built-in metric and for a custom metric that reads `answer`, to pin the
  recompute-input decision; `evals_df` one row once shards are removed from
  the listed tree; eval-set accepts the merged log). All local, no network,
  in `tests/log/` and `tests/test_eval_set.py`.
- All options that recompute: a test that a header naming an unregistered
  metric with a `task_file` does not import that file from a reader path.
- B and C: the same Python assertions plus listing/grouping tests, and
  viewer end-to-end tests in `ts-mono` for grouped listing and grouped
  sample reads across the three hosts.
- Chosen direction: listing tests for the exclusion (shards under
  `shards/<group>/` are absent from `list_eval_logs`, `evals_df`, the viewer
  listing and a bundle of the parent directory; present when that directory
  is listed directly; a user directory named `shards` above the listed root
  is unaffected); incremental-merge tests (merge, grow a shard, merge again
  and see only the new members added; add a shard and see the status return
  to `started`; a retried sample replaced by the newer copy; two shards
  overlapping refused; a stray non-matching `.eval` in the group refused);
  an eval-set startup test over a partial group producing a `started`
  merged log that the set then resumes; and a check that unsharded logs and
  a log directory without `shards/` are unaffected.

## Not this design

- `log_samples_complete` classifies a log complete by count, so a `--limit 3`
  or other-shard log satisfies a different 3-id `--sample-id` request
  (verified in the spike). Worth an issue on its own.
- An eval set over a directory containing unrecognised shards re-runs the
  task from the first matching log and orphans the others (spike). Fixed
  implicitly by any chosen option once shards are recognised; until then a
  clearer error would help.
- Per-epoch sharding (running one epoch of a sample on one worker) is not
  expressible with `sample_id`/`limit` and is out of scope.
- `resolve_scorers_info` imports a log's `task_file` to find unregistered
  metrics (`score.py:653-665`). That is today's behaviour for `inspect score`,
  the public `recompute_metrics` and `edit_score` (`log/_metric.py:39-41`,
  `log/_score.py:146-147`) and recovery, including recovery triggered during
  eval-set resume and eval retry, on any log, sharded or not; whether those
  operations should require an opt-in before importing log-named code is a
  separate question.
- `EvalDataset.samples` records the full dataset size while `sample_ids` is
  the slice; the pair is the only present hint that a log is partial and its
  documentation could say so.
