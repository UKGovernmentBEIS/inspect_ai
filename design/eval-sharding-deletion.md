# Eval sharding: deleting a merged log's shards

## Overview

`merge_eval_log_shards()` and `inspect log merge-shards` gain an option,
`delete_shards=True` (`--delete-shards`), that deletes the merged log's
`<name>.shards/` directory once the merge has left a complete merged log
that holds every shard's current attempt. The merge deletes nothing
without the option. With it, the merge first merges as usual; then, still
inside its overlap guard, it reads the merged log back from storage,
lists the shards directory again and checks that nothing changed since
the merge read it. Only then does it delete, by the names that listing
returned, every shard's current attempt last; on S3 each delete is
conditional on the object's listed ETag. An interrupted deletion leaves a
state that a later merge refuses with a message to finish it, and
running the merge again with the option finishes it. The typical use is
to merge, check the merged log, then run the same merge again with the
option: it writes nothing and deletes the shards.

## Why

The merge reads shards and writes the merged log; it never deletes
anything (decision: Ransom, 2026-11-03). The user removes
`<name>.shards/` by hand once the merged log is checked, with `rm -r` or
`aws s3 rm --recursive` ([sharding docs, "Merging"](../docs/sharding.qmd)).
Hand removal has three problems:

- Nothing checks that the merged log holds what is being deleted. A
  worker that wrote a new attempt after the last merge, or a merge that
  ended incomplete, loses data that no log holds, with no warning.
- Hand removal that stops part way (a timeout of `aws s3 rm`, a
  permissions error on one key) leaves some shard directories gone and
  others present, which every later merge refuses as vanished shards.
  The message says to delete the rest, which the user then does by hand
  again.
- A launcher that shards a task to one sample per machine has thousands
  of shard directories per run. It needs a cleanup step it can run
  unattended and branch on, which the merge command already gives it for
  merging (`--json`).

The implementation plan reserves this as PR 9: one rule for removing a
merged log's companion, offered by the merge as an option, including
what is verified before deleting and what a partial deletion leaves
([implementation plan, "Implementation plan" item 9](eval-sharding-implementation.md#implementation-plan)).

## Goals and non-goals

Goals:

- One public option on the merge API and the merge command, off by
  default.
- One rule for when the merge may delete, the same on local storage and
  S3: the merged log is `success` and holds every current attempt the
  shards directory holds when deletion starts.
- Deletion never removes something that was not verified: nothing
  created or replaced after the verification, and nothing outside
  `<name>.shards/`.
- A partial deletion that any later merge recognises and that the same
  call, run again, finishes.
- What users and launchers see: the result field, the command's report
  and `--json` field, and the error kinds.

Non-goals:

- Deleting without merging, or without a task. The merge is the only
  entry point (see "Alternatives considered").
- Deleting the shards of an incomplete merged log. A user abandoning a
  run removes its shards by hand.
- The viewer. `/log-delete` keeps deleting only the file requested
  (decision: Ransom, 2026-09-24; implementation plan, ["Removing
  shards"](eval-sharding-implementation.md#removing-shards)).
- Retry cleanup in `eval_set()`. `eval_set()` refuses a log directory
  that holds shard logs (decision: Ransom with JJ Allaire, 2026-11-18),
  so its cleanup never meets a companion ("Current behaviour").
- Moving shards to an archive location, or recovering deleted ones. A
  versioned S3 bucket keeps them as noncurrent versions, as `aws s3 rm`
  does.
- Changing anything else the merge reads, checks or writes. This design
  relies on the merge as the implementation plan specifies it and does
  not restate it.

## Current behaviour

What this design depends on, read on `main`:

- **The merge entry point.** `merge_eval_log_shards_async`
  (`src/inspect_ai/log/_shards/_api.py:173`) checks its arguments before
  any I/O, then runs one pass inside `merge_guard`
  (`_api.py:197`, `_publish.py:101`): a lock file beside a local merged
  log, nothing for S3, whose guard is the conditional publish
  (`publish`, `_publish.py:147`, which returns the new ETag on S3). It
  returns `ShardMergeResult(log, written)` (`_api.py:74`).
- **Unchanged shards.** A shard's current attempt is unchanged when its
  ledger entry has the same file name and the same ETag, or the same
  size and mtime where either side has no ETag (`is_unchanged`,
  `_plan.py:215`). A pass where nothing changed and the selection is the
  recorded one writes nothing (`_api.py:438`).
- **Vanished shards.** A ledger entry whose `<k>/` has no attempt while
  some other shard still has one is refused before anything is read,
  with "Delete <shards dir> to keep the merged log as it is, or restore
  the files" (`check_vanished`, `_plan.py:452`, called at
  `_api.py:384`).
- **No shards left.** When no `<k>/` holds an attempt, the merge writes
  nothing and returns the merged log as recorded, refusing a selection
  that differs from the recorded one and an incomplete status without
  `allow_incomplete` (`_api.py:368`, `_recorded_pass` at `_api.py:520`).
- **The listing.** `list_shard_set` (`_walk.py:128`) lists the shards
  directory and each directory under it, two levels and no deeper.
  Files other than attempts in a `<k>/` (`scans/`, a
  `<shard>.checkpoints/`, a `.buffer/`) are ancillary and not listed
  further. Every listed name goes through `check_s3_location`
  (`_walk.py:44`), which refuses an S3 name that S3 would read as
  another key (`#`, `?`, a tab or line break, a leading `/`).
- **Deleting a file.** `AsyncFilesystem.delete_file`
  (`src/inspect_ai/_util/asyncfiles.py:1676`) deletes one local file or
  one S3 key, unconditionally, re-parsing the key from the URL. There is
  no conditional delete. `iter_files(recursive=True, detail=True)`
  lists every object under an S3 prefix in one paginated sweep, with
  each object's ETag.
- **S3 conditional deletes.** botocore 1.43.117 (locked) accepts
  `IfMatch` on `DeleteObject` and a per-object `ETag` in `DeleteObjects`.
  A spike against moto 5.2.2 (locked) showed that `DeleteObject` with a
  wrong `IfMatch` fails with `412 PreconditionFailed` and keeps the
  object, a right one deletes it, and a missing key fails with
  `404 NoSuchKey`; `DeleteObjects` with a wrong per-object `ETag` deletes
  the object anyway. Only the single-object form can be tested against
  moto.
- **Worker threads.** Every worker thread the merge starts goes through
  `run_owned` (`_owned.py:12`), so the lock is never released while one
  runs; a test scans the merge's modules for any other thread dispatch.
- **`eval_set()`.** `_refuse_shard_companions`
  (`src/inspect_ai/_eval/evalset.py:201`) refuses a log directory when a
  listed log is a shard log, and tells the user to merge, then move the
  `.shards` directory out. An empty companion, or one holding no log,
  is not refused.
- **Docs.** `docs/sharding.qmd` tells users to delete the shards
  directory by hand (line 71, quoted under "Documentation" below) and
  lists the vanished-shard refusal as a limitation (line 131).

## Design

### The option

```python
def merge_eval_log_shards(
    log: str,
    task: Task,
    *,
    sample_ids: Sequence[str | int] | None = None,
    sample_count: int | None = None,
    allow_incomplete: bool = False,
    delete_shards: bool = False,
) -> ShardMergeResult: ...
```

`merge_eval_log_shards_async` takes the same keyword. The merge command
takes `--delete-shards` (a flag, read only from the command line, like
`--allow-incomplete`).

```python
@dataclass(frozen=True)
class ShardMergeResult:
    log: EvalLog
    written: bool
    shards_deleted: bool = False
    """True when `delete_shards` was given and the shards directory is gone:
    a listing after deletion found nothing under it. Also true when it was
    already gone."""
```

Default `False`: the merge deletes nothing unless the option is given
(decision: Ransom, 2026-11-03).

With `delete_shards`, a local `<name>.shards` that is a symbolic link
raises `ShardSetError` before the merge takes its lock or writes
anything, as a merged log that is a link does: deleting through the link
would empty a directory the user did not name.

`delete_shards=True` with `allow_incomplete=True` raises `ValueError`
with the other argument checks, before any I/O: the pair asks to write
an incomplete log and delete the shards that would complete it. With
`delete_shards`, an incomplete set raises `ShardSetIncomplete` before
anything is written or deleted, as the merge already does without
`allow_incomplete`.

### Ownership

The merge owns deletion: a new module, `log/_shards/_delete.py`, called
by `merge_eval_log_shards_async` after the pass, inside the same
`merge_guard` and the same `AsyncFilesystem` scope. The pass decides
nothing about deletion; deletion runs only after the pass returned (its
publish succeeded, or it wrote nothing). No other code path deletes a
companion: not the viewer, not `eval_set()`, not `eval_retry()`.

`AsyncFilesystem` gains one primitive, a conditional delete of one S3
object: delete the key if its ETag matches, raise `WriteConflictError`
on `412`, and treat `404` as already deleted. Local files are deleted
with an ordinary unlink of the path, never following a symbolic link,
through `run_owned`.

### The rule: what is verified before anything is deleted

Deletion runs only when all of these hold. Each is checked against
storage after the pass, not taken from the pass's memory, and a failure
deletes nothing:

1. **The merged log is complete.** Its status, read back from storage
   (header and central directory, the reads the merge already makes of
   an existing merged log), is `success`.
2. **It is the merged log this call left.** On S3 its ETag is the one
   the pass published, or read when it wrote nothing; otherwise another
   merge published in between and deletion raises `WriteConflictError`.
   Locally the lock already excludes other merges.
3. **It holds what its ledger says.** Its `samples/` members number the
   ledger's sample counts, the merge's own count check.
4. **The shards directory holds exactly what the ledger records.** A
   fresh listing of `<name>.shards/` finds no stray log file, and every
   `<k>/` with an attempt has a ledger entry whose attempt is its current
   attempt, unchanged (`is_unchanged`). A ledger entry whose `<k>/` has
   no attempt is allowed only as a partial deletion ("Partial deletion"
   below).
5. **The set to delete is fixed and verified.** Deletion removes exactly
   the entries one recursive listing of `<name>.shards/` returned, taken
   for this check: every `.eval` file directly in a `<k>/` that it holds
   is an attempt that check 4 saw (the current one or an older one),
   and on S3 every name in it passes `check_s3_location`, so no key is
   read as another.

Checks 4 and 5 reuse the merge's own listing and comparison rules
(`list_shard_set`, `is_unchanged`, `check_s3_location`); deletion adds
no rule of its own about what a shard set holds.

Cost check: 1–3 cost the header and central-directory reads of one
`AsyncZipReader` (two or three ranged GETs on S3) and add no new
mechanism. 4 is one more `list_shard_set` (on S3, one list request per
`<k>/`, at most 32 at a time). 5 is one recursive listing (one paginated
sweep on S3, a walk locally). For a run of 10,000 one-sample shards that
is about 10,000 list requests and a few seconds, fewer requests than
the shard reads its first merge made.

### Deleting

- **By name, never by prefix.** Each file and S3 object in the set from
  check 5 is deleted by its own name. Nothing created after that listing
  is deleted. Locally, directories are then removed deepest first, each
  only if it is empty, the companion itself last; a symbolic link is
  removed as a link and its target is never visited. On S3 every delete
  is conditional on the ETag the listing returned, so an object replaced
  after the listing is kept and the deletion stops with
  `WriteConflictError`.
- **Current attempts last.** Every other entry of the set (older
  attempts, `scans/`, checkpoint directories, a `.buffer/`, other files)
  is deleted first; each shard's current attempt is deleted only after
  all of them. So whenever a deletion stops, every `<k>/` either still
  holds its current attempt, unchanged, or holds no attempt at all.
  (Deleting a current attempt before an older one in the same `<k>/`
  would make the older one current, which the merge refuses as an
  attempt regression.)
- **Bounded and owned.** Deletes run at most 32 at a time. Local unlinks
  and `rmdir`s go through `run_owned`, so the lock is not released while
  one runs. The first failure stops new deletes; deletes in flight
  finish; the failure propagates.
- **Confirmed.** After the last delete, one more recursive listing of
  `<name>.shards/` must find nothing. `shards_deleted` is true only
  then. If it finds anything (a file a worker wrote during deletion), the
  call raises `ShardSetError` naming up to ten of the entries with the
  total, and saying they were not merged.

Cost check: one request per object on S3, against one per thousand
objects with `DeleteObjects`. S3 does not charge for deletes, and at 32
in flight 10,000 objects take seconds; the single-object form is the one
whose condition moto honours, so its guarantee is testable ("Current
behaviour"). Current attempts last costs nothing: the same deletes in
two groups. The confirming listing is one sweep.

### Partial deletion

A deletion stopped by an error, a cancellation, a crash or a `412`
leaves `<name>.shards/` with some entries gone. Because current attempts
go last, every shard still with an attempt holds its ledger's current
attempt unchanged, and every other ledger entry's `<k>/` holds no
attempt. How each later operation treats that state:

- **The merge without the option** refuses it as vanished shards, as
  today. The message now also says how to finish: "If a deletion of
  the shards was interrupted, merge again with `delete_shards=True`
  (`--delete-shards`) to finish it."
- **The merge with the option** finishes it. When some ledger entries
  are vanished and every shard that still has an attempt is unchanged,
  the pass writes nothing and keeps the merged log as recorded, exactly
  as when no shard is left: a supplied selection must equal the recorded
  one, and the recorded status must be `success`. Deletion then verifies
  and deletes what remains. If any remaining shard changed, or a new
  `<k>/` appeared, the merge refuses as vanished shards: merging the
  remainder would write a merged log with fewer records, and deleting it
  would lose the change.
- **Nothing but ancillary entries left** (every attempt deleted): the
  merge, with or without the option, takes its existing no-shards path
  and returns the merged log as recorded; with the option it deletes the
  rest.
- **A local lock left by a crash during deletion** is reported and never
  overridden, as for a crashed merge; the user deletes it and runs the
  merge again with the option.
- **`eval_set()`** refuses the log directory while any shard log remains
  and accepts it once none does, as today. `eval_retry()` of the merged
  log is unaffected: deletion never changes the merged log.

The rule needs no marker of a deletion in progress: a partially deleted
companion is recognised from the ledger and the listing alone. The same
rule finishes a hand removal that stopped part way, which the vanished
message already tells the user to complete.

Cost check: no new state and no new reads; the classification the merge
already makes, with one more accepted case.

### Composition with the overlap guards

- **Local.** Verification and deletion run under the merge's lock. A
  merge started during deletion is refused with `WriteConflictError`
  until the lock is released, after the confirming listing or the
  failure.
- **S3.** There is no lock. Check 2 refuses deletion when another merge
  published after this call's pass. A merge that overlaps the deletion
  either lists the companion after some current attempts are gone and
  refuses them as vanished, or read them all before; its publish then
  holds the same attempts this deletion verified, since a replaced
  attempt makes its conditional delete fail and is kept. Overlapping
  merges remain a broken contract (parent design, "Overlapping merges");
  these checks make an overlap refuse rather than lose data.
- **Running workers.** Deleting requires a `success` merged log, so
  every current attempt was `success` when read. A worker that starts a
  new attempt in a `<k>/` after the merge read it makes check 4 or 5
  fail if it is listed before deletion, and otherwise is left in place by
  deletion by name and reported by the confirming listing. Merging after
  the workers have exited remains the supported use.

### What users see

- **Python.** `ShardMergeResult.shards_deleted`. Refusals before
  deletion raise `ShardSetError` (checks 1, 3, 4, 5; the message says
  whether the merged log was written in this call and that the shards
  were not deleted) or `WriteConflictError` (check 2, the lock, a `412`
  during deletion). A storage error during deletion propagates as
  raised. Each message ends with how to continue: run the merge again,
  with the option, once the workers have exited.
- **Command report.** After the status line, `  shards: deleted
  <shards dir>` when `shards_deleted` is true.
- **`--json`.** The result object gains `"shards_deleted": true|false`,
  always present. Errors use the existing kinds: `invalid_arguments` for
  `--delete-shards` with `--allow-incomplete`, `incomplete` for an
  incomplete set, `refused` for checks 1, 3, 4 and 5 and the confirming
  listing, `conflict` for check 2, the lock and a `412`, `storage_error`
  for a failed delete.
- **The `eval_set()` refusal** names the option as an alternative to
  moving the `.shards` directory out.

### Documentation

`docs/sharding.qmd` loses this paragraph from "Merging":

> The merge does not delete the shards. Once you have checked the merged
> log, delete the `.shards` directory yourself, for example with
> `rm -r logs/<name>.shards` or
> `aws s3 rm --recursive s3://<bucket>/logs/<name>.shards/`. Later merges
> then return the merged log as it is. When a later unsharded run of the
> task supersedes a merged log, the merged log and its `.shards`
> directory stay until you remove them.

and gains a "Removing shards" section after "Merging":

> ### Removing shards
>
> The merge keeps the shards unless you ask it to delete them. Once you
> have checked the merged log, merge again with `--delete-shards` (or
> `delete_shards=True`):
>
> ``` bash
> inspect log merge-shards logs/<name>.eval --task mytask.py \
>   -T difficulty=hard --delete-shards
> ```
>
> If nothing has changed since the merge you checked, this writes
> nothing and then deletes the `.shards` directory. It deletes only when
> the merged log is complete (`success`) and holds the newest log of
> every shard directory as the `.shards` directory stands when deletion
> starts; otherwise it raises an error and deletes nothing.
> `--delete-shards` cannot be combined with `--allow-incomplete`. On S3
> each file is deleted only if it has not changed since the merge listed
> it. Deletion cannot be undone, except from object versions on a
> versioned S3 bucket.
>
> If deletion is interrupted, part of the `.shards` directory remains and
> later merges refuse it. Merge again with `--delete-shards` to finish.
> You can still delete the `.shards` directory by hand (`rm -r`,
> `aws s3 rm --recursive`); later merges then return the merged log as it
> is.
>
> When a later unsharded run of the task supersedes a merged log, the
> merged log and its `.shards` directory stay until you remove them.

The Limitations bullet on deleting one shard directory by hand adds
"Merging with `--delete-shards` deletes the rest." The "Eval sets"
section's last sentence becomes "Then move the `.shards` directory out
of the log directory, or delete it with `--delete-shards`, before you run
an eval set there." The command section lists `--delete-shards`, the
`--json` example gains `"shards_deleted": false`, and the error-kind
table's `refused` and `conflict` rows mention deletion.

## Alternatives considered

- **A separate `delete_eval_log_shards(log)` without a task.** Users
  would not rebuild the task to delete. It lost because the task text
  makes deletion a merge option, and a second entry point would need its
  own guard, its own handling of a stale merged log and its own error
  envelope. The merge gives all three, and merging first means a merged
  log that is behind its shards is brought up to date before they go.
- **Allow deletion of an incomplete merged log.** Deleting the shards
  of a `started` or `error` merged log freezes it: no later merge can
  add the missing samples or change the selection. Users abandoning a run
  can remove the shards by hand; the option stays safe to put in a
  launcher.
- **`DeleteObjects` batches with per-object ETags.** A thousandth of the
  requests, and real S3 honours the condition, but moto deletes the
  object anyway (spike above), so no test could prove the guarantee.
  Deletes are free on S3 and the single-object form is fast enough.
- **Unconditional prefix deletion** (`fs.rm(recursive=True)`, `aws s3 rm
  --recursive`). Simplest, but it deletes files created or replaced after
  the verification, and a local recursive removal visits what it finds
  rather than what was verified.
- **A marker for a deletion in progress** (a file in or beside the
  companion, or a field in the merged log). Not needed: the ledger and
  the listing identify a partial deletion. A file in the companion would
  break the rule that it holds only shard files, and a field in the merged
  log would mean a publish before every deletion.
- **Re-verify every sample of the merged log** (decompress and parse each
  member) before deleting. It would roughly double the cost of every
  deleting merge, and the merge already checks each member's CRC as it
  copies it. Checks 1–3 confirm that the published object is the
  readable merged log the pass wrote.
- **Delete by default.** Refused by the parent decision (Ransom,
  2026-11-03): deletion is the one step that cannot be undone after a bad
  merge.

## Compatibility and migration

No migration required.

- **API.** `delete_shards` is a new keyword with default `False`;
  existing callers are unchanged. `ShardMergeResult.shards_deleted` is a
  new field with default `False`.
- **CLI.** `--delete-shards` is new. The `--json` result object gains
  the `shards_deleted` key; existing keys are unchanged.
- **Messages.** The vanished-shard message and the `eval_set()` refusal
  gain a sentence. Callers that match their text exactly (the merge's
  own tests) change with them.
- **Log format.** None: deletion reads the merged log and writes nothing
  to it. No schema or `ts-mono` change.
- **Partial states.** A companion partly removed by hand, before or
  after this change, is finished by the same option.

## Security

Untrusted input that reaches deletion:

- **Names in the shards directory.** Workers, or anyone who can write
  the log directory, choose them. Deletion is confined to
  `<name>.shards/`: locally, the recursive listing does not follow
  symbolic links, and a link is removed without visiting its target; a
  companion that is itself a symbolic link is refused before the merge
  writes anything, as a linked merged log is. On S3, only keys under the
  companion's prefix with its trailing `/` are listed (so
  `<name>.shards-x/` is not), and every name passes
  `check_s3_location` before anything is deleted, so no key is deleted
  in place of another.
- **The merged log's ledger.** It decides whether deletion may run, never
  what is deleted: the set to delete comes only from listing the
  companion. A ledger edited outside the merge can make checks 3 and 4
  fail, never widen the set.
- **Credentials.** Deletion uses the caller's storage credentials, like
  the merge. No access policy is consulted; the viewer, which has one,
  does not delete companions.

## Testing

In `tests/log/test_shards.py` unless noted, local and on S3 through the
`mock_s3` fixture, under asyncio and Trio (`--runtrio`):

Step 1 (primitive), in `tests/util/test_asyncfiles.py`:

- `test_delete_file_if_match_deletes_matching_object`,
  `test_delete_file_if_match_keeps_replaced_object` (`WriteConflictError`,
  object intact), `test_delete_file_if_match_missing_key_is_deleted`.

Step 2 (deletion in the merge):

- `test_merge_deletes_nothing_by_default`: a merge without the option
  leaves every companion entry.
- `test_delete_shards_removes_companion` (local, `file://`, S3), including
  older attempts, `scans/`, a checkpoint directory and a `.buffer/`;
  `shards_deleted` is true and a later merge returns the merged log as
  recorded.
- `test_delete_shards_after_unchanged_merge`: `written=False`,
  `shards_deleted=True`.
- `test_delete_shards_with_allow_incomplete_is_refused`: `ValueError`, no
  I/O.
- `test_delete_shards_refuses_incomplete_set`: `ShardSetIncomplete`,
  nothing written or deleted.
- `test_delete_shards_refuses_attempt_changed_after_pass`: between the
  pass and verification, a new attempt appears in one `<k>/`, and
  separately a current attempt is replaced; the merged log is written,
  nothing is deleted, and running the merge again merges it and deletes.
- `test_delete_shards_refuses_merged_log_replaced_on_s3`: the merged log
  is replaced between pass and verification; `WriteConflictError`,
  nothing deleted.
- `test_delete_shards_keeps_object_replaced_during_deletion` (S3): an
  object replaced after the recursive listing is kept,
  `WriteConflictError`.
- `test_delete_shards_keeps_file_created_during_deletion` (local and S3):
  the file survives, `ShardSetError` names it, `shards_deleted` is not
  reported.
- `test_delete_shards_deletes_current_attempts_last`: the first delete of
  a current attempt fails; every other entry is gone, every current
  attempt is present, and a merge without the option writes nothing.
- `test_delete_shards_finishes_partial_deletion`: with some `<k>/` emptied
  and the rest unchanged, a merge without the option refuses with the
  new message; with it, writes nothing and deletes the rest; with a
  different selection, refuses.
- `test_delete_shards_refuses_partial_deletion_with_changed_shard`: one
  remaining shard changed; refused, nothing deleted.
- `test_delete_shards_does_not_follow_symlinks` (local): a link in a
  `<k>/` to a directory outside is removed and its target is intact; a
  linked companion is refused before anything is written.
- `test_delete_shards_stays_in_prefix` (S3): keys under `<name>.shards-x/`
  and `<name>.shardsx` survive.
- `test_delete_shards_refuses_unsafe_s3_name`: a key with `#` deep under
  `scans/`; refused before anything is deleted.
- `test_delete_shards_holds_lock` (local): a merge started during
  deletion raises `WriteConflictError`.
- `test_delete_shards_cancelled`: cancellation during deletion (cancel
  scope and direct task cancel), the lock released only after owned work
  finishes, and a re-run with the option completes.
- In `tests/test_eval_set.py`:
  `test_eval_set_accepts_log_dir_after_delete_shards`.
- Command tests (beside the existing `merge-shards` tests):
  `--delete-shards` report line and `shards_deleted` in `--json`;
  `--delete-shards --allow-incomplete` exits 1 with `invalid_arguments`.

No test needs network, Docker or a model provider.

## Implementation plan

1. **Conditional S3 delete.** The `AsyncFilesystem` primitive (asyncio
   and Trio routes, `412` as `WriteConflictError`, `404` as deleted).
   Files: `src/inspect_ai/_util/asyncfiles.py`,
   `tests/util/test_asyncfiles.py`.
2. **Deletion in the merge.** `log/_shards/_delete.py` (verification,
   deletion, confirming listing); the option, the result field, the
   argument check and the partial-deletion case in `log/_shards/_api.py`;
   the vanished message in `log/_shards/_plan.py`; `--delete-shards`,
   the report line and the JSON field in
   `src/inspect_ai/_cli/log_merge_shards.py`; the refusal message in
   `src/inspect_ai/_eval/evalset.py`; `docs/sharding.qmd`
   ("Documentation"). Tests as listed. Depends on 1.

## Open questions

- **Deletion only for a `success` merged log.** Recommendation: yes; an
  incomplete run's shards are removed by hand, and the option stays safe
  to put in a launcher unconditionally.
  Confidence: high

## Not this design

- A viewer delete of a merged log that also removes its companion, with
  per-object authorization (implementation plan, "Not this design").
- A delete command or function that needs no task.
- Deleting a merged log's `<name>.checkpoints/` (meridianlabs-ai/inspect_ai#582).
- Relocating per-shard scan results before deletion, so that scanner
  resume can reuse them (implementation plan, "Not this design").
- A same-host dead-process check for stale local merge locks.
