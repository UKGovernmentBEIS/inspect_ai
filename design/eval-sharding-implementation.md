# Eval sharding, Step 1: API and implementation plan

Status: proposed, 2026-09-24. Issue:
https://github.com/meridianlabs-ai/inspect_ai/issues/529 (part of #509).
Author: agent (Claude), reviewed by Codex; see the PR. Verified against
`43ebaebc38`.

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
it: the layout helpers (meridianlabs-ai/inspect_ai#530) and ctl log-dir mode
(meridianlabs-ai/inspect_ai#528, whose later steps read the merged log's
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
- A listing exclusion for shards (deferred by the parent, "Listing").
- S3 server-side composition with `UploadPartCopy`; the parent orders it
  after raw member copy, "when measured merges of large logs justify it".
- Chunked-shape samples (see "Validation" and "Not this design").
- Distributed merge ownership and a remote lock protocol (parent,
  "Overlapping merges").

## Current behaviour

Only what the plan depends on. Verified by reading the code at `43ebaebc38`
and, where noted, by running it.

**Layout helpers.** `log_basename` (strip `.eval`, then `-recovered`) and
`eval_checkpoints_dir` live in
`src/inspect_ai/util/_checkpoint/_layout/eval_checkpoints_dir.py:23,40`;
the checkpoint package (`hydrate.py:78`, `staging_dir.py:29`) is their only
caller. The log file name is built by `FileRecorder._log_file_key`
(`src/inspect_ai/log/_recorders/file.py:157`) from an `EvalSpec`:
`{created}_` + `INSPECT_EVAL_LOG_FILE_PATTERN` (default `{task}_{id}`), with
`{model}` substituted. #530 moves the first two to a neutral module, adds
`eval_shards_dir` and its reverse, and factors the name builder; its
worktree has no commits yet.

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

**Reading logs.** `AsyncZipReader` (`src/inspect_ai/_util/async_zip.py:310`)
reads the central directory with a suffix read, records the object's ETag
(`etag`, `:351`), and streams a member decompressed (`open_member`) or raw
(`open_member_raw`, `:373`). `ZipEntry`
(`src/inspect_ai/_util/zip_common.py:18`) holds name, method, sizes and
local-header offset, but no CRC-32; ctl log-dir mode adds the CRC and an
opt-in CRC check on member reads (its step 2, #528). A running log has no
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

**Viewer delete.** `/log-delete/{log}` (`fastapi_server.py:228`) calls
`_validate_delete` for the requested path only (`:177`), maps it
(`_map_file`, `:162`) and calls `delete_log`
(`src/inspect_ai/_view/common.py:409`), a bare `fs.rm` that sees neither the
request nor the policy; it deletes a corrupt `.eval` without reading it
(HTTP 200, the round-1 reviewer's probe). The policy protocol is per file
(`AccessPolicy.can_delete(request, file)`, `:90`). A separate
`FileMappingPolicy` maps request paths to storage paths with arbitrary
`map` and `unmap` (`:100`); listing endpoints `unmap` each storage object
(`:167`, `:382`).

**Other outputs beside a worker's log.** A worker's default scan directory
is under its own log directory, `<k>/scans/scan_id=...`, while an eval
set over the parent looks under `<dir>/scans/` (`_scan_dir`,
`src/inspect_ai/_eval/task/scan.py:829`). Checkpoints live beside each log
as `<log>.checkpoints/` (`eval_checkpoints_dir`), deleted on success by
default and kept with `retention="retain"`
(`src/inspect_ai/util/_checkpoint/config.py:172,233`).

**Work in flight that overlaps this plan.** #530 (layout helpers, not
started), #528 (ctl log-dir mode steps 1–2, including
`AsyncFilesystem.list_dir` and the `ZipEntry` CRC, not started),
UKGovernmentBEIS/inspect_ai#5396 (open: retry cleanup also removes older
`started` logs and their buffers; touches `latest_completed_task_eval_logs`),
UKGovernmentBEIS/inspect_ai#5401 (draft: viewer scoped authorization;
touches `fastapi_server.py` and `common.py`) and
UKGovernmentBEIS/inspect_ai#5391 (design: S3 flushes by server-side
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
  other with #530's helpers. Plain paths, `file://` and `s3://` (and other
  fsspec URLs, without the overlap guard; see "Overlap guards"). A `.eval`
  argument is the output path; a companion argument writes `<name>.eval`.
- `sample_ids` / `sample_count`: the intended selection, mutually exclusive
  (`ValueError` if both). Ids are compared as `str(id)`, the readers' sample
  key. When neither is given, the selection recorded in the merged log's
  field is used; when that is absent too, the set is complete only if the
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
  every worker has exited and nothing else writes into the companion (the
  launcher's lifecycle, parent "Ownership"); the merge cannot tell a
  finished shard from a paused one. Combined with `allow_incomplete=True` it
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
does, and records which source it used in the field (`metrics_source`,
below). Parent "Trust": the merge runs only as a trusted step; no reader
path calls it.

#### CLI

`inspect log merge-shards`, in `src/inspect_ai/_cli/log.py` beside
`recover`:

```
inspect log merge-shards LOG [LOG ...]
    [--sample-id IDS | --sample-count N]
    [--allow-incomplete] [--delete-shards] [--json]
```

- Each `LOG` is a merged log path, a companion directory, or a log
  directory. A log directory merges every companion found in it (the same
  discovery as the `eval_set()` startup merge, "Eval-set integration"); the
  selection options are then refused with a usage error, because one
  selection cannot apply to several tasks.
- `--sample-id` takes comma-separated ids (`parse_sample_id`,
  `src/inspect_ai/_util/samples.py:17`), concrete ids only; `--sample-count`
  an integer.
- Human output: one line per merged log with its status, the number of new
  samples and shards, and, when incomplete, the missing count and the
  running and failed shard names. When the `task_file` fallback imported
  code, a notice on stderr names the file (parent decision, 2026-09-21: a
  visible notice, no opt-in).
- `--json`: one object per `LOG` with `log`, `status`, `written`, `shards`,
  `samples`, `missing` (ids or null), `running`, `failed`,
  `shards_deleted`, and `error` (message) for a failed item.
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
class EvalShardSampleKey(BaseModel):
    """One `(id, epoch)` record merged from a shard."""

    id: str | int
    epoch: int


class EvalShardEntry(BaseModel):
    """Ledger entry for one shard, as of the merge that last read it."""

    shard: str
    """Name of the shard's directory (`<k>`) in the companion."""

    log: str
    """File name of the shard's current attempt (the newest `.eval` in `<k>/`)."""

    attempts: int
    """Number of `.eval` files in `<k>/` (superseded attempts plus the current one)."""

    eval_id: str
    """`eval_id` of the current attempt."""

    task_id: str
    """`task_id` of the current attempt (each shard has its own)."""

    eval_set_id: str | None = Field(default=None)
    """`eval_set_id` of the current attempt."""

    status: EvalStatus
    """Status of the current attempt when it was read."""

    error: EvalError | None = Field(default=None)
    """Error of the current attempt when its status is `error` or `cancelled`."""

    sample_keys: list[EvalShardSampleKey]
    """The `(id, epoch)` records merged from this shard, exactly as held."""

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

    location: str
    """Companion directory the last merge read (informational; readers derive it from the name)."""

    sample_ids: list[str] | list[int] | list[str | int] | None = Field(default=None)
    """Intended selection as ids, when the last merge had one."""

    sample_count: int | None = Field(default=None)
    """Intended selection as a count, when the last merge had one."""

    template: str
    """Name of the shard whose header supplied the merged header's task fields."""

    merged_at: UtcDatetimeStr
    """Time of the last merge that wrote this log."""

    metrics_source: Literal["registry", "task_file"]
    """Whether metrics were resolved from registered code or by importing the header's `task_file`."""

    ledger: list[EvalShardEntry]
    """One entry per shard with a current attempt, in shard order."""
```

`EvalSpec` gains `shards: EvalShards | None = Field(default=None)` with the
docstring "Shards merged into this log (merged logs only)." Absent on every
unsharded log and on shards; its presence is how `eval_set()`, the viewer's
delete endpoint and ctl log-dir mode recognise a merged log.

Choices the parent left open:

- **The ledger holds everything a later pass needs from a shard it does not
  reopen.** A pass reopens only changed and new shards, so every
  per-shard input to the merged header must be in the ledger: the exact
  keys (to attribute merged samples to shards, detect conflicts against
  unchanged shards, and decide completeness), the full `EvalError` (the
  merged log's `error` is the first failing shard's, and `EvalError`
  requires `traceback` and `traceback_ansi`, `src/inspect_ai/_util/error.py:12`),
  the statistics (`stats` is recomputed from the entries, so replacing one
  shard's attempt replaces exactly its contribution), `eval_set_id`, and
  which shard supplied the task fields (`template`, "Building the merged
  log"). With this, an incremental pass and a fresh merge of the same
  companion compute the same header. The parent listed a per-shard sample
  count; the count is `len(sample_keys)`.
- **Exact keys, not ids times epochs.** A shard can hold fewer records than
  its ids times epochs: a running shard, a failed one, and a gracefully
  drained `success` shard (`logged_samples`, `evalset.py:1868`). Expanding
  ids would invent records. ctl log-dir mode's step 6 uses the same keys to
  take an unchanged shard's rows from the merged log's `summaries.json`.
  Size: an unsharded header already lists every id in
  `dataset.sample_ids`; the ledger adds one small object per `(id, epoch)`,
  so a merged header is larger by a factor of about the epoch count, the
  same order of growth.
- **Two selection fields**, not one `list | int` union, so the generated
  TypeScript type stays two plain optional fields and ctl reads "id list
  times epochs, or count times epochs" without type tests.
- **`size`, `etag`, `mtime`** are what `FileInfo` carries
  (`src/inspect_ai/_util/file.py:195`); change detection compares ETags when
  both sides have one and `(size, mtime)` otherwise.
- **Unknown-field behaviour**: nothing new. Old Inspect versions drop the
  field on read (no `extra` policy), and readers that do not know it treat
  a merged log as an ordinary log, as the parent requires. An old version
  that *rewrites* a merged log (for example a viewer edit) drops the field;
  the result is an ordinary log, which the merge then refuses to overwrite
  (step 3). That is the support boundary for cross-version editing.

Schema impact: three new component schemas (`EvalShards`,
`EvalShardEntry`, `EvalShardSampleKey`) and one optional property on
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
   `.eval` path) and `<name>.shards/`. Open one `AsyncFilesystem` scope for
   the whole pass; every read below shares it.
2. **Acquire the local guard** when the output is local ("Overlap guards").
   S3 has nothing to acquire; its guard is at publication.
3. **Read the merged log's header and central directory**, if it exists,
   through one `AsyncZipReader` (range reads; S3 costs the suffix read and
   the `header.json` member, whatever the log's size). Keep the reader's
   ETag `E0` for the conditional publish. If the log exists and
   `eval.shards` is absent, raise `ShardSetError` ("`<name>.eval` is an
   ordinary log; refusing to overwrite it"): a merge never replaces a log
   it did not write.
4. **List the shard set** with `list_shard_set` ("Code shared ...") into
   shards `<k>` with their attempt files in attempt order, stray files and
   ancillary entries. Stray files (an `.eval` directly in `<name>.shards/`,
   or a `.json` log in any `<k>/`) raise `ShardSetError`. Ancillary entries
   (scan results, checkpoint directories) do not affect merging; they block
   deletion ("Deleting shards").
5. **Classify each shard.** For each `<k>`, the current attempt is the last
   file in attempt order. It is *unchanged* when the ledger has an entry
   for `<k>` with the same `log` name and equal ETag (or equal `size` and
   `mtime` where either side has no ETag); otherwise *changed* or *new*. A
   ledger entry with no `<k>` in the listing is *vanished*.
6. **Read changed and new shards**, bounded (16 concurrent), each through
   one `AsyncZipReader`: the central directory, the header (synthesised from
   `_journal/start.json` for a running attempt), the summaries (journal
   summaries for a running attempt), with ctl log-dir mode's opt-in CRC
   check on every member read ("Consistent reads"). If the template shard
   ("Building the merged log") is unchanged but is not the recorded
   `template`, read its header too. The ledger records the reader's ETag
   (`AsyncZipReader.etag`), which may differ from the listing's when the
   object was replaced in between; the next pass then sees a changed ETag
   and re-reads. A key is *held* by an attempt when its summaries list it
   and its central directory has the sample member.
7. **Validate** ("Validation"). Refuse with `ShardSetError` on any failure.
8. **Plan** the sample set ("The sample set"), the status ("Status") and
   the header ("Building the merged log"), from the ledger entries of
   unchanged shards and the attempts read in step 6. A call that read no
   shard plans from the ledger alone.
9. **Enforce the status.** An incomplete status without `allow_incomplete`
   raises `ShardSetIncomplete`, before any write, whether or not anything
   changed.
10. **Decide whether to write.** With the companion present: write when
    there is no merged log, or any shard is changed, new or vanished, or the
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
- **One owner per id.** Each id is held by at most one shard's current
  attempt, where an unchanged shard's keys are its ledger `sample_keys`.
  A shard selects whole samples, so two shards holding records of one id,
  even different epochs of it, both selected that id, and their keys would
  collide as they progress. This is stricter than the parent's disjoint
  `(id, epoch)` sets and makes ownership unambiguous.
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
current attempt and any `<k>` record the new attempt lacks is dropped; when
`<k>/` disappears, its records and ledger entry are dropped. Within one
attempt a duplicated key resolves as the readers resolve it (last summary
row and last member of the name win). For an unchanged shard the keys are
its ledger `sample_keys`, which are exactly what the pass that read it
held.

Reasons: the result is a function of the companion's current attempts, so
an incremental merge and a fresh merge of the same companion hold the same
records (the parent's "idempotent and deterministic"); it is the rule ctl
log-dir mode already uses ("Older files in the same `<k>/` are superseded
... otherwise ignored"), so the two never disagree about which records a
shard contributes; and it loses nothing in the normal paths, because a
seeded retry of a shard (`design/retry-seeded-attempt-log.md`) holds its
prior samples from its first flush and a plain re-run re-runs them. The
parent's "newest wins" is this rule applied per shard.

Consequences, documented in the API docstring:

- Deleting one `<k>/` removes its records at the next merge. Deleting the
  whole companion leaves the merged log as it is (step 10).
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
  equal the selection's ids times epochs `1..E` exactly (with ids: every
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
and so on). When the template shard equals the recorded `template` and its
attempt is unchanged, these fields are carried from the merged header,
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
| `eval.dataset.sample_ids` | the selection ids when given as ids, else the sorted distinct held ids |
| `eval.config.sample_id`, `eval.config.limit` | the selection ids and `None` when given as ids; otherwise both `None` |
| `eval.shards` | the new field: ledger entries for every current attempt, `template` the template shard's name, `merged_at` now, `metrics_source` from "Metric recomputation" |
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
source (summaries are lossy, parent "Constraints"). `metrics_source` is
`"task_file"` when `resolve_scorers_info` imported the header's `task_file`
(detected by checking the registry for each metric name before the call),
else `"registry"`. A metric that neither source provides raises, as
`metric_create` does today, and nothing is written (parent: "fails rather
than store metrics from a lossy input").

Memory: the current sample plus every sample's `SampleScore`s, as the
parent's "Scale" accepts. The baseline parses each sample whole, so peak
memory follows the largest sample; "Scale items" bounds it.

#### Consistent reads

A running shard's object is replaced on every flush, so a member range read
after the central directory can land in a newer object. Every member read
of a shard uses the CRC check ctl log-dir mode adds (#528, its step 2). A
mismatch means the shard changed after it was planned: the pass discards
its plan and temp output and restarts from step 4 (a fresh listing, so the
shard's keys, status and identity are re-read and re-validated), at most
three times, then fails with the storage error and writes nothing. The
merged log itself is read from a local copy pinned to `E0` (S3) or under the
local lock, so it needs no re-reads.

#### Deleting shards

Only when `delete_shards=True` and the merged log's status is `success`:

1. Verify the merged log: open it (S3: checking the reader's ETag equals
   the publish response's ETag, or `E0` when step 11 did not write), check
   that its central directory has a sample member for every planned key and
   that its `eval.shards.ledger` matches the plan.
2. Delete the companion through `remove_shards_dir` (below).

A failed verification or a refusal raises `ShardSetError` after
publication, with the shards left in place.

`remove_shards_dir(log: str, *, include_log: bool = False,
authorize: Callable[[str], Awaitable[None]] | None = None) -> None` in
`_delete.py` is the one companion-deletion routine, used by
`delete_shards`, retry cleanup and (with `authorize`) the viewer:

1. List every object under the companion (recursive).
2. Refuse (`ShardSetError`, nothing deleted) when any `<k>/` holds
   ancillary output, meaning anything other than its `.eval` attempt files
   and objects under `<k>/.buffer/`: scan results (a worker's default scan
   directory is `<k>/scans/scan_id=...`, from `_scan_dir` on its log
   directory, `src/inspect_ai/_eval/task/scan.py:829`) and checkpoint
   directories (`<shard>.checkpoints/` beside each shard,
   `eval_checkpoints_dir`, including ones kept with `retention="retain"`,
   `src/inspect_ai/util/_checkpoint/config.py:172`). Step 1 neither merges
   nor relocates them, so deleting them would lose data the merged log
   does not hold.
3. When `authorize` is given, call it for every listed object before
   deleting any (the viewer's per-object policy check).
4. Delete exactly the listed objects (S3 batch deletes; locally file by
   file), never a recursive delete of the prefix, then list again. If
   anything is left (an object created after step 1), raise
   `ShardSetError` naming it and keep the merged log; otherwise remove the
   now-empty local directories and, with `include_log`, the merged log.

The order, companion before log, matters: a crash between the two leaves a
self-contained merged log, whereas the reverse would leave shards that the
next `eval_set()` startup re-merges into a resurrected log.

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
`_file.py:1118`). The lock does not cover a viewer edit of the merged log
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
  `WriteConflictError`; the multipart upload is aborted.
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
2. `list_eval_logs(log_dir)` once. Every listed file whose path relative to
   `log_dir` has a component ending in `.shards` marks a companion, the
   path up to the first such component (`is_shard_path`, shared helper);
   collect the distinct companions.
3. For each companion (4 at a time, one `AsyncFilesystem` scope), read one
   header (the merged log's, else the first shard's current attempt),
   compute its identifier and find the resolved task with it. A companion
   matching no task is left alone with a warning, like any other log that
   belongs to no task in the set.
4. Merge it with `allow_incomplete=True` and the selection
   `selected_sample_ids(task.task.dataset, limit, sample_id, task.task.name,
   task_names)`, a new sibling of `samples_selected` in
   `eval_set_manifest.py` that returns the ids `slice_dataset` would select
   (same unset-id rule). The eval set's selection is the intended selection,
   so an eval set run over a sharded subset without the subset's
   `sample_id` treats the rest of the dataset as missing and runs it, which
   is what an eval set means.
5. `ShardSetError` or `WriteConflictError` aborts `eval_set()` with a
   `PrerequisiteError` naming the companion (see "Open questions");
   `ShardSetIncomplete` cannot occur (`allow_incomplete=True`).
6. If any merge wrote, list again; otherwise reuse the listing.

**Shard skip before header reads.** `list_all_eval_logs` gains
`skip_shards: bool = False`, which drops `is_shard_path(log_dir, name)`
files before `read_eval_log_headers`. Both eval-set call sites (startup and
`cleanup_older_eval_logs`) pass `True`; `inspect_flow`'s callers keep the
default. The startup path in step 2 applies the same filter to the listing
it already holds.

**Completeness.** `log_samples_complete` gains a branch for a log with
`eval.shards`: complete when `status == "success"` (already required by the
caller), epochs are unchanged (the existing `epochs_changed` check), and
every planned key (each `selected_sample_ids` id with every epoch) is in
the union of the ledger's `sample_keys`. The count comparison is not used
for such logs. After a successful startup merge this agrees with the merged
status; it matters when the startup merge was skipped (no matching task) or
when an older merged log with a different selection is present.

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
  is superseded by it. Logs in `U` other than the latest are removed as
  today (non-`started` only).
- **Otherwise** the group is ordered and cleaned exactly as today; a
  removed non-latest merged log goes through `remove_shards_dir(...,
  include_log=True)` instead of `fs.rm`.
- A `remove_shards_dir` refusal (ancillary output in the companion,
  "Deleting shards") logs a warning and leaves that merged log and its
  companion in place; since it is never the latest in the first case,
  pairing is unaffected.

So the ordering among unsharded attempts never changes. The case that rules
out a sort key promoting unsharded successes: a merged log `M`, an older
unsharded `success` `S`, and a newer unsharded `error` `E` holding more
samples (for example after the epochs were raised). Today's order over `U`
makes `E` latest; cleanup removes `S` and `M` with its companion.

UKGovernmentBEIS/inspect_ai#5396 edits the same function (it also removes
older `started` unsharded logs and their buffers). This design does not
depend on it; whichever lands second rebases onto the other and keeps both
rules.

### Viewer delete authorization

`/log-delete/{log}` (`fastapi_server.py:228`):

1. `_validate_delete(request, file)` and `mapped = _map_file(request,
   file)`, as today.
2. Try to read the header of `mapped`. If it cannot be read or parsed (a
   corrupt file, an unsupported format version, a non-`.eval` log), or
   `eval.shards` is absent, delete `mapped` alone, exactly as today: the
   endpoint deletes a corrupt log today (the round-1 reviewer's probe: HTTP
   200) and keeps doing so. Provenance that cannot be established causes no
   cascade. A companion beside an ordinary log is not the log's, and the
   viewer does not delete it.
3. Otherwise call `remove_shards_dir(mapped, include_log=True,
   authorize=...)`. The `authorize` callback receives each actual storage
   object, computes its request path with `_unmap_file(request, obj)` (the
   mapping policy's own `unmap`, as the listing endpoints already use,
   `fastapi_server.py:167,382`), checks that `_map_file` of that path gives
   back the same object (fail closed with 403 when it does not, or when
   `unmap` raises), and calls `_validate_delete` on the request path. Checks
   run 16 at a time. Any denial is a 403 for the whole request, raised
   before anything is deleted.
4. `remove_shards_dir` deletes exactly the authorized objects, re-lists, and
   deletes the canonical log only when the companion is empty. An object
   that appeared after authorization is not deleted: the endpoint returns
   409 with a message that the delete must be retried (the retry authorizes
   the new object), and the canonical log stays. Ancillary output in the
   companion is also a 409, naming the directories, with nothing deleted.

The endpoint keeps the request and the policy; `common.delete_log` is
unchanged and remains the single-file path. With `OnlyDirAccessPolicy`
every companion object is under the log's directory, so each check is a
prefix test; a hosted policy pays one call per object, which is the price
of not deleting what it denies. The viewer client is unchanged (same
endpoint; 403 and 409 surface as delete errors).
UKGovernmentBEIS/inspect_ai#5401 reworks the policy layer; this change is
written against whichever policy interface is on `main` when it lands.

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
  entry with the new offset, ZIP64 when needed. Needs the `ZipEntry` CRC
  (#528 or PR 5). Removes the recompress of every sample; the decompress for
  score extraction remains. With CRCs available, a changed shard's member
  whose CRC equals the carried member's is kept from the merged log without
  reading the shard.

### Code shared with ctl log-dir mode

| Piece | Owner PR | Merge uses it for | ctl log-dir mode uses it for |
|---|---|---|---|
| `log_basename`, `eval_shards_dir`, reverse derivation, the name builder | #530 | the `<name>.eval` / `<name>.shards/` pair, `<name>` minting by launchers | mapping `X.shards/` to its merged log (its "Logical tasks") |
| `AsyncFilesystem.list_dir(base) -> DirListing(files: list[FileInfo], dirs: list[str])` | #528 (its step 2); PR 3 below if #528 has not landed | listing `<name>.shards/` and each `<k>/` | the delimited walk |
| `ZipEntry` CRC-32 and the opt-in CRC check | #528 (its step 2); PR 5 below if #528 has not landed | consistent shard reads; raw copy | consistent member reads |
| `list_shard_set`, `attempt_sort_key`, `is_shard_path` (`src/inspect_ai/log/_shards/_walk.py`) | PR 3 below | steps 4–5; the eval-set skip and companion discovery | its step 4 (shard aggregation) calls these instead of re-implementing the rules |
| `EvalShards`, `EvalShardEntry`, `EvalShardSampleKey` | PR 2 below | writing the field | its step 6 (totals from the selection, cold start from the ledger's exact keys) |

`DirListing.dirs` entries are full URIs ending in `/`, as `iter_dirs`
yields today (`asyncfiles.py:952`). `list_dir` does not follow local
directory symlinks.

The shard-set rules, one implementation for both consumers:

- `list_shard_set(fs, shards_dir) -> ShardSetListing(shards:
  list[ShardDir], stray: list[StrayFile])`, with `ShardDir(name: str, dir:
  str, attempts: list[FileInfo], has_buffer: bool, ancillary: list[str])`
  and `current` the last attempt or `None`. It lists `<name>.shards/` once
  with `list_dir`, then each `<k>/` (32 at a time). In `<k>/`: `.eval`
  files are attempts, a `.buffer/` prefix sets `has_buffer`, and every other
  file or directory (for example `scans/` or `<shard>.checkpoints/`) is
  recorded in `ancillary` and not descended into. A
  `<k>` directory whose name starts with `.` is not a shard. `.eval` files
  directly in `<name>.shards/`, and `.json` logs in any `<k>/`, are
  `stray` with a reason. The merge refuses stray files; ctl reports them
  (its `unreadable` list is the natural place; that choice is ctl's).
- `attempt_sort_key(info)`: the `{created}` timestamp prefix of the file
  name (matched with `_timestamp_prefix_re`, `_file.py:1163`), parsed as a
  datetime rather than compared as text; then a `-recovered` file after
  the file it was recovered from; then mtime. Names without a timestamp
  sort by mtime alone. This is ctl's "Attempt order", and matches the
  parent's "newest by the shard's `created` time", since the recorder names
  files from `eval.created`. It is not mtime-first, as `eval_set()` orders
  retries, because a running older attempt's mtime moves on every flush.
- `is_shard_path(root, path)`: true when `path`, relative to `root`, has a
  directory component ending in `.shards`. Relative to the listed root, so
  a log directory that is itself a `<k>/` (a worker's view) is not a shard
  of itself.

ctl log-dir mode's step 4 depends on PR 3; its step 6 on PR 2. Neither
depends on the merge.

## Alternatives considered

- **Key attribution outside the header.** A `shards.json` zip member in the
  merged log mapping keys to shards keeps the header small. Rejected: a new
  stored member that seeded retries would copy into unsharded logs unless
  `_prune_prior_members` learned it (`eval.py:1522` keeps unknown
  members), and ctl would need a second read for its cold start. The header
  already carries `dataset.sample_ids`; exact keys add a factor of about the
  epoch count.
- **Reopen unchanged shards instead of storing their stats and errors.**
  Keeps the ledger small, but every pass would read one header per shard,
  which is exactly the cost the incremental design avoids at 300 shards.
- **Id-level ledger (`sample_ids`) expanded by epochs.** Smaller, but it
  invents records for running, failed and drained shards and makes fresh
  and incremental merges disagree (round 1 of this document).
- **Merge scan results and checkpoints into the merged log's locations.**
  Would let deletion proceed, but it is a new relocation feature with its
  own compatibility rules (Scout's scan directory layout, checkpoint
  retention); Step 1 refuses deletion instead ("Deleting shards").
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
- **Warn and continue when the startup merge refuses a companion.** Lets an
  eval set run, but then it pairs against a stale merged log or re-runs the
  task from scratch while the shards sit unmerged, which is the silent
  coercion AGENTS.md rules out. See "Open questions".

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
  `.json` logs and chunked-shape samples are not supported as shards.
- **Generated types.** `inspect-openapi.json` and `ts-mono`'s
  `generated.ts` gain `EvalShards`, `EvalShardEntry`, `EvalShardSampleKey`
  and `EvalSpec.shards?`; landed through `land-ts-mono`. The viewer does
  not read the field in Step 1. `inspect_scout` gets the types from
  `@tsmono/inspect-common` when its `ts-mono` version moves.
- **Public Python API.** New: `merge_eval_log_shards`,
  `merge_eval_log_shards_async`, `ShardMergeResult`, `ShardSetError`,
  `ShardSetIncomplete`, `EvalShards`, `EvalShardEntry`,
  `EvalShardSampleKey` in `inspect_ai.log`,
  listed in a "Sharding" section of `docs/reference/inspect_ai.log.qmd`.
  `list_all_eval_logs` (internal, but imported by `inspect_flow`) gains a
  keyword argument whose default keeps its behaviour.
- **CLI.** New `inspect log merge-shards`. No existing command changes.
- **Eval sets.** Behaviour changes only for task groups that contain a
  merged log: startup merges, shards skipped before header reads, merged
  logs classified by the ledger's exact keys, not recovered, and, once an
  unsharded retry succeeds, never chosen as latest and removed with their
  companions (including a `started` merged log) unless the companion holds
  scan results or checkpoints. Ordering among unsharded attempts is
  unchanged.
- **Scan results and checkpoints written by workers** stay in their
  `<k>/`; Step 1 neither merges nor relocates them, an eval set with
  scanners over the parent directory scans the merged log's samples again
  under `<dir>/scans/`, and every deletion path refuses a companion that
  holds them.
- **Viewer.** Deleting a merged log also deletes its companion: 403 if the
  access policy denies any companion object (after the mapping policy's
  `unmap`), 409 if objects appeared during the delete or the companion holds
  scan results or checkpoints. Deleting any other log, including one whose
  header cannot be read, is unchanged.
- **`AsyncFilesystem`.** New `list_dir` (if not already added by #528),
  `get_file_if_match` and `write_file_conditional`, and a second,
  non-retrying S3 client used only by the conditional final call; existing
  methods and clients unchanged.

## Security

- **Untrusted inputs.** Shard headers, summaries, sample members, file and
  directory names in the companion, and the merged log itself are written
  by processes that may run agent code, or by anyone with write access to
  the bucket. They go through the existing pydantic models and zip readers.
  Paths are derived from listed names by fixed rules (`<name>` from the
  basename, `<k>` from listed prefixes, member names from keys); the
  field's `location` and ledger file names are never used to locate
  anything. Sample member names are rebuilt from `(id, epoch)` with the
  existing `_sample_filename` rather than copied from a source central
  directory, so a crafted member name cannot place data under another key.
- **Membership by location.** Strict validation (identifier, scorers,
  metrics, dataset size, epochs, reducer, format version, one owner per id,
  selection) refuses a stray or
  hostile file rather than skipping it; a merge never overwrites a
  `<name>.eval` without the field.
- **Code execution.** Recomputation may import the header's `task_file`
  (the existing `resolve_scorers_info` fallback). The merge runs only in
  trusted steps (API, CLI, `eval_set()` startup), records the source used,
  and the CLI prints a notice. No reader path (viewer server,
  `read_eval_log*`, dataframes, ctl log-dir mode) calls it.
- **Viewer delete scope.** The cascade authorizes every actual companion
  object through the request's access policy, at the request path the
  mapping policy's own `unmap` gives it (failing closed when the mapping
  does not round-trip), before deleting anything, and then deletes only the
  authorized objects; an object that appears afterwards is not deleted (see
  "Viewer delete authorization"). The header read that decides whether to
  cascade is authorized by the same `_validate_delete` check on the
  requested file, and an unreadable header causes no cascade.
- **Destructive cleanup.** No deletion path (viewer, `delete_shards`, retry
  cleanup) performs a recursive delete of the companion prefix; all go
  through the exact-object routine, which refuses when scan results or
  checkpoints are present.
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

1. **#530, layout helpers.** Its own issue's list: both derivations for
   local paths, `file://` and `s3://`; `-recovered`; checkpoint results
   unchanged; the factored name builder equals the recorder's name for the
   default and a custom pattern with `{model}`.
2. **The field.** `tests/log/test_eval_log.py`: round trip of a header
   with `shards` (both selection forms, entries with and without
   `etag`/`error`, with usage and keys); a header without it serialises with
   no `shards` key; a
   header carrying an unknown extra key still validates (the property old
   versions rely on). `check-schema-and-types` in CI proves the regenerated
   schema and types match.
3. **Shared walk.** `tests/util/test_asyncfiles.py` (if this PR adds
   `list_dir`): files and prefixes from one delimited listing on `mock_s3`,
   including more than 1,000 keys (pagination); local listing does not
   follow a directory symlink loop. `tests/log/test_shards.py`: a companion
   with `<k>/` directories holding one attempt, an original plus its
   `-recovered` copy (recovered current), two attempts with the older one
   touched last (the file-name timestamp wins over mtime), an empty `<k>/`,
   a `.buffer/` prefix, a `scans/` directory and a `<shard>.checkpoints/`
   directory (both `ancillary`), a stray `.eval` in the companion root and a
   `.json` log in a `<k>/` (both stray); `is_shard_path` relative to the root,
   including a root that is itself a `<k>/`, and a user directory named
   `shards`.
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
     is recorded with exactly that key, and after another shard changes the
     next pass still holds `(x, 1)` only and stays `started`; two shards
     holding different epochs of one id are refused; fresh and incremental
     merges make the same conflict and completeness decisions;
   - validation: identifier, scorer, metric, dataset-size, epochs, reducer
     and format-version mismatches (a scorer change that keeps the
     identifier included), one id in two shards, a held id outside the
     selection, a chunked-shape sample, a slash-containing id
     (`group/item`, a monolith, accepted), stray files, and an existing
     ordinary `<name>.eval`, each refused (or accepted) with nothing
     written on refusal;
   - incremental: a grown shard adds only its new samples; an unchanged
     shard is not opened (a spy on `AsyncZipReader` construction); a pass
     over unchanged shards writes nothing and returns `written=False`; a
     new attempt in `<k>/` replaces `<k>`'s samples and drops ones it
     lacks; a deleted `<k>/` drops its samples; an added shard returns a
     `success` log to `started`; `eval_id`, `run_id` and `task_id` are
     stable across passes; header edits (`tags`) survive a pass and a
     sample `edit_score` survives while its shard is unchanged;
   - fresh equals incremental: after replacing one shard's attempt, after
     removing the template shard, and after a sequence where shard A fails,
     then B fails, then A recovers, the incremental header equals a fresh
     merge's (`stats` with distinct per-shard usage, `error` with full
     traceback fields, `eval_set_id`, template fields, results, keys);
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
     writing;
   - `delete_shards`: removes the companion after a verified `success`
     publish; a verification failure leaves the shards; combined with
     `allow_incomplete` it is a `ValueError`; a companion with a
     `<k>/scans/` directory or a retained `<shard>.checkpoints/` is refused
     with nothing deleted; an object created between listing and deletion
     (a storage hook) is left, and the call raises with the merged log kept;
   - trust: a metric registered only in a `task_file` is resolved through
     the fallback and recorded as `metrics_source: "task_file"`; a missing
     metric fails without writing; a spy asserts no reader path
     (`read_eval_log`, `list_eval_logs`, `evals_df`) calls the merge;
   - cancellation mid-pass (after reads, during the build, during the S3
     upload) leaves the merged log and shards as they were and no temp or
     lock file behind; run with `--runtrio`.
   `tests/cli/test_log.py`: `merge-shards` on a merged log, a companion and
   a log directory; `--sample-id` and `--sample-count`; the usage error for
   a selection with a directory; `--json` shape; the `task_file` notice;
   exit codes.
6. **Eval-set integration.** `tests/test_eval_set.py`: startup over a
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
   with `retry_cleanup=False` everything stays; no shard
   header is read outside the merge (spy on `read_eval_log_headers`
   inputs); an invalid companion aborts with `PrerequisiteError`;
   `selected_sample_ids` equals `slice_dataset`'s ids for `limit`,
   `sample_id` and unset-id datasets; a selection-mode worker does not merge.
7. **Viewer delete.** `tests/_view/test_view_server.py` with a FastAPI test
   client over `/log-delete`: a policy that allows the merged log and
   denies one companion object returns 403 and deletes nothing; allowing
   both removes the companion then the log; an ordinary log with a
   same-named companion beside it deletes only the log; a corrupt `.eval`
   and one with an unsupported format version are deleted alone with 200,
   as today; a mapping policy that is not a common-prefix replacement (it
   maps individual companion objects to unrelated request paths) authorizes
   each object at its `unmap`ped path, and a mapping that does not
   round-trip fails closed with 403; a denied object inserted between
   authorization and deletion (a barrier in the storage layer) is not
   deleted, the response is 409 and the merged log remains; a companion
   with scan results is 409 with nothing deleted.
8. **Streaming recomputation.** `tests/log/test_shards.py`: peak memory
   (`tracemalloc`) of a merge over shards with large transcripts and small
   scores does not grow with transcript size; with large score metadata,
   growth matches the retained metric inputs and custom metrics receive
   them unchanged.
9. **Raw copy.** `tests/util/test_zipfile.py`: raw-copied members read back
   byte-identical through `zipfile` and `AsyncZipReader`, including ZIP64
   sizes and offsets and both compression methods in use;
   `tests/log/test_shards.py`: a merge with raw copy produces the same
   member contents and results as without; a changed shard member whose
   CRC equals the carried member's is not read from the shard.

No test needs a network, Docker or a model provider. Gated runs before each
PR: `--runtrio` for PRs 3–6, 8 and 9. A manual check against a real S3
bucket for PR 4 (conditional multipart with `IfMatch`, which moto does not
enforce) is recommended and reported in the PR's "Slow tests" section.

## Implementation plan

Step 1 in nine PRs.

| PR | Depends on | Can run in parallel with |
|---|---|---|
| 1 layout helpers (#530) | none | 2, 4 |
| 2 field + `ts-mono` | none | 1, 3, 4 |
| 3 shared walk | 1 | 2, 4 |
| 4 guard primitives | none | 1, 2, 3, 7 |
| 5 merge core, API, CLI | 2, 3, 4 | 7 |
| 6 eval-set integration | 5 | 7, 8 |
| 7 viewer delete | 1, 2, 3; same release as 5 | 4–6 |
| 8 streaming recomputation | 5 | 6, 7 |
| 9 raw member copy | 5, 8 | 6, 7 |

1. **Layout and naming helpers** (#530, in progress). Moves `log_basename`
   and `eval_checkpoints_dir` to a neutral module, adds `eval_shards_dir`
   and the reverse derivation, factors the name builder. No behaviour
   change. Files: the neutral module #530 chooses,
   `util/_checkpoint/_layout/`, `log/_recorders/file.py`, tests.
2. **The `EvalSpec.shards` field and its `ts-mono` landing.** Models,
   field, exports, `inspect-openapi.json`, the `ts-mono` PR regenerating
   `generated.ts`, gitlink bump per `land-ts-mono`. No behaviour change
   (nothing writes the field yet). Independent of 1. Files:
   `log/_log.py`, `log/__init__.py`, `_view/inspect-openapi.json`,
   `_view/ts-mono` (gitlink), `tests/log/test_eval_log.py`. No CHANGELOG
   entry (no user-visible change until PR 5).
3. **Shared walk.** `AsyncFilesystem.list_dir` if #528 has not landed it
   (otherwise reuse), `log/_shards/_walk.py` (`list_shard_set`,
   `attempt_sort_key`, `is_shard_path`). Depends on 1. Files:
   `_util/asyncfiles.py`, `log/_shards/__init__.py`, `log/_shards/_walk.py`,
   `tests/util/test_asyncfiles.py`, `tests/log/test_shards.py`. After this
   PR, ctl log-dir mode's step 4 can land.
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
   _publish,_delete}.py`, exports and the reference section, `inspect log
   merge-shards`, docs (a "Sharding" section in `docs/parallelism.qmd`
   covering the layout, the launcher's job and the harness notes from the
   parent), CHANGELOG entry. Depends on 2, 3, 4. Must ship in the same
   release as 7 (a viewer delete of a merged log without the cascade would
   leave shards that the next eval set re-merges). Files as listed plus
   `log/__init__.py`, `_cli/log.py`, `docs/reference/inspect_ai.log.qmd`,
   `docs/parallelism.qmd`, `CHANGELOG.md`, `tests/log/test_shards.py`,
   `tests/cli/test_log.py`. Needs the `ZipEntry` CRC and the opt-in CRC
   check ("Consistent reads"): if #528 has not landed them, this PR adds
   them in `_util/zip_common.py` and `_util/async_zip.py` as #528's design
   specifies, and #528 reuses them.
6. **Eval-set integration.** Startup merge, `selected_sample_ids`,
   `skip_shards`, completeness branch, no recovery of merged logs, cleanup
   ordering and companion deletion, `docs/eval-sets.qmd` note, CHANGELOG
   entry. Depends on 5. Coordinate with #5396. Files:
   `_eval/evalset.py`, `_eval/eval_set_manifest.py`, `docs/eval-sets.qmd`,
   `CHANGELOG.md`, `tests/test_eval_set.py`.
7. **Viewer delete authorization.** The cascade with per-object policy
   checks through `remove_shards_dir(..., authorize=...)`. Depends on 1, 2
   and 3 (it recognises merged logs by the field, derives the companion by
   name, and uses the walk's ancillary rule), and on `_delete.py`, which it
   introduces if it lands before 5; land before or with 5.
   Coordinate with #5401. Files: `_view/fastapi_server.py`,
   `_view/common.py`, `tests/_view/test_view_server.py`, CHANGELOG entry.
8. **Streaming recomputation.** Include-only score extraction and the
   memory tests. Depends on 5. Files: `log/_shards/_write.py`,
   `log/_recorders/eval.py` (expose the builder if needed),
   `tests/log/test_shards.py`.
9. **Raw compressed-member copy.** The raw member writer and its use in the
   merge, with the CRC shortcut. Depends on 5 (which brings the CRC);
   after 8 so the two measurements are separable. Files:
   `_util/zipfile.py`, `log/_shards/_write.py`, `tests/util/test_zipfile.py`,
   `tests/log/test_shards.py`.

PRs 5–7 each carry a CHANGELOG line; 1–4 are internal. Each PR reports its
`--runtrio` run under "Slow tests".

## Open questions

1. **Startup merge refusals.** When the `eval_set()` startup merge refuses
   a companion (invalid shard set, or another merge holding the lock or
   publishing first), should `eval_set()` stop with a `PrerequisiteError`
   or warn and continue without that companion? Recommendation: stop.
   Continuing pairs the task against a stale merged log or re-runs it from
   scratch while the shards sit unmerged. (The round-1 reviewer agreed.)

Stale local locks are report-only, as the parent's test list requires; a
same-host dead-pid check can be added if crashed merges turn out to happen.

## Not this design

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
