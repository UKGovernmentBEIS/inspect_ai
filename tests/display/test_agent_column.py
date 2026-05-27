from inspect_ai._eval.task.run import plan_agent_name, resolve_plan
from inspect_ai._eval.task.task import Task
from inspect_ai._util.registry import RegistryInfo, set_registry_info
from inspect_ai.agent import Agent, AgentState, agent, as_solver
from inspect_ai.dataset import Sample
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


def test_resolve_plan_does_not_mutate_plan_with_setup() -> None:
    """resolve_plan must not stack setup steps onto a caller-supplied Plan.

    It can run more than once for the same task (evalset identity hashing, then
    the run), so prepending setup in place would make setup run multiple times.
    """
    plan = Plan([my_solver(), as_solver(my_agent())], internal=True)
    task = Task(
        dataset=[Sample(input="x", target="x")],
        setup=generate(),
        solver=plan,
    )

    for _ in range(3):
        resolved = resolve_plan(task, None)
        # each resolve prepends setup exactly once (3 = setup + 2 original steps)
        assert len(resolved.steps) == 3
        assert plan_agent_name(resolved) == "my_agent"
        # the caller's Plan is never mutated
        assert len(plan.steps) == 2


def test_resolve_plan_preserves_plan_identity() -> None:
    """The shallow copy keeps the plan's finish/cleanup/name."""

    async def _cleanup(state: TaskState) -> None:
        return None

    plan = Plan(
        [as_solver(my_agent())],
        finish=my_solver(),
        cleanup=_cleanup,
        name="my_plan",
        internal=True,
    )
    task = Task(dataset=[Sample(input="x", target="x")], setup=generate(), solver=plan)
    resolved = resolve_plan(task, None)
    assert resolved is not plan
    assert resolved.name == "my_plan"
    assert resolved.finish is plan.finish
    assert resolved.cleanup is plan.cleanup
