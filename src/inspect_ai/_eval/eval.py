import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from shortuuid import uuid
from typing_extensions import Unpack

from inspect_ai._display.logger import init_logger
from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_lookup
from inspect_ai._view.view import view_notify_eval
from inspect_ai.log import EvalConfig, EvalLog, EvalLogInfo, read_eval_log
from inspect_ai.log._file import JSONRecorder
from inspect_ai.model import (
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    get_model,
)
from inspect_ai.model._model import init_async_context_model
from inspect_ai.solver import Solver, ToolEnvironmentSpec
from inspect_ai.util._context import init_async_context

from .loader import resolve_tasks
from .task import PreviousTask, Tasks
from .task.log import TaskLogger
from .task.run import eval_log_sample_source, task_run
from .task.util import task_file, task_run_dir

log = logging.getLogger(__name__)


def eval(
    tasks: Tasks,
    model: str | Model | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] = dict(),
    task_args: dict[str, Any] = dict(),
    toolenv: ToolEnvironmentSpec | None = None,
    toolenv_cleanup: bool | None = None,
    plan: Solver | list[Solver] | None = None,
    log_level: str | None = None,
    log_dir: str | None = None,
    limit: int | tuple[int, int] | None = None,
    epochs: int | None = None,
    max_messages: int | None = None,
    max_samples: int | None = None,
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
        model (str | Model | None): Model for evaluation. If not
            specified uses the current eval's model, or failing that
            the value of the INSPECT_EVAL_MODEL environment variable.
        model_base_url: (str | None): Base URL for communicating
            with the model API.
        model_args (dict[str,Any]): Model creation parameters
        task_args (dict[str,Any]): Task arguments
        toolenv (ToolEnvironmentSpec | None): Tool
           environment type (or optionally a tuple with type and config file)
        toolenv_cleanup (bool | None): Cleanup tool environments after task completes
          (defaults to True)
        plan (Solver | list[Solver] | None): Alternative plan
           for evaluating task(s). Optional (uses task plan by default).
        log_level (str | None): "debug", "http", "info", "warning", "error",
           or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        limit (int | tuple[int, int] | None): Limit evaluated samples
            (defaults to all samples).
        epochs (int | None): Number of times to repeat evaluation of
            samples (defaults to 1)
        max_messages (int | None): Maximum number of messages to allow
           in a task conversation.
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is running all samples in parallel)
        max_subprocesses (int | None): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to True)
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
            toolenv=toolenv,
            toolenv_cleanup=toolenv_cleanup,
            plan=plan,
            log_level=log_level,
            log_dir=log_dir,
            limit=limit,
            epochs=epochs,
            max_messages=max_messages,
            max_samples=max_samples,
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
    model: str | Model | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] = dict(),
    task_args: dict[str, Any] = dict(),
    toolenv: ToolEnvironmentSpec | None = None,
    toolenv_cleanup: bool | None = None,
    plan: Solver | list[Solver] | None = None,
    log_level: str | None = None,
    log_dir: str | None = None,
    limit: int | tuple[int, int] | None = None,
    epochs: int | None = None,
    max_messages: int | None = None,
    max_samples: int | None = None,
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
        model (str | Model | None): Model for evaluation. If not
            specified uses the current eval's model, or failing that
            the value of the INSPECT_EVAL_MODEL environment variable.
        model_base_url: (str | None): Base URL for communicating
            with the model API.
        model_args (dict[str,Any]): Model creation parameters
        task_args (dict[str,Any]): Task arguments
        toolenv (ToolEnvironentSpec | None): Tool
           environment type (or optionally a tuple with type and config file)
        toolenv_cleanup (bool | None): Cleanup tool environments after task completes
           (defaults to True)
        plan (Solver | list[Solver] | None): Alternative plan
            for evaluating task(s). Optional (uses task plan by default).
        log_level (str | None): "debug", "http", "info", "warning", "error",
            or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
            (defaults to file log in ./logs directory).
        limit (int | tuple[int, int] | None): Limit evaluated samples
            (defaults to all samples).
        epochs (int | None): Number of times to repeat evaluation of
            samples (defaults to 1)
        max_messages (int | None): Maximum number of messages to allow
            in a task conversation.
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is running all samples in parallel)
        max_subprocesses (int | None): Maximum number of subprocesses to
            run in parallel (default is os.cpu_count())
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to True)
        log_buffer: (int | None): Number of samples to buffer before writing log file
            (defaults to 10 for local filesystems and 100 for remote filesystems)
        score (bool): Score output (defaults to True)
        **kwargs (GenerateConfigArgs): Model generation options.

    Returns:
        List of EvalLog (one for each task)
    """
    # Provide .env and log support bootstrap for notebooks and invoking
    # an eval as a plain Python script (as opposed to via inspect eval)
    init_dotenv()
    init_logger(log_level)

    # resolve model
    model = get_model(
        model=model,
        base_url=model_base_url,
        config=GenerateConfig(**kwargs),
        **model_args,
    )

    # init async context vars
    init_async_context(max_subprocesses)
    init_async_context_model(model)

    # if this is a PreviousTask then we are being spotted our id and log
    if isinstance(tasks, PreviousTask):
        task_id = tasks.id
        eval_log = tasks.log
        tasks = tasks.task
    else:
        task_id = None
        eval_log = None

    # resolve tasks
    eval_tasks = resolve_tasks(tasks, model, task_args)

    # if we have an eval_log, see if we can re-use its logged samples
    sample_source = eval_log_sample_source(eval_log, eval_tasks[0].dataset)

    # warn and return empty string if we resolved no tasks
    if len(eval_tasks) == 0:
        log.warning("No inspect tasks were found at the specified paths.")
        return []

    # resolve recorder
    log_dir = log_dir if log_dir else os.environ.get("INSPECT_LOG_DIR", "./logs")
    log_dir = cwd_relative_path(log_dir)
    recorder = JSONRecorder(log_dir, log_buffer=log_buffer)

    # build task names and versions (include version if > 0)
    task_names: list[str] = [task.name for task in eval_tasks]
    task_versions: list[int] = [task.version for task in eval_tasks]

    # create config
    eval_config = EvalConfig(
        limit=limit,
        epochs=epochs,
        max_messages=max_messages,
        max_samples=max_samples,
        max_subprocesses=max_subprocesses,
        toolenv_cleanup=toolenv_cleanup,
        log_samples=log_samples,
        log_images=log_images,
        log_buffer=log_buffer,
    )

    run_id = uuid()
    loggers: list[TaskLogger] = []
    results: list[EvalLog] = []
    for index, name, version, task in zip(
        range(0, len(task_names)), task_names, task_versions, eval_tasks
    ):
        # tasks can provide their own epochs and max_messages
        task_eval_config = eval_config.model_copy()
        if task.epochs is not None:
            task_eval_config.epochs = task.epochs
        if task.max_messages is not None:
            task_eval_config.max_messages = task.max_messages

        # create and track the logger
        logger = TaskLogger(
            task_name=name,
            task_version=version,
            task_file=task_file(task, relative=True),
            task_run_dir=task_run_dir(task),
            task_id=task_id if task_id else uuid(),
            run_id=run_id,
            model=model,
            dataset=task.dataset,
            tool_environment=toolenv,
            task_attribs=task.attribs,
            task_args=task_args,
            model_args=model_args,
            eval_config=task_eval_config,
            recorder=recorder,
        )
        loggers.append(logger)

        # run the eval
        result = await task_run(
            task=task,
            sequence=(index + 1, len(task_names)),
            model=model,
            logger=logger,
            config=task_eval_config,
            plan=plan,
            score=score,
            sample_source=sample_source,
            **kwargs,
        )

        # mark completed and append result
        results.append(result)

        # notify the view module that an eval just completed
        # (in case we have a view polling for new evals)
        view_notify_eval(logger.location)

    # return list of eval logs
    return EvalLogs(results)


def eval_retry(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_dir: str | None = None,
    max_samples: int | None = None,
    max_subprocesses: int | None = None,
    toolenv_cleanup: bool | None = None,
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
        log_level (str | None): "debug", "http", "info", "warning", "error",
           or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is running all samples in parallel)
        max_subprocesses (int | None): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        toolenv_cleanup (bool | None): Cleanup tool environments after task completes
           (defaults to True)
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to True)
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
            max_subprocesses=max_subprocesses,
            toolenv_cleanup=toolenv_cleanup,
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
    max_subprocesses: int | None = None,
    toolenv_cleanup: bool | None = None,
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
        log_level (str | None): "debug", "http", "info", "warning", "error",
           or "critical" (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is running all samples in parallel)
        max_subprocesses (int): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        toolenv_cleanup (bool | None): Cleanup tool environments after task completes
           (defaults to True)
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to True)
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
                raise FileNotFoundError("Task file '{task_file}' not found")
            task = f"{task_file}@{task_name}"
        else:
            if registry_lookup("task", task_name) is None:
                raise FileNotFoundError("Task '{task_name}' not found.")
            task = task_name

        # collect the rest of the params we need for the eval
        model = eval_log.eval.model
        model_base_url = eval_log.eval.model_base_url
        model_args = eval_log.eval.model_args
        task_args = eval_log.eval.task_args
        limit = eval_log.eval.config.limit
        epochs = eval_log.eval.config.epochs
        max_messages = eval_log.eval.config.max_messages
        max_samples = max_samples
        max_subprocesses = max_subprocesses or eval_log.eval.config.max_subprocesses
        toolenv_cleanup = (
            toolenv_cleanup
            if toolenv_cleanup is not None
            else eval_log.eval.config.toolenv_cleanup
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
                toolenv=eval_log.eval.tool_environment,
                toolenv_cleanup=toolenv_cleanup,
                log_level=log_level,
                log_dir=log_dir,
                limit=limit,
                epochs=epochs,
                max_messages=max_messages,
                max_samples=max_samples,
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
