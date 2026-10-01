"""The parameter schemas a bridged scaffold declared, as it declared them."""

from typing import Any

from inspect_ai.model._openai_responses import RESPONSES_VERBATIM
from inspect_ai.tool._tool_info import ToolInfo


def with_declared_schema(info: ToolInfo, schema: Any) -> ToolInfo:
    """Record the JSON Schema `info` was declared with (if it is an object).

    `info.parameters` is a normalized copy that can drop constraints (`oneOf`,
    `$ref`) or add them (`additionalProperties: false` when omitted), so a call
    is validated against the schema as declared instead (`effective_schema()`).
    The schema is not serialized with `info`.
    """
    if isinstance(schema, dict):
        info._declared_parameters = dict(schema)
        info._declared_for = info.parameters.model_copy(deep=True)
    return info


def effective_schema(info: ToolInfo) -> dict[str, Any]:
    """The JSON Schema a call to `info` is validated against before approval.

    The schema the model is sent for the declaration: the verbatim Responses
    declaration when there is one, otherwise the schema recorded by
    `with_declared_schema()` while `info.parameters` is still what it was
    declared with. A declaration a filter changed or built has only its
    `parameters`.
    """
    verbatim = (info.options or {}).get(RESPONSES_VERBATIM)
    if isinstance(verbatim, dict) and isinstance(verbatim.get("parameters"), dict):
        return dict(verbatim["parameters"])
    if info._declared_parameters is not None and info._declared_for == info.parameters:
        return info._declared_parameters
    return info.parameters.model_dump(exclude_none=True)
