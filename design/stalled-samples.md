# Resolving Stalled Samples

Part of the push-button eval pipeline effort ([control-channel.md](control-channel.md), [recover.md](recover.md)). Complex agentic evals often "end" with a handful of hung or interminable samples — 7 or 8 out of hundreds — and today there is no way to bring such a run to a terminal, completed state without manual surgery. This doc designs the last mile: **ending stalled samples with a chosen disposition and guaranteeing the eval reaches `status == "success"`**, whether the operator is a human, a configured policy inside the eval process, or an LLM agent driving the pipeline from outside.

> **Status: proposal.** Nothing below is implemented; the "What exists today" section describes shipped machinery this design builds on.

## Problem

Two distinct failure shapes leave an eval permanently un-terminal:

1. **Stalled samples in a live process.** The event loop is healthy, but a few samples are wedged — a sandbox exec that never returns, an agent loop cycling without progress, a model call stuck behind an interminable retry. Per-sample `time_limit` / `working_limit` can bound these, but for long-horizon agentic tasks a tight absolute budget punishes legitimate slow samples; operators instead leave limits loose and end up babysitting the tail.

2. **A wedged process.** The event loop itself is stuck (blocking sync call, deadlock) and the only remedy is SIGKILL. After the kill, `inspect log recover` reconstructs the log — but it marks in-progress samples as cancelled *errors* and writes `status="error"` ([recover.md](recover.md)). A subsequent `eval-retry` / `eval_set` re-runs exactly those samples, which hang again. The pipeline loops; the log never reaches `"success"`.

In both shapes the operator's actual intent is often: *"these N samples are not going to finish — mark them appropriately and complete the eval."* Today that intent has no expression anywhere in the system except the live `ctl sample cancel` directive, which requires a responsive process and a human (or agent) noticing in time.

The goal, in JJ's words: if the process is completely hung we SIGKILL it, run recovery, mark all incomplete samples appropriately, and set the eval to completed — the last mile in a robust push-button eval pipeline.

## What exists today

| Mechanism | Where | What it does | Gap |
|---|---|---|---|
| `time_limit` / `working_limit` | `EvalConfig`, enforced in `task/run.py` | Absolute per-sample budgets; graceful end (sample gets `limit`, is scored) | Absolute — can't distinguish "slow but progressing" from "hung" |
| `ctl sample cancel TASK SID EPOCH [--error]` | control channel, shipped ([control-channel.md](control-channel.md) phase 3) | Interrupts a live sample; `action="score"` ends it with `limit = EvalSampleLimit(type="operator", limit=1)` and scores current state (`task/run.py:1385`); `action="error"` marks it errored | Requires a live process and an external actor polling for stalls |
| `inspect log recover` | `log/_recover/` ([recover.md](recover.md)) | Reconstructs crashed logs from the sample buffer DB; in-progress samples become cancelled errors; header written with `status="error"` | No way to say "these samples are final"; recovered log always re-enters the retry loop |
| Automatic recovery in `eval_retry` / `eval_set` | `_eval/eval.py:1526`, `_eval/evalset.py:992` | Opportunistically recovers crashed logs before retry so completed-but-unflushed samples are reused | Same — hung in-progress samples are re-run every attempt |
| `fail_on_error` | `EvalConfig` | `False` / count / proportion thresholds let an eval finish `"success"` despite sample errors | Only helps samples that *end*; a hung sample never ends |
| Eval-set completeness | `evalset.py:log_samples_complete` | Complete ⇔ `status == "success"` ∧ not invalidated ∧ `results.total_samples >= dataset × epochs` | Defines the target state this design must produce |

The building blocks are all present: a disposition vocabulary (`score` / `error`) already shipped for live cancellation, an "operator ended this" limit type, recovery that reconstructs everything reconstructable, and a completeness predicate. What's missing is (a) expressing dispositions at recovery time and finalizing the log, and (b) automating stall detection so no one has to watch.

## Design overview

One shared concept — **resolving** a sample: administratively ending it with a **disposition**:

- **`score`** — end the sample as-is: `limit = operator` (or `stall`, see below), no error, score whatever state exists. The sample counts as completed; retry reuses it.
- **`error`** — end the sample with an `EvalError` describing the stall/termination. Visible as a failure in analysis; a later `eval-retry` would re-run it, but a finalized log (`status="success"`) stops the eval-set loop.
- **`retry`** — not resolved: leave the sample marked for re-running (today's behavior; remains the default everywhere).

The same vocabulary is delivered at three points, matching who is acting:

| Piece | Actor | Situation |
|---|---|---|
| **A. Recovery dispositions** | human / agent / eval-set retry loop | process was killed; post-mortem finalization |
| **B. In-process stall policy** | the eval itself, configured up front | live process, cancellable hangs; zero-touch |
| **C. External operator workflow** | human or LLM agent via `inspect ctl` | live process, judgment-call intervention (mostly shipped) |

Piece C is largely built; this design specifies A and B and ties C into the same vocabulary.

## Piece A: dispositions in recovery

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
    incomplete: Literal["retry", "error", "score"] = "retry",
    max_incomplete: int | float | None = None,
) -> EvalLog:
```

- `incomplete="retry"` — today's behavior, unchanged default.
- `incomplete="error"` — in-progress samples get `error = EvalError("Sample terminated by operator during recovery: ...")` plus a `SampleLimitEvent(type="operator")` appended to their reconstructed transcript. Header finalized per the rule above. `fail_on_error` from the original `EvalConfig` is deliberately **not** applied — the operator explicitly chose to complete the eval; recording the samples as errors is for analysis honesty, not for status computation.
- `incomplete="score"` — like `error`, but additionally attempt post-hoc scoring of the reconstructed sample state (messages/output recovered from the buffer DB) via the existing `inspect score` machinery (`_eval/score.py`), setting `limit = operator` and `error = None`. Requires the task's scorer to be resolvable from the registry — the same constraint `eval-retry` already imposes.
- `max_incomplete` — safety threshold (count, or proportion if < 1): refuse to resolve (error out, leaving the log recoverable-as-today) when more than this many samples are incomplete. This is the "pre-agreed threshold" guard: 7 hung samples out of 500 is a tail; 300 is a systemic failure that should not be silently completed. `None` = no guard (explicit manual invocation).

**Scoring caveat (important):** many agentic scorers inspect sandbox state. After a SIGKILL the sandboxes are gone, so post-hoc `score` disposition can only work for scorers that operate on the transcript/completion. When scoring a resolved sample raises, recovery falls back to the `error` disposition for that sample and reports it — it does not fail the whole recovery. The doc for the CLI should be explicit that `score` is best-effort post-mortem and fully reliable only in the live path (Piece B/C), where the sandbox is still up.

### CLI

```
inspect log recover <file> --incomplete error [--max-incomplete 10]
inspect log recover <file> --incomplete score
```

Output states the resolution explicitly, e.g.:

```
Recovered 493 samples to mylog-recovered.eval (status: success)
  486 completed, 7 resolved as errors (stalled at crash)
```

`--json` for agents, following the ctl output conventions (the resolved sample ids/epochs in the envelope, so an agent can report exactly what was given up on).

### eval / eval-set / eval-retry integration

`eval_retry()` and `eval_set()` (and their CLI commands) gain the same pair of parameters, threaded to the opportunistic recovery they already perform:

```python
eval_set(..., incomplete_samples="retry" | "error" | "score" = "retry",
              max_incomplete: int | float | None = None)
```

Semantics differ from the manual command in *when* the disposition applies. Applying it on the first attempt would defeat retry — the whole point of the retry loop is that a re-run might succeed. The disposition is an **exhaustion policy**:

- `eval_retry` (single-shot): applies immediately — the user invoking retry with a disposition is saying "recover, resolve, and if that completes the log, don't re-run".
  - Open question: should it apply pre-run (resolve then skip the eval entirely if finalized) or post-run (retry once more, then resolve whatever still didn't finish)? Leaning pre-run for `eval_retry` — it composes: run retry without the flag first, then with it.
- `eval_set` (retry loop): applies on the **final** retry attempt. Attempts 1..N-1 behave exactly as today (recover → re-run incomplete). If attempt N still leaves a log incomplete and the incomplete count is within `max_incomplete`, resolve and finalize instead of returning failure. This is the "guaranteed terminal state" knob: an eval-set configured with `incomplete_samples="error", max_incomplete=0.05` *always* ends with all-success logs unless something is systemically wrong.

One wrinkle: eval-set's final attempt may end with a log whose status is `"error"` (process alive, samples errored) rather than a crashed `"started"` log. Sample-level errors already have a completion story (`fail_on_error`); this design does not change that. The resolution path only concerns samples that *never ended* — which, in a live process that reached log-finish, don't exist. So eval-set resolution triggers only for `"started"` (crashed/killed) logs, via recovery. A wedged-but-alive process (samples hung, loop healthy) is Piece B/C territory; if those pieces end the stragglers, the log finishes normally and eval-set never needs A.

### Missing samples vs in-progress samples

Recovery distinguishes:

- **In-progress at crash** — present in the buffer DB with events. Resolvable: we have a transcript to mark and (maybe) score.
- **Never started / lost** — expected by the dataset but absent from both the `.eval` file and the buffer DB. *Not* resolvable — there is nothing to mark. If any exist, the recovered log stays `status="error"` and they re-run on retry. In the eval-set exhaustion flow this is fine: earlier attempts run them; by the final attempt the only stragglers are the perennially-hung in-progress ones.

Synthesizing empty errored placeholder samples for never-started ones (to force finalization no matter what) was considered and rejected: a placeholder with no transcript is analysis-hostile, and "samples that never even started" genuinely is retryable work, not a stall.

## Piece B: in-process stall policy

Configuration that lets the eval end stalled samples itself — no external watcher.

### Detection signal: inactivity, not duration

Absolute budgets (`time_limit`, `working_limit`) can't express "hung". The distinguishing signal of a hung sample is **transcript inactivity**: a healthy long-running agentic sample continuously emits events (model calls, tool calls, sandbox events); a hung one emits nothing. The control channel's `ctl sample list` already computes an idle metric from last-event recency for exactly this diagnosis — the policy automates the same judgment in-process.

Two refinements to avoid false positives:

- **Model-retry backoff must not count as inactivity.** A sample waiting out a rate-limit storm is idle but not hung. `ActiveSample` already distinguishes waiting time from working time; the stall clock only accrues while the sample is *working* but eventless. (Model retries also emit retry events, which reset the clock — but don't rely solely on that.)
- **Systemic-stall guard.** If many samples stall simultaneously (provider outage, sandbox host down), resolving them all silently converts an infrastructure incident into a "completed" eval. The policy takes a threshold: stop auto-resolving (and warn loudly) when more than `stall_max` samples (count or proportion) have been resolved.

### Configuration

New `EvalConfig` fields (CLI flags on `inspect eval` / `eval-set`, parallel to `--time-limit`):

```python
stall_limit: int | None          # seconds of working-but-eventless inactivity
                                 # before a sample is considered stalled
stall_action: Literal["score", "error"] = "score"   # disposition applied
stall_max: int | float | None    # guard: max samples auto-resolved (count, or
                                 # proportion if < 1); beyond it, stop resolving
```

`stall_action="score"` is the default because it matches the completion goal: the sample ends with a `limit`, gets scored on its current state (sandbox still alive — scoring is reliable here, unlike post-mortem), and the eval completes with full results. `"error"` is for tasks where a stalled sample must read as a failure (subject to `fail_on_error` as usual — an operator who sets both `stall_action="error"` and `fail_on_error=True` has asked for the eval to fail, and it will).

### Mechanism

Implemented as a monitor alongside `monitor_working_limit()` in `task/run.py` — a per-sample coroutine that watches last-activity timestamps and, on expiry, ends the sample through the **same path as `ctl sample cancel`** (`ActiveSample.interrupt(action)` for `score`/`error`). Reusing the interrupt path means the transcript, limit field, scoring flow, and `fails_on_error` interlock all behave identically whether the resolver was a human, an agent, or the policy.

Sample limit type: the shipped interrupt path stamps `EvalSampleLimit(type="operator", limit=1)`. A policy-resolved sample isn't operator-ended, and analysis will want to distinguish them; propose adding `"stall"` to `EvalSampleLimitType` (used by Piece B, and arguably by recovery-resolved samples in Piece A too — open question below). The `SampleLimitEvent` message carries the specifics (idle seconds, threshold).

Scope note: this handles **cancellable** hangs — the stuck await responds to task-group cancellation. A hang that wedges the event loop itself takes the whole process with it; that's Piece A's SIGKILL-and-recover territory. The two pieces are complementary, not redundant: B prevents most stalls from ever reaching the kill, A guarantees termination when one does.

Later, `stall_limit` / `stall_action` should be retunable mid-flight via `ctl config` alongside the planned `--time-limit` retuning ([control-channel.md](control-channel.md) phase 3) — an operator watching a run decide the tail policy without relaunching.

## Piece C: external operators (human or agent)

Mostly shipped; recorded here so the three pieces read as one surface.

**Live process, agent-driven** (the control-channel headline scenario, extended):

```
inspect ctl sample list <task> --json          # idle column identifies stragglers
inspect ctl sample cancel <task> <sid> <epoch> --dry-run
inspect ctl sample cancel <task> <sid> <epoch>            # disposition: score
inspect ctl sample cancel <task> <sid> <epoch> --error    # disposition: error
```

When the tail is resolved, the eval finishes normally — log status `"success"`, no recovery involved.

**Wedged process, agent-driven** (new, enabled by Piece A):

```
kill -9 <pid>                                             # process unresponsive
inspect log recover <log> --incomplete error --max-incomplete 10 --json
inspect eval-retry ... / eval-set re-run                  # no-op: log is complete
```

An agent operating under a "pre-agreed threshold with the operator" (JJ's framing) encodes that agreement as `--max-incomplete`: the command itself refuses to overreach, so the agent doesn't have to be trusted with the judgment. Everything the agent needs to report back — which samples were resolved, with what disposition — is in the `--json` envelope.

The symmetric design intent: **anything the policy (B) can do automatically, an agent (C) can do explicitly with the same vocabulary, and anything an agent can do live, recovery (A) can do post-mortem.** Threshold semantics (`stall_max` / `max_incomplete`), dispositions, and log markings are shared across all three.

## How resolved samples appear in logs

| | `error` field | `limit` field | scores | transcript |
|---|---|---|---|---|
| resolved: `score` (live) | `None` | `operator` (agent/human) or `stall` (policy) | scored on current state | `SampleLimitEvent` |
| resolved: `score` (recovery) | `None` | `operator` | post-hoc scored, or falls back to `error` | `SampleLimitEvent` appended |
| resolved: `error` | `EvalError` (stall/termination message) | `None` | `None` | `SampleLimitEvent` + `ErrorEvent` |
| unresolved (`retry`) | `EvalError` (cancelled) | `None` | `None` | as recovered today |

Retry semantics follow from existing classification (`eval_log_sample_source`, `task/run.py:1945`): `error=None` → reused; `error` set → re-run *if* anything retries the log — which a finalized `status="success"` log prevents at the eval-set level while still permitting an explicit later `inspect eval-retry` to take another swing at the errored samples. That reversibility is deliberate: resolving as `error` completes the pipeline without destroying the option to try again tomorrow.

Provenance: resolution is an administrative edit to the record, similar in spirit to sample invalidation (`EvalSample.invalidation: ProvenanceData`). At minimum the `SampleLimitEvent` message records who/what resolved (`operator` / `stall policy` / `recovery`) and the threshold context. Whether to add structured provenance (a `resolution: ProvenanceData`-style field) is an open question — start with the event, add structure if analysis needs it.

## Interactions and invariants

- **Eval-set completeness** (`log_samples_complete`): a finalized recovered log must carry `results` with `total_samples = dataset × epochs` (the *expected* count, matching what live runs record via `profile.samples`) — not the count of samples present — or the completeness predicate fails and the finalization is pointless. Recovery's results computation (`recompute_metrics`) needs to honor this.
- **`fail_on_error`**: applies to Piece B `error` dispositions (live path, normal rules). Deliberately *not* applied during Piece A finalization — see above.
- **Epochs/reducers**: an epoch resolved without scores simply doesn't contribute to the reduction; existing reducers already tolerate missing per-epoch scores (same as errored epochs today). Verify during implementation.
- **`retry_on_error`**: orthogonal — sample-level error retries happen within a run; resolution happens at end-of-run or post-mortem.
- **Early stopping** (`task.early_stopping`): related in spirit (ending work early by policy) but different axis — it stops *the task* on metric confidence; this design ends *individual samples* on stall. No interaction beyond both producing partial-but-final logs.
- **Recovered-file bookkeeping**: unchanged from [recover.md](recover.md) — finalized recovered logs participate in eval-set log grouping by `task_id` exactly like a successful retry log would (they *are* the latest successful log).

## Open questions

1. **Limit type for resolved samples** — reuse `"operator"` everywhere vs add `"stall"` for policy-resolved (proposed above) vs also a distinct type for recovery-resolved. Adding literals to `EvalSampleLimitType` is a log-schema change; the viewer and analysis dataframes need to render them.
2. **`eval_retry` disposition timing** — resolve pre-run (skip re-running entirely) vs post-run (one more attempt, then resolve). Proposed pre-run; needs a decision.
3. **Naming** — `stall_limit` vs `inactivity_limit`; `incomplete` vs `resolve_incomplete`; bikeshed before the CLI ships since flags are forever.
4. **Post-hoc scoring dependencies** — is scorer-from-registry resolution enough, or does the recovery-score path need the full task context (`-T` args, model roles) that `eval-retry` reconstructs? If the latter, `incomplete="score"` may only be offered on the `eval-retry`/`eval-set` integrations (which have that context), with `log recover` limited to `error`.
5. **Structured resolution provenance** on the sample record (vs transcript-event-only).
6. **Should Piece B's stall clock also watch sandbox activity?** A sample whose transcript is quiet but whose sandbox is burning CPU may be doing legitimate work an event-based clock can't see (e.g. a long compile). Possible refinement: consult `SandboxConnection` activity where available; punt initially and let `stall_limit` be set generously.
