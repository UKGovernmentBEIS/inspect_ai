import asyncio
import contextlib
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import PurePath
from typing import Callable, Literal, cast

from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display._display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
)
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_MAX_CONNECTIONS,
    SAMPLE_SUBTASK,
)
from inspect_ai._util.datetime import iso_now
from inspect_ai._util.error import exception_message
from inspect_ai._util.hooks import send_telemetry
from inspect_ai._util.registry import (
    is_registry_object,
    registry_log_name,
)
from inspect_ai._view.notify import view_notify_eval
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.log import (
    EvalConfig,
    EvalError,
    EvalLog,
    EvalResults,
    EvalSample,
    EvalStats,
)
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._file import eval_log_json
from inspect_ai.log._log import EvalSampleReductions, eval_error
from inspect_ai.log._transcript import (
    ErrorEvent,
    SampleInitEvent,
    ScoreEvent,
    transcript,
)
from inspect_ai.model import (
    CachePolicy,
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    ModelAPI,
    ModelName,
)
from inspect_ai.model._model import init_sample_model_usage, sample_model_usage
from inspect_ai.scorer import Scorer, Target
from inspect_ai.scorer._metric import SampleScore, Score
from inspect_ai.scorer._score import init_scoring_context
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import Generate, Plan, TaskState
from inspect_ai.solver._chain import Chain, unroll
from inspect_ai.solver._fork import set_task_generate
from inspect_ai.solver._solver import Solver
from inspect_ai.solver._task_state import set_sample_state, state_jsonable
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._subtask import init_subtask

from ..context import init_task_context
from ..task import Task
from .error import SampleErrorHandler
from .generate import task_generate
from .images import (
    sample_without_base64_images,
    samples_with_base64_images,
    state_without_base64_images,
    states_with_base64_images,
)
from .log import TaskLogger, collect_eval_data, log_start
from .results import eval_results
from .rundir import set_task_run_dir
from .sandbox import sandboxenv_context
from .util import sample_messages, task_run_dir

py_logger = getLogger(__name__)


EvalSampleSource = Callable[[int | str, int], EvalSample | None]


@dataclass
class TaskRunOptions:
    task: Task
    model: Model
    sandbox: SandboxEnvironmentSpec | None
    logger: TaskLogger
    eval_wd: str
    config: EvalConfig = field(default_factory=EvalConfig)
    solver: Solver | None = field(default=None)
    tags: list[str] | None = field(default=None)
    score: bool = field(default=True)
    debug_errors: bool = field(default=False)
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
    solver = options.solver
    tags = options.tags
    score = options.score
    sample_source = options.sample_source
    sample_semaphore = options.sample_semaphore
    kwargs = options.kwargs

    # resolve default generate_config for task
    generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

    # init task context
    init_task_context(model, generate_config)

    # establish run_dir for duration of execution
    with set_task_run_dir(task_run_dir(task)):
        # track stats and error
        results: EvalResults | None = None
        reductions: list[EvalSampleReductions] | None = None
        stats = EvalStats(started_at=iso_now())
        error: EvalError | None = None
        cancelled = False

        # handle sample errors (raise as required)
        sample_error_handler = SampleErrorHandler(
            config.fail_on_error, len(task.dataset)
        )

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
            message_limit=config.message_limit,
            token_limit=config.token_limit,
        )

        # resolve the plan (unroll chains)
        solver = solver or task.solver
        if isinstance(solver, Plan):
            plan = solver
        elif isinstance(solver, Chain):
            plan = Plan(list(solver), internal=True)
        else:
            plan = Plan(unroll(solver), internal=True)

        # reaolve the scorer
        score = score and task.scorer is not None
        scorers: list[Scorer] | None = task.scorer if (score and task.scorer) else None
        scorer_profiles = (
            [
                registry_log_name(scorer)
                for scorer in scorers
                if is_registry_object(scorer)
            ]
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
            tags=tags,
            log_location=log_location,
        )

        with display().task(profile) as td:
            try:
                # start the log
                log_start(logger, plan, generate_config)

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

                    # set generate for fork module
                    set_task_generate(generate)

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
                            sample_error=sample_error_handler,
                            semaphore=sample_semaphore,
                        )
                        for (sample, state) in zip(samples, states)
                    ]

                    # run them in parallel (subject to config.max_samples)
                    sample_results = await asyncio.gather(*sample_coroutines)

                # compute and record metrics if we have scores
                completed_scores = [
                    score_dict
                    for score_dict in sample_results
                    if isinstance(score_dict, dict)
                ]

                if len(completed_scores) > 0:
                    results, reductions = eval_results(
                        samples=profile.samples,
                        scores=completed_scores,
                        reducers=task.epochs_reducer,
                        scorers=scorers,
                        metrics=task.metrics,
                    )

                # collect eval data
                collect_eval_data(stats)

                # display task summary
                td.complete(
                    TaskSuccess(
                        samples_completed=logger.samples_completed,
                        stats=stats,
                        results=results or EvalResults(),
                    )
                )

            except asyncio.CancelledError:
                # flag as cancelled
                cancelled = True

                # collect eval data
                collect_eval_data(stats)

                # display task cancelled
                td.complete(TaskCancelled(logger.samples_completed, stats))

            except BaseException as ex:
                if options.debug_errors:
                    raise
                else:
                    # get exception info
                    type, value, traceback = sys.exc_info()
                    type = type if type else BaseException
                    value = value if value else ex

                    # build eval error
                    error = eval_error(ex, type, value, traceback)

                    # collect eval data
                    collect_eval_data(stats)

                    # display it
                    td.complete(
                        TaskError(logger.samples_completed, type, value, traceback)
                    )

        # log as appropriate
        if cancelled:
            eval_log = logger.log_finish("cancelled", stats, results, reductions)
        elif error:
            eval_log = logger.log_finish("error", stats, results, reductions, error)
        else:
            eval_log = logger.log_finish("success", stats, results, reductions)

        # notify the view module that an eval just completed
        # (in case we have a view polling for new evals)
        view_notify_eval(logger.location)

        try:
            await send_telemetry("eval_log", eval_log_json(eval_log))
        except Exception as ex:
            py_logger.warning(
                f"Error occurred sending telemetry: {exception_message(ex)}"
            )

        # return eval log
        return eval_log


async def task_run_sample(
    task_name: str,
    sample: Sample,
    state: TaskState,
    sandbox: SandboxEnvironmentSpec | None,
    sandbox_cleanup: bool,
    plan: Plan,
    scorers: list[Scorer] | None,
    generate: Generate,
    progress: Callable[..., None],
    logger: TaskLogger | None,
    log_images: bool,
    sample_source: EvalSampleSource | None,
    sample_error: Callable[[BaseException], EvalError],
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
                logger.log_sample(previous_sample, flush=False)

            # return score
            if previous_sample.scores:
                return {
                    key: SampleScore(
                        sample_id=previous_sample.id,
                        value=score.value,
                        answer=score.answer,
                        explanation=score.explanation,
                        metadata=score.metadata,
                    )
                    for key, score in previous_sample.scores.items()
                }
            else:
                return {}

    # use semaphore if provided
    semaphore_cm: asyncio.Semaphore | contextlib.AbstractAsyncContextManager[None] = (
        semaphore if semaphore else contextlib.nullcontext()
    )

    # initialise subtask and scoring context
    init_sample_model_usage()
    set_sample_state(state)
    init_subtask(SAMPLE_SUBTASK, state.store)
    if scorers:
        init_scoring_context(scorers, Target(sample.target))

    # use sandbox if provided
    sandboxenv_cm = (
        sandboxenv_context(task_name, sandbox, sandbox_cleanup, sample)
        if sandbox or sample.sandbox is not None
        else contextlib.nullcontext()
    )

    # solver loop
    async with semaphore_cm, sandboxenv_cm:
        error: EvalError | None = None
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

            # set progress for plan then run it
            plan.progress = progress
            state = await plan(state, generate)

        except asyncio.CancelledError:
            # allow cancelled error to propagate
            raise

        except BaseException as ex:
            # handle error (this will throw if we've exceeded the limit)
            error = sample_error(ex)

            # fire error event
            transcript()._event(ErrorEvent(error=error))

        # score it
        results: dict[str, SampleScore] = {}
        if scorers and error is None:
            for scorer in scorers:
                scorer_name = unique_scorer_name(scorer, list(results.keys()))
                with transcript().step(name=scorer_name, type="scorer"):
                    score_result = (
                        await scorer(state, Target(sample.target)) if scorer else None
                    )
                    if score_result is not None:
                        sample_score = SampleScore(
                            sample_id=sample.id,
                            value=score_result.value,
                            answer=score_result.answer,
                            explanation=score_result.explanation,
                            metadata=score_result.metadata,
                        )
                        transcript()._event(
                            ScoreEvent(score=score_result, target=sample.target)
                        )
                        results[scorer_name] = sample_score
        progress()

        # log it
        if logger is not None:
            # if we are logging images then be sure to base64 images injected by solvers
            if log_images:
                state = (await states_with_base64_images([state]))[0]

            # otherwise ensure there are no base64 images in sample or messages
            else:
                sample = sample_without_base64_images(sample)
                state = state_without_base64_images(state)

            # log the sample
            log_sample(
                logger=logger,
                sample=sample,
                state=state,
                scores=results,
                error=error,
                log_images=log_images,
            )

        # return
        if error is None:
            return results
        else:
            return None


def log_sample(
    logger: TaskLogger,
    sample: Sample,
    state: TaskState,
    scores: dict[str, SampleScore],
    error: EvalError | None,
    log_images: bool,
) -> None:
    # sample must have id to be logged
    id = sample.id
    if id is None:
        raise ValueError(
            f"Samples without IDs cannot be logged: {sample.model_dump_json()}"
        )

    # construct sample for logging
    eval_sample = EvalSample(
        id=id,
        epoch=state.epoch,
        input=sample.input,
        choices=sample.choices,
        target=sample.target,
        metadata=state.metadata if state.metadata else {},
        sandbox=sample.sandbox,
        files=list(sample.files.keys()) if sample.files else None,
        setup=sample.setup,
        messages=state.messages,
        output=state.output,
        scores=cast(dict[str, Score], scores),
        store=dict(state.store.items()),
        events=transcript().events,
        model_usage=sample_model_usage(),
        error=error,
    )

    logger.log_sample(condense_sample(eval_sample, log_images), flush=True)


async def resolve_dataset(
    dataset: Dataset,
    model_name: ModelName,
    limit: int | tuple[int, int] | None,
    epochs: int,
    log_images: bool,
    message_limit: int | None,
    token_limit: int | None,
) -> tuple[Dataset, list[Sample], list[TaskState]]:
    # apply limit to dataset
    dataset_limit = (
        slice(0, len(dataset))
        if limit is None
        else (slice(*limit) if isinstance(limit, tuple) else slice(0, limit))
    )
    dataset = dataset[dataset_limit]

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
                message_limit=message_limit,
                token_limit=token_limit,
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
            "Unable to re-use samples from retry log file because the dataset size changed "
            + f"(log samples {eval_log.eval.dataset.samples}, dataset samples {len(dataset)})"
        )
        return no_sample_source
    else:

        def previous(id: int | str, epoch: int) -> EvalSample | None:
            return next(
                (
                    sample
                    for sample in (eval_log.samples or [])
                    if sample.id == id
                    and sample.epoch == epoch
                    and sample.error is None
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
