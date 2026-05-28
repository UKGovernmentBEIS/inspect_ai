import contextlib
import functools
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import PurePath
from typing import Any, Awaitable, Callable, Literal

import anyio
from typing_extensions import Unpack

from inspect_ai._display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
    display,
)
from inspect_ai._display.core.display import TaskCancel, TaskDisplayMetric
from inspect_ai._eval.task.scan import Scanners
from inspect_ai._util._async import tg_collect
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_CONNECTIONS_BATCH,
)
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.error import exception_message
from inspect_ai._util.exception import TerminateTaskError
from inspect_ai._util.notgiven import NOT_GIVEN
from inspect_ai._util.registry import (
    is_registry_object,
    registry_log_name,
)
from inspect_ai._view.notify import view_notify_eval
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.log import (
    EvalConfig,
    EvalLog,
    EvalResults,
    EvalSample,
    EvalStats,
)
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._file import (
    EvalLogInfo,
    eval_log_json_str,
    read_eval_log_sample_async,
)
from inspect_ai.log._log import (
    EvalSampleReductions,
    eval_error,
)
from inspect_ai.model import (
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    ModelAPI,
    ModelName,
)
from inspect_ai.model._model import (
    init_model_usage,
    init_role_usage,
)
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.scorer import Scorer, Target
from inspect_ai.scorer._metric import Metric, SampleScore
from inspect_ai.scorer._reducer.types import ScoreReducer
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import Plan, TaskState
from inspect_ai.solver._chain import Chain, unroll
from inspect_ai.solver._fork import set_task_generate
from inspect_ai.solver._solver import Solver
from inspect_ai.util._checkpoint._layout import (
    has_sample_checkpoint,
    sample_checkpoints_dir,
)
from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint
from inspect_ai.util._checkpoint.config import (
    CheckpointConfig,
)
from inspect_ai.util._early_stopping import (
    EarlyStop,
    EarlyStoppingSummary,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._sandbox.limits import reset_sandbox_limits, set_sandbox_limits

from ..context import init_task_context
from ..task import Task
from .error import SampleErrorHandler, _should_eval_fail
from .generate import task_generate
from .images import (
    sample_with_base64_content,
)
from .log import TaskLogger, collect_eval_data, log_start
from .results import eval_results

# re-exports for backward-compat with tests that import these names from
# `_eval.task.run` (their canonical home is now `sample_helpers`).
from .sample_helpers import (
    init_sample_assistant_internal as init_sample_assistant_internal,
)
from .sample_helpers import log_sample as log_sample
from .sample_runner import SampleRunner
from .scan import (
    resume_scan_previous_sample,
    scanned_transcripts_for_resume,
)
from .store import DiskSampleStore, maybe_page_to_disk
from .util import sample_messages, slice_dataset

py_logger = getLogger(__name__)


EvalSampleSource = Callable[
    [int | str, int], Awaitable[EvalSample | ResumeCheckpoint | None]
]

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
    checkpoint: CheckpointConfig | None
    """Task-level checkpoint config (raw `task.checkpoint`)."""
    eval_checkpoint: CheckpointConfig | None
    """Eval/CLI-level checkpoint config (overrides task/sample)."""
    logger: TaskLogger
    eval_wd: str
    config: EvalConfig = field(default_factory=EvalConfig)
    solver: Solver | None = field(default=None)
    scanner: "Scanners | None" = field(default=None)
    scan_id: str | None = field(default=None)
    tags: list[str] | None = field(default=None)
    run_samples: bool | None = field(default=True)
    score: bool = field(default=True)
    debug_errors: bool = field(default=False)
    sample_source: EvalSampleSource | None = field(default=None)
    display_name: str | None = field(default=None)
    kwargs: GenerateConfigArgs = field(default_factory=lambda: GenerateConfigArgs())
    initial_model_usage: dict[str, ModelUsage] | None = field(default=None)
    initial_role_usage: dict[str, ModelUsage] | None = field(default=None)


def resolve_plan(task: Task, solver: Solver | None) -> Plan:
    # resolve the plan (unroll chains)
    solver = solver or task.solver
    if isinstance(solver, Plan):
        plan = solver
    elif isinstance(solver, Chain):
        plan = Plan(list(solver), internal=True)
    else:
        plan = Plan(unroll(solver), internal=True)

    # add setup solver(s) if specified
    if task.setup:
        plan.steps = unroll(task.setup) + plan.steps

    return plan


async def task_run(options: TaskRunOptions, task_cancel: TaskCancel | None) -> EvalLog:
    from inspect_ai.hooks._hooks import (
        emit_task_end,
        emit_task_start,
    )
    from inspect_ai.hooks._legacy import send_telemetry_legacy

    # destructure options
    task = options.task
    model = options.model
    model_roles = options.model_roles
    sandbox = options.sandbox
    checkpoint = options.checkpoint
    eval_checkpoint = options.eval_checkpoint
    logger = options.logger
    eval_wd = options.eval_wd
    config = options.config
    solver = options.solver
    scanner = options.scanner
    scan_id = options.scan_id
    tags = options.tags
    score = options.score
    sample_source = options.sample_source
    kwargs = options.kwargs

    # resolve default generate_config for task
    generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

    # seed model/role usage from a prior log when this task is a retry
    # (the deepcopy guards against shared dict mutation across attempts).
    # init_task_context's no-arg init_model_usage/init_role_usage will leave
    # these seeded values in place.
    if options.initial_model_usage:
        init_model_usage(deepcopy(options.initial_model_usage))
    if options.initial_role_usage:
        init_role_usage(deepcopy(options.initial_role_usage))

    # init task context
    init_task_context(
        model,
        model_roles,
        generate_config,
        options.task.approval,
    )

    # track stats, results, and log
    results: EvalResults | None = None
    reductions: list[EvalSampleReductions] | None = None
    progress_results: list[dict[str, SampleScore]] = []
    eval_log: EvalLog | None = None
    stats = EvalStats(started_at=iso_now())

    # resolve some config
    model_name = ModelName(model)
    epochs = config.epochs if config.epochs else DEFAULT_EPOCHS
    sandbox_cleanup = config.sandbox_cleanup is not False
    log_images = config.log_images is not False
    log_model_api = config.log_model_api
    log_samples = config.log_samples is not False

    # slice dataset (but don't materialize all sample+state pairs upfront --
    # they are created lazily inside run_sample to keep memory at
    # O(concurrent_samples) instead of O(total_samples * epochs))
    dataset = slice_dataset(task.dataset, config.limit, config.sample_id)
    total_samples = len(dataset) * epochs

    # handle sample errors (raise as required). use total_samples (sliced
    # dataset * epochs) as the denominator for fractional fail_on_error so
    # the mid-run abort threshold matches the end-of-run check below.
    sample_error_handler = SampleErrorHandler(
        config.fail_on_error if config.continue_on_fail is not True else False,
        total_samples,
    )

    # optionally page dataset to disk if it exceeds the memory budget
    sample_store = maybe_page_to_disk(dataset, config.max_dataset_memory)

    # release in-memory samples now that they're paged to disk
    if sample_store is not dataset:
        del dataset

    # resolve the plan (unroll chains)
    solver = solver or task.solver
    plan = resolve_plan(task, solver)

    # resolve the scorer
    score = score and task.scorer is not None
    scorers: list[Scorer] | None = task.scorer if (score and task.scorer) else None

    # resolve unique scorer names once so sample scoring
    # and aggregation use the same names
    scorer_names: list[str] | None = None
    if scorers:
        scorer_names = []
        for s in scorers:
            scorer_names.append(unique_scorer_name(s, scorer_names))

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
        name=options.display_name or task.name,
        file=logger.eval.task_file,
        model=model_name,
        dataset=task.dataset.name or "(samples)",
        scorer=", ".join(scorer_profiles),
        samples=total_samples,
        steps=total_samples * SAMPLE_TOTAL_PROGRESS_UNITS,
        eval_config=config,
        task_args=logger.eval.task_args_passed,
        generate_config=generate_config,
        tags=tags,
        log_location=log_location,
        task_id=logger.eval.task_id,
        task_cancel=task_cancel,
    )

    # set custom sandbox limits
    limit_tokens = set_sandbox_limits()

    with display().task(
        profile,
    ) as td:
        # start the log (do this outside fo the try b/c the try/except assumes
        # that the log is initialized)
        await log_start(logger, plan, generate_config)

        try:
            # return immediately if we are not running samples
            if not options.run_samples:
                return await logger.log_finish("started", stats)

            # call hook
            await emit_task_start(logger)

            # call early stopping if we have it
            stopping_manager: str = ""
            if options.task.early_stopping is not None:
                stopping_manager = await options.task.early_stopping.start_task(
                    logger.eval,
                    samples=[
                        deepcopy(sample_store[i]) for i in range(len(sample_store))
                    ],
                    epochs=epochs,
                )

            with td.progress() as p:
                # forward progress
                def progress(number: int) -> None:
                    p.update(number)

                # provide solvers a function that they can use to generate output
                async def generate(
                    state: TaskState,
                    tool_calls: Literal["loop", "single", "none"] = "loop",
                    **kwargs: Unpack[GenerateConfigArgs],
                ) -> TaskState:
                    return await task_generate(
                        model=model,
                        state=state,
                        tool_calls=tool_calls,
                        cache=kwargs.get("cache", False) or NOT_GIVEN,
                        config=generate_config.merge(kwargs),
                    )

                # set generate for fork module
                set_task_generate(generate)

                # semaphore to limit concurrency
                sample_semaphore = create_sample_semaphore(
                    config, generate_config, model.api
                )

                scanned_per_scanner = scanned_transcripts_for_resume(
                    scanner, scan_id, profile.log_location
                )

                def update_metrics(metrics: list[TaskDisplayMetric]) -> None:
                    td.update_metrics(metrics)
                    logger.update_metrics(metrics)

                update_metrics_display = update_metrics_display_fn(
                    update_metrics,
                    display_metrics=profile.eval_config.score_display is not False,
                )

                async def sample_complete(
                    sample_id: int | str,
                    epoch: int,
                    sample_score: dict[str, SampleScore],
                ) -> None:
                    # Capture the result
                    progress_results.append(sample_score)

                    # Increment the segment progress
                    td.sample_complete(
                        complete=len(progress_results), total=total_samples
                    )

                    # Update metrics
                    update_metrics_display(
                        len(progress_results),
                        progress_results,
                        scorers,
                        scorer_names,
                        task.epochs_reducer,
                        task.metrics,
                    )

                    # call the early stopping hook
                    if options.task.early_stopping is not None:
                        await options.task.early_stopping.complete_sample(
                            sample_id, epoch, sample_score
                        )

                # initial progress
                td.sample_complete(complete=0, total=total_samples)

                # Update metrics to empty state
                update_metrics_display(
                    len(progress_results),
                    progress_results,
                    scorers,
                    scorer_names,
                    task.epochs_reducer,
                    task.metrics,
                )

                async def run_sample(
                    sample_index: int, epoch: int
                ) -> dict[str, SampleScore] | EarlyStop | None:
                    # check for cached result from previous eval (before
                    # materialization to avoid unnecessary deepcopy + image I/O)
                    sample_id = sample_store[sample_index].id
                    resume_checkpoint: ResumeCheckpoint | None = None
                    if sample_source and sample_id is not None:
                        previous_sample = await sample_source(sample_id, epoch)
                        if isinstance(previous_sample, EvalSample):
                            progress(SAMPLE_TOTAL_PROGRESS_UNITS)
                            if logger and log_samples:
                                await logger.complete_sample(
                                    condense_sample(previous_sample, log_images),
                                    flush=False,
                                )
                            sample_scores = (
                                {
                                    key: SampleScore(
                                        score=score,
                                        sample_id=previous_sample.id,
                                        sample_metadata=previous_sample.metadata,
                                        scorer=key,
                                    )
                                    for key, score in previous_sample.scores.items()
                                }
                                if previous_sample.scores
                                else {}
                            )
                            await resume_scan_previous_sample(
                                previous_sample,
                                scanner,
                                scanned_per_scanner,
                                sample_semaphore,
                                scan_id=scan_id,
                                eval_id=logger.eval.eval_id,
                                log_location=profile.log_location,
                                model=str(model),
                                eval_spec=logger.eval,
                            )
                            await sample_complete(sample_id, epoch, sample_scores)
                            return sample_scores
                        elif isinstance(previous_sample, ResumeCheckpoint):
                            # signal intent — agent code can branch on
                            # `cp.is_resuming`. No state hydration yet.
                            resume_checkpoint = previous_sample

                    # factory to create sample+state lazily (after semaphore)
                    # so only concurrently executing samples consume memory
                    async def create_sample_state(
                        sample_uuid: str | None = None,
                    ) -> tuple[Sample, TaskState]:
                        sample = deepcopy(sample_store[sample_index])
                        if log_images:
                            sample = await sample_with_base64_content(sample)
                        state = deepcopy(
                            TaskState(
                                sample_id=sample.id or 0,
                                epoch=epoch,
                                model=model_name,
                                input=sample.input,
                                target=Target(sample.target),
                                choices=sample.choices,
                                messages=sample_messages(sample),
                                message_limit=config.message_limit,
                                token_limit=config.token_limit,
                                cost_limit=config.cost_limit,
                                completed=False,
                                metadata=sample.metadata if sample.metadata else {},
                                sample_uuid=sample_uuid,
                            )
                        )
                        return sample, state

                    return await SampleRunner(
                        task_name=task.name,
                        log_location=profile.log_location,
                        create_sample_state=create_sample_state,
                        sandbox=sandbox,
                        checkpoint=checkpoint,
                        eval_checkpoint=eval_checkpoint,
                        resume_checkpoint=resume_checkpoint,
                        max_sandboxes=config.max_sandboxes,
                        sandbox_cleanup=sandbox_cleanup,
                        plan=plan,
                        scorers=scorers,
                        scorer_names=scorer_names,
                        scanner=scanner,
                        cleanup=task.cleanup,
                        generate=generate,
                        progress=progress,
                        logger=logger if log_samples else None,
                        log_images=log_images,
                        log_model_api=log_model_api,
                        sample_error=sample_error_handler,
                        sample_complete=sample_complete,
                        early_stopping=options.task.early_stopping,
                        fails_on_error=(
                            config.fail_on_error is not False
                            and config.continue_on_fail is not True
                            and config.score_on_error is not True
                        ),
                        retry_on_error=config.retry_on_error or 0,
                        score_on_error=config.score_on_error or False,
                        error_retries=[],
                        time_limit=config.time_limit,
                        working_limit=config.working_limit,
                        semaphore=sample_semaphore,
                        eval_set_id=logger.eval.eval_set_id,
                        run_id=logger.eval.run_id,
                        task_id=logger.eval.eval_id,
                        scan_id=options.scan_id,
                    ).run()

                sample_results = await tg_collect(
                    [
                        functools.partial(run_sample, sample_index, epoch)
                        for epoch in range(1, epochs + 1)
                        for sample_index in range(len(sample_store))
                    ]
                )

            # compute and record metrics if we have scores
            completed_scores = [
                score_dict
                for score_dict in sample_results
                if isinstance(score_dict, dict)
            ]

            early_stops = [
                stopped_sample
                for stopped_sample in sample_results
                if isinstance(stopped_sample, EarlyStop)
            ]

            # call early stopping if we have it
            stopping_summary: EarlyStoppingSummary | None = None
            if options.task.early_stopping is not None:
                stopping_metadata = await options.task.early_stopping.complete_task()
                stopping_summary = EarlyStoppingSummary(
                    manager=stopping_manager,
                    early_stops=early_stops,
                    metadata=stopping_metadata,
                )

            if len(completed_scores) > 0:
                results, reductions = eval_results(
                    samples=profile.samples,
                    scores=completed_scores,
                    reducers=task.epochs_reducer,
                    scorers=scorers,
                    metrics=task.metrics,
                    scorer_names=scorer_names,
                    early_stopping=stopping_summary,
                )

            # collect eval data
            collect_eval_data(stats)

            # use the SampleErrorHandler's authoritative count (incremented in
            # handle_error() exactly once per sample after retries are
            # exhausted). With score_on_error, errored samples now return a
            # populated score dict instead of None, so counting via
            # `result is None` would miss them.
            sample_error_count = sample_error_handler.error_count
            mark_log_as_error = _should_eval_fail(
                sample_error_count, profile.samples, config.fail_on_error
            )

            # finish
            eval_log = await logger.log_finish(
                "error" if mark_log_as_error else "success", stats, results, reductions
            )

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

                # compute partial results from samples that completed
                if len(progress_results) > 0:
                    results, reductions = eval_results(
                        samples=profile.samples,
                        scores=progress_results,
                        reducers=task.epochs_reducer,
                        scorers=scorers,
                        metrics=task.metrics,
                        scorer_names=scorer_names,
                    )

                if task_cancel and task_cancel.cancel_type is not None:
                    # User-initiated cancel (abort/retry) — log as error so
                    # eval_set doesn't interpret it as external cancellation
                    cancel_ex = TerminateTaskError(
                        f"Task cancelled by user ({task_cancel.cancel_type})"
                    )
                    error = eval_error(cancel_ex, TerminateTaskError, cancel_ex, None)
                    eval_log = await logger.log_finish(
                        "error", stats, results, reductions, error
                    )
                    td.complete(
                        TaskError(
                            logger.samples_completed,
                            TerminateTaskError,
                            cancel_ex,
                            None,
                        )
                    )
                else:
                    # External cancellation (ctrl+c)
                    eval_log = await logger.log_finish(
                        "cancelled", stats, results, reductions
                    )
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

    # cleanup disk sample store if used
    if isinstance(sample_store, DiskSampleStore):
        sample_store.close()

    # notify the view module that an eval just completed
    # (in case we have a view polling for new evals)
    view_notify_eval(logger.location)

    assert eval_log is not None

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

    # restore sandbox limits
    reset_sandbox_limits(limit_tokens)

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
        list[str] | None,
        ScoreReducer | list[ScoreReducer] | None,
        list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None,
    ],
    None,
]:
    next_compute_time = time.perf_counter() + initial_interval

    def compute(
        sample_count: int,
        sample_scores: list[dict[str, SampleScore]],
        scorers: list[Scorer] | None,
        scorer_names: list[str] | None,
        reducers: ScoreReducer | list[ScoreReducer] | None,
        metrics: list[Metric | dict[str, list[Metric]]]
        | dict[str, list[Metric]]
        | None,
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
                scorer_names=scorer_names,
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
                                params=metric.params,
                            )
                        )
                update_fn(task_metrics)

            # determine how long to wait before recomputing metrics
            time_end = time.perf_counter()
            elapsed_time = time_end - time_start
            wait = max(min_interval, elapsed_time * 10)
            next_compute_time = time_end + wait

    return compute


# we can reuse samples from a previous eval_log if and only if:
#   - The datasets have not been shuffled OR the samples in the dataset have unique ids
#   - The datasets have the exact same length
def eval_log_sample_source(
    eval_log: EvalLog | None,
    eval_log_info: EvalLogInfo | None,
    dataset: Dataset,
    eval_checkpoints_dir: str | None = None,
) -> EvalSampleSource:
    # return dummy function for no sample source
    async def no_sample_source(id: int | str, epoch: int) -> None:
        return None

    async def _resume_if_checkpointed(
        id: int | str, epoch: int
    ) -> ResumeCheckpoint | None:
        if eval_checkpoints_dir is None:
            return None
        if not await has_sample_checkpoint(eval_checkpoints_dir, id, epoch):
            return None
        return ResumeCheckpoint(
            sample_checkpoints_dir=sample_checkpoints_dir(
                eval_checkpoints_dir, id, epoch
            )
        )

    # take care of no log or no samples in log. Note we still proceed when
    # in-memory samples and `eval_log_info` are both absent if a
    # `eval_checkpoints_dir` is available — the prior eval may have been
    # killed before writing any sample, and on-disk sidecars can still
    # drive resume detection in `read_from_memory` below.
    if not eval_log:
        return no_sample_source
    elif not eval_log.samples and not eval_log_info and not eval_checkpoints_dir:
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
    elif eval_log_info:
        reader: AsyncZipReader | None = None

        async def read_from_file(
            id: int | str, epoch: int
        ) -> EvalSample | ResumeCheckpoint | None:
            nonlocal reader
            if not reader:
                reader = AsyncZipReader(get_async_filesystem(), eval_log_info.name)
            try:
                sample = await read_eval_log_sample_async(
                    eval_log_info, id, epoch, reader=reader
                )
                if sample.error is None and sample.invalidation is None:
                    return sample
            except IndexError:
                pass
            return await _resume_if_checkpointed(id, epoch)

        return read_from_file
    else:

        async def read_from_memory(
            id: int | str, epoch: int
        ) -> EvalSample | ResumeCheckpoint | None:
            clean = next(
                (
                    sample
                    for sample in (eval_log.samples or [])
                    if sample.id == id
                    and sample.epoch == epoch
                    and sample.error is None
                    and sample.invalidation is None
                ),
                None,
            )
            return clean if clean else await _resume_if_checkpointed(id, epoch)

        return read_from_memory


# semaphore to limit concurrency. default max_samples to
# max_connections + 1 if not explicitly specified (this is
# to make sure it always saturates the connection pool)
def create_sample_semaphore(
    config: EvalConfig,
    generate_config: GenerateConfig,
    modelapi: ModelAPI | None = None,
) -> contextlib.AbstractAsyncContextManager[Any]:
    from inspect_ai.util._concurrency import (
        DynamicSampleLimiter,
        adaptive_active,
        resolve_adaptive,
    )

    if config.max_samples is not None:
        # explicit max_samples wins silently — under default-on
        # adaptive_connections, warning when max_samples < adaptive.max
        # would fire for nearly every deliberate max_samples setting
        return anyio.Semaphore(config.max_samples)
    elif adaptive_active(
        generate_config.adaptive_connections,
        generate_config.max_connections,
        generate_config.batch,
    ):
        # adaptive: dynamic limiter that tracks the controller(s) — sample
        # concurrency grows with the controller's current limit so setup work
        # (sandboxes etc.) stays proportional to actual model concurrency.
        # Both explicit max_connections and batch mode silently override
        # adaptive (matches the precedence in Model._connection_concurrency).
        return DynamicSampleLimiter(
            resolve_adaptive(generate_config.adaptive_connections)
        )
    else:
        # static path (existing behavior, unchanged)
        max_samples = (
            generate_config.max_connections
            if generate_config.max_connections is not None
            else DEFAULT_MAX_CONNECTIONS_BATCH
            if generate_config.batch
            else modelapi.max_connections()
            if modelapi
            else DEFAULT_MAX_CONNECTIONS
        )
        return anyio.Semaphore(max_samples)
