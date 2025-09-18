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
        dialect: Union[
            SQLDialect, Literal["sqlite", "duckdb", "postgres"]
        ] = SQLDialect.SQLITE,
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

    def _build_sql(
        self, dialect: SQLDialect, param_offset: int = 0
    ) -> tuple[str, list[Any]]:
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

            if (
                dialect == SQLDialect.POSTGRES
                and isinstance(self.left, str)
                and "." in self.left
            ):

                def _pg_cast(col: str, val: Any) -> str:
                    # PostgreSQL's ->> returns text, so we need to cast from text
                    # bool must be checked before int (bool is a subclass of int)
                    if isinstance(val, bool):
                        return f"({col})::text::boolean"
                    if isinstance(val, int) and not isinstance(val, bool):
                        return f"({col})::text::bigint"
                    if isinstance(val, float):
                        return f"({col})::text::double precision"
                    return col

                # Skip casts for operators that don't compare numerically/textually
                skip_ops = {
                    Operator.LIKE,
                    Operator.NOT_LIKE,
                    Operator.ILIKE,
                    Operator.NOT_ILIKE,
                    Operator.IS_NULL,
                    Operator.IS_NOT_NULL,
                }

                if self.operator not in skip_ops:
                    hint = None
                    if self.operator in (Operator.BETWEEN, Operator.NOT_BETWEEN):
                        # use first non-None bound as hint
                        hint = next((x for x in self.params if x is not None), None)
                    elif self.operator in (Operator.IN, Operator.NOT_IN):
                        # use first non-None value as hint for IN/NOT IN
                        hint = next((x for x in self.params if x is not None), None)
                    else:
                        hint = self.params[0] if self.params else None
                    column = _pg_cast(column, hint)

            # Add DuckDB type casting for JSON paths
            if (
                dialect == SQLDialect.DUCKDB
                and isinstance(self.left, str)
                and "." in self.left
            ):

                def _duck_cast(col: str, val: Any) -> str:
                    # DuckDB casting for type-safe comparisons
                    if isinstance(val, bool):
                        return f"({col})::BOOLEAN"
                    if isinstance(val, int) and not isinstance(val, bool):
                        return f"({col})::BIGINT"
                    if isinstance(val, float):
                        return f"({col})::DOUBLE"
                    return col

                # Apply casting for non-text operators
                skip_ops_duck = {
                    Operator.LIKE,
                    Operator.NOT_LIKE,
                    Operator.ILIKE,
                    Operator.NOT_ILIKE,
                    Operator.IS_NULL,
                    Operator.IS_NOT_NULL,
                }

                if self.operator not in skip_ops_duck:
                    hint = None
                    if self.operator in (Operator.BETWEEN, Operator.NOT_BETWEEN):
                        hint = next((x for x in self.params if x is not None), None)
                    elif self.operator in (Operator.IN, Operator.NOT_IN):
                        hint = next((x for x in self.params if x is not None), None)
                    else:
                        hint = self.params[0] if self.params else None
                    column = _duck_cast(column, hint)

            if self.operator == Operator.IS_NULL:
                return f"{column} IS NULL", []
            elif self.operator == Operator.IS_NOT_NULL:
                return f"{column} IS NOT NULL", []
            elif self.operator == Operator.IN:
                # Handle NULL values in IN list
                vals = [v for v in self.params if v is not None]
                has_null = any(v is None for v in self.params)
                n = len(vals)

                if n == 0 and not has_null:
                    return "1 = 0", []  # empty IN = always false

                sql_parts = []
                if n > 0:
                    placeholders = self._get_placeholders(n, dialect, param_offset)
                    sql_parts.append(f"{column} IN ({placeholders})")
                if has_null:
                    sql_parts.append(f"{column} IS NULL")

                sql = " OR ".join(sql_parts) if sql_parts else "1 = 0"
                if len(sql_parts) > 1:
                    sql = f"({sql})"
                return sql, vals

            elif self.operator == Operator.NOT_IN:
                # Handle NULL values in NOT IN list
                vals = [v for v in self.params if v is not None]
                has_null = any(v is None for v in self.params)
                n = len(vals)

                if n == 0 and not has_null:
                    return "1 = 1", []  # empty NOT IN = always true

                sql_parts = []
                if n > 0:
                    placeholders = self._get_placeholders(n, dialect, param_offset)
                    sql_parts.append(f"{column} NOT IN ({placeholders})")
                if has_null:
                    sql_parts.append(f"{column} IS NOT NULL")

                if not sql_parts:
                    sql = "1 = 1"
                elif len(sql_parts) == 1:
                    sql = sql_parts[0]
                else:
                    sql = f"({sql_parts[0]} AND {sql_parts[1]})"
                return sql, vals
            elif self.operator == Operator.BETWEEN:
                p1 = self._get_placeholder(param_offset, dialect)
                p2 = self._get_placeholder(param_offset + 1, dialect)
                return f"{column} BETWEEN {p1} AND {p2}", self.params
            elif self.operator == Operator.NOT_BETWEEN:
                p1 = self._get_placeholder(param_offset, dialect)
                p2 = self._get_placeholder(param_offset + 1, dialect)
                return f"{column} NOT BETWEEN {p1} AND {p2}", self.params
            elif self.operator == Operator.ILIKE:
                placeholder = self._get_placeholder(param_offset, dialect)
                if dialect == SQLDialect.POSTGRES:
                    return f"{column} ILIKE {placeholder}", self.params
                else:
                    # For SQLite and DuckDB, use LOWER() for case-insensitive comparison
                    return f"LOWER({column}) LIKE LOWER({placeholder})", self.params
            elif self.operator == Operator.NOT_ILIKE:
                placeholder = self._get_placeholder(param_offset, dialect)
                if dialect == SQLDialect.POSTGRES:
                    return f"{column} NOT ILIKE {placeholder}", self.params
                else:
                    # For SQLite and DuckDB, use LOWER() for case-insensitive comparison
                    return f"LOWER({column}) NOT LIKE LOWER({placeholder})", self.params
            else:
                assert self.operator is not None
                placeholder = self._get_placeholder(param_offset, dialect)
                return f"{column} {self.operator.value} {placeholder}", self.params

    def _esc_double(self, s: str) -> str:
        return s.replace('"', '""')

    def _esc_single(self, s: str) -> str:
        return s.replace("'", "''")

    def _parse_json_path(self, path: str) -> tuple[str, list[tuple[str, bool]]]:
        """Parse a JSON path supporting array indices and quoted keys.

        Returns:
            Tuple of (base_column, list of (segment, is_array_index))
        """
        # First check if this is a simple column (no dots)
        if "." not in path and "[" not in path:
            return path, []

        # Split on dots but preserve quoted sections
        # Handle: base."quoted.key".normal.0."another.quoted"
        parts = []
        current = ""
        in_quotes = False

        for char in path:
            if char == '"':
                in_quotes = not in_quotes
                current += char
            elif char == "." and not in_quotes:
                if current:
                    parts.append(current)
                    current = ""
            else:
                current += char
        if current:
            parts.append(current)

        if not parts:
            return path, []

        base = parts[0]
        path_parts = []

        for part in parts[1:]:
            # Handle bracket notation [0]
            if part.startswith("[") and part.endswith("]"):
                index = part[1:-1]
                if index.isdigit():
                    path_parts.append((index, True))
            # Handle quoted segments "user.name"
            elif part.startswith('"') and part.endswith('"'):
                path_parts.append((part[1:-1], False))
            # Handle regular segments or numeric strings
            elif part.isdigit():
                path_parts.append((part, True))
            else:
                path_parts.append((part, False))

        return base, path_parts

    def _format_column(self, column_name: str, dialect: SQLDialect) -> str:
        # If dotted, treat as: <base_column>.<json.path.inside.it>
        if "." in column_name or "[" in column_name:
            base, path_parts = self._parse_json_path(column_name)

            if not path_parts:
                # No JSON path, just a column name that might contain a dot
                # in table.column format (not supported in current implementation)
                return f'"{self._esc_double(column_name)}"'

            if dialect == SQLDialect.SQLITE:
                # Build JSONPath like $.key[0]."user.name"
                json_path_parts = []
                for segment, is_index in path_parts:
                    if is_index:
                        json_path_parts.append(f"[{segment}]")
                    elif "." in segment or segment.startswith('"'):
                        # Keys with special chars need quoting in JSONPath
                        json_path_parts.append(f'."{segment}"')
                    else:
                        json_path_parts.append(f".{segment}")
                json_path = "$" + "".join(json_path_parts)
                return f"json_extract(\"{self._esc_double(base)}\", '{self._esc_single(json_path)}')"

            elif dialect == SQLDialect.DUCKDB:
                # Use json_extract for better compatibility with VARCHAR columns
                json_path_parts = []
                for segment, is_index in path_parts:
                    if is_index:
                        json_path_parts.append(f"[{segment}]")
                    elif "." in segment:
                        # Keys with dots need quoting
                        json_path_parts.append(f'."{segment}"')
                    else:
                        json_path_parts.append(f".{segment}")
                json_path = "$" + "".join(json_path_parts)
                return f"json_extract(\"{self._esc_double(base)}\", '{self._esc_single(json_path)}')"

            elif dialect == SQLDialect.POSTGRES:
                result = f'"{self._esc_double(base)}"'
                for i, (segment, is_index) in enumerate(path_parts):
                    op = "->>" if i == len(path_parts) - 1 else "->"
                    if is_index:
                        # Array index: use unquoted integer
                        result = f"{result}{op}{segment}"
                    else:
                        # Object key: use quoted string
                        result = f"{result}{op}'{self._esc_single(segment)}'"
                return result

        # Simple (non-JSON) column
        return f'"{self._esc_double(column_name)}"'

    def _get_placeholder(self, position: int, dialect: SQLDialect) -> str:
        """Get parameter placeholder for the dialect.

        Args:
            position: Zero-based position in the parameter array.
            dialect: SQL dialect to use.
        """
        if dialect == SQLDialect.POSTGRES:
            return f"${position + 1}"  # PostgreSQL uses 1-based indexing
        else:  # SQLite and DuckDB use ?
            return "?"

    def _get_placeholders(
        self, count: int, dialect: SQLDialect, offset: int = 0
    ) -> str:
        """Get multiple parameter placeholders for the dialect.

        Args:
            count: Number of placeholders to generate.
            dialect: SQL dialect to use.
            offset: Zero-based starting position in the parameter array.
        """
        if dialect == SQLDialect.POSTGRES:
            # PostgreSQL uses 1-based $1, $2, $3, etc.
            return ", ".join([f"${offset + i + 1}" for i in range(count)])
        else:  # SQLite and DuckDB use ?
            return ", ".join(["?" for _ in range(count)])


class Column:
    """Represents a database column with comparison operators."""

    def __init__(self, name: str):
        self.name = name

    def __eq__(self, other: Any) -> Condition:  # type: ignore[override]
        return Condition(
            self.name,
            Operator.IS_NULL if other is None else Operator.EQ,
            None if other is None else other,
        )

    def __ne__(self, other: Any) -> Condition:  # type: ignore[override]
        return Condition(
            self.name,
            Operator.IS_NOT_NULL if other is None else Operator.NE,
            None if other is None else other,
        )

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
        """SQL LIKE pattern matching (case-sensitive)."""
        return Condition(self.name, Operator.LIKE, pattern)

    def not_like(self, pattern: str) -> Condition:
        """SQL NOT LIKE pattern matching (case-sensitive)."""
        return Condition(self.name, Operator.NOT_LIKE, pattern)

    def ilike(self, pattern: str) -> Condition:
        """PostgreSQL ILIKE pattern matching (case-insensitive).

        Note: For SQLite and DuckDB, this will use LIKE with LOWER() for case-insensitivity.
        """
        return Condition(self.name, Operator.ILIKE, pattern)

    def not_ilike(self, pattern: str) -> Condition:
        """PostgreSQL NOT ILIKE pattern matching (case-insensitive).

        Note: For SQLite and DuckDB, this will use NOT LIKE with LOWER() for case-insensitivity.
        """
        return Condition(self.name, Operator.NOT_ILIKE, pattern)

    def is_null(self) -> Condition:
        """Check if value is NULL."""
        return Condition(self.name, Operator.IS_NULL, None)

    def is_not_null(self) -> Condition:
        """Check if value is not NULL."""
        return Condition(self.name, Operator.IS_NOT_NULL, None)

    def between(self, low: Any, high: Any) -> Condition:
        """Check if value is between two values.

        Args:
            low: Lower bound (inclusive). If None, raises ValueError.
            high: Upper bound (inclusive). If None, raises ValueError.

        Raises:
            ValueError: If either bound is None.
        """
        if low is None or high is None:
            raise ValueError("BETWEEN operator requires non-None bounds")
        return Condition(self.name, Operator.BETWEEN, (low, high))

    def not_between(self, low: Any, high: Any) -> Condition:
        """Check if value is not between two values.

        Args:
            low: Lower bound (inclusive). If None, raises ValueError.
            high: Upper bound (inclusive). If None, raises ValueError.

        Raises:
            ValueError: If either bound is None.
        """
        if low is None or high is None:
            raise ValueError("NOT BETWEEN operator requires non-None bounds")
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
