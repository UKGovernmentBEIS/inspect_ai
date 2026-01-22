"""Taxonomy definitions for EvalLog field classification.

This module defines the sensitivity and informativeness levels for classifying
EvalLog fields, enabling secure log publication by clearly identifying which
fields contain sensitive data and which are critical for analysis.

The taxonomy data is loaded from _taxonomy.yml, which can be customized
or extended by users for their specific needs.
"""

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError


class Sensitivity(str, Enum):
    """Sensitivity level for a field.

    Indicates how sensitive the data in a field is from a privacy/security
    perspective.
    """

    LOW = "low"
    """Non-sensitive data (versions, IDs, timestamps, configuration options)."""

    MEDIUM = "medium"
    """Potentially identifying data (file paths, hostnames, project structure)."""

    HIGH = "high"
    """Sensitive data (credentials, user inputs, model outputs, personal data)."""


class Informativeness(str, Enum):
    """Informativeness level for a field.

    Indicates how valuable a field is for understanding and analyzing
    evaluation results.
    """

    LOW = "low"
    """Limited analytical value (internal IDs, format versions)."""

    MEDIUM = "medium"
    """Useful for some analyses (configuration, timing, resource usage)."""

    HIGH = "high"
    """Critical for understanding results (scores, model outputs, errors)."""


class FieldClassification(BaseModel, frozen=True):
    """Classification of a field's sensitivity and informativeness.

    Used to categorize EvalLog fields to support decisions about which fields
    to include when publishing or sharing evaluation logs.
    """

    sensitivity: Sensitivity
    """How sensitive the data in this field is."""

    informativeness: Informativeness
    """How useful this field is for analysis."""

    rationale: str = ""
    """Explanation for why this classification was assigned."""

    may_contain_user_data: bool = False
    """Whether this field may contain user-provided data."""

    may_contain_model_output: bool = False
    """Whether this field may contain model-generated content."""

    may_contain_credentials: bool = False
    """Whether this field may contain API keys, tokens, or other credentials."""


class SanitizationTaxonomy(BaseModel, frozen=True):
    """A complete field classification taxonomy for log sanitization.

    Contains all field classifications, dynamic patterns, and the default
    classification for unknown fields.
    """

    fields: dict[str, FieldClassification]
    """Field path to classification mappings."""

    patterns: dict[str, FieldClassification]
    """Wildcard patterns for dynamic fields (e.g., *.metadata.*)."""

    default: FieldClassification
    """Default classification for unknown fields."""


def _parse_classification(data: dict[str, Any]) -> FieldClassification:
    """Parse a field classification from YAML data.

    Args:
        data: Dictionary with sensitivity, informativeness, and optional flags.

    Returns:
        FieldClassification instance.

    Raises:
        ValidationError: If the data doesn't match the expected schema.
    """
    return FieldClassification(
        sensitivity=Sensitivity(data["sensitivity"]),
        informativeness=Informativeness(data["informativeness"]),
        rationale=data.get("rationale", ""),
        may_contain_user_data=data.get("may_contain_user_data", False),
        may_contain_model_output=data.get("may_contain_model_output", False),
        may_contain_credentials=data.get("may_contain_credentials", False),
    )


def _create_user_taxonomy(file_path: Path) -> SanitizationTaxonomy:
    """Create a sanitization taxonomy with the user's fields. This will then be merged into the default taxonomy to create a new taxonomy incorporating user overrides.

    Args:
        file_path: Path to the YAML file containing taxonomy definitions.

    Returns:
        A SanitizationTaxonomy containing only what's defined in the file.

    Raises:
        yaml.YAMLError: If the YAML file is malformed.
        ValidationError: If the data doesn't match the expected schema.
        KeyError: If required fields are missing.
    """
    with open(file_path) as f:
        data = yaml.safe_load(f)

    if not data:
        return SanitizationTaxonomy(
            fields={},
            patterns={},
            default=FieldClassification(
                sensitivity=Sensitivity.HIGH,
                informativeness=Informativeness.LOW,
                rationale="Unknown field - defaulting to high sensitivity for safety",
            ),
        )

    # Parse field classifications
    fields: dict[str, FieldClassification] = {}
    if "fields" in data:
        for field_path, field_data in data["fields"].items():
            try:
                fields[field_path] = _parse_classification(field_data)
            except (KeyError, ValueError, ValidationError) as e:
                raise type(e)(
                    f"Error parsing field '{field_path}' in {file_path}: {e}"
                ) from e

    # Parse pattern classifications
    patterns: dict[str, FieldClassification] = {}
    if "patterns" in data:
        for pattern, pattern_data in data["patterns"].items():
            try:
                patterns[pattern] = _parse_classification(pattern_data)
            except (KeyError, ValueError, ValidationError) as e:
                raise type(e)(
                    f"Error parsing pattern '{pattern}' in {file_path}: {e}"
                ) from e

    # Parse default classification
    if "default" in data:
        try:
            default = _parse_classification(data["default"])
        except (KeyError, ValueError, ValidationError) as e:
            raise type(e)(
                f"Error parsing default classification in {file_path}: {e}"
            ) from e
    else:
        default = FieldClassification(
            sensitivity=Sensitivity.HIGH,
            informativeness=Informativeness.LOW,
            rationale="Unknown field - defaulting to high sensitivity for safety",
        )

    return SanitizationTaxonomy(fields=fields, patterns=patterns, default=default)


_DEFAULT_TAXONOMY_PATH = Path(__file__).parent / "_taxonomy.yml"

# Load the default taxonomy at module import time
_default_taxonomy = _create_user_taxonomy(_DEFAULT_TAXONOMY_PATH)

DEFAULT_TAXONOMY: dict[str, FieldClassification] = _default_taxonomy.fields
"""Comprehensive field classifications for EvalLog fields.

Field paths use type-qualified dot notation:
- EvalLog.field - direct field on EvalLog
- EvalSpec.field - field on nested EvalSpec type
- EvalSample.messages[] - list elements
"""

DYNAMIC_FIELD_PATTERNS: dict[str, FieldClassification] = _default_taxonomy.patterns
"""Wildcard patterns for dynamic fields (metadata, store, args dicts).

These patterns match fields that can have arbitrary keys.
"""

DEFAULT_FIELD_CLASSIFICATION: FieldClassification = _default_taxonomy.default
"""Default classification for unknown fields - conservative defaults."""


def load_sanitization_taxonomy(path: Path | None = None) -> SanitizationTaxonomy:
    """Load a sanitization taxonomy.

    Args:
        path: Path to a YAML file with taxonomy overrides. If None, returns
            the default taxonomy.

    Returns:
        A SanitizationTaxonomy. If path is provided, user overrides are merged
        with the defaults; otherwise returns the default taxonomy.

    Raises:
        FileNotFoundError: If the provided path does not exist.
    """
    if path is None:
        return _default_taxonomy

    if not path.exists():
        raise FileNotFoundError(f"Taxonomy file not found: {path}")

    user_taxonomy = _create_user_taxonomy(path)

    # Merge: user overrides take precedence
    merged_fields = {**_default_taxonomy.fields, **user_taxonomy.fields}
    merged_patterns = {**_default_taxonomy.patterns, **user_taxonomy.patterns}

    return SanitizationTaxonomy(
        fields=merged_fields,
        patterns=merged_patterns,
        default=_default_taxonomy.default,
    )
