# inspect_ai.viewer – Inspect

## Viewer

### ViewerConfig

Top-level viewer configuration.

This allows per task customization of the Task’s sample list and each sample’s score and scanner result display.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L267)

``` python
class ViewerConfig(BaseModel)
```

#### Attributes

`scanner_result_view` [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview) \| dict\[str, [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview)\]  
Glob-keyed map from scanner name pattern to its sidebar config. May also be a bare [ScannerResultView](../reference/inspect_ai.viewer.html.md#scannerresultview).

`sample_score_view` [SampleScoreView](../reference/inspect_ai.viewer.html.md#samplescoreview) \| None  
Defaults for the sample-header score panel. Honoured only when the user has not explicitly overridden the view or sort in their browser.

`task_samples_view` [TaskSamplesView](../reference/inspect_ai.viewer.html.md#tasksamplesview) \| list\[[TaskSamplesView](../reference/inspect_ai.viewer.html.md#tasksamplesview)\] \| None  
Default configuration for the task’s Sample List grid (the list of samples shown in a task’s eval-log view). When a list is supplied, the first entry is the default for now; multi-view selection UI may land later. Honoured only when the user has not explicitly overridden the view in their browser.

## Scanner Results

### ScannerResultView

Customizes the rendering of the sample scanner results.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L43)

``` python
class ScannerResultView(BaseModel)
```

#### Attributes

`fields` list\[[ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) \| [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) \| str\] \| None  
Ordered list of sections to render. The list order provides any preferred render order; fields that are not included in the list will be rendered in their natural order after the included fields are rendered. `None` means fall back to the built-in default order.

`exclude_fields` list\[[ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) \| [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) \| str\]  
Fields to suppress. For a [ScannerResultField](../reference/inspect_ai.viewer.html.md#scannerresultfield) entry, the matching section is removed from the resolved `fields` list (useful to subtract from the default order). For a [MetadataField](../reference/inspect_ai.viewer.html.md#metadatafield) entry, the key is additionally removed from the generic `metadata` section’s display.

## Sample Score Panel

### SampleScoreView

How the sample-header score panel should render when there are 3 or more scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L69)

``` python
class SampleScoreView(BaseModel)
```

#### Attributes

`default` Literal\['chips', 'grid'\] \| None  
Default rendering mode. `chips` = wrapping pills; `grid` = sortable table. When None, the viewer picks based on score count.

`sort` [SampleScoreViewSort](../reference/inspect_ai.viewer.html.md#samplescoreviewsort) \| None  
Default sort. When None, scores render in their natural order.

### SampleScoreViewSort

Default sort applied to the sample-header score panel.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L58)

``` python
class SampleScoreViewSort(BaseModel)
```

#### Attributes

`column` Literal\['name', 'value'\] \| None  
Column to sort by. `name` = scorer name; `value` = score value. `None` means no sort (display order).

`dir` Literal\['asc', 'desc'\]  
Sort direction.

## Sample List

### TaskSamplesView

Default configuration for the task’s Sample List grid.

Configures the list of samples shown in a task’s eval-log view.

The viewer applies [TaskSamplesView](../reference/inspect_ai.viewer.html.md#tasksamplesview) only when the user has not explicitly overridden the view in their browser. User overrides shadow the eval-author default; the resolution priority is `user > eval default > built-in`.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L194)

``` python
class TaskSamplesView(BaseModel)
```

#### Attributes

`name` str  
Display name. Surfaced in the future view switcher.

`columns` list\[[TaskSamplesColumn](../reference/inspect_ai.viewer.html.md#tasksamplescolumn)\] \| None  
Default Ordered list of columns. None = use the viewer’s built-in defaults for this log’s column shape.

`sort` list\[[TaskSamplesSort](../reference/inspect_ai.viewer.html.md#tasksamplessort)\] \| None  
Default Sort order. None = no eval-author default (viewer default applies).

`multiline` bool \| None  
Default row layout. True = list-style multi-line rows; False = compact single-line rows. None = viewer default (currently True).

`compact_scores` bool \| None  
Default presentation for score columns. True = compact narrow columns with rotated 45° headers; False = standard-width columns with horizontal headers. None = viewer default (currently False).

`score_labels` dict\[str, str\] \| None  
Display labels for score columns, keyed by score name. e.g. `{"audit_situational_awareness": "Situational Awareness"}` causes the viewer to render that header as “Situational Awareness” instead of the raw scorer name. Lookup falls back to the scorer name itself when no override is set.

`score_color_scales` dict\[str, Literal\['good-high', 'good-low', 'neutral', 'diverging'\] \| [ScoreColorScale](../reference/inspect_ai.viewer.html.md#scorecolorscale) \| dict\[str, Literal\['good', 'bad', 'warn', 'info', 'muted'\]\]\] \| None  
Background-colour scales for score cells, keyed by score name. Each entry is one of:

- a named palette string (numeric scores; gradient anchored at the descriptor’s auto-detected min/max);
- a [ScoreColorScale](../reference/inspect_ai.viewer.html.md#scorecolorscale) with the same palette name plus optional `min`/`max` overrides (numeric scores with a known *conceptual* range that may not match the observed data range);
- a map from value to semantic role (categorical scores).

Numeric palettes: - `good-high`: low → red, high → green - `good-low`: low → green, high → red - `neutral`: transparent → blue (magnitude only, no good/bad signal) - `diverging`: red ↔︎ green centred on the midpoint of min / max

Categorical roles (`good` / `bad` / `warn` / `info` / `muted`) resolve to appropriate colors for the category.

Pass/fail and boolean scores ignore this config — their pre-coloured pills already encode the semantic. Scores not in the map render with no background.

`color_scales_enabled` bool \| None  
Whether the score-cell color-scale heatmap is on by default.

### TaskSamplesColumn

A column entry in the task’s Sample List view.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L138)

``` python
class TaskSamplesColumn(BaseModel)
```

#### Attributes

`id` TaskSamplesColumnId \| str  
Column id. Use a built-in `TaskSamplesColumnId` or `TaskSamplesColumn.score()` for score columns.

`visible` bool  
Whether the column is visible by default.

#### Methods

score  
Column entry referencing a score column.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L148)

``` python
@classmethod
def score(
    cls,
    scorer: str,
    score: str | None = None,
    *,
    visible: bool = True,
) -> "TaskSamplesColumn"
```

`scorer` str  
Scorer name (the key under `sample.scores`).

`score` str \| None  
Sub-score key, used only when a scorer emits a dictionary of named values. Defaults to `scorer`, which is correct for the common case of a scorer producing a single value. This is *not* a metric such as `accuracy` or `stderr` — those are aggregated across samples and do not appear as per-sample columns.

`visible` bool  
Whether the column is visible by default.

### TaskSamplesSort

A single sort entry for the task’s Sample List grid.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L105)

``` python
class TaskSamplesSort(BaseModel)
```

#### Attributes

`column` TaskSamplesColumnId \| str  
Column id. Use a built-in `TaskSamplesColumnId` or `TaskSamplesSort.score()` for score columns.

`dir` Literal\['asc', 'desc'\]  
Sort direction.

#### Methods

score  
Sort entry referencing a score column.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L115)

``` python
@classmethod
def score(
    cls,
    scorer: str,
    score: str | None = None,
    *,
    dir: Literal["asc", "desc"] = "asc",
) -> "TaskSamplesSort"
```

`scorer` str  
Scorer name (the key under `sample.scores`).

`score` str \| None  
Sub-score key, used only when a scorer emits a dictionary of named values. Defaults to `scorer`, which is correct for the common case of a scorer producing a single value. This is *not* a metric such as `accuracy` or `stderr` — those are aggregated across samples and do not appear as per-sample columns.

`dir` Literal\['asc', 'desc'\]  
Sort direction.

## Score Colors

### ScoreColorScale

A numeric `score_color_scales` entry with an explicit value range.

By default the viewer anchors a named palette at the descriptor’s auto-detected min/max, which is the *observed* range across the log’s samples. When the score has a known *conceptual* range — e.g. an alignment-judge dimension that’s always graded 1..10 — pin it via `min`/`max` so middling values don’t get paint-clamped to the extremes when the observed data happens to cluster at one end. Either bound can be omitted to fall back to the descriptor’s detection for that side.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L171)

``` python
class ScoreColorScale(BaseModel)
```

#### Attributes

`palette` Literal\['good-high', 'good-low', 'neutral', 'diverging'\]  
Named palette (same options as the string-shorthand form).

`min` float \| None  
Lower anchor for the gradient. None = descriptor’s auto-detected min.

`max` float \| None  
Upper anchor for the gradient. None = descriptor’s auto-detected max.

## Fields

### MetadataField

Identifies a field in metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L28)

``` python
class MetadataField(BaseModel)
```

#### Attributes

`key` str  
The `metadata[key]` entry to promote into its own section.

`label` str \| None  
Override the section header text. Defaults to `key` when unset.

`collapsed` bool  
Whether the field should be collapsed by default.

### ScannerResultField

A built-in scanner-result section (e.g. `value`, `explanation`).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/14ec8cfe2dd3ebbd437a9987d26de8a9cb681714/src/inspect_ai/viewer/_config.py#L6)

``` python
class ScannerResultField(BaseModel)
```

#### Attributes

`name` Literal\['explanation', 'label', 'value', 'validation', 'answer', 'metadata'\]  
Which built-in section to render.

`label` str \| None  
Override the section header text (e.g. `"Explanation" → "Rationale"`).

`collapsed` bool  
Whether the field should be collapsed by default.
