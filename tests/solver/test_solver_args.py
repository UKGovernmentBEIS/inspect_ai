"""Tests for solver_args vs solver_args_passed distinction.

These tests validate the feature that captures all solver arguments (including defaults)
in solver_args while only capturing explicitly passed arguments in solver_args_passed.
"""

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._eval.loader import as_solver_spec, solver_from_spec
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


@solver
def solver_with_kwargs(base: str = "base", **kwargs):
    """Solver with a **kwargs parameter, for testing VAR_KEYWORD round-trips."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return await generate(state)

    return solve


def test_var_keyword_args_captured_flat():
    """**kwargs captured under their own names, not nested by param name (#4374)."""
    slv = solver_with_kwargs(base="hello", max_tokens=123, temperature=0.5)

    assert registry_params(slv) == {
        "base": "hello",
        "max_tokens": 123,
        "temperature": 0.5,
    }


def test_var_keyword_args_round_trip_is_idempotent():
    """Reconstructing from a spec must not deepen **kwargs nesting (#4374)."""
    original = solver_with_kwargs(base="hello", max_tokens=123)

    replayed = solver_from_spec(as_solver_spec(original))

    assert registry_params(replayed) == registry_params(original)


def test_reserved_name_var_keyword_args_do_not_collide():
    """A ``**kwargs`` key named like registry_tag's positional params must not collide.

    A key named `type`, `o`, or `info` raised `TypeError: got multiple values for
    argument ...` at capture time before those parameters were made positional-only.
    """
    for key in ("type", "o", "info"):
        slv = solver_with_kwargs(base="hello", **{key: "demo"})
        assert slv is not None

        # replay drives the capture path again (create_registry_object -> registry_tag)
        assert solver_from_spec(as_solver_spec(slv)) is not None


@solver
def solver_explicit_type(base: str = "base", type: str = "x"):
    """Solver with an explicit parameter named ``type``."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return await generate(state)

    return solve


def test_explicit_param_named_type_round_trip():
    """An explicit `type` parameter must survive capture AND replay (#4504).

    Unlike a ``**kwargs`` key, an explicit parameter is captured flat at the
    top level of args_passed, so replay really does feed it back into the
    registry instantiation path — where it used to collide with
    registry_create's own leading `type` parameter. Replay goes through
    create_registry_object (args as a dict), which has no such parameters.
    """
    original = solver_explicit_type(base="hello", type="y")

    replayed = solver_from_spec(as_solver_spec(original))

    assert registry_params(replayed) == registry_params(original)
    assert registry_params(replayed)["type"] == "y"


def test_var_keyword_name_kwarg_round_trip():
    """A **kwargs key named `name` must round-trip (#4375).

    Flattening (#4374) records such a key at the top level of args_passed, so
    replaying via registry_create("solver", solver_name, **args_passed) would
    bind it to registry_create's own positional `name` and raise TypeError: got
    multiple values for argument 'name'. Replay goes through create_registry_object
    (args as a dict) to avoid that collision.
    """
    original = solver_with_kwargs(base="hello", name="demo", max_tokens=123)

    replayed = solver_from_spec(as_solver_spec(original))

    assert registry_params(replayed) == registry_params(original)
    assert registry_params(replayed)["name"] == "demo"


@task
def task_with_var_keyword(base: str = "b", **kwargs):
    return Task()


@task
def task_with_extra_var_keyword(base: str = "b", **extra):
    return Task()


def test_task_create_replays_name_kwarg_without_collision():
    """A task arg named `name` must survive the retry-path splat (#4375).

    eval_retry replays via task_create(task_spec, **task_args); with flat
    capture a `name` key collided with task_create's own leading parameter
    (TypeError: got multiple values for argument 'name'), one frame before
    the registry_create collision fixed for solvers. task_create now takes
    its leading name positionally and instantiates through
    create_registry_object.
    """
    from inspect_ai._eval.registry import task_create

    instance = task_create("task_with_var_keyword", base="b", name="demo")

    assert isinstance(instance, Task)


def test_task_create_keeps_args_for_differently_named_var_keyword(caplog):
    """A `**extra` factory must keep replay args (#4375).

    task_create's pass-through check used to key on the literal param name
    `kwargs`, so a factory whose variadic keyword param was named anything
    else warned and dropped every replayed arg.
    """
    import logging

    from inspect_ai._eval.registry import task_create

    with caplog.at_level(logging.WARNING):
        instance = task_create("task_with_extra_var_keyword", base="b", max_tokens=5)

    assert isinstance(instance, Task)
    assert not [
        record for record in caplog.records if "not used by task" in record.getMessage()
    ]
