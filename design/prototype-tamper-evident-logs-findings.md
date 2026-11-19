# Prototype findings: tamper-evident eval logs, step 1

Spec: the plan "Tamper-evident eval logs" (v80). Branch
`epatey/tamper-evident-logs-prototype`, from `main` at ec5d110b1. Built by
Claude Code on Opus 5.5 (`claude-opus-5-5`), session default effort.

All runs use a local S3 emulator: moto server 5.2.2 on 127.0.0.1, in a
subprocess with IAM enforcement on. No AWS calls were made. No AWS
credentials other than moto's fake keys were used. Nothing was installed
outside the project venv (`uv sync --locked` only).

This is prototype code. It answers the plan's four questions. It is not
ready for review as a feature.

## Summary

| Question | Answer | Evidence |
| --- | --- | --- |
| 1. No legitimate event version is written after the event is complete and a boundary stored it | True for every path run. Two paths that were not run can break it (see below). | `test_agent_eval_validates`, `test_streaming_eval_validates`, timing script (40 samples, 0 findings); rule proven by `test_late_event_version_flagged` |
| 2. Every buffered event has a uuid | True. The `uuid()` fallback at `buffer/database.py:424` never fires for sample events. | Code path below; validator check `event_without_uuid` found none in any run |
| 3. A sample rebuilt from buffer rows matches the sample logged from memory | True for every sample run (events compared field by field). | `test_agent_eval_validates` (6 samples), `test_streaming_eval_validates`, timing script (40 samples) |
| 4. Time per boundary write | Local moto, not S3: median 5.8 ms with 1 sample (put alone 3.7 ms). Median 32 ms, p95 69 ms with 10 samples at once (put alone 23 ms). | `scripts/prototype_addonly_timing.py` |

## What was built

- `src/inspect_ai/log/_addonly/`
  - `_store.py`: the store client. Each put sends `If-None-Match: *`. The
    check before the eval starts writes the start record, writes it again
    (must get 412), tries to read and delete it (must be denied), and reads
    the Object Lock settings (must be enabled, COMPLIANCE).
  - `_records.py`: record models and keys, as in the plan:
    `<eval-id>/start`, `<eval-id>/closing`,
    `<eval-id>/<sample-id>.<epoch>/<attempt>/<seq>`,
    `<eval-id>/<sample-id>.<epoch>/<attempt>/closing`.
  - `_writer.py`: `EvalRecordWriter` (holds the nonce, in memory only) and
    `SampleRecordWriter` (one sequence per sample attempt). `store_boundary()`
    writes the current sample's new buffer rows and waits for the store.
  - `_validate.py`: the validator.
- Buffer: `SampleBufferDatabase.sample_row_marks`, `sample_rows_after` (rows
  after a per-table row id, in insertion order) and `insert_sample_rows`
  (used by the validator to rebuild a sample).
- Boundaries:
  - before each generate request: `model/_model.py:1909`, inside `send()`,
    so retries and resends also write first;
  - before each stage of tool calls: `model/_call_tools.py:706`;
  - at sample end, after scoring: `_eval/task/run.py:3666` (last rows, then
    the sample closing record).
- `TaskLogger.log_start` writes the start record and runs the check before
  any sample starts. `TaskLogger.log_finish` writes the eval closing record.
- A failed write stops the eval: `AddOnlyStoreError` turns off retries and
  scoring for the sample (`run.py`), and always fails the eval, whatever
  `fail_on_error` says (`_eval/task/error.py`).
- `inspect validate LOG_DIR --store s3://bucket/prefix`
  (`_cli/validate.py`). Checks: bucket settings (COMPLIANCE lock,
  versioning, a policy that denies a put without If-None-Match), one version
  per key, no delete markers, multipart uploads, a start record, nonces,
  sequence gaps, sample and eval closing records, record counts, attempts
  missing from the eval closing list, late event versions, events without a
  uuid, a .eval file for each eval, and the .eval events against the stored
  events. It exits non-zero on any finding. `--verbose` lists each record
  with its arrival time.
- Tests: `tests/log/test_addonly_store.py` (10 tests),
  `tests/test_helpers/addonly_moto.py` (moto setup),
  `tests/test_helpers/addonly_agents.py` (scripted agents).
- Scripts: `scripts/prototype_addonly_timing.py`,
  `scripts/prototype_addonly_moto_probe.py`.

Run them from the repo root:

```bash
pytest tests/log/test_addonly_store.py
PYTHONPATH=tests python scripts/prototype_addonly_timing.py
PYTHONPATH=tests python scripts/prototype_addonly_moto_probe.py
```

The eval writes to the store when `INSPECT_ADDONLY_STORE=s3://bucket/prefix`
is set. It needs `log_realtime` (the default), and fails at start without
it.

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

Note: tools are serial unless they set `parallel=True` (current `main`). A
first run without it ran every call as its own stage.

The records of one sample in the timing run (one line per write):

```
1: span_begin:init, sample_init, span_end, span_begin:solvers, span_begin:react, span_begin:react, model pending
2: model, model
3: span_begin:add, tool:add pending, span_begin:add, tool:add pending, span_begin:researcher, tool:researcher pending, span_begin:researcher, span_begin:researcher, tool:researcher pending, span_begin:researcher, model pending, model pending
4: span_end, span_end, tool:add, tool:add
5: model, model
6: model, model
7: span_begin:lookup, tool:lookup pending, span_begin:lookup, tool:lookup pending, span_end, tool:lookup, model pending
8: span_end, model, model, tool:lookup
9: model pending
10: span_begin:submit, tool:submit pending, span_end, tool:submit, span_end, span_end, model, model
11: tool:researcher, span_begin:submit, tool:submit pending, span_end, tool:submit, span_end, span_end, tool:researcher, model pending
12: model, model
13: span_begin:note, tool:note pending, span_end, tool:note, model pending
14: model, model
15: span_begin:submit, tool:submit pending, span_end, tool:submit, span_end, state, span_end, span_end, span_begin:scorers, span_begin:includes, score, span_end, span_end
```

Write 2 is the boundary before the parallel stage: it holds the response
that asked for the tools. The two researcher tool events are stored pending
in write 3 and complete in write 11, after six writes made by the
sub-agents. Write 4 is the second sub-agent's boundary; it holds the `add`
outputs that finished while the first sub-agent's write was waiting.

## Answers

### 1. No legitimate late event versions

True for every path run. The validator flags any version of an event that
comes in a later record than one where the event was stored complete (not
`pending`). It found none in:

- `test_agent_eval_validates`: 6 samples. The test also asserts that some
  tool events were stored pending and completed in a later record, so the
  legitimate case (an event that spans boundaries) did occur.
- `test_streaming_eval_validates`: pending model versions with partial
  output, then the complete version.
- The timing script: 40 samples, 0 findings.

`test_late_event_version_flagged` shows the rule flags a late version and
accepts pending-then-complete and several versions in one record.

The model event's second complete version (timing fields set and the event
sent again, `model/_model.py:1249`) is always in the same record as the
first ("model, model" above), as the plan says.

Code reading of every `Transcript._event_updated` caller found two paths,
not run here, that can write a version after the event is complete:

- `agent/_bridge/types.py:726` sets `message_id` on a finished bridged
  ToolEvent when the next request from the agent arrives. Today no boundary
  falls between the tool finishing and this update, because bridged host
  tools have no boundary (see Plan errors, item 3). Once that boundary is
  added, this update becomes a late version.
- `_sentinel/_sidecar/_judging.py:98` corrects `working_time` and
  `output.time` of a complete model event after the sentinel sidecar
  judged the call. I did not confirm that this always runs before the next
  boundary.

The other callers (`_call_tools.py`, `_stream.py`, `log/_samples.py:786`,
`util/_subtask.py`, `agent/_acp/transport_live.py`,
`agent/_bridge/sandbox/host_tool.py`) update pending events only.

### 2. Every buffered event has a uuid

True. The only writer of sample event rows is the transcript subscriber
(`_eval/task/run.py:2859`, `TaskLogger.log_sample_event`). Each event gets
its uuid before any subscriber sees it:

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

True for every sample run. None of these evals evicted events, so every
.eval sample was logged from memory. The validator rebuilds each sample from
its records with the plan's read-back code: it inserts the stored rows into
a new sample buffer, then calls `open_sample_history` and
`materialize_streaming_sample` (the code at `_eval/task/run.py` that logs a
sample whose events were evicted). It reads the .eval sample with
attachments resolved in full, and compares each event's JSON field by field.
The 47 samples in these runs compared equal (6 + 1 in tests, 40 in the
timing script).

The comparison covers events. The other sample fields come from the .eval
copy; the store keeps only the scores (in the sample closing record).

`test_edit_eval_file_detected` shows the comparison finds an edit (one tool
result changed in the .eval file).

### 4. Time per boundary write

Against a local moto server on the same host, not real S3. The numbers show
the prototype's own cost and moto's, not S3 latency. "Wait" is the time the
sample waits at a boundary: the lock, reading rows from SQLite, JSON, and
the put.

| Run | Writes | Wait median / p95 / max | Put median / p95 | Record size median / max |
| --- | --- | --- | --- | --- |
| 1 sample | 15 | 5.8 / 8.5 / 11.1 ms | 3.7 / 5.7 ms | 5.6 / 10.6 KiB |
| 20 samples x 2 epochs, 10 at once | 600 | 32.0 / 68.8 / 96.1 ms | 23.0 / 35.9 ms | 6.5 / 10.6 KiB |

Wall time for the larger eval: 1.88 s without the store, 2.98 s with it
(mockllm answers at once, so this is the whole cost of the writes). The
host has 8 cores.

With one sample, the work outside the put is about 1 to 2 ms. With 10
samples at once, the moto server becomes slower, and a boundary in one
sub-agent also waits for a write that another sub-agent of the same sample
started (one sequence per sample). The plan's estimate of tens of
milliseconds for a real S3 put is not tested.

## What moto does and does not enforce

From `scripts/prototype_addonly_moto_probe.py`:

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
  covers the encoding.
- A multipart object's arrival time in moto is when the upload completed.
  The plan (from AWS docs) says S3 uses the time the upload started. Not
  testable on moto.

The plan's assumption 1 (AWS enforces compliance mode and the If-None-Match
policy) can only be checked on real AWS.

## Decisions made

Eric was away. I made these decisions without him:

1. Store location: the env var `INSPECT_ADDONLY_STORE` for the eval. The
   validator takes `--store` (or `INSPECT_VALIDATE_STORE`), never the .eval
   file. A real build would use an eval option.
2. Client: synchronous boto3 in a worker thread (`anyio.to_thread`), from a
   new boto3 session per eval. This works under asyncio and trio, and
   avoids fsspec. A new session is needed because the default session keeps
   the first credentials it found.
3. Retries: botocore's own retries, no extra loop, no time limit. The
   plan's open decision on the time limit stays open. See Plan errors,
   item 1.
4. A boundary with no new rows writes nothing.
5. One lock per sample attempt. The write reads the rows inside the lock,
   so sequence numbers follow row order even when sub-agents reach
   boundaries together.
6. After a failed write, the attempt writes nothing more: later boundaries
   in the same sample raise, and there is no closing record. The validator
   then reports the attempt as cut short (`test_failed_write_stops_eval`,
   which removes the eval host's write permission from inside a tool).
7. A failed write fails the eval even with `fail_on_error=False` and
   `retry_on_error` set.
8. The sample closing record is written after scoring and before the .eval
   sample is written, for every outcome except a retry. The eval closing
   record is written after the .eval file is finished, so a store outage
   still leaves a finished copy.
9. Records are JSON. Buffer rows are kept as the buffer's own text.
10. The validator reads the earliest version of a key that has several. It
    compares events only, with attachments and pools resolved in full. It
    treats an event as complete when its JSON has no true `pending`.
11. Multipart detection: an ETag with a `-`. A real build would use
    GetObjectAttributes.
12. The sample id in a key is URL-encoded, and `.` is also encoded as
    `%2E` (see Plan errors, item 4).
13. This note is in `design/`, the repo's design notes folder. `docs/` is
    the source of the public website.

## Plan errors and gaps the prototype found

1. A 412 can be the eval's own record. The plan says a 412 means a bug or
   an attack, and the eval fails at once. But if a put succeeds and its
   response is lost, the SDK retries and gets 412 for the eval's own
   record. The eval host cannot read the store to check. The plan needs a
   rule for a 412 that follows a retried put. Inspect's `AsyncFilesystem`
   already turns off SDK retries for the final call of a conditional write
   (`_util/asyncfiles.py`, `_s3_final_client`).
2. A failed buffer insert loses events quietly. Writes to the sample buffer
   go through a transcript subscriber, and `Transcript._notify_subscribers`
   logs a subscriber's exception and continues (`log/_transcript.py:854`).
   An event that fails to insert never reaches the store, and the eval goes
   on. The plan names only the failed 10 s upload. With the store on, a
   failed insert must stop the sample.
3. Bridged host tools have no boundary. `agent/_bridge/sandbox/host_tool.py:393`
   runs the tool directly, not through `execute_tools`, so no write comes
   before it. Adding one there turns the `message_id` update at
   `agent/_bridge/types.py:726` into a late version (answer 1).
4. "URL-encoded" does not cover `.`: `quote` leaves it as is. The plan must
   say to encode it.
5. Sub-agents in one sample wait for each other's writes. The plan says
   each sample waits only at its own boundaries. Inside one sample, one
   sequence means one write at a time, so a sub-agent's boundary can wait
   for another sub-agent's write. In the timing run the p95 wait was
   nearly twice the p95 put.
6. Matching eval ids to .eval files needs a scope. The validator lists every
   eval in the store and reports each one with no .eval file in the log
   dir. When many log dirs share one bucket, every eval from another log
   dir is reported. The tests give each test its own prefix for this
   reason. A real build needs a scope: a prefix per log dir, a time window,
   or a list of eval ids.

## What a real build would change

- Use an async S3 client (aiobotocore, as `AsyncFilesystem` does) with
  connection reuse.
- Define the retry time limit and the rule for a 412 after a retry.
- Stop the sample when a buffer insert fails and the store is on.
- Add boundaries to every path that runs a tool outside `execute_tools`
  (bridged host tools at least), and settle the bridge `message_id` update
  and the sentinel timing update.
- Take the sequence number under the lock and put outside it, with each
  boundary waiting for every earlier number to be confirmed. This keeps one
  sequence and lets sub-agents' writes overlap.
- Configure the store through eval options, not an env var.
- Validator: a scope for eval ids, parallel reads, JSON output, the hash
  index of Appendix C, and GetObjectAttributes for multipart detection.
- Records for retries, re-scores and shard merges (out of scope here).
- Test compliance mode, the If-None-Match policy and real put latency in a
  sandbox AWS account.

## Not tested

- Real S3 (by instruction).
- Trio: the code uses only anyio primitives, but no eval ran under trio.
- The sentinel sidecar, the agent bridge, checkpoint resume, sample retries
  (only the stop-on-failure path), evicted events (the buffer read-back
  path at log time), and large model inputs.
