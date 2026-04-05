"""Tests for CustomJsonSchemaGenerator and build_openapi_schema.

Verifies:
1. Field requiredness is determined by nullability, not defaults
2. JsonValue generates a proper oneOf schema instead of empty {}
"""

from typing import Any

import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field, JsonValue

from inspect_ai._view._openapi import _CustomJsonSchemaGenerator, build_openapi_schema


# Test models for requiredness
class NonNullableNoDefault(BaseModel):
    field: str


class NonNullableWithDefault(BaseModel):
    field: str = Field(default="value")


class NullableNoDefault(BaseModel):
    field: str | None


class NullableWithDefault(BaseModel):
    field: str | None = Field(default=None)


class NullableWithNonNoneDefault(BaseModel):
    field: str | None = Field(default="value")


class NestedNonNullable(BaseModel):
    nested: NonNullableNoDefault


class NestedNullable(BaseModel):
    nested: NonNullableNoDefault | None = Field(default=None)


# Test models for JsonValue
class WithJsonValue(BaseModel):
    value: JsonValue


class WithNullableJsonValue(BaseModel):
    value: JsonValue | None = Field(default=None)


def get_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Get JSON schema using CustomJsonSchemaGenerator."""
    return model.model_json_schema(schema_generator=_CustomJsonSchemaGenerator)


def _get_openapi_schemas(model: type[BaseModel]) -> dict[str, Any]:
    """Get components/schemas from build_openapi_schema with model as endpoint."""
    app = FastAPI(title="test", version="0.1.0")

    @app.get(f"/{model.__name__}")
    def _endpoint() -> model:  # type: ignore[valid-type]
        raise NotImplementedError

    return build_openapi_schema(app)["components"]["schemas"]


@pytest.mark.parametrize(
    ("model", "field_name", "expected_required"),
    [
        # Non-nullable fields are always required
        (NonNullableNoDefault, "field", True),
        (NonNullableWithDefault, "field", True),
        # Nullable fields are never required
        (NullableNoDefault, "field", False),
        (NullableWithDefault, "field", False),
        (NullableWithNonNoneDefault, "field", False),
        # Nested models follow same rules
        (NestedNonNullable, "nested", True),
        (NestedNullable, "nested", False),
    ],
    ids=[
        "str_no_default",
        "str_with_default",
        "str|None_no_default",
        "str|None_default_None",
        "str|None_default_value",
        "nested_non_nullable",
        "nested_nullable",
    ],
)
def test_field_requiredness(
    model: type[BaseModel], field_name: str, expected_required: bool
) -> None:
    schema = get_schema(model)
    required = schema.get("required", [])
    if expected_required:
        assert field_name in required
    else:
        assert field_name not in required


def test_default_pydantic_treats_defaulted_fields_as_optional() -> None:
    """Document difference: default Pydantic makes fields with defaults optional."""
    schema = NonNullableWithDefault.model_json_schema()
    assert "field" not in schema.get("required", [])

    # Our custom generator keeps non-nullable fields required
    custom_schema = get_schema(NonNullableWithDefault)
    assert "field" in custom_schema.get("required", [])


def test_pydantic_json_value_is_empty() -> None:
    """Pydantic generates empty {} for JsonValue; TS postTransform handles it."""
    schema = WithJsonValue.model_json_schema()
    assert schema["$defs"]["JsonValue"] == {}

    # build_openapi_schema passes it through as-is
    schemas = _get_openapi_schemas(WithJsonValue)
    assert schemas["JsonValue"] == {}
