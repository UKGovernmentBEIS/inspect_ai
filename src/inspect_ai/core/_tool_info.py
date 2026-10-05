from typing import Any

from pydantic import BaseModel, Field

from ._tool_params import ToolParams


class ToolInfo(BaseModel):
    """Specification of a tool (JSON Schema compatible)

    If you are implementing a ModelAPI, most LLM libraries can
    be passed this object (dumped to a dict) directly as a function
    specification. For example, in the OpenAI provider:

    ```python
    ChatCompletionToolParam(
        type="function",
        function=tool.model_dump(exclude_none=True),
    )
    ```

    In some cases the field names don't match up exactly. In that case
    call `model_dump()` on the `parameters` field. For example, in the
    Anthropic provider:

    ```python
    ToolParam(
        name=tool.name,
        description=tool.description,
        input_schema=tool.parameters.model_dump(exclude_none=True),
    )
    ```
    """

    name: str
    """Name of tool."""
    description: str
    """Short description of tool."""
    parameters: ToolParams = Field(default_factory=ToolParams)
    """JSON Schema of tool parameters object."""
    options: dict[str, Any] | None = Field(default=None)
    """Optional property bag that can be used by the model provider to customize the implementation of the tool"""


INTERNAL_TOOL_TYPE = "__internal_tool_type__"
"""Well-known ``ToolInfo.options`` key carrying the
:class:`~inspect_ai.core.ContentToolUse` ``tool_type`` literal
(``"web_search"`` / ``"code_execution"`` / ``"mcp_call"``) for tools that a
model provider may execute server-side within a single API call."""


def internal_tool_type(tool: ToolInfo) -> str | None:
    """Return the server-side tool type if ``tool`` is an internal tool.

    Internal tools (:func:`~inspect_ai.tool.web_search`,
    :func:`~inspect_ai.tool.code_execution`, hosted MCP) set
    :data:`INTERNAL_TOOL_TYPE` in their ``options``; this returns that value
    so callers (e.g. agent-bridge filters) can distinguish them from
    ordinary function tools without name-matching. Returns ``None`` for
    function tools.
    """
    return (tool.options or {}).get(INTERNAL_TOOL_TYPE)
