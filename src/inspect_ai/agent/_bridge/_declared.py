"""The parameter schemas a bridged scaffold declared, as it declared them."""

from typing import Any

from inspect_ai.tool._tool_info import ToolInfo


def with_declared_schema(info: ToolInfo, schema: Any) -> ToolInfo:
    """Record the JSON Schema `info` was declared with (if it is an object).

    `info.parameters` is a normalized copy that can drop constraints (`oneOf`,
    `$ref`) or add them (`additionalProperties: false` when omitted), so a call
    is validated against the schema the model was given instead
    (`AgentBridge.reviewed_calls`). The schema is not serialized with `info`.
    """
    if isinstance(schema, dict):
        info._declared_parameters = dict(schema)
    return info


def declared_schema(info: ToolInfo) -> dict[str, Any] | None:
    """The JSON Schema recorded by `with_declared_schema()`, if any."""
    return info._declared_parameters
