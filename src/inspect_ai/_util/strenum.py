"""Backport of :class:`enum.StrEnum` for Python 3.10.

On 3.11+ this re-exports the stdlib class so that
``inspect_ai.scorer.StrEnum is enum.StrEnum`` and user-defined
``enum.StrEnum`` subclasses pass ``issubclass(..., StrEnum)`` checks.

The 3.10 fallback mirrors the CPython implementation: ``StrEnum`` inherits
from ``(str, ReprEnum)`` and the enum metaclass wires ``__str__``/
``__format__`` to ``str``'s methods for ``ReprEnum`` subclasses. ``ReprEnum``
does not exist on 3.10, so we set those explicitly here — without them,
``str(member)`` on a ``(str, Enum)`` mixin yields ``"Class.MEMBER"`` rather
than the value.
"""

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum as StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Enum where members are also (and must be) strings."""

        def __new__(cls, *values: object) -> "StrEnum":
            if len(values) > 3:
                raise TypeError(f"too many arguments for str(): {values!r}")
            if len(values) >= 1 and not isinstance(values[0], str):
                raise TypeError(f"{values[0]!r} is not a string")
            if len(values) >= 2 and not isinstance(values[1], str):
                raise TypeError(f"encoding must be a string, not {values[1]!r}")
            if len(values) == 3 and not isinstance(values[2], str):
                raise TypeError(f"errors must be a string, not {values[2]!r}")
            value = str(*values)
            member = str.__new__(cls, value)
            member._value_ = value
            return member

        __str__ = str.__str__
        __format__ = str.__format__

        @staticmethod
        def _generate_next_value_(  # type: ignore[override]
            name: str, start: int, count: int, last_values: list[str]
        ) -> str:
            return name.lower()


__all__ = ["StrEnum"]
