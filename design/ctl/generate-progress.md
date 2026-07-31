# In-Flight Generate Progress

> **Status: layer 1 implemented** (activity indicator, including the `retry_wait` type per Open question 4); **layers 2–3 proposed.** Companion to [`control-channel.md`](control-channel.md), which owns the control-channel architecture and documented this gap twice (the Phase 1 `GET /evals/<id>/samples` caveat, and §"Trace-log anomalies for stall diagnosis"); this doc owns closing it. Originating issue: meridianlabs-ai/inspect_ai#158.

## Problem

While a sample is inside a long model call, `inspect ctl sample list` renders it as if it were hung: the `idle` clock climbs and `tokens` / `messages` stay flat. Observed on a live run (gpt-5-nano, one healthy 455s `generate()` with no retries):

```
sample             epoch  status   time  idle  tokens  messages  turns
recO3hvCWRGiG0odN  4      running  7:13  7:12  0       1         0
```

The row reads "stuck since start"; the log later shows `working_time ≈ total_time` — the sample was busy the entire span. The view whose job is answering "is this sample stuck?" cannot distinguish a long-but-healthy generation from a genuine hang.

The mechanics: `idle` is `now - last_activity_at`, and `last_activity_at` is the timestamp of the sample's most recent transcript event (`_active_sample_summary`, `src/inspect_ai/_control/state.py`). The pending `ModelEvent` is appended to the transcript **at generation start** (`_record_model_interaction`, `src/inspect_ai/model/_model.py`) and updated in place when the call returns — no new event lands in between, so `last_activity_at` jumps at call start and then freezes for the call's whole duration. `tokens` (`ActiveSample.total_tokens`) advances only when `record_and_check_model_usage` runs, which is once, after completion. `inspect ctl sample events` has the same blind spot: the events cursor serves nothing new during the call, and the pending event's projection carries zero tokens and no completion.

The blind spot is already documented in three places — the Phase 1 note in `control-channel.md`, the `sample list` section of `docs/control-channel.qmd` ("a single in-flight model request produces no events until it returns, so idle time also accumulates during one long model call"), and the comment block in `_active_sample_summary` itself — and `control-channel.md` names the fix's ingredients: "closing it needs streaming token deltas or a 'current operation' indicator". This design does both.

## Goals

- **A running sample mid-generate must not read as idle.** The listing shows that a model request is in flight and for how long, so "generating 7:12" replaces the misreading of "idle 7:12".
- **Show progress on in-flight calls where the provider gives us any.** When the provider call streams, surface cumulative output tokens so far — a climbing number is the strongest possible "not hung" signal, and it is also the early-warning signal for runaway generations (14k reasoning tokens visible at 2:00, not after 7:35).
- **`idle` means "time since last observed progress", uniformly.** A streamed call that is healthy shows idle ≈ 0; a streamed call whose stream has gone quiet shows climbing idle (a *real* stall signal, sharper than today's); a non-streamed call shows climbing idle *with* a `generating` indicator alongside it that explains why.
- Same information available to every consumer class: JSON rows for agents (the canonical shape), the human table, `sample show`, `sample events`, and the in-process TUI.

Non-goals:

- **Changing when providers stream.** Streaming remains each provider's transport decision (`auto_streaming()` on Anthropic, opt-in flags elsewhere). This design instruments streams that already flow; it does not turn streaming on for monitoring's sake (that would change provider code paths, response assembly, and failure modes for a display concern).
- **Counting in-flight tokens toward token limits or the sample's authoritative totals.** `total_tokens`, the limit tree, and cost accounting stay completion-driven. In-flight counts are provider-reported partials on a call that may still fail and be retried (and then be counted again); folding them into authoritative counters would double-count and make limit enforcement racy. Mid-flight limit enforcement is future work with its own semantics — the layer-2 progress record is the input such a design would need, so its shape stays provider-neutral.
- **Diagnosing *why* a genuinely stalled call is stalled.** That remains `ctl process anomalies` (trace-log reconstruction, works against a wedged process). This design makes the healthy case stop looking like the pathological one, so the escalation fires less often and more accurately.

## What exists today (the parts we build on)

- **`Transcript.pending_events`** (`src/inspect_ai/log/_transcript.py`) — an O(in-flight) sidecar of currently-pending events, maintained on every `_event` / `_event_updated`. Pending events are pinned across eviction, so the live object stays resident.
- **The TUI already answers this question in-process.** `SampleToolbar.sync_sample` (`src/inspect_ai/_display/textual/widgets/samples.py`) iterates `pending_events`, classifies (pending tool wins over pending model, with a documented rationale), and renders "Generating..." / "Generating (N retries)..." / "Executing N tools..." with a 1-second clock started from the pending event's `timestamp`. This is the classification rule and the elapsed-time definition to reuse — the control channel just never got the same read.
- **A precedent for mid-flight mutation from provider code**: `set_active_model_event_call()` (`src/inspect_ai/log/_samples.py`) — providers call it at request start to attach the request payload to the pending event, located via the `_active_model_event` ContextVar that `track_active_model_event` sets around the provider call. `report_active_sample_retry()` uses the same ContextVar to bump `ModelEvent.retries` in place.
- **Provider streaming exists but is consumed silently.** Anthropic streams (auto, when thinking is on or `max_tokens >= 8192`) and iterates the event stream already (`_capture_compaction_from_stream`), discarding deltas; Google iterates chunks and accumulates; SageMaker hand-parses SSE including a usage chunk; Grok iterates and keeps only the last value; OpenAI-compatible calls `get_final_completion()` without observing chunks. **No provider reports anything mid-flight today** — there is no chunk callback, no in-flight usage ContextVar, nothing.

## Design

Three layers, deliverable in order, each useful without the next:

1. **Activity indicator** — expose the pending-op read the TUI already does through the control channel and CLI. No provider changes. Closes the headline misreading ("generating 7:12" instead of a bare idle clock).
2. **Progress channel** — a cheap `report_active_model_progress()` path from provider streaming loops onto the pending event; providers that already iterate a stream call it per delta with cumulative output tokens where the provider supplies them.
3. **Idle upgrade** — `last_activity_at` becomes `max(last event timestamp, in-flight progress timestamps)`, so idle = time since last observed progress. Falls out of layer 2 server-side; old CLIs get the improved idle for free.

### Layer 1 — activity indicator

**Server.** `_active_sample_summary` (`_control/state.py`) additionally iterates `s.transcript.pending_events` (O(in-flight), typically 0–2 entries) and classifies exactly as the TUI does: any pending `ToolEvent` → tool activity (earliest one leads); else a pending `ModelEvent` → model activity. Running rows gain one field, present on every row per the output contract (null on rows with nothing pending, and on non-running rows):

```json
"activity": {
  "type": "model",                    // "model" | "tool" | "retry_wait"
  "count": 1,                         // concurrent pending ops of that type
  "started_at": 1753649000.1,         // earliest pending op's timestamp (unix ts)
  "detail": "openai/gpt-5-nano",      // model name, or tool function
  "retries": null,                    // in-call retries on the pending model call (null when none)
  "tokens": null,                     // layer 2: cumulative streamed output tokens, null when unavailable
  "last_progress_at": null            // layer 2: unix ts of last observed progress, null when none
}
```

Elapsed is client-computed (`now - started_at`), matching the idle column's convention and the TUI clock's definition (wall-clock from the pending event's `timestamp`). `retries` comes from the pending `ModelEvent.retries` — which counts provider-SDK-internal retries within the current attempt; an outer tenacity retry completes the failed attempt's event *in place* (`complete()` in `_record_model_interaction` sets `pending = None` but never re-stamps `event.timestamp`, so completion advances nothing) and re-enters with a fresh pending event, whose append is what moves `last_activity_at`. The pending event's own clock therefore always describes the current attempt. Note `report_active_sample_retry` mutates the live event without `transcript()._event_updated()` — fine here, since this read holds the same in-memory object.

**Known gap: the tenacity backoff window.** Between attempts — after a failed attempt's event completes and before the next attempt appends its fresh pending event — there is no pending event at all, so `activity` is null while `idle` reads as the failed attempt's full duration plus the backoff elapsed so far (backoff waits reach minutes under rate limiting). That is the same "looks hung but is healthy" misreading this design exists to fix, recurring in exactly the state where an operator is most tempted to conclude a stall. Nothing in the ctl sample surface's read path records "waiting to retry" today: `Model.should_retry` → `report_http_retry` → `report_active_sample_retry` runs only after the exception has unwound out of `track_active_model_event`, so the `_active_model_event` ContextVar is already reset and the bump lands nowhere (within-attempt SDK retries fire it while the ContextVar is live, which is why `ModelEvent.retries` counts only those); and the listing's row-level `retries` counts sample-level `error_retries`, not generate-loop retries. The wait *is* observable elsewhere — `on_before_sleep` already drives `log_model_retry` (`src/inspect_ai/model/_model.py`), which writes an HTTP-level trace record (`-> <model> retry N (retrying in S seconds)`, part of what `ctl process anomalies` reconstructs from) and awaits the `emit_model_retry(model_name, attempt, wait_time)` hook — it just never reaches a per-sample record. That makes the retry loop the natural place to hang the signal: `model_retry_config`'s `on_before_sleep` (`src/inspect_ai/model/_retry.py`) runs once per backoff, knows `rs.upcoming_sleep` and the attempt number, and already fans retry-wait info out to the trace log and hooks, so a per-sample retry-wait record slots in alongside those existing calls rather than being new plumbing (there is no pending event to attach to during the wait). `_active_sample_summary` reads it as a third activity type, `"type": "retry_wait"` with `count` = attempt number, `detail` = model, and the wait deadline; cleared when the retried call resolves (a `finally` in `Model.generate` / `count_tokens` / `compact` — there is no clear-on-append hook), while during the next attempt the record is merely shadowed for generate (whose fresh pending event takes precedence in classification); `count_tokens`/`compact` re-attempts record no pending event, so their record renders as bare `retrying` — still truthful — until the call resolves. This ships as part of layer 1 (Open question 4).

Additive response field, so **no `CONTROL_API_VERSION` bump** (per the skew policy in `_control/__init__.py`); an old CLI ignores it, a new CLI against an old server null-guards and renders as today.

**CLI (`sample list`).** A conditional `activity` column, shown — like `idle` — only when some row has non-null activity, rendered from type/detail/elapsed/retries/tokens:

```
sample             epoch  status   time  idle  activity              tokens  messages  turns
recO3hvCWRGiG0odN  4      running  7:13  7:12  generating 7:12       0       1         0
14                 1      running  12:40 0:02  bash 0:41             48210   22        11
17                 1      running  8:12  0:00  generating 2:31 · 1.2k tok   31055  14  7
```

`generating M:SS`, with `(N retries)` appended when the pending call has in-call retries, `· X tok` when layer-2 tokens are present; tool activity renders the function name (`bash 0:41`, `2 tools 1:10`). The first row is the issue's scenario after layer 1 alone: idle still climbs (non-streamed call, no progress signal), but the row now says *why* — in a model call that whole time — which is the honest rendering: "no observed progress for 7:12, because the provider gives us none mid-call".

**`sample show`** includes the same activity detail (it reuses `_active_sample_summary` for running samples already). **`sample events`** starts rendering the `pending` flag the endpoint already sends but the CLI ignores: a pending model event's summary reads `model · generating 2:31` (plus `· 1.2k tok streamed` with layer 2) instead of an empty completion — so the transcript tail also stops implying "nothing happening".

Shipped alongside layer 1: the three places that documented the blind spot — the Phase 1 caveat in `control-channel.md`, `docs/control-channel.qmd`'s `sample list` section, and the comment in `_active_sample_summary` — now describe the activity indicator (with layers 2–3 noted as the remaining streamed-progress work). Two implementation notes beyond the spec above: the retry-wait record lives on `ActiveSample` as a single slot (concurrent generates overwrite last-writer-wins; a per-context ownership guard keeps one call's clear from dropping a sibling's live wait — clearing on resolution rather than on next-attempt append matters because no next attempt ever appends after a final failure), and stamping is gated off for batch admin-op retry loops, whose worker task inherits an arbitrary sample's context.

### Layer 2 — the progress channel

**Reporting API.** A new module-level function alongside `report_active_sample_retry` in `src/inspect_ai/log/_samples.py`:

```python
def report_active_model_progress(output_tokens: int | None = None) -> None:
    """Record progress on the in-flight model call (from a provider streaming loop).

    Called per stream delta. `output_tokens` is the cumulative output token
    count for the call so far when the provider reports one, else None (a
    bare heartbeat). Updates the pending ModelEvent's progress record only —
    deliberately no transcript notification and no buffer write (see below).
    """
```

It resolves the pending event via the existing `_active_model_event` ContextVar (set by `track_active_model_event` around `api.generate()`, so provider streaming loops run inside it; ContextVars are per-coroutine-context, so concurrent generates within one sample each hit their own event) and updates a progress record: `last_progress_at` (wall clock) and `output_tokens` (cumulative, when given). The call is a couple of attribute writes — cheap enough to invoke per chunk with no throttling, and per the repo's no-speculative-locks rule it needs no lock (single event loop; providers' stream loops don't interleave mid-statement).

**Where the record lives: on the pending event, not serialized.** The progress record is a small mutable object attached to the `ModelEvent` as a pydantic `PrivateAttr` (exposed via a typed accessor, e.g. `model_event_progress(event)`), because `pending_events` is already the discovery path every consumer uses (control server, TUI, ACP) — attaching to the event needs no key management and is garbage-collected with the call. It must not be a serialized field: it is meaningful only while pending, and adding it to the event schema would leak an ephemeral monitoring artifact into logs and the type-generation pipeline.

**Deliberately not `transcript()._event_updated()` per delta.** `_event_updated` fans out to subscribers, one of which persists to the realtime buffer DB (insert-only — each update is a new row). Routing per-chunk progress through it would turn a 15k-token stream into thousands of buffer inserts per call, exactly the class of cost the endpoint-cost-audit exists to prevent. Readers poll (the control server on request, the TUI on its 1-second tick); a poll of an in-memory record needs no notification. The consequence — progress is invisible to the buffer DB and to crash recovery — is correct: a recovered log should contain the completed call or its error, not a partial token count.

**Provider integration.** Instrument the loops that already exist; leave transport decisions alone:

| Provider | Loop exists? | Tokens available mid-stream? | Work |
|---|---|---|---|
| Anthropic | yes (`_capture_compaction_from_stream`) | yes — `message_delta` carries cumulative `usage.output_tokens` | report per event; tokens from `message_delta` |
| Google | yes (chunk loop in `_stream_generate_content`) | chunks carry `usage_metadata` (cumulative where present) | report per chunk; tokens when present |
| SageMaker | yes (manual SSE parse) | usage parsed already (final chunk) | report per event |
| Grok | yes (`async for ... in chat.stream()`) | per SDK | report per iteration |
| OpenAI-compatible / Together | no — `await stream.get_final_completion()` | usage only in final chunk (`stream_options.include_usage`) | iterate the SDK stream's events (then `get_final_completion()` as today) reporting heartbeats; tokens stay null until the final chunk |
| Non-streaming providers / non-streamed calls | — | — | none; layer-1 indicator only |

Where the provider reports a real cumulative count, report it; where it doesn't, report bare heartbeats — **no fabricated token estimates** (a chunk count is not a token count, and an estimated number in a monitoring surface will be read as real; see Open questions). A heartbeat alone still delivers the layer-3 idle fix, which is most of the value.

The provider work is independent per provider and can land incrementally; the surface degrades gracefully (null `tokens`, null `last_progress_at`) for any provider not yet instrumented.

### Layer 3 — idle means "time since last observed progress"

`_active_sample_summary` computes `last_activity_at` as the max of the last transcript event's timestamp and every pending event's `last_progress_at`. The CLI's idle computation (`now - last_activity_at`) is unchanged — meaning **old CLIs against a new server get the corrected idle for free**, and the field's documented meaning shifts from "last transcript event" to "last observed activity" (update `docs/control-channel.qmd` accordingly).

Resulting semantics, per the goals: streamed + healthy → idle ≈ 0 with `generating M:SS · X tok` alongside; streamed + stream gone quiet → idle climbs, and now that's a *sharp* signal (heartbeats were flowing and stopped); non-streamed → idle climbs with the indicator explaining it. The `--active-since` recency delta on `sample list` keys off `last_activity_at`, so a streaming sample naturally shows up in "what changed" polls — consistent with the field's contract ("started or updated since T"), since the sample genuinely is active.

### TUI adoption

Once the progress record exists, `SampleToolbar` extends its caption for free: `Generating (12.4k tokens)...` read off the same pending event it already holds, on the same 1-second tick. Low priority relative to the ctl surface (the TUI already shows *that* generation is happening; ctl shows nothing), but it makes the two views tell one story.

### Cost-audit compliance

The binding constraint (`endpoint-cost-audit.md`): the samples handler shares the eval's event loop, so per-row work must stay O(1)-ish and must not scan events. Layer 1 adds an iteration over `pending_events` — O(in-flight ops per sample), bounded by within-sample concurrency, no event scan. Layers 2–3 add scalar reads of the progress record. The write side (per-chunk reporting) is attribute writes on a resident object, no allocation beyond the record itself, no notification fan-out.

## Alternatives considered

- **Synthetic heartbeat events in the transcript** (emit a progress event every N seconds/tokens during a call). Rejected: pollutes the transcript and the log schema with monitoring artifacts, generates buffer-DB writes proportional to call duration, and forces every transcript consumer to filter them.
- **Route progress through `_event_updated`** (mutate the pending event's `output.usage` and notify). Rejected for the buffer-write cost above, and because partially-filled `ModelOutput.usage` on a pending event would be read as authoritative by anything that doesn't check `pending`.
- **The `ExecutionObserver` route** (`agent/_channel/observer.py`), which `control-channel.md` floated for a "current operation" indicator. The observer is a per-sample installed hook aimed at the agent-channel consumer; the pending-events read is already how every in-process view answers this question, needs no installation, and keeps one source of truth. The observer remains the right vehicle for *channel* consumers; nothing here precludes it.
- **Estimate tokens from chunk counts** when the provider sends no usage. Rejected as a default: a monitoring surface that shows a number teaches consumers to trust it, and chat-completions deltas are not 1:1 with tokens. Heartbeats carry the liveness signal without the fabrication. (Revisit if agents demand a number badly enough to accept a labeled estimate — see Open questions.)
- **Lean on `ctl process anomalies`** (the shipped trace-log escalation) instead of touching the listing. Insufficient: it is process-scoped with no sample attribution and no tokens, and it's the escalation you reach for *after* the listing has told you something looks stalled — the listing lying is the problem.

## Testing

- `tests/_control/test_state.py`: activity classification (pending model / pending tool / both / none), `last_activity_at` max with progress timestamps, null-guarding on terminal and pending rows; the retry backoff window classifies as `retry_wait` rather than null.
- `tests/_control/test_ctl.py`: activity column rendering (conditional display, retries/tokens variants), `sample events` pending-row summary — alongside the existing idle-column tests.
- Progress channel: unit-test `report_active_model_progress` under `track_active_model_event` (including two concurrent generates in one sample via `tg_collect`); mockllm can drive an end-to-end "listing shows generating + tokens mid-call" test by reporting progress from a stub provider.
- Provider loops: per-provider tests are thin (assert the loop calls the reporter); the recorded-response harnesses don't exercise real streams, so live-API smoke coverage rides the existing provider test tiers.

## Open questions

1. **Batched calls** (`--batch`) — *deferred*: a pending call parked in a provider batch queue can legitimately sit for a long time with zero progress, and `activity` could distinguish it (e.g. `"batched": true`) so a monitoring agent doesn't cancel healthy batch waits. Ship without it; a batched call renders as a plain long-running `generating` for now. Revisit (starting with what the batch path attaches to the pending event today) if batch-heavy runs make the misreading bite.
2. **Labeled token estimates** for chunk-only providers (OpenAI-compatible until the final usage chunk) — *deferred*: ship without estimates (heartbeat + null tokens) and let demand decide whether an `"estimated": true` variant is worth it.
3. **Should `sample list` surface `last_progress_at` distinctly from `idle`** (e.g. for streamed calls, "stream quiet for M:SS")? — *resolved*: no; the single upgraded idle number suffices. The JSON carries both regardless, so agents can compute anything.
4. **The retry backoff window** (see the known gap under layer 1) — *resolved: ships inside layer 1*. The gap is real — idle misreads during rate-limit backoffs, precisely when operators most suspect a stall — and although the fix needs its own plumbing (a per-sample record stamped from `on_before_sleep`, since no pending event exists during the wait) rather than the pending-events read the rest of layer 1 reuses, the layer's whole point is that a healthy-but-waiting sample must not read as hung, and a rate-limited sample is the commonest healthy-but-waiting case.
