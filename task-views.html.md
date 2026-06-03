# Task Views – Inspect

> **NOTE:**
>
> The task views feature described below requires the development version of Inspect. You can install the development version from GitHub with:
>
> ``` bash
> pip install git+https://github.com/UKGovernmentBEIS/inspect_ai
> ```

## Overview

By default the log viewer chooses sensible defaults for how a task’s samples are listed, how their scores are summarized, and how scanner results are displayed. For your own task, however you have a better idea which scores matter, which columns are worth showing, and more. Your task can customize the view directly by using the `viewer` arg of the [Task](./reference/inspect_ai.html.md#task).

For example, the following customizes the Task’s view by passing a set of columns, a default sort, and enables multiline display (which may be better for long textual fields):

``` python
from inspect_ai import Task, task
from inspect_ai.scorer import match
from inspect_ai.viewer import (
    TaskSamplesColumn,
    TaskSamplesSort,
    TaskSamplesView,
    ViewerConfig,
)

@task
def popularity():
    return Task(
        name="popularity",
        dataset=dataset,
        scorer=match(location="any"),
        viewer=ViewerConfig(
            task_samples_view=TaskSamplesView(
                name="Default",
                columns=[
                    TaskSamplesColumn(id="sampleId"),
                    TaskSamplesColumn(id="input"),
                    TaskSamplesColumn(id="target"),
                    TaskSamplesColumn(id="answer"),
                    TaskSamplesColumn.score("match"),
                    TaskSamplesColumn(id="sampleStatus", visible=False),
                    TaskSamplesColumn(id="tokens", visible=False),
                    TaskSamplesColumn(id="duration", visible=False),
                ],
                sort=[
                    TaskSamplesSort.score("match", dir="asc"),
                    TaskSamplesSort(column="sampleId", dir="asc"),
                ],
                multiline=True,
            )
        ),
    )
```

The configuration that you specify in your task will be serialized into the eval log when it is written, so the configuration will be used for anyone viewing the log file produced using the configuration.

[ViewerConfig](./reference/inspect_ai.viewer.html.md#viewerconfig) covers three areas, each configured independently:

| Field | Configures |
|----|----|
| `task_samples_view` | The task’s sample list — the grid of samples shown for an eval log. |
| `sample_score_view` | The score panel in an individual sample’s score display. |
| `scanner_result_view` | The scanner results sidebar (for [scanners](./scanners.html.md)). |

> **NOTE: Note**
>
> These settings are defaults, not overrides. The viewer honors them only until a reviewer customizes the view in their own browser. The resolution priority is `user override > view configuration > viewer built-in`, so a user’s hand-picked columns or sort always win and are never clobbered by the eval default.

## The Sample List

`task_samples_view` configures the grid of samples shown for an eval log. A [TaskSamplesView](./reference/inspect_ai.viewer.html.md#tasksamplesview) requires a `name` and accepts optional column, sort, and presentation settings — any field left unset falls back to the viewer’s built-in behaviour.

``` python
from inspect_ai.viewer import (
    ViewerConfig,
    TaskSamplesView,
    TaskSamplesColumn,
    TaskSamplesSort,
)

ViewerConfig(
    task_samples_view=TaskSamplesView(
        name="Triage",
        columns=[
1            TaskSamplesColumn(id="sampleId"),
            TaskSamplesColumn(id="input"),
            TaskSamplesColumn.score("my_scorer"),
2            TaskSamplesColumn(id="target", visible=False),
        ],
3        sort=[TaskSamplesSort.score("my_scorer", dir="desc")],
4        multiline=True,
    )
)
```

1  
Controls the order of these columns.

2  
Hide these columns by default.

3  
Sort by `my_scorer`’s value, descending.

4  
Enable multiline display.

### Columns

You can control the order and visibility of columns within the task’s sample list by passing a list of [TaskSamplesColumn](./reference/inspect_ai.viewer.html.md#tasksamplescolumn) to `columns`. The order of the columns in this list is the default order for the columns in the sample view. Use `visible=False` on a column to hide it by default. Leaving `columns` as `None` uses the viewer’s built-in column set for that log’s shape.

All samples have the following built-in columns available:

`sampleStatus`, `sampleId`, `sampleUuid`, `epoch`, `input`, `target`, `answer`, `tokens`, `duration`, `retries`, `error`, `limit`.

### Score columns

Score columns are addressed by scorer name with the [score()](./reference/inspect_ai.scorer.html.md#score) helpers. For simple scorers, you can just pass the scorer name:

``` python
TaskSamplesColumn.score("my_scorer")
TaskSamplesSort.score("my_scorer", dir="desc")
```

Pass the score you’d like to target when a scorer emits a dictionary of named sub-scores:

``` python
TaskSamplesColumn.score("my_scorer", "calibration")
```

### Sort

`sort` is a list of [TaskSamplesSort](./reference/inspect_ai.viewer.html.md#tasksamplessort) entries (each a `column` id and a `dir` of `"asc"` or `"desc"`), applied in order. Use `TaskSamplesSort.score(...)` to sort on a score column.

### Score labels

`score_labels` renames score column headers for display, keyed by score name. Lookup falls back to the scorer name when no override is set.

``` python
TaskSamplesView(
    name="Audit",
    score_labels={
        "situational_awareness": "Situational Awareness",
        "ascii-art": "ASCII Art",
    },
)
```

### Color scales

Numeric score cells can be shaded with a background heat scale. `score_color_scales` is keyed by score name, and each entry is either a named palette, a [ScoreColorScale](./reference/inspect_ai.viewer.html.md#scorecolorscale) (a palette with an explicit value range), or — for categorical scores — a map from value to a semantic role.

[![](images/inspect-view-petri-custom-view.png)](images/inspect-view-petri-custom-view.png)

``` python
from inspect_ai.viewer import TaskSamplesView, ScoreColorScale

TaskSamplesView(
    name="Heat",
    score_color_scales={
        # named palette anchored to the observed data range
        "accuracy": "good-high",
        # palette pinned to a known 1..10 rubric so middling values
        # aren't paint-clamped when the data clusters at one end
        "concerning": ScoreColorScale(palette="good-low", min=1, max=10),
        # categorical score → semantic roles
        "verdict": {"yes": "bad", "no": "good", "maybe": "warn"},
    },
    color_scales_enabled=True,
)
```

**Numeric palettes** map a value’s position in the range to a colour along a gradient (low → high):

| Palette     | Low → High | Use when                              |
|-------------|------------|---------------------------------------|
| `good-high` |            | higher is better (e.g. accuracy)      |
| `good-low`  |            | lower is better (e.g. error rate)     |
| `neutral`   |            | magnitude only, no good/bad signal    |
| `diverging` |            | signed values centred on the midpoint |

**Categorical roles** assign a fixed colour to each mapped value:

| Role    | Colour | Conveys                                |
|---------|--------|----------------------------------------|
| `good`  |  green | a positive / desired outcome           |
| `bad`   |  red   | a negative / undesired outcome         |
| `warn`  |  amber | a borderline / needs-attention outcome |
| `info`  |  blue  | a neutral, informational value         |
| `muted` |  grey  | a low-salience value                   |

The swatches above approximate light mode; the actual cell colours are theme variables that adapt to light / dark. Pass/fail and boolean scores ignore this config — their pre-coloured pills already encode the result. `color_scales_enabled` seeds the toolbar heatmap toggle’s initial state.

### Row layout

`multiline` controls row density: `True` (the default) gives list-style multi-line rows; `False` gives compact single-line rows. `compact_scores` narrows score columns and rotates their headers 45° to fit many scores side by side.

## The Score Panel

`sample_score_view` configures the score panel shown in an individual sample’s detail view (distinct from the score *columns* in the sample list above). It applies when a sample has three or more scores.

[![‘Chips’ score panel](images/inspect-view-chips-score.png)](images/inspect-view-chips-score.png "‘Chips’ score panel")

‘Chips’ score panel

``` python
from inspect_ai.viewer import ViewerConfig, SampleScoreView, SampleScoreViewSort

ViewerConfig(
    sample_score_view=SampleScoreView(
        default="chips",
        sort=SampleScoreViewSort(column="value", dir="desc"),
    )
)
```

- `default` chooses the initial rendering mode: `chips` (wrapping pills) or `grid` (a sortable table). When unset, the viewer picks based on the number of scores.
- `sort` sets the initial sort by `name` (scorer name) or `value`, with a direction of `asc` or `desc`.

## Scanner Results

`scanner_result_view` customizes the scanner results sidebar for samples produced with [scanners](./scanners.html.md). It is a glob-keyed map from scanner-name pattern to a [ScannerResultView](./reference/inspect_ai.viewer.html.md#scannerresultview), so you can target specific scanners or apply one configuration to all of them:

``` python
from inspect_ai.viewer import (
    ViewerConfig,
    ScannerResultView,
    ScannerResultField,
    MetadataField,
)

ViewerConfig(
    scanner_result_view={
        "*": ScannerResultView(
            fields=[
                ScannerResultField(name="explanation", label="Rationale"),
                MetadataField(key="summary", label="Summary"),
                "value",
            ],
            exclude_fields=["validation"],
        ),
    }
)
```

Keys are fnmatch-style globs (`"*"`, `"audit_*"`, or exact scanner names). As a shorthand, you can pass a bare [ScannerResultView](./reference/inspect_ai.viewer.html.md#scannerresultview) instead of a map to apply a single configuration to every scanner.

`fields` is an ordered list of sections to render; entries are:

- A [ScannerResultField](./reference/inspect_ai.viewer.html.md#scannerresultfield) — a built-in section (`explanation`, `label`, `value`, `validation`, `answer`, or `metadata`), with an optional `label` override and `collapsed` default.
- A [MetadataField](./reference/inspect_ai.viewer.html.md#metadatafield) — promotes a single `metadata[key]` entry into its own top-level section.
- A bare string — shorthand for the matching [ScannerResultField](./reference/inspect_ai.viewer.html.md#scannerresultfield) name.

`exclude_fields` subtracts sections from the resolved set. Excluding a [MetadataField](./reference/inspect_ai.viewer.html.md#metadatafield) also removes that key from the generic `metadata` dump.

## Reference

See the [`inspect_ai.viewer`](./reference/inspect_ai.viewer.html.md) reference for the complete field list of every type described here.
