"""Textual widgets for the Phase 2 conversation pane.

Each widget is driven by :mod:`inspect_ai.agent._acp.tui.state` —
they read snapshots of ``SessionState`` and update on its subscribe
callback. No widget touches the wire directly.
"""

from .footer import AppFooter
from .header import AppHeaderWidget, SessionHeaderWidget
from .message import MessageWidget
from .plan import PlanStripWidget
from .tool_call import ToolCallWidget
from .transcript import TranscriptWidget

__all__ = [
    "AppFooter",
    "AppHeaderWidget",
    "MessageWidget",
    "PlanStripWidget",
    "SessionHeaderWidget",
    "ToolCallWidget",
    "TranscriptWidget",
]
