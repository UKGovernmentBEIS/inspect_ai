# SampleSource: driving a running task from code

This document describes `SampleSource` — the sample-level mirror of
[`TaskSource`](task-source.md). Where a `TaskSource` produces *tasks* for a
running eval, a `SampleSource` produces *samples* for a running task: a seed
plus result-driven follow-ups, all within one task / eval log. Motivating use
cases are the same (RL loops, adaptive evals), scoped inside a single task.

## The contract

`src/inspect_ai/_eval/task/sample_source.py` defines a subclassable base class
with no-op defaults:

```python
class SampleSource:
    def initial_samples(self) -> list[Sample]: ...                       # sync seed (immediate; may be empty)
    async def next_samples(self) -> list[Sample] | None: ...             # async; None ends the task
    async def sample_complete(self, sample: EvalSample) -> list[Sample] | None: ...  # observe + add
```

The asymmetry mirrors `TaskSource`:

- **`initial_samples()` is synchronous** — it is called when the `Task` is
  constructed (see below) and becomes the task's up-front dataset, driving
  validation / sandbox startup / display totals. Unlike a plain dataset it
  **may be empty**: the task then starts by calling `next_samples()`.
- **`next_samples()` is async and may block indefinitely.** It is called only
  when the task is fully idle (nothing in flight, nothing buffered), so no
  completion can enqueue while it blocks (no lost wakeup). Returning `None`
  ends the task.
- **`sample_complete()`** fires per sample (right after the sample is logged /
  `emit_sample_end`, alongside the `TaskSource.sample_complete` firing site in
  `task_run_sample`) and may **return follow-up samples**, which are routed
  onto the task's `SampleEnqueuer` — the same buffer `enqueue_sample` feeds.

`SampleSource.from_samples(initial_samples, *, next_samples=None,
sample_complete=None)` builds a source from a seed + callbacks without
subclassing (mirrors `TaskSource.from_tasks`).

There is no `@sample_source` decorator: a `SampleSource` lives *inside* a
`Task`, and tasks are already registerable / loadable by name via `@task` — the
source needs no registry identity of its own.

## Where it plugs in

A `SampleSource` is passed as the **`dataset` argument to `Task`** (just as a
`TaskSource` is passed as the `tasks` argument to `eval()`):

- **Task resolution** — `resolve_dataset_or_source`
  ([task.py](../src/inspect_ai/_eval/task/task.py)) returns a `ResolvedDataset`
  NamedTuple: `task.dataset` is a `MemoryDataset` of the seed (empty allowed —
  the plain-dataset empty check is bypassed) and `task.sample_source` carries
  the source. Everything downstream that reads `task.dataset` (log spec,
  sandbox startup, auto-id assignment of the seed in `prepare_options`) is
  unchanged.
- **No eval-level changes** — the source travels on the `Task` itself; `eval()`
  / `eval_run` / `TaskRunOptions` needed no new parameter. (`TaskRunOptions`
  already has a `sample_source` field — that is `EvalSampleSource`, the
  prior-attempt lookup used by retries. Inside `task_run` the SampleSource is
  therefore held in a local named `sample_feed` to avoid confusion.)
- **The dispatcher** — in [task/run.py](../src/inspect_ai/_eval/task/run.py),
  `task_run` replaces the fixed `tg_collect` fan-out with a live loop
  (`run_samples_dynamic`) when `task.sample_source` is set. It mirrors
  `run_multiple`'s feed loop: spawn the seed, then per cycle drain the
  enqueuer (spawning injected samples immediately — live, not batched), wait
  on a re-armable `Wake` (moved to `_util/_async.py`, shared with the
  eval-level dispatchers) while anything is in flight, and only when fully
  idle await the blocking `next_samples()`. Sample concurrency is already
  bounded by the sample semaphore inside `run_sample`, so the dispatcher
  spawns eagerly with no cap of its own. Plain tasks keep the unchanged
  `tg_collect` path. When `next_samples()` returns `None`, the enqueuer is
  drained once more so samples enqueued during the terminal call still run
  (nothing is silently dropped; the source may then be consulted again). Each
  loop iteration starts with an `anyio.lowlevel.checkpoint()` so a source
  that never blocks (e.g. returns `[]` forever) stays cancellable.
- **Injected sample storage** — injected samples are appended to an in-memory
  list indexed after the (possibly disk-paged) seed store; `get_sample(index)`
  dispatches between the two. Each injected sample runs for the task's
  configured `epochs`, like the seed.
- **Ids** — injected samples without ids get auto-ids continuing the seed's
  1-based numbering, skipping ids already in use; a duplicate explicit id is a
  hard error. Ids are compared by their `str()` form, matching
  `ensure_unique_ids` (log member names and score grouping key on it).
- **Growing totals** — `total_samples` grows as samples are added, updating the
  display denominator (`td.sample_complete`), the fractional `fail_on_error`
  threshold (`SampleErrorHandler.total_samples`), the end-of-run
  `eval_results` / `_should_eval_fail` counts, and the control-channel state
  via `record_samples_added` ([eval_state.py](../src/inspect_ai/_control/eval_state.py))
  — which also un-stamps a provisional `completed_at` (every planned sample
  can be terminal while the source is still producing). `register_eval` now
  copies its `sample_ids` argument so the state's planned-ids list grows only
  via `record_samples_added` (task_run mutates its own list for
  carry-forward).

## `enqueue_sample`

The imperative primitive (mirrors `enqueue_task`): `enqueue_sample(samples)`
adds samples to the running task from *arbitrary* code (a solver, a scorer, a
tool). Backed by a `ContextVar`-scoped `SampleEnqueuer` registered by
`task_run` for the task's lifetime — per-task, so concurrent tasks in one
process can't cross-enqueue. Unlike `enqueue_task` (which works on plain runs
as a follow-up batch), `enqueue_sample` **requires** the running task to be
SampleSource-driven: a plain task's fixed `tg_collect` path has no loop to run
additions, so the call raises a clear `RuntimeError` instead of silently
dropping samples.

## Interactions / known limits

- **`--limit`** caps the *total* number of samples (seed + produced): the seed
  is sliced as usual, and the dispatcher spends the remainder
  (`sample_limit_count(limit) - seed`) as its budget for added samples —
  additions beyond it are ignored with a warning, and once the budget is
  exhausted the loop finishes without consulting `next_samples()` again. A
  tuple limit's budget is the size of its slice (`stop - start`).
- **`--sample-id`** filters produced samples with the same
  normalise+`fnmatch` predicate that filters the seed (`sample_id_filter` in
  task/util.py). The seed of a SampleSource task is marked with
  `DATASET_SAMPLE_SOURCE_ATTR` so `slice_dataset` (log spec, sandbox startup,
  task_run) neither warns nor raises for requested ids missing from the seed —
  the source may produce them at runtime. Filtered-out samples still register
  their ids (duplicate ids stay a hard error) but don't run and don't grow the
  planned totals. As in `slice_dataset`, `--sample-id` and `--limit` are
  mutually exclusive (the filter wins).
- **Task retries** (`task_retry_attempts` / eval-set): the retry attempt
  re-drives the source; completed samples are reused via the normal
  `EvalSampleSource` lookup only where regenerated ids match — i.e. resume
  pays off for deterministic sources, the same determinism contract as
  `TaskSource` + eval_set (see task-source.md).
- **Early stopping** managers receive only the seed at `start_task`;
  `schedule_sample` / `complete_sample` still fire for injected samples.
- **The log's dataset spec stays seed-sized**: the finished log's
  `eval.dataset.samples` / `sample_ids` describe the seed, not the grown set
  (`log.samples` and `results.total_samples` do reflect everything that ran).
  Consumers that read the spec as the planned set therefore under-count for
  dynamic tasks — the analysis evals dataframe (`dataset_samples` /
  `dataset_sample_ids` columns and the completion denominator in
  `analysis/_dataframe/evals/table.py`) and crash recovery
  (`log/_recover/_api.py` computes `total = dataset.samples * epochs`). This
  is intentional, not an oversight: the seed-sized spec is load-bearing for
  retry reuse — `eval_log_sample_source` rejects a prior log when
  `eval.dataset.samples != len(dataset)`, and a retry's fresh seed is
  seed-sized — so the spec must not be rewritten to the grown size at finish.
- **Sandboxes**: the task-level sandbox startup pass runs once, up front, over
  the seed. Injected samples get per-sample sandboxes via `sandboxenv_context`
  as usual, but a *sample-level* sandbox spec appearing only on injected
  samples won't have had its task-level `task_init` startup pass.
- **Progress bar steps** (`profile.steps`) are fixed at seed size; the
  completed/total counter grows correctly (total passed on each update), and a
  zero-step seed no longer divides by zero (`RichProgress.update` guards it).

## Tests

`tests/test_sample_source.py` — generations under one task/log with auto-ids;
seed-only when `next_samples()` is `None`; `sample_complete` returning
follow-ups chains generations; `from_samples` (callbacks and seed-only); empty
seed; epochs applied to injected samples; explicit + auto id assignment and
duplicate-id error; live injection discriminated from batch-at-a-time (blocker
parks until an injected sample releases it, `fail_after` bounds a regression);
`enqueue_sample` rejected on plain tasks and outside a task; `--limit` caps
totals (budget spent, seed-consumed limit never consults the source, batch
truncation, samples-not-runs with epochs); `--sample-id` filters produced
samples and tolerates ids missing from the seed; samples enqueued during a
terminal `next_samples()` still run.
