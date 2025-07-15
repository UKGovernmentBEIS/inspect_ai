import contextlib
import functools
import sys
import time
from copy import copy, deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from logging import getLogger
from pathlib import PurePath
from typing import Callable, Literal

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
    display,
)
from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._util._async import tg_collect
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_CONNECTIONS_BATCH,
)
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.error import exception_message
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.registry import (
    is_registry_object,
    registry_log_name,
    registry_unqualified_name,
)
from inspect_ai._util.working import init_sample_working_time, sample_waiting_time
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
from inspect_ai.log._file import eval_log_json_str
from inspect_ai.log._log import (
    EvalSampleLimit,
    EvalSampleReductions,
    EvalSampleSummary,
    eval_error,
)
from inspect_ai.log._samples import (
    active_sample,
)
from inspect_ai.log._transcript import (
    ErrorEvent,
    SampleInitEvent,
    SampleLimitEvent,
    ScoreEvent,
    Transcript,
    init_transcript,
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
from inspect_ai.scorer._metric import Metric, SampleScore
from inspect_ai.scorer._reducer.types import ScoreReducer
from inspect_ai.scorer._score import init_scoring_context
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import Generate, Plan, TaskState
from inspect_ai.solver._chain import Chain, unroll
from inspect_ai.solver._fork import set_task_generate
from inspect_ai.solver._solver import Solver
from inspect_ai.solver._task_state import sample_state, set_sample_state, state_jsonable
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._limit import LimitExceededError
from inspect_ai.util._limit import time_limit as create_time_limit
from inspect_ai.util._limit import working_limit as create_working_limit
from inspect_ai.util._sandbox.context import sandbox_connections
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._span import span
from inspect_ai.util._store import init_subtask_store

from ..context import init_task_context
from ..task import Task
from .error import SampleErrorHandler
from .generate import task_generate
from .images import (
    sample_without_base64_content,
    samples_with_base64_content,
    state_without_base64_content,
    states_with_base64_content,
)
from .log import TaskLogger, collect_eval_data, log_start
from .results import eval_results
from .sandbox import sandboxenv_context
from .util import sample_messages, slice_dataset

py_logger = getLogger(__name__)


EvalSampleSource = Callable[[int | str, int], EvalSample | None]

# Units allocated for sample progress - the total units
# represents the total units of progress for an individual sample
# the remainder are increments of progress within a sample (and
# must sum to the total_progress_units when the sample is complete)
SAMPLE_TOTAL_PROGRESS_UNITS = 1


@dataclass
class TaskRunOptions:
    task: Task
    model: Model
    model_roles: dict[str, Model] | None
    sandbox: SandboxEnvironmentSpec | None
    logger: TaskLogger
    eval_wd: str
    config: EvalConfig = field(default_factory=EvalConfig)
    solver: Solver | None = field(default=None)
    tags: list[str] | None = field(default=None)
    run_samples: bool | None = field(default=True)
    score: bool = field(default=True)
    debug_errors: bool = field(default=False)
    sample_source: EvalSampleSource | None = field(default=None)
    kwargs: GenerateConfigArgs = field(default_factory=lambda: GenerateConfigArgs())


async def task_run(options: TaskRunOptions) -> EvalLog:
    from inspect_ai.hooks._hooks import emit_task_end, emit_task_start
    from inspect_ai.hooks._legacy import send_telemetry_legacy

    # destructure options
    task = options.task
    model = options.model
    model_roles = options.model_roles
    sandbox = options.sandbox
    logger = options.logger
    eval_wd = options.eval_wd
    config = options.config
    solver = options.solver
    tags = options.tags
    score = options.score
    sample_source = options.sample_source
    kwargs = options.kwargs

    # resolve default generate_config for task
    generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

    # init task context
    init_task_context(model, model_roles, options.task.approval, generate_config)

    # track stats and error
    results: EvalResults | None = None
    reductions: list[EvalSampleReductions] | None = None
    stats = EvalStats(started_at=iso_now())

    # handle sample errors (raise as required)
    sample_error_handler = SampleErrorHandler(config.fail_on_error, len(task.dataset))

    # resolve some config
    model_name = ModelName(model)
    epochs = config.epochs if config.epochs else DEFAULT_EPOCHS
    sandbox_cleanup = config.sandbox_cleanup is not False
    log_images = config.log_images is not False
    log_samples = config.log_samples is not False

    # resolve dataset
    _, samples, states = await resolve_dataset(
        dataset=task.dataset,
        model_name=model_name,
        limit=config.limit,
        sample_id=config.sample_id,
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
        plan = Plan(list(solver), cleanup=task.cleanup, internal=True)
    else:
        plan = Plan(unroll(solver), cleanup=task.cleanup, internal=True)

    # add setup solver(s) if specified
    if task.setup:
        plan.steps = unroll(task.setup) + plan.steps

    # resolve the scorer
    score = score and task.scorer is not None
    scorers: list[Scorer] | None = task.scorer if (score and task.scorer) else None
    scorer_profiles = (
        [registry_log_name(scorer) for scorer in scorers if is_registry_object(scorer)]
        if scorers is not None
        else ["(none)"]
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
        steps=len(samples) * SAMPLE_TOTAL_PROGRESS_UNITS,
        eval_config=config,
        task_args=logger.eval.task_args_passed,
        generate_config=generate_config,
        tags=tags,
        log_location=log_location,
    )

    with display().task(
        profile,
    ) as td:
        try:
            # start the log
            await log_start(logger, plan, generate_config)

            # return immediately if we are not running samples
            if not options.run_samples:
                return await logger.log_finish("started", stats)

            # call hook
            await emit_task_start(logger)

            with td.progress() as p:
                # forward progress
                def progress(number: int) -> None:
                    p.update(number)

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
                sample_semaphore = create_sample_semaphore(
                    config, generate_config, model.api
                )

                # track when samples complete and update progress as we go
                progress_results: list[dict[str, SampleScore]] = []

                def update_metrics(metrics: list[TaskDisplayMetric]) -> None:
                    td.update_metrics(metrics)
                    logger.update_metrics(metrics)

                update_metrics_display = update_metrics_display_fn(
                    update_metrics,
                    display_metrics=profile.eval_config.score_display is not False,
                )

                def sample_complete(sample_score: dict[str, SampleScore]) -> None:
                    # Capture the result
                    progress_results.append(sample_score)

                    # Increment the segment progress
                    td.sample_complete(
                        complete=len(progress_results), total=len(samples)
                    )

                    # Update metrics
                    update_metrics_display(
                        len(progress_results),
                        progress_results,
                        scorers,
                        task.epochs_reducer,
                        task.metrics,
                    )

                # initial progress
                td.sample_complete(complete=0, total=len(samples))

                # Update metrics to empty state
                update_metrics_display(
                    len(progress_results),
                    progress_results,
                    scorers,
                    task.epochs_reducer,
                    task.metrics,
                )

                async def run_sample(
                    sample: Sample, state: TaskState
                ) -> dict[str, SampleScore] | None:
                    result: dict[str, SampleScore] | None = None

                    async def run(tg: TaskGroup) -> None:
                        try:
                            nonlocal result
                            result = await task_run_sample(
                                tg=tg,
                                task_name=task.name,
                                log_location=profile.log_location,
                                sample=sample,
                                state=state,
                                sandbox=sandbox,
                                max_sandboxes=config.max_sandboxes,
                                sandbox_cleanup=sandbox_cleanup,
                                plan=plan,
                                scorers=scorers,
                                generate=generate,
                                progress=progress,
                                logger=logger if log_samples else None,
                                log_images=log_images,
                                sample_source=sample_source,
                                sample_error=sample_error_handler,
                                sample_complete=sample_complete,
                                fails_on_error=(
                                    config.fail_on_error is None
                                    or config.fail_on_error is True
                                ),
                                retry_on_error=config.retry_on_error or 0,
                                error_retries=[],
                                time_limit=config.time_limit,
                                working_limit=config.working_limit,
                                semaphore=sample_semaphore,
                                run_id=logger.eval.run_id,
                                task_id=logger.eval.eval_id,
                            )
                        finally:
                            tg.cancel_scope.cancel()

                    try:
                        async with anyio.create_task_group() as tg:
                            tg.start_soon(run, tg)
                    except Exception as ex:
                        raise inner_exception(ex)

                    return result

                sample_results = await tg_collect(
                    [
                        functools.partial(run_sample, sample, state)
                        for (sample, state) in zip(
                            samples,
                            states,
                        )
                    ]
                )

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

            # finish w/ success status
            eval_log = await logger.log_finish("success", stats, results, reductions)

            await emit_task_end(logger, eval_log)

            # display task summary
            td.complete(
                TaskSuccess(
                    samples_completed=logger.samples_completed,
                    stats=stats,
                    results=results or EvalResults(),
                )
            )

        except anyio.get_cancelled_exc_class():
            with anyio.CancelScope(shield=True):
                # collect eval data
                collect_eval_data(stats)

                # finish w/ cancelled status
                eval_log = await logger.log_finish(
                    "cancelled", stats, results, reductions
                )

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

                # finish with error status
                eval_log = await logger.log_finish(
                    "error", stats, results, reductions, error
                )

                # display it
                td.complete(TaskError(logger.samples_completed, type, value, traceback))

    # notify the view module that an eval just completed
    # (in case we have a view polling for new evals)
    view_notify_eval(logger.location)

    try:
        # Log file locations are emitted to the "new" hooks via the "task end" event,
        if (
            await send_telemetry_legacy("eval_log_location", eval_log.location)
            == "not_handled"
        ):
            # Converting the eval log to JSON is expensive. Only do so if
            # eval_log_location was not handled.
            await send_telemetry_legacy("eval_log", eval_log_json_str(eval_log))
    except Exception as ex:
        py_logger.warning(f"Error occurred sending telemetry: {exception_message(ex)}")

    # return eval log
    return eval_log


def update_metrics_display_fn(
    update_fn: Callable[[list[TaskDisplayMetric]], None],
    initial_interval: float = 0,
    min_interval: float = 0.9,
    display_metrics: bool = True,
) -> Callable[
    [
        int,
        list[dict[str, SampleScore]],
        list[Scorer] | None,
        ScoreReducer | list[ScoreReducer] | None,
        list[Metric] | dict[str, list[Metric]] | None,
    ],
    None,
]:
    next_compute_time = time.perf_counter() + initial_interval

    def compute(
        sample_count: int,
        sample_scores: list[dict[str, SampleScore]],
        scorers: list[Scorer] | None,
        reducers: ScoreReducer | list[ScoreReducer] | None,
        metrics: list[Metric] | dict[str, list[Metric]] | None,
    ) -> None:
        # Don't compute metrics if they are not being displayed
        if not display_metrics:
            return None

        nonlocal next_compute_time
        time_start = time.perf_counter()
        if time_start >= next_compute_time:
            # compute metrics
            results, reductions = eval_results(
                samples=sample_count,
                scores=sample_scores,
                reducers=reducers,
                scorers=scorers,
                metrics=metrics,
            )

            # Name, reducer, value
            task_metrics: list[TaskDisplayMetric] = []
            if len(results.scores) > 0:
                for score in results.scores:
                    for key, metric in score.metrics.items():
                        task_metrics.append(
                            TaskDisplayMetric(
                                scorer=score.name,
                                name=metric.name,
                                value=metric.value,
                                reducer=score.reducer,
                            )
                        )
                update_fn(task_metrics)

            # determine how long to wait before recomputing metrics
            time_end = time.perf_counter()
            elapsed_time = time_end - time_start
            wait = max(min_interval, elapsed_time * 10)
            next_compute_time = time_end + wait

    return compute


async def task_run_sample(
    *,
    tg: TaskGroup,
    task_name: str,
    log_location: str,
    sample: Sample,
    state: TaskState,
    sandbox: SandboxEnvironmentSpec | None,
    max_sandboxes: int | None,
    sandbox_cleanup: bool,
    plan: Plan,
    scorers: list[Scorer] | None,
    generate: Generate,
    progress: Callable[[int], None],
    logger: TaskLogger | None,
    log_images: bool,
    sample_source: EvalSampleSource | None,
    sample_error: SampleErrorHandler,
    sample_complete: Callable[[dict[str, SampleScore]], None],
    fails_on_error: bool,
    retry_on_error: int,
    error_retries: list[EvalError],
    time_limit: int | None,
    working_limit: int | None,
    semaphore: anyio.Semaphore | None,
    run_id: str,
    task_id: str,
) -> dict[str, SampleScore] | None:
    from inspect_ai.hooks._hooks import emit_sample_end, emit_sample_start

    # if there is an existing sample then tick off its progress, log it, and return it
    if sample_source and sample.id is not None:
        previous_sample = sample_source(sample.id, state.epoch)
        if previous_sample:
            # tick off progress for this sample
            progress(SAMPLE_TOTAL_PROGRESS_UNITS)

            # log if requested
            if logger:
                await logger.complete_sample(previous_sample, flush=False)

            # return score
            sample_scores = (
                {
                    key: SampleScore(
                        score=score,
                        sample_id=previous_sample.id,
                        sample_metadata=previous_sample.metadata,
                    )
                    for key, score in previous_sample.scores.items()
                }
                if previous_sample.scores
                else {}
            )
            sample_complete(sample_scores)
            return sample_scores

    # copy variables that we may pass back to ourselves on a retry
    initial_state = deepcopy(state)

    # use semaphore if provided
    semaphore_cm: anyio.Semaphore | contextlib.AbstractAsyncContextManager[None] = (
        semaphore if semaphore else contextlib.nullcontext()
    )

    # validate that we have sample_id (mostly for the typechecker)
    sample_id = sample.id
    if sample_id is None:
        raise ValueError("sample must have id to run")

    # initialise subtask and scoring context
    init_sample_model_usage()
    set_sample_state(state)
    sample_transcript = Transcript()
    init_transcript(sample_transcript)
    init_subtask_store(state.store)
    if logger:
        sample_transcript._subscribe(
            lambda event: logger.log_sample_event(sample_id, state.epoch, event)
        )
    if scorers:
        init_scoring_context(scorers, Target(sample.target))

    # use sandbox if provided
    sandboxenv_cm = (
        sandboxenv_context(task_name, sandbox, max_sandboxes, sandbox_cleanup, sample)
        if sandbox or sample.sandbox is not None
        else contextlib.nullcontext()
    )

    # helper to handle exceptions (will throw if we've exceeded the limit)
    def handle_error(ex: BaseException) -> tuple[EvalError, BaseException | None]:
        # helper to log sample error
        def log_sample_error() -> None:
            msg = f"Sample error (id: {sample.id}, epoch: {state.epoch}): {exception_message(ex)})"
            if retry_on_error > 0:
                msg = f"{msg}. Sample will be retried."
            py_logger.warning(msg)

        # if we have retries left then return EvalError
        if retry_on_error > 0:
            log_sample_error()
            return eval_error(ex, type(ex), ex, ex.__traceback__), None
        else:
            err = sample_error(ex)
            # if we aren't raising the error then print a warning
            if err[1] is None:
                log_sample_error()
            transcript()._event(ErrorEvent(error=err[0]))
            return err

    # solver loop
    async with (
        semaphore_cm,
        active_sample(
            task=task_name,
            log_location=log_location,
            model=str(state.model),
            sample=sample,
            epoch=state.epoch,
            message_limit=state.message_limit,
            token_limit=state.token_limit,
            time_limit=time_limit,
            working_limit=working_limit,
            fails_on_error=fails_on_error or (retry_on_error > 0),
            transcript=sample_transcript,
            tg=tg,
        ) as active,
    ):
        start_time: float | None = None
        error: EvalError | None = None
        raise_error: BaseException | None = None
        results: dict[str, SampleScore] = {}
        limit: EvalSampleLimit | None = None
        try:
            # begin init
            init_span = span("init", type="init")
            await init_span.__aenter__()

            # sample init event (remove file bodies as they have content or absolute paths)
            event_sample = sample.model_copy(
                update=dict(files={k: "" for k in sample.files.keys()})
                if sample.files
                else None
            )
            transcript()._event(
                SampleInitEvent(sample=event_sample, state=state_jsonable(state))
            )

            async with sandboxenv_cm:
                try:
                    # update active sample wth sandboxes now that we are initialised
                    # (ensure that we still exit init context in presence of sandbox error)
                    try:
                        active.sandboxes = await sandbox_connections()
                    finally:
                        await init_span.__aexit__(None, None, None)

                    # record start time
                    start_time = time.monotonic()
                    init_sample_working_time(start_time)

                    # run sample w/ optional limits
                    with (
                        state._token_limit,
                        state._message_limit,
                        create_time_limit(time_limit),
                        create_working_limit(working_limit),
                    ):
                        # mark started
                        active.started = datetime.now().timestamp()

                        # emit/log sample start
                        sample_summary = EvalSampleSummary(
                            id=sample_id,
                            epoch=state.epoch,
                            input=sample.input,
                            target=sample.target,
                            metadata=sample.metadata or {},
                        )
                        if logger is not None:
                            await logger.start_sample(sample_summary)
                        # only emit the sample start once: not on retries
                        if not error_retries:
                            await emit_sample_start(
                                run_id, task_id, state.uuid, sample_summary
                            )

                        # set progress for plan then run it
                        async with span("solvers"):
                            state = await plan(state, generate)

                except TimeoutError:
                    # Scoped time limits manifest themselves as LimitExceededError, not
                    # TimeoutError.
                    py_logger.warning(
                        "Unexpected timeout error reached top of sample stack. Are you handling TimeoutError when applying timeouts?"
                    )

                    # capture most recent state for scoring
                    state = sample_state() or state

                except anyio.get_cancelled_exc_class() as ex:
                    if active.interrupt_action:
                        # record event
                        transcript()._event(
                            SampleLimitEvent(
                                type="operator",
                                message="Sample completed: interrupted by operator",
                            )
                        )

                        # handle the action
                        match active.interrupt_action:
                            case "score":
                                # continue to scoring (capture the most recent state)
                                state = sample_state() or state
                            case "error":
                                # default error handling
                                error, raise_error = handle_error(ex)

                    else:
                        # task group provided by tg_collect will automatically
                        # handle the cancel exception
                        raise

                except LimitExceededError as ex:
                    # capture most recent state for scoring
                    state = sample_state() or state
                    limit = EvalSampleLimit(
                        type=ex.type, limit=ex.limit if ex.limit is not None else -1
                    )

                except TerminateSampleError:
                    # capture most recent state for scoring
                    state = sample_state() or state
                    limit = EvalSampleLimit(type="operator", limit=1)

                except BaseException as ex:
                    error, raise_error = handle_error(ex)

                # mark completed
                state.completed = True

                # set timeout for scoring. if the original timeout was hit we still
                # want to provide opportunity for scoring, but we don't necessarily
                # want to wait the full timeout again (especially in the case where
                # the cause of the timeout is a hung container and scoring requires
                # interacting with the container). as a middle ground we use half
                # of the original timeout value for scoring.
                scoring_time_limit = time_limit / 2 if time_limit else None

                set_sample_state(state)

                # scoring
                try:
                    # timeout during scoring will result in an ordinary sample error
                    with create_time_limit(scoring_time_limit):
                        if error is None:
                            async with span(name="scorers"):
                                for scorer in scorers or []:
                                    scorer_name = unique_scorer_name(
                                        scorer, list(results.keys())
                                    )
                                    async with span(name=scorer_name, type="scorer"):
                                        score_result = (
                                            await scorer(state, Target(sample.target))
                                            if scorer
                                            else None
                                        )
                                        if score_result is not None:
                                            sample_score = SampleScore(
                                                score=score_result,
                                                sample_id=sample.id,
                                                sample_metadata=sample.metadata,
                                                scorer=registry_unqualified_name(
                                                    scorer
                                                ),
                                            )
                                            transcript()._event(
                                                ScoreEvent(
                                                    score=score_result,
                                                    target=sample.target,
                                                )
                                            )
                                            results[scorer_name] = sample_score

                                # add scores returned by solvers
                                if state.scores is not None:
                                    for name, score in state.scores.items():
                                        results[name] = SampleScore(
                                            score=score,
                                            sample_id=state.sample_id,
                                            sample_metadata=state.metadata,
                                        )
                                        transcript()._event(
                                            ScoreEvent(
                                                score=score, target=sample.target
                                            )
                                        )

                                # propagate results into scores
                                state.scores = {k: v.score for k, v in results.items()}

                except anyio.get_cancelled_exc_class():
                    if active.interrupt_action:
                        transcript()._event(
                            SampleLimitEvent(
                                type="operator",
                                message="Unable to score sample due to operator interruption",
                            )
                        )

                    raise

                except BaseException as ex:
                    # handle error
                    error, raise_error = handle_error(ex)

        except Exception as ex:
            error, raise_error = handle_error(ex)

        # complete the sample if there is no error or if there is no retry_on_error in play
        if not error or (retry_on_error == 0):
            progress(SAMPLE_TOTAL_PROGRESS_UNITS)

            # if we are logging images then be sure to base64 images injected by solvers
            if log_images:
                state = (await states_with_base64_content([state]))[0]

            # otherwise ensure there are no base64 images in sample or messages
            else:
                sample = sample_without_base64_content(sample)
                state = state_without_base64_content(state)

            # emit/log sample end
            eval_sample = create_eval_sample(
                start_time=start_time,
                sample=sample,
                state=state,
                scores=results,
                error=error,
                limit=limit,
                error_retries=error_retries,
            )
            if logger:
                await log_sample(
                    eval_sample=eval_sample, logger=logger, log_images=log_images
                )
            await emit_sample_end(run_id, task_id, state.uuid, eval_sample)

    # error that should be retried (we do this outside of the above scope so that we can
    # retry outside of the original semaphore -- our retry will therefore go to the back
    # of the sample queue)
    if error and retry_on_error > 0:
        # remove any buffered sample events
        if logger is not None:
            logger.remove_sample(state.sample_id, state.epoch)

        # recurse w/ tick down of retry_on_error and append of error to error_retries
        return await task_run_sample(
            task_name=task_name,
            log_location=log_location,
            sample=sample,
            # state was deep copied at the outset
            state=initial_state,
            sandbox=sandbox,
            max_sandboxes=max_sandboxes,
            sandbox_cleanup=sandbox_cleanup,
            plan=plan,
            scorers=scorers,
            generate=generate,
            progress=progress,
            logger=logger,
            log_images=log_images,
            sample_source=sample_source,
            sample_error=sample_error,
            sample_complete=sample_complete,
            fails_on_error=fails_on_error,
            # tick retry count down
            retry_on_error=retry_on_error - 1,
            # forward on error that caused retry
            error_retries=copy(error_retries) + [error],
            time_limit=time_limit,
            working_limit=working_limit,
            semaphore=semaphore,
            tg=tg,
            run_id=run_id,
            task_id=task_id,
        )

    # no error
    elif error is None:
        # call sample_complete callback if we have score results
        if results is not None:
            sample_complete(results)
        return results

    # we have an error and should raise it
    elif raise_error is not None:
        raise raise_error

    # we have an error and should not raise it
    else:
        return None


def create_eval_sample(
    start_time: float | None,
    sample: Sample,
    state: TaskState,
    scores: dict[str, SampleScore],
    error: EvalError | None,
    limit: EvalSampleLimit | None,
    error_retries: list[EvalError],
) -> EvalSample:
    # sample must have id to be logged
    id = sample.id
    if id is None:
        raise ValueError(
            f"Samples without IDs cannot be logged: {to_json_str_safe(sample)}"
        )

    # construct sample for logging

    # compute total time if we can
    total_time = time.monotonic() - start_time if start_time is not None else None

    return EvalSample(
        id=id,
        epoch=state.epoch,
        input=sample.input,
        choices=sample.choices,
        target=sample.target,
        metadata=state.metadata or {},
        sandbox=sample.sandbox,
        files=list(sample.files.keys()) if sample.files else None,
        setup=sample.setup,
        messages=state.messages,
        output=state.output,
        scores={k: v.score for k, v in scores.items()},
        store=dict(state.store.items()),
        uuid=state.uuid,
        events=list(transcript().events),
        model_usage=sample_model_usage(),
        total_time=round(total_time, 3) if total_time is not None else None,
        working_time=round(total_time - sample_waiting_time(), 3)
        if total_time is not None
        else None,
        error=error,
        error_retries=error_retries,
        limit=limit,
    )


async def log_sample(
    eval_sample: EvalSample, logger: TaskLogger, log_images: bool
) -> None:
    await logger.complete_sample(condense_sample(eval_sample, log_images), flush=True)


async def resolve_dataset(
    dataset: Dataset,
    model_name: ModelName,
    limit: int | tuple[int, int] | None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None,
    epochs: int,
    log_images: bool,
    message_limit: int | None,
    token_limit: int | None,
) -> tuple[Dataset, list[Sample], list[TaskState]]:
    # slice dataset
    dataset = slice_dataset(dataset, limit, sample_id)

    # apply epochs (deepcopy the samples so they remain independent)
    samples: list[Sample] = []
    for _ in range(0, epochs):
        samples.extend([deepcopy(sample) for sample in dataset])

    # if we are logging images then resolve sample images here
    if log_images:
        samples = await samples_with_base64_content(samples)

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
                target=Target(sample.target),
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
) -> anyio.Semaphore:
    # if the user set max_samples then use that
    if config.max_samples is not None:
        return anyio.Semaphore(config.max_samples)

    # use max_connections
    max_samples = (
        generate_config.max_connections
        if generate_config.max_connections is not None
        else DEFAULT_MAX_CONNECTIONS_BATCH
        if generate_config.batch
        else modelapi.max_connections()
        if modelapi
        else DEFAULT_MAX_CONNECTIONS
    )

    # return the semaphore
    return anyio.Semaphore(max_samples)
