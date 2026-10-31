# Incremental S3 Log Flushes

## Overview

An `.eval` log is written to a local temp zip and copied to its destination
at every flush. On S3, under the asyncio backend, a flush does not re-upload
the whole file. The temp zip only grows between flushes, so the object after
the next flush is the current object's member area followed by the members
written since and a new central directory. The recorder remembers a
**compose prefix** (an S3 object, the ETag it must still carry, and how many
of its leading bytes equal the temp file's), and a flush asks S3 to build the
new object from that range (`UploadPartCopy`) plus the uploaded tail. The
result is byte-identical to a whole upload. The prefix comes from the log's
own previous flush, or, for a seeded retry attempt's first flush, from the
prior attempt's log. Anything that rewrites the temp file's leading bytes
clears the prefix. A changed compose source or an S3 service error falls
back to a whole upload; cancellation and other exceptions propagate.

In the test suite a verification mode digests the prefix when it is recorded
and again before each compose, and fails the flush loudly on a mismatch.

Separately, sample completions that arrive during a slow flush do not queue
redundant flushes of small remainders: a queued buffer-full flush re-checks
the threshold before writing.

The code is `ZipLogFile` in
[`eval.py`](../src/inspect_ai/log/_recorders/eval.py),
`AsyncFilesystem.compose_file()` in
[`asyncfiles.py`](../src/inspect_ai/_util/asyncfiles.py), and
`TaskLogger._flush_pending_samples()` in
[`log.py`](../src/inspect_ai/_eval/task/log.py). Seeding a retry attempt's
log from the prior log is described in
[`retry-seeded-attempt-log.md`](retry-seeded-attempt-log.md).

## Why

A whole-file flush sends the entire log every `log_buffer` completions, so a
run uploads on the order of (flushes × final size) / 2 bytes, and each flush
stalls the sample that triggered it for the length of the upload. A seeded
retry attempt's first flush would upload the whole prior log, which S3
already holds, before any sample runs. Locally a flush is a file copy; the
cost is remote only. See Performance for measurements.

## The compose prefix

`ZipLogFile` keeps its temp file open as an append-mode `ZipFile`. CPython's
append mode seeks to the old central directory, writes new members over it,
and at `close()` writes the central directory and end record at `start_dir`
(the end of the member area) and truncates the file. So bytes
`[0, start_dir)` after one flush are unchanged by every later write until the
temp file itself is replaced, and directory-only prunes change the central
directory, not the member area.

**Invariant:** when `_compose_prefix` is set, the temp file's
`[0, prefix.length)` equals the leading `prefix.length` bytes of the object
`prefix.filename` with ETag `prefix.etag`.

`member_end`, the length of a prefix recorded at a flush, is `start_dir`
read from the closed `ZipFile` just before the write.

| Event | Compose prefix |
|---|---|
| a new log | none |
| a seed adopts the prior log's bytes without rewriting them; prior and destination are both `s3://`; the copy's ETag is known (asyncio) | the prior's key, its ETag, the copy's `start_dir` |
| a seed rewrites the copy (excluded samples or dead bytes), or either location is not S3, or the ETag is unknown (trio, other backends) | none |
| a successful write to S3 under asyncio, composed or whole | the log's own key, the returned ETag, `member_end` |
| a successful local or non-S3 write | none |
| a failed or cancelled write | none |
| a successful compaction (replaces the temp file) | none |
| a failed compaction (reopens the original) | unchanged |
| appended members, directory-only prunes | unchanged |

A prefix is always set and cleared through `_record_compose_prefix()` and
`_clear_compose_prefix()`, which keep its verification digest in step (see
Verification mode).

## The compose primitive

`AsyncFilesystem.can_compose(filename)` is true for an `s3://` URL under the
asyncio backend. `compose_file(filename, prefix, tail)` replaces `filename`
with `prefix`'s leading bytes followed by `tail` from its current position
to EOF, and returns the new ETag:

1. `HeadObject` on the source. A different ETag, a size under
   `prefix.length`, or a missing object raises `ComposeSourceChangedError`.
   The check exists because some S3-compatible stores (moto among them)
   ignore `CopySourceIfMatch`; real S3 enforces both.
2. `CreateMultipartUpload` on the destination. Once it returns an upload
   ID, every exit other than a successful complete aborts the upload under
   a shielded 30 s timeout and re-raises.
3. Copy the prefix as `UploadPartCopy` parts with
   `CopySourceIfMatch` set to the prefix's ETag, at most 32 at a time. The
   prefix is split into equal ranges of about 16 MiB (one part copies at
   about 50 MB/s, so a large prefix is copied in parallel); the part count
   is capped at 5,000, so beyond about 78 GiB the equal ranges grow past
   16 MiB. A `PreconditionFailed` or missing-object error raises
   `ComposeSourceChangedError`.
4. Upload the tail with the same part pipeline the whole-file multipart
   upload uses (`_s3_upload_parts_async`): 8 MiB parts read off the event
   loop, the last possibly tiny.
5. `CompleteMultipartUpload`; the new object replaces the old one
   atomically, and the old one stays readable until then.

`compose_file` raises `ValueError` when `can_compose` is false, the source
is not S3, or the prefix is under `S3_COMPOSE_MIN_PREFIX` (8 MiB, the
multipart threshold, which also keeps every copied part over S3's 5 MiB
minimum). A stale-signature failure is retried from the same tail position,
as whole uploads are.

`read_file_into` returns the ETag of the S3 response its bytes came from
(asyncio only, `None` elsewhere), so a seed's bytes and its ETag describe
the same object version.

## A flush

`flush()` holds `_lock`, closes the zip, records `member_end`, and writes.
For a remote destination `_write_remote()` composes when a prefix is set,
composing is not disabled, the prefix is at least `S3_COMPOSE_MIN_PREFIX`
and `can_compose` holds; otherwise it uploads the whole file:

- `ComposeSourceChangedError`: warn and upload the whole file this time.
  The source changed (another writer replaced the object, or a viewer
  rewrote the prior log's header after the seed), and the whole upload
  records a fresh prefix.
- Any other `ClientError`: warn, set `_compose_disabled`, and upload whole
  logs for the rest of this log. Such a failure (a store without
  `UploadPartCopy`, a policy denying the source read, an encryption key that
  cannot re-encrypt) would recur at every flush.
- Cancellation and other exceptions propagate. The primitive has aborted its
  upload, and `flush()` clears the prefix.

A composed write's trace action is `Log Write` with the message
`"<file> (compose: copy N bytes + upload M bytes)"`, so trace tooling can
tell composed flushes from whole ones.

A flush with nothing new still composes a tail of a central directory and
end record: a few small requests, kept rather than adding a "nothing
changed" test that must hold under directory-only prunes.

### The seeded start flush

A retry attempt's log is seeded from the prior log before `log_start` (see
[`retry-seeded-attempt-log.md`](retry-seeded-attempt-log.md#copy-validate-adopt)).
When the seed adopts the prior's bytes as they are, its temp file is the
prior object byte for byte, so the seed records the prior as the compose
prefix up to the copy's `start_dir`. `log_start`'s flush then copies the
prior's member area server-side and uploads only the summaries journal,
re-journaled config updates, `start.json` and the new central directory.
The prior's pruned metadata members stay as dead bytes in the composed
object, as they would in a whole upload.

Seeds that rewrite the copy (a restricted plan, or a prior with dead bytes),
priors under 8 MiB, priors or destinations off S3, and trio upload whole.
Retry cleanup removes older logs only between eval-set passes and at the
end of the run, so the prior normally exists at `log_start`; if it does not,
the flush falls back to a whole upload.

### Own-key flushes

Every successful S3 write records the log's own object as the next prefix.
Each later flush copies the previous object's member area and uploads the
members written since plus the central directory. A reader opening the
object during a flush sees the previous complete object, as with a whole
upload. Range readers that span a flush can see a torn view under either
write path; composing neither adds nor removes that window.

A successful finish that compacts (dead bytes over 10% of the member area)
replaces the temp file, so its final flush uploads whole.

## Verification mode

Composing is correct only while every writer of the temp file's leading
bytes clears the prefix. Verification mode turns a future violation of that
rule into a test failure instead of a corrupt `.eval`.

- **Switch.** `INSPECT_VERIFY_COMPOSE_PREFIX`, truthy by the usual
  `INSPECT_*` rule, read on every call. Off by default; `tests/conftest.py`
  turns it on for every test run.
- **Check.** When a prefix is recorded in verify mode, a `blake2b` digest of
  the temp file's `[0, prefix.length)` is recorded with it (in a worker
  thread, under `_lock`). Before each compose the range is digested again;
  a mismatch raises `ComposePrefixInvariantError`, a `RuntimeError` that
  `_write_remote()` does not catch, so the flush fails rather than falling
  back to a whole upload that would hide the bug.
- **Sticky.** The first violation is stored. Every later `flush()` raises a
  new `ComposePrefixInvariantError` (chained from the stored one) before
  touching the temp file or the destination, and so does `close()` after
  releasing the temp file. The stale-flush timer catches exceptions, logs
  "Stale eval log flush failed" and re-arms, so the eval fails at its next
  eval-owned flush (a buffer-full flush or the final flush) with the
  violation in its error, and the destination keeps its last complete
  object. An on-demand `flush_samples()` request (`inspect ctl task
  log-flush`) fails on its own without ending the eval; the violation stays
  for the next eval-owned flush.
- **Why a local digest suffices.** When a prefix is recorded, the local
  bytes and the object's leading bytes are the same by construction (the
  write just sent them, or the seed just received them from that object
  version), and the remote side is pinned by ETag from then on. Only the
  local side can drift silently.
- **Remote comparison.** `slow`-marked tests in
  [`tests/log/test_eval_log.py`](../tests/log/test_eval_log.py) compose
  120 and 200 MiB logs on the moto server, read the object's prefix range
  with their own S3 client, check its ETag against the one the flush
  returned, compare its digest with the local one, and compare the whole
  object to the temp file. They run in the scheduled slow-test run, not in
  the PR suite.

Production records no digest and does no check.

## Queued flushes re-check the threshold

`TaskLogger._finalize_sample()` decides that the flush threshold is reached
before it waits on the flush lock. During a slow flush every completion
sees the in-flight batch still pending and queues its own call; without a
re-check, each queued call would flush the few samples that arrived since
the previous one with a whole write.

The buffer-full call passes `require_threshold=True` to
`_flush_pending_samples()`, which re-reads the pending list and
`flush_buffer` under the lock. Fewer than `flush_buffer` pending: it writes
nothing and arms the stale-flush timer for the remainder (arming is a no-op
when a timer is already running or the list has reached the threshold
again, in which case that batch's own call flushes it). The stale-flush
timer and `flush_samples()` do not pass it and still flush whatever is
pending. So N completions during a flush cause one follow-up flush when
N ≥ `flush_buffer`, and none otherwise.

## Known limitations

- **A lost `CreateMultipartUpload` response leaves nothing to abort.** If
  the creation commits but its response is lost or cancelled, there is no
  upload ID, so the incomplete upload stays until the bucket's lifecycle
  rule removes it (see Compatibility).
- **A hard kill during a write** likewise leaves an incomplete upload for
  the lifecycle rule.

## Performance

Measured on real S3 from an office link (about 7–10 MB/s each way), verify
mode off, on the retry benchmark's synthetic logs (a react agent on
`mockllm/model` with pseudo-random prose; the method is under
[Performance](retry-seeded-attempt-log.md#performance) in the retry design).
Shape A is 500 samples × 80 turns (113–118 MB); shape B is 50 samples × 400
turns (190–202 MB). "Whole" uploads every flush whole, except that a seeded
retry's start flush composes; "composed" composes every flush.

| Run | Whole: wall, log writes | Composed: wall, log writes |
|---|---|---|
| A, first attempt (30 writes) | 324–355 s, 192–195 s | 164–197 s, 41–43 s |
| B, first attempt (4 writes) | 180–197 s, 54–56 s | 151–170 s, 22–23 s |
| A, retry (4 writes) | 79–83 s, 47–49 s | 35–37 s, 3.3–4.1 s |
| B, retry (2 writes) | 66 s, 26–27 s | 41–42 s, 1.8–2.1 s |

A composed flush took 0.6–3.8 s whatever the log size; whole uploads grew
with the log (14 s at 94 MB in a microbenchmark, 25.5 s at 190 MB). Shape
B's first attempt gains less because its first large flush (181 MB) has no
large object to compose from and uploads whole. On a retry the seed's
download of the prior log (15–17 s on A, 26–27 s on B) is unchanged, and
becomes 44% (A) and 63–65% (B) of the composed retry's wall time. Every run
ended `success` with all samples present and left no multipart upload in
progress, and the microbenchmark's objects equalled their temp files byte
for byte.

## Decisions

- 2026-09-23: seeding a retry without downloading the prior log is built
  only if, with every flush composed, the seed download is at least 20% of
  retry wall time on benchmark shape A or B from the office link; in-region
  numbers are informational (decision: Ransom, 2026-09-23).
- 2026-09-23: trio keeps whole uploads; no boto3 `upload_part_copy`
  variant (decision: Ransom, 2026-09-23).
- 2026-09-29: verification mode ships with composing, on in the test suite
  and off in production, and the suite covers the mismatch case.
  Production does not hash the prefix (decision: Ransom, 2026-09-29).
- 2026-09-29: slower verification passes, such as the remote comparison,
  are `slow`-marked and run in the scheduled slow-test run, not the PR
  suite (decision: Ransom, 2026-09-29).
- 2026-10-08: the local digest check stays on in every run of the PR
  suite; the 2026-09-29 decision covers only the remote pass (decision:
  Ransom, 2026-10-08).
- 2026-10-08: a prefix violation is sticky in the recorder. The stale-flush
  timer keeps catching and re-arming; the recorder re-raises on every later
  flush and close (decision: Ransom, 2026-10-08).
- 2026-10-08: the remote comparison reads the object range without
  `IfMatch` and checks the response's ETag instead (decision: Ransom,
  2026-10-08).
- 2026-10-26: seeding without the download is not built. The measured
  share clears the 20% threshold (44% on A, 63–65% on B, office link), but
  the local copy is still read by the reuse sweep (full-size scores and
  metadata, invalidation and `error_retries` exist only in sample bodies),
  by whole uploads after a failed or cancelled flush, a changed source or
  on trio, and by restricted-seed rewrites and compaction. A second seeding
  path is not worth it for a cost that matters only off-region; the single
  download-and-seed path stays (decision: Ransom, 2026-10-26).

## Alternatives considered

- **Whole-object `CopyObject` of the prior log at attempt start.** The
  first flush would overwrite it, and the copy would carry the prior's
  `header.json`. Composing copies only the member area, at the flush.
- **Skip the seeded `log_start` flush.** Saves an upload but leaves the
  attempt invisible until a later flush, loses fail-fast on an unwritable
  destination, and a hard kill before the next flush re-runs the attempt's
  completions.
- **Track the prefix in `AsyncFilesystem`.** The filesystem does not know
  when the temp file is replaced; the recorder does, and the invariant
  lives next to the events that break it.
- **Hash the prefix in production.** Hundreds of MB hashed per flush on
  every S3 eval, against a bug the suite catches, with no better remedy
  than the failure the test reports.
- **Compose under trio** through boto3 in a worker thread. A second
  primitive for the backend whose S3 uploads already differ.
- **Disable composing after every failure, or never.** Never means a store
  without `UploadPartCopy` pays a failing round trip per flush; always
  means one changed source turns composing off for the whole log.
- **Rely on `CopySourceIfMatch` without `HeadObject`.** Correct on real S3
  but untestable on moto; one extra request per flush is small next to the
  upload it replaces.
- **Copy the prefix as equal parts of up to 5 GiB.** One `UploadPartCopy`
  runs at about 50 MB/s, so a large prefix copied as one part takes longer
  than parallel 16 MiB parts.
- **Hold the pending-list lock across a flush, or decide the threshold in
  the recorder.** The first serializes every completion behind an upload;
  the second puts `TaskLogger` policy in the recorder.
- **Seed without downloading the prior log** (a sparse temp file whose
  member area is a hole, remote conditional body reads, materializing the
  hole before any whole upload). Not built; see the 2026-10-26 decision.

## Compatibility

- **Stored format.** None: a composed object is byte-identical to a whole
  upload, so every reader sees the same bytes.
- **ETags.** Every `.eval` over 8 MiB already had a multipart ETag
  (`"<md5>-<parts>"`); composing changes the part count, not the shape.
  Consumers compare ETags opaquely (conditional header writes, `IfMatch`
  downloads, `EvalLog.etag`); none computes an MD5.
- **Public API, CLI, config.** None. `AsyncFilesystem` is internal.
- **Other stores.** GCS and Azure are unchanged. An S3-compatible store
  without `UploadPartCopy` warns once and uploads whole logs from then on.
- **IAM.** `UploadPartCopy` needs `s3:GetObject` on the source and
  `s3:PutObject` on the destination, which the recorder already uses; a
  policy that denies the copy surfaces as the one-time warning.
- **Incomplete multipart uploads.** An upload left incomplete (see Known
  limitations) is billed as storage, and composing makes every flush
  multipart. The [Amazon S3](../docs/eval-logs.qmd#sec-amazon-s3) section of
  the log docs recommends a lifecycle rule that aborts them.

## Security

- **Locations** (log dir, prior log). Parsed by `s3_bucket_and_key` and
  passed to `CopySource` as structured bucket and key fields, never built
  into a URL string.
- **Object bytes.** Copied server-side and never parsed by the primitive.
  A seed validates its copy as a zip before adopting it, and the prefix
  length comes from that copy's own central directory; the `HeadObject`
  size check refuses a prefix longer than the source.
- **ETags** from S3 responses are opaque strings, quoted for the
  precondition header.
- **Model output, tool arguments, sandbox output.** None reaches this code.
- **Concurrent writers.** The ETag precondition means a compose never
  builds on an object it did not write; the fallback overwrites, as a
  whole upload does.

## Not this design

- **Compose the S3 header-only rewrite.** `write_eval_log(header_only=True)`
  on S3 downloads the object and rewrites it without dead bytes. It could
  copy the member area and upload a new `header.json` and central
  directory, keeping the old header as dead bytes as the local in-place
  edit does.
- **Native compose for GCS (`compose`) and Azure (`Put Block From URL`).**
  Needs async clients those backends do not have here.
- **Skip a flush whose temp file is unchanged.** See "A flush".
- **`ZipLogFile.discard()`'s synchronous `fs.rm`** on remote log dirs
  blocks the event loop (a TODO in the code).
- **Concurrent seed** (live samples start while the seed downloads): a
  follow-up in [`retry-seeded-attempt-log.md`](retry-seeded-attempt-log.md#not-this-design).
