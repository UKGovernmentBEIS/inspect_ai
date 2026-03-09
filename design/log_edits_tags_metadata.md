# Log Edits Spec (Unified Tags + Metadata)

## Summary

Add the ability to edit tags and metadata on existing eval logs with provenance tracking. Eval-time values (`EvalSpec.tags`, `EvalSpec.metadata`) remain unchanged. A new `log_updates` field on `EvalLog` records post-eval mutations as an append-only edit log. Convenience functions and properties provide separate tag/metadata interfaces; shared storage keeps internals simple.

## Motivation

Users need to annotate logs after evaluation for workflows like QA review, categorisation, and filtering. Currently tags and metadata can only be set at eval-time via `eval(tags=..., metadata=...)` or `--tags` / `--metadata`. Post-eval editing enables workflows like: tag as `"needs_qa"` at eval time -> teammate filters by tag -> reviews and removes/adds tags and metadata.

## Task-Level Tags

Add a `tags` parameter to `Task`, mirroring the existing `metadata` parameter. Task tags and eval tags are merged at eval time using union, matching how metadata works today:

```python
class Task:
    def __init__(
        self,
        ...
        tags: list[str] | None = None,    # NEW
        metadata: dict[str, Any] | None = None,
        ...
    ) -> None:
        ...
        self.tags = tags
```

In `eval_run()`, merge eval-level and task-level tags (mirroring the metadata merge on line 233):

```python
tags=list(set(tags or []) | set(task.tags or [])) or None,
```

Both sources contribute; duplicates are eliminated.

### Files to Modify

| File | Change |
|------|--------|
| `src/inspect_ai/_eval/task/task.py` | Add `tags` parameter to `Task.__init__()` |
| `src/inspect_ai/_eval/run.py` | Merge `tags` and `task.tags` (line 219) |
| `tests/test_metadata.py` | Add tests for task-level tags and merge behavior |

## Design: Unified Edit Log Overlay

`EvalSpec.tags` and `EvalSpec.metadata` stay unchanged (no breaking changes). Post-eval mutations are stored as an ordered list of edits on `EvalLog`.

### Data Model

```python
# In src/inspect_ai/log/_edit.py


class LogUpdate(BaseModel):
    """A group of edits that share provenance."""
    edits: list[LogEdit] = Field(default_factory=list)
    provenance: ProvenanceData

class LogEdit(BaseModel):
    """A single edit action on log tags and/or metadata."""

class TagsEdit(LogEdit):
    tags_add: list[str] = Field(default_factory=list)
    tags_remove: list[str] = Field(default_factory=list)

class MetadataEdit(LogEdit):
    metadata_set: dict[str, Any] = Field(default_factory=dict)
    metadata_remove: list[str] = Field(default_factory=list)

```

```python
# In src/inspect_ai/log/_log.py, on EvalLog
# Place AFTER `invalidated` field, BEFORE `samples` field

log_updates: list[LogUpdate] | None = Field(default=None)
"""Post-eval edits to tags and metadata."""
```

Existing logs deserialize fine (`log_updates` defaults to `None`).

### Read API

Access tags and metadata directly on `EvalLog`:

```python
log.tags        # list[str] — eval-time tags + edits applied
log.metadata    # dict[str, Any] — eval-time metadata + edits applied
```

- `log.tags` / `log.metadata` — current values with edits applied, persisted to disk (use these)
- `log.eval.tags` / `log.eval.metadata` — eval-time values only (unchanged)

These are regular Pydantic fields that are **persisted** to disk and **recomputed** from `eval` + `log_updates` on deserialization via a model validator. This means:

1. Simple consumers (JS, jq, View UI) read `tags` and `metadata` directly from JSON.
2. Python consumers access them as normal fields.
3. All writes go through `edit_eval_log()` — direct assignment should not be used.

See `EvalLog.recompute_tags_and_metadata()` in [`_log.py`](../src/inspect_ai/log/_log.py). It runs automatically on construction/deserialization (via `@model_validator`) and is called explicitly by `edit_eval_log()` after appending a new `LogUpdate`.

### Write API

```python
def edit_eval_log(
    log: EvalLog,
    edits: list[LogEdit],
    provenance: ProvenanceData,
) -> EvalLog:
    """Apply edits to a log.

    Creates a LogUpdate from the edits and provenance, appends it to
    log.log_updates, and recomputes cached tags/metadata.
    Returns modified log (not persisted). Use write_eval_log() to save.
    """
```

### Usage

```python
from inspect_ai.log import (
    read_eval_log, write_eval_log, edit_eval_log,
    TagsEdit, MetadataEdit, ProvenanceData,
)

log = read_eval_log("path/to/log.eval")

# Edit
log = edit_eval_log(log, [
    TagsEdit(tags_add=["qa_passed"], tags_remove=["needs_qa"]),
    MetadataEdit(metadata_set={"reviewer": "alice"}, metadata_remove=["draft_notes"]),
], ProvenanceData(author="alice", reason="QA complete"))
write_eval_log(log, location=log.location)

# Read
log.tags        # ["qa_passed"]
log.metadata    # {"reviewer": "alice", ...}
```

### list_eval_logs: tags filter

Add a convenience `tags` parameter to `list_eval_logs`:

```python
def list_eval_logs(
    log_dir: str = ...,
    formats: list[Literal["eval", "json"]] | None = None,
    filter: Callable[[EvalLog], bool] | None = None,
    tags: list[str] | None = None,           # NEW
    recursive: bool = True,
    descending: bool = True,
    fs_options: dict[str, Any] = {},
) -> list[EvalLogInfo]:
```

When `tags` is provided, only logs where ALL specified tags are in `log.tags` are returned. Applied in addition to the existing `filter` parameter. Uses header-only reads (`log_updates` is in the header).

### Public Exports

Add to `inspect_ai.log.__init__` exports:
- `LogEdit`, `TagsEdit`, `MetadataEdit`, `LogUpdate`, `ProvenanceData`
- `edit_eval_log`

### Write Path

Matches invalidation pattern:
1. `read_eval_log()` to load
2. `edit_eval_log()` to mutate in-memory
3. `write_eval_log()` to persist

`log_updates` is a top-level `EvalLog` field, so it's included in `header.json` inside the eval zip file. Header-only reads pick it up automatically.

### Consumer Migration

| Consumer | Current | Change |
|----------|---------|--------|
| `evals_df` tags column | Reads `eval.tags` path | Use `log.tags` property |
| `evals_df` metadata column | Reads `eval.metadata` path | Use `log.metadata` property |
| View UI TaskTab | `evalSpec.tags.join(", ")` | Use `EvalLog.tags` property |
| `list_eval_logs` | No tag filter | Add `tags` param using `log.tags` |

### View UI

- Display tags on the log header/info panel (from `EvalLog.tags`).
- Show edit history (with provenance) in an expandable section, similar to invalidation cards.
- Add tag filter to log list view.

### Edge Cases

- **Adding a tag already in `log.tags`**: No-op (don't append edit).
- **Removing a tag not in `log.tags`**: No-op.
- **Re-adding a previously removed tag**: Appends a new edit (audit trail preserved).
- **Empty tag string**: Reject with ValueError.
- **Setting a metadata key to same value**: Appends edit (value may have changed semantically).
- **Removing a metadata key that doesn't exist**: No-op.

### Files to Modify

| File | Change |
|------|--------|
| `src/inspect_ai/log/_log.py` | Add `log_updates` field, `tags` and `metadata` properties to `EvalLog` |
| `src/inspect_ai/log/_edit.py` | Add `LogEdit`, `TagsEdit`, `MetadataEdit`, `LogUpdate`, `ProvenanceData`, `edit_eval_log` |
| `src/inspect_ai/log/__init__.py` | Export new types and functions |
| `src/inspect_ai/log/_file.py` | Add `tags` parameter to `list_eval_logs` |
| `src/inspect_ai/_view/www/src/@types/log.d.ts` | Auto-regenerated |
| `src/inspect_ai/_view/www/src/app/log-view/tabs/TaskTab.tsx` | Display effective tags/metadata |
| `src/inspect_ai/analysis/_dataframe/evals/columns.py` | Use `log.tags` / `log.metadata` for DataFrame columns |
| `tests/log/test_edit.py` | Tests for all new functions |

### Not in Scope

- CLI command for editing logs (future work, likely in inspect-flow)
