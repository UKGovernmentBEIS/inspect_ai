import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Set, cast

from shortuuid import uuid
from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display._display import clear_task_screen, init_task_screen
from inspect_ai._util.error import exception_message
from inspect_ai._util.path import chdir
from inspect_ai.log import EvalConfig, EvalLog
from inspect_ai.log._recorders import Recorder
from inspect_ai.model import GenerateConfig, GenerateConfigArgs
from inspect_ai.scorer._reducer import ScoreReducer, reducer_log_names
from inspect_ai.scorer._reducer.registry import validate_reducer
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util._sandbox.environment import TaskCleanup, TaskInit
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv

from .loader import (
    ResolvedTask,
    as_solver_spec,
    solver_from_spec,
)
from .task.log import TaskLogger
from .task.run import TaskRunOptions, create_sample_semaphore, task_run
from .task.rundir import task_run_dir_switching
from .task.sandbox import TaskSandboxEnvironment, resolve_sandbox_for_task
from .task.util import task_run_dir

log = logging.getLogger(__name__)


async def eval_run(
    run_id: str,
    tasks: list[ResolvedTask],
    parallel: int,
    eval_config: EvalConfig,
    recorder: Recorder,
    model_args: dict[str, Any],
    epochs_reducer: list[ScoreReducer] | None = None,
    solver: Solver | SolverSpec | None = None,
    tags: list[str] | None = None,
    debug_errors: bool = False,
    score: bool = True,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    # see if we need to use run_dir switching
    run_dir = task_run_dir(tasks[0].task)
    multiple_run_dirs = any([task_run_dir(task.task) != run_dir for task in tasks])
    has_sandbox = next((task.has_sandbox for task in tasks), None)

    # if we have a sandbox then we need to enforce sample concurrency at
    # this level of the eval (so we don't explode the # of sandboxes)
    sample_semaphore: asyncio.Semaphore | None = (
        create_sample_semaphore(eval_config, GenerateConfig(**kwargs))
        if has_sandbox
        else None
    )

    # get cwd before switching to task dir
    eval_wd = os.getcwd()

    # run startup pass for the sandbox environments
    shutdown_sandbox_environments: Callable[[], Awaitable[None]] | None = None
    if has_sandbox:
        cleanup = eval_config.sandbox_cleanup is not False
        shutdown_sandbox_environments = await startup_sandbox_environments(
            tasks, cleanup
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
                # token_limit, and fail_on_error so broadcast these
                # into the eval config (so long as they aren't overriding a
                # value specified from eval() or the CLI)
                task = resolved_task.task
                task_eval_config = eval_config.model_copy()

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

                # fail_on_error
                if task_eval_config.fail_on_error is None:
                    task_eval_config.fail_on_error = task.fail_on_error
                else:
                    task.fail_on_error = task_eval_config.fail_on_error

                # add sample ids to dataset if they aren't there (start at 1 not 0)
                for id, sample in enumerate(task.dataset):
                    if sample.id is None:
                        sample.id = id + 1

                # create and track the logger
                logger = TaskLogger(
                    task_name=task.name,
                    task_version=task.version,
                    task_file=resolved_task.task_file,
                    task_id=resolved_task.id if resolved_task.id else uuid(),
                    run_id=run_id,
                    solver=eval_solver_spec,
                    tags=tags,
                    model=resolved_task.model,
                    dataset=task.dataset,
                    sandbox=resolved_task.sandbox,
                    task_attribs=task.attribs,
                    task_args=resolved_task.task_args,
                    model_args=model_args,
                    eval_config=task_eval_config,
                    metadata=task.metadata,
                    recorder=recorder,
                )

                # append task
                task_run_options.append(
                    TaskRunOptions(
                        task=task,
                        model=resolved_task.model,
                        sandbox=resolved_task.sandbox,
                        logger=logger,
                        eval_wd=eval_wd,
                        config=task_eval_config,
                        solver=eval_solver,
                        tags=tags,
                        score=score,
                        debug_errors=debug_errors,
                        sample_source=resolved_task.sample_source,
                        sample_semaphore=sample_semaphore,
                        kwargs=kwargs,
                    )
                )

        # multiple mode is for running/displaying multiple
        # task definitions, which requires some smart scheduling
        # to ensure that we spread work among models
        if parallel > 1:
            if multiple_run_dirs:
                with task_run_dir_switching():
                    return await run_multiple(task_run_options, parallel)
            else:
                with chdir(run_dir):
                    return await run_multiple(task_run_options, parallel)

        # single mode is for a single task definitions (which
        # could in turn be executed for multiple models)
        else:
            with chdir(run_dir):
                return await run_single(task_run_options)

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
async def run_single(tasks: list[TaskRunOptions]) -> list[EvalLog]:
    # https://discuss.python.org/t/asyncio-cancel-a-cancellation-utility-as-a-coroutine-this-time-with-feeling/26304/3

    with display().task_screen(total_tasks=len(tasks), parallel=False) as screen:
        init_task_screen(screen)
        asyncio_tasks = [asyncio.create_task(task_run(task)) for task in tasks]
        try:
            return await asyncio.gather(*asyncio_tasks)
        except asyncio.CancelledError:
            results: list[EvalLog] = []
            for task in asyncio_tasks:
                if task.done():
                    results.append(task.result())
                else:
                    task.cancel()
                    await task
                    results.append(task.result())
        finally:
            clear_task_screen()
        return results


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
    queue: asyncio.Queue[TaskRunOptions] = asyncio.Queue()
    results: list[EvalLog] = []
    tasks_completed = 0
    total_tasks = len(tasks)

    async def enque_next_task() -> bool:
        if tasks_completed < total_tasks:
            # find a task that keeps as many different models as possible running concurrently
            model = min(model_counts.items(), key=lambda m: m[1])[0]
            next_task = next((t for t in pending_tasks if str(t.model) == model), None)
            if next_task:
                pending_tasks.remove(next_task)
                model_counts[str(next_task.model)] += 1
                await queue.put(next_task)
                return True
            else:
                return False
        else:
            return False

    async def worker() -> None:
        # worker runs untiil cancelled
        nonlocal tasks_completed
        while True:
            # remove the task from the queue and run it
            task_options = await queue.get()
            task = asyncio.create_task(task_run(task_options))
            try:
                await task
                result = task.result()
                results.append(result)
            except asyncio.CancelledError:
                task.cancel()
                await task
                result = task.result()
                results.append(result)

            # tracking
            tasks_completed += 1
            model_counts[str(task_options.model)] -= 1
            queue.task_done()

            if result.status != "cancelled":
                await enque_next_task()
            else:
                break

    # with task display
    with display().task_screen(total_tasks=len(tasks), parallel=True) as screen:
        # set screen
        init_task_screen(screen)

        # start worker tasks
        workers = [asyncio.create_task(worker()) for _ in range(0, parallel)]

        # enque initial set of tasks
        for _ in range(0, parallel):
            await enque_next_task()

        # wait for all tasks to complete
        try:
            await queue.join()
        except asyncio.CancelledError:
            pass
        finally:
            clear_task_screen()

        # cancel worker tasks
        for w in workers:
            w.cancel()

        return results


async def startup_sandbox_environments(
    tasks: list[ResolvedTask], cleanup: bool
) -> Callable[[], Awaitable[None]]:
    # find unique sandboxenvs
    sandboxenvs: Set[TaskSandboxEnvironment] = set()
    for task in tasks:
        # resolve each sample and add to sandboxenvs
        for sample in task.task.dataset:
            sandbox = resolve_sandbox_for_task(task.task, sample)
            if sandbox is not None and sandbox not in sandboxenvs:
                sandboxenvs.add(sandbox)

    # initialiase sandboxenvs (track cleanups)
    cleanups: list[tuple[TaskCleanup, str | None, str]] = []
    for sandboxenv in sandboxenvs:
        # find type
        sandboxenv_type = registry_find_sandboxenv(sandboxenv.sandbox.type)

        # run startup
        task_init = cast(TaskInit, getattr(sandboxenv_type, "task_init"))
        with chdir(sandboxenv.run_dir):
            await task_init("startup", sandboxenv.sandbox.config)

        # append cleanup method
        task_cleanup = cast(TaskCleanup, getattr(sandboxenv_type, "task_cleanup"))
        cleanups.append((task_cleanup, sandboxenv.sandbox.config, sandboxenv.run_dir))

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
