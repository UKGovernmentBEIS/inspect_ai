"""Log sanitization taxonomy for secure log publication.

This module provides a taxonomy for classifying EvalLog fields by sensitivity
and informativeness to support secure log publication.

Example:
    >>> from inspect_ai.log._sanitize import (
    ...     get_field_classification,
    ...     Sensitivity,
    ...     Informativeness,
    ... )
    >>> classification = get_field_classification("EvalSample.input")
    >>> classification.sensitivity
    <Sensitivity.HIGH: 'high'>
    >>> classification.may_contain_user_data
    True
"""

from ._fields import (
    ContentFlag,
    LevelType,
    get_all_field_paths,
    get_field_classification,
    get_fields_by_informativeness,
    get_fields_by_level,
    get_fields_by_sensitivity,
    get_fields_with_content,
    get_fields_with_credentials,
    get_fields_with_model_output,
    get_fields_with_user_data,
    normalize_field_path,
)
from ._taxonomy import (
    DEFAULT_FIELD_CLASSIFICATION,
    DEFAULT_TAXONOMY,
    DYNAMIC_FIELD_PATTERNS,
    FieldClassification,
    Informativeness,
    Sensitivity,
)

__all__ = [
    # Enums
    "Sensitivity",
    "Informativeness",
    # Classification model
    "FieldClassification",
    # Taxonomy data
    "DEFAULT_TAXONOMY",
    "DYNAMIC_FIELD_PATTERNS",
    "DEFAULT_FIELD_CLASSIFICATION",
    # Lookup functions
    "get_field_classification",
    "normalize_field_path",
    "get_all_field_paths",
    # Parameterized lookup functions
    "ContentFlag",
    "LevelType",
    "get_fields_with_content",
    "get_fields_by_level",
    # Convenience wrappers
    "get_fields_by_sensitivity",
    "get_fields_by_informativeness",
    "get_fields_with_user_data",
    "get_fields_with_model_output",
    "get_fields_with_credentials",
]
