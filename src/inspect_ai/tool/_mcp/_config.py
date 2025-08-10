from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MCPConfig:
    type: Literal["stdio", "http", "sse"]
    name: str


@dataclass(frozen=True)
class MCPConfigStdio(MCPConfig):
    type: Literal["stdio"]


@dataclass(frozen=True)
class MCPConfigRemote(MCPConfig):
    type: Literal["http", "sse"]
    url: str
    headers: dict[str, str] | None

    def authorization(self) -> str | None:
        if self.headers and "Authorization" in self.headers:
            authorization = str(self.headers["Authorization"])
            return (
                authorization[7:]
                if authorization.upper().startswith("BEARER ")
                else authorization
            )
        else:
            return None


@dataclass(frozen=True)
class MCPConfigHTTP(MCPConfigRemote):
    type: Literal["http"]


@dataclass(frozen=True)
class MCPConfigSSE(MCPConfigRemote):
    type: Literal["sse"]
