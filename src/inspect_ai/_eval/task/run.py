import asyncio
import base64
import contextlib
import sys
from copy import deepcopy
from logging import getLogger
from typing import AsyncGenerator, Awaitable, Callable, Literal

from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display._display import TaskProfile
from inspect_ai._util.constants import DEFAULT_EPOCHS
from inspect_ai._util.datetime import iso_now
from inspect_ai._util.dotenv import dotenv_environ
from inspect_ai._util.error import exception_message
from inspect_ai._util.file import file, filesystem
from inspect_ai._util.path import chdir_python
from inspect_ai._util.registry import (
    is_registry_object,
    registry_log_name,
)
from inspect_ai._util.url import data_uri_to_base64, is_data_uri
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.log import (
    EvalConfig,
    EvalError,
    EvalLog,
    EvalResults,
    EvalSample,
    EvalStats,
)
from inspect_ai.log._log import eval_error
from inspect_ai.model import (
    CachePolicy,
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    ModelAPI,
    ModelName,
)
from inspect_ai.scorer import Score, Scorer, Target
from inspect_ai.solver import Generate, Plan, Solver, TaskState, ToolEnvironment
from inspect_ai.solver._tool.environment.context import (
    cleanup_tool_environments_sample,
    init_tool_environments_sample,
    startup_tool_environments,
)

from ..task import Task
from .generate import task_generate
from .images import samples_with_base64_images, states_with_base64_images
from .log import TaskLogger, collect_eval_data, log_plan
from .results import eval_results
from .util import sample_messages, task_run_dir

py_logger = getLogger(__name__)


EvalSampleSource = Callable[[int | str, int], EvalSample | None]


async def task_run(
    task: Task,
    sequence: tuple[int, int],
    model: Model,
    logger: TaskLogger,
    config: EvalConfig = EvalConfig(),
    plan: Plan | Solver | list[Solver] | None = None,
    score: bool = True,
    sample_source: EvalSampleSource | None = None,
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
        sample_source (EvalSampleSource | None): Source from which
          previously executed samples can be found/returned
        **kwargs (GenerateConfigArgs): Generation config options

    Returns:
      EvalLog for executed task.

    """
    with chdir_python(task_run_dir(task)), dotenv_environ():
        # track stats and error
        stats = EvalStats(started_at=iso_now())
        error: EvalError | None = None
        cancelled = False

        # resolve some config
        model_name = ModelName(model)
        epochs = config.epochs if config.epochs else DEFAULT_EPOCHS
        toolenv_cleanup = config.toolenv_cleanup is not False
        log_images = config.log_images is not False
        log_samples = config.log_samples is not False
        generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

        # resolve dataset
        _, samples, states = await resolve_dataset(
            dataset=task.dataset,
            model_name=model_name,
            limit=config.limit,
            epochs=epochs,
            log_images=log_images,
            max_messages=config.max_messages,
        )

        # resolve tool_environment
        if task.tool_environment:
            tool_environment = (
                logger.eval.tool_environment
                if logger.eval.tool_environment
                else task.tool_environment
            )
        else:
            tool_environment = None

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

        # run startup pass for the tool_environment
        shutdown_tool_environments: Callable[[], Awaitable[None]] | None = None
        if tool_environment:
            shutdown_tool_environments = await startup_tool_environments(
                task.name, tool_environment, toolenv_cleanup
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
                        state: TaskState,
                        tool_calls: Literal["loop", "single", "none"] = "loop",
                        cache: bool | CachePolicy = False,
                        **kwargs: Unpack[GenerateConfigArgs],
                    ) -> TaskState:
                        return await task_generate(
                            model=model,
                            state=state,
                            tool_calls=tool_calls,
                            cache=cache,
                            config=generate_config.merge(kwargs),
                        )

                    # semaphore to limit concurrency
                    task_semaphore = create_task_semaphone(
                        config, generate_config, model.api
                    )

                    # create tasks
                    tasks = [
                        task_run_sample(
                            task_name=task.name,
                            sample=sample,
                            state=state,
                            tool_environment=tool_environment,
                            toolenv_cleanup=toolenv_cleanup,
                            plan=plan,
                            max_messages=config.max_messages,
                            scorer=scorer,
                            generate=generate,
                            progress=progress,
                            logger=logger if log_samples else None,
                            log_images=log_images,
                            sample_source=sample_source,
                            semaphore=task_semaphore,
                        )
                        for (sample, state) in zip(samples, states)
                    ]

                    # run them in parallel (subject to config.max_samples)
                    scores = await asyncio.gather(*tasks)

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

            except (asyncio.CancelledError, KeyboardInterrupt):
                # flag as cancelled
                cancelled = True

                # collect eval data
                collect_eval_data(stats, logger)

                # display task cancelled
                td.cancelled(logger.samples_logged, stats)

            except BaseException as ex:
                # get exception info
                type, value, traceback = sys.exc_info()
                type = type if type else BaseException
                value = value if value else ex

                # build eval error
                error = eval_error(ex, type, value, traceback)

                # collect eval data
                collect_eval_data(stats, logger)

                # display it
                td.error(logger.samples_logged, error, type, value, traceback)

        # log as appropriate
        if cancelled:
            eval_log = logger.log_cancelled(stats)
        elif error:
            eval_log = logger.log_failure(stats, error)
        else:
            eval_log = logger.log_success(stats)

        # run tool environment shutdown if we have it
        if shutdown_tool_environments:
            try:
                await shutdown_tool_environments()
            except BaseException as ex:
                py_logger.warning(
                    f"Error occurred shutting down tool environments: {exception_message(ex)}"
                )

    # return eval log
    return eval_log


async def task_run_sample(
    task_name: str,
    sample: Sample,
    state: TaskState,
    tool_environment: tuple[str, str | None] | None,
    toolenv_cleanup: bool,
    plan: Plan,
    max_messages: int | None,
    scorer: Scorer | None,
    generate: Generate,
    progress: Callable[..., None],
    logger: TaskLogger | None,
    log_images: bool,
    sample_source: EvalSampleSource | None,
    semaphore: asyncio.Semaphore | None,
) -> Score | None:
    # if there is an existing sample then tick off its progress, log it, and return it
    if sample_source and sample.id is not None:
        previous_sample = sample_source(sample.id, state.epoch)
        if previous_sample:
            # tick off progress
            for _ in range(0, len(plan.steps) + 1 + (1 if plan.finish else 0)):
                progress()
            # log if requested
            if logger:
                logger.log_event("sample", previous_sample, False)

            # return score
            return previous_sample.score

    # use semaphore if provided
    semaphore_cm: asyncio.Semaphore | contextlib.AbstractAsyncContextManager[None] = (
        semaphore if semaphore else contextlib.nullcontext()
    )

    # use toolenv if provided
    toolenv_cm = (
        toolenv_context(task_name, tool_environment, toolenv_cleanup, sample)
        if tool_environment
        else contextlib.nullcontext()
    )

    # solver loop
    async with semaphore_cm, toolenv_cm:
        try:
            # run plan steps (checking for early termination)
            for index, solver in enumerate(plan.steps):
                # run the solver
                state = await solver(state, generate)
                progress()

                # check for early termination (tick remaining progress)
                if state.completed:
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
                    py_logger.warning(
                        f"Exception occurred during plan cleanup for task {task_name}: "
                        + f"{exception_message(ex)}"
                    )

        # score it
        result = await scorer(state, Target(sample.target)) if scorer else None
        progress()

        # log it
        if logger is not None:
            # if we are logging images then be sure to base64 images injected by solvers
            if log_images:
                state = (await states_with_base64_images([state]))[0]

            # log the sample
            logger.log_sample(state.epoch, sample, state, result, True)

        # return
        return result


async def resolve_dataset(
    dataset: Dataset,
    model_name: ModelName,
    limit: int | tuple[int, int] | None,
    epochs: int,
    log_images: bool,
    max_messages: int | None,
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
                max_messages=max_messages,
                completed=False,
                metadata=sample.metadata if sample.metadata else {},
            )
        )
        for epoch, sample in zip(sample_epochs, samples)
    ]

    return (dataset, samples, states)


# we can reuse samples from a previous eval_log if and only if:
#   - The datasets have not been shuffled OR the samples in the dataset have unique ids
#   - The datasets have the exact same length
def eval_log_sample_source(
    eval_log: EvalLog | None, dataset: Dataset
) -> EvalSampleSource:
    # return dummy function for no sample source
    def no_sample_source(id: int | str, epoch: int) -> None:
        return None

    # take care of no log or no samples in log
    if not eval_log:
        return no_sample_source
    elif not eval_log.samples or len(eval_log.samples) == 0:
        return no_sample_source

    # determine whether all samples in the dataset have ids (if not, then we can't
    # provide a sample source in the case where either dataset is shuffled, as the ids
    # will be auto-assigned based on position, and therefore not stable)
    samples_have_ids = (
        next((sample for sample in dataset if sample.id is None), None) is None
    )

    if (eval_log.eval.dataset.shuffled or dataset.shuffled) and not samples_have_ids:
        py_logger.warning(
            "Unable to re-use samples from retry log file because the dataset was shuffled "
            + "and some samples in the dataset do not have an 'id' field."
        )
        return no_sample_source

    elif eval_log.eval.dataset.samples != len(dataset):
        py_logger.warning(
            "Unable to re-use samples from retry log file because the dataset size changed"
        )
        return no_sample_source
    else:

        def previous(id: int | str, epoch: int) -> EvalSample | None:
            return next(
                (
                    sample
                    for sample in (eval_log.samples or [])
                    if sample.id == id and sample.epoch == epoch
                ),
                None,
            )

        return previous


# semaphore to limit concurrency. default max_samples to
# max_connections + 1 if not explicitly specified (this is
# to make sure it always saturates the connection pool)
def create_task_semaphone(
    config: EvalConfig, generate_config: GenerateConfig, modelapi: ModelAPI
) -> asyncio.Semaphore:
    max_samples = (
        config.max_samples
        if config.max_samples is not None
        else (
            generate_config.max_connections
            if generate_config.max_connections is not None
            else modelapi.max_connections()
        )
        + 1
    )
    return asyncio.Semaphore(max_samples)


@contextlib.asynccontextmanager
async def toolenv_context(
    task_name: str,
    tool_environment: tuple[str, str | None],
    cleanup: bool,
    sample: Sample,
) -> AsyncGenerator[None, None]:
    # read files from sample
    files: dict[str, bytes] = {}
    if sample.files:
        for path, contents in sample.files.items():
            if is_data_uri(contents):
                contents_base64 = data_uri_to_base64(contents)
                file_bytes = base64.b64decode(contents_base64)
            else:
                # try to read as a file (if it doesn't exist or has a path not cool w/
                # the fileystem then we fall back to contents)
                try:
                    fs = filesystem(contents)
                    if fs.exists(contents):
                        with file(contents, "rb") as f:
                            file_bytes = f.read()
                    else:
                        file_bytes = contents.encode("utf-8")
                except Exception:
                    file_bytes = contents.encode("utf-8")

            # record resolved bytes
            files[path] = file_bytes

    interrupted = False
    environments: dict[str, ToolEnvironment] | None = None
    try:
        # initialize tool environment,
        environments = await init_tool_environments_sample(
            type=tool_environment[0],
            task_name=task_name,
            config=tool_environment[1],
            files=files,
            metadata=sample.metadata if sample.metadata else {},
        )

        # run sample
        yield

    except BaseException as ex:
        interrupted = True
        raise ex

    finally:
        # cleanup tool environment
        if environments and cleanup:
            await cleanup_tool_environments_sample(
                type=tool_environment[0],
                task_name=task_name,
                config=tool_environment[1],
                environments=environments,
                interrupted=interrupted,
            )
