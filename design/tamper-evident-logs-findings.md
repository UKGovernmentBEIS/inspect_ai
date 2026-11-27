# Tamper-evident logs: design and findings

This note describes the tamper-evident logs prototype on branch
`epatey/tamper-evident-logs-prototype`: what the store and the validator do,
what they guarantee, why the design is as it is, and where it stops. The
user docs are `docs/tamper-evident-logs.qmd`. The feature is experimental.

The tests run against a local S3 emulator (moto server, in a subprocess with
IAM enforcement on). Real S3 behavior that moto cannot show is marked as
such below.

## Summary

An eval writes each sample's events to an add-only store while it runs. The
store is an S3 bucket in a separate account where the eval host can add
objects but cannot read, change or delete them. The `.eval` file is then a
copy, and `inspect validate` compares the copy with the store.

The plan asked four questions. The answers, with the runs that back them,
are in [Probe results](#probe-results).

| Question | Answer |
| --- | --- |
| 1. No legitimate event version is written after a boundary stored the event complete | False for bridged host tools that a scaffold calls one at a time. True for every other path that was run. |
| 2. Every buffered event has a uuid | True. |
| 3. A sample rebuilt from buffer rows matches the sample logged from memory | True, when no warning is logged from a worker thread during the sample. |
| 4. Time per boundary write | Against local moto: median 4.5 ms with 1 sample, 34 ms with 10 samples at once. Real S3 is not measured. |

## The store

All keys are under the store prefix:

```
<eval-id>/start
<eval-id>/closing
<eval-id>/<sample-id>.<epoch>/<attempt>/<seq>
<eval-id>/<sample-id>.<epoch>/<attempt>/closing
rescores/<eval-id>/<rescore-id>/start
rescores/<eval-id>/<rescore-id>/<sample-id>.<epoch>
rescores/<eval-id>/<rescore-id>/closing
```

The records are JSON models in `src/inspect_ai/log/_addonly/_records.py`.
Each record holds the eval's nonce, a secret that the eval makes at start and
keeps only in memory.

- `StartRecord`: the eval id, the nonce, and `prior_eval_id` (the eval that a
  retry copied samples from).
- `SampleRecord`: one attempt's sample buffer rows since its previous record
  (events, attachments, message and call pools), with its sequence number.
- `SampleClosingRecord`: the number of sample records the attempt wrote, and
  the sample's scores.
- `EvalClosingRecord`: the eval's status, stats and results, every sample
  attempt the eval started (`samples`), and `logged`, the
  `<sample-id>.<epoch>` of each sample in its `.eval` file when the eval
  finished.
- `RescoreStartRecord`, `RescoreSampleRecord` and `RescoreClosingRecord`: see
  [How a rescore writes](#how-a-rescore-writes).

A sample id in a key is URL-encoded with `quote(safe="")`, so a `/` in the id
cannot add a key level. The epoch is the digits after the last `.`, so a `.`
in the id needs no encoding.

## How an eval writes

The eval writes to the store when it gets `tamper_evident_store` (`eval()`,
`eval_set()`, `eval_retry()`) or `--tamper-evident-store` (`inspect eval`,
`eval-set`, `eval-retry`). Without the option, it writes nothing to the
store. The option needs `log_realtime`, which is on by default, because the
records come from the sample buffer.

### Start

`TaskLogger.log_start` calls `EvalRecordWriter.start` before any sample
starts. It writes the start record, then runs the store check
(`AddOnlyStore.put_start_and_check`):

1. The same put again must get 412.
2. A read and a delete of the record must get `AccessDenied`.
3. The Object Lock settings must be enabled, with default retention in
   COMPLIANCE mode.

If any step fails, the eval fails. The check finds setup mistakes. It is not
a security check, because a compromised host can report anything.

### Boundaries

A sample writes to the store at these points, and waits until S3 confirms
each write:

- Before each generate request, inside the `send()` that `Model._generate`
  defines, so a retry or a resend of the request also writes first
  (`model/_model.py`).
- Before each stage of tool calls (`model/_call_tools.py`).
- Before each bridged host tool runs (`agent/_bridge/sandbox/host_tool.py`).
- At sample end, after scoring (`_eval/task/run.py`): the last rows, then the
  sample closing record.

`SampleRecordWriter.write` reads the rows the sample inserted since its last
record, and takes the next sequence number, with no `await` between the two
steps. So numbers follow row order without a lock. It then puts the record,
and waits until every record numbered up to the last one taken is
confirmed. Sub-agents of one sample share the writer, so their puts overlap.
A boundary with no new rows puts nothing, but it still waits for the numbers
already taken, because a record in flight can hold rows that its own agent
recorded.

### Failures

A put uses `If-None-Match: *`. Botocore's standard retries try it up to 8
times (`S3_MAX_ATTEMPTS`) on a network error, throttling or a server error.
Any 412 fails the write, also a 412 after a retried put: the host cannot read
the store to tell its own lost put from a record that another writer added.
When botocore retried the put, the error message says that the record may be
the eval's own earlier put (`_put_error` reads
`ResponseMetadata.RetryAttempts`).

A failed write raises `AddOnlyStoreError`. The sample gets no retry and no
score, and the eval fails whatever `fail_on_error` and `retry_on_error` say
(`_eval/task/run.py`, `_eval/task/error.py`). After a failed put, the
attempt writes nothing more: later boundaries raise, and `close` writes no
closing record.

An event that the sample buffer cannot insert does not reach the store. The
transcript logs the error and the sample goes on, and the validator then
reports `event_mismatch`.

### Retry time

If every try of a put reaches the 60 s connect and read timeouts, a failing
write takes about 17 minutes, the waits between tries included. The user
docs give this bound ("Errors and Cancellation"). The figure is for
botocore 1.43.117 and changes with its retry behavior.

### Cancellation

With the store on, two shields keep an honest cancelled run valid:

- `SampleRecordWriter._put` shields each put. Without it, a pending cancel
  can stop a put after its sequence number was taken, and the sample is then
  logged with no closing record (`unstored_sample` in
  `test_eval_retry_after_cancel_at_boundary_validates`).
- In `_task_run_sample_attempt` (`run.py`), `completion_scope` shields the
  sample's completion through its closing record and its log write. Without
  it, a sample cancelled after its closing record and before it is logged
  gives `missing_sample` in the retry
  (`test_eval_retry_after_cancel_in_close_validates[closing]`). The
  sample's `on_sample_event` hooks are drained before the shield, and the
  shield drops after the sample is logged, so hooks, scanners and sidecar
  teardown stay cancellable
  (`test_eval_retry_after_cancel_in_sample_event_hook_validates`). A sample
  cancelled while its hooks are drained stops before its closing record, as
  a sample cancelled before scoring does.

Each shield was removed in a copy of the tree to confirm the failure it
prevents. The cost is that an eval stopped during an S3 outage waits while
botocore retries these writes.

### End

The sample closing record is written after scoring and before the sample is
written to the `.eval` file, for every outcome except a retry of the
attempt. Once the sample is logged, `_task_run_sample_attempt` clears the
sample's writer (`init_sample_record_writer(None)`), so a model call in a
scanner or an `on_sample_end` hook adds no record after the closing record
(`test_model_call_in_sample_end_hook_validates`). `TaskLogger.log_finish`
writes the eval closing record after the `.eval` file is finished, so a
store outage still leaves a finished copy.

The eval closing record's `logged` list is the key of each sample in
`recorder.sample_summaries(eval)`, read under the flush lock after any prune.
So a pruned record, and an admission copy that failed or was cancelled
before its summary, are not listed.

## How a rescore writes

`inspect score` and `score()` take `--tamper-evident-store` and
`tamper_evident_store`. A rescore writes with the eval's nonce, which it
takes from the `INSPECT_TAMPER_EVIDENT_NONCE` environment variable, never
from a CLI option. It fails before it scores when the option is set and the
variable is not. `inspect validate --nonce <eval-id> --store ...` reads the
nonce from the eval's start record with one `get_object`, using the
validator's read access. So the rescorer needs only add rights, like the
eval host.

A rescore has its own id and writes:

- `start`: eval id, rescore id, nonce and action (`append` or `overwrite`),
  with the same store check as an eval's start record.
- One record per sample, written after the sample's scorers finish and
  before the sample is logged: its new scores, the events its scorers added
  (attachments resolved), and `built_on`, the sample's latest rescore before
  this one.
- `closing`: the new results.

Before its scorers run, the rescore adds an info event to each sample's new
scorers span (`source="tamper_evident_rescore"`, a `RescoreMarker`). The
marker names the eval id and the rescore id, and holds `chain_length`, the
number of rescores in the sample's chain including this one. The rescorer
takes the latest marker from its input (`latest_marker`, the one with the
longest chain) for the sample record's `built_on` and the new marker's
length.

## What the validator checks

`inspect validate LOG_DIR --store s3://bucket/prefix` (or
`INSPECT_VALIDATE_STORE`) runs `validate_store`. It takes the store location
from its own configuration, never from a `.eval` file. It exits non-zero on
any finding. `--verbose` lists each record with its S3 arrival time.

Store checks:

- `settings`: Object Lock in COMPLIANCE mode, and a bucket policy statement
  that denies a put without `If-None-Match`.
- `overwrite`: a key with more than one version, or a delete marker. The
  validator reads the earliest version (S3 lists versions newest first).
- `missing_start`, `nonce`, `malformed_record` (a key the eval never writes,
  a record it cannot read or of the wrong type, or rows that stop the sample
  rebuild), `unlisted_attempt` (an attempt the eval closing record does not
  list), `record_count` (a closed attempt's records not numbered 1 to its
  count), and `late_event_version`.
- A record that S3 refuses to return, for example one in an archive storage
  class (`InvalidObjectState`), is a record the validator cannot read. A
  refusal that is about the validator's credentials or the bucket
  (`AccessDenied`, `NoSuchBucket`, an expired or invalid key) stops the
  validator instead (`_STORE_READ_REFUSED`). S3 also returns `AccessDenied`
  for a record encrypted with a KMS key the validator cannot use, so
  eval-host keys can stop the validator this way; it fails, it does not
  pass.

`.eval` checks, for every `.eval` file in the log directory with the eval's
id:

- `unstored_eval` and `missing_eval_file`.
- `unstored_sample`: a `.eval` sample with no closed attempt in the eval, or
  in the prior evals it copied from, or one that the eval closing record's
  `logged` list does not have.
- `missing_sample`: a closed sample, or a sample in the eval closing
  record's `logged` list, that is not in the `.eval` file.
- `event_mismatch` and `score_mismatch`: the sample's events and scores
  against the records, after the rescores the sample names.
- `missing_eval_closing` and `eval_mismatch`: the file's status and stats
  against the eval closing record, and its results against the eval closing
  record or the latest rescore's closing record.
- `missing_rescore` and `rescore_mismatch`.

The validator rebuilds a sample's events with the code that logs a sample
whose events were evicted: it inserts the stored rows into a new sample
buffer and reads them back with `open_sample_history` and
`materialize_streaming_sample`. It reads the `.eval` sample with attachments
resolved in full, and compares JSON text (`_same_json`), so NaN equals NaN
and `1` differs from `true`. It finds `.eval` samples by summary and by zip
member name, so a member added under a new name is reported.

These lines are listed before the count and do not change the exit code:
`stopped`, `not_logged`, `prior_without_file`, `rescored` and
`original_results`.

## Guarantees

Every record under the prefix is checked, whether or not its attempt or
eval closed. Every sample in a `.eval` file must match a closed attempt of
its own eval or, if it has none, of the nearest earlier eval along the
prior-eval chain that closed it, after each rescore it names. Every closed
sample, and every sample in the eval closing record's `logged` list, must be
in the `.eval` file, unless the eval stopped before it finished the file.
When the eval has a closing record, every sample in the `.eval` file must be
in its `logged` list. A finished `.eval` file must match its eval closing
record. Its results must match its latest rescore's closing record, or the
eval closing record when it is not rescored. An
attempt, eval or rescore with no closing record is listed as `stopped`, not
reported as a finding.

## Design decisions

1. **The store location is an eval option, and the log does not record it.**
   A retry needs the option again. The validator takes `--store`, never a
   value from a `.eval` file, so an editor of the file cannot point the
   validator at another store.
2. **One store prefix per log directory.** The validator reports every eval
   under its prefix that has no `.eval` file, so this scope needs no new
   option. The listing matches `prefix/`, so `evals` does not match `evalsx`
   (`test_prefix_per_log_dir_scopes_validation`).
3. **A synchronous boto3 client in a worker thread**, from a new boto3
   session per eval. It works under asyncio and trio, and avoids fsspec. A
   new session is needed because the default session keeps the first
   credentials it found. The pool has 50 connections (see
   [Events lost when a worker thread logs a warning](#events-lost-when-a-worker-thread-logs-a-warning)).
4. **Botocore's standard retries, with any 412 a failure.** One retry
   mechanism, with known bounds. The plan leaves the time limit open.
5. **No lock in the writer.** Rows and number are taken together, puts
   overlap, and each boundary waits for every earlier number. A lock per
   sample made sub-agents wait for each other's puts.
6. **A failed write stops the eval.** A sample cannot go past a boundary
   that the store did not confirm. A failed buffer insert does not stop the
   sample. Eric accepted this on Nov-27 as a rare case, and the validator
   reports the result as `event_mismatch`.
7. **The eval closing record comes after the `.eval` file is finished**, so
   an outage at the end still leaves a finished copy. The cost is
   `missing_eval_closing` for an honest run whose last write fails.
8. **Events are the record.** The validator compares events, scores, which
   samples exist, and the eval's status, stats and results. Messages are a
   copy of what the model events hold, so they are not compared. Eric kept
   events as the record.
9. **A stopped attempt or eval is listed, not a finding.** Eric, Nov-25: "I'd
   like the validator to record that it stopped rather than failed
   validation. How to interpret what that means is a separate issue". A
   sample in a `.eval` file still needs a closed attempt, so a compromised
   process cannot skip a closing record and then edit the sample's confirmed
   events in its copy. A finished `.eval` file still needs its eval closing
   record.
10. **A retry names one prior eval.** Every sample that one eval copies
    comes from the same earlier eval, so the start record's
    `prior_eval_id` is enough. The validator follows the chain of start
    records to the nearest eval that closed each copied sample.
11. **The eval closing record lists the samples in the `.eval` file.** The
    `logged` list states what the `.eval` file must hold, so the validator
    does not infer a retry's copies from its selection. The list holds every
    sample in the log, so the logger does not track which samples it copied.
    The list is per attempt, so `task_retry_attempts` and `eval_set` retries
    need no prior eval id on the logger.
12. **A copy that a stopped retry kept is compared with the nearest earlier
    eval that closed it.** A retry seeds its `.eval` file with the prior
    eval's samples, also the errored ones it runs again. When it stops
    while it runs one again, the copy stays in the file, so comparing it
    with the retry's own attempt would fail an honest run.
13. **A missing `.eval` file that a later eval names is listed, not a
    finding.** `eval_set`'s `retry_cleanup` deletes the failed attempt's
    file (Eric's decision). The eval shows as `prior_without_file`, because
    eval-host keys can forge the later eval.
14. **Rescore authority is the eval's nonce** (Eric, Nov-25). A separate
    rescorer role is not needed, and a rescore record without the nonce is
    a `nonce` finding.
15. **The rescore marker is an event, and the latest marker has the longest
    chain.** An event reaches the `.eval` file with no log schema change,
    with append, overwrite and `--stream`. Event order does not show the
    latest rescore: an append moves its events under the old scorers span,
    and an overwrite can remove the marker that an earlier append's marker
    builds on.
16. **`built_on` is in each rescore sample record, not in the start
    record.** With `--stream`, the rescorer has only the log header when it
    writes the start record. The closing record does not list the rescored
    samples, because the nonce covers forged records and `rescore_mismatch`
    covers a sample put back to its copy from before a rescore.
17. **A rescore in a sample's chain must be of an eval the sample's copy
    came through**, from the file's eval back to the eval that closed the
    attempt. Otherwise a rescore copied from another eval in the same store
    would pass (`test_rescore_of_another_eval`).
18. **The validator applies rescores with `inspect score`'s own functions**
    (`_get_updated_scores`, `_get_updated_events`), so the event order that
    a rescore produces is reproduced, not checked against a second
    implementation.
19. **Arrival times are only printed.** No check uses them. For a record
    uploaded in parts, S3 lists the time its upload started (AWS docs, not
    testable on moto). Such a record still needs the nonce.
20. **The validator does not check bucket versioning.** Object Lock turns
    versioning on, and real S3 refuses to suspend it on an Object Lock
    bucket.
21. **Rescore records under an eval id with no other records give no
    `nonce` finding.** They cannot affect a comparison, because a sample can
    name only rescores of evals that its copy came through, and there is no
    eval start record to check their nonce against. Each rescore is still
    read: one with no rescore start record gives `missing_start`, and an
    unreadable record gives `malformed_record`.

## Honest runs that validate

The store tests run each of these end to end against moto and validate with
0 findings:

- `retry_on_error`: the failed attempt has no closing record and is listed
  as `stopped` (`test_retry_on_error_validates`).
- `task_retry_attempts`, `eval_retry`, and a retry of a retry
  (`test_task_retry_attempts_validates`, `test_eval_retry_validates`). The
  tests assert each eval's `logged` list.
- `eval_set` retries with and without `retry_cleanup`, narrower retries by
  `sample_id` or epochs, a limited dynamic feed, a pruned prior record, and
  an admission copy that fails or is cancelled
  (`test_eval_set_retry_validates`, `test_eval_set_narrower_retry_validates`,
  `test_eval_set_limited_feed_retry_validates`,
  `test_eval_set_retry_pruned_sample_not_copied`,
  `test_eval_set_limited_feed_retry_interrupted_copy_validates`).
- Rescores: append, overwrite, chains of both, `--stream`, and a retry of a
  rescored log (`test_rescore_validates`,
  `test_eval_retry_of_rescored_log_validates`).
- Stopped runs: a cancel while a hook waits, a retry that waits for a sample
  slot, a retry that stops while it runs a sample again, and a host that
  crashes before its first `.eval` write or with samples still buffered
  (`test_eval_stopped_while_hook_waits_lists_stopped`,
  `test_eval_stopped_while_retry_waits_lists_stopped`,
  `test_retry_stopped_while_hook_waits_validates`,
  `test_eval_host_crash_lists_stopped`). These list `stopped` or
  `not_logged` lines.

## Validation edge cases

The user docs (`docs/tamper-evident-logs.qmd`) give one line for each of
these cases. This section has the full text.

### Lost samples and closing records

- **Lost samples.** Each sample attempt writes a closing record at its end, and each eval writes one after it finishes its `.eval` file. A sample in the `.eval` file must have an attempt with a closing record, or the validator reports `unstored_sample`. A sample with a closed attempt must be in the `.eval` file, or the validator reports `missing_sample`. A finished `.eval` file must have its eval closing record, or the validator reports `missing_eval_closing`. Each attempt and eval with no closing record is also listed as `stopped`, and the validator still checks every record that it wrote.

- **Honest runs with a missing closing record.** A sample stops writing without a closing record when its write to the store fails. The sample is still in the `.eval` file with its error, so the validator reports `unstored_sample` for a run that was not changed. An eval that finishes its `.eval` file and then cannot write its eval closing record (for example during an S3 outage) gives `missing_eval_closing` in the same way.

### Attempts and evals that stop

- **An attempt or eval that stops writing.** A compromised process can stop writing a sample attempt before its closing record. The validator lists the attempt as `stopped` and does not compare its events with the `.eval` file. If the sample is not in the `.eval` file, or the process writes a later attempt of the sample with a closing record, the stopped attempt's events show only in the store. In the same way, an eval with no closing record and a `.eval` file that is not finished is listed as `stopped`, and its status, stats and results are not compared.

```
stopped LdM2ww.../s0.1/1: No closing record: cut short, or its host stopped writing.
```

The line means that the store has no closing record for the attempt or the eval. The attempt or the eval was cut short, for example by a cancel, an error in another sample, a crash or a retry, or its host stopped writing. The validator still checks every record that it wrote. An eval that stopped before it wrote its `.eval` file has only this line.

- **A sample that a retry stopped running.** A retry copies the samples that the earlier eval completed with an error into its `.eval` file before it runs them again. If the retry stops writing such a sample, its `.eval` file can keep the earlier eval's copy. The validator compares that copy with the records of the nearest earlier eval that closed the sample, so the retry's own stored events for the sample are not compared. The retry's attempt is listed as `stopped`.

- **What a `stopped` line means.** How to interpret a stopped attempt or eval is an open question. It can come from an honest cancel or crash, but a compromised host can also stop writing to hide what a sample did. The validator lists it and does not decide. The same applies to a `not_logged` line.

### Samples not logged by an eval that stopped

- **Samples deleted from the `.eval` file of an eval that stopped.** Inspect writes samples to the `.eval` file in groups of several samples (the `log_buffer` option), not one at a time. So when an honest eval host dies, the store usually has closed samples that are not in the file. When an eval has no closing record and its `.eval` file has the status `started`, the validator lists each closed sample that is not in the file as `not_logged`. So if someone deletes samples from the `.eval` file of such an eval, the validator shows a `not_logged` line for each sample, not a finding. A sample that such an eval copied from an earlier eval's log shows no line at all, because only the eval closing record lists those samples. An eval with no closing record, no closed sample attempt and no `.eval` file is listed only as `stopped`. An eval with a closed sample attempt and no `.eval` file is a `missing_eval_file` finding, because an honest eval writes its `.eval` file before any sample runs.

```
not_logged LdM2ww.../s0.1/1: Closed, not in the .eval file: the eval stopped before it logged the sample.
```

The line means that the sample attempt wrote its closing record, and the eval stopped before the sample was in its `.eval` file. The eval has no closing record, and its `.eval` file has the status `started`.

### Evals with no `.eval` file that a later eval names

- **A deleted `.eval` file of an eval that a later eval names.** When a later eval's start record names an eval as the one it retried, the validator does not report a missing `.eval` file for the earlier eval. It lists the eval as `prior_without_file`, which does not change the exit code. Eval-host keys can forge a later eval that names any eval. So when someone deletes the `.eval` file of any eval, successful or not, and forges such an eval, the deletion shows only in this list, not as a finding. If the forged eval has its own records of the same samples, the validator compares the samples with these records, not with the records of the earlier eval. The earlier eval's records stay in the store.

An eval with no `.eval` file that a later eval names as its prior eval also shows as one line before the count. It is not a finding. Make sure that you ran the later eval as a retry of the eval, because eval-host keys can forge the later eval:

```
prior_without_file MBjNiQ...: No .eval file; EMhV3K... names it as its prior eval.
```

`eval_set()` deletes the `.eval` file of a failed attempt after its retry (`retry_cleanup`, on by default). This does not cause a finding: the retry's records name the failed attempt's eval, and the validator still uses that eval's records to check the samples that the retry reused. The validator lists the failed attempt's eval as `prior_without_file`.

### Samples a retry copied

- **Samples a retry copied.** A retry copies the samples that it selects from the earlier eval's log into its own before it runs any sample, with or without an error. A dataset that adds samples while it runs, with `limit` set, copies each one when it admits it. The retry's eval closing record lists each sample in its `.eval` file when it finished, the copies included, and each one must still be in that file, or the validator reports `missing_sample`. A sample in the file that the list does not have, such as one of the earlier eval's samples that a narrower retry did not select, is an `unstored_sample` finding. A copy that the retry ran again and closed is compared through that attempt instead. A retry with no eval closing record has no list, so a copied sample deleted from its `.eval` file, or added to it, is not reported.

## Known limits

What a pass shows:

- A pass shows that the `.eval` file matches what was stored. It does not
  show that the run was honest.
- A process compromised while the eval runs knows the nonce. It can write
  false events, a later attempt, a fake retry that names a real eval, or a
  rescore. Events that a sample recorded after its last confirmed write and
  before the compromise are not protected.
- A compromised eval host can write the records of an eval that never ran.
  The validator reports it only if no `.eval` file has its eval id.
- A retry's `prior_eval_id` is a claim by the retry's eval host. The earlier
  eval's records are protected, so a wrong id gives a finding for each
  reused sample.
- The validator does not compare the eval spec and plan, each sample's
  messages, output and error, the sample summaries, tags and metadata,
  invalidation, or `log_updates`.

Stopped runs:

- A `stopped` line can be an honest cancel or crash, or a compromised host
  that stopped writing. The validator does not decide, and the same applies
  to `not_logged`. A stopped attempt's events, and a stopped eval's status,
  stats and results, are not compared with the `.eval` file.
- A retry that stops while it runs a sample again can keep the earlier
  eval's copy. The validator compares that copy with the nearest earlier
  eval that closed the sample, so the retry's own stored events for the
  sample are not compared.
- A sample deleted from the `.eval` file of an eval that stopped (no eval
  closing record, status `started`) gives a `not_logged` line, not a
  finding. A sample that such an eval copied from its prior log gives no
  line.
- A retry with no eval closing record has no `logged` list, so a copied
  sample deleted from its `.eval` file, or a prior eval's sample added to
  it, is not reported.

Retries:

- A deleted `.eval` file of an eval that a later eval names gives a
  `prior_without_file` line, not a finding. Eval-host keys can forge such a
  later eval.

Rescores:

- A rescore is a claim by whoever held the eval's nonce and could add to the
  store. A nonce once handed out works for every later rescore of the eval.
  The validator lists each rescore and does not vouch for it.
- If a retry was not rescored, a sample it reused can be replaced with the
  earlier eval's copy from before or after one of that eval's rescores, and
  the validator passes it. `rescore_mismatch` compares only the rescores of
  the file's own eval, because the store does not record which rescores a
  retry's copy came with.
- A nonce holder's rescore sample record whose events are not one top-level
  scorers span, or an overwrite whose sample has a scorers span with a
  parent that is not in the events, stops the validator with an error in
  `_get_updated_events` when a `.eval` sample names that rescore. Removing
  that marker from the `.eval` sample clears it.
- A rescore without the store option fails validation, as any other change
  to the scores or events does.
- The rescore does not validate its input. An input edited before the
  rescore still gives a finding, because the validator checks the sample's
  other events and kept scores against the original records. An edit that
  the rescore replaces, such as a score that an overwrite drops, leaves
  nothing in the output to report.

Honest runs that give a finding:

- A failed write to the store gives `unstored_sample`. In a retry that runs
  a sample again that the prior eval closed with an error, it gives
  `event_mismatch` "(reused from ...)" instead, because the retry's copy has
  no closed attempt.
- A failed write of the eval closing record, after the `.eval` file is
  finished, gives `missing_eval_closing`.
- `logged` comes from the recorder's sample summaries. If an admission copy
  writes the sample to the `.eval` file and then fails to write its summary,
  and the retry still finishes, the sample is not listed, and the validator
  reports `unstored_sample`. A review found the failed summary write with
  fault injection.
- An event that the sample buffer cannot insert (a full disk, a database
  error), or that skips the buffer because a worker thread logged a warning
  during the sample, never reaches the store. The validator reports
  `event_mismatch`.
- A scaffold that calls bridged host tools one at a time gives
  `late_event_version` (see [Answers, 1](#1-no-legitimate-late-event-versions)).
- A tool that changes the eval's status, stats or results after the run
  gives `eval_mismatch`.

Not handled:

- Merged shard logs, and samples removed during the run.
- Checkpoint resume: the validator does not check a resumed sample's
  restored state against the earlier eval's records.
- Validation cost: the validator reads every record of every eval under the
  prefix, with one S3 request per record.
- The sentinel sidecar's output and timing updates can be late versions when
  sub-agents of one sample run at once (code reading, not run).

## Probe results

### Answers

#### 1. No legitimate late event versions

The validator flags any version of an event that comes in a later record
than one where the event was stored complete (not `pending`).
`test_late_event_version_flagged` shows that the rule flags a late version
and accepts pending-then-complete and several versions in one record.

No late version was found in:

- `test_agent_eval_validates`: a react agent with two sub-agents run as
  tools in one parallel stage, 1 sample. The test also asserts that some
  tool events were stored pending and completed in a later record.
- `test_samples_at_once_validate`: the same agent, 3 samples x 2 epochs
  run at once.
- `test_streaming_eval_validates`: pending model versions with partial
  output, then the complete version.
- `test_host_tools_against_addonly_store[parallel]`: bridged host tools
  called two at a time.
- A timing script, not in the branch: 40 samples per run.

The model event's second complete version (timing fields set and the event
sent again) was in the same record as the first in every run.

Three open cases:

- **Bridge `message_id`.** `agent/_bridge/types.py` sets the tool event's
  `message_id` when the scaffold's next request arrives. When the scaffold
  calls bridged host tools one at a time, the second call's boundary stores
  the first call complete, and the update comes in the next record.
  `test_host_tools_against_addonly_store[serial]` gets 2
  `late_event_version` findings, one per round. Parallel calls finish
  before the next request, so the update is in the same record.
- **Sentinel sidecar updates** (`_sentinel/_sidecar/_judging.py`). Not run.
  `count_judging_as_waiting` and the sidecar output update run after the
  generate call awaits the sidecar's decision. No boundary of the same agent
  falls in between, but a boundary of another sub-agent of the same sample
  can, and it stores the model event complete.
- **Bridge `agent_tool_call_ids`.** `_record_agent_tool_call_ids`
  (`agent/_bridge/util.py`) updates a completed model event when the bridge
  gives the agent fresh tool-call ids. No run checked whether a boundary
  can store the event before this update.

The other callers of `Transcript._event_updated` update pending events only.

#### 2. Every buffered event has a uuid

True. The only writer of sample event rows is the transcript subscriber
(`on_sample_event_buffered` in `_eval/task/run.py`). Each event gets its uuid before
any subscriber sees it: `BaseEvent.model_post_init` sets it unless the event
is read from a log, `Transcript._event` calls `_ensure_event_key` before it
notifies subscribers, and restored checkpoint events get uuids in
`_normalize_seeded_events`. So the `event.event.uuid or uuid()` fallback in
`SampleBufferDatabase` does not fire for sample events. A validator check
that each row's `event_id` equals the event's `uuid` found no case in any
run. The rebuild and the late-version check go by row id, so the validator
does not check this.

#### 3. Rebuilt samples match samples logged from memory

True for every sample run. None of these evals evicted events, so every
`.eval` sample was logged from memory and compared with the rebuild.

##### Events lost when a worker thread logs a warning

With overlapping puts, about one timing run in 17 had one `event_mismatch`:
a tool event's completion was in the `.eval` file, and the store had only its
pending version. The sample buffer never got the completion row. The cause:

1. With more than 10 puts in flight on one boto3 client (its default pool
   size), urllib3 logs "Connection pool is full, discarding connection" in
   the put's worker thread.
2. `anyio.to_thread.run_sync` copies the context, so `transcript()` in that
   thread is the sample's transcript, and Inspect's log handler records the
   warning there as a `LoggerEvent` from the worker thread.
3. `Transcript._notify_subscribers` skips a subscriber that is already being
   notified (`_notifying_subscribers`). The set is per transcript, not per
   thread. While the worker thread is inside the buffer subscriber, an event
   that the event loop thread records at the same time skips the buffer,
   with no error.

Evidence: the pool warnings showed as `LoggerEvent`s in 6 of 20 samples of
one timing run, the mismatched sample's records had two of them next to the
missing completion, and a short script with two threads showed the skip.

The store client has a pool of 50 connections, the value `AsyncFilesystem`
uses, so its puts do not log the warning at this concurrency. With that
pool, 25 more runs of the 20 x 2 eval (1,000 samples) had no `LoggerEvent`
and no finding. Any other warning logged from a worker thread during a
sample can still make the buffer skip an event. The same loss affects the
sample buffer that live viewing reads. The core fix is
UKGovernmentBEIS/inspect_ai pr 6693.

#### 4. Time per boundary write

Against a local moto server on the same host (8 cores), not real S3. "Wait"
is the time the sample waits at a boundary: reading rows from SQLite, JSON,
the put, and waiting for earlier records of the same sample. The runs used
the current writer, with overlapping puts. The store client then had its own
retry loop in place of botocore's retries. No put failed, so retries did not
affect the times.

| Run | Writes | Wait median / p95 / max | Put median / p95 | Record size median / max |
| --- | --- | --- | --- | --- |
| 1 sample | 15 | 4.5 / 15.6 / 16.3 ms | 3.9 / 7.1 ms | 5.8 / 10.6 KiB |
| 20 samples x 2 epochs, 10 at once | 600 | 34.4 / 65.3 / 90.4 ms | 27.2 / 49.9 ms | 6.5 / 10.6 KiB |

Wall time for the larger eval: 1.96 s without the store, 3.23 s with it.
mockllm answers at once, so the difference is the whole cost of the writes.
In that run, 175 of 600 sample record puts started while another put of the
same sample was in flight. Real S3 put latency is not measured.

### What moto does and does not enforce

From a moto probe script, not in the branch:

```
action                                                       real S3 (docs)                moto
host: put new key, If-None-Match                             allowed                       allowed
host: put same key, If-None-Match                            refused (412)                 refused (PreconditionFailed)
host: put same key, no If-None-Match (no bucket policy)      allowed, adds a version       allowed
host: get                                                    refused (role)                refused (AccessDenied)
host: delete                                                 refused (role)                refused (AccessDenied)
host: list (moto setup grants s3:ListBucket)                 refused (role)                allowed
host: read Object Lock settings (moto: needs s3:ListBucket)  allowed                       allowed
admin: delete a locked version                               refused (compliance)          refused (AccessDenied)
admin: delete a locked version, bypass governance            refused (compliance)          refused (AccessDenied)
admin: shorten compliance retention                          refused (compliance)          allowed
admin: delete that version after shortening                  refused (never shortened)     allowed
admin: suspend versioning on an Object Lock bucket           refused (InvalidBucketState)  allowed
policy Deny if s3:if-none-match is Null: put without header  refused (403)                 refused (403)
policy Deny if s3:if-none-match is Null: put with header     allowed                       refused (403)
validator: list versions, Prefix with '/'                    allowed                       refused (SignatureDoesNotMatch)
host: put key with '%' in it                                 allowed                       refused (SignatureDoesNotMatch)
```

- `If-None-Match: *` on PutObject is enforced (412), also on
  CompleteMultipartUpload.
- Compliance-mode Object Lock is enforced only in part. moto refuses to
  delete a locked version, but lets anyone shorten compliance retention and
  then delete the version, and lets versioning be suspended. Real S3 refuses
  both. So moto cannot show that compliance mode keeps originals.
- moto applies a Deny with the `s3:if-none-match` condition key to every
  put, with or without the header. The tests set this policy only after the
  eval has written, so the validator's settings check has a policy to read.
- With IAM on, moto enforces user policies on S3 actions, so the start check
  is real under moto: the eval host user can put, and cannot get, delete or
  change settings. moto files the Object Lock settings read under
  `s3:ListBucket`, so the moto eval host user can also list.
- moto's signature check fails for a `/` in a list Prefix and for a `%` in a
  key. The validator lists without the trailing `/` and filters. The moto
  tests use sample ids that need no encoding, and a unit test covers the
  encoding. The same check fails on a paginated listing once a prefix holds
  more than 1,000 versions, so tests use a new prefix per run.
- A multipart object's arrival time in moto is when the upload completed.

The plan's assumption that AWS enforces compliance mode and the
If-None-Match policy can only be checked on real AWS.

## Not tested

- Real S3 in this note's runs. The PR description records separate real-S3
  runs.
- The `--tamper-evident-store` flag of `inspect eval`: it is passed through
  and type-checked, but no test runs a CLI eval with it. The rescore tests
  run `inspect score --tamper-evident-store`.
- The sentinel sidecar, sandboxed bridged agents (the bridge runs in
  process), checkpoint resume, evicted events (the buffer read-back path at
  log time), and large model inputs.
- The cross-account setup in the user docs.

Run the tests from the repo root:

```bash
pytest tests/log/test_addonly_store.py
INSPECT_ASYNC_BACKEND=trio pytest tests/log/test_addonly_store.py
pytest tests/log/test_addonly_store.py --runtrio
pytest tests/agent/test_bridge_approval.py -k addonly_store
```
