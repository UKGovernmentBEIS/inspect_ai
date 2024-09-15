from typing import cast

from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.registry import (
    registry_create_from_dict,
    registry_dict,
    registry_info,
    registry_lookup,
)
from inspect_ai.scorer import Metric, Score, metric
from inspect_ai.solver import Plan, Solver, plan, solver, use_tools
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
    @plan
    def create_plan(solver: Solver) -> Plan:
        return Plan(solver)

    @solver
    def create_solver(tool: Tool) -> Solver:
        return use_tools(tool)

    myplan = create_plan(create_solver(bash(timeout=10)))
    plan_dict = registry_dict(myplan)
    assert plan_dict["type"] == "plan"
    assert plan_dict["params"]["solver"]["type"] == "solver"
    assert plan_dict["params"]["solver"]["params"]["tool"]["type"] == "tool"

    myplan2 = cast(Plan, registry_create_from_dict(plan_dict))
    assert isinstance(myplan2, Plan)
    assert isinstance(myplan2.steps[0], Solver)
