from copy import deepcopy
from dataclasses import dataclass
from logging import getLogger
from typing import Any, Callable, Sequence, cast

from pydantic import BaseModel
from typing_extensions import TypedDict, Unpack

from inspect_ai._util.logger import warn_once
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai._util.registry import is_registry_object, registry_info
from inspect_ai.approval._policy import ApprovalPolicy, approval_policies_from_config
from inspect_ai.dataset import Dataset, MemoryDataset, Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import Metric, Scorer
from inspect_ai.scorer._reducer import ScoreReducers, create_reducers
from inspect_ai.solver import Plan, Solver, generate
from inspect_ai.solver._chain import chain
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

    Args:
        dataset (Dataset | Sequence[Sample]): Dataset to evaluate
        setup: (Solver | list[Solver] | None): Setup step (always run
          even when the main `solver` is replaced).
        solver: (Solver | list[Solver]): Solver or list of solvers.
          Defaults to generate(), a normal call to the model.
        scorer: (Scorer | list[Scorer] | None): Scorer used to evaluate model output.
        metrics (list[Metric] | dict[str, list[Metric]] | None):
          Alternative metrics (overrides the metrics provided by the specified scorer).
        config (GenerateConfig): Model generation config.
        sandbox (SandboxEnvironmentType | None): Sandbox environment type
          (or optionally a str or tuple with a shorthand spec)
        approval: (str | list[ApprovalPolicy] | None): Tool use approval policies.
          Either a path to an approval policy config file or a list of approval policies.
          Defaults to no approval policy.
        epochs (int | Epochs | None): Epochs to repeat samples for and optional score
           reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error (bool | float | None): `True` to fail on first sample error
           (default); `False` to never fail on sample errors; Value between 0 and 1
           to fail if a proportion of total samples fails. Value greater than 1 to fail
           eval if a count of samples fails.
        message_limit (int | None): Limit on total messages used for each sample.
        token_limit (int | None): Limit on total tokens used for each sample.
        time_limit (int | None): Limit on time (in seconds) for execution of each sample.
        name: (str | None): Task name. If not specified is automatically
          determined based on the name of the task directory (or "task")
          if its anonymous task (e.g. created in a notebook and passed to
          eval() directly)
        version: (int): Version of task (to distinguish evolutions
          of the task spec or breaking changes to it)
        metadata: (dict[str, Any] | None): Additional metadata to associate with the task.
    """

    def __init__(
        self,
        dataset: Dataset | Sequence[Sample] | None = None,
        setup: Solver | list[Solver] | None = None,
        solver: Solver | list[Solver] = generate(),
        scorer: Scorer | list[Scorer] | None = None,
        metrics: list[Metric] | dict[str, list[Metric]] | None = None,
        config: GenerateConfig = GenerateConfig(),
        sandbox: SandboxEnvironmentType | None = None,
        approval: str | list[ApprovalPolicy] | None = None,
        epochs: int | Epochs | None = None,
        fail_on_error: bool | float | None = None,
        message_limit: int | None = None,
        token_limit: int | None = None,
        time_limit: int | None = None,
        name: str | None = None,
        version: int = 0,
        metadata: dict[str, Any] | None = None,
        **kwargs: Unpack[TaskDeprecatedArgs],
    ) -> None:
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
        self.scorer = resolve_scorer(scorer)
        self.metrics = metrics
        self.config = config
        self.sandbox = resolve_sandbox_environment(sandbox)
        self.approval = resolve_approval(approval)
        epochs = resolve_epochs(epochs)
        self.epochs = epochs.epochs if epochs else None
        self.epochs_reducer = epochs.reducer if epochs else None
        self.fail_on_error = fail_on_error
        self.message_limit = message_limit
        self.token_limit = token_limit
        self.time_limit = time_limit
        self.version = version
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
    solver: Solver | list[Solver] | NotGiven = NOT_GIVEN,
    scorer: Scorer | list[Scorer] | None | NotGiven = NOT_GIVEN,
    metrics: list[Metric] | dict[str, list[Metric]] | None | NotGiven = NOT_GIVEN,
    config: GenerateConfig | NotGiven = NOT_GIVEN,
    sandbox: SandboxEnvironmentType | None | NotGiven = NOT_GIVEN,
    approval: str | list[ApprovalPolicy] | None | NotGiven = NOT_GIVEN,
    epochs: int | Epochs | None | NotGiven = NOT_GIVEN,
    fail_on_error: bool | float | None | NotGiven = NOT_GIVEN,
    message_limit: int | None | NotGiven = NOT_GIVEN,
    token_limit: int | None | NotGiven = NOT_GIVEN,
    time_limit: int | None | NotGiven = NOT_GIVEN,
    name: str | None | NotGiven = NOT_GIVEN,
    version: int | NotGiven = NOT_GIVEN,
    metadata: dict[str, Any] | None | NotGiven = NOT_GIVEN,
) -> Task:
    """Task adapted with alternate values for one or more options.

    Args:
        task (Task): Task to adapt (it is deep copied prior to mutating options)
        dataset (Dataset | Sequence[Sample]): Dataset to evaluate
        setup: (Solver | list[Solver] | None): Setup step (always run
          even when the main `solver` is replaced).
        solver: (Solver | list[Solver]): Solver or list of solvers.
          Defaults to generate(), a normal call to the model.
        scorer: (Scorer | list[Scorer] | None): Scorer used to evaluate model output.
        metrics (list[Metric] | dict[str, list[Metric]] | None):
          Alternative metrics (overrides the metrics provided by the specified scorer).
        config (GenerateConfig): Model generation config.
        sandbox (SandboxEnvironmentType | None): Sandbox environment type
          (or optionally a str or tuple with a shorthand spec)
        approval: (str | list[ApprovalPolicy] | None): Tool use approval policies.
          Either a path to an approval policy config file or a list of approval policies.
          Defaults to no approval policy.
        epochs (int | Epochs | None): Epochs to repeat samples for and optional score
           reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error (bool | float | None): `True` to fail on first sample error
           (default); `False` to never fail on sample errors; Value between 0 and 1
           to fail if a proportion of total samples fails. Value greater than 1 to fail
           eval if a count of samples fails.
        message_limit (int | None): Limit on total messages used for each sample.
        token_limit (int | None): Limit on total tokens used for each sample.
        time_limit (int | None): Limit on time (in seconds) for execution of each sample.
        name: (str | None): Task name. If not specified is automatically
          determined based on the name of the task directory (or "task")
          if its anonymous task (e.g. created in a notebook and passed to
          eval() directly)
        version: (int): Version of task (to distinguish evolutions
          of the task spec or breaking changes to it)
        metadata: (dict[str, Any] | None): Additional metadata to associate with the task.

    Returns:
        Task: Task adapted with alternate options.
    """
    # deep copy the task
    task = deepcopy(task)

    if not isinstance(dataset, NotGiven):
        task.dataset = resolve_dataset(dataset)
    if not isinstance(setup, NotGiven):
        task.setup = setup
    if not isinstance(solver, NotGiven):
        task.solver = resolve_solver(solver)
    if not isinstance(scorer, NotGiven):
        task.scorer = resolve_scorer(scorer)
    if not isinstance(metrics, NotGiven):
        task.metrics = metrics
    if not isinstance(config, NotGiven):
        task.config = config
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
    if not isinstance(message_limit, NotGiven):
        task.message_limit = message_limit
    if not isinstance(token_limit, NotGiven):
        task.token_limit = token_limit
    if not isinstance(time_limit, NotGiven):
        task.time_limit = time_limit
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
    log: EvalLog


Tasks = (
    str
    | PreviousTask
    | TaskInfo
    | Task
    | Callable[..., Task]
    | type[Task]
    | list[str]
    | list[PreviousTask]
    | list[TaskInfo]
    | list[Task]
    | list[Callable[..., Task]]
    | list[type[Task]]
    | None
)
r"""One or more tasks.

Tasks to be evaluated. Many forms of task specification are
supported including directory names, task functions, task
classes, and task instances (a single task or list of tasks
can be specified). None is a request to read a task out
of the current working directory.
"""


def resolve_approval(
    approval: str | list[ApprovalPolicy] | None,
) -> list[ApprovalPolicy] | None:
    return (
        approval_policies_from_config(approval)
        if isinstance(approval, str)
        else approval
    )


def resolve_epochs(epochs: int | Epochs | None) -> Epochs | None:
    if isinstance(epochs, int):
        epochs = Epochs(epochs)
    if epochs is not None and epochs.epochs < 1:
        raise ValueError("epochs must be a positive integer.")
    return epochs


def resolve_dataset(dataset: Dataset | Sequence[Sample] | None) -> Dataset:
    dataset = dataset or [Sample(input="prompt")]
    return dataset if isinstance(dataset, Dataset) else MemoryDataset(list(dataset))


def resolve_solver(solver: Solver | list[Solver]) -> Solver:
    return chain(solver) if isinstance(solver, list) else solver


def resolve_scorer(scorer: Scorer | list[Scorer] | None) -> list[Scorer] | None:
    return (
        scorer if isinstance(scorer, list) else [scorer] if scorer is not None else None
    )
