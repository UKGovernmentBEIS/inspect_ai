"""Restic binary acquisition for checkpointing.

The :func:`resolve_restic` coroutine returns a path to a usable restic
executable for a requested platform, downloading and caching it on demand.
See ``design/plans/checkpointing-working.md`` §4c for the design.
"""

from ._platform import Platform, current_platform
from ._resolver import resolve_restic

__all__ = ["Platform", "current_platform", "resolve_restic"]
