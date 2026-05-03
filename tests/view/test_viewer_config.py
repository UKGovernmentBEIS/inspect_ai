"""Tests for the `inspect_ai.viewer` Pydantic config classes."""

import pytest
from pydantic import ValidationError

from inspect_ai.viewer import (
    MetadataField,
    SampleScoreView,
    SampleScoreViewSort,
    ScannerResultField,
    ScannerResultView,
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


def test_score_panel_view_defaults() -> None:
    view = SampleScoreView()
    assert view.view is None
    assert view.sort is None


def test_score_panel_view_rejects_unknown_view() -> None:
    with pytest.raises(ValidationError):
        SampleScoreView(view="table")  # type: ignore[arg-type]


def test_viewer_config_score_panel_view_defaults_to_none() -> None:
    """Existing logs / unconfigured callers must keep working unchanged."""
    cfg = ViewerConfig()
    assert cfg.score_panel_view is None


def test_score_panel_view_roundtrip() -> None:
    cfg = ViewerConfig(
        score_panel_view=SampleScoreView(
            view="grid",
            sort=SampleScoreViewSort(column="value", dir="desc"),
        )
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
    assert restored.score_panel_view is not None
    assert restored.score_panel_view.view == "grid"
    assert restored.score_panel_view.sort is not None
    assert restored.score_panel_view.sort.column == "value"
    assert restored.score_panel_view.sort.dir == "desc"


def test_score_panel_view_partial_configs_roundtrip() -> None:
    """View only, sort only, and both — each should serialize cleanly."""
    view_only = ViewerConfig(score_panel_view=SampleScoreView(view="chips"))
    sort_only = ViewerConfig(
        score_panel_view=SampleScoreView(sort=SampleScoreViewSort(column="name"))
    )
    both = ViewerConfig(
        score_panel_view=SampleScoreView(
            view="grid", sort=SampleScoreViewSort(column="name", dir="asc")
        )
    )
    for cfg in (view_only, sort_only, both):
        assert ViewerConfig.model_validate_json(cfg.model_dump_json()) == cfg


def test_score_panel_view_coexists_with_scanner_result_view() -> None:
    """Both top-level fields can be set simultaneously without interaction."""
    cfg = ViewerConfig(
        scanner_result_view=ScannerResultView(fields=["value"]),
        score_panel_view=SampleScoreView(view="grid"),
    )
    restored = ViewerConfig.model_validate_json(cfg.model_dump_json())
    assert restored == cfg
