from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MCPServerConfig(BaseModel):
    """Configuration for MCP server."""

    model_config = ConfigDict(frozen=True)

    type: Literal["stdio", "http", "sse"]
    """Server type."""

    name: str
    """Human readable server name."""

    tools: Literal["all"] | list[str] = Field(default="all")
    """Tools to make available from server ("all" for all tools)."""


class MCPServerConfigStdio(MCPServerConfig):
    """Configuration for MCP servers with stdio interface."""

    type: Literal["stdio"] = Field(default="stdio")
    """Server type."""

    command: str
    """The executable to run to start the server."""

    args: list[str] = Field(default_factory=list)
    """Command line arguments to pass to the executable."""

    cwd: str | Path | None = Field(default=None)
    """The working directory to use when spawning the process."""

    env: dict[str, str] | None = Field(default=None)
    """The environment to use when spawning the process in addition to the platform specific set of default environment variables (e.g. "HOME", "LOGNAME", "PATH","SHELL", "TERM", and "USER" for Posix-based systems)"""


class MCPServerConfigHTTP(MCPServerConfig):
    """Conifguration for MCP servers with HTTP interface."""

    type: Literal["http", "sse"]
    """Server type."""

    url: str
    """URL for remote server."""

    headers: dict[str, str] | None = Field(default=None)
    """Headers for remote server (type "http" or "sse")"""

    @property
    def authorization_token(self) -> str | None:
        if self.headers and "Authorization" in self.headers:
            authorization = str(self.headers["Authorization"])
            authorization = (
                authorization[7:]
                if authorization.upper().startswith("BEARER ")
                else authorization
            )
            return authorization
        else:
            return None
