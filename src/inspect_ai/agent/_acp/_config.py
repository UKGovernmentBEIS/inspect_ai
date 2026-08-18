"""ACP transport / runtime configuration constants.

Single home for module-level numeric / wire-side knobs the ACP
subsystem reads in multiple places. Keep this small — values here
should describe *contracts* (e.g. wire buffer limits applied
identically on both sides) rather than tunable behavior.
"""

from __future__ import annotations

from typing import Final

# Buffer size for ``asyncio.StreamReader``s on every ACP socket — server
# accept side, TUI client connect side, and the stdio bridge in both
# directions. Asyncio's default is 64 KiB; ``readline()`` raises
# :class:`asyncio.LimitOverrunError` if a single line exceeds the limit
# without finding the delimiter, which crashes the receive loop and
# silently drops the message.
#
# 64 KiB is fine for tiny editor RPC messages but catastrophic for
# Inspect's transcript firehose: a single ``ScoreEvent`` from a
# swe-bench-style scorer can carry a 500 KB explanation (test stdout
# / stderr captured verbatim into ``Score.explanation``). When that
# message hits the TUI's reader, the receive loop dies, the
# connection breaks, and the operator's UI is left frozen on
# ``scoring · X…`` because the matching score chip never arrived.
#
# 64 MiB is the cap because it's two orders of magnitude past what
# we've seen in the wild and well below any realistic memory
# pressure. If a single ACP message exceeds 64 MiB we have a bigger
# problem than the receive-loop crash.
ACP_STREAM_BUFFER_LIMIT: Final[int] = 64 * 1024 * 1024
