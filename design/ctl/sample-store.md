# Sample Store Read (`inspect ctl sample store`)

> **Status: implemented** (the read helpers live in
> `src/inspect_ai/_control/store.py`; the open questions below resolved as
> proposed — no `--full` size guard, `size` = UTF-8 bytes of compact JSON).
> Companion to [`control-channel.md`](control-channel.md), which
> owns the control-channel architecture and conventions this read inherits (the
> read-surface phasing, selector rules, projection tiers, and the "cheap
> shoveling" invariant); this doc owns the store-read semantics. Originating
> issue: meridianlabs-ai/inspect_ai#282.

A sample's `Store` is where solvers, tools, and agents coordinate shared state
— progress flags, intermediate results, agent scratchpads, `StoreModel`
fields. Today the only way to see it mid-run from outside the process is to
reconstruct it client-side by replaying the full event backlog:

```bash
inspect ctl sample events <task> <sample-id> [epoch] \
    --type store --from-start --full --json   # page, page, page… then replay
```

That works (the issue's report confirms it) but is the wrong shape three ways:
it pages the entire transcript to answer a point-in-time question, it makes the
*client* re-implement store replay (span-ordering rules included), and on a
bounded live transcript the resident window isn't even guaranteed to hold the
full store history without server-side re-materialization from the buffer.
Meanwhile the answer already exists as a plain dict in memory (live) or on the
logged sample (terminal). **`sample store` reads it directly.**

## Scenarios

- **Watchdog / monitoring agent reading eval progress.** A solver records
  `phase`, `attempts`, `best_score` in the store; an external agent polls the
  store snapshot (metadata or a couple of `--key`s) instead of tailing events
  and replaying.
- **Debugging a live agent.** An operator inspects what an agent has
  accumulated in its scratchpad (`--key 'AgentState:*' --content`) while the
  sample runs, without attaching a debugger or waiting for the log.
- **Post-mortem on a just-finished sample.** Same command, same shape, after
  termination — served from the recorder/log fallback, before or after flush.
- **Scripted extraction.** `inspect ctl sample store t s1 --key result --full
  --json | jq .store.result` as a building block, replacing the
  page-and-replay loop.

## Surface

Following the drill-down family (`sample show` — "how is it doing",
`sample events` — "what happened, in order", `sample messages` — "what does
the model see"), this verb answers **"what state has it accumulated"**:

- **`GET /evals/{eval_id}/sample/store`** with `sample_id` (query param, like
  the sibling per-sample reads — ids may contain URL-reserved characters),
  `epoch` (default 1), repeatable `key`, `content`, `full`.
- **CLI: `inspect ctl sample store TASK SAMPLE_ID [EPOCH] [--key K ...]
  [--content] [--full] [--json]`.** `TASK` resolves by the standard selector;
  the response echoes the resolved identifiers (a defaulted epoch stays
  visible and round-trips into other commands' selectors).

### Snapshot, not cursored

Same rationale as `sample messages`, verbatim: the store is rewritable —
`set` overwrites, `delete` removes, and agent code mutates values in place —
so no index or version cursor over it could deliver exactly-once resume. Each
call returns the current snapshot, enveloped with `as_of` / `status` /
`count`; a watcher polls, or follows `sample events --type store` when it
genuinely wants the change *stream* (that path remains; this verb replaces
only the reconstruct-current-state use of it).

### Envelope

```json
{
  "task_id": "…", "sample_id": "…", "epoch": 1,
  "as_of": 1755720000.0,
  "status": "running",            // running | completed | error
  "count": 7,                     // total keys in the store, pre-filter
  "store": { "phase": {…}, … },   // key → projection, post-filter
  "missing": ["no_such_key"]      // exact --key requests not present
}
```

- The identifier echo (`task_id` / `sample_id` / `epoch`) is added at the CLI
  `--json` layer, exactly as in `messages` — the server response carries only
  `as_of` / `status` / `count` / `store` / `missing` (the server is keyed by
  `eval_id` and has no notion of `task_id`).
- `count` is always the whole store's key count, so a filtered read still
  shows how much it didn't ask for (the "no silent truncation" rule —
  structural signal, not inference from `len(store)`).
- `missing` lists requested exact keys that aren't present, so scripts can
  tell "absent" from "filtered out" without comparing sets. Present only when
  `--key` was given (stable shape per mode).

### Key filtering

`--key` (repeatable; `key=` repeated on the wire) selects keys **server-side**
— the point is that one large key doesn't drag the whole store over the wire,
so filtering client-side would defeat it. Two match forms:

- **Exact**: `--key phase`.
- **Trailing-`*` prefix**: `--key 'AgentState:*'` — the `StoreModel`
  namespacing convention (`ClassName:field`, `ClassName:instance:field`)
  makes prefix selection the natural way to read one model's fields, without
  this surface knowing anything about `StoreModel` itself.

No other glob forms (no mid-string `*`, no regex) — prefix covers the
namespacing convention, and a closed grammar keeps the wire contract simple.
Unknown-key selection is not an error (the store is schemaless; a key may
simply not be written yet) — it lands in `missing`.

### Projection tiers (trust boundary)

Store values are **agent-controlled text** — agents write their scratchpads,
tool outputs, and accumulated blobs into the store — so the read gets the
same three tiers as `events` / `messages` ("Trust boundary for readers" in
`control-channel.md`), sharing the events projection's `_truncate` / `_to_text`
helpers so renderings can't drift:

- **Default: metadata only.** Per key: JSON `type` (`object` / `array` /
  `string` / `number` / `boolean` / `null`), serialized `size` in UTF-8
  bytes, and
  a length hint (`len` — string length, array length, or object key count).
  No values. This is the effortless poll target: a monitor can watch keys
  appear and sizes move without ever ingesting agent-authored content.
- **`--content`**: adds `value` — the truncated (shared `_TRUNCATE` width)
  single-line preview of each value's JSON serialization.
- **`--full`**: raw jsonable values (what `store_jsonable` yields — the same
  serialization `EvalSample.store` gets, with non-serializable values falling
  back to `null`). Unbounded by design, like `messages --full`; combining
  with `--key` is the recommended way to keep it bounded, and the CLI help
  says so.

One boundary note, documented rather than solved: **key names** sit in the
metadata tier (like tool function names in the events projection) even though
an agent with store access can technically mint arbitrary keys. Keys are
overwhelmingly code-authored (solver/`StoreModel` field names), a keys-only
listing is the whole point of the metadata tier, and the same class of
exposure already exists on the shipped surfaces; a monitor hardened against
agent text should treat key names with the same suspicion it treats function
names.

Human (non-`--json`) rendering is a table — `key | type | size [| value]` —
per the CLI's existing render conventions.

## Data sources

The running-vs-terminal split every sibling read uses, and — unlike
`messages`, which had to add the `ActiveSample.live_state` handle — **zero new
plumbing on either side**:

- **Running** ← `find_active_sample(eval_id, sample_id, epoch)` →
  `ActiveSample.live_state.store` → `store_jsonable()`. The live-state handle
  added for the messages read already carries the store (`TaskState.store`
  rides the same object the compare-and-swap refresh tracks, so fork branches
  can't hijack it — see the messages design in `control-channel.md`). The
  control server shares the eval's event loop, so the snapshot can never
  observe a half-applied mutation. No log, no events, no replay — which is
  exactly why a sample whose transcript is bounded (or buffered-only) still
  answers.
- **Terminal** ← `_full_sample(eval_id, sample_id, epoch,
  exclude_fields={"messages", "events", "attachments", "output",
  "error_retries"})` — the shared recorder-then-on-disk-log source, keeping
  only `store` (plus the identity/error fields the envelope needs).
  `error_retries` is excluded too: each retry can carry a full transcript of
  its own, which this read never uses (`status` needs only `error`, and the
  field defaults to `None`, so exclusion is safe). Resolved through a
  `TerminalSourceCache` like the sibling reads (a terminal sample's store is
  immutable; don't re-pay the sample parse per poll), invalidated when a
  running attempt supersedes it. `status` reads `error` / `completed` off the
  sample, as in `messages`.

Two source facts verified against current code, on which the terminal path
leans:

1. **`EvalSample.store` is stored verbatim** — `condense_sample` /
   `resolve_sample_attachments` walk `input` / `messages` / `events` /
   `error_retries` but never the sample-level `store`, so no attachment
   resolution is needed (store *events* get pooled; the final store dict does
   not).
2. **The streaming-completion path retains the store.** The event-less sample
   the recorder keeps for pre-flush control reads
   (`EvalRecorder.buffer_sample_streaming` → `_streaming_samples`) strips only
   `events` / `events_data` / `attachments`; `store` rides along, so a
   just-completed streaming sample answers without waiting for flush.

### Filter-before-serialize

Apply the `--key` filter to the raw dict **before** `store_jsonable` /
serialization, so a targeted read of one small key never pays serialization
of a sibling megabyte blob. The metadata tier does serialize every
(post-filter) value once to measure `size` — O(store) work of the same order
the store-event recording path already pays per step, and bounded by the
filter for targeted reads. Serialization applies on **both** sources: the
terminal path's pre-flush recorder samples hold raw Python store values
(`create_eval_sample` copies `state.store` verbatim — an agent may have
stashed a non-JSON-serializable object), so the terminal path must run values
through `store_jsonable` just like the live path, never return `sample.store`
verbatim in `--full`. That satisfies the cheap-shoveling invariant the
same way `messages` does (O(conversation) per request): request-shaped work,
no background tasks, no cross-request state beyond the terminal cache.

## Rejected alternatives

- **Server-side `store_from_events` replay.** The obvious lift of the
  client-side workaround: `store_from_events()` already exists and handles
  parallel-span ordering. Rejected because it is O(events) work on the eval's
  own loop per request (against transcripts that can run to tens of thousands
  of events), on a bounded live transcript it requires re-materializing
  evicted events from the buffer just to fold them down to a dict that
  already exists in memory, and it computes a value the live path can read in
  O(1) and the terminal path already holds as a plain dict on the sample. Replay is the fallback
  shape for when state *doesn't* exist anywhere — not the case here on either
  side of the running/terminal split.
- **Folding into `sample show`.** Same answer as the messages read: `show` is
  the summary poll target; a store can be megabytes. Separate verb, same
  summary-then-detail relationship. (A `keys: <count>` field on `show` would
  be a harmless future addition, not part of this slice.)
- **`StoreModel`-aware read (`--model AgentState`, un-namespaced fields).**
  `store_from_events_as` shows the demand, but it drags model-class import
  and validation into the server. The prefix filter (`--key 'AgentState:*'`)
  gives the same selection without the server knowing what a `StoreModel`
  is; a client-side nicety can un-prefix for display later if wanted.
- **Cursored / delta reads.** No stable index exists over a rewritable dict
  (see "Snapshot, not cursored"); `sample events --type store` already *is*
  the change stream for consumers that want deltas.

## Sequencing and versioning

Read-only — no directive machinery, no security-hardening dependency — so it
extends the phase-2 read surface and can land independently, exactly as the
messages read did. New route ⇒ **no `CONTROL_API_VERSION` bump**: an older
server answers the stock route-missing 404, which the CLI maps to the
standard "older inspect — restart the eval" message via
`not_found_missing_route` (the `sample messages` precedent).

Implementation shape (mirroring `_control/messages.py`):

- `_control/store.py`: `sample_store(eval_id, sample_id, epoch, *, keys,
  content, full)` + `_running_source` / `_resolve_logged_source` (resolved
  through the shared `resolve_sample_source` / `TerminalSourceCache`) + the
  per-key projection.
- `server.py`: `GET /evals/{eval_id}/sample/store` (repeatable `key` query
  param; 404 envelope on unknown sample).
- `_cli/ctl/_sample.py` + `_sample_read.py`: the `sample store` command,
  uniform empty `--json` envelope when no evals are running, table render.
- Tests alongside the existing control-channel read tests: live snapshot
  (including mid-run mutation visibility), terminal fallback pre- and
  post-flush (streaming path included), key/prefix filtering + `missing`,
  projection tiers, bounded-transcript sample (works with no event access at
  all), older-server route-missing handling.

## Open questions

1. **Should `--full` get a server-side response-size guard?** `messages
   --full` ships without one; stores are likelier to hold single multi-MB
   values. Proposed: ship without a cap (consistent; `--key` + the
   metadata-tier `size` field make targeted reads the documented pattern),
   revisit with a structural `truncated` flag if it bites.
2. **Value `size` semantics.** UTF-8 bytes of compact JSON serialization
   (`ensure_ascii=False`, so non-ASCII text counts its real bytes) is
   proposed (cheap, deterministic); it will differ from Python-side
   `sys.getsizeof` and from the log's on-disk size. Fine for its purpose
   (spotting the big keys) — worth one sentence in the CLI help.
