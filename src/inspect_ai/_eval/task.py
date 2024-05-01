import asyncio
import os
import sys
from copy import deepcopy
from dataclasses import dataclass
from logging import getLogger
from typing import Any, Callable, Sequence, cast

from pydantic import BaseModel
from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display._display import TaskProfile
from inspect_ai._util.constants import DEFAULT_EPOCHS
from inspect_ai._util.datetime import iso_now
from inspect_ai._util.dotenv import dotenv_environ
from inspect_ai._util.error import exception_message
from inspect_ai._util.path import chdir_python, cwd_relative_path
from inspect_ai._util.registry import (
    is_registry_object,
    registry_info,
    registry_log_name,
    registry_params,
)
from inspect_ai.dataset import Dataset, MemoryDataset, Sample
from inspect_ai.log import (
    EvalConfig,
    EvalError,
    EvalLog,
    EvalPlan,
    EvalPlanStep,
    EvalStats,
    LoggingMessage,
)
from inspect_ai.log._log import eval_error
from inspect_ai.model import (
    ChatMessage,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    ModelName,
    ToolCall,
    ToolFunction,
    ToolInfo,
)
from inspect_ai.model._model import collect_model_usage
from inspect_ai.scorer import Metric, Score, Scorer, Target
from inspect_ai.solver import Generate, Plan, Solver, TaskState, Tool, generate
from inspect_ai.solver._tool.tool import TOOL_PARAMS
from inspect_ai.solver._tool.tool_def import ToolDef, tool_defs
from inspect_ai.util._context.logger import collect_logger_records

from .images import (
    messages_with_base64_images,
    samples_with_base64_images,
)
from .log import EvalLogger
from .score import eval_results, score_async

logger = getLogger(__name__)

TASK_FILE_ATTR = "__task_file__"
TASK_RUN_DIR_ATTR = "__task_run_dir__"


class Task:
    r"""Evaluation task.

    Tasks are the basis for defining and running evaluations. Tasks
    are parameterized with a dataset, a scorer, and metrics. Tasks
    also may optionally provide a default plan for execution.

    Args:
        dataset (Dataset | Sequence[Sample]): Dataset to evaluate
        plan: (Plan | Solver | list[Solver]): Default plan. If not specified
          defaults to generate(), a normal call to the model.
        scorer: (Scorer | None): Scorer used to evaluate model output.
        metrics (list[Metric]): Additional metrics to compute beyond
          the base metrics provided by the scorer.
        config (GenerateConfig): Model generation config.
        epochs (int): Default number of epochs to run for.
        max_messages (int | None): Limit on total messages in the conversation.
        name: (str | None): Task name. If not specified is automatically
          determined based on the name of the task directory (or "task")
          if its anonymous task (e.g. created in a notebook and passed to
          eval() directly)
        version: (int): Version of task (to distinguish evolutions
          of the task spec or breaking changes to it)
    """

    def __init__(
        self,
        dataset: Dataset | Sequence[Sample],
        plan: Plan | Solver | list[Solver] = generate(),
        scorer: Scorer | None = None,
        metrics: list[Metric] = [],
        config: GenerateConfig = GenerateConfig(),
        epochs: int | None = None,
        max_messages: int | None = None,
        name: str | None = None,
        version: int = 0,
    ) -> None:
        self.dataset = (
            dataset if isinstance(dataset, Dataset) else MemoryDataset(list(dataset))
        )
        self.plan = plan if isinstance(plan, Plan) else Plan(plan)
        self.scorer = scorer
        self.metrics = metrics
        self.config = config
        self.epochs = epochs
        self.max_messages = max_messages
        self.version = version
        self._name = name

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

    async def run(
        self,
        sequence: tuple[int, int],
        model: Model,
        logger: EvalLogger,
        config: EvalConfig = EvalConfig(),
        plan: Plan | Solver | list[Solver] | None = None,
        score: bool = True,
        **kwargs: Unpack[GenerateConfigArgs],
    ) -> EvalLog:
        r"""Run the task.

        Run the task with the passed model and configuration, using the
        samples, scorer, metrics and solver(s) specified for the task.

        Args:
            sequence (int): Sequence of the run within a larger set of runs
            model (Model): Model used to generate output
            logger (EvalLogger): Logger for recording results.
            config (EvalConfig): Config (sample range/epochs, logging options)
            plan:(Plan | Solver | list[Solver] | None): Override of
               task default plan.
            score (bool | None): Score model output. If not specified
              is determined automatically based on whether the task
              has a solver and metrics defined.
            **kwargs (GenerateConfigArgs): Generation config options

        Returns:
          EvalLog for executed task.

        """
        with chdir_python(task_run_dir(self)), dotenv_environ():
            # track stats and error
            stats = EvalStats(started_at=iso_now())
            error: EvalError | None = None

            # see if we are scoring
            score = score and self.scorer is not None

            # evaluate the task (accumulate scores for metrics)
            model_name = ModelName(model)

            # apply limit to dataset
            dataset_limit = (
                slice(0, len(self.dataset))
                if config.limit is None
                else (
                    slice(*config.limit)
                    if isinstance(config.limit, tuple)
                    else slice(0, config.limit)
                )
            )
            dataset = self.dataset[dataset_limit] if dataset_limit else self.dataset

            # add sample ids to dataset if they aren't there (start at 1 not 0)
            for id, sample in zip(
                range(dataset_limit.start, dataset_limit.stop), dataset
            ):
                if sample.id is None:
                    sample.id = id + 1

            # resolve the plan and scorer
            plan = (
                plan
                if isinstance(plan, Plan)
                else Plan(plan)
                if plan is not None
                else self.plan
            )
            scorer: Scorer | None = self.scorer if (score and self.scorer) else None

            # compute the generate() config. we start with the base task config,
            # then merge any deltas provided by the **kwargs for this call to run()
            generate_config = self.config.merge(GenerateConfigArgs(**kwargs))

            # log the plan
            self._log_plan(logger, plan, generate_config)

            # provide solvers a function that they can use to generate output
            async def generate(
                state: TaskState, **kwargs: Unpack[GenerateConfigArgs]
            ) -> TaskState:
                return await self._generate(
                    model=model,
                    state=state,
                    config=generate_config.merge(kwargs),
                    max_messages=config.max_messages,
                )

            # apply epochs (deepcopy the samples so they remain independent)
            epochs = config.epochs if config.epochs else DEFAULT_EPOCHS
            samples: list[Sample] = []
            for _ in range(0, epochs):
                samples.extend([deepcopy(sample) for sample in dataset])

            # if we are logging images then resolve sample images here
            log_images = config.log_images is not False
            if log_images:
                samples = await samples_with_base64_images(samples)

            # prime the eval tasks (deep copy so they share no state w/ sample)
            sample_epochs: list[int] = []
            for e in range(0, epochs):
                sample_epochs.extend([e + 1] * len(dataset))
            states = [
                deepcopy(
                    TaskState(
                        sample_id=sample.id or 0,
                        epoch=epoch,
                        model=model_name,
                        input=sample.input,
                        choices=sample.choices,
                        messages=sample_messages(sample),
                        completed=False,
                        metadata=sample.metadata if sample.metadata else {},
                    )
                )
                for epoch, sample in zip(sample_epochs, samples)
            ]

            # create task profile for display
            profile = TaskProfile(
                name=self.name,
                sequence=sequence,
                model=model_name,
                dataset=self.dataset.name or "(samples)",
                scorer=(
                    registry_log_name(self.scorer)
                    if is_registry_object(self.scorer)
                    else "(none)"
                ),
                samples=len(samples),
                eval_config=config,
                task_args=logger.eval.task_args,
                generate_config=generate_config,
                log_location=logger.location,
            )

            with display().task(profile) as td:
                try:
                    # run w/ progress (steps = samples * steps in plan + 1 for scorer)
                    total_steps = len(samples) * (
                        len(plan.steps) + (1 if plan.finish else 0) + (1)  # scorer
                    )
                    with td.progress(total=total_steps) as p:

                        def progress() -> None:
                            p.update(1)

                        tasks = [
                            self.run_eval_task(
                                sample=sample,
                                state=state,
                                plan=plan,
                                max_messages=config.max_messages,
                                scorer=scorer,
                                generate=generate,
                                progress=progress,
                            )
                            for (sample, state) in zip(samples, states)
                        ]

                        # run them in parallel
                        scores = await asyncio.gather(*tasks)

                    # log output by epoch
                    if config.log_samples is not False:
                        # if we are logging images then be sure to base64 images injected by solvers
                        if log_images:
                            states = await states_with_base64_images(states)

                        for e in range(0, epochs):
                            sl = slice(e * len(dataset), (e + 1) * (len(dataset)))
                            self._log_output(
                                logger, e + 1, samples[sl], states[sl], scores[sl]
                            )

                    # compute and record metrics if we have scores (don't compute metrics on errors)
                    completed_scores = [
                        score for score in scores if isinstance(score, Score)
                    ]
                    if len(completed_scores) > 0:
                        results = eval_results(
                            completed_scores,
                            self.scorer,
                            self.metrics,
                        )
                        logger.log_results(results)

                    # collect eval data
                    collect_eval_data(stats, logger)

                    # display task summary
                    td.summary(results, stats)

                except asyncio.CancelledError as ex:
                    raise ex

                except BaseException as ex:
                    # mark completed
                    stats.completed_at = iso_now()

                    # get exception info
                    type, value, traceback = sys.exc_info()
                    type = type if type else BaseException
                    value = value if value else ex

                    # build eval error
                    error = eval_error(ex, type, value, traceback)

                    # collect eval data
                    collect_eval_data(stats, logger)

                    # display it
                    td.error(error, type, value, traceback)

        # log as appropriate
        if error:
            return logger.log_failure(stats, error)
        else:
            return logger.log_success(stats)

    async def score(self, log: EvalLog) -> EvalLog:
        with chdir_python(task_run_dir(self)), dotenv_environ():
            # confirm we have a scorer
            if self.scorer is None:
                raise ValueError("You must specify a scorer for evals to be scored.")

            # confirm we have samples
            if log.samples is None or len(log.samples) == 0:
                raise ValueError("There are no samples to score in the log.")

            task_name = self.name
            display().print(f"Scoring {len(log.samples)} samples for task: {task_name}")

            # perform scoring
            log = await score_async(log, self.scorer)

        # compute and log metrics
        display().print(f"Aggregating scores for task: {task_name}")
        if self.scorer and log.samples:
            log.results = eval_results(
                [
                    sample.score
                    for sample in log.samples
                    if isinstance(sample.score, Score)
                ],
                self.scorer,
                self.metrics,
            )
        return log

    async def run_eval_task(
        self,
        sample: Sample,
        state: TaskState,
        plan: Plan,
        max_messages: int | None,
        scorer: Scorer | None,
        generate: Generate,
        progress: Callable[..., None],
    ) -> Score | None:
        # solver loop
        try:
            # run plan steps (checking for early termination)
            for index, solver in enumerate(plan.steps):
                # run the solver
                state = await solver(state, generate)
                progress()

                # check for early termination (tick remaining progress)
                if state.completed or has_max_messages(state, max_messages):
                    for _ in range(index + 1, len(plan.steps)):
                        progress()
                    break

            # run finishing step them mark completed
            if plan.finish:
                state = await plan.finish(state, generate)
                progress()
            state.completed = True

        finally:
            # safely run cleanup function if there is one
            if plan.cleanup:
                try:
                    await plan.cleanup(state)
                except Exception as ex:
                    logger.warning(
                        f"Exception occurred during plan cleanup for task {self.name}: "
                        + f"{exception_message(ex)}"
                    )
                    pass

        # score it
        result = await scorer(state, Target(sample.target)) if scorer else None
        progress()

        # return
        return result

    async def _generate(
        self,
        model: Model,
        state: TaskState,
        config: GenerateConfig,
        max_messages: int | None,
    ) -> TaskState:
        # track tool_choice (revert to "none" after first forced call of a tool)
        tool_choice = state.tool_choice

        while True:
            # call the model
            output = await model.generate(
                state.messages,
                tools_info(state.tools),
                tool_choice,
                config,
            )

            # append the assistant message
            message = output.choices[0].message
            state.messages.append(message)

            # check for max messages
            if has_max_messages(state, max_messages):
                state.output = output
                return state

            # resolve tool calls if necessary
            tdefs = tool_defs(state.tools)
            if message.tool_calls and len(message.tool_calls) > 0:
                for tool_call in message.tool_calls:
                    tool_error: str | None = None
                    try:
                        result = await call_tool(tdefs, tool_call, state.metadata)
                    except Exception as ex:
                        result = ""
                        tool_error = exception_message(ex)

                    if isinstance(result, tuple):
                        result, metadata = result
                        state.metadata.update(metadata)

                    state.messages.append(
                        ChatMessageTool(
                            content=str(result),
                            tool_error=tool_error,
                            tool_call_id=tool_call.id,
                        )
                    )

                    # check for max messages
                    if has_max_messages(state, max_messages):
                        state.output = output
                        return state

                    # if a tool_call was forced set tool_choice to 'none'
                    # (otherwise it will get forced over and over again)
                    if isinstance(tool_choice, ToolFunction):
                        tool_choice = "none"

            # no tool calls, we are done!
            else:
                state.output = output
                return state

    def _log_output(
        self,
        logger: EvalLogger,
        epoch: int,
        samples: list[Sample],
        states: list[TaskState],
        scores: list[Score | None],
    ) -> None:
        for i in range(len(samples)):
            logger.log_sample(epoch, samples[i], states[i], scores[i])

    def _log_plan(
        self,
        logger: EvalLogger,
        plan: Plan,
        config: GenerateConfig,
    ) -> None:
        def eval_plan_step(solver: Solver) -> EvalPlanStep:
            return EvalPlanStep(
                solver=registry_log_name(solver), params=registry_params(solver)
            )

        eval_plan = EvalPlan(
            name=plan.name,
            steps=[eval_plan_step(solver) for solver in plan.steps],
            finish=eval_plan_step(plan.finish) if plan.finish else None,
            config=config,
        )
        if plan.finish:
            eval_plan.steps.append(eval_plan_step(plan.finish))

        logger.log_event("plan", eval_plan)


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
class TaskSpec:
    id: str
    task: str


Tasks = (
    str
    | TaskSpec
    | TaskInfo
    | Task
    | Callable[..., Task]
    | type[Task]
    | list[str]
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


def task_file(task: Task, relative: bool = False) -> str | None:
    file = cast(str | None, getattr(task, TASK_FILE_ATTR, None))
    if file:
        if relative:
            return cwd_relative_path(file)
        else:
            return file
    else:
        return None


def task_run_dir(task: Task) -> str:
    return getattr(task, TASK_RUN_DIR_ATTR, os.getcwd())


def sample_messages(sample: Sample) -> list[ChatMessage]:
    if isinstance(sample.input, str):
        return [ChatMessageUser(content=sample.input, source="input")]
    else:
        messages = deepcopy(sample.input)
        for message in messages:
            message.source = "input"
        return messages


def has_max_messages(state: TaskState, max_messages: int | None) -> bool:
    return max_messages is not None and (len(state.messages) >= max_messages)


async def states_with_base64_images(states: list[TaskState]) -> list[TaskState]:
    return await asyncio.gather(*[state_with_base64_images(state) for state in states])


async def state_with_base64_images(state: TaskState) -> TaskState:
    state.messages = await messages_with_base64_images(state.messages)
    return state


def collect_eval_data(stats: EvalStats, logger: EvalLogger) -> None:
    # collect stats
    stats.completed_at = iso_now()
    stats.model_usage = collect_model_usage()

    # collect log output
    for record in collect_logger_records():
        logger.log_event("logging", LoggingMessage.from_log_record(record))


def tools_info(tools: list[Tool]) -> list[ToolInfo]:
    tdefs = tool_defs(tools)
    return [
        ToolInfo(name=tool.name, description=tool.description, params=tool.params)
        for tool in tdefs
    ]


async def call_tool(
    tools: list[ToolDef], call: ToolCall, metadata: dict[str, Any]
) -> Any:
    # find the tool
    tool_def = next((tool for tool in tools if tool.name == call.function), None)
    if tool_def is None:
        return f"Tool {call.function} not found"

    # resolve metadata params and prepend to arguments
    tool_params: dict[str, str] = registry_info(tool_def.tool).metadata.get(
        TOOL_PARAMS, {}
    )
    resolved_params: dict[str, Any] = {}
    for name, value in tool_params.items():
        key = value.removeprefix("metadata.")
        resolved = metadata.get(key, None)
        if resolved is None:
            raise ValueError(f"Metadata value '{key}' not found for tool parameter")
        resolved_params[name] = resolved
    arguments = resolved_params | call.arguments

    # call the tool
    try:
        return await tool_def.tool(**arguments)
    except Exception as e:
        return f"Error: {exception_message(e)}"
