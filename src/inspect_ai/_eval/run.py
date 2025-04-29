import logging
import os
import sys
from typing import Any, Awaitable, Callable, Set, cast

from inspect_ai._eval.task.task import Task
from inspect_ai._util.environ import environ_vars
from inspect_ai._util.trace import trace_action

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

import anyio
from shortuuid import uuid
from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display.core.active import (
    clear_task_screen,
    init_task_screen,
)
from inspect_ai._display.core.display import TaskSpec
from inspect_ai._util.error import PrerequisiteError, exception_message
from inspect_ai._util.path import chdir
from inspect_ai._util.registry import registry_unqualified_name
from inspect_ai.dataset._dataset import Dataset
from inspect_ai.log import EvalConfig, EvalLog
from inspect_ai.log._recorders import Recorder
from inspect_ai.model import GenerateConfigArgs
from inspect_ai.model._model import ModelName
from inspect_ai.scorer._metric import to_metric_specs
from inspect_ai.scorer._reducer import ScoreReducer, reducer_log_names
from inspect_ai.scorer._reducer.registry import validate_reducer
from inspect_ai.scorer._scorer import as_scorer_spec
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    SandboxEnvironmentType,
    TaskCleanup,
    TaskInit,
    resolve_sandbox_environment,
)
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv

from .loader import (
    as_solver_spec,
    solver_from_spec,
)
from .task.log import TaskLogger
from .task.resolved import ResolvedTask
from .task.run import TaskRunOptions, task_run
from .task.sandbox import TaskSandboxEnvironment, resolve_sandbox_for_task_and_sample
from .task.util import slice_dataset, task_run_dir

log = logging.getLogger(__name__)


async def eval_run(
    run_id: str,
    tasks: list[ResolvedTask],
    parallel: int,
    eval_config: EvalConfig,
    eval_sandbox: SandboxEnvironmentType | None,
    recorder: Recorder,
    epochs_reducer: list[ScoreReducer] | None = None,
    solver: Solver | SolverSpec | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    debug_errors: bool = False,
    score: bool = True,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    # are sandboxes in play?
    has_sandbox = next((task.has_sandbox for task in tasks), None)

    # get cwd before any switching
    eval_wd = os.getcwd()

    # ensure sample ids
    task: Task | None = None
    for resolved_task in tasks:
        # add sample ids to dataset if they aren't there (start at 1 not 0)
        task = resolved_task.task
        for id, sample in enumerate(task.dataset):
            if sample.id is None:
                sample.id = id + 1

        # Ensure sample ids are unique
        ensure_unique_ids(task.dataset)

    assert task, "Must encounter a task"

    # run startup pass for the sandbox environments
    shutdown_sandbox_environments: Callable[[], Awaitable[None]] | None = None
    if has_sandbox:
        cleanup = eval_config.sandbox_cleanup is not False
        shutdown_sandbox_environments = await startup_sandbox_environments(
            resolve_sandbox_environment(eval_sandbox), tasks, eval_config, cleanup
        )

    # resolve solver and solver spec
    if isinstance(solver, Solver):
        eval_solver = solver
        eval_solver_spec = as_solver_spec(solver)
    elif isinstance(solver, SolverSpec):
        eval_solver = solver_from_spec(solver)
        eval_solver_spec = solver
    else:
        eval_solver = None
        eval_solver_spec = None

    try:
        # create run tasks
        task_run_options: list[TaskRunOptions] = []
        for resolved_task in tasks:
            with chdir(task_run_dir(resolved_task.task)):
                # tasks can provide their epochs, message_limit,
                # token_limit, time_limit, and fail_on_error so broadcast these
                # into the eval config (so long as they aren't overriding a
                # value specified from eval() or the CLI)
                task = resolved_task.task
                task_eval_config = eval_config.model_copy()

                # sample_ids can be specified per task
                task_eval_config.sample_id = resolve_task_sample_ids(
                    resolved_task.task.name, task_eval_config.sample_id
                )

                # resolve the task scorers
                eval_scorer_specs = (
                    [as_scorer_spec(scorer) for scorer in task.scorer]
                    if task.scorer is not None
                    else None
                )

                # resolve task metrics
                eval_metrics = (
                    to_metric_specs(task.metrics) if task.metrics is not None else None
                )

                # epochs
                if task_eval_config.epochs is None:
                    task_eval_config.epochs = task.epochs
                else:
                    task.epochs = task_eval_config.epochs

                # epochs reducer
                if epochs_reducer is not None:
                    # override task (eval_config already reflects epochs_reducer)
                    task.epochs_reducer = epochs_reducer
                else:
                    # use task (eval_config needs to be updated to reflect task reducer)
                    task_eval_config.epochs_reducer = reducer_log_names(
                        task.epochs_reducer
                    )

                # validate task epochs
                if task.epochs and task.epochs_reducer:
                    for reducer in task.epochs_reducer:
                        validate_reducer(task.epochs, reducer)

                # sample message limit
                if task_eval_config.message_limit is None:
                    task_eval_config.message_limit = task.message_limit
                else:
                    task.message_limit = task_eval_config.message_limit

                # sample token limit
                if task_eval_config.token_limit is None:
                    task_eval_config.token_limit = task.token_limit
                else:
                    task.token_limit = task_eval_config.token_limit

                # sample time limit
                if task_eval_config.time_limit is None:
                    task_eval_config.time_limit = task.time_limit
                else:
                    task.time_limit = task_eval_config.time_limit

                # sample execution limit
                if task_eval_config.working_limit is None:
                    task_eval_config.working_limit = task.working_limit
                else:
                    task.working_limit = task_eval_config.working_limit

                # fail_on_error
                if task_eval_config.fail_on_error is None:
                    task_eval_config.fail_on_error = task.fail_on_error
                else:
                    task.fail_on_error = task_eval_config.fail_on_error

                # create and track the logger
                logger = TaskLogger(
                    task_name=task.name,
                    task_version=task.version,
                    task_file=resolved_task.task_file,
                    task_registry_name=resolved_task.task.registry_name,
                    task_id=resolved_task.id if resolved_task.id else uuid(),
                    run_id=run_id,
                    solver=eval_solver_spec,
                    tags=tags,
                    model=resolved_task.model,
                    model_roles=resolved_task.model_roles,
                    dataset=task.dataset,
                    scorer=eval_scorer_specs,
                    metrics=eval_metrics,
                    sandbox=resolved_task.sandbox,
                    task_attribs=task.attribs,
                    task_args=resolved_task.task_args,
                    model_args=resolved_task.model.model_args,
                    eval_config=task_eval_config,
                    metadata=((metadata or {}) | (task.metadata or {})) or None,
                    recorder=recorder,
                )
                await logger.init()

                # append task
                task_run_options.append(
                    TaskRunOptions(
                        task=task,
                        model=resolved_task.model,
                        model_roles=resolved_task.model_roles,
                        sandbox=resolved_task.sandbox,
                        logger=logger,
                        eval_wd=eval_wd,
                        config=task_eval_config,
                        solver=eval_solver,
                        tags=tags,
                        score=score,
                        debug_errors=debug_errors,
                        sample_source=resolved_task.sample_source,
                        kwargs=kwargs,
                    )
                )

        # multiple mode is for running/displaying multiple
        # task definitions, which requires some smart scheduling
        # to ensure that we spread work among models
        if parallel > 1:
            return await run_multiple(task_run_options, parallel)
        else:
            return await run_single(task_run_options, debug_errors)

    finally:
        # shutdown sandbox environments
        if shutdown_sandbox_environments:
            try:
                await shutdown_sandbox_environments()
            except BaseException as ex:
                log.warning(
                    f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
                )


# single mode -- run a single logical task (could consist of multiple
# executable tasks if we are evaluating against multiple models)
async def run_single(tasks: list[TaskRunOptions], debug_errors: bool) -> list[EvalLog]:
    async with display().task_screen(task_specs(tasks), parallel=False) as screen:
        # init ui
        init_task_screen(screen)

        results: list[tuple[int, EvalLog]] = []
        try:
            async with anyio.create_task_group() as tg:

                async def run_task(index: int) -> None:
                    result = await task_run(tasks[index])
                    results.append((index, result))

                for i in range(0, len(tasks)):
                    tg.start_soon(run_task, i)
        # exceptions can escape when debug_errors is True and that's okay
        except ExceptionGroup as ex:
            if debug_errors:
                raise ex.exceptions[0]
            else:
                raise
        except anyio.get_cancelled_exc_class():
            # child tasks have already each handled this and updated results
            pass
        finally:
            # clear ui
            clear_task_screen()

        # sort results by original index and return just the values
        return [r for _, r in sorted(results)]


# multiple mode -- run multiple logical tasks (requires some smart
# schedluing to ensure that we are spreading work among models)
async def run_multiple(tasks: list[TaskRunOptions], parallel: int) -> list[EvalLog]:
    # track current usage of each model
    models: Set[str] = set()
    for task in tasks:
        models.add(str(task.model))
    model_counts = {model: 0 for model in models}

    # setup pending tasks, queue, and results
    pending_tasks = tasks.copy()
    results: list[EvalLog] = []
    tasks_completed = 0
    total_tasks = len(tasks)

    # produce/consume tasks
    send_channel, receive_channel = anyio.create_memory_object_stream[TaskRunOptions](
        parallel * 2
    )

    # find a task that keeps as many different models as possible running concurrently
    async def enque_next_task() -> bool:
        if tasks_completed < total_tasks:
            # filter out models that have no pending tasks
            models_with_pending = {
                model
                for model in model_counts
                if any(str(t.model) == model for t in pending_tasks)
            }
            if not models_with_pending:
                return False

            # among those models, pick one with the least usage
            model = min(models_with_pending, key=lambda m: model_counts[m])

            # now we know there’s at least one pending task for this model so it’s safe to pick it
            next_task = next(t for t in pending_tasks if str(t.model) == model)
            pending_tasks.remove(next_task)
            model_counts[str(next_task.model)] += 1
            with trace_action(
                log, "Enque Task", f"task: {next_task.task.name} ({next_task.model})"
            ):
                await send_channel.send(next_task)
            return True
        else:
            return False

    async def worker() -> None:
        try:
            nonlocal tasks_completed
            async for task_options in receive_channel:
                result: EvalLog | None = None

                # run the task
                try:
                    with trace_action(
                        log,
                        "Run Task",
                        f"task: {task_options.task.name} ({task_options.model})",
                    ):
                        async with anyio.create_task_group() as tg:
                            # Create a factory function that captures the current
                            # task_options. Otherwise, we suffer from Python's
                            # late/by reference binding behavior.
                            # see: https://docs.python.org/3/faq/programming.html#why-do-lambdas-defined-in-a-loop-with-different-values-all-return-the-same-result
                            def create_task_runner(
                                options: TaskRunOptions = task_options,
                            ) -> Callable[[], Awaitable[None]]:
                                async def run_task() -> None:
                                    nonlocal result
                                    result = await task_run(options)
                                    results.append(result)

                                return run_task

                            tg.start_soon(create_task_runner())

                except Exception as ex:
                    # errors generally don't escape from tasks (the exception being if an error
                    # occurs during the final write of the log)
                    log.error(
                        f"Task '{task_options.task.name}' encountered an error during finalisation: {ex}"
                    )

                # tracking
                tasks_completed += 1
                model_counts[str(task_options.model)] -= 1

                # if a task was cancelled we are done
                if not result or result.status == "cancelled":
                    break

                # check if there are more tasks to process
                if tasks_completed < total_tasks:
                    await enque_next_task()
                elif tasks_completed == total_tasks:
                    # all tasks are complete, close the stream
                    try:
                        await send_channel.aclose()
                    except anyio.ClosedResourceError:
                        # another worker might have already closed it
                        pass
        except anyio.EndOfStream:
            pass

    # with task display
    async with display().task_screen(task_specs(tasks), parallel=True) as screen:
        # init screen
        init_task_screen(screen)

        # Use anyio task group instead of manual task management
        try:
            async with anyio.create_task_group() as tg:
                # computer number of workers (never more than total_tasks)
                num_workers = min(parallel, total_tasks)

                # start worker tasks
                for _ in range(num_workers):
                    tg.start_soon(worker)

                # enqueue initial set of tasks
                for _ in range(num_workers):
                    await enque_next_task()
        except anyio.get_cancelled_exc_class():
            pass
        finally:
            # Always ensure channels are closed
            try:
                await send_channel.aclose()
            except anyio.ClosedResourceError:
                pass

            try:
                await receive_channel.aclose()
            except anyio.ClosedResourceError:
                pass

            clear_task_screen()

        return results


def resolve_task_sample_ids(
    task: str, sample_id: str | int | list[str] | list[int] | list[str | int] | None
) -> str | int | list[str] | list[int] | list[str | int] | None:
    def collect_for_task(sample: str | int) -> str | int | None:
        if isinstance(sample, str):
            scoped = sample.split(":", maxsplit=1)
            if len(scoped) > 1:
                if scoped[0].lower() == task.lower():
                    return scoped[1]
                else:
                    return None
            else:
                return sample
        else:
            return sample

    if sample_id is not None:
        if isinstance(sample_id, list):
            ids: list[int | str] = []
            for id in sample_id:
                collect = collect_for_task(id)
                if collect is not None:
                    ids.append(collect)
            return ids

        else:
            collect = collect_for_task(sample_id)
            if collect is not None:
                return collect
            else:
                return []

    else:
        return sample_id


async def startup_sandbox_environments(
    eval_sandbox: SandboxEnvironmentSpec | None,
    tasks: list[ResolvedTask],
    config: EvalConfig,
    cleanup: bool,
) -> Callable[[], Awaitable[None]]:
    # find unique sandboxenvs
    sandboxenvs: Set[TaskSandboxEnvironment] = set()
    for task in tasks:
        # resolve each sample and add to sandboxenvs
        dataset = slice_dataset(task.task.dataset, config.limit, config.sample_id)
        for sample in dataset:
            sandbox = await resolve_sandbox_for_task_and_sample(
                eval_sandbox, task.task, sample
            )
            if sandbox is not None and sandbox not in sandboxenvs:
                sandboxenvs.add(sandbox)

    # initialiase sandboxenvs (track cleanups)
    cleanups: list[tuple[TaskCleanup, SandboxEnvironmentConfigType | None, str]] = []
    with display().suspend_task_app():
        for sandboxenv in sandboxenvs:
            # find type
            sandboxenv_type = registry_find_sandboxenv(sandboxenv.sandbox.type)

            # run startup
            task_init = cast(TaskInit, getattr(sandboxenv_type, "task_init"))
            with chdir(sandboxenv.run_dir), environ_vars(dict(sandboxenv.env)):
                await task_init("startup", sandboxenv.sandbox.config)

            # append cleanup method
            task_cleanup = cast(TaskCleanup, getattr(sandboxenv_type, "task_cleanup"))
            cleanups.append(
                (task_cleanup, sandboxenv.sandbox.config, sandboxenv.run_dir)
            )

    # return shutdown method
    async def shutdown() -> None:
        for cleanup_jobs in cleanups:
            try:
                cleanup_fn, config, task_run_dir = cleanup_jobs
                with chdir(task_run_dir):
                    await cleanup_fn("shutdown", config, cleanup)
            except BaseException as ex:
                log.warning(
                    f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
                )

    return shutdown


def task_specs(tasks: list[TaskRunOptions]) -> list[TaskSpec]:
    return [
        TaskSpec(registry_unqualified_name(task.task.name), ModelName(task.model))
        for task in tasks
    ]


def ensure_unique_ids(dataset: Dataset) -> None:
    """
    Validates that all samples in the dataset have unique IDs.

    Raises a error if duplicates are found.

    Args:
        dataset (Datatset): The dataset

    Raises:
        PrerequisiteError: If duplicate IDs are found in the dataset.
    """
    seen_ids = set()
    for sample in dataset:
        if sample.id in seen_ids:
            raise PrerequisiteError(
                f"The dataset contains duplicate sample ids (duplicate id: {sample.id}). Please ensure each sample has a unique id."
            )
        seen_ids.add(sample.id)
