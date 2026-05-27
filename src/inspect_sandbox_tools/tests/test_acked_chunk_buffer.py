"""Tests for AckedChunkBuffer — pure logic, no async, no mocks."""

from inspect_sandbox_tools._remote_tools._exec_remote._acked_chunk_buffer import (
    AckedChunkBuffer,
)


def test_first_delivery() -> None:
    sd = AckedChunkBuffer[str]()
    sd.push("A")
    seq, chunks = sd.collect(0)
    assert seq == 1
    assert chunks == ["A"]


def test_normal_ack_flow() -> None:
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    seq1, chunks1 = sd.collect(0)
    assert seq1 == 1
    assert chunks1 == ["A"]

    # Host acks seq 1
    sd.push("B")
    seq2, chunks2 = sd.collect(1)
    assert seq2 == 2
    assert chunks2 == ["B"]


def test_retransmit_prepends_held() -> None:
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    seq1, _ = sd.collect(0)
    assert seq1 == 1

    # Host did NOT receive seq 1, sends ack_seq=0 again
    sd.push("B")
    seq2, chunks2 = sd.collect(0)
    assert seq2 == 2
    assert chunks2 == ["A", "B"]


def test_multiple_retransmits_accumulate() -> None:
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    sd.collect(0)  # seq=1

    sd.push("B")
    sd.collect(0)  # seq=2, held=["A","B"]

    sd.push("C")
    seq3, chunks3 = sd.collect(0)  # seq=3, held=["A","B","C"]
    assert seq3 == 3
    assert chunks3 == ["A", "B", "C"]


def test_empty_chunk_on_retransmit() -> None:
    sd = AckedChunkBuffer[str]()

    sd.push("data")
    sd.collect(0)  # seq=1

    sd.push("")  # retransmit, no new data
    seq2, chunks2 = sd.collect(0)
    assert seq2 == 2
    assert chunks2 == ["data", ""]


def test_ack_seq_greater_than_seq_clears_all() -> None:
    """Defensive: ack_seq > _seq discards everything (future ack)."""
    sd = AckedChunkBuffer[str]()

    sd.push("A")
    sd.collect(0)  # seq=1

    # ack_seq=5 > _seq=2 — "B" at seq=2 is also acked
    sd.push("B")
    seq2, chunks2 = sd.collect(5)
    assert seq2 == 2
    assert chunks2 == []


def test_tuple_chunks() -> None:
    """Works with tuple chunks (e.g. stdout/stderr pairs)."""
    sd = AckedChunkBuffer[tuple[str, str]]()

    sd.push(("out1", "err1"))
    seq, chunks = sd.collect(0)
    assert seq == 1
    assert chunks == [("out1", "err1")]

    # Retransmit
    sd.push(("out2", "err2"))
    seq2, chunks2 = sd.collect(0)
    assert seq2 == 2
    assert chunks2 == [("out1", "err1"), ("out2", "err2")]


def test_dict_chunks() -> None:
    """Works with dict chunks."""
    sd = AckedChunkBuffer[dict[str, int]]()
    sd.push({"a": 1})
    seq, chunks = sd.collect(0)
    assert seq == 1
    assert chunks == [{"a": 1}]


def test_ack_then_retransmit_then_ack() -> None:
    """Full cycle: normal -> lost -> retransmit -> ack."""
    sd = AckedChunkBuffer[str]()

    # Normal
    sd.push("A")
    sd.collect(0)  # seq=1

    sd.push("B")
    sd.collect(1)  # seq=2, acked 1

    # Response for seq=2 lost
    sd.push("C")
    sd.collect(1)  # seq=3, held=["B","C"]

    # Host finally acks seq=3
    sd.push("D")
    seq4, chunks4 = sd.collect(3)
    assert seq4 == 4
    assert chunks4 == ["D"]


def test_returned_list_is_a_copy() -> None:
    """Returned chunks list should be independent of internal state."""
    sd = AckedChunkBuffer[str]()
    sd.push("A")
    _, chunks = sd.collect(0)
    chunks.append("mutated")

    # Internal state should be unaffected
    sd.push("B")
    _, chunks2 = sd.collect(0)
    assert chunks2 == ["A", "B"]
