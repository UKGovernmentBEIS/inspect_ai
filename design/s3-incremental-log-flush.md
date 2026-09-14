# Efficient S3 log flushes: server-side composition instead of whole-file re-uploads

Status: proposed, 2026-09-14. Author: agent (Claude), reviewed by Codex; see
the PR. One design for four fork issues that share a mechanism:

- [meridianlabs-ai/inspect_ai#479](https://github.com/meridianlabs-ai/inspect_ai/issues/479)
  — a seeded retry attempt re-uploads the prior log at `log_start`; compose
  it from the prior object instead. **The anchor.**
- [meridianlabs-ai/inspect_ai#480](https://github.com/meridianlabs-ai/inspect_ai/issues/480)
  — samples completing during a slow flush queue redundant whole-log
  flushes. Independent bug fix.
- [meridianlabs-ai/inspect_ai#481](https://github.com/meridianlabs-ai/inspect_ai/issues/481)
  — every S3 flush re-uploads the whole `.eval`; compose the delta onto the
  log's own key. Generalises #479.
- [meridianlabs-ai/inspect_ai#482](https://github.com/meridianlabs-ai/inspect_ai/issues/482)
  — a seeded retry downloads the whole prior log; evaluate seeding without
  the download once flushes are incremental. Gated on measurement.

Follows [`retry-seeded-attempt-log.md`](retry-seeded-attempt-log.md) (#420),
whose Performance section filed these four. Its option C ("filesystem-level
copy of the prior log") was rejected because *the first flush overwrites the
destination*; this design removes that objection by making the flush itself
a composition, so the objection's other half — the copied object would carry
the prior's `header.json` — is answered by copying only the prior's member
area, never its central directory.

## Why

Every flush of an `.eval` log to a remote filesystem re-uploads the entire
temp zip: `ZipLogFile.flush` seeks the temp file to 0 and hands it to
`AsyncFilesystem.write_file_streaming`
(`src/inspect_ai/log/_recorders/eval.py:1305-1309`). The log grows for the
whole run and is flushed every `log_buffer` completions, so the bytes sent
over a run are on the order of (flushes × final size) / 2, and every flush
stalls the sample that triggered it for the full upload. Locally a flush is a
sub-second file copy; this is a remote-only cost.

Measurements in the issues (2026-09-10, office link at ≈11 MB/s each way,
`s3://inspect-flow-test/perf-420/`; not re-measured for this design):

| Prior log | one whole-log upload |
|---|---|
| 119 MB (500 samples × 80 turns) | ≈11 s |
| 195 MB (50 samples × 400 turns) | ≈18 s |

In the #420 retry benchmark those uploads were 50–75% of a retry's wall
time, and a seeded retry pays one of them at `log_start` (#479) before any
work runs. A separate race (#480) added a fifth upload to a run that needed
four: completions landing during an 11 s upload each queue their own flush,
and the queued flushes drain a handful of samples each with a whole-log
upload apiece.

The reason a retry attempt re-uploads bytes S3 already holds is structural:
the recorder has one write primitive, "replace the object with the temp
file". The observation this design rests on is that **the temp zip is
append-only between rewrites**, so the object after flush *k+1* is the object
after flush *k* with its central directory replaced by new members and a new
central directory. S3 can build that object server-side from the existing
one plus a small uploaded tail (`UploadPartCopy` of a byte range into a
multipart upload), without the bytes leaving S3.

## Goals and non-goals

Goals:

- A seeded retry's `log_start` flush on S3 no longer scales with the prior
  log's size (#479).
- Every S3 flush of an `.eval` log uploads only what changed since the last
  successful flush (#481).
- A completion that lands during an in-flight flush never causes a flush of
  fewer than `log_buffer` samples (#480).
- The object written by a composed flush is **byte-identical** to the one the
  full upload writes. Nothing downstream — readers, the viewer, `AsyncZipReader`,
  recovery, the ETag-conditional header write — needs to know which path
  produced it.
- Every failure falls back to today's full upload, and no failure leaves an
  incomplete multipart upload behind that the code could have aborted.
- Decide #482 (seed without the download) on measurement, with its design
  questions answered so the decision is only go/no-go.

Non-goals:

- Changing the log format, the one-log-per-attempt identity, the flush
  cadence (`log_buffer`, the stale-flush timer), or when a flush happens.
- Incremental writes for the `.json` recorder (deprecated format), for
  non-S3 remotes (GCS, Azure via fsspec: no `UploadPartCopy`), or under the
  trio backend (its S3 path is boto3 in a worker thread and stays a full
  upload; see Alternatives).
- Composing the S3 `write_eval_log(header_only=True)` rewrite (see Not this
  design).
- Any new user-facing option. Composition is an internal optimisation with
  an automatic fallback.

## Current behaviour

Verified by reading the code at the base commit (`18b1348be2`) and by two
spikes run against the primary clone's venv (moto 5.2.2, aiobotocore 2.25.1,
boto3 1.40.61, CPython 3.13.7); the spikes are not checked in.

### The temp zip is append-only and its member area is stable

`ZipLogFile` keeps an anonymous temp file open as an append-mode `ZipFile`
(`_open`, `eval.py:1696-1701`). CPython's append mode parses the existing
central directory, sets `start_dir` to its offset and seeks there, so every
new member overwrites the old central directory
(`zipfile/__init__.py:1402-1407`); each write advances `start_dir` to the
end of the new member (`:1984`), and `close()` seeks to `start_dir`, writes
the central directory and end record, and **truncates** the file in append
mode (`:1990-2007`, `:2103`). Consequences, all confirmed by a spike that
wrote, closed, reopened, pruned a member from the directory, wrote again and
closed:

- After `close()`, the file is exactly `[members 0..start_dir) [central
  directory] [end record]`, with no trailing garbage.
- Bytes `[0, start_dir_k)` of the file after flush *k* are unchanged by every
  later write until the temp file itself is replaced. Directory-only prunes
  (`_prune_prior_members` `eval.py:1522`, `prune_samples` `:1558`,
  `_restrict_members` `:1600`) change the central directory, not the member
  area.
- `object_{k+1} == object_k[:start_dir_k] + tempfile[start_dir_k:]`, byte for
  byte.
- A close with nothing written leaves the file unchanged (`_didModify`
  false), and `start_dir` on the closed `ZipFile` object still holds the
  member-area end.

The temp file **is** replaced by two operations: `seed_from_prior_log`
(`eval.py:1482-1491`, before any destination write) and a successful
`compact()` (`eval.py:1670-1673`, at a successful finish only, when dead bytes
exceed 10% of the member area, `_should_compact` `:1678`). A failed compaction
reopens the original file (`:1674-1676`).

### How a flush reaches S3

`EvalRecorder.flush` writes buffered samples then `ZipLogFile.flush(fsync=False)`
(`eval.py:293-301`). `ZipLogFile.flush` holds `_lock`, closes the zip, and
for a non-local filesystem streams the temp file from offset 0 through
`AsyncFilesystem.write_file_streaming` (`eval.py:1276-1312`), recording the
returned ETag as `_etag` on success (`:1323-1326`) — that ETag becomes
`EvalLog.etag` at `close()` (`:1375`, `:1400`) and feeds the viewer's
conditional header writes.

`write_file_streaming` on asyncio calls `_s3_upload_fileobj_async`
(`asyncfiles.py:726-730`): a single `PutObject` below the 8 MiB
`multipart_threshold`, otherwise a multipart upload with 8 MiB parts read in
a worker thread, uploaded with `max_request_concurrency` workers, completed
with `CompleteMultipartUpload`, and **aborted on any exception** under a
shielded 30 s timeout (`_s3_multipart_upload_async`, `asyncfiles.py:240-311`;
`_S3_ABORT_TIMEOUT`, `:1539`). Seekable sources are retried from their start
offset on `RequestTimeTooSkewed` by `_s3_put_with_retry` (`:1323-1342`).
Every `.eval` log over 8 MiB therefore **already has a multipart ETag**
(`"<md5>-<parts>"`), not an MD5 — confirmed by
`test_write_file_streaming_s3` (`tests/util/test_asyncfiles.py:640-666`,
which asserts `"-" in etag`). The S3 client is created with
`request_checksum_calculation="when_required"` so no per-part checksum is
attached (`:1141-1154`; real S3 rejects mismatched checksum declarations).

The trio path uploads via boto3's `TransferManager` in a worker thread
(`_s3_upload_fileobj_sync`, `:391-411`).

### How a seeded retry's first flush happens

`task_run` seeds the log before `log_start` (`_eval/task/run.py:941-961`):
`TaskLogger.seed_from_prior` → `EvalRecorder.log_seed` →
`ZipLogFile.seed_from_prior_log` (`eval.py:1407-1520`). The seed copies the
prior `.eval` into a fresh temp file with `_copy_prior_log` (`:841-882`,
`AsyncFilesystem.read_file_into` with a bounded retry), reads its summaries,
and — when the seed is restricted (`keep` excludes members) or the prior has
dead bytes — rewrites the copy with `compact_zip` (`:1463-1477`;
`zip_needs_rewrite`, `_util/zipfile.py:277-305`). Otherwise the copy is
adopted as-is: `_open()` parses the prior's central directory, so
`start_dir` is the prior's member-area end, and the prior's metadata members
are pruned from the directory only (`:1494-1495`). The seed then appends one
summaries journal member, re-journals config updates (`:1503-1519`), and
`start()` appends `_journal/start.json` (`:1037-1040`). `TaskLogger.log_start`
flushes immediately (`_eval/task/log.py:639-643`): the first destination
write, a whole-file upload of prior member area + small tail.

`read_file_into` on asyncio streams a single `GetObject` response
(`asyncfiles.py:613-623` via `read_file_bytes`, `:535-556`); the response
carries the object's ETag, which is not currently surfaced.

### The redundant-flush race (#480)

`TaskLogger._finalize_sample` (`_eval/task/log.py:754-778`) appends the
completed key to `flush_pending` under `_flush_pending_lock`, decides
`threshold_reached = len(flush_pending) >= flush_buffer` **there**, and only
then awaits `_flush_pending_samples`, which serialises on `_flush_lock`
(`:796-834`). The in-flight flush's keys stay in `flush_pending` until it
finishes (`del self.flush_pending[: len(pending)]`, `:825`), so during an
11 s upload every completion sees a list at or over the threshold and queues
its own call. When the lock frees, each queued call snapshots whatever
arrived since the previous one — often one or two keys — and flushes it with
a whole-log upload. The stale-flush timer path
(`_stale_flush_after_delay`, `:1111-1133`) and the on-demand `flush_samples`
(`:836-855`, the `inspect ctl` path) call the same function and must keep
flushing whatever is pending.

### What S3 and moto support (spike, 2026-09-14)

Against a `ThreadedMotoServer` (the `mock_s3` fixture's server,
`tests/conftest.py:951-972`) with aiobotocore:

| Behaviour | moto 5.2.2 | real S3 (documented) |
|---|---|---|
| `UploadPartCopy` with `CopySourceRange` into a multipart upload, then `UploadPart` tail, `CompleteMultipartUpload` | works; object byte-identical to prefix + tail | supported; parts other than the last must be ≥ 5 MiB, each ≤ 5 GiB, ≤ 10,000 parts |
| Source key == destination key | works; the old object stays readable until complete | supported; replacement is atomic at complete |
| `CopySourceIfMatch` mismatch | **ignored** (copy succeeds) | `412 PreconditionFailed` |
| Part under 5 MiB followed by another part | `EntityTooSmall` at complete | `EntityTooSmall` at complete |
| `AbortMultipartUpload` | no object, no listed upload | same |
| ETag of a completed multipart upload | `"<md5>-<n>"` | same |

moto ignoring `CopySourceIfMatch` is the same gap the conditional header
write already works around: `_s3_put_object` does a `HeadObject` and
compares ETags before a `PutObject` with `IfMatch`
(`eval.py:742-764`, comment at `:753-755`). The compose primitive does the
same.

## Design

One mechanism, three producers. The recorder remembers a **compose prefix**:
an S3 object, the ETag it must still have, and how many of its leading bytes
equal the temp file's leading bytes. A flush that has a valid prefix asks S3
to build the new object from that range plus the temp file's tail; a flush
without one, or whose compose fails, uploads the whole file as today. The
prefix is set by the seed (#479: the prior log's key), by every successful
S3 flush (#481: the log's own key), and cleared by anything that replaces the
temp file. #480 is a separate change to `TaskLogger` and shares no code.

```
temp file after flush k          [ members ............ M_k )[ CD_k ][EOCD]
temp file at flush k+1           [ members ............ M_k | new members )[ CD_k+1 ][EOCD]
                                  \______ unchanged ______/ \_____ tail = temp[M_k:] _____/
object after flush k+1  =  UploadPartCopy(object_k, bytes 0..M_k-1)  +  UploadPart(tail)
```

### The compose primitive (`src/inspect_ai/_util/asyncfiles.py`)

```python
class ComposeSource(NamedTuple):
    """An S3 object whose leading bytes become the start of a composed object."""
    filename: str  # s3:// URL
    etag: str      # unquoted ETag the object must still carry
    length: int    # copy bytes [0, length)


class ComposeSourceChangedError(Exception):
    """The compose source no longer matches ``ComposeSource`` (ETag or size)."""


# Compose only when the copied prefix is at least this long. Below it the
# whole object is a single PutObject anyway (== multipart_threshold), and it
# clears S3's 5 MiB minimum for every part but the last.
S3_COMPOSE_MIN_PREFIX = 8 * 1024 * 1024
_S3_MAX_PART_SIZE = 5 * 1024 * 1024 * 1024


class AsyncFilesystem:
    def can_compose(self, filename: str) -> bool:
        """True when ``compose_file`` is available for ``filename``:
        an s3:// URL under the asyncio backend."""

    async def compose_file(
        self, filename: str, prefix: ComposeSource, tail: BinaryIO
    ) -> str:
        """Replace ``filename`` with ``prefix``'s leading bytes followed by
        ``tail`` (read from its current position to EOF), server-side, and
        return the new object's ETag.

        Raises ``ComposeSourceChangedError`` when the source's ETag or size
        no longer matches ``prefix``; ``ValueError`` when ``can_compose`` is
        false or ``prefix.length < S3_COMPOSE_MIN_PREFIX`` (the caller checks
        both first); ``ClientError`` for any other S3 failure. Never leaves
        an initiated multipart upload behind on a failure it observes.
        """
```

`compose_file`:

1. Records `tail_start = tail.tell()` and runs the steps below through
   `_s3_put_with_retry` (stale-signature retry), seeking `tail` back to
   `tail_start` before each attempt — the `write_file_streaming` pattern
   (`asyncfiles.py:713-743`).
2. `HeadObject` on the source. If the ETag (quotes stripped) differs from
   `prefix.etag`, or `ContentLength < prefix.length`, raise
   `ComposeSourceChangedError`. A `404`/`NoSuchKey`/`NotFound` (the
   `_S3_MISSING_OBJECT_CODES` set, `:57`) raises the same error: a vanished
   source is "changed" for the caller's purposes. This pre-check exists
   because moto ignores `CopySourceIfMatch`; real S3 enforces the header as
   well, closing the HEAD-to-copy window.
3. `CreateMultipartUpload` on the destination. From here every exit that is
   not a successful complete aborts the upload under
   `anyio.move_on_after(_S3_ABORT_TIMEOUT, shield=True)` with exceptions
   suppressed, exactly as `_s3_multipart_upload_async` does (`:304-309`),
   then re-raises.
4. Copy parts. Split `[0, prefix.length)` into `n = ceil(length /
   _S3_MAX_PART_SIZE)` **equal** slices of `ceil(length / n)` bytes (equal
   rather than "5 GiB then a remainder" so the last slice can never fall
   under 5 MiB: with `length ≥ 8 MiB`, one slice is ≥ 8 MiB and two or more
   are each ≥ 2.5 GiB). Each is an `UploadPartCopy(PartNumber=i,
   CopySource={Bucket, Key}, CopySourceRange="bytes=start-end",
   CopySourceIfMatch='"<etag>"')`; the part ETag is
   `CopyPartResult["ETag"]`. Issued through `tg_collect` bounded by
   `config.max_request_concurrency`. A `412 PreconditionFailed` from any
   copy part is re-raised as `ComposeSourceChangedError` (after the abort).
5. Tail parts, numbered `n+1` onward: the read/upload pipeline of
   `_s3_multipart_upload_async` (`read_parts`/`upload_parts`, `:255-282`),
   which reads `multipart_chunksize` (8 MiB) chunks off the loop via
   `_read_exactly` and uploads them concurrently. Every tail part but the
   last is 8 MiB, so the 5 MiB minimum holds; the last may be tiny (a
   no-op flush's tail is just the central directory and end record). That
   pipeline is extracted from `_s3_multipart_upload_async` into a helper
   taking `(client, source, bucket, key, upload_id, parts, first_part_number,
   config)` so both callers share it; the existing upload's behaviour and
   tests (`tests/util/test_asyncfiles.py:1076-1130`) are unchanged.
6. `CompleteMultipartUpload` with the parts sorted by number; return the
   response ETag stripped of quotes (raise `RuntimeError` if absent, as
   `_s3_upload_fileobj_async` does, `:337-339`).

Part-count bound: prefix ≤ `n` parts (one per 5 GiB), tail ≤ `size / 8 MiB`
parts; the 10,000-part limit is reached only for a tail over ~80 GB, which
a single flush cannot produce.

`read_file_into` (`:582-632`) gains a return value `str | None`: the ETag of
the S3 object read on the asyncio path (from the `GetObject` response that
`read_file_bytes` wraps in `_StreamingBodyByteReceiveStream`, which gets an
`etag` attribute), `None` for every other backend and under trio. The bytes
in `dest` and the ETag come from one response, so they describe the same
object version.

### The recorder's compose prefix (`src/inspect_ai/log/_recorders/eval.py`)

`ZipLogFile` gains:

```python
self._compose_prefix: ComposeSource | None = None
self._compose_disabled: bool = False   # a non-precondition S3 failure: full uploads for the rest of this log
```

**Invariant:** when `_compose_prefix` is set, `tempfile[0:prefix.length] ==
object(prefix.filename)[0:prefix.length]` for the object version carrying
`prefix.etag`. It is maintained by these rules:

| Event | `_compose_prefix` |
|---|---|
| `init()` (fresh log, or `destination_exists` for `score --overwrite`) | `None` |
| `seed_from_prior_log` adopts the copy **without** a rewrite, prior is `s3://`, ETag known | `ComposeSource(prior_log, etag, self._zip.start_dir)` right after `_open()` — #479 |
| `seed_from_prior_log` rewrote the copy (`compact_zip`), or prior not S3, or ETag `None` (trio) | `None` |
| successful S3 flush (upload **or** compose) | `ComposeSource(self._file, returned_etag, member_end)` — #481 |
| any flush failure (compose or upload, exception or cancellation) | `None` |
| `compact()` replaced the temp file | `None` |
| `compact()` failed and reopened the original | unchanged |
| directory-only prunes (`_prune_prior_members`, `prune_samples`, `_restrict_members`) | unchanged (member area untouched) |
| local filesystem, non-S3 remote, trio | never set (`can_compose` false / ETag `None`) |

`member_end` is `self._zip.start_dir` read **after** `self._zip.close()` and
before the write (the closed object retains it; the upload then reads the
file whose member area ends there). Reading it after the `finally: _open()`
would also work but couples the record to the reopen.

`flush()`'s remote branch becomes:

```python
self._zip.close()
member_end = self._zip.start_dir
written, etag = True, None
with trace_action(logger, "Log Write", self._file):   # same action name: trace tooling counts flushes by it
    try:
        if self._fs.is_local():
            ...unchanged...
        else:
            async with AsyncFilesystem() as async_fs:
                etag = await self._write_remote(async_fs, member_end)
    except BaseException:
        self._compose_prefix = None
        raise
    finally:
        self._open()
if written:
    self._streaming_samples.clear()
    self._destination_written = True
    self._etag = etag
    self._compose_prefix = (
        ComposeSource(self._file, etag, member_end)
        if etag is not None and async_fs_can_compose   # computed inside _write_remote
        else None
    )
```

`_write_remote(async_fs, member_end) -> str | None`:

```python
prefix = self._compose_prefix
if (
    prefix is not None
    and not self._compose_disabled
    and prefix.length >= S3_COMPOSE_MIN_PREFIX
    and async_fs.can_compose(self._file)
):
    self._temp_file.seek(prefix.length)
    try:
        return await async_fs.compose_file(self._file, prefix, self._temp_file)
    except ComposeSourceChangedError as ex:
        logger.warning(f"Log {self._file}: compose source changed ({ex}); uploading the whole log")
    except ClientError as ex:
        logger.warning(f"Log {self._file}: server-side compose failed ({ex}); uploading whole logs from now on")
        self._compose_disabled = True
self._temp_file.seek(0)
return await async_fs.write_file_streaming(self._file, self._temp_file)
```

Why two fallback shapes: a changed source is a one-off (the viewer rewrote
the prior log's header between the seed and `log_start`; another process
replaced our object) and the full upload re-establishes a fresh prefix. Any
other `ClientError` that survived botocore's adaptive retries means the
store does not support the operation (an S3-compatible endpoint without
`UploadPartCopy`, a bucket policy denying `s3:GetObject` on the source, a
KMS key we can decrypt but not re-encrypt) and would fail again on every
flush; the log keeps working on full uploads and the warning fires once.
Cancellation (`BaseException`) is not caught here: the primitive has already
aborted its multipart upload, the prefix is cleared by `flush()`'s handler,
and the cancel propagates as today.

The trace message for a composed write carries the mode and sizes
(`"<file> (compose: copy N bytes + upload M bytes)"`) so the retry
benchmark's trace-split method (`retry-seeded-attempt-log.md`, Performance)
can distinguish composed from full flushes without changing the action name.

**Why a no-op flush still composes.** A flush with nothing new (the temp
file unchanged since the last flush) composes a tail of a few hundred bytes:
five small requests instead of zero. Skipping it would need a "nothing
changed" test that is correct under directory-only prunes; not worth it for
a case the stale-flush timer already avoids creating.

**Compaction.** `compact()` sets `self._compose_prefix = None` in the branch
that adopts `compacted` (`eval.py:1670-1673`). Since compaction runs only at a
*successful* `log_finish` and only when dead bytes exceed 10% of the member
area, a successful eval whose log carries little dead weight (every fresh
eval; most retries) keeps composing through its final flush; one that does
compact pays one full upload — the final one, whose bytes are all new anyway.

### #479: the seeded start flush

`_copy_prior_log` returns the ETag `read_file_into` returned (from the final
successful attempt; `reset_before_retry` truncates `dest`, so bytes and ETag
always come from the same GET). In `seed_from_prior_log`, after the swap and
`_open()` (`eval.py:1490-1492`):

```python
self._compose_prefix = (
    ComposeSource(prior_log, prior_etag, self._zip.start_dir)
    if prior_etag is not None and not rewritten and is_s3_filename(prior_log)
    else None
)
```

where `rewritten` is true when the `zip_needs_rewrite` branch replaced the
copy. On the byte-copy path the adopted file *is* the prior object, so its
`[0, start_dir)` equals the prior's member area — including the prior's
pruned metadata members, which stay as dead bytes in both the temp file and
the composed object, exactly as the full upload carries them. On the rewrite
path the offsets changed and there is no S3 object with those bytes; full
upload as today.

`log_start`'s flush then composes: copy `prior[0:start_dir)` with
`CopySourceIfMatch` = the prior's ETag, upload `tempfile[start_dir:]` — the
summaries journal, re-journaled config updates, `start.json`, the new
central directory. Result: the same bytes as today's upload, in time
proportional to the tail. The `keep=None` seed of a dynamic-feed task
(`run.py:944-951`) takes the byte-copy path without a rewrite check and sets
the prefix the same way.

Cases that keep today's full upload, all by construction of the rules above:
restricted seed (rewrite), prior smaller than 8 MiB, prior on a local or
non-S3 filesystem, prior in a different format (the `Recorder.log_seed`
re-log path never reaches `seed_from_prior_log`), trio backend, a prior
whose ETag changed between the copy and the flush (`ComposeSourceChangedError`).
`retry_cleanup` deletes older logs at the start of the next eval-set pass and
at the end of the run (`_eval/evalset.py:1096`, `:1182-1184`), never during
an attempt, so the prior key normally exists at `log_start`; if it does not,
the HEAD's 404 is a "changed source" and the flush falls back.

Landing #479 alone (implementation steps 2–3) introduces the primitive, the
prefix field and the flush's compose path, with the **seed as the only
producer** of a prefix: `flush()`'s success path leaves `_compose_prefix =
None` until step 4 flips it to record the own-key prefix. So #479's first
flush composes from the prior and every later flush is a full upload, as
today.

### #481: every S3 flush composes onto the log's own key

Step 4 is the one-line change already shown in `flush()`'s success path:
record `ComposeSource(self._file, etag, member_end)` after every successful
S3 write. From then on every flush copies `object[0:member_end_prev)` from
the log's own key with `CopySourceIfMatch` = the ETag we were handed at the
previous flush, and uploads `tempfile[member_end_prev:]` — the members
written since plus the central directory. S3 keeps the previous object
readable until `CompleteMultipartUpload` replaces it atomically (spike:
"old object intact before complete"), so a concurrent reader (`inspect view`,
`AsyncZipReader` range reads guarded by `IfMatch` in
`_s3_download_file_async`, `asyncfiles.py:358-363`) sees either the previous
complete object or the new one, as today.

If another writer replaced our object (the ETag no longer matches), the
`HeadObject` pre-check raises `ComposeSourceChangedError` and this flush
uploads the whole temp file, overwriting — which is what today's flush does
unconditionally. Nothing is lost relative to today; the composed path is
strictly more careful.

The `_write_log_s3(header_only=True)` rewrite (`eval.py:534-540`) is
unaffected: it operates on finished logs through `write_eval_log`, not the
recorder, and still downloads and rewrites (see Not this design).

### #480: re-check the threshold under the flush lock

`_flush_pending_samples` (`_eval/task/log.py:796-834`) gains a keyword
`require_threshold: bool = False`. `_finalize_sample` passes `True`; the
stale-flush timer and `flush_samples` pass nothing.

```python
async with self._flush_lock:
    if self._finished or self._discarded:
        return 0
    async with self._flush_pending_lock:
        pending = list(self.flush_pending)
        if not pending:
            return 0
        if require_threshold and len(pending) < self.flush_buffer:
            # a preceding flush drained the batch this caller was queued
            # for; what remains is below the threshold — leave it to the
            # stale-flush timer (armed below, outside the lock)
            below_threshold = True
    if below_threshold:
        reschedule_stale_flush = True
    else:
        ...existing flush, remove, del prefix, reschedule computation...
if reschedule_stale_flush:
    await self._arm_stale_flush_timer(generation=stale_flush_generation)
return flushed
```

`self.flush_buffer` is read under the lock at decision time, so a mid-run
`buffer_config` retune (`:860-899`) applies to queued callers. `_arm_stale_flush_timer`
already refuses to arm when the list has reached the threshold or a timer
is running (`:986-989`), so if a threshold-reaching batch landed while this
caller waited, the timer is not armed and that batch's own `_finalize_sample`
call, queued behind the lock, flushes it. The decline path returns 0, which
`_finalize_sample` ignores.

Sequence for N completions landing during an in-flight flush: the first
queued caller sees all N pending. `N ≥ flush_buffer`: one flush of N; the
remaining callers find the list empty and return. `N < flush_buffer`: the
first caller declines and arms the timer; the rest find `len(pending) <
flush_buffer` too and return without re-arming (already armed). Exactly one
follow-up flush or none — the issue's acceptance criteria.

`_finalize_sample` stops the stale timer before calling
`_flush_pending_samples` (`:773`); the decline path re-arms it, so pending
samples are never left without a timer. The window between stop and re-arm
is spent waiting on `_flush_lock` behind a flush that is writing, which is
harmless.

### #482: seeding without the download (gated)

With #481 the destination is composed from the previous object at every
flush and the local temp file contributes only bytes at or beyond the
recorded prefix. The prior's member area therefore never needs to be *local*
for the destination's sake; the seed downloads it today for two other
reasons (`retry-seeded-attempt-log.md`, "The reuse sweep becomes bookkeeping"):
the reuse sweep reads each planned key's body from the local zip through the
`buffered_sample` local tier (`eval.py:1236-1251`; `run.py:1374-1385`), and
restricted seeds rewrite the archive locally.

#482 is decided on measurement (its own acceptance criterion): re-run the
#420 retry benchmark shapes A and B after #481 lands, on an office link and
on an in-region host. **Go** only if the seed download is at least 20% of
the retry's wall time on a shape and link users actually run (the office-link
case; in-region the download is a second or two and the issue says so). The
mechanism and the decisions it needs, so that a go is only a go:

**Sparse-prefix temp zip.** On a go, `seed_from_prior_log` for an S3 prior
whose seed needs no rewrite, under asyncio, replaces the whole-file copy
with: `HeadObject` (size, ETag); read the prior's central directory and
summaries by range request through `AsyncZipReader` (`_util/async_zip.py:310`,
as `log_init` already does for an existing destination, `eval.py:157-166`);
create the temp file as a **sparse** file of the prior's member-area length
(`seek(start_dir); truncate()` — a hole, no disk use on APFS/ext4/XFS) with
the prior's central directory and end record appended verbatim. Append-mode
`ZipFile` parses that directory and appends after it exactly as it does over
a full copy; `zip_dead_bytes` and the prunes work on the directory alone.
The compose prefix is set as in #479. Nothing changes in `flush()`.

What must change because the hole holds zeros, not the prior's bytes:

1. **Body reads go remote.** `buffered_sample`'s local tier serves seeded
   names from `self._zip.read(name)`; for a sparse seed the seeded members'
   extents (header offset, compressed size, method — from the prior's
   central directory, captured at seed time) are read by range from **the
   log's own key** through a shared `AsyncZipReader`-style reader (the
   offsets are identical in the composed object and remain valid across
   flushes because the member area is never rewritten; the prior key would
   also work but ties the attempt to a file `retry_cleanup` may later
   remove). Reads are bounded as the unseeded sweep's are
   (`PRIOR_LOOKUP_CONCURRENCY`, `run.py:323`, 25) and run outside `_lock`
   (a remote read must not hold the recorder's lock). Scanner resume and a
   dynamic feed's `sample_complete` read through the same tier and become
   slower per read; acceptable since they read one sample at a time.
2. **No compaction, no full-upload fallback.** `compact()` returns early
   when the temp file is sparse (it would recompress zeros), and a compose
   failure cannot fall back to uploading the temp file (it would publish
   zeros). Instead the fallback **rehydrates**: download `[0, prefix.length)`
   from the compose source into the hole (the download #482 avoided, paid
   only on failure), clear the sparse flag, then full-upload as today. A
   rehydrate failure fails the flush as any upload failure does.
3. **Mid-sweep read failure** (the issue's first design question). Today a
   prior-log read failure happens in the seed, before `log_start`, and
   fails the attempt with no destination. With remote body reads it can
   happen after the destination exists. Recommendation: **fail the attempt**
   (raise from `read_prior_sample` after a bounded retry, the
   `_copy_prior_log` idiom), because the sweep cannot classify a key it
   cannot read and guessing "absent → re-run" would re-run completed work.
   The attempt's log is still complete: the destination already holds every
   prior record via the composed `log_start` flush, and `log_finish` writes
   an error log on top of it. The next attempt seeds from that log. This
   matches the invalid-state rule (a defined failure, not a coerced result)
   and is covered by a test that fails one range read mid-sweep and asserts
   the attempt's error status plus a complete sample set in its log.
4. **Restricted seeds** keep today's path (download and rewrite). Expressing
   an exclusion as multiple `UploadPartCopy` ranges is possible (one per
   kept run of members, each ≥ 5 MiB but the last) but adds a second
   compose shape for the rarer case; not worth it before the measurement
   says the common case matters.
5. **Trio** keeps the download (no compose).

If the measurement says no-go, the sparse mechanism is not built and this
section stands as the record of why.

### Dependencies and landing order

```
#480 (independent)  ──────────────────────────────────────┐
#479 primitive  →  #479 seeded start flush  →  #481 own-key flushes  →  #482 measure → go/no-go
```

- **#480 first.** Smallest change, a bug on `main` unrelated to compose, and
  it removes a confound from the #481 benchmark (the fifth upload).
- **#479 before #481**: #481's flush path *is* #479's with a second producer
  of the prefix; landing #479 first exercises the primitive on one flush per
  retry before it runs on every flush of every S3 eval.
- **#482 last**, only after #481's benchmark, because its entire premise
  (the local prefix is never uploaded) is #481.

## Alternatives considered

- **Whole-object `CopyObject` of the prior at attempt start** (option C in
  `retry-seeded-attempt-log.md`). Rejected there because the first flush
  overwrote it and the copy carried the prior's `header.json`. Composition
  fixes the first objection; the second is why the copy is a *range*
  (member area only), not the object.
- **Skip the `log_start` flush for seeded attempts.** Saves one upload but
  leaves the attempt invisible to `inspect view` until a later flush, loses
  fail-fast on an unwritable destination, and a hard kill before the first
  later flush re-runs the attempt's live completions. Rejected in the #420
  design's Performance section; #479 keeps the flush and makes it cheap.
- **Track the prefix in `AsyncFilesystem` instead of the recorder.** The
  filesystem does not know when the temp file is replaced; the recorder
  does. Keeping the invariant next to the events that break it (`compact`,
  `seed_from_prior_log`) is the whole safety argument.
- **Compare bytes rather than trust the invariant** (hash the prefix at each
  flush and refuse to compose on mismatch). Hashing hundreds of MB per flush
  costs what the upload cost in CPU. The invariant is a structural property
  of append-mode `ZipFile` (verified) plus two explicit invalidation points;
  a test that mutates the prefix and asserts the composed object still
  equals the file is the check.
- **Compose under trio through boto3 in a worker thread.** Possible
  (`upload_part_copy` exists on the sync client) but doubles the primitive
  for the backend the codebase treats as second-class for S3 (its uploads
  already differ, `_s3_upload_fileobj_sync`). Trio users keep full uploads;
  revisit if anyone asks.
- **Always disable compose after any failure, or never disable.** Never
  disabling means an S3-compatible store without `UploadPartCopy` pays a
  failing round trip on every flush; always disabling means one transient
  412 turns off the optimisation for a whole eval. Splitting by error class
  (changed source → retry next time; anything else → off) costs one
  `except` clause.
- **A `HeadObject`-free compose** relying on `CopySourceIfMatch` alone.
  Correct on real S3, untestable on moto (which ignores the header). The
  header write already chose HEAD-plus-header for the same reason
  (`eval.py:753-755`); one extra ~20 ms request per flush is nothing next to
  the upload it replaces.
- **#480: hold `_flush_pending_lock` across the flush**, or move the
  threshold decision into `recorder.flush`. The first serialises every
  completion behind an upload (the lock protects a short, await-free
  section by design, `:376-377`); the second puts `TaskLogger` policy in the
  recorder. Re-checking under `_flush_lock` is a three-line change at the
  point that already snapshots `pending`.
- **#482 without a sparse file**: hand-rolled offset bookkeeping so the
  local zip's directory refers to bytes it does not hold. That is what the
  sparse file gives for free from `ZipFile`; the hand-rolled version would
  reimplement the central-directory writer.

## Compatibility and migration

- **Stored format.** None: the composed object is byte-identical to the
  full upload's (tested). `.eval` readers, `AsyncZipReader`, recovery, the
  viewer and `inspect log` see the same bytes.
- **ETags.** Already multipart (`"<md5>-<n>"`) for every `.eval` over 8 MiB
  (verified above); compose changes the part count, never the shape. Every
  consumer compares ETags opaquely: `_s3_put_object`'s HEAD compare and
  `IfMatch` (`eval.py:742-764`), `_s3_download_file_async`'s `IfMatch`
  (`asyncfiles.py:358-363`), `AsyncZipReader.etag` (`async_zip.py:351`),
  `EvalLog.etag` → the viewer's conditional header write
  (`_view/common.py:256-289`), `fs.info().etag` (`_view/common.py:298-309`).
  `parse_log_token` (`_view/common.py:176-185`) parses an `mtime-size` token,
  not an ETag. No consumer computes an MD5.
- **Public API / CLI / config.** None. `AsyncFilesystem` is internal
  (`_util`); `read_file_into` gains a return value, and `_copy_prior_log`
  (`eval.py:882`) is its only caller.
- **Viewer TypeScript types.** None: no serialized model changes.
- **Old logs, old callers.** A log written by an older Inspect and retried
  by a newer one composes from it like any other (the prior's ETag comes
  from the GET). A newer log read by an older Inspect is the same bytes.
- **Other stores.** GCS/Azure via fsspec: not S3 URLs, `can_compose` false,
  unchanged. S3-compatible endpoints (MinIO, R2, Ceph) without
  `UploadPartCopy` or with different minimums: first compose fails with a
  `ClientError`, warning once, full uploads thereafter.
- **IAM.** `UploadPartCopy` needs `s3:GetObject` on the source and
  `s3:PutObject` on the destination — the recorder already reads its own
  logs and the prior log and writes the destination, so no new permission
  class; a policy that denies the copy surfaces as the one-time warning.
- **Incomplete multipart uploads.** A hard kill (SIGKILL, power loss)
  between `CreateMultipartUpload` and complete leaves an incomplete upload
  holding storage until aborted — already true today for every upload over
  8 MiB. Composition makes every flush multipart, so the docs should
  recommend a bucket lifecycle rule (`AbortIncompleteMultipartUpload`,
  e.g. 1 day) in the S3 log-dir section of `docs/eval-logs.qmd` (step 4).

## Security

Untrusted or externally controlled input reaching the new code:

- **The prior log location and the log dir** (user arguments, eval-set
  listing). Parsed by the existing `s3_bucket_and_key`; the compose passes
  bucket and key into `CopySource` as structured fields, never string-built
  into a URL, so a key containing `/`, `?` or `%` cannot change the request.
- **Object bytes.** Copied server-side and never parsed by the primitive.
  The seed already validates the copy as a zip before adopting it
  (`_read_prior_summaries`, `eval.py:885-895`) and the prefix length comes
  from *that validated file's* end record, so a hostile prior cannot point
  the copy past its own size (the HEAD size check would refuse it anyway).
- **ETags** from S3 responses, sent back as `CopySourceIfMatch`. Treated as
  opaque strings, quoted for the header exactly as `_s3_put_object` does.
- **Model output, tool arguments, sandbox output.** None reaches this code:
  it moves already-serialized log bytes.
- **Concurrent writers.** The ETag precondition means a compose never
  builds on an object it did not write; the fallback overwrites, as today.

## Testing

Unit, `tests/util/test_asyncfiles.py` (next to the `_MultipartClient` fake at
`:1040` and the moto tests at `:640`):

- `compose_file` on moto: 12 MiB source, prefix 10 MiB + 1 MiB tail →
  object equals `source[:10 MiB] + tail`, returned ETag equals `info().etag`;
  source == destination (own-key compose) with the previous ETag → the
  previous object is readable until complete and the result is
  `prev[:n] + tail`; prefix over 5 GiB is not testable on moto in CI —
  the equal-slice arithmetic is unit-tested as a pure function.
- Fake-client tests (the `_MultipartClient` pattern): HEAD ETag mismatch →
  `ComposeSourceChangedError` and no `CreateMultipartUpload`; HEAD 404 →
  same; `412 PreconditionFailed` from `upload_part_copy` →
  `ComposeSourceChangedError` **after** `abort_multipart_upload`; a failing
  tail part → abort then `ClientError`; cancellation during the tail →
  abort; `RequestTimeTooSkewed` on the first attempt → tail re-read from
  `tail_start` and the second attempt succeeds; `ValueError` for a
  non-S3 URL and for a prefix under `S3_COMPOSE_MIN_PREFIX`.
- `read_file_into` returns the S3 ETag on asyncio and `None` under trio
  (`--runtrio`) and for a local file.

Unit, `tests/log/test_eval_log.py` (next to the seed tests at `:1715-2300`):

- **#481 byte-identity**: a `ZipLogFile` on moto, flushed after each of
  several batches of >8 MiB of samples with a directory-only prune in
  between; after every flush, download the object and assert it equals the
  temp file's bytes; assert via a spy on the client that flushes after the
  first used `upload_part_copy` and uploaded only the tail. Same sequence
  under trio asserts no `upload_part_copy` and identical bytes.
- **Compaction**: a log with >10% dead bytes finishing `success` → the final
  flush is a full upload and the object round-trips through
  `read_eval_log`; a finish without compaction composes.
- **Changed source**: replace the object between two flushes → warning,
  full upload, next flush composes again. **Unsupported store**: fake client
  raising `NotImplemented` on `upload_part_copy` → warning once, every
  later flush uploads whole, `_compose_disabled` set.
- **Failure clears the prefix**: cancel a compose mid-tail → the next
  flush uploads whole; the moto server lists no in-progress uploads.
- **#479 seeded start flush**: seed from an S3 prior >8 MiB (byte-copy
  path), `start()`, `flush()` → object equals the temp file and the client
  saw one `upload_part_copy` with `CopySource` = the prior key; restricted
  seed (rewrite), prior <8 MiB, local prior, `.json` prior → no copy, full
  upload; prior rewritten (header edit) between seed and flush → fallback,
  correct object.
- `tests/log/test_s3_conditional_writes.py`: a header-only conditional
  write on a composed object succeeds with the ETag the flush returned
  (`test_returned_etag_supports_chained_conditional_writes` shape, `:162`).

Unit, `tests/log/test_task_log.py` (next to
`test_task_logger_concurrent_flushes_do_not_double_remove_pending`, `:406`):

- **#480**: block the recorder's `flush` on an `anyio.Event`; complete
  `flush_buffer` samples to start a flush; while blocked complete N more;
  release. `N ≥ flush_buffer` → exactly two recorder flushes and an empty
  `flush_pending`; `N < flush_buffer` → exactly one flush, N pending, stale
  timer armed. `flush_samples()` and the stale timer still flush a
  below-threshold remainder (existing tests `:616`, `:636` unchanged).

Eval-level, `tests/test_eval_set.py`: the #420 seeded-retry repro against
`mock_s3` asserting the final log's sample set, so the composed path runs
end to end through `eval_set`.

CI: every test above uses the `mock_s3` fixture (a local moto server) or a
fake client — no network, no keys, runs in the normal `pytest` job. Trio
variants via `--runtrio` locally. Real S3 is exercised by the benchmark
below, run by hand; `CopySourceIfMatch` enforcement (moto ignores it) is
covered by the fake-client 412 test and by the HEAD pre-check test.

Benchmark (manual, recorded in this document's Performance section when
step 4 lands): the #420 retry benchmark shapes A and B on
`s3://inspect-flow-test/perf-420/` from the office link, trace-split into
flush time and the rest. Expected from the issues: shape A at default
`log_buffer` from ≈75 s to ≈25–30 s; flush time no longer scaling with log
size.

## Implementation plan

1. **#480 — threshold re-check.** `src/inspect_ai/_eval/task/log.py`
   (`_flush_pending_samples`, `_finalize_sample`); tests in
   `tests/log/test_task_log.py`; CHANGELOG: "Fewer redundant log writes when
   samples complete during a slow log flush." One PR.
2. **#479a — compose primitive.** `src/inspect_ai/_util/asyncfiles.py`:
   `ComposeSource`, `ComposeSourceChangedError`, `S3_COMPOSE_MIN_PREFIX`,
   `AsyncFilesystem.can_compose`/`compose_file`, `_s3_compose_async`, the
   part-pipeline helper extracted from `_s3_multipart_upload_async`,
   `read_file_into` returning the ETag; tests in
   `tests/util/test_asyncfiles.py`. No CHANGELOG (no behaviour change yet).
3. **#479b — seeded start flush.** `src/inspect_ai/log/_recorders/eval.py`:
   `_compose_prefix`/`_compose_disabled`, `_write_remote`, `flush()` changes,
   `_copy_prior_log` returning the ETag, `seed_from_prior_log` setting the
   prefix, `compact()` clearing it; tests in `tests/log/test_eval_log.py`;
   CHANGELOG: "Retrying an eval whose logs are on S3 no longer re-uploads the
   prior attempt's log before the retry starts." Steps 2 and 3 are one PR
   (#479) in two commits, or two PRs if the first is wanted in isolation.
4. **#481 — own-key flushes.** `eval.py`: record the prefix after every
   successful S3 flush (the success-path assignment in `flush()`); the
   byte-identity, compaction, changed-source, unsupported-store and
   failure tests; `docs/eval-logs.qmd`: lifecycle-rule recommendation in
   the S3 section; CHANGELOG: "Log flushes to S3 no longer re-upload the
   whole `.eval` file; only the samples written since the last flush are
   uploaded." Then re-run the benchmark and add a Performance section to
   this document with the numbers.
5. **#482 — measure, then decide.** Re-run the benchmark with the seed
   download split out (both links). No-go: close #482 citing the numbers.
   Go: revise this document's #482 section into a full mechanism (sparse
   seed in `seed_from_prior_log`; remote tier in `buffered_sample`;
   `compact()` guard; rehydrate-on-failure in `_write_remote`;
   `read_prior_sample` failure handling in `run.py`) and implement it as
   its own PR with the mid-sweep failure test.

## Open questions

1. **#482 go threshold.** The issue says "material share of retry time in a
   scenario users actually run". Recommendation: ≥ 20% of retry wall time on
   shape A or B from the office link after #481; in-region numbers are
   informational. Ransom to confirm or set the bar.
2. **Trio.** Keep full uploads under trio (recommended; see Alternatives),
   or build the boto3 variant now so both backends behave alike?

## Not this design

- **Compose the S3 header-only rewrite.** `_write_log_s3(header_only=True)`
  downloads the object and rewrites it without dead bytes
  (`_rewrite_eval_zip_with_new_header`, `eval.py:592-607`). It could instead
  copy the member area and upload a new `header.json` + central directory,
  accepting the old header as dead bytes (the local in-place edit already
  does, `_replace_eval_header_in_place`, `:568-589`). Same primitive, a
  different caller with its own dead-bytes trade-off; #481's issue lists it
  as an optional follow-up.
- **Native compose for GCS (`compose` API, 32 sources) and Azure (`Put
  Block From URL`).** Would need async clients those backends do not have
  here.
- **Skipping a flush whose temp file is unchanged.** See "Why a no-op flush
  still composes".
- **`ZipLogFile.discard`'s synchronous `fs.rm` on remote log dirs** (TODO at
  `eval.py:1354-1358`), noticed while reading the flush path.
- **Concurrent seed (A2)** and **retry cleanup of older `started` logs
  (#459)**: unchanged follow-ups from `retry-seeded-attempt-log.md`.
