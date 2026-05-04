# Scanners in `eval_set`

## Goal

Allow callers of `eval_set` to attach one or more `inspect_scout` scanners that run against each sample's transcript as the sample completes. Scanner results are persisted into a scout scan directory under the eval log dir, not embedded in the inspect_ai `EvalLog`.

## User-facing API

A new `scanner` parameter on `eval_set` accepting the same shape as `inspect_scout.scan_async`'s `scanners` argument:

```python
scanner: (
    Sequence[Scanner[Any] | tuple[str, Scanner[Any]]]
    | dict[str, Scanner[Any]]
    | ScanJob
    | ScanJobConfig
    | None
) = None
```

Aliased in scout as `inspect_scout.Scanners`. Singular name (`scanner`) follows the existing `solver` precedent. Type matches scout exactly so `ScanJob` users can pass full scout configurations through unchanged.

`inspect_scout` remains an **optional** dependency. Importing inspect_ai must not require inspect_scout. Only callers that pass a non-`None` `scanner` cause scout to be imported.

## Integration Strategy

### Per-sample dispatch via scout's `_scan_one`

After each sample completes (`task_run_sample`, between `log_sample` and `emit_sample_end`), invoke each user-supplied scanner against the just-completed sample's transcript. We call scout's per-scanner dispatch primitive (`_scan_one`) directly rather than going through `scan_async`. This skips `scan_async`'s recorder lifecycle, display setup, multi-process strategy, and worklist resolution — none of which add value for a single in-memory transcript.

`_scan_one(job, *, validation=None, fail_on_error=False) -> list[ResultReport]` is exposed at module level in scout's `_scan.py` (extracted from a closure in `_scan_async_inner`). It iterates the scanner's loader over a `union_transcript`, invokes the scanner per yielded input, captures inspect-side events and model usage, and returns `ResultReport`s. inspect_ai imports it as `from inspect_scout._scan import _scan_one`.

### In-memory transcript construction

Building a `Transcript` from an `EvalSample` is done directly in inspect_ai's `_eval/task/scan.py`. We don't subclass scout's `Transcripts`/`TranscriptsReader` ABCs because we never call `scan_async` — we just need a single `Transcript` instance to hand to `ScannerJob`. The construction:

- `transcript_id = sample.uuid or f"{sample.id}_{sample.epoch}"`
- `task_id = str(sample.id)`, `task_repeat = sample.epoch` — these match scout's `EvalLogTranscripts` keying so log-derived and in-eval scans unify on `(task_id, task_repeat)`
- `messages` and `events` from the sample directly
- `timelines` from `sample.timelines` if populated; otherwise built via `inspect_ai.event.timeline_build(sample.events)` if needed by a scanner
- Other `TranscriptInfo` fields populated from in-scope context (`eval_id`, `model`, `log_location`, sample timing/scoring metadata)

### Output layout

Per-sample scans share a single scan directory keyed by `eval_set_id`:

```
{log_dir}/scans/scan_id={eval_set_id}/
  scan.json                       # ScanSpec (written once at init)
  _summary.json                   # live, updated per record()
  _errors.jsonl                   # live, appended per record()
  {scanner_name}.parquet          # compacted result per scanner (post-sync)
```

`scan_id` matches `eval_set_id` so eval_set retries write into the same scan directory.

During the eval, per-transcript parquets accumulate in scout's existing buffer (a hashed cache dir under `inspect_data_dir("scout_scanbuffer")`). At end of `eval_set`, `FileRecorder.sync(scan_dir, complete=True)` compacts the buffer into `<scanner>.parquet` files in the scan dir.

## Lifecycle in `eval_set`

`scanner: Scanners | None` is threaded from `eval_set` through `eval` → `eval_async` → `_eval_async_inner` → `eval_run` → `TaskRunOptions` → `task_run` → `task_run_sample`. The chain mirrors how `solver` is forwarded.

Recorder lifecycle is bound to `eval_set` (one recorder per eval_set, shared across retries):

```python
# evalset.py
if scanner is not None:
    run_coroutine(scan_eval_set_init(scanner, eval_set_id, log_dir))
try:
    results = retry(try_eval)   # threads `scanner` down to task_run_sample
finally:
    if scanner is not None:
        run_coroutine(scan_eval_set_finalize(eval_set_id, log_dir))
```

Per-sample dispatch happens in `task_run_sample` between `log_sample` and `emit_sample_end`:

```python
await scan_eval_sample(
    eval_sample,
    scanner,
    eval_set_id=eval_set_id,
    eval_id=task_id,
    log_dir=log_dir,
    log_location=log_location,
    model=str(state.model),
)
```

## Implementation in `_eval/task/scan.py`

Module-level state in `scan.py` holds per-eval_set bookkeeping (just the `scan_dir` location and the normalized scanners dict — no Python recorder object, see "Recorder lifecycle" below).

```python
# state populated by scan_eval_set_init, drained by scan_eval_set_finalize
@dataclass
class _ScanState:
    scan_dir: str
    scanners: dict[str, Scanner[Any]]

_scan_states: dict[str, _ScanState] = {}   # keyed by eval_set_id


async def scan_eval_set_init(scanner, eval_set_id, log_dir):
    """Build ScanSpec, lay down scan dir + scan.json + initial buffer state."""
    scanners_dict = _normalize_scanners(scanner)
    spec = ScanSpec(scan_id=eval_set_id, scan_name="eval_set", scanners=_spec_scanners(scanners_dict))
    recorder = FileRecorder()
    await recorder.init(spec, f"{log_dir}/scans")
    _scan_states[eval_set_id] = _ScanState(
        scan_dir=await recorder.location(),
        scanners=scanners_dict,
    )


async def scan_eval_sample(eval_sample, scanner, *, eval_set_id, eval_id, log_dir, log_location, model):
    if eval_set_id is None:
        return
    state = _scan_states.get(eval_set_id)
    if state is None:
        return   # no scanner configured; no init was done

    info = _transcript_info(eval_sample, eval_id=eval_id, model=model, log_location=log_location)
    transcript = _transcript(eval_sample, info=info)

    for name, scanner_fn in state.scanners.items():
        job = ScannerJob(union_transcript=transcript, scanner=scanner_fn, scanner_name=name)
        reports = await _scan_one(job)              # unlocked, parallel-safe
        recorder = FileRecorder()
        await recorder.resume(state.scan_dir)
        await recorder.record(info, name, reports, metrics=None)


async def scan_eval_set_finalize(eval_set_id, log_dir):
    state = _scan_states.pop(eval_set_id, None)
    if state is None:
        return
    await FileRecorder.sync(state.scan_dir, complete=True)
```

## Recorder lifecycle

We **don't** hold a long-lived `FileRecorder` instance. Each `scan_eval_sample` call constructs an ephemeral `FileRecorder()` and calls `.resume(scan_dir)` to attach to the on-disk scan state. The on-disk state — `scan.json`, the buffer dir, the per-transcript parquets, the summary file — is the source of truth; the Python object is just a transient handle.

Why ephemeral:

- No state needs threading through layers (the scanner config is already threaded; the recorder is implementation detail)
- `resume()` is cheap (small JSON read of `scan.json` + summary file)
- No shared in-memory mutable across coroutines, so most concurrency hazards disappear

Why a one-time `init()` upfront:

- `init()` writes `scan.json` and the initial empty `_summary.json`/`_errors.jsonl`
- Subsequent `resume()` calls find that state and attach to it (no `reset=True`, so accumulated summary is preserved)
- Per-sample re-init would wipe the summary file each call

## Concurrency

Inspect_ai runs samples concurrently up to `max_samples`. Multiple `scan_eval_sample` calls overlap. Within each call, scanners dispatch **sequentially** in a simple loop. Cross-sample parallelism is where the win is: each scanner's `_scan_one` (the LLM call) is unlocked, so concurrent samples run their scanner work in parallel.

We deliberately do not parallelize scanners *within a sample*. Scout uses a "lead/follower" cache-warming pattern (`_scan.py:613-622`): the first scanner's generate populates the prompt cache so subsequent scanners hit the warm cache. We get the same benefit by running scanners sequentially within a sample. Naive `tg_collect` over all scanners would lose that benefit.

Even the lead/follower pattern only pays off at **3+ LLM scanners** per sample: with N scanners under the pattern, wall-clock is ~`lead_time + max(follower_times)` ≈ `2 * scanner_time` (assuming similar per-scanner latency), versus `N * scanner_time` sequentially. The savings only become positive at N ≥ 3. Until eval traces show real wall-clock pain on 3+ scanner setups, sequential within-sample is the right default.

The contended resources are scout's `RecorderBuffer` shared mutables:

| Resource | Concurrency profile | Lock needed? |
|---|---|---|
| Per-transcript parquet (`scanner=<n>/<id>.parquet`) | One file per `(scanner, transcript_id)` pair — distinct paths | No |
| `_errors.jsonl` (append-only) | OS-atomic append (`open(..., "at")`) | No |
| `_summary.json` (read-modify-write) | Multiple writers across ephemeral instances | **Yes** |

`_summary.json` is the only true race. Each `record()` call reads the existing summary, updates in memory, and writes back. Without serialization, concurrent `record()` calls produce lost updates (last writer wins).

### Optional in-process lock in scout

`RecorderBuffer` gains an opt-in concurrent-summary mode. Existing scout users (single-process and multi-process scans via `scan_async`) keep current behavior; inspect_ai opts in.

```python
class RecorderBuffer:
    def __init__(
        self,
        scan_location: str,
        spec: ScanSpec,
        *,
        pool_dedup: bool = True,
        reset: bool = False,
        concurrent_writers: bool = False,   # NEW
    ): ...
```

When `concurrent_writers=True`, `record()` and `record_metrics()` acquire a module-level `anyio.Lock` keyed by buffer dir before the read-modify-write of the summary file. The parquet write stays outside the lock — concurrent samples writing to S3 don't block each other, only the brief summary update is serialized.

`FileRecorder.resume()` gains the same kwarg and forwards it.

In-process scope is sufficient because all per-sample scans within an `eval_set` happen in one process. Scout's existing multi-process scan flow doesn't use `concurrent_writers=True` and isn't affected.

## What scout already gives us (no change needed)

`RecorderBuffer` already writes per-transcript parquets keyed by `transcript_id`:

```
<buffer_root>/<hash_of_scan_location>/
  scanner=<scanner_name>/
    <transcript_id>.parquet
```

`is_recorded()` checks the per-transcript parquet directly. `RecorderBuffer.__init__(reset=True)` only resets the summary and errors files — it does **not** touch transcript parquets. So per-transcript artifacts are durable across re-init.

`FileRecorder.sync(scan_location, complete=True)` already compacts buffer parquets into `<scanner>.parquet` and copies summary/errors to the scan dir. We use this unchanged at end-of-evalset.

## Required scout changes

1. **Extract `_scan_one`** from inside `_scan_async_inner`'s closure to a module-level function in `_scan.py`, taking `(job, *, validation=None, fail_on_error=False)`. The closure version delegates. (Done.)

2. **Add `Scanners` type alias** in scout, exported from `inspect_scout/__init__.py`. (Done.)

3. **Add `concurrent_writers: bool = False` kwarg** to `RecorderBuffer.__init__`, `FileRecorder.init`, `FileRecorder.resume`. When `True`, summary read-modify-write is wrapped in a per-buffer-dir `anyio.Lock`. Default `False` preserves existing behavior.

## Concurrency, Errors, Retries

- **Awaited inline.** Sample completion blocks on the scan. The eval's existing `max_samples` controls per-sample concurrency, so scanner load scales with sample load.
- **Sample retries.** A sample retried via `retry_on_error` produces a scan only on its successful (or final) attempt. Abandoned attempts are not scanned.
- **Eval-set retries.** Re-running a sample writes a new parquet keyed by `transcript_id` — same id, same parquet path, overwrite. No de-duplication needed.
- **Scanner errors.** Captured by scout's existing error handling (`Error` records). Scanner errors do not fail the sample.
- **Crash mid-eval.** Per-transcript parquets are durable in the buffer. If `eval_set` crashes before `finalize()`, a manual `scan_complete <scan_dir>` reproduces the canonical layout. The `scan_eval_set_finalize` runs in a `finally` to maximize the chance it executes.

## Out of Scope (Initial Cut)

- Embedding scanner results into the inspect_ai `EvalLog`.
- A unified `inspect view` rendering of scan results alongside eval logs.
- `fail_on_error` integration (per-scanner or eval-wide).
- Plumbing eval-level model config into scout (scanners configure their own models).
- Sharing a single scout `Recorder` instance across samples within a process (would reduce per-sample resume cost; not measured yet).
- Scanner support on `eval()` / `eval_async()` directly. Currently only `eval_set` calls `scan_eval_set_init`/`finalize`. Direct `eval()` callers who pass a `scanner` argument get it threaded through but no recorder is initialized; `scan_eval_sample` no-ops.

## Future Work

### Buffer co-located with scan dir (or eliminated entirely)

The current design keeps scout's existing buffer behavior — per-sample parquets accumulate in a hashed cache dir under `inspect_data_dir("scout_scanbuffer")` and are compacted into the scan dir only by `sync()`. Trade-offs of that posture:

- **Mid-eval visibility.** The scan dir contains `scan.json`, `_summary.json`, and `_errors.jsonl` mid-eval (the latter two updated live), but not the per-scanner parquets — those land only after `sync()`.
- **Self-containment.** Copying or moving the eval log dir doesn't bring per-transcript scanner data with it (the buffer is in cache).
- **Crash recovery.** If `eval_set` crashes before `sync()`, the buffer parquets remain in cache; the user must run `scan_complete <scan_dir>` (or know about the cache dir) to materialize them.

A natural improvement is to co-locate the buffer with the scan dir — `<scan_dir>/scanner=<name>/<transcript_id>.parquet` directly. The reason this isn't in the initial cut is S3 write performance under per-sample load, which we haven't measured. Once we've measured, we can decide whether to co-locate or eliminate the buffer entirely. This is a separable change from scanner-in-eval-set.

## Open Questions

1. **Cross-process summary safety.** The `concurrent_writers` lock is in-process only. Scout's existing multi-process scan flow has the same race today (and isn't affected by this change). If anyone uses scout multi-process and observes lost summary updates, a `fcntl.flock`-based file lock is the natural fix — out of scope here.
