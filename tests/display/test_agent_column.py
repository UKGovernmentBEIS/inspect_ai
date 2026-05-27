from inspect_ai._eval.task.run import plan_agent_name
from inspect_ai._util.registry import RegistryInfo, set_registry_info
from inspect_ai.agent import Agent, AgentState, agent, as_solver
from inspect_ai.solver import Generate, Solver, generate, solver
from inspect_ai.solver._plan import Plan
from inspect_ai.solver._task_state import TaskState


@agent
def my_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        return state

    return execute


@solver
def my_solver() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    return solve


def test_plan_agent_name_default_generate() -> None:
    assert plan_agent_name(Plan([generate()], internal=True)) == "generate"


def test_plan_agent_name_agent() -> None:
    plan = Plan([as_solver(my_agent())], internal=True)
    assert plan_agent_name(plan) == "my_agent"


def test_plan_agent_name_solver() -> None:
    plan = Plan([my_solver()], internal=True)
    assert plan_agent_name(plan) == "my_solver"


def test_plan_agent_name_uses_terminal_step() -> None:
    plan = Plan([my_solver(), as_solver(my_agent())], internal=True)
    assert plan_agent_name(plan) == "my_agent"


def test_plan_agent_name_strips_package_prefix() -> None:
    slv = my_solver()
    set_registry_info(slv, RegistryInfo(type="solver", name="mypkg/researcher"))
    plan = Plan([slv], internal=True)
    assert plan_agent_name(plan) == "researcher"


def test_plan_agent_name_empty_plan() -> None:
    assert plan_agent_name(Plan([], internal=True)) is None
