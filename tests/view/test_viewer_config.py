"""Tests for the `inspect_ai.viewer` Pydantic config classes."""

import pytest
from pydantic import ValidationError

from inspect_ai.viewer import (
    MetadataField,
    SampleScoreView,
    SampleScoreViewSort,
    ScannerResultField,
    ScannerResultView,
    ScoreColorScale,
    TaskSamplesColumn,
    TaskSamplesSort,
    TaskSamplesView,
    ViewerConfig,
)


def test_scanner_result_field_defaults() -> None:
    f = ScannerResultField(name="value")
    assert f.kind == "builtin"
    assert f.name == "value"
    assert f.label is None
    assert f.collapsed is False


def test_metadata_field_defaults() -> None:
    f = MetadataField(key="summary")
    assert f.kind == "metadata"
    assert f.key == "summary"
    assert f.label is None
    assert f.collapsed is False


def test_scanner_result_field_rejects_unknown_name() -> None:
    with pytest.raises(ValidationError):
        ScannerResultField(name="not_a_real_field")  # type: ignore[arg-type]


def test_scanner_result_view_defaults() -> None:
    view = ScannerResultView()
    assert view.fields is None
    assert view.exclude_fields == []


def test_viewer_config_defaults() -> None:
    cfg = ViewerConfig()
    assert cfg.scanner_result_view == {}


def test_roundtrip_preserves_all_fields() -> None:
    cfg = ViewerConfig(
        scanner_result_view={
            "*": ScannerResultView(
                fields=[
                    ScannerResultField(name="explanation", label="Rationale"),
                    MetadataField(key="summary", label="Summary", collapsed=True),
                    ScannerResultField(name="value"),
                    ScannerResultField(name="metadata"),
                ],
                exclude_fields=[
                    MetadataField(key="_internal_state"),
                    MetadataField(key="_debug"),
                    ScannerResultField(name="validation"),
                ],
            ),
            "audit_*": ScannerResultView(
                fields=[
                    ScannerResultField(name="value"),
                    ScannerResultField(name="explanation"),
                ],
            ),
        }
    )
    dumped = cfg.model_dump(exclude_none=True)
    restored = ViewerConfig.model_validate(dumped)
    assert restored == cfg


def test_roundtrip_via_json_preserves_all_fields() -> None:
    """JSON round-trip — what actually happens when persisted in an eval log."""
    cfg = ViewerConfig(
        scanner_result_view={
            "*": ScannerResultView(
                fields=[
                    ScannerResultField(name="explanation"),
                    MetadataField(key="summary"),
                ],
            ),
        }
    )
    json_blob = cfg.model_dump_json()
    restored = ViewerConfig.model_validate_json(json_blob)
    assert restored == cfg


def test_discriminated_union_parses_builtin() -> None:
    view = ScannerResultView.model_validate(
        {"fields": [{"kind": "builtin", "name": "value"}]}
    )
    assert view.fields is not None
    assert isinstance(view.fields[0], ScannerResultField)
    assert view.fields[0].name == "value"


def test_discriminated_union_parses_metadata() -> None:
    view = ScannerResultView.model_validate(
        {"fields": [{"kind": "metadata", "key": "summary"}]}
    )
    assert view.fields is not None
    assert isinstance(view.fields[0], MetadataField)
    assert view.fields[0].key == "summary"


def test_exclude_fields_accepts_both_model_variants() -> None:
    view = ScannerResultView(
        exclude_fields=[
            ScannerResultField(name="answer"),
            MetadataField(key="_internal_state"),
        ]
    )
    assert len(view.exclude_fields) == 2
    assert isinstance(view.exclude_fields[0], ScannerResultField)
    assert isinstance(view.exclude_fields[1], MetadataField)


def test_glob_patterns_stored_verbatim() -> None:
    """Glob patterns as scanner keys are accepted without any validation."""
    cfg = ViewerConfig(
        scanner_result_view={
            "*": ScannerResultView(),
            "audit_*": ScannerResultView(),
            "is_ascii": ScannerResultView(),
            "weird/*/path": ScannerResultView(),
        }
    )
    assert isinstance(cfg.scanner_result_view, dict)
    assert set(cfg.scanner_result_view.keys()) == {
        "*",
        "audit_*",
        "is_ascii",
        "weird/*/path",
    }


def test_fields_none_is_distinct_from_empty_list() -> None:
    """`None` means "use default fields"; `[]` means "hide everything"."""
    unconfigured = ScannerResultView()
    empty = ScannerResultView(fields=[])
    assert unconfigured.fields is None
    assert empty.fields == []
    assert unconfigured != empty


# ---------------------------------------------------------------------------
# Bare-string shorthand: stored as-is (no coercion). Readers resolve at use
# site via the shared resolver — the model deliberately preserves whatever the
# caller wrote so the serialized eval log matches the authored form.
# ---------------------------------------------------------------------------


def test_string_shorthand_is_preserved_in_fields() -> None:
    view = ScannerResultView(fields=["value", "metadata.summary"])
    assert view.fields == ["value", "metadata.summary"]


def test_string_shorthand_is_preserved_in_exclude_fields() -> None:
    view = ScannerResultView(exclude_fields=["answer", "metadata._internal_state"])
    assert view.exclude_fields == ["answer", "metadata._internal_state"]


def test_string_shorthand_mixed_with_models_preserved_in_order() -> None:
    view = ScannerResultView(
        fields=[
            "explanation",
            MetadataField(key="summary", label="Summary"),
            "value",
            "metadata.other_key",
        ]
    )
    assert view.fields is not None
    assert view.fields[0] == "explanation"
    assert isinstance(view.fields[1], MetadataField)
    assert view.fields[1].key == "summary"
    assert view.fields[2] == "value"
    assert view.fields[3] == "metadata.other_key"


def test_string_shorthand_roundtrips_as_strings() -> None:
    """Strings stay as strings through dump/load — no magical coercion."""
    view = ScannerResultView(fields=["value", "metadata.summary"])
    dumped = view.model_dump(exclude_none=True)
    assert dumped == {
        "fields": ["value", "metadata.summary"],
        "exclude_fields": [],
    }
    restored = ScannerResultView.model_validate(dumped)
    assert restored == view


# ---------------------------------------------------------------------------
# `scanner_result_view` accepts a bare `ScannerResultView` as a shorthand for
# `{"*": cfg}`. Stored form is whatever the caller wrote — the resolver
# treats the bare form as the `"*"` entry at render time.
# ---------------------------------------------------------------------------


def test_bare_scanner_result_view_is_stored_as_is() -> None:
    inner = ScannerResultView(fields=["value", "explanation"])
    cfg = ViewerConfig(scanner_result_view=inner)
    assert isinstance(cfg.scanner_result_view, ScannerResultView)
    assert cfg.scanner_result_view == inner


def test_bare_scanner_result_view_roundtrip() -> None:
    cfg = ViewerConfig(scanner_result_view=ScannerResultView(fields=["value"]))
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert isinstance(restored.scanner_result_view, ScannerResultView)
    assert restored == cfg


def test_dict_scanner_result_view_roundtrip() -> None:
    cfg = ViewerConfig(
        scanner_result_view={
            "audit_*": ScannerResultView(fields=["value"]),
            "is_ascii": ScannerResultView(fields=["explanation"]),
        }
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert isinstance(restored.scanner_result_view, dict)
    assert restored == cfg


# ---------------------------------------------------------------------------
# Score panel view defaults: eval-author hint that pre-seeds the
# chips/grid toggle and sort in the V2 sample-header score panel.
# ---------------------------------------------------------------------------


def test_score_panel_sort_defaults() -> None:
    sort = SampleScoreViewSort()
    assert sort.column is None
    assert sort.dir == "asc"


def test_score_panel_sort_rejects_unknown_column() -> None:
    with pytest.raises(ValidationError):
        SampleScoreViewSort(column="explanation")  # type: ignore[arg-type]


def test_score_panel_sort_rejects_unknown_dir() -> None:
    with pytest.raises(ValidationError):
        SampleScoreViewSort(dir="up")  # type: ignore[arg-type]


def test_sample_score_view_defaults() -> None:
    view = SampleScoreView()
    assert view.default is None
    assert view.sort is None


def test_sample_score_view_rejects_unknown_view() -> None:
    with pytest.raises(ValidationError):
        SampleScoreView(default="table")  # type: ignore[arg-type]


def test_viewer_config_sample_score_view_defaults_to_none() -> None:
    """Existing logs / unconfigured callers must keep working unchanged."""
    cfg = ViewerConfig()
    assert cfg.sample_score_view is None


def test_sample_score_view_roundtrip() -> None:
    cfg = ViewerConfig(
        sample_score_view=SampleScoreView(
            default="grid",
            sort=SampleScoreViewSort(column="value", dir="desc"),
        )
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    assert restored.sample_score_view is not None
    assert restored.sample_score_view.default == "grid"
    assert restored.sample_score_view.sort is not None
    assert restored.sample_score_view.sort.column == "value"
    assert restored.sample_score_view.sort.dir == "desc"


def test_sample_score_view_partial_configs_roundtrip() -> None:
    """View only, sort only, and both — each should serialize cleanly."""
    view_only = ViewerConfig(sample_score_view=SampleScoreView(default="chips"))
    sort_only = ViewerConfig(
        sample_score_view=SampleScoreView(sort=SampleScoreViewSort(column="name"))
    )
    both = ViewerConfig(
        sample_score_view=SampleScoreView(
            default="grid", sort=SampleScoreViewSort(column="name", dir="asc")
        )
    )
    for cfg in (view_only, sort_only, both):
        assert ViewerConfig.model_validate_json(cfg.model_dump_json()) == cfg


def test_sample_score_view_coexists_with_scanner_result_view() -> None:
    """Both top-level fields can be set simultaneously without interaction."""
    cfg = ViewerConfig(
        scanner_result_view=ScannerResultView(fields=["value"]),
        sample_score_view=SampleScoreView(default="grid"),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg


# ---------------------------------------------------------------------------
# Samples view: defaults the eval author can set for the task's
# Sample List grid (visible columns + order, sort, multiline).
# Distinct from `sample_score_view`, which configures the score panel
# inside an individual sample's detail view.
# ---------------------------------------------------------------------------


def test_samples_sort_defaults() -> None:
    s = TaskSamplesSort(column="tokens")
    assert s.column == "tokens"
    assert s.dir == "asc"


def test_samples_sort_rejects_unknown_dir() -> None:
    with pytest.raises(ValidationError):
        TaskSamplesSort(column="tokens", dir="up")  # type: ignore[arg-type]


def test_samples_column_defaults() -> None:
    c = TaskSamplesColumn(id="input")
    assert c.id == "input"
    assert c.visible is True


def test_samples_view_requires_name() -> None:
    with pytest.raises(ValidationError):
        TaskSamplesView()  # type: ignore[call-arg]


def test_samples_view_defaults() -> None:
    view = TaskSamplesView(name="Default")
    assert view.name == "Default"
    assert view.columns is None
    assert view.sort is None
    assert view.multiline is None
    assert view.compact_scores is None
    assert view.score_labels is None


def test_samples_view_rejects_non_bool_multiline() -> None:
    with pytest.raises(ValidationError):
        TaskSamplesView(name="Default", multiline="single")  # type: ignore[arg-type]


def test_samples_view_rejects_non_bool_compact_scores() -> None:
    with pytest.raises(ValidationError):
        TaskSamplesView(name="Default", compact_scores="narrow")  # type: ignore[arg-type]


def test_samples_view_compact_scores_roundtrip() -> None:
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(name="Compact", compact_scores=True),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    assert isinstance(restored.task_samples_view, TaskSamplesView)
    assert restored.task_samples_view.compact_scores is True


def test_samples_view_score_labels_roundtrip() -> None:
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Triage",
            score_labels={
                "audit_situational_awareness": "Situational Awareness",
                "ascii-art": "ASCII Art",
            },
        ),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    assert isinstance(restored.task_samples_view, TaskSamplesView)
    assert restored.task_samples_view.score_labels == {
        "audit_situational_awareness": "Situational Awareness",
        "ascii-art": "ASCII Art",
    }


def test_samples_view_score_labels_rejects_non_string_value() -> None:
    """Labels are display strings — non-string values should be rejected at parse."""
    with pytest.raises(ValidationError):
        TaskSamplesView(
            name="Default",
            score_labels={"x": 1},  # type: ignore[dict-item]
        )


def test_samples_view_score_color_scales_named_palette_roundtrip() -> None:
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Heat",
            score_color_scales={
                "accuracy": "good-high",
                "harm_score": "good-low",
                "alpha_count": "neutral",
                "delta": "diverging",
            },
        ),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    assert isinstance(restored.task_samples_view, TaskSamplesView)
    assert restored.task_samples_view.score_color_scales == {
        "accuracy": "good-high",
        "harm_score": "good-low",
        "alpha_count": "neutral",
        "delta": "diverging",
    }


def test_samples_view_score_color_scales_categorical_roundtrip() -> None:
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Heat",
            score_color_scales={
                "verdict": {"yes": "bad", "no": "good", "maybe": "warn"},
            },
        ),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg


def test_samples_view_score_color_scales_mixed_roundtrip() -> None:
    """A single config can mix numeric palettes and categorical maps."""
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Heat",
            score_color_scales={
                "accuracy": "good-high",
                "verdict": {"yes": "bad", "no": "good"},
            },
        ),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg


def test_samples_view_score_color_scales_rejects_unknown_palette() -> None:
    with pytest.raises(ValidationError):
        TaskSamplesView(
            name="Default",
            score_color_scales={"accuracy": "rainbow"},  # type: ignore[dict-item]
        )


def test_samples_view_score_color_scales_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        TaskSamplesView(
            name="Default",
            score_color_scales={
                "verdict": {"yes": "amazing"},  # type: ignore[dict-item]
            },
        )


def test_samples_view_score_color_scales_object_form_roundtrip() -> None:
    """`ScoreColorScale` lets authors pin the conceptual range.

    E.g. a 1..10 rubric — so middling values aren't paint-clamped to
    the extremes when the observed data happens to cluster at one end.
    """
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Heat",
            score_color_scales={
                "concerning": ScoreColorScale(palette="good-low", min=1, max=10),
                "admirable": "good-high",  # string shorthand still works
            },
        ),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    view = restored.task_samples_view
    assert isinstance(view, TaskSamplesView)
    assert view.score_color_scales is not None
    pinned = view.score_color_scales["concerning"]
    assert isinstance(pinned, ScoreColorScale)
    assert pinned.palette == "good-low"
    assert pinned.min == 1
    assert pinned.max == 10
    assert view.score_color_scales["admirable"] == "good-high"


def test_score_color_scale_partial_bounds() -> None:
    """Either bound can be omitted on `ScoreColorScale`.

    The resolver falls back to the descriptor's auto-detection for
    the missing side.
    """
    only_min = ScoreColorScale(palette="good-high", min=0)
    only_max = ScoreColorScale(palette="good-low", max=10)
    assert only_min.max is None
    assert only_max.min is None
    # Both round-trip cleanly.
    for s in (only_min, only_max):
        assert ScoreColorScale.model_validate_json(s.model_dump_json()) == s


def test_score_color_scale_rejects_unknown_palette() -> None:
    with pytest.raises(ValidationError):
        ScoreColorScale(palette="rainbow", min=1, max=10)  # type: ignore[arg-type]


def test_samples_view_color_scales_enabled_roundtrip() -> None:
    """Eval authors can seed the colour-scale toolbar toggle's initial value."""
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Heat",
            score_color_scales={"accuracy": "good-high"},
            color_scales_enabled=False,
        ),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    view = restored.task_samples_view
    assert isinstance(view, TaskSamplesView)
    assert view.color_scales_enabled is False


def test_samples_view_color_scales_enabled_defaults_to_none() -> None:
    """Like the other view defaults: None means "viewer default applies"."""
    view = TaskSamplesView(name="Default")
    assert view.color_scales_enabled is None


def test_samples_view_roundtrip_with_columns_and_sort() -> None:
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Triage",
            columns=[
                TaskSamplesColumn(id="status"),
                TaskSamplesColumn(id="input"),
                TaskSamplesColumn(id="target", visible=False),
                TaskSamplesColumn(id="tokens"),
            ],
            sort=[TaskSamplesSort(column="tokens", dir="desc")],
            multiline=False,
        )
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    assert isinstance(restored.task_samples_view, TaskSamplesView)
    assert restored.task_samples_view.multiline is False


def test_samples_view_accepts_list() -> None:
    cfg = ViewerConfig(
        task_samples_view=[
            TaskSamplesView(name="All"),
            TaskSamplesView(name="Errors"),
        ]
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    assert isinstance(restored.task_samples_view, list)
    assert len(restored.task_samples_view) == 2
    assert restored.task_samples_view[1].name == "Errors"


def test_viewer_config_task_samples_view_defaults_to_none() -> None:
    """Existing logs / unconfigured callers must keep working unchanged."""
    cfg = ViewerConfig()
    assert cfg.task_samples_view is None


def test_samples_view_coexists_with_other_top_level_fields() -> None:
    cfg = ViewerConfig(
        scanner_result_view=ScannerResultView(fields=["value"]),
        sample_score_view=SampleScoreView(default="grid"),
        task_samples_view=TaskSamplesView(name="Default"),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg


# ---------------------------------------------------------------------------
# `.score()` classmethods build the `score__{scorer}__{name}` wire id so
# authors don't hand-assemble the string.
# ---------------------------------------------------------------------------


def test_task_samples_column_score_builds_wire_id() -> None:
    col = TaskSamplesColumn.score("judge", "correctness")
    assert col.id == "score__judge__correctness"
    assert col.visible is True
    assert (
        TaskSamplesColumn.score("judge", "correctness", visible=False).visible is False
    )


def test_task_samples_sort_score_builds_wire_id() -> None:
    s = TaskSamplesSort.score("judge", "correctness", dir="desc")
    assert s.column == "score__judge__correctness"
    assert s.dir == "desc"


def test_task_samples_column_score_roundtrips() -> None:
    cfg = ViewerConfig(
        task_samples_view=TaskSamplesView(
            name="Scores",
            columns=[TaskSamplesColumn.score("judge", "correctness")],
            sort=[TaskSamplesSort.score("judge", "correctness", dir="desc")],
        )
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg


# ---------------------------------------------------------------------------
# Renamed public names keep resolving (via a logged deprecation) until 0.4.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "old_name, new_obj",
    [
        ("SamplesView", TaskSamplesView),
        ("SamplesColumn", TaskSamplesColumn),
        ("SamplesSort", TaskSamplesSort),
    ],
)
def test_renamed_names_resolve_to_new_class(old_name, new_obj) -> None:
    import inspect_ai.viewer as viewer

    assert getattr(viewer, old_name) is new_obj


def test_removed_name_still_raises_attribute_error() -> None:
    import inspect_ai.viewer as viewer

    missing = "NotAViewerType"
    with pytest.raises(AttributeError):
        getattr(viewer, missing)
