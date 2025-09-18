"""Tests for the LogMetadata typed interface for transcript queries."""

import json
import uuid

import pandas as pd
import pytest

from inspect_ai.scanner._transcript.database import EvalLogTranscriptsDB
from inspect_ai.scanner._transcript.log import LogMetadata
from inspect_ai.scanner._transcript.log import log_metadata as lm
from inspect_ai.scanner._transcript.metadata import metadata as m
from inspect_ai.scanner._transcript.transcripts import transcripts


def create_log_dataframe(num_samples: int = 10) -> pd.DataFrame:
    """Create a test DataFrame with Inspect log columns."""
    data = []
    for i in range(num_samples):
        data.append(
            {
                # ID columns
                "sample_id": f"sample_{i:03d}_{uuid.uuid4().hex[:8]}",
                "eval_id": f"eval_{uuid.uuid4().hex[:8]}",
                "eval_set_id": f"set_{uuid.uuid4().hex[:8]}" if i % 2 == 0 else None,
                "run_id": f"run_{uuid.uuid4().hex[:8]}",
                "task_id": f"task_{uuid.uuid4().hex[:8]}",
                # Log path
                "log": f"/path/to/log_{i:03d}.json",
                # Eval info
                "created": f"2024-01-{(i % 28) + 1:02d}T10:00:00",
                "tags": json.dumps(
                    ["prod", "test", "dev"][i % 3]
                ),  # Serialize list to JSON
                "git_origin": "https://github.com/example/repo.git",
                "git_commit": f"commit_{uuid.uuid4().hex[:8]}",
                "packages": json.dumps(
                    {"inspect": "1.0.0", "numpy": "1.24.0"}
                ),  # Serialize dict to JSON
                "metadata": json.dumps(
                    {"experiment": f"exp_{i}", "version": "1.0"}
                ),  # Serialize dict to JSON
                # Task configuration
                "task_name": ["math_problem", "code_gen", "reasoning"][i % 3],
                "task_display_name": ["Math", "Code", "Reasoning"][i % 3],
                "task_version": f"{i % 3}.0.0",
                "task_file": f"tasks/{['math', 'code', 'reason'][i % 3]}.py",
                "task_attribs": json.dumps(
                    {"difficulty": ["easy", "medium", "hard"][i % 3]}
                ),  # Serialize dict
                "task_arg_temperature": 0.7 + (i % 3) * 0.1,  # Dynamic task_arg_*
                "task_arg_max_tokens": 1000 + (i % 5) * 500,
                "solver": ["cot", "react", "basic"][i % 3],
                "solver_args": json.dumps({"steps": i % 5 + 1}),  # Serialize dict
                "sandbox_type": ["docker", "local", None][i % 3],
                "sandbox_config": json.dumps({"memory": "2G"})
                if i % 3 != 2
                else None,  # Serialize dict
                # Model configuration
                "model": ["gpt-4", "claude-3", "gemini-pro"][i % 3],
                "model_base_url": "https://api.example.com",
                "model_args": json.dumps({"api_key": "secret"}),  # Serialize dict
                "model_generate_config": json.dumps(
                    {"temperature": 0.7}
                ),  # Serialize dict
                "model_roles": json.dumps(
                    {"assistant": {"model": "gpt-3.5"}}
                ),  # Serialize dict
                # Dataset
                "dataset_name": ["train", "test", "validation"][i % 3],
                "dataset_location": f"/data/{['train', 'test', 'val'][i % 3]}.jsonl",
                "dataset_samples": 100 + i * 10,
                "dataset_sample_ids": json.dumps(
                    list(range(i * 10, (i + 1) * 10))
                ),  # Serialize list
                "dataset_shuffled": i % 2 == 0,
                # Eval configuration
                "epochs": (i % 3) + 1,
                "epochs_reducer": ["mean", "median", "max"][i % 3],
                "approval": "auto" if i % 2 == 0 else "manual",
                "message_limit": 50 + i * 10,
                "token_limit": 4000 + i * 100,
                "time_limit": 300 + i * 30,
                "working_limit": 200 + i * 20,
                # Results
                "status": ["success", "error", "cancelled"][i % 3],
                "error_message": "timeout error" if i % 3 == 1 else None,
                "error_traceback": "Traceback..." if i % 3 == 1 else None,
                "total_samples": 100,
                "completed_samples": 90 + i,
                "score_headline_name": "accuracy",
                "score_headline_metric": "mean",
                "score_headline_value": 0.7 + (i % 3) * 0.1,
                "score_headline_stderr": 0.05,
                # Dynamic score columns
                "score_accuracy": 0.7 + (i % 10) * 0.03,
                "score_f1": 0.65 + (i % 10) * 0.03,
                # Sample-level data
                "id": i,  # Sample id within eval
                "epoch": (i % 2) + 1,
                "input": f"Question {i}: What is 2 + 2?",
                "target": "4",
                "model_usage": json.dumps(
                    {"prompt_tokens": 100 + i * 10, "completion_tokens": 50 + i * 5}
                ),  # Serialize dict
                "total_time": 10.5 + i * 0.5,
                "working_time": 8.2 + i * 0.4,
                "error": "connection timeout" if i % 5 == 4 else None,
                "limit": "token" if i % 4 == 3 else None,
                "retries": i % 3,
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
    assert lm.eval_set_id.name == "eval_set_id"
    assert lm.run_id.name == "run_id"
    assert lm.task_id.name == "task_id"

    # Log path
    assert lm.log.name == "log"

    # Eval info columns
    assert lm.created.name == "created"
    assert lm.tags.name == "tags"
    assert lm.git_origin.name == "git_origin"
    assert lm.git_commit.name == "git_commit"
    assert lm.packages.name == "packages"
    assert lm.metadata.name == "metadata"

    # Task configuration columns
    assert lm.task_name.name == "task_name"
    assert lm.task_display_name.name == "task_display_name"
    assert lm.task_version.name == "task_version"
    assert lm.task_file.name == "task_file"
    assert lm.task_attribs.name == "task_attribs"
    assert lm.solver.name == "solver"
    assert lm.solver_args.name == "solver_args"
    assert lm.sandbox_type.name == "sandbox_type"
    assert lm.sandbox_config.name == "sandbox_config"

    # Model configuration columns
    assert lm.model.name == "model"
    assert lm.model_base_url.name == "model_base_url"
    assert lm.model_args.name == "model_args"
    assert lm.model_generate_config.name == "model_generate_config"
    assert lm.model_roles.name == "model_roles"

    # Dataset columns
    assert lm.dataset_name.name == "dataset_name"
    assert lm.dataset_location.name == "dataset_location"
    assert lm.dataset_samples.name == "dataset_samples"
    assert lm.dataset_sample_ids.name == "dataset_sample_ids"
    assert lm.dataset_shuffled.name == "dataset_shuffled"

    # Eval configuration columns
    assert lm.epochs.name == "epochs"
    assert lm.epochs_reducer.name == "epochs_reducer"
    assert lm.approval.name == "approval"
    assert lm.message_limit.name == "message_limit"
    assert lm.token_limit.name == "token_limit"
    assert lm.time_limit.name == "time_limit"
    assert lm.working_limit.name == "working_limit"

    # Results columns
    assert lm.status.name == "status"
    assert lm.error_message.name == "error_message"
    assert lm.error_traceback.name == "error_traceback"
    assert lm.total_samples.name == "total_samples"
    assert lm.completed_samples.name == "completed_samples"
    assert lm.score_headline_name.name == "score_headline_name"
    assert lm.score_headline_metric.name == "score_headline_metric"
    assert lm.score_headline_value.name == "score_headline_value"
    assert lm.score_headline_stderr.name == "score_headline_stderr"

    # Sample-level columns
    assert lm.id.name == "id"
    assert lm.epoch.name == "epoch"
    assert lm.input.name == "input"
    assert lm.target.name == "target"
    assert lm.model_usage.name == "model_usage"
    assert lm.total_time.name == "total_time"
    assert lm.working_time.name == "working_time"
    assert lm.error.name == "error"
    assert lm.limit.name == "limit"
    assert lm.retries.name == "retries"
    assert lm.messages.name == "messages"


def test_typed_properties_have_docstrings():
    """Test that typed properties have meaningful docstrings."""
    # Properties are descriptors, so we need to check their fget docstrings
    assert "Globally unique id for eval" in LogMetadata.eval_id.fget.__doc__
    assert "Model used for eval" in LogMetadata.model.fget.__doc__
    assert "Task name" in LogMetadata.task_name.fget.__doc__
    assert (
        "Number of samples in the dataset" in LogMetadata.dataset_samples.fget.__doc__
    )
    assert "Number of epochs to run samples over" in LogMetadata.epochs.fget.__doc__
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

    # Status equality
    condition = lm.status == "success"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"status" = ?'
    assert params == ["success"]


def test_sql_generation_comparison_operators():
    """Test SQL generation for comparison operators using typed properties."""
    # Greater than
    condition = lm.epochs > 1
    sql, params = condition.to_sql("sqlite")
    assert sql == '"epochs" > ?'
    assert params == [1]

    # Less than or equal
    condition = lm.dataset_samples <= 1000
    sql, params = condition.to_sql("sqlite")
    assert sql == '"dataset_samples" <= ?'
    assert params == [1000]

    # Greater than or equal
    condition = lm.score_headline_value >= 0.8
    sql, params = condition.to_sql("sqlite")
    assert sql == '"score_headline_value" >= ?'
    assert params == [0.8]

    # Not equal
    condition = lm.sandbox_type != "docker"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"sandbox_type" != ?'
    assert params == ["docker"]


def test_sql_generation_complex_conditions():
    """Test SQL generation for complex conditions using typed properties."""
    # AND condition
    condition = (lm.model == "gpt-4") & (lm.epochs > 1)
    sql, params = condition.to_sql("sqlite")
    assert sql == '("model" = ? AND "epochs" > ?)'
    assert params == ["gpt-4", 1]

    # OR condition
    condition = (lm.status == "error") | (lm.retries > 2)
    sql, params = condition.to_sql("sqlite")
    assert sql == '("status" = ? OR "retries" > ?)'
    assert params == ["error", 2]

    # Complex nested
    condition = (
        ((lm.model == "gpt-4") & (lm.dataset_samples > 100))
        | ((lm.model == "claude-3") & (lm.dataset_samples > 50))
    ) & (lm.status == "success")

    sql, params = condition.to_sql("sqlite")
    assert "AND" in sql
    assert "OR" in sql
    assert len(params) == 5


def test_sql_generation_null_handling():
    """Test SQL generation for NULL handling using typed properties."""
    # IS NULL
    condition = lm.error_message.is_null()
    sql, params = condition.to_sql("sqlite")
    assert sql == '"error_message" IS NULL'
    assert params == []

    # IS NOT NULL
    condition = lm.sandbox_config.is_not_null()
    sql, params = condition.to_sql("sqlite")
    assert sql == '"sandbox_config" IS NOT NULL'
    assert params == []

    # == None should map to IS NULL
    condition = lm.error_traceback == None  # noqa: E711
    sql, params = condition.to_sql("sqlite")
    assert sql == '"error_traceback" IS NULL'
    assert params == []

    # != None should map to IS NOT NULL
    condition = lm.eval_set_id != None  # noqa: E711
    sql, params = condition.to_sql("sqlite")
    assert sql == '"eval_set_id" IS NOT NULL'
    assert params == []


def test_sql_generation_in_operators():
    """Test SQL generation for IN operators using typed properties."""
    # IN
    condition = lm.model.in_(["gpt-4", "claude-3", "gemini"])
    sql, params = condition.to_sql("sqlite")
    assert sql == '"model" IN (?, ?, ?)'
    assert params == ["gpt-4", "claude-3", "gemini"]

    # NOT IN
    condition = lm.status.not_in(["error", "cancelled"])
    sql, params = condition.to_sql("sqlite")
    assert sql == '"status" NOT IN (?, ?)'
    assert params == ["error", "cancelled"]


def test_sql_generation_like_operators():
    """Test SQL generation for LIKE operators using typed properties."""
    # LIKE
    condition = lm.task_file.like("%.py")
    sql, params = condition.to_sql("sqlite")
    assert sql == '"task_file" LIKE ?'
    assert params == ["%.py"]

    # NOT LIKE
    condition = lm.dataset_location.not_like("/tmp/%")
    sql, params = condition.to_sql("sqlite")
    assert sql == '"dataset_location" NOT LIKE ?'
    assert params == ["/tmp/%"]

    # ILIKE (case-insensitive)
    condition = lm.error_message.ilike("%TIMEOUT%")
    sql, params = condition.to_sql("sqlite")
    assert sql == 'LOWER("error_message") LIKE LOWER(?)'
    assert params == ["%TIMEOUT%"]


def test_sql_generation_between_operators():
    """Test SQL generation for BETWEEN operators using typed properties."""
    # BETWEEN
    condition = lm.epochs.between(1, 5)
    sql, params = condition.to_sql("sqlite")
    assert sql == '"epochs" BETWEEN ? AND ?'
    assert params == [1, 5]

    # NOT BETWEEN
    condition = lm.total_time.not_between(10.0, 20.0)
    sql, params = condition.to_sql("sqlite")
    assert sql == '"total_time" NOT BETWEEN ? AND ?'
    assert params == [10.0, 20.0]


def test_sql_generation_different_dialects():
    """Test SQL generation works across different SQL dialects."""
    condition = (lm.model == "gpt-4") & (lm.epochs > 1)

    # SQLite
    sql, params = condition.to_sql("sqlite")
    assert sql == '("model" = ? AND "epochs" > ?)'
    assert params == ["gpt-4", 1]

    # PostgreSQL - uses $1, $2 placeholders
    sql, params = condition.to_sql("postgres")
    assert sql == '("model" = $1 AND "epochs" > $2)'
    assert params == ["gpt-4", 1]

    # DuckDB
    sql, params = condition.to_sql("duckdb")
    assert sql == '("model" = ? AND "epochs" > ?)'
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

    # Access task_arg_* columns
    condition = lm["task_arg_temperature"] == 0.7
    sql, params = condition.to_sql("sqlite")
    assert sql == '"task_arg_temperature" = ?'
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
    cond_log = (lm.epochs > 1) & (lm.dataset_samples >= 100)
    cond_base = (m.epochs > 1) & (m.dataset_samples >= 100)

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

    # Filter by epochs
    results = list(await db.query(where=[lm.epochs > 1]))
    for result in results:
        assert result.metadata["epochs"] > 1

    # Filter by dataset samples range
    results = list(await db.query(where=[lm.dataset_samples.between(100, 150)]))
    for result in results:
        assert 100 <= result.metadata["dataset_samples"] <= 150


@pytest.mark.asyncio
async def test_complex_query_with_typed_properties(db):
    """Test complex database queries using typed properties."""
    # Complex condition with multiple typed properties
    conditions = [
        (lm.model.in_(["gpt-4", "claude-3"])) & (lm.epochs > 1),
        lm.status == "success",
    ]

    results = list(await db.query(where=conditions))
    for result in results:
        assert result.metadata["model"] in ["gpt-4", "claude-3"]
        assert result.metadata["epochs"] > 1
        assert result.metadata["status"] == "success"


@pytest.mark.asyncio
async def test_count_with_typed_properties(db):
    """Test counting records using typed properties."""
    # Count all successful runs
    count = await db.count(where=[lm.status == "success"])

    # Verify count matches query
    results = list(await db.query(where=[lm.status == "success"]))
    assert count == len(results)

    # Count with complex condition
    count = await db.count(where=[(lm.model == "gpt-4") & (lm.dataset_samples > 100)])
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
    count = await filtered.count()
    assert count > 0

    # Chain multiple filters
    filtered = (
        t.where(lm.model == "gpt-4").where(lm.epochs > 1).where(lm.status == "success")
    )

    # Collect and verify results
    results = []
    async for transcript in filtered.collect():
        results.append(transcript)
        assert transcript.metadata["model"] == "gpt-4"
        assert transcript.metadata["epochs"] > 1
        assert transcript.metadata["status"] == "success"


@pytest.mark.asyncio
async def test_transcripts_complex_filtering():
    """Test complex filtering scenarios with Transcripts and LogMetadata."""
    df = create_log_dataframe(30)
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    try:
        # Complex multi-condition filter
        conditions = [
            ((lm.model == "gpt-4") & (lm.dataset_samples > 100))
            | ((lm.model == "claude-3") & (lm.dataset_samples > 50)),
            lm.error_message.is_null(),
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
                assert meta["dataset_samples"] > 100
            elif meta["model"] == "claude-3":
                assert meta["dataset_samples"] > 50
            else:
                pytest.fail(f"Unexpected model: {meta['model']}")

            # Check error_message is null/not present
            assert meta.get("error_message") is None
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
        conditions = [lm.status == "success"]

        # Query with shuffle and limit
        results = list(await db.query(conditions, limit=5, shuffle=42))

        for result in results:
            assert result.metadata["status"] == "success"

        assert len(results) <= 5
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

    # 'input' is also a builtin
    condition = lm.input == "test input"
    sql, params = condition.to_sql("sqlite")
    assert sql == '"input" = ?'
    assert params == ["test input"]


def test_all_operators_with_typed_properties():
    """Test that all operators work with typed properties."""
    # Test each operator type
    operators_tests = [
        (lm.epochs == 2, '"epochs" = ?', [2]),
        (lm.epochs != 2, '"epochs" != ?', [2]),
        (lm.epochs > 2, '"epochs" > ?', [2]),
        (lm.epochs >= 2, '"epochs" >= ?', [2]),
        (lm.epochs < 2, '"epochs" < ?', [2]),
        (lm.epochs <= 2, '"epochs" <= ?', [2]),
        (lm.model.in_(["a", "b"]), '"model" IN (?, ?)', ["a", "b"]),
        (lm.model.not_in(["a", "b"]), '"model" NOT IN (?, ?)', ["a", "b"]),
        (lm.task_file.like("%.py"), '"task_file" LIKE ?', ["%.py"]),
        (lm.task_file.not_like("%.py"), '"task_file" NOT LIKE ?', ["%.py"]),
        (lm.error.is_null(), '"error" IS NULL', []),
        (lm.error.is_not_null(), '"error" IS NOT NULL', []),
        (lm.epochs.between(1, 3), '"epochs" BETWEEN ? AND ?', [1, 3]),
        (lm.epochs.not_between(1, 3), '"epochs" NOT BETWEEN ? AND ?', [1, 3]),
    ]

    for condition, expected_sql, expected_params in operators_tests:
        sql, params = condition.to_sql("sqlite")
        assert sql == expected_sql
        assert params == expected_params


def test_chaining_operations():
    """Test that operations can be chained naturally."""
    # Build up a complex query step by step
    condition = lm.model == "gpt-4"
    condition = condition & (lm.epochs > 1)
    condition = condition & (lm.dataset_samples >= 100)
    condition = condition | (lm.status == "error")

    sql, params = condition.to_sql("sqlite")
    assert "AND" in sql
    assert "OR" in sql
    assert len(params) == 4


@pytest.mark.asyncio
async def test_empty_dataframe_with_log_metadata():
    """Test LogMetadata works with empty DataFrames."""
    df = pd.DataFrame(columns=["sample_id", "log", "model", "epochs"])
    db = EvalLogTranscriptsDB(df)
    await db.connect()

    # Query with typed properties on empty DB
    results = list(await db.query(where=[lm.model == "gpt-4"]))
    assert len(results) == 0

    count = await db.count(where=[lm.epochs > 1])
    assert count == 0

    await db.disconnect()


def test_type_hints_preserved():
    """Test that type hints are preserved and work correctly."""
    from inspect_ai.scanner._transcript.metadata import Column

    # Verify that properties return Column type
    assert isinstance(lm.model, Column)
    assert isinstance(lm.epochs, Column)
    assert isinstance(lm.dataset_samples, Column)

    # Verify that operations return Condition type
    from inspect_ai.scanner._transcript.metadata import Condition

    condition = lm.model == "gpt-4"
    assert isinstance(condition, Condition)

    complex_condition = (lm.epochs > 1) & (lm.status == "success")
    assert isinstance(complex_condition, Condition)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
