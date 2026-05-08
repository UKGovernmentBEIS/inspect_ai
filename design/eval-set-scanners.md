# Scanners in `eval_set` (and `eval`)

## Goal

Allow callers of `eval_set` (and `eval`) to attach one or more `inspect_scout` scanners that run against each sample's transcript as the sample completes. Scanner results are persisted into a scout-format scan directory under the eval log dir, not embedded in the inspect_ai `EvalLog`.

A central design constraint: **the on-disk scan directory should match scout's standalone-`scout scan` layout exactly.** A scan dir produced by an inspect_ai eval_set must be indistinguishable from one produced by `scout scan`, so scout's tooling — `scan_resume`, `scan_complete`, the viewer, parquet readers — works unchanged. The eval_set-specific behavior is layered on top: lifecycle is driven by the eval_set call boundaries instead of scout's own CLI, and the per-sample dispatch loop runs alongside the eval rather than reading transcripts back from logs.

`inspect_scout` remains an **optional** dependency. Importing inspect_ai must not require inspect_scout. Only callers that pass a non-`None` `scanner` cause scout to be imported.

## User-facing API

A `scanner` parameter on `eval_set`, `eval`, and `eval_async`:

```python
scanner: EvalScanners | None = None
```

`EvalScanners` is a TypeAlias accepting:

- `Sequence[Scanner | tuple[str, Scanner]]` — direct scanner construction
- `dict[str, Scanner]` — named scanners
- `EvalScannerConfig` — Pydantic model carrying scanners + `tags`/`metadata`/`filter`/`model`/`model_args`/`generate_config`/`model_roles`/`scans`/`name`. A subset of scout's `ScanJob` schema, narrowed to fields that make sense when eval_set is generating the transcripts (drops `transcripts`, `worklist`, `limit`, `shuffle`, `max_processes`, `max_transcripts`, `validation`, `log_level`).

`EvalScannerConfig.from_file(path)` loads a YAML/JSON file (with `ScannerSpec` references resolved through scout's registry), making it possible to drive scanners from config.

### CLI

`inspect eval` and `inspect eval-set` accept the same input formats as `scout scan`:

```
--scanner SPEC                          # YAML/JSON config OR Python @scanner file OR pkg/name
--scanner-arg KEY=VALUE                 # scanner args
--scans                                 # output dir override
--scan-name / --scan-tags / --scan-metadata
-F / --scan-filter                      # SQL WHERE per-sample
--scan-model / --scan-model-base-url
--scan-model-arg / --scan-model-config
--scan-model-role
--scan-generate-config
```

CLI flags override equivalent fields in a YAML config.

## Scan Directory State

This is the load-bearing section. The state of the scan dir on disk is what scout's tooling reads, and it's where the inspect_ai/scout consistency invariant lives.

### Layout

A scan dir matches scout's standard layout:

```
{log_dir}/scans/scan_id={scan_id}/
  _scan.json                # ScanSpec — written once at init
  _summary.json             # whole-scan summary; complete flag
  _errors.jsonl             # one Error record per failed (scanner, transcript)
  {scanner_name}.parquet    # per-scanner compacted output
```

`scan_id` is the eval_set's `eval_set_id` when called from `eval_set`, or the eval's `run_id` when called standalone from `eval()`. The scan dir is created the first time a scanner-bearing call runs against a given log_dir.

Alongside, scout's per-transcript buffer accumulates in a separate location keyed by a hash of the scan dir path:

```
<scout_scanbuffer>/<hash>/
  _summary.json             # live, updated per record() call
  _errors.jsonl             # live, appended per record() call
  scanner=<name>/<tid>.parquet   # one per (scanner, transcript) pair
```

`<scout_scanbuffer>` defaults to `inspect_data_dir("scout_scanbuffer")`, overridable via `SCOUT_SCANBUFFER_DIR`. This is scout's existing convention; eval_set inherits it unchanged.

### State at each lifecycle phase

The scan dir's state is well-defined at each phase boundary. The buffer dir's state is also tracked because resume correctness depends on it.

| Phase | scan_dir contents | Buffer dir contents |
| --- | --- | --- |
| Before any scanner call | (does not exist) | (does not exist) |
| After `scan_init` (fresh) | `_scan.json` | `_summary.json` (`complete=False`) |
| After `scan_init` (attach to existing) | `_scan.json`, prior `_summary.json` flipped to `complete=False`, prior `*.parquet`, prior `_errors.jsonl` | `_summary.json` seeded from scan dir; per-transcript files preserved if previous run was `complete=False`, fresh if `complete=True` |
| Mid-scan (per-sample work in flight) | `_scan.json` only — `_summary.json`/`_errors.jsonl` not updated mid-flight | `_summary.json` updated per `record()`, `_errors.jsonl` appended per error, `<tid>.parquet` written per (scanner, transcript) |
| After `scan_finalize` with no scanner errors | `_scan.json`, `_summary.json` (`complete=True`), `_errors.jsonl` (empty), `*.parquet` containing every recorded row | Cleaned up |
| After `scan_finalize` with scanner errors | `_scan.json`, `_summary.json` (`complete=False`), `_errors.jsonl` (one entry per failure), `*.parquet` | Preserved (so `scan_resume` can pick up failed pairs) |
| After process kill mid-flight | Whatever the most recent finalize wrote, **plus** `_scan.json` if the kill was after `scan_init` of the current call | Buffer state from the killed call preserved (`complete=False` from `scan_init`) |

### `_summary.json`'s `complete` flag is meaningful

`_summary.json`'s `complete: bool` is the canonical signal for "did the most recent call's `scan_finalize` run, and did it run cleanly?"

To make this signal reliable across calls, `scan_init` flips `complete` to `False` in place when attaching to an existing scan dir. Stats (`scans`, `errors`, `results`, `tokens`, `model_usage`) are preserved — only the boolean is touched. Without this invalidation, a clean `complete=True` from run 1 would survive any subsequent crashed run, masking the gap.

Combined with `scan_finalize`'s `_sync_status_files` rewriting `_summary.json` with `complete = not errors_in_buffer` at every finalize, we get:

- `complete=True` ⇔ the most recent prior call's `scan_finalize` ran AND no scanner errors were captured AND no subsequent call has started.
- `complete=False` (or summary absent) ⇒ either the most recent call had errors, the most recent call crashed before finalize, or this is a fresh scan dir.

### Scout consistency invariant

The on-disk shape above is **identical** to what `scout scan` produces. Specifically:

- Same `_scan.json` schema (scout's `ScanSpec`).
- Same `_summary.json` schema (scout's `Summary`).
- Same `_errors.jsonl` format (scout's `Error` per line).
- Same compacted parquet schema (scout's `scanner_table` output).
- Same buffer dir layout (`scanner=<name>/<tid>.parquet`).
- Same `complete=True ⇒ buffer cleaned` invariant after `sync`.
- Same snapshot in `_scan.json`'s `transcripts` field (scout's `ScanTranscripts`).

This means:

- `scout scan-resume <scan_dir>` works on an inspect_ai-produced scan dir to retry failed scans.
- `scout scan-complete <scan_dir>` works to materialize a buffer-only scan that crashed before finalize.
- The scout viewer reads inspect_ai-produced scan dirs without modification.

The only inspect_ai-specific behavior is *who triggers* `scan_init` / `record` / `sync` and *when* — eval_set's per-sample call boundaries instead of scout's CLI lifecycle. The data shape is unchanged.

## Lifecycle

`scanner: EvalScanners | None` is threaded from the public entry point (`eval_set` or `eval`) down through `eval_async` → `_eval_async_inner` → `eval_run` → `TaskRunOptions` → `task_run` → `task_run_sample`.

The init/finalize bracket lives in a context manager `scan_context(scanner, scan_id, log_dir)`:

```python
@contextmanager
def scan_context(scanner, *, scan_id, log_dir):
    if scanner is None:
        yield
        return
    run_coroutine(scan_init(scanner, scan_id=scan_id, log_dir=log_dir))
    try:
        yield
    finally:
        run_coroutine(scan_finalize(scan_id=scan_id, log_dir=log_dir, scanner=scanner))
```

`eval_set` wraps its retry loop in `scan_context` keyed on `eval_set_id`. `eval()` wraps its run loop in `scan_context` keyed on `run_id` *only when called standalone* (i.e. when no `eval_set_id` is set) — when called from eval_set, the outer scan_context already brackets the call.

### Per-sample dispatch (eval phase)

In `task_run_sample`, after `log_sample` and before `emit_sample_end`:

```python
await scan_eval_sample(
    eval_sample, scanner,
    scan_id=scan_id, eval_id=task_id,
    log_location=log_location, model=str(state.model),
)
```

`scan_eval_sample` builds a `Transcript` from the `EvalSample`, applies the `EvalScannerConfig.filter` SQL clauses to skip non-matching samples, and dispatches each scanner via scout's `_scan_one`. Records to the buffer via an ephemeral `FileRecorder().attach(scan_dir, concurrent_writers=True)`.

### Per-sample resume-scan (reuse path)

When `eval_set` resumes — or when a scanner is added on a later call — some samples come back as `PreviousTask` reuses rather than fresh runs. For these, `task_run_sample` is bypassed; the sample is fetched from the prior log via `sample_source` and short-circuited.

To close the gap (sample logged but never scanned), `task_run` snapshots the set of already-scanned transcript_ids per scanner via `scanned_transcripts_for_resume` and passes it to the reuse path. Inside the reuse branch, `resume_scan_previous_sample` checks the snapshot and dispatches `scan_eval_sample` for any reused sample whose transcript_id is missing — under the same `sample_semaphore` so resume-scan work shares the eval phase's parallelism budget.

The snapshot is non-empty (and the check fires) **only** when `scan_already_clean(scanner, scan_id, log_dir)` is False — i.e., the most recent prior finalize wasn't clean. When the prior scan finalized cleanly, the check is skipped entirely (the file existence + parquet column read) — no per-sample work.

### Routing success-logs through `PreviousTask`

`eval_set` normally short-circuits to return success-logs unchanged when there's nothing pending or failed. When a scanner is configured **and** the prior scan isn't already clean, success-logs are converted to `PreviousTask` wrappers and added to `tasks_to_run` (alongside any pending/failed tasks) so the per-sample reuse path runs for them — picking up unscanned transcripts. When the prior scan is clean, the routing is skipped — pure short-circuit, no scanner work.

This routing must fire whether or not there are also pending/failed tasks in the same call. Otherwise unscanned transcripts in already-completed tasks are silently skipped on every call that has any other work.

## Concurrency

Inspect_ai runs samples concurrently up to `max_samples`. Multiple `scan_eval_sample` calls overlap. Within each call, scanners dispatch sequentially in a simple loop — keeps scout's prompt-cache-warming "lead/follower" pattern intact (the savings only become positive at 3+ scanners per sample, so naive `tg_collect` would lose the benefit).

The contended resource is scout's `_summary.json` (read-modify-write). `RecorderBuffer` accepts a `concurrent_writers=True` flag that wraps the read-modify-write in a per-buffer-dir `anyio.Lock`. inspect_ai opts in; scout's existing single-process and multi-process flows leave it off.

The connection-pool semaphore for the eval-side model API is shared with scanner-side calls when the scanner inherits the eval's model. Scout's per-Model semaphore keys on `connection_key()` so calls from both sides queue through the same limit.

## Filter semantics

`EvalScannerConfig.filter` is a SQL WHERE clause (or list of them) lifted from scout's `Transcripts.where(...)`. Where scout applies the filter at query time against its database, eval_set applies it per-sample inline before dispatching scanners. The semantics are identical: a sample whose transcript fields don't match is skipped — no parquet row, no entry in the snapshot, no scan attempt.

### How `_sample_matches_filters` evaluates a clause

Per-sample evaluation runs through scout's filter language end-to-end:

1. **Parse + emit** via scout's `condition_from_sql` (parses the user's WHERE clause into a `Condition`) and `condition_as_sql(cond, "sqlite")` (emits parameterized sqlite SQL with double-quoted identifiers and `json_extract` for JSON-path shorthand like `sample_metadata.group = 'a'`). Same parser/emitter scout uses against parquet/sqlite-backed transcripts.
2. **Build a one-row table** using scout's `TranscriptColumns` schema. `_filter_row` calls inspect_ai's `import_record` twice — once with a synthesized `EvalLog` for eval-level columns (`model`, `task_set`, `eval_metadata`, …), once with the `EvalSample` for sample-level columns (`task_id`, `total_tokens`, `sample_metadata`, …). JSON columns are JSON-encoded by scout's column `value` callbacks so `json_extract` works.
3. **Run** `SELECT 1 FROM t WHERE {scout_emitted_sql}` against an in-memory sqlite table containing that one row. Filter values bind as `?` parameters; only identifiers are interpolated.

Iterating `TranscriptColumns` (rather than hand-rolling each column) means new columns scout adds flow through automatically.

### Safety properties

- **No injection via filter values.** Scout's emitter parameterizes user-supplied values as `?`. Adversarial filter strings (`error = ''; DROP TABLE t; --`, `UNION SELECT ...`, subqueries) are rejected at parse time — verified with tests.
- **Identifier escaping.** Column names from `score_*` expansion can contain arbitrary characters (a malicious score name like `evil") CHECK(0=1)) --` would otherwise inject a CHECK constraint into our `CREATE TABLE`). All identifiers are escaped per the SQL standard (`"` → `""`) before interpolation.
- **Typo'd column refs raise.** sqlite's "double-quoted string literal" compatibility mode would silently turn `"unknown_col" = 'x'` into `'unknown_col' = 'x'` (always False). A regex pre-pass over scout's emitted SQL extracts double-quoted identifiers and raises `OperationalError: no such column: ...` if any aren't in the row's columns.

## Scanner config verification on reattach

When a second `eval_set` call lands on an existing scan dir, `scan_init` runs `_verify_scanner_config_unchanged` before doing anything else. Three checks, ordered cheapest first; any mismatch raises `PrerequisiteError`:

1. **Scanner names** — set equality between prior `_scan.json`'s `scanners` keys and the new run's. Adding/removing a scanner means the new run wants different output than the scan dir holds.
2. **Per-scanner `ScannerSpec` equality** — full equality on each scanner's `params`, `version`, `file`, `package_version`. Same name + different code/params produces different output for the same transcript; reusing the prior parquet rows would be wrong.
3. **Eval-set-level config hash** — sha256 of `filter`, `model`, `model_args`, `generate_config`, `model_roles`, `model_base_url`. None of these are in scout's `ScannerSpec`. The hash is stashed in `ScanSpec.metadata[__inspect_scan_config_hash__]` at fresh-init and at every successful reattach.

Why this matters: the `prior_scan_clean` short-circuit (see "Routing success-logs through `PreviousTask`") elides per-sample resume-scan work when the prior finalize was clean, on the assumption "every transcript already has a row." That's only true if the scanner config hasn't changed. Otherwise — the user's example, `filter="error != ''"` → no filter — previously-filtered-out transcripts would be silently left unscanned.

Excluded from the hash by design: `name`, `tags`, `metadata`, `scans`. Those are labels/output-location, not behavior; users updating a tag shouldn't be forced to start fresh. The eval-level model (`eval_set(model=...)`) is also excluded — different model produces different transcript uuids, which already differentiate work in the scan dir naturally; capturing it in the hash would force a fresh `log_dir` for every model swap.

Resolution surface: the error message names which check fired and points at the user's two options — different `log_dir`/`scan_id` for a fresh scan, or revert the change. No override flag; if someone needs one, they can ask.

## Scout-side changes that landed

These accumulated as the design firmed up; all are merged in scout:

1. `_scan_one` extracted from `_scan_async_inner`'s closure to a module-level function in `_scan.py`.
2. `Scanners` type alias exported.
3. `concurrent_writers: bool = False` kwarg on `RecorderBuffer.__init__` / `FileRecorder.init` / `FileRecorder.resume`. Wraps `_summary.json` read-modify-write in a per-buffer-dir `anyio.Lock`.
4. `scanner_table` dedupes by `transcript_id` between buffer files and `extra_inputs`. The buffer's per-transcript file is authoritative for its transcript_id; rows for the same id from `extra_inputs` (the previously-compacted parquet) are dropped. Without this, multi-call `sync` cycles double-count.

## Retry behavior

inspect_ai has three retry mechanisms that each interact differently with scanners. The scan layer's invariant cuts across all of them: **after `scan_finalize`, the parquet's `transcript_id`s equal the union of `sample.uuid` across surviving eval logs.** Live samples have rows; orphans (uuids that no longer correspond to any sample) are swept.

### 1. Sample-level retry — `retry_on_error`

Per-sample retry inside `task_run_sample`. If a sample errors with retries left, the function recurses with `retry_on_error - 1`. The retry happens before `log_sample` and `scan_eval_sample` for the failed attempt would have fired — so failed attempts that will be retried produce no eval log entry and no scan row. Only the *settled* attempt (the one that won't retry, whether it succeeded or exhausted the budget) runs the log + scan block.

The guard in `task_run_sample`:

```python
if not error or (retry_on_error == 0) or (cancelled_error is not None):
    ... log_sample + scan_eval_sample ...
```

Net effect: a sample retried N times produces **exactly one** parquet row, reflecting the final settled outcome (success or exhausted-retry error).

### 2. Task-level retry — `retry_immediate=True`

When `retry_immediate=True`, eval_set's `task_retry_attempts` is forwarded to `run_task_retry_attempts`, which re-queues the whole task on error. Each retry:

- Calls `task_options.logger.reinit()` → fresh `eval_id`, fresh log file.
- Carries forward succeeded samples via `eval_log_sample_source` — these reuse their original uuid.
- Filters out errored samples (`if sample.error is not None: return None`) — these get **re-executed** by the eval phase with a brand new `TaskState`, which mints a new `uuid` (`sample_uuid or uuid()` in `TaskState.__init__`).

So a sample that always fails accumulates one parquet row per attempt, each with a distinct `transcript_id`. After all retries:

- `retry_cleanup=True` (default) deletes the older log files; only the latest survives.
- `scan_finalize` runs the orphan cleanup: scan rows whose transcript_id isn't a uuid in any surviving log are removed.

Result: parquet matches the surviving log — one row per surviving sample. With `retry_cleanup=False`, every log file survives, every uuid stays live, and every row is preserved.

`summary.scans` counts work *performed* across attempts (sum of `record()` calls), not surviving rows. So a 3-attempt always-failing sample has `summary.scans == 3` and `parquet.num_rows == 1` after cleanup. The summary is the historical view; the parquet is the live view.

### 3. eval_set retry — `retry_immediate=False` (default)

The legacy path: tenacity wraps `try_eval` and retries it on `not all_evals_succeeded`. Each retry of `try_eval`:

- Re-discovers logs in `log_dir`.
- Builds `failed_tasks = as_previous_tasks(failed_resolved_tasks, failed_logs, ...)` — wraps the failed log as a `PreviousTask`.
- Calls `run_eval(eval_set_id, tasks_to_run)`.

`run_eval` uses the same `eval_log_sample_source` path internally — succeeded samples reuse their uuid, errored samples get re-executed with a fresh uuid. Same shape as the task-level retry, just driven from a different layer.

After all retries, `retry_cleanup` and `scan_finalize` produce the same on-disk shape as `retry_immediate=True`. The two paths converge on the same scan dir invariant.

### Why uuids change for re-executed errored samples

A re-execution is a new sample run with new messages, new model calls, possibly different scores. Reusing the prior uuid would conflate two distinct attempts in any downstream system that keys on transcript_id (scout's compaction, dedup, the viewer). So each fresh execution gets a fresh identity — the asymmetry between succeeded samples (reuse uuid) and errored re-runs (new uuid) follows from this: succeeded samples aren't actually re-executed, just carried forward.

### Orphan cleanup at `scan_finalize`

`_cleanup_orphan_scan_rows` runs between `sync` and the snapshot step. Steps:

1. Walk `list_eval_logs(log_dir)` and read cheap `EvalSampleSummary`s. Collect every `summary.uuid` → `live_tids`.
2. For each scanner's compacted parquet (`<scan_dir>/<name>.parquet`):
   - Stream row-group-by-row-group via `ParquetFile.read_row_group(i)` (avoids pyarrow's cross-row-group schema-merge issue with scout's dictionary-encoded output).
   - Filter via `pc.is_in(transcript_id, value_set=live_tids)`.
   - Rewrite only if any rows were actually removed.
3. For each scanner's buffer dir (`<buffer_dir>/scanner=<name>/`):
   - Unlink `<tid>.parquet` for any tid not in `live_tids`. Covers the `complete=False` case where the buffer survives sync.

The snapshot in `_scan.json` is built from the cleaned compacted parquet, so it also reflects only live transcripts.

### Quick reference

| Scenario | Behavior |
| --- | --- |
| Sample retried via `retry_on_error` | One parquet row per sample (final settled attempt only); intermediate retries skip log + scan |
| Sample re-run by `retry_immediate=True` or eval_set retry | One row per attempt mid-run; orphan cleanup at finalize sweeps rows whose log was deleted by `retry_cleanup` |
| `retry_cleanup=False` | All attempt logs preserved → all uuids live → no orphans removed → all rows preserved |
| Sample's scan errored (parquet `scan_error` populated) | Treated as intentional, not retried by inspect_ai. `scout scan-resume` is the path for retrying captured scan errors |
| Sample's eval log lands but scan never recorded (crash in window, or scanner added on later call) | Caught on next eval_set call by the per-sample resume-scan in the reuse path |
| Process killed mid-flight | `_summary.json` at scan_dir reflects whatever the last finalize wrote (or absent); buffer state preserved from the killed call. Next eval_set call's `scan_init` invalidates `complete=False`, runs the per-sample resume-scan check, recovers the gap |

## Out of Scope

- Embedding scanner results into the inspect_ai `EvalLog`.
- A unified `inspect view` rendering of scan results alongside eval logs.
- `fail_on_error` integration (per-scanner or eval-wide).
- Plumbing eval-level model config into scout (scanners configure their own models).

## Future Work

### Buffer co-located with scan dir (or eliminated entirely)

Per-transcript buffer parquets live in `<scout_scanbuffer>/<hash>/`, separate from the scan dir. Trade-offs:

- Mid-eval visibility: scan dir has `_scan.json` only mid-flight; buffer dir is where the live state is.
- Self-containment: copying or moving the eval log dir doesn't bring scanner data with it.
- Crash recovery: a crash before finalize leaves data in cache, recoverable by `scout scan-complete <scan_dir>`.

A natural improvement is to co-locate the buffer at `<scan_dir>/scanner=<name>/<tid>.parquet`. The reason this isn't done yet is S3 write performance under per-sample load, which we haven't measured. This is a scout-side change that doesn't affect inspect_ai's call sites.

### Retry-errored-scans on resume

Today `scan_eval_sample` errors recorded by scout (parquet rows with `scan_error`) are intentional and aren't retried by inspect_ai's per-sample resume-scan path — `scout scan-resume <scan_dir>` is the path for that. We could add an opt-in `retry_errors` flag on `EvalScannerConfig` so a transient scanner error self-heals on the next eval_set call.
