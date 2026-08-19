# Interim scoring: score a running eval's completed and in-flight samples

> **Status: design proposal** (meridianlabs-ai/inspect_ai#91). Nothing described here is
> built yet — but the pause-gate machinery the `--pause` mode depends on has
> since shipped as the hard pause (`pause --now`, meridianlabs-ai/inspect_ai#103; see
> [`ctl/pause-resume.md`](ctl/pause-resume.md)), and shape 3 below is now
> specified against it rather than sketching new gates. The control-channel
> context this builds on is in
> [`control-channel.md`](ctl/control-channel.md); the partial-sample persistence
> machinery referenced throughout is described in [`recover.md`](recover.md).

The feature: a **non-destructive control-channel directive** — `inspect ctl
task score` — that runs the task's scorers over every scoreable sample of a
*running* eval (both completed samples and a snapshot of in-flight ones),
computes interim metrics, and persists the results to disk and to the logs.

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
| `ctl task pause --now` (and model/process scope) | holds in-flight samples at their next model call, state stable while held | holds but doesn't score — no snapshot, no scorer run, no interim metrics; this design's `--pause` mode composes it with scoring |
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
inspect ctl task score [TASK] [--dry-run] [--pause] [--no-wait] [--json]
```

- `TASK` follows the mutation selector rule (sole running task is the
  default; several running tasks require the selector). Unlike `task cancel`
  it is *not* required outright — the directive is non-destructive, so it
  sits with `log-flush` on the selector-optional side.
- `--dry-run` reports what would be scored (counts by sample disposition —
  see "Which samples" below) without scoring anything.
- `--pause` (maps to a `pause` query param) briefly holds each in-flight
  sample at its next model call — a per-sample application of the shipped
  hard-pause gate — while its own scoring runs, trading sample wall-clock
  for a coherent view of live state + sandbox — see shape 3 under "The
  context problem". Off by default: the snapshot mode never delays the run.
- The pass can take minutes (model-graded scorers over hundreds of samples),
  so the HTTP shape is **start + poll**, not one long request (see "Job
  model"); by default the CLI polls to completion and renders progress, and
  `--no-wait` returns the started-pass envelope immediately (the agent
  re-polls with a repeat invocation).
- `--json` everywhere, per the agent output contract.

HTTP endpoints, task-keyed like `config` / `log-flush` / `cancel` (a task id
never dangles across a retry):

| Operation | Endpoint |
|---|---|
| Start a scoring pass | `POST /tasks/<task-id>/score?dry_run=<bool>` |
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
| **In-flight** (started, not terminal) | scored on a **snapshot** of its work so far (the headline capability) |
| **Completed, unscored** (the eval ran with `--no-score`, or a scorer previously errored) | scored from its serialized form — the `inspect score` recipe applied mid-run |
| **Completed, scored** | *not* re-scored (the task's scorers are fixed at eval start, so re-running them buys nothing); its existing final scores are included in the interim metrics |
| **Errored / cancelled** | follows the task's `score_on_error` policy — scored if final scoring would score them, otherwise skipped |
| **Queued / pending** | skipped — nothing to score |

"Partially completed" in the issue title is the in-flight row: a sample with
real work in its transcript that hasn't reached its solver's end. The
completed-unscored row makes the directive double as *mid-run* deferred
scoring for `--no-score` runs (today those wait for `inspect score` after the
fact) — and with `--ctl-server=keep`, a parked finished eval can be scored
through the same surface.

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

Three shapes can score an in-flight sample without ending it:

1. **In-context cooperative scoring (chosen as the default mode).** Each running sample services
   score requests *from inside its own context*: the runner spawns a small
   companion task inside the sample's task group at sample start, parked on a
   request signal published via the `ActiveSample` (the same object the
   control layer already reaches through `find_active_sample`). On request it
   deep-copies the live `TaskState` and runs the task's scorers against the
   snapshot via the existing `score()` machinery — recording
   `ScoreEvent(intermediate=True)` on the live transcript, exactly as
   task-authored intermediate scoring does — and posts the scores back to the
   pass. (The companion must be spawned from the sample's coroutine, not from
   the handler: anyio's `start_soon` gives the child a copy of the *caller's*
   context, so a handler-spawned task would be no better off than the handler.)

2. **Handler-side reconstruction (rejected for in-flight, reused for
   completed).** Rebuild a `TaskState` from the sample's serialized form —
   the recorder's `buffered_sample()` or the sample-buffer events, via the
   `_recover` package's `reconstruct_eval_sample` — and score it on the
   handler side, the way `_run_score_task` (`_eval/score.py`) does for logged
   samples. Rejected for in-flight samples because the reconstruction is
   low-fidelity exactly where agentic scorers care: **no sandbox access**
   (sandbox environments are per-sample context; scorers on agentic tasks
   routinely inspect the sandbox to score) and a store/state view limited to
   what events captured. It stays the right recipe for **completed** samples,
   where it is already proven — it's what `inspect score` does.

3. **Cooperative pause-and-score (opt-in mode on 1, via `--pause`).** The
   snapshot in (1) covers only in-memory state — the sandbox is shared, live,
   and keeps moving under the still-running solver, so a sandbox-inspecting
   scorer reads a sandbox that can drift from the `TaskState` snapshot it was
   handed. This mode restores coherence by *holding the solver* while its
   scoring runs. The gate machinery this shape originally sketched has since
   shipped as the hard pause (`pause --now` —
   [`ctl/pause-resume.md`](ctl/pause-resume.md), gate module
   `src/inspect_ai/_control/pause.py`): a `PauseGate` awaited at
   generate-attempt start (`wait_generate_dispatch`, gating `Model.compact()`
   too), per-task held-sample accounting (`task_held_count`, surfaced as the
   `held` count on `GET /tasks` rows), incremental waiting-time crediting so
   a held span never burns `working_limit`, cancel escalating over the hold
   via the gate's escape check, and last-write-wins pause/resume. A sample
   parked at that gate mutates its `TaskState` only from its own coroutine,
   so the live state is stable while held — no deep copy, no drift, sandbox
   reads coherent with the message history — and the compact gate means the
   conversation can't be rewritten under the scorer either.

   The shipped semantics settle several of the sketch's build requirements —
   this mode inherits them rather than reopening them:

   - **Park point: the next model call**, not every runner chokepoint (the
     hard-pause build deliberately gates only generate/compact; tool calls
     and sandbox commands in progress run to completion). So the ack
     protocol stands: request the hold, wait for the sample to actually park
     — the held accounting is exactly that signal — then score. A tool-heavy
     sample may take a while to reach its next model call; one that
     completes instead is reported as "completed before interim scoring
     finished", its final score superseding.
   - **Wall clock is the operator's risk.** `time_limit` deadlines keep
     running while held — deadline-shifting was considered and rejected in
     the hard-pause build, which drops the original sketch's "add pause time
     to `time_limit` deadlines" surgery. A scoring hold is minutes, not
     hours, but a sample near its deadline can expire while held; the pass's
     per-sample rows carry the held duration so the cost is visible.
     `working_limit` exclusion needs no new work — the shipped crediting
     already covers it.
   - **A parked call keeps its connection slot** (the trade-off the
     hard-pause build accepted). For a per-sample hold the exposure is
     bounded — one sample's concurrent calls — but the sketch's deadlock
     hazard survives in miniature: a run whose `max_connections` is at or
     near the held sample's parked-call count, with a grader on the same
     pool, starves the scorer. The release-and-reacquire escape hatch named
     in `pause-resume.md` is the remedy if it bites.

   What remains to build is the *per-sample* hold: the shipped gate
   registries key task / model / process, so `--pause` needs a sample-keyed
   hard hold consulted at the same `wait_generate_dispatch` site (which
   already resolves the active sample for the held count), plus the
   wait-for-park ack above, a hold timeout so a stuck scorer can't wedge the
   sample, independence from the operator latches (an unrelated `ctl
   task resume` must not release a scoring hold, nor the pass's release
   clear an operator's pause) — and a **scorer exemption**: the hard gate
   deliberately holds *every* generate in the sample's context, grader calls
   included, so without one a model-graded interim scorer would park at the
   very hold that exists for its benefit. The companion's scoring context
   must carry a pass token the sample-keyed hold checks, precedented by the
   gate's existing interrupt-escape check. Each sample holds only while
   *its own* scoring runs, not for the whole pass. Opt-in rather than
   default because
   a hold steals the scoring duration from every in-flight sample's
   wall-clock: fine for a one-off "should I kill this run?" check, wrong for
   the recurring watchdog/dashboard polling scenario, where it would turn
   periodic monitoring into periodic eval-wide stalls that perturb the thing
   being measured. Note the limit of what it buys: agent-launched
   *background* processes in the sandbox keep running (a true sandbox freeze
   is provider-specific — `docker pause` has no portable k8s/local
   equivalent), so this reaches parity with task-authored `score()`
   consistency, not absolute quiescence.

   Until built, a composition is available by hand from phase 1: `ctl
   task pause --now`, poll `task list` until the in-flight samples read as
   held, `ctl task score`, `ctl task resume`. Coarser than `--pause` — the
   whole task holds for the whole pass, and a sample still mid-tool-call
   when its scoring starts scores un-held (its row can say so: the pass
   checks the held state at snapshot time) — and bounded by the exemption
   gap above: the task-scope hard gate holds the in-context companion's own
   grader calls too, so under `task pause --now` the composition serves
   non-model-graded interim scorers, or model-graded ones via the
   model-scoped spelling (`ctl model pause --now` on the *solver's* model,
   when the grader is a different model). Within those bounds it needs zero
   new runner machinery, which is exactly why built-in `--pause` stays in
   the "later" phase.

The in-context shape buys full fidelity (real `TaskState`, live store, live
sandbox), free log persistence (the transcript event flows through the
realtime sample buffer into the final log), and semantic continuity with the
existing `score()` API. Its costs are runner changes and the concurrency
hazards named below.

### In-context scoring: requirements on the companion

- **Snapshot first.** The solver keeps running while scoring proceeds, so the
  companion deep-copies the `TaskState` (messages / output / store) at
  request time and scores the copy. The scores are stamped with the snapshot
  time (`ScoreEvent.timestamp` covers this). The copy covers *in-memory*
  state only — the sandbox is live and shared, so sandbox reads pair a
  read-time sandbox with a snapshot-time message history; `--pause` (shape 3
  above) is the coherence remedy when that matters.
- **Never delay the sample.** The companion runs in its own cancel scope;
  sample completion (or interrupt, or limit) cancels any in-progress interim
  scoring rather than waiting for it. The pass reports that sample as
  "completed before interim scoring finished" — its final score supersedes.
- **Never spend the sample's budget.** Scorer model calls must not count
  against the sample's token / time / message limits (an operator asking
  "how's it going?" must not be able to push a sample over its limit), and
  must not distort the sample's reported usage. Spawning the companion before
  the sample's limit scopes are applied keeps its context copy outside them;
  the pass envelope reports the scoring usage separately. The exact
  attribution mechanics (contextvar copies share mutable objects) are an
  implementation detail to pin down with tests.
- **One at a time.** A second request while a sample's interim scoring is
  running joins the in-progress result rather than double-scoring.

### Completed samples

Scored on the handler side with the `_run_score_task` recipe over the
sample's serialized form, sourced from the live recorder: the
completed-but-unflushed set via `Recorder.buffered_sample()`, flushed ones
read back from the log (the same running-vs-terminal split every read
endpoint already makes). Scoring runs on the eval's loop as async tasks,
bounded by a small concurrency cap so a large backlog can't starve the
running eval (model calls are additionally governed by the existing
connection limits — see "Hazards").

### Interim metrics

The pass ends by computing interim `EvalResults` over the union of:

- final `SampleScore`s of completed-and-scored samples (the same inputs the
  live display's periodic `compute()` uses),
- the pass's freshly computed scores for completed-unscored samples,
- the pass's snapshot scores for in-flight samples,

via the existing `eval_results()` machinery (the task's reducers and
metrics — the same path `recompute_metrics` uses for post-hoc recompute).
The result is labeled **interim** everywhere it surfaces: epochs may be
incomplete (a reducer over a sample's partial epoch set sees fewer values
than it will at eval end), and in-flight scores are snapshots by
construction. The eval's own `results` — computed at eval end — are entirely
unaffected.

## Persistence ("save scores to disk/logs")

Three sinks, complementary:

1. **The result envelope** (the `--json` output): per-sample
   `{sample_id, epoch, disposition, scores}` rows plus the interim metrics
   and an `as_of` stamp — the dashboard/agent surface.
2. **The log, via the transcript** (in-flight samples): each snapshot score
   is a `ScoreEvent(intermediate=True)` on the sample's live transcript, so
   it persists through the realtime sample buffer immediately and rides into
   the final log when the sample completes — and into a *recovered* log if
   the run dies (the buffer is exactly what `inspect log recover` reads).
   `EvalSample.scores` is untouched: intermediate events never populate final
   scores, an invariant `score()` already established.
3. **A scores sidecar on disk** (the durable aggregate): each pass appends
   one JSON line — `{as_of, run_id, eval_id, task_id, counts, samples,
   metrics}` — to a sidecar next to the log (e.g.
   `<log-location>.scores.jsonl`), written through the async filesystem
   layer so S3-backed log dirs work. Append-only JSONL gives a time series
   of interim metrics across repeated passes for free. A sidecar rather than
   a log rewrite because mutating a mid-write log is exactly what the
   view-server editing design refuses to do (`viewer_log_editing.md` rejects
   edits on `status == "started"` logs), and because the extension must not
   collide with log listing (`.jsonl` is invisible to `list_eval_logs`,
   which matches `.eval` / `.json`).

Completed-unscored samples' pass scores live in sinks 1 and 3 only: their
log records are already written (or buffered for write), and injecting
scores into them mid-run would be a log mutation with no safe path. Scoring
them *into the log* remains `inspect score`'s job after the run — the pass
gives the operator the numbers now, not a rewritten log.

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
  `{pass_id, running, progress: {scored, failed, total}, as_of, result?}`
  with per-sample rows and interim metrics once complete. Pass state is
  in-memory on the `EvalState` (like the counters); the durable record is
  the sidecar.
- Per-sample scorer failures are recorded on the row and don't fail the
  pass. A pass outlives nothing: task finish / retry / cancel tears it down,
  and the poll reports it as interrupted with whatever partial rows it
  produced (already appended to the sidecar).

The CLI wraps the pair: start, then poll with progress rendering; `--no-wait`
for the fire-and-poll agent loop.

## Hazards, named

- **Resource contention.** Scorer model calls share the process's connection
  limits (adaptive controllers included) with the running eval, so a pass
  *will* slow the run while it executes. That's inherent — the same model
  capacity serves both — and the existing `ctl config` knobs
  (`--max-connections`) are the throttle. The pass's own sample-level
  concurrency is capped (small default) so it contends gently.
- **Sandbox perturbation.** An in-context scorer sees the sample's *live*
  sandbox. Scorers that mutate sandbox state (run cleanup scripts, write
  marker files) can perturb the still-running agent — and the interference
  runs both ways: an agent can *observe* concurrent scoring activity (a
  stray grader artifact in its workspace is contamination). v1 documents the
  caveat — scorers must be read-only with respect to the environment to be
  safely interim-scorable; a per-task or per-scorer opt-out is an open
  question below. (`--pause` narrows the window — the agent isn't executing
  while its scorer runs — but doesn't remove the caveat.)
- **Snapshot semantics.** An interim score describes a moment; by the time
  it's read the sample has moved on. The `as_of` stamps and the
  `intermediate` flag keep this honest everywhere the scores surface.
- **Partial-epoch reduction.** Interim metrics reduce over incomplete epoch
  sets; the envelope carries the completed/total counts so a consumer can
  weigh the number.
- **Grader-model divergence.** The pass uses the task's own scorers and
  model roles as resolved at eval start (the task definition is fixed
  mid-flight — a control-channel non-goal). A `--scorer` / `--model`
  override like `inspect score`'s is deliberately out of scope for v1.

## Version skew & security

- **No `CONTROL_API_VERSION` bump.** New endpoints need none (the
  missing-route 404 policy): the CLI passes `not_found_missing_route` and an
  older server yields the definitive "older inspect — restart the eval"
  message. Params on the new routes are born strict (the app-wide
  unknown-query-param rejection).
- **Security posture.** Non-destructive mutation over the local AF_UNIX
  socket, like `log-flush`: idempotent, dry-runnable from day one, and it
  neither ends samples nor changes eval behavior (beyond the contention
  noted above). It can ship ahead of the phase-3 SO_PEERCRED hardening on
  the same reasoning as the buffer directives.

## Phasing

1. **Pass plumbing + completed samples.** The endpoint pair, job model,
   dispositions, `_run_score_task` over the live recorder's serialized
   samples, interim metrics, envelope + sidecar. No runner changes; this
   slice already delivers mid-run scoring for `--no-score` runs and interim
   metrics over everything scored so far.
2. **In-flight snapshot scoring.** The in-context companion (spawn point,
   snapshot copy, cancel-on-completion, budget isolation),
   `ScoreEvent(intermediate=True)` recording, per-sample results into the
   pass. This is the headline capability.
3. **Later.** `--pause` coherent-scoring mode (shape 3 — since `pause --now`
   shipped, a thin layer over the existing gates: sample-keyed hold,
   wait-for-park ack, hold timeout, scorer exemption; meanwhile the manual
   `pause --now` + score + `resume` composition covers part of the need
   from phase 1); `ctl sample score` (per-sample variant); surfacing the latest
   interim score in `ctl sample list` rows; recovery consuming intermediate
   scores (a recovered in-progress sample could carry its last interim score
   instead of no score — see open questions); scheduled/periodic passes
   (`--every`, or shell composition with a watchdog loop).

When this ships, `control-channel.md`'s endpoint table and CLI hierarchy
gain the corresponding rows (this doc is referenced from there rather than
duplicating the tables now).

## Open questions

1. **Sidecar location and lifecycle.** `<log-location>.scores.jsonl` keeps
   the artifact next to its log (and S3-compatible), but log-dir consumers
   that glob indiscriminately will see a new file type. Alternative: an
   `interim-scores/` subdirectory of the log dir. Retention (delete on
   successful eval end? keep always?) is also open — keeping always is the
   simple, honest default.
2. **Scoring errored samples.** The table above defers to the task's
   `score_on_error` policy; is there operator value in a `--include-errored`
   override for triage ("how close did the failures get?")?
3. **Sandbox-mutating scorers.** Is a declarative "safe for interim scoring"
   marker on scorers worth it (scorer metadata, or a task-level flag), or is
   the documented caveat enough until someone is bitten?
4. **Recovery integration.** Should `inspect log recover` populate a
   reconstructed in-progress sample's `scores` from its latest
   `ScoreEvent(intermediate=True)` (clearly marked), rather than leaving it
   unscored? It changes recovered-log semantics, so it belongs to a separate
   decision — but the events will be sitting right there in the buffer.
5. **Eval-set aggregate.** The pass is per-task, consistent with the `ctl`
   surface today; an eval-set-wide "score everything running" is shell
   composition (`ctl task list --json | jq ... | xargs`) until the eval-set
   noun group exists.

## Alternatives considered

- **Cancel-with-score, then requeue.** Compose the existing destructive
  primitives: `sample cancel --action score` followed by `sample requeue`
  (since built — [`ctl/sample-requeue.md`](ctl/sample-requeue.md)).
  Rejected: requeue restarts the sample from scratch — the in-flight work is
  scored but then *discarded*, which inverts the point of a non-destructive
  snapshot.
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
- **Handler-side reconstruction for in-flight samples.** Covered in
  "Mechanics" — rejected for fidelity (sandbox, store), kept for completed
  samples.
