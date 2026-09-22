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
    async def sample_abandoned(self, sample: Sample, epoch: int) -> list[Sample] | None: ...  # never-logged cancel
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
  It fires *after* the (shielded) completion block, so user callback code is
  never uncancellable; a sample cancelled individually by the operator is
  delivered (the task runs on, and a source waiting on it would otherwise
  stall), but a sample cancelled by the task's own unwind (abort/retry cancel,
  ^C) is not — the scope is cancelled and no follow-up could run.
- **`sample_abandoned()`** covers the cancels `sample_complete()` cannot: a
  run cancelled before anything reached the log, so there is no `EvalSample`
  to deliver. Three paths end that way (all return the scheduler's
  `DISCARDED` sentinel from `task_run_sample`): a queued-sample cancel
  (`ctl sample cancel --action cancel` on a parked run, discarded at its
  queue-exit check), a graceful task cancel (`drain` / `score` / `error`)
  abandoning a queued run at the same check, and an interrupt landing in an
  errored attempt's pre-retry drain window (the retry is suppressed and the
  attempt abandoned). `run_sample` fires the hook — for the `SampleSource`
  and the `TaskSource` alike — when `task_run_sample` returns `DISCARDED`,
  delivering a copy of the dataset `Sample` plus the epoch, and routes any
  returned samples onto the enqueuer like `sample_complete`'s. The delivery
  rule is `sample_complete`'s: not while the task is unwinding
  (`abort`/`retry` stamp), where no follow-up could run; and additionally
  not for a requeue re-run, whose withdrawn/abandoned run leaves the prior,
  already-reported terminal outcome standing. A separate hook was chosen
  over synthesizing an `EvalSample` with a cancellation `error`: the source
  would otherwise be handed a record that exists nowhere in the log and
  cannot be distinguished from a logged operator cancel. Because the hook
  runs *after* the run's terminal count (unlike `sample_complete`, which
  precedes it), the last sample's count can land while the source is still
  being told — so a `TaskSource`-driven eval also registers as `dynamic`
  (its `completed_at` is stamped by `finalize_eval`, as a `SampleSource`
  task's already is), keeping `ctl task cancel` effective while a callback
  is suspended rather than reading the task as finished. Timing: a
  queued-sample cancel is *counted* at accept but the parked coroutine
  discards only when it next acquires a slot, so the notification arrives
  when the sample would otherwise have started — an orchestrator waiting on
  a rollout it enqueued therefore needs spare sample capacity, exactly as it
  would for the rollout to run at all.

`SampleSource.from_samples(initial_samples, *, next_samples=None,
sample_complete=None, sample_abandoned=None)` builds a source from a seed +
callbacks without subclassing (mirrors `TaskSource.from_tasks`).

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
  via `record_samples_added` ([eval_state.py](../src/inspect_ai/_control/eval_state.py)).
  The eval registers as `dynamic`, which suppresses the provisional
  `completed_at` stamp entirely — every planned sample can be terminal while
  the source is still producing (or the seed can be empty, `total == 0`), and
  a stamped `completed_at` would make `ctl task cancel` no-op and listings
  read "completed" while the task idles in `next_samples()`; only
  `finalize_eval` (the task's true finish point) clears the flag and stamps.
  `register_eval` also copies its `sample_ids` argument so the state's
  planned-ids list grows only via `record_samples_added` (task_run mutates
  its own list for carry-forward).

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
  *range* limit (`start,end`) is rejected with a `PrerequisiteError`: it
  selects seed samples by position, and added samples have no position, so
  there is no coherent way to apply it (it would select nothing from a short
  seed while still admitting `stop - start` additions).
- **`fail_on_error`**: a fractional threshold is *deferred* to the end-of-run
  check for SampleSource tasks (`SampleErrorHandler(defer_fractional=True)`) —
  the planned total grows while the task runs, so a mid-run check would
  measure early errors against a transiently small denominator (a 1-sample
  seed erroring first would trip `1 >= 0.5*1` before the source produced the
  rest). Absolute-count and any-error thresholds still abort mid-run.
- **`--sample-id`** filters produced samples with the same
  normalise+`fnmatch` predicate that filters the seed (`sample_id_filter` in
  task/util.py). Callers that hold the task pass `dynamic=True` to
  `slice_dataset` (log spec, sandbox startup, task_run) so it neither warns
  nor raises for requested ids missing from the seed — the source may produce
  them at runtime. Filtered-out samples still register their ids (duplicate
  ids stay a hard error) but don't run and don't grow the planned totals. As
  in `slice_dataset`, `--sample-id` and `--limit` are mutually exclusive (the
  filter wins).
- **Task retries** (`task_retry_attempts` / eval-set): the retry attempt
  re-drives the *same source instance* (the retry rebuilds `TaskRunOptions`
  around the same `Task`); completed samples are reused via the normal
  `EvalSampleSource` lookup, and the reuse path re-fires
  `sample_feed.sample_complete` for each reused sample so a completion-driven
  source regenerates its follow-ups (which are then themselves reused where
  regenerated ids match). A source that instead holds internal
  `next_samples()` state resumes mid-state on retry — it must be resumable
  (or derive its follow-ups from `sample_complete`) for retries to
  reconstruct the run; this is the same determinism contract as `TaskSource`
  + eval_set (see task-source.md).
- **Early stopping** is rejected (`PrerequisiteError`): managers register a
  fixed sample set at `start_task` (added samples would never be registered),
  and samples a manager halts complete without notifying the source, which
  would hang a source blocked awaiting completions.
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
- **Sandboxes**: the task-level sandbox startup pass runs up front over the
  seed, and *incrementally* for samples the source adds: each added batch goes
  through `SandboxManager.start_for_samples` (threaded into the dispatcher as
  `TaskRunOptions.startup_sandboxes`) before spawning, so a sandbox config
  first seen in an added sample — including the task-level config when the
  seed is empty — still gets `task_init` (image build/pull, validation) and a
  registered `task_cleanup`. Already-started configs are a set-membership
  no-op. Per-sample sandboxes then run via `sandboxenv_context` as usual.
- **Provider state a late `task_init` registers is owned by the batch, not
  the feeder.** `start_for_samples` runs inside the feeder task, which
  `SampleScheduler.run` starts as a *sibling* of the sample tasks; the
  run-level `task_cleanup` runs in `eval_run`'s own context. A `ContextVar`
  a provider *binds* in `task_init` on this path is therefore visible to
  nobody else — not the samples, not the cleanup (the Docker provider's
  registries of running projects and generated compose files used to be
  bound this way, so an empty-seed `sandbox="docker"` task failed every
  sample with a `LookupError`, and files registered by the feeder were never
  removed). The fix is explicit ownership rather than a default on the
  variable: `SandboxManager.open()` binds a fresh
  `SandboxLifecycleState` (`util/_sandbox/lifecycle.py`) in `eval_run`'s
  context before any task of the batch is spawned — even when no initial
  sample has a sandbox — and `SandboxManager.shutdown()` runs the
  accumulated cleanups and then releases it. Every task of the batch
  inherits a reference to the same object, so provider hooks (`task_init`,
  `sample_init`, `sample_cleanup`, `task_cleanup`) *mutate* the state they
  inherit and never rebind or clear it: a second config's `task_init` keeps
  the first's registrations, a `task_init` that fails releases only a
  startup file it alone registered — a legacy `.compose.yaml` or a reused
  auto-compose path that an earlier initialization or a live sample already
  registered is kept, since their `compose` commands still name it (the
  batch's live samples and its final cleanup are untouched either way) —
  and `task_cleanup` releases the entries it
  processes so repeat calls (one per started config) are no-ops. Because the
  scope is per `eval_run`, sequential `TaskSource` batches (which reuse the
  outer task) and independent evaluations in one process each start from an
  empty registry; a process-wide mutable default would instead have carried
  one batch's projects into the next batch's cleanup or "not yet cleaned up"
  report. Outside any scope (the provider driven directly, without a
  `SandboxManager`) a registry belongs to the task whose `task_init` bound it,
  for one lifecycle: a `task_init` in another task (a child that inherited
  the binding) or after that registry's `task_cleanup` binds its own, so
  concurrent or successive direct lifecycles never share cleanup state,
  while reads (`sample_init`, `task_cleanup`) use whatever registry the
  context holds, so a direct lifecycle may still spread over a task and its
  children.
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

`tests/util/sandbox/test_docker_cleanup.py` — the Docker provider's cleanup
registry under batch ownership, with the daemon stubbed at the compose-command
layer and compose files generated and removed for real: `task_init` in a
feeder task and `sample_init` in a sibling share the scope's registry for
every config family (bare Docker, Dockerfile, `ComposeConfig`, explicit
compose file preserved, legacy `.compose.yaml` removed); shutdown cleans or
reports (`sandbox_cleanup=False`) an interrupted sample and releases every
entry; a second config's `task_init` keeps the first's startup file; a failed
`task_init` releases only its own file and leaves live samples and the final
cleanup alone, and a failed or cancelled re-initialization of a shared legacy
or reused auto-compose path keeps that file; direct provider use without a
scope, including two overlapping child-task lifecycles after a parent's; and,
through `eval_async`
(asyncio and trio): the first Docker sample arriving via `next_samples`,
`enqueue_sample` or a `sample_complete` return; a late config alongside the
seed's; a late config failing while the seed sample is live; two sequential
`TaskSource` batches with a cancel in the second; two independent evaluations
(the first retaining its container). One real-Docker test runs the empty-seed
dynamic evaluation.
