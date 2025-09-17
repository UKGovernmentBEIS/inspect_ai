"""Metadata filtering DSL for transcript queries.

This module provides a pythonic, type-safe DSL for building WHERE clauses
to filter metadata in SQLite and DuckDB databases.

Usage:
    from inspect_ai.scanner import metadata as m

    # Simple conditions
    filter = m.model == "gpt-4"
    filter = m["custom_field"] > 100

    # Combined conditions
    filter = (m.model == "gpt-4") & (m.score > 0.8)
    filter = (m.status == "error") | (m.retries > 3)

    # Generate SQL
    sql, params = filter.to_sql("sqlite")
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Union


class SQLDialect(Enum):
    """Supported SQL dialects."""

    SQLITE = "sqlite"
    DUCKDB = "duckdb"
    POSTGRES = "postgres"


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
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    BETWEEN = "BETWEEN"
    NOT_BETWEEN = "NOT BETWEEN"


class LogicalOperator(Enum):
    """Logical operators for combining conditions."""

    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class Condition:
    """Represents a WHERE clause condition that can be combined with others."""

    def __init__(
        self,
        left: Union[str, "Condition", None] = None,
        operator: Union[Operator, LogicalOperator, None] = None,
        right: Any = None,
        is_compound: bool = False,
    ):
        self.left = left
        self.operator = operator
        self.right = right
        self.is_compound = is_compound
        self.params: list[Any] = []

        # Store parameters for simple conditions
        if not is_compound and operator not in (Operator.IS_NULL, Operator.IS_NOT_NULL):
            if operator == Operator.IN or operator == Operator.NOT_IN:
                self.params = list(right) if right is not None else []
            elif operator == Operator.BETWEEN or operator == Operator.NOT_BETWEEN:
                self.params = [right[0], right[1]] if right is not None else []
            elif right is not None:
                self.params = [right]

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

    def to_sql(
        self,
        dialect: Union[SQLDialect, Literal["sqlite", "duckdb", "postgres"]] = SQLDialect.SQLITE,
    ) -> tuple[str, list[Any]]:
        """Generate SQL WHERE clause and parameters.

        Args:
            dialect: Target SQL dialect (sqlite, duckdb, or postgres).

        Returns:
            Tuple of (sql_string, parameters_list).
        """
        if isinstance(dialect, str):
            dialect = SQLDialect(dialect)

        sql, params = self._build_sql(dialect)
        return sql, params

    def _build_sql(self, dialect: SQLDialect, param_offset: int = 0) -> tuple[str, list[Any]]:
        """Recursively build SQL string and collect parameters.

        Args:
            dialect: SQL dialect to use.
            param_offset: Starting parameter position for PostgreSQL numbering.

        Returns:
            Tuple of (sql_string, parameters_list).
        """
        if self.is_compound:
            if self.operator == LogicalOperator.NOT:
                assert isinstance(self.left, Condition)
                left_sql, left_params = self.left._build_sql(dialect, param_offset)
                return f"NOT ({left_sql})", left_params
            else:
                assert isinstance(self.left, Condition)
                assert isinstance(self.right, Condition)
                assert self.operator is not None
                left_sql, left_params = self.left._build_sql(dialect, param_offset)
                # Update offset for right side based on left side parameters
                right_offset = param_offset + len(left_params)
                right_sql, right_params = self.right._build_sql(dialect, right_offset)
                return (
                    f"({left_sql} {self.operator.value} {right_sql})",
                    left_params + right_params,
                )
        else:
            # Simple condition
            assert isinstance(self.left, str)
            column = self._format_column(self.left, dialect)

            if self.operator == Operator.IS_NULL:
                return f"{column} IS NULL", []
            elif self.operator == Operator.IS_NOT_NULL:
                return f"{column} IS NOT NULL", []
            elif self.operator == Operator.IN:
                placeholders = self._get_placeholders(len(self.params), dialect, param_offset)
                return f"{column} IN ({placeholders})", self.params
            elif self.operator == Operator.NOT_IN:
                placeholders = self._get_placeholders(len(self.params), dialect, param_offset)
                return f"{column} NOT IN ({placeholders})", self.params
            elif self.operator == Operator.BETWEEN:
                p1 = self._get_placeholder(param_offset + 1, dialect)
                p2 = self._get_placeholder(param_offset + 2, dialect)
                return f"{column} BETWEEN {p1} AND {p2}", self.params
            elif self.operator == Operator.NOT_BETWEEN:
                p1 = self._get_placeholder(param_offset + 1, dialect)
                p2 = self._get_placeholder(param_offset + 2, dialect)
                return f"{column} NOT BETWEEN {p1} AND {p2}", self.params
            else:
                assert self.operator is not None
                placeholder = self._get_placeholder(param_offset + 1, dialect)
                return f"{column} {self.operator.value} {placeholder}", self.params

    def _format_column(self, column_name: str, dialect: SQLDialect) -> str:
        """Format column name for the target dialect."""
        # Handle nested JSON paths
        if "." in column_name:
            parts = column_name.split(".")
            if dialect == SQLDialect.SQLITE:
                # SQLite JSON extraction: json_extract(metadata, '$.field.subfield')
                json_path = "$." + ".".join(parts[1:])
                return f"json_extract(metadata, '{json_path}')"
            elif dialect == SQLDialect.DUCKDB:
                # DuckDB JSON extraction: metadata->'field'->'subfield'
                result = "metadata"
                for part in parts[1:]:
                    result = f"{result}->'{part}'"
                return result
            else:  # PostgreSQL
                # PostgreSQL JSON extraction: metadata->'field'->'subfield' or metadata->'field'->>'subfield' for text
                # Using ->> for the last element to get text, -> for intermediate
                result = "metadata"
                for i, part in enumerate(parts[1:]):
                    if i == len(parts[1:]) - 1:
                        # Last element: use ->> to get as text
                        result = f"{result}->>'{part}'"
                    else:
                        # Intermediate elements: use -> to get JSON
                        result = f"{result}->'{part}'"
                return result
        else:
            # Simple column name - quote it for safety
            return f'"{column_name}"'

    def _get_placeholder(self, position: int, dialect: SQLDialect) -> str:
        """Get parameter placeholder for the dialect."""
        if dialect == SQLDialect.POSTGRES:
            return f"${position}"
        else:  # SQLite and DuckDB use ?
            return "?"

    def _get_placeholders(self, count: int, dialect: SQLDialect, offset: int = 0) -> str:
        """Get multiple parameter placeholders for the dialect."""
        if dialect == SQLDialect.POSTGRES:
            # PostgreSQL uses $1, $2, $3, etc.
            return ", ".join([f"${offset + i + 1}" for i in range(count)])
        else:  # SQLite and DuckDB use ?
            return ", ".join(["?" for _ in range(count)])


class Column:
    """Represents a database column with comparison operators."""

    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other: Any) -> Condition:  # type: ignore[override]
        """Equal to."""
        return Condition(self.name, Operator.EQ, other)

    def __ne__(self, other: Any) -> Condition:  # type: ignore[override]
        """Not equal to."""
        return Condition(self.name, Operator.NE, other)

    def __lt__(self, other: Any) -> Condition:
        """Less than."""
        return Condition(self.name, Operator.LT, other)

    def __le__(self, other: Any) -> Condition:
        """Less than or equal to."""
        return Condition(self.name, Operator.LE, other)

    def __gt__(self, other: Any) -> Condition:
        """Greater than."""
        return Condition(self.name, Operator.GT, other)

    def __ge__(self, other: Any) -> Condition:
        """Greater than or equal to."""
        return Condition(self.name, Operator.GE, other)

    def in_(self, values: list[Any]) -> Condition:
        """Check if value is in a list."""
        return Condition(self.name, Operator.IN, values)

    def not_in(self, values: list[Any]) -> Condition:
        """Check if value is not in a list."""
        return Condition(self.name, Operator.NOT_IN, values)

    def like(self, pattern: str) -> Condition:
        """SQL LIKE pattern matching."""
        return Condition(self.name, Operator.LIKE, pattern)

    def not_like(self, pattern: str) -> Condition:
        """SQL NOT LIKE pattern matching."""
        return Condition(self.name, Operator.NOT_LIKE, pattern)

    def is_null(self) -> Condition:
        """Check if value is NULL."""
        return Condition(self.name, Operator.IS_NULL, None)

    def is_not_null(self) -> Condition:
        """Check if value is not NULL."""
        return Condition(self.name, Operator.IS_NOT_NULL, None)

    def between(self, low: Any, high: Any) -> Condition:
        """Check if value is between two values."""
        return Condition(self.name, Operator.BETWEEN, (low, high))

    def not_between(self, low: Any, high: Any) -> Condition:
        """Check if value is not between two values."""
        return Condition(self.name, Operator.NOT_BETWEEN, (low, high))


class Metadata:
    """Entry point for building metadata filter expressions.

    Supports both dot notation and bracket notation for accessing columns:
        metadata.column_name
        metadata["column_name"]
        metadata["nested.json.path"]
    """

    def __getattr__(self, name: str) -> Column:
        """Access columns using dot notation."""
        if name.startswith("_"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )
        return Column(name)

    def __getitem__(self, name: str) -> Column:
        """Access columns using bracket notation."""
        return Column(name)


# Singleton instance for the DSL
metadata = Metadata()
