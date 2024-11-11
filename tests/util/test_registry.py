from typing import cast

from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.registry import (
    registry_create_from_dict,
    registry_info,
    registry_lookup,
    registry_value,
)
from inspect_ai.scorer import Metric, Score, metric
from inspect_ai.solver import Plan, Solver, solver, use_tools
from inspect_ai.tool import Tool, bash


def test_registry_namespaces() -> None:
    # define a local metric which we can lookup by simple name
    @metric(name="local_accuracy")
    def accuracy1(correct: str = "C") -> Metric:
        def metric(scores: list[Score]) -> int | float:
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

    mysolver2 = cast(Plan, registry_create_from_dict(solver_dict))
    assert isinstance(mysolver2, Solver)
