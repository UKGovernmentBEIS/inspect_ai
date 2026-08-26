# Interim scoring: score a running eval's in-flight samples mid-run

> **Status: initial implementation shipped** (meridianlabs-ai/inspect_ai#91) —
> phases 1 and 2 below: the `ctl task score` directive, the endpoint pair, and
> pause-and-score of in-flight samples via the sample-keyed hard hold
> (`inspect_ai._control.scoring` + the sample gate in
> `inspect_ai._control.pause`). Per maintainer direction on the design review
> (meridianlabs-ai/inspect_ai#94), the **initial implementation scores in-flight
> samples by pausing them** — a per-sample application of the hard-pause gate
> that shipped as `pause --now` (meridianlabs-ai/inspect_ai#103; see
> [`pause-resume.md`](pause-resume.md)) — and the in-context
> cooperative (no-hold snapshot) shape is **deferred** (phase 3). The
> control-channel context this builds on is in
> [`control-channel.md`](control-channel.md); the partial-sample persistence
> machinery referenced throughout is described in [`recover.md`](../recover.md).

The feature: a **non-destructive control-channel directive** — `inspect ctl
task score` — that runs the task's scorers over a *running* eval's in-flight
samples (each briefly held while scored), folds completed samples' existing
final scores in, computes interim metrics, reports the results in the
command's output envelope, and persists in-flight samples' scores into their
log transcripts (as intermediate score events).

## Motivation

Long-running evals — agentic tasks especially — give the operator no score
signal until samples finish, and no aggregate signal until the eval does. On
a multi-day run the questions an operator (or a monitoring agent — see the
watchdog / dashboarder scenarios in `control-channel.md`, which explicitly
name "scoring distribution so far" as a dashboard metric) needs answered are:

- **Is it working?** An interim accuracy over the work done so far is the
  difference between "keep spending" and "cancel now" — today the only way to
  get scores out of in-flight samples is to kill them.
- **What do we have if it dies?** Interim scores persisted mid-run mean a
  later crash doesn't reduce days of agent work to unscored transcripts.
- **How are the long-tail samples doing?** A sample that runs for days can be
  scored on its work-so-far repeatedly (some tasks author this in via the
  `score()` API — but that requires the task author to have anticipated it).

What exists today, and why none of it covers this:

| Existing machinery | What it does | Gap |
|---|---|---|
| `ctl sample cancel --action score` / `ctl task cancel --action score` | scores the work done so far | **destructive** — ends the sample / the task |
| `ctl task pause --now` (and model/process scope) | holds in-flight samples at their next model call, state stable while held | holds but doesn't score — no scorer run, no interim metrics; this design composes the hold with scoring, and makes it per-sample |
| `inspect score` (CLI) / `score_async` | re-scores a log | post-hoc: in-flight samples aren't in the log (only in the sample buffer), and a live log is mid-write |
| `score()` (`inspect_ai/scorer/_score.py`) | intermediate scoring from *inside* a sample; emits `ScoreEvent(intermediate=True)` | must be authored into the task; an operator can't trigger it from outside |
| live display metrics (`compute()` in `_eval/task/run.py`) | periodically recomputes metrics over completed samples | completed samples only; display-only; in-process |
| `inspect log recover` + `inspect score` | reconstructs a crashed eval from the sample buffer, then scores it | offline — requires the process to be dead |

The pieces are all there — an in-context intermediate-scoring primitive with a
first-class log representation (`ScoreEvent.intermediate`), a
score-from-serialized-sample recipe (`_run_score_task`), a metrics-recompute
path (`recompute_metrics` / `eval_results`), and a control channel with
task-keyed directives. This design composes them into an operator-triggered
surface.

## Command surface

A task-scoped directive, following the `ctl` noun-group conventions:

```
inspect ctl task score [TASK] [--dry-run] [--completed-only] [--no-wait] [--status] [--json]
```

- `TASK` follows the mutation selector rule (sole running task is the
  default; several running tasks require the selector). Unlike `task cancel`
  it is *not* required outright — the directive is non-destructive, so it
  sits with `log-flush` on the selector-optional side.
- `--dry-run` reports what would be scored (counts by sample disposition —
  see "Which samples" below) without scoring anything.
- In-flight samples are **held while scored**: the pass briefly parks each
  one at its next model call — a per-sample application of the shipped
  hard-pause gate — scores its then-stable live state, and releases it (see
  shape 3 under "The context problem"). The hold is per-sample and lasts
  only while that sample's own scoring runs; a sample that neither parks nor
  completes within the hold timeout is skipped and reported. A
  never-delays-the-run snapshot mode (no hold) is the deferred in-context
  shape — when built it arrives as an explicit opt-in flag on this command.
- `--completed-only` (maps to a `completed_only` query param) skips the
  in-flight rows entirely — no holds, and (since completed samples are never
  re-scored) no scorer model calls at all: interim metrics over existing
  final scores. The free spelling for *recurring* watchdog/dashboard polling
  until the no-hold snapshot mode ships (see "Hazards": periodic holds would
  perturb the run being measured).
- The pass can take minutes (model-graded scorers over hundreds of samples),
  so the HTTP shape is **start + poll**, not one long request (see "Job
  model"); by default the CLI polls to completion and renders progress, and
  `--no-wait` returns the started-pass envelope immediately.
- `--status` reads the current (or most recent) pass without starting one —
  the follow-up spelling after `--no-wait`. A repeat *start* is idempotent
  only against a still-running pass; once the first pass finishes it would
  spawn a fresh one (re-holding in-flight samples, re-spending grader
  calls), so the follow-up must be the GET, not another POST. `--status`
  polls a running pass to completion; `--status --no-wait` is a single
  snapshot.
- `--json` everywhere, per the agent output contract.

HTTP endpoints, task-keyed like `config` / `log-flush` / `cancel` (a task id
never dangles across a retry):

| Operation | Endpoint |
|---|---|
| Start a scoring pass | `POST /tasks/<task-id>/score?dry_run=<bool>&completed_only=<bool>` |
| Read pass status / result | `GET /tasks/<task-id>/score` |

A per-sample variant (`ctl sample score TASK SID [EPOCH]`, `POST
/evals/<id>/sample/score?...`) is a natural later slice — same machinery,
sample-scoped — and is deliberately deferred (the task-wide pass is the
motivating ask, and one sample's interim score is obtainable today by reading
its events after a task-wide pass). Tracked as a follow-up in
meridianlabs-ai/inspect_ai#102.

## Which samples

Each sample in the eval falls into one disposition, reported per-sample in
the result envelope and counted in `--dry-run`:

| Sample state | Disposition |
|---|---|
| **In-flight** (started, not terminal) | **held** at its next model call, scored on its stable work-so-far, released (the headline capability); reported un-scored if it neither parks nor completes within the hold timeout |
| **Completed, unscored** (a scorer previously errored, or an errored sample scoreable under `score_on_error`) | *not* scored by the pass — a skip row pointing at post-run `inspect score` (see "Completed samples" for why mid-run re-scoring was removed) |
| **Completed, scored** | *not* re-scored (the task's scorers are fixed at eval start, so re-running them buys nothing); its existing final scores are included in the interim metrics |
| **Errored / cancelled** | mirrors final scoring for classification: errored samples count as scoreable (completed-unscored) only if the eval's resolved `score_on_error` flag is set; cancelled samples are never scoreable (final scoring excludes them regardless of the flag) |
| **Queued / pending** | skipped — nothing to score |

"Partially completed" in the issue title is the in-flight row: a sample with
real work in its transcript that hasn't reached its solver's end. Note that
a `--no-score` run cannot be interim-scored at all: the runner resolves no
scorers under `score=False`, so the task publishes an empty scoring handle
and the start directive rejects with "no scorers" — those runs remain served
by `inspect score` after the fact. With `--ctl-server=keep`, a parked
finished eval *can* be scored through this surface.

## Mechanics

### The context problem (in-flight samples)

The fundamental constraint: **a running sample's live `TaskState` is
context-bound**. It lives in the `_sample_state` `ContextVar`
(`solver/_task_state.py`), set inside the sample's own coroutine. The control
server runs as a sibling task on the eval's loop, so a handler cannot reach
it — which is precisely why the existing score-on-cancel path doesn't score
from the handler at all: `ActiveSample.interrupt("score")` cancels the
sample's task group, and the sample's *own* coroutine catches the
cancellation, grabs `sample_state()` from within its context, and falls
through to the ordinary scoring block (`_eval/task/run.py`).

Three shapes can score an in-flight sample without ending it (numbering
kept from the original proposal; **3 is chosen for the initial
implementation, 1 is deferred** — maintainer direction on the design
review, meridianlabs-ai/inspect_ai#94):

1. **In-context cooperative scoring (deferred).** Each running sample
   services score requests *from inside its own context*: the runner spawns
   a small companion task inside the sample's task group at sample start,
   parked on a request signal published via the `ActiveSample`. On request
   it deep-copies the live `TaskState` and runs the task's scorers against
   the snapshot via the existing `score()` machinery, posting the scores
   back to the pass. (The companion must be spawned from the sample's
   coroutine, not from the handler: anyio's `start_soon` gives the child a
   copy of the *caller's* context, so a handler-spawned task would be no
   better off than the handler.) Its unique virtue is that it **never
   delays the sample** — the solver keeps running while the copy is scored
   — which is exactly what the recurring watchdog/dashboard polling
   scenario wants: periodic monitoring must not turn into periodic
   eval-wide stalls that perturb the thing being measured. Deferred, not
   rejected, because it is the expensive shape: dedicated runner machinery
   (companion spawn, request/response signalling, cancel-on-completion),
   subtle budget isolation (the companion's context copy carries the
   sample's limit contextvars, so its grader calls must be excluded —
   `suspend_token_limit()` / `suspend_turn_limit()` are the prior art, and
   there is no cost-limit equivalent yet), and a coherence gap (the deep
   copy covers in-memory state only — the live sandbox keeps moving under
   the still-running solver, so a sandbox-inspecting scorer can read a
   sandbox that has drifted from the message snapshot it was handed). When
   built, it becomes an opt-in no-hold snapshot mode on the same pass.

2. **Handler-side reconstruction (rejected).** Rebuild a `TaskState` from
   the sample's serialized form — the recorder's `buffered_sample()` or the
   sample-buffer events, via the `_recover` package's
   `reconstruct_eval_sample` — and score it on the handler side, the way
   `_run_score_task` (`_eval/score.py`) does for logged samples. Rejected
   for in-flight samples because the reconstruction is low-fidelity exactly
   where agentic scorers care: **no sandbox access** (sandbox environments
   are per-sample context; scorers on agentic tasks routinely inspect the
   sandbox to score) and a store/state view limited to what events
   captured. It remains `inspect score`'s post-run recipe for completed
   samples; the initial build applied it to completed-unscored samples
   mid-run too, and that was subsequently removed (see "Completed
   samples").

3. **Pause-and-score (chosen for the initial implementation).** Hold the
   sample, then score its live state from the handler side. The hold is the
   hard-pause gate that shipped as `pause --now`
   ([`pause-resume.md`](pause-resume.md), gate module
   `src/inspect_ai/_control/pause.py`) applied per-sample: a `PauseGate`
   awaited at generate-attempt start (`wait_generate_dispatch`, gating
   `Model.compact()` too), held-sample accounting (`task_held_count`,
   surfaced as the `held` count on `GET /tasks` rows), incremental
   waiting-time crediting so a held span never burns `working_limit`, and
   cancel escalating over the hold via the gate's escape check. A sample
   parked at that gate mutates its `TaskState` only from its own coroutine,
   so the live state is stable while held — and the compact gate means the
   conversation can't be rewritten under the scorer either.

   **The hold dissolves the context problem.** The contextvar constraint
   bites because the live `TaskState` moves under its own coroutine — the
   only safe place to *read a moving state* is from inside its context.
   Held, the state is stable, so the pass can score it from the handler
   side against direct references, with no companion task at all. The
   runner change shrinks to a publication: at sample start, expose the
   sample's live handles on the `ActiveSample` (the same object the control
   layer already reaches through `find_active_sample`) — the live
   `TaskState`, the sandbox environments dict (`ActiveSample` today carries
   sandbox *connections* for the VS Code surface, not the environments),
   and the scoring `Target`. The pass then runs the task's scorers in a
   purpose-built scoring context on the eval's loop: the transcript var
   bound to the sample's live `Transcript` — so `ScoreEvent(intermediate=True)`
   is recorded exactly as task-authored `score()` records it, and flows
   through the realtime buffer — the sandbox contextvars
   (`sandbox_environments_context_var`) bound to the live environments so
   sandbox-inspecting scorers work, and `init_scoring_context` supplying
   scorers and target.

   **What the scoring context deliberately does *not* bind: the sample
   itself.** `sample_active()` stays `None` in the pass's context, and that
   buys two properties *structurally* rather than by mechanism:

   - **Budget isolation.** The sample's limit scopes are contextvars its
     own context entered; the pass's context never did. Grader calls
     therefore cannot push the sample over its token / cost / message
     limits or distort its reported usage — no `suspend_*` wrapping, no
     attribution surgery. The pass envelope reports scoring usage
     separately.
   - **Hold escape.** `wait_generate_dispatch` resolves the sample and task
     it is holding for through the active sample
     (`_active_sample_hold_key`), so the pass's own grader calls pass the
     sample-keyed hold — and any operator *task*-scope hard pause — without
     an exemption token. The original sketch's "scorer exemption" build
     item falls away; what's left is a caveat, not a mechanism: a
     process-wide `pause --now` (checked unconditionally) or a hard model
     pause on the grader's model (keyed on the model actually being called)
     *will* park the pass's graders — which is consistent with what those
     incident levers promise.

   **What remains to build — the per-sample hold.** The shipped gate
   registries key task / model / process, so the pass needs:

   - a **sample-keyed hard hold** consulted at the same
     `wait_generate_dispatch` site (which already resolves the active
     sample for the held count);
   - the **wait-for-park ack**: request the hold, wait for the sample's
     held accounting to register, then score. The park point is the next
     model call, not every runner chokepoint (the hard-pause build
     deliberately gates only generate/compact; tool calls and sandbox
     commands in progress run to completion), so a tool-heavy sample parks
     only when its current tool call ends. For a sample running concurrent
     solver branches (parallel subagents), one branch parking doesn't by
     itself still the others — and a quiescence predicate over generate
     attempts alone cannot be made sound, because a sibling branch *between*
     model calls (mid-tool-call, mid-sandbox-exec, or in pure Python)
     presents no generate attempt to cover yet is about to mutate the shared
     `TaskState`. The predicate therefore needs a non-generate activity
     signal (the same activity accounting deferred under open question 3),
     or — simpler and safe — multi-branch samples without full coverage time
     out to the "did not park" row like non-parking samples do. Which of the
     two ships first is a build detail to pin down with tests;
   - a **hold timeout**, so a sample that neither parks nor completes (a
     long sandbox command, a solver phase with no model calls) can't wedge
     the pass. On timeout the sample's row reports "did not park", and it
     is *not* scored: scoring a moving state from the handler is precisely
     the race the hold exists to prevent, and the deferred snapshot mode
     (shape 1) is the eventual answer for these samples;
   - **independence from the operator latches**: a separate registry, so an
     unrelated `ctl task resume` doesn't release a scoring hold and the
     pass's release doesn't clear an operator's pause. Each sample is held
     only while *its own* scoring runs and released immediately after — the
     pass never holds the whole task;
   - **release-on-completion**: a sample that completes (or is interrupted,
     or hits a limit) instead of parking — or mid-scoring — is reported as
     "completed before interim scoring finished", its final score
     superseding.

   The shipped semantics settle the rest, inherited rather than reopened:
   **wall clock is the operator's risk** (`time_limit` deadlines keep
   running while held — deadline-shifting was considered and rejected in
   the hard-pause build; a scoring hold is minutes, not hours, but a sample
   near its deadline can expire while held, so the pass's per-sample rows
   carry the held duration; `working_limit` exclusion needs no new work —
   the shipped crediting covers it). One shipped semantic *changed* for
   this build rather than being inherited: a parked call now **releases its
   connection slot** while parked and reacquires it before resuming (the
   release-and-reacquire escape hatch `pause-resume.md` named). The
   original keep-the-slot trade-off was untenable here: a run whose
   `max_connections` is at or near the held sample's parked-call count,
   with a grader on the same pool, would starve the scorer for the full
   scoring deadline on every held sample.

   Note the limit of what the hold buys: agent-launched *background*
   processes in the sandbox keep running (a true sandbox freeze is
   provider-specific — `docker pause` has no portable k8s/local
   equivalent), so this is coherent live state, not absolute quiescence.

   A coarse composition of the same idea becomes available partway through
   phase 2, before the per-sample hold does: once the `ActiveSample`
   publication and the pass's scoring context exist (the first phase-2
   slice below), `ctl task pause --now`, poll `task list` until the
   in-flight samples read as held, `ctl task score`, `ctl task resume`
   scores held in-flight samples under a whole-task hold for the whole
   pass rather than per-sample holds. (Phase 1 alone doesn't get there:
   without the publication and scoring context, a pass under the same
   composition reports the held in-flight samples as skipped.) Note that
   with handler-side scoring the composition has no grader gap: the
   task-scope hard gate resolves its target through the active sample,
   which the pass's scoring context doesn't bind, so the pass's own grader
   calls run even under `task pause --now`.

Pause-and-score buys the best fidelity of the three shapes — the *real*
`TaskState` (not a copy, not a reconstruction), live store, live sandbox,
all coherent with one another because the sample is held — plus free log
persistence (the transcript event flows through the realtime sample buffer
into the final log) and semantic continuity with the `score()` API's
`ScoreEvent(intermediate=True)`. Its cost is the one it wears openly: each
scored in-flight sample stops for the duration of its own scoring (see
"Hazards"), which rules it out as an *every-few-minutes polling* surface —
that use case is what keeps shape 1 on the roadmap.

### Scoring a held sample: requirements on the pass

- **Park, then score.** The pass touches a sample's live state only between
  the park ack and the release — never a moving state. Scores are stamped
  with the hold time (`ScoreEvent.timestamp` covers this).
- **Bound the hold.** The hold timeout caps how long the pass waits for a
  park, and a per-sample scoring deadline caps how long a stuck scorer can
  hold a parked sample — the sample must always come back. Each sample is
  released the moment its own scoring ends; samples are held one (or a
  small capped batch) at a time, never all at once for the whole pass.
- **Yield to the sample.** Sample completion (or interrupt, or a limit)
  during scoring cancels the in-progress interim scoring and releases the
  hold rather than waiting; the pass reports that sample as "completed
  before interim scoring finished" — its final score supersedes.
- **Never spend the sample's budget.** Scorer model calls must not count
  against the sample's token / cost / message limits (an operator asking
  "how's it going?" must not be able to push a sample over its limit), and
  must not distort the sample's reported usage. Handler-side scoring gets
  this structurally — the pass's context never entered the sample's limit
  scopes and never binds the sample as active — but it's an invariant to
  lock in with tests, not an accident to rely on silently. (Separate
  scoring-usage reporting in the pass envelope is deferred — see the
  implementation notes below.)
- **One at a time.** A second request while a sample's interim scoring is
  running joins the in-progress result rather than double-scoring (and
  never stacks a second hold).

### Completed samples

Never scored by a pass. Already-scored samples contribute their existing
final scores to the interim metrics (summaries only — no full-sample reads,
no grader calls); unscored completed samples get a skip row pointing at
post-run `inspect score`.

Mid-run re-scoring of completed-unscored samples from their serialized form
(the `_run_score_task` recipe over the recorder's buffered samples) shipped
in the initial build and was then **removed**: it carried most of the
feature's operational risk — synchronous deep copies of full samples on the
eval loop, whole-pass sensitivity to one unreadable record, long pass
windows widening every teardown race — for a population that is near-empty
on normal runs (samples score inline at completion, and a `--no-score` run
resolves no scorers so it can't start a pass at all), and its output was
envelope-only, unmarked, and re-bought by every subsequent pass. The
durable path for completed samples is post-run `inspect score`.

### Interim metrics

The pass ends by computing interim `EvalResults` over the union of:

- final `SampleScore`s of completed-and-scored samples (the same inputs the
  live display's periodic `compute()` uses),
- the pass's held-state scores for in-flight samples,

via the existing `eval_results()` machinery (the task's reducers and
metrics — the same path `recompute_metrics` uses for post-hoc recompute).
The result is labeled **interim** everywhere it surfaces: epochs may be
incomplete (a reducer over a sample's partial epoch set sees fewer values
than it will at eval end), and an in-flight score describes a held moment
mid-run by construction. The eval's own `results` — computed at eval end —
are entirely unaffected.

## Results: reporting and persistence

The pass **reports** through the result envelope (the `--json` output):
per-sample `{sample_id, epoch, disposition, scores}` rows plus the interim
metrics and an `as_of` stamp — the dashboard/agent surface. The envelope is
process output, not persistence; a caller who wants a durable copy captures
it.

The pass **persists** through the log, via the transcript (in-flight
samples): each held-state score is a `ScoreEvent(intermediate=True)` on the
sample's live transcript, so it persists through the realtime sample buffer
immediately and rides into the final log when the sample completes — and
into a *recovered* log if the run dies (the buffer is exactly what `inspect
log recover` reads). `EvalSample.scores` is untouched: intermediate events
never populate final scores, an invariant `score()` already established.

Completed samples' log records are already written (or buffered for write),
and injecting scores into them mid-run would be a log mutation with no safe
path — one of the reasons the pass doesn't score them at all (see "Completed
samples"); `inspect score` after the run is their path into the log. (An
on-disk scores sidecar as an additional durable record was considered and
dropped — see "Alternatives considered".)

## Job model

Scoring is minutes-long work, and the control-channel transport assumes
short requests (busy retry budgets, agents' timeouts). So the directive is a
**start + poll** pair:

- `POST /tasks/<task-id>/score` starts a pass and returns immediately:
  `{target, applied: true, pass_id, targeted: {in_flight, completed_unscored,
  completed_scored, skipped}}`. One pass per task at a time: a start while
  one is running is the idempotent no-op (`applied: false`, the running
  pass's id and progress in `detail`) — an agent retrying on confusion never
  stacks passes.
- `GET /tasks/<task-id>/score` reports the current (or most recent) pass:
  `{pass_id, running, progress: {scored, failed, unscored, total}, as_of,
  result?}` (`unscored` counts in-flight samples the pass never attempted —
  completed on their own mid-hold, or never parked — plus held samples every
  scorer declined to score (returned `None`), kept apart from `failed`,
  which counts genuine scoring failures)
  with per-sample rows and interim metrics once complete. Pass state is
  in-memory, in a module-level task-keyed registry (deliberately off the
  `EvalState`, so the most recent pass survives an attempt supersede and
  the poll can still report it); in-flight samples'
  scores additionally persist as transcript events, and a caller
  who wants a durable record of the envelope captures the `--json` output.
- Per-sample scorer failures are recorded on the row and don't fail the
  pass. A pass outlives nothing: a retry superseding the attempt cancels a
  running pass outright (`cancel_score_pass`, fired from
  `detach_eval_live`), task finish / cancel is caught by the
  between-samples supersede check, and the poll reports the pass as
  interrupted with whatever partial rows it produced.

The CLI wraps the pair: start, then poll with progress rendering; `--no-wait`
for the fire-and-poll agent loop, with `--status` as the poll-only follow-up
(see the command surface above).

## Hazards, named

- **Held wall-clock.** Every scored in-flight sample stops for the duration
  of its own scoring, and `time_limit` deadlines keep running while held.
  That's the accepted price of coherence for an on-demand "should I keep
  spending?" check — but it makes the v1 pass the wrong tool for
  *recurring* watchdog/dashboard polling, where periodic holds would
  perturb the thing being measured; the deferred no-hold snapshot mode
  (shape 1) is the full remedy there, and `--completed-only` gives
  recurring pollers hold-free interim metrics over completed samples in
  the meantime. Per-sample rows carry the held duration so the cost is
  visible.
- **Resource contention.** Scorer model calls share the process's connection
  limits (adaptive controllers included) with the running eval, so a pass
  *will* slow the run while it executes. That's inherent — the same model
  capacity serves both — and the existing `ctl config` knobs
  (`--max-connections`) are the throttle. Samples are held (and scored)
  one at a time so the pass contends gently — and a held sample's parked
  calls release their connection slots while parked (see shape 3), so the
  pass's own graders can't starve behind the hold.
- **Sandbox perturbation.** The pass's scorers see the sample's *live*
  sandbox. The hold means the agent isn't executing while its scorer runs —
  which narrows both directions of interference (a scorer perturbing an
  agent mid-action; an agent observing concurrent scoring activity) — but
  doesn't remove the caveat: mutations persist after release (a cleanup
  script's deletions, a stray grader artifact in the workspace is
  contamination the agent sees on resume), and background processes keep
  running through the hold. The documented caveat is the answer — scorers
  must be read-only with respect to the environment to be safely
  interim-scorable; a declarative per-scorer/per-task marker was considered
  and rejected as not worth the machinery (see "Alternatives considered").
- **Interim-score semantics.** An interim score describes the held moment;
  by the time it's read the sample has moved on. The `as_of` stamps and the
  `intermediate` flag keep this honest everywhere the scores surface.
- **Partial-epoch reduction.** Interim metrics reduce over incomplete epoch
  sets; the envelope carries the completed/total counts so a consumer can
  weigh the number.
- **Grader-model divergence.** The pass uses the task's own scorers and
  model roles as resolved at eval start (the task definition is fixed
  mid-flight — a control-channel non-goal). A `--scorer` / `--model`
  override like `inspect score`'s is deliberately out of scope for v1.
- **Cancellation vs streamed partials (merge ordering with #4853).** The
  deadline-cancel handler in `Model._generate` completes a still-pending
  ModelEvent so it can't pin phantom activity on a held sample — and since
  streaming callbacks (upstream #4853) landed first, that handler also
  calls `discard_partial_output()` before completing, so a cancelled
  attempt's partial streamed snapshot is never serialized into the log as
  if it were a response (the same rule as the provider-error paths).

## Version skew & security

- **No `CONTROL_API_VERSION` bump.** New endpoints need none (the
  missing-route 404 policy): the CLI passes `not_found_missing_route` and an
  older server yields the definitive "older inspect — restart the eval"
  message. Params on the new mutation route (the `POST`) are born strict
  (the app-wide unknown-query-param rejection short-circuits on safe
  methods, so the `GET` poll route stays tolerant like every other read).
- **Security posture.** Non-destructive mutation over the local AF_UNIX
  socket, like `log-flush`: idempotent, dry-runnable from day one, and it
  neither ends samples nor changes eval behavior (beyond the contention
  noted above). It rides on the shipped access model — filesystem
  permissions plus the SO_PEERCRED / LOCAL_PEERCRED peer-UID check (see
  [`security.md`](security.md)) — like the other non-destructive
  mutations.

## Phasing

Phases 1 and 2 together are the initial implementation (shipped):

1. **Pass plumbing + completed-sample fold.** The endpoint pair, job model,
   dispositions, the existing-final-scores fold, interim metrics, the
   result envelope. No runner changes; this slice already delivers interim
   metrics over everything scored so far (in-flight samples report as
   skipped until phase 2; `--no-score` runs are rejected outright — no
   scorers are published, see "Which samples"). Mid-run re-scoring of
   completed-unscored samples originally shipped in this slice and was
   subsequently removed — see "Completed samples".
2. **In-flight pause-and-score (the headline).** Two slices, in order.
   First the **publication + scoring context**: the `ActiveSample`
   publication (live `TaskState`, sandbox environments, target), the
   pass's scoring context, `ScoreEvent(intermediate=True)` recording,
   per-sample results into the pass — on its own this already enables the
   hand composition with `ctl task pause --now` / `resume` (the coarse
   whole-task form described under shape 3). Then the **per-sample hold**
   (sample-keyed gate at `wait_generate_dispatch`, wait-for-park ack, hold
   timeout, latch independence, release-on-completion), which makes the
   holds per-sample and retires the hand steps.
3. **Later.** The deferred in-context companion (shape 1) as an opt-in
   no-hold snapshot mode for recurring polling (spawn point, snapshot copy,
   cancel-on-completion, budget isolation — `suspend_token_limit()` /
   `suspend_turn_limit()` prior art, cost-limit equivalent to be added);
   `ctl sample score` (per-sample variant); surfacing the latest
   interim score in `ctl sample list` rows; scheduled/periodic passes
   (`--every`, or shell composition with a watchdog loop).

`control-channel.md`'s endpoint table and CLI hierarchy carry shipped
entries for the directive that point back to this doc (rather than
duplicating its detail).

Implementation notes on the shipped build (details the doc left to pin
down): the quiescence predicate is the park ack (≥ 1 parked generate
attempt) plus a transcript-settle window — no new events across the window,
using the shared transcript as the non-generate activity signal, *and* no
pending events on it (a sibling branch mid tool call emitted its ToolEvent
at call start, so silent in-flight work is visible only through the pending
sidecar; parked generate attempts themselves have no pending event — the
gate is awaited before the attempt's ModelEvent is created) — with a sample
whose transcript never settles timing out to the "did not park" row. The
park ack and the yield-to-the-sample watch are event-driven (a park waiter
fired from the gate's held accounting, and a terminal event on the
`ActiveSample` set by complete/interrupt/limit), not polled; a synchronous
terminal re-check immediately before each `ScoreEvent` append is the
correctness backstop for a sample completing in the same tick a scorer
returns (the score is dropped as superseded rather than recorded onto a
finalizing transcript). The hold timeout is a constant (120s), as is the
per-sample scoring deadline (600s — with one pass per task at a time, an
unbounded scorer would wedge the directive); in-flight samples are held
strictly one at a time, with the sample's scorers running concurrently
inside the hold so hold time tracks the slowest scorer rather than the sum.
The scoring context binds the eval's resolved `GenerateConfig` (so interim
grader calls run under the settings final scoring uses), the sample's
sandbox environments *with* the default-sandbox binding sample init sets up
(so `sandbox()` works in scorers), and the pass task is spawned in a fresh
(empty) context, making the no-sample-binding properties hold even if a
start were ever issued from in-sample code. A parked attempt releases its
connection-pool slot while parked (see shape 3). A grader call the deadline
(or a completing sample) cancels mid-flight completes its pending
`ModelEvent` rather than leaking it (the model layer now completes pending
events on cancellation, not just on exceptions). The recorded intermediate
event carries no `model_usage`/`role_usage` snapshot (unlike task-authored
`score()`'s — the sample's usage is context-bound and not reachable from
the pass), and the pass envelope does not yet report scoring usage
separately (the budget-isolation invariant itself is enforced and tested;
the usage reporting is deferred). In result rows, `scorer_errors` is keyed
by scorer name only; pass-level failures (the scoring deadline, a sample
with no live state yet) travel on the row's `reason` field.

## Open questions

1. **Scoring errored samples — deferred.** The table above mirrors the
   eval's resolved `score_on_error` flag. A `--include-errored` override
   for triage ("how close did the failures get?") is deferred for potential
   later implementation: not in v1, revisit if an operator asks for it.
2. **Eval-set aggregate.** The pass is per-task, consistent with the `ctl`
   surface today; an eval-set-wide "score everything running" is shell
   composition (`ctl task list --json | jq ... | xargs`) until the eval-set
   noun group exists.
3. **Hold-timeout policy — resolved: constant to start.** v1 ships with a
   hardcoded timeout (a few minutes; exact value pinned during
   implementation). Deferred until someone needs them: a `--hold-timeout`
   operator knob, and distinguishing *why* a sample timed out ("mid long
   tool call" — retry later might catch it — vs. "solver no longer calls
   models" — retrying never helps; the activity accounting could tell
   them apart).

## Alternatives considered

- **Cancel-with-score, then requeue.** Compose the existing destructive
  primitives: `sample cancel --action score` followed by `sample requeue`
  (since built — [`sample-requeue.md`](sample-requeue.md)).
  Rejected: requeue restarts the sample from scratch — the in-flight work is
  scored but then *discarded*, which inverts the point of a non-destructive
  interim score.
- **Post-hoc `inspect score` pointed at the live log + buffer.** Make
  `inspect score` read a running eval's log and sample buffer directly from
  a second process. Rejected: it races the writer (the log is mid-write; the
  buffer is being pruned on every flush), duplicates the reconstruction
  logic the server can do authoritatively, has no sandbox access, and puts
  scorer model load in an unmanaged second process. The control channel
  exists precisely so external tools direct the process that owns the state.
- **Task-authored periodic scoring.** Solvers can already call `score()` on
  a timer. Rejected as *the* answer: it requires anticipation by the task
  author, doesn't cover completed samples, and gives the operator no
  on-demand trigger — but it's the same underlying machinery, and tasks that
  author it get logs that look identical to this feature's.
- **Recovery populating scores from interim events.** `inspect log recover`
  could fill a reconstructed in-progress sample's `scores` from its latest
  `ScoreEvent(intermediate=True)` — the events do reach the sample buffer
  recover reads (see "Results: reporting and persistence"). Rejected: it
  would silently promote a
  mid-run held-moment score into the position of a final score, changing
  recovered-log semantics for every downstream consumer. The events remain
  visible in the recovered transcript for anyone who wants them;
  `EvalSample.scores` stays final-scores-only, the invariant `score()`
  established.
- **A declarative "safe for interim scoring" marker on scorers** (scorer
  metadata or a task-level flag) to gate the pass away from
  sandbox-mutating scorers. Rejected: not worth the machinery — the
  documented read-only caveat (see "Hazards") is the answer, and no
  decorator/marker is planned.
- **A scores sidecar on disk** (e.g. `<log-location>.scores.jsonl`): an
  append-only JSONL of pass results next to the log, as a durable
  record beyond the envelope and the transcript events. Rejected: its
  only irreplaceable payload is a cross-pass time
  series of interim metrics, which nothing needs yet. Completed-unscored
  samples — the scores with no other durable home — are near-nonexistent
  on normal runs (samples score inline at completion), and `--no-score`
  runs can't run a pass at all (no scorers are published) — their operator
  has committed to a post-run `inspect score`, which writes scores into a
  proper rewritten log; the envelope covers the "numbers now" need. Not
  worth a new file type next to the logs (glob
  collisions for log-dir consumers, no S3 append primitive, retention
  questions). If a durable pass history is ever needed, this is the shape
  to revisit.
- **Handler-side reconstruction.** Covered in "Mechanics" — rejected for
  in-flight fidelity (sandbox, store); its mid-run application to
  completed-unscored samples shipped initially and was removed (see
  "Completed samples").
- **In-context cooperative scoring as the initial in-flight shape.** The
  original proposal's choice — deferred to phase 3, not rejected (shape 1
  in "Mechanics"): the pause gates shipping first made pause-and-score the
  cheaper, higher-fidelity v1, while the companion's never-delay-the-sample
  property remains the right answer for recurring polling.
