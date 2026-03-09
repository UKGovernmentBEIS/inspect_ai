"""Bounded output buffer with circular and backpressure modes."""

import asyncio
from collections import deque


class _OutputBuffer:
    """Buffer for subprocess output with configurable overflow behavior.

    Two modes:
    - circular=True: Keeps the most recent max_bytes (tail preservation).
      Used for stream=False where client wants bounded output.
    - circular=False: Backpressure mode. Accumulates data up to max_bytes,
      then signals full. Caller must await wait_for_space() before writing
      more. Used for stream=True where all data should flow through.
    """

    def __init__(self, max_bytes: int, circular: bool) -> None:
        self._max_bytes = max_bytes
        self._circular = circular
        self._chunks: deque[bytes] = deque()
        self._total_bytes = 0
        self._has_space = asyncio.Event()
        self._has_space.set()

    def write(self, data: bytes) -> None:
        """Append data to the buffer."""
        if not data:
            return
        self._chunks.append(data)
        self._total_bytes += len(data)

        if self._circular:
            # Drop oldest full chunks until we fit
            while self._total_bytes > self._max_bytes and len(self._chunks) > 1:
                removed = self._chunks.popleft()
                self._total_bytes -= len(removed)
            # Trim the front of the remaining first chunk if still over
            if self._total_bytes > self._max_bytes and self._chunks:
                excess = self._total_bytes - self._max_bytes
                self._chunks[0] = self._chunks[0][excess:]
                self._total_bytes = self._max_bytes
        else:
            if self._total_bytes >= self._max_bytes:
                self._has_space.clear()

    async def wait_for_space(self) -> None:
        """Block until buffer has space (backpressure mode only).

        In circular mode this returns immediately.
        """
        if self._circular:
            return
        await self._has_space.wait()

    def drain(self) -> str:
        """Return all buffered data as a string and clear the buffer."""
        if not self._chunks:
            return ""
        result = b"".join(self._chunks).decode("utf-8", errors="replace")
        self._chunks.clear()
        self._total_bytes = 0
        if not self._circular:
            self._has_space.set()
        return result

    def unblock(self) -> None:
        """Manually signal that space is available (e.g. on process exit)."""
        self._has_space.set()
