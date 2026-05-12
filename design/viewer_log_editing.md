# Viewer Log Editing

## Summary

Add the ability to edit eval log files from inside the inspect viewer. The viewer
currently is read-only against `EvalLog` files; this work expands the view server
with HTTP endpoints that wrap the existing Python edit APIs in
`inspect_ai.log` and lays groundwork for matching UI affordances.

Scope is everything in the inspect API that accepts a `ProvenanceData`:

| Python API | Wrapped server endpoint (planned) | Phase |
|------------|-----------------------------------|-------|
| `edit_eval_log` (`TagsEdit`)      | `POST /api/log-edit/{log}` | 1 (this change) |
| `edit_eval_log` (`MetadataEdit`)  | `POST /api/log-edit/{log}` | 2 |
| `invalidate_samples`              | `POST /api/log-invalidate-samples/{log}` | 3 |
| `uninvalidate_samples`            | `POST /api/log-uninvalidate-samples/{log}` | 3 |

`uninvalidate_samples` does not take `ProvenanceData` but pairs with
`invalidate_samples` and belongs alongside it.

## Motivation

Eval log mutation has, until now, been a Python-only workflow:

```python
log = read_eval_log(path)
log = edit_eval_log(log, [TagsEdit(tags_add=["qa_passed"])], ProvenanceData(author="alice"))
write_eval_log(log)
```

Surfacing the same operations through the viewer lets reviewers, QA, and
non-Python users perform the same workflows without dropping into a shell or
notebook. The natural delivery vehicle is the existing view server (both the
aiohttp and FastAPI variants) so that hosted viewer deployments (e.g.
inspect-flow) inherit the new endpoints for free.

## Non-goals

- CLI commands for editing logs (already noted as out-of-scope in
  `log_edits_tags_metadata.md`; tracked separately).
- Editing scores (`edit_score` does not take `ProvenanceData` and follows a
  different storage path — separate effort).
- Concurrency control beyond what S3 conditional writes (`if_match_etag`) already
  provide. The Phase 1 endpoint performs a read-modify-write against the header
  only; collision handling is best-effort and documented per endpoint.

## Phase 1 — Tag edits (this change)

### Endpoint

```
POST /api/log-edit/{log}
Content-Type: application/json

{
  "edits": [
    { "type": "tags", "tags_add": ["qa_passed"], "tags_remove": ["needs_qa"] }
  ],
  "provenance": { "author": "alice", "reason": "QA complete" }
}
```

The request body matches the existing `LogUpdate` pydantic model
(`inspect_ai.log._edit.LogUpdate`): a discriminated union of `TagsEdit` /
`MetadataEdit` plus a `ProvenanceData`. Phase 1 only exercises the `TagsEdit`
branch on the server but the schema accepts both because they share an
implementation; the metadata variant is unblocked in Phase 2 with no server
changes if we choose to ship it that way.

Response: the updated `EvalLog` header (same shape as `GET /api/logs/{log}?header-only=0`).
This gives the client the recomputed `tags` / `metadata` and the new
`log_updates` entry without a follow-up round trip.

### Handler shape

```python
log = await read_eval_log_async(file, header_only=True)
log = edit_eval_log(log, body.edits, body.provenance)
await write_eval_log_async(log, location=file, header_only=True)
```

`header_only=True` is correct on both sides: tags, metadata, and `log_updates`
all live in the header, and `write_eval_log_async(..., header_only=True)`
appends the new header to the existing zip without touching samples. This keeps
edits cheap for large logs.

### Access policy

`AccessPolicy` (FastAPI) gains `can_write` alongside the existing
`can_read` / `can_delete` / `can_list`. `OnlyDirAccessPolicy` returns `True` for
files inside the log dir (mirroring `can_delete`). aiohttp continues to rely on
the `validate_log_file_request` helper plus the optional `Authorization` header.

### Errors

| Condition | Response |
|-----------|----------|
| File outside `log_dir` (no auth) | 401 (aiohttp) / 403 (FastAPI) |
| Body validation fails (pydantic) | 422 |
| `edit_eval_log` raises `ValueError` (empty tag, overlap, etc.) | 400 |
| Underlying read/write fails | 500 |
| Conditional write conflict (future) | 409 |

### Out of scope for Phase 1

- ETag round-trip / `If-Match`. Editing is single-writer in the common viewer
  case; deferring until we add S3-hosted multi-user editing.
- Surfacing edit history in the viewer UI (Phase 4).

## Phase 2 — Metadata edits

If we keep one unified `/api/log-edit` endpoint, this is purely a viewer/UI
exercise: surface a metadata editor that POSTs `MetadataEdit` payloads to the
same route. Server-side test coverage gets extended to the metadata branch.

## Phase 3 — Sample invalidation

Two endpoints, each wrapping the matching Python function:

```
POST /api/log-invalidate-samples/{log}
{
  "sample_uuids": ["..."] | "all",
  "provenance":   { "author": "...", ... }
}

POST /api/log-uninvalidate-samples/{log}
{
  "sample_uuids": ["..."] | "all"
}
```

These do touch sample records, so a full read + write (not header-only) is
required. We need to think about:

- Streaming large logs through memory (consider `read_eval_log_sample` style
  partial mutation) — open question.
- Whether the response should be the new header or the modified samples.

## Phase 4 — View UI

Out of scope for this design doc; deferred until the server endpoints land and
stabilize. Initial sketch (from `log_edits_tags_metadata.md`):

- Display effective `tags` / `metadata` on the log header.
- Inline tag chip editor that POSTs a `TagsEdit`.
- Expandable edit history with provenance (like the existing invalidation
  card).
- Tag filter on the log list view.

A follow-up doc will cover the UI design once the server side is stable.

## Open questions

- Auth/identity: today the viewer has a single shared `Authorization` token. We
  surface `provenance.author` from the client. If we ever want server-attested
  authors, we need a real auth story — out of scope here.
- Editing in-progress logs: edits against a still-running eval would race
  the recorder. Phase 1 simply doesn't gate this; the recorder will overwrite.
  Worth deciding before Phase 3 (sample invalidation can plausibly target a
  running eval).
- Eval-format vs JSON-format logs: `header_only` write is implemented per
  recorder. Verify both recorders honor `header_only=True` semantics — Phase 1
  tests cover the `.eval` recorder; `.json` is a follow-up if we keep
  supporting it for editing.

## Files touched (Phase 1)

| File | Change |
|------|--------|
| `src/inspect_ai/_view/common.py` | (optional) helper for editing if shared between servers |
| `src/inspect_ai/_view/server.py` | aiohttp: `POST /api/log-edit/{log}` |
| `src/inspect_ai/_view/fastapi_server.py` | FastAPI: `POST /log-edit/{log:path}`, `AccessPolicy.can_write`, `OnlyDirAccessPolicy.can_write` |
| `tests/_view/test_view_server.py` | parameterized roundtrip + validation tests |
