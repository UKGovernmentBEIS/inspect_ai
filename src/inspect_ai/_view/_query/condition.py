from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Union

from pydantic import BaseModel, Field

# Scalar values that can be used in conditions
ScalarValue = str | int | float | bool | datetime | date | None


class Operator(Enum):
    """SQL comparison operators."""

    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"
    NOT_LIKE = "NOT LIKE"
    ILIKE = "ILIKE"  # PostgreSQL case-insensitive LIKE
    NOT_ILIKE = "NOT ILIKE"  # PostgreSQL case-insensitive NOT LIKE
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    BETWEEN = "BETWEEN"
    NOT_BETWEEN = "NOT BETWEEN"


class LogicalOperator(Enum):
    """Logical operators for combining conditions."""

    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class Condition(BaseModel):
    """WHERE clause condition that can be combined with others."""

    left: Union[str, "Condition", None] = Field(default=None)
    """Column name (simple) or left operand (compound)."""

    operator: Union[Operator, LogicalOperator, None] = Field(default=None)
    """Comparison operator (simple) or logical operator (compound)."""

    right: Union[
        "Condition",
        list[ScalarValue],
        tuple[ScalarValue, ScalarValue],
        ScalarValue,
    ] = Field(default=None)
    """Comparison value (simple) or right operand (compound)."""

    is_compound: bool = Field(default=False)
    """True for AND/OR/NOT conditions, False for simple comparisons."""

    @property
    def params(self) -> list[ScalarValue]:
        """SQL parameters extracted from the condition for parameterized queries."""
        if self.is_compound or self.operator in (
            Operator.IS_NULL,
            Operator.IS_NOT_NULL,
        ):
            return []
        if self.operator in (Operator.IN, Operator.NOT_IN):
            return list(self.right) if isinstance(self.right, list) else []
        if self.operator in (Operator.BETWEEN, Operator.NOT_BETWEEN):
            if isinstance(self.right, (tuple, list)) and len(self.right) >= 2:
                return [self.right[0], self.right[1]]
            return []
        if self.right is not None and not isinstance(
            self.right, (Condition, list, tuple)
        ):
            return [self.right]
        return []

    def __and__(self, other: Condition) -> Condition:
        """Combine conditions with AND."""
        return Condition(
            left=self,
            operator=LogicalOperator.AND,
            right=other,
            is_compound=True,
        )

    def __or__(self, other: Condition) -> Condition:
        """Combine conditions with OR."""
        return Condition(
            left=self,
            operator=LogicalOperator.OR,
            right=other,
            is_compound=True,
        )

    def __invert__(self) -> Condition:
        """Negate a condition with NOT."""
        return Condition(
            left=self,
            operator=LogicalOperator.NOT,
            right=None,
            is_compound=True,
        )
