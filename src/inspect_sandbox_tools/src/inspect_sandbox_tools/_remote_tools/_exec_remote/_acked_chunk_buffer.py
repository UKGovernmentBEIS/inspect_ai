"""Ack-gated chunk buffer for reliable output transport.

Holds output chunks until the host confirms receipt, preventing data loss
when RPC responses are lost in transit.
"""

from typing import Generic, TypeVar

T = TypeVar("T")


class AckedChunkBuffer(Generic[T]):
    """Track held chunks and sequence numbers for reliable delivery.

    Two-step usage per RPC round-trip:

    1. ``push(chunk)`` — record new output.
    2. ``collect(ack_seq)`` — discard chunks the host has confirmed,
       return everything still unacked, each with its seq.

    Example — normal flow::

        sd = AckedChunkBuffer[str]()
        sd.push("A")
        sd.collect(0)  # [(1, "A")]
        sd.push("B")
        sd.collect(1)  # [(2, "B")]

    Example — retransmit (response lost)::

        sd = AckedChunkBuffer[str]()
        sd.push("A")
        sd.collect(0)  # [(1, "A")] — response lost
        sd.push("B")
        sd.collect(0)  # [(1, "A"), (2, "B")]
    """

    def __init__(self) -> None:
        self._seq: int = 0
        self._held: list[tuple[int, T]] = []  # (seq, chunk) pairs

    def push(self, chunk: T) -> None:
        """Append a chunk."""
        self._seq += 1
        self._held.append((self._seq, chunk))

    def collect(self, ack_seq: int) -> list[tuple[int, T]]:
        """Discard acked chunks and return what's left.

        Args:
            ack_seq: Host's last successfully received seq (0 = nothing received).

        Returns:
            Copy of the unacked ``(seq, chunk)`` pairs, in push order.
        """
        self._held = [(s, c) for s, c in self._held if s > ack_seq]
        return list(self._held)
