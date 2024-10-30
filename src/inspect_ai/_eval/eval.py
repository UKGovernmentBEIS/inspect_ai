import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Literal

from shortuuid import uuid
from typing_extensions import Unpack

from inspect_ai._cli.util import parse_cli_args
from inspect_ai._util.config import resolve_args
from inspect_ai._util.constants import DEFAULT_LOG_FORMAT
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import absolute_file_path
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_lookup
from inspect_ai.approval._apply import init_tool_approval
from inspect_ai.approval._policy import (
    ApprovalPolicy,
    ApprovalPolicyConfig,
    approval_policies_from_config,
    config_from_approval_policies,
)
from inspect_ai.log import EvalConfig, EvalLog, EvalLogInfo, read_eval_log
from inspect_ai.log._recorders import create_recorder_for_format
from inspect_ai.model import (
    GenerateConfig,
    GenerateConfigArgs,
    Model,
)
from inspect_ai.model._model import init_active_model, resolve_models
from inspect_ai.scorer._reducer import reducer_log_names
from inspect_ai.solver._chain import chain
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util import SandboxEnvironmentType

from .context import init_eval_context
from .loader import ResolvedTask, resolve_tasks
from .run import eval_run
from .task import Epochs, PreviousTask, Tasks

log = logging.getLogger(__name__)


def eval(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | list[Solver] | SolverSpec | None = None,
    tags: list[str] | None = None,
    trace: bool | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
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
        model_args (dict[str,Any] | str): Model creation args
            (as a dictionary or as a path to a JSON or YAML config file)
        task_args (dict[str,Any] | str): Task creation arguments
            (as a dictionary or as a path to a JSON or YAML config file)
        sandbox (SandboxEnvironmentType | None): Sandbox environment type
          (or optionally a str or tuple with a shorthand spec)
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
          (defaults to True)
        solver (Solver | list[Solver] | SolverSpec | None): Alternative solver for task(s).
          Optional (uses task solver by default).
        tags (list[str] | None): Tags to associate with this evaluation run.
        trace: (bool | None): Trace message interactions with evaluated model to terminal.
        approval: (str | list[ApprovalPolicy] | None): Tool use approval policies.
          Either a path to an approval policy config file or a list of approval policies.
          Defaults to no approval policy.
        log_level (str | None): Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript (str | None): Level for logging to the log file (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        log_format (Literal["eval", "json"] | None): Format for writing log files (defaults
           to "eval", the native high-performance format).
        limit (int | tuple[int, int] | None): Limit evaluated samples
           (defaults to all samples).
        epochs (int | Epochs | None): Epochs to repeat samples for and optional score
           reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error (bool | float | None): `True` to fail on first sample error
           (default); `False` to never fail on sample errors; Value between 0 and 1
           to fail if a proportion of total samples fails. Value greater than 1 to fail
           eval if a count of samples fails.
        debug_errors (bool | None): Raise task errors (rather than logging them)
           so they can be debugged (defaults to False).
        message_limit (int | None): Limit on total messages used for each sample.
        token_limit (int | None): Limit on total tokens used for each sample.
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int | None): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file.
           If not specified, an appropriate default for the format and filesystem is
           chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
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
            solver=solver,
            tags=tags,
            trace=trace,
            approval=approval,
            log_level=log_level,
            log_level_transcript=log_level_transcript,
            log_dir=log_dir,
            log_format=log_format,
            limit=limit,
            epochs=epochs,
            fail_on_error=fail_on_error,
            debug_errors=debug_errors,
            message_limit=message_limit,
            token_limit=token_limit,
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
    model_args: dict[str, Any] | str = dict(),
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | list[Solver] | SolverSpec | None = None,
    tags: list[str] | None = None,
    trace: bool | None = None,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
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
        model_args (dict[str,Any] | str): Model creation args
            (as a dictionary or as a path to a JSON or YAML config file)
        task_args (dict[str,Any] | str): Task creation arguments
            (as a dictionary or as a path to a JSON or YAML config file)
        sandbox (SandboxEnvironmentType | None): Sandbox environment type
          (or optionally a str or tuple with a shorthand spec)
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
           (defaults to True)
        solver (Solver | list[Solver] | SolverSpec | None): Alternative solver for task(s).
          Optional (uses task solver by default).
        tags (list[str] | None): Tags to associate with this evaluation run.
        trace: (bool | None): Trace message interactions with evaluated model to terminal.
        approval: (str | list[ApprovalPolicy] | None): Tool use approval policies.
          Either a path to an approval policy config file or a list of approval policies.
          Defaults to no approval policy.
        log_level (str | None): Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript (str | None): Level for logging to the log file (defaults to "info")
        log_dir (str | None): Output path for logging results
            (defaults to file log in ./logs directory).
        log_format (Literal["eval", "json"] | None): Format for writing log files (defaults
           to "eval", the native high-performance format).
        limit (int | tuple[int, int] | None): Limit evaluated samples
            (defaults to all samples).
        epochs (int | Epochs | None): Epochs to repeat samples for and optional score
            reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error (bool | float | None): `True` to fail on first sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.
        debug_errors (bool | None): Raise task errors (rather than logging them)
           so they can be debugged (defaults to False).
        message_limit (int | None): Limit on total messages used for each sample.
        token_limit (int | None): Limit on total tokens used for each sample.
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int | None): Maximum number of subprocesses to
            run in parallel (default is os.cpu_count())

        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file.
           If not specified, an appropriate default for the format and filesystem is
           chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
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

    # resolve model and task args
    model_args = resolve_args(model_args)
    task_args = resolve_args(task_args)

    try:
        # intialise eval
        model, approval, resolved_tasks = eval_init(
            tasks=tasks,
            model=model,
            model_base_url=model_base_url,
            model_args=model_args,
            task_args=task_args,
            sandbox=sandbox,
            trace=trace,
            approval=approval,
            max_subprocesses=max_subprocesses,
            log_level=log_level,
            log_level_transcript=log_level_transcript,
            **kwargs,
        )

        # warn and return empty string if we resolved no tasks
        if len(resolved_tasks) == 0:
            log.warning("No inspect tasks were found at the specified paths.")
            return []

        # apply trace mode constraints
        if trace:
            # single task at a time
            if max_tasks is not None:
                max_tasks = 1

            # single sample at a time
            max_samples = 1

            # multiple models not allowed in trace mode
            if len(model) > 1:
                raise PrerequisiteError(
                    "Trace mode cannot be used when evaluating multiple models."
                )

        # resolve recorder
        log_dir = log_dir if log_dir else os.environ.get("INSPECT_LOG_DIR", "./logs")
        log_dir = absolute_file_path(log_dir)
        recorder = create_recorder_for_format(log_format or DEFAULT_LOG_FORMAT, log_dir)

        # resolve solver
        solver = chain(solver) if isinstance(solver, list) else solver

        # resolve epochs
        if isinstance(epochs, int):
            epochs = Epochs(epochs)
        if epochs is not None and epochs.epochs < 1:
            raise ValueError("epochs must be a positive integer.")

        # create config
        epochs_reducer = epochs.reducer if epochs else None
        eval_config = EvalConfig(
            limit=limit,
            epochs=epochs.epochs if epochs else None,
            epochs_reducer=reducer_log_names(epochs_reducer)
            if epochs_reducer
            else None,
            trace=trace,
            approval=config_from_approval_policies(approval) if approval else None,
            fail_on_error=fail_on_error,
            message_limit=message_limit,
            token_limit=token_limit,
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
        task_definitions = len(resolved_tasks) // len(model)
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
                        solver=solver,
                        tags=tags,
                        score=score,
                        debug_errors=debug_errors is True,
                        **kwargs,
                    )
                )
                # exit the loop if there was a cancellation
                if any([result.status == "cancelled" for result in results]):
                    break

            # return list of eval logs
            logs = EvalLogs(results)

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
                solver=solver,
                tags=tags,
                score=score,
                **kwargs,
            )
            logs = EvalLogs(results)

    finally:
        _eval_async_running = False

    # return logs
    return logs


# single call to eval_async at a time
_eval_async_running = False


def eval_retry(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    sandbox_cleanup: bool | None = None,
    trace: bool | None = None,
    fail_on_error: bool | float | None = None,
    debug_errors: bool | None = None,
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
        log_level (str | None): Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript (str | None): Level for logging to the log file (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        log_format (Literal["eval", "json"] | None): Format for writing log files (defaults
           to "eval", the native high-performance format).
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int | None): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
           (defaults to True)
        trace (bool | None): Trace message interactions with evaluated model to terminal.
        fail_on_error (bool | float | None): `True` to fail on first sample error
           (default); `False` to never fail on sample errors; Value between 0 and 1
           to fail if a proportion of total samples fails. Value greater than 1 to fail
           eval if a count of samples fails.
        debug_errors (bool | None): Raise task errors (rather than logging them)
           so they can be debugged (defaults to False).
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file.
           If not specified, an appropriate default for the format and filesystem is
           chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
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
            log_level_transcript=log_level_transcript,
            log_dir=log_dir,
            log_format=log_format,
            max_samples=max_samples,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            sandbox_cleanup=sandbox_cleanup,
            trace=trace,
            fail_on_error=fail_on_error,
            debug_errors=debug_errors,
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
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    sandbox_cleanup: bool | None = None,
    trace: bool | None = None,
    fail_on_error: bool | float | None = None,
    debug_errors: bool | None = None,
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
        log_level (str | None): Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript (str | None): Level for logging to the log file (defaults to "info")
        log_dir (str | None): Output path for logging results
           (defaults to file log in ./logs directory).
        log_format (Literal["eval", "json"] | None): Format for writing log files (defaults
           to "eval", the native high-performance format).
        max_samples (int | None): Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks (int | None): Maximum number of tasks to run in parallel
           (default is 1)
        max_subprocesses (int): Maximum number of subprocesses to
           run in parallel (default is os.cpu_count())
        sandbox_cleanup (bool | None): Cleanup sandbox environments after task completes
           (defaults to True)
        trace (bool | None): Trace message interactions with evaluated model to terminal.
        fail_on_error (bool | float | None): `True` to fail on first sample error
           (default); `False` to never fail on sample errors; Value between 0 and 1
           to fail if a proportion of total samples fails. Value greater than 1 to fail
           eval if a count of samples fails.
        debug_errors (bool | None): Raise task errors (rather than logging them)
           so they can be debugged (defaults to False).
        log_samples: (bool | None): Log detailed samples and scores (defaults to True)
        log_images: (bool | None): Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to False)
        log_buffer: (int | None): Number of samples to buffer before writing log file.
           If not specified, an appropriate default for the format and filesystem is
           chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
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

        # see if there is solver spec in the eval log
        solver = (
            SolverSpec(eval_log.eval.solver, eval_log.eval.solver_args or {})
            if eval_log.eval.solver
            else None
        )

        # collect the rest of the params we need for the eval
        model = eval_log.eval.model
        model_base_url = eval_log.eval.model_base_url
        model_args = eval_log.eval.model_args
        task_args = eval_log.eval.task_args
        tags = eval_log.eval.tags
        limit = eval_log.eval.config.limit
        epochs = (
            Epochs(eval_log.eval.config.epochs, eval_log.eval.config.epochs_reducer)
            if eval_log.eval.config.epochs
            else None
        )
        trace = eval_log.eval.config.trace or trace
        approval = eval_log.eval.config.approval
        message_limit = eval_log.eval.config.message_limit
        token_limit = eval_log.eval.config.token_limit
        max_samples = max_samples or eval_log.eval.config.max_samples
        max_tasks = max_tasks or eval_log.eval.config.max_tasks
        max_subprocesses = max_subprocesses or eval_log.eval.config.max_subprocesses
        sandbox_cleanup = (
            sandbox_cleanup
            if sandbox_cleanup is not None
            else eval_log.eval.config.sandbox_cleanup
        )
        fail_on_error = (
            fail_on_error
            if fail_on_error is not None
            else eval_log.eval.config.fail_on_error
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
                tasks=PreviousTask(
                    id=task_id, task=task, task_args=task_args, log=eval_log
                ),
                model=model,
                model_base_url=model_base_url,
                model_args=model_args,
                task_args=task_args,
                sandbox=eval_log.eval.sandbox,
                sandbox_cleanup=sandbox_cleanup,
                solver=solver,
                tags=tags,
                trace=trace,
                approval=approval,
                log_level=log_level,
                log_level_transcript=log_level_transcript,
                log_dir=log_dir,
                log_format=log_format,
                limit=limit,
                epochs=epochs,
                fail_on_error=fail_on_error,
                debug_errors=debug_errors,
                message_limit=message_limit,
                token_limit=token_limit,
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


def eval_init(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    trace: bool | None = None,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = None,
    max_subprocesses: int | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> tuple[list[Model], list[ApprovalPolicy] | None, list[ResolvedTask]]:
    # init eval context
    init_eval_context(trace, log_level, log_level_transcript, max_subprocesses)

    # resolve model and task args
    model_args = resolve_args(model_args)
    task_args = resolve_args(task_args)

    # resolve model args from environment if not specified
    if len(model_args) == 0:
        env_model_args = os.environ.get("INSPECT_EVAL_MODEL_ARGS", None)
        if env_model_args:
            args = [arg.strip() for arg in env_model_args.split(" ")]
            model_args = parse_cli_args(args)

    # resolve models
    generate_config = GenerateConfig(**kwargs)
    models = resolve_models(model, model_base_url, model_args, generate_config)

    # resolve tasks (set active model to resolve uses of the
    # 'default' model in tools, solvers, and scorers)
    resolved_tasks: list[ResolvedTask] = []
    for m in models:
        init_active_model(m, generate_config)
        resolved_tasks.extend(resolve_tasks(tasks, task_args, m, sandbox))

    # resolve approval
    if isinstance(approval, str | ApprovalPolicyConfig):
        approval = approval_policies_from_config(approval)
    init_tool_approval(approval)

    return models, approval, resolved_tasks


# A list of eval logs is returned from eval(). We've already displayed
# all of the output we need to to though, so we make the return
# value 'invisible'
class EvalLogs(list[EvalLog]):
    def _ipython_display_(self) -> None:
        pass

    def __repr__(self) -> str:
        return ""
