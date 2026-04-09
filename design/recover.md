# Recover

## Research: Current State After a Hard Crash

### 1. Eval Log (.eval file)

The `.eval` file is a ZIP archive that accumulates data during an eval run. Its internal structure:

```
_journal/
  start.json            # EvalSpec + EvalPlan (written at log_start)
  summaries_1.json      # Sample summaries after 1st flush
  summaries_2.json      # Sample summaries after 2nd flush
  ...
summaries.json          # Consolidated summaries (written at log_finish only)
reductions.json         # Score reductions (written at log_finish only)
header.json             # Final EvalLog with status/results (written at log_finish only)
samples/
  sample_1_1.json       # Full EvalSample: id=1, epoch=1
  sample_2_1.json       # Full EvalSample: id=2, epoch=1
  ...
```

**Flushing strategy** (`eval.py:95-104`): The recorder buffers completed samples in memory and periodically flushes them to the ZIP. For normal runs, flushes happen every 1-10 samples depending on total count. High-throughput runs (100+ connections or 1000+ samples) flush ~10 times during the run.

**On each flush** (`eval.py:151-159`, `631-647`):
1. Buffered samples written into ZIP
2. Versioned `_journal/summaries_N.json` written
3. ZIP closed, entire temp file streamed to output location
4. ZIP reopened in append mode

**On normal completion** (`eval.py:162-218`):
1. Remaining buffered samples written
2. Consolidated `summaries.json` written
3. `reductions.json` written (if applicable)
4. `header.json` written with final status, stats, and results
5. Final flush to disk

**After a hard crash:**
- Status: `"started"` (the default — `header.json` is never written, so status is never updated)
- The `.eval` file on disk contains data up to the **last successful flush**
- Contains: `start.json` + samples/summaries from prior flushes
- Missing: `header.json`, `summaries.json`, `reductions.json`, and any samples buffered in memory since the last flush
- The ZIP itself should be valid since flushes write the complete accumulated state

### 2. Sample Buffer Database

The sample buffer database is a **SQLite database** used by the realtime log viewer UI. It is stored **outside** the log directory, in the platform data directory:

- **Location**: `~/.local/share/inspect_ai/samplebuffer/<log_dir_hash>/<filename>.<pid>.db`
- **Resolution**: `inspect_data_dir("samplebuffer")` via `platformdirs.user_data_path()` (`database.py:765-766`)
- **Created**: At `TaskLogger.init()` when `log_realtime` is not False (`task/log.py:263-267`)

**Schema** (`database.py:61-99`):

| Table | Contents |
|-------|----------|
| `samples` | `EvalSampleSummary` as JSON — id, epoch, input, target, scores, model_usage, etc. |
| `events` | Full event objects as JSON — includes all `ChatMessage` data, tool calls, model outputs |
| `attachments` | Binary content (images, etc.) referenced by hash |
| `task_database` | Version counter and metrics |

**Critical data flow — what the buffer DB contains at any given time:**

1. **Sample starts** → `start_sample()` inserts `EvalSampleSummary` into buffer DB
2. **Events logged** → `log_sample_event()` inserts full events into buffer DB (these contain complete message history)
3. **Sample completes** → `complete_sample()` updates the summary in buffer DB with final scores
4. **Flush to .eval** → `remove_samples()` **deletes** flushed samples from buffer DB

So the buffer DB contains exactly the samples that have **not yet been flushed** to the `.eval` file — both in-progress and completed-but-unflushed samples.

**After a hard crash:**
- The SQLite database **persists on disk** — it is not cleaned up
- It contains all samples that were not yet flushed to the `.eval` file
- This includes both completed samples (with scores) and in-progress samples (without scores)
- The `events` table has the full event stream for these samples (messages, tool calls, model outputs)
- The `samples` table has `EvalSampleSummary` data (input, target, scores if completed)

**Cleanup** (`database.py:732-749`):
- `cleanup_sample_buffer_databases()` is called at end of eval runs (`eval.py:791`)
- Only removes databases that are **>3 days old** AND whose PID no longer exists
- After a crash, the database will persist until the next eval run triggers cleanup (and even then, only if >3 days old)

### 3. Recovery Data Availability

After a crash, the complete set of sample data is split across two sources:

| Source | Contains | Data Type |
|--------|----------|-----------|
| `.eval` file | Samples from prior flushes | Full `EvalSample` (messages, output, scores, metadata) |
| Buffer DB | Samples since last flush | `EvalSampleSummary` + full event stream |

**What IS recoverable:**
- All **completed** samples: those flushed to `.eval` + those completed but unflushed (in buffer DB)
- `EvalSpec` and `EvalPlan` from `start.json`
- For unflushed completed samples: scores, input, target, messages (via events)

**What is NOT recoverable:**
- In-progress samples at crash time (started but `complete_sample()` never called — no scores)
- `EvalResults` / `EvalStats` (would need recomputation from recovered samples)
- Any `reductions` data

### 4. Key Distinction: EvalSample vs EvalSampleSummary

The `.eval` file stores full `EvalSample` objects which include `messages` (full chat history) and `output` (model output). The buffer DB stores `EvalSampleSummary` which does **not** include messages/output — but the `events` table separately stores the complete event stream which contains all the message data needed to reconstruct the conversation.

**`EvalSample`** (`_log.py:314`): id, epoch, input, choices, target, sandbox, files, setup, **messages**, **output**, scores, metadata

**`EvalSampleSummary`** (`_log.py:220`): id, epoch, input, choices, target, metadata (truncated), scores (truncated), model_usage, role_usage, started_at, completed_at, error, limit

## Design: `inspect recover`

### Overview

Recovery takes a crashed `.eval` log (status `"started"`, missing `header.json`) and produces a new recovered `.eval` file that combines:

1. **Flushed samples** already in the `.eval` file
2. **Unflushed samples** from the sample buffer database (both completed and in-progress)

The recovered log has status `"error"`. In-progress samples (those that were running when the crash happened) are marked as cancelled, following the same pattern as normal eval cancellation — their `error` field is set to an `EvalError` with a cancellation message, and they have no scores.

### Python API

```python
def recoverable_eval_logs(log_dir: str | None = None) -> list[RecoverableEvalLog]:
    """List eval logs that can be recovered (crashed with buffer DB available).
    
    Returns list with log info plus recovery stats (completed/in-progress sample counts).
    """

def recover_eval_log(
    log: str,
    output: str | None = None,
    cleanup: bool = True,
) -> EvalLog:
    """Recover a crashed eval log.

    Args:
        log: Path to the crashed .eval file.
        output: Output path (default: <name>-recovered.eval alongside original).
        cleanup: Remove the buffer DB after recovery.

    Returns:
        The recovered EvalLog.
    """
```

`RecoverableEvalLog` includes the `EvalLogInfo` plus stats about what's recoverable:
- Number of samples already flushed to `.eval`
- Number of completed (scored) samples in buffer DB
- Number of in-progress (unscored) samples in buffer DB

### CLI: `inspect log recover`

#### Interactive Mode (default, no arguments)

When invoked with no arguments, `inspect log recover` launches a Textual TUI that:

1. **Scans** for recoverable logs (status `"started"` with a matching buffer DB)
2. **Displays a table** showing each recoverable log with:
   - Task name / eval file path
   - Crash time (last modified time of the `.eval` file or buffer DB)
   - Flushed samples (already in `.eval`)
   - Recoverable samples from buffer DB (completed + in-progress)
   - Total samples expected (from `EvalSpec` if available)
3. **Checkbox selection** — user checks which logs to recover
4. **Recover button** — runs recovery on selected logs, showing progress
5. **Results** — displays paths to recovered files

If no recoverable logs are found, prints a message and exits (no TUI needed).

#### Direct Mode (with arguments)

```
inspect log recover <log_file> [--output <path>] [--no-cleanup]
```

Recovers a single log directly without the interactive UI. Useful for scripting.

#### List Mode

```
inspect log recover --list [--log-dir <path>] [--json]
```

Non-interactive listing of recoverable logs with stats. Prints to stdout.

### Output

Creates a new file alongside the original: `<name>-recovered.eval`. The original `.eval` file is not modified.

### Algorithm

1. **Validate** the input `.eval` file:
   - Must exist and be a valid ZIP
   - Must have `_journal/start.json`
   - Must NOT have `header.json` (i.e., status is effectively `"started"` — the eval never finished)
   - If `header.json` exists, the eval completed normally and recovery is not needed

2. **Read from `.eval` file:**
   - `start.json` → `EvalSpec` + `EvalPlan`
   - All `samples/sample_*.json` → already-flushed `EvalSample` objects
   - All `_journal/summaries_*.json` → existing sample summaries

3. **Find and read from buffer DB:**
   - Locate DB at `inspect_data_dir("samplebuffer") / <log_dir_hash> / <filename>.*.db`
   - Use existing `SampleBufferDatabase(location, create=False)` to open it
   - Read all remaining samples and their events
   - Distinguish completed vs in-progress samples (completed samples have `completed_at` set and scores populated)

4. **Construct recovered samples from buffer DB data:**
   - For **completed** unflushed samples: reconstruct `EvalSample` from `EvalSampleSummary` + events
   - For **in-progress** samples: construct `EvalSample` with:
     - `error` set to `EvalError(message="Cancelled", traceback="...", traceback_ansi="...")` matching the cancellation pattern from `run.py`
     - `scores` set to `None`
     - Messages/events captured up to the crash point

5. **Build the recovered `.eval` file:**
   - Write `start.json` (from original)
   - Write all samples (flushed + recovered from buffer DB)
   - Write consolidated `summaries.json`
   - Write `header.json` with:
     - `status = "error"`
     - `error` = `EvalError` indicating crash recovery
     - `results` = computed from all completed samples (re-run score reduction/aggregation)
     - `stats` = computed from all samples

6. **Clean up** the buffer DB for this log (since data is now in the recovered file). **Important:** the recovered `.eval` file must be fully written and verified before calling `buffer.cleanup()`. The buffer DB is the only source of unflushed sample data — if cleanup happens before the write completes (or if the write fails), that data is permanently lost. The `SampleBufferDatabase` has no persistent connection (connections are per-operation via context manager), so the handle can be held open for the duration of `recover_eval_log()` without resource concerns.

### Extracting Messages from Buffer DB Events

The buffer DB `events` table stores the full event stream. To extract messages for a recovered `EvalSample`, use the same approach as `inspect_scout`'s `span_messages()`:

1. Call `timeline_build(events)` (from `inspect_ai.event`) to build a hierarchical timeline from the flat event list — this discovers the "main" trajectory
2. Walk the timeline's root span, filtering for `ModelEvent` instances
3. For each `ModelEvent`, extract `input` messages + assistant output message (from `output.choices[0].message`)
4. Handle `CompactionEvent` boundaries (summary grafts pre+post, trim prepends prefix, edit is transparent)

This gives us the reconstructed `messages` list. The last `ModelEvent.output` provides the `output` field for the `EvalSample`.

### Reconstructing EvalSample from Buffer DB

| Field | Source |
|-------|--------|
| `id`, `epoch`, `input`, `choices`, `target`, `metadata` | `EvalSampleSummary` from `samples` table |
| `messages` | Extracted from events via `timeline_build` + `ModelEvent` walking (see above) |
| `output` | Last `ModelEvent.output` from event stream |
| `scores` | From summary (if completed), `None` (if in-progress) |
| `events` | Directly from `events` table |
| `timelines` | Built via `timeline_build(events)` |
| `attachments` | From `attachments` table |
| `model_usage`, `role_usage` | From summary |
| `error` | From summary (if completed) or synthesized cancellation `EvalError` (if in-progress) |
| `started_at`, `completed_at`, `total_time` | From summary |

### Memory Efficiency

Recovery must handle large eval runs without loading all samples into memory. The approach:

1. **Open output ZIP in append mode** — use `ZipFile(temp_file, mode="a")` exactly as `ZipLogFile` does during normal eval recording. Each sample is written with `writestr()` and is immediately compressed and committed to the ZIP — it does not accumulate in memory.

2. **Stream flushed samples from the original .eval** — read each `samples/sample_*.json` entry from the source ZIP one at a time, write it directly to the output ZIP. Never load all flushed samples simultaneously.

3. **Iterate buffer DB samples** — fetch the sample summary list from the `samples` table (lightweight), then for each sample:
   - Fetch its events via `get_sample_data(id, epoch)` 
   - Reconstruct the `EvalSample`
   - Write it to the output ZIP
   - Discard before processing the next sample

4. **Summaries accumulate** — `EvalSampleSummary` objects are small and must all be present for the final `summaries.json`, so these are collected in a list (same as normal eval recording). This is fine since summaries are ~1% the size of full samples.

This mirrors the streaming pattern already used by `ZipLogFile` during eval execution — samples flow through one at a time, only summaries accumulate.

### Edge Cases

- **No buffer DB found**: Recover what's in the `.eval` file only (flushed samples). Warn that unflushed samples are lost.
- **Buffer DB has no additional samples**: Just finalize the `.eval` file with proper header/summaries.
- **Multiple buffer DBs** (from retried evals): Use the most recent one (by file modification time or PID).
- **`.eval` file has no samples at all** (crash before first flush): All data comes from buffer DB.

## Implementation Steps

Each step is self-contained and fully tested before moving on. Each step will have a distinct plan created and approved before coding begins.

### Step 1: Read crashed .eval files (done: `162628a3f`)

Created `src/inspect_ai/log/_recover/` package with:
- `_read.py` — `CrashedEvalLog` dataclass, `read_crashed_eval_log()` (async, uses `AsyncFilesystem` for S3 compatibility), `read_flushed_sample()` for streaming individual samples from an `AsyncZipReader`
- `__init__.py` — public exports

`read_crashed_eval_log()` validates the file is crashed (has `_journal/start.json` but no `header.json`), extracts `LogStart` (EvalSpec + EvalPlan), reads journal summaries from `_journal/summaries/*.json`, and collects sample entry names without loading sample data.

**Tests** (`tests/log/test_recover_read.py`): 6 tests covering basic reading, no-samples crash, rejection of complete logs, rejection of invalid files, individual sample reading, and multiple flush batches.

### Step 2: Read recovery data from sample buffer database (done: `664a9a43b`)

Created `_buffer.py` in the `_recover` package with:
- `BufferRecoveryData` dataclass — holds `completed` and `in_progress` sample lists plus an open `SampleBufferDatabase` handle for per-sample event/attachment queries
- `read_buffer_recovery_data(location, db_dir=None)` — locates the buffer DB via `SampleBufferDatabase(location, create=False)`, reads all sample summaries, classifies by `completed_at` field

No new query methods were needed — the existing `get_samples()` and `get_sample_data(id, epoch)` methods on `SampleBufferDatabase` are sufficient.

**Tests** (`tests/log/test_recover_buffer.py`): 6 tests covering mixed completed/in-progress, event accessibility via DB handle, no DB, empty DB, all-completed, all-in-progress.

### Step 3: Reconstruct EvalSample from buffer DB data (done: `a05ce7fda`)

Created `_reconstruct.py` in the `_recover` package with:
- `reconstruct_eval_sample(summary, sample_data, cancelled=False)` — deserializes event JSON dicts via `TypeAdapter(list[Event])`, uses `timeline_build()` + `span_messages` pattern to extract messages (handling compaction boundaries: summary grafts, trim prefix, edit transparent), extracts output from last `ModelEvent`, synthesizes cancellation `EvalError` for in-progress samples (`message="CancelledError()"` matching normal cancellation flow)
- Produces fully resolved (uncondensed) `EvalSample` — `condense_sample()` is applied later at write time in Step 4

Key design decisions:
- Buffer DB events have full `ModelEvent.input` (no message pooling) — pooling only happens in `.eval` file writes
- Attachments from buffer DB stored in `EvalSample.attachments` dict
- Timeline built via `timeline_build()` and stored in `EvalSample.timelines`
- Memory: one uncondensed sample at a time in the Step 4/5 streaming pipeline

**Tests** (`tests/log/test_recover_reconstruct.py`): 7 tests covering completed sample, cancelled sample, no ModelEvents, multiple ModelEvents, empty events, attachments, and `.summary()` round-trip.

### Step 4: Write recovered .eval file (done: `493de0a1d`)

Created `_write.py` in the `_recover` package with:
- `write_recovered_eval_log(crashed, flushed_samples, buffer_samples, output)` — combines all samples, sorts by epoch/id, computes `EvalStats` (aggregated model/role usage, timestamps), builds `EvalLog` with status `"error"`, calls `recompute_metrics()` to compute `EvalResults` from sample scores using scorer config in `EvalSpec`, writes via `write_eval_log_async()` (which handles `condense_sample()` for message pooling)
- `default_output_path()` — replaces `.eval` with `-recovered.eval`
- Logs `logger.warning` if `recompute_metrics()` fails (e.g. missing scorer config)

**Tests** (`tests/log/test_recover_write.py`): 6 tests covering basic write+readback, sample sorting, stats aggregation, mixed scored/unscored, default output path, empty samples.

### Step 5: `recover_eval_log()` Python API

Wire steps 1-4 together into the public `recover_eval_log()` function. Handle the full lifecycle: validate input, read crashed log, find buffer DB, reconstruct samples, write recovered file, optionally clean up the buffer DB. Also implement `recoverable_eval_logs()` for discovery.

**Tests:** End-to-end test — set up a crashed `.eval` + buffer DB, call `recover_eval_log()`, verify the output file is a valid complete log. Test `recoverable_eval_logs()` discovery. Test edge cases (no buffer DB, empty buffer DB).

### Step 6: `inspect log recover` CLI (direct and list modes)

Add the Click command to the `log` command group. Implement direct mode (`inspect log recover <file>`) and list mode (`inspect log recover --list`). These are thin wrappers over the Python API.

**Tests:** CLI invocation tests using Click's test runner.

### Step 7: Interactive TUI mode

Build the Textual app for the default no-argument `inspect log recover` invocation. Table display of recoverable logs with stats, checkbox selection, batch recovery with progress feedback.
