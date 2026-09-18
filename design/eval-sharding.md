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
- **Results are recomputable from summaries.** `eval_results`
  (`src/inspect_ai/_eval/task/results.py:90`) takes sample scores plus the
  scorer, metric and reducer definitions, all of which the header records and
  `score.py` already rebuilds (`metrics_from_log_header`,
  `reducers_from_log_header`, `resolve_scorers_info`,
  `src/inspect_ai/_eval/score.py:562-648`); log recovery does the same
  recompute (`src/inspect_ai/log/_recover/_write.py:270-285`). Summary rows
  keep score values intact and thin only text and oversize metadata
  (`EvalSampleSummary.thin_data`, `src/inspect_ai/log/_log.py:371`;
  `thin_metadata`, `src/inspect_ai/log/_util.py:147`), so whole-task metrics
  can be recomputed from `summaries.json` alone, except grouped metrics keyed
  on metadata values larger than 1 KB.

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
  over the union of shards' scores. The recompute path exists (see
  "Constraints"); the options differ in *when* it runs and *where the answer
  lives*.

### Option A: merge shards into one canonical log after the run

A library function and CLI (`inspect log merge`, or a `--merge` step in the
runner) reads the shards of a group, writes one ordinary `.eval` containing
the union of samples, the union of summaries, recomputed `results` and
`reductions`, aggregated `stats` (min start, max finish, summed usage), and a
header whose `dataset.sample_ids` is the union in dataset order and whose
`config.sample_id`/`limit` describe the group's selection. Shards can then be
deleted or kept beside it. The shard marker also records provenance in the
merged header (which shards, their `eval_id`s).

- **Advantages.** Zero reader changes: the viewer, `read_eval_log*`,
  dataframes, Scout, `inspect score`, log editing and eval-set matching all
  see one normal log. Fully honours the self-contained-log constraint; the
  merged log *is* the whole truth. Old Inspect versions can open the output.
  Smallest surface; most of the work is in one module and mirrors what
  `recover_eval_log` already does (combine sample sources, recompute
  results).
- **Disadvantages.** Someone must run the merge after the last shard
  finishes, so it needs an owner (see "Who orchestrates" below). No
  whole-task view while shards are still running or if a shard fails and is
  never retried. Storage is doubled until shards are deleted; the merge
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
shard holding each `(id, epoch)`, summaries are concatenated, and `results`
are recomputed on read (or read from a small cached results object once the
group is complete). The viewer's listing and log reader do the same in
TypeScript; eval-set completeness reasons over the union.

- **Advantages.** No post-run step and no second copy of the data. A partial
  view of a sharded task exists as soon as any shard has flushed, which fits
  the "one sample per machine" case where the last shard may be hours behind
  the first. Closest to the Scout analogy in the issue.
- **Disadvantages.** Touches every reader: the Python log API (a log
  "location" becomes a group, which breaks `EvalLog.location: str`,
  `write_eval_log`, log editing, `inspect log dump/convert`, header-only
  reads that assume one central directory), the dataframe layer, eval-set
  pairing and cleanup, Scout's eval-log transcript reader, and the
  TypeScript client in every host (server, VS Code, static bundle, which has
  no server to synthesise anything). Results are recomputed on every read of
  a group unless a cache is written, and writing a cache is Option A's
  problem in disguise. Directly contradicts the self-contained-log
  constraint; the "newest log is the truth" rule for retries has to be
  restated for groups.
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
whole-task results, or readers compute them when the manifest is absent.

- **Advantages.** One location per task, so the Python API's "a log is a
  location" model survives and the recorder abstraction contains the
  change. Grouping is explicit on disk rather than inferred from headers.
  Shards remain valid `.eval` files. Whole-task results can be written once
  (in the manifest) and read cheaply.
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

Option B has no post-run step but needs the runner or user to stamp the
shard marker consistently, so it depends on (1) or (3) for the writer side.

## Comparison

| | A: merge after run | B: readers group shards | C: directory + manifest | D: shared log |
|---|---|---|---|---|
| Reader changes | none | Python API, dataframes, eval-set, viewer TS (3 hosts), Scout | recorder layer, listing, viewer TS, Scout | as C plus a third reader |
| Writer changes | shard marker | shard marker | shard marker, directory layout | new writer |
| Post-run step | merge (owner needed) | none | finalise (owner needed) | finalise |
| Whole-task view during run | no | yes (partial) | yes if readers compute without manifest | yes |
| Old readers open the result | yes | shards only | no | no |
| Self-contained-log constraint | kept | relaxed | relaxed (per directory) | relaxed |
| Storage | 2× until shards deleted | 1× | 1× | 1× |
| Where results live | merged header | recomputed per read, or cache | manifest | header |
| Complexity | S–M | L | L | L |
| Main risk | partial merge presented as whole | partial-group semantics across many consumers | format adoption, S3 directory semantics | S3 object counts, concurrency |

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
3. **Who owns orchestration?** If sharding is only ever driven by the external
   runner, the shard marker and merge/finalise belong in the selection
   protocol and the runner. If arbitrary users sharding with `--sample-id`
   from a shell script are in scope, a CLI merge (A) is the only option that
   serves them without a runner.
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
readers and go through `filesystem()`/`local_path()`; a merge (A) or group
read (B) adds no new kind of input beyond reading more of them. C's manifest
is a new pointer type and must be constrained to entries inside its own
directory to avoid a log that reads arbitrary paths. Sample JSON from shards
is parsed by the same Pydantic models as today.

## Testing (at options level)

- A: unit tests over mock-model shards like the spike (merge whole group,
  refuse partial group, recomputed metrics equal an unsharded run's,
  `evals_df` one row, eval-set accepts the merged log). All local, no
  network, in `tests/log/` and `tests/test_eval_set.py`.
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
- `EvalDataset.samples` records the full dataset size while `sample_ids` is
  the slice; the pair is the only present hint that a log is partial and its
  documentation could say so.
