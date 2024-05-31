import asyncio
import contextlib
import sys
from copy import deepcopy
from logging import getLogger
from typing import Callable

from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display._display import TaskProfile
from inspect_ai._util.constants import DEFAULT_EPOCHS
from inspect_ai._util.datetime import iso_now
from inspect_ai._util.dotenv import dotenv_environ
from inspect_ai._util.error import exception_message
from inspect_ai._util.path import chdir_python
from inspect_ai._util.registry import (
    is_registry_object,
    registry_log_name,
)
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.log import (
    EvalConfig,
    EvalError,
    EvalLog,
    EvalResults,
    EvalStats,
)
from inspect_ai.log._log import eval_error
from inspect_ai.model import (
    GenerateConfigArgs,
    Model,
    ModelName,
)
from inspect_ai.scorer import Score, Scorer, Target
from inspect_ai.solver import Generate, Plan, Solver, TaskState

from ..task import Task
from .generate import task_generate
from .images import samples_with_base64_images, states_with_base64_images
from .log import TaskLogger, collect_eval_data, log_output, log_plan
from .results import eval_results
from .util import has_max_messages, sample_messages, task_run_dir

logger = getLogger(__name__)


async def task_run(
    task: Task,
    sequence: tuple[int, int],
    model: Model,
    logger: TaskLogger,
    config: EvalConfig = EvalConfig(),
    plan: Plan | Solver | list[Solver] | None = None,
    score: bool = True,
    **kwargs: Unpack[GenerateConfigArgs],
) -> EvalLog:
    r"""Run the task.

    Run the task with the passed model and configuration, using the
    samples, scorer, metrics and solver(s) specified for the task.

    Args:
        task (Task): Task to run.
        sequence (int): Sequence of the run within a larger set of runs
        model (Model): Model used to generate output
        logger (TaskLogger): Logger for recording results.
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
    with chdir_python(task_run_dir(task)), dotenv_environ():
        # track stats and error
        stats = EvalStats(started_at=iso_now())
        error: EvalError | None = None

        # resolve some config
        model_name = ModelName(model)
        epochs = config.epochs if config.epochs else DEFAULT_EPOCHS
        log_images = config.log_images is not False
        log_samples = config.log_samples is not False
        generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

        # resolve dataset
        dataset, samples, states = await resolve_dataset(
            dataset=task.dataset,
            model_name=model_name,
            limit=config.limit,
            epochs=epochs,
            log_images=log_images,
        )

        # resolve the plan and scorer
        plan = (
            plan
            if isinstance(plan, Plan)
            else Plan(plan)
            if plan is not None
            else task.plan
        )
        score = score and task.scorer is not None
        scorer: Scorer | None = task.scorer if (score and task.scorer) else None

        # create task profile for display
        profile = TaskProfile(
            name=task.name,
            sequence=sequence,
            model=model_name,
            dataset=task.dataset.name or "(samples)",
            scorer=(
                registry_log_name(scorer) if is_registry_object(scorer) else "(none)"
            ),
            samples=len(samples),
            eval_config=config,
            task_args=logger.eval.task_args,
            generate_config=generate_config,
            log_location=logger.location,
        )

        with display().task(profile) as td:
            try:
                # log the plan
                log_plan(logger, plan, generate_config)

                # run w/ progress (steps = samples * steps in plan + 1 for scorer)
                total_steps = len(samples) * (
                    len(plan.steps) + (1 if plan.finish else 0) + (1)  # scorer
                )
                with td.progress(total=total_steps) as p:
                    # forward progress
                    def progress() -> None:
                        p.update(1)

                    # provide solvers a function that they can use to generate output
                    async def generate(
                        state: TaskState, **kwargs: Unpack[GenerateConfigArgs]
                    ) -> TaskState:
                        return await task_generate(
                            model=model,
                            state=state,
                            config=generate_config.merge(kwargs),
                            max_messages=config.max_messages,
                        )

                    # optional semaphore to limit concurrency
                    task_semaphore = (
                        asyncio.Semaphore(config.max_samples)
                        if config.max_samples
                        else None
                    )

                    # create tasks
                    tasks = [
                        task_run_sample(
                            task_name=task.name,
                            sample=sample,
                            state=state,
                            plan=plan,
                            max_messages=config.max_messages,
                            scorer=scorer,
                            generate=generate,
                            progress=progress,
                            semaphore=task_semaphore,
                        )
                        for (sample, state) in zip(samples, states)
                    ]

                    # run them in parallel (subject to config.max_samples)
                    scores = await asyncio.gather(*tasks)

                # log output by epoch
                if log_samples is not False:
                    # if we are logging images then be sure to base64 images injected by solvers
                    if log_images:
                        states = await states_with_base64_images(states)

                    for e in range(0, epochs):
                        sl = slice(e * len(dataset), (e + 1) * (len(dataset)))
                        log_output(logger, e + 1, samples[sl], states[sl], scores[sl])

                # compute and record metrics if we have scores
                completed_scores = [
                    score for score in scores if isinstance(score, Score)
                ]
                if len(completed_scores) > 0:
                    results = eval_results(
                        scores=completed_scores,
                        scorer=scorer,
                        metrics=task.metrics,
                    )
                    logger.log_results(results)
                else:
                    results = EvalResults()

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


async def task_run_sample(
    task_name: str,
    sample: Sample,
    state: TaskState,
    plan: Plan,
    max_messages: int | None,
    scorer: Scorer | None,
    generate: Generate,
    progress: Callable[..., None],
    semaphore: asyncio.Semaphore | None,
) -> Score | None:

    # use semaphore if provided
    cm: asyncio.Semaphore | contextlib.AbstractAsyncContextManager[None] = (
        semaphore if semaphore else contextlib.nullcontext()
    )

    # solver loop
    async with cm:
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
                        f"Exception occurred during plan cleanup for task {task_name}: "
                        + f"{exception_message(ex)}"
                    )
                    pass

        # score it
        result = await scorer(state, Target(sample.target)) if scorer else None
        progress()

        # return
        return result


async def resolve_dataset(
    dataset: Dataset,
    model_name: ModelName,
    limit: int | tuple[int, int] | None,
    epochs: int,
    log_images: bool,
) -> tuple[Dataset, list[Sample], list[TaskState]]:
    # apply limit to dataset
    dataset_limit = (
        slice(0, len(dataset))
        if limit is None
        else (slice(*limit) if isinstance(limit, tuple) else slice(0, limit))
    )
    dataset = dataset[dataset_limit]

    # add sample ids to dataset if they aren't there (start at 1 not 0)
    for id, sample in zip(range(dataset_limit.start, dataset_limit.stop), dataset):
        if sample.id is None:
            sample.id = id + 1

    # apply epochs (deepcopy the samples so they remain independent)
    samples: list[Sample] = []
    for _ in range(0, epochs):
        samples.extend([deepcopy(sample) for sample in dataset])

    # if we are logging images then resolve sample images here
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

    return (dataset, samples, states)
