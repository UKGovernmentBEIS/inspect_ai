# Sentinel class used until PEP 0661 is accepted
from typing import Literal

from typing_extensions import override


class NotGiven:
    """A sentinel singleton class used to distinguish omitted keyword arguments from those passed in with the value None (which may have different behavior)."""

    def __bool__(self) -> Literal[False]:
        return False

    @override
    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = NotGiven()
