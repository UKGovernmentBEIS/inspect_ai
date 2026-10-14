"""Re-export of :class:`enum.StrEnum`.

``inspect_ai.util.StrEnum is enum.StrEnum``, so user-defined
``enum.StrEnum`` subclasses pass ``issubclass(..., StrEnum)`` checks.
"""

from enum import StrEnum as StrEnum

__all__ = ["StrEnum"]
