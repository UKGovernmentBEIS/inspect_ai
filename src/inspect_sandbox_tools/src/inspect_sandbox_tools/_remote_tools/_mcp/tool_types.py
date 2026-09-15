from pydantic import BaseModel

from ..._util.user_switch import RunAs
from .jsonrpc_types import JSONRPCNotification, JSONRPCRequest, StdioServerParameters


class McpBaseParams(BaseModel):
    session_id: int
    """This is the id the represents the MCP session - which also correlates to a process instance."""


class LaunchServerParams(BaseModel):
    server_params: StdioServerParameters
    user: str | RunAs | None = None
    """User to run as: a username, or the sandbox default user's identity as
    captured by the host. Switching requires the server to run as root, unless
    the server already runs as that identity."""
    model_config = {"extra": "forbid"}


class KillServerParams(McpBaseParams):
    pass


class SendRequestParams(McpBaseParams):
    request: JSONRPCRequest


class SendNotificationParams(McpBaseParams):
    notification: JSONRPCNotification
