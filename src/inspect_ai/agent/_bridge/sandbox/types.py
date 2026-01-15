from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.model._model import GenerateFilter
from inspect_ai.tool import Tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP


class SandboxAgentBridge(AgentBridge):
    """Sandbox agent bridge."""

    def __init__(
        self,
        state: AgentState,
        filter: GenerateFilter | None,
        retry_refusals: int | None,
        compaction: CompactionStrategy | None,
        port: int,
        model: str | None,
        mcp_server_configs: list[MCPServerConfigHTTP] | None = None,
        bridged_tools: dict[str, dict[str, Tool]] | None = None,
    ) -> None:
        super().__init__(state, filter, retry_refusals, compaction)
        self.port = port
        self.model = model
        self.mcp_server_configs = mcp_server_configs or []
        self.bridged_tools = bridged_tools or {}

    port: int
    """Model proxy server port."""

    model: str | None
    """Model to use when the request does not use "inspect" or an "inspect/"
    prefixed model (defaults to "inspect", can also specify e.g.
    "inspect/openai/gpt-4o" to force another specific model).
    """

    mcp_server_configs: list[MCPServerConfigHTTP]
    """MCP server configs for bridged tools (resolved from bridged_tools parameter)."""

    bridged_tools: dict[str, dict[str, Tool]]
    """Registry of bridged tools by server name, then tool name."""
