# Framing: Pagination of Messages/Events Within a Sample

Status: framing/explanation — not yet a plan. Captures problem, principles, current design, proposed direction, access-pattern inventory, confounders, open questions, and next steps.

## Problem

A single sample must support an essentially arbitrary number of messages and events. Today all data for a sample lives in one JSON entry inside the `.eval` zip. JSON parses sequentially from the top, which is at odds with the near-term requirement to serve windows/pages of messages and events.

## Principles & working assumptions

Principles:

- **Scale target**: samples with 10M+ messages must be tractable.
- **Single portable `.zip`** containing everything remains the format.
- **Viewer access model**: paginated, filtered, index-based queries only — there is no "get all events" access pattern in the new design (sorting is unused). The one whole-sample summary any view reads is the structural skeleton (span-proportional, see Confounder 2), consumed by the outline. Full-fidelity reads (export, Python `read_eval_log`) remain as explicit bulk operations.
- **Persisted data is unopinionated**: the format stores structural and semantic facts (ids, ordinals, nesting, event types, names, counters) — never transformed output. Every interpretation — event-type filtering, turn synthesis, scoring collapse, labels, iconography, collapse defaults — is viewer-side policy, applied at read time. Nothing persisted may bake in a presentation decision; policy evolves faster than stored logs. (Restated for the skeleton specifically in Confounder 2.)
- **Data comes straight from the eval file** even when a server is present — the server just serves bytes.

Decided (implemented in the converter, `src/inspect_ai/log/_recorders/eval2/`): four flat chunked sequences per sample (messages, events, calls, attachments) as zip entries with client-driven random access; chunk names carry the start index only; count-based chunking for item sequences and size-based for attachments (both writer policy); JSON-array chunk encoding; stable per-sample indexes with range-encoded references, half-open `[start, end_exclusive)` everywhere ranges appear in data; rehydration external to the format. Still open: structural-skeleton details (location, counter set — see Confounder 2).

## Current design (verified)

- `.eval` = zip of zstd-compressed JSON entries: `header.json`, `summaries.json`, `reductions.json`, `_journal/start.json`, `_journal/summaries/{N}.json`, and **one entry per sample** `samples/{id}_epoch_{epoch}.json` (`src/inspect_ai/log/_recorders/eval.py`).
- The per-sample entry is the full `EvalSample`: `messages`, `events`, `scores`, `store`, plus two dedup structures:
  - `attachments: dict[hash, content]` — content-addressed (`attachment://<mm3hash>`), added to stop large content being duplicated in every turn's copy of the messages.
  - `events_data` — two pools of two currencies: `messages: list[ChatMessage]` (dedup of `ModelEvent.input`, same type as top-level `messages`) and `calls: list[JsonValue]` (raw provider-specific `ModelCall` request/response payloads — often the largest per-sample data; default reads leave them condensed via `resolve_attachments="core"`). `ModelEvent.input_refs` already range-encodes pool references as `(start, end_exclusive)` tuples.
  - **Double storage of the final conversation**: pooling applies only to events (`condense_model_event_inputs`); the top-level `messages` list is stored materialized in full (only images are attachment-extracted — long text stays inline, unlike the events walk). Since the final ModelEvent's input is ~the same list via pool refs, the last-turn conversation is effectively stored twice (`src/inspect_ai/log/_condense.py:147-212`). A unified id-addressed message sequence eliminates this.
- **Random access exists at sample granularity, not within a sample.** `AsyncZipReader` (Python) and `remoteZipFile.ts` (browser) range-read the central directory and individual entries. Within a sample the only relief is the ijson `exclude_fields` band-aid (skip top-level fields).
- **Completed-log reads are client-driven.** The view server has no per-sample JSON endpoint; the browser does its own zip random access via `/log-bytes` byte ranges or presigned S3 URLs, decompressing client-side (fflate/fzstd). static-http and VS Code backends ride the same path.
- **Live-run pagination already exists** and is unaffected: sample buffer (SQLite, cursor-based `get_sample_data(after_event_id=…)`) plus `.buffer/` segment zips for shared filesystems. The gap is the **at-rest** format.
- Write path: the recorder holds the zip open in append mode on a temp file; every flush rewrites the central directory and re-uploads the whole file. Large samples stress writes too, not just reads.
- Evidence of pain: browser hard-caps samples (512MB/2048MB uncompressed) and silently strips oversized events arrays (`clearLargeEventsArray`); the multi-frame zstd patch exists because single sample entries outgrew the browser decoder.
- Versioning: `LOG_SCHEMA_VERSION = 2`; forward tolerance via pydantic before-validators, no migration ladder. This restructure implies version 3.

## Proposed direction

Inspired by parquet row groups.

Terminology: a **sequence** is an ordered, homogeneous, index-addressed set of items (messages, events, calls), append-only during the run, physically stored as N chunk entries. (Deliberately not "stream" — that term is reserved for the live streaming/cursor path.)

- **Per-sample TOC** plus, for each high-scale sequence (messages, events, calls, attachments), a set of **chunk files** as sibling zip entries.
- **The TOC is a structural skeleton, not a rendered artifact.** The outline (`TranscriptOutline`) is the only view that needs a summary of *all* events; every other view reads detail via paginated index-window queries. The skeleton persists raw structure — the span tree plus per-span counters — never transformed output: the viewer's transformations (span unwrapping, turn synthesis, scoring collapse — `transform.ts`, `tree-visitors.ts`) are client policy that evolves faster than stored logs. Size invariant: skeleton size is proportional to *structural* span count (fixed-size counters per span; leaf tool spans are summarized by counters, not stored — see "Structural skeleton (draft)"), never to event count — readable in full even for 100M-event samples. The likely producer is the Python timeline code (`src/inspect_ai/event/_timeline.py`; a TS twin in `inspect-components/src/transcript/timeline/` is kept in sync via a shared JSON test suite); computation is cheap (type comparisons, no content introspection) and the event sequence is append-only, so it's rewritten (or incrementally updated) at sample boundaries. Index→chunk mapping stays in chunk filenames — the skeleton is not needed for that. Details in Confounder 2.
- **Chunk names carry the start index only** (`{start}.json`, no zero-padding). Filenames have no range semantics: every range that appears in the *data* is half-open `[start, end_exclusive)` (matching Python/TS slicing and the `input_refs` convention), and a filename like `0-50` invites inclusive misreading. Chunks are contiguous and complete, so the chunk holding index `i` is the one with the greatest start ≤ `i`; a chunk's extent is the next chunk's start, and the last chunk's end is the sequence count from the shell's `sequences` boundaries. Every reader must fetch the zip central directory anyway (byte offsets), so index→chunk is a binary search over numerically-sorted entry names. This makes the format **agnostic to chunking policy**: count-based (item sequences, default 1000), size-based (attachments, ~2MiB target), or adaptive chunking all read identically — chunking is a writer-side tuning knob, not a format property. Per-chunk metadata (type counts, span/time ranges), if needed, is its own concern — not index mapping.
- **Chunks as zip entries preserves the architecture**: clients keep doing byte-range + central-directory reads; no new server endpoints required for completed logs.
- **Events reference messages by stable per-sample indexes, range-encoded** as half-open `[start, end_exclusive)` pairs (e.g. `[[0, 9874], [9875, 9876]]`), never flat lists — model-event inputs are prefixes-plus-delta, and flat lists are O(N²) across a transcript. (`ModelEvent.input_refs` uses exactly this encoding into the pool; `.eval2` keeps it unchanged.)
- **Rehydration is a consumer concern**: the format guarantees stable ids and range-named chunks; consumers resolve which message chunks a window of events needs (via central-directory names) and fetch them independently. (See confounder: the last page.)
- **The message sequence subsumes the `events_data.messages` pool**: pooled messages and top-level `messages` are the same currency (`ChatMessage`) — they differ only in membership (pool = superset across all ModelEvent inputs; top-level = the final main thread). The sequence *is* the pool, extended with any final-conversation messages not already pooled (e.g. the last assistant answer, which is only ever an output); the shell's final conversation becomes range-encoded refs (`message_refs`) into it. Sequence order is event-appearance order, not conversation order — consumers must always go through refs. (Precedent: the buffer SQLite DB already has `message_pool` with autoincrement ids.) The `calls` pool is a different currency (raw provider payloads) and a **third sequence**.
- **Attachments survive as a fourth sequence** (bare strings, referenced as `attachment://<index>`; identity = sequence index, content-hash dedup is write-time policy only, never persisted). They cannot be inlined: attachments dedup content *across containers* — the same string recurs in pooled messages, wire request/response payloads, tool events, state deltas, model outputs, and per-turn tool schemas, most of which no pool touches. Measured on an attachment-heavy log (petri, 470 samples): 92MB of unique attachment content is referenced from ~2–6+ sites each and inlines to 444MB. Attachments chunk by target byte size rather than item count (contents vary ~100B to MBs; an oversized item gets a chunk to itself).
- **Sample `metadata` is a sibling entry** (`metadata.json`, written only when non-empty) rather than a shell field — it is user-controlled and can be arbitrarily large.
- **Chunk encoding: JSON first; protobuf deferred.** Ship with JSON-array chunks and revisit encoding only if measurement demands it. The tradeoff to carry in mind: zip compresses entries independently; dedup pools remove *content* duplication but not JSON *structural* redundancy (key names, enum strings), which per-entry zstd currently recovers and which small chunks forfeit — so JSON pressures X upward, and protobuf (which eliminates structural redundancy by construction) is what would make small X cheap. Protobuf's cost is a shared schema with TS + Python codegen (pydantic is currently the source of truth). Range-named chunks make encoding a per-entry concern (the extension says what's inside), so a later protobuf phase is additive, not a format break.

### Zip layout (per sample)

As written by the converter (chunk sizes shown for default policy: 1000 items; ~2MiB attachment chunks). Skeleton location (inside shell vs separate entry, e.g. `skeleton.json`) still open.

```
samples/
└── 1_epoch_1/
    ├── sample.json          # the "shell" — everything small, cheap by construction:
    │                        #   id, epoch, input, target, scores, model_usage,
    │                        #   error, limit, timing, uuid...
    │                        #   + message_refs: [[0, 25], [26, 27]]   (final conversation,
    │                        #       half-open ranges into the message sequence)
    │                        #   + sequences: cumulative end-exclusive chunk boundaries,
    │                        #       {messages: [1000, 2000, 2210], events: [...],
    │                        #        calls: [...], attachments: [...]}
    │                        #       (last element = sequence count)
    │                        #   NO messages / events / attachments / events_data / metadata
    ├── metadata.json        # sample.metadata (only when non-empty)
    ├── messages/
    │   ├── 0.json           # items [0, 1000)
    │   ├── 1000.json        # name = start index; extent = next chunk's start
    │   └── 2000.json
    ├── events/
    │   ├── 0.json           # ModelEvents carry range-encoded input_refs/call_refs
    │   └── ...              #   instead of inline copies
    ├── calls/
    │   └── 0.json           # raw ModelCall payloads, one per model event
    └── attachments/
        ├── 0.json           # bare strings, referenced as attachment://<index>;
        └── 812.json         #   size-based chunking, so starts are irregular
```

Notes:
- Everything for a sample lives under one `{id}_epoch_{epoch}/` prefix (shell included, as `sample.json`), so per-sample enumeration is a central-directory prefix scan.
- The final conversation (`sample.messages`) becomes range-encoded indexes into the message sequence — no double storage.
- `attachments`/`events_data` disappear as shell fields; their jobs are absorbed by the sequences.
- Per-chunk type counts (event-type filter, turn numbering), if adopted, would add a skinny sibling per event chunk or a per-chunk table in the skeleton.
- Top-level entries (`header.json`, `summaries.json`, `reductions.json`) are unchanged from `.eval`; `_journal/` is not carried over. `LOG_SCHEMA_VERSION` stays 2 — the `.eval2` extension is the format gate while experimental.

### Tension around chunk size

Too big → overread; too small → chatty (one range request per chunk — same-sequence chunks are not byte-adjacent, so windows spanning k chunks cost k requests) and, with JSON, poor compression. A later protobuf phase would substantially relax the lower bound.

### Measured: size vs `.eval` (petri, 470 samples, 36MB)

- Compressed: 37.7MB → 51.1MB (+36%). Uncompressed: 332MB → 292MB.
- The uncompressed drop is the dedup working (double-stored final conversation gone, `_journal` dropped). It does not translate to compressed savings because dedup and zstd remove the *same* redundancy — in the monolith, repeated content compressed to near-zero back-references anyway.
- The compressed regression is per-entry compression scope, isolated experimentally: one sample's identical bytes compress to 0.41MB as a single stream vs 0.57MB across its 6 entries. Splitting severs cross-entry matching (sub-extraction-threshold strings repeated across sequences, near-duplicate attachments, JSON structural redundancy re-learned per entry). This is the direct price of random access.
- Null results: attachment chunk target (2/8/32MiB) makes no difference (most samples fit one chunk); zstd level 9 saves only ~7%.
- Levers if the toll ever matters: protobuf chunk encoding (removes structural redundancy) or per-log trained zstd dictionaries (pre-warms every entry; needs browser fzstd support).

**Comingling sequences into shared chunks** (measured on the 15 largest petri samples, concatenation as a proxy for time-interleaving): all four sequences comingled −27.6% compressed; events+attachments alone −24.4%; messages+events −3.8%; messages+attachments −1.9%; events+calls −0.2%. The redundancy is almost entirely the events↔attachments affinity (event bodies — outputs, response payloads, tool args, state deltas — near-duplicate the attachment strings). Full comingling is rejected: messages are ~4% of sample bytes, so time-interleaving smears a message window across essentially every chunk of the sample (type-density dilution defeats per-type pagination, the format's core access pattern). events+attachments comingling is the viable fallback — the transcript path wants both together anyway and the dilution ratio is mild (~1.8:1) — at the cost of event-chunk overread for attachment hydration from the Messages tab. The zero-read-cost alternative is the shared zstd dictionary. Decision deferred until the render phase proves the access patterns.

### Converter

`inspect log convert-eval2 PATH --output-dir DIR [--overwrite] [--chunk-size N]` (hidden command) converts `.eval` → `.eval2`; implementation in `src/inspect_ai/log/_recorders/eval2/` (`format.py` = naming/chunking shared with future readers, `convert.py` = the transform). Conversion details: existing `input_refs`/`call_refs` remain valid (the pool is a prefix of the sequence); inline model-event inputs/calls from logs predating pooling are condensed; final-conversation messages get the events-flavored attachment extraction so content-hash dedup matches their pooled twins (they were written with the weaker messages-flavor walk); `attachment://<hash>` refs are renumbered to indexes by a pass over serialized JSON, which uniformly covers sites the typed walkers miss (`ModelOutput.completion` — see issue #4515 — state-event deltas, provider response payloads).

## Access-pattern inventory

From the view server and TS client (completed-log path):

| # | Pattern | Accessed by | Today | Demand on new format |
|---|---|---|---|---|
| 1 | Header / summaries / listing | Log list + sample list UI: `remoteLogFile.readHeader`/`readLogSummary`, `/log-headers`, `/log-files` | Separate small zip entries | none |
| 2 | Sample "shell" (metadata, scores, usage, error) | Opening sample detail (header strip, Scoring/Usage/Metadata tabs); Python `read_eval_log_sample(exclude_fields)` | Full parse or `exclude_fields` | Shell = slimmed sample entry; cheap by construction |
| 3 | Page messages by index window | Messages tab: `ChatViewVirtualList` (`SampleDisplay.tsx`) | Full load; virtualization is DOM-only | index→chunk via range-named entries (core design) |
| 4 | Page events by index window | Transcript tab scroll: `TranscriptVirtualListComponent` → `VirtualList` | Same | Same |
| 5 | Tail / jump-to-last / follow | Auto-follow of running sample; `VirtualList` `followOutput`/`scrollToIndex` | Full load | last chunk from total count (shell/TOC) |
| 6 | Transcript structure w/o content: event tree, outline, timeline | First render of Transcript tab: `treeifyEvents` (`useEventNodes`), `useTranscriptTimeline`, `TranscriptOutline` | Walks entire events array before first render | span-proportional skeleton — see Confounder 2 |
| 7 | Deep links (event uuid, message→event) | URL deep links / citations: `scrollToEvent` (`TranscriptViewNodes`), `resolveMessageToEvent` | `findIndex` over full array | identity = sequence index; legacy uuid links via on-demand chunk scan |
| 8 | Event-type filtering | Transcript filter menu: `eventFilter.filteredTypes` (`TranscriptPanel`) | Client-side array filter | per-chunk type counts, or degrade (open) |
| 9 | In-sample search | Transcript find-in-sample: `sampleSearch.findAllMatches`; scout `/scout/*` server search | Full scan client-side (scout offers server-side) | progressive per-chunk scan, or push server-side |
| 10 | Full hydration / export / Python full read | JSON tab, copy/download transcript (`SampleDisplay`), `readCompleteLog`, Python `read_eval_log` | Whole file | read all chunks + reassemble (N reads) |
| 11 | Live streaming | Running-sample view: `sampleStream.ts` cursors → `/pending-sample-data(-urls)`; `finalizeRunningSample` handoff | Buffer cursors + segments — already paginated | unaffected; finalize-handoff could become chunk-aware |
| 12 | Python `read_eval_log_sample(exclude_fields, resolve_attachments)`, scout | Programmatic analysis/scoring pipelines; scout transcript indexing | ijson band-aid | shell + selective chunk reads |

## Confounders

Three access patterns fight the chunked design; each needs an explicit stance.

### Confounder 1: the last page (hydration pulls in everything)

The common case for "open a sample" is the *end* of the transcript — and the last page of events almost always contains the final ModelEvent, whose input references essentially the entire conversation. Naively hydrating the last events chunk therefore means downloading every message chunk: pagination defeated by one event. What keeps it workable:

- The reference metadata itself stays tiny: range-encoded ids (`[0..N]`), never flat lists (which go O(N²) across a transcript).
- Interactive consumers are fine: the last chunk alone renders the frame; message ranges hydrate lazily at ceil(window/X) chunk fetches on scroll-into-view (the message list inside a model event is already virtualized).
- Non-interactive consumers (scoring pipelines, scout-style analysis, full-fidelity Python reads) that want the fully hydrated final event genuinely need the whole conversation — that is information content, and no format fixes it. The mitigation is API-shaped, not format-shaped: reading APIs must not force hydration.

### Confounder 2: structure without content (inventory pattern 6)

Why can't first render get by with just the event count? Count + estimated row heights is fully sufficient for a *flat* virtualized list (scrollbar extent + fetch-on-scroll — pattern 6 would collapse into pattern 4). Three consumers break count-only, in descending stringency:

1. **The main transcript is a flattened tree, not a flat list** (`treeifyEvents` → `flatTree`): every event carries `span_id`, rows are the depth-first flattening filtered by collapse state. A collapsed span elides its descendants, so row count ≠ event count. Naively that demands span membership of every event; per-span descendant counts + extents get row counts and elision without per-event data (see resolution), with span membership of *fetched* events coming from their bodies.
2. **The outline (left tree view)**: renders spans, which are sparse (span begin/end events, orders of magnitude fewer than events). A sparse span sequence serves it without per-event data.
3. **Timeline/swimlanes**: currently walks the full events array but is conceptually span-driven (rows = spans, extents = timestamps); the same sparse span data could serve it.

Structure metadata is also the elision index: per-chunk span coverage lets a collapsed 10k-event span skip fetching its chunks entirely.

**Resolution (direction): a span-proportional structural skeleton.** One persisted structure per sample, sized by the invariant **skeleton ∝ span count** — fixed-size counters per span, nothing event-proportional (model events scale with sample size too, so even "one entry per turn" is disallowed). Contents:

- **Span tree**: per span — span_id, name, type, parent, begin-event index, time extents (timestamps/working_start, which also serve the timeline/swimlanes).
- **Per-span counters**: descendant event count (scrollbar extent under collapse — row count ≠ event count), model-event count (turn synthesis and "turn N of M" numbering without per-turn entries; `collapseTurns` folds runs of turns into one "N turns" row anyway), plus collapse-relevant flags (e.g. contains-failed-tool).
- **Span event extents** `[first, last]` sequence indexes: the elision index — a collapsed span skips fetching its chunks. Interleaved (parallel) spans make extents overlap; that's tolerated (elision is an optimization, correctness comes from span_id on fetched events).
- **Sparse notable positions** only for genuinely sparse event types (score events for `collapseScoring`); never for event-proportional types.

How each consumer is served:

1. **Main transcript** gets *no per-event data*. It windows events (pattern 4) and uses the skeleton only for scrollbar extent under collapse and fetch elision. `treeifyEvents`/`transformTree`/retry-grouping/approval-pairing rework from whole-array passes to window-local operation slotted into the skeleton's span scaffolding (pairs like approval↔tool and retry runs are adjacent in the sequence; fetch-with-margin covers window edges).
2. **Outline** synthesizes its rows client-side from the skeleton alone: span rows via the `transformTree` unwrapping policy, "N turns" rows from model-event counters, scoring row from score positions.
3. **Timeline/swimlanes** read span extents from the skeleton.

The skeleton stores *raw* structure, and the transformations remain client-side viewer policy — persisting transformed output would freeze policy into data.

**Identity is the sequence index, not uuid.** Node ids (collapse-state keys, outline↔transcript scroll sync, selection, deep links) become event sequence indexes (spans: span_id). Per-event uuids are never persisted outside event bodies — 100M events would mean gigabytes of uuids. Indexes are as stable as uuids for a completed log (append-only during the run, immutable at rest — the same property `input_refs` relies on). Legacy `?event=<uuid>` deep links resolve by an on-demand scan of event chunks (rare, one-time, parallelizable).

**Event-type filtering (pattern 8)**: exact filtered row counts need per-event types. Per-chunk type counts give an approximate-then-exact scrollbar — and are independently load-bearing for pagination decode (see "View-row pagination"), so they ride along regardless; only the exact-count UX stance stays open.

Field-level inputs of every viewer transformation: see the appendix. Draft structure: see "Structural skeleton (draft)".

### Confounder 3: jump-to-end with variable-height rows

Ctrl+End / follow-output must position a scrollbar in a virtualized list whose row heights are unknowable without rendering. Today's approach — estimated heights cached and refined as rows render, error shrinking with row count — carries over; heuristics are unavoidable. Pagination doesn't make this worse (the shell's counts give the estimator its denominator with zero chunk fetches), but research is needed on how best-in-class virtualizers handle it.

## Structural skeleton (draft)

Draft spec for the Confounder 2 resolution — stances proposed, not decided. Everything here is bounded by the invariant **skeleton ∝ structural span count (+ sparse notables)**, never event count: no per-event entry of any width exists (at 100M events even one packed word per event is 800MB — the fix is asymptotic class, not bit-packing).

### Entry & lifecycle

- **Sibling entry** `skeleton.json` under the sample prefix, not a shell field: the shell stays cheap-by-construction and schema-stable while the skeleton iterates under its own `version`; the two fetch in parallel at sample open. Monolithic small samples (below the small-sample threshold) carry no skeleton — the viewer derives structure in memory as today.
- **Derived data.** The skeleton is a deterministic function of the events sequence (producer: the Python timeline code with its TS twin — see Proposed direction). Recovery from corruption or version skew is regeneration, never migration; the converter backfills it for converted logs. Written at sample finalize; the append-only event sequence permits incremental update if the live-write path wants it.

### Structure

Three parts: sample totals, the span table, the notables table.

```jsonc
{
  "version": 1,
  "counts": { "events": 250000, "models": 3400 },   // sample totals
  "spans": [
    {
      "id": "aB3x…",               // span_id (identity for span rows / collapse keys)
      "parent": null,               // index into this array
      "name": "react",
      "type": "agent",             // solver | agent | subtask | handoff | scorer | …
      "begin": 1042,                // sequence index of the span_begin event
      "extent": [1042, 15200],      // [first, last] descendant event index (fetch elision;
                                    //   parallel spans may overlap — tolerated, correctness
                                    //   comes from span_id on fetched events)
      "t": ["2026-07-01T10:00:02Z", "2026-07-01T10:41:17Z"],  // timeline extents
      "working": [12.5, 340.2],
      "events": 14158,              // descendant event count (incl. nested spans)
      "models": 212,                // descendant model-event count
      "gap_models": [5, 190, 0, 17],// see "Turn placement" below
      "children": { "state": 1 },   // direct-child event-type counts, sparse —
                                    //   feeds child-shape transformer matches
      "flags": ["failed_tool"]      // collapse-relevant booleans, sparse
    }
  ],
  "notables": [
    { "i": 9120, "span": 0, "type": "score" },
    { "i": 249995, "span": 0, "type": "checkpoint", "checkpoint_id": 3 }
  ]
}
```

**Turn placement (`gap_models`) — the load-bearing counter.** Define a span's *items* as its direct-child structural spans and its notables, merged in sequence order. `gap_models[k]` = model-event count strictly between item `k-1` and item `k` (bounded by the span's begin/end), so `len == items + 1`. This is exactly the outline's row layout for the span: walk gaps and items in order, emitting one "N turns" row per nonzero gap. Splitting between items matters because today's turn synthesis flushes a run at every intervening row — a score or child span between model events splits the run — and gap counters reproduce that without per-turn entries. A gap row's anchor ordinal (scroll sync, deep links, collapse key) is the gap's lower bound.

**Notables table** — positions of genuinely sparse event types the outline renders as rows: `score`, `error`, `sample_limit`, `compaction`, `checkpoint` (with the minimal per-type extra a label needs, e.g. `checkpoint_id`). `span` is the owning span (extent containment is ambiguous under interleaving). Trap: score events are *not* guaranteed sparse — intermediate scoring can emit one per turn, which is event-proportional. Writer caps the table (policy, e.g. 10k) and sets an `overflow` flag; overflow degrades scoring rows in the outline, never counters or correctness. Cap policy open.

**Leaf-tool exclusion rule.** Every tool call gets a `type: "tool"` span, so raw span count is a constant fraction of event count (~1/10–1/30) — event-proportional in disguise. A tool span with no child spans, no model events, and no notables is excluded and summarized in its parent's counters (`events`, `children`). Tool spans containing structure (agent-as-tool, handoff subtrees, model calls) stay. "Structural span" means: a span that can produce an outline row.

### Consumer contracts

- **Outline**: rows synthesized per span from items + `gap_models` (document order falls out); labels/icons/tooltips are viewer policy over `name`/`type`/notable type. Row identity: `span_id` for spans, anchor ordinal for gap/notable rows.
- **Scroll sync**: coordinate system is the sequence index. The main list reports its topmost visible ordinal; current outline row = binary search over row anchor ordinals. No id enumeration anywhere (today's O(events) `elementIds` surface dies).
- **Main transcript**: `events` counters give scrollbar extent under collapse; `extent` gives fetch elision; cumulative `models`/`gap_models` give "turn N of M" numbering window-locally.
- **Timeline/swimlanes**: `t`/`working` extents.

### Fidelity: parity oracle & signed-off divergences

Acceptance is differential: the legacy in-memory pipeline (frozen as an oracle) vs the skeleton-fed pipeline, compared row-for-row (label, depth, icon, collapsibility) across converted real logs and synthetic fixtures × collapse states (none / each collapsible row / all). Gap-based turns reproduce today's collapse interaction exactly — collapse hides whole subtrees while the collapsed row itself stays visible, so runs never merge or split across a toggle. Known divergence classes, each rare and to be signed off (or rejected) explicitly rather than discovered:

1. **Models nested directly under tool events** (no intervening span): the legacy flat-list synthesis emits a depth-anomalous extra turn row; the skeleton yields the structurally-nested row.
2. **Cross-span consecutive score merging**: legacy merges adjacent score rows into one "scoring" row even across a span boundary; per-span notables yield two.
3. **"N turns" click anchor**: gap lower bound vs legacy's first model event — may differ by leading tool events in the gap.

### Sizing

Structural spans are typically 10s–1000s per sample; ~100B/span raw JSON + small-int gap arrays + a capped notables table → well under 1MB uncompressed even for pathological samples, independent of event count. Object-per-span shown for readability; columnar parallel arrays (`names: […], types: […]`) are the fallback encoding if measurement demands it (RLE/zstd-friendly).

## View-row pagination (draft)

Companion to the skeleton: how the main transcript renders a window of *view rows*. View rows are not events — the viewer transformations (appendix) filter events out, merge runs of events into one row (retry groups, sandbox runs), and elide whole subtrees (collapse) — so "fetch 20 rows" has no fixed answer in raw-event units, and a raw-ordinal window can split mid-row (the UTF-8 mid-character problem: a window boundary landing inside what decodes to a single row). The outline is untouched by all of this — its rows come entirely from the skeleton, zero event reads. For the main list, the resolution is a two-layer decode whose I/O invariant is: **reads ∝ rows emitted, never events skipped**.

### Layer 1: filtered cursor read (the primitive)

`readEvents(fromOrdinal, {types, max}) → {events: [{ordinal, raw}…], next}` — a cursor read over the flat event sequence where **`max` counts *surviving* events**, with type filtering pushed down into the reader (per-chunk type counts let it skip non-matching chunks unread). This is the load-bearing contract: it fully absorbs density (10k logger events between two surviving rows cost ~nothing), so callers never estimate raw↔surviving ratios. A raw-count window primitive would bounce the density problem back to every caller.

A thin `FilteredCursor` wraps it with `peek()`/`next()` over an internal buffer (one refill ≈ one screenful of surviving events) plus `seek(ordinal)`: jump past a skipped range — advance in-buffer if the target is already buffered (small span), else drop the buffer and refetch from the target. `done` covers both exhaustion flavors: seek past the last ordinal, or a refill returning nothing (everything remaining filtered).

### Layer 2: the decode walk

Produce rows by walking surviving events, consuming ~1:1 except where the skeleton lets the walk *seek* (zero reads) or a run *coalesces*:

```ts
// filter always force-includes span_begin/span_end — structure drives the
// walk and is only conditionally a row, never subject to the user's filter
cursor = FilteredCursor(startOrdinal, userFilter ∪ {span_begin, span_end})

while (rows.length < n && !cursor.done) {
  ev = cursor.peek()
  if (ev is span_begin) {
    span = skeleton.byBeginOrdinal(ev.ordinal)
    if (!hasVisibleContents(span, userFilter)) cursor.seek(span.extent[1])  // filterEmpty, from counters
    else if (isCollapsed(span.id)) { rows.push(spanRow(span, collapsed)); cursor.seek(span.extent[1]) }
    else                           { rows.push(spanRow(span, expanded));  cursor.next() }
  }
  else if (ev is span_end) cursor.next()                       // no row
  else if (isRunType(ev)) rows.push(runRow(takeRun(cursor, ev)))
  else { rows.push(eventRow(ev, skeleton.depthAt(ev.ordinal))); cursor.next() }
}
```

Properties: a collapsed span covering 1M events is one row and one seek — collapsed regions are *free*, not expensive. `hasVisibleContents` is answered from per-span type counters (this is why the skeleton carries them; without it an expanded-but-all-filtered span costs a probe read). 20 rows over a 100M-event log ≈ 20-ish event reads + skeleton binary searches.

Starting mid-stream (`startOrdinal = k`, for scroll-to or upward pagination) adds exactly two steps: seed depth from `skeleton.spanStackAt(k)` (binary search over extents — giant spans never need to be fetched to know where you are inside them), and one backward run-resync if `k` lands mid-run. Upward pagination is the same walk over a reversed cursor.

### Runs: the mid-character case, bounded

Merge runs (retry groups, sandbox runs — maximal sequences of consecutive same-kind events under one parent) are the only decode units that can straddle arbitrarily many chunks. Two properties bound them:

1. **Run membership is decidable from type + span facts alone.** So `takeRun` finds a run's extent by scanning chunk *statistics*, not events: a chunk whose type counts say "100% sandbox" cannot contain the terminator — skipped unread. Only the 1–2 mixed chunks at the run's edges are read (a run ends exactly where types mix). Chunk boundary descriptors carrying first/last event type + span_id make edge resolution O(1); without span_id there, the fallback is one extra boundary-chunk read (optimization knob, not correctness).
2. **A run's row needs O(1) representative events, never its contents.** A sandbox-run row is a group header (extent suffices); a retry-group row is the surviving model event + count. The run's interior is fetched only if the user expands into it, then windowed like anything else.

**Design constraint (binding on future transforms):** every row-merging rule must be decidable from type/span facts available in chunk stats — never from event payload contents. A payload-dependent merge rule silently reintroduces unbounded lookback.

### Consequences

- **Per-chunk type counts are load-bearing**, not optional: they are the filter-pushdown mechanism (layer 1) and the run-extent scan (runs), independent of whether the event-type-filter *feature* keeps exact scrollbar counts.
- The virtualizer contract (`totalCount` + `item(index)`) still wants a global view-row index space, which exact-computes only chunk-proportionally (sum surviving counts) and shifts slightly as merges resolve on fetch. Landing: estimate-then-correct, same class of trick as variable row heights (Confounder 3).

## Open questions

(Decided items listed up top in Principles.)

- Mid-sequence state reconstruction (`StateEvent`/`StoreEvent` JSON Patch deltas are hostile to random access; keyframe snapshots are the classic fix; the converter leaves deltas as-is).
- Skeleton (draft spec in "Structural skeleton (draft)"; stances there proposed, not decided). Still genuinely open beyond ratifying those stances: notables cap/degrade policy (intermediate scoring makes score events event-proportional), the exact `flags` set, whether agent spans carry a `desc` for outline tooltips, legacy step-only logs (do step begin/end markers map to span-table entries in the producer?), the columnar-encoding trigger.
- Per-chunk type counts: decided load-bearing (filter pushdown + run-extent scans — see "View-row pagination"); open is only their encoding/placement (chunk boundary descriptors vs a stats sidecar) and whether boundary descriptors also carry first/last span_id.
- Event-type filtering UX stance: exact filtered scrollbar counts (chunk-stat sum) vs approximate-then-correct.
- In-sample search: allowed to become progressive or server-side (scout)?
- Chunk encoding (current: JSON array per chunk; protobuf deferred — the measured +36% per-entry compression toll is the standing pressure). JSONL was considered and set aside: its append-only strength doesn't apply (chunks are sealed write-once zip entries), and it trades away the single-call parse/validate fast path on the common whole-chunk case to buy partial parsing of overreads. Reconsider JSONL's complexity only if parsing of overread chunks proves material.
- Live write path: append chunks as the sample runs (converging recorder with the buffer/filestore segment mechanism) vs assemble at sample completion? Is full-reupload-per-flush in scope? The attachment hash→index dedup table belongs in the sample-buffer SQLite (same pattern as its `message_pool`); a bounded table degrades to duplicate storage, never incorrectness. A native writer can also append messages at creation time, making sequence order = creation order (the converter's appended final-conversation tail is out of chronological order).
- Inline threshold for attachment extraction (currently inherited from `.eval`'s policy). Cross-sample attachment dedup rejected: it breaks per-sample prefix enumeration, sample-independent writes, and sample-level GC.
- Phasing/compat: dual-format period? migration tooling for v2 logs? reader fallback story.
- **Small-sample threshold**: the chunked format's costs (the ~+36% compression toll, per-entry overhead, chattier reads) buy random access that small samples don't need — the toll is regressive at the low end, and a monolithic small sample is the limit case of comingling (recovers the whole toll, one-fetch open, and the browser holds the whole sample anyway). Granularity is per-sample, not per-log (a log mixes one monster transcript among thousands of small samples; the `{id}_epoch_{n}/` prefix supports both shapes side by side): below threshold a sample is stored as a single monolithic entry, above as shell + chunks. Readers then handle both per-sample shapes — softened if the monolith shape is today's `EvalSample` entry, which readers support anyway. Denomination: uncompressed serialized sample bytes — the unit both browser budgets (bytes-before-first-render, bytes-held-in-memory) are actually paid in; item counts are poor proxies (10k events can be 1MB or 1GB), and the writer knows exact bytes for free at sample-finalize. Estimate: ~32MiB. Calibration points from existing per-sample caps (all uncompressed bytes): the viewer strips the events array at 350MiB events / 512MiB total (`ts-mono/apps/inspect/src/utils/clear-events-preprocessor.ts`), refuses samples outright at 2048MiB (`remoteLogFile.ts` `MAX_SAMPLE_SIZE_BYTES`), and caps the raw-JSON tab at 25MiB (`SampleJSONView.tsx`); scout's transcripts API returns 413 above 350MiB (`inspect_scout/_view/_api_v2_transcripts.py` `MAX_TRANSCRIPT_BYTES`). Those caps mark where the monolith *dies* (data amputated or refused) — the threshold marks where it should stop being *chosen*, roughly 10x below, and next to the 25MiB the viewer will render raw. Keep it a config/env knob with CI pinning it to 0 so the chunked path — otherwise exercised only by monster transcripts — is tested on every small log.

## Next steps

1. **Render** (current goal): prove the browser client can consume paginated `.eval2` files — get real converted logs rendering — before investing in the live-write path. Requires the structural skeleton for the outline (Confounder 2).
2. Add a CLAUDE.md rule: any timeline code change must update both the Python and TypeScript implementations and their shared JSON test suite (sync has slipped before).

## Appendix: transformation audit

Every transformation the viewer applies to the event stream, the fields it reads, and where it runs against the skeleton + windowed fetches:

| Transformation | Reads (per event/span) | New home |
|---|---|---|
| `processPendingEvents` (fixups.ts) | `pending`, `uuid` | dropped — live-path only; at-rest logs contain no pending events |
| `collapseSampleInit` (fixups.ts) | event type | window-local; legacy no-span logs only |
| `groupSandboxEvents` (fixups.ts) | event type, timestamp | window-local (sandbox runs are contiguous; margin covers window edges) |
| `injectScorersSpan` (treeify.ts) | span type (`scorer`/`scorers`) | skeleton (synthesize wrapper over scorer spans in the span tree) |
| `treeifyWithSpans` (treeify.ts) | `span_id`, `parent_id` per event | window-local — fetched bodies carry `span_id`; skeleton provides the span scaffolding |
| `transformTree` unwraps: `main`, `solvers`, `checkpoint`, `collapse_same_name_spans` (transform.ts) | span type, span name | skeleton (span-level matches only) |
| `transformTree` child-shape matches: `unwrap_tools`, `unwrap_subtasks`, `unwrap_agent_solver`, `unwrap_handoff` (transform.ts) | direct-child event types + exact counts, tool child's `agent` | skeleton per-span child-type counts for outline purposes; full fidelity window-local in the main transcript |
| `correctRetryTimestamps` / `groupRetryAttempts` (useEventNodes) | model error/success, `span_id`, timestamp | window-local with margin (retry runs are adjacent) |
| `collapseFilters` default-collapse (useEventNodes) | span/step name+type, tool `agent`/`failed`, subtask | skeleton flags for spans; tool/subtask rows evaluated from fetched bodies |
| `filterEmpty` (useEventNodes) | children counts | skeleton counters |
| `removeNodeVisitor` × logger/info/state/store/approval/input/sandbox, `removeStepSpanNameVisitor`, `noScorerChildren` (tree-visitors.ts) | event type, span name/type | outline: implicit (skeleton carries no such events); transcript: window-local |
| `makeTurns` / `collapseTurns` (tree-visitors.ts) | event type sequence (model/tool/logger/info), depth | skeleton `gap_models` counters (see "Structural skeleton (draft)") — synthesize "N turns" rows without per-turn entries |
| `collapseScoring` (tree-visitors.ts) | event type == score | skeleton sparse score positions |
| `computeTurnMap` (tree-visitors.ts) | model-event positions | skeleton cumulative model counters |
| `pairToolApprovals` (toolApprovals.ts) | approval `call.id`/`approver`/`decision` ↔ tool `id` | window-local with margin (pairs are adjacent) |
| `flatTree` row math (flatten.ts) | tree + collapse state | skeleton descendant counts (scrollbar extent), extents (fetch elision) |

