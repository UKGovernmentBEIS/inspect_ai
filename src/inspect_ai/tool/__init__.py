from inspect_ai._util.citation import (
    Citation,
    CitationBase,
    ContentCitation,
    DocumentCitation,
    UrlCitation,
)
from inspect_ai._util.content import (
    Content,
    ContentAudio,
    ContentData,
    ContentImage,
    ContentReasoning,
    ContentText,
    ContentVideo,
)
from inspect_ai._util.deprecation import relocated_module_attribute

from ._mcp import (
    MCPServer,
    mcp_connection,
    mcp_server_sandbox,
    mcp_server_sse,
    mcp_server_stdio,
    mcp_tools,
)
from ._tool import Tool, ToolError, ToolResult, ToolSource, tool
from ._tool_call import (
    ToolCall,
    ToolCallContent,
    ToolCallError,
    ToolCallModelInput,
    ToolCallView,
    ToolCallViewer,
)
from ._tool_choice import ToolChoice, ToolFunction
from ._tool_def import ToolDef
from ._tool_info import ToolInfo
from ._tool_params import ToolParam, ToolParams
from ._tool_with import tool_with
from ._tools._bash_session import bash_session
from ._tools._computer import computer
from ._tools._execute import bash, python
from ._tools._text_editor import text_editor
from ._tools._think import think
from ._tools._web_browser import web_browser
from ._tools._web_search import web_search

__all__ = [
    "bash",
    "bash_session",
    "computer",
    "python",
    "web_browser",
    "web_search",
    "think",
    "text_editor",
    "tool",
    "tool_with",
    "Tool",
    "ToolCallError",
    "ToolError",
    "ToolResult",
    "ToolSource",
    "mcp_tools",
    "mcp_connection",
    "mcp_server_stdio",
    "mcp_server_sse",
    "mcp_server_sandbox",
    "MCPServer",
    "Content",
    "ContentAudio",
    "ContentData",
    "ContentImage",
    "ContentReasoning",
    "ContentText",
    "ContentVideo",
    "ToolCall",
    "ToolCallContent",
    "ToolCallModelInput",
    "ToolCallView",
    "ToolCallViewer",
    "ToolChoice",
    "ToolDef",
    "ToolFunction",
    "ToolInfo",
    "ToolParam",
    "ToolParams",
    "Citation",
    "CitationBase",
    "DocumentCitation",
    "ContentCitation",
    "UrlCitation",
]

_UTIL_MODULE_VERSION = "0.3.19"
_JSON_MODULE_VERSION = "0.3.73"
_REMOVED_IN = "0.4"

relocated_module_attribute(
    "JSONType",
    "inspect_ai.util.JSONType",
    _JSON_MODULE_VERSION,
    _REMOVED_IN,
)

relocated_module_attribute(
    "ToolEnvironment",
    "inspect_ai.util.SandboxEnvironment",
    _UTIL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ToolEnvironments",
    "inspect_ai.util.SandboxEnvironments",
    _UTIL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "ToolEnvironmentSpec",
    "inspect_ai.util.SandboxEnvironmentSpec",
    _UTIL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "tool_environment",
    "inspect_ai.util.sandbox",
    _UTIL_MODULE_VERSION,
    _REMOVED_IN,
)
relocated_module_attribute(
    "toolenv", "inspect_ai.util.sandboxenv", _UTIL_MODULE_VERSION, _REMOVED_IN
)
relocated_module_attribute(
    "web_browser_tools",
    "inspect_ai.tool.web_browser",
    "0.3.19",
    _REMOVED_IN,
)
