from test_helpers.tasks import minimal_task

from inspect_ai import task_with
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.approval._policy import ApprovalPolicyConfig, ApproverPolicyConfig


def test_task_with_add_options():
    task = task_with(minimal_task(), time_limit=30)
    assert task.time_limit == 30
    assert task.metadata is not None


def test_task_with_remove_options():
    task = task_with(
        minimal_task(),
        scorer=None,
    )
    assert task.scorer is None
    assert task.metadata is not None


def test_task_with_edit_options():
    task = task_with(
        minimal_task(),
        metadata={"foo": "bar"},
    )
    assert task.metadata == {"foo": "bar"}


def test_task_with_name_option():
    task = task_with(minimal_task(), name="changed")
    assert task.name == "changed"


def test_task_with_approval_policy():
    task = Task(
        approval=ApprovalPolicyConfig(
            approvers=[
                ApproverPolicyConfig(name="human", tools="*"),
                ApproverPolicyConfig(name="auto", tools="tool_1"),
            ]
        )
    )
    assert isinstance(task.approval, list)
    assert len(task.approval) == 2
    assert task.approval[0].tools == "*"
    assert task.approval[1].tools == "tool_1"

    task_with(
        task,
        approval=ApprovalPolicyConfig(
            approvers=[
                ApproverPolicyConfig(name="human", tools="new_tool"),
                ApproverPolicyConfig(name="auto", tools="new_tool_2"),
            ]
        ),
    )
    assert isinstance(task.approval, list)
    assert len(task.approval) == 2
    assert task.approval[0].tools == "new_tool"
    assert task.approval[1].tools == "new_tool_2"


def test_task_with_version():
    task = task_with(minimal_task(), version="1.0.0")
    assert task.version == "1.0.0"
    task = task_with(minimal_task(), version=2)
    assert task.version == 2


@agent
def minimal_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        return state

    return execute


def test_task_with_agent_as_solver():
    task = task_with(
        minimal_task(),
        solver=minimal_agent(),
    )
    assert str(task.solver).find("agent_to_solver") != -1
