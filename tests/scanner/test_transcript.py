"""Comprehensive tests for the _transcript module."""

import uuid

import pandas as pd
import pytest

from inspect_ai.scanner._transcript.database import EvalLogTranscriptsDB
from inspect_ai.scanner._transcript.metadata import metadata as m
from inspect_ai.scanner._transcript.transcripts import transcripts
from inspect_ai.scanner._transcript.types import TranscriptInfo


def create_test_dataframe(num_samples: int = 10) -> pd.DataFrame:
    """Create a test DataFrame with sample data for testing."""
    data = []
    for i in range(num_samples):
        data.append(
            {
                "sample_id": f"sample_{i:03d}_{uuid.uuid4().hex[:8]}",
                "log": f"/path/to/log_{i:03d}.json",
                "model": ["gpt-4", "gpt-3.5-turbo", "claude"][i % 3],
                "score": 0.5 + (i % 10) * 0.05,  # 0.5 to 0.95
                "status": ["success", "error", "timeout"][i % 3],
                "retries": i % 4,
                "temperature": 0.7 + (i % 5) * 0.1,
                "max_tokens": 1000 + (i % 5) * 500,
                "dataset": ["train", "test", "validation"][i % 3],
                "run_date": f"2024-01-{(i % 28) + 1:02d}",
                "duration_seconds": 10 + i * 5,
                "token_count": 500 + i * 100,
                "error_message": "timeout error" if i % 3 == 2 else None,
            }
        )
    return pd.DataFrame(data)


@pytest.fixture
async def db():
    """Create and connect to a test database."""
    df = create_test_dataframe(20)
    db = EvalLogTranscriptsDB(df)
    await db.connect()
    yield db
    await db.disconnect()


# ============================================================================
# Metadata Filtering DSL Tests
# ============================================================================


def test_simple_equality():
    """Test simple equality conditions."""
    condition = m.model == "gpt-4"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"model" = ?'
    assert params == ["gpt-4"]


def test_comparison_operators():
    """Test all comparison operators."""
    # Greater than
    condition = m.score > 0.8
    sql, params = condition.to_sql("sqlite")
    assert sql == '"score" > ?'
    assert params == [0.8]

    # Less than or equal
    condition = m.retries <= 3
    sql, params = condition.to_sql("sqlite")
    assert sql == '"retries" <= ?'
    assert params == [3]

    # Not equal
    condition = m.status != "error"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"status" != ?'
    assert params == ["error"]


def test_in_operator():
    """Test IN and NOT IN operators."""
    condition = m.model.in_(["gpt-4", "claude"])
    sql, params = condition.to_sql("sqlite")
    assert sql == '"model" IN (?, ?)'
    assert params == ["gpt-4", "claude"]

    condition = m.status.not_in(["error", "timeout"])
    sql, params = condition.to_sql("sqlite")
    assert sql == '"status" NOT IN (?, ?)'
    assert params == ["error", "timeout"]


def test_empty_in_operator():
    """Test empty IN and NOT IN operators."""
    # Empty IN should always be false (nothing can be in an empty set)
    condition = m.model.in_([])
    sql, params = condition.to_sql("sqlite")
    assert sql == "1 = 0"  # Always false
    assert params == []

    # Empty NOT IN should always be true (everything is not in an empty set)
    condition = m.status.not_in([])
    sql, params = condition.to_sql("sqlite")
    assert sql == "1 = 1"  # Always true
    assert params == []

    # Test with other dialects too
    condition = m.model.in_([])
    sql, params = condition.to_sql("postgres")
    assert sql == "1 = 0"
    assert params == []

    condition = m.status.not_in([])
    sql, params = condition.to_sql("duckdb")
    assert sql == "1 = 1"
    assert params == []


def test_null_operators():
    """Test NULL and NOT NULL operators."""
    condition = m.error_message.is_null()
    sql, params = condition.to_sql("sqlite")
    assert sql == '"error_message" IS NULL'
    assert params == []

    condition = m.error_message.is_not_null()
    sql, params = condition.to_sql("sqlite")
    assert sql == '"error_message" IS NOT NULL'
    assert params == []


def test_none_comparison():
    """Test that == None and != None map to IS NULL and IS NOT NULL."""
    # == None should map to IS NULL
    condition = m.error_message == None
    sql, params = condition.to_sql("sqlite")
    assert sql == '"error_message" IS NULL'
    assert params == []

    # != None should map to IS NOT NULL
    condition = m.error_message != None
    sql, params = condition.to_sql("sqlite")
    assert sql == '"error_message" IS NOT NULL'
    assert params == []

    # Test with other dialects
    condition = m.status == None
    sql, params = condition.to_sql("postgres")
    assert sql == '"status" IS NULL'
    assert params == []

    condition = m.status != None
    sql, params = condition.to_sql("duckdb")
    assert sql == '"status" IS NOT NULL'
    assert params == []

    # Combined with other conditions
    condition = (m.model == "gpt-4") & (m.error == None)
    sql, params = condition.to_sql("sqlite")
    assert sql == '("model" = ? AND "error" IS NULL)'
    assert params == ["gpt-4"]


def test_like_operator():
    """Test LIKE and NOT LIKE operators."""
    condition = m.error_message.like("%timeout%")
    sql, params = condition.to_sql("sqlite")
    assert sql == '"error_message" LIKE ?'
    assert params == ["%timeout%"]

    condition = m.log.not_like("/tmp/%")
    sql, params = condition.to_sql("sqlite")
    assert sql == '"log" NOT LIKE ?'
    assert params == ["/tmp/%"]


def test_between_operator():
    """Test BETWEEN and NOT BETWEEN operators."""
    condition = m.score.between(0.5, 0.9)
    sql, params = condition.to_sql("sqlite")
    assert sql == '"score" BETWEEN ? AND ?'
    assert params == [0.5, 0.9]

    condition = m.retries.not_between(1, 3)
    sql, params = condition.to_sql("sqlite")
    assert sql == '"retries" NOT BETWEEN ? AND ?'
    assert params == [1, 3]


def test_logical_operators():
    """Test AND, OR, and NOT logical operators."""
    # AND
    condition = (m.model == "gpt-4") & (m.score > 0.8)
    sql, params = condition.to_sql("sqlite")
    assert sql == '("model" = ? AND "score" > ?)'
    assert params == ["gpt-4", 0.8]

    # OR
    condition = (m.status == "error") | (m.retries > 2)
    sql, params = condition.to_sql("sqlite")
    assert sql == '("status" = ? OR "retries" > ?)'
    assert params == ["error", 2]

    # NOT
    condition = ~(m.model == "gpt-3.5-turbo")
    sql, params = condition.to_sql("sqlite")
    assert sql == 'NOT ("model" = ?)'
    assert params == ["gpt-3.5-turbo"]


def test_complex_nested_conditions():
    """Test complex nested conditions."""
    condition = (
        ((m.model == "gpt-4") & (m.score > 0.8))
        | ((m.model == "claude") & (m.score > 0.7))
    ) & ~(m.error_message.is_not_null())

    sql, params = condition.to_sql("sqlite")
    assert "AND" in sql
    assert "OR" in sql
    assert "NOT" in sql
    assert len(params) == 4


def test_bracket_notation():
    """Test bracket notation for column access."""
    condition = m["custom_field"] > 100
    sql, params = condition.to_sql("sqlite")
    assert sql == '"custom_field" > ?'
    assert params == [100]


def test_nested_json_paths():
    """Test nested JSON path extraction with proper escaping."""
    # Simple nested path
    condition = m["metadata.config.temperature"] > 0.7

    # SQLite
    sql, params = condition.to_sql("sqlite")
    assert sql == 'json_extract("metadata", \'$.config.temperature\') > ?'
    assert params == [0.7]

    # DuckDB - should use ->> for last element
    sql, params = condition.to_sql("duckdb")
    assert sql == '"metadata"->\'config\'->>\'temperature\' > ?'
    assert params == [0.7]

    # PostgreSQL - should use ->> for last element AND cast for numeric comparison
    sql, params = condition.to_sql("postgres")
    assert sql == '''("metadata"->'config'->>'temperature')::double precision > $1'''
    assert params == [0.7]


def test_column_name_escaping():
    """Test that column names with special characters are properly escaped."""
    # Column name with double quotes
    condition = m['col"umn'] == "value"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"col""umn" = ?'
    assert params == ["value"]

    # JSON path with single quotes
    condition = m["metadata.key'with'quotes"] == "value"
    sql, params = condition.to_sql("sqlite")
    assert sql == 'json_extract("metadata", \'$.key\'\'with\'\'quotes\') = ?'
    assert params == ["value"]

    # DuckDB with quotes in path
    sql, params = condition.to_sql("duckdb")
    assert sql == '"metadata"->>\'key\'\'with\'\'quotes\' = ?'
    assert params == ["value"]


def test_postgres_json_type_casting():
    """Test that PostgreSQL properly casts JSON values for comparisons."""
    # Integer comparison - should cast to bigint
    condition = m["metadata.retries"] > 3
    sql, params = condition.to_sql("postgres")
    assert sql == """("metadata"->>'retries')::bigint > $1"""
    assert params == [3]

    # Float comparison - should cast to double precision
    condition = m["metadata.score"] >= 0.75
    sql, params = condition.to_sql("postgres")
    assert sql == """("metadata"->>'score')::double precision >= $1"""
    assert params == [0.75]

    # Boolean comparison - should cast to boolean
    condition = m["metadata.enabled"] == True
    sql, params = condition.to_sql("postgres")
    assert sql == """("metadata"->>'enabled')::boolean = $1"""
    assert params == [True]

    condition = m["metadata.flag"] != False
    sql, params = condition.to_sql("postgres")
    assert sql == """("metadata"->>'flag')::boolean != $1"""
    assert params == [False]

    # BETWEEN with numeric values - should cast
    condition = m["metadata.score"].between(0.5, 0.9)
    sql, params = condition.to_sql("postgres")
    assert sql == """("metadata"->>'score')::double precision BETWEEN $1 AND $2"""
    assert params == [0.5, 0.9]

    # String comparison - no cast needed
    condition = m["metadata.status"] == "active"
    sql, params = condition.to_sql("postgres")
    assert sql == """"metadata"->>'status' = $1"""
    assert params == ["active"]

    # LIKE operator - should NOT cast (string operation)
    condition = m["metadata.message"].like("%error%")
    sql, params = condition.to_sql("postgres")
    assert sql == """"metadata"->>'message' LIKE $1"""
    assert params == ["%error%"]

    # IN operator - should NOT cast
    condition = m["metadata.status"].in_(["active", "pending"])
    sql, params = condition.to_sql("postgres")
    assert sql == """"metadata"->>'status' IN ($1, $2)"""
    assert params == ["active", "pending"]

    # IS NULL - should NOT cast
    condition = m["metadata.optional"].is_null()
    sql, params = condition.to_sql("postgres")
    assert sql == """"metadata"->>'optional' IS NULL"""
    assert params == []

    # Deep nested paths with casting
    condition = m["metadata.config.max_retries"] < 10
    sql, params = condition.to_sql("postgres")
    assert sql == """("metadata"->'config'->>'max_retries')::bigint < $1"""
    assert params == [10]


def test_postgres_casting_with_none():
    """Test PostgreSQL casting handles None values correctly."""
    # Comparison with None should not crash the casting logic
    condition = m["metadata.field"] == None
    sql, params = condition.to_sql("postgres")
    assert sql == """"metadata"->>'field' IS NULL"""
    assert params == []


def test_no_casting_for_non_json_columns():
    """Test that regular columns don't get cast in PostgreSQL."""
    # Regular column with integer - no casting
    condition = m.retries > 3
    sql, params = condition.to_sql("postgres")
    assert sql == '"retries" > $1'
    assert params == [3]

    # Regular column with float - no casting
    condition = m.score >= 0.75
    sql, params = condition.to_sql("postgres")
    assert sql == '"score" >= $1'
    assert params == [0.75]


def test_deep_nested_paths():
    """Test deeply nested JSON paths."""
    condition = m["metadata.level1.level2.level3.value"] > 10

    # SQLite
    sql, params = condition.to_sql("sqlite")
    assert sql == 'json_extract("metadata", \'$.level1.level2.level3.value\') > ?'
    assert params == [10]

    # DuckDB - multiple -> operators, ->> for last
    sql, params = condition.to_sql("duckdb")
    assert sql == '"metadata"->\'level1\'->\'level2\'->\'level3\'->>\'value\' > ?'
    assert params == [10]

    # PostgreSQL - should cast integer for numeric comparison
    sql, params = condition.to_sql("postgres")
    assert sql == '''("metadata"->'level1'->'level2'->'level3'->>'value')::bigint > $1'''
    assert params == [10]


# ============================================================================
# TranscriptDB Tests
# ============================================================================


@pytest.mark.asyncio
async def test_connect_disconnect():
    """Test database connection and disconnection."""
    df = create_test_dataframe(5)
    db = EvalLogTranscriptsDB(df)

    # Connect
    await db.connect()
    assert db._conn is not None

    # Disconnect
    await db.disconnect()
    # Can't check if connection is closed in SQLite, but no error is good


@pytest.mark.asyncio
async def test_query_all(db):
    """Test querying all records."""
    results = list(await db.query(where=[]))
    assert len(results) == 20

    # Check that each result is a TranscriptInfo
    for result in results:
        assert isinstance(result, TranscriptInfo)
        assert result.id.startswith("sample_")
        assert result.source.startswith("/path/to/log_")
        assert isinstance(result.metadata, dict)


@pytest.mark.asyncio
async def test_query_with_filter(db):
    """Test querying with filters."""
    # Filter by model
    results = list(await db.query(where=[m.model == "gpt-4"]))
    for result in results:
        assert result.metadata["model"] == "gpt-4"

    # Filter by score range
    results = list(await db.query(where=[m.score > 0.7]))
    for result in results:
        assert result.metadata["score"] > 0.7


@pytest.mark.asyncio
async def test_query_with_multiple_conditions(db):
    """Test querying with multiple conditions."""
    conditions = [m.model == "gpt-4", m.score > 0.6]
    results = list(await db.query(where=conditions))

    for result in results:
        assert result.metadata["model"] == "gpt-4"
        assert result.metadata["score"] > 0.6


@pytest.mark.asyncio
async def test_query_with_limit(db):
    """Test querying with limit."""
    results = list(await db.query(where=[], limit=5))
    assert len(results) == 5

    # With filter and limit
    results = list(await db.query(where=[m.model == "gpt-4"], limit=2))
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_query_with_shuffle(db):
    """Test querying with shuffle."""
    # Get results without shuffle
    results1 = list(await db.query(where=[], limit=10))
    ids1 = [r.id for r in results1]

    # Get results with shuffle (seed=42)
    results2 = list(await db.query(where=[], limit=10, shuffle=42))
    ids2 = [r.id for r in results2]

    # Results should be different order (very unlikely to be same)
    assert ids1 != ids2

    # Get results with same seed - should be same order
    results3 = list(await db.query(where=[], limit=10, shuffle=42))
    ids3 = [r.id for r in results3]
    assert ids2 == ids3


@pytest.mark.asyncio
async def test_count_all(db):
    """Test counting all records."""
    count = await db.count(where=[])
    assert count == 20


@pytest.mark.asyncio
async def test_count_with_filter(db):
    """Test counting with filters."""
    # Count by model
    count = await db.count(where=[m.model == "gpt-4"])
    assert count > 0

    # Verify count matches query
    results = list(await db.query(where=[m.model == "gpt-4"]))
    assert count == len(results)


@pytest.mark.asyncio
async def test_count_with_limit(db):
    """Test counting with limit."""
    count = await db.count(where=[], limit=5)
    assert count == 5

    # With filter and limit
    total_gpt4 = await db.count(where=[m.model == "gpt-4"])
    count_limited = await db.count(where=[m.model == "gpt-4"], limit=2)
    assert count_limited == min(2, total_gpt4)


@pytest.mark.asyncio
async def test_complex_queries(db):
    """Test complex queries with multiple operators."""
    # Complex condition
    conditions = [
        (m.model.in_(["gpt-4", "claude"])) & (m.score > 0.6),
        m.error_message.is_null(),
    ]

    results = list(await db.query(where=conditions))
    for result in results:
        assert result.metadata["model"] in ["gpt-4", "claude"]
        assert result.metadata["score"] > 0.6
        assert result.metadata.get("error_message") is None


@pytest.mark.asyncio
async def test_metadata_extraction(db):
    """Test that metadata is properly extracted."""
    results = list(await db.query(where=[], limit=1))
    assert len(results) == 1

    result = results[0]
    metadata = result.metadata

    # Check expected metadata fields
    assert "model" in metadata
    assert "score" in metadata
    assert "status" in metadata
    assert "retries" in metadata

    # sample_id and log should not be in metadata
    assert "sample_id" not in metadata
    assert "log" not in metadata


@pytest.mark.asyncio
async def test_none_comparison_in_db(db):
    """Test that == None and != None work correctly in database queries."""
    # Using == None (should behave same as is_null())
    results_eq_none = list(await db.query(where=[m.error_message == None]))  # noqa: E711
    results_is_null = list(await db.query(where=[m.error_message.is_null()]))
    assert len(results_eq_none) == len(results_is_null)

    # Using != None (should behave same as is_not_null())
    results_ne_none = list(await db.query(where=[m.error_message != None]))  # noqa: E711
    results_is_not_null = list(await db.query(where=[m.error_message.is_not_null()]))
    assert len(results_ne_none) == len(results_is_not_null)

    # Verify they partition all records
    assert len(results_eq_none) + len(results_ne_none) == 20


@pytest.mark.asyncio
async def test_null_value_handling(db):
    """Test handling of NULL values in metadata."""
    # Query for null error_message
    results = list(await db.query(where=[m.error_message.is_null()]))

    for result in results:
        # NULL values should not appear in metadata dict
        assert (
            "error_message" not in result.metadata
            or result.metadata["error_message"] is None
        )

    # Query for non-null error_message
    results = list(await db.query(where=[m.error_message.is_not_null()]))

    for result in results:
        assert result.metadata.get("error_message") is not None


# ============================================================================
# Transcripts API Tests
# ============================================================================


def test_transcripts_function():
    """Test the transcripts() function."""
    df = create_test_dataframe(5)
    t = transcripts(df)

    # Should return a Transcripts instance
    assert hasattr(t, "_db")
    assert isinstance(t._db, EvalLogTranscriptsDB)


@pytest.mark.asyncio
async def test_transcripts_query_integration():
    """Test end-to-end query through transcripts API."""
    df = create_test_dataframe(15)
    t = transcripts(df)

    await t._db.connect()

    # Test query
    results = list(await t._db.query(where=[m.score > 0.7], limit=5))

    assert len(results) <= 5
    for result in results:
        assert result.metadata["score"] > 0.7

    await t._db.disconnect()


# ============================================================================
# Edge Cases Tests
# ============================================================================


@pytest.mark.asyncio
async def test_empty_dataframe():
    """Test with empty DataFrame."""
    df = pd.DataFrame(columns=["sample_id", "log"])
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    results = list(await db.query(where=[]))
    assert len(results) == 0

    count = await db.count(where=[])
    assert count == 0

    await db.disconnect()


@pytest.mark.asyncio
async def test_missing_required_columns():
    """Test error handling when required columns are missing."""
    # DataFrame with all required columns but one has None
    df = pd.DataFrame(
        {
            "sample_id": [None],  # Missing sample_id value
            "log": ["/path/to/log.json"],
            "model": ["gpt-4"],
        }
    )

    db = EvalLogTranscriptsDB(df)
    await db.connect()

    # Should raise error when trying to query
    with pytest.raises(ValueError, match="Missing required fields"):
        list(await db.query(where=[]))

    await db.disconnect()


@pytest.mark.asyncio
async def test_empty_in_clause_in_db(db):
    """Test that empty IN/NOT IN work correctly in actual queries."""
    # Empty IN should return no results
    results = list(await db.query(where=[m.model.in_([])]))
    assert len(results) == 0  # Always false, no results

    # Empty NOT IN should return all results
    results = list(await db.query(where=[m.model.not_in([])]))
    assert len(results) == 20  # Always true, all results

    # Combined with other conditions
    results = list(await db.query(where=[
        m.score > 0.5,
        m.status.not_in([])  # This is always true, shouldn't affect results
    ]))
    # Should be same as just m.score > 0.5
    results_without = list(await db.query(where=[m.score > 0.5]))
    assert len(results) == len(results_without)


@pytest.mark.asyncio
async def test_large_in_clause():
    """Test IN clause with many values."""
    df = create_test_dataframe(100)
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    # Create a large list of values
    large_list = [f"model_{i}" for i in range(50)]
    large_list.append("gpt-4")  # Include one that exists

    results = list(await db.query(where=[m.model.in_(large_list)]))

    # Should find some results
    assert len(results) > 0

    await db.disconnect()


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
