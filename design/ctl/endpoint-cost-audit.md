# Ctl endpoint cost audit — the "cheap shoveling" invariant

Audit of every control-channel endpoint against the invariant below, prompted
by a control-channel incident (meridianlabs-ai/inspect_ai#118). Audited at
`ef5fcba34` (2026-07-21), covering `src/inspect_ai/_control/` (`server.py`,
`state.py`, `events.py`, `messages.py`, `cancel.py`, `limits.py`, `buffer.py`,
`eval_state.py`) and the data-source paths they call into (`TaskLogger`,
the recorders, `read_eval_log_*`); extended at `2fc34e792` (2026-07-22) to
cover the control-surface work merged since: the pause/resume endpoints and
quiesce auto-flush (#4531, `pause.py`), config-PATCH persistence into eval
logs (#4575, `config_record.py`), and `GET /tasks`' per-row
`paused`/`quiesced` fields. The two remaining `_control/` modules are
checked but out of scope for the per-endpoint table: `discovery.py` is off the
request path entirely (per-PID discovery files written at startup, read by CLI
clients), and `strict.py` runs per mutation request but is O(declared query
params) route introspection, independent of payload sizes.

## Background: the incident

The control server runs as a task **on the eval's own event loop** (see
"Server lifecycle aligned with `eval()`" in
[`control-channel.md`](control-channel.md)). That is what makes directives
like cancel safe to fire from a route handler — and it is also what turns an
expensive endpoint into a self-DoS: CPU spent in a handler is CPU stolen from
the samples the endpoint exists to observe.

In the incident, `ctl sample list` did minutes of synchronous CPU per request
(re-summarizing 165 buffered transcript-heavy samples through
`EvalSample.summary()` / `textwrap.shorten` on every poll), a 30-second poller
queued ~180 requests, and the process spent hours serving stale polls while
samples starved. Client timeouts don't help: uvicorn keeps processing queued
requests after the client hangs up, and a CPU-bound handler blocks the loop so
the disconnect isn't even noticed.

The specific bug was fixed by computing summaries once at buffer time
(meridianlabs-ai/inspect_ai#116; see `_BufferedSample` in
`log/_recorders/eval.py` and `JSONLogFile.summaries` in
`log/_recorders/json.py`). This audit checks every other endpoint for the
same class of defect.

## The invariant

> **Every ctl endpoint must be cheap shoveling of already-materialized data.**
> No per-request CPU proportional to *payload* sizes (transcripts, message
> histories, metadata blobs). Anything expensive must be computed once at
> write time, off the request path.

What the invariant permits and forbids, concretely:

- **Row-count-proportional work is acceptable.** Building a listing from N
  small, already-thinned summary objects is O(N) over cheap dicts — the
  constant is what matters. This is why the `/samples` row cap not bounding
  the listing build (the `counts` histogram needs the full listing) is fine:
  the full build is over cached summaries, not over transcripts.
- **Payload-proportional work is not.** Parsing, validating, summarizing, or
  serializing a sample's transcript / conversation / metadata on the request
  path scales with what the eval produced, which is unbounded. `thin_data`
  (a.k.a. `EvalSample.summary()`), `model_validate` over an event list, and
  attachment resolution are all in this class.
- **Async I/O is not a free pass.** An `await`ed remote read yields the loop,
  but the parse/validate of what it fetched runs synchronously on the loop —
  and repeating an idempotent read per poll multiplies both.
- **"The endpoint's job" work is allowed but must be idempotent-cheap on
  repeat.** `log-flush` writes the log — that is the point — but a retrying
  client queueing N flushes must get N−1 cheap no-ops, not N writes.

## Per-endpoint audit

**Log-format scope.** The terminal-path analysis below (the "Fallback /
terminal path" column and the per-section terminal notes) assumes the default
`.eval` log format unless it says otherwise. Terminal reads dispatch by file
extension: `.eval` lands in `EvalRecorder` (pre-thinned `summaries.json`,
ijson field exclusion — the mitigations the sections below describe), while
`--log-format=json` inherits `FileRecorder`'s read methods, which have none
of them — every `.json` terminal read is a whole-log parse and the listing
fallback re-summarizes full samples per request. That is finding 2, and it
overlays every ⚠️/❌ terminal cell in the table for `.json` logs. Note that
`.json` is a legacy format with poor performance characteristics throughout
(whole-log reads are inherent to its layout), so `.json`-only defects are
documented here but low priority to fix.

| Endpoint | Live path | Fallback / terminal path | Verdict |
|---|---|---|---|
| `GET /tasks` | O(states + active samples) grouping over counters | Deferred per-log stats: once-only, memoized | ✅ holds |
| `GET /evals/{id}/samples` | O(rows) over cached summaries + pending synthesis | One log read, memoized on `EvalState` (finding 3 — fixed) | ✅ holds (`.json` pays finding 2's parse on the first read only) |
| `GET /evals/{id}/sample` (error detail) | O(active samples) scan | Streamed sample scan + a summaries row served from finding 3's memo | ✅ holds (finding 4 — fixed by finding 3's memo) |
| `GET /evals/{id}/sample/events` | Paged, bounded by `limit` | Full-transcript parse **per page** once flushed to disk | ❌ finding 1 |
| `GET /evals/{id}/sample/messages` | O(conversation) copy + truncating projection | Excluded-field scan + attachment resolution | ✅ holds (payload = the response; terminal `tail` reads — watch item) |
| `POST /tasks/{id}/log-flush` | Full-log write (the endpoint's job); repeats are no-ops | — | ✅ holds |
| `POST .../cancel` (task, sample) | O(active samples) scans | Sample cancel's no-op branch reads error detail (inherits finding 4) | ✅ holds |
| `GET`/`PATCH /config`, `/tasks/{id}/config` | O(registry entries); PATCH writes applied changes to live logs | — | ✅ holds |
| `POST /pause`, `/resume`, `/tasks/{id}/pause`, `/tasks/{id}/resume` | O(1) gate flip; pause runs the quiesce auto-flush (log-flush's write, same idempotency) | — | ✅ holds |
| `POST /keep`, `/release` | O(1) | — | ✅ holds |

### `GET /tasks`

Groups `EvalState` counters and `active_samples()` rows — all small,
in-memory, maintained at write time by the `record_sample_*` hooks. The one
expensive step, `resolve_deferred_sample_stats` (per-reused-log summary
reads), is deliberately lazy and **once-only**: the provider is claimed under
the registry lock before the read, so concurrent first requests perform at
most one read; a failed read leaves the provisional header-derived values
permanently (no retry storm); only a cancellation restores the claim for a
later retry. Bounded and confirmed. The per-row `paused`/`quiesced` fields
added by #4531 keep the listing counter-shaped: `task_pause_sources` and
`task_dispatched_count` are O(1) lookups against in-memory gate state and a
dispatch counter maintained at the sample gate (write time), not derived per
request.

### `GET /evals/{id}/samples`

**Live path — holds.** Both recorders now cache each sample's summary at
buffer/log time; `sample_summaries()` is pure list building (its docstring
pins this). The per-row projection (`_summary_from_eval_sample_summary`)
sums a small `model_usage` dict and copies scalar fields — no large-field
access, no re-validation. Summaries were already thinned (`thin_data`) when
created, so response rows are size-bounded. Confirmed: nothing on the live
path re-validates or serializes large fields.

**Row cap doesn't bound the build — acceptable.** The full listing is built
before capping because the `counts` histogram must cover every sample. That
work is row-count-proportional over cached summaries — the acceptable class.
Two sub-costs worth naming:

- *Pending-row synthesis* builds a dict per planned-but-unstarted
  `(sample_id, epoch)` pair per request — O(dataset × epochs) while the eval
  runs. For a 10k-sample × 10-epoch grid that is ~100k small dict builds per
  poll: still row-count work, but the largest constant on this path. It is
  already skipped under `filter=errors`, and a finished eval drops its
  `sample_ids` (nothing pending), so the exposure window is "very large grid,
  mid-run, unfiltered polling". If this ever shows up in practice, the
  synthesized rows are pure functions of `(sample_ids, epochs)` minus the
  seen-set and could be memoized on `EvalState`.
- *`all=true`* uncaps the response — see "Response serialization" below.

**Fallback path — findings 2 and 3.** Once the live recorder is gone (eval
finished and torn down, reused log, superseded retry attempt),
`_completed_sample_summaries` falls back to
`read_eval_log_sample_summaries_async(log_location)` — a per-request re-read
of the log's summaries (for `.eval`: zip open, central directory,
`summaries.json` parse — or, for a log missing it, the per-sample journal
members; the two are exclusive alternatives, and on a finalized log the only
journal cost is a central-directory filename scan — plus `EvalSampleSummary`
validation for every sample), possibly from S3. The data is immutable at that point (the log is
finalized), so every re-read after the first is pure waste. This is exactly
the incident's shape — a keep-alive-parked process being polled every 30s.
For `.eval` logs it is minus the worst constant (summaries are pre-thinned,
so it is row-count work with a validation constant, not transcript work) —
finding 3. For `.json` logs the constant *is* the incident's:
`FileRecorder.read_log_sample_summaries` re-runs `EvalSample.summary()` over
every full-size sample on every request — finding 2.

*Fixed (finding 3):* `_sample_summaries_from_log` now memoizes the read on
`EvalState.log_sample_summaries` — one read per finalized log, later polls
served from memory; the retry sweep clears the memo when it deletes a
superseded attempt's log (`invalidate_log_sample_summaries`). The memo also
shields this endpoint's fallback for `.json` logs (finding 2's parse is paid
once, not per poll), though finding 2's other terminal readers remain.

### `GET /evals/{id}/sample` (error detail)

**Running path — holds.** One `active_samples()` scan; error history comes
off fields already on the `ActiveSample`.

**Terminal path — mostly holds on `.eval`, inherits finding 3, one linear
scan.** `_full_sample` excludes the heavy fields (`messages`, `events`,
`store`, `attachments`, `output`); for an `.eval` log the exclusion is
applied at *parse* time (`_read_member_json_excluding` in `_recorders/eval.py`
streams the member with ijson and never builds or validates the excluded
subtrees). The stream still scans the full member's bytes — linear in sample
size, but with a small constant and no pydantic validation of the heavy
fields; acceptable, though worth knowing it is not O(error-fields). For a
`.json` log, `FileRecorder.read_log_sample` ignores `exclude_fields` and
parses the *whole log*, mitigated only by the single-entry parse cache —
finding 2. The subsequent "pick this sample's summary row" step calls
`_completed_sample_summaries` — the entire listing — which is cheap on
the live path (cached) and, since finding 3's memo landed, on the fallback
path too (previously a *second* full summaries read per request —
finding 4, fixed). The response's
`error_retries` carry full tracebacks (message + plain + ANSI) per retry —
proportional to retry history, bounded in practice by retry limits.

### `GET /evals/{id}/sample/events` — finding 1

The checklist question was whether page assembly is bounded by `limit` rather
than total transcript size. Three sources, three answers:

- **Running sample — bounded.**
  `TranscriptHistory.events_from(offset, limit)` serves resident events from
  memory and materializes evicted ones from the realtime buffer with the
  `limit` riding down to the buffer query.
- **Terminal, streaming-completion sample not yet flushed — bounded.** The
  recorder's retained sample is event-less; pages go through the eval's
  buffer-backed events provider, again `limit`-bounded.
- **Terminal, flushed to disk — NOT bounded.** `_logged_source` calls
  `_full_sample(...)` with **no `exclude_fields`**: the entire sample —
  including its full event list — is read, JSON-parsed, and
  pydantic-validated per page request, then sliced in memory
  (`events[start:start+limit]`). The parse/validate runs synchronously on
  the eval's loop. A client paginating an N-event transcript performs
  ⌈N/limit⌉ full-transcript parses — O(N²/limit) aggregate work — and a
  *poller* (`--follow`-style usage re-issuing the cursor) pays a full
  transcript parse per poll even when zero new events exist (a finished
  sample never has new events, but the source is re-resolved every time).
  (That per-page-reparse profile is the `.eval` path; on `.json` the first
  page parses the *whole log*, after which pages of the same log hit the
  single-entry parse cache — finding 2's cost profile instead.)

This is the most severe invariant violation on the default `.eval` path. The
`_full_sample` read is also needed just to derive the cursor nonce
(`sample.uuid` + `error_retries` count) before the events are touched, so
even the buffer-provider branch pays it (free in-memory pre-flush, full parse
after).

### `GET /evals/{id}/sample/messages`

The response *is* the conversation, so O(conversation) work is the endpoint's
job rather than overhead. Running path copies the live message list
(loop-shared, so the copy is coherent) and projects with truncation
(`_TRUNCATE = 256` per field) — response size bounded per message. Terminal
path excludes `events`/`store`/`output` at parse time (`.eval`; on `.json`
the whole log is parsed regardless — finding 2) and resolves
attachments in `core` mode (messages only, not events) — linear in
conversation size, once per request. One caveat: `tail` bounds the
*response*, not the *read* — the parse and attachment resolution cover the
whole conversation before the slice (`sample_messages` tails afterwards),
and once the sample is finished that source is immutable, so a watcher that
polls until it notices the terminal `status` re-pays the full-conversation
work per poll. By this audit's own "immutable sources must not be re-read
per request" criterion that is a watch item — finding 1's
polling-amplification shape at a smaller constant (events are excluded
here) — and the terminal-source cache of finding 1(a) would cover it.
`full=true` with no `tail` serializes the raw conversation — see "Response
serialization". Deliberately
snapshot-not-cursored (the list is rewritable), so a poller re-transfers the
conversation each poll; the compact projection and `tail` exist to keep that
cheap, and the envelope's `count` is the documented staleness signal to avoid
re-pulling at all.

### Mutations: `log-flush`, cancel, config, pause/resume

- **`log-flush` — idempotent under a retrying client, confirmed.** All flush
  paths funnel through `_flush_pending_samples`, serialized by
  `_flush_lock`; the pending list is drained under the lock, so N queued
  requests behind one slow (possibly S3) flush each acquire the lock in turn,
  find nothing pending, and return `flushed: 0`. Queued no-ops cost a lock
  acquire each — they cannot re-trigger the write. The write itself
  serializes buffered samples into the zip (pydantic dump + zstd) on the
  loop — the same cost the eval's own threshold flush pays, i.e. the
  endpoint's job, not added overhead; the local-file copy runs in a worker
  thread and the remote upload streams through `AsyncFilesystem`.
- **Cancel (task / sample) — holds.** O(active samples) scans over small
  objects; firing `TaskCancel` / `ActiveSample.interrupt` is O(1) on the
  loop it must run on anyway. The sample-cancel "already finished" no-op
  branch reads `sample_error_detail`, inheriting that path's fallback costs
  (finding 4) — acceptable for a mutation's terminal-state check.
- **Config GET/PATCH — holds.** Views enumerate concurrency registries and
  controller history tails (`_RECENT_CHANGES = 5`) — O(registry entries),
  all small. Since #4575 a PATCH also persists: applied changes are grouped
  into `ConfigUpdate` records (`config_record.py`) and written into every
  affected task's live log (task scope → one log; process scope → every live
  task log, plus a run-scoped inherited-updates list new loggers catch up
  from). Records are written **only when a directive actually changed
  something**, so a retried or no-op PATCH writes nothing — invariant-
  compliant by the mutation rule. The per-log write is a small journal
  member plus a push of the buffered zip to the destination on `.eval`
  (`log-flush`'s write class, paid per applied retune — operator-rate, a
  handful per run — not per poll; `.json` accumulates in memory until the
  next flush). Recording failures degrade to `persisted: false` in the
  response without failing the retune, and a finished log declines the
  record rather than erroring.
- **Pause / resume (task and process) — holds.** Four endpoints added by
  #4531 (`pause.py`). The latches are plain in-memory gates: pause/resume is
  an O(1) flag flip plus waking parked waiters and dispatchers (O(waiters),
  all cheap resumptions). The one expensive step is deliberate: a pause that
  actually changes state runs `flush_quiesced_tasks()` — an O(eval states)
  scan plus `flush_samples()` for each quiesced (paused + zero dispatched)
  task, making the pause durable. That write funnels through the same
  `flush_samples`/`_flush_lock` drain as `log-flush`, with the same
  idempotency (nothing pending → `0`, no write), and a repeated `pause`
  returns `changed: false` *before* reaching the flush — a retrying client
  cannot re-trigger the write. `dry_run` never mutates or flushes.

### Response serialization (FastAPI JSON encoding on the loop)

Encoding the response body is loop CPU proportional to response bytes, so
response sizes are part of the invariant. Default shapes are bounded: the
samples listing defaults to 100 rows of thinned summaries; events pages
default to 500 events of truncated compact projections; messages truncate
per-message. Note these are *defaults*, not caps — neither endpoint clamps
`limit` upward (only `limit < 1` is rejected), so a bare oversized `limit`
uncaps either response and, on the live events path, rides down to the
buffer query and materializes an arbitrarily large page. That makes four
unbounded knobs, all relying on the caller knowing what they asked for —
the uncapped `limit` plus three explicit opt-outs:

- `samples?all=true` — the full row dump (rows are small; the grid may not be).
- `sample/events?full=true` — `limit` bounds the event *count*, not bytes; a
  single model event can carry a full conversation snapshot, so a 500-event
  full page can be tens of MB of `model_dump` + JSON encoding.
- `sample/messages?full=true` (especially with no `tail`) — the raw
  conversation.

All four are acceptable as deliberate drill-downs (constraint 2 in
control-channel.md already pushes defaults toward summaries), but any future
*default* response shape must stay bounded, and a byte-oriented cap on `full`
events pages is worth considering if agent tooling starts defaulting to it.

## Findings

Ranked. On the default `.eval` format none reproduces the incident's severity
(minutes of CPU per request) — finding 1 is the same *kind* of defect at a
smaller constant. Finding 2 *is* the incident's defect class verbatim
(per-request re-summarization of full samples), gated only by the non-default
`--log-format=json` — and since `.json` is a legacy format with poor
performance generally, it is low priority despite the severity of its
constant.

**What is actually worth fixing: findings 1 and 3.** Finding 2 is
legacy-format-only (see above). Finding 4's expensive half (the second,
full-listing read) disappears once finding 3's memo lands; its remaining
read is inherent to serving error detail and already parse-minimized, so it
needs no work of its own. **Findings 3 and 4 are now fixed** (the
`EvalState.log_sample_summaries` memo — meridianlabs-ai/inspect_ai#154);
finding 1 remains open.

1. **Events pages over a flushed sample re-parse the whole transcript per
   page** (`events.py` `_logged_source` → `_full_sample` with no
   `exclude_fields`). Per-request CPU proportional to total transcript size —
   an invariant violation. Amplified by pagination (O(N²/limit) to walk a
   transcript) and by cursor-polling a finished sample (full parse per poll,
   zero new data). Fix directions, roughly in order of appeal: (a) short-TTL
   cache of the resolved terminal `EventsSource` keyed by nonce — a finished
   attempt's transcript is immutable, so even a tiny cache collapses both the
   pagination and the polling amplification; (b) answer the "no new events"
   poll cheaply before resolving the source (the cursor offset vs. a cached
   `total` is enough); (c) an exclude-based two-step read (nonce fields
   first, then a paged event read) — more invasive, only worth it if (a) is
   insufficient.

2. **Every terminal read of a `.json`-format log re-parses and/or
   re-summarizes the full log per request** (`log/_recorders/file.py`:
   `FileRecorder.read_log_sample_summaries` / `read_log_sample`, inherited by
   `JSONRecorder`; `read_eval_log_*` dispatches by file extension). The
   listing fallback re-runs `EvalSample.summary()` — the `thin_data` /
   `textwrap.shorten` pass that was the incident's expensive operation — over
   every full-size sample on every request, *even when the parse is cached*.
   The parse cache (`_log_file_maybe_cached`) is a single class-level entry
   keyed by location, so a parked eval-set with several finished `.json` logs
   polled alternately also re-pays the full-log parse (all samples, full
   pydantic validation) per poll. And `read_log_sample` ignores
   `exclude_fields`, so the ijson streaming exclusion the error-detail and
   messages paths rely on does not exist for `.json`.
   meridianlabs-ai/inspect_ai#116 fixed the *live* `.json` path
   (`JSONLogFile.summaries` caches at log time); these terminal paths retain
   the per-request re-summarization defect. Payload-proportional per poll —
   the incident's class — but only under `--log-format=json`, hence ranked
   below the default-format finding 1; and because `.json` is a legacy
   format whose read performance is poor by construction, this finding is
   low priority. Fix directions, should it ever matter: cache computed
   summaries alongside the parsed log in `_log_file_maybe_cached` (fixes
   every reader, not just ctl), and/or the `EvalState` memo of finding 3,
   which shields the ctl listing path for both formats.

3. **Finished/reused evals re-read summaries from the log on every listing
   request** (`state.py` `_sample_summaries_from_log` →
   `read_eval_log_sample_summaries_async`). The log is finalized and
   immutable at that point; a keep-alive-parked process being polled re-pays
   the read (possibly against S3) every 30 seconds, per finished eval —
   the incident's request shape. For `.eval` logs it is
   row-count-proportional (summaries are pre-thinned), so the constant is far
   smaller than the incident's (the `.json` case is finding 2), but it is
   repeated waste on exactly the path designed for long-lived parked
   processes. Fix: memoize the summaries on `EvalState` once the live
   recorder is gone — `resolve_deferred_sample_stats` already demonstrates
   the claim-once pattern (including the cancellation-restores-claim
   subtlety); the memo must be invalidated by `detach_eval_live`'s sweep
   semantics (a superseded attempt's log can be deleted under it, and the
   current per-request read degrades to `[]` on `FileNotFoundError`).
   **Fixed** (meridianlabs-ai/inspect_ai#154):
   `EvalState.log_sample_summaries`, populated by the first fallback read in
   `_sample_summaries_from_log`. Invalidation happens at the deletion itself
   (`latest_completed_task_eval_logs`'s cleanup calls
   `invalidate_log_sample_summaries` per removed log) rather than at
   `detach_eval_live`: detach doesn't make the memo wrong (it holds the
   superseded attempt's *own* log data, valid until the file goes), and
   legacy batch-retry sweeps logs without any detach ever firing. A
   `FileNotFoundError` read is never memoized, preserving the `[]`
   degradation. No stale-memo race with an in-flight listing read:
   requests are served either on the eval's loop (running only inside an
   `eval()` call) or by the keep-alive park's own server, while sweeps run
   between `eval()` calls and before the park — never concurrently with a
   request.

4. **Error detail on the fallback path does two log reads per request**
   (`state.py` `sample_error_detail`): the excluded-field sample scan plus a
   full summaries listing read just to pick one row. Each is linear with a
   small constant (on `.eval`; finding 2 covers `.json`); together they make
   `ctl sample show` against a parked process a two-round-trip remote read.
   Fixing finding 3 fixes the second read for free; the first is inherent to
   serving error detail and already parse-minimized. Low priority on its own.
   **Fixed** by finding 3's memo (the summaries-row read is now served from
   memory after the first fallback read); the inherent sample read remains,
   as intended.

Watch items (bounded today, could grow constants): pending-row synthesis on
very large dataset × epoch grids (see the `/samples` section); `full=true`
response byte sizes (see "Response serialization"); terminal messages reads
under `tail` (the parse + attachment resolution cover the full conversation
before the slice, re-paid per poll against an immutable source — see the
messages section; finding 1(a)'s terminal-source cache would cover it).

## Structural guards

Cheap handlers are the real fix — every guard below failed open in the
incident only because the handler was expensive — but the failure mode
compounds silently, so guards are worth having. **None of these exist
today** (`uvicorn.Config` sets only logging + `timeout_keep_alive`; no
handler checks disconnects; no coalescing):

- **Pile-up guard.** `uvicorn limit_concurrency` rejects (503) rather than
  queues excess connections — a blunt but honest backstop against a
  pathological poller queueing unbounded identical work. Tracked as
  [meridianlabs-ai/inspect_ai#225](https://github.com/meridianlabs-ai/inspect_ai/issues/225).
  Coalescing identical
  concurrent listing requests (one in-flight build, late arrivals await its
  result) is the finer-grained version; only worth building if a legitimate
  multi-client pattern emerges.
- **Disconnect check.** An `await request.is_disconnected()` before
  nontrivial work skips serving hung-up clients. Tracked as
  [meridianlabs-ai/inspect_ai#226](https://github.com/meridianlabs-ai/inspect_ai/issues/226).
  Only useful if the loop
  yields between queued requests — which cheap handlers guarantee and a
  CPU-bound handler defeats; that ordering (handlers first, guard second) is
  the lesson of the incident.
- **The invariant in review.** New endpoints (drain / requeue / add-task,
  SSE) must be designed to the invariant — see the note added to
  [`control-channel.md`](control-channel.md), which is the doc future
  endpoint work starts from. SSE deserves particular care: a push stream's
  serialization also runs on the eval's loop, per subscriber, continuously.

## Guidance for future endpoints

Distilled from the audit, for the phase 3-4 surface still to come:

1. Serve from data materialized at write time (counters, cached summaries,
   buffer DB pages). If a read needs something expensive, compute it where
   the data is written (like `_BufferedSample`) or once-and-memoized on first
   request (like `resolve_deferred_sample_stats` — including its
   claim-under-lock and cancellation-restore details).
2. Bound every response: row caps with a structural `truncated` flag,
   page limits that ride down to the storage query, truncating projections
   with `full`/`all` as explicit opt-outs.
3. Immutable sources (finalized logs, finished attempts) must not be re-read
   per request.
4. Mutations may be expensive once but must be cheap on retry (drain the work
   under a lock; report `changed: false` / zero-work no-ops).
5. Remember the loop is shared: async I/O yields, but parse / validate /
   serialize of what it fetched does not. Measure handlers against "what does
   a 30-second poller cost the eval over an hour?"
