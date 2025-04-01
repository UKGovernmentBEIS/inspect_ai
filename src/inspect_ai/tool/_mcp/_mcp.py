from pathlib import Path
from typing import Any, Literal

from ._types import McpClient


class McpSSEClient(McpClient):
    def __init__(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: float = 5,
        sse_read_timeout: float = 60 * 5,
    ) -> None:
        super().__init__()

    async def close(self) -> None:
        pass


class McpStdioClient(McpClient):
    def __init__(
        self,
        command: str,
        args: list[str] = [],
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        encoding: str = "utf-8",
        encoding_error_handler: Literal["strict", "ignore", "replace"] = "strict",
    ) -> None:
        super().__init__()

        # self._client =

    async def close(self) -> None:
        pass


class McpSandboxClient(McpClient):
    def __init__(self) -> None:
        super().__init__()

    async def close(self) -> None:
        pass
