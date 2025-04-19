import asyncio
from typing import Callable


class SafeStreamReader:
    """
    A class that safely reads from an asyncio stream, handling incomplete UTF-8 sequences and providing updates through a callback mechanism.

    This reader processes data as soon as it's available from the stream.
    """

    def __init__(
        self,
        stream: asyncio.StreamReader,
        on_data: Callable[[bytes], None],
        chunk_size: int = 4096,
    ):
        """
        Initialize a SafeStreamReader.

        It safely reads from an asyncio stream, handling incomplete UTF-8
        sequences and providing updates through a callback mechanism.

        Args:
            stream: The asyncio.StreamReader to read from
            on_data: Callback that will be called with the data buffer whenever
              new complete data is available
            chunk_size: Maximum size of chunks to read from the stream
        """
        self._stream = stream
        self._on_data = on_data
        self._chunk_size = chunk_size
        self._incomplete: bytes | None = None
        self._read_task = asyncio.create_task(self._read_loop())
        self._stopping = False

    async def stop(self) -> None:
        if self._read_task:
            self._stopping = True
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

    async def _read_loop(self) -> None:
        while not self._stopping:
            # Read available data - this will return as soon as any data is available
            # up to the maximum chunk_size
            chunk = await self._stream.read(self._chunk_size)
            if self._stopping:
                break

            if not chunk:  # EOF
                if self._incomplete:
                    raise UnicodeDecodeError(
                        "utf-8",
                        self._incomplete,
                        0,
                        len(self._incomplete),
                        "Incomplete UTF-8 sequence at end of stream",
                    )
                break

            data: bytes
            if self._incomplete:
                # Handle any incomplete sequences from previous reads
                data = self._incomplete + chunk
                self._incomplete = None
            else:
                data = chunk

            self._process_data(data)

    def _process_data(self, data: bytes) -> None:
        """
        Process the accumulated data, handling incomplete UTF-8 sequences.

        Calls the on_data callback.
        """
        try:
            # Attempt a decode just to detect a break in the middle of a UTF-8 sequence
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            # Keep only valid bytes in data moving the bogus data into _incomplete
            valid_bytes = e.start
            self._incomplete = data[valid_bytes:]
            data = data[:valid_bytes]

        # Call the callback with the processed data if provided
        if len(data) > 0:
            self._on_data(data)
