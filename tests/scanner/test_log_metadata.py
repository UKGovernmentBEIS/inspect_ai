"""Tests for the LogMetadata typed interface for transcript queries."""

import json
import uuid

import pandas as pd
import pytest

from inspect_ai.scanner._transcript.database import EvalLogTranscriptsDB, transcripts
from inspect_ai.scanner._transcript.log import LogMetadata
from inspect_ai.scanner._transcript.log import log_metadata as lm
from inspect_ai.scanner._transcript.metadata import metadata as m
from inspect_ai.scanner._transcript.types import TranscriptContent


def create_log_dataframe(num_samples: int = 10) -> pd.DataFrame:
    """Create a test DataFrame with Inspect log columns."""
    data = []
    for i in range(num_samples):
        data.append(
            {
                # ID columns
                "sample_id": f"sample_{i:03d}_{uuid.uuid4().hex[:8]}",
                "eval_id": f"eval_{uuid.uuid4().hex[:8]}",
                "log": f"/path/to/log_{i:03d}.json",
                # Eval info
                "eval_created": f"2024-01-{(i % 28) + 1:02d}T10:00:00",
                "eval_tags": json.dumps(
                    ["prod", "test", "dev"][i % 3]
                ),  # Serialize list to JSON
                "eval_metadata": json.dumps(
                    {"experiment": f"exp_{i}", "version": "1.0"}
                ),  # Serialize dict to JSON
                # Task configuration
                "task_name": ["math_problem", "code_gen", "reasoning"][i % 3],
                "task_args": json.dumps({"temperature": 0.7 + (i % 3) * 0.1}),
                "solver": ["cot", "react", "basic"][i % 3],
                "solver_args": json.dumps({"steps": i % 5 + 1}),  # Serialize dict
                # Model configuration
                "model": ["gpt-4", "claude-3", "gemini-pro"][i % 3],
                "generate_config": json.dumps({"temperature": 0.7}),  # Serialize dict
                "model_roles": json.dumps(
                    {"assistant": {"model": "gpt-3.5"}}
                ),  # Serialize dict
                # Sample-level data
                "id": i,  # Sample id within eval
                "epoch": (i % 2) + 1,
                "sample_metadata": json.dumps({"custom": f"value_{i}"}),
                "score": 0.7 + (i % 10) * 0.03,
                # Dynamic score columns
                "score_accuracy": 0.7 + (i % 10) * 0.03,
                "score_f1": 0.65 + (i % 10) * 0.03,
                "total_tokens": 150 + i * 15,
                "total_time": 10.5 + i * 0.5,
                "working_time": 8.2 + i * 0.4,
                "limit": "token" if i % 4 == 3 else None,
                "messages": f"[Message history for sample {i}]",
                # Custom metadata fields
                "metadata_custom": f"custom_value_{i}",
                "metadata_experiment_id": f"exp_{i:03d}",
            }
        )
    return pd.DataFrame(data)


@pytest.fixture
async def db():
    """Create and connect to a test database."""
    df = create_log_dataframe(20)
    db = EvalLogTranscriptsDB(df)
    await db.connect()
    yield db
    await db.disconnect()


# ============================================================================
# Typed Interface Tests
# ============================================================================


def test_typed_properties_exist():
    """Test that all typed properties exist and return Column objects."""
    # ID columns
    assert lm.sample_id.name == "sample_id"
    assert lm.eval_id.name == "eval_id"
    assert lm.log.name == "log"

    # Eval info columns
    assert lm.eval_created.name == "eval_created"
    assert lm.eval_tags.name == "eval_tags"
    assert lm.eval_metadata.name == "eval_metadata"

    # Task configuration columns
    assert lm.task_name.name == "task_name"
    assert lm.task_args.name == "task_args"
    assert lm.solver.name == "solver"
    assert lm.solver_args.name == "solver_args"

    # Model configuration columns
    assert lm.model.name == "model"
    assert lm.generate_config.name == "generate_config"
    assert lm.model_roles.name == "model_roles"

    # Sample-level columns
    assert lm.id.name == "id"
    assert lm.epoch.name == "epoch"
    assert lm.sample_metadata.name == "sample_metadata"
    assert lm.score.name == "score"
    assert lm.total_tokens.name == "total_tokens"
    assert lm.total_time.name == "total_time"
    assert lm.working_time.name == "working_time"
    assert lm.limit.name == "limit"


def test_typed_properties_have_docstrings():
    """Test that typed properties have meaningful docstrings."""
    # Properties are descriptors, so we need to check their fget docstrings
    assert "Globally unique id for eval" in LogMetadata.eval_id.fget.__doc__
    assert "Model used for eval" in LogMetadata.model.fget.__doc__
    assert "Task name" in LogMetadata.task_name.fget.__doc__
    assert "Headline score value" in LogMetadata.score.fget.__doc__
    assert (
        "Total time that the sample was running" in LogMetadata.total_time.fget.__doc__
    )


# ============================================================================
# SQL Generation Tests
# ============================================================================


def test_sql_generation_simple_equality():
    """Test SQL generation for simple equality using typed properties."""
    # Model equality
    condition = lm.model == "gpt-4"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"model" = ?'
    assert params == ["gpt-4"]

    # Task name equality
    condition = lm.task_name == "math_problem"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"task_name" = ?'
    assert params == ["math_problem"]

    # Solver equality
    condition = lm.solver == "cot"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"solver" = ?'
    assert params == ["cot"]


def test_sql_generation_comparison_operators():
    """Test SQL generation for comparison operators using typed properties."""
    # Greater than
    condition = lm.epoch > 1
    sql, params = condition.to_sql("sqlite")
    assert sql == '"epoch" > ?'
    assert params == [1]

    # Less than or equal
    condition = lm.total_tokens <= 1000
    sql, params = condition.to_sql("sqlite")
    assert sql == '"total_tokens" <= ?'
    assert params == [1000]

    # Greater than or equal
    condition = lm.score >= 0.8
    sql, params = condition.to_sql("sqlite")
    assert sql == '"score" >= ?'
    assert params == [0.8]

    # Not equal
    condition = lm.solver != "cot"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"solver" != ?'
    assert params == ["cot"]


def test_sql_generation_complex_conditions():
    """Test SQL generation for complex conditions using typed properties."""
    # AND condition
    condition = (lm.model == "gpt-4") & (lm.epoch > 1)
    sql, params = condition.to_sql("sqlite")
    assert sql == '("model" = ? AND "epoch" > ?)'
    assert params == ["gpt-4", 1]

    # OR condition
    condition = (lm.solver == "cot") | (lm.total_time > 10.0)
    sql, params = condition.to_sql("sqlite")
    assert sql == '("solver" = ? OR "total_time" > ?)'
    assert params == ["cot", 10.0]

    # Complex nested
    condition = (
        ((lm.model == "gpt-4") & (lm.total_tokens > 100))
        | ((lm.model == "claude-3") & (lm.total_tokens > 50))
    ) & (lm.score > 0.8)

    sql, params = condition.to_sql("sqlite")
    assert "AND" in sql
    assert "OR" in sql
    assert len(params) == 5


def test_sql_generation_null_handling():
    """Test SQL generation for NULL handling using typed properties."""
    # IS NULL
    condition = lm.limit.is_null()
    sql, params = condition.to_sql("sqlite")
    assert sql == '"limit" IS NULL'
    assert params == []

    # IS NOT NULL
    condition = lm.sample_metadata.is_not_null()
    sql, params = condition.to_sql("sqlite")
    assert sql == '"sample_metadata" IS NOT NULL'
    assert params == []

    # == None should map to IS NULL
    condition = lm.limit == None  # noqa: E711
    sql, params = condition.to_sql("sqlite")
    assert sql == '"limit" IS NULL'
    assert params == []

    # != None should map to IS NOT NULL
    condition = lm.eval_metadata != None  # noqa: E711
    sql, params = condition.to_sql("sqlite")
    assert sql == '"eval_metadata" IS NOT NULL'
    assert params == []


def test_sql_generation_in_operators():
    """Test SQL generation for IN operators using typed properties."""
    # IN
    condition = lm.model.in_(["gpt-4", "claude-3", "gemini-pro"])
    sql, params = condition.to_sql("sqlite")
    assert sql == '"model" IN (?, ?, ?)'
    assert params == ["gpt-4", "claude-3", "gemini-pro"]

    # NOT IN
    condition = lm.solver.not_in(["cot", "react"])
    sql, params = condition.to_sql("sqlite")
    assert sql == '"solver" NOT IN (?, ?)'
    assert params == ["cot", "react"]


def test_sql_generation_like_operators():
    """Test SQL generation for LIKE operators using typed properties."""
    # LIKE
    condition = lm.task_name.like("math%")
    sql, params = condition.to_sql("sqlite")
    assert sql == '"task_name" LIKE ?'
    assert params == ["math%"]

    # NOT LIKE
    condition = lm.log.not_like("/tmp/%")
    sql, params = condition.to_sql("sqlite")
    assert sql == '"log" NOT LIKE ?'
    assert params == ["/tmp/%"]

    # ILIKE (case-insensitive)
    condition = lm.model.ilike("%GPT%")
    sql, params = condition.to_sql("sqlite")
    assert sql == 'LOWER("model") LIKE LOWER(?)'
    assert params == ["%GPT%"]


def test_sql_generation_between_operators():
    """Test SQL generation for BETWEEN operators using typed properties."""
    # BETWEEN
    condition = lm.epoch.between(1, 5)
    sql, params = condition.to_sql("sqlite")
    assert sql == '"epoch" BETWEEN ? AND ?'
    assert params == [1, 5]

    # NOT BETWEEN
    condition = lm.total_time.not_between(10.0, 20.0)
    sql, params = condition.to_sql("sqlite")
    assert sql == '"total_time" NOT BETWEEN ? AND ?'
    assert params == [10.0, 20.0]


def test_sql_generation_different_dialects():
    """Test SQL generation works across different SQL dialects."""
    condition = (lm.model == "gpt-4") & (lm.epoch > 1)

    # SQLite
    sql, params = condition.to_sql("sqlite")
    assert sql == '("model" = ? AND "epoch" > ?)'
    assert params == ["gpt-4", 1]

    # PostgreSQL - uses $1, $2 placeholders
    sql, params = condition.to_sql("postgres")
    assert sql == '("model" = $1 AND "epoch" > $2)'
    assert params == ["gpt-4", 1]

    # DuckDB
    sql, params = condition.to_sql("duckdb")
    assert sql == '("model" = ? AND "epoch" > ?)'
    assert params == ["gpt-4", 1]


# ============================================================================
# Dynamic Field Access Tests
# ============================================================================


def test_dynamic_field_access():
    """Test that dynamic fields work with LogMetadata."""
    # Access dynamic score columns
    condition = lm["score_accuracy"] > 0.9
    sql, params = condition.to_sql("sqlite")
    assert sql == '"score_accuracy" > ?'
    assert params == [0.9]

    # Access score_f1 column
    condition = lm["score_f1"] >= 0.7
    sql, params = condition.to_sql("sqlite")
    assert sql == '"score_f1" >= ?'
    assert params == [0.7]

    # Access metadata_* columns
    condition = lm["metadata_custom"] == "custom_value_1"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"metadata_custom" = ?'
    assert params == ["custom_value_1"]

    # Access completely custom fields
    condition = lm["my_custom_field"] < 100
    sql, params = condition.to_sql("sqlite")
    assert sql == '"my_custom_field" < ?'
    assert params == [100]


def test_nested_json_fields():
    """Test accessing nested JSON fields with LogMetadata."""
    # This tests that the base Metadata functionality is preserved
    condition = lm["config.nested.value"] > 10

    # SQLite - uses json_extract
    sql, params = condition.to_sql("sqlite")
    assert sql == "json_extract(\"config\", '$.nested.value') > ?"
    assert params == [10]

    # DuckDB - uses json_extract with type casting
    sql, params = condition.to_sql("duckdb")
    assert sql == "(json_extract(\"config\", '$.nested.value'))::BIGINT > ?"
    assert params == [10]


def test_json_metadata_fields():
    """Test querying nested values in eval_metadata and sample_metadata."""
    # Query nested field in eval_metadata
    condition = lm["eval_metadata.experiment"] == "exp_5"
    sql, params = condition.to_sql("sqlite")
    assert sql == "json_extract(\"eval_metadata\", '$.experiment') = ?"
    assert params == ["exp_5"]

    # Query nested field in sample_metadata
    condition = lm["sample_metadata.custom"] == "value_10"
    sql, params = condition.to_sql("sqlite")
    assert sql == "json_extract(\"sample_metadata\", '$.custom') = ?"
    assert params == ["value_10"]

    # Query nested field in task_args
    condition = lm["task_args.temperature"] >= 0.7
    sql, params = condition.to_sql("sqlite")
    assert sql == "json_extract(\"task_args\", '$.temperature') >= ?"
    assert params == [0.7]

    # Complex condition with JSON fields
    condition = (lm["eval_metadata.version"] == "1.0") & (lm.model == "gpt-4")
    sql, params = condition.to_sql("sqlite")
    assert "json_extract" in sql
    assert params == ["1.0", "gpt-4"]


# ============================================================================
# Backward Compatibility Tests
# ============================================================================


def test_backward_compatibility_with_base_metadata():
    """Test that LogMetadata is compatible with base Metadata."""
    # Both should generate identical SQL for the same conditions

    # Simple equality
    cond_log = lm.model == "gpt-4"
    cond_base = m.model == "gpt-4"

    sql_log, params_log = cond_log.to_sql("sqlite")
    sql_base, params_base = cond_base.to_sql("sqlite")

    assert sql_log == sql_base
    assert params_log == params_base

    # Complex condition
    cond_log = (lm.epoch > 1) & (lm.total_tokens >= 100)
    cond_base = (m.epoch > 1) & (m.total_tokens >= 100)

    sql_log, params_log = cond_log.to_sql("sqlite")
    sql_base, params_base = cond_base.to_sql("sqlite")

    assert sql_log == sql_base
    assert params_log == params_base

    # Dynamic field access
    cond_log = lm["custom_field"] > 50
    cond_base = m["custom_field"] > 50

    sql_log, params_log = cond_log.to_sql("sqlite")
    sql_base, params_base = cond_base.to_sql("sqlite")

    assert sql_log == sql_base
    assert params_log == params_base


def test_mixing_log_and_base_metadata():
    """Test that LogMetadata conditions can be mixed with base Metadata conditions."""
    # Mix LogMetadata and base Metadata in the same query
    condition = (lm.model == "gpt-4") & (m.score > 0.8)

    sql, params = condition.to_sql("sqlite")
    assert sql == '("model" = ? AND "score" > ?)'
    assert params == ["gpt-4", 0.8]


# ============================================================================
# Integration Tests with Database
# ============================================================================


@pytest.mark.asyncio
async def test_query_with_typed_properties(db):
    """Test database queries using typed properties."""
    # Filter by model
    results = list(await db.query(where=[lm.model == "gpt-4"]))
    for result in results:
        assert result.metadata["model"] == "gpt-4"

    # Filter by epoch
    results = list(await db.query(where=[lm.epoch > 1]))
    for result in results:
        assert result.metadata["epoch"] > 1

    # Filter by total tokens range
    results = list(await db.query(where=[lm.total_tokens.between(150, 300)]))
    for result in results:
        assert 150 <= result.metadata["total_tokens"] <= 300


@pytest.mark.asyncio
async def test_complex_query_with_typed_properties(db):
    """Test complex database queries using typed properties."""
    # Complex condition with multiple typed properties
    conditions = [
        (lm.model.in_(["gpt-4", "claude-3"])) & (lm.epoch > 1),
        lm.solver == "cot",
    ]

    results = list(await db.query(where=conditions))
    for result in results:
        assert result.metadata["model"] in ["gpt-4", "claude-3"]
        assert result.metadata["epoch"] > 1
        assert result.metadata["solver"] == "cot"


@pytest.mark.asyncio
async def test_count_with_typed_properties(db):
    """Test counting records using typed properties."""
    # Count all with specific model
    count = await db.count(where=[lm.model == "gpt-4"])

    # Verify count matches query
    results = list(await db.query(where=[lm.model == "gpt-4"]))
    assert count == len(results)

    # Count with complex condition
    count = await db.count(where=[(lm.model == "gpt-4") & (lm.total_tokens > 100)])
    assert count >= 0


# ============================================================================
# Integration Tests with Transcripts API
# ============================================================================


@pytest.mark.asyncio
async def test_transcripts_with_log_metadata():
    """Test using LogMetadata with the Transcripts API."""
    df = create_log_dataframe(20)
    t = transcripts(df)

    # Simple filter
    filtered = t.where(lm.model == "gpt-4")
    async with filtered:
        count = await filtered.count()
        assert count > 0

    # Chain multiple filters
    filtered = (
        t.where(lm.model == "gpt-4").where(lm.epoch > 1).where(lm.solver == "cot")
    )

    # Collect and verify results
    results = []
    async with filtered:
        for info in await filtered.index():
            transcript = await filtered.read(
                info, TranscriptContent(messages="all", events="all")
            )
            results.append(transcript)
            assert transcript.metadata["model"] == "gpt-4"
            assert transcript.metadata["epoch"] > 1
            assert transcript.metadata["solver"] == "cot"


@pytest.mark.asyncio
async def test_transcripts_complex_filtering():
    """Test complex filtering scenarios with Transcripts and LogMetadata."""
    df = create_log_dataframe(30)
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    try:
        # Complex multi-condition filter
        conditions = [
            ((lm.model == "gpt-4") & (lm.total_tokens > 150))
            | ((lm.model == "claude-3") & (lm.total_tokens > 160)),
            lm.limit.is_null(),
        ]

        # Verify count
        count = await db.count(conditions)
        assert count >= 0

        # Verify results match conditions
        results = list(await db.query(conditions, limit=10))
        for result in results:
            meta = result.metadata

            # Check the OR condition
            if meta["model"] == "gpt-4":
                assert meta["total_tokens"] > 150
            elif meta["model"] == "claude-3":
                assert meta["total_tokens"] > 160
            else:
                pytest.fail(f"Unexpected model: {meta['model']}")

            # Check limit is null/not present
            assert meta.get("limit") is None
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_transcripts_with_shuffle_and_limit():
    """Test that shuffle and limit work with LogMetadata filters."""
    df = create_log_dataframe(20)
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    try:
        # Apply filter with shuffle and limit
        conditions = [lm.model == "gpt-4"]

        # Query with shuffle and limit
        results = list(await db.query(conditions, limit=5, shuffle=42))

        for result in results:
            assert result.metadata["model"] == "gpt-4"

        assert len(results) <= 5
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_query_json_metadata_fields():
    """Test querying nested JSON fields in metadata columns."""
    df = create_log_dataframe(20)
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    try:
        # Query by nested eval_metadata field
        conditions = [lm["eval_metadata.version"] == "1.0"]
        results = list(await db.query(conditions))

        # All results should have version 1.0 in their eval_metadata
        for result in results:
            metadata = json.loads(result.metadata.get("eval_metadata", "{}"))
            assert metadata.get("version") == "1.0"

        # Query by nested sample_metadata field
        conditions = [lm["sample_metadata.custom"].like("value_%")]
        results = list(await db.query(conditions))

        # Should get results with matching custom values
        assert len(results) > 0
        for result in results:
            sample_meta = json.loads(result.metadata.get("sample_metadata", "{}"))
            assert sample_meta.get("custom", "").startswith("value_")

        # Complex query combining regular and JSON fields
        conditions = [
            (lm.model == "gpt-4") & (lm["eval_metadata.experiment"].like("exp_%"))
        ]
        results = list(await db.query(conditions))

        for result in results:
            assert result.metadata["model"] == "gpt-4"
            eval_meta = json.loads(result.metadata.get("eval_metadata", "{}"))
            assert eval_meta.get("experiment", "").startswith("exp_")
    finally:
        await db.disconnect()


# ============================================================================
# Edge Cases and Special Scenarios
# ============================================================================


def test_special_column_names():
    """Test that special column names work correctly."""
    # Columns that might conflict with Python keywords or have special chars

    # 'id' is a builtin but should work as a property
    condition = lm.id > 5
    sql, params = condition.to_sql("sqlite")
    assert sql == '"id" > ?'
    assert params == [5]

    # Test sample_id
    condition = lm.sample_id == "sample_001"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"sample_id" = ?'
    assert params == ["sample_001"]


def test_all_operators_with_typed_properties():
    """Test that all operators work with typed properties."""
    # Test each operator type
    operators_tests = [
        (lm.epoch == 2, '"epoch" = ?', [2]),
        (lm.epoch != 2, '"epoch" != ?', [2]),
        (lm.epoch > 2, '"epoch" > ?', [2]),
        (lm.epoch >= 2, '"epoch" >= ?', [2]),
        (lm.epoch < 2, '"epoch" < ?', [2]),
        (lm.epoch <= 2, '"epoch" <= ?', [2]),
        (lm.model.in_(["a", "b"]), '"model" IN (?, ?)', ["a", "b"]),
        (lm.model.not_in(["a", "b"]), '"model" NOT IN (?, ?)', ["a", "b"]),
        (lm.task_name.like("math%"), '"task_name" LIKE ?', ["math%"]),
        (lm.task_name.not_like("code%"), '"task_name" NOT LIKE ?', ["code%"]),
        (lm.limit.is_null(), '"limit" IS NULL', []),
        (lm.limit.is_not_null(), '"limit" IS NOT NULL', []),
        (lm.epoch.between(1, 3), '"epoch" BETWEEN ? AND ?', [1, 3]),
        (lm.epoch.not_between(1, 3), '"epoch" NOT BETWEEN ? AND ?', [1, 3]),
    ]

    for condition, expected_sql, expected_params in operators_tests:
        sql, params = condition.to_sql("sqlite")
        assert sql == expected_sql
        assert params == expected_params


def test_chaining_operations():
    """Test that operations can be chained naturally."""
    # Build up a complex query step by step
    condition = lm.model == "gpt-4"
    condition = condition & (lm.epoch > 1)
    condition = condition & (lm.total_tokens >= 100)
    condition = condition | (lm.solver == "cot")

    sql, params = condition.to_sql("sqlite")
    assert "AND" in sql
    assert "OR" in sql
    assert len(params) == 4


@pytest.mark.asyncio
async def test_empty_dataframe_with_log_metadata():
    """Test LogMetadata works with empty DataFrames."""
    df = pd.DataFrame(columns=["sample_id", "eval_id", "log", "model", "epoch"])
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    # Query with typed properties on empty DB
    results = list(await db.query(where=[lm.model == "gpt-4"]))
    assert len(results) == 0

    count = await db.count(where=[lm.epoch > 1])
    assert count == 0

    await db.disconnect()


def test_type_hints_preserved():
    """Test that type hints are preserved and work correctly."""
    from inspect_ai.scanner._transcript.metadata import Column

    # Verify that properties return Column type
    assert isinstance(lm.model, Column)
    assert isinstance(lm.epoch, Column)
    assert isinstance(lm.total_tokens, Column)

    # Verify that operations return Condition type
    from inspect_ai.scanner._transcript.metadata import Condition

    condition = lm.model == "gpt-4"
    assert isinstance(condition, Condition)

    complex_condition = (lm.epoch > 1) & (lm.solver == "cot")
    assert isinstance(complex_condition, Condition)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
