# Framing: Pagination of Messages/Events Within a Sample

Status: framing/explanation — not yet a plan. Captures problem, principles, current design, proposed direction, access-pattern inventory, confounders, open questions, and next steps.

## Problem

A single sample must support an essentially arbitrary number of messages and events. Today all data for a sample lives in one JSON entry inside the `.eval` zip. JSON parses sequentially from the top, which is at odds with the near-term requirement to serve windows/pages of messages and events.

## Principles & working assumptions

Principles:

- **Scale target**: samples with 10M+ messages must be tractable.
- **Single portable `.zip`** containing everything remains the format.
- **Viewer access model**: paginated, filtered, index-based queries only — there is no "get all events" access pattern in the new design (sorting is unused). Full-fidelity reads (export, Python `read_eval_log`) remain as explicit bulk operations.
- **Data comes straight from the eval file** even when a server is present — the server just serves bytes.

Decided (implemented in the converter, `src/inspect_ai/log/_recorders/eval2/`): four flat chunked sequences per sample (messages, events, calls, attachments) as zip entries with client-driven random access; chunk names carry the start index only; count-based chunking for item sequences and size-based for attachments (both writer policy); JSON-array chunk encoding; stable per-sample indexes with range-encoded references, half-open `[start, end_exclusive)` everywhere ranges appear in data; rehydration external to the format. Still open: per-sample TOC (likely = the precomputed timeline).

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
- **The TOC is (likely) the timeline.** The timeline — today computed in-memory by the client on every sample load — is precomputed and embedded per sample, becoming the persisted data source for the tree view/outline. Two timeline implementations exist (Python `src/inspect_ai/event/_timeline.py`, TS `inspect-components/src/transcript/timeline/`) kept in sync via a shared JSON test suite. Computation is cheap (type comparisons, no content introspection); the event sequence is append-only, so it's rewritten (or incrementally updated) at sample boundaries. Index→chunk mapping stays in chunk filenames — the TOC is not needed for that.
- **Chunk names carry the start index only** (`{start}.json`, no zero-padding). Filenames have no range semantics: every range that appears in the *data* is half-open `[start, end_exclusive)` (matching Python/TS slicing and the `input_refs` convention), and a filename like `0-50` invites inclusive misreading. Chunks are contiguous and complete, so the chunk holding index `i` is the one with the greatest start ≤ `i`; a chunk's extent is the next chunk's start, and the last chunk's end is the sequence count from the shell's `sequences` boundaries. Every reader must fetch the zip central directory anyway (byte offsets), so index→chunk is a binary search over numerically-sorted entry names. This makes the format **agnostic to chunking policy**: count-based (item sequences, default 1000), size-based (attachments, ~2MiB target), or adaptive chunking all read identically — chunking is a writer-side tuning knob, not a format property. The TOC therefore earns its keep only for per-chunk metadata (type counts, span/time ranges) — not for index mapping.
- **Chunks as zip entries preserves the architecture**: clients keep doing byte-range + central-directory reads; no new server endpoints required for completed logs.
- **Events reference messages by stable per-sample indexes, range-encoded** as half-open `[start, end_exclusive)` pairs (e.g. `[[0, 9874], [9875, 9876]]`), never flat lists — model-event inputs are prefixes-plus-delta, and flat lists are O(N²) across a transcript. (`ModelEvent.input_refs` uses exactly this encoding into the pool; `.eval2` keeps it unchanged.)
- **Rehydration is a consumer concern**: the format guarantees stable ids and range-named chunks; consumers resolve which message chunks a window of events needs (via central-directory names) and fetch them independently. (See confounder: the last page.)
- **The message sequence subsumes the `events_data.messages` pool**: pooled messages and top-level `messages` are the same currency (`ChatMessage`) — they differ only in membership (pool = superset across all ModelEvent inputs; top-level = the final main thread). The sequence *is* the pool, extended with any final-conversation messages not already pooled (e.g. the last assistant answer, which is only ever an output); the shell's final conversation becomes range-encoded refs (`message_refs`) into it. Sequence order is event-appearance order, not conversation order — consumers must always go through refs. (Precedent: the buffer SQLite DB already has `message_pool` with autoincrement ids.) The `calls` pool is a different currency (raw provider payloads) and a **third sequence**.
- **Attachments survive as a fourth sequence** (bare strings, referenced as `attachment://<index>`; identity = sequence index, content-hash dedup is write-time policy only, never persisted). They cannot be inlined: attachments dedup content *across containers* — the same string recurs in pooled messages, wire request/response payloads, tool events, state deltas, model outputs, and per-turn tool schemas, most of which no pool touches. Measured on an attachment-heavy log (petri, 470 samples): 92MB of unique attachment content is referenced from ~2–6+ sites each and inlines to 444MB. Attachments chunk by target byte size rather than item count (contents vary ~100B to MBs; an oversized item gets a chunk to itself).
- **Sample `metadata` is a sibling entry** (`metadata.json`, written only when non-empty) rather than a shell field — it is user-controlled and can be arbitrarily large.
- **Chunk encoding: JSON first; protobuf deferred.** Ship with JSON-array chunks and revisit encoding only if measurement demands it. The tradeoff to carry in mind: zip compresses entries independently; dedup pools remove *content* duplication but not JSON *structural* redundancy (key names, enum strings), which per-entry zstd currently recovers and which small chunks forfeit — so JSON pressures X upward, and protobuf (which eliminates structural redundancy by construction) is what would make small X cheap. Protobuf's cost is a shared schema with TS + Python codegen (pydantic is currently the source of truth). Range-named chunks make encoding a per-entry concern (the extension says what's inside), so a later protobuf phase is additive, not a format break.

### Zip layout (per sample)

As written by the converter (chunk sizes shown for default policy: 1000 items; ~2MiB attachment chunks). TOC location (inside shell vs separate entry) still open.

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
- Confounder 2 option (c) would add a skinny sibling per event chunk, e.g. `events/0.skel.json`.
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
| 6 | Transcript structure w/o content: event tree, outline, timeline | First render of Transcript tab: `treeifyEvents` (`useEventNodes`), `useTranscriptTimeline`, `TranscriptOutline` | Walks entire events array before first render | **The hard one** — see Confounder 2 |
| 7 | Deep links (event uuid, message→event) | URL deep links / citations: `scrollToEvent` (`TranscriptViewNodes`), `resolveMessageToEvent` | `findIndex` over full array | id→index mapping (TOC or per-chunk id ranges) |
| 8 | Event-type filtering | Transcript filter menu: `eventFilter.filteredTypes` (`TranscriptPanel`) | Client-side array filter | per-chunk type counts in TOC |
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

1. **The main transcript is a flattened tree, not a flat list** (`treeifyEvents` → `flatTree`): every event carries `span_id`, rows are the depth-first flattening filtered by collapse state. A collapsed span elides its descendants, so row count ≠ event count and row↔event mapping needs the span membership of every event. This is the only consumer that needs *something about every event* — but only ~2 tiny fields (span_id, type), not bodies.
2. **The outline (left tree view)**: renders spans, which are sparse (span begin/end events, orders of magnitude fewer than events). A sparse span sequence serves it without per-event data.
3. **Timeline/swimlanes**: currently walks the full events array but is conceptually span-driven (rows = spans, extents = timestamps); the same sparse span data could serve it.

Structure metadata is also the elision index: per-chunk span coverage lets a collapsed 10k-event span skip fetching its chunks entirely.

**Resolution (direction): the precomputed timeline is the structure.** Rather than choosing among a TOC skeleton, a sparse span sequence, or a skeleton column, the existing timeline-building code (which already derives the semantic tree from events) is enhanced to also produce the outline, and both are persisted per sample — eliminating the fetch-all-events pattern for the tree view. The outline persisted is *maximal*: event filtering (e.g. hiding checkpoints) can only reduce it, and compaction-region selection is head/tail slicing, so every runtime view is a subset of the stored one. Remaining details: granularity (per-event leaves vs span-level + counts — decides persisted timeline size) and location (in the shell vs a sibling entry).

### Confounder 3: jump-to-end with variable-height rows

Ctrl+End / follow-output must position a scrollbar in a virtualized list whose row heights are unknowable without rendering. Today's approach — estimated heights cached and refined as rows render, error shrinking with row count — carries over; heuristics are unavoidable. Pagination doesn't make this worse (the shell's counts give the estimator its denominator with zero chunk fetches), but research is needed on how best-in-class virtualizers handle it.

## Open questions

(Decided items listed up top in Principles.)

- Mid-sequence state reconstruction (`StateEvent`/`StoreEvent` JSON Patch deltas are hostile to random access; keyframe snapshots are the classic fix; the converter leaves deltas as-is).
- Timeline-as-TOC details: persisted granularity (per-event leaves vs span-level + counts) and location (inside the sample shell entry vs a sibling entry).
- In-sample search: allowed to become progressive or server-side (scout)?
- Chunk encoding (current: JSON array per chunk; protobuf deferred — the measured +36% per-entry compression toll is the standing pressure). JSONL was considered and set aside: its append-only strength doesn't apply (chunks are sealed write-once zip entries), and it trades away the single-call parse/validate fast path on the common whole-chunk case to buy partial parsing of overreads. Reconsider JSONL's complexity only if parsing of overread chunks proves material.
- Live write path: append chunks as the sample runs (converging recorder with the buffer/filestore segment mechanism) vs assemble at sample completion? Is full-reupload-per-flush in scope? The attachment hash→index dedup table belongs in the sample-buffer SQLite (same pattern as its `message_pool`); a bounded table degrades to duplicate storage, never incorrectness. A native writer can also append messages at creation time, making sequence order = creation order (the converter's appended final-conversation tail is out of chronological order).
- Inline threshold for attachment extraction (currently inherited from `.eval`'s policy). Cross-sample attachment dedup rejected: it breaks per-sample prefix enumeration, sample-independent writes, and sample-level GC.
- Phasing/compat: dual-format period? migration tooling for v2 logs? reader fallback story.
- **Small-log threshold**: the chunked format's costs (the ~+36% compression toll, per-entry overhead, chattier reads) buy random access that small samples don't need — the toll is regressive at the low end. The writer may want a threshold (e.g. per-sample event/message counts or byte size) below which it keeps writing the old monolithic form — either whole logs staying `.eval`, or small samples stored as a single entry within an `.eval2` (readers must then handle both per-sample shapes). Where the threshold sits and at which granularity is open.

## Next steps

1. **Render** (current goal): prove the browser client can consume paginated `.eval2` files — get real converted logs rendering — before investing in the live-write path. Requires the timeline-as-TOC for the transcript tree (Confounder 2).
2. Add a CLAUDE.md rule: any timeline code change must update both the Python and TypeScript implementations and their shared JSON test suite (sync has slipped before).
