# Pause / Resume for Running Evals and Eval-Sets

> **Status: implemented** (v1 quiesce semantics — the gate module lives in `src/inspect_ai/_control/pause.py`; Future work below remains open). Companion to [`control-channel.md`](control-channel.md), which owns the control-channel architecture this surface rides on; this doc owns the pause/resume semantics and implementation plan. Originating issue: meridianlabs-ai/inspect_ai#90.

`inspect ctl` can today observe a running eval, retune its config, and cancel it — but there is nothing between "running" and "cancelled". An operator (or watchdog agent) facing a provider incident, a cost overrun, or a suspicious-looking transcript has exactly two levers: throttle (`ctl config`) or kill (`ctl task cancel`). Killing forfeits the run's place in line — resuming means a fresh `eval-set` invocation, a new process, and re-running every sample that wasn't durably complete.

This design adds the missing state: **pause** stops a running eval from starting new work while keeping the process, its queue, and its control surface alive; **resume** picks up exactly where it left off. Pausing is non-destructive, idempotent, and reversible — the properties cancel structurally cannot have.

## Scenarios

- **Provider incident.** The model API starts returning elevated error rates. Today the choices are "let the retry loop grind" (burning the retry budget and money) or cancel. With pause: `inspect ctl process pause`, wait out the incident (watching with the read surface, which stays live), `inspect ctl process resume`. Nothing is lost; no relaunch.
- **Cost / budget control.** An eval-set is spending faster than expected. Pause it, get the budget conversation had, resume — or decide to cancel with full information. A paused-and-quiesced run spends nothing.
- **Yield shared capacity.** A long low-priority eval-set is saturating the org's rate limit and an urgent eval needs to run. Pause the big one, run the urgent one, resume. (`ctl config --max-connections` can throttle, but can't reach zero; pause can.)
- **Investigate before deciding.** A watchdog (or human) spots policy-violating-looking behavior in a transcript. Pause the task, read `sample events` at leisure (the control server keeps answering), cancel the offending samples or the whole task — or conclude it's fine and resume. Pause buys time to decide without the decision being forced by the run's momentum.
- **Pause across a process restart.** Machine maintenance, spot-instance reclaim. Pause, wait for quiesce (all in-flight samples finished and flushed), kill the process; later, re-invoke `inspect eval-set` on the same `log_dir` — the existing run-vs-reuse logic re-runs only what didn't complete. Pause's job here is to make the kill point *clean* (nothing in flight, everything flushed); the resume half already exists.

The consumers are the control channel's usual two: humans at a shell, and LLM/scripted agents driving eval workflows (the watchdog scenario in `control-channel.md` scenario 2 — "back off when API errors spike" — wants pause as its strongest backoff).

## What "pause" means (and what it deliberately doesn't)

Three candidate semantics, in increasing order of invasiveness:

1. **Quiesce (chosen).** Stop *starting* work: no new samples leave the queue, no new task attempts start, no new eval-set tasks dispatch. In-flight samples run to natural completion. The process, its event loop, and the control server stay up. Once in-flight work drains, the run is fully idle — zero model calls, zero sandbox churn — but resumable in O(1).
2. **Suspend in-flight samples.** Additionally freeze samples mid-execution. Rejected for v1: a sample's wall-clock `time_limit` is a fixed `anyio.move_on_after` deadline baked into its cancel scope at start (`_TimeLimit`, `src/inspect_ai/util/_limit.py`) — a paused sample would keep burning its budget, or the limit machinery needs rework; an in-flight model API call, batch wait, or tool subprocess cannot be meaningfully frozen from outside; and sandboxes keep running (and billing) regardless. "Frozen but leaking time, money, and API state" is a worse promise than "finishing what it started". A checkpoint-based interrupt-and-requeue variant is sketched under Future work.
3. **Process-level freeze (SIGSTOP).** Rejected outright: it freezes the control server too (so `resume` can't be delivered over the channel), drops in-flight HTTP connections into server-side timeouts, and leaves sandbox containers running with a dead supervisor. See Alternatives.

So **paused = the run stops consuming from its queues** — the sample queue (samples parked at the sample semaphore), the retry queue (a task attempt waiting to re-run), and the task queue (eval-set tasks not yet started). Everything already in flight completes normally, including scoring and log writes. This is deliberately the same "stop dispatching" machinery that the planned `task drain` and the deferred graceful-drain cancel variant need (`control-channel.md` phase 3 notes both as blocked on it) — pause builds that machinery and makes it reversible; drain becomes "pause + let the task finish with what it has" and can land as a thin follow-on.

**Timing is free by construction.** The pause gate sits at the queue-exit boundary in `task_run_sample` (`src/inspect_ai/_eval/task/run.py`) — before sample materialization, sandbox creation, and the point where the sample's clocks start (`start_time` / `init_sample_working_time`, after the semaphore). A sample held at the gate has spent none of its `time_limit` or `working_limit`; a sample past the gate finishes normally under its original limits. No limit-machinery changes are needed for v1.

## CLI surface

Two scopes, following the noun groups and selector conventions of `control-channel.md`:

```
inspect ctl task pause TASK [--dry-run]      # pause one task (sample dispatch + its retries)
inspect ctl task resume TASK [--dry-run]     # resume it
inspect ctl process pause [PID] [--dry-run]  # pause the whole run: every task + the eval-set task/retry scheduler
inspect ctl process resume [PID] [--dry-run] # resume the whole run
```

- **`task pause` / `task resume`** take the standard task selector (task-id prefix or name). `TASK` follows the mutation selector rule — sole running task is the default; several running tasks require an explicit selector. Pause is non-destructive and trivially reversible, so it does *not* join `task cancel` in the selector-always-required class (the same reasoning that gives `process keep` / `release` the sole-target default: the worst case of a wrongly targeted pause is a resume).
- **`process pause` / `process resume`** answer the eval-set question. An eval-set is one process (single `eval()` call under the default `retry_immediate=True`), so "pause the eval-set" is a process-scoped intent: no new tasks start, no task retries start, and no samples dispatch in any task. This is not a fan-out over task pauses (which the CLI conventions reject) — it is one process-scoped latch, like keep-alive, that all dispatch points check. When the `ctl eval-set` noun group eventually lands, an `eval-set pause` spelling can alias to this; the semantics are already right.
- Task-level and process-level pause are **independent latches**: a sample dispatches only when both its task's gate and the process latch are open. `process resume` does not clear task-level pauses (and vice versa) — resuming the run after an incident should not silently un-pause a task an operator paused for its own reasons. The task-list output labels which latch holds a paused task.
- Both verbs are idempotent (pausing a paused or finished task reports `changed: false`), last-write-wins (pause → resume → pause holds), and `--dry-run`-able, per the phase-3 directive conventions. All carry `--json` with the uniform mutation envelope (`{target, applied, dry_run, detail}`).

Naming: `pause` / `resume` over `suspend` / `stop` / `hold`. `resume` is the natural inverse and reads correctly in both scopes; `stop` collides with cancel semantics; `suspend` implies the in-flight freezing this design rejects. One caution documented in help text: `process resume` resumes a *paused* run; `process release` releases a *keep-alive park* — different states, and a paused run is not parked (its eval body hasn't returned).

## HTTP endpoints

Per the "three scopes, three roots" URL rule:

| Operation | Endpoint |
|---|---|
| Pause / resume a task | `POST /tasks/<task-id>/pause`, `POST /tasks/<task-id>/resume` |
| Pause / resume the process (run) | `POST /pause`, `POST /resume` |

- All accept `?dry_run=true` and return `changed` for the idempotent no-op, matching the cancel directives.
- Task-keyed (not attempt-keyed), like `config` / `log-flush` / `cancel`: a pause handle must not dangle across a retry.
- **No `CONTROL_API_VERSION` bump.** New *routes* fail loudly against an older server (stock `{"detail": "Not Found"}` 404), so the CLI passes `not_found_missing_route` and reports "older inspect — restart the eval", exactly the cancel-verbs precedent.
- **Read-surface additions.** `GET /tasks` rows gain `paused` (`null` | `"task"` | `"process"` | `"both"` — which latch holds) and `quiesced` (paused **and** zero in-flight samples — the "safe to kill" signal for the durable-pause scenario). Purely additive response fields the CLI null-guards: no version bump, per conventions. `ctl task list` renders a paused marker in the human table so a paused run doesn't read as stalled; `ctl process list` reports the process latch.

## Semantics in detail

- **In-flight samples** run to completion — solving, scoring, log write — under their original limits. Pause never preempts (the same drain-don't-kill principle as every shipped config knob).
- **Queued samples** hold at the gate, unstarted: no sandbox, no clocks running, status still `pending`/`queued` in `sample list`. They are exactly as resumable as they were before the pause.
- **Task retries.** A task whose last attempt errored and has an in-run retry queued (`retry_immediate=True`, the `run_task_retry_attempts` loop in `_eval/run.py`) does not start the retry attempt while its task gate or the process latch is closed. This also softens an existing wart: `task cancel` currently rejects a between-attempts task with a 409 ("re-issue once the retry starts"); a paused task's retry is parked at a well-defined point, making the between-attempts window inspectable instead of a race.
- **Eval-set task dispatch.** Under the process latch, the scheduler does not start not-yet-started tasks (and, once `run_single` is retired per the add-task plan, "the scheduler" is uniformly the `run_multiple` worker pool — workers check the latch before dequeuing). A task injected via the planned `ctl task add` while paused registers normally and simply holds at dispatch, no special case.
- **Cancel escalates over pause.** `task cancel` / `sample cancel` work unchanged on a paused task — pause must never make teardown harder. A graceful cancel (`--action score|error`) of a paused task resolves in-flight samples as usual and abandons queued ones; the gate doesn't hold terminal transitions, only starts.
- **Config retunes compose.** `ctl config` against a paused task works (retune `max_samples` while paused; the new value applies on resume). Lowering `--max-connections` to ride out an incident and pausing are independent levers.
- **Keep-alive interplay.** A paused eval never finishes, so the keep-alive park is not involved; `process release` on a paused process means "exit when done" as always — which, while paused, is never. The task-list footer should flag a paused process with a pending release so the contradiction is visible.
- **Log/flush behavior.** Completed samples flush per the normal buffer policy while draining. **On quiesce** (last in-flight sample of a paused task completes), the task auto-flushes its buffered samples (the `log-flush` machinery) — so a quiesced pause is durable by default: everything completed is in the log, and killing the process at that point loses nothing that a later `eval-set` re-invocation (or crash recovery via the buffer DB) can't account for.
- **What pause does not stop:** the control server (that's the point), transcript event buffering for in-flight samples, and wall-clock time limits of *in-flight* samples (they're running; their deadlines stand). It also doesn't release semaphore-external resources an in-flight sample holds (sandboxes, subprocesses) until that sample finishes.
- **Legacy `retry_immediate=False`.** Between tenacity attempts there is no control server (documented limitation), so a process-level pause can't be *delivered* in that window, and per-run registries reset across the per-attempt `eval()` calls, so a pause does not survive into the next batch attempt. Documented as unsupported in that mode (task-level pause still works within an attempt), mirroring the keep-alive limitation rather than inventing new machinery for a legacy path.
- **Crash/restart honesty.** Pause state is in-memory only (like every other control-channel intent). If the process dies while paused, the run is simply an interrupted run: `status="started"` log, buffer-DB recovery, eval-set re-run of the incomplete remainder. Pause is not a durable flag — durability comes from quiesce + the existing resume machinery, not from persisting "paused" anywhere.

## Resuming across process boundaries (the second half of the issue)

"Resume an eval-set" has a second reading: the process is *gone* (finished with failures, crashed, or killed while paused) and the operator wants to continue it. That machinery **already exists** and this design deliberately builds on rather than duplicates it:

- `inspect eval-set` re-invoked on the same `log_dir` re-runs only tasks without a complete success log (`list_latest_eval_logs` / `log_samples_complete` in `src/inspect_ai/_eval/evalset.py`) — cancelled, errored, and crashed (`started`) logs are all retry seeds.
- Within a re-run task, `eval_log_sample_source` (`_eval/task/run.py`) reuses every prior sample with `error is None` verbatim, resumes checkpointed samples, and re-runs the rest; crashed logs get buffer-DB recovery first (`design/recover.md`).
- `inspect eval-retry` does the same for a standalone eval log.

So the cross-process resume command already has a spelling: *run the same `eval-set` again*. What this design adds to that story is (a) a **clean pause point** — quiesce + auto-flush means the kill loses zero completed work, where killing a busy run today abandons whatever the buffer hadn't flushed to in-flight-cancelled status — and (b) **visibility** (`quiesced` in `task list`) so the operator/agent knows when the kill is safe. A dedicated `inspect eval-set --resume` alias is out of scope: it would be a second name for the existing idempotent invocation.

## Implementation sketch

- **Gate primitive.** A small re-armable async gate (`anyio.Condition`-based — `anyio.Event` can't re-arm, and pause/resume is last-write-wins; precedent: the keep-alive `_park_cond` in `_control/server.py`). `await gate.wait_open()` parks while closed; `open()` / `close()` flip it and notify waiters.
- **Task gates live in a task-id-keyed process-global registry**, parallel to the sample-semaphore registry (`task_sample_semaphore` in `src/inspect_ai/util/_concurrency.py`) and reset at the same run boundary — so a pause survives in-run retry attempts of the same task, matching how a `max_samples` retune survives them. The **process latch** is one module-level gate, reset at the outermost run boundary like the keep-alive intent.
- **Dispatch hooks** (all on the eval's single loop, so no cross-thread concerns):
  1. `task_run_sample`: await both gates at the queue-exit boundary — before the sample-semaphore acquire (so held samples don't pin limiter slots), with a re-check after acquire (a pause landing while a coroutine was already blocked on the semaphore must not leak a start: on re-check failure, release the slot and re-await the gate). This is the same boundary the graceful-cancel `cancel_type` check occupies.
  2. `run_task_retry_attempts` (`_eval/run.py`): await the gates before starting a retry attempt.
  3. The task scheduler's worker dequeue: await the process latch before picking up the next task.
- **Routes** (`_control/server.py`) resolve the target via `latest_eval_for_task` exactly like cancel, flip the gate, and report `changed`. `EvalState` needs no new mutable state — the server reads pause state from the gate registry the same way `limits.py` reads the semaphore registry; `GET /tasks` derives `paused` / `quiesced` from it plus the existing in-flight sample count.
- **Quiesce auto-flush**: when a paused task's in-flight count reaches zero, invoke the existing on-demand flush (`TaskLogger` flush path, already serialized by its lock).
- **Display**: the task display shows a `paused` badge on affected tasks (nice-to-have; the ctl read surface is the primary reporting path).

Estimated blast radius: one new module for the gate + registry, ~4 hook sites in `_eval/task/run.py` and `_eval/run.py` (retry loop / scheduler), two route pairs in `_control/server.py`, CLI verbs in `_cli/ctl.py`, and the `GET /tasks` row fields.

## Alternatives considered

- **`SIGSTOP` / OS-level suspend.** Freezes the control server (resume can't arrive over the channel), breaks in-flight model API connections (server-side timeouts fire while the client is frozen, then surface as errors on `SIGCONT`), leaves sandbox containers running unsupervised, and is invisible to the read surface (the process just stops answering — indistinguishable from wedged). Also per-process only: can't pause one task of an eval-set.
- **`ctl config --max-samples 0`.** The resizable-limiter floor is 1 by design (`ResizableLimiter` rejects 0), and even at 0 it would only gate the sample semaphore — not task retries or eval-set task dispatch. More fundamentally, a limit of 0 is a *lie* about intent: pause is a state, not a setpoint, and it should be reported, escalated over, and reasoned about as one (an agent reading `max_samples: 0` can't tell a pause from a typo). Same reason `keep` isn't spelled as a config knob.
- **Cancel now, resume later via eval-set.** Works today and remains the durable path — but it forfeits in-flight work (or force-resolves it via `--action score`), tears down the process (losing the warm state: sandboxes being pulled, adaptive-concurrency learning, the control surface itself), and makes resume a relaunch with startup cost. Pause is strictly cheaper for anything short of "we're done with this machine".
- **A drain-only verb (no resume).** `task drain` is already planned and remains so — but drain answers "finish with what you have", not "wait, then continue". Building pause first gets drain nearly free (drain ≈ pause + resolve the task when in-flight completes); building drain first would leave the resume half — the actual ask of this issue — unbuilt.
- **Persisting pause state to disk** (so a restarted process comes back paused). Rejected: a restarted process is a *new run* whose operator explicitly invoked it; arriving paused would be astonishing. Durability is delegated to the log/recovery layer, where it already lives.

## Future work

- **`task drain`** as a thin composition over the pause gate (stop dispatch + auto-resolve the task at quiesce instead of holding).
- **Hard pause (interrupt-and-requeue).** `pause --now`: interrupt in-flight samples as `cancelled` and requeue them so resume re-runs them (losing in-sample progress except for checkpointed solvers, which `_resume_if_checkpointed` can pick up). Needs `sample requeue` (planned) and a decision on whether interrupted attempts count against `retry_on_error` budgets. Wait for a concrete need — quiesce covers the known scenarios.
- **Pause-aware limits for a hard pause**: making `time_limit` deadline-shifting and recording paused spans as waiting time (`record_waiting_time`) — only needed if samples can ever be held mid-flight.
- **Auto-resume / pause timeout.** A paused-and-forgotten run lingers forever (same failure mode as a forgotten keep-alive park). A `--for DURATION` or watchdog-side timer could bound it; not v1.
- **`ctl eval-set pause`** spelling once the eval-set noun group exists (semantics unchanged — aliases the process latch).

## Resolved questions

Decided for v1 (revisit only if usage argues otherwise):

1. **`process pause` does not gate the batcher.** In-flight *batched* generate calls await provider batches for minutes-to-hours; quiesce semantics say let them finish (consistent with the batch exemptions in the retry-override knobs). A paused run can therefore take hours to quiesce — accept and report (the in-flight count makes it visible); an operator who can't wait has cancel.
2. **Pause gates only the attempt start, not `retry_wait`-style backoff clocks.** Backoff timers keep running while paused; the attempt begins when both the backoff has elapsed *and* the gate is open.
3. **No notification shape for `quiesced`** — polling `task list` suffices for the pause-then-kill workflow. Phase-4 push could carry it later if polling proves inadequate.
4. **Permission asymmetry for agents is a docs note, not machinery.** Pause is reversible, so a Bash-allowlist policy might want to allow `ctl task pause*`/`resume*` while gating `cancel`. Add a line to the agent-workflow docs once shipped.
