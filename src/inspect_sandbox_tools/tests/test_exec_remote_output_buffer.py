"""Unit tests for BoundedByteBuffer and DecodingBuffer."""

import asyncio

import pytest
from inspect_sandbox_tools._remote_tools._exec_remote._output_buffer import (
    BoundedByteBuffer,
    DecodingBuffer,
)


@pytest.mark.asyncio
async def test_small_output_no_blocking():
    buf = BoundedByteBuffer(max_bytes=100)
    await buf.put(b"hello")
    assert buf.drain() == b"hello"


@pytest.mark.asyncio
async def test_blocks_when_full():
    buf = BoundedByteBuffer(max_bytes=5)
    await buf.put(b"12345")
    # Buffer is full, next put should block
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(buf.put(b"x"), timeout=0.05)


@pytest.mark.asyncio
async def test_unblocks_after_drain():
    buf = BoundedByteBuffer(max_bytes=5)
    await buf.put(b"12345")
    buf.drain()
    # Should not block now
    await asyncio.wait_for(buf.put(b"x"), timeout=0.05)


@pytest.mark.asyncio
async def test_close_wakes_waiter():
    buf = BoundedByteBuffer(max_bytes=5)
    await buf.put(b"12345")

    woke = False

    async def waiter():
        nonlocal woke
        await buf.put(b"more")
        woke = True

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    assert not woke
    buf.close()
    await asyncio.wait_for(task, timeout=0.1)
    assert woke


@pytest.mark.asyncio
async def test_put_after_close_is_noop():
    buf = BoundedByteBuffer(max_bytes=100)
    await buf.put(b"before")
    buf.close()
    await buf.put(b"after")
    assert buf.drain() == b"before"


@pytest.mark.asyncio
async def test_preserves_all_data_under_limit():
    buf = BoundedByteBuffer(max_bytes=100)
    await buf.put(b"aaa")
    await buf.put(b"bbb")
    await buf.put(b"ccc")
    assert buf.drain() == b"aaabbbccc"


@pytest.mark.asyncio
async def test_drain_clears_buffer():
    buf = BoundedByteBuffer(max_bytes=100)
    await buf.put(b"hello")
    buf.drain()
    assert buf.drain() == b""


@pytest.mark.asyncio
async def test_empty_put_is_noop():
    buf = BoundedByteBuffer(max_bytes=10)
    await buf.put(b"")
    assert buf.drain() == b""


@pytest.mark.asyncio
async def test_empty_put_on_full_buffer_does_not_block():
    buf = BoundedByteBuffer(max_bytes=5)
    await buf.put(b"12345")
    await asyncio.wait_for(buf.put(b""), timeout=0.05)


def test_max_bytes_zero_raises():
    with pytest.raises(ValueError):
        BoundedByteBuffer(max_bytes=0)


def test_max_bytes_negative_raises():
    with pytest.raises(ValueError):
        BoundedByteBuffer(max_bytes=-1)


@pytest.mark.asyncio
async def test_decoding_buffer_splits_multibyte_across_drains():
    """A multi-byte UTF-8 character split across two drains decodes correctly."""
    buf = BoundedByteBuffer(max_bytes=100)
    dec = DecodingBuffer(buf)
    # "café!" = b"caf\xc3\xa9!" — split the é (\xc3\xa9) across two puts/drains
    await buf.put(b"caf\xc3")
    part1 = dec.drain()
    await buf.put(b"\xa9!")
    part2 = dec.drain(final=True)
    assert part1 + part2 == "café!"


@pytest.mark.asyncio
async def test_decoding_buffer_trailing_partial_on_final():
    """A trailing incomplete sequence produces a replacement character on final drain."""
    buf = BoundedByteBuffer(max_bytes=100)
    dec = DecodingBuffer(buf)
    await buf.put(b"hello\xc3")
    result = dec.drain(final=True)
    assert result == "hello\ufffd"
