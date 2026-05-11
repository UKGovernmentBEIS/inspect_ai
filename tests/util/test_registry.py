from inspect_ai import Task, eval, task
from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.registry import (
    extract_named_params,
    registry_create_from_dict,
    registry_info,
    registry_kwargs,
    registry_lookup,
    registry_value,
)
from inspect_ai.dataset import Sample
from inspect_ai.model._compaction.auto import CompactionAuto
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.native import CompactionNative
from inspect_ai.model._compaction.summary import CompactionSummary
from inspect_ai.model._compaction.trim import CompactionTrim
from inspect_ai.model._compaction.types import CompactionStrategy
from inspect_ai.scorer import Metric, metric
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.solver import Solver, solver, use_tools
from inspect_ai.tool import Tool, bash


def test_registry_namespaces() -> None:
    # define a local metric which we can lookup by simple name
    @metric(name="local_accuracy")
    def accuracy1(correct: str = "C") -> Metric:
        def metric(scores: list[SampleScore]) -> int | float:
            return 1

        return metric

    assert registry_lookup("metric", "local_accuracy")

    # confirm that inspect_ai builtins have their namespace auto-appended
    info = registry_info(registry_lookup("metric", f"{PKG_NAME}/accuracy"))
    assert info
    assert info.name == f"{PKG_NAME}/accuracy"


def test_registry_dict() -> None:
    @solver
    def create_solver(tool: Tool) -> Solver:
        return use_tools(tool)

    mysolver = create_solver(bash(timeout=10))
    solver_dict = registry_value(mysolver)
    assert solver_dict["type"] == "solver"
    assert solver_dict["params"]["tool"]["type"] == "tool"

    mysolver2 = registry_create_from_dict(solver_dict)
    assert isinstance(mysolver2, Solver)


@task
def task_with_default(variant: str = "default") -> Task:
    return Task(dataset=[Sample(input="")], plan=[])


def test_registry_tag_default_argument() -> None:
    task_instance = task_with_default()
    log = eval(task_instance)[0]
    assert log.eval.task_args == {"variant": "default"}


def test_registry_tag_overridden_default() -> None:
    task_instance = task_with_default(variant="override")
    log = eval(task_instance)[0]
    assert log.eval.task_args == {"variant": "override"}


@task
def task_with_default_and_required(required: str, variant: str = "default") -> Task:
    return Task(dataset=[Sample(input="")], plan=[])


def test_registry_tag_default_with_required() -> None:
    task_instance = task_with_default_and_required("required_value")
    log = eval(task_instance)[0]
    assert log.eval.task_args == {"required": "required_value", "variant": "default"}


def test_registry_tag_overridden_default_with_required() -> None:
    task_instance = task_with_default_and_required("required_value", variant="override")
    log = eval(task_instance)[0]
    assert log.eval.task_args == {"required": "required_value", "variant": "override"}


def test_registry_kwargs() -> None:
    @solver
    def create_solver(tool: Tool) -> Solver:
        return use_tools(tool)

    mysolver = create_solver(bash(timeout=10))

    obj = {
        "solver": mysolver,
        "solver_list": [mysolver],
        "solver_tuple": (mysolver,),
        "solver_dict": {"inner_solver": mysolver},
    }
    dict = registry_value(obj)
    for solver_dict in (
        dict["solver"],
        dict["solver_list"][0],
        dict["solver_tuple"][0],
        dict["solver_dict"]["inner_solver"],
    ):
        assert solver_dict["type"] == "solver"
        assert solver_dict["name"] == "create_solver"
        assert solver_dict["params"]["tool"]["type"] == "tool"

    args = registry_kwargs(**dict)
    for arg_solver in (
        args["solver"],
        args["solver_list"][0],
        args["solver_tuple"][0],
        args["solver_dict"]["inner_solver"],
    ):
        assert isinstance(arg_solver, Solver)


def _extract(fn, *args, **kwargs):
    """Helper to call extract_named_params with apply_defaults=True."""
    return extract_named_params(fn, True, *args, **kwargs)


def test_repr_params_serialization() -> None:
    """Test that objects with _repr_params_ are serialized as dicts, not class names."""

    def my_solver(compaction: CompactionStrategy) -> None: ...

    result = _extract(
        my_solver, compaction=CompactionEdit(threshold=0.8, keep_tool_uses=5)
    )

    assert isinstance(result["compaction"], dict)
    assert result["compaction"]["type"] == "edit"
    assert result["compaction"]["threshold"] == 0.8
    assert result["compaction"]["keep_tool_uses"] == 5
    assert result["compaction"]["memory"] is True
    assert result["compaction"]["keep_thinking_turns"] == 1
    assert result["compaction"]["keep_tool_inputs"] is True
    assert result["compaction"]["exclude_tools"] is None


def test_repr_params_all_strategies() -> None:
    """Test _repr_params_ for each CompactionStrategy subclass."""

    def my_solver(compaction: CompactionStrategy) -> None: ...

    # CompactionEdit
    result = _extract(my_solver, compaction=CompactionEdit(threshold=0.7))
    assert result["compaction"]["type"] == "edit"
    assert result["compaction"]["threshold"] == 0.7
    assert "keep_tool_uses" in result["compaction"]

    # CompactionTrim
    result = _extract(my_solver, compaction=CompactionTrim(threshold=0.6, preserve=0.5))
    assert result["compaction"]["type"] == "trim"
    assert result["compaction"]["threshold"] == 0.6
    assert result["compaction"]["preserve"] == 0.5

    # CompactionSummary
    result = _extract(
        my_solver,
        compaction=CompactionSummary(threshold=0.85, instructions="Keep code"),
    )
    assert result["compaction"]["type"] == "summary"
    assert result["compaction"]["threshold"] == 0.85
    assert result["compaction"]["instructions"] == "Keep code"

    # CompactionNative
    result = _extract(
        my_solver, compaction=CompactionNative(threshold=0.9, instructions="Be concise")
    )
    assert result["compaction"]["threshold"] == 0.9
    assert result["compaction"]["instructions"] == "Be concise"

    # CompactionAuto
    result = _extract(
        my_solver, compaction=CompactionAuto(threshold=0.75, memory="auto")
    )
    assert result["compaction"]["threshold"] == 0.75
    assert result["compaction"]["memory"] == "auto"
