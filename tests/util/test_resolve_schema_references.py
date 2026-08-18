"""Tests for resolve_schema_references handling of self-referential schemas.

resolve_schema_references inlines $ref pointers by replacing them with deep copies of the referenced definition, then recursively processing the copy. This works for non-recursive schemas but enters infinite recursion when a
definition references itself — e.g. JSONSchema, where fields like `items`, `properties`, `additionalProperties`, and `anyOf` all point back to `#/$defs/JSONSchema`.

This matters in practice because cls_json_schema() calls
resolve_schema_references on the output of model_json_schema() for any Pydantic BaseModel used as a tool parameter type hint. ToolParams (which contains JSONSchema) is one such type — any tool whose signature includes `ToolParams` triggers infinite recursion during parse_tool_info.
"""

from inspect_ai.tool._tool_info import parse_tool_info
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util._json import JSONSchema, cls_json_schema, resolve_schema_references

# ── resolve_schema_references ────────────────────────────────────────────────


def test_resolve_non_recursive_refs() -> None:
    """Baseline: non-recursive $defs should still be inlined correctly."""
    schema = {
        "type": "object",
        "properties": {
            "address": {"$ref": "#/$defs/Address"},
        },
        "$defs": {
            "Address": {
                "type": "object",
                "properties": {
                    "street": {"type": "string"},
                    "city": {"type": "string"},
                },
            }
        },
    }

    resolved = resolve_schema_references(schema)

    # $defs should be removed
    assert "$defs" not in resolved
    # The $ref should be replaced with the inlined definition
    addr = resolved["properties"]["address"]
    assert addr["type"] == "object"
    assert "street" in addr["properties"]
    assert "city" in addr["properties"]


def test_resolve_self_referential_refs() -> None:
    """Self-referential $defs must not cause infinite recursion.

    JSONSchema is the canonical example: its `items`, `properties`,
    `additionalProperties`, and `anyOf` fields all reference back to
    `#/$defs/JSONSchema`.  resolve_schema_references currently tries to
    inline these recursively without cycle detection, causing a
    RecursionError.
    """
    # Use the actual JSONSchema model — this is the real-world case that
    # triggers the bug.
    schema = JSONSchema.model_json_schema()

    # This should complete without RecursionError.
    resolved = resolve_schema_references(schema)

    assert "$defs" not in resolved
    assert resolved["type"] == "object"


# ── cls_json_schema ──────────────────────────────────────────────────────────


def test_cls_json_schema_self_referential_model() -> None:
    """cls_json_schema should handle self-referential Pydantic models.

    cls_json_schema calls model_json_schema() then resolve_schema_references().
    For self-referential models like JSONSchema (used inside ToolParams), this
    currently causes infinite recursion.
    """
    result = cls_json_schema(JSONSchema)
    assert result.type == "object"


def test_cls_json_schema_toolparams() -> None:
    """ToolParams contains JSONSchema and must not recurse infinitely."""
    result = cls_json_schema(ToolParams)
    assert result.type == "object"
    assert "properties" in (result.properties or {})


# ── parse_tool_info with ToolParams parameter ────────────────────────────────


def test_parse_tool_info_toolparams_parameter() -> None:
    """parse_tool_info must handle functions with ToolParams type hints.

    This is the end-to-end scenario: a tool function has a parameter typed
    as `ToolParams | None`. When inspect processes the tool (e.g. during
    disable_parallel_tools in Model.generate), parse_tool_info is called,
    which calls json_schema(ToolParams | None) -> cls_json_schema(ToolParams)
    -> resolve_schema_references on the self-referential schema.
    """

    async def my_tool(name: str, parameters: ToolParams | None = None) -> str:
        """Create a tool.

        Args:
            name: Tool name.
            parameters: JSON Schema for parameters.
        """
        return ""

    info = parse_tool_info(my_tool)
    assert info.name == "my_tool"
    assert "name" in info.parameters.properties
    assert "parameters" in info.parameters.properties
