"""Textual TUI client for ``inspect acp``.

Phase 1 — attach plumbing only. See
``design/acp/agent-acp-tui.md`` for the full phasing.
"""

from ._app import InspectAcpApp, run_tui

__all__ = ["InspectAcpApp", "run_tui"]
