import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from shortuuid import uuid
from typing_extensions import Unpack

from inspect_ai._display.logger import init_logger
from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.file import absolute_file_path
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_lookup
from inspect_ai.log import EvalConfig, EvalLog, EvalLogInfo, read_eval_log
from inspect_ai.log._file import JSONRecorder
from inspect_ai.model import (
    GenerateConfig,
    GenerateConfigArgs,
    Model,
)
from inspect_ai.model._model import init_active_model, resolve_models
from inspect_ai.scorer._reducer import reducer_log_names
from inspect_ai.solver import Plan, Solver
from inspect_ai.util import SandboxEnvironmentSpec

from .context import init_eval_context
from .loader import ResolvedTask, resolve_tasks
from .run import eval_run
from .task import Epochs, PreviousTask, Tasks

log = logging.getLogger(__name__)


def eval(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] = dict(),
    task_args: dict[str, Any] = dict(),
    sandbox: SandboxEnvironmentSpec | None = None,
    sandbox_cleanup: bool | None = None,
    plan: Plan | Solver | list[Solver] | None = None,
    log_level: str | None = None,
    log_dir: str | None = None,
    limit: int | tuple[int, int] | None = None,
    epochs: int | Epochs | None = None,
    max_messages: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    score: bool = True,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    r"""Evaluate tasks using a Model.

    Args:
        tasks: (Tasks): Task(s) to evaluate. If None, attempt
            to evaluate a task in the current working directory
        model (str | Model | list[str] | list[Model] | None): Model(s) for
            evaluation. If not specified use the value of the INSPECT_EVAL_MODEL
            environment variable.
        model_base_url: (str | None): Base URL for communicating
            with the model API.
        model_args (dict[str,Any]): Model creation parameters
        task_args (dict[str,Any]): Task arguments
        sandbox (SandboxEnvironmentSpec | None): Sandbox
           environment type (or optionally a tuple with type and config file)
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
          (defaults to True)
        plan (Plan | Solver | list[Solver] | None): Alternative plan
           for evaluating task(s). Optional (uses task plan by default).
        log_level (str | None): "debug", "http", "sandbox", "info", "warning", "error",
           or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        limit (int | tuple[int, int] | None): Limit evaluated samples
           (defaults to all samples).
        epochs (int | Epochs | None): Epochs to repeat samples for and optional score
           reducer function(s) used to combine sample scores (defaults to "mean")
        max_messages (int | None): Maximum number of messages to allow
           in a task conversation.
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int | None): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file
            (defaults to 10 for local filesystems and 100 for remote filesystems)
        score (bool): Score output (defaults to True)
        **kwargs (GenerateConfigArgs): Model generation options.

    Returns:
        List of EvalLog (one for each task)
    """
    # standard platform init for top level entry points
    platform_init()

    return asyncio.run(
        eval_async(
            tasks=tasks,
            model=model,
            model_base_url=model_base_url,
            model_args=model_args,
            task_args=task_args,
            sandbox=sandbox,
            sandbox_cleanup=sandbox_cleanup,
            plan=plan,
            log_level=log_level,
            log_dir=log_dir,
            limit=limit,
            epochs=epochs,
            max_messages=max_messages,
            max_samples=max_samples,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            log_samples=log_samples,
            log_images=log_images,
            log_buffer=log_buffer,
            score=score,
            **kwargs,
        )
    )


async def eval_async(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] = dict(),
    task_args: dict[str, Any] = dict(),
    sandbox: SandboxEnvironmentSpec | None = None,
    sandbox_cleanup: bool | None = None,
    plan: Plan | Solver | list[Solver] | None = None,
    log_level: str | None = None,
    log_dir: str | None = None,
    limit: int | tuple[int, int] | None = None,
    epochs: int | Epochs | None = None,
    max_messages: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    score: bool = True,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    r"""Evaluate tasks using a Model (async).

    Args:
        tasks: (Tasks): Task(s) to evaluate. If None, attempt
            to evaluate a task in the current working directory
        model (str | Model | list[str] | list[Model] | None): Model(s) for
            evaluation. If not specified use the value of the INSPECT_EVAL_MODEL
            environment variable.
        model_base_url: (str | None): Base URL for communicating
            with the model API.
        model_args (dict[str,Any]): Model creation parameters
        task_args (dict[str,Any]): Task arguments
        sandbox (SandboxEnvironentSpec | None): Sandbox
           environment type (or optionally a tuple with type and config file)
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
           (defaults to True)
        plan (Plan | Solver | list[Solver] | None): Alternative plan
           for evaluating task(s). Optional (uses task plan by default).
        log_level (str | None): "debug", "http", "sandbox", "info", "warning", "error",
            or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
            (defaults to file log in ./logs directory).
        limit (int | tuple[int, int] | None): Limit evaluated samples
            (defaults to all samples).
        epochs (int | Epochs | None): Epochs to repeat samples for and optional score
            reducer function(s) used to combine sample scores (defaults to "mean")
        max_messages (int | None): Maximum number of messages to allow
            in a task conversation.
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int | None): Maximum number of subprocesses to
            run in parallel (default is os.cpu_count())
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file
            (defaults to 10 for local filesystems and 100 for remote filesystems)
        score (bool): Score output (defaults to True)
        **kwargs (GenerateConfigArgs): Model generation options.

    Returns:
        List of EvalLog (one for each task)
    """
    # only a single call to eval_async can be active at a time, this is
    # because when running a task a chdir to the task's directory (and
    # similar mutation of the Python sys.path) occurs. since this is a
    # change to global process state it cannot occur in parallel. for
    # task parallelism, pass multiple tasks to eval or eval_async (which
    # will enforce the appropriate constraints on task parallelism)
    global _eval_async_running
    if _eval_async_running:
        raise RuntimeError("Multiple concurrent calls to eval_async are not allowed.")

    _eval_async_running = True
    try:
        # Provide .env and log support bootstrap for notebooks and invoking
        # an eval as a plain Python script (as opposed to via inspect eval)
        init_dotenv()
        init_logger(log_level)

        # init eval context
        init_eval_context(max_subprocesses)

        # resolve models
        generate_config = GenerateConfig(**kwargs)
        models = resolve_models(model, model_base_url, model_args, generate_config)

        # resolve epochs
        if isinstance(epochs, int):
            epochs = Epochs(epochs)

        # resolve tasks (set active model to resolve uses of the
        # 'default' model in tools, solvers, and scorers)
        resolved_tasks: list[ResolvedTask] = []
        for m in models:
            init_active_model(m, generate_config)
            resolved_tasks.extend(resolve_tasks(tasks, task_args, m, sandbox))

        # warn and return empty string if we resolved no tasks
        if len(resolved_tasks) == 0:
            log.warning("No inspect tasks were found at the specified paths.")
            return []

        # resolve recorder
        log_dir = log_dir if log_dir else os.environ.get("INSPECT_LOG_DIR", "./logs")
        log_dir = absolute_file_path(log_dir)
        recorder = JSONRecorder(log_dir, log_buffer=log_buffer)

        # create config
        epochs_reducer = epochs.reducer if epochs else None
        eval_config = EvalConfig(
            limit=limit,
            epochs=epochs.epochs if epochs else None,
            epochs_reducer=reducer_log_names(epochs_reducer)
            if epochs_reducer
            else None,
            max_messages=max_messages,
            max_samples=max_samples,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            sandbox_cleanup=sandbox_cleanup,
            log_samples=log_samples,
            log_images=log_images,
            log_buffer=log_buffer,
        )

        # run tasks - 2 codepaths, one for the traditional task at a time
        # (w/ optional multiple models) and the other for true multi-task
        # (which requires different scheduling and UI)
        run_id = uuid()
        task_definitions = len(resolved_tasks) // len(models)
        parallel = 1 if (task_definitions == 1 or max_tasks is None) else max_tasks

        # single task definition (could be multi-model) or max_tasks capped to 1
        if parallel == 1:
            results: list[EvalLog] = []
            for sequence in range(0, task_definitions):
                task_batch = list(
                    filter(lambda t: t.sequence == sequence, resolved_tasks)
                )
                results.extend(
                    await eval_run(
                        run_id=run_id,
                        tasks=task_batch,
                        parallel=parallel,
                        eval_config=eval_config,
                        recorder=recorder,
                        model_args=model_args,
                        epochs_reducer=epochs_reducer,
                        plan=plan,
                        score=score,
                        **kwargs,
                    )
                )
                # exit the loop if there was a cancellation
                if any([result.status == "cancelled" for result in results]):
                    break

            # return list of eval logs
            return EvalLogs(results)

        # multiple task definitions AND tasks not capped at 1
        else:
            results = await eval_run(
                run_id=run_id,
                tasks=resolved_tasks,
                parallel=parallel,
                eval_config=eval_config,
                recorder=recorder,
                model_args=model_args,
                epochs_reducer=epochs_reducer,
                plan=plan,
                score=score,
                **kwargs,
            )
            return EvalLogs(results)

    finally:
        _eval_async_running = False


# single call to eval_async at a time
_eval_async_running = False


def eval_retry(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_dir: str | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    sandbox_cleanup: bool | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    score: bool = True,
    max_retries: int | None = None,
    timeout: int | None = None,
    max_connections: int | None = None,
) -> list[EvalLog]:
    """Retry a previously failed evaluation task.

    Args:
        tasks: (str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog]):
            Log files for task(s) to retry.
        log_level (str | None): "debug", "http", "sandbox", "info", "warning", "error",
           or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int | None): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
           (defaults to True)
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file
            (defaults to 10 for local filesystems and 100 for remote filesystems)
        score (bool): Score output (defaults to True)
        max_retries (int | None):
           Maximum number of times to retry request.
        timeout: (int | None):
           Request timeout (in seconds)
        max_connections (int | None):
           Maximum number of concurrent connections to Model API (default is per Model API)

    Returns:
        List of EvalLog (one for each task)
    """
    platform_init()

    return asyncio.run(
        eval_retry_async(
            tasks=tasks,
            log_level=log_level,
            log_dir=log_dir,
            max_samples=max_samples,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            sandbox_cleanup=sandbox_cleanup,
            log_samples=log_samples,
            log_images=log_images,
            log_buffer=log_buffer,
            score=score,
            max_retries=max_retries,
            timeout=timeout,
            max_connections=max_connections,
        )
    )


async def eval_retry_async(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_dir: str | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    sandbox_cleanup: bool | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    score: bool = True,
    max_retries: int | None = None,
    timeout: int | None = None,
    max_connections: int | None = None,
) -> list[EvalLog]:
    """Retry a previously failed evaluation task.

    Args:
        tasks: (str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog]):
            Log files for task(s) to retry.
        log_level (str | None): "debug", "http", "sandbox", "info", "warning", "error",
           or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
           (defaults to True)
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file
            (defaults to 10 for local filesystems and 100 for remote filesystems)
        score (bool): Score output (defaults to True)
        max_retries (int | None):
           Maximum number of times to retry request.
        timeout: (int | None):
           Request timeout (in seconds)
        max_connections (int | None):
           Maximum number of concurrent connections to Model API (default is per Model API)

    Returns:
        List of EvalLog (one for each task)
    """
    # resolve into a list of eval logs
    if isinstance(tasks, EvalLogInfo):
        tasks = [tasks]
    elif isinstance(tasks, EvalLog):
        tasks = [tasks]
    elif isinstance(tasks, str):
        tasks = [tasks]
    retry_eval_logs = [
        (
            task
            if isinstance(task, EvalLog)
            else (
                read_eval_log(task.name)
                if isinstance(task, EvalLogInfo)
                else read_eval_log(task)
            )
        )
        for task in tasks
    ]

    # eval them in turn
    eval_logs: list[EvalLog] = []
    for eval_log in retry_eval_logs:
        # the task needs to be either filesystem or registry
        # based in order to do a retry (we don't have enough
        # context to reconstruct ephemeral Task instances)
        task: str | None
        task_id = eval_log.eval.task_id
        task_name = eval_log.eval.task
        task_file = eval_log.eval.task_file
        if task_file:
            if not Path(task_file).exists():
                raise FileNotFoundError(f"Task file '{task_file}' not found")
            task = f"{task_file}@{task_name}"
        else:
            if registry_lookup("task", task_name) is None:
                raise FileNotFoundError(f"Task '{task_name}' not found.")
            task = task_name

        # collect the rest of the params we need for the eval
        model = eval_log.eval.model
        model_base_url = eval_log.eval.model_base_url
        model_args = eval_log.eval.model_args
        task_args = eval_log.eval.task_args
        limit = eval_log.eval.config.limit
        epochs = eval_log.eval.config.epochs
        max_messages = eval_log.eval.config.max_messages
        max_samples = max_samples or eval_log.eval.config.max_samples
        max_tasks = max_tasks or eval_log.eval.config.max_tasks
        max_subprocesses = max_subprocesses or eval_log.eval.config.max_subprocesses
        sandbox_cleanup = (
            sandbox_cleanup
            if sandbox_cleanup is not None
            else eval_log.eval.config.sandbox_cleanup
        )
        log_samples = (
            log_samples if log_samples is not None else eval_log.eval.config.log_samples
        )
        log_images = (
            log_images if log_images is not None else eval_log.eval.config.log_images
        )
        log_buffer = (
            log_buffer if log_buffer is not None else eval_log.eval.config.log_buffer
        )

        config = eval_log.plan.config
        config.max_retries = max_retries or config.max_retries
        config.timeout = timeout or config.timeout
        config.max_connections = max_connections or config.max_connections

        # run the eval
        log = (
            await eval_async(
                tasks=PreviousTask(task=task, id=task_id, log=eval_log),
                model=model,
                model_base_url=model_base_url,
                model_args=model_args,
                task_args=task_args,
                sandbox=eval_log.eval.sandbox,
                sandbox_cleanup=sandbox_cleanup,
                log_level=log_level,
                log_dir=log_dir,
                limit=limit,
                epochs=epochs,
                max_messages=max_messages,
                max_samples=max_samples,
                max_tasks=max_tasks,
                max_subprocesses=max_subprocesses,
                log_samples=log_samples,
                log_images=log_images,
                log_buffer=log_buffer,
                score=score,
                **dict(config),
            )
        )[0]

        # add it to our results
        eval_logs.append(log)

    return EvalLogs(eval_logs)


# A list of eval logs is returned from eval(). We've already displayed
# all of the output we need to to though, so we make the return
# value 'invisible'
class EvalLogs(list[EvalLog]):
    def _ipython_display_(self) -> None:
        pass

    def __repr__(self) -> str:
        return ""
