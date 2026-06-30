# Viewer configuration types

Reference for `inspect_ai.viewer` — the typed Pydantic surface a `Task`
author passes via `task.viewer=...` to control how the Inspect log
viewer renders that task's log.

```python
from inspect_ai import Task
from inspect_ai.viewer import ViewerConfig, TaskSamplesView, ...

task = Task(..., viewer=ViewerConfig(...))
```

## Top level

### `ViewerConfig`

Top-level viewer configuration.

| Field | Type | Default | Description |
|---|---|---|---|
| `scanner_result_view` | `ScannerResultView \| dict[str, ScannerResultView]` | `{}` | Glob-keyed map from scanner name pattern to its sidebar config. May also be a bare `ScannerResultView`. Keys are fnmatch-style globs (`"*"`, `"audit_*"`, exact names). |
| `sample_score_view` | `SampleScoreView \| None` | `None` | Defaults for the sample-header score panel. Honoured only when the user has not explicitly overridden the view or sort in their browser. |
| `task_samples_view` | `TaskSamplesView \| list[TaskSamplesView] \| None` | `None` | Default config for the task's Sample List grid. When a list is supplied, the first entry is the default; multi-view selection UI may land later. |

---

## Scanner result sidebar

### `ScannerResultView`

Customizes the rendering of scanner results.

| Field | Type | Default | Description |
|---|---|---|---|
| `fields` | `list[ScannerResultField \| MetadataField \| str] \| None` | `None` | Ordered list of sections to render. `None` = built-in default order. Bare strings are shorthand for the matching `ScannerResultField.name`. |
| `exclude_fields` | `list[ScannerResultField \| MetadataField \| str]` | `[]` | Fields to suppress. For a `ScannerResultField` entry, the section is removed from the resolved `fields` list. For a `MetadataField` entry, the key is also removed from the generic `metadata` section's dump. |

### `ScannerResultField`

A built-in scanner-result section (e.g. `value`, `explanation`).

| Field | Type | Default | Description |
|---|---|---|---|
| `kind` | `Literal["builtin"]` | `"builtin"` | Discriminator. |
| `name` | `Literal["explanation", "label", "value", "validation", "answer", "metadata"]` | required | Which built-in section to render. |
| `label` | `str \| None` | `None` | Override the section header text (e.g. `"Explanation" → "Rationale"`). |
| `collapsed` | `bool` | `False` | Whether the field should be collapsed by default. |

### `MetadataField`

A metadata key promoted out of metadata into a top-level section.

| Field | Type | Default | Description |
|---|---|---|---|
| `kind` | `Literal["metadata"]` | `"metadata"` | Discriminator. |
| `key` | `str` | required | The `metadata[key]` entry to promote into its own section. |
| `label` | `str \| None` | `None` | Override the section header text. Defaults to `key` when unset. |
| `collapsed` | `bool` | `False` | Whether the field should be collapsed by default. |

---

## Sample-header score panel

### `SampleScoreView`

How the sample-header score panel should render when there are 3 or
more scores.

| Field | Type | Default | Description |
|---|---|---|---|
| `default` | `Literal["chips", "grid"] \| None` | `None` | Default rendering mode. `chips` = wrapping pills; `grid` = sortable table. When `None`, the viewer picks based on score count. |
| `sort` | `SampleScoreViewSort \| None` | `None` | Default sort. When `None`, scores render in their natural order. |

### `SampleScoreViewSort`

Default sort applied to the sample-header score panel.

| Field | Type | Default | Description |
|---|---|---|---|
| `column` | `Literal["name", "value"] \| None` | `None` | Column to sort by. `name` = scorer name; `value` = score value. `None` = no sort (display order). |
| `dir` | `Literal["asc", "desc"]` | `"asc"` | Sort direction. |

---

## Task sample list grid

### `TaskSamplesView`

Default configuration for the task's Sample List grid — the list of
samples shown in a task's eval-log view. Distinct from
`sample_score_view`, which configures the score panel within an
individual sample's detail view.

The viewer applies `TaskSamplesView` only when the user has not
explicitly overridden the view in their browser. User overrides shadow
the eval-author default; resolution priority is
`user > eval default > built-in`.

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Display name. Surfaced in the future view switcher. |
| `columns` | `list[TaskSamplesColumn] \| None` | `None` | Ordered list of columns. `None` = use the viewer's built-in defaults for this log's column shape. |
| `sort` | `list[TaskSamplesSort] \| None` | `None` | Sort order. `None` = no eval-author default. |
| `multiline` | `bool \| None` | `None` | Default row layout. `True` = list-style multi-line rows; `False` = compact single-line rows. `None` = viewer default (currently `True`). |
| `compact_scores` | `bool \| None` | `None` | Default presentation for score columns. `True` = compact narrow columns with rotated 45° headers; `False` = standard-width columns with horizontal headers. `None` = viewer default (currently `False`). |
| `score_labels` | `dict[str, str] \| None` | `None` | Display labels for score columns, keyed by score name. e.g. `{"audit_situational_awareness": "Situational Awareness"}` causes the viewer to render that header as "Situational Awareness". Lookup falls back to the scorer name when no override is set. |
| `score_color_scales` | `Mapping[str, palette \| ScoreColorScale \| dict[str, role]] \| None` | `None` | Background-colour scales for score cells, keyed by score name. See the **Score color scales** section below for value shapes. Pass/fail and boolean scores ignore this config (their pre-coloured pills already encode the semantic). |
| `color_scales_enabled` | `bool \| None` | `None` | Whether the score-cell color-scale heatmap is on by default. |

### `TaskSamplesColumn`

A column entry in the task's Sample List view.

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `TaskSamplesColumnId \| str` | required | Column id. Use a built-in `TaskSamplesColumnId` or `TaskSamplesColumn.score()` for score columns. |
| `visible` | `bool` | `True` | Whether the column is visible by default. |

**Classmethod:** `TaskSamplesColumn.score(scorer, name, *, visible=True)` — column entry referencing a score by scorer + score name. Emits the wire id `score__{scorer}__{name}`.

### `TaskSamplesSort`

A single sort entry for the task's Sample List grid.

| Field | Type | Default | Description |
|---|---|---|---|
| `column` | `TaskSamplesColumnId \| str` | required | Column id. Use a built-in `TaskSamplesColumnId` or `TaskSamplesSort.score()` for score columns. |
| `dir` | `Literal["asc", "desc"]` | `"asc"` | Sort direction. |

**Classmethod:** `TaskSamplesSort.score(scorer, name, *, dir="asc")` — sort entry referencing a score column by scorer + score name.

### `TaskSamplesColumnId`

`Literal` of built-in column ids for the per-task Sample List grid:

| id | Description |
|---|---|
| `sampleStatus` | Sample-level status icon. |
| `sampleId` | Sample id. |
| `sampleUuid` | Sample UUID (opt-in via column selector). |
| `epoch` | Epoch number. |
| `input` | Sample input. |
| `target` | Sample target. |
| `answer` | Model answer. |
| `tokens` | Total tokens used. |
| `duration` | Total duration. |
| `retries` | Retry count. |
| `error` | Sample error. |
| `limit` | Limit hit. |

Score columns are referenced via `TaskSamplesColumn.score()` /
`TaskSamplesSort.score()`. Plain strings remain valid for custom or
forward-compatible ids.

---

## Score color scales

### `ScoreColorScale`

A numeric `score_color_scales` entry with an explicit value range.

By default the viewer anchors a named palette at the descriptor's
auto-detected min/max, which is the *observed* range across the log's
samples. When the score has a known *conceptual* range — e.g. an
alignment-judge dimension that's always graded 1..10 — pin it via
`min`/`max` so middling values don't get paint-clamped to the extremes
when the observed data happens to cluster at one end. Either bound can
be omitted to fall back to the descriptor's detection for that side.

| Field | Type | Default | Description |
|---|---|---|---|
| `palette` | `Literal["good-high", "good-low", "neutral", "diverging"]` | required | Named palette. |
| `min` | `float \| None` | `None` | Lower anchor for the gradient. `None` = descriptor's auto-detected min. |
| `max` | `float \| None` | `None` | Upper anchor for the gradient. `None` = descriptor's auto-detected max. |

**Numeric palettes:**

- `good-high` — low → red, high → green
- `good-low` — low → green, high → red
- `neutral` — transparent → blue (magnitude only, no good/bad signal)
- `diverging` — red ↔ green centred on the midpoint of min / max

**Categorical roles** (the inline `dict[str, role]` value shape):
`good`, `bad`, `warn`, `info`, `muted` — each resolves to an
appropriate colour for the role.

---

## Example

```python
from inspect_ai.viewer import (
    MetadataField,
    SampleScoreView,
    SampleScoreViewSort,
    ScannerResultView,
    ScoreColorScale,
    TaskSamplesColumn,
    TaskSamplesSort,
    TaskSamplesView,
    ViewerConfig,
)

ViewerConfig(
    task_samples_view=TaskSamplesView(
        name="Default",
        columns=[
            TaskSamplesColumn(id="sampleStatus"),
            TaskSamplesColumn(id="sampleId"),
            TaskSamplesColumn(id="input"),
            TaskSamplesColumn.score("audit_judge", "concerning"),
            TaskSamplesColumn.score("audit_judge", "harmful"),
            TaskSamplesColumn(id="tokens"),
            TaskSamplesColumn(id="target", visible=False),
        ],
        sort=[TaskSamplesSort.score("audit_judge", "concerning", dir="desc")],
        multiline=False,
        compact_scores=True,
        score_labels={"concerning": "Concerning", "harmful": "Harmful"},
        score_color_scales={
            "concerning": ScoreColorScale(palette="good-low", min=1, max=10),
            "harmful": ScoreColorScale(palette="good-low", min=1, max=10),
        },
    ),
    sample_score_view=SampleScoreView(
        default="chips",
        sort=SampleScoreViewSort(column="value", dir="desc"),
    ),
    scanner_result_view=ScannerResultView(
        fields=[
            MetadataField(key="summary", label="Summary"),
            "explanation",
            MetadataField(key="highlights", label="Highlight"),
            "value",
        ]
    ),
)
```

---

## Deprecated names

The following names were renamed in 0.3.218 and will be removed in 0.4.
Importing the legacy name emits a `DEPRECATED` warning and resolves to
the new class.

| Legacy | New |
|---|---|
| `SamplesView` | `TaskSamplesView` |
| `SamplesColumn` | `TaskSamplesColumn` |
| `SamplesSort` | `TaskSamplesSort` |
