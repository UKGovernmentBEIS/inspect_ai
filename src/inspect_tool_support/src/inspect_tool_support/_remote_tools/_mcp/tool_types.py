from typing import Literal

from mcp import JSONRPCRequest, JSONRPCResponse, StdioServerParameters
from pydantic import BaseModel, RootModel


class McpBaseParams(BaseModel):
    session_name: str
    server_name: str


class CreateProcessParams(McpBaseParams):
    server_params: StdioServerParameters


class KillProcessParams(McpBaseParams):
    pass


class ExecuteRequestParams(McpBaseParams):
    inner_request: JSONRPCRequest


class McpParams(
    RootModel[CreateProcessParams | KillProcessParams | ExecuteRequestParams]
):
    pass


ExecuteRequestResult = JSONRPCResponse


class NewSessionResult(BaseModel):
    session_name: str


CreateProcessResult = Literal["OK"]


KillProcessResult = Literal["OK"]
