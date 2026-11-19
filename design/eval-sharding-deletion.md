# Eval sharding: deleting a merged log's shards

## Overview

`merge_eval_log_shards()` and `inspect log merge-shards` gain an option,
`delete_shards=True` (`--delete-shards`), that deletes the merged log's
`<name>.shards/` directory after a merge that leaves a complete
(`success`) merged log. Without the option the merge deletes nothing.
With it, the merge merges as usual, then, still holding its lock, it
reads the merged log back, lists the shards directory again and checks
that it holds exactly the attempts the merged log records. Only then
does it delete the files and objects that listing found, by name, each
shard's current attempt last, and it confirms that nothing is left. A
deletion that is interrupted is finished by running the same merge with
the option again. Like removing shards by hand, the option is for a
finished run that nothing else is touching; the user is responsible for
that. The typical use is to merge, check the merged log, then run the
same merge again with the option: it writes nothing and deletes the
shards.

## Why

The merge reads shards and writes the merged log, and deletes nothing
(decision: Ransom, 2026-11-03). Today the user removes `<name>.shards/`
by hand once the merged log is checked, with `rm -r` or `aws s3 rm
--recursive` (the docs' "Merging" section, quoted under "Documentation"
below). That has three problems:

- Nothing checks that the merged log holds the shards being deleted: a
  shard that changed after the last merge, or a merge that ended
  incomplete, is deleted all the same.
- A removal that stops part way (a timeout, a permissions error on one
  key) leaves some shard directories gone and others present, which every
  later merge refuses as vanished shards until the user finishes by hand.
- A launcher that shards a task down to one sample per machine has
  thousands of shard directories per run, and needs a cleanup step it
  can run unattended and branch on, as `--json` lets it do for the merge.

The implementation plan reserves this as PR 9: one rule for removing a
merged log's companion, offered by the merge as an option
([implementation plan, item 9](eval-sharding-implementation.md#implementation-plan)).

## Goals and non-goals

Goals:

- One public option on the merge API and the merge command, off by
  default.
- One rule, the same for local storage and S3, for when the merge may
  delete: the merged log is `success` and holds every current attempt
  the shards directory holds.
- Deletion confined to what was verified: nothing outside
  `<name>.shards/`, nothing a symbolic link points to, nothing the
  verifying listing did not return.
- An interrupted deletion that the same call, run again, finishes.
- What users and launchers see: the result field, the command's report
  and `--json` field, the errors.

Non-goals:

- Protecting a run that something else is writing while the cleanup
  runs (workers, log edits or scoring, other merges). The option
  requires a quiescent run, as hand removal does ("The quiescence
  requirement").
- Deleting the shards of an incomplete merged log (decision: Ransom,
  2026-11-19). A user abandoning a run removes its shards by hand.
- Deleting without merging, or without a task. The merge is the one
  entry point ("Alternatives considered").
- The viewer, whose `/log-delete` keeps deleting only the file requested
  (decision: Ransom, 2026-09-24), and `eval_set()`'s retry cleanup,
  which never meets a companion because `eval_set()` refuses a log
  directory that holds shard logs (decision: Ransom with JJ Allaire,
  2026-11-18).
- Moving shards to an archive location or recovering deleted ones. On a
  versioned S3 bucket deleted shards stay as noncurrent versions, as
  with `aws s3 rm`.
- Any other change to what the merge reads, checks or writes.

## Current behaviour

This design builds on the merge as the implementation plan specifies it
and does not restate it. It relies on:

- **Unchanged shards and the ledger.** The merged log's ledger records
  each shard's current attempt, and the merge decides whether an attempt
  is unchanged by file name and ETag, or size and mtime where there is
  no ETag ([implementation plan, "The merge"](eval-sharding-implementation.md#the-merge),
  step 5).
- **Vanished shards and no shards.** A ledger entry whose `<k>/` holds
  no attempt, while another shard still has one, is refused; with no
  attempt left anywhere the merge returns the merged log as recorded
  ([implementation plan, "Validation"](eval-sharding-implementation.md#validation)
  and step 10 of "The merge"). Removing the whole companion is therefore
  already a supported state.
- **The overlap guards.** A local merge holds `<name>.merge.lock` for the
  whole call; an S3 merge has no lock and publishes conditionally
  ([implementation plan, "Overlap guards"](eval-sharding-implementation.md#overlap-guards)).
  Neither excludes writers other than merges: the viewer's log edits and
  `inspect score` rewrite logs without the lock.
- **Worker threads.** Every worker thread the merge starts goes through
  one helper, so the lock is never released while one runs
  ([implementation plan, "Cancellation and concurrency"](eval-sharding-implementation.md#cancellation-and-concurrency)).
- **Listing and names.** The merge lists the companion two levels deep
  (`list_shard_set`) and refuses an S3 name that S3 would read as another
  key (`check_s3_location`), both in `src/inspect_ai/log/_shards/_walk.py`.
  `AsyncFilesystem`'s recursive S3 file listing skips keys ending in `/`
  (directory markers, which the S3 console and sync tools create), and
  its `delete_file` deletes one local file or S3 key
  (`src/inspect_ai/_util/asyncfiles.py`).
- **Docs.** `docs/sharding.qmd` tells users to delete the shards
  directory by hand, and lists the vanished-shard refusal as a limitation.

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


@dataclass(frozen=True)
class ShardMergeResult:
    log: EvalLog
    written: bool
    shards_deleted: bool = False
    """True when `delete_shards` was given and the shards directory is
    gone: a listing after deletion found nothing under it (also when it
    was already gone)."""
```

`merge_eval_log_shards_async` takes the same keyword; the command takes
`--delete-shards`, a flag read only from the command line, like
`--allow-incomplete`. The default is `False`: the merge deletes nothing
unless asked (decision: Ransom, 2026-11-03).

`delete_shards=True` with `allow_incomplete=True` raises `ValueError`
with the other argument checks, before any I/O. With `delete_shards`, an
incomplete set raises `ShardSetIncomplete` before anything is written or
deleted, as without `allow_incomplete` today (decision: Ransom,
2026-11-19).

### The quiescence requirement

`delete_shards` is supported only on a finished run that nothing else is
touching: a `success` merged log, and no workers, log edits or scoring
of the merged log or shards, and no other merge of the run, while the
cleanup runs (decision: Ransom, 2026-11-19). This is the user's
responsibility, the same condition under which the docs tell users to
remove shards by hand today. The merge does not enforce it beyond its
own lock and the verification below. If it is broken, a concurrent
writer's work can be lost, as with a hand removal: a shard attempt
rewritten after verification is deleted, and a merge that publishes
after verification keeps its log while the shards it read are deleted.

Cost check: free. Enforcing it would need every writer of a log (the
recorder, the viewer, `inspect score`, the merge on S3) to share a lock
or a conditional protocol with deletion, which no writer has today.

### Ownership

The merge owns deletion: a new module, `log/_shards/_delete.py`, called
by `merge_eval_log_shards_async` after the merge pass returns (its
publish succeeded, or it wrote nothing), inside the same lock and
`AsyncFilesystem` scope. No other code path deletes a companion. S3
objects are deleted with plain deletes and local files with an unlink
that never follows a symbolic link, through the merge's worker-thread
helper, so the lock is held until every delete has finished.

### Verified before anything is deleted

Deletion runs only when all of these hold, each checked against storage
after the merge pass; a failure raises `ShardSetError` and deletes
nothing:

1. **The merged log is complete.** Read back from storage (header and
   central directory), its status is `success`.
2. **It holds what its ledger records.** Its `samples/` members number
   the ledger's sample counts.
3. **The shards directory matches the ledger.** A fresh listing, with
   the merge's own listing and comparison rules, finds no stray log
   file, and every `<k>/` with an attempt has a ledger entry whose
   attempt is its current attempt, unchanged. A ledger entry with no
   attempt left is allowed only as an interrupted deletion ("Interrupted
   deletion").
4. **The set to delete is fixed.** One recursive listing of
   `<name>.shards/`, taken after check 3, is the set deleted: every file,
   and on S3 every object under the companion's prefix with its
   trailing `/`, directory markers included. Every attempt in it is one
   check 3 saw, and on S3 every name in it passes `check_s3_location`.

Cost check: checks 1 and 2 are the header and central-directory reads
the merge already makes of an existing merged log (two or three ranged
GETs on S3). Check 3 is one more companion listing (on S3 one list
request per `<k>/`, at most 32 at a time). Check 4 is one recursive
listing (a paginated sweep on S3, a walk that does not follow links
locally). For 10,000 one-sample shards that is about 10,000 list
requests, fewer than the shard reads of the first merge.

These checks catch a shard that changed or appeared between the last
merge and the cleanup, and a merged log that is incomplete or was
altered. They do not make concurrent writing safe ("The quiescence
requirement").

### Deleting

- **By listed name, never by prefix.** Each entry of the set from check
  4 is deleted by its own name, so nothing the listing did not return is
  deleted. Locally, directories are then removed deepest first, each only
  if empty, the companion last. A symbolic link is removed as a link and
  its target is never visited.
- **Current attempts last.** Every other entry (older attempts,
  `scans/`, checkpoint directories, a `.buffer/`, directory markers,
  other files) is deleted before any shard's current attempt. So
  whenever a deletion stops, each shard still with an attempt holds its
  recorded current attempt, and an older attempt never becomes current.
  Cost: none, the same deletes in two groups.
- **Bounded.** At most 32 deletes in flight. The first failure stops new
  deletes; those in flight finish; the failure propagates as raised.
  Deletes are one request per object on S3, which does not charge for
  deletes; 10,000 objects take seconds.
- **Confirmed.** After the last delete, one more recursive listing,
  directory markers included, must find nothing under `<name>.shards/`.
  Only then is `shards_deleted` true; otherwise the call raises
  `ShardSetError` naming up to ten of the entries left, with the total.
  Cost: one listing.

### Interrupted deletion

A deletion stopped by an error, a cancellation or a crash leaves each
shard either holding its recorded current attempt or holding no attempt.
What a later merge without the option does depends on when it stopped,
and only one case is new:

- **Before any current attempt was deleted**, every shard still holds
  its recorded attempt: an ordinary unchanged merge, which writes
  nothing.
- **After every current attempt was deleted** (only empty directories or
  ancillary entries left): the existing no-shards case, which returns
  the merged log as recorded.
- **Part way through the current attempts**, some shards have no
  attempt while others do: refused as vanished shards, as today. The
  message gains "If a deletion of the shards was interrupted, merge
  again with `delete_shards=True` (`--delete-shards`) to finish it."

A merge with the option finishes every case. In the third, when the
only difference from the ledger is shards with no attempt left, it
writes nothing and keeps the merged log as recorded (as when no shard is
left: the recorded status must be `success` and a supplied selection
must equal the recorded one); in all three it then verifies and deletes
what remains. Any other difference (a changed shard, a new `<k>/`) is
refused as today. A local lock left by a crash is reported, as for a
crashed merge; the user deletes it and reruns.

The rule needs no marker of a deletion in progress: the ledger and the
listing identify it, and it also finishes a hand removal that stopped
part way. Cost: none beyond the classification the merge already makes.

### What users see

- **Python.** `ShardMergeResult.shards_deleted`. A refused verification
  or a non-empty confirming listing raises `ShardSetError`, whose message
  says whether this call wrote the merged log and that the shards were
  not (or not all) deleted; a storage error propagates as raised. Each
  message says to merge again with the option once nothing else is
  writing the run.
- **Command report.** After the status line, `  shards: deleted <shards
  dir>` when `shards_deleted` is true.
- **`--json`.** The result object gains `"shards_deleted": true|false`,
  always present. Errors use the existing kinds: `invalid_arguments` for
  `--delete-shards` with `--allow-incomplete`, `incomplete` for an
  incomplete set, `refused` for a failed check or a non-empty confirming
  listing, `conflict` for the lock, `storage_error` for a failed delete.
- **The `eval_set()` refusal** names `--delete-shards` beside moving the
  `.shards` directory out.

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
> every shard directory; otherwise it raises an error and deletes
> nothing. `--delete-shards` cannot be combined with
> `--allow-incomplete`.
>
> Use it only on a finished run: no workers still running, no edits or
> scoring of the merged log or shards, and no other merge of the run
> until it returns. Something written to the run while the shards are
> deleted can be lost, as when you delete them by hand. Deletion cannot
> be undone, except from object versions on a versioned S3 bucket.
>
> If deletion is interrupted, part of the `.shards` directory remains,
> and if some shard directories still hold logs while others do not,
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
table's `refused` row mentions deletion.

## Alternatives considered

- **Enforce quiescence.** Conditional S3 deletes (`IfMatch` on each
  object's listed ETag), a re-check of the merged log's ETag, and local
  replace detection would narrow the windows for concurrent writers, but
  not close them: the viewer and `inspect score` rewrite logs outside the
  merge's lock, and a merge that publishes after verification still lets
  every delete succeed. Closing them needs a protocol shared by every
  log writer. Dropped (decision: Ransom, 2026-11-19) in favour of the
  stated requirement, the condition hand removal already has.
- **A separate `delete_eval_log_shards(log)` that needs no task.** Users
  would not rebuild the task to delete. It lost because a second entry
  point needs its own lock, its own handling of a merged log that is
  behind its shards and its own error envelope; the merge has all three,
  and merging first brings a stale merged log up to date before the
  shards go.
- **Deletion of an incomplete merged log.** It would freeze the log: no
  later merge could add the missing samples or change the selection.
  Refused (decision: Ransom, 2026-11-19).
- **Unconditional prefix deletion** (`fs.rm(recursive=True)`, `aws s3 rm
  --recursive`). Simplest, but it deletes entries the verification never
  saw and gives no ordering, so an interruption can leave an older
  attempt current.
- **A marker for a deletion in progress** (a file in or beside the
  companion, or a field in the merged log). Not needed: the ledger and
  the listing identify an interrupted deletion. A file in the companion
  would break the rule that it holds only shard files, and a field would
  mean a publish before every deletion.
- **Re-read every sample of the merged log before deleting.** It would
  roughly double the cost of a deleting merge; the merge already checks
  each member's CRC as it copies it, and checks 1 and 2 confirm the
  published object is the merged log the pass wrote.
- **Delete by default.** Refused (decision: Ransom, 2026-11-03):
  deletion is the one step that cannot be undone after a bad merge.

## Compatibility and migration

No migration required.

- **API.** `delete_shards` is a new keyword, default `False`;
  `ShardMergeResult.shards_deleted` a new field, default `False`.
  Existing callers are unchanged.
- **CLI.** `--delete-shards` is new; the `--json` result object gains
  the `shards_deleted` key, and existing keys are unchanged.
- **Messages.** The vanished-shard message and the `eval_set()` refusal
  gain a sentence; tests matching their text change with them.
- **Log format.** None. Deletion writes nothing to the merged log; no
  schema or `ts-mono` change.
- **Partial states.** A companion partly removed by hand is finished by
  the same option.

## Security

Untrusted input that reaches deletion:

- **Names in the shards directory**, chosen by workers or anyone who can
  write the log directory. Deletion stays inside `<name>.shards/`:
  locally the listing does not follow symbolic links and a link is
  removed without visiting its target; with `delete_shards`, a local
  `<name>.shards` that is itself a symbolic link is refused before the
  merge writes anything, as a merged log that is a link is. On S3 only
  keys under the companion's prefix with its trailing `/` are listed (so
  not `<name>.shards-x/`), and every name passes `check_s3_location`
  before anything is deleted, so no key is deleted in place of another.
- **The merged log's ledger** decides whether deletion runs, never what
  is deleted: the set comes only from listing the companion. A ledger
  edited outside the merge can make checks 2 and 3 fail, not widen the
  set.
- **Credentials.** Deletion uses the caller's storage credentials, like
  the merge, and consults no access policy; the viewer, which has one,
  does not delete companions.

## Testing

In `tests/log/test_shards.py`, local (plain path and `file://`) and on
S3 through the `mock_s3` fixture, under asyncio and Trio (`--runtrio`).
No test needs network, Docker or a model provider.

- `test_merge_deletes_nothing_by_default`: a merge without the option
  leaves every companion entry.
- `test_delete_shards_removes_companion`: older attempts, `scans/`, a
  checkpoint directory and a `.buffer/` go too; `shards_deleted` is true
  and a later merge returns the merged log as recorded.
- `test_delete_shards_removes_s3_directory_markers`: keys ending in `/`
  at the companion root and below shard and ancillary directories are
  deleted, and `shards_deleted` is true.
- `test_delete_shards_after_unchanged_merge`: `written=False`,
  `shards_deleted=True`.
- `test_delete_shards_with_allow_incomplete_is_refused`: `ValueError`, no
  I/O.
- `test_delete_shards_refuses_incomplete_set`: `ShardSetIncomplete`,
  nothing written or deleted.
- `test_delete_shards_refuses_shard_changed_since_merge`: a shard gains a
  new attempt after a merge; a deleting merge merges it, then deletes.
  Separately, a ledger whose counts do not match the merged log's members
  is refused with nothing deleted.
- `test_delete_shards_interrupted_then_finished`, parametrized over a
  failure injected before, during and after the deletion of current
  attempts (at the last non-attempt delete, at the first current-attempt
  delete, and at the first directory removal or the confirming listing).
  In every case every attempt left is a recorded current attempt and no
  older attempt has become current; a merge without the option writes
  nothing in the first and third cases and refuses with the new message
  in the second; a merge with the option writes nothing and deletes the
  rest. In the second case, a finishing merge with a different selection
  is refused.
- `test_delete_shards_refuses_interrupted_deletion_with_changed_shard`:
  one remaining shard changed; refused, nothing deleted.
- `test_delete_shards_does_not_follow_symlinks` (local): a link in a
  `<k>/` to a directory outside is removed and its target is intact; a
  linked companion is refused before anything is written.
- `test_delete_shards_stays_in_prefix` (S3): keys under `<name>.shards-x/`
  and `<name>.shardsx` survive.
- `test_delete_shards_refuses_unsafe_s3_name`: a key with `#` deep under
  `scans/` is refused before anything is deleted.
- `test_delete_shards_holds_lock` (local): a merge started during
  deletion raises `WriteConflictError`.
- `test_delete_shards_cancelled`: cancellation during deletion (cancel
  scope and direct task cancel) releases the lock only after the deletes
  in flight finish, and a rerun with the option completes.
- In `tests/test_eval_set.py`:
  `test_eval_set_accepts_log_dir_after_delete_shards`.
- Command tests beside the existing `merge-shards` tests: the report line
  and `shards_deleted` in `--json`; `--delete-shards --allow-incomplete`
  exits 1 with kind `invalid_arguments`.

## Implementation plan

One PR: `log/_shards/_delete.py` (verification, deletion, confirming
listing); the option, the result field, the argument check and the
interrupted-deletion case in `log/_shards/_api.py`; the vanished message
in `log/_shards/_plan.py`; a recursive listing that includes S3
directory markers if `AsyncFilesystem` has none (in
`src/inspect_ai/_util/asyncfiles.py`, leaving existing listings
unchanged); `--delete-shards`, the report line and the JSON field in
`src/inspect_ai/_cli/log_merge_shards.py`; the refusal message in
`src/inspect_ai/_eval/evalset.py`; `docs/sharding.qmd`
("Documentation"); the tests above.

## Open questions

None. Resolved by Ransom on 2026-11-19: deletion requires a `success`
merged log and cannot be combined with `allow_incomplete`, and the
option is supported only on a quiescent run, without coordination
against other writers.

## Not this design

- A viewer delete of a merged log that also removes its companion, with
  per-object authorization (implementation plan, "Not this design").
- A delete command or function that needs no task.
- Coordination between deletion and other log writers (the recorder,
  viewer edits, `inspect score`, S3 merges), should concurrent cleanup
  ever need to be safe.
- Deleting a merged log's `<name>.checkpoints/`
  (meridianlabs-ai/inspect_ai#582).
- Relocating per-shard scan results before deletion, so that scanner
  resume can reuse them (implementation plan, "Not this design").
