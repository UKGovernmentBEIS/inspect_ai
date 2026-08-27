# Resolving Stalled Samples

Part of the push-button eval pipeline effort ([ctl/control-channel.md](ctl/control-channel.md), [recover.md](recover.md)). Complex agentic evals often "end" with a handful of hung or interminable samples — 7 or 8 out of hundreds — and until recently there was no way to bring such a run to a terminal, completed state without manual surgery. This doc covers the last mile: **ending stalled samples with a chosen disposition and guaranteeing the eval reaches `status == "success"`**.

The operating assumption throughout is that **an LLM agent is watching the eval** and can act through `inspect ctl` — the control-channel headline scenario. A human at the CLI drives the identical commands; a configured in-process policy (Piece B) is the fallback for runs nobody watches, not the primary design.

> **Status: partially shipped.** The live-process surface — detection, diagnosis, unsticking, resolution with dispositions, and second chances via `inspect ctl` (Piece C) — is implemented on `main`. The post-mortem half — recovery dispositions and finalization after a SIGKILL (Piece A) — and the in-process stall policy (Piece B) remain proposals. Piece A is the one gap the watching agent cannot cleanly work around today; see "What the agent still cannot do".

## Problem

Two distinct failure shapes leave an eval permanently un-terminal:

1. **Stalled samples in a live process.** The event loop is healthy, but a few samples are wedged — a sandbox exec that never returns, an agent loop cycling without progress, a model call stuck behind an interminable retry. Per-sample `time_limit` / `working_limit` can bound these, but for long-horizon agentic tasks a tight absolute budget punishes legitimate slow samples; operators instead leave limits loose. **This shape is now handled**: the watching agent detects the stall, diagnoses it, and resolves it through `ctl` (see the playbook below).

2. **A wedged process.** The event loop itself is stuck (blocking sync call, deadlock) and the only remedy is SIGKILL. After the kill, `inspect log recover` reconstructs the log — but it marks in-progress samples as cancelled *errors* and writes `status="error"` ([recover.md](recover.md)). A subsequent `eval-retry` / `eval_set` re-runs exactly those samples, which hang again. The pipeline loops; the log never reaches `"success"`. **This shape remains open** — it is Piece A.

The goal, in JJ's words: if the process is completely hung we SIGKILL it, run recovery, mark all incomplete samples appropriately, and set the eval to completed — the last mile in a robust push-button eval pipeline.

## What exists today

| Mechanism | Where | What it does |
|---|---|---|
| `ctl sample list` | shipped | Idle column (working-but-eventless recency) identifies stragglers; status histogram (`counts`) covers all samples even when the listing is capped; a long-idle listing prints a stall-escalation footer pointing at `process anomalies` |
| `ctl process anomalies [PID]` | shipped | Reconstructs in-flight actions (model call, sandbox exec — entered, never exited, with live durations) from the pid's *trace file*, so it works against a busy or hung process, and even post-mortem after a kill |
| `ctl sample show / events / messages / store`, `ctl sample errors` | shipped | Per-sample diagnosis: transcript tail, pending tool calls, store state, errored-sample triage across the whole process |
| `ctl sample cancel TASK SID EPOCH --action score\|error\|cancel` | shipped (default `score`) | Interrupts one running sample via `ActiveSample.interrupt`: `score` ends it with `EvalSampleLimit(type="operator")` and scores work-so-far; `error` marks it errored; `cancel` records it cancelled (no scoring, not counted as an error). Idempotent, dry-runnable |
| `ctl task cancel TASK --action cancel\|score\|error` | shipped (default `cancel`) | `cancel` aborts (log finalized `status="error"`, eval-set does not retry). `score`/`error` resolve gracefully: in-flight samples interrupted with the matching action, queued samples abandoned, and the task runs to *natural completion* with its ordinary terminal status — one command resolves the whole stalled tail |
| `ctl sample cancel-tool-call` | shipped | Surgical unstick: cancels one hung in-flight tool call so the model sees an ordinary tool timeout and the sample *continues* rather than ending |
| `ctl sample requeue TASK [SID EPOCH ...] \| --errored` | shipped | Second chance without leaving the process: re-queues errored/cancelled samples under the task's normal machinery (error history seeded, checkpointed samples resume from checkpoint) |
| `ctl config [TASK] --time-limit / --token-limit / --message-limit` | shipped | Mid-flight retune of per-sample limits (was "later" in early drafts of this doc) — tighten the budget on a loose-limited run instead of hand-resolving each straggler |
| `ctl task score [--completed-only]` | shipped | Interim metrics over work-so-far — tells the agent whether the tail it is about to abandon matters |
| `ctl task log-flush` | shipped | Flush buffered samples to the `.eval` file — the pre-kill mitigation when the process is still responsive |
| `ctl task pause/resume`, `ctl process pause/resume`, `process keep/release` | shipped | Freeze a run while investigating; keep a finished process's control surface alive |
| `--json` everywhere + structured error envelopes | shipped | Success envelopes carry what changed; failures carry `kind` (`busy` = alive but starved, `connect_error` = process likely gone, ...) — how an agent distinguishes a slow process from a dead one |
| `inspect eval / eval-set --json`, `--detach` | shipped | Launch records (`run_id` / `pid` / control socket) emitted only after the control server binds — the agent's handle on the process it will watch |
| `time_limit` / `working_limit` | shipped (pre-existing) | Absolute per-sample budgets; graceful end (sample gets `limit`, is scored). Absolute — can't distinguish "slow but progressing" from "hung" |
| `fail_on_error` | shipped (pre-existing) | `False` / count / proportion thresholds let an eval finish `"success"` despite sample errors. Only helps samples that *end* |
| `inspect log recover` (`log/_recover/`) | shipped ([recover.md](recover.md)) | Reconstructs crashed logs from the sample buffer DB. **Gap:** in-progress samples become cancelled errors, header stays `status="error"`, and the recovered log always re-enters the retry loop — no dispositions, no finalization (Piece A) |
| Automatic recovery in `eval_retry` / `eval_set` | shipped (`_eval/eval.py`, `_eval/evalset.py`) | Opportunistically recovers crashed logs before retry so completed-but-unflushed samples are reused. Same gap — hung in-progress samples re-run every attempt |
| Eval-set completeness | `evalset.py:log_samples_complete` | Complete ⇔ `status == "success"` ∧ not invalidated ∧ `results.total_samples >= dataset × epochs` — the target state Piece A must produce post-mortem |

## The watching agent's playbook (shipped)

The disposition vocabulary — **resolving** a sample by administratively ending it with `score` (end as-is, `limit = operator`, score current state; retry reuses it), `error` (end with an `EvalError`; a later retry re-runs it), or `cancel` (transcript preserved, no scoring, not an error for `fail_on_error` purposes; a later retry re-runs it) — is live on the `ctl` cancel commands. The healthy-process loop, end to end:

1. **Detect.** `ctl sample list --json` — the idle metric (working-but-eventless time; retry backoff does not accrue) flags stragglers. A `busy` error envelope on repeated reads is itself a signal: the process is alive but starved.
2. **Diagnose.** `ctl sample events` / `messages` / `show` say what the sample was doing; `ctl process anomalies` reads the trace file (no cooperation from the process needed) and names the single in-flight operation — model call vs sandbox exec — that a transcript-quiet sample is blocked on. This distinguishes hung from slow-but-healthy, which no idle threshold alone can.
3. **Unstick without ending.** Often the right move is not to give up on the sample: `ctl sample cancel-tool-call` times out one hung tool call and lets the sample continue; `ctl config TASK --time-limit ...` retunes loose limits so the run's own machinery bounds the tail.
4. **Resolve.** `ctl sample cancel <task> <sid> <epoch>` (disposition `score` by default) for one straggler; `ctl task cancel <task> --action score` for the whole tail at once — in-flight samples resolved, queued samples abandoned, task runs to natural completion. `--dry-run` first; every mutation is idempotent, so an agent retrying on confusion is safe. Note `--action error` is rejected (409) when samples are configured to fail on errors — the auto-fail would race it; use `score` or `cancel` there.
5. **Second chances.** A sample resolved as `error`/`cancel` (or errored on its own) can be given another attempt *inside the live run* with `ctl sample requeue` — prior error history seeded, checkpoint resume where available. "Stalled once" no longer forces the choice between abandoning and a whole `eval-retry` cycle.
6. **Complete.** When the tail is resolved, the eval finishes normally — log status `"success"` (subject to `fail_on_error` if `error` dispositions were used), no recovery involved. A graceful task-level resolution is never retried by the in-run retry loop (`_eval/run.py`, "a user cancel like abort"). Queued samples abandoned by a task-level resolution are *absent from the log* — genuinely retryable work a later `eval_set` invocation may re-run (completed and resolved samples are reused) — but in the tail scenario the queue is empty and the log satisfies the completeness predicate outright.

And when the process itself is wedged:

```
inspect ctl task log-flush <task>        # if the control channel still answers — minimize recovery surface
kill -9 <pid>
inspect ctl process anomalies <pid>      # still works: trace file survives the kill; says what each sample was stuck on
inspect log recover <log>
inspect eval-retry ... / eval_set re-run
```

Everything up to `log recover` is in place — including post-mortem diagnosis. The recovery step is where the story currently ends: the recovered log is `status="error"` with the hung samples marked as retryable cancelled errors, and the retry re-runs them.

## What the agent still cannot do

The answer to "is anything still missing for the agent to bring an eval to the desired terminal state":

1. **Finalize after a SIGKILL (Piece A — the real gap).** There is no way to express a disposition at recovery time. `recover_eval_log` (`log/_recover/_api.py`) takes no `incomplete_action` / `incomplete_max`; recovered in-progress samples always become cancelled errors; the header is always `status="error"`; `eval-retry` / `eval_set` then re-run the hung samples. The agent's only workaround is indirect: let the retry re-run the stalled samples, wait for them to wedge *again*, and race to `ctl task cancel --action score` while the new process is still responsive. That works only when the re-run stays healthy enough to accept the directive — a sample that wedges the event loop itself on every attempt can never be resolved, and the pipeline loops forever. Piece A closes this.
2. **Post-mortem scoring.** Live, `--action score` is reliable (sandbox still up). After a kill there is no shipped path to score reconstructed work-so-far at all — part of Piece A (`incomplete_action="score"`), with checkpoint-resume-for-scoring as the strong variant for checkpointed tasks.
3. **Distinguish resolutions in analysis.** Everything the agent resolves today stamps `EvalSampleLimit(type="operator")` — accurate for agent-driven action, but recovery-resolved samples (Piece A) need a `"recovery"` limit type, and a future in-process policy (Piece B) a `"stall"` type; neither literal exists yet in `EvalSampleLimitType` (`log/_log.py`).
4. **Cross-execution stall memory.** Nothing records "this sample already stalled once" across attempts, so a policy like "requeue on first stall, resolve on second" lives entirely in the agent's own memory/context. Retries do seed per-sample error history (`error_retries`), so this is buildable — open question below.
5. **Unwatched runs.** Everything above presumes the agent is present. A run nobody watches still has no in-process stall detection (Piece B) — with a watching agent this is defense-in-depth rather than a requirement, which is why B is demoted below.

Item 1 is the only one that blocks the push-button goal outright; 2 and 3 ride along with its implementation.

## Piece A: dispositions in recovery (proposed)

### Semantics

`recover_eval_log()` gains a disposition for in-progress samples. The unifying rule for the header:

> A resolved sample is **final**. When every expected sample in the recovered log is final (flushed-complete, buffer-complete, or resolved), the recovered log is finalized with `status="success"` and full results/stats — it satisfies the eval-set completeness predicate and nothing will retry it. If expected samples are *missing* entirely (never started, or lost between flush and crash), the log keeps `status="error"` and the missing samples remain retryable.

So there is no separate `--complete` flag to hold wrong: choosing a resolving disposition *is* the request to finalize, and finalization happens exactly when it's true that nothing is left to run. (JJ's "completed" status = Inspect's `"success"` literal — `EvalStatus` has no separate "completed" value.)

### API

```python
def recover_eval_log(
    log: str,
    output: str | None = None,
    overwrite: bool = False,
    cleanup: bool = True,
    no_events: bool = False,
    incomplete_action: Literal["retry", "error", "score"] = "retry",
    incomplete_max: int | float | None = None,
) -> EvalLog:
```

- `incomplete_action="retry"` — today's behavior, unchanged default.
- `incomplete_action="error"` — in-progress samples get `error = EvalError("Sample terminated by operator during recovery: ...")` plus a `SampleLimitEvent(type="recovery")` appended to their reconstructed transcript. Header finalized per the rule above. `fail_on_error` from the original `EvalConfig` is deliberately **not** applied — the operator explicitly chose to complete the eval; recording the samples as errors is for analysis honesty, not for status computation.
- `incomplete_action="score"` — like `error`, but additionally attempt post-hoc scoring of the reconstructed sample state (messages/output recovered from the buffer DB) via the existing `inspect score` machinery (`_eval/score.py`), setting `limit = recovery` and `error = None`. Requires the task's scorer to be resolvable from the registry — the same constraint `eval-retry` already imposes.
- `incomplete_max` — safety threshold (count, or proportion if < 1): refuse to resolve (error out, leaving the log recoverable-as-today) when more than this many samples are incomplete. This is the "pre-agreed threshold" guard: 7 hung samples out of 500 is a tail; 300 is a systemic failure that should not be silently completed. `None` = no guard (explicit manual invocation).

**Scoring caveat (important):** many agentic scorers inspect sandbox state. After a SIGKILL the sandboxes are gone, so post-hoc `score` disposition can only work for scorers that operate on the transcript/completion. When scoring a resolved sample raises, recovery falls back to the `error` disposition for that sample and reports it — it does not fail the whole recovery. The doc for the CLI should be explicit that `score` is best-effort post-mortem and fully reliable only in the live path, where the sandbox is still up.

**Checkpointing changes this picture.** For tasks running with checkpointing enabled (`util/_checkpoint/`), on-disk checkpoints include sandbox snapshots (the restic layer, rehydrated on resume), and the retry sample source already prefers checkpoint resume for non-clean samples (`eval_log_sample_source` → `_resume_if_checkpointed`, `task/run.py`) — the shipped `ctl sample requeue` uses the same path live. So a hung sample killed mid-run needn't choose between transcript-only scoring and re-running from scratch: the `score` disposition on the `eval-retry`/`eval-set` integrations could resume the sample from its latest checkpoint — sandbox state restored — and run only the scoring phase. That makes checkpointed tasks the one post-mortem case where sandbox-inspecting scorers work properly. Detail to work through at implementation time (checkpoint freshness vs the buffer DB's event stream; only `eval-retry`/`eval-set` have the task context to resume — reinforcing open question 2).

### CLI

```
inspect log recover <file> --incomplete-action error [--incomplete-max 10]
inspect log recover <file> --incomplete-action score
```

Output states the resolution explicitly, e.g.:

```
Recovered 493 samples to mylog-recovered.eval (status: success)
  486 completed, 7 resolved as errors (stalled at crash)
```

`--json` for agents, following the ctl output conventions (the resolved sample ids/epochs in the envelope, so the agent can report exactly what was given up on). An agent operating under a "pre-agreed threshold with the operator" (JJ's framing) encodes that agreement as `--incomplete-max`: the command itself refuses to overreach, so the agent doesn't have to be trusted with the judgment.

A refinement worth pulling forward now that `ctl process anomalies` works post-mortem: the buffer DB records event timestamps, so recovery could apply the stall test after the fact — samples idle past a threshold at crash time were genuinely stalled (resolve them per the disposition); samples actively progressing were merely truncated by the kill (retry them regardless). See open question 4.

### eval / eval-set / eval-retry integration

`eval_retry()` and `eval_set()` (and their CLI commands) gain the same pair of parameters, passed straight through to the opportunistic recovery they already perform:

```python
eval_set(..., incomplete_action="retry" | "error" | "score" = "retry",
              incomplete_max: int | float | None = None)
```

The semantics are identical to the manual command — the disposition applies wherever recovery runs. For `eval_set` that is startup: when it encounters a crashed `"started"` log from a previous execution, the recovery it already performs resolves the in-progress samples per the disposition (within `incomplete_max`). If that leaves every expected sample final, the log finalizes as `"success"`, the task classifies as complete, and nothing re-runs; if the log also has never-started samples, it stays `"error"` and those re-run as today (see "Missing samples vs in-progress samples" — resolution only sticks when it finalizes). Likewise for `eval_retry`: recovery happens before re-running, resolution happens there, and if the log finalizes there is nothing left to retry.

The disposition is per-invocation intent, exactly like the CLI. The expected agent workflow: run with the default (`retry`); if the re-run stalls again and stays *responsive*, resolve live via `ctl` (no recovery involved); if it wedges again, kill and re-run with `incomplete_action="error"` (or `"score"`) so startup recovery resolves the tail and the run completes. A pipeline may also bake the disposition in from the start (fully push-button, no watcher). Then the *first* crash encounter resolves — a sample that hung once but would have succeeded on a re-run gets no second chance. That is the configured trade-off, and `incomplete_max` is the guard that keeps it honest: a hung tail is precisely a *small* in-progress set at kill time, while a transient infra failure typically dies with a *large* in-flight set — exceeding the guard and falling back to today's recover-and-retry behavior. A graduated policy ("re-run once; resolve on the second crash") needs cross-execution memory the log dir already contains — parked in open question 5.

### Missing samples vs in-progress samples

Recovery distinguishes:

- **In-progress at crash** — present in the buffer DB with events. Resolvable: we have a transcript to mark and (maybe) score.
- **Never started / lost** — expected by the dataset but absent from both the `.eval` file and the buffer DB. *Not* resolvable — there is nothing to mark. If any exist, the recovered log stays `status="error"` and they re-run on retry. Note that on a non-finalized log, samples resolved as `error` are re-run too (error set → re-run, per the retry classification) — resolution only "sticks" when it finalizes. That is coherent: since the log couldn't complete anyway, the hung samples get another chance alongside the missing ones, and the next kill-and-recover — now with no missing samples — finalizes.

Synthesizing empty errored placeholder samples for never-started ones (to force finalization no matter what) was considered and rejected: a placeholder with no transcript is analysis-hostile, and "samples that never even started" genuinely is retryable work, not a stall. (The shipped `ctl task cancel --action score/error` makes the same call from the other side: queued samples it abandons are *absent from the log*, not synthesized.)

## Piece B: in-process stall policy (proposed, demoted)

Configuration that lets the eval end stalled samples itself. Under the watching-agent assumption this is **defense-in-depth for unwatched runs**, not the primary mechanism — the agent already does everything this policy would, with judgment the policy lacks (diagnose via anomalies, unstick via tool-call cancel, requeue for a second chance). It stays in the design for pipelines that run without a watcher.

Detection signal: **transcript inactivity, not duration** — the same working-but-eventless idle metric `ctl sample list` computes, automated in-process. Model-retry backoff must not count (a sample waiting out a rate-limit storm is idle but not hung; `ActiveSample` already distinguishes waiting from working time). A systemic-stall guard mirrors `incomplete_max`: stop auto-resolving (and warn loudly) beyond a threshold, so a provider outage doesn't silently convert into a "completed" eval.

```python
stall_limit: int | None          # seconds of working-but-eventless inactivity
stall_action: Literal["score", "error"] = "score"
stall_max: int | float | None    # guard: max samples auto-resolved (count, or
                                 # proportion if < 1); beyond it, stop resolving
```

Implemented as a monitor alongside `monitor_working_limit()` in `task/run.py`, ending the sample through the **same `ActiveSample.interrupt(action)` path as `ctl sample cancel`** — transcript, limit field, scoring flow, and `fail_on_error` interlock behave identically whether the resolver was an agent or the policy. A policy-resolved sample stamps `EvalSampleLimit(type="stall")` (new literal) rather than `"operator"`, so analysis can tell them apart. Since `ctl config` retuning has shipped, `stall_limit` / `stall_action` should be retunable mid-flight like `--time-limit` — an agent that *is* watching can loosen or disable the policy rather than fight it.

Scope note: this handles **cancellable** hangs — the stuck await responds to task-group cancellation. A hang that wedges the event loop takes the whole process with it; that's Piece A's SIGKILL-and-recover territory. The known limitation either way: an event-based clock can't see a sandbox burning CPU on legitimate work (long compile) — the agent can (`process anomalies` shows the exec's live duration; a human judgment call either way), the policy can't, which is one more reason B defers to a watcher when one exists.

## How resolved samples appear in logs

| | `error` field | `limit` field | scores | transcript | status |
|---|---|---|---|---|---|
| resolved: `score` (live — agent/human) | `None` | `operator` | scored on current state | `SampleLimitEvent(type="operator")` | **shipped** |
| resolved: `error` (live) | `EvalError` ("interrupted by operator") | `None` | `None` | `SampleLimitEvent` + `ErrorEvent` | **shipped** |
| resolved: `cancel` (live) | `EvalError` (cancelled; bypasses `fail_on_error`) | `None` | `None` | `SampleLimitEvent` + `ErrorEvent` | **shipped** |
| resolved: `score` (stall policy) | `None` | `stall` | scored on current state | `SampleLimitEvent` | proposed (B) |
| resolved: `score` (recovery) | `None` | `recovery` | post-hoc scored, or falls back to `error` | `SampleLimitEvent` appended | proposed (A) |
| resolved: `error` (recovery) | `EvalError` (stall/termination message) | `None` | `None` | `SampleLimitEvent` + `ErrorEvent` | proposed (A) |
| unresolved (`retry`) | `EvalError` (cancelled) | `None` | `None` | as recovered today | shipped (default) |

Retry semantics follow from existing classification (`eval_log_sample_source`, `task/run.py`): `error=None` → reused; `error` set → re-run *if* anything retries the log — which a finalized `status="success"` log prevents at the eval-set level while still permitting an explicit later `inspect eval-retry` to take another swing at the errored samples. That reversibility is deliberate: resolving as `error` completes the pipeline without destroying the option to try again tomorrow. Live, the same reversibility now exists *inside* the run: `ctl sample requeue` re-runs an errored/cancelled sample without waiting for a retry cycle.

Provenance: resolution is an administrative edit to the record, similar in spirit to sample invalidation (`EvalSample.invalidation: ProvenanceData`). The shipped events record *that* an operator resolved ("interrupted by operator") but not *who* — see open question 3.

## Interactions and invariants

- **Eval-set completeness** (`log_samples_complete`, `_eval/evalset.py`): a finalized recovered log must carry `results` with `total_samples = dataset × epochs` (the *expected* count, matching what live runs record via `profile.samples`) — not the count of samples present — or the completeness predicate fails and the finalization is pointless. Recovery's results computation needs to honor this.
- **`fail_on_error`**: applies to live `error` dispositions (the control layer rejects `--action error` outright when samples fail on errors, and a task-level resolution arriving mid-init downgrades `error` to `score` — the auto-fail can't fire). Deliberately *not* applied during Piece A finalization — see above.
- **Graceful vs abort escalation**: a plain `ctl task cancel` escalates over a pending `score`/`error` resolution — the graceful path can stall on a hung scorer, and the operator must keep a way to tear the task down. The agent's ladder is: graceful resolve → abort → SIGKILL (→ recover, Piece A).
- **Epochs/reducers**: an epoch resolved without scores simply doesn't contribute to the reduction; existing reducers already tolerate missing per-epoch scores (same as errored epochs today). Verify during Piece A implementation.
- **`retry_on_error` / requeue**: orthogonal to recovery-time resolution — sample-level error retries and `ctl sample requeue` happen within a run; Piece A resolution happens post-mortem.
- **Early stopping** (`task.early_stopping`): related in spirit but different axis — it stops *the task* on metric confidence; this design ends *individual samples* on stall. No interaction beyond both producing partial-but-final logs.
- **Recovered-file bookkeeping**: unchanged from [recover.md](recover.md) — finalized recovered logs participate in eval-set log grouping by `task_id` exactly like a successful retry log would (they *are* the latest successful log).

## Open questions

1. **Naming** — the recovery family (`incomplete_{action,max}`) should read as the post-mortem spelling of the shipped `--action` vocabulary. The shipped live surface settles the disposition names (`score` / `error` / `cancel`); recovery adds `retry` (no live meaning) and likely drops `cancel` (a recovered in-progress sample is already cancelled — that *is* the `retry` state). Settle before the CLI ships.
2. **Post-hoc scoring dependencies** — is scorer-from-registry resolution enough, or does the recovery-score path need the full task context (`-T` args, model roles) that `eval-retry` reconstructs? If the latter, `incomplete_action="score"` may only be offered on the `eval-retry`/`eval-set` integrations (which have that context), with `log recover` limited to `error`.
3. **Structured resolution provenance** on the sample record (vs transcript-event-only). The shipped live path records a `SampleLimitEvent(type="operator")` whose message carries the story in prose; the limit type is the machine-readable classifier. The open question is whether to also add a structured field on `EvalSample` — the precedent is invalidation, which stores `EvalSample.invalidation: ProvenanceData` (`timestamp` / `author` / `reason` / `metadata`, `log/_edit.py`), and resolution is the same kind of administrative edit. In favor: queryability ("which samples across this eval-set were given up on, by whom, when?") and attribution — in the agent-driven pipeline the resolver is an LLM agent acting under a pre-agreed threshold, exactly the sort of action an org wants durably attributed (`author` distinguishes human / named agent / stall policy / recovery). Against: a log-schema change plus TS type generation and viewer rendering. Proposed: start event-only, add the field when analysis needs it — but if the audit requirement is real from day one (likely for the orgs this targets), it is cheaper to add now than to backfill, since events written without structured authorship can't be retroactively attributed. Now that agent-driven resolution is *shipped* without provenance, every week of use widens the unattributable window.
4. **Post-hoc stall detection in recovery.** The buffer DB records event timestamps, so recovery could apply the stall test after the fact: samples idle past a threshold at crash time were genuinely stalled — resolve them per `incomplete_action`; samples actively progressing were merely truncated by the kill — retry them regardless of the disposition. That would make the disposition apply to exactly the samples an operator means by "the stalled ones" and soften the eager-resolution trade-off in the baked-in pipeline case. `ctl process anomalies`' post-mortem trace analysis already demonstrates the underlying signal is available after death. Consider after the basic dispositions ship.
5. **Cross-execution stall tracking ("stalled twice = give up").** `stall_max` and `incomplete_max` are per-operation — a sample resolved as `error` and then re-run starts the next attempt with no memory that it stalled before. Retries already seed per-sample error history across executions (`error_retries` via `_seed_error_retries`, `task/run.py`), and requeue rides the same plumbing live, so a refinement like "resolve permanently after a sample has stalled in N attempts" is buildable. Today this memory lives only in the watching agent's context; deferred until the basic dispositions prove out.

## Resolved questions

1. **Limit type for resolved samples** — `"operator"` shipped in `EvalSampleLimitType` for live directives (agent and human alike — the agent *is* the operator). Add `"recovery"` with Piece A and `"stall"` with Piece B; remaining work is mechanical (log-schema literals, viewer and analysis dataframe rendering).
2. **`eval_retry` disposition timing** — pre-run: the disposition applies in the recovery `eval_retry` performs before re-running, and if resolution finalizes the log there is nothing left to retry. It composes: run retry without the flag first, then with it.
3. **Live-path design (former Piece C)** — shipped, and broader than originally sketched: per-sample and task-level cancel with dispositions, the `cancel` disposition (not in the original vocabulary), tool-call cancel, requeue, interim scoring, mid-flight limit retune, log-flush, and post-mortem trace anomalies. The original in-process stall policy (Piece B) was correspondingly demoted from co-equal piece to unwatched-run fallback.
