from contextlib import _AsyncGeneratorContextManager
from typing import TypeAlias

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.types import (
    JSONRPCMessage,
)

MCPServerContext: TypeAlias = _AsyncGeneratorContextManager[
    tuple[
        MemoryObjectReceiveStream[JSONRPCMessage | Exception],
        MemoryObjectSendStream[JSONRPCMessage],
    ],
]
