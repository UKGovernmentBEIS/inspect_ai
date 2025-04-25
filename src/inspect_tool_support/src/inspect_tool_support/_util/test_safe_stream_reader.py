import asyncio
from typing import cast

import pytest

from inspect_tool_support._util.safe_stream_reader import SafeStreamReader


@pytest.mark.asyncio
async def test_split_utf8():
    processor = StreamProcessor([b"Juan Per\xc3", b"\xb3n"])
    await processor.process_stream()
    assert processor.decoded_result == "Juan Perón"


@pytest.mark.asyncio
async def test_malformed_utf8():
    """Test with real-world malformed UTF-8 data."""
    processor = StreamProcessor([b"Juan Per\xc2\xc3\xb3\xc3n"])
    await processor.process_stream()
    assert processor.decoded_result == "Juan Per�ó�n"


@pytest.mark.asyncio
async def test_bogus_at_end():
    processor = StreamProcessor([b"Juan Per\xc3"])

    with pytest.raises(UnicodeDecodeError) as exception_info:
        await processor.process_stream()
    assert "Incomplete UTF-8 sequence at end of stream" in str(exception_info.value)
    assert processor.decoded_result == "Juan Per"


@pytest.mark.asyncio
async def test_empty_stream():
    """Test with an empty stream to ensure proper handling of no data."""
    processor = StreamProcessor([])
    await processor.process_stream()
    assert processor.decoded_result == ""


@pytest.mark.asyncio
async def test_large_chunks():
    """Test with large data chunks to verify performance with bigger payloads."""
    large_chunk = b"x" * 1024 * 1024  # 1MB chunk
    processor = StreamProcessor([large_chunk, large_chunk])
    await processor.process_stream()
    assert len(processor.decoded_result) == 2 * 1024 * 1024


@pytest.mark.asyncio
async def test_many_chunks():
    """Test with many small chunks to ensure proper handling of numerous reads."""
    small_chunks = [b"chunk" for _ in range(100)]
    processor = StreamProcessor(small_chunks)
    await processor.process_stream()
    assert processor.decoded_result == "chunk" * 100


@pytest.mark.asyncio
async def test_mixed_encoding():
    """Test with a mix of ASCII and multi-byte UTF-8 characters."""
    processor = StreamProcessor(
        [
            b"ASCII text ",
            b"\xe4\xb8\xad\xe6\x96\x87 ",  # Chinese characters
            b"\xd8\xb9\xd8\xb1\xd8\xa8\xd9\x8a ",  # Arabic characters
            b"\xe0\xa4\xb9\xe0\xa4\xbf\xe0\xa4\xa8\xe0\xa5\x8d\xe0\xa4\xa6\xe0\xa5\x80",  # Hindi characters
        ]
    )
    await processor.process_stream()
    assert "ASCII text 中文 عربي हिन्दी" == processor.decoded_result


@pytest.mark.asyncio
async def test_error_handling():
    """Test error handling during stream processing."""

    class ErrorProcessor(StreamProcessor):
        async def read(self, _chunk_size):
            self.read_complete.set()  # Make sure to set this so wait_until_complete() doesn't hang
            # Simulate an error during reading
            raise IOError("Simulated read error")

    processor = ErrorProcessor([b"data"])

    with pytest.raises(IOError) as exception_info:
        await processor.process_stream()

    assert "Simulated read error" in str(exception_info.value)


class StreamProcessor:
    def __init__(self, test_chunks: list[bytes]):
        self.received_data: list[bytes] = []
        self.test_chunks = test_chunks
        # MockStreamReader data
        self.index = 0
        self.read_complete = asyncio.Event()

    def _on_data(self, data: bytes):
        self.received_data.append(data)

    async def read(self, _chunk_size):
        """Mock stream read method that returns chunks sequentially."""
        if self.index < len(self.test_chunks):
            chunk = self.test_chunks[self.index]
            self.index += 1
            if self.index >= len(self.test_chunks):
                self.read_complete.set()
            return chunk
        self.read_complete.set()
        return b""  # EOF

    async def wait_until_complete(self) -> None:
        await self.read_complete.wait()

    async def process_stream(self) -> None:
        reader = SafeStreamReader(cast(asyncio.StreamReader, self), self._on_data)

        await self.wait_until_complete()
        await reader.stop()

    @property
    def decoded_result(self) -> str:
        return b"".join(self.received_data).decode("utf-8")
