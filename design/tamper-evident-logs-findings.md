# Findings: tamper-evident logs, step 1

Spec: the tamper-evident logs plan. Step 1 was built against v80.
Step 1b changed the code to match v81, which took in the step 1
findings (see [Step 1b: changes for plan v81](#step-1b-changes-for-plan-v81)).
Branch `epatey/tamper-evident-logs-prototype`, from `main` at ec5d110b1.
Built by Claude Code on Opus 5.5 (`claude-opus-5-5`), session default
effort.

All runs use a local S3 emulator: moto server 5.2.2 on 127.0.0.1, in a
subprocess with IAM enforcement on. No AWS calls were made. No AWS
credentials other than moto's fake keys were used. Nothing was installed
outside the project venv (`uv sync --locked` only).

This code answers the plan's four questions. It is not yet ready for
review as a feature.

## Summary

| Question | Answer | Evidence |
| --- | --- | --- |
| 1. No legitimate event version is written after the event is complete and a boundary stored it | False for bridged host tools called one at a time: the bridge's `message_id` update is a late version (seen in a run). True for every other path run. The sentinel sidecar's updates can also be late when sub-agents run at once (code reading, not run). | `test_host_tools_against_addonly_store[serial]` (2 findings); `test_agent_eval_validates`, `test_streaming_eval_validates`, `test_host_tools_against_addonly_store[parallel]`, timing script (0 findings); rule proven by `test_late_event_version_flagged` |
| 2. Every buffered event has a uuid | True. The `uuid()` fallback at `buffer/database.py:424` never fires for sample events. | Code path below; validator check `event_without_uuid` found none in any run |
| 3. A sample rebuilt from buffer rows matches the sample logged from memory | True for every sample run, once no warning is logged from a worker thread (see [Events lost when a worker thread logs a warning](#events-lost-when-a-worker-thread-logs-a-warning)). | `test_agent_eval_validates` (6 samples), `test_streaming_eval_validates`, bridge test, timing script and probe runs (1,000+ samples) |
| 4. Time per boundary write | Local moto, not S3: median 4.5 ms with 1 sample (put alone 3.9 ms). Median 34 ms, p95 65 ms with 10 samples at once (put alone 27 ms). | `scripts/addonly_timing.py` |

## What was built

- `src/inspect_ai/log/_addonly/`
  - `_store.py`: the store client. Each put sends `If-None-Match: *`. The
    client has SDK retries off; `AddOnlyStore.put` retries network errors,
    throttling and 5xx for up to 60 s, and fails on any 412. The check
    before the eval starts writes the start record, writes it again (must
    get 412), tries to read and delete it (must be denied), and reads the
    Object Lock settings (must be enabled, COMPLIANCE).
  - `_records.py`: record models and keys, as in the plan:
    `<eval-id>/start`, `<eval-id>/closing`,
    `<eval-id>/<sample-id>.<epoch>/<attempt>/<seq>`,
    `<eval-id>/<sample-id>.<epoch>/<attempt>/closing`.
  - `_writer.py`: `EvalRecordWriter` (holds the nonce, in memory only) and
    `SampleRecordWriter` (one sequence per sample attempt). `store_boundary()`
    takes the current sample's new buffer rows and the next sequence number,
    puts the record, and waits until every record numbered up to its own is
    confirmed.
  - `_validate.py`: the validator.
- Buffer: `SampleBufferDatabase.sample_row_marks`, `sample_rows_after` (rows
  after a per-table row id, in insertion order) and `insert_sample_rows`
  (used by the validator to rebuild a sample).
- Boundaries:
  - before each generate request: `model/_model.py:1909`, inside `send()`,
    so retries and resends also write first;
  - before each stage of tool calls: `model/_call_tools.py:706`;
  - before each bridged host tool runs:
    `agent/_bridge/sandbox/host_tool.py:381`;
  - at sample end, after scoring: `_eval/task/run.py` (last rows, then
    the sample closing record).
- `TaskLogger.log_start` writes the start record and runs the check before
  any sample starts. `TaskLogger.log_finish` writes the eval closing record.
- A failed write stops the eval: `AddOnlyStoreError` turns off retries and
  scoring for the sample (`run.py`), and always fails the eval, whatever
  `fail_on_error` says (`_eval/task/error.py`).
- A failed insert into the sample buffer stops the sample at its next
  boundary (`_eval/task/run.py:2873`, `SampleRecordWriter.insert_failed`).
- `inspect validate LOG_DIR --store s3://bucket/prefix`
  (`_cli/validate.py`). Checks: bucket settings (COMPLIANCE lock,
  versioning, a policy that denies a put without If-None-Match), one version
  per key, no delete markers, multipart uploads, a start record, nonces,
  sequence gaps, sample and eval closing records, record counts, attempts
  missing from the eval closing list, late event versions, events without a
  uuid, a .eval file for each eval, and the .eval events against the stored
  events. Step 1c added: records the eval could not have written, .eval
  files and samples with no records, two .eval files with one eval id, and
  the .eval scores and eval status, stats and results against the closing
  records. Review round 1 added: samples found by zip member name, values
  compared as JSON text, rows that stop the sample rebuild, retried
  attempts (listed, not findings), and samples an eval retry reused
  (compared with the earlier eval's records). Review round 2 changed how
  reused samples are found (the start record's `prior_eval_id`), and added
  reused samples missing from a retry's .eval. Review round 3 applied the
  retry's own selection to that check, and lists evals with no .eval file
  that a later eval names. It exits non-zero on any
  finding. `--verbose` lists each record
  with its arrival time. The scope for matching eval ids to .eval files is
  the `--store` prefix: one prefix per log directory.
- Tests:
  - `tests/log/test_addonly_store.py`: 15 tests in step 1b; step 1c added
    end-to-end tamper tests (see [Step 1c](#step-1c-end-to-end-tamper-tests)).
  - `tests/agent/test_bridge_approval.py`: `test_host_tool_stores_before_it_runs`
    and `test_host_tools_against_addonly_store` (parallel and serial).
  - `tests/test_helpers/addonly_moto.py` (moto setup, `MotoStore.validate`),
    `tests/test_helpers/addonly_agents.py` (scripted agents).
- Scripts: `scripts/addonly_timing.py`,
  `scripts/addonly_moto_probe.py`.

Run them from the repo root:

```bash
pytest tests/log/test_addonly_store.py
pytest tests/agent/test_bridge_approval.py -k addonly_store
PYTHONPATH=tests python scripts/addonly_timing.py
PYTHONPATH=tests python scripts/addonly_moto_probe.py
```

The eval writes to the store when it gets
`tamper_evident_store="s3://bucket/prefix"` (`eval()`, `eval_set()`,
`eval_retry()`) or `--tamper-evident-store s3://bucket/prefix` (`inspect
eval`, `eval-set`, `eval-retry`). Without it, the eval writes nothing to the
store. The log does not record it, so a retry must be given it again (as
`sentinel_proxy`). It needs `log_realtime` (the default), and fails at
start without it.

## Step 1b: changes for plan v81

Plan v81 took in the six plan errors of step 1. Each change below matches
the code to the plan.

1. **412.** The eval host's S3 client has SDK retries off
   (`_store.py:84`, `retries={"max_attempts": 0}`, as `asyncfiles`
   does for its final conditional call). `AddOnlyStore.put` (`_store.py:112`)
   is the eval's own retry loop: it retries network errors, throttling, 5xx
   and `ConditionalRequestConflict` (`_transient`, `_store.py:93`) for up
   to 60 s with backoff, and fails the write on any other error. Every 412
   fails the write, so the eval fails. A 412 after a retried put says that
   the record may be the eval's own lost put (`_put_error`,
   `_store.py:195`). Tests: `test_put_retries_and_412_after_retry` (a
   network error before the put reaches the store is retried; a put that
   reaches the store and loses its response fails on the retry's 412),
   `test_put_has_sdk_retries_off`.
2. **Failed buffer insert.** The transcript still logs a subscriber's error
   and goes on. The sample's event callback (`_eval/task/run.py:2865`)
   now tells the sample's writer when the insert fails
   (`SampleRecordWriter.insert_failed`, `_writer.py:125`). The next
   boundary raises `SampleBufferInsertError`, which is an ordinary sample
   error: the sample stops, and `fail_on_error` and `retry_on_error` apply
   as usual (a failed write, by contrast, always fails the eval). The
   attempt writes nothing more and has no closing record, so the validator
   reports it as cut short. Test: `test_failed_buffer_insert_stops_sample`
   (the sample errors, no generate request follows the failed insert, the
   eval completes, the validator reports `missing_closing`). Limit: an
   insert that fails after the sample's last boundary (for example during
   scoring with no model call) cannot stop the sample before it is logged;
   the attempt then has no closing record.
3. **Every path that runs a tool.** Bridged host tools now write before the
   tool runs (`agent/_bridge/sandbox/host_tool.py:381`), before the tool's
   span and pending event, as `execute_tools` does for a stage. The other
   `ToolEvent` producers do not run a tool on the host: `_call_tools.py`
   is `execute_tools` itself, and `agent/_acp/event_mapping.py` records
   tool calls that the ACP agent ran in its sandbox. Tests:
   `test_host_tool_stores_before_it_runs` (the boundary comes before the
   tool), `test_host_tools_against_addonly_store` (a real eval with bridged
   host tools, validated). What the runs show about the two open late
   updates is in [Answers, 1](#1-no-legitimate-late-event-versions). They
   are not settled here.
4. **`.` as `%2E`.** Already done in step 1 (`sample_key_part`).
5. **Sub-agents.** The lock is gone. `SampleRecordWriter.write`
   (`_writer.py:136`) reads the new rows and takes the next sequence number
   with no `await` between them, so numbers follow row order. It then puts
   the record outside that step (`_put`, `_writer.py:154`), and waits until
   every record numbered up to its own is confirmed (`_writer.py:150`). A
   boundary with no new rows puts nothing but still waits for the numbers
   already taken, because a record still in flight can hold rows this
   sub-agent recorded. A failed put makes every waiting boundary raise.
   Test: `test_writes_overlap_and_wait_for_earlier_numbers` (record 2's put
   starts while record 1's put is held; neither boundary, nor an empty one,
   returns until record 1 is confirmed; when record 1 fails, all three
   raise). In the timing run, 175 of 600 sample record puts
   started while another put of the same sample was in flight.
6. **Validator scope.** The simplest scope: a prefix per log directory. The
   validator already lists only under its `--store` prefix, so this needs
   no new code; the `--store` help now says to use one prefix per log
   directory. The listing matches `prefix/`, so `evals` does not match
   `evalsx`. Test: `test_prefix_per_log_dir_scopes_validation` (two log
   directories in one bucket, prefixes `P` and `Px`: each validates clean,
   and validating one log directory against the other's prefix reports the
   missing .eval file). A time window or a list of eval ids would need a
   new option; a list of eval ids would also have to come from somewhere
   other than the log directory, or deleting a .eval file would hide its
   eval.

After these changes the writer's guarantees are: each boundary returns only
after every record numbered up to the last one taken is confirmed; once a
put or a buffer insert fails, the attempt writes nothing more; every 412
fails the write. The code has one mechanism per clause.

## Step 1c: end-to-end tamper tests

Each test runs a real eval with the store on, checks that it validates
clean, changes the .eval file or the store, then runs the `inspect
validate` command in a subprocess and checks the exact finding kinds. 3
happy-path tests (plain eval, agent eval, 3 samples x 2 epochs at once), 16
.eval tampers, 22 store tampers and settings changes. Set
`ADDONLY_EVIDENCE_DIR` to keep each command's output.

Validator bugs the tests found, each fixed with a test that failed first:

1. With two versions of a key in the same second (S3 times have whole
   seconds), the validator read the newest, not the first. An overwrite
   with matching .eval edits then hid the `event_mismatch`. It now takes
   the last version listed (S3 lists newest first).
2. A record the eval could not have written (bad JSON, a bad event, an
   unknown key, a record of the wrong type) stopped the validator with a
   traceback, so no eval under the prefix was checked. Anyone with the host
   keys can add one. Now `malformed_record`. *Correction (review round 1):*
   this fix covered the record and its event rows only. A record with a
   bad pool row, or a row whose key was already stored, still stopped the
   validator in the sample rebuild. Fixed in review round 1 (fix 3 below).
3. These passed, with the line "The .eval files match the add-only store":
   an extra .eval file with no records (`unstored_eval`), an edited copy of
   a .eval with the same eval id (`duplicate_eval_file`, removed in
   [Rescore support](#rescore-support)), an added sample
   (`unstored_sample`), an edited sample score (`score_mismatch`), and an
   edited eval status, stats or results (`eval_mismatch`).
4. The pass line now says what was checked and what was not. *Review
   round 1:* the "Not checked" part read as a full list, which it was not.
   It now reads "Not checked: everything else, including the eval spec and
   plan, each sample's messages, output and error, what the sample
   summaries say, invalidation and log_updates."

## Review round 1: fixes and changes after the run

Two fresh-context reviews (Claude Opus 5.5; Codex gpt-6.1-sol, xhigh) of
5e6fb89a9..524ddb439 found these defects. Each fix has a test that failed
before it.

1. **NaN and 1 == True.** The score and eval checks compared `model_dump`
   dicts with `==`. A clean run with a NaN score or metric gave
   `score_mismatch` and `eval_mismatch` (NaN != NaN). A score value 1
   edited to true passed, in the sample scores and in the score event
   (1 == True). The score, eval and event checks now compare JSON text
   (`_same_json`: `json.dumps(..., sort_keys=True)`). Tests:
   `test_nan_score_validates`, `test_edit_score_one_to_true`.
2. **An extra zip member with a stored sample's id.** A member
   `samples/extra_epoch_1.json` holding s0's sample JSON (id s0), with an
   edited tool result and score, passed with 0 findings: the full read gave
   id s0 only, and s0 was compared from its own member. Samples are now
   found by zip member name (`read_log_sample_keys`) and summary id. The
   extra member gives `unstored_sample`. Test:
   `test_add_sample_member_same_id`.
3. **Rows that stop the sample rebuild.** A message or call pool row whose
   data is not JSON (JSONDecodeError), or any row whose key the store
   already has (sqlite IntegrityError), stopped the validator, and no other
   eval was checked. Now `malformed_record` for the attempt; the validator
   goes on. Test: `test_malformed_buffer_row` (5 cases; a second eval
   under the prefix is still checked).
4. **Docs.** The pass line (above), test docstrings (an overwrite's second
   version is usually in a later second, not the same one;
   `remove_last_record` keeps both closing records, so it is not the store
   that a host that stops early leaves), and the evidence notes.

Changes after the run (plan v83), with Eric's go:

- **retry_on_error.** A retried attempt has no closing record, so the
  validator reported `missing_closing`. Now, when a later attempt of the
  same sample has a closing record, the attempt is listed as `retried`
  and is not a finding. With no later closed attempt, it is still
  `missing_closing`. Test: `test_retry_on_error_validates`. *Review round
  2:* also only when `retry_on_error` allows the attempt (fix 4).
  *Changed Nov-25:* replaced by `stopped`.
- **eval_retry.** A sample the retry reused from an earlier eval has no
  records under the retry's eval id, so the validator reported
  `unstored_sample`. The retry's .eval does not say which eval the sample
  came from (the sample keeps its uuid and event uuids; nothing names the
  earlier eval). As plan v83 says, the retry's eval closing record now
  lists each reused sample with the earlier eval's id
  (`EvalClosingRecord.reused`). The validator compares the sample with
  that eval's records, and follows the list when the earlier eval is a
  retry too. An earlier eval with no closed attempt of the sample gives
  `unstored_sample`. Tests: `test_eval_retry_validates` (two retries),
  `test_edit_reused_sample`. *Replaced in review round 2* by the start
  record's `prior_eval_id` (fixes 1 to 3): the list crashed
  `task_retry_attempts` and eval_set retries.
- **Rescore (`inspect score`).** Not changed; the design is pending with
  Eric. Plan v83 expects a rescore to change only scores and the header.
  But `inspect score` also writes the sample's events again: it builds the
  event tree and flattens it (`_get_updated_events`, `_eval/score.py:204`;
  `event_sequence`, `event/_tree.py:94`), so each span's events come
  together and parallel spans lose their order, and the new scorers span
  replaces the old one. A rescore then gives `event_mismatch` too. Test:
  `test_rescore_fails_validation`. *Replaced by* [Rescore
  support](#rescore-support); the test is now
  `test_rescore_without_store_fails_validation`.

Also: the store location is now the eval option `tamper_evident_store`
(see [What was built](#what-was-built)); the environment variable is
gone.

## Review round 2: fixes

Two fresh-context reviews (Claude Opus 5.5; Codex gpt-6.1-sol) of the
branch at 482060faa found these. Each fix has a test that failed first,
and its own commit.

1. **Crash on task_retry_attempts and eval_set retries** (7789f1c04). The
   retry crashed at its first reused sample (`assert self.prior_eval_id is
   not None` in `note_reused`), because `TaskLogger.reinit` did not change
   the prior eval id. eval_set retries by default with
   `task_retry_attempts`, so every eval_set retry with a reused sample
   crashed. Tests: `test_task_retry_attempts_validates`,
   `test_eval_set_retry_validates`.
2. **One prior eval per eval, not a list per sample** (same commit). Every
   sample that one eval reuses comes from the same earlier eval. The start
   record now has `prior_eval_id`, from the retry's
   `EvalSampleSource.prior_eval_id` (`task_run` passes it to
   `TaskLogger.log_start`); no copy is kept in `TaskLogger` or the writer.
   Removed: `ReusedSampleRef`, `EvalClosingRecord.reused`, `note_reused`
   and its call in `task_run`. The validator treats a .eval sample with no
   records under the eval as reused, and finds its closed attempt along the
   chain of start records (`_earlier_attempt`, `_prior_evals`). With no
   prior eval, or no closed attempt in the chain, it is `unstored_sample`
   (`test_add_sample_to_retry`).
3. **A deleted reused sample** (19bcb1ee7). Change 2 lost a check: a
   reused sample deleted from a retry's .eval gave 0 findings (the reused
   list had given `missing_sample`). Restored without the list: a retry
   copies every sample of its prior eval that it selects (its sample ids
   and epochs; review round 3, fix 1 corrects this) into its log before
   any sample runs (`TaskLogger.seed_from_prior`, `log.py:595`; called at
   `run.py:1231`). So each sample that the prior evals closed without an
   error, and that the retry has no records of, must be in the retry's
   .eval; else `missing_sample`. Test: `test_delete_reused_sample`. The
   reuse rule itself (`classify`, `run.py:4246`) also needs no
   invalidation, which the store does not hold; this does not matter,
   since the seed copies those samples too. False `missing_sample` is
   possible when a retry stops before it runs the sample and has no copy of
   it: (a) the retry is unseeded (the prior .eval was gone at start, or
   `log_samples` is off; `log.py:630`), (b) a limited dynamic sample feed
   is cancelled during admission (`log.py:614`), (c) the prior eval put the
   sample's closing record and stopped before the sample reached its .eval
   (`run.py:3706`). A later retry that completes holds the samples, and
   eval_set's cleanup then removes the stopped retry's .eval.
4. **Retried only when retry_on_error allows it** (8df86b887). An attempt
   with no closing record was `retried` whenever a later attempt was
   closed. Now the attempt number must also be at most the start record's
   `eval.config.retry_on_error`; else `missing_closing`. Test:
   `test_retried_needs_retry_on_error`. With `retry_on_error` on, a
   compromised process can still write a later attempt so that an earlier
   attempt's events are not compared; the docs say so. *Changed Nov-25:*
   replaced by `stopped`.
5. **eval_set retry cleanup** (231a7f0b5; Eric's decision D2, option b).
   `retry_cleanup` (on by default) deletes the failed attempt's .eval file,
   so the validator reported `missing_eval_file`. Now an eval with no .eval
   file is not a finding when a later eval's start record names it as
   `prior_eval_id`. Its records are still read and used for the reused
   samples. Deleting such a file is then not reported; the docs say so.
   (Review round 3 lists such an eval as `prior_without_file`.)
   Test: `test_eval_set_retry_validates[True]`.
6. **A bad attempt in a key** (e50504901). `<eval>/s0.1/bad/closing`
   stopped the validator at `int(attempt)`. The key check now needs a
   decimal attempt, so the key is `malformed_record` and validation goes
   on. Test: `test_malformed_record[bad_attempt_closing]`,
   `[bad_attempt_record]`.
7. **Docs** (ef6e2ddbc): bucket setup wording, `--region` on
   create-bucket, where the nonce is, the shortened record list, retries
   by eval_set and `task_retry_attempts`, "Experimental" in the
   `eval_retry` docstrings.

Not changed: rescore (on hold with Eric).

After these changes, the retry guarantees are: a retry's reused sample
must match a closed attempt of the eval that ran it, found along the chain
of start records; a retry's .eval must hold each sample that the prior
evals closed without an error; and an eval whose .eval file is gone is a
finding unless a later eval names it. One mechanism (the start record's
`prior_eval_id`) serves all three.

## Review round 3: fixes

Two fresh-context reviews (Claude Opus 5.5; Codex gpt-6.1-sol) found
these. Each fix has a test that failed first, and its own commit.

1. **False `missing_sample` for a narrower retry** (65f1b61bc). An
   eval_set retried with `sample_id=["s0"]`, or with fewer epochs, gave
   `missing_sample` for each sample of the prior chain that the retry
   does not select. The seed copies only the selected samples
   (`seed_from_prior`, `log.py:608`; `run.py:1237`: the dataset sample ids
   and the epoch count). The check now applies the retry's own selection,
   from its start record's eval spec (`_selects`). The eval spec replaces
   the `started` flag of `_StoredEval`. Tests:
   `test_eval_set_narrower_retry_validates[sample_id]`, `[epochs]`.
2. **A visible list for evals with no .eval file that a later eval
   names** (8f313aa41). This keeps decision D2 (not a finding), but the
   eval now shows: `inspect validate` prints
   `prior_without_file <eval id>: No .eval file; <later eval id> names it
   as its prior eval.` before the count, as for `retried`
   (`ValidationReport.prior_without_file`). The exit code does not
   change. Eval-host keys can forge a later eval that names any eval, so a
   deleted .eval file of any eval, successful or not, shows only in this
   list. A forged later eval with its own records of the same samples
   replaces their records in the comparison. The docs say both. Test:
   `test_forged_successor_lists_deleted_eval_file`; also
   `test_eval_set_retry_validates[True]` shows the line.
3. **An eval that names itself as prior** (8a26474f0). Its missing .eval
   file was not reported. The check now looks only at the other evals.
   Test: `test_eval_names_itself_as_prior`.
4. **Docs.** The early-stop limit now says that a retry must keep only
   the samples it selects. New known limit: a retry also copies the
   samples that the prior eval closed with an error; if the retry stops
   before it runs one again, and someone deletes the copy from the
   retry's .eval, the validator does not report it (the check covers
   samples closed without an error only). An eval_set run again later to
   retry an earlier run needs the store option again.

Not changed: rescore (on hold with Eric).

After these changes, the retry guarantees are: a retry's reused sample
must match a closed attempt of the eval that ran it, found along the chain
of start records; a retry's .eval must hold each sample that the prior
evals closed without an error and that the retry selects; and an eval
whose .eval file is gone is a finding unless another eval names it, and
then it is listed. The start record (its `prior_eval_id` and eval spec)
serves all three.

## Stopped attempts and evals

Eric's decision, Nov-25: "I'm interested in the honest run that stops
partway through. why is it considered a validation failure? we should be
able to validate that every that was written so far is valid." And: "I'd
like the validator to record that it stopped rather than failed
validation. How to interpret what that means is a separate issue".

Changes:

1. **Stopped, not a finding.** A sample attempt with no closing record is
   listed in `ValidationReport.stopped` (its key prefix), and
   `inspect validate` prints `stopped <prefix>: No closing record: cut
   short, or its host stopped writing.` before the count. The exit code
   does not change. Every record that the attempt wrote is still checked:
   nonce, sequence numbers, record type, event versions, malformed
   records. `missing_closing` is gone from `FindingKind`.
2. **One list for retries too.** The `retried` list and its
   `retry_on_error` condition are gone. A retried attempt has no closing
   record, so it is in `stopped`.
3. **Evals.** An eval with no closing record is in `stopped` (its eval
   id). Checks that need the eval closing record (`unlisted_attempt`)
   are skipped, as before.
4. **A sample in the .eval file needs a closed attempt.** Built as first
   briefed, a .eval sample whose only attempt has no closing record was
   not compared and not reported: a compromised process could skip a
   sample's closing record and then change its confirmed events in the
   .eval copy (`test_remove_sample_closing` passed with "0 sample(s)
   compared"). That breaks the documented protection against edits by a
   compromised eval process. With the coordinator's go (option a), the
   `unstored_sample` check now takes the .eval samples with no closed
   attempt, not the ones with no records. A reused sample already needed
   a closed attempt in the eval that ran it.
5. **A finished .eval file needs its eval closing record.** The same rule
   one level up: when the eval has no closing record and its .eval file
   has a status other than `started`, the validator reports
   `missing_eval_closing`. A .eval file that is still `started` (the host
   stopped before it finished the file) only lists the eval as stopped.

Tests (`tests/log/test_addonly_store.py`):

- `test_stopped_attempt_records_checked[None]`: an attempt and an eval
  with no closing record give no finding and are both listed.
  `[sequence_gap]` and `[nonce]`: the stopped attempt's records still give
  these findings.
- `test_eval_host_stops_before_finish`: no eval closing record and a .eval
  file still `started`: 0 findings, the eval listed, its sample compared.
- `test_remove_eval_closing`: `missing_eval_closing`, the eval listed.
- `test_remove_sample_closing`: `unstored_sample`, the attempt listed.
- The three honest cancel cases from the reviews of 901a1f6fb. Each gave
  `missing_closing` at 66522b474 and gives 0 findings now, with the
  attempt listed:
  `test_eval_stopped_while_hook_waits_lists_stopped[scoring]` (s0 waits in
  `on_sample_scoring` when s1's error stops the eval),
  `[attempt_end]` (with `retry_on_error`, s0 waits in its attempt end hook
  before the retry), and
  `test_eval_stopped_while_retry_waits_lists_stopped` (with
  `retry_on_error` and one sample slot, a retry still waits for the slot
  when the eval stops).
- `test_failed_write_stops_eval` and `test_failed_buffer_insert_stops_sample`
  now expect the findings below.

Honest runs that still give a finding (documented as known limits):

- A sample whose write to the store fails, or that has an event the
  sample buffer cannot insert, writes no closing record but is logged with
  its error: `unstored_sample`. Before, these gave `missing_closing`.
- An eval that finishes its .eval file and then cannot write its eval
  closing record (the eval closing record is written after the .eval file
  is finished): `missing_eval_closing`, as before.

The completion shield in `run.py` (`completion_scope`) and the shielded
put in `SampleRecordWriter._put` are still needed. With each removed in a
copy of the tree: without the put shield, a sample cancelled at a
boundary is logged with no closing record, so
`test_eval_retry_after_cancel_at_boundary_validates[True]` and `[False]`
give `unstored_sample`. Without the completion shield, a sample cancelled
after its closing record and before it is logged gives `missing_sample`
in the retry (`test_eval_retry_after_cancel_in_close_validates[closing]`).
A sample cancelled between its last record and its closing record
(`[2]`) now gives only a stopped attempt, so that part of the shield is
not needed for validation; the docs still promise that a scored sample
writes its closing record and is logged when the eval is cancelled.

Open question: how to interpret a stopped attempt or eval. It can be an
honest cancel or crash, but a compromised host can also stop writing to
hide what a sample did. The validator lists it and does not decide.

After this change, the guarantees are: every record in the store is
checked, whether or not its attempt or eval closed; and every sample in a
.eval file, and every finished .eval file, must match a closing record in
the store. An attempt or eval with no closing record is listed as
stopped.

## Review of the stopped change: fixes

A Codex review and a Claude review of 3d0c17711 found these. Dev Desk
decided item 4 under Eric's "I'd like the validator to record that it
stopped rather than failed validation".

1. **Record checks for every attempt.** The validator rebuilt a sample's
   events from its records only to compare them with a .eval sample. So
   a stopped attempt's pool row that is not JSON, or an attachment key
   stored twice, was not a finding. Now `_read_eval` rebuilds every
   attempt once (`rebuild_events`), closed or not. A rebuild that fails
   is `malformed_record`, and the comparison uses the events of that
   rebuild. Test: `test_stopped_attempt_malformed_buffer_row[message_pool]`,
   `[call_pool]` and `[attachments]`.
2. **Attempts with no records.** An attempt that the eval closing record
   names, with no records and no closing record, was not listed. It is
   now in `stopped`. Test:
   `test_eval_stopped_while_hook_waits_lists_stopped[init]` (s0 waits in
   `on_sample_init`, before its first record, when s1's error stops the
   eval).
3. **A retry's own stopped sample.** For a .eval sample with no closed
   attempt, the lookup of a closed attempt started at the prior eval,
   also when the retry had records of the sample. So a retry with a
   stopped attempt of s0 and the prior eval's errored s0 in its .eval
   file passed. The lookup now starts at the eval itself, so a sample
   that the eval ran is never compared with a prior eval's copy. The
   result is `unstored_sample`: "with no closed attempt in the store for
   this eval, which ran it." Test:
   `test_retry_logs_prior_copy_of_sample_it_ran`. *Changed Nov-25:*
   reverted in review round 8.
4. **Honest crash.** The sample closing record is written before the
   sample is logged, and the .eval recorder writes logged samples in
   groups (`log_buffer`; `default_log_buffer` gives up to 10 for most
   runs). So an eval host that dies
   usually leaves closed samples that are not in the .eval file, which
   gave `missing_sample`. A death before the first .eval write gave
   `missing_eval_file`. Now, when the eval has no closing record and its
   .eval file is `started`, each closed sample that is not in the file is
   in `ValidationReport.not_logged`, and `inspect validate` prints
   `not_logged <key>: Closed, not in the .eval file: the eval stopped
   before it logged the sample.` The same rule applies to a retry's
   reused sample (the `missing_sample` check of the prior chain). An eval
   with no closing record and no .eval file is only in `stopped`.
   *Changed Nov-25:* also needs no closed attempt (review round 8).
   `missing_sample` still applies to an eval with a closing record or a
   finished .eval file, and `missing_eval_file` to an eval with a closing
   record. Tests: `test_eval_host_crash_lists_stopped[before_first_flush]`
   and `[sample_not_logged]`. Each runs the eval in a subprocess that
   calls `os._exit`. The second has 6 samples, so the default buffer is 2.
5. The two older `retried` entries have a *Changed Nov-25* mark.

Effect on the protection: someone who deletes samples from the .eval
file of a crashed eval (status `started`) gets a `not_logged` line, not
a finding. A compromised process can already hide a sample's events: it
does not write the sample's closing record. So the change adds nothing
for that threat. It removes the deletion check for the logs of crashed
evals only. The docs list it under "What it does not protect".

Each new test failed at 3d0c17711: `missing_eval_file` and
`missing_sample` for the two crash tests, an empty stopped list for
`[init]`, and a pass with 0 findings for the three malformed-row tests
and the retry test.

After these fixes, the guarantees are: every record in the store is
checked, also the rows of a stopped attempt; a sample in a .eval file
must match a closed attempt of the eval that ran it, and a closed sample
must be in the .eval file unless the eval stopped before it finished the
file; a finished .eval file must match its eval closing record. An
attempt or eval with no closing record is listed as stopped, and a
closed sample that a stopped eval did not log is listed as not logged.

## Review round 8: fixes

A Codex review and a Claude review of d3af27e47 found these.

1. **An honest retry that stops while it runs a sample again.** A retry
   seeds its .eval file with the prior eval's samples, also the ones
   closed with an error, before it runs any sample
   (`TaskLogger.seed_from_prior`). When the retry stops while it runs
   such a sample again, the seeded copy stays in the file. Fix 3 of the
   stopped change started the lookup at the retry, which has records (or
   an attempt in its closing record) of the sample, so this run gave
   `unstored_sample`. The lookup starts at the prior eval again, as
   before fix 3. The copy is compared with the prior eval's records, and
   the retry's attempt is listed as `stopped`. So the retry's own stored
   events for the sample are not compared; the docs list this under
   "What Is Not Protected". Test:
   `test_retry_stopped_while_hook_waits_validates[init]` and
   `[scoring]`. The first eval closes s0 and s1 with errors; in the
   retry, s1 fails while s0 waits in a hook. The test
   `test_retry_logs_prior_copy_of_sample_it_ran` is deleted.
2. **A deleted .eval file of a crashed eval.** Fix 4 of the stopped
   change reported `missing_eval_file` only for an eval with a closing
   record, so deleting the .eval file of a crashed eval gave no finding.
   An honest eval writes its first .eval file before any sample runs
   (`log_start`), so an eval with a closed attempt always has one. Now
   `missing_eval_file` applies to an eval with a closing record or a
   closed attempt. An eval with neither and no .eval file is listed only
   as `stopped`. Test: `test_eval_host_crash_eval_file_deleted`; the
   `[before_first_flush]` case of `test_eval_host_crash_lists_stopped`
   covers the other case.
3. **Setup order.** The bucket policy names the `eval-host` role, and S3
   refuses a policy whose principal does not exist. The docs now create
   the role (step 2) before the bucket policy (step 3).

Each new test failed at d3af27e47: `unstored_sample` for the two retry
cases, and 0 findings for the deleted file.

After these fixes, the guarantees are: every record in the store is
checked, also the rows of a stopped attempt; a sample in a .eval file
must match a closed attempt of the eval or of the prior evals it reused
from, and a closed sample must be in the .eval file unless the eval
stopped before it finished the file; a finished .eval file must match
its eval closing record, and an eval with a closing record or a closed
attempt must have a .eval file. An attempt or eval with no closing
record is listed as stopped, and a closed sample that a stopped eval did
not log is listed as not logged.

## Review round 9: fixes

A Codex review and a Claude review of 62cffe88d found these.

1. **A second retry that stops while it runs a sample again.** The first
   eval closes s0 with an error; a retry stops while it runs s0 again,
   and a retry of that retry stops the same way. Both retries keep the
   first eval's copy of s0. The lookup for the second retry stopped at
   the first retry, which has records of s0 but no closed attempt, so the
   run gave `unstored_sample`. The lookup now goes on to the nearest
   earlier eval that closed the sample, so the copy is compared with the
   first eval's records. This is the round 8 rule (a stopped retry's own
   events for a kept copy are not compared) for any number of retries.
   The `missing_sample` check of the prior chain uses the same lookup.
   Before, it gave no finding when the nearest eval with records of the
   sample had only stopped it; now it uses an older closed copy. An
   honest run gets the new finding only when an earlier retry ran a
   sample that an older eval closed without an error but did not log
   (one of the causes in "A retry that stops early"), stopped while it
   ran it, and the later retry stops before it runs it. That is the same
   limit, one eval further back. Test:
   `test_retry_stopped_while_hook_waits_validates[*-2]`.
2. **Test gates.** eval_retry loads the task from its file, which runs
   the test module again with an empty `_cancel_gates`. So in the retry
   test, s1 failed with `KeyError` at once instead of waiting for s0's
   hook, and under Trio the `[scoring]` case failed about half its runs.
   The gates are now in `tests/test_helpers/addonly_gates.py`, which both
   module copies import once, and the test checks that the retry's error
   is the intended one. In the other retry tests, the retry's solver does
   not read the gates.
3. **Docs.** A failed write or buffer insert while a retry runs a sample
   again gives `event_mismatch` "(reused from ...)". The docs now say so
   in the `event_mismatch` row and the honest-runs limit.

Each `[*-2]` case failed at 62cffe88d with `unstored_sample`.

After these fixes, the guarantees are: every record in the store is
checked, also the rows of a stopped attempt; a sample in a .eval file
must match the eval's own closed attempt or, if it has none, the nearest
earlier eval's closed attempt along the chain of prior evals; a closed
sample must be in the .eval file unless the eval stopped before it
finished the file; a finished .eval file must match its eval closing
record, and an eval with a closing record or a closed attempt must have
a .eval file. An attempt or eval with no closing record is listed as
stopped, and a closed sample that a stopped eval did not log is listed
as not logged.

## Rescore support

Plan: `2026-11-25-1040-6668-rescore-plan.md` (Eric, Nov-25: "rescoring
protected logs is a common feature. let's do #2 now"). Built on
6d4c4eaff by Claude Code on Opus 5.5 (`claude-opus-5-5`).

### What was built

- `inspect score` and `score()` / `score_async()` take the store option
  eval takes (`--tamper-evident-store`, `tamper_evident_store=`). Without
  it, nothing changes.
- A rescore has its own id and writes the eval's nonce in each record.
  `inspect score` takes the nonce from the `INSPECT_TAMPER_EVIDENT_NONCE`
  environment variable (never a CLI option, never printed or logged) and
  fails before it scores when the store option is on and the variable is
  not set. `inspect validate --nonce <eval-id> --store ...` prints the
  nonce from the eval's start record, with the validator's read access.
  So the rescorer needs add rights only, as the eval host has. The
  records, under `rescores/<eval-id>/<rescore-id>/` in the store prefix:
  - `start`: eval id, rescore id, nonce, action (append or overwrite).
    Written with the same checks as the eval's start record
    (`put_start_and_check`).
  - `<sample-id>.<epoch>`, one per sample, written once the sample's
    scorers finish and before the sample is logged: its new scores
    (`SampleScore`, as score.py's `_run_score_task` returns them), the
    events the scorers added (with attachments resolved), and the
    sample's latest rescore before this one (`built_on`).
  - `closing`: the new results.
- The marker: the rescore adds an info event
  (`source="tamper_evident_rescore"`) to each sample's new scorers span,
  before the scorers run. Its data names the rescore (eval id and rescore
  id) and the number of rescores in the sample's chain, this one included
  (`chain_length`). It is in the sample's events, so it reaches the .eval
  without a change to the log schema, with append and overwrite, and with
  `--stream`. The rescorer reads the sample's latest marker (the one with
  the longest chain) from its input to fill in the sample record's
  `built_on` and the new marker's `chain_length`.
- Validator:
  - A sample's expected scores and events are those of the original run
    (rebuilt from the records as before), with each rescore of the chain
    applied, oldest first, by score.py's own `_get_updated_scores` and
    `_get_updated_events`. The chain starts at the sample's latest marker
    and follows each rescore record's `built_on`. So the new event order
    is reproduced, not changed.
  - Status and stats are compared with the eval closing record. Results
    are compared with the closing record of the latest rescore the
    samples name, or with the eval closing record if the file is not
    rescored.
  - Every .eval file with a given eval id is compared, not only the first
    (`_eval_files` already listed them). `duplicate_eval_file` is gone:
    an original and its rescored copy in one log dir are both checked,
    and an edited copy gets its own findings.
  - A pass lists each rescore (`rescored <eval-id> by <rescore-id> at
    <S3 time> (append|overwrite)`, S3 time of the start record) and the
    eval's original results (`original_results <eval-id>: ...`). A
    rescore with no closing record is listed as `stopped`
    (`rescores/<eval-id>/<rescore-id>`).
  - New findings: `missing_rescore` (a sample names a rescore that is not
    in the store, that has no record of the sample, or that rescores an
    eval the sample's copy did not come through; the sample is not
    compared), `rescore_mismatch` (the samples of a file name different
    latest rescores of the eval; an honest rescore rescores every sample,
    so this catches a sample put back to its copy from before a rescore),
    `rescore_without_eval` (a rescore under an eval id with no other
    records). Existing kinds cover the rest: `nonce` for a rescore record
    whose nonce is not the eval's, `missing_start` and `malformed_record`
    for rescore records, `missing_eval_closing` for a
    finished file whose latest rescore has no closing record,
    `score_mismatch` and `event_mismatch` (messages say "after rescores
    ...") and `eval_mismatch`.
  - A rescore sample record whose events are not one top-level scorers
    span is `malformed_record`, not a validator crash: score.py's
    `_get_updated_events` unpacks one span, and an overwrite asserts that
    the scorers span's parent is in the tree.

### Changes from the plan

Eric's change during the build (Nov-25): rescore authority is the eval's
nonce, passed back in. The plan's per-rescore nonce and its "Decision for
Eric" (a separate rescorer role under `rescores/`) are replaced by it.

Agreed with the coordinator before the build:

1. The rescore a sample built on is in each rescore sample record, not
   in the start record. With `--stream` the rescorer has only the log
   header when it writes the start record; samples are read one at a
   time while they are scored.
2. The marker names the eval id as well as the rescore id. `eval_retry`
   copies samples from a rescored prior .eval, so a reused sample's
   marker names the prior eval's rescore (an honest case; test
   `test_eval_retry_of_rescored_log_validates`). The latest marker is not
   the last one in the events: an append moves the new events under the
   old scorers span but leaves their span ids pointing at the dropped new
   span, so a later append reorders them. It was the one no other marker
   named as `built_on`; review round 12 replaced that with the longest
   chain.
3. The rescore sample record holds the new events as JSON with
   attachments resolved, not buffer rows (the rescorer has no sample
   buffer, and the validator compares with full resolution). The closing
   record does not list the samples rescored: nothing would check the
   list (the eval's nonce covers forged records, and `rescore_mismatch` a
   sample put back to its unrescored copy).

### Review round 11: fixes

Review of 53c971c8a (Claude Opus 5.5, fresh context).

1. **A rescore copied from another eval passed.** The chain followed any
   rescore a marker named. An editor with no nonce and no store access
   could copy eval B's rescored scores and scorer events (marker
   included) from B's .eval onto eval A's sample; A's results were still
   compared with A's own closing record, and the file passed. The same
   let a retry take its prior eval's rescore of a sample the retry ran
   itself. Now each rescore in a sample's chain must be of an eval on
   the `_prior_evals` path from the file's eval back to the eval that
   closed the sample's attempt (the file's eval for a sample it ran);
   otherwise `missing_rescore`. A reused sample can still name the
   rescores of the evals it came through
   (`test_eval_retry_of_rescored_log_validates`). Tests:
   `test_rescore_of_another_eval`,
   `test_retry_takes_prior_rescore_of_own_sample`. Both failed at
   53c971c8a, where the validator passed the file.
2. **Epochs reducer.** The rescore closing record does not hold it, and
   the validator does not compare it. The results are compared,
   and each of their scores names its reducer (`EvalScore.reducer`), so
   a header reducer that differs while the results match changes only
   the eval spec, which is not checked.
3. **Test.** `test_rescore_record_without_scorers_span` now adds a marker
   naming the rescore to the sample, so the chain is applied. It gives
   `malformed_record` and `missing_rescore`; without the scorers span
   check the validator would crash in `_get_updated_events`.

### Review round 12: fixes

Review of 49678616e (Claude Opus 5.5, fresh context).

1. **Append, overwrite, overwrite failed.** An overwrite replaces the
   scorers span, but an append's events sit outside it after a re-read,
   so a later overwrite keeps the append's marker. After append r1,
   overwrite r2, overwrite r3 the markers were r3 (built on r2) and r1;
   r2's was gone, so nothing named r1, and the rule "the marker no other
   marker names" picked r1. The validator then applied only r1 and
   reported `score_mismatch`, `event_mismatch` and `eval_mismatch`; a
   fourth rescore stored `built_on` r1. Now each marker holds its chain
   length (`chain_length`), and the latest marker is the one with the
   longest chain. A new rescore's length is one more than the longest in
   its input, so in an honest sample it is longer than every marker left.
   An edited length changes the marker, which the event comparison
   reports. Test: `test_rescore_validates` with append, overwrite,
   overwrite, and the same with an append on top. They failed at
   49678616e; the same chain through three retried evals (review probe
   p8) now passes too.
2. **Docs.** "What Is Not Protected" now says that a retry that was not
   rescored can hold, for a reused sample, its earlier eval's copy from
   before or after a rescore of that eval, and the validator passes it.
   The validator checks `rescore_mismatch` only among the file's own
   eval's rescores; checking more would need to know which rescores the
   retry's copy came with, which the store does not record.

### Review round 13: fixes

Review of 31f614186 (Claude Opus 5.5, fresh context).

1. **Marker `built_on` removed.** After round 12 no code read it: the
   rescorer uses the latest marker's `rescore` for the sample record's
   `built_on`, and the validator follows the sample records' `built_on`.
   The marker is still compared as an event with the stored records.

### Guarantees

A rescored sample in a .eval file must match the original run's records
with each stored rescore of its chain applied as `inspect score` applies
it, and each of those rescores must be of an eval the sample's copy came
through; a rescored file's results must match its latest rescore's
closing record, and its status and stats the eval closing record. Every
rescore record must have the eval's nonce. A rescore is a claim by
whoever held that nonce: the validator lists it and does not vouch for
it.

### Not changed

- A nonce, once handed out, works for every later rescore of the eval.
  A process compromised during the run already knows it (an existing
  limit). The docs say to give it only to the host that runs the
  rescore.
- The input is not validated before rescoring (the rescorer has add
  rights only). An input edited before the rescore still gives a finding,
  as its other events are checked against the original records.

## The evals that were run

All use mockllm with a scripted output function
(`tests/test_helpers/addonly_agents.py`):

- A react agent. Turn 1 asks for four tool calls in one parallel stage: two
  `add` calls and two calls to a sub-agent used as a tool
  (`as_tool(react(...))`), so two sub-agents run at the same time. Each
  sub-agent calls a `lookup` tool and then submits. Turn 2 calls a serial
  tool (`parallel=False`), which is its own stage. Turn 3 submits.
- 3 samples x 2 epochs at once (`test_agent_eval_validates`), and 20 samples
  x 2 epochs with `max_samples=10` (timing script).
- Streaming: mockllm does not stream. `test_streaming_eval_validates` uses a
  small mockllm subclass that reports stream deltas through the real
  streaming observer, with `generate(on_stream=...)`. The buffer then gets
  pending versions of the model event with partial output.
- Bridged host tools: the existing in-process scaffold of
  `tests/agent/test_bridge_approval.py` (`host_scaffold`, which runs every
  call it gets as a bridged host tool through `SandboxAgentBridge`), in a
  real eval: two rounds of two calls, then an answer. Run with the calls in
  parallel (as the scaffold does) and one at a time.

Note: tools are serial unless they set `parallel=True` (current `main`). A
first run without it ran every call as its own stage.

The records of one sample in the timing run (one line per write):

```
1: span_begin:init, sample_init, span_end, span_begin:solvers, span_begin:react, span_begin:react, model pending
2: model, model
3: span_begin:add, tool:add pending, span_begin:add, tool:add pending, span_begin:researcher, tool:researcher pending, span_begin:researcher, span_begin:researcher, tool:researcher pending, span_begin:researcher, model pending
4: model pending
5: span_end, span_end, tool:add, tool:add, model, model
6: model, model
7: span_begin:lookup, tool:lookup pending, span_begin:lookup, tool:lookup pending, span_end, tool:lookup, model pending
8: span_end, tool:lookup, model, model
9: model pending
10: span_begin:submit, tool:submit pending, span_end, tool:submit, model, model
11: span_end, span_end, tool:researcher, span_begin:submit, tool:submit pending, span_end, tool:submit, span_end, span_end, tool:researcher, model pending
12: model, model
13: span_begin:note, tool:note pending, span_end, tool:note, model pending
14: model, model
15: span_begin:submit, tool:submit pending, span_end, tool:submit, span_end, state, span_end, span_end, span_begin:scorers, span_begin:includes, score, span_end, span_end
```

Write 2 is the boundary before the parallel stage: it holds the response
that asked for the tools. The researcher tool events are stored pending in
write 3 and complete in a later write, after writes made by the sub-agents.
With overlapping puts, the two sub-agents' first boundaries now often make
two writes where step 1 made one (one sub-agent's write is in flight while
the other reads its new rows), so the layout differs from step 1 run to
run.

## Answers

### 1. No legitimate late event versions

The validator flags any version of an event that comes in a later record
than one where the event was stored complete (not `pending`). It found none
in:

- `test_agent_eval_validates`: 6 samples. The test also asserts that some
  tool events were stored pending and completed in a later record, so the
  legitimate case (an event that spans boundaries) did occur.
- `test_streaming_eval_validates`: pending model versions with partial
  output, then the complete version.
- `test_host_tools_against_addonly_store[parallel]`: bridged host tools
  called two at a time.
- The timing script: 40 samples per run, 0 findings.

`test_late_event_version_flagged` shows the rule flags a late version and
accepts pending-then-complete and several versions in one record.

The model event's second complete version (timing fields set and the event
sent again, `model/_model.py:1249`) was in the same record as the first in
every run.

The two updates the plan leaves open:

- **Bridge `message_id`** (`agent/_bridge/types.py:726`). Seen in a run:
  with the new boundary, the update is a late version when a scaffold calls
  bridged host tools one at a time. The second call's boundary stores the
  first call complete (no `message_id`), and the bridge sets `message_id`
  when the scaffold's next request arrives, in the next record.
  `test_host_tools_against_addonly_store[serial]` gets 2
  `late_event_version` findings, one per round. When the scaffold calls them
  in parallel, both calls finish before the next request, and its boundary
  stores the completion and the update together: no finding. Records of the
  serial run:

  ```
  2 model, model
  3 span_begin, tool:read_file pending, span_end, tool:read_file (no message_id)
  4 span_begin, tool:read_file pending, span_end, tool:read_file (no message_id),
    tool:read_file (message_id set), tool:read_file (message_id set), model pending
  ```

- **Sentinel sidecar timing** (`_sentinel/_sidecar/_judging.py:98`). Not
  run. From the code: `count_judging_as_waiting` runs in the `finally` of
  `Model._generate` (`model/_model.py:1303`), after
  `await request_result(...)` asks the sidecar what it decided
  (`model/_model.py:1273`), which can wait while the sidecar judges. The
  sidecar output update (`model/_model.py:1293`) comes after the same
  `await`. No boundary of the same agent falls in between. But a boundary
  of another sub-agent of the same sample can run during that `await`, and
  it stores the model event complete; both updates would then be late
  versions. A sample with one agent does not have this problem.

The other callers of `Transcript._event_updated` (`_call_tools.py`,
`_stream.py`, `log/_samples.py:786`, `util/_subtask.py`,
`agent/_acp/transport_live.py`, `agent/_bridge/sandbox/host_tool.py`)
update pending events only.

### 2. Every buffered event has a uuid

True. The only writer of sample event rows is the transcript subscriber
(`_eval/task/run.py`, `on_sample_event`, which calls
`TaskLogger.log_sample_event`). Each event gets its uuid before any
subscriber sees it:

- `BaseEvent.model_post_init` sets `uuid` unless the event is being read
  from a log (`event/_base.py:69`).
- `Transcript._event` calls `_ensure_event_key` before it notifies
  subscribers (`log/_transcript.py:698`, then `:710`).
- Restored checkpoint events get uuids in `_normalize_seeded_events`.

So the fallback `event.event.uuid or uuid()` at `buffer/database.py:424`
does not fire for sample events. The validator checks every stored row:
the row's `event_id` must equal the `uuid` in the event JSON
(`event_without_uuid`). No run had a finding.

### 3. Rebuilt samples match samples logged from memory

True for every sample run once the fix below was in. None of these evals
evicted events, so every .eval sample was logged from memory. The validator
rebuilds each sample from its records with the plan's read-back code: it
inserts the stored rows into a new sample buffer, then calls
`open_sample_history` and `materialize_streaming_sample` (the code at
`_eval/task/run.py` that logs a sample whose events were evicted). It reads
the .eval sample with attachments resolved in full, and compares each
event's JSON field by field.

The comparison covers events. The other sample fields come from the .eval
copy; the store keeps only the scores (in the sample closing record).

`test_edit_eval_file_detected` shows the comparison finds an edit (one tool
result changed in the .eval file).

#### Events lost when a worker thread logs a warning

Step 1b found a real loss of events, not a validator error. With
overlapping puts, about one timing run in 17 had one `event_mismatch`: a
tool event's completion was in the .eval file but not in the store, and the
store had only its pending version. The sample buffer never got the
completion row, so no record could hold it.

The cause:

1. With more than 10 puts in flight on one boto3 client (its default pool
   size), urllib3 logs "Connection pool is full, discarding connection" in
   the put's worker thread.
2. `anyio.to_thread.run_sync` copies the context, so `transcript()` in that
   thread is the sample's transcript, and Inspect's log handler records the
   warning there as a `LoggerEvent` (`_util/logger.py:274`), from the worker
   thread.
3. `Transcript._notify_subscribers` (`log/_transcript.py:845`) skips a
   subscriber that is already being notified (`_notifying_subscribers`).
   The set is per transcript, not per thread. While the worker thread is
   inside the buffer subscriber (inserting its `LoggerEvent`), an event that
   the event loop thread records at the same time skips the buffer. No
   error is raised, so the rule for a failed insert (change 2) does not
   catch it.

Evidence: a probe found the pool warnings as `LoggerEvent`s in 6 of 20
samples of one timing run; the mismatched sample's records had two such
`LoggerEvent`s next to the missing completion; and a 15-line script with
two threads shows the event loop thread's event skipping a subscriber that
the other thread is inside.

Fix in this branch: the store's client has a pool of 50 connections
(`_store.py:83`, the value `AsyncFilesystem` uses), so its puts no longer
log the warning at this concurrency. After the fix, 25 more runs of the
20 x 2 eval (1,000 samples) had no `LoggerEvent` and no finding. The
underlying problem stays: any warning logged from a worker thread during a
sample (a bigger eval that fills 50 connections, or any other library
called through `to_thread`) can make the buffer skip an event of that
sample. This is in inspect_ai today: the same loss affects the sample
buffer that live viewing reads.

### 4. Time per boundary write

Against a local moto server on the same host, not real S3. The numbers show
this code's own cost and moto's, not S3 latency. "Wait" is the time the
sample waits at a boundary: reading rows from SQLite, JSON, the put, and
waiting for earlier records of the same sample.

| Run | Writes | Wait median / p95 / max | Put median / p95 | Record size median / max |
| --- | --- | --- | --- | --- |
| Step 1b, 1 sample | 15 | 4.5 / 15.6 / 16.3 ms | 3.9 / 7.1 ms | 5.8 / 10.6 KiB |
| Step 1b, 20 samples x 2 epochs, 10 at once | 600 | 34.4 / 65.3 / 90.4 ms | 27.2 / 49.9 ms | 6.5 / 10.6 KiB |
| Step 1, 1 sample (one lock per sample) | 15 | 5.8 / 8.5 / 11.1 ms | 3.7 / 5.7 ms | 5.6 / 10.6 KiB |
| Step 1, 20 samples x 2 epochs, 10 at once | 600 | 32.0 / 68.8 / 96.1 ms | 23.0 / 35.9 ms | 6.5 / 10.6 KiB |

Wall time for the larger eval in step 1b: 1.96 s without the store, 3.23 s with it (step 1: 1.88 s and 2.98 s). mockllm answers at once, so this is the whole cost of the writes. The host has 8 cores. Run-to-run spread is wide on this host: three step 1b runs of the larger eval before the pool change gave wait p95 58 to 63 ms and put median 26 ms.

With overlapping puts, the p95 wait is closer to the p95 put than in step 1
(where the p95 wait was nearly twice the p95 put), because a sub-agent no
longer waits for the other's put to finish before it starts its own. The
median put is a little slower, since moto serves more puts at once. The
plan's estimate of tens of milliseconds for a real S3 put is not tested.

## What moto does and does not enforce

From `scripts/addonly_moto_probe.py`:

```
action                                                       real S3 (docs)                moto
host: put new key, If-None-Match                             allowed                       allowed
host: put same key, If-None-Match                            refused (412)                 refused (PreconditionFailed)
host: put same key, no If-None-Match (no bucket policy)      allowed, adds a version       allowed
  versions of 'a' now                                        2                             2
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

- `If-None-Match: *` on PutObject: enforced (412). Also on
  CompleteMultipartUpload.
- Compliance-mode Object Lock: partly. moto refuses to delete a locked
  version, even with the governance bypass. But moto lets anyone shorten
  compliance retention and then delete the version, and lets versioning be
  suspended on an Object Lock bucket. Real S3 refuses both. So moto cannot
  show that compliance mode keeps originals.
- Bucket policy that requires If-None-Match: not enforced. moto applies the
  Deny but ignores the `s3:if-none-match` condition key, so it refuses every
  put, with or without the header. An IAM Allow with the same condition is
  also not checked. The tests set this policy only after the eval has
  written, so the validator's settings check has a policy to read.
- IAM (with `INITIAL_NO_AUTH_ACTION_COUNT`): moto enforces user policies on
  S3 actions. This made the start check real: the eval host user can put,
  and cannot get, delete or change settings. moto files the Object Lock
  settings read under `s3:ListBucket` (real S3:
  `s3:GetBucketObjectLockConfiguration`), so the moto eval host user can
  also list.
- With IAM on, moto's signature check fails for a `/` in a list Prefix and
  for a `%` in a key. The validator lists without the trailing `/` and
  filters. The moto tests use sample ids that need no encoding; a unit test
  covers the encoding. The same check fails on a paginated listing once a
  prefix holds more than 1,000 versions (the next page's key marker has a
  `/`), so the probes use a new prefix per run.
- A multipart object's arrival time in moto is when the upload completed.
  The plan (from AWS docs) says S3 uses the time the upload started. Not
  testable on moto.

The plan's assumption 1 (AWS enforces compliance mode and the If-None-Match
policy) can only be checked on real AWS.

## Decisions made

Eric was away for step 1. I made these decisions without him. Step 1b
changed decisions 2, 3, 5 and 6, and added 14 and 15; each change is marked.

1. Store location: *changed in review round 1* from the env var
   `INSPECT_ADDONLY_STORE` to the eval option `tamper_evident_store`
   (CLI `--tamper-evident-store`). The log does not record it; a retry is
   given it again. The validator takes `--store` (or
   `INSPECT_VALIDATE_STORE`), never the .eval file.
2. Client: synchronous boto3 in a worker thread (`anyio.to_thread`), from a
   new boto3 session per eval. This works under asyncio and trio, and
   avoids fsspec. A new session is needed because the default session keeps
   the first credentials it found. *Changed in 1b:* the eval host's client
   has SDK retries off and a pool of 50 connections.
3. *Changed in 1b (was: botocore's own retries, no time limit).* Retries:
   the eval's own loop, SDK retries off. It retries network errors,
   throttling, 5xx and `ConditionalRequestConflict` for up to 60 s, and
   fails on any other error, including every 412. The 60 s is a placeholder;
   the plan's open decision on the time limit stays open.
4. A boundary with no new rows writes nothing. (In 1b it still waits for
   the records already numbered.)
5. *Replaced in 1b (was: one lock per sample attempt).* No lock. A write
   reads the rows and takes the sequence number with no `await` between
   them, puts outside that step, and waits until every record numbered up to
   its own is confirmed.
6. After a failed write, the attempt writes nothing more: later boundaries
   in the same sample raise, and there is no closing record. The validator
   then reports the attempt as cut short (`test_failed_write_stops_eval`,
   which removes the eval host's write permission from inside a tool).
   *Extended in 1b:* the same holds after a failed buffer insert.
   *Changed Nov-25:* the attempt is listed as stopped; the logged sample
   gives `unstored_sample`.
7. A failed write fails the eval even with `fail_on_error=False` and
   `retry_on_error` set.
8. The sample closing record is written after scoring and before the .eval
   sample is written, for every outcome except a retry. The eval closing
   record is written after the .eval file is finished, so a store outage
   still leaves a finished copy.
9. Records are JSON. Buffer rows are kept as the buffer's own text.
10. The validator reads the earliest version of a key that has several. It
    compares events only (*step 1c:* also the scores and the eval's status,
    stats and results, which the closing records hold; Eric kept events as
    the record, so messages and output are not compared), with attachments and pools resolved in full. It
    treats an event as complete when its JSON has no true `pending`.
11. Multipart detection: an ETag with a `-`. A real build would use
    GetObjectAttributes.
12. The sample id in a key is URL-encoded, and `.` is also encoded as
    `%2E` (now in the plan).
13. This note is in `design/`, the repo's design notes folder. `docs/` is
    the source of the public website.
14. *New in 1b.* A failed buffer insert is an ordinary sample error
    (`SampleBufferInsertError`), not an add-only store error: it stops the
    sample, and `fail_on_error` and `retry_on_error` decide what happens to
    the eval. The plan says "stops the sample"; a failed write still stops
    the eval.
15. *New in 1b.* Validator scope: one store prefix per log directory, given
    to both the eval and the validator. No new option.

## Plan issues these runs still find

Plan v81 fixed the six plan errors of step 1 (412 after a retried put,
failed buffer insert, bridged host tools, `.` in keys, sub-agents waiting
for each other, validator scope). These remain or are new:

1. **Events can skip the sample buffer with no error.** A warning logged
   from a worker thread during a sample makes the transcript skip the
   buffer for events recorded at the same time (see
   [Events lost when a worker thread logs a warning](#events-lost-when-a-worker-thread-logs-a-warning)).
   The plan's rule "a failed insert stops the sample" assumes the insert is
   tried; here it is not. The plan needs every event to reach the buffer,
   which means fixing the transcript's re-entry check across threads (or
   not recording worker-thread log records in the sample transcript) in
   core. This branch only removed its own trigger.
2. **Sidecar updates with sub-agents.** The plan says the sidecar's output
   update and timing update happen "inside the generate call or tool call,
   before the next boundary". That holds for the agent that made the call,
   but not for the sample: another sub-agent's boundary can run while the
   generate call waits for the sidecar's decision, and store the model event
   complete. Both updates are then late versions. From code reading; not
   run.
3. **Bridge `message_id`.** Confirmed as a late version, but only when a
   scaffold calls bridged host tools one at a time; parallel calls do not
   make one. The open question can be narrowed to that case.
4. **Empty boundaries must wait too.** The plan says "each boundary waits
   until every earlier number is confirmed". A boundary with no new rows
   takes no number, but it must still wait for every number already taken:
   a record still in flight can hold rows that its own agent recorded.
5. **A failed insert after the last boundary.** The plan's "a failed insert
   stops the sample" cannot apply when no boundary follows (scoring with no
   model call). The sample is logged; the store has no closing record for
   it, so the validator reports it cut short. The plan could say this is
   the expected result. (*Nov-25:* the attempt is listed as stopped, and
   the logged sample gives `unstored_sample`; see
   [Stopped attempts and evals](#stopped-attempts-and-evals).)

## What a real build would change

- Use an async S3 client (aiobotocore, as `AsyncFilesystem` does) with
  connection reuse.
- Set the retry time limit (this branch uses 60 s).
- Make sure every event of a sample reaches the buffer, also when a worker
  thread logs during the sample (plan issue 1).
- Settle the bridge `message_id` update and the sentinel sidecar updates
  (plan issues 2 and 3).
- Validator: parallel reads, JSON output, the hash index of Appendix C, and
  GetObjectAttributes for multipart detection.
- Records for re-scores and shard merges (out of scope here; retries are
  done).
- Test compliance mode, the If-None-Match policy and real put latency in a
  sandbox AWS account.

## Validation runs (review round 3)

Code at 144b3b161 (the last commit before this note changes only docs).
moto server only:

- Each fix's test failed before the fix: `missing_sample` for s1.1
  (`test_eval_set_narrower_retry_validates[sample_id]`) and s1.2
  (`[epochs]`); exit 0 with no `prior_without_file` line
  (`test_forged_successor_lists_deleted_eval_file`); exit 0, no
  `missing_eval_file` (`test_eval_names_itself_as_prior`).
- `pytest tests/log/test_addonly_store.py -n 4` (with
  `ADDONLY_EVIDENCE_DIR` set): 79 passed, 4 skipped (trio variants); with
  `--runtrio`, the 4 trio variants pass. 63 output files.
- `pytest tests/sentinel/test_sentinel_config.py -n 4`: 63 passed.
- `pytest tests/log -n 4` (with `.venv/bin` on `PATH`): 2,378 passed, 510
  skipped, 0 failed.
- `pytest tests/test_retry.py tests/test_eval_set.py
  tests/test_eval_set_overrides.py tests/test_sample_source.py
  tests/test_eval.py -n 4`: 535 passed, 44 skipped, 0 failed.
- `ruff check .`, `ruff format --check .`, `mypy --exclude
  tests/test_package src tests`, mypy on the two scripts: clean.

## Validation runs (review round 2)

Code at ef6e2ddbc, plus the test fix in the next commit (one stub in
`tests/test_eval_set.py`). moto server only:

- `pytest tests/log/test_addonly_store.py -n 4` (with
  `ADDONLY_EVIDENCE_DIR` set): 75 passed, 4 skipped (trio variants); with
  `--runtrio`, the 4 trio variants pass. 59 output files.
- `pytest tests/log -n 4` (with `.venv/bin` on `PATH`): 2,374 passed, 510
  skipped, 0 failed.
- `pytest tests/agent/test_bridge_approval.py tests/test_retry.py
  tests/test_eval_set.py tests/test_eval_set_overrides.py tests/test_eval.py
  tests/test_task_cancel.py -n 4`: 1,937 passed, 1,312 skipped, 0 failed,
  after the stub fix. Before it: 1 failed
  (`test_retry_abandoned_during_seed_never_starts_the_log`, a `log_start`
  stub with two arguments).
- PR CI at 77acc34d6 found two more `log_start` stubs with two arguments,
  in `tests/test_sample_source.py` (14 failed); fixed in d4a7f53d5, and
  `pytest tests/test_sample_source.py -n 4` then gave 108 passed. Also
  failing in CI, not from this round:
  `test_sentinel_is_the_last_positional_parameter` (3 tests; fails since
  `tamper_evident_store` was added after `sentinel_proxy`, at 482060faa
  too) and `test_shared_action_calls_pin_one_sha` (fails on `main` too).
- `ruff check .`, `ruff format --check .`, `mypy --exclude
  tests/test_package src tests`, mypy on the two scripts: clean.
- eval_set with a retry against moto: `test_eval_set_retry_validates[False]`
  (`retry_cleanup=False`) gives 2 evals, 4 samples compared, 0 findings;
  `[True]` (the default cleanup) gives 2 evals, 2 samples compared, 0
  findings.

## Validation runs (review round 1)

At 408cf8bd0, moto server only:

- `pytest tests/log/test_addonly_store.py -n 4`: 66 passed, 4 skipped
  (trio variants); with `--runtrio`, the 4 trio variants pass.
- `pytest tests/log -n 4` (with `.venv/bin` on `PATH`): 2,365 passed, 510
  skipped, 0 failed.
- `pytest tests/agent/test_bridge_approval.py tests/test_retry.py
  tests/test_eval_set.py tests/test_eval_set_overrides.py tests/test_eval.py
  -n 4`: 1,876 passed, 1,279 skipped, 0 failed (at 0d1ea78ba; the next
  commit changes only a test helper used by `tests/log`).
- `ruff check .`, `ruff format --check .`, `mypy --exclude
  tests/test_package src tests`, mypy on the two scripts: clean.
- Evidence: `ADDONLY_EVIDENCE_DIR` set for the `test_addonly_store.py` run
  at 0d1ea78ba: 52 output files.

## Validation runs (step 1b)

- `pytest tests/log/test_addonly_store.py`: 17 passed, 4 skipped (trio
  variants); with `--runtrio`, the 4 trio variants pass.
- `pytest tests/agent/test_bridge_approval.py -k "stores_before_it_runs or
  against_addonly"`: 3 passed, 1 skipped (trio variant).
- `pytest tests/log tests/model tests/agent tests/test_eval.py -n 4`:
  11,758 passed, 6,763 skipped (gated and trio), 0 failed, with `.venv/bin`
  on `PATH` (one test runs the `inspect` command; without it on `PATH`
  that test fails with `FileNotFoundError`).
- `ruff check`, `ruff format`, `mypy --exclude tests/test_package src tests`
  (plus the timing script): clean.

## Validation edge cases

The user docs (`docs/tamper-evident-logs.qmd`) give one line for each of
these cases. This section has the full text.

### Lost samples and closing records

- **Lost samples.** Each sample attempt writes a closing record at its end, and each eval writes one after it finishes its `.eval` file. A sample in the `.eval` file must have an attempt with a closing record, or the validator reports `unstored_sample`. A sample with a closed attempt must be in the `.eval` file, or the validator reports `missing_sample`. A finished `.eval` file must have its eval closing record, or the validator reports `missing_eval_closing`. Each attempt and eval with no closing record is also listed as `stopped`, and the validator still checks every record that it wrote.

- **Honest runs with a missing closing record.** A sample stops writing without a closing record when its write to the store fails, or when an event cannot go into the local sample buffer. The sample is still in the `.eval` file with its error, so the validator reports `unstored_sample` for a run that was not changed. An eval that finishes its `.eval` file and then cannot write its eval closing record (for example during an S3 outage) gives `missing_eval_closing` in the same way.

### Attempts and evals that stop

- **An attempt or eval that stops writing.** A compromised process can stop writing a sample attempt before its closing record. The validator lists the attempt as `stopped` and does not compare its events with the `.eval` file. If the sample is not in the `.eval` file, or the process writes a later attempt of the sample with a closing record, the stopped attempt's events show only in the store. In the same way, an eval with no closing record and a `.eval` file that is not finished is listed as `stopped`, and its status, stats and results are not compared.

```
stopped LdM2ww.../s0.1/1: No closing record: cut short, or its host stopped writing.
```

The line means that the store has no closing record for the attempt or the eval. The attempt or the eval was cut short, for example by a cancel, an error in another sample, a crash or a retry, or its host stopped writing. The validator still checks every record that it wrote. An eval that stopped before it wrote its `.eval` file has only this line.

- **A sample that a retry stopped running.** A retry copies the samples that the earlier eval completed with an error into its `.eval` file before it runs them again. If the retry stops writing such a sample, its `.eval` file can keep the earlier eval's copy. The validator compares that copy with the records of the nearest earlier eval that closed the sample, so the retry's own stored events for the sample are not compared. The retry's attempt is listed as `stopped`.

- **What a `stopped` line means.** How to interpret a stopped attempt or eval is an open question. It can come from an honest cancel or crash, but a compromised host can also stop writing to hide what a sample did. The validator lists it and does not decide. The same applies to a `not_logged` line.

### Samples not logged by an eval that stopped

- **Samples deleted from the `.eval` file of an eval that stopped.** Inspect writes samples to the `.eval` file in groups of several samples (the `log_buffer` option), not one at a time. So when an honest eval host dies, the store usually has closed samples that are not in the file. When an eval has no closing record and its `.eval` file has the status `started`, the validator lists each closed sample that is not in the file as `not_logged`. So if someone deletes samples from the `.eval` file of such an eval, the validator shows a `not_logged` line for each sample, not a finding. An eval with no closing record, no closed sample attempt and no `.eval` file is listed only as `stopped`. An eval with a closed sample attempt and no `.eval` file is a `missing_eval_file` finding, because an honest eval writes its `.eval` file before any sample runs.

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

### A retry that stops early

- **A retry that stops early.** A retry must keep each sample that the earlier eval completed without an error and that the retry selects (by its sample ids and number of epochs), or the validator reports `missing_sample`. A retry copies these samples into its log before it runs any sample, so it usually keeps them. But in these cases a retry that stops before it runs the sample has no copy and no records of it, and the validator reports a `missing_sample` for a run that was not changed: the earlier `.eval` file was gone when the retry started, or `log_samples` is off; a dataset that adds samples while it runs, with `limit` set, was cancelled; or the earlier eval stopped after it stored the sample and before the sample was in its `.eval` file. Each of these can also be true of an eval further back in a chain of retries. A later retry that completes keeps the samples. If eval_set deletes the stopped retry's `.eval` file, the finding goes away. A retry that stops before it finishes its `.eval` file lists the sample as `not_logged` instead.

## Known limits

- A rescore is a claim by whoever held the eval's nonce and could add to
  the store. A handed-out nonce works for every later rescore of the
  eval. See [Rescore support](#rescore-support).
- A nonce holder's scorers span whose parent is not in the events crashes
  the validator in `_get_updated_events` on an overwrite rescore.
- A retry that was not rescored can hold, for a reused sample, the
  earlier eval's copy from before or after a rescore of that eval; it
  passes (review round 12, fix 2).
- A retry's `prior_eval_id` is a claim by the retry's eval host. The
  earlier eval's records are protected, so a reused sample is still
  checked against them; a wrong id gives a finding for each reused sample.
- A retry that stops early can give a false `missing_sample` (review
  round 2, fix 3, cases a to c). A retry that stops before it finishes
  its .eval file lists the sample as `not_logged` instead.
- A deleted .eval file of an eval that a later eval names is not a
  finding (review round 2, fix 5); it is listed as `prior_without_file`
  (review round 3, fix 2). Eval-host keys can forge such a later eval.
- A copied errored sample deleted from a retry's .eval, before the retry
  runs it again, is not reported (review round 3, fix 4).
- A stopped attempt or eval is listed, not a finding. How to interpret it
  (an honest cancel or crash, or a compromised host that stops writing to
  hide what a sample did) is an open question. A compromised process that
  stops writing an attempt, and keeps the sample out of the .eval file or
  writes a later closed attempt, leaves the stopped attempt's events in
  the store only.
- A failed write or a failed buffer insert gives `unstored_sample`, and an
  eval closing record that cannot be written after the .eval file is
  finished gives `missing_eval_closing`, for runs that were not changed.
  In a retry that runs a sample again that the prior eval closed with an
  error, a failed write or buffer insert gives `event_mismatch` "(reused
  from ...)" instead: the retry's copy has no closed attempt, so it is
  compared with the prior eval's records.
- A sample deleted from the .eval file of an eval that stopped before it
  finished the file (no eval closing record, status `started`) is listed
  as `not_logged`, not a finding. An honest crash leaves such samples.

## Not tested

- Real S3 (by instruction).
- The `--tamper-evident-store` CLI flag: passed through (mypy-checked),
  but no CLI eval ran with it. `eval_set()` ran with a retry in review
  round 2.
- Trio: the unit tests of the writer and the store run under trio; no eval
  ran under trio.
- The sentinel sidecar, sandboxed bridged agents (the bridge runs in
  process), checkpoint resume, evicted events (the buffer read-back path at log time), and large
  model inputs.
