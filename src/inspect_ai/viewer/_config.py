from typing import Literal

from pydantic import BaseModel, Field


class ScannerResultField(BaseModel):
    """A built-in scanner-result section (e.g. `value`, `explanation`)."""

    kind: Literal["builtin"] = "builtin"

    name: Literal[
        "explanation",
        "label",
        "value",
        "validation",
        "answer",
        "metadata",
    ]
    """Which built-in section to render."""

    label: str | None = None
    """Override the section header text (e.g. `"Explanation" → "Rationale"`)."""

    collapsed: bool = False
    """Whether the field should be collapsed by default."""


class MetadataField(BaseModel):
    """Identifies a field in metadata."""

    kind: Literal["metadata"] = "metadata"

    key: str
    """The `metadata[key]` entry to promote into its own section."""

    label: str | None = None
    """Override the section header text. Defaults to `key` when unset."""

    collapsed: bool = False
    """Whether the field should be collapsed by default."""


class ScannerResultView(BaseModel):
    """Customizes the rendering of the sample scanner results."""

    fields: list[ScannerResultField | MetadataField | str] | None = None
    """Ordered list of sections to render. The list order provides any preferred render order; fields that are not included in the list will be rendered in their natural order after the included fields are rendered. `None` means fall back to the built-in default order. """

    exclude_fields: list[ScannerResultField | MetadataField | str] = Field(
        default_factory=list
    )
    """Fields to suppress. For a `ScannerResultField` entry, the matching
    section is removed from the resolved `fields` list (useful to subtract
    from the default order). For a `MetadataField` entry, the key is
    additionally removed from the generic `metadata` section's display."""


class SampleScoreViewSort(BaseModel):
    """Default sort applied to the sample-header score panel."""

    column: Literal["name", "value"] | None = None
    """Column to sort by. `name` = scorer name; `value` = score value.
    `None` means no sort (display order)."""

    dir: Literal["asc", "desc"] = "asc"
    """Sort direction."""


class SampleScoreView(BaseModel):
    """How the sample-header score panel should render when there are 3 or more scores."""

    default: Literal["chips", "grid"] | None = None
    """Default rendering mode. `chips` = wrapping pills; `grid` = sortable
    table. When None, the viewer picks based on score count."""

    sort: SampleScoreViewSort | None = None
    """Default sort. When None, scores render in their natural order."""


TaskSamplesColumnId = Literal[
    "sampleStatus",
    "sampleId",
    "sampleUuid",
    "epoch",
    "input",
    "target",
    "answer",
    "tokens",
    "duration",
    "retries",
    "error",
    "limit",
]
"""Built-in column ids for the per-task Sample List grid.

Score columns are referenced via `TaskSamplesColumn.score()` /
`TaskSamplesSort.score()`. Plain strings remain valid for custom or
forward-compatible ids."""


def _score_column_id(scorer: str, score: str | None) -> str:
    return f"score__{scorer}__{score if score is not None else scorer}"


class TaskSamplesSort(BaseModel):
    """A single sort entry for the task's Sample List grid."""

    column: TaskSamplesColumnId | str
    """Column id. Use a built-in `TaskSamplesColumnId` or `TaskSamplesSort.score()`
    for score columns."""

    dir: Literal["asc", "desc"] = "asc"
    """Sort direction."""

    @classmethod
    def score(
        cls,
        scorer: str,
        score: str | None = None,
        *,
        dir: Literal["asc", "desc"] = "asc",
    ) -> "TaskSamplesSort":
        """Sort entry referencing a score column.

        Args:
            scorer: Scorer name (the key under `sample.scores`).
            score: Sub-score key, used only when a scorer emits a
                dictionary of named values. Defaults to `scorer`, which is
                correct for the common case of a scorer producing a single
                value. This is *not* a metric such as `accuracy` or
                `stderr` — those are aggregated across samples and do not
                appear as per-sample columns.
            dir: Sort direction.
        """
        return cls(column=_score_column_id(scorer, score), dir=dir)


class TaskSamplesColumn(BaseModel):
    """A column entry in the task's Sample List view."""

    id: TaskSamplesColumnId | str
    """Column id. Use a built-in `TaskSamplesColumnId` or
    `TaskSamplesColumn.score()` for score columns."""

    visible: bool = True
    """Whether the column is visible by default."""

    @classmethod
    def score(
        cls,
        scorer: str,
        score: str | None = None,
        *,
        visible: bool = True,
    ) -> "TaskSamplesColumn":
        """Column entry referencing a score column.

        Args:
            scorer: Scorer name (the key under `sample.scores`).
            score: Sub-score key, used only when a scorer emits a
                dictionary of named values. Defaults to `scorer`, which is
                correct for the common case of a scorer producing a single
                value. This is *not* a metric such as `accuracy` or
                `stderr` — those are aggregated across samples and do not
                appear as per-sample columns.
            visible: Whether the column is visible by default.
        """
        return cls(id=_score_column_id(scorer, score), visible=visible)


class ScoreColorScale(BaseModel):
    """A numeric `score_color_scales` entry with an explicit value range.

    By default the viewer anchors a named palette at the descriptor's
    auto-detected min/max, which is the *observed* range across the
    log's samples. When the score has a known *conceptual* range —
    e.g. an alignment-judge dimension that's always graded 1..10 —
    pin it via `min`/`max` so middling values don't get paint-clamped
    to the extremes when the observed data happens to cluster at one
    end. Either bound can be omitted to fall back to the descriptor's
    detection for that side.
    """

    palette: Literal["good-high", "good-low", "neutral", "diverging"]
    """Named palette (same options as the string-shorthand form)."""

    min: float | None = None
    """Lower anchor for the gradient. None = descriptor's auto-detected min."""

    max: float | None = None
    """Upper anchor for the gradient. None = descriptor's auto-detected max."""


class TaskSamplesView(BaseModel):
    """Default configuration for the task's Sample List grid.

    Configures the list of samples shown in a task's eval-log view.

    The viewer applies `TaskSamplesView` only when the user has not
    explicitly overridden the view in their browser. User overrides
    shadow the eval-author default; the resolution priority is
    `user > eval default > built-in`.
    """

    name: str
    """Display name. Surfaced in the future view switcher."""

    columns: list[TaskSamplesColumn] | None = None
    """Default Ordered list of columns. None = use the viewer's built-in defaults
    for this log's column shape."""

    sort: list[TaskSamplesSort] | None = None
    """Default Sort order. None = no eval-author default (viewer default applies)."""

    multiline: bool | None = None
    """Default row layout. True = list-style multi-line rows; False =
    compact single-line rows. None = viewer default (currently True)."""

    compact_scores: bool | None = None
    """Default presentation for score columns. True = compact narrow
    columns with rotated 45° headers; False = standard-width columns
    with horizontal headers. None = viewer default (currently False)."""

    score_labels: dict[str, str] | None = None
    """Display labels for score columns, keyed by score name.
    e.g. `{"audit_situational_awareness": "Situational Awareness"}`
    causes the viewer to render that header as "Situational Awareness"
    instead of the raw scorer name. Lookup falls back to the scorer
    name itself when no override is set."""

    score_color_scales: (
        dict[
            str,
            Literal["good-high", "good-low", "neutral", "diverging"]
            | ScoreColorScale
            | dict[str, Literal["good", "bad", "warn", "info", "muted"]],
        ]
        | None
    ) = None
    """Background-colour scales for score cells, keyed by score
    name. Each entry is one of:

    - a named palette string (numeric scores; gradient anchored at
      the descriptor's auto-detected min/max);
    - a `ScoreColorScale` with the same palette name plus optional
      `min`/`max` overrides (numeric scores with a known *conceptual*
      range that may not match the observed data range);
    - a map from value to semantic role (categorical scores).

    Numeric palettes:
    - `good-high`: low → red, high → green
    - `good-low`:  low → green, high → red
    - `neutral`:   transparent → blue (magnitude only, no good/bad signal)
    - `diverging`: red ↔ green centred on the midpoint of min / max

    Categorical roles (`good` / `bad` / `warn` / `info` / `muted`)
    resolve to appropriate colors for the category.

    Pass/fail and boolean scores ignore this config — their pre-coloured
    pills already encode the semantic. Scores not in the map render
    with no background."""

    color_scales_enabled: bool | None = None
    """Whether the score-cell color-scale heatmap is on by default."""


class ViewerConfig(BaseModel):
    """Top-level viewer configuration.

    This allows per task customization of the
    Task's sample list and each sample's score and scanner result display.
    """

    scanner_result_view: ScannerResultView | dict[str, ScannerResultView] = Field(
        default_factory=dict
    )
    """Glob-keyed map from scanner name pattern to its sidebar config. May also
    be a bare `ScannerResultView`."""

    sample_score_view: SampleScoreView | None = None
    """Defaults for the sample-header score panel. Honoured only when the
    user has not explicitly overridden the view or sort in their browser."""

    task_samples_view: TaskSamplesView | list[TaskSamplesView] | None = None
    """Default configuration for the task's Sample List grid (the list of
    samples shown in a task's eval-log view). When a list is supplied,
    the first entry is the default for now; multi-view selection UI may
    land later. Honoured only when the user has not explicitly
    overridden the view in their browser."""
