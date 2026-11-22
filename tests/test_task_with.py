import copy
import inspect
from typing import Any

import pytest
from test_helpers.tasks import minimal_task

from inspect_ai import task_with
from inspect_ai._eval.task.task import Task, task_score_names
from inspect_ai._util.registry import registry_info
from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.approval._policy import ApprovalPolicyConfig, ApproverPolicyConfig
from inspect_ai.log import HeadlineMetric
from inspect_ai.scorer import match, mean


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


def test_task_scorer_dict_keeps_scorer_a_list() -> None:
    strict, loose = match(location="end"), match(location="begin")
    task = Task(scorer={"accuracy_strict": strict, "accuracy_loose": loose})
    assert task.scorer == [strict, loose]
    assert task_score_names(task) == ["accuracy_strict", "accuracy_loose"]


def test_task_scorer_list_has_no_score_names() -> None:
    assert task_score_names(Task(scorer=[match(), match()])) is None
    assert task_score_names(Task(scorer=match())) is None
    assert task_score_names(Task()) is None


def test_task_with_scorer_dict() -> None:
    strict = match(location="end")
    task = task_with(Task(scorer=match()), scorer={"accuracy_strict": strict})
    assert task.scorer == [strict]
    assert task_score_names(task) == ["accuracy_strict"]

    # other options leave the names in place
    task = task_with(task, time_limit=30)
    assert task_score_names(task) == ["accuracy_strict"]


@pytest.mark.parametrize("scorer", [match(), [match()], None])
def test_task_with_scorer_replaces_score_names(scorer: Any) -> None:
    task = task_with(Task(scorer={"accuracy_strict": match()}), scorer=scorer)
    assert task_score_names(task) is None


def test_task_scorer_assignment_drops_score_names() -> None:
    task = Task(scorer={"accuracy_strict": match()})
    replacement = [match(), match()]
    task.scorer = replacement
    assert task.scorer == replacement
    assert task_score_names(task) is None

    task = Task(scorer={"accuracy_strict": match()})
    single = match()
    task.scorer = single
    assert task.scorer == [single]
    assert task_score_names(task) is None

    task = Task(scorer={"accuracy_strict": match()})
    task.scorer = None
    assert task.scorer is None
    assert task_score_names(task) is None


def test_task_scorer_assignment_accepts_dict() -> None:
    strict, loose = match(location="end"), match(location="begin")
    task = Task(scorer=match())
    task.scorer = {"accuracy_strict": strict, "accuracy_loose": loose}
    assert task.scorer == [strict, loose]
    assert task_score_names(task) == ["accuracy_strict", "accuracy_loose"]

    # a dict replaces the names of an earlier dict
    task.scorer = {"accuracy": loose}
    assert task.scorer == [loose]
    assert task_score_names(task) == ["accuracy"]


def test_task_scorer_list_passed_on_has_no_score_names() -> None:
    task = Task(scorer={"accuracy_strict": match()})
    assert task_score_names(Task(scorer=task.scorer)) is None


def test_task_scorer_changed_in_place_is_error() -> None:
    task = Task(scorer={"accuracy_strict": match()})
    assert task.scorer is not None
    task.scorer.append(match())
    with pytest.raises(ValueError, match="2 scorers but 1 score names"):
        task_score_names(task)


def test_task_scorer_dict_survives_copy() -> None:
    task = Task(scorer={"accuracy_strict": match()})
    for copied in (copy.copy(task), copy.deepcopy(task)):
        assert task_score_names(copied) == ["accuracy_strict"]
        assert copied.scorer is not None and len(copied.scorer) == 1


@pytest.mark.parametrize("name", ["", 1, None])
def test_task_scorer_dict_invalid_name_is_error(name: Any) -> None:
    scorers: Any = {name: match()}
    with pytest.raises(ValueError, match="Score names must be non-empty strings"):
        Task(scorer=scorers)
    with pytest.raises(ValueError, match="Score names must be non-empty strings"):
        task_with(Task(), scorer=scorers)
    with pytest.raises(ValueError, match="Score names must be non-empty strings"):
        Task().scorer = scorers


def test_task_scorer_dict_metrics_override() -> None:
    task = Task(scorer={"accuracy_strict": match()}, metrics=[mean()])
    assert task.scorer is not None
    assert registry_info(task.scorer[0]).metadata["metrics"] == task.metrics
