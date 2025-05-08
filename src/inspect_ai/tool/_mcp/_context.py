from contextlib import _AsyncGeneratorContextManager
from typing import TypeAlias

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage

MCPServerContext: TypeAlias = _AsyncGeneratorContextManager[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ],
]
