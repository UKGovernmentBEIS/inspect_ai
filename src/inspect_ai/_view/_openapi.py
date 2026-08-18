"""OpenAPI schema generation helpers.

Shared between inspect_ai and inspect_scout. Scout imports from here
to ensure both produce structurally identical OpenAPI schemas.
"""

from typing import Any

from fastapi import FastAPI
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import CoreSchema, core_schema


class _CustomJsonSchemaGenerator(GenerateJsonSchema):
    """Custom JSON schema generator for OpenAPI schemas.

    Customizations:
    - JSON Schema `required` list is determined by nullability, not defaults.
      Non-nullable fields are always required even with defaults (`str = "foo"`
      → required). Nullable fields are never required (`str | None = None`
      → not required). See design/type-optionality.md for rationale.
    """

    def _is_nullable_schema(self, schema: CoreSchema) -> bool:
        """Check if schema represents a nullable type."""
        schema_type = schema.get("type")
        if schema_type == "nullable":
            return True
        if schema_type in (
            "default",
            "function-before",
            "function-after",
            "function-wrap",
        ):
            return self._is_nullable_schema(schema.get("schema", {}))
        return False

    def field_is_required(
        self,
        field: core_schema.ModelField
        | core_schema.DataclassField
        | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        schema = field.get("schema", {})
        return not self._is_nullable_schema(schema)


def build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """Build customized OpenAPI schema.

    Args:
        app: FastAPI application with endpoints whose return types define
            the schema. Use RootModel wrappers to give stable names to
            unions and literals.

    Returns:
        OpenAPI schema dict with post-processing applied.
    """
    import fastapi._compat as fastapi_compat
    import fastapi.openapi.utils as openapi_utils
    from fastapi.openapi.utils import get_openapi

    # Monkey-patch custom schema generator for nullability-based required semantics.
    # FastAPI < 0.118 keeps `GenerateJsonSchema` on a `v2` submodule; FastAPI 0.118+
    # collapsed `_compat` into a single module and the lookup site moved into
    # `fastapi.openapi.utils` itself, so patch both locations defensively.
    if hasattr(fastapi_compat, "v2"):
        setattr(fastapi_compat.v2, "GenerateJsonSchema", _CustomJsonSchemaGenerator)
    else:
        setattr(fastapi_compat, "GenerateJsonSchema", _CustomJsonSchemaGenerator)
    setattr(openapi_utils, "GenerateJsonSchema", _CustomJsonSchemaGenerator)

    openapi_schema = get_openapi(
        title=app.title, version=app.version, routes=app.routes
    )

    # Remove implied and noisy 422 responses
    for path in openapi_schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict):
                operation.get("responses", {}).pop("422", None)

    return openapi_schema
