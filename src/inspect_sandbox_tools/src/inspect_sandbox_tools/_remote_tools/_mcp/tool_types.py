from pydantic import BaseModel

from ..._util.user_switch import RunAs
from .jsonrpc_types import JSONRPCNotification, JSONRPCRequest, StdioServerParameters


class McpBaseParams(BaseModel):
    session_id: int
    """This is the id the represents the MCP session - which also correlates to a process instance."""


class LaunchServerParams(BaseModel):
    server_params: StdioServerParameters
    run_as: RunAs | None = None
    """Sandbox default user to run the server as."""


class KillServerParams(McpBaseParams):
    pass


class SendRequestParams(McpBaseParams):
    request: JSONRPCRequest


class SendNotificationParams(McpBaseParams):
    notification: JSONRPCNotification
