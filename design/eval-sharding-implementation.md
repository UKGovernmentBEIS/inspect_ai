# Eval sharding, Step 1: API and implementation plan

Status: proposed, 2026-09-24; revised the same day after Ransom removed
viewer changes from Step 1 and asked for simple shard deletion. Issue:
https://github.com/meridianlabs-ai/inspect_ai/issues/529 (part of #509).
Author: agent (Claude), reviewed by Codex; see the PR. Verified against
`43ebaebc38`; updated on 2026-09-29 (`18acb828a2`) for what has landed
since: the layout helpers (UKGovernmentBEIS/inspect_ai#5541), ctl log-dir
mode steps 1–2 with `list_dir` and the CRC check (#5542) and the viewer's
hiding of merged shards (#5591). Revised on 2026-09-29 so that the merged
header carries no per-sample data beyond the `dataset.sample_ids` list
every log header has (decision: Ransom, 2026-09-29): the ledger holds a
count and a selection digest per shard instead of each shard's exact keys,
and the recorded selection lives in the ordinary header fields. Revised
on 2026-10-05 for the shared walk as PR 3 (UKGovernmentBEIS/inspect_ai#5622)
implements it: `is_shard_path` is true only for the files the walk lists,
so a log nested deeper in a companion is an ordinary log, and ctl log-dir
mode lists it as one, matching eval-set (decision: Ransom, 2026-10-05).
Revised on 2026-10-08 for the sign-off review: deletion removes each
shard's current attempt last, the merge restarts on every torn-read error,
`eval_retry` refuses every eval-set merged log (stated), a `-recovered`
output argument is refused, the CLI's `--json` has one object per
companion, and a companion with no header to match is refused.

This is the follow-on document that [`eval-sharding.md`](eval-sharding.md)
("the parent design") names: the public surface, the shape of the stored
provenance field, the merge algorithm in enough detail to build, the PR
sequence for Step 1 and a test plan per PR. It does not reopen the parent's
decisions; where it had to choose something the parent left open, the choice
and its reason are stated in place. The companion design
[`ctl/log-dir-mode.md`](ctl/log-dir-mode.md) ("ctl log-dir mode") reads the
same layout, and "Code shared with ctl log-dir mode" below fixes which pieces
the two implementations share.

## Why

The parent design fixes the direction: shards are ordinary `.eval` files in
`<dir>/<name>.shards/<k>/`, a trusted incremental merge writes the canonical
log `<dir>/<name>.eval`, and `eval_set()` runs the merge at startup. It
leaves the API signatures, the ledger's exact shape and the order of work to
this document, and two implementation efforts have already started against
it: the layout helpers (meridianlabs-ai/inspect_ai#530, since landed as
UKGovernmentBEIS/inspect_ai#5541) and ctl log-dir mode
(meridianlabs-ai/inspect_ai#528, steps 1–2 since landed as
UKGovernmentBEIS/inspect_ai#5542; its later steps read the merged log's
provenance field). Without a fixed surface and sequence, those efforts and
the merge would each invent their own versions of the shared pieces (the
directory walk, the attempt order inside `<k>/`, the ledger fields) and
diverge.

## Goals and non-goals

Goals:

- A public Python API and CLI command for the merge, with every parameter
  the parent requires: the intended selection as an id list or a count, the
  option to write an incomplete (`started` or `error`) merged log, and the
  option to delete shards after a verified complete merge.
- The typed `EvalSpec` field that carries provenance and the ledger, with its
  JSON schema and `ts-mono` impact.
- A merge algorithm specified to the level of data flow, validation,
  status, header fields, publication, cancellation and concurrency.
- The Step 1 PR sequence with dependencies, the files each PR touches and a
  test plan for each.
- One owner for each piece of code that ctl log-dir mode also needs.

Non-goals:

- Anything the parent design places in Step 2 or Step 3 (live whole-task
  metrics, viewer collapsing of shards, per-shard metrics in the viewer).
- A launcher. Inspect ships none in Step 1 (parent, "Phased plan").
- A listing exclusion for shards beyond the viewer's. The viewer already
  hides shards that a `success` merged log covers
  (UKGovernmentBEIS/inspect_ai#5591; parent, "Listing"); other enumerators
  still list them.
- S3 server-side composition with `UploadPartCopy`; the parent orders it
  after raw member copy, "when measured merges of large logs justify it".
- Chunked-shape samples (see "Validation" and "Not this design").
- Distributed merge ownership and a remote lock protocol (parent,
  "Overlapping merges").
- Viewer changes of any kind (decision: Ransom, 2026-09-24: "for stage 1,
  we are not planning any viewer changes"). The shard hiding in #5591
  landed separately and needs nothing from this plan. `/log-delete` keeps
  deleting the one file requested; see "Deleting shards" for the limitation this
  leaves.
- Deletion that is safe against concurrent deleters or resumable after a
  crash (decision: Ransom, 2026-09-24, "keep deletion simple"). Earlier
  revisions of this document specified a deletion marker, recorded object
  identities and a `detached` state for this; each review round found new
  holes in that machinery, so it was removed rather than patched.

## Current behaviour

Only what the plan depends on. Verified by reading the code at `43ebaebc38`
and, where noted, by running it.

**Layout helpers** (landed in UKGovernmentBEIS/inspect_ai#5541, from
#530). `src/inspect_ai/_util/log_layout.py` is the single owner of the
suffix rule and the log name, as pure path functions:

- `log_basename(log)`: the basename with `.eval`, then `-recovered`,
  stripped.
- `eval_checkpoints_dir(log, override_root)`: `<log-base>.checkpoints`.
  The checkpoint package re-exports it from
  `util/_checkpoint/_layout/eval_checkpoints_dir.py` and imports
  `log_basename` in `staging_dir.py`.
- `eval_shards_dir(log)`: `<dir>/<name>.eval` or
  `<dir>/<name>-recovered.eval` to `<dir>/<name>.shards`.
- `eval_log_for_shards_dir(shards_dir)`: the inverse, to
  `<dir>/<name>.eval` (a trailing `/` or `\` is allowed). It raises
  `ValueError` when the last component does not end in `.shards` or is
  exactly `.shards`. A `-recovered` log and its original share one
  companion, which maps back to the original.
- `merged_log_candidates_for_shard(shard)`: for
  `<dir>/<name>.shards/<k>/<file>`, `[<name>.eval, <name>-recovered.eval]`;
  `None` off the layout. Added later by UKGovernmentBEIS/inspect_ai#5591
  for the viewer's shard hiding (`log/_shard_listing.py`).
- `eval_log_name(*, task, task_id, created, model)`: the log file name
  without directory or suffix, `{created}_` +
  `INSPECT_EVAL_LOG_FILE_PATTERN` (default `{task}_{id}`) with `{model}`
  substituted. `FileRecorder._log_file_key`
  (`src/inspect_ai/log/_recorders/file.py:156`) now calls it, so a launcher
  can mint `<name>` without an `EvalSpec`.

The derivations replace only the last path component, so relative names,
`file://` and `s3://bucket/` prefixes and Windows separators keep their
form.

**The header model.** `EvalSpec` (`src/inspect_ai/log/_log.py:1013`) sets
no `extra` policy (`model_config` at `:1120` only sets
`protected_namespaces`), so pydantic ignores unknown fields on read. New
logs build their `EvalSpec` field by field in `TaskLogger.__init__`
(`src/inspect_ai/_eval/task/log.py:281`), so a field set on a prior log is
never copied onto a retry's log. The name `ProvenanceData` is already taken
by the log-edit model (`src/inspect_ai/log/_edit.py:13`). The schema flows
`EvalLog` → `src/inspect_ai/_view/inspect-openapi.json` →
`packages/inspect-common/src/types/generated.ts` in `ts-mono`
(`src/inspect_ai/_view/schema.py`; `design/type-generation-pipeline.md`),
and `inspect log schema` prints the OpenAPI file
(`src/inspect_ai/_cli/log.py:265`). `evals_df` columns are an explicit list
(`src/inspect_ai/analysis/_dataframe/evals/columns.py`), so a new field adds
no column by itself.

**A log's recorded selection.** `TaskLogger.__init__` sets
`eval.dataset.sample_ids` to the ids of `slice_dataset(dataset, limit,
sample_id, dynamic=...)` (`src/inspect_ai/_eval/task/log.py:242`), so a
worker started with `--sample-id` or a `limit` range records exactly the
ids it selected, in dataset order; `eval.config.sample_id` keeps the
`--sample-id` value as given. The header of a running attempt comes from
`_journal/start.json`, a `LogStart` holding the same `EvalSpec`
(`src/inspect_ai/log/_recorders/eval.py:98,1045`), so the selection is
known from a shard's first flush. The field is optional (`| None`,
`_log.py:966`), and older logs may lack it. A task driven by a
`SampleSource` (`Task.sample_source`, `src/inspect_ai/_eval/task/run.py:751`)
records only its seed there: samples the source adds while the task runs
are appended to a local list (`run.py:1684`) and reported through
`record_samples_added`, never written back into `dataset.sample_ids`.

**Sample member names.** A monolith sample is the member
`samples/{id}_epoch_{epoch}.json` (`_sample_filename`,
`src/inspect_ai/log/_recorders/eval.py:2010`); readers treat `1` and `"1"`
as the same sample for that reason (`log/_recorders/recorder.py:91`).
Because the epoch is an integer, splitting the name after `samples/` and
before `.json` at its last `_epoch_` recovers `(str(id), epoch)`, including
for an id containing `/` or `_epoch_`.

**Reading logs.** `AsyncZipReader` (`src/inspect_ai/_util/async_zip.py:343`)
reads the central directory with a suffix read, records the object's ETag
(`etag`, `:393`), and streams a member decompressed (`open_member`) or raw
(`open_member_raw`). `ZipEntry` (`src/inspect_ai/_util/zip_common.py`)
holds name, method, sizes, local-header offset and, since #5542, `crc32`
(`int | None`, from the central directory). `AsyncZipReader(...,
verify_crc=True)` checks every decompressed member read against it and
raises `ZipCrcError` (a `ValueError`) on a mismatch; ctl log-dir mode
re-reads up to twice on one. A running log has no
`header.json`; `_read_header_async` synthesises the header from
`_journal/start.json` and `_read_all_summaries_async` reads journal
summaries, deduped by `(id, epoch)` with the last row winning
(`src/inspect_ai/log/_recorders/eval.py:1858,1935,1920`).
`_s3_download_with_etag` (`eval.py:793`) returns the ETag of exactly the
bytes it downloads but reads the whole body into memory first;
`_s3_download_file_async` (`src/inspect_ai/_util/asyncfiles.py:344`)
downloads in concurrent ranged GETs, each pinned with `IfMatch` to the ETag
of its own `head_object`.

**Chunked samples.** A sample may be stored as a monolith member
`samples/{id}_epoch_{n}.json` or in the chunked shape under a
`samples/{id}_epoch_{n}/` prefix (`classify_sample_shape`,
`src/inspect_ai/log/_recorders/chunked/format.py:121`). On `main` only the
hidden `inspect log convert-chunked` command writes the chunked shape
(`src/inspect_ai/_cli/log.py:223-243`); the recorder writes monoliths.

**Writing and publishing.** The recorder builds a zip in a local temp file
and `ZipLogFile.flush` publishes it: `atomic_write` locally (temp file plus
`os.replace`, `src/inspect_ai/_util/atomic_write.py:99`), otherwise
`AsyncFilesystem.write_file_streaming`
(`src/inspect_ai/_util/asyncfiles.py:695`), which on asyncio uses
`_s3_upload_fileobj_async` (a single `put_object` below the multipart
threshold, else `_s3_multipart_upload_async`, `:314,240`) and on Trio runs
boto3's managed transfer in a thread (`s3_write_file_streaming`,
`_s3_upload_fileobj_sync`, `:1271,391`). Neither route sends a condition.
The only conditional write is `_s3_put_object` (`eval.py:742`): a
`head_object` ETag pre-check, then `put_object` with `IfMatch`, from a whole
body in memory; conflicts raise `WriteConflictError`
(`src/inspect_ai/_util/error.py:77`, exported from `inspect_ai.log`).
Both shared S3 clients are built with SDK retries
(`retries={"max_attempts": 10, "mode": "adaptive"}`, `asyncfiles.py:1057`,
`:1141`), so any single call may be dispatched more than once; the
round-1 reviewer's probe showed a conditional `put_object` sent twice when
the transport returned 500 then 200.
Verified by running against the installed packages (boto3 1.43.75,
s3transfer 0.19.2, moto 5.2.2):

- botocore's `CompleteMultipartUpload` and `PutObject` accept `IfMatch` and
  `IfNoneMatch`; `UploadPartCopy` accepts `CopySourceIfMatch`.
- s3transfer cannot send either condition: neither is in
  `TransferManager.ALLOWED_UPLOAD_ARGS` nor in
  `UploadSubmissionTask.COMPLETE_MULTIPART_ARGS`. The Trio route therefore
  cannot carry a condition through boto3's managed transfer.
- moto honours `IfNoneMatch: *` on both `put_object` and
  `complete_multipart_upload` (`PreconditionFailed` when the key exists) and
  `IfMatch` on `put_object`, but ignores `IfMatch` on
  `complete_multipart_upload` (a wrong ETag completes). Tests of a
  conditional multipart publish over `mock_s3` see the `IfMatch` refusal only
  through a `head_object` pre-check.

A local marker file is created atomically with
`os.open(..., O_CREAT | O_EXCL | O_WRONLY)` in `_try_create_marker`
(`src/inspect_ai/_lfs/_cache.py:183`).

**Merge building blocks.** `copy_live_members`
(`src/inspect_ai/_util/zipfile.py:212`) copies zip members by decompressing
and recompressing, chunked. `recompute_metrics`
(`src/inspect_ai/log/_metric.py:9`) needs an `EvalLog` with `samples`
loaded; its parts do not: `metrics_from_log_header`,
`reducers_from_log_header`, `resolve_scorers_info`
(`src/inspect_ai/_eval/score.py:562,594,648`; the last imports the header's
`task_file` when a metric is not registered) and `eval_results`
(`src/inspect_ai/_eval/task/results.py:90`), which takes one
`dict[str, SampleScore]` per sample. `seed_from_prior_log`
(`eval.py:1407`) shows the pattern for copying a remote log into a local
temp zip before building on it. `task_file` is recorded relative to the
working directory (`src/inspect_ai/_eval/loader.py:115`) and is part of
`task_identifier`.

**Eval sets.** `try_eval` lists the directory with `list_all_eval_logs`
(`src/inspect_ai/_eval/evalset.py:1043`), which reads every listed header
before pairing (`:1758-1770`); the retry-cleanup sweep lists through the
same helper (`cleanup_older_eval_logs`, `:1930-1936`, called at `:1191`).
`inspect_flow` also calls `list_all_eval_logs` (`_runner/run.py:263`,
`_runner/logs.py:178`, `_store/deltalake.py:159`). Completeness compares
counts (`log_samples_complete`, `:1837`, with `samples_selected` from
`src/inspect_ai/_eval/eval_set_manifest.py:187`); a `started` log is handed
to `_recover_crashed_log` (`:1512`) from `as_previous_tasks` (`:1464`) and,
for a resolving disposition, from `list_latest_eval_logs` (`:1773`);
`latest_completed_task_eval_logs` (`:1939`) orders a `task_id` group by
mtime and removes every non-`started` log but the newest with a bare
`fs.rm` (`started` logs are kept on purpose, `:1971`). Selection (worker) mode returns before any of this: "everything
below this point is eval-set orchestration ... deliberately skipped"
(`:832-837`), so a worker never scans the directory.

**Viewer delete.** `/log-delete/{log}` (`fastapi_server.py:238`) checks
the access policy for the requested path and calls `delete_log`
(`src/inspect_ai/_view/common.py:500`), a bare `fs.rm` of that one file.
Step 1 leaves it unchanged.

**Viewer shard hiding** (UKGovernmentBEIS/inspect_ai#5591). The view
server's `/logs` and `/log-files` listings (`hide_merged_shards`,
`src/inspect_ai/_view/common.py:174`) and `write_log_listing`
(`listing.json`, bundles; `src/inspect_ai/log/_file.py:1309`) drop a log
under `<name>.shards/<k>/` when its merged log is in the same listing, has
status `success`, and is strictly newer than the shard by mtime
(`filter_merged_shards`, `src/inspect_ai/log/_shard_listing.py:43`). A
shard tied with the merged log or newer than it, and every shard of a
merged log that is `started`, `error`, `cancelled` or unreadable, stays
visible.
`inspect view --show-shards` turns the filter off. It keys on the layout
and the merged log's status only; it does not read `eval.shards`.

**Other outputs beside a worker's log.** A worker's default scan directory
is under its own log directory, `<k>/scans/scan_id=...`, while an eval
set over the parent looks under `<dir>/scans/` (`_scan_dir`,
`src/inspect_ai/_eval/task/scan.py:829`). Checkpoints live beside each log
as `<log>.checkpoints/` (`eval_checkpoints_dir`), deleted on success by
default and kept with `retention="retain"`
(`src/inspect_ai/util/_checkpoint/config.py:172,233`).

**Landed since the first revision.** #528's steps 1–2
(UKGovernmentBEIS/inspect_ai#5542): `inspect ctl --log-dir`,
`AsyncFilesystem.list_dir`, the `ZipEntry` CRC and the opt-in CRC check
("Code shared with ctl log-dir mode"). Its steps 4 and 6 (shard
aggregation, ledger totals) wait for PRs 3 and 2 below.

**Work in flight that overlaps this plan.**
UKGovernmentBEIS/inspect_ai#5396 (open: retry cleanup also removes older
`started` logs and their buffers; touches `latest_completed_task_eval_logs`)
and UKGovernmentBEIS/inspect_ai#5391 (design: S3 flushes by server-side
composition).

## Design

### Public surface

#### Python API

In `inspect_ai.log`, beside `recover_eval_log`, following its sync-plus-async
pattern:

```python
def merge_eval_log_shards(
    log: str,
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
    delete_shards: bool = False,
) -> ShardMergeResult: ...


async def merge_eval_log_shards_async(...same parameters...) -> ShardMergeResult: ...


@dataclass(frozen=True)
class ShardMergeResult:
    log: EvalLog
    """Header of the merged log (samples not loaded); `log.location` is its path."""

    written: bool
    """False when nothing had changed since the last merge and nothing was written."""

    shards_deleted: bool
    """True when `delete_shards` removed the companion directory."""


class ShardSetError(Exception):
    """The companion directory's contents cannot be merged (details in the message)."""


class ShardSetIncomplete(Exception):
    """The shard set is incomplete and `allow_incomplete` was not set."""

    status: Literal["started", "error"]
    missing: list[str | int] | None  # ids of the intended selection no shard holds; None for a count
    running: list[str]               # shard names whose current attempt is `started`
    failed: list[str]                # shard names whose current attempt is `error` or `cancelled`
```

Parameters:

- `log`: the merged log `<dir>/<name>.eval` or its companion
  `<dir>/<name>.shards` (trailing slash allowed); each is derived from the
  other with `eval_shards_dir` / `eval_log_for_shards_dir` ("Layout
  helpers"). Plain paths, `file://` and `s3://` (and other
  fsspec URLs, without the overlap guard; see "Overlap guards"). A `.eval`
  argument is the output path; a companion argument writes `<name>.eval`.
  A `.eval` argument named `<name>-recovered.eval` raises `ValueError`
  before anything is read, naming `<name>.eval` and the companion as the
  arguments to pass: `eval_shards_dir` maps it to the same
  `<name>.shards/` as `<name>.eval`, while eval-set discovery and
  `eval_log_for_shards_dir` always write `<name>.eval`, so merging into it
  would put a second merged log, with its own ledger and the same
  `task_id`, beside the one the next startup merge writes. Refusing is
  chosen over silently writing `<name>.eval` instead, because the caller
  named a different output file.
- `sample_ids` / `sample_count`: the intended selection, mutually exclusive
  (`ValueError` if both). Ids are compared as `str(id)`, the readers' sample
  key. When neither is given, the selection recorded in the merged log's
  header is used ("Recorded selection", under the field below); when that
  is absent too, the set is complete only if the
  distinct ids held equal the shards' `dataset.samples` (a whole-dataset
  run, parent "Completeness"). A given selection replaces the recorded one
  while the companion exists; once it is gone, a selection that differs
  from the recorded one raises `ShardSetError` (see step 10).
- `allow_incomplete`: without it an incomplete outcome raises
  `ShardSetIncomplete` and writes nothing, on every call, including one
  that finds nothing new since an earlier incomplete merge; with it the
  merge writes the `started` or `error` log (parent "Completeness",
  "Errored shards"). This is the issue's "write `started`" option; it is
  named for both statuses because an errored set writes `error`.
- `delete_shards`: when the merged log is `success`, whether written by
  this call or already current, verify it and delete the companion's
  objects (see "Deleting shards"). Precondition, stated in the docstring:
  every worker has exited and nothing else operates on this log or its
  companion while the call runs (no other merge, no other deletion); the
  merge cannot tell a finished shard from a paused one, and nothing is
  guaranteed when the precondition is broken. If deletion is interrupted,
  the call raises `ShardSetError` listing what is left; re-running it, or
  deleting `<name>.shards/` by hand, finishes the job. Combined with
  `allow_incomplete=True` it
  is a `ValueError` at call time, since a deletion that happens only
  sometimes is the wrong contract for the one irreversible option.

`ShardSetIncomplete.missing` lists the ids with at least one selected epoch
that no shard holds (`None` for a count selection).

Raises: `ShardSetError`, `ShardSetIncomplete`, `WriteConflictError` (another
merge holds the lock or published first; re-run later),
`FileNotFoundError` (neither the merged log nor the companion exists), and
storage errors as they occur.

Trust: the merge follows `resolve_scorers_info`'s `task_file` fallback as
`recompute_metrics` does, logs a warning naming the imported file when it
does; the CLI also prints a notice (below). Parent "Trust": the merge runs
only as a trusted step; no reader path calls it.

#### CLI

`inspect log merge-shards`, in `src/inspect_ai/_cli/log.py` beside
`recover`:

```
inspect log merge-shards LOG [LOG ...]
    [--sample-id IDS | --sample-count N]
    [--allow-incomplete] [--delete-shards] [--json]
```

- Each `LOG` is a merged log path, a companion directory, or a log
  directory. A log directory merges every companion found in it, found as
  steps 1–2 of the `eval_set()` startup merge find them ("Eval-set
  integration"): one `list_eval_logs` of the directory, each companion
  marked by its `is_shard_path` files. Steps 3–4 (matching a task and
  taking its selection) do not apply, since the CLI has no task: each
  companion is merged with no selection argument, so its recorded
  selection is used, or none on a first merge. The selection options are
  refused with a usage error for a directory, because one selection
  cannot apply to several tasks.
- `--sample-id` takes comma-separated ids (`parse_sample_id`,
  `src/inspect_ai/_util/samples.py:17`), concrete ids only; `--sample-count`
  an integer.
- Human output: one line per merged log with its status, the number of new
  samples and shards, and, when incomplete, the missing count and the
  running and failed shard names. When the `task_file` fallback imported
  code, a notice on stderr names the file (parent decision, 2026-09-21: a
  visible notice, no opt-in).
- `--json`: a JSON array with one object per merged log, that is one per
  companion: a merged-log or companion `LOG` gives one object, and a
  directory `LOG` one per companion found in it (none when it holds no
  companion). Each object has `source` (the `LOG` argument it came from),
  `log` (the merged log path), `status`, `written`, `shards`, `samples`,
  `missing` (ids or null), `running`, `failed`, `shards_deleted`, and
  `error` (message) for a failed item, with the fields it could not
  compute null. A `LOG` that fails before any companion is known (a
  directory that cannot be listed, a missing path, a `-recovered`
  argument) gives one object with `log` null and `error` set.
- Exit 0 when every item merged or had nothing new; 1 when any item raised
  (an incomplete set without `--allow-incomplete` raises). A directory run
  continues past a failed companion and reports each.

The command imports the merge lazily inside the function body, as
`recover` does, so `tests/cli/test_startup_imports.py` is unaffected.

#### The `EvalSpec.shards` field

Named `shards` rather than "provenance" because `ProvenanceData` already
means log-edit provenance. In `src/inspect_ai/log/_log.py`, exported from
`inspect_ai.log`:

```python
class EvalShardEntry(BaseModel):
    """Ledger entry for one shard, as of the merge that last read it."""

    shard: str
    """Name of the shard's directory (`<k>`) in the companion."""

    log: str
    """File name of the shard's current attempt (the newest `.eval` in `<k>/`)."""

    eval_set_id: str | None = Field(default=None)
    """`eval_set_id` of the current attempt."""

    status: EvalStatus
    """Status of the current attempt when it was read."""

    error: EvalError | None = Field(default=None)
    """Error of the current attempt when its status is `error` or `cancelled`."""

    samples: int
    """Number of `(id, epoch)` records the current attempt held when read (all merged)."""

    selected: int
    """Number of distinct ids in the current attempt's selection (its `eval.dataset.sample_ids`)."""

    selection_digest: str
    """SHA-256 (hex) of the current attempt's selection."""

    started_at: UtcDatetimeStr | Literal[""] = Field(default_factory=str)
    """`stats.started_at` of the current attempt."""

    completed_at: UtcDatetimeStr | Literal[""] = Field(default_factory=str)
    """`stats.completed_at` of the current attempt (empty while it runs)."""

    model_usage: dict[str, ModelUsage] = Field(default_factory=dict)
    """`stats.model_usage` of the current attempt."""

    role_usage: dict[str, ModelUsage] = Field(default_factory=dict)
    """`stats.role_usage` of the current attempt."""

    size: int
    """Size in bytes of the current attempt when it was read."""

    etag: str | None = Field(default=None)
    """ETag of the bytes read (object stores that report one)."""

    mtime: float | None = Field(default=None)
    """Modification time of the current attempt when it was read."""


class EvalShards(BaseModel):
    """Provenance of a merged log: its shards and the ledger of the last merge."""

    selection: Literal["ids", "count", "none"]
    """Form of the intended selection the last merge had; the ids are `eval.dataset.sample_ids`."""

    sample_count: int | None = Field(default=None)
    """Intended selection as a count, when `selection` is `"count"`."""

    ledger: list[EvalShardEntry]
    """One entry per shard with a current attempt, in shard order."""
```

Nothing else is recorded (decision: Ransom, 2026-09-29): no companion
location (readers derive it from the name, and a recorded one goes stale
when the log moves), no template name (the template shard is the first
in shard order, so the last merge's template is `ledger[0].shard`; the
ledger is in shard order and a companion with vanished entries is refused,
"Validation"), no merge time, no metric source (the merge's warning and
the CLI notice name an imported `task_file`), and per shard no attempt
count (a reader that shows it counts the `.eval` files in `<k>/`) and no
`eval_id` or `task_id` (`log` names the attempt).

`EvalSpec` gains `shards: EvalShards | None = Field(default=None)` with the
docstring "Shards merged into this log (merged logs only)." Absent on every
unsharded log and on shards; its presence is how `eval_set()` and ctl
log-dir mode recognise a merged log.

Choices the parent left open:

- **The ledger holds everything a later pass needs from a shard it does not
  reopen, and nothing per sample.** A pass reopens only changed and new
  shards, so every per-shard input to the merged header must be in the
  ledger: the full `EvalError` (the merged log's `error` is the first
  failing shard's, and `EvalError` requires `traceback` and
  `traceback_ansi`, `src/inspect_ai/_util/error.py:12`), the statistics
  (`stats` is recomputed from the entries, so replacing one shard's attempt
  replaces exactly its contribution), `eval_set_id`, and the
  values that let the merge attribute merged records to shards without
  listing them: `samples` (the parent's per-shard sample count) and
  `selection_digest`. `selected`, the size of the shard's selection, is
  not needed by the merge; it lets a reader tell a shard that holds its
  whole selection (`status == "success"` and `samples == selected × epochs`)
  from a drained one without opening it (ctl log-dir mode's cold start).
  The records themselves are the merged log's own
  sample members, which step 3 reads from its central directory; "The
  sample set" gives the attribution rule and the checks that keep it
  sound. With this, an incremental pass and a fresh merge of the same
  companion compute the same header.
- **The digest.** `selection_digest` is the SHA-256 hex digest of
  `json.dumps(sorted({str(i) for i in ids}), ensure_ascii=False,
  separators=(",", ":")).encode()`, where `ids` is the attempt's
  `eval.dataset.sample_ids`: 64 characters whatever the selection's size,
  independent of dataset order and of `1` versus `"1"`, as the readers'
  keys are. It detects a shard whose selection changed between attempts
  ("Validation"); it is never used to locate anything.
- **Size.** The ledger is a fixed set of fields per shard (the usage
  dictionaries grow with the models used and a failed shard's error with
  its traceback, not with samples), so a merged header is an ordinary
  header plus an amount per shard that does not depend on its samples. Its only
  per-sample content is the list an ordinary header has,
  `dataset.sample_ids`; `config.sample_id` is left unset. At 10,000 samples and 5 epochs the
  exact-key ledger of the previous revision added about 50,000 objects
  (about 2 MB for short ids) to `header.json`, which every `eval_set()` listing,
  `read_eval_log_headers` call and viewer log list would parse.
- **Recorded selection: the ids in `dataset.sample_ids`, the form in a
  scalar.** The merge writes the selection it merged against as:

  | Selection | `eval.shards.selection` | `eval.shards.sample_count` | `eval.dataset.sample_ids` |
  |---|---|---|---|
  | ids | `"ids"` | absent | the ids, as given |
  | count | `"count"` | the count | the distinct held ids, sorted by `str(id)` |
  | neither | `"none"` | absent | the distinct held ids, sorted by `str(id)` |

  `eval.config.sample_id` and `eval.config.limit` are always absent on a
  merged log, so the one per-sample list is `dataset.sample_ids`. A later
  pass reads the recorded selection back from `selection`: the
  `dataset.sample_ids` list for `"ids"`, `sample_count` for `"count"`,
  none for `"none"`. Selections are compared as sets of `str(id)`. The
  marker is a scalar in `eval.shards` rather than a second use of an
  ordinary field: `dataset.sample_ids` holds ids in every form, so it cannot
  say which form it is, and `config.limit` means the first N of the
  dataset, which a merge cannot claim.

  **`eval_retry` of a merged log.** `eval_retry_async` re-launches a log's
  task with the log's `config.sample_id` as its subset
  (`src/inspect_ai/_eval/eval.py:1795`), which a merged log leaves unset.
  Decision (Ransom, 2026-09-29): `eval_retry` of a merged log is supported only
  for `selection == "none"`, whose selection is the whole dataset, so the
  ordinary retry (the whole dataset, reusing prior records by `(id, epoch)`
  under the existing stability checks, `src/inspect_ai/_eval/task/run.py:3625`)
  runs exactly the right samples. For `"ids"` and `"count"` it raises
  `ValueError` before any sample runs, naming the log and the ways to
  finish the run: `eval_set()` over the directory with the same selection
  (which seeds its retry from the merged log, "No recovery of merged
  logs"), or re-running the incomplete shards and merging again. Why not
  pass the recorded ids as the retry's subset: the retry selects with
  patterns, not exact keys. `sample_id_filter` normalises digit strings to
  integers and applies `fnmatch` (`src/inspect_ai/_eval/task/util.py:56`,
  `src/inspect_ai/dataset/_util.py:25`), so `"01"` also selects `"1"`,
  `"-1"` does not select the integer `-1`, wildcards and, on Windows, case
  and separators change the match; and a shard made with `limit` and
  `sample_shuffle` from a dataset without ids records ids assigned after
  the shuffle (`src/inspect_ai/_eval/run.py:206`), which name different
  samples in an unshuffled retry. A count names no ids at all. An exact
  selection path for retries is listed under "Not this design". The check
  is one branch at the top of the per-log loop in `eval_retry_async`, keyed
  on `eval.shards`. Version boundary: an Inspect version without this field
  drops `eval.shards` on read and so retries an id- or count-selected
  merged log over the whole dataset, which may run samples outside the
  selection; Ransom accepts that boundary (2026-09-29: "Fine with older
  Inspect version not knowing about shards"). Files: `_eval/eval.py` (PR 5).

  **This refuses every merged log `eval_set()` writes.** Its startup merge
  always passes the eval set's selection as ids (`selected_sample_ids`,
  "Eval-set integration" step 4), even when that selection is the whole
  dataset, so the log records `"ids"`. `eval_retry` therefore refuses an
  eval-set merged log, whole-dataset runs included, and the message points
  to `eval_set()` over the same directory, which is how an eval set's run
  is finished anyway. The alternative, passing no selection when the eval
  set covers the whole dataset so that the log records `"none"`, was not
  taken: with no selection the merge uses the recorded one, so an eval set
  could no longer replace a narrower selection recorded by an earlier CLI
  merge; and an id selection that covers the whole dataset is already
  refused (Ransom, 2026-09-29). The sharding docs (PR 5) and the eval-sets
  note (PR 6) state the restriction.
- **`size`, `etag`, `mtime`** are what `FileInfo` carries
  (`src/inspect_ai/_util/file.py:195`); change detection compares ETags when
  both sides have one and `(size, mtime)` otherwise.
- **Unknown-field behaviour**: nothing new. Old Inspect versions drop the
  field on read (no `extra` policy), and readers that do not know it treat
  a merged log as an ordinary log, as the parent requires. An old version
  that *rewrites* a merged log (for example a viewer edit) drops the field;
  the result is an ordinary log, which the merge then refuses to overwrite
  (step 3). That is the support boundary for cross-version editing.

Schema impact: two new component schemas (`EvalShards`,
`EvalShardEntry`) and one optional property on
`EvalSpec` in `inspect-openapi.json`; the same in `generated.ts`.
`EvalStatus`, `EvalError` and `ModelUsage` are reused. The viewer ignores
the field until Step 3 but the generated types change, so the PR lands with
a coordinated `ts-mono` PR per `.agents/skills/land-ts-mono/SKILL.md`.
`inspect_scout` consumes these types from `@tsmono/inspect-common` in
`ts-mono` (its own `scripts/export_openapi_schema.py` excludes
Inspect-originated types), so it adopts the change when its `ts-mono`
version moves and needs no code change.

### The merge

`src/inspect_ai/log/_shards/` (new package): `_api.py` (the public
functions), `_walk.py` (shared with ctl, "Code shared with ctl log-dir
mode"), `_plan.py` (pure functions: validation, sample set, status, header),
`_write.py` (building the merged zip), `_publish.py` (guards and
publication), `_delete.py` (companion deletion).

One pass, in order. Steps 1–9 run on every call; the merged log is
downloaded and rewritten only when step 10 says so.

1. **Derive the pair.** From `log`, derive `<name>.eval` (or the given
   `.eval` path) and `<name>.shards/` with `eval_shards_dir` /
   `eval_log_for_shards_dir`. Open one `AsyncFilesystem` scope for
   the whole pass; every read below shares it.
2. **Acquire the local guard** when the output is local ("Overlap guards").
   S3 has nothing to acquire; its guard is at publication.
3. **Read the merged log's header and central directory**, if it exists,
   through one `AsyncZipReader` (range reads; S3 costs the suffix read and
   the `header.json` member, whatever the log's size). Keep the reader's
   ETag `E0` for the conditional publish, or note that the log is absent
   (a later publish then uses `IfNoneMatch: *`). If the log exists and
   `eval.shards` is absent, raise `ShardSetError` ("`<name>.eval` is an
   ordinary log; refusing to overwrite it"): a merge never replaces a log
   it did not write. The central directory's `samples/` members give the
   merged log's records, `M`, as `(str(id), epoch)` pairs ("Sample member
   names"); a `samples/` member that does not parse as a monolith name
   raises `ShardSetError` (the merge writes only monoliths, so the log was
   rewritten outside it).
4. **List the shard set** with `list_shard_set` ("Code shared ...") into
   shards `<k>` with their attempt files in attempt order, stray files and
   ancillary entries. Any stray file the walk reports (a log directly in
   `<name>.shards/` or in a directory under it whose name starts with `.`,
   or a `.json` log in any `<k>/`) raises `ShardSetError`; the walk itself
   only reports them. Ancillary entries (scan results, checkpoint
   directories) do not affect merging; they block deletion ("Deleting
   shards"). A log nested inside an ancillary directory is an ordinary log,
   not a shard ("Code shared with ctl log-dir mode"), and the merge does
   not read it.
5. **Classify each shard.** For each `<k>`, the current attempt is the last
   file in attempt order. It is *unchanged* when the ledger has an entry
   for `<k>` with the same `log` name and equal ETag (or equal `size` and
   `mtime` where either side has no ETag); otherwise *changed* or *new*. A
   ledger entry whose `<k>` is missing from the listing, or holds no `.eval`
   file, is *vanished*. Vanished shards are refused in "Validation", with
   one exception for re-running an interrupted `delete_shards`. This
   classification applies only while the companion exists: when
   `<name>.shards/` is absent altogether (shards deleted after a verified
   merge), steps 5–7 are skipped and step 10's companion-gone branch
   returns the self-contained merged log.
6. **Read changed and new shards**, bounded (16 concurrent), each through
   one `AsyncZipReader`: the central directory, the header (synthesised from
   `_journal/start.json` for a running attempt), the summaries (journal
   summaries for a running attempt), with the opt-in CRC check
   (`verify_crc=True`) on every member read ("Consistent reads"). If the
   template shard ("Building the merged log") is unchanged but is not the
   last merge's template, `ledger[0].shard`, read its header too. The ledger records the
   reader's ETag
   (`AsyncZipReader.etag`), which may differ from the listing's when the
   object was replaced in between; the next pass then sees a changed ETag
   and re-reads. A key is *held* by an attempt when its summaries list it
   and its central directory has the sample member. A read attempt's
   *selection* `S_k` is its header's `eval.dataset.sample_ids`, as
   `str(id)`.
7. **Validate** ("Validation"). Refuse with `ShardSetError` on any failure.
8. **Plan** the sample set ("The sample set"), the status ("Status") and
   the header ("Building the merged log"), from the ledger entries of
   unchanged shards, the merged records `M` and the attempts read in step
   6. A call that read no shard plans from the ledger and `M` alone.
9. **Enforce the status.** An incomplete status without `allow_incomplete`
   raises `ShardSetIncomplete`, before any write, whether or not anything
   changed.
10. **Decide whether to write.** With the companion present: write when
    there is no merged log, or any shard is changed or new, or the
    effective selection differs from the recorded one; otherwise nothing is
    written (`written=False`). With the companion gone (shards deleted after
    a verified merge, parent "Provenance and ledger"): nothing is written;
    a supplied selection must equal the recorded one, else `ShardSetError`
    ("the shards of `<name>.eval` were deleted; its selection can no longer
    change"), and the status in steps 8–9 is the recorded one.
11. **Build and publish**, only when step 10 writes: copy the merged log to
    a local temp file (local: read in place under the lock; S3: bounded,
    ETag-pinned ranged download, "Overlap guards"), build the merged zip in
    a second temp file ("Building the merged log"), recomputing metrics as
    members stream through ("Metric recomputation"), and publish it: local
    `atomic_write`; S3 conditional upload with `IfMatch: E0`, or
    `IfNoneMatch: *` for a first merge; other backends
    `write_file_streaming`.
12. **Delete shards** when `delete_shards` is set and the merged log's
    status is `success` ("Deleting shards"). This runs whether or not step
    11 wrote.
13. **Release** the local guard and remove temp files, in `finally`.

#### Validation

Across the current attempts of all shards, the reopened ones and, through
the merged header, the unchanged ones:

- Equal `task_identifier(header, None)` (`evalset.py:2058`), computed with
  the running Inspect's `TASK_IDENTIFIER_VERSION`. An unchanged shard is
  represented by the merged header, which was built from a validated shard
  header and keeps every field the identifier reads. Because `task_file` is
  cwd-relative and part of the identifier, workers must be launched from
  the same working directory relative to the task file; the mismatch error
  says so when the identifiers differ only in `task_file`.
- Equal `eval.scorers`, `eval.metrics` and `eval.dataset.samples`. The
  identifier does not cover them (a changed scorer list or dataset size
  keeps the identifier, verified by the round-1 reviewer), and they decide
  the recomputed metrics and the whole-dataset completeness rule, so
  workers running different task code without a task-version change are
  refused rather than merged.
- Equal `config.epochs` and `config.epochs_reducer` (checked explicitly;
  not in the identifier).
- Equal `EvalLog.version` (log format version); a version newer than the
  running Inspect writes is refused.
- No chunked-shape sample: `classify_sample_shape(entry_names, id, epoch)`
  (`chunked/format.py:121`) returns `"monolith"` for every held key. Step 1
  copies monolith members only; refusing is explicit where silently copying
  one member of a multi-member sample would corrupt the merged log. The
  rule is per key, so an id containing `/` (whose monolith member is
  `samples/group/item_epoch_1.json`) is a monolith as usual.
- **No attempt regression.** A shard's current attempt must not sort
  before the attempt its ledger entry records (`attempt_sort_key`); that
  happens only when the recorded attempt was deleted from `<k>/` while an
  older one was kept, and merging the older attempt would replace current
  records with obsolete ones. Refused, naming both files. `delete_shards`
  never causes it, even when interrupted: it deletes each shard's current
  attempt only after every other object ("Deleting shards"), so the
  regression comes only from a deletion by hand.
- **No vanished shard.** While the companion exists, every ledger entry
  still has a current attempt in its `<k>/`. (A companion that is gone
  altogether is not checked; step 10 returns the merged log as it is.) A
  vanished shard means shard files were deleted after they
  were merged: by hand, or by a `delete_shards` that was interrupted
  ("Deleting shards"). Merging the remainder would overwrite the merged log
  with fewer records, so the merge refuses, naming the vanished shards and
  saying to finish deleting `<name>.shards/` (re-run with `delete_shards`,
  or delete the directory by hand) or to restore the files. The one
  exception: a call with `delete_shards=True` in which every shard still
  present is unchanged and none is new. Such a call writes nothing (the
  merged log already holds every recorded shard's records), verifies the
  merged log against its ledger, and deletes what remains; this is what
  makes re-running an interrupted `delete_shards` finish the job.
- **A recorded selection that covers what the shard holds.** Every read
  attempt has `eval.dataset.sample_ids` (not `None`), and every key it holds
  has its id in `S_k`. Otherwise refused, naming the shard: the merge
  attributes records to shards by selection ("The sample set"), and an
  attempt with no recorded selection, or holding samples outside it,
  cannot be attributed. This is how a shard of a `SampleSource` task is
  refused: its header lists only the seed ("A log's recorded selection"),
  so the first added sample it holds is outside `S_k`. Decision (this
  document): refuse. A launcher shards by `--sample-id` or `limit`, which
  presumes the samples are known before the workers start, and the
  fallback (re-reading the attempt the ledger's `log` names to recover its
  keys) does not work for the common change, a running attempt that grew
  in place, whose earlier contents no longer exist.
- **A shard's selection does not change across attempts.** For a changed
  shard, the digest of `S_k` equals its ledger `selection_digest`.
  Otherwise refused, naming both files: a new attempt in `<k>/` that
  selects different samples belongs in a new `<k>/`; to accept it where it
  is, delete `<name>.eval`, and the next merge rebuilds it from the current
  attempts (a first merge has no ledger to compare with). The message says
  both.
- **One owner per id, by selection.** The selections of the shards read in
  the pass are pairwise disjoint, and for each read shard the merged
  records with ids in `S_k` number exactly its ledger `samples` if it is
  changed, and zero if it is new (a new shard whose selection meets a
  merged record would take over another shard's records). A shard selects
  whole samples, so an id belongs to the one shard that selected it,
  whatever epochs it has run; this is stricter than the parent's disjoint
  `(id, epoch)` sets and makes ownership unambiguous.
- **The merged log matches its ledger.** While the companion exists, `M`
  numbers the sum of `samples` over the ledger entries. With the per-shard
  counts above, the records carried for unchanged shards therefore number
  exactly the sum of those shards' `samples`. A mismatch means the merged
  log's samples were changed outside the merge (a member removed, a log
  rebuilt by other tooling); refused with the advice to delete
  `<name>.eval` and re-merge from the shards. Checked on every pass,
  including one that writes nothing. Sample edits that keep the member
  (`edit_score`) do not change the count.
- When a selection is known (given or recorded), every held id is in it
  (ids outside it mean a stray or mislabelled shard). With a count, the
  number of distinct held ids must not exceed it.

The error message names the offending shard files and the differing field.

#### The sample set

Decision (this document): **the merged log holds, for each shard, exactly
the records its current attempt holds**: the exact `(id, epoch)` keys, never
ids expanded by epochs. A key moves from shard to merged log when first
seen; when shard `<k>`'s current attempt changes (it grew, or a newer
attempt appeared in `<k>/`), all of `<k>`'s records are taken from the
current attempt and any `<k>` record the new attempt lacks is dropped. A
shard whose files disappear is refused, not dropped ("Validation"). Within one
attempt a duplicated key resolves as the readers resolve it (last summary
row and last member of the name win).

**Attribution by id.** The ledger does not list a shard's keys; the merged
log's own members `M` are the record of what unchanged shards contributed.
A pass plans:

- *dropped*: the records of `M` whose id is in the selection `S_k` of some
  shard read in this pass (changed or new);
- *carried*: the rest of `M`, copied from the merged log as they are;
- *taken*: every key each read shard's current attempt holds.

The planned set is carried plus taken. A record of `M` is never assigned to
a particular unchanged shard; all that matters is that it belongs to one of
them, which the checks in "Validation" establish.

Why this is exact. After every write, `M` is the union of the keys held by
each ledger entry's recorded attempt, and those sets have disjoint ids
(induction over passes; a first merge reads every shard). In a later pass,
a changed shard's recorded keys lie in its recorded selection, which has
the same digest as `S_k` ("Validation"), and `M` has exactly `samples` records
with ids in `S_k`, as many as the recorded keys, so those records are
exactly its recorded keys. A new shard has none. So *dropped* is exactly
the read shards' previous records, *carried* is exactly the unchanged
shards' held keys, and the planned set is the union of every current
attempt's held keys, with disjoint ids since the read selections are
disjoint from each other and from the carried records. That is also what a
fresh merge of the same companion plans, so an incremental merge and a
fresh merge hold the same records (the parent's "idempotent and
deterministic"). The count checks are what make the step from counts to
key sets valid; an edit to `M` outside the merge breaks the induction, and
"The merged log matches its ledger" refuses it.

Where the two can decide differently: a fresh merge reads every selection
and so refuses any two overlapping ones; an incremental pass reads only the
changed and new shards' selections and refuses an overlap with an unchanged
shard when a record falls in the intersection: at once if the unchanged
shard holds it (a new or changed shard's selection meets a carried
record), otherwise when that unchanged shard is next read (its count check
then sees the other shard's record). Overlapping selections break the
launcher contract; both merges refuse them, and whenever both accept they
hold the same records. An incremental pass keeps accepting such an overlap
only while the overlapped shard is never read again (for example it
finished, drained, without holding the shared ids); the merged records are
still exact, each held once.

Reasons for the rule: the result is a function of the companion's current
attempts, so incremental and fresh merges agree as shown above; it is the rule ctl
log-dir mode already uses ("Older files in the same `<k>/` are superseded
... otherwise ignored"), so the two never disagree about which records a
shard contributes; and it loses nothing in the normal paths, because a
seeded retry of a shard (`design/retry-seeded-attempt-log.md`) holds its
prior samples from its first flush and a plain re-run re-runs them. The
parent's "newest wins" is this rule applied per shard.

Consequences, documented in the API docstring:

- Deleting one `<k>/` by hand makes later merges refuse until the rest of
  the companion is deleted or the files are restored. Deleting the whole
  companion leaves the merged log as it is (step 10).
- Edits to the merged log: header edits (`log_updates`, `tags`,
  `invalidated`) are carried to every later pass. Sample edits (for example
  `edit_score`) survive while the shard holding the sample is unchanged,
  and are replaced by the shard's copy when that shard changes. Editing a
  merged log whose shards are still growing is therefore not supported;
  finish the run first, or edit the shards.

#### Status

From the planned set (parent "Completeness" and "Errored shards"):

- `error` if any current attempt is `error` or `cancelled`; the merged
  log's `error` is the first such entry's `EvalError` in shard order, and
  every failing entry keeps its own.
- else `success` if every current attempt is `success` and the held keys
  (the planned set, "The sample set") equal the selection's ids times
  epochs `1..E` exactly (with ids: every
  `(id, epoch)` of every selected id; with a count: that many distinct ids,
  each with every epoch; with neither: the distinct held ids equal
  `dataset.samples`, each with every epoch). A drained `success` shard
  that holds fewer records leaves the set `started`.
- else `started`.

Shard order is numeric for all-digit names and lexicographic otherwise,
digits first.

#### Building the merged log

The *template shard* is the first shard in shard order. Its current
attempt's header supplies every field not listed below (task name, file,
args, model, plan, scorers, metrics, packages, revision, sandbox, metadata
and so on). When the template shard is the last merge's template
(`ledger[0].shard`) and its attempt is unchanged, these fields are carried from the merged header,
which was built from that same header; otherwise its header was read in
step 6. Fields that validation proves equal are the same whichever shard
supplies them; the rest (for example `packages` and `revision`) come from a
well-defined shard, so fresh and incremental merges agree.

| Field | Value |
|---|---|
| `version` | the shards' common log format version |
| `status`, `error` | from "Status" |
| `eval.eval_id`, `eval.run_id`, `eval.created` | minted at the first merge, then carried from the merged header (parent: one `eval_id` across passes) |
| `eval.task_id` | `{id}` parsed from `<name>` with `_try_parse_filename` (`src/inspect_ai/log/_file.py:1178`), so name and header agree; when `<name>` does not parse, minted at the first merge and then carried |
| `eval.eval_set_id` | the entries' common `eval_set_id`, else absent |
| `eval.dataset.sample_ids` | the selection ids when given as ids, else the sorted distinct held ids, typed as in the summaries written ("Recorded selection") |
| `eval.config.sample_id`, `eval.config.limit` | `None` ("Recorded selection") |
| `eval.shards` | the new field: ledger entries for every current attempt (a read shard's with `samples` the number of keys taken, `selected` the size of its `S_k` and the digest of `S_k`; an unchanged shard's carried as they were), `selection` and `sample_count` ("Recorded selection") |
| `results` | from "Metric recomputation"; `total_samples` is the selection size (or, without one, the distinct held ids) times epochs, `completed_samples` the merged samples without `error`; `early_stopping`, `logged_samples`, `metadata` absent |
| `stats` | from the ledger entries: `started_at` the earliest, `completed_at` the latest (`""` while any entry's is empty), `model_usage` and `role_usage` summed per key with `ModelUsage.__add__`; `connection_limit_history` empty (per-process history stays in the shards) |
| `log_updates`, `tags`, `invalidated` | carried from the existing merged header (merged-log edits), absent at the first merge |
| `config_updates` | absent (per-process runtime changes stay in the shards) |

Members, written into a local temp zip with the recorder's compression
settings (`zipfile_compress_kwargs`):

- `samples/{id}_epoch_{n}.json` for every planned key, named with
  `_sample_filename` (`eval.py:2005`): carried keys copied from the merged
  log's temp copy, keys of changed shards from the shard via
  `AsyncZipReader` streaming. The baseline copies by decompressing and
  recompressing, as `copy_live_members` does; "Scale items" replaces that
  with a raw copy.
- `summaries.json`: the planned keys' summaries, from the shards'
  summaries for changed shards and the merged log's `summaries.json` for
  carried keys.
- `reductions.json` from "Metric recomputation", and `header.json` last.
- No `_journal/` members: the merged log is written finished, whatever its
  status, so readers never take the running-log path for it.

The merge never builds an `EvalLog` holding samples; it holds one sample at
a time plus the metric inputs.

#### Metric recomputation

As each planned sample passes through step 11, the merge parses it once and
keeps `SampleScore(score=..., sample_id=..., sample_metadata=...)` per
scorer and whether `error` is set; everything else in the sample is
discarded before the next. After the last sample it calls
`eval_results(samples=..., scores=..., reducers=reducers_from_log_header(h),
scorers=resolve_scorers_info(h), metrics=metrics_from_log_header(h),
completed_samples=..., headline_metric=h.eval.headline_metric)` with the
template header `h`, mirroring `recompute_metrics` without loading the log.
Carried samples are read from the merged log's temp copy on every pass that
writes, because the merged log's sample members are the only lossless
source (summaries are lossy, parent "Constraints"). When
`resolve_scorers_info` would import the header's `task_file` (detected by
checking the registry for each metric name before the call), the merge
logs a warning naming the file and the CLI prints its notice; nothing is
recorded in the log. A metric that neither source provides raises, as
`metric_create` does today, and nothing is written (parent: "fails rather
than store metrics from a lossy input").

Memory: the current sample plus every sample's `SampleScore`s, as the
parent's "Scale" accepts. The baseline parses each sample whole, so peak
memory follows the largest sample; "Scale items" bounds it.

#### Consistent reads

A running shard's object is replaced on every flush, so a member range read
after the central directory can land in a newer object. Every member read
of a shard goes through an `AsyncZipReader` built with `verify_crc=True`
(#5542). A torn read means the shard changed after it was planned:
the pass discards its plan and temp output and restarts from step 4 (a
fresh listing, so the
shard's keys, status and identity are re-read and re-validated), at most
three times, then fails with the last error and writes nothing.

A `ZipCrcError` is not the only sign of a torn read. Member range reads
are not pinned to the central directory's ETag, the local header at the
recorded offset is parsed without a signature check, and
`read_member_fully` decompresses before it checks the CRC
(`src/inspect_ai/_util/async_zip.py:470`). So a shard rewritten with
different offsets (a new flush that grew a member, an `edit_score` or a
viewer edit that rewrites the whole zip) can instead raise a decompression
error, a `struct.error` from a garbage header, or an `EOFError` from a
short read. When the rewrite makes the object shorter, a stale offset can
lie past its new end: locally that is a short read, but on S3 the ranged
`get_object` fails with a `ClientError` whose code is `InvalidRange`
(HTTP 416), which `AsyncFilesystem.read_file_bytes` propagates
(`src/inspect_ai/_util/asyncfiles.py:592`; only the missing-object codes
are mapped, to `FileNotFoundError`, by `_map_missing_s3_object` at `:64`).

The merge restarts when `is_torn_read(ex)` is true for an exception from
any read of a shard. PR 5 adds that predicate to `_util/async_zip.py`
beside `ZipCrcError`: true for an instance of the set ctl log-dir mode
already treats as torn (`_TORN_READ_ERRORS` in
`src/inspect_ai/_control/log_dir/consistency.py:40`: `ZipCrcError`,
`zlib.error`, `zstandard.ZstdError`, `struct.error`, `EOFError`, ijson's
`JSONError` and `ValueError`), moved beside it, and for a botocore
`ClientError` whose `response["Error"]["Code"]` is `"InvalidRange"`.
Every other `ClientError` (access denied, expired credentials, throttling
after the client's retries) is not torn and propagates at once, as do
`FileNotFoundError` and other storage errors. ctl's `consistency.py`
calls the same predicate, so the two agree on what counts as torn, and
ctl gains the `InvalidRange` case ("Reading a member consistently" in its
design). As in ctl, a pydantic `ValidationError` is not a torn read and is
checked first (it subclasses `ValueError`): it is raised only after the
bytes passed their CRC check, so it means the member itself does not
parse, and the pass fails at once.
Checking the local-header signature in the reader would catch some of
these cases earlier but not a decompression error from a stale range, so
it is not needed. A shard that is corrupt rather than changing fails the
same way after its restarts. The merged log itself is read from a local
copy pinned to `E0` (S3) or under the local lock, so it needs no
re-reads, and an error reading it is not a torn read.

#### Deleting shards

Decision (Ransom, 2026-09-24): keep deletion simple. Two callers delete a
companion: `delete_shards` (keeps the merged log) and eval-set retry
cleanup (removes the merged log too). Both use one routine,
`remove_shards_dir(log: str, *, include_log: bool = False) -> None` in
`_delete.py`, under this contract:

- **Only after a verified merge.** `delete_shards` runs it after its own
  pass has published or confirmed a `success` merged log and verified it:
  it reopens the merged log (S3: checking the reader's ETag equals the
  publish response's ETag, or `E0` when nothing was written), checks that
  its central directory's sample members are exactly the planned keys
  (every selected id with every epoch, numbering the sum of the ledger's
  `samples`), and that its `eval.shards.ledger` matches the plan; a failed
  verification raises
  `ShardSetError` with nothing deleted. Retry cleanup runs it only for a
  merged log that an unsharded `success` log has superseded ("Eval-set
  integration").
- **The caller is the only one operating on that log.** No worker is
  still writing into the companion and no other merge or deletion of the
  same log runs at the same time. Nothing is guaranteed when that is not
  true: two deletions can interleave, a concurrent merge can publish a
  merged log from a partly deleted companion, and a file written into the
  companion during the deletion may be left behind.
- **No object identity is needed.** The routine deletes the objects it
  listed and reports anything it finds afterwards; it never needs to tell
  one version of an object from another. It therefore works on every
  backend the merge accepts, and no backend is refused.
- **No resumption protocol.** An interrupted deletion leaves some objects
  behind and reports them; the user re-runs the command or removes the rest
  by hand. Nothing records that a deletion was in progress.

The routine:

1. List every object under the companion.
2. Refuse up front (`ShardSetError`, nothing changed) when any `<k>/` holds
   ancillary output, meaning anything other than its `.eval` attempt files
   and objects under `<k>/.buffer/`: scan results (a worker's default scan
   directory is `<k>/scans/scan_id=...`, from `_scan_dir` on its log
   directory, `src/inspect_ai/_eval/task/scan.py:829`) and checkpoint
   directories (`<shard>.checkpoints/` beside each shard,
   `eval_checkpoints_dir`, including ones kept with `retention="retain"`,
   `src/inspect_ai/util/_checkpoint/config.py:172`). Step 1 neither merges
   nor relocates them, so deleting them would lose data the merged log
   does not hold. Also refuse when a log file lies below a directory in the
   companion whose name starts with `.`: one directly in it is a stray file
   the merge already refused, and one nested deeper is an ordinary log
   (`is_shard_path`), which deletion must not remove.
3. With `include_log`, delete the merged log first.
4. Delete the listed objects (S3 batch deletes; file by file locally and
   on other fsspec backends), never a recursive delete of the prefix, in
   two phases. First every listed object except each `<k>/`'s current
   attempt (the last in `attempt_sort_key` order: superseded attempts,
   including an original beside its `-recovered` copy, and buffer
   objects). If any of these deletes fails, stop and go to step 5 without
   starting the second phase. Then the current attempts, in any order.
   Recovery depends on this order (below).
5. List again and remove the empty local directories. If anything is left
   (a failed delete, or a file written after step 1), raise
   `ShardSetError` naming every remaining path.

Why the merged log goes first when it is removed too: if the routine is
interrupted, what remains is part of a companion with no merged log. The
next `eval_set()` startup merges that remainder into a new merged log with
the same `task_id` (it comes from `<name>`), and retry cleanup removes it
again, because the unsharded `success` log that superseded it is kept
("Retry cleanup": a failed removal also stops cleanup of that task group
for the rest of the `eval_set()` call). A merge running concurrently that had
read the merged log before step 3 has its conditional publish refused,
since the object it expected is gone ("Overlap guards"); one that starts
after step 3 is the concurrent case the contract excludes.

Why `delete_shards` deletes current attempts last: the merged log stays and
holds every record, and after an interruption every later merge refuses the
companion because its ledger names shards that have vanished
("Validation"). So a remnant is never merged over the complete log.
Re-running with `delete_shards=True` passes that check only when every
shard still present is unchanged (the exception in "Validation"). The
two phases keep that true at every point of interruption: each `<k>/`
either still has the current attempt its ledger entry records (unchanged,
whatever superseded files or buffer objects are left) or has no attempt
at all (vanished). Deleting in listing order would break this: `X-recovered.eval`
sorts before `X.eval`, and S3 batch deletes can fail per key in any order,
so an interruption could leave a superseded attempt as the current one,
which the merge refuses as an attempt regression. The second phase needs
no order, because a `<k>/` whose current attempt is deleted then has no
attempt left.

What the user sees after an interruption:

| Interrupted | What is left | What the user sees | What to do |
|---|---|---|---|
| `delete_shards` (API or `inspect log merge-shards --delete-shards`) | the complete merged log and part of `<name>.shards/` | `ShardSetError` listing the remaining paths; until they are gone, every merge of the log, including the `eval_set()` startup merge, refuses with "shards vanished" (and `eval_set()` stops with `PrerequisiteError`, "Eval-set integration") | re-run the same call with `delete_shards=True`, or delete `<name>.shards/` by hand |
| retry cleanup in `eval_set()` | the unsharded `success` log, part of `<name>.shards/`, no merged log, and every other log of that task group (cleanup of the group stops for the rest of the call) | a warning naming the remaining paths and asking for them to be deleted | delete `<name>.shards/` by hand. If it is left, the next `eval_set()` with `retry_cleanup` normally rebuilds a merged log from the remnant and removes it again; that is a fallback, not a guarantee (a remnant the merge refuses stops `eval_set()` with `PrerequisiteError`) |

**The viewer is not a deleter.** `/log-delete` is unchanged (decision:
Ransom, 2026-09-24): deleting a merged log in the viewer deletes only that
file. Its `<name>.shards/` companion remains, and the next `eval_set()`
startup merge over the directory rebuilds the merged log from it. Until
then the viewer lists the shards again, since no merged log covers them
(#5591). To remove a sharded run for good, delete the companion directory
as well. This is a documented limitation of Step 1, stated in the sharding
docs.

Compatibility boundary for ancillary output: Step 1 does not merge
per-shard scan results or checkpoints. Scan rows written by workers stay in
their `<k>/scans/`; an `eval_set()` with scanners over the parent directory
looks under `<dir>/scans/` and scans the merged log's samples there again.
Deletion refuses rather than destroys, and the refusal message names the
ancillary directories so the user can move or remove them deliberately.

#### Cancellation and concurrency

- Cancellation before publication leaves the merged log and shards
  untouched; temp files are closed in `finally`, and the local lock is
  removed in `finally`. Cancellation during publication is covered under
  "Overlap guards".
- Shard listing (`<k>/` listings) is bounded at 32 concurrent, shard reads
  at 16, all within the pass's one `AsyncFilesystem` scope, through
  `tg_collect`. Blocking zip work (compressing, `zipfile` writes) runs in
  `anyio.to_thread.run_sync` with `anyio.from_thread.check_cancelled()`
  between members, as `copy_live_members(..., cancellable=True)` does
  (`src/inspect_ai/_util/zipfile.py:212`).
- The pass holds no lock across `await` other than the local lock file,
  which is a filesystem object, not an in-process lock.

### Overlap guards

Parent decision (2026-09-22): callers serialise merges; compare-and-swap
publication turns a broken contract into a refused publish.

**Local.** Before step 3 the merge creates `<dir>/<name>.merge.lock` with
`O_CREAT | O_EXCL | O_WRONLY` and writes `{"pid", "host", "started"}` into
it; the lock is removed after publication or failure. If the file exists,
the merge raises `WriteConflictError` naming the file and its contents and
does nothing else; a lock left by a crashed merge is reported, never
overridden (the parent's test list). The lock sits beside the merged log
rather than in the companion so that the companion holds only shard files
(parent: nothing else is written into `<name>.shards/`); its extension
keeps it out of every log listing (`_filter_log_files` keys on extensions,
`_file.py:1118`). `delete_shards` runs inside the merge pass and so under
this lock; retry cleanup does not take it (its callers are covered by the
"only one operating on that log" contract in "Deleting shards"). The lock
does not cover a viewer edit of the merged log
made during a merge; the merge's `os.replace` wins. S3's `IfMatch` does
catch that case.

**S3 download.** The merged log is copied to a local temp file only when
step 10 writes, by a new `AsyncFilesystem.get_file_if_match(remote, local,
etag)`: ranged GETs of `_s3_transfer_config().multipart_chunksize`, each
with `IfMatch: E0`, so memory is bounded by chunk size times concurrency and
every byte comes from the object whose header step 3 read. On asyncio it is
`_s3_download_file_async` (`asyncfiles.py:344`, which already pins its
ranges with `IfMatch`) given the expected ETag instead of taking it from its
own `head_object`; on Trio, the same ranged loop with synchronous boto3 in
`anyio.to_thread.run_sync`, checking cancellation between ranges. A `412`
(the object changed since step 3) raises `WriteConflictError`.
`_s3_download_with_etag` (`eval.py:793`), which reads the whole body into
memory, is not used.

**S3 publish.** A new method in `src/inspect_ai/_util/asyncfiles.py`:

```python
async def write_file_conditional(
    self,
    filename: str,
    source: BinaryIO,
    *,
    if_match: str | None = None,
    if_none_match: bool = False,
) -> str:
    """Upload `source` to an S3 key only if the key's current state matches.

    Exactly one of `if_match` (the expected ETag) and `if_none_match` (the key
    must not exist) is required. Returns the new object's ETag. Raises
    WriteConflictError when the condition fails. S3 URLs only.
    """
```

- Below the multipart threshold: `put_object` with `IfMatch` or
  `IfNoneMatch: *`. At or above it: create, upload parts, then
  `complete_multipart_upload` with the condition. S3 honours both
  conditions on both calls.
- Pre-checks for backends that ignore the condition: for `if_match`, the
  `head_object` ETag comparison `_s3_put_object` already makes (moto needs
  it for the multipart case, "Current behaviour"); for `if_none_match`, a
  `head_object` that must return 404. The second is not atomic; it narrows
  the window on backends without `IfNoneMatch` support, which otherwise
  keep only the contract (parent).
- `PreconditionFailed` from the final call, or a pre-check mismatch, raises
  `WriteConflictError`; the multipart upload is aborted. Under `if_match`, a
  missing object (the pre-check's 404, or S3's 404 or 412 on the final
  call) is also a conflict: that is how a merge that read `E0` is refused
  after retry cleanup removed the merged log ("Deleting shards", step 3).
- **The final call is sent once.** Both shared clients are created with
  `retries={"max_attempts": 10, "mode": "adaptive"}`
  (`asyncfiles.py:1057`, `:1141`), and the SDK retries a `500` on its own
  (the round-1 reviewer's probe: one conditional `put_object` dispatched
  twice), so bypassing `_s3_put_with_retry` is not enough. The
  `AsyncFilesystem` therefore creates, on first use, a second client with
  `retries={"total_max_attempts": 1}` and otherwise the same configuration
  (`_create_s3_client_async` and the boto3 client builder gain a
  `max_attempts` argument), and uses it only for the conditional
  `put_object` and `complete_multipart_upload`. Pre-checks, part uploads
  and every existing caller keep the retrying clients. A retried final call
  that had in fact succeeded would be refused by its own condition, which
  is why it is never retried.
- **Ambiguous outcomes.** If the final call fails without a response
  (timeout, connection reset) or the task is cancelled after it was sent,
  the object may or may not have been written. The error (or cancellation)
  propagates unchanged, not as `WriteConflictError`. Re-running the merge
  is safe: a publish that landed is read as the current merged log, its
  ledger matches the shards, and the next pass writes nothing.
- asyncio route: `_s3_upload_fileobj_async` and
  `_s3_multipart_upload_async` gain an optional `condition` mapping and
  `final_client` applied to the final call; existing callers pass neither
  and are unchanged. Cancellation while a part is uploading aborts the
  upload through the existing shielded abort; cancellation during the
  final `await` is the ambiguous case above (the abort is still attempted
  and fails harmlessly if the upload completed).
- Trio route: s3transfer cannot send the conditions, so the method runs a
  small synchronous multipart upload in `anyio.to_thread.run_sync`
  (create, sequential `upload_part` from the source, conditional
  complete). A non-abandoning worker thread does not see the task's
  cancellation by itself, so the loop calls
  `anyio.from_thread.check_cancelled()` before each part and immediately
  before the final call; a cancellation raised there (or any exception)
  aborts the upload in the thread before re-raising. Once the final call
  has been sent the thread runs it to completion and the outcome is the
  ambiguous case above. Parts use the `_s3_transfer_config()` sizes.

The merge's first publish uses `if_none_match=True`; later ones
`if_match=E0`. `write_file_streaming` and every existing caller stay
unconditional.

**Other backends** (GCS, Azure and other fsspec filesystems) publish with
`write_file_streaming` and keep only the contract; the docstring says so.
The parent defers per-backend preconditions to a future remote lock
protocol.

### Eval-set integration

Changes in `src/inspect_ai/_eval/evalset.py`; none in selection mode, which
never scans the directory.

**Startup merge.** In `try_eval`, before the directory is read for pairing:

1. Build `eval_set_args` and `all_tasks` (identifiers) first; they are
   pure and today are built just after the listing (`:1047`, `:1083`).
2. `list_eval_logs(log_dir)` once. Every listed file for which
   `is_shard_path(log_dir, name)` is true (shared helper) marks a
   companion: the path up to the first component below `log_dir` that ends
   in `.shards`. Collect the distinct companions. A log nested deeper in a
   companion (inside a shard's ancillary directory, including a companion
   nested there) is an ordinary log: it marks no companion and takes part
   in pairing like any other log. A companion with no log file left
   (for example only `.buffer/` objects after an interrupted deletion) is
   not found, and needs no merge.
3. For each companion (4 at a time, one `AsyncFilesystem` scope), read one
   header, compute its identifier and find the resolved task with it. The
   header is the merged log's when it is in the step 2 listing; otherwise
   that of the first attempt the listing holds for the companion: the
   `.eval` files directly in a `<k>/` whose name does not start with `.`,
   taking `<k>/` in `list_shard_set`'s shard order and the current attempt
   in it by `attempt_sort_key` (a running attempt's header synthesised
   from `_journal/start.json`, as in the merge's step 6). A `<k>/` with no
   attempt (only `scans/` or
   `.buffer/`) is passed over, so a later shard identifies the companion.
   Any attempt serves, since the merge refuses shards whose identifiers
   differ. A companion with neither a merged log nor an attempt was marked
   in step 2 only by stray files; it stops `eval_set()` with
   `PrerequisiteError` before any task runs, naming the companion and its
   stray files, the outcome its merge would have ("stray files", step 5),
   rather than being skipped, since nothing can tell which task it belongs
   to. A companion matching no task is left alone with a warning, like any
   other log that belongs to no task in the set.
4. Merge it with `allow_incomplete=True` and the selection
   `selected_sample_ids(task.task.dataset, limit, sample_id, task.task.name,
   task_names)`, a new sibling of `samples_selected` in
   `eval_set_manifest.py` that returns the ids `slice_dataset` would select
   (same unset-id rule). The eval set's selection is the intended selection,
   so an eval set run over a sharded subset without the subset's
   `sample_id` treats the rest of the dataset as missing and runs it, which
   is what an eval set means.
5. **A refused startup merge stops `eval_set()` with `PrerequisiteError`,
   in every case** (decision: Ransom, 2026-09-24: "yes, PrerequisiteError
   in all cases"). Nothing warns and continues, including a lost S3
   publish race. Every exception a startup merge raises is re-raised as a
   `PrerequisiteError` (the original chained as its cause) before any task
   runs; cancellation propagates unchanged. `ShardSetIncomplete` cannot
   occur (`allow_incomplete=True`). The message names the companion
   (`<dir>/<name>.shards/`), the cause as the merge reported it, and what to
   do next:

   | Cause | Raised by the merge as | What the message tells the user to do |
   |---|---|---|
   | Invalid shard set: mismatched identifier, scorers, metrics, dataset size, epochs, reducer or format version; overlapping shard selections; ids outside the selection; a shard with no recorded selection or holding samples outside it (a `SampleSource` task); a shard whose selection changed across attempts; stray files; chunked-shape samples | `ShardSetError` | fix the shards named in the message (remove or move the offending files; for a changed selection, move the new attempt to its own `<k>/` or delete `<name>.eval`), then re-run |
   | Merged log does not match its ledger (its samples were changed outside the merge) | `ShardSetError` | delete `<name>.eval` so the next merge rebuilds it from the shards, then re-run |
   | Vanished shard (shard files deleted after they were merged, for example an interrupted `delete_shards`) | `ShardSetError` | finish the deletion (`inspect log merge-shards <name>.eval --delete-shards`, or delete `<name>.shards/` by hand) or restore the files, then re-run |
   | Attempt regression (a shard's current attempt deleted by hand while an older attempt was kept) | `ShardSetError` | restore the deleted attempt; or delete `<name>.shards/` by hand to keep the merged log as it is; or delete `<name>.eval` to rebuild it from the attempts now present; then re-run |
   | An ordinary `<name>.eval` (no `eval.shards` field) where the merged log belongs | `ShardSetError` | move or rename that log, or the companion, then re-run |
   | Local merge lock held (`<name>.merge.lock`), including one left by a crashed merge | `WriteConflictError` | wait for the other merge to finish and re-run; if no merge is running (the lock's `pid`/`host` shown in the message), delete the lock file and re-run |
   | Lost S3 publish race (another merge published first, or the merged log changed during the pass) | `WriteConflictError` | re-run once the other merge has finished; the merge is idempotent |
   | Anything else (a storage or transport error, a metric the merge cannot resolve) | the original exception | the cause is in the message and the chained exception; fix it and re-run |
6. If any merge wrote, list again; otherwise reuse the listing.

**Shard skip before header reads.** `list_all_eval_logs` gains
`skip_shards: bool = False`, which drops `is_shard_path(log_dir, name)`
files before `read_eval_log_headers`: every attempt and stray file of a
companion, and nothing else. A log nested deeper in a companion stays in
the listing as an ordinary log, so the skip never hides a log that the
shard walk does not report. Both eval-set call sites (startup and
`cleanup_older_eval_logs`) pass `True`; `inspect_flow`'s callers keep the
default. The startup path in step 2 applies the same filter to the listing
it already holds.

**Completeness.** `log_samples_complete` gains a branch for a log with
`eval.shards`: complete when `status == "success"` (already required by the
caller), epochs are unchanged (the existing `epochs_changed` check), and
the log's `eval.dataset.sample_ids`, as a set of `str(id)`, equals the
planned selection (`selected_sample_ids`). The count comparison is not used
for such logs, and no key list is needed: the merge writes `success` only
when the held keys are the recorded selection times every epoch, and on a
`success` log `dataset.sample_ids` is the selection's ids in every form of
selection ("Recorded selection": the ids themselves, or the held ids,
which then are the whole selection). After a successful startup merge this
agrees with the merged status, since the startup merge records the eval
set's own selection; the branch keeps the rule right on its own, for
example for a merged log last written by the CLI with a different
selection.

**No recovery of merged logs.** `_recover_crashed_log` returns its inputs
unchanged when `eval_log.eval.shards` is set, so neither call site recovers
a `started` merged log (which has no buffer; the startup merge has already
brought it up to date). The retry then seeds from the merged log and re-runs
the missing samples as an ordinary unsharded log (parent).

**Retry cleanup.** In `latest_completed_task_eval_logs`, for each `task_id`
group, with `M` the logs carrying `eval.shards` and `U` the rest:

- **`M` non-empty and some log in `U` is `success`** (an unsharded retry
  of a merged log succeeded): the latest log is chosen from `U` alone, by
  mtime, exactly as today's rule orders any group. Every log in `M` is
  never the latest, and with cleanup on is removed, whatever its status,
  `started` included, through `remove_shards_dir(log, include_log=True)`.
  This is the parent's rule (the unsharded `success` log is kept and the
  merged log is removed with its shards, regardless of mtime), and it is
  the one exception to "`started` logs are never removed": a `started`
  merged log is the normal state before such a retry, has no buffer, and
  is superseded by it. The logs in `M` are removed first. Logs in `U`
  other than the latest are then removed as today (non-`started` only),
  with one exception: unless every log of `M` was removed completely (the
  merged log and every companion object), the newest `success` log in `U`
  is kept even when it is not the latest. It
  is the evidence that `M` is superseded; without it, the next
  classification would fall into the branch below, pick `M` (or a merged
  log rebuilt from a leftover companion) by mtime, and delete the newer
  unsharded attempt.
- **Otherwise** the group is ordered and cleaned exactly as today; a
  removed non-latest merged log goes through `remove_shards_dir(...,
  include_log=True)` instead of `fs.rm`.
- A `remove_shards_dir` refusal or failure (ancillary output in the
  companion, a failed delete, a file left over; "Deleting shards") logs a
  warning naming what is left and asking the user to delete it, and stops
  cleanup of that task group for the rest of the `eval_set()` call: the
  group's `task_id` goes into an in-memory set that the final
  `cleanup_older_eval_logs` sweep (`evalset.py:1191`), which lists again
  without a startup merge, skips. That is what keeps the newest unsharded
  `success` alive after the merged log itself was deleted: the final sweep
  would otherwise see no merged log, fall into the branch below, and remove
  it, and the next startup could rebuild the merged log from the remnant,
  pick it by its fresh mtime, and delete the newer unsharded attempt. The
  set is not persisted. In a later call the startup merge runs first, so a
  merged log rebuilt from a remnant meets the kept `success` and stays in
  the first branch (never latest, removed again).

So the ordering among unsharded attempts never changes. The case that rules
out a sort key promoting unsharded successes: a merged log `M`, an older
unsharded `success` `S`, and a newer unsharded `error` `E` holding more
samples (for example after the epochs were raised). Today's order over `U`
makes `E` latest; cleanup removes `M` with its companion and then `S`. If
`M`'s removal is refused (its companion holds scan results), `S` is kept,
so the next pass again makes `E` latest and removes nothing it should not;
`S` goes once `M` does.

UKGovernmentBEIS/inspect_ai#5396 edits the same function (it also removes
older `started` unsharded logs and their buffers). This design does not
depend on it; whichever lands second rebases onto the other and keeps both
rules.

### Scale items

Two PRs after the merge core, each with the measurement that justifies it:

- **Streaming recomputation.** Score extraction parses each sample with an
  include-only streaming parse (ijson, the builder behind
  `_read_member_json_excluding`, `eval.py:666`, with the excluded set taken
  as every `EvalSample` field except `id`, `epoch`, `scores`, `metadata`,
  `error`), so peak memory stops following the largest transcript. The
  parse still tokenises the whole member; it no longer builds its objects.
  One exception is inherited: the builder falls back to `json.loads` of the
  whole member for non-finite numbers and integers too large for the
  streaming parser (`eval.py:686`), so such a sample is still parsed whole;
  the bound holds for every other sample. Acceptance: the parent's memory
  test (peak memory independent of transcript size; growth with score
  metadata accounted to the retained metric inputs), plus one sample that
  takes the fallback, measured and reported rather than bounded.
- **Raw compressed-member copy.** A writer in `src/inspect_ai/_util/zipfile.py`
  that appends a member from its compressed bytes: a fresh local header
  built from the source central-directory entry (method, CRC-32, sizes,
  name), the compressed bytes verbatim (`AsyncZipReader.open_member_raw`
  for shards, the local copy for carried members), and a central-directory
  entry with the new offset, ZIP64 when needed. Uses the `ZipEntry` CRC
  (landed, #5542). Removes the recompress of every sample; the decompress for
  score extraction remains. With CRCs available, a changed shard's member
  whose CRC equals the carried member's is kept from the merged log without
  reading the shard.

### Code shared with ctl log-dir mode

| Piece | Owner PR | Merge uses it for | ctl log-dir mode uses it for |
|---|---|---|---|
| `log_basename`, `eval_shards_dir`, `eval_log_for_shards_dir`, `eval_log_name` (`src/inspect_ai/_util/log_layout.py`) | #530, landed (UKGovernmentBEIS/inspect_ai#5541) | the `<name>.eval` / `<name>.shards/` pair, `<name>` minting by launchers | mapping `X.shards/` to its merged log (its "Logical tasks") |
| `AsyncFilesystem.list_dir(base) -> DirListing(files: list[FileInfo], dirs: list[str])` | #528, landed (UKGovernmentBEIS/inspect_ai#5542) | listing `<name>.shards/` and each `<k>/` | the delimited walk |
| `ZipEntry.crc32` and `AsyncZipReader(verify_crc=True)` / `ZipCrcError` | #528, landed (UKGovernmentBEIS/inspect_ai#5542) | consistent shard reads; raw copy | consistent member reads |
| `list_shard_set`, `attempt_sort_key`, `is_shard_path` (`src/inspect_ai/log/_shards/_walk.py`) | PR 3 below | steps 4–5; the eval-set skip and companion discovery | its step 4 (shard aggregation) calls these instead of re-implementing the rules |
| `EvalShards`, `EvalShardEntry` and the recorded selection ("The `EvalSpec.shards` field") | PR 2 below | writing the field | its step 6: totals from the recorded selection; a cold start of the one-row-per-task `task list` row (not sample rows or per-sample reads) from the merged `summaries.json` only for a complete `success` snapshot whose shards are all unchanged and each hold their whole selection (`samples == selected × epochs`), otherwise the shards; `--shards` rows read every shard |

`list_dir` (`src/inspect_ai/_util/asyncfiles.py:1029`) makes one
delimited listing (on S3 one `list_objects_v2` sweep with `Delimiter="/"`;
locally `os.scandir`, not following directory symlinks). Paths keep the
form `base` was given in (a `file://` child is built with `to_uri`), and
`DirListing.dirs` entries have no trailing separator. A missing local
`base` raises `FileNotFoundError`, while an empty S3 prefix lists as empty;
`list_shard_set` maps both to an empty listing (no companion), so local and
S3 behave the same.

The shard-set rules, one implementation for both consumers:

- `list_shard_set(fs, shards_dir) -> ShardSetListing(shards:
  list[ShardDir], stray: list[StrayFile])`, with `ShardDir(name: str, dir:
  str, attempts: list[FileInfo], has_buffer: bool, ancillary: list[str])`
  and `current` the last attempt or `None`. It lists `<name>.shards/` once
  with `list_dir`, then each directory directly under it (32 at a time),
  and nothing deeper. In `<k>/`: `.eval`
  files are attempts, a `.buffer/` prefix sets `has_buffer`, and every other
  file or directory (for example `scans/` or `<shard>.checkpoints/`) is
  recorded in `ancillary` and not descended into. A
  directory whose name starts with `.` is not a shard; it is listed only
  to report the logs directly in it. That includes a `.buffer/` directly in
  the companion (the buffer of a stray log there): listed once, never
  descended, so its `<stem>/` directories and segments are not listed;
  every other `.buffer/` (in a `<k>/`) is not listed at all. Shards with all-digit names sort
  first, numerically, then the rest by name; a `<k>/` with nothing in it
  is left out. `stray` holds every log file the walk sees that is not an
  attempt, each a `StrayFile(path, reason)`, sorted by path: a log
  (`.eval` or `.json`) directly in `<name>.shards/`, a log directly in a
  directory whose name starts with `.`, and a `.json` log in a `<k>/`. The
  walk never raises for them. The merge refuses any stray file; ctl
  reports them (its `unreadable` list is the natural place; that choice is
  ctl's). Together, attempts and stray files are exactly the logs
  `is_shard_path` places in the companion.
- `ShardSetListing.unlisted_dirs: list[str]`, added by ctl log-dir mode's
  step 4 (PR 3 does not have it): the directories the walk saw and did not
  list, sorted. These are every directory in a `<k>/` other than
  `.buffer/` (including `<shard>.checkpoints/`), and every directory in a
  directory whose name starts with `.` other than a `.buffer/` (the buffer
  of a stray log in the companion root). ctl descends them to find the
  ordinary logs nested there (below); `ShardDir.ancillary` mixes files and
  directories with no marker, so without this field ctl would need a
  listing per ancillary entry to tell them apart. The merge does not read
  it.
- `attempt_sort_key(info)`: the `{created}` timestamp prefix of the file
  name (matched with `_timestamp_prefix_re`, `_file.py:1163`), parsed as a
  datetime rather than compared as text; then a `-recovered` file after
  the file it was recovered from; then mtime. Names without a timestamp
  sort by mtime alone. This is ctl's "Attempt order", and matches the
  parent's "newest by the shard's `created` time", since the recorder names
  files from `eval.created`. It is not mtime-first, as `eval_set()` orders
  retries, because a running older attempt's mtime moves on every flush.
- `is_shard_path(root, path)`: true when `path`, relative to `root`, is
  directly in the first directory below `root` named `<name>.shards`, or
  in a directory directly under it: exactly the files `list_shard_set`
  lists for that companion. Only components below `root` count, so a log
  directory that is itself a `<k>/` (a worker's view) is not a shard of
  itself. Plain paths and `file://` URIs compare as absolute local paths;
  a `path` outside `root` raises `ValueError`.

**Logs nested deeper in a companion are ordinary logs** (decision:
Ransom, 2026-10-05). A log in a shard's ancillary directory (for example
`run.shards/0/scans/<file>.eval`), or deeper than a dot-directory of the
companion, is not a shard path, so no consumer drops it unreported:
eval-set keeps it in pairing and header reads, ctl log-dir mode lists it as
an ordinary log by descending `unlisted_dirs` (its "Walking the
directory"), the merge ignores it, and deletion refuses to remove it
("Deleting shards"). A companion nested in an ancillary directory follows
the same rule: from a root above the outer companion its logs are
ordinary logs, and from a root that is the outer companion or a directory
inside it, it is a shard set. Given the same root, eval-set and ctl
therefore agree on which files are shard attempts, which are stray and
which are ordinary logs.

ctl log-dir mode's step 4 depends on PR 3, and adds `unlisted_dirs` to the
shared module; its step 6 depends on PR 2. Neither depends on the merge.

## Alternatives considered

- **Exact keys in the ledger** (`sample_keys`, one `(id, epoch)` object per
  record merged from each shard; this document's earlier revisions).
  Attributes every record to its shard directly and lets ctl take any
  shard's rows from the merged summaries. Rejected (Ransom, 2026-09-29): it
  puts about epochs times `dataset.sample_ids` of new per-sample data in
  every merged header, which every header read parses; the merged log's
  own members already say which records exist, and attribution by id
  needs only a count and a digest per shard ("The sample set").
- **Key attribution in a zip member** (a `shards.json` mapping keys to
  shards) instead of the header. Keeps the header small, but adds a stored
  member that seeded retries would copy into unsharded logs unless
  `_prune_prior_members` learned it (`eval.py:1522` keeps unknown members),
  and a second read for ctl's cold start. Attribution by id needs no
  mapping at all.
- **Reopen unchanged shards instead of storing their stats and errors.**
  Keeps the ledger small, but every pass would read one header per shard,
  which is exactly the cost the incremental design avoids at 300 shards.
- **Each shard's selection ids in the ledger** instead of a digest. Would
  let an incremental pass check every pair of selections, as a fresh merge
  does, but it is per-sample data again (one id per selected sample). The
  digest detects the one change attribution cannot survive; overlaps are
  refused through the counts ("The sample set").
- **Id-level records (`sample_ids` expanded by epochs).** Smaller, but it
  invents records for running, failed and drained shards and makes fresh
  and incremental merges disagree (round 1 of this document). Attribution by
  id is different: it groups the records that exist, taken from the merged
  log's members, and never expands ids into keys.
- **Fall back for a shard with no usable selection** (a `SampleSource`
  task, or a header without `sample_ids`) by re-reading the attempt the
  ledger's `log` names and attributing its keys exactly. Rejected:
  a running attempt grows in place, so the attempt the ledger names is the
  same file with newer contents, and its old keys are gone; and sharding a
  task whose samples are produced while it runs has no launcher use in
  Step 1 ("Validation").
- **Deletion that survives crashes and concurrent deleters, and a viewer
  delete cascade.** Rounds 2 to 5 of this document's review built a
  deletion marker, recorded object identities, a `detached` header state,
  resumption rules and a per-object viewer authorization cascade; each
  round's review found new races in that machinery. Rejected (Ransom,
  2026-09-24): Step 1 makes no viewer changes and keeps deletion simple
  (only after a verified merge, no concurrent operation on the same log,
  report leftovers, finish by re-running or by hand). The vanished-shard
  refusal in "Validation" is what keeps an interrupted `delete_shards` from
  being merged over the complete log without any of that state.
- **Merge scan results and checkpoints into the merged log's locations.**
  Would let deletion proceed, but it is a new relocation feature with its
  own compatibility rules (Scout's scan directory layout, checkpoint
  retention); Step 1 refuses deletion instead ("Deleting shards").
- **A broad shard-path rule** (`is_shard_path` true for any path with a
  directory component ending in `.shards`; this document's earlier
  revisions). Simpler to state, but `list_shard_set` never lists below a
  `<k>/`, so a log nested in an ancillary directory (`<k>/scans/...`, or a
  companion nested there) would be skipped by eval-set and reported by
  nothing. Rejected (Ransom, 2026-10-05) for the rule matching the walk
  ("Code shared with ctl log-dir mode"). Descending ancillary directories
  in the walk instead would make the merge list scan and checkpoint trees
  it never uses.
- **Keep samples from superseded attempts ("newest copy of each key across
  every file in `<k>/`").** Also deterministic, and keeps samples a newer
  attempt lacks. Rejected: every pass must read every attempt's summaries,
  and ctl already chose "current attempt only"; two rules would show
  different sample sets for the same directory.
- **A lossless metric-input cache in the merged log** (scores and sample
  metadata per key, keyed by the sample member's CRC so edits invalidate
  it). Saves reading carried samples each pass. Deferred: a new stored
  member and an invalidation rule, for a cost the parent already accepts
  ("merge rarely"). Revisit with measurements after the raw copy.
- **One `write_file_streaming` with an optional condition.** Fewer methods,
  but the conditional path has different retry semantics (never retry the
  final call) and a different Trio implementation; a separate method keeps
  every existing caller's behaviour visibly unchanged.
- **Merge core before the guards, guards later.** Shorter path to a first
  merge, but a release could ship an unguarded public merge. The guard
  primitives are independent of the merge, so they go first.
- **Directory-wide merge in the Python API.** The CLI accepts a log
  directory; the Python API takes one merged log. A caller with a directory
  and Python can list companions itself; adding a second public function
  now is surface without a caller.
- **Name the CLI `inspect log merge`.** Shorter, but reads as merging
  arbitrary logs. `merge-shards` matches the Python name
  (`merge_eval_log_shards`).
- **Warn and continue when the startup merge refuses a companion**,
  including only for a lost S3 publish race. Lets an eval set run, but then
  it pairs against a stale merged log or re-runs the task from scratch while
  the shards sit unmerged, which is the silent coercion AGENTS.md rules out.
  Rejected (Ransom, 2026-09-24): `PrerequisiteError` in all cases.

## Compatibility and migration

No migration required. Everything is opt-in through the directory layout;
logs, directories and callers that do not use `<name>.shards/` behave as
today.

- **Stored format.** `EvalSpec.shards` is optional and absent on every log
  but a merged log. Old Inspect versions read merged logs as ordinary logs
  and drop the field; an old version that rewrites a merged log produces an
  ordinary log, which the merge then refuses to overwrite (cross-version
  editing of merged logs is not supported). The merged log's members are
  the ordinary finished `.eval` members. Shard headers are unchanged.
  The merged header's only per-sample data is what an ordinary header
  carries (`dataset.sample_ids`; `config.sample_id` is left unset).
- **`eval_retry` of a merged log** is refused unless it was merged with
  no selection (`"none"`), which excludes every merged log `eval_set()`
  writes; `eval_set()` over the directory finishes those. An older Inspect
  retries any merged log over the whole dataset ("`eval_retry` of a
  merged log"). `.json` logs and chunked-shape samples are not supported as
  shards, and neither are shards of a `SampleSource` task or shards whose
  header has no `dataset.sample_ids` (logs from Inspect versions that did
  not record it); the merge refuses them ("Validation").
- **Changing a shard's selection.** A new attempt in an existing `<k>/`
  must select the same samples as the attempt already merged; otherwise the
  merge refuses until the attempt is moved to its own `<k>/` or the merged
  log is deleted and rebuilt.
- **Generated types.** `inspect-openapi.json` and `ts-mono`'s
  `generated.ts` gain `EvalShards`, `EvalShardEntry` and
  `EvalSpec.shards?`; landed through `land-ts-mono`. The viewer does
  not read the field in Step 1. `inspect_scout` gets the types from
  `@tsmono/inspect-common` when its `ts-mono` version moves.
- **Public Python API.** New: `merge_eval_log_shards`,
  `merge_eval_log_shards_async`, `ShardMergeResult`, `ShardSetError`,
  `ShardSetIncomplete`, `EvalShards`, `EvalShardEntry` in `inspect_ai.log`,
  listed in a "Sharding" section of `docs/reference/inspect_ai.log.qmd`.
  `list_all_eval_logs` (internal, but imported by `inspect_flow`) gains a
  keyword argument whose default keeps its behaviour.
- **CLI.** New `inspect log merge-shards`. No existing command changes.
- **Eval sets.** Behaviour changes only for task groups that contain a
  merged log: startup merges, shards skipped before header reads (attempts
  and stray files only; a log nested deeper in a companion is listed and
  read as today), merged
  logs classified by their status and recorded selection, not recovered, and, once an
  unsharded retry succeeds, never chosen as latest and removed with their
  companions (including a `started` merged log) unless the companion holds
  scan results or checkpoints. Ordering among unsharded attempts is
  unchanged. A directory whose companion the startup merge refuses (for
  any reason, including a held lock or a lost S3 race) now stops
  `eval_set()` with `PrerequisiteError` naming the companion, the cause and
  the next step, before any task runs.
- **Scan results and checkpoints written by workers** stay in their
  `<k>/`; Step 1 neither merges nor relocates them, an eval set with
  scanners over the parent directory scans the merged log's samples again
  under `<dir>/scans/`, and every deletion path refuses a companion that
  holds them.
- **Viewer.** Unchanged, including `/log-delete`. Its shard hiding
  (#5591) applies to merged logs as written here: a complete merge
  publishes a `success` log after reading its shards, so it is newer than
  them and hides them; an incomplete merge's log is not `success`, so its
  shards stay visible; a pass that writes nothing leaves the mtime as it
  was. Limitation: deleting a
  merged log in the viewer deletes only that file; its `<name>.shards/`
  companion remains, its shards show again, and the next `eval_set()`
  startup merge rebuilds the merged log. To remove a sharded run for
  good, delete the companion directory as well. The sharding docs (PR 5)
  say so.
- **Deletion guarantees.** `delete_shards` and retry cleanup assume they
  are the only operation on that log; an interrupted deletion reports what
  is left and is finished by re-running or by hand ("Deleting shards").
- **`AsyncFilesystem`.** New `get_file_if_match` and
  `write_file_conditional`, and a second, non-retrying S3 client used
  only by the conditional final call; existing
  methods and clients unchanged.

## Security

- **Untrusted inputs.** Shard headers, summaries, sample members, file and
  directory names in the companion, and the merged log itself are written
  by processes that may run agent code, or by anyone with write access to
  the bucket. They go through the existing pydantic models and zip readers.
  Paths are derived from listed names by fixed rules (`<name>` from the
  basename, `<k>` from listed prefixes, member names from keys); the
  ledger's file names and selection digests are never used to locate
  anything. Merged records parsed from the merged log's
  member names are used only as `(str(id), epoch)` keys for planning and
  counting; a name that does not parse is refused. Sample member names are rebuilt from `(id, epoch)` with the
  existing `_sample_filename` rather than copied from a source central
  directory, so a crafted member name cannot place data under another key.
- **Membership by location.** Strict validation (identifier, scorers,
  metrics, dataset size, epochs, reducer, format version, one owner per id,
  selection) refuses a stray or
  hostile file rather than skipping it; a merge never overwrites a
  `<name>.eval` without the field.
- **Code execution.** Recomputation may import the header's `task_file`
  (the existing `resolve_scorers_info` fallback). The merge runs only in
  trusted steps (API, CLI, `eval_set()` startup), logs a warning naming
  the imported file, and the CLI prints a notice. No reader path (viewer server,
  `read_eval_log*`, dataframes, ctl log-dir mode) calls it.
- **Viewer.** No change to the viewer server; its delete endpoint still
  authorizes and deletes only the requested file, so the new companion
  layout widens nothing it can delete.
- **Destructive cleanup.** Only trusted Python steps delete companions
  (`delete_shards`, retry cleanup). Both refuse, before changing anything,
  when scan results, checkpoints or an ordinary log nested in the
  companion are present, delete the objects they
  listed rather than the prefix, and report leftovers. They assume no
  concurrent operation on the same log; with one, a file written during the
  deletion may be deleted or left, which is a correctness limit, not an
  access-control boundary (anyone able to write into the companion can
  already delete it).
- **Resource use.** A hostile shard can make a merge expensive (huge
  samples, many keys), as the same files make `read_eval_log` expensive
  today. The scale PRs bound memory by the largest sample's metric inputs
  rather than its transcript. Nothing here runs inside a running eval.
- **Lock file.** Its contents are informational and never parsed for a
  decision; it is created with `O_EXCL` and default permissions beside the
  merged log.

## Testing

All tests run in the default CI job unless noted: mock-model evals
(`mockllm/model`) write real shards into a temp directory, and S3 cases use
the `mock_s3` fixture (`tests/conftest.py`, a moto server). New sharding
tests go in `tests/log/test_shards.py`, since no existing file covers the
area; eval-set, CLI, viewer and filesystem tests go in the existing files
named below. Async tests run under asyncio by default and under Trio with
`--runtrio` before each PR.

Per PR (numbers from "Implementation plan"):

1. **Layout helpers.** Landed with their tests in
   `tests/log/test_log_filename.py` (UKGovernmentBEIS/inspect_ai#5541).
   Nothing further here; later PRs test their own use of the helpers.
2. **The field.** `tests/log/test_eval_log.py`: round trip of a header
   with `shards` (each `selection` form, with `sample_count` for `"count"`,
   entries with and without `etag`/`error`, with usage, `samples`,
   `selected` and `selection_digest`; none of the dropped fields, `location`,
   `template`, `merged_at`, `metrics_source`, `attempts`, `eval_id` or
   `task_id`, is in the schema); a header
   without it serialises with
   no `shards` key; a
   header carrying an unknown extra key still validates (the property old
   versions rely on). `check-schema-and-types` in CI proves the regenerated
   schema and types match.
3. **Shared walk.** `list_dir` landed with its tests (#5542).
   `tests/log/test_shards.py`: a companion
   with `<k>/` directories holding one attempt, an original plus its
   `-recovered` copy (recovered current), two attempts with the older one
   touched last (the file-name timestamp wins over mtime), an empty `<k>/`,
   a `.buffer/` prefix, a `scans/` directory and a `<shard>.checkpoints/`
   directory (both `ancillary`), a `.buffer/<stem>/` with segments directly
   in the companion (listed once, its stem never; a recording of
   `list_dir` calls asserts it), a log in the companion root, a log in a
   directory whose name starts with `.` and a `.json` log in a `<k>/` (all
   stray); `is_shard_path` relative to the root,
   including a root that is itself a `<k>/`, a user directory named
   `shards`, logs nested deeper than a `<k>/` (not shard paths) and a path
   outside the root (`ValueError`). A consistency test, for plain paths,
   `file://` URIs and S3, that the logs `is_shard_path` places in a
   companion are exactly the attempts and stray files `list_shard_set`
   reports, including companions nested in a shard's ancillary directory
   or a dot-directory, seen from above and from inside the outer
   companion. Ctl log-dir mode's step 4 extends it when it adds
   `unlisted_dirs`: those logs, plus every log a recursive listing of
   `unlisted_dirs` finds, are every log `list_eval_logs` finds in the
   companion.
4. **Guard primitives.** `tests/util/test_asyncfiles.py` on `mock_s3`, for
   a body below and above a lowered multipart threshold, on asyncio and
   Trio: `if_none_match` creates an absent key and raises
   `WriteConflictError` for an existing one; `if_match` with the current
   ETag succeeds and with a stale one raises (through the pre-check, since
   moto ignores `IfMatch` on completion); a refused or failing completion
   leaves no in-progress multipart upload (`list_multipart_uploads` empty);
   Trio: cancellation while a part upload is blocked (a botocore
   `before-send` hook waiting on an event) aborts the upload and no object
   appears, on both routes; the final call is dispatched once: a
   `before-send` hook on `PutObject` and on `CompleteMultipartUpload`
   counts real dispatches and returns `500`, and the method raises after
   exactly one while part uploads are still retried; an ambiguous publish (a
   hook that lets the request through and then raises a connection error)
   propagates that error, not `WriteConflictError`, and the object exists.
   `get_file_if_match`: downloads a large object in bounded ranges (peak
   memory below twice the chunk size times concurrency), and raises
   `WriteConflictError` when the object is replaced between the expected
   ETag and the ranges.
   The local lock helper, in `tests/util/test_file.py`: a second acquire
   raises `WriteConflictError` naming the holder; release in `finally`
   after an exception and after cancellation.
5. **Merge core, API and CLI.** `tests/log/test_shards.py`, local and
   `mock_s3`:
   - arguments: `<name>-recovered.eval` raises `ValueError` naming
     `<name>.eval` and the companion, reads nothing and writes no second
     merged log (with and without `<name>.eval` present);
   - complete merges: shards from `--sample-id` subsets and from `limit`
     ranges; recomputed metrics equal an unsharded run's for a built-in
     metric and for a custom metric reading `answer` and `sample_metadata`,
     with epochs and a reducer;
   - status: running shards give `started`; an `error` and a `cancelled`
     shard give `error` with the message in the ledger and the first as the
     log's error; a rerun in the same `<k>/` clears it; `allow_incomplete`
     off raises `ShardSetIncomplete` with the missing ids and writes
     nothing; selection by ids, by count, and absent (whole dataset); a
     drained `success` shard holding fewer records leaves the set
     `started`;
   - partial epochs: with two epochs, a running shard holding only `(x, 1)`
     is recorded with exactly that key (`samples: 1`), and after another
     shard changes the next pass still holds `(x, 1)` only and stays
     `started`; two shards selecting one id are refused; fresh and
     incremental merges make the same completeness decisions and, for
     disjoint selections, the same conflict decisions;
   - attribution: the recorded selection round-trips in all three forms
     (`selection` `"ids"` with `dataset.sample_ids`, `"count"` with
     `sample_count`, `"none"`), and a later pass without a selection reads
     it back; the digest is independent of id order and of `1` versus
     `"1"`; a merged header of a 3-epoch, 100-sample set holds no
     per-sample list other than `dataset.sample_ids`: `config.sample_id` is
     unset, and its `header.json` is no larger than an unsharded log's of
     the same selection plus a per-shard bound; `eval_retry` of an incomplete
     merged log with `selection` `"ids"` (including one whose template shard
     used `limit` and `sample_shuffle`) and with `"count"` raises
     `ValueError` naming the log and runs no sample, while one with
     `"none"` retries the missing samples and reuses the merged records; an
     ordinary retry of a `--sample-id` pattern log and of a shuffled log
     behaves as before; a new attempt in `<k>/` with a
     different `--sample-id` is refused with both files named, and deleting
     `<name>.eval` then merges it; a new shard whose selection meets a
     carried record is refused; a changed shard whose merged records were
     reduced by hand (a member removed from the merged log) is refused, as
     is a pass over unchanged shards after the same edit; a shard of a
     `SampleSource` task that adds a sample is refused once it holds the
     added sample, and a shard header without `sample_ids` is refused;
     overlapping selections where neither shard holds the shared id yet
     are accepted incrementally and refused when the overlapped shard
     next changes, while a fresh merge refuses them at once;
   - validation: identifier, scorer, metric, dataset-size, epochs, reducer
     and format-version mismatches (a scorer change that keeps the
     identifier included), overlapping selections, a held id outside the
     selection, a chunked-shape sample, a slash-containing id
     (`group/item`, a monolith, accepted), stray files, and an existing
     ordinary `<name>.eval`, each refused (or accepted) with nothing
     written on refusal;
   - incremental: a grown shard adds only its new samples; an unchanged
     shard is not opened (a spy on `AsyncZipReader` construction); a pass
     over unchanged shards writes nothing and returns `written=False`; a
     new attempt in `<k>/` replaces `<k>`'s samples and drops ones it
     lacks; a deleted `<k>/` is refused as a vanished shard while removing
     the whole companion returns the existing header unchanged; an added
     shard returns a
     `success` log to `started`; `eval_id`, `run_id` and `task_id` are
     stable across passes; header edits (`tags`) survive a pass and a
     sample `edit_score` survives while its shard is unchanged;
   - fresh equals incremental: after replacing one shard's attempt, after
     adding a shard whose name sorts before the template shard (so the
     template changes), and after a sequence where shard A fails,
     then B fails, then A recovers, the incremental header equals a fresh
     merge's (`stats` with distinct per-shard usage, `error` with full
     traceback fields, `eval_set_id`, template fields, results, ledger
     counts and digests) and the member lists are equal;
   - no-write paths keep the contract: after an `allow_incomplete=True`
     merge, an unchanged call without it raises `ShardSetIncomplete`; after
     a `success` merge that kept shards, an unchanged call with
     `delete_shards=True` verifies and deletes; with the companion gone, a
     different selection raises `ShardSetError` and an equal one returns the
     header; each also through the CLI;
   - S3 cost: an unchanged pass over a large merged log reads only its
     suffix and `header.json` (a botocore hook counts `GetObject` ranges and
     bytes) and holds no more memory than a small one; a writing pass
     downloads it in bounded ranges;
   - overlap: two first merges started together yield one merged log and
     one `eval_id`, the other refused (local lock; S3 `IfNoneMatch`); a
     merge whose shard snapshot is older publishing after a newer one is
     refused (S3 `IfMatch`; locally blocked by the lock) and a re-run then
     merges cleanly; a stale lock file is reported;
   - consistent reads: a shard replaced between its central-directory read
     and a member read, including during sample copying after planning,
     restarts the pass from the listing (its new keys, status and identity
     are re-validated), and exhausted restarts fail the pass without
     writing. The replacement is tested both with the same member offsets
     (a CRC mismatch) and with different offsets (an `edit_score` rewrite
     of the shard, so the stale offset yields a decompression,
     local-header or short-read error); both restart. On `mock_s3`, a
     rewrite that shrinks the shard so that a planned member's offset lies
     past the new end makes the member read fail with `InvalidRange`
     (416); the pass restarts, re-reads the new central directory,
     re-validates the shard and merges it. A storage error that is not
     `InvalidRange` (an injected `AccessDenied` `ClientError`) fails the
     pass at once without a restart, and so does a shard member that
     passes its CRC but fails validation. `tests/util/test_async_zip.py`
     covers `is_torn_read` for each case;
   - `delete_shards`: removes the companion after a verified `success`
     publish; a verification failure leaves the shards; combined with
     `allow_incomplete` it is a `ValueError`; a companion with a
     `<k>/scans/` directory, a retained `<shard>.checkpoints/` or a log
     nested below a dot-directory of the companion is refused
     with nothing deleted; an object created between listing and deletion
     (a storage hook) is left, and the call raises with the merged log kept;
   - interrupted `delete_shards`, local and `mock_s3`: a storage hook fails
     the delete after shard A's objects and before B's; the call raises
     `ShardSetError` listing B's paths and the merged log is untouched; a
     following explicit merge and a following `eval_set()` startup refuse
     with "shards vanished" and leave the merged log byte-identical;
     re-running `delete_shards=True` deletes the rest and succeeds; a
     changed or new shard in the remnant makes the re-run refuse rather
     than delete; a hand-deleted `<k>/` and a hand-deleted current attempt
     are refused (vanished shard, attempt regression);
   - deletion order, local and `mock_s3`, with a `<k>/` holding two
     attempts and another holding `X.eval` beside `X-recovered.eval`: a
     recording hook shows every superseded attempt and buffer object
     deleted before any current attempt. A hook that fails one superseded
     attempt's delete makes the call raise before any current attempt is
     deleted, and a following merge finds every shard unchanged and writes
     nothing. A hook that fails one current attempt's delete after another
     current attempt's delete succeeded makes the call raise, and a
     following merge refuses as "shards vanished", never as an attempt
     regression. In both cases a re-run with `delete_shards=True` deletes
     the rest;
   - a merge that read the merged log before a retry-cleanup removal
     deleted it has its conditional publish refused (`WriteConflictError`),
     on `mock_s3` with a pause between the read and the publish;
   - trust: a metric registered only in a `task_file` is resolved through
     the fallback, with a warning naming the file (and the CLI notice); a missing
     metric fails without writing; a spy asserts no reader path
     (`read_eval_log`, `list_eval_logs`, `evals_df`) calls the merge;
   - cancellation mid-pass (after reads, during the build, during the S3
     upload) leaves the merged log and shards as they were and no temp or
     lock file behind; run with `--runtrio`.
   `tests/cli/test_log.py`: `merge-shards` on a merged log, a companion and
   a log directory; `--sample-id` and `--sample-count`; the usage error for
   a selection with a directory; `--json` shape, including a directory
   holding two companions (two objects, each with its own `log` and the
   directory as `source`, one of them refused with `error` set and the
   other merged) and a `LOG` that cannot be listed (one object, `log`
   null); a `-recovered` `LOG` reported as a failed item; the `task_file`
   notice; exit codes.
6. **Eval-set integration.** `tests/test_eval_set.py`: `log_samples_complete`
   on a `success` merged log is true when its `dataset.sample_ids` equals the
   eval set's selection (for each recorded form: ids, count, neither) and
   false for a different selection or changed epochs; startup over a
   complete shard set pairs only the merged log and runs nothing; over an
   incomplete set writes a `started` merged log that the set resumes
   (missing samples run once, unsharded); an `error` shard set is retried
   seeded from the merged log; a `started` merged log is not recovered
   (spy on `recover_eval_log`); after a successful retry with
   `retry_cleanup`, the merged log (`started` and `error` cases) and its
   companion are removed together even when the merged log has the newer
   mtime, and a second startup finds nothing to merge; the three-attempt
   case (merged log, older unsharded `success`, newer unsharded `error`)
   keeps the newer `error` as latest and removes the other two; a group
   without a merged log orders and cleans exactly as before; a companion
   holding scan results is left with a warning and does not change pairing;
   two passes of the three-attempt case with `M`'s removal refused (scan
   results in its companion) and, separately, failing after the merged log
   was deleted (part of the companion left): both passes keep `E` as
   latest, keep `S`, and never delete `E`; in the second case, within one
   `eval_set()` call (startup cleanup fails on the companion, the retried
   task fails again, the final sweep runs), the final sweep leaves the
   group alone and `S` survives, and the next call's startup rebuilds a
   merged log from the leftover, keeps `E` as latest and removes the
   rebuilt log again; after the scan results are moved away in the first
   case, the next pass removes `M` and its companion, then `S`; a viewer
   deletion of a merged log (the unchanged `/log-delete`) leaves the
   companion, and the next startup rebuilds the merged log (the documented
   limitation);
   with `retry_cleanup=False` everything stays; no shard
   header is read outside the merge (spy on `read_eval_log_headers`
   inputs), while an ordinary log nested in a shard's `scans/` directory is
   kept in the listing and has its header read like any other log, and
   marks no companion; a startup merge refusal stops `eval_set()` with
   `PrerequisiteError` before any task runs, asserted once per category
   (each with the companion path, the cause and the next step in the
   message, and the original exception as `__cause__`): a mismatched
   identifier, overlapping ids, a stray file, a chunked-shape sample, a
   vanished shard, an attempt regression, an ordinary `<name>.eval` in the
   way, a held local lock and a stale one, a lost S3 publish race on
   `mock_s3` (a second merge published between the pass's read and its
   publish), and a storage error from the listing;
   `selected_sample_ids` equals `slice_dataset`'s ids for `limit`,
   `sample_id` and unset-id datasets; a selection-mode worker does not merge;
   a companion holding only a stray `.eval` (no merged log, no attempt)
   stops `eval_set()` with `PrerequisiteError` naming the stray file before
   any task runs, and a companion whose first `<k>/` holds only `scans/`
   is matched to its task from the attempt in a later `<k>/`;
   an eval set over the whole dataset writes a merged log with `selection`
   `"ids"`, and `eval_retry` of it (left `started` by an incomplete shard
   set) raises `ValueError` naming `eval_set()` and runs no sample.
7. **Streaming recomputation.** `tests/log/test_shards.py`: peak memory
   (`tracemalloc`) of a merge over shards with large transcripts and small
   scores does not grow with transcript size; with large score metadata,
   growth matches the retained metric inputs and custom metrics receive
   them unchanged.
8. **Raw copy.** `tests/util/test_zipfile.py`: raw-copied members read back
   byte-identical through `zipfile` and `AsyncZipReader`, including ZIP64
   sizes and offsets and both compression methods in use;
   `tests/log/test_shards.py`: a merge with raw copy produces the same
   member contents and results as without; a changed shard member whose
   CRC equals the carried member's is not read from the shard.

No test needs a network, Docker or a model provider. Gated runs before each
PR: `--runtrio` for PRs 3–8. A manual check against a real S3
bucket for PR 4 (conditional multipart with `IfMatch`, which moto does not
enforce) is recommended and reported in the PR's "Slow tests" section.

## Implementation plan

Step 1 in eight PRs, of which PR 1 has landed. There is no viewer PR
(decision: Ransom, 2026-09-24).

| PR | Depends on | Can run in parallel with |
|---|---|---|
| 1 layout helpers (#530) | landed (#5541) | — |
| 2 field + `ts-mono` | none | 3, 4 |
| 3 shared walk | none (1 landed) | 2, 4 |
| 4 guard primitives | none | 2, 3 |
| 5 merge core, API, CLI | 2, 3, 4 | none |
| 6 eval-set integration | 5 | 7 |
| 7 streaming recomputation | 5 | 6 |
| 8 raw member copy | 5, 7 | 6 |

1. **Layout and naming helpers** (#530): landed as
   UKGovernmentBEIS/inspect_ai#5541. `src/inspect_ai/_util/log_layout.py`
   holds `log_basename`, `eval_checkpoints_dir`, `eval_shards_dir`,
   `eval_log_for_shards_dir` and `eval_log_name` ("Layout helpers"), with
   no behaviour change. The later PRs keep their numbers.
2. **The `EvalSpec.shards` field and its `ts-mono` landing.** Models,
   field, exports, `inspect-openapi.json`, the `ts-mono` PR regenerating
   `generated.ts`, gitlink bump per `land-ts-mono`. No behaviour change
   (nothing writes the field yet). Independent of 1. Files:
   `log/_log.py`, `log/__init__.py`, `_view/inspect-openapi.json`,
   `_view/ts-mono` (gitlink), `tests/log/test_eval_log.py`. No CHANGELOG
   entry (no user-visible change until PR 5).
3. **Shared walk.** `log/_shards/_walk.py` (`list_shard_set`,
   `attempt_sort_key`, `is_shard_path`) over the landed `list_dir`. Uses
   PR 1's helpers. Files: `log/_shards/__init__.py`, `log/_shards/_walk.py`,
   `tests/log/test_shards.py`. After this
   PR, ctl log-dir mode's step 4 can land; it adds `unlisted_dirs` to
   `_walk.py`.
4. **Guard primitives.** `AsyncFilesystem.write_file_conditional` (asyncio
   and Trio routes, pre-checks, abort, cooperative cancellation on Trio, a
   non-retrying client for the final call), `get_file_if_match`, the
   optional `condition` and `final_client` on `_s3_upload_fileobj_async` and
   `_s3_multipart_upload_async`, the `max_attempts` argument on the client
   builders, and the local lock helper (in
   `_util/file.py`, `acquire_exclusive_lock(path, info) -> context
   manager`). Independent of 1–3. Files: `_util/asyncfiles.py`,
   `_util/file.py`, `tests/util/test_asyncfiles.py`,
   `tests/util/test_file.py`.
5. **Merge core, public API and CLI.** `log/_shards/{_api,_plan,_write,
   _publish,_delete}.py` (`_plan.py` holds the member-name parser, the
   selection digest, attribution by id and the ledger checks), the
   `eval_retry` refusal for id- and count-selected merged logs (`_eval/eval.py`), exports and
   the reference section, `inspect log
   merge-shards`, docs (a "Sharding" section in `docs/parallelism.qmd`
   covering the layout, the launcher's job (disjoint `--sample-id` or
   `limit` selections, fixed per `<k>/`; no `SampleSource` tasks) and the harness notes from the
   parent, and the limitations: deletion is not safe against concurrent
   operations, `eval_retry` refuses a merged log merged with a selection
   (every one `eval_set()` writes), and a viewer delete of a merged log
   leaves its companion,
   whose shards the viewer lists again until the next eval set re-merges
   them), CHANGELOG entry. Depends on 2, 3,
   4. Files as listed plus `log/__init__.py`, `_cli/log.py`, `_eval/eval.py`,
   `_util/async_zip.py` and `_control/log_dir/consistency.py` (the shared
   `is_torn_read` predicate, "Consistent reads"),
   `tests/util/test_async_zip.py`,
   `docs/reference/inspect_ai.log.qmd`, `docs/parallelism.qmd`,
   `CHANGELOG.md`, `tests/log/test_shards.py`, `tests/cli/test_log.py`.
   Uses the landed `ZipEntry` CRC and `verify_crc=True` reads
   ("Consistent reads").
6. **Eval-set integration.** Startup merge, `selected_sample_ids`,
   `skip_shards`, completeness branch, no recovery of merged logs, cleanup
   ordering and companion deletion, `docs/eval-sets.qmd` note (including
   that `eval_retry` refuses an eval set's merged log), CHANGELOG
   entry. Depends on 5. Coordinate with #5396. Files:
   `_eval/evalset.py`, `_eval/eval_set_manifest.py`, `docs/eval-sets.qmd`,
   `CHANGELOG.md`, `tests/test_eval_set.py`.
7. **Streaming recomputation.** Include-only score extraction and the
   memory tests. Depends on 5. Files: `log/_shards/_write.py`,
   `log/_recorders/eval.py` (expose the builder if needed),
   `tests/log/test_shards.py`.
8. **Raw compressed-member copy.** The raw member writer and its use in the
   merge, with the CRC shortcut. Depends on 5; after 7 so the two
   measurements are separable. Files:
   `_util/zipfile.py`, `log/_shards/_write.py`, `tests/util/test_zipfile.py`,
   `tests/log/test_shards.py`.

PRs 5 and 6 each carry a CHANGELOG line; 1–4, 7 and 8 are internal or
performance-only. Each PR reports its
`--runtrio` run under "Slow tests".

## Open questions

None. Resolved by Ransom on 2026-09-24: Step 1 makes no viewer changes and
keeps deletion simple ("Deleting shards"), and a refused startup merge
stops `eval_set()` with `PrerequisiteError` in all cases ("Eval-set
integration"). Resolved by Ransom on 2026-09-29: the merged header carries
no per-sample data beyond `dataset.sample_ids` (a count and digest per
shard, attribution by id, the selection in the ordinary header fields).
This document decides the one case that left open: a shard with no usable
selection (a `SampleSource` task, or no `sample_ids`) is refused, not
merged by a fallback ("Validation").

Stale local locks are report-only, as the parent's test list requires; a
same-host dead-pid check can be added if crashed merges turn out to happen.

## Not this design

- A viewer delete that also removes a merged log's `<name>.shards/`
  companion, with per-object authorization (removed from Step 1 by
  Ransom, 2026-09-24); until then the viewer deletes only the log and the
  next `eval_set()` startup rebuilds it.
- Deletion that is safe against concurrent operations or resumable after a
  crash, if interrupted or concurrent deletions turn out to matter in
  practice.

- An exact-key sample selection for `eval_retry` (and `--sample-id`
  generally): the current selector matches normalised patterns, which is
  why `eval_retry` refuses id- and count-selected merged logs
  ("`eval_retry` of a merged log").
- Chunked-shape samples in shards: refused in Step 1. Supporting them means
  copying every member under the sample's prefix and extracting scores from
  the shell member, once the recorder writes the shape.
- S3 server-side composition (`UploadPartCopy`) for the merged log; the
  primitive UKGovernmentBEIS/inspect_ai#5391 designs for flushes is the
  natural base.
- An `evals_df` column for `eval.shards` (the parent's "filter on the
  provenance field" needs one) and a helper that selects merged logs.
- Merging or relocating per-shard scan results (`<k>/scans/`) and
  retained checkpoints into the merged log's locations, so that scanner
  resume reuses worker rows and deletion can proceed. Step 1 keeps them in
  place and refuses deletion ("Deleting shards").
- `seed_from_prior_log` keeps unknown zip members (`_prune_prior_members`
  prunes a fixed list), so any future extra member in a log would be copied
  into retries seeded from it.
- `_replace_eval_header_in_place` edits local headers non-atomically; a
  viewer edit concurrent with any writer of the same local log can be lost,
  merged or not.
