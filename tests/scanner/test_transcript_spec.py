"""Tests for transcript spec save/load functionality."""

import base64
import pickle

import pandas as pd
import pytest

from inspect_ai.scanner._transcript.database import transcripts, transcripts_from_spec
from inspect_ai.scanner._transcript.metadata import metadata as m


def create_test_dataframe(num_samples: int = 10) -> pd.DataFrame:
    """Create a test DataFrame with sample data."""
    data = []
    for i in range(num_samples):
        data.append(
            {
                "sample_id": f"sample_{i:03d}",
                "log": f"/path/to/log_{i:03d}.json",
                "model": ["gpt-4", "gpt-3.5-turbo", "claude"][i % 3],
                "score": 0.5 + (i % 10) * 0.05,
                "status": ["success", "error", "timeout"][i % 3],
                "retries": i % 4,
                "temperature": 0.7 + (i % 5) * 0.1,
                "dataset": ["train", "test", "validation"][i % 3],
            }
        )
    return pd.DataFrame(data)


# ============================================================================
# Basic Spec Operations Tests
# ============================================================================


def test_save_spec_structure():
    """Test that save_spec returns expected structure."""
    df = create_test_dataframe(5)
    t = transcripts(df)

    spec = t.save_spec()

    # Check required fields exist
    assert "type" in spec
    assert "where" in spec
    assert "limit" in spec
    assert "shuffle" in spec

    # Check type value
    assert spec["type"] == "eval_log"

    # Check defaults
    assert spec["limit"] is None
    assert spec["shuffle"] is False

    # Check where is base64 encoded pickle
    decoded = pickle.loads(base64.b64decode(spec["where"]))
    assert isinstance(decoded, list)
    assert decoded == []  # No filters by default


def test_save_spec_with_filters():
    """Test save_spec preserves filter conditions."""
    df = create_test_dataframe(10)
    t = transcripts(df).where(m.model == "gpt-4").where(m.score > 0.7)

    spec = t.save_spec()

    # Decode where conditions
    where_conditions = pickle.loads(base64.b64decode(spec["where"]))
    assert len(where_conditions) == 2

    # Verify conditions are preserved
    sql1, params1 = where_conditions[0].to_sql("sqlite")
    assert sql1 == '"model" = ?'
    assert params1 == ["gpt-4"]

    sql2, params2 = where_conditions[1].to_sql("sqlite")
    assert sql2 == '"score" > ?'
    assert params2 == [0.7]


def test_save_spec_with_limit():
    """Test save_spec preserves limit."""
    df = create_test_dataframe(10)
    t = transcripts(df).limit(5)

    spec = t.save_spec()
    assert spec["limit"] == 5


def test_save_spec_with_shuffle_no_seed():
    """Test save_spec preserves shuffle without seed."""
    df = create_test_dataframe(10)
    t = transcripts(df).shuffle()

    spec = t.save_spec()
    assert spec["shuffle"] is True


def test_save_spec_with_shuffle_seed():
    """Test save_spec preserves shuffle with seed."""
    df = create_test_dataframe(10)
    t = transcripts(df).shuffle(42)

    spec = t.save_spec()
    assert spec["shuffle"] == 42


def test_load_spec_basic():
    """Test loading a basic spec."""
    df = create_test_dataframe(10)

    # Create a spec manually - must include logs for EvalLogTranscripts
    spec = {
        "type": "eval_log",
        "where": base64.b64encode(pickle.dumps([])).decode("utf-8"),
        "limit": None,
        "shuffle": False,
        "logs": base64.b64encode(pickle.dumps(df)).decode(
            "utf-8"
        ),  # Required for EvalLogTranscripts
    }

    # Load it into a new instance
    t2 = transcripts_from_spec(spec)

    # Verify fields are loaded
    assert t2._where == []
    assert t2._limit is None
    assert t2._shuffle is False


def test_save_load_roundtrip():
    """Test that save_spec and load_spec are inverses."""
    df = create_test_dataframe(10)
    t1 = (
        transcripts(df)
        .where(m.model == "gpt-4")
        .where(m.score.between(0.6, 0.9))
        .limit(10)
        .shuffle(seed=123)
    )

    # Save spec
    spec = t1.save_spec()

    # Load into new instance
    t2 = transcripts_from_spec(spec)

    # Verify all fields match
    assert len(t2._where) == len(t1._where)
    assert t2._limit == t1._limit
    assert t2._shuffle == t1._shuffle

    # Verify conditions are equivalent
    for cond1, cond2 in zip(t1._where, t2._where):
        sql1, params1 = cond1.to_sql("sqlite")
        sql2, params2 = cond2.to_sql("sqlite")
        assert sql1 == sql2
        assert params1 == params2


# ============================================================================
# Complex Filters Tests
# ============================================================================


def test_combined_conditions():
    """Test save/load with combined AND/OR conditions."""
    df = create_test_dataframe(20)
    condition = (m.model == "gpt-4") & ((m.score > 0.8) | (m.retries < 2))
    t1 = transcripts(df).where(condition)

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    # Verify condition is preserved
    assert len(t2._where) == 1
    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


def test_in_clause():
    """Test save/load with IN clause conditions."""
    df = create_test_dataframe(20)
    t1 = transcripts(df).where(m.model.in_(["gpt-4", "claude", "gemini"]))

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


def test_null_conditions():
    """Test save/load with NULL conditions."""
    df = create_test_dataframe(20)
    t1 = transcripts(df).where(m.error_message.is_null())

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


def test_like_conditions():
    """Test save/load with LIKE conditions."""
    df = create_test_dataframe(20)
    t1 = transcripts(df).where(m.log.like("/path/to/%"))

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


def test_multiple_where_clauses():
    """Test save/load with multiple where() calls."""
    df = create_test_dataframe(20)
    t1 = (
        transcripts(df)
        .where(m.model == "gpt-4")
        .where(m.score > 0.7)
        .where(m.status != "error")
        .where(m.retries <= 3)
    )

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    # Should have 4 conditions
    assert len(t2._where) == 4

    # Each should match
    for cond1, cond2 in zip(t1._where, t2._where):
        sql1, params1 = cond1.to_sql("sqlite")
        sql2, params2 = cond2.to_sql("sqlite")
        assert sql1 == sql2
        assert params1 == params2


# Note: Content-related tests removed as the content() method has been removed
# from the Transcripts API. Content is now passed directly to collect().


# ============================================================================
# Factory Function Tests
# ============================================================================


def test_factory_with_eval_log_type():
    """Test factory function creates correct type for eval_log."""
    df = create_test_dataframe(5)
    spec = {
        "type": "eval_log",
        "where": base64.b64encode(pickle.dumps([])).decode("utf-8"),
        "limit": 5,
        "shuffle": 42,
        "logs": base64.b64encode(pickle.dumps(df)).decode(
            "utf-8"
        ),  # Required for EvalLogTranscripts
    }

    t = transcripts_from_spec(spec)

    assert t.type() == "eval_log"
    assert t._where == []
    assert t._limit == 5
    assert t._shuffle == 42


def test_factory_with_unknown_type():
    """Test factory function raises error for unknown type."""
    spec = {
        "type": "unknown_type",
        "where": base64.b64encode(pickle.dumps([])).decode("utf-8"),
        "limit": None,
        "shuffle": False,
    }

    with pytest.raises(ValueError, match="Unrecognized transcript type"):
        transcripts_from_spec(spec)


def test_factory_missing_type():
    """Test factory function handles missing type field."""
    spec = {
        "where": base64.b64encode(pickle.dumps([])).decode("utf-8"),
        "limit": None,
        "shuffle": False,
    }

    with pytest.raises(ValueError, match="Unrecognized transcript type"):
        transcripts_from_spec(spec)


# ============================================================================
# Edge Cases Tests
# ============================================================================


def test_empty_where_list():
    """Test save/load with empty where list."""
    df = create_test_dataframe(10)
    t1 = transcripts(df)  # No filters

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    assert t2._where == []


def test_deeply_nested_conditions():
    """Test save/load with deeply nested logical conditions."""
    df = create_test_dataframe(20)
    condition = (
        ((m.model == "gpt-4") & (m.score > 0.8))
        | ((m.model == "claude") & (m.score > 0.7))
        | ((m.model == "gemini") & (m.score > 0.6))
    ) & (m.status != "error")

    t1 = transcripts(df).where(condition)

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    # Complex condition should be preserved
    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


def test_json_path_conditions():
    """Test save/load with JSON path conditions."""
    df = create_test_dataframe(20)
    t1 = transcripts(df).where(m["metadata.config.temperature"] > 0.7)

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


def test_special_characters_in_values():
    """Test save/load with special characters in filter values."""
    df = create_test_dataframe(20)
    t1 = transcripts(df).where(m.path == "path/with'quotes\"and\\backslash")

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


def test_boolean_conditions():
    """Test save/load with boolean value conditions."""
    df = create_test_dataframe(20)
    t1 = transcripts(df).where(m.is_active == True)  # noqa: E712

    spec = t1.save_spec()
    t2 = transcripts_from_spec(spec)

    sql1, params1 = t1._where[0].to_sql("sqlite")
    sql2, params2 = t2._where[0].to_sql("sqlite")
    assert sql1 == sql2
    assert params1 == params2


# ============================================================================
# Chained Operations Tests
# ============================================================================


def test_all_operations_chained():
    """Test save/load with all operations chained together."""
    df = create_test_dataframe(30)
    t1 = (
        transcripts(df)
        .where(m.model.in_(["gpt-4", "claude"]))
        .where(m.score > 0.6)
        .where(m.status != "error")
        .limit(15)
        .shuffle(seed=999)
    )

    spec = t1.save_spec()

    # Verify all fields in spec
    assert spec["type"] == "eval_log"
    assert spec["limit"] == 15
    assert spec["shuffle"] == 999

    # Load and verify
    t2 = transcripts_from_spec(spec)

    assert t2._limit == 15
    assert t2._shuffle == 999
    assert len(t2._where) == 3

    # Verify conditions match
    for cond1, cond2 in zip(t1._where, t2._where):
        sql1, params1 = cond1.to_sql("sqlite")
        sql2, params2 = cond2.to_sql("sqlite")
        assert sql1 == sql2
        assert params1 == params2


def test_order_independence():
    """Test that order of limit/shuffle doesn't matter for spec."""
    df = create_test_dataframe(20)

    # Different orders
    t1 = transcripts(df).limit(10).shuffle(42).where(m.score > 0.5)
    t2 = transcripts(df).where(m.score > 0.5).shuffle(42).limit(10)
    t3 = transcripts(df).shuffle(42).where(m.score > 0.5).limit(10)

    # All should produce equivalent specs
    spec1 = t1.save_spec()
    spec2 = t2.save_spec()
    spec3 = t3.save_spec()

    # Check non-where fields
    assert spec1["limit"] == spec2["limit"] == spec3["limit"] == 10
    assert spec1["shuffle"] == spec2["shuffle"] == spec3["shuffle"] == 42

    # Where conditions should be in the order they were added
    assert len(pickle.loads(base64.b64decode(spec1["where"]))) == 1
    assert len(pickle.loads(base64.b64decode(spec2["where"]))) == 1
    assert len(pickle.loads(base64.b64decode(spec3["where"]))) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
