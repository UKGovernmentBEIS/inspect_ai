import inspect
from typing import Any

from test_helpers.tasks import minimal_task

from inspect_ai import task_with
from inspect_ai._eval.task.task import Task
from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.approval._policy import ApprovalPolicyConfig, ApproverPolicyConfig
from inspect_ai.log import HeadlineMetric


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


def test_task_with_headline_metric():
    task = task_with(minimal_task(), headline_metric=HeadlineMetric(metric="accuracy"))
    assert task.headline_metric == HeadlineMetric(metric="accuracy")

    # passing None clears an existing declaration
    task = task_with(task, headline_metric=None)
    assert task.headline_metric is None


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


def test_task_description() -> None:
    assert Task().description is None
    assert Task(description="Solve the puzzle.").description == "Solve the puzzle."


def test_task_positional_version_compatibility() -> None:
    # This pins version at its historical 29th positional argument.
    positional: list[Any] = [None] * 28 + ["v2"]
    task = Task(*positional)
    assert task.version == "v2"
    assert task.description is None


def test_task_description_is_keyword_only() -> None:
    assert (
        inspect.signature(Task).parameters["description"].kind
        == inspect.Parameter.KEYWORD_ONLY
    )


def test_task_with_description() -> None:
    task = task_with(Task(description="Original."), description="Changed.")
    assert task.description == "Changed."
    assert task_with(task, description=None).description is None
    # unspecified leaves the description in place
    task = task_with(Task(description="Kept."), time_limit=30)
    assert task.description == "Kept."
