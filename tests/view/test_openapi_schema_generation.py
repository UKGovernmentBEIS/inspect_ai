"""Tests for the Python → OpenAPI JSON Schema layer.

Verifies that field optionality is consistent across entry paths:
  1. FastAPI endpoint return type (response)
  2. FastAPI endpoint parameter (request body)

For each field pattern, we verify:
  - Whether the field is in the JSON Schema `required` list
  - Whether the property has a `"default"` key
  - Whether the property has anyOf with null (nullable)
"""

from typing import Annotated, Any, Literal, NamedTuple

import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Discriminator, RootModel, Tag

from inspect_ai._view._openapi import build_openapi_schema

# ---------------------------------------------------------------------------
# Test models — each has a single `field` with a specific pattern
# ---------------------------------------------------------------------------


class StrRequired(BaseModel):
    field: str


class StrWithDefault(BaseModel):
    field: str = "foo"


class StrOrNone(BaseModel):
    field: str | None


class StrOrNoneDefaultNone(BaseModel):
    field: str | None = None


class StrOrNoneDefaultFoo(BaseModel):
    field: str | None = "foo"


class IntWithDefault(BaseModel):
    field: int = 0


class ListOrNoneDefaultNone(BaseModel):
    field: list[str] | None = None


class DictOrNoneDefaultNone(BaseModel):
    """Object|null — the type that triggers TS crashes with incorrect optionality."""

    field: dict[str, Any] | None = None


ALL_MODELS = [
    StrRequired,
    StrWithDefault,
    StrOrNone,
    StrOrNoneDefaultNone,
    StrOrNoneDefaultFoo,
    IntWithDefault,
    ListOrNoneDefaultNone,
    DictOrNoneDefaultNone,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _endpoint_input_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Schema when model is a FastAPI endpoint request body (input)."""
    app = FastAPI(title="test", version="0.1.0")

    @app.post(f"/{model.__name__}")
    def _endpoint(item: model) -> None:  # type: ignore[valid-type]
        raise NotImplementedError

    openapi = build_openapi_schema(app)
    return openapi["components"]["schemas"][model.__name__]


def _endpoint_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Schema when model is a FastAPI endpoint return type (output)."""
    app = FastAPI(title="test", version="0.1.0")

    @app.get(f"/{model.__name__}")
    def _endpoint() -> model:  # type: ignore[valid-type]
        raise NotImplementedError

    openapi = build_openapi_schema(app)
    return openapi["components"]["schemas"][model.__name__]


def _is_required(schema: dict[str, Any], field: str) -> bool:
    return field in schema.get("required", [])


def _has_default(schema: dict[str, Any], field: str) -> bool:
    return "default" in schema.get("properties", {}).get(field, {})


def _is_nullable(schema: dict[str, Any], field: str) -> bool:
    """True if property uses anyOf containing {"type": "null"}."""
    prop = schema.get("properties", {}).get(field, {})
    any_of = prop.get("anyOf", [])
    return any(entry.get("type") == "null" for entry in any_of)


# ---------------------------------------------------------------------------
# Expected values for each model
# ---------------------------------------------------------------------------


class Expect(NamedTuple):
    """Expected JSON Schema properties for a Pydantic field.

    Attributes:
        required: Whether the field appears in the schema's `required` list.
            Our _CustomJsonSchemaGenerator bases this on nullability: non-nullable
            fields are required (even with defaults), nullable fields are not.
        has_default: Whether the field's property dict contains a `"default"` key.
            Pydantic includes `"default": null` for `str | None = None` and
            `"default": "foo"` for `str = "foo"`.
        nullable: Whether the field's property uses `anyOf` containing
            `{"type": "null"}`, indicating the field accepts null values.
    """

    required: bool
    has_default: bool
    nullable: bool


EXPECTATIONS: dict[type[BaseModel], Expect] = {
    StrRequired: Expect(required=True, has_default=False, nullable=False),
    StrWithDefault: Expect(required=True, has_default=True, nullable=False),
    IntWithDefault: Expect(required=True, has_default=True, nullable=False),
    StrOrNone: Expect(required=False, has_default=False, nullable=True),
    StrOrNoneDefaultNone: Expect(required=False, has_default=False, nullable=True),
    StrOrNoneDefaultFoo: Expect(required=False, has_default=True, nullable=True),
    ListOrNoneDefaultNone: Expect(required=False, has_default=False, nullable=True),
    DictOrNoneDefaultNone: Expect(required=False, has_default=False, nullable=True),
}


# ---------------------------------------------------------------------------
# Parametrized: all models × all entry paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ALL_MODELS, ids=[m.__name__ for m in ALL_MODELS])
@pytest.mark.parametrize(
    "schema_fn",
    [_endpoint_input_schema, _endpoint_output_schema],
    ids=["endpoint_input", "endpoint_output"],
)
def test_field_schema_properties(
    model: type[BaseModel],
    schema_fn: Any,
) -> None:
    """All entry paths should produce identical required/default/nullable."""
    schema = schema_fn(model)
    expect = EXPECTATIONS[model]
    field = "field"
    expect_has_default = expect.has_default

    assert _is_required(schema, field) == expect.required, (
        f"required mismatch for {model.__name__} via {schema_fn.__name__}: "
        f"got {_is_required(schema, field)}, expected {expect.required}\n"
        f"schema={schema}"
    )
    assert _has_default(schema, field) == expect_has_default, (
        f"default mismatch for {model.__name__} via {schema_fn.__name__}: "
        f"got {_has_default(schema, field)}, expected {expect_has_default}\n"
        f"schema={schema}"
    )
    assert _is_nullable(schema, field) == expect.nullable, (
        f"nullable mismatch for {model.__name__} via {schema_fn.__name__}: "
        f"got {_is_nullable(schema, field)}, expected {expect.nullable}\n"
        f"schema={schema}"
    )


# ---------------------------------------------------------------------------
# Verify no -Input/-Output variants are generated
# ---------------------------------------------------------------------------


def _all_schemas_for_input(model: type[BaseModel]) -> dict[str, Any]:
    app = FastAPI(title="test", version="0.1.0")

    @app.post(f"/{model.__name__}")
    def _endpoint(item: model) -> None:  # type: ignore[valid-type]
        raise NotImplementedError

    return build_openapi_schema(app)["components"]["schemas"]


def _all_schemas_for_output(model: type[BaseModel]) -> dict[str, Any]:
    app = FastAPI(title="test", version="0.1.0")

    @app.get(f"/{model.__name__}")
    def _endpoint() -> model:  # type: ignore[valid-type]
        raise NotImplementedError

    return build_openapi_schema(app)["components"]["schemas"]


@pytest.mark.parametrize("model", ALL_MODELS, ids=[m.__name__ for m in ALL_MODELS])
@pytest.mark.parametrize(
    "schemas_fn",
    [_all_schemas_for_input, _all_schemas_for_output],
    ids=["endpoint_input", "endpoint_output"],
)
def test_no_input_output_variants(model: type[BaseModel], schemas_fn: Any) -> None:
    """No entry path should produce -Input/-Output variants.

    On current Pydantic (2.11+), json_schema_serialization_defaults_required
    defaults to False, making validation and serialization schemas identical.
    """
    schemas = schemas_fn(model)
    variant_names = [n for n in schemas if "-Input" in n or "-Output" in n]
    assert variant_names == [], (
        f"Unexpected -Input/-Output variants for {model.__name__} "
        f"via {schemas_fn.__name__}: {variant_names}"
    )


# ---------------------------------------------------------------------------
# Contrast with default Pydantic behavior
# ---------------------------------------------------------------------------


def test_default_pydantic_makes_defaulted_fields_not_required() -> None:
    """Without our override, str = 'foo' would NOT be required."""
    default_schema = StrWithDefault.model_json_schema()
    assert "field" not in default_schema.get("required", [])

    # Our override (via endpoint) keeps non-nullable fields required
    custom_schema = _endpoint_output_schema(StrWithDefault)
    assert "field" in custom_schema.get("required", [])


# ---------------------------------------------------------------------------
# Union types via RootModel endpoints
#
# These tests document how Pydantic/FastAPI represent unions in OpenAPI
# schemas when exposed via RootModel endpoint wrappers. The behavior
# differs based on whether a Discriminator annotation is present:
#
#   - Plain Union[A, B]                        → anyOf, no discriminator
#   - Annotated[Union[...], Discriminator(...)] → oneOf + discriminator mapping
#
# Both produce a named schema entry whose key is the RootModel class name,
# with member types referenced via $ref.
# ---------------------------------------------------------------------------


class DogModel(BaseModel):
    type: Literal["dog"] = "dog"
    bark: str


class CatModel(BaseModel):
    type: Literal["cat"] = "cat"
    meow: str


# Plain union of models — no discriminator annotation
PlainAnimalUnion = DogModel | CatModel


class PlainAnimal(RootModel[PlainAnimalUnion]):
    pass


# Mixed union — Literal values + a Pydantic model (like ToolChoice)
class CustomChoice(BaseModel):
    name: str


MixedUnion = Literal["auto", "none"] | CustomChoice


class MixedChoice(RootModel[MixedUnion]):
    pass


# Discriminated union — field-based discriminator (requires Union[] for Annotated)
DiscriminatedAnimalUnion = Annotated[
    Annotated[DogModel, Tag("dog")] | Annotated[CatModel, Tag("cat")],
    Discriminator("type"),
]


class DiscriminatedAnimal(RootModel[DiscriminatedAnimalUnion]):
    pass


def _union_schemas(
    *root_models: type[RootModel[Any]],
) -> dict[str, Any]:
    """Build OpenAPI schemas dict with RootModel endpoints."""
    app = FastAPI(title="test", version="0.1.0")
    for i, model in enumerate(root_models):
        name = model.__name__

        def make_endpoint(m: type[RootModel[Any]]) -> Any:
            def endpoint() -> m:  # type: ignore[valid-type]
                raise NotImplementedError

            return endpoint

        app.get(f"/{name}-{i}")(make_endpoint(model))
    return build_openapi_schema(app)["components"]["schemas"]


def test_plain_union_via_rootmodel_endpoint() -> None:
    """Plain Union (no Discriminator) produces anyOf without discriminator."""
    schemas = _union_schemas(PlainAnimal)

    assert "PlainAnimal" in schemas
    animal = schemas["PlainAnimal"]

    # Plain unions use anyOf
    assert "anyOf" in animal
    assert "oneOf" not in animal
    assert "discriminator" not in animal

    # Members referenced via $ref
    refs = {entry["$ref"] for entry in animal["anyOf"] if "$ref" in entry}
    assert "#/components/schemas/DogModel" in refs
    assert "#/components/schemas/CatModel" in refs

    # Member schemas exist
    assert "DogModel" in schemas
    assert "CatModel" in schemas


def test_mixed_union_via_rootmodel_endpoint() -> None:
    """Union of Literal values + a model produces anyOf with inline enums."""
    schemas = _union_schemas(MixedChoice)

    assert "MixedChoice" in schemas
    choice = schemas["MixedChoice"]

    # Mixed unions use anyOf
    assert "anyOf" in choice
    assert "oneOf" not in choice
    assert "discriminator" not in choice

    # One entry is a $ref to the model, others are inline enum/const schemas
    refs = [entry for entry in choice["anyOf"] if "$ref" in entry]
    non_refs = [entry for entry in choice["anyOf"] if "$ref" not in entry]
    assert len(refs) == 1
    assert refs[0]["$ref"] == "#/components/schemas/CustomChoice"
    assert len(non_refs) > 0
    # Literal values appear as const or enum entries
    literal_values = set()
    for entry in non_refs:
        if "const" in entry:
            literal_values.add(entry["const"])
        elif "enum" in entry:
            literal_values.update(entry["enum"])
    assert literal_values == {"auto", "none"}

    assert "CustomChoice" in schemas


def test_discriminated_union_via_rootmodel_endpoint() -> None:
    """Discriminated union produces oneOf with discriminator mapping."""
    schemas = _union_schemas(DiscriminatedAnimal)

    assert "DiscriminatedAnimal" in schemas
    animal = schemas["DiscriminatedAnimal"]

    # Discriminated unions use oneOf
    assert "oneOf" in animal
    assert "anyOf" not in animal

    # Members referenced via $ref
    refs = {entry["$ref"] for entry in animal["oneOf"] if "$ref" in entry}
    assert "#/components/schemas/DogModel" in refs
    assert "#/components/schemas/CatModel" in refs

    # Discriminator mapping present
    assert animal["discriminator"]["propertyName"] == "type"
    mapping = animal["discriminator"]["mapping"]
    assert mapping["dog"] == "#/components/schemas/DogModel"
    assert mapping["cat"] == "#/components/schemas/CatModel"

    # Member schemas exist
    assert "DogModel" in schemas
    assert "CatModel" in schemas


# ---------------------------------------------------------------------------
# JsonValue
#
# Pydantic generates an empty {} schema for JsonValue (a recursive type it
# can't represent). The TS side handles this via a postTransform in
# openapi-typescript that replaces JsonValue references with a proper
# recursive TypeScript type imported from @tsmono/util.
# ---------------------------------------------------------------------------


def test_json_value_is_empty_schema() -> None:
    """Pydantic produces empty {} for JsonValue; TS postTransform handles it."""
    from pydantic import JsonValue

    class HasJsonValue(BaseModel):
        data: JsonValue

    app = FastAPI(title="test", version="0.1.0")

    @app.get("/has-json-value")
    def _endpoint() -> HasJsonValue:
        raise NotImplementedError

    schemas = build_openapi_schema(app)["components"]["schemas"]

    assert "JsonValue" in schemas
    assert schemas["JsonValue"] == {}
