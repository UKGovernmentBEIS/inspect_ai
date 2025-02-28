from __future__ import annotations


class Rectangle:
    def __init__(self, left: float, top: float, width: float, height: float):
        self._left = int(left)
        self._width = int(width)
        self._top = int(top)
        self._height = int(height)

    @classmethod
    def _from_left_right_top_bottom(
        cls, left: float, right: float, top: float, bottom: float
    ) -> Rectangle:
        return cls(left, top, right - left, bottom - top)

    @property
    def _right(self) -> int:
        return self._left + self._width

    @property
    def _bottom(self) -> int:
        return self._top + self._height

    @property
    def center_x(self) -> int:
        return self._left + self._width // 2

    @property
    def center_y(self) -> int:
        return self._top + self._height // 2

    @property
    def has_area(self) -> bool:
        return self._width > 0 and self._height > 0

    def __str__(self) -> str:
        return f"({self._left}, {self._top}, {self._width}, {self._height})"

    def scale(self, scale: float) -> Rectangle:
        return self._from_left_right_top_bottom(
            self._left * scale,
            self._right * scale,
            self._top * scale,
            self._bottom * scale,
        )

    def overlaps(self, other: Rectangle) -> bool:
        """Returns if the two rectangles intersect."""
        return (
            other._left < self._right  # pylint: disable=protected-access
            and other._right > self._left  # pylint: disable=protected-access
            and other._top < self._bottom  # pylint: disable=protected-access
            and other._bottom > self._top  # pylint: disable=protected-access
        )

    def within(self, other: Rectangle) -> bool:
        """Returns if this rectangle is within the other rectangle."""
        return (
            other._left <= self._left  # pylint: disable=protected-access
            and other._right >= self._left  # pylint: disable=protected-access
            and other._top <= self._bottom  # pylint: disable=protected-access
            and other._bottom >= self._top  # pylint: disable=protected-access
        )
