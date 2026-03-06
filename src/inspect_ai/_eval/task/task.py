from __future__ import annotations

from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Sequence, cast, overload

from inspect_ai.util._early_stopping import EarlyStopping

if TYPE_CHECKING:
    from inspect_ai.scorer._scorers import Scorers

from pydantic import BaseModel
from typing_extensions import TypedDict, Unpack

from inspect_ai._util.logger import warn_once
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_info,
    registry_unqualified_name,
    set_registry_info,
)
from inspect_ai.agent._agent import Agent, is_agent
from inspect_ai.agent._as_solver import as_solver
from inspect_ai.approval._policy import (
    ApprovalPolicy,
    ApprovalPolicyConfig,
    approval_policies_from_config,
)
from inspect_ai.dataset import Dataset, MemoryDataset, Sample
from inspect_ai.log import EvalLog, EvalLogInfo
from inspect_ai.model import GenerateConfig
from inspect_ai.model._model import Model
from inspect_ai.model._util import resolve_model, resolve_model_roles
from inspect_ai.scorer import Metric, Scorer
from inspect_ai.scorer._reducer import ScoreReducers, create_reducers
from inspect_ai.solver import Plan, Solver, generate
from inspect_ai.solver._chain import chain
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironmentSpec,
    SandboxEnvironmentType,
    resolve_sandbox_environment,
)

from .epochs import Epochs

logger = getLogger(__name__)


class TaskDeprecatedArgs(TypedDict, total=False):
    plan: Plan | Solver | list[Solver]
    tool_environment: str | SandboxEnvironmentSpec | None
    epochs_reducer: ScoreReducers | None
    max_messages: int | None


class Task:
    r"""Evaluation task.

    Tasks are the basis for defining and running evaluations.
    """

    def __init__(
        self,
        dataset: Dataset | Sequence[Sample] | None = None,
        setup: Solver | list[Solver] | None = None,
        solver: Solver | Agent | list[Solver] = generate(),
        cleanup: Callable[[TaskState], Awaitable[None]] | None = None,
        scorer: "Scorers" | None = None,
        metrics: list[Metric | dict[str, list[Metric]]]
        | dict[str, list[Metric]]
        | None = None,
        model: str | Model | None = None,
        config: GenerateConfig = GenerateConfig(),
        model_roles: dict[str, str | Model] | None = None,
        sandbox: SandboxEnvironmentType | None = None,
        approval: str | ApprovalPolicyConfig | list[ApprovalPolicy] | None = None,
        epochs: int | Epochs | None = None,
        fail_on_error: bool | float | None = None,
        continue_on_fail: bool | None = None,
        message_limit: int | None = None,
        token_limit: int | None = None,
        time_limit: int | None = None,
        working_limit: int | None = None,
        cost_limit: float | None = None,
        early_stopping: "EarlyStopping" | None = None,
        display_name: str | None = None,
        name: str | None = None,
        version: int | str = 0,
        metadata: dict[str, Any] | None = None,
        **kwargs: Unpack[TaskDeprecatedArgs],
    ) -> None:
        """Create a task.

        Args:
            dataset: Dataset to evaluate
            setup: Setup step (always run even when the main `solver` is replaced).
            solver: Solver or list of solvers. Defaults to generate(), a normal call to the model.
            cleanup: Optional cleanup function for task. Called after
                all solvers and scorers have run for each sample (including if an
                exception occurs during the run)
            scorer: Scorer used to evaluate model output.
            metrics: Alternative metrics (overrides the metrics provided by the specified scorer).
            model: Default model for task (Optional, defaults to eval model).
            config: Model generation config for default model (does not apply to model roles)
            model_roles: Named roles for use in `get_model()`.
            sandbox: Sandbox environment type (or optionally a str or tuple with a shorthand spec)
            approval: Tool use approval policies.
                Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies. Defaults to no approval policy.
            epochs: Epochs to repeat samples for and optional score
                reducer function(s) used to combine sample scores (defaults to "mean")
            fail_on_error: `True` to fail on first sample error
                (default); `False` to never fail on sample errors; Value between 0 and 1
                to fail if a proportion of total samples fails. Value greater than 1 to fail
                eval if a count of samples fails.
            continue_on_fail: `True` to continue running and only fail at the end if the `fail_on_error` condition is met.
                `False` to fail eval immediately when the `fail_on_error` condition is met (default).
            message_limit: Limit on total messages used for each sample.
            token_limit: Limit on total tokens used for each sample.
            time_limit: Limit on clock time (in seconds) for samples.
            working_limit: Limit on working time (in seconds) for sample. Working
                time includes model generation, tool calls, etc. but does not include
                time spent waiting on retries or shared resources.
            cost_limit: Limit on total cost (in dollars) for each sample.
                Requires model cost data via set_model_cost() or --model-cost-config.
            early_stopping: Early stopping callbacks.
            name: Task name. If not specified is automatically
                determined based on the registered name of the task.
            display_name: Task display name (e.g. for plotting). If not specified then defaults to the registered task name.
            version: Version of task (to distinguish evolutions
                of the task spec or breaking changes to it)
            metadata:  Additional metadata to associate with the task.
            **kwargs: Deprecated arguments.
        """
        # handle deprecated args
        for arg, value in kwargs.items():
            newarg = ""
            if arg == "tool_environment":
                newarg = "sandbox"
                sandbox = cast(str | SandboxEnvironmentSpec | None, value)
            elif arg == "epochs_reducer":
                newarg = "epochs"
                if isinstance(epochs, int):
                    epochs = Epochs(
                        epochs, create_reducers(cast(ScoreReducers | None, value))
                    )
            elif arg == "plan":
                # no deprecation warning (yet) as it would affect 100% of evals in the wild
                solver = cast(Solver, value)
            elif arg == "max_messages":
                # no deprecation warning (yet) as many tasks set this
                message_limit = int(cast(int, value))
            if newarg:
                warn_once(
                    logger,
                    f"DEPRECATED: the '{arg}' parameter is deprecated (please use the '{newarg}' parameter instead)",
                )

        self.dataset = resolve_dataset(dataset)
        self.setup = setup
        self.solver = resolve_solver(solver)
        self.cleanup = cleanup
        self.scorer = resolve_scorer_metrics(resolve_scorer(scorer), metrics)
        self.metrics = metrics
        self.model = resolve_model(model)
        self.config = config
        self.model_roles = resolve_model_roles(model_roles)
        self.sandbox = resolve_sandbox_environment(sandbox)
        self.approval = resolve_approval(approval)
        epochs = resolve_epochs(epochs)
        self.epochs = epochs.epochs if epochs else None
        self.epochs_reducer = epochs.reducer if epochs else None
        self.fail_on_error = fail_on_error
        self.continue_on_fail = continue_on_fail
        self.message_limit = message_limit
        self.token_limit = token_limit
        self.time_limit = time_limit
        self.working_limit = working_limit
        self.cost_limit = cost_limit
        self.early_stopping = early_stopping
        self.version = version
        self._display_name = display_name
        self._name = name
        self.metadata = metadata

    @property
    def name(self) -> str:
        if self._name is not None:
            return self._name
        elif is_registry_object(self):
            return registry_info(self).name
        else:
            return "task"

    @property
    def registry_name(self) -> str | None:
        if is_registry_object(self):
            return registry_info(self).name
        else:
            return None

    @property
    def display_name(self) -> str:
        if self._display_name is not None:
            return self._display_name
        elif self._name is not None:
            return self._name
        elif is_registry_object(self):
            return registry_unqualified_name(self)
        else:
            return "task"

    @property
    def attribs(self) -> dict[str, Any]:
        if is_registry_object(self):
            return cast(dict[str, Any], registry_info(self).metadata.get("attribs", {}))
        else:
            return dict()


def task_with(
    task: Task,
    *,
    dataset: Dataset | Sequence[Sample] | None | NotGiven = NOT_GIVEN,
    setup: Solver | list[Solver] | None | NotGiven = NOT_GIVEN,
    solver: Solver | Agent | list[Solver] | NotGiven = NOT_GIVEN,
    cleanup: Callable[[TaskState], Awaitable[None]] | None | NotGiven = NOT_GIVEN,
    scorer: "Scorers" | None | NotGiven = NOT_GIVEN,
    metrics: list[Metric | dict[str, list[Metric]]]
    | dict[str, list[Metric]]
    | None
    | NotGiven = NOT_GIVEN,
    model: str | Model | NotGiven = NOT_GIVEN,
    config: GenerateConfig | NotGiven = NOT_GIVEN,
    model_roles: dict[str, str | Model] | NotGiven = NOT_GIVEN,
    sandbox: SandboxEnvironmentType | None | NotGiven = NOT_GIVEN,
    approval: str
    | ApprovalPolicyConfig
    | list[ApprovalPolicy]
    | None
    | NotGiven = NOT_GIVEN,
    epochs: int | Epochs | None | NotGiven = NOT_GIVEN,
    fail_on_error: bool | float | None | NotGiven = NOT_GIVEN,
    continue_on_fail: bool | None | NotGiven = NOT_GIVEN,
    message_limit: int | None | NotGiven = NOT_GIVEN,
    token_limit: int | None | NotGiven = NOT_GIVEN,
    time_limit: int | None | NotGiven = NOT_GIVEN,
    working_limit: int | None | NotGiven = NOT_GIVEN,
    cost_limit: float | None | NotGiven = NOT_GIVEN,
    early_stopping: EarlyStopping | None | NotGiven = NOT_GIVEN,
    name: str | None | NotGiven = NOT_GIVEN,
    version: int | str | NotGiven = NOT_GIVEN,
    metadata: dict[str, Any] | None | NotGiven = NOT_GIVEN,
) -> Task:
    """Task adapted with alternate values for one or more options.

    This function modifies the passed task in place and returns it.
    If you want to create multiple variations of a single task using
    `task_with()` you should create the underlying task multiple times.

    Args:
        task: Task to adapt
        dataset: Dataset to evaluate
        setup: Setup step (always run even when the main `solver` is replaced).
        solver: Solver or list of solvers. Defaults to generate(), a normal call to the model.
        cleanup: Optional cleanup function for task. Called after
            all solvers and scorers have run for each sample (including if an
            exception occurs during the run)
        scorer: Scorer used to evaluate model output.
        metrics: Alternative metrics (overrides the metrics provided by the specified scorer).
        model: Default model for task (Optional, defaults to eval model).
        config: Model generation config for default model (does not apply to model roles)
        model_roles: Named roles for use in `get_model()`.
        sandbox: Sandbox environment type (or optionally a str or tuple with a shorthand spec)
        approval: Tool use approval policies.
            Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies. Defaults to no approval policy.
        epochs: Epochs to repeat samples for and optional score
            reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error: `True` to fail on first sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail
            eval if a count of samples fails.
        continue_on_fail: `True` to continue running and only fail at the end if the `fail_on_error` condition is met.
            `False` to fail eval immediately when the `fail_on_error` condition is met (default).
        message_limit: Limit on total messages used for each sample.
        token_limit: Limit on total tokens used for each sample.
        time_limit: Limit on clock time (in seconds) for samples.
        working_limit: Limit on working time (in seconds) for sample. Working
            time includes model generation, tool calls, etc. but does not include
            time spent waiting on retries or shared resources.
        cost_limit: Limit on total cost (in dollars) for each sample.
            Requires model cost data via set_model_cost() or --model-cost-config.
        early_stopping: Early stopping callbacks.
        name: Task name. If not specified is automatically
            determined based on the name of the task directory (or "task")
            if its anonymous task (e.g. created in a notebook and passed to
            eval() directly)
        version: Version of task (to distinguish evolutions
            of the task spec or breaking changes to it)
        metadata:  Additional metadata to associate with the task.

    Returns:
        Task: Passed `task` with modifications.
    """
    if not isinstance(dataset, NotGiven):
        task.dataset = resolve_dataset(dataset)
    if not isinstance(setup, NotGiven):
        task.setup = setup
    if not isinstance(solver, NotGiven):
        task.solver = resolve_solver(solver)
    if not isinstance(cleanup, NotGiven):
        task.cleanup = cleanup
    if not isinstance(scorer, NotGiven):
        task.scorer = resolve_scorer(scorer)
    if not isinstance(metrics, NotGiven):
        task.metrics = metrics
    if not isinstance(model, NotGiven):
        task.model = resolve_model(model)
    if not isinstance(config, NotGiven):
        task.config = config
    if not isinstance(model_roles, NotGiven):
        task.model_roles = resolve_model_roles(model_roles)
    if not isinstance(sandbox, NotGiven):
        task.sandbox = resolve_sandbox_environment(sandbox)
    if not isinstance(approval, NotGiven):
        task.approval = resolve_approval(approval)
    if not isinstance(epochs, NotGiven):
        epochs = resolve_epochs(epochs)
        task.epochs = epochs.epochs if epochs else None
        task.epochs_reducer = epochs.reducer if epochs else None
    if not isinstance(fail_on_error, NotGiven):
        task.fail_on_error = fail_on_error
    if not isinstance(continue_on_fail, NotGiven):
        task.continue_on_fail = continue_on_fail
    if not isinstance(message_limit, NotGiven):
        task.message_limit = message_limit
    if not isinstance(token_limit, NotGiven):
        task.token_limit = token_limit
    if not isinstance(time_limit, NotGiven):
        task.time_limit = time_limit
    if not isinstance(working_limit, NotGiven):
        task.working_limit = working_limit
    if not isinstance(cost_limit, NotGiven):
        task.cost_limit = cost_limit
    if not isinstance(early_stopping, NotGiven):
        task.early_stopping = early_stopping
    if not isinstance(version, NotGiven):
        task.version = version
    if not isinstance(name, NotGiven):
        task._name = name
    if not isinstance(metadata, NotGiven):
        task.metadata = metadata

    # return modified task
    return task


class TaskInfo(BaseModel):
    """Task information (file, name, and attributes)."""

    file: str
    """File path where task was loaded from."""

    name: str
    """Task name (defaults to function name)"""

    attribs: dict[str, Any]
    """Task attributes (arguments passed to `@task`)"""

    def __str__(self) -> str:
        return f"{self.file}@{self.name}"

    def __hash__(self) -> int:
        return hash(
            (self.file, self.name)
            + tuple(self.attribs.keys())
            + tuple(self.attribs.values())
        )


@dataclass
class PreviousTask:
    id: str
    task: str | Task
    task_args: dict[str, Any]
    model: Model | None
    model_roles: dict[str, Model] | None
    log: EvalLog
    log_info: EvalLogInfo | None


def resolve_approval(
    approval: str | ApprovalPolicyConfig | list[ApprovalPolicy] | None,
) -> list[ApprovalPolicy] | None:
    return (
        approval_policies_from_config(approval)
        if isinstance(approval, str | ApprovalPolicyConfig)
        else approval
    )


def resolve_epochs(epochs: int | Epochs | None) -> Epochs | None:
    if isinstance(epochs, int):
        epochs = Epochs(epochs)
    if epochs is not None and epochs.epochs < 1:
        raise ValueError("epochs must be a positive integer.")
    return epochs


def resolve_dataset(dataset: Dataset | Sequence[Sample] | None) -> Dataset:
    # this is a convenience for tests that don't want to define a dummy sample
    if dataset is None:
        dataset = [Sample(input="prompt")]

    # raise error if the dataset is empty
    if len(dataset) == 0:
        raise ValueError("The specified dataset is empty (has no samples)")

    # resolve sequence to dataset if necessary
    return dataset if isinstance(dataset, Dataset) else MemoryDataset(list(dataset))


def resolve_solver(solver: Solver | Agent | list[Solver]) -> Solver:
    if isinstance(solver, list):
        return chain(solver)
    elif is_agent(solver):
        return as_solver(solver)
    else:
        return cast(Solver, solver)


@overload
def resolve_scorer(scorer: "Scorers") -> list[Scorer]: ...


@overload
def resolve_scorer(scorer: None) -> None: ...


def resolve_scorer(
    scorer: "Scorers" | None = None,
) -> list[Scorer] | None:
    if scorer is None:
        return scorer

    scorers = list(scorer) if isinstance(scorer, Sequence) else [scorer]
    return [to_scorer(s) for s in scorers]


def to_scorer(s: Any) -> Scorer:
    if is_registry_object(s, type="scanner"):
        from inspect_scout import as_scorer

        return as_scorer(s)
    elif is_registry_object(s, type="scorer"):
        return cast(Scorer, s)
    else:
        raise TypeError(f"Unexpected scorer type: {type(s)}")


AGENT_DESCRIPTION = "description"


def resolve_scorer_metrics(
    scorers: list[Scorer] | None,
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None,
) -> list[Scorer] | None:
    if scorers is not None and metrics is not None:
        for scorer in scorers:
            scorer_info = registry_info(scorer)
            new_metadata = {**scorer_info.metadata, "metrics": metrics}
            new_info = RegistryInfo(
                type=scorer_info.type, name=scorer_info.name, metadata=new_metadata
            )
            set_registry_info(scorer, new_info)
    return scorers
