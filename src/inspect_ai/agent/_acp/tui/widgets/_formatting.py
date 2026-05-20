"""Shared formatters + visual constants for the TUI widgets.

Single source of truth for the few presentation helpers that show up
in more than one widget — keeps duration / token formatting consistent
across the picker, header chips, and event cards, and avoids three
slightly different copies of the same Braille spinner.
"""

from __future__ import annotations

import time

# Braille spinner — ten frames is enough for smooth motion without
# strobing. Used by the assistant chip in MessageWidget and the
# in-flight footer in ToolCallWidget so both surfaces animate in sync.
SPINNER_FRAMES: tuple[str, ...] = (
    "⠋",
    "⠙",
    "⠹",
    "⠸",
    "⠼",
    "⠴",
    "⠦",
    "⠧",
    "⠇",
    "⠏",
)


def format_duration(seconds: float | None) -> str:
    """Compact wall-clock duration: ``0.2s`` / ``12s`` / ``3m 04s`` / ``1h 02m``.

    Sub-second values carry one decimal so tool-call footers (where
    most durations land) don't all read as ``0s``. Higher units drop
    to whole-second / whole-minute precision so the column stays
    narrow in the picker and the chip stays compact in the card.
    """
    if seconds is None:
        return "—"
    if seconds < 1.0:
        return f"{seconds:.1f}s"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        m, s = divmod(total, 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m:02d}m"


def format_running(started_at: float | None, now: float | None = None) -> str:
    """Elapsed time since ``started_at`` — whole-second granularity.

    Distinct from :func:`format_duration` only in the sub-second case:
    the picker's ``running`` column shows ``0s`` rather than ``0.0s``
    because samples always run for ≥ 1s in practice and the decimal
    is visual noise. Tool-call cards (millisecond completions) use
    :func:`format_duration` directly so they keep the sub-second
    floor.

    ``now`` is parametrised so the picker's per-tick column refresh
    passes a single ``time.time()`` snapshot for all rows (consistent
    elapsed values across the table on each tick).
    """
    if started_at is None:
        return "—"
    elapsed = (now if now is not None else time.time()) - started_at
    if elapsed < 1.0:
        return "0s"
    return format_duration(elapsed)


def format_tokens(n: int) -> str:
    """Pretty-format token counts with K / M / B suffixes.

    Token totals routinely cross the million mark on long agent runs;
    a literal ``1234567`` is hard to scan in a narrow column. One
    decimal for under-10 values (``1.2K``, ``9.9M``); whole numbers
    above that. Trailing ``.0`` trimmed so ``1000`` reads as ``1K``.

    Zero collapses to ``—`` (em-dash) so the picker doesn't show a
    bare ``0`` for samples that haven't generated any model output
    yet — visually distinguishes "no data" from "small but non-zero".
    """
    if n == 0:
        return "—"
    if n < 1_000:
        return str(n)
    for unit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= unit:
            value = n / unit
            text = f"{value:.1f}" if value < 10 else f"{value:.0f}"
            if text.endswith(".0"):
                text = text[:-2]
            return f"{text}{suffix}"
    return str(n)  # unreachable; keeps mypy happy
