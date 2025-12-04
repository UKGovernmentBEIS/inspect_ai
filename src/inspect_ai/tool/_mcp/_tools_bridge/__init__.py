"""MCP tools bridge for exposing host-side tools to sandboxed agents."""

from .bridge import BridgedToolsSpec, setup_bridged_tools

__all__ = ["BridgedToolsSpec", "setup_bridged_tools"]
