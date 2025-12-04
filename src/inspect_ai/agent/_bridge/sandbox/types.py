from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._model import GenerateFilter
from inspect_ai.tool._mcp._config import MCPServerConfigStdio


class SandboxAgentBridge(AgentBridge):
    """Sandbox agent bridge."""

    def __init__(
        self,
        state: AgentState,
        filter: GenerateFilter | None,
        retry_refusals: int | None,
        port: int,
        model: str | None,
        mcp_server_configs: list[MCPServerConfigStdio] | None = None,
    ) -> None:
        super().__init__(state, filter, retry_refusals)
        self.port = port
        self.model = model
        self.mcp_server_configs = mcp_server_configs or []

    port: int
    """Model proxy server port."""

    model: str | None
    """Specify that the bridge should use a speicifc model (e.g. "inspect" to use
    thet default model for the task or "inspect/openai/gpt-4o" to use another
    specific model).
    """

    mcp_server_configs: list[MCPServerConfigStdio]
    """MCP server configs for bridged tools (resolved from bridged_tools parameter)."""
