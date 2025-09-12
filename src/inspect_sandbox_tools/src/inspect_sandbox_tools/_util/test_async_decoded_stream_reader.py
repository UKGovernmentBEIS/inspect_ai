import asyncio
import os
from unittest.mock import Mock, patch

import pytest

from .async_decoded_stream_reader import AsyncDecodedStreamReader


@pytest.mark.asyncio
async def test_read_simple_data():
    """Test reading simple ASCII data."""
    async with FDPipeReader() as (reader, write_pipe):
        test_data = b"Trudging across the tundra. Mile after mile."
        write_pipe.write(test_data)
        write_pipe.close_write()  # Close the write end to signal EOF
        result = await reader.read()
        assert result == "Trudging across the tundra. Mile after mile."


@pytest.mark.asyncio
async def test_read_utf8_data():
    """Test reading UTF-8 encoded data with multi-byte characters."""
    async with FDPipeReader() as (reader, write_pipe):
        test_data = "Hi café हाँ! 👨‍👩‍👧‍👦 apple аррӏе".encode("utf-8")
        write_pipe.write(test_data)
        write_pipe.close_write()
        result = await reader.read()
        assert result == "Hi café हाँ! 👨‍👩‍👧‍👦 apple аррӏе"


@pytest.mark.asyncio
async def test_incremental_reading():
    """Test reading data in multiple chunks."""
    async with FDPipeReader() as (reader, write_pipe):

        async def write_data():
            write_pipe.write(b"First ")
            await asyncio.sleep(0.1)
            write_pipe.write(b"Second ")
            await asyncio.sleep(0.1)
            write_pipe.write(b"Third")
            write_pipe.close_write()

        write_task = asyncio.create_task(write_data())

        first_chunk = await reader.read(6)
        assert first_chunk == "First "

        rest = await reader.read()
        assert rest == "Second Third"

        await write_task


@pytest.mark.asyncio
async def test_split_utf8_character():
    """Test handling a UTF-8 character that's split across multiple reads."""
    async with FDPipeReader() as (reader, write_pipe):
        write_pipe.write(b"Juan Per\xc3")

        # Read the first - it should omit the \xc3 since it's an incomplete character
        first_result = await asyncio.wait_for(reader.read(100), 0.5)
        assert first_result == "Juan Per"

        write_pipe.write(b"\xb3n")
        write_pipe.close_write()

        # Now we should get the rest
        second_result = await reader.read()
        assert second_result == "ón"


@pytest.mark.asyncio
async def test_malformed_utf8():
    """Test handling malformed UTF-8 data."""
    async with FDPipeReader() as (reader, pipe):
        test_data = b"Juan Per\xc2\xc3\xb3\xc3n"
        pipe.write(test_data)
        pipe.close_write()
        result = await reader.read()
        assert result == "Juan Per�ó�n"


def test_close():
    """Test proper cleanup when close() is called."""
    mock_reader = Mock()
    mock_transport = Mock()
    reader = AsyncDecodedStreamReader(
        reader=mock_reader,
        read_transport=mock_transport,
        encoding="utf-8",
    )
    reader.close()
    mock_transport.close.assert_called_once()


@pytest.mark.asyncio
@patch("asyncio.get_event_loop")
async def test_resource_management(mock_get_loop):
    """Test that resources are properly managed during creation and cleanup."""
    mock_loop = Mock()
    mock_get_loop.return_value = mock_loop
    mock_transport = Mock()
    mock_protocol = Mock()
    future = asyncio.Future()
    future.set_result((mock_transport, mock_protocol))
    mock_loop.connect_read_pipe.return_value = future

    # Use the context manager approach
    async with await AsyncDecodedStreamReader.create(1):
        pass  # Resources will be automatically cleaned up

    mock_loop.connect_read_pipe.assert_called_once()


@pytest.mark.asyncio
async def test_context_manager_open():
    """Test using AsyncDecodedStreamReader.open as an async context manager."""
    read_fd, write_fd = os.pipe()

    try:
        # Use the open method which is explicitly designed for context manager usage
        async with await AsyncDecodedStreamReader.open(read_fd) as reader:
            test_data = b"Context manager test"
            os.write(write_fd, test_data)
            os.close(write_fd)

            result = await reader.read()
            assert result == "Context manager test"
        # Reader should be automatically closed here
    finally:
        # Clean up file descriptors if anything went wrong
        try:
            os.close(read_fd)
        except OSError:
            pass
        try:
            os.close(write_fd)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_direct_context_manager():
    """Test using AsyncDecodedStreamReader instance directly as an async context manager."""
    read_fd, write_fd = os.pipe()

    try:
        # Create the reader first, then use it as a context manager
        reader = await AsyncDecodedStreamReader.create(read_fd)
        async with reader:
            test_data = b"Direct context manager"
            os.write(write_fd, test_data)
            os.close(write_fd)

            result = await reader.read()
            assert result == "Direct context manager"
        # Reader should be automatically closed here
    finally:
        # Clean up file descriptors if anything went wrong
        try:
            os.close(read_fd)
        except OSError:
            pass
        try:
            os.close(write_fd)
        except OSError:
            pass


class FDPipeReader:
    """Helper class for testing AsyncDecodedStreamReader with pipes.

    This class is an async context manager that automatically sets up and tears down
    pipes for testing AsyncDecodedStreamReader.

    Usage:
        async with FDPipeReader() as (reader, write_pipe):
            # Write to the pipe
            write_pipe.write(b"data")
            write_pipe.close_write()

            # Read from the reader
            result = await reader.read()
            assert result == "data"
    """

    def __init__(self):
        self.read_fd, self.write_fd = os.pipe()
        self.reader = None
        self.reader_ctx = None

    async def __aenter__(self):
        # Use the reader as a context manager
        self.reader_ctx = await AsyncDecodedStreamReader.create(self.read_fd)
        self.reader = (
            self.reader_ctx
        )  # They are the same object, but helps clarify intent
        return self.reader, self  # Return both the reader and self as the pipe

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def write(self, data):
        """Write data to the pipe."""
        os.write(self.write_fd, data)

    def close_write(self):
        """Close the write end of the pipe to signal EOF."""
        os.close(self.write_fd)

    def cleanup(self):
        """Clean up all resources."""
        if self.reader:
            self.reader.close()
            self.reader = None
        try:
            os.close(self.read_fd)
        except OSError:
            pass
        try:
            os.close(self.write_fd)
        except OSError:
            pass
