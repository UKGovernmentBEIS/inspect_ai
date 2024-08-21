import asyncio
import base64
import contextlib
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import PurePath
from typing import AsyncGenerator, Callable, Literal

from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display._display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
)
from inspect_ai._eval.task.util import sample_messages
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_MAX_CONNECTIONS,
    SAMPLE_SUBTASK,
)
from inspect_ai._util.datetime import iso_now
from inspect_ai._util.error import exception_message
from inspect_ai._util.file import file, filesystem
from inspect_ai._util.hooks import send_telemetry
from inspect_ai._util.registry import (
    is_registry_object,
    registry_log_name,
)
from inspect_ai._util.url import data_uri_to_base64, is_data_uri
from inspect_ai._view.view import view_notify_eval
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.log import (
    EvalConfig,
    EvalError,
    EvalLog,
    EvalResults,
    EvalSample,
    EvalStats,
)
from inspect_ai.log._file import eval_log_json
from inspect_ai.log._log import eval_error
from inspect_ai.model import (
    CachePolicy,
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    ModelAPI,
    ModelName,
)
from inspect_ai.scorer import Scorer, Target
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import Generate, Plan, Solver, TaskState
from inspect_ai.solver._subtask.subtask import init_subtask
from inspect_ai.solver._subtask.transcript import (
    SampleInitEvent,
    ScoreEvent,
    transcript,
)
from inspect_ai.solver._task_state import state_jsonable
from inspect_ai.util._sandbox.context import (
    cleanup_sandbox_environments_sample,
    init_sandbox_environments_sample,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironment

from ..context import init_task_context
from ..task import Task
from .generate import task_generate
from .images import samples_with_base64_images, states_with_base64_images
from .log import TaskLogger, collect_eval_data, log_plan
from .results import eval_results
from .transcript import solver_transcript

py_logger = getLogger(__name__)


EvalSampleSource = Callable[[int | str, int], EvalSample | None]


@dataclass
class TaskRunOptions:
    task: Task
    model: Model
    sandbox: tuple[str, str | None] | None
    logger: TaskLogger
    eval_wd: str
    config: EvalConfig = field(default_factory=EvalConfig)
    plan: Plan | Solver | list[Solver] | None = field(default=None)
    score: bool = field(default=True)
    sample_source: EvalSampleSource | None = field(default=None)
    sample_semaphore: asyncio.Semaphore | None = field(default=None)
    kwargs: GenerateConfigArgs = field(default_factory=lambda: GenerateConfigArgs())


async def task_run(options: TaskRunOptions) -> EvalLog:
    # destructure options
    task = options.task
    model = options.model
    sandbox = options.sandbox
    logger = options.logger
    eval_wd = options.eval_wd
    config = options.config
    plan = options.plan
    score = options.score
    sample_source = options.sample_source
    sample_semaphore = options.sample_semaphore
    kwargs = options.kwargs

    # resolve default generate_config for task
    generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

    # init task context
    init_task_context(model, generate_config)

    # track stats and error
    stats = EvalStats(started_at=iso_now())
    error: EvalError | None = None
    cancelled = False

    # resolve some config
    model_name = ModelName(model)
    epochs = config.epochs if config.epochs else DEFAULT_EPOCHS
    sandbox_cleanup = config.sandbox_cleanup is not False
    log_images = config.log_images is True
    log_samples = config.log_samples is not False

    # resolve dataset
    _, samples, states = await resolve_dataset(
        dataset=task.dataset,
        model_name=model_name,
        limit=config.limit,
        epochs=epochs,
        log_images=log_images,
        max_messages=config.max_messages,
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
    scorers: list[Scorer] | None = task.scorer if (score and task.scorer) else None
    scorer_profiles = (
        [registry_log_name(scorer) for scorer in scorers if is_registry_object(scorer)]
        if scorers is not None
        else ["(none)"]
    )

    # compute steps (steps = samples * steps in plan + 1 for scorer)
    steps = len(samples) * (
        len(plan.steps) + (1 if plan.finish else 0) + (1)  # scorer
    )

    # compute an eval directory relative log location if we can
    if PurePath(logger.location).is_relative_to(PurePath(eval_wd)):
        log_location = PurePath(logger.location).relative_to(eval_wd).as_posix()
    else:
        log_location = logger.location

    # create task profile for display
    profile = TaskProfile(
        name=task.name,
        file=logger.eval.task_file,
        model=model_name,
        dataset=task.dataset.name or "(samples)",
        scorer=", ".join(scorer_profiles),
        samples=len(samples),
        steps=steps,
        eval_config=config,
        task_args=logger.eval.task_args,
        generate_config=generate_config,
        log_location=log_location,
    )

    with display().task(profile) as td:
        try:
            # log the plan
            log_plan(logger, plan, generate_config)

            with td.progress() as p:
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
                sample_semaphore = (
                    sample_semaphore
                    if sample_semaphore
                    else create_sample_semaphore(config, generate_config, model.api)
                )

                # create sample coroutines
                sample_coroutines = [
                    task_run_sample(
                        task_name=task.name,
                        sample=sample,
                        state=state,
                        sandbox=sandbox,
                        sandbox_cleanup=sandbox_cleanup,
                        plan=plan,
                        scorers=scorers,
                        generate=generate,
                        progress=progress,
                        logger=logger if log_samples else None,
                        log_images=log_images,
                        sample_source=sample_source,
                        semaphore=sample_semaphore,
                    )
                    for (sample, state) in zip(samples, states)
                ]

                # run them in parallel (subject to config.max_samples)
                scores = await asyncio.gather(*sample_coroutines)

            # compute and record metrics if we have scores
            completed_scores = [
                score_dict for score_dict in scores if isinstance(score_dict, dict)
            ]

            if len(completed_scores) > 0:
                results = eval_results(
                    scores=completed_scores,
                    reducers=task.epochs_reducer,
                    scorers=scorers,
                    metrics=task.metrics,
                )
                logger.log_results(results)
            else:
                results = EvalResults()

            # collect eval data
            collect_eval_data(stats, logger)

            # display task summary
            td.complete(TaskSuccess(stats, results))

        except asyncio.CancelledError:
            # flag as cancelled
            cancelled = True

            # collect eval data
            collect_eval_data(stats, logger)

            # display task cancelled
            td.complete(TaskCancelled(logger.samples_logged, stats))

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
            td.complete(TaskError(logger.samples_logged, type, value, traceback))

    # log as appropriate
    if cancelled:
        eval_log = logger.log_cancelled(stats)
    elif error:
        eval_log = logger.log_failure(stats, error)
    else:
        eval_log = logger.log_success(stats)

    # notify the view module that an eval just completed
    # (in case we have a view polling for new evals)
    view_notify_eval(logger.location)

    try:
        await send_telemetry("eval_log", eval_log_json(eval_log))
    except Exception as ex:
        py_logger.warning(f"Error occurred sending telemetry: {exception_message(ex)}")

    # return eval log
    return eval_log


async def task_run_sample(
    task_name: str,
    sample: Sample,
    state: TaskState,
    sandbox: tuple[str, str | None] | None,
    sandbox_cleanup: bool,
    plan: Plan,
    scorers: list[Scorer] | None,
    generate: Generate,
    progress: Callable[..., None],
    logger: TaskLogger | None,
    log_images: bool,
    sample_source: EvalSampleSource | None,
    semaphore: asyncio.Semaphore | None,
) -> dict[str, SampleScore] | None:
    # if there is an existing sample then tick off its progress, log it, and return it
    if sample_source and sample.id is not None:
        previous_sample = sample_source(sample.id, state.epoch)
        if previous_sample:
            # tick off progress
            for _ in range(0, len(plan.steps) + 1 + (1 if plan.finish else 0)):
                progress()
            # log if requested
            if logger:
                logger.log("sample", previous_sample, False)

            # return score
            if previous_sample.scores:
                return {
                    key: SampleScore(
                        value=score.value,
                        answer=score.answer,
                        explanation=score.explanation,
                        sample_id=previous_sample.id,
                    )
                    for key, score in previous_sample.scores.items()
                }

    # use semaphore if provided
    semaphore_cm: asyncio.Semaphore | contextlib.AbstractAsyncContextManager[None] = (
        semaphore if semaphore else contextlib.nullcontext()
    )

    # initialise subtask
    init_subtask(SAMPLE_SUBTASK, state.store)

    # use toolenv if provided
    sandboxenv_cm = (
        sandboxenv_context(task_name, sandbox, sandbox_cleanup, sample)
        if sandbox
        else contextlib.nullcontext()
    )

    # solver loop
    async with semaphore_cm, sandboxenv_cm:
        try:
            # sample init event (remove file bodies as they have content or absolute paths)
            event_sample = sample.model_copy(
                update=dict(files={k: "" for k in sample.files.keys()})
                if sample.files
                else None
            )
            transcript()._event(
                SampleInitEvent(sample=event_sample, state=state_jsonable(state))
            )

            # run plan steps (checking for early termination)
            for index, solver in enumerate(plan.steps):
                # run the solver
                with solver_transcript(solver, state) as st:
                    state = await solver(state, generate)
                    st.complete(state)
                progress()

                # check for early termination (tick remaining progress)
                if state.completed:
                    for _ in range(index + 1, len(plan.steps)):
                        progress()
                    break

            # run finishing step them mark completed
            if plan.finish:
                with solver_transcript(plan.finish, state) as st:
                    state = await plan.finish(state, generate)
                    st.complete(state)
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
        results: dict[str, SampleScore] = {}
        if scorers:
            for scorer in scorers:
                scorer_name = unique_scorer_name(scorer, list(results.keys()))
                with transcript().step(name=scorer_name, type="scorer"):
                    score_result = (
                        await scorer(state, Target(sample.target)) if scorer else None
                    )
                    if score_result is not None:
                        sample_score = SampleScore(
                            value=score_result.value,
                            answer=score_result.answer,
                            explanation=score_result.explanation,
                            metadata=score_result.metadata,
                            sample_id=sample.id,
                        )
                        transcript()._event(ScoreEvent(score=score_result))
                        results[scorer_name] = sample_score
        progress()

        # log it
        if logger is not None:
            # if we are logging images then be sure to base64 images injected by solvers
            if log_images:
                state = (await states_with_base64_images([state]))[0]

            # log the sample
            logger.log_sample(state.epoch, sample, state, results, True)

        # return
        return results


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
def create_sample_semaphore(
    config: EvalConfig,
    generate_config: GenerateConfig,
    modelapi: ModelAPI | None = None,
) -> asyncio.Semaphore:
    # if the user set max_samples then use that
    if config.max_samples is not None:
        return asyncio.Semaphore(config.max_samples)

    # use max_connections
    max_samples = (
        generate_config.max_connections
        if generate_config.max_connections is not None
        else modelapi.max_connections()
        if modelapi
        else DEFAULT_MAX_CONNECTIONS
    )

    # if max_tasks is specified and max_samples is less
    # than max_tasks then bump it up
    if config.max_tasks is not None:
        max_samples = max(max_samples, config.max_tasks)

    # return the semaphore
    return asyncio.Semaphore(max_samples)


@contextlib.asynccontextmanager
async def sandboxenv_context(
    task_name: str,
    sandbox: tuple[str, str | None],
    cleanup: bool,
    sample: Sample,
) -> AsyncGenerator[None, None]:
    # read files from sample
    files: dict[str, bytes] = {}
    if sample.files:
        for path, contents in sample.files.items():
            files[path] = read_sandboxenv_file(contents)

    # read setup script from sample (add bash shebang if necessary)
    setup: bytes | None = None
    if sample.setup:
        setup = read_sandboxenv_file(sample.setup)
        setup_str = setup.decode(encoding="utf-8")
        if not setup_str.strip().startswith("#!"):
            setup_str = f"#!/usr/bin/env bash\n\n{setup_str}"
            setup = setup_str.encode(encoding="utf-8")

    interrupted = False
    environments: dict[str, SandboxEnvironment] | None = None
    try:
        # initialize sandbox environment,
        environments = await init_sandbox_environments_sample(
            type=sandbox[0],
            task_name=task_name,
            config=sandbox[1],
            files=files,
            setup=setup,
            metadata=sample.metadata if sample.metadata else {},
        )

        # run sample
        yield

    except BaseException as ex:
        interrupted = True
        raise ex

    finally:
        # cleanup sandbox environment
        if environments and cleanup:
            await cleanup_sandbox_environments_sample(
                type=sandbox[0],
                task_name=task_name,
                config=sandbox[1],
                environments=environments,
                interrupted=interrupted,
            )


def read_sandboxenv_file(contents: str) -> bytes:
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

    return file_bytes
