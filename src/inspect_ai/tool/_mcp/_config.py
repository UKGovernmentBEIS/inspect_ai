from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class MCPConfig:
    type: Literal["stdio", "http", "sse"]


@dataclass(frozen=True)
class MCPConfigStdio(MCPConfig):
    type: Literal["stdio"]


@dataclass(frozen=True)
class MCPConfigRemote(MCPConfig):
    type: Literal["http", "sse"]
    url: str | None = field(default=None)
    authorization: str | None = field(default=None)


@dataclass(frozen=True)
class MCPConfigHTTP(MCPConfigRemote):
    type: Literal["http"]


@dataclass(frozen=True)
class MCPConfigSSE(MCPConfigRemote):
    type: Literal["sse"]
