"""Field path utilities and lookup functions for taxonomy.

This module provides utilities for working with field paths and looking up
field classifications from the taxonomy.
"""

import re
from typing import Literal

from ._taxonomy import (
    DEFAULT_FIELD_CLASSIFICATION,
    DEFAULT_TAXONOMY,
    DYNAMIC_FIELD_PATTERNS,
    FieldClassification,
)


def normalize_field_path(path: str) -> str:
    """Normalize a field path for lookup.

    Converts various path formats to the canonical format used in the taxonomy:
    - Strips leading/trailing whitespace
    - Removes array indices (e.g., messages[0] -> messages[])
    - Normalizes list notation (e.g., messages.0 -> messages[])

    Args:
        path: The field path to normalize.

    Returns:
        The normalized field path.
    """
    path = path.strip()

    # Replace numeric indices with [] notation
    # e.g., messages[0] -> messages[], messages.0 -> messages[]
    path = re.sub(r"\[\d+\]", "[]", path)
    path = re.sub(r"\.(\d+)(?=\.|$)", "[]", path)

    return path


def get_field_classification(path: str) -> FieldClassification:
    """Get the classification for a field path.

    Looks up the classification in the following order:
    1. Exact match in DEFAULT_TAXONOMY
    2. Match against DYNAMIC_FIELD_PATTERNS (wildcard patterns)
    3. Falls back to DEFAULT_FIELD_CLASSIFICATION (high sensitivity)

    Args:
        path: The field path to look up (e.g., "EvalLog.status",
              "EvalSample.metadata.*", "EvalSample.messages[]").

    Returns:
        The FieldClassification for the specified path.

    Examples:
        >>> get_field_classification("EvalLog.status")
        FieldClassification(sensitivity=Sensitivity.LOW, ...)

        >>> get_field_classification("EvalSample.metadata.custom_key")
        FieldClassification(sensitivity=Sensitivity.HIGH, ...)
    """
    path = normalize_field_path(path)

    # First, try exact match in taxonomy
    if path in DEFAULT_TAXONOMY:
        return DEFAULT_TAXONOMY[path]

    # Try matching dynamic patterns
    for pattern, classification in DYNAMIC_FIELD_PATTERNS.items():
        if _matches_pattern(path, pattern):
            return classification

    # Fall back to default (conservative high sensitivity)
    return DEFAULT_FIELD_CLASSIFICATION


def _matches_pattern(path: str, pattern: str) -> bool:
    """Check if a path matches a wildcard pattern.

    Supports * which matches any single path component (anything except a dot).
    For example, "*.metadata.*" matches "EvalSample.metadata.key".

    Args:
        path: The field path to check.
        pattern: The pattern to match against.

    Returns:
        True if the path matches the pattern.
    """
    # Convert pattern to regex where * matches any single path component
    # e.g., "*.metadata.*" -> ^[^.]+\.metadata\.[^.]+$ which matches "EvalSample.metadata.key"
    regex_pattern = pattern.replace(".", r"\.")
    regex_pattern = regex_pattern.replace("*", "[^.]+")
    regex_pattern = f"^{regex_pattern}$"

    return bool(re.match(regex_pattern, path))


def get_all_field_paths() -> list[str]:
    """Get all explicitly defined field paths in the taxonomy.

    Returns:
        A sorted list of all field paths in DEFAULT_TAXONOMY.
    """
    return sorted(DEFAULT_TAXONOMY.keys())


LevelType = Literal["sensitivity", "informativeness"]
LevelValue = Literal["low", "medium", "high"]


def get_fields_by_level(
    level_type: LevelType,
    level_value: LevelValue,
) -> list[tuple[str, FieldClassification]]:
    """Get all fields with a specific sensitivity or informativeness level.

    Args:
        level_type: The type of level to filter by ("sensitivity" or "informativeness").
        level_value: The level value ("low", "medium", or "high").

    Returns:
        A list of (path, classification) tuples for fields matching
        the specified level.
    """
    return [
        (path, classification)
        for path, classification in DEFAULT_TAXONOMY.items()
        if getattr(classification, level_type).value == level_value
    ]


def get_fields_by_sensitivity(
    sensitivity: LevelValue,
) -> list[tuple[str, FieldClassification]]:
    """Get all fields with a specific sensitivity level."""
    return get_fields_by_level("sensitivity", sensitivity)


def get_fields_by_informativeness(
    informativeness: LevelValue,
) -> list[tuple[str, FieldClassification]]:
    """Get all fields with a specific informativeness level."""
    return get_fields_by_level("informativeness", informativeness)


ContentFlag = Literal["user_data", "model_output", "credentials"]


def get_fields_with_content(
    flag: ContentFlag,
) -> list[tuple[str, FieldClassification]]:
    """Get all fields that may contain a specific type of content.

    Args:
        flag: The content type to filter by:
            - "user_data": Fields that may contain user-provided data
            - "model_output": Fields that may contain model-generated content
            - "credentials": Fields that may contain API keys, tokens, etc.

    Returns:
        A list of (path, classification) tuples for fields matching
        the specified content flag.
    """
    attr_name = f"may_contain_{flag}"
    return [
        (path, classification)
        for path, classification in DEFAULT_TAXONOMY.items()
        if getattr(classification, attr_name)
    ]


def get_fields_with_user_data() -> list[tuple[str, FieldClassification]]:
    """Get all fields that may contain user data."""
    return get_fields_with_content("user_data")


def get_fields_with_model_output() -> list[tuple[str, FieldClassification]]:
    """Get all fields that may contain model output."""
    return get_fields_with_content("model_output")


def get_fields_with_credentials() -> list[tuple[str, FieldClassification]]:
    """Get all fields that may contain credentials."""
    return get_fields_with_content("credentials")
