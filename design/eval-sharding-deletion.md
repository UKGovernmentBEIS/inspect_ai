# Eval sharding: deleting a merged log's shards

## Overview

`merge_eval_log_shards()` and `inspect log merge-shards` gain an option,
`delete_shards=True` (`--delete-shards`), that deletes the merged log's
`<name>.shards/` directory once the merge has left a complete
(`success`) merged log. Without the option the merge deletes nothing.
With it, the merge takes its lock, lists the shards directory once to
fix what it will delete, merges as usual, and then deletes what that
listing found, by name, each shard's current attempt last, and confirms
that nothing is left. A deletion that is interrupted is finished by
running the same merge with the option again. Like removing shards by
hand, the option is for a finished run that nothing else is touching;
the user is responsible for that. The typical use is to merge, check the
merged log, then run the same merge again with the option: it writes
nothing and deletes the shards.

## Why

The merge reads shards and writes the merged log and deletes nothing
unless asked (decision: Ransom, 2026-11-03). Today the user removes
`<name>.shards/` by hand once the merged log is checked, with `rm -r` or
`aws s3 rm --recursive` (the docs' "Merging" section, quoted under
"Documentation" below). That has two problems:

- Nothing checks that the merged log holds the shards being deleted: a
  shard that changed after the last merge, or a merge that ended
  incomplete, is deleted all the same.
- A launcher that shards a task down to one sample per machine has
  thousands of shard directories per run, and needs a cleanup step it
  can run unattended, recover from when interrupted, and branch on, as
  `--json` lets it do for the merge.

The implementation plan reserves this as PR 9: one rule for removing a
merged log's companion, offered by the merge as an option
([implementation plan, item 9](eval-sharding-implementation.md#implementation-plan)).

## Goals and non-goals

Goals:

- One public option on the merge API and the merge command, off by
  default.
- One rule, the same for local storage and S3, for when the merge may
  delete: the merged log is `success` and holds every current attempt
  in the shards directory.
- Deletion confined to what was listed: nothing outside
  `<name>.shards/`, nothing a symbolic link points to, no name absent
  from the listing that fixes the set.
- An interrupted deletion that the same call, run again, finishes.
- What users and launchers see: the command's report and the errors.

Non-goals:

- Protecting a run that something else is writing while the cleanup
  runs (workers, log edits or scoring, other merges). The option
  requires a quiescent run ("The quiescence requirement").
- Deleting the shards of an incomplete merged log (decision: Ransom,
  2026-11-19). A user abandoning a run removes its shards by hand.
- Finishing a removal started by hand. A partial `rm -r` or `aws s3 rm
  --recursive` is finished by hand.
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
and does not restate it:

- What a merge pass checks before it writes or returns (listing every
  shard, merging changed attempts, refusing stray logs, vanished shards
  and attempt regressions, the ledger count and the status):
  [implementation plan, "The merge"](eval-sharding-implementation.md#the-merge)
  and ["Validation"](eval-sharding-implementation.md#validation). A
  merge that finds no shard attempt left returns the merged log as
  recorded (step 10 of "The merge"), so a fully removed companion is
  already a supported state.
- The local lock and S3's conditional publish:
  ["Overlap guards"](eval-sharding-implementation.md#overlap-guards).
  Neither excludes writers other than merges (the viewer's log edits,
  `inspect score`).
- Worker threads that the merge waits for before it releases the lock,
  and cancellation:
  ["Cancellation and concurrency"](eval-sharding-implementation.md#cancellation-and-concurrency).
- How S3 names that S3 would read as another key are refused:
  ["Removing shards"](eval-sharding-implementation.md#removing-shards),
  "S3 names".
- The user docs (`docs/sharding.qmd`) tell users to delete the shards
  directory by hand.

The recursive file listing Inspect has for S3 skips keys ending in `/`
(directory markers, which the S3 console and sync tools create), so
deletion needs a listing that includes them.

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

`merge_eval_log_shards_async` takes the same keyword; the command takes
`--delete-shards`, a flag read only from the command line, like
`--allow-incomplete`. The default is `False`: the merge deletes nothing
unless asked. `ShardMergeResult` is unchanged: every way of not deleting
raises, so a call that returns with `delete_shards=True` deleted the
shards.

`delete_shards=True` with `allow_incomplete=True` raises `ValueError`
with the other argument checks, before any I/O. With `delete_shards`, an
incomplete set raises `ShardSetIncomplete` before anything is written or
deleted (decision: Ransom, 2026-11-19), and a local `<name>.shards` that
is a symbolic link raises `ShardSetError` before the merge writes
anything.

### The quiescence requirement

`delete_shards` is supported only on a finished run that nothing else is
touching: a `success` merged log, and no workers, log edits or scoring
of the merged log or shards, and no other merge of the run, from the
first deleting call until a call with the option returns, across any
interruption and rerun (decision: Ransom, 2026-11-19). This is the
user's responsibility, the same condition under which users remove
shards by hand today. The merge enforces nothing beyond its own lock and
the checks of its pass. If the requirement is broken, a concurrent
writer's work can be lost, as with a hand removal.

Cost check: free. Enforcing it would need every writer of a log (the
recorder, the viewer, `inspect score`, the merge on S3) to share a lock
or a conditional protocol with deletion, which none has.

### Ownership

The merge owns deletion, in a new module `log/_shards/_delete.py` called
by `merge_eval_log_shards_async` inside the same lock and filesystem
scope as the pass. No other code path deletes a companion.

### The set to delete

At the start of a deleting call, under the merge lock and before the
pass, one recursive listing of `<name>.shards/` fixes the set to delete:
every file, and on S3 every object under the companion's prefix with its
trailing `/`, directory markers included. Every S3 name in it must pass
the merge's S3 name check, or the call refuses before anything is
written or deleted. The pass then runs as usual; deletion runs only if
the pass returns a `success` merged log, and removes only entries of
that listing. No name absent from the listing is deleted: a new attempt
written between the listing and the pass is merged by the pass and left
in place, the confirming listing reports it, and a rerun with the option
finishes. Content rewritten under a listed name is deleted with it; that
is a write the quiescence requirement rules out.

Cost check: one recursive listing (a paginated sweep on S3, a walk that
does not follow links locally) on top of the pass's own listing.

### Deleting

- **By listed name, never by prefix.** Each entry of the set is deleted
  by its own name; locally, directories are then removed deepest first,
  each only if empty, the companion last. A symbolic link is removed as
  a link, and its target is never visited. Locally this is deletion's
  own unlink in `log/_shards/_delete.py`, which removes a symbolic link
  as a link and treats a missing entry as deleted; neither
  `AsyncFilesystem.delete_file` (which raises `FileNotFoundError` for a
  missing local file) nor fsspec's `rm` (which fails on a link to a
  directory) does both. On S3 it is the existing object delete.
- **Current attempts last.** Every other entry (older attempts,
  `scans/`, checkpoint directories, a `.buffer/`, directory markers) is
  deleted before any shard's current attempt. Cost: none, the same
  deletes in two groups.
- **Bounded.** At most 32 deletes in flight, run with the merge's
  ordinary bounded concurrency (`tg_collect`): the first failure or a
  cancellation cancels the remaining deletes and propagates. Deletes are
  one request per object on S3, which does not charge for them. A
  delete that finds its entry already gone counts as deleted.
- **Not owned threads.** Local deletes are a deliberate exception to the
  implementation plan's rule that every worker thread the merge starts
  goes through `run_owned` ("Cancellation and concurrency"): after a
  cancellation, an unlink already started may finish after the lock is
  released. It can only remove an entry of the listed set, and on S3 a
  delete already sent cannot be waited for either.
- **Confirmed.** After the last delete, one more recursive listing,
  directory markers included, must find nothing under `<name>.shards/`;
  otherwise the call raises, naming up to ten entries left and the
  total. Cost: one listing.

### Interrupted deletion

Guarantees:

- An interrupted deletion (an error, a cancellation, a crash) leaves
  every shard holding its recorded current attempt or no attempt, and
  never makes an older attempt current; the error or cancellation
  propagates. This holds because the current-attempt group starts only
  after every other delete has finished without error.
- A merge with the option, run again on the untouched run, writes
  nothing and finishes the deletion, whichever point it stopped at.
  After a crash of a local merge, its lock file stays, as for any
  crashed merge ("Overlap guards" in the implementation plan): the user
  checks that the process it names has stopped, deletes the lock file,
  then reruns.

Other states (a shard changed or added after an interruption, a plain
merge of a partly deleted companion) arise only when the quiescence
requirement is broken, or by the user's choice not to finish; the merge
handles them as today, refusing a companion where some shards have lost
their current attempt as vanished shards, with today's advice to delete
the shards directory or restore the files.

The deleting rerun takes the merge's existing path for a companion with
no attempts left, which it also takes when the only differences from
the ledger are shard directories with no attempt left: the stored status
must be `success`, a supplied selection must equal the recorded one, and
every shard that still has an attempt must match the ledger. No marker
of a deletion in progress is needed. Cost: none beyond the merge's own
classification.

### What users see

- **Messages say what must be corrected before retrying**: rename an S3
  name that S3 would read as another key; delete and rebuild a merged log
  changed outside the merge. On a deleting call, the existing
  incomplete-set message drops its hint to pass `allow_incomplete`,
  which cannot be combined with the option, and says that a run being
  abandoned has its shards removed by hand. A reported storage error
  during deletion says to run the merge again with the option. Exception
  types are the merge's existing ones, and a storage error keeps its
  type.
- **Cancellation and crashes.** Ctrl-C or cancellation propagates
  without a merge report or error envelope, as for any merge, and a
  crashed process reports nothing; the retry guidance then comes from
  the docs ("Documentation" below) and from a later merge's
  vanished-shard refusal.
- **Command report.** After the status line, `  shards: deleted <shards
  dir>` when `--delete-shards` was given.
- **`--json`.** The result object is unchanged. Errors use the existing
  kinds: `invalid_arguments` for `--delete-shards` with
  `--allow-incomplete`, `incomplete` for an incomplete set, `refused` for
  a refused name, a refused shard set or a non-empty confirming listing,
  `conflict` for the lock, `storage_error` for a failed delete.
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
> scoring of the merged log or shards, and no other merge of the run.
> Keep the merged log and its shards unchanged from the first deleting
> call until cleanup succeeds, including between retries. Something
> written to the run while the shards are deleted can be lost, as when
> you delete them by hand. Deletion cannot be undone, except from object
> versions on a versioned S3 bucket.
>
> If deletion is interrupted, part of the `.shards` directory remains and
> later merges may refuse it. Merge again with `--delete-shards` to
> finish.
>
> You can still delete the `.shards` directory by hand (`rm -r`,
> `aws s3 rm --recursive`); once all of it is gone, later merges return
> the merged log as it is. If a removal by hand stops part way, finish
> it by hand.
>
> When a later unsharded run of the task supersedes a merged log, the
> merged log and its `.shards` directory stay until you remove them.

The "Eval sets" section's last sentence becomes "Then move the `.shards`
directory out of the log directory, or delete it with
`--delete-shards`, before you run an eval set there." The command
section lists `--delete-shards` and its report line, and the error-kind
table's `refused` row mentions deletion.

## Alternatives considered

- **Enforce quiescence.** Conditional S3 deletes on each object's listed
  ETag, a re-check of the merged log's ETag and local replace detection
  would narrow the windows for concurrent writers, but not close them:
  the viewer and `inspect score` rewrite logs outside the merge's lock,
  and a merge that publishes in between still lets every delete succeed.
  Closing them needs a protocol shared by every log writer.
- **Re-check after the pass** (read the merged log back, list every
  shard again) or **validate a merged log that a deleting rerun keeps**
  (recount members, plan its status). Each repeats checks the pass makes
  or guards only against edits the quiescence requirement already rules
  out.
- **Check that every attempt in the set was listed by the pass.** Taking
  the listing before the pass makes it unnecessary: no name created
  after the listing is in the set.
- **Finish a removal started by hand.** A partial `aws s3 rm
  --recursive` keeps no order and can leave an older attempt current,
  and the rerun path cannot check that the merged log is unchanged since
  its last merge. Users finish a hand removal by hand.
- **A `shards_deleted` result field and `--json` key.** Every way of not
  deleting raises, so on any return it would equal the argument.
- **A separate `delete_eval_log_shards(log)` that needs no task.** A
  second entry point needs its own lock, its own handling of a merged log
  that is behind its shards and its own error envelope; the merge has
  all three, and merging first brings a stale merged log up to date
  before the shards go.
- **Deletion of an incomplete merged log.** It would freeze the log: no
  later merge could add the missing samples or change the selection.
- **Unconditional prefix deletion** (`fs.rm(recursive=True)`, `aws s3 rm
  --recursive`). It deletes entries the listing never saw and gives no
  ordering, so an interruption can leave an older attempt current.
- **A marker for a deletion in progress** (a file in or beside the
  companion, or a field in the merged log). The ledger and the listing
  identify an interrupted deletion; a file in the companion would break
  the rule that it holds only shard files, and a field would mean a
  publish before every deletion.
- **Leave S3 directory markers.** The recursive file listing skips them,
  so the companion would never list as empty and the confirming listing
  could not hold.
- **Delete S3 objects by their raw listed key** rather than by URL. The
  name check already refuses every key a URL would misread, as the merge
  does.
- **Let a merge without the option accept a partly deleted companion.**
  It changes existing merge behaviour, and a shard directory deleted by
  hand would no longer be flagged.
- **Delete by default.** Deletion is the one step that cannot be undone
  after a bad merge.

## Compatibility and migration

No migration required.

- **API.** `delete_shards` is a new keyword, default `False`. Existing
  callers and `ShardMergeResult` are unchanged.
- **CLI.** `--delete-shards` is new, and the report gains a line when it
  is given; the `--json` result object is unchanged.
- **Messages.** The incomplete-set message on a deleting call and the
  `eval_set()` refusal change; tests matching their text change with
  them.
- **Log format.** None. Deletion writes nothing to the merged log; no
  schema or `ts-mono` change.

## Security

Untrusted input that reaches deletion:

- **Names in the shards directory**, chosen by workers or anyone who can
  write the log directory. Deletion stays inside `<name>.shards/`:
  locally the listing does not follow symbolic links, a link is removed
  without visiting its target, and a companion that is itself a link is
  refused. On S3 only keys under the companion's prefix with its
  trailing `/` are listed (so not `<name>.shards-x/`), and every name
  passes the S3 name check before anything is written or deleted, so no
  key is deleted in place of another.
- **The merged log's ledger** decides whether deletion runs, never what
  is deleted: the set comes only from listing the companion.
- **Credentials.** Deletion uses the caller's storage credentials, like
  the merge, and consults no access policy; the viewer, which has one,
  does not delete companions.

## Testing

In `tests/log/test_shards.py`, on a local path and on S3 (the `mock_s3`
fixture). The basic removal tests on each storage, the marker test, the
lock test and the cancellation test also run under Trio (`--runtrio`);
the rest run under asyncio only. No test needs network, Docker or a
model provider.

- `test_merge_deletes_nothing_by_default`: a merge without the option
  leaves the companion as it was.
- `test_delete_shards_removes_companion`: everything in the companion,
  older attempts and ancillary directories included, is deleted, and a
  later merge returns the merged log as recorded.
- `test_delete_shards_removes_s3_directory_markers`: markers at every
  level are deleted and the companion lists as empty.
- `test_delete_shards_after_unchanged_merge`: a deleting merge after a
  checked merge writes nothing and deletes the shards.
- `test_delete_shards_merges_shard_changed_since_merge`: a shard changed
  since the last merge is merged first, then deleted.
- `test_delete_shards_leaves_attempt_written_after_listing`: an attempt
  created under a new name after the listing is not deleted, the call
  raises naming it, and a rerun finishes.
- `test_delete_shards_with_allow_incomplete_is_refused`: `ValueError`
  before any I/O.
- `test_delete_shards_refuses_incomplete_set`: nothing is written or
  deleted, and the message does not suggest `allow_incomplete`.
- `test_delete_shards_interrupted_then_finished`: after an interruption
  at each stage, every shard holds its recorded current attempt or none,
  and a deleting rerun finishes (after a simulated crash, once the stale
  local lock is removed).
- `test_delete_shards_rerun_refuses_partly_deleted` (parametrized): on a
  companion left partly deleted by an interruption, a deleting rerun
  whose stored status is not `success`, whose supplied selection differs
  from the recorded one, or whose remaining shard has changed is
  refused, and nothing is written or deleted.
- `test_plain_merge_refuses_partly_deleted`: a merge without the option
  refuses the same partly deleted companion as vanished shards.
- `test_delete_shards_does_not_follow_symlinks` (local): link targets
  survive, and a linked companion is refused before anything is written.
- `test_delete_shards_stays_in_prefix` (S3): sibling prefixes survive.
- `test_delete_shards_refuses_unsafe_s3_name`: refused before anything is
  written or deleted, with the advice to rename.
- `test_delete_shards_storage_error`: a failed delete keeps its error
  type and says to rerun with the option; the command reports
  `storage_error` with that advice.
- `test_delete_shards_holds_lock` (local): a merge started during
  deletion is refused with `WriteConflictError`. It does not check that
  no unlink runs after a cancellation ("Not owned threads" above).
- `test_delete_shards_cancelled`: after cancellation every shard holds
  its recorded current attempt or none, and a rerun completes.
- In `tests/test_eval_set.py`,
  `test_eval_set_accepts_log_dir_after_delete_shards`: the log directory
  is accepted once the shards are deleted.
- Command tests beside the existing `merge-shards` tests: the report
  line, an unchanged `--json` result, and `--delete-shards
  --allow-incomplete` as `invalid_arguments`.

## Implementation plan

One PR:

- `log/_shards/_delete.py`: the listing, the S3 name check, deletion
  (with its own local unlink) and the confirming listing.
- `log/_shards/_api.py`: the option, the argument check, the listing
  before the pass, the deleting rerun's acceptance of shard directories
  with no attempt left, and the incomplete-set message on a deleting
  call.
- `src/inspect_ai/_util/asyncfiles.py`: a recursive listing that
  includes S3 directory markers, if none exists, leaving existing
  listings unchanged.
- `src/inspect_ai/_cli/log_merge_shards.py`: `--delete-shards`, the
  report line and the rerun advice for a failed delete.
- `src/inspect_ai/_eval/evalset.py`: the refusal message.
- `docs/sharding.qmd` ("Documentation") and the tests above.

## Open questions

None.

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
