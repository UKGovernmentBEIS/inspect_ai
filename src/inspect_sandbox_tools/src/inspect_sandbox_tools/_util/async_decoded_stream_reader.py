import asyncio
import codecs
import os
from types import TracebackType
from typing import AsyncContextManager, Optional, Type


class AsyncDecodedStreamReader:
    """Encapsulates reading decoded text from a pipe/socket using `asyncio`.

    This class is necessary when the consumer needs to read textual data from an
    FD that refers to a pipe/socket as opposed to an actual file. This is because
    `asyncio`'s transport layer requires binary which prevents simply opening
    the FD in text mode.

    With pipe/socket file descriptors (as opposed to regular files), data arrives
    in chunks of arbitrary size that don't respect character boundaries. UTF-8
    characters can be split across read operations, requiring the incremental
    decoder to buffer partial character bytes until a complete character can be
    decoded.

    This class sets up the stack that turns a file descriptor into a decoder:
    - StreamReader: High-level interface for reading data asynchronously
    - StreamReaderProtocol: Bridge between transport and StreamReader
    - ReadTransport: Low-level component for I/O operations on the fd
    - Incremental Decoder: Handles decoding with proper split character handling

    Methods:
        create(fd: int, encoding: str = "utf-8"): Class method to create an
            instance from a file descriptor
        open(fd: int, encoding: str = "utf-8"): Class method to create an
            instance for use as an async context manager
        read(n: int = -1): Read and decode data from the file descriptor
        close(): Release all resources

    The class also implements the AsyncContextManager protocol and can be used
    with async with:
        async with AsyncDecodedStreamReader.open(fd) as reader:
            data = await reader.read()
    """

    @classmethod
    async def create(
        cls,
        fd: int,
        encoding: str = "utf-8",
    ) -> "AsyncDecodedStreamReader":
        """Create a AsyncDecodedStreamReader from a file descriptor.

        Args:
            fd: The file descriptor to read from.
            encoding: The character encoding to use for decoding the bytes read
              from the file descriptor. Default is 'utf-8'.

        Returns:
            A AsyncDecodedStreamReader instance configured to read from the given
            file descriptor.

        Note:
            The caller is responsible for calling close() when done with the
            reader.
            If you prefer automatic resource management, use the open() method
            instead with an async context manager.

        Example:
            ```python
            reader = await AsyncDecodedStreamReader.create(fd)
            try:
                data = await reader.read()
            finally:
                reader.close()
            ```
        """
        reader = asyncio.StreamReader()
        read_transport, _ = await asyncio.get_event_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(os.dup(fd), "rb")
        )

        return cls(reader=reader, read_transport=read_transport, encoding=encoding)

    @classmethod
    async def open(
        cls,
        fd: int,
        encoding: str = "utf-8",
    ) -> AsyncContextManager["AsyncDecodedStreamReader"]:
        """Create a AsyncDecodedStreamReader from a file descriptor for use with async context manager.

        Args:
            fd: The file descriptor to read from.
            encoding: The character encoding to use for decoding the bytes read
              from the file descriptor. Default is 'utf-8'.

        Returns:
            A AsyncDecodedStreamReader instance that can be used with async with.
            The reader will be automatically closed when the context is exited.

        Example:
            ```python
            async with AsyncDecodedStreamReader.open(fd) as reader:
                data = await reader.read()
            # Reader is automatically closed here
            ```
        """
        return await cls.create(fd, encoding)

    def __init__(
        self,
        reader: asyncio.StreamReader,
        read_transport: asyncio.ReadTransport,
        encoding: str,
    ) -> None:
        self._reader = reader
        self._read_transport = read_transport
        self._decoder = codecs.getincrementaldecoder(encoding)(errors="replace")

    async def read(self, n=-1) -> str:
        """Read and decode data from the file descriptor using the specified encoding.

        Args:
            n: Maximum number of bytes to read. If n is negative or omitted,
               read until EOF is reached.

        Returns:
            Decoded string from the read bytes using the encoding specified during initialization.
        """
        return self._decoder.decode(await self._reader.read(n))

    def close(self) -> None:
        """Release all resources.

        This closes the transport (which will close the duplicated file descriptor internally) and resets the decoder.
        """
        self._read_transport.close()
        self._decoder.reset()

    # Async context manager protocol implementation
    async def __aenter__(self) -> "AsyncDecodedStreamReader":
        """Enter the async context and return self."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Exit the async context and close resources."""
        self.close()
