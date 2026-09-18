# Eval sharding with per-worker log files: options and trade-offs

Status: options document (phase 1), 2026-09-18. No approach is selected here;
this document exists so an approach can be chosen with the trade-offs in view.
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

- **Self-contained logs.** The #420 design adopted, on Ransom's review feedback,
  the constraint that *every log file stays self-contained, and the newest log
  for a task stays the whole truth about that task*
  (`design/retry-seeded-attempt-log.md:19`). A logical log spread over files
  is exactly the cross-file concept that constraint rejected for retries. Any
  option that teaches readers to look across files needs that constraint
  either re-affirmed as "retries only" or consciously relaxed.
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

Non-goals for this document: a chosen approach, API signatures, exhaustive edge
cases, an implementation plan. Those are phase 2.

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
  choice and every option below assumes one; it is a public log-schema change
  (JSON schema, generated TypeScript types, `EvalSpec` consumers).
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
  runs any merge or finalisation step (see "Who orchestrates").

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
  ever recomputes or imports log-named code. Fully honours the
  self-contained-log constraint; the merged log *is* the whole truth. Old
  Inspect versions can open the output. Smallest surface; most of the work
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
  Directly contradicts the self-contained-log constraint; the "newest log is
  the truth" rule for retries has to be restated for groups.
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
  as N logs if they recurse, or nothing). Directories are a weak concept on
  S3 (listing cost, no atomic finalise). Still needs a finaliser to write the
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
   when every worker has exited; it stamps the shard marker via the selection
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
| Self-contained-log constraint | kept | relaxed | relaxed (per directory) | relaxed |
| Storage | 2× until shards deleted | 1× | 1× | 1× |
| Where results live | merged header | B1 recomputed per read; B2 stored group results | manifest | header |
| Complexity | S–M | L | L | L |
| Main risk | partial merge presented as whole; shards left in the listed tree | partial-group semantics across many consumers; readers importing log-named code (B1) | format adoption, S3 directory semantics | S3 object counts, concurrency |

Recompute input applies to every column: summaries suffice only for metrics
and reducers over score `value`; anything else needs full sample reads.

## Key questions to choose

1. **Is a post-run merge acceptable, or must a sharded task read as one log
   while shards are still running?** This is the A-versus-B/C decision. The
   issue text ("read the sharded copies as a single logical log") reads as B;
   the "one sample per machine" motivation makes the during-run view
   valuable. If the answer is "after the run is fine", A dominates on cost
   and risk.
2. **Does the #420 self-contained-log constraint apply here?** If yes, only A
   (and a C variant that finalises into one file) qualifies. If it was meant
   for retries only, B and C are open.
3. **Who owns the merge or finalise step, and is shard identity exposed to
   ordinary callers?** Two independent decisions. (a) Ownership of A's merge,
   B2's aggregation or C's finalise: the external runner, `eval_set()`, or
   the user via CLI. (b) Whether `eval()` and `inspect eval` grow a way to
   stamp the shard marker and group selection, or whether only the selection
   protocol can. If (b) is yes, every option serves shell-script users: A
   with a CLI merge, B with user-stamped markers, C with a user-created group
   location plus a CLI finaliser. If (b) is no, sharding is a runner-only
   feature in every option.
7. **Recompute input and metric support.** Summaries-only recompute keeps
   aggregation cheap but changes results for custom metrics that read more
   than `value`; full-sample recompute is lossless but reads every shard's
   sample bytes. Is a value-only guarantee acceptable for a first version,
   with full-sample recompute as an option or a later step?
4. **Is the viewer in scope for the first implementation?** A needs no viewer
   work. B and C are mostly viewer work, across the server, VS Code and
   static-bundle hosts, in a separate repository with its own release.
5. **Shard identity.** A new `EvalSpec` field versus reusing `task_id` or
   `eval_set_id`. The `retry_cleanup` deletion hazard argues for a new field;
   the cost is a schema and generated-types change.
6. **Partial groups.** What a reader or merge does when a shard is missing,
   failed or still running: refuse, present with a non-`success` status, or
   present the partial set. This matters in every option but is the whole
   design in B.

## Compatibility notes (at options level)

- All options add a header field, so `EvalSpec`, the JSON schema, the
  generated TypeScript types and any exhaustive `model_fields` enumeration
  change. Old logs lack the field and are treated as unsharded.
- A adds an API/CLI; nothing existing changes. B changes what
  `list_eval_logs`, `EvalLogInfo` and the viewer listing mean for sharded
  directories. C adds a location kind old versions cannot read.
- `.json` format logs are deprecated; every option can be `.eval`-only.
- Eval-set completeness (`log_samples_complete`) must in all options stop
  comparing counts when a shard marker is present, either by treating a merged
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
- All: a header round-trip test for the new field and a check that unsharded
  logs are unaffected.

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
