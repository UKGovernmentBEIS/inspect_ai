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
        self._stopping = False
        self._exception: Exception | None = None
        self._read_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        if self._read_task:
            self._stopping = True
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

            # Re-raise any exception that occurred during reading
            if self._exception:
                raise self._exception

    async def _read_loop(self) -> None:
        try:
            while not self._stopping:
                # Read available data - this will return as soon as any data is available
                # up to the maximum chunk_size
                try:
                    chunk = await self._stream.read(self._chunk_size)
                except Exception as e:
                    # Capture and store the exception
                    self._exception = e
                    # Break out of the loop to stop reading
                    break

                if self._stopping:
                    break

                if not chunk:  # EOF
                    if self._incomplete:
                        self._exception = UnicodeDecodeError(
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
        except Exception as e:
            # Catch any other exceptions in the read loop
            self._exception = e

    def _process_data(self, data: bytes) -> None:
        """
        Process the accumulated data, handling incomplete UTF-8 sequences.

        Calls the on_data callback.
        """
        try:
            # Try strict decode first
            data.decode("utf-8")
            # If successful, process all data
            if len(data) > 0:
                self._on_data(data)
            return
        except UnicodeDecodeError as e:
            # Decode failed - try with replacement
            decoded = data.decode("utf-8", errors="replace")

            # Check if the last character is a replacement character
            if decoded and decoded[-1] != "�":
                # If the last char is not a replacement, all errors are in the middle
                # We can safely use the entire data with replacements
                if len(data) > 0:
                    self._on_data(decoded.encode("utf-8"))
            else:
                # The error is at the end, so keep only valid bytes in data
                # moving the bogus data into _incomplete
                valid_bytes = e.start
                self._incomplete = data[valid_bytes:]
                data = data[:valid_bytes]
                self._on_data(data)
