"""Tests for the log sanitization taxonomy."""

import pytest
from pydantic import BaseModel

from inspect_ai.log._sanitize import (
    DEFAULT_FIELD_CLASSIFICATION,
    DEFAULT_TAXONOMY,
    DYNAMIC_FIELD_PATTERNS,
    FieldClassification,
    Informativeness,
    Sensitivity,
    get_all_field_paths,
    get_field_classification,
    get_fields_by_informativeness,
    get_fields_by_sensitivity,
    get_fields_with_credentials,
    get_fields_with_model_output,
    get_fields_with_user_data,
    normalize_field_path,
)


class TestSensitivityEnum:
    """Tests for the Sensitivity enum."""

    def test_sensitivity_values(self) -> None:
        """Test that all expected sensitivity values exist."""
        assert Sensitivity.LOW.value == "low"
        assert Sensitivity.MEDIUM.value == "medium"
        assert Sensitivity.HIGH.value == "high"

    def test_sensitivity_is_string_enum(self) -> None:
        """Test that Sensitivity is a string enum."""
        assert isinstance(Sensitivity.LOW, str)
        assert Sensitivity.LOW.value == "low"


class TestInformativenessEnum:
    """Tests for the Informativeness enum."""

    def test_informativeness_values(self) -> None:
        """Test that all expected informativeness values exist."""
        assert Informativeness.LOW.value == "low"
        assert Informativeness.MEDIUM.value == "medium"
        assert Informativeness.HIGH.value == "high"

    def test_informativeness_is_string_enum(self) -> None:
        """Test that Informativeness is a string enum."""
        assert isinstance(Informativeness.LOW, str)
        assert Informativeness.LOW.value == "low"


class TestFieldClassification:
    """Tests for the FieldClassification model."""

    def test_field_classification_creation(self) -> None:
        """Test creating a FieldClassification."""
        classification = FieldClassification(
            sensitivity=Sensitivity.HIGH,
            informativeness=Informativeness.LOW,
            rationale="Test rationale",
        )
        assert classification.sensitivity == Sensitivity.HIGH
        assert classification.informativeness == Informativeness.LOW
        assert classification.rationale == "Test rationale"

    def test_field_classification_defaults(self) -> None:
        """Test default values for FieldClassification."""
        classification = FieldClassification(
            sensitivity=Sensitivity.LOW,
            informativeness=Informativeness.LOW,
        )
        assert classification.rationale == ""
        assert classification.may_contain_user_data is False
        assert classification.may_contain_model_output is False
        assert classification.may_contain_credentials is False

    def test_field_classification_is_frozen(self) -> None:
        """Test that FieldClassification is frozen (immutable)."""
        classification = FieldClassification(
            sensitivity=Sensitivity.LOW,
            informativeness=Informativeness.LOW,
        )
        with pytest.raises(Exception):  # Pydantic raises ValidationError
            classification.sensitivity = Sensitivity.HIGH  # type: ignore

    def test_field_classification_is_hashable(self) -> None:
        """Test that FieldClassification is hashable (can be used in sets/dicts)."""
        classification = FieldClassification(
            sensitivity=Sensitivity.LOW,
            informativeness=Informativeness.LOW,
        )
        # Should not raise
        hash(classification)
        assert classification in {classification}

    def test_field_classification_is_pydantic_model(self) -> None:
        """Test that FieldClassification is a Pydantic model."""
        assert issubclass(FieldClassification, BaseModel)


class TestDefaultTaxonomy:
    """Tests for the DEFAULT_TAXONOMY."""

    def test_taxonomy_is_not_empty(self) -> None:
        """Test that the taxonomy has entries."""
        assert len(DEFAULT_TAXONOMY) > 0

    def test_all_taxonomy_values_are_field_classifications(self) -> None:
        """Test that all taxonomy values are FieldClassification instances."""
        for path, classification in DEFAULT_TAXONOMY.items():
            assert isinstance(classification, FieldClassification), (
                f"Value for {path} is not a FieldClassification"
            )

    def test_all_taxonomy_keys_are_valid_paths(self) -> None:
        """Test that all taxonomy keys follow the expected format."""
        for path in DEFAULT_TAXONOMY.keys():
            # Path should be TypeName.field or TypeName.field.subfield
            assert "." in path, f"Path {path} does not contain a dot"
            parts = path.split(".")
            # First part should be a type name (PascalCase)
            assert parts[0][0].isupper(), f"Path {path} does not start with a type name"

    def test_key_fields_are_classified(self) -> None:
        """Test that important EvalLog fields are classified."""
        key_fields = [
            "EvalLog.version",
            "EvalLog.status",
            "EvalLog.eval",
            "EvalLog.samples",
            "EvalLog.results",
            "EvalSpec.model",
            "EvalSpec.task",
            "EvalSample.input",
            "EvalSample.output",
            "EvalSample.messages",
            "EvalSample.scores",
        ]
        for field in key_fields:
            assert field in DEFAULT_TAXONOMY, f"Key field {field} not in taxonomy"

    def test_eval_sample_input_is_high_sensitivity(self) -> None:
        """Test that sample input is classified as high sensitivity."""
        classification = DEFAULT_TAXONOMY["EvalSample.input"]
        assert classification.sensitivity == Sensitivity.HIGH
        assert classification.may_contain_user_data is True

    def test_eval_sample_scores_is_low_sensitivity(self) -> None:
        """Test that sample scores are low sensitivity."""
        classification = DEFAULT_TAXONOMY["EvalSample.scores"]
        assert classification.sensitivity == Sensitivity.LOW
        assert classification.informativeness == Informativeness.HIGH

    def test_metadata_fields_are_high_sensitivity(self) -> None:
        """Test that metadata fields are high sensitivity."""
        metadata_fields = [
            "EvalSpec.metadata",
            "EvalSample.metadata",
            "EvalResults.metadata",
        ]
        for field in metadata_fields:
            classification = DEFAULT_TAXONOMY[field]
            assert classification.sensitivity == Sensitivity.HIGH, (
                f"{field} should be high sensitivity"
            )


class TestDynamicFieldPatterns:
    """Tests for DYNAMIC_FIELD_PATTERNS."""

    def test_patterns_exist(self) -> None:
        """Test that dynamic patterns are defined."""
        assert len(DYNAMIC_FIELD_PATTERNS) > 0

    def test_metadata_pattern_exists(self) -> None:
        """Test that metadata wildcard pattern exists."""
        assert "*.metadata.*" in DYNAMIC_FIELD_PATTERNS

    def test_store_pattern_exists(self) -> None:
        """Test that store wildcard pattern exists."""
        assert "*.store.*" in DYNAMIC_FIELD_PATTERNS

    def test_patterns_are_high_or_medium_sensitivity(self) -> None:
        """Test that dynamic patterns default to at least medium sensitivity."""
        for pattern, classification in DYNAMIC_FIELD_PATTERNS.items():
            assert classification.sensitivity in [
                Sensitivity.MEDIUM,
                Sensitivity.HIGH,
            ], f"Pattern {pattern} should be at least medium sensitivity"


class TestNormalizeFieldPath:
    """Tests for the normalize_field_path function."""

    def test_strips_whitespace(self) -> None:
        """Test that whitespace is stripped."""
        assert normalize_field_path("  EvalLog.status  ") == "EvalLog.status"

    def test_normalizes_array_indices(self) -> None:
        """Test that array indices are normalized."""
        assert normalize_field_path("EvalSample.messages[0]") == "EvalSample.messages[]"
        assert (
            normalize_field_path("EvalSample.messages[123]") == "EvalSample.messages[]"
        )

    def test_normalizes_dotted_indices(self) -> None:
        """Test that dotted array indices are normalized."""
        assert normalize_field_path("EvalSample.messages.0") == "EvalSample.messages[]"
        assert (
            normalize_field_path("EvalSample.messages.0.content")
            == "EvalSample.messages[].content"
        )

    def test_preserves_non_indexed_paths(self) -> None:
        """Test that paths without indices are preserved."""
        assert normalize_field_path("EvalLog.status") == "EvalLog.status"
        assert normalize_field_path("EvalSpec.model") == "EvalSpec.model"


class TestGetFieldClassification:
    """Tests for the get_field_classification function."""

    def test_exact_match(self) -> None:
        """Test exact match in taxonomy."""
        classification = get_field_classification("EvalLog.status")
        assert classification.sensitivity == Sensitivity.LOW
        assert classification.informativeness == Informativeness.HIGH

    def test_normalized_path(self) -> None:
        """Test that paths are normalized before lookup."""
        classification = get_field_classification("  EvalLog.status  ")
        assert classification == DEFAULT_TAXONOMY["EvalLog.status"]

    def test_unknown_field_returns_default(self) -> None:
        """Test that unknown fields return the default classification."""
        classification = get_field_classification("UnknownType.unknown_field")
        assert classification == DEFAULT_FIELD_CLASSIFICATION
        assert classification.sensitivity == Sensitivity.HIGH

    def test_dynamic_metadata_match(self) -> None:
        """Test matching dynamic metadata fields."""
        classification = get_field_classification("EvalSample.metadata.custom_key")
        # Should match the metadata pattern and be high sensitivity
        assert classification.sensitivity == Sensitivity.HIGH

    def test_dynamic_store_match(self) -> None:
        """Test matching dynamic store fields."""
        classification = get_field_classification("EvalSample.store.some_state")
        assert classification.sensitivity == Sensitivity.HIGH

    def test_array_field(self) -> None:
        """Test classification of array fields."""
        classification = get_field_classification("EvalSample.messages[]")
        assert classification.sensitivity == Sensitivity.HIGH


class TestGetAllFieldPaths:
    """Tests for get_all_field_paths function."""

    def test_list_is_sorted(self) -> None:
        """Test that the list is sorted."""
        paths = get_all_field_paths()
        assert isinstance(paths, list)
        assert paths == sorted(paths)

    def test_contains_key_paths(self) -> None:
        """Test that key paths are included."""
        paths = get_all_field_paths()
        assert "EvalLog.status" in paths
        assert "EvalSample.input" in paths


class TestGetFieldsBySensitivity:
    """Tests for get_fields_by_sensitivity function."""

    def test_all_sensitivities_covered(self) -> None:
        """Test that all sensitivity levels have some fields."""
        for level in [Sensitivity.LOW, Sensitivity.MEDIUM, Sensitivity.HIGH]:
            fields = get_fields_by_sensitivity(level.value)
            assert len(fields) > 0, f"No fields with {level} sensitivity"


class TestGetFieldsByInformativeness:
    """Tests for get_fields_by_informativeness function."""

    def test_all_informativeness_levels_covered(self) -> None:
        """Test that all informativeness levels have some fields."""
        for level in [
            Informativeness.LOW,
            Informativeness.MEDIUM,
            Informativeness.HIGH,
        ]:
            fields = get_fields_by_informativeness(level.value)
            assert len(fields) > 0, f"No fields with {level} informativeness"


class TestGetFieldsWithFlags:
    """Tests for get_fields_with_* functions."""

    def test_get_fields_with_user_data(self) -> None:
        """Test getting fields that contain user data."""
        fields = get_fields_with_user_data()
        assert len(fields) > 0
        for path, classification in fields:
            assert classification.may_contain_user_data is True
        # Sample input should be in this list
        paths = [path for path, _ in fields]
        assert "EvalSample.input" in paths

    def test_get_fields_with_model_output(self) -> None:
        """Test getting fields that contain model output."""
        fields = get_fields_with_model_output()
        assert len(fields) > 0
        for path, classification in fields:
            assert classification.may_contain_model_output is True
        # Sample output should be in this list
        paths = [path for path, _ in fields]
        assert "EvalSample.output" in paths

    def test_get_fields_with_credentials(self) -> None:
        """Test getting fields that may contain credentials."""
        fields = get_fields_with_credentials()
        assert len(fields) > 0
        for path, classification in fields:
            assert classification.may_contain_credentials is True
        # Sample output should be in this list
        paths = [path for path, _ in fields]
        assert "EvalLog.error" in paths


class TestTaxonomyCompleteness:
    """Tests for taxonomy completeness against EvalLog structure."""

    def test_eval_log_top_level_fields(self) -> None:
        """Test that all top-level EvalLog fields are classified."""
        # These are the fields defined in EvalLog
        eval_log_fields = [
            "version",
            "status",
            "eval",
            "plan",
            "results",
            "stats",
            "error",
            "invalidated",
            "samples",
            "reductions",
        ]
        for field in eval_log_fields:
            path = f"EvalLog.{field}"
            assert path in DEFAULT_TAXONOMY, f"EvalLog.{field} not in taxonomy"

    def test_eval_spec_fields(self) -> None:
        """Test that key EvalSpec fields are classified."""
        eval_spec_fields = [
            "eval_set_id",
            "eval_id",
            "run_id",
            "created",
            "task",
            "task_id",
            "task_version",
            "task_file",
            "model",
            "model_args",
            "config",
            "revision",
            "packages",
            "metadata",
        ]
        for field in eval_spec_fields:
            path = f"EvalSpec.{field}"
            assert path in DEFAULT_TAXONOMY, f"EvalSpec.{field} not in taxonomy"

    def test_eval_sample_fields(self) -> None:
        """Test that key EvalSample fields are classified."""
        eval_sample_fields = [
            "id",
            "epoch",
            "input",
            "target",
            "messages",
            "output",
            "scores",
            "metadata",
            "store",
            "events",
            "error",
        ]
        for field in eval_sample_fields:
            path = f"EvalSample.{field}"
            assert path in DEFAULT_TAXONOMY, f"EvalSample.{field} not in taxonomy"

    def test_event_fields(self) -> None:
        """Test that key event fields are classified."""
        # ModelEvent fields
        assert "ModelEvent.input" in DEFAULT_TAXONOMY
        assert "ModelEvent.output" in DEFAULT_TAXONOMY
        # ToolEvent fields
        assert "ToolEvent.arguments" in DEFAULT_TAXONOMY
        assert "ToolEvent.result" in DEFAULT_TAXONOMY
        # SandboxEvent fields
        assert "SandboxEvent.cmd" in DEFAULT_TAXONOMY
        assert "SandboxEvent.output" in DEFAULT_TAXONOMY


class TestTaxonomyConsistency:
    """Tests for taxonomy consistency and correctness."""

    def test_user_data_fields_are_high_or_medium_sensitivity(self) -> None:
        """Test that fields with user data are appropriately sensitive."""
        for path, classification in DEFAULT_TAXONOMY.items():
            if classification.may_contain_user_data:
                assert classification.sensitivity in [
                    Sensitivity.MEDIUM,
                    Sensitivity.HIGH,
                ], f"Field {path} contains user data but has low sensitivity"

    def test_model_output_fields_are_high_or_medium_sensitivity(self) -> None:
        """Test that fields with model output are at least medium sensitivity."""
        for path, classification in DEFAULT_TAXONOMY.items():
            if classification.may_contain_model_output:
                assert classification.sensitivity in [
                    Sensitivity.MEDIUM,
                    Sensitivity.HIGH,
                ], f"Field {path} contains model output but has low sensitivity"

    def test_critical_result_fields_are_high_informativeness(self) -> None:
        """Test that critical analysis fields are high informativeness."""
        critical_fields = [
            "EvalLog.status",
            "EvalSpec.model",
            "EvalSpec.task",
            "EvalSample.scores",
            "EvalResults.total_samples",
            "EvalResults.completed_samples",
        ]
        for path in critical_fields:
            classification = DEFAULT_TAXONOMY[path]
            assert classification.informativeness == Informativeness.HIGH, (
                f"Critical field {path} should be high informativeness"
            )
