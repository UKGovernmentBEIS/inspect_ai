"""Textual widgets for the Phase 2 conversation pane.

Each widget is driven by :mod:`inspect_ai.agent._acp._tui._state` —
they read snapshots of ``SessionState`` and update on its subscribe
callback. No widget touches the wire directly.
"""

from ._message import MessageWidget
from ._status_row import StatusRowWidget
from ._tool_call import ToolCallWidget
from ._transcript import TranscriptWidget

__all__ = [
    "MessageWidget",
    "StatusRowWidget",
    "ToolCallWidget",
    "TranscriptWidget",
]
