"""How a sandboxed scaffold names bridged tools to its model."""

from typing import Any, NamedTuple, Sequence

from inspect_ai.tool._tool_call import ToolCall


class BridgedToolName(NamedTuple):
    """One name a scaffold declares a bridged tool under to its model."""

    name: str
    """The function name the model sees and calls."""

    namespace: str | None = None
    """The Responses API namespace the function is grouped in, when the scaffold
    uses one (Codex CLI); `None` for a flat declaration."""


class BridgedToolCall(NamedTuple):
    """The bridged tool call a dispatcher call stands for."""

    server: str
    """Bridged server named by the call."""

    tool: str
    """Tool within the server."""

    arguments: dict[str, Any]
    """The arguments the scaffold will send to the tool."""


class BridgedToolNaming:
    """How a sandboxed scaffold presents bridged tools to its model.

    The sandbox agent bridge executes a host tool only for a call the model
    proposed, so it has to map the function name in a model response back to the
    bridged (server, tool). Scaffolds name MCP tools to their models under their
    own schemes: a per-tool function under a rewritten name (for example
    ``mcp__<server>__<tool>``), a bare name grouped in a Responses API namespace,
    or one dispatcher function whose arguments name the target. The naming is a
    property of the scaffold and its version, so the wrapper that launches the
    scaffold passes it to `sandbox_agent_bridge(tool_naming=...)`.

    Subclass and override `declared_names` for a scaffold that declares each
    bridged tool as its own function, and `dispatched_call` for one that routes
    calls through a dispatcher. The base class is the default naming: the bare
    tool name and ``mcp__<server>__<tool>``, no dispatcher. A call the naming
    cannot map to exactly one bridged tool is denied, so a wrong or missing naming
    fails closed rather than executing the wrong tool.

    Example:
        ```python
        class OpenCodeNaming(BridgedToolNaming):
            def declared_names(self, server: str, tool: str) -> list[BridgedToolName]:
                return [BridgedToolName(f"{server}_{tool}")]

        async with sandbox_agent_bridge(
            bridged_tools=[BridgedToolsSpec(name="host", tools=[...])],
            tool_naming=OpenCodeNaming(),
        ) as bridge:
            ...
        ```
    """

    def declared_names(self, server: str, tool: str) -> Sequence[BridgedToolName]:
        """The names the scaffold may declare this bridged tool under.

        Usually one. Return several when the scaffold's exact rewriting is not
        known in advance (for example, a length cap that changed between
        versions); a call matching any of them denotes the tool.

        Args:
            server: Bridged server name (`BridgedToolsSpec.name`).
            tool: Tool name within the server, as served by `tools/list`.

        Returns:
            The model-facing names, each with the Responses API namespace it is
            declared in, if any.
        """
        return [BridgedToolName(tool), BridgedToolName(f"mcp__{server}__{tool}")]

    def dispatched_call(self, call: ToolCall) -> BridgedToolCall | None:
        """The bridged tool call a dispatcher call stands for, if this is one.

        For a scaffold that exposes MCP tools through a single function whose
        arguments name the server, tool and arguments. Return `None` for any call
        that is not a dispatch; the call is then resolved by name through
        `declared_names`.

        Args:
            call: A tool call from the model response handed to the scaffold.

        Returns:
            The named bridged tool call, or `None`.
        """
        return None
