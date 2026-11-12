"""Tests for AckedChunkBuffer — pure logic, no async, no mocks."""

from inspect_sandbox_tools._remote_tools._exec_remote._acked_chunk_buffer import (
    AckedChunkBuffer,
)


def test_first_delivery() -> None:
    sd = AckedChunkBuffer[str]()
    sd.push("A")
    assert sd.collect(0) == [(1, "A")]


def test_normal_ack_flow() -> None:
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    assert sd.collect(0) == [(1, "A")]

    # Host acks seq 1
    sd.push("B")
    assert sd.collect(1) == [(2, "B")]


def test_retransmit_prepends_held() -> None:
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    sd.collect(0)

    # Host did NOT receive seq 1, sends ack_seq=0 again
    sd.push("B")
    assert sd.collect(0) == [(1, "A"), (2, "B")]


def test_multiple_retransmits_accumulate() -> None:
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    sd.collect(0)

    sd.push("B")
    sd.collect(0)

    sd.push("C")
    assert sd.collect(0) == [(1, "A"), (2, "B"), (3, "C")]


def test_ack_seq_greater_than_seq_clears_all() -> None:
    """Defensive: ack_seq > _seq discards everything (future ack)."""
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    sd.collect(0)

    # ack_seq=5 > _seq=2 — "B" at seq=2 is also acked
    sd.push("B")
    assert sd.collect(5) == []


def test_tuple_chunks() -> None:
    """Works with tuple chunks (e.g. stdout/stderr pairs)."""
    sd = AckedChunkBuffer[tuple[str, str]]()

    sd.push(("out1", "err1"))
    assert sd.collect(0) == [(1, ("out1", "err1"))]

    # Retransmit
    sd.push(("out2", "err2"))
    assert sd.collect(0) == [(1, ("out1", "err1")), (2, ("out2", "err2"))]


def test_ack_then_retransmit_then_ack() -> None:
    """Full cycle: normal -> lost -> retransmit -> ack."""
    sd = AckedChunkBuffer[str]()

    # Normal
    sd.push("A")
    sd.collect(0)

    sd.push("B")
    sd.collect(1)  # acked 1

    # Response for seq=2 lost
    sd.push("C")
    assert sd.collect(1) == [(2, "B"), (3, "C")]

    # Host finally acks seq=3
    sd.push("D")
    assert sd.collect(3) == [(4, "D")]


def test_returned_list_is_a_copy() -> None:
    """Returned chunks list should be independent of internal state."""
    sd = AckedChunkBuffer[str]()
    sd.push("A")
    chunks = sd.collect(0)
    chunks.append((99, "mutated"))

    # Internal state should be unaffected
    sd.push("B")
    assert sd.collect(0) == [(1, "A"), (2, "B")]
