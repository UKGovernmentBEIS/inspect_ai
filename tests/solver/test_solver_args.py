"""Tests for solver_args vs solver_args_passed distinction.

These tests validate the feature that captures all solver arguments (including defaults)
in solver_args while only capturing explicitly passed arguments in solver_args_passed.
"""

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._util.registry import registry_params
from inspect_ai.agent import agent
from inspect_ai.agent._as_solver import as_solver
from inspect_ai.dataset import Sample
from inspect_ai.log._log import migrate_values
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
)
from inspect_ai.solver._constants import SOLVER_ALL_PARAMS_ATTR


@task
def simple_task():
    return Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        solver=generate(),
    )


@solver
def solver_with_defaults(rate: float = 0.5, mode: str = "fast"):
    """Solver with default parameters for testing args vs args_passed."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return await generate(state)

    return solve


def test_solver_args_vs_args_passed():
    """Test that solver_args includes defaults while solver_args_passed doesn't."""
    # Only pass 'rate', let 'mode' use default
    log = eval(
        simple_task(), solver=solver_with_defaults(rate=0.8), model="mockllm/model"
    )[0]

    # solver_args should include ALL params (with defaults applied)
    assert log.eval.solver_args == {"rate": 0.8, "mode": "fast"}

    # solver_args_passed should only include explicitly passed params
    assert log.eval.solver_args_passed == {"rate": 0.8}


def test_solver_args_no_params_passed():
    """Test solver with no explicit params - all defaults."""
    log = eval(simple_task(), solver=solver_with_defaults(), model="mockllm/model")[0]

    # solver_args should include all defaults
    assert log.eval.solver_args == {"rate": 0.5, "mode": "fast"}

    # solver_args_passed should be empty
    assert log.eval.solver_args_passed == {}


def test_retry_uses_args_passed():
    """Test that retry correctly reconstructs using only passed args."""
    # Create solver passing only 'rate', not 'mode'
    log = eval(
        simple_task(), solver=solver_with_defaults(rate=0.8), model="mockllm/model"
    )[0]

    # Verify initial state
    assert log.eval.solver_args == {"rate": 0.8, "mode": "fast"}
    assert log.eval.solver_args_passed == {"rate": 0.8}

    # Retry should reconstruct with only passed args
    retry_log = eval_retry(log)[0]

    # Should still have correct values after retry
    assert retry_log.eval.solver_args == {"rate": 0.8, "mode": "fast"}
    assert retry_log.eval.solver_args_passed == {"rate": 0.8}


def test_migrate_old_log_without_solver_args_passed():
    """Test that old logs without solver_args_passed are correctly migrated."""
    # Simulate old log data without solver_args_passed
    old_values = {
        "solver_args": {"rate": 1.0, "mode": "slow"},
        # No solver_args_passed field - simulating old log format
    }

    migrated = migrate_values(old_values)

    # Should copy solver_args to solver_args_passed for backwards compatibility
    assert migrated["solver_args_passed"] == {"rate": 1.0, "mode": "slow"}
    # Original solver_args should be preserved
    assert migrated["solver_args"] == {"rate": 1.0, "mode": "slow"}


def test_migrate_preserves_existing_solver_args_passed():
    """Test that migration doesn't overwrite existing solver_args_passed."""
    values = {
        "solver_args": {"rate": 1.0, "mode": "slow"},
        "solver_args_passed": {"rate": 1.0},  # Already has the field
    }

    migrated = migrate_values(values)

    # Should NOT overwrite existing solver_args_passed
    assert migrated["solver_args_passed"] == {"rate": 1.0}


@agent
def sample_agent_with_params(temperature: float = 0.7, max_tokens: int = 100):
    """Sample agent with parameters for testing."""

    async def run(state):
        return state

    return run


def test_agent_params_forwarded_to_solver():
    """Test that agent params are correctly forwarded when converted to solver."""
    # Create agent with explicit temperature, default max_tokens
    ag = sample_agent_with_params(temperature=0.9)
    slv = as_solver(ag)

    # All params should be forwarded (including defaults)
    assert getattr(slv, SOLVER_ALL_PARAMS_ATTR) == {
        "temperature": 0.9,
        "max_tokens": 100,
    }

    # Only passed params should be in registry_params
    assert registry_params(slv) == {"temperature": 0.9}


def my_custom_function():
    """A custom function for testing callable serialization."""
    pass


@solver
def solver_with_callable(fn=my_custom_function):
    """Solver that accepts a callable parameter."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return await generate(state)

    return solve


def test_callable_param_serialization():
    """Test that callable params are serialized to their names."""
    log = eval(simple_task(), solver=solver_with_callable(), model="mockllm/model")[0]

    # Callable should be serialized to its name
    assert log.eval.solver_args["fn"] == "my_custom_function"
    assert log.eval.solver_args_passed == {}  # Using default, so nothing passed


def test_callable_param_serialization_explicit():
    """Test callable param serialization when explicitly passed."""

    def another_function():
        pass

    log = eval(
        simple_task(),
        solver=solver_with_callable(fn=another_function),
        model="mockllm/model",
    )[0]

    # Callable should be serialized to its name
    assert log.eval.solver_args["fn"] == "another_function"
    assert log.eval.solver_args_passed["fn"] == "another_function"
