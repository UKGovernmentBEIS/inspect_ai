import logging
import os
import sys
from pathlib import Path
from typing import Any, Literal, cast

from inspect_ai._eval.task.task import resolve_model_roles
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai.agent._agent import Agent, is_agent
from inspect_ai.agent._as_solver import as_solver
from inspect_ai.log._model import model_roles_config_to_model_roles

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from shortuuid import uuid
from typing_extensions import Unpack

from inspect_ai._cli.util import parse_cli_args
from inspect_ai._display.core.active import display as task_display
from inspect_ai._util.config import resolve_args
from inspect_ai._util.constants import (
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_SHARED,
    JSON_LOG_FORMAT,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import absolute_file_path
from inspect_ai._util.logger import warn_once
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_lookup
from inspect_ai.approval._apply import init_tool_approval
from inspect_ai.approval._policy import (
    ApprovalPolicy,
    ApprovalPolicyConfig,
    approval_policies_from_config,
    config_from_approval_policies,
)
from inspect_ai.log import EvalConfig, EvalLog, EvalLogInfo
from inspect_ai.log._file import read_eval_log_async
from inspect_ai.log._recorders import create_recorder_for_format
from inspect_ai.log._recorders.buffer import cleanup_sample_buffers
from inspect_ai.model import (
    GenerateConfig,
    GenerateConfigArgs,
    Model,
)
from inspect_ai.model._model import get_model, init_active_model, resolve_models
from inspect_ai.scorer._reducer import reducer_log_names
from inspect_ai.solver._chain import chain
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util import SandboxEnvironmentType
from inspect_ai.util._display import (
    DisplayType,
    display_type,
    display_type_initialized,
    init_display_type,
)

from .context import init_eval_context
from .loader import resolve_tasks
from .run import eval_run
from .task import Epochs, PreviousTask
from .task.resolved import ResolvedTask, resolved_model_names
from .task.tasks import Tasks

log = logging.getLogger(__name__)


def eval(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    model_roles: dict[str, str | Model] | None = None,
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    approval: str | list[ApprovalPolicy] | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    retry_on_error: int | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    r"""Evaluate tasks using a Model.

    Args:
        tasks: Task(s) to evaluate. If None, attempt
            to evaluate a task in the current working directory
        model: Model(s) for evaluation. If not specified use the value of the INSPECT_EVAL_MODEL
            environment variable. Specify `None` to define no default model(s), which will
            leave model usage entirely up to tasks.
        model_base_url: Base URL for communicating
            with the model API.
        model_args: Model creation args
            (as a dictionary or as a path to a JSON or YAML config file)
        model_roles: Named roles for use in `get_model()`.
        task_args: Task creation arguments
            (as a dictionary or as a path to a JSON or YAML config file)
        sandbox: Sandbox environment type
            (or optionally a str or tuple with a shorthand spec)
        sandbox_cleanup: Cleanup sandbox environments after task completes
            (defaults to True)
        solver: Alternative solver for task(s).
            Optional (uses task solver by default).
        tags: Tags to associate with this evaluation run.
        metadata: Metadata to associate with this evaluation run.
        trace: Trace message interactions with evaluated model to terminal.
        display: Task display type (defaults to 'full').
        approval: Tool use approval policies.
            Either a path to an approval policy config file or a list of approval policies.
            Defaults to no approval policy.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
            "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript: Level for logging to the log file (defaults to "info")
        log_dir: Output path for logging results
            (defaults to file log in ./logs directory).
        log_format: Format for writing log files (defaults
            to "eval", the native high-performance format).
        limit: Limit evaluated samples
            (defaults to all samples).
        sample_id: Evaluate specific sample(s) from the dataset. Use plain ids or preface with task names as required to disambiguate ids across tasks (e.g. `popularity:10`).
        epochs: Epochs to repeat samples for and optional score
            reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error: `True` to fail on first sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail
            eval if a count of samples fails.
        retry_on_error: Number of times to retry samples if they encounter errors
            (by default, no retries occur).
        debug_errors: Raise task errors (rather than logging them)
            so they can be debugged (defaults to False).
        message_limit: Limit on total messages used for each sample.
        token_limit: Limit on total tokens used for each sample.
        time_limit: Limit on clock time (in seconds) for samples.
        working_limit: Limit on working time (in seconds) for sample. Working
            time includes model generation, tool calls, etc. but does not include
            time spent waiting on retries or shared resources.
        max_samples: Maximum number of samples to run in parallel
            (default is max_connections)
        max_tasks: Maximum number of tasks to run in parallel
            (defaults to number of models being evaluated)
        max_subprocesses: Maximum number of subprocesses to
            run in parallel (default is os.cpu_count())
        max_sandboxes: Maximum number of sandboxes (per-provider)
            to run in parallel.
        log_samples: Log detailed samples and scores (defaults to True)
        log_realtime: Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.
        log_images: Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to False)
        log_buffer: Number of samples to buffer before writing log file.
            If not specified, an appropriate default for the format and filesystem is
            chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Sync sample events to log directory so that users on other systems
            can see log updates in realtime (defaults to no syncing). Specify `True`
            to sync every 10 seconds, otherwise an integer to sync every `n` seconds.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        **kwargs: Model generation options.

    Returns:
        List of EvalLog (one for each task)
    """
    # standard platform init for top level entry points
    platform_init()

    # resolve eval trace
    max_tasks, max_samples = init_eval_display(
        display, trace, max_tasks, max_samples, model
    )

    async def run_task_app() -> list[EvalLog]:
        try:
            return await eval_async(
                tasks=tasks,
                model=model,
                model_base_url=model_base_url,
                model_args=model_args,
                model_roles=model_roles,
                task_args=task_args,
                sandbox=sandbox,
                sandbox_cleanup=sandbox_cleanup,
                solver=solver,
                tags=tags,
                metadata=metadata,
                approval=approval,
                log_level=log_level,
                log_level_transcript=log_level_transcript,
                log_dir=log_dir,
                log_format=log_format,
                limit=limit,
                sample_id=sample_id,
                epochs=epochs,
                fail_on_error=fail_on_error,
                retry_on_error=retry_on_error,
                debug_errors=debug_errors,
                message_limit=message_limit,
                token_limit=token_limit,
                time_limit=time_limit,
                working_limit=working_limit,
                max_samples=max_samples,
                max_tasks=max_tasks,
                max_subprocesses=max_subprocesses,
                max_sandboxes=max_sandboxes,
                log_samples=log_samples,
                log_realtime=log_realtime,
                log_images=log_images,
                log_buffer=log_buffer,
                log_shared=log_shared,
                score=score,
                score_display=score_display,
                **kwargs,
            )
        # exceptions can escape when debug_errors is True and that's okay
        except ExceptionGroup as ex:
            if debug_errors:
                raise ex.exceptions[0] from None
            else:
                raise

    return task_display().run_task_app(run_task_app)


# single call to eval_async at a time
_eval_async_running = False


async def eval_async(
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    model_roles: dict[str, str | Model] | None = None,
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    retry_on_error: int | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    r"""Evaluate tasks using a Model (async).

    Args:
        tasks: Task(s) to evaluate. If None, attempt
            to evaluate a task in the current working directory
        model: Model(s) for evaluation. If not specified use the value of the INSPECT_EVAL_MODEL
            environment variable. Specify `None` to define no default model(s), which will
            leave model usage entirely up to tasks.
        model_base_url: Base URL for communicating with the model API.
        model_args: Model creation args (as a dictionary or as a path to a JSON or YAML config file
        model_roles: Named roles for use in `get_model()`.
        task_args: Task creation arguments (as a dictionary or as a path to a JSON or YAML config file)
        sandbox: Sandbox environment type (or optionally a str or tuple with a shorthand spec)
        sandbox_cleanup: Cleanup sandbox environments after task completes (defaults to True)
        solver: Alternative solver for task(s).  Optional (uses task solver by default).
        tags: Tags to associate with this evaluation run.
        metadata: Metadata to associate with this evaluation run.
        approval: Tool use approval policies.
          Either a path to an approval policy config file or a list of approval policies.
          Defaults to no approval policy.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript: Level for logging to the log file (defaults to "info")
        log_dir: Output path for logging results (defaults to file log in ./logs directory).
        log_format: Format for writing log files (defaults to "eval", the native high-performance format).
        limit: Limit evaluated samples (defaults to all samples).
        sample_id: Evaluate specific sample(s) from the dataset. Use plain ids or preface with task names as required to disambiguate ids across tasks (e.g. `popularity:10`).
        epochs: Epochs to repeat samples for and optional score
            reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error: `True` to fail on first sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.
        retry_on_error: Number of times to retry samples if they encounter errors
            (by default, no retries occur).
        debug_errors: Raise task errors (rather than logging them) so they can be debugged (defaults to False).
        message_limit: Limit on total messages used for each sample.
        token_limit: Limit on total tokens used for each sample.
        time_limit: Limit on clock time (in seconds) for samples.
        working_limit: Limit on working time (in seconds) for sample. Working
            time includes model generation, tool calls, etc. but does not include
            time spent waiting on retries or shared resources.
        max_samples: Maximum number of samples to run in parallel (default is max_connections)
        max_tasks: Maximum number of tasks to run in parallel
            (defaults to number of models being evaluated)
        max_subprocesses: Maximum number of subprocesses to run in parallel (default is os.cpu_count())
        max_sandboxes: Maximum number of sandboxes (per-provider) to run in parallel.
        log_samples: Log detailed samples and scores (defaults to True)
        log_realtime: Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.
        log_images: Log base64 encoded version of images, even if specified as a filename or URL (defaults to False)
        log_buffer: Number of samples to buffer before writing log file.
           If not specified, an appropriate default for the format and filesystem is
           chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Indicate that the log directory is shared, which results in additional syncing of realtime log data for Inspect View.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        **kwargs: Model generation options.

    Returns:
        List of EvalLog (one for each task)
    """
    # only a single call to eval_async can be active at a time, this used
    # to be due to running tasks switching to the task's directory, however
    # that feature no longer exists so we may be able to revisit this
    # restriction (probably just need to examine if there is *global* state
    # that could have conflicts in the case of multiple eval_async calls)
    global _eval_async_running
    if _eval_async_running:
        raise RuntimeError("Multiple concurrent calls to eval_async are not allowed.")

    _eval_async_running = True

    # if we are called outside of eval() then set display type to "plain"
    if not display_type_initialized():
        init_display_type("plain")

    # resolve model and task args
    model_args = resolve_args(model_args)
    task_args = resolve_args(task_args)

    try:
        # intialise eval
        model = eval_init(
            model=model,
            model_base_url=model_base_url,
            model_args=model_args,
            max_subprocesses=max_subprocesses,
            log_level=log_level,
            log_level_transcript=log_level_transcript,
            **kwargs,
        )

        # resolve tasks
        resolved_tasks, approval = eval_resolve_tasks(
            tasks,
            task_args,
            model,
            model_roles,
            GenerateConfig(**kwargs),
            approval,
            sandbox,
        )

        # warn and return empty string if we resolved no tasks
        if len(resolved_tasks) == 0:
            log.warning("No inspect tasks were found at the specified paths.")
            return []

        # if there is no max tasks then base it on unique model names
        if max_tasks is None:
            model_count = len(resolved_model_names(resolved_tasks))
            if model_count > 1:
                max_tasks = model_count

        # apply conversation display constraints
        if display_type() == "conversation":
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

        # resolve recorder (confirm writeable)
        log_dir = log_dir if log_dir else os.environ.get("INSPECT_LOG_DIR", "./logs")
        log_dir = absolute_file_path(log_dir)
        recorder = create_recorder_for_format(log_format or DEFAULT_LOG_FORMAT, log_dir)
        if not recorder.is_writeable():
            raise PrerequisiteError(
                f"ERROR: You do not have write permission for the log_dir '{log_dir}'"
            )

        # resolve log_shared
        log_shared = DEFAULT_LOG_SHARED if log_shared is True else log_shared

        # validate that --log-shared can't use used with 'json' format
        if log_shared and log_format == JSON_LOG_FORMAT:
            raise PrerequisiteError(
                "ERROR: --log-shared is not compatible with the json log format."
            )

        # resolve solver
        if isinstance(solver, list):
            solver = chain(solver)
        elif is_agent(solver):
            solver = as_solver(solver)
        else:
            solver = cast(Solver | SolverSpec | None, solver)

        # ensure consistency of limit and sample_id
        if sample_id is not None and limit is not None:
            raise ValueError("You cannot specify both sample_id and limit.")

        # resolve epochs
        if isinstance(epochs, int):
            epochs = Epochs(epochs)
        if epochs is not None and epochs.epochs < 1:
            raise ValueError("epochs must be a positive integer.")

        # create config
        epochs_reducer = epochs.reducer if epochs else None
        eval_config = EvalConfig(
            limit=limit,
            sample_id=sample_id,
            epochs=epochs.epochs if epochs else None,
            epochs_reducer=reducer_log_names(epochs_reducer)
            if epochs_reducer
            else None,
            approval=config_from_approval_policies(approval) if approval else None,
            fail_on_error=fail_on_error,
            retry_on_error=retry_on_error,
            message_limit=message_limit,
            token_limit=token_limit,
            time_limit=time_limit,
            working_limit=working_limit,
            max_samples=max_samples,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            max_sandboxes=max_sandboxes,
            sandbox_cleanup=sandbox_cleanup,
            log_samples=log_samples,
            log_realtime=log_realtime,
            log_images=log_images,
            log_buffer=log_buffer,
            log_shared=log_shared,
            score_display=score_display,
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
                        eval_sandbox=sandbox,
                        recorder=recorder,
                        epochs_reducer=epochs_reducer,
                        solver=solver,
                        tags=tags,
                        metadata=metadata,
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
                eval_sandbox=sandbox,
                recorder=recorder,
                epochs_reducer=epochs_reducer,
                solver=solver,
                tags=tags,
                metadata=metadata,
                score=score,
                **kwargs,
            )
            logs = EvalLogs(results)

        # cleanup sample buffers if required
        cleanup_sample_buffers(log_dir)

    finally:
        _eval_async_running = False

    # return logs
    return logs


def eval_retry(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    sandbox_cleanup: bool | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    fail_on_error: bool | float | None = None,
    retry_on_error: int | None = None,
    debug_errors: bool | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    max_retries: int | None = None,
    timeout: int | None = None,
    max_connections: int | None = None,
) -> list[EvalLog]:
    """Retry a previously failed evaluation task.

    Args:
        tasks: Log files for task(s) to retry.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
            "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript: Level for logging to the log file (defaults to "info")
        log_dir: Output path for logging results
            (defaults to file log in ./logs directory).
        log_format: Format for writing log files (defaults
            to "eval", the native high-performance format).
        max_samples: Maximum number of samples to run in parallel
            (default is max_connections)
        max_tasks: Maximum number of tasks to run in parallel
            (defaults to number of models being evaluated)
        max_subprocesses: Maximum number of subprocesses to
            run in parallel (default is os.cpu_count())
        max_sandboxes: Maximum number of sandboxes (per-provider)
            to run in parallel.
        sandbox_cleanup: Cleanup sandbox environments after task completes
            (defaults to True)
        trace: Trace message interactions with evaluated model to terminal.
        display: Task display type (defaults to 'full').
        fail_on_error: `True` to fail on first sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail
            eval if a count of samples fails.
        retry_on_error: Number of times to retry samples if they encounter errors
            (by default, no retries occur).
        debug_errors: Raise task errors (rather than logging them)
            so they can be debugged (defaults to False).
        log_samples: Log detailed samples and scores (defaults to True)
        log_realtime: Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.
        log_images: Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to False)
        log_buffer: Number of samples to buffer before writing log file.
            If not specified, an appropriate default for the format and filesystem is
            chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Sync sample events to log directory so that users on other systems
            can see log updates in realtime (defaults to no syncing). Specify `True`
            to sync every 10 seconds, otherwise an integer to sync every `n` seconds.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        max_retries:
            Maximum number of times to retry request.
        timeout:
            Request timeout (in seconds)
        max_connections:
            Maximum number of concurrent connections to Model API (default is per Model API)

    Returns:
        List of EvalLog (one for each task)
    """
    # standard platform init for top level entry points
    platform_init()

    # resolve eval trace
    max_tasks, max_samples = init_eval_display(display, trace, max_tasks, max_samples)

    async def run_task_app() -> list[EvalLog]:
        return await eval_retry_async(
            tasks=tasks,
            log_level=log_level,
            log_level_transcript=log_level_transcript,
            log_dir=log_dir,
            log_format=log_format,
            max_samples=max_samples,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            max_sandboxes=max_sandboxes,
            sandbox_cleanup=sandbox_cleanup,
            fail_on_error=fail_on_error,
            retry_on_error=retry_on_error,
            debug_errors=debug_errors,
            log_samples=log_samples,
            log_realtime=log_realtime,
            log_images=log_images,
            log_buffer=log_buffer,
            log_shared=log_shared,
            score=score,
            score_display=score_display,
            max_retries=max_retries,
            timeout=timeout,
            max_connections=max_connections,
        )

    return task_display().run_task_app(run_task_app)


async def eval_retry_async(
    tasks: str | EvalLogInfo | EvalLog | list[str] | list[EvalLogInfo] | list[EvalLog],
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    sandbox_cleanup: bool | None = None,
    fail_on_error: bool | float | None = None,
    retry_on_error: int | None = None,
    debug_errors: bool | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    max_retries: int | None = None,
    timeout: int | None = None,
    max_connections: int | None = None,
) -> list[EvalLog]:
    """Retry a previously failed evaluation task.

    Args:
        tasks: Log files for task(s) to retry.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript: Level for logging to the log file (defaults to "info")
        log_dir: Output path for logging results (defaults to file log in ./logs directory).
        log_format: Format for writing log files (defaults to "eval", the native high-performance format).
        max_samples: Maximum number of samples to run in parallel
           (default is max_connections)
        max_tasks: Maximum number of tasks to run in parallel (default is 1)
        max_subprocesses: Maximum number of subprocesses to run in parallel (default is os.cpu_count())
        max_sandboxes: Maximum number of sandboxes (per-provider) to run in parallel.
        sandbox_cleanup: Cleanup sandbox environments after task completes
           (defaults to True)
        fail_on_error: `True` to fail on first sample error
           (default); `False` to never fail on sample errors; Value between 0 and 1
           to fail if a proportion of total samples fails. Value greater than 1 to fail
           eval if a count of samples fails.
        retry_on_error: Number of times to retry samples if they encounter errors
           (by default, no retries occur).
        debug_errors: Raise task errors (rather than logging them)
           so they can be debugged (defaults to False).
        log_samples: Log detailed samples and scores (defaults to True)
        log_realtime: Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.
        log_images: Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to False)
        log_buffer: Number of samples to buffer before writing log file.
           If not specified, an appropriate default for the format and filesystem is
           chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Indicate that the log directory is shared, which results in
            additional syncing of realtime log data for Inspect View.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        max_retries: Maximum number of times to retry request.
        timeout: Request timeout (in seconds)
        max_connections: Maximum number of concurrent connections to Model API (default is per Model API)

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
                await read_eval_log_async(task.name)
                if isinstance(task, EvalLogInfo)
                else await read_eval_log_async(task)
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
        task_name = eval_log.eval.task_registry_name or eval_log.eval.task
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

        # resolve the model
        model = get_model(
            model=eval_log.eval.model,
            config=eval_log.eval.model_generate_config,
            base_url=eval_log.eval.model_base_url,
            **eval_log.eval.model_args,
        )

        # resolve model roles
        model_roles = model_roles_config_to_model_roles(eval_log.eval.model_roles)

        # collect the rest of the params we need for the eval
        task_args = eval_log.eval.task_args
        tags = eval_log.eval.tags
        limit = eval_log.eval.config.limit
        sample_id = eval_log.eval.config.sample_id
        epochs = (
            Epochs(eval_log.eval.config.epochs, eval_log.eval.config.epochs_reducer)
            if eval_log.eval.config.epochs
            else None
        )
        approval = eval_log.eval.config.approval
        message_limit = eval_log.eval.config.message_limit
        token_limit = eval_log.eval.config.token_limit
        time_limit = eval_log.eval.config.time_limit
        working_limit = eval_log.eval.config.working_limit
        max_samples = max_samples or eval_log.eval.config.max_samples
        max_tasks = max_tasks or eval_log.eval.config.max_tasks
        max_subprocesses = max_subprocesses or eval_log.eval.config.max_subprocesses
        max_sandboxes = max_sandboxes or eval_log.eval.config.max_sandboxes
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
        retry_on_error = (
            retry_on_error
            if retry_on_error is not None
            else eval_log.eval.config.retry_on_error
        )
        log_samples = (
            log_samples if log_samples is not None else eval_log.eval.config.log_samples
        )
        log_realtime = (
            log_realtime
            if log_realtime is not None
            else eval_log.eval.config.log_realtime
        )
        log_images = (
            log_images if log_images is not None else eval_log.eval.config.log_images
        )
        log_buffer = (
            log_buffer if log_buffer is not None else eval_log.eval.config.log_buffer
        )
        log_shared = (
            log_shared if log_shared is not None else eval_log.eval.config.log_shared
        )
        score_display = (
            score_display
            if score_display is not None
            else eval_log.eval.config.score_display
        )

        config = eval_log.plan.config
        config.max_retries = max_retries or config.max_retries
        config.timeout = timeout or config.timeout
        config.max_connections = max_connections or config.max_connections

        # run the eval
        log = (
            await eval_async(
                tasks=PreviousTask(
                    id=task_id,
                    task=task,
                    task_args=task_args,
                    model=None,
                    model_roles=None,
                    log=eval_log,
                ),
                model=model,
                model_roles=cast(dict[str, str | Model], model_roles),
                task_args=task_args,
                sandbox=eval_log.eval.sandbox,
                sandbox_cleanup=sandbox_cleanup,
                solver=solver,
                tags=tags,
                approval=approval,
                log_level=log_level,
                log_level_transcript=log_level_transcript,
                log_dir=log_dir,
                log_format=log_format,
                limit=limit,
                sample_id=sample_id,
                epochs=epochs,
                fail_on_error=fail_on_error,
                retry_on_error=retry_on_error,
                debug_errors=debug_errors,
                message_limit=message_limit,
                token_limit=token_limit,
                time_limit=time_limit,
                working_limit=working_limit,
                max_samples=max_samples,
                max_tasks=max_tasks,
                max_subprocesses=max_subprocesses,
                max_sandboxes=max_sandboxes,
                log_samples=log_samples,
                log_realtime=log_realtime,
                log_images=log_images,
                log_buffer=log_buffer,
                log_shared=log_shared,
                score=score,
                score_display=score_display,
                **dict(config),
            )
        )[0]

        # add it to our results
        eval_logs.append(log)

    return EvalLogs(eval_logs)


def eval_init(
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    max_subprocesses: int | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[Model]:
    # init eval context
    init_eval_context(log_level, log_level_transcript, max_subprocesses)

    # resolve model and task args
    model_args = resolve_args(model_args)

    # resolve model args from environment if not specified
    if len(model_args) == 0:
        env_model_args = os.environ.get("INSPECT_EVAL_MODEL_ARGS", None)
        if env_model_args:
            args = [arg.strip() for arg in env_model_args.split(" ")]
            model_args = parse_cli_args(args)

    # resolve and return models
    generate_config = GenerateConfig(**kwargs)
    models = resolve_models(model, model_base_url, model_args, generate_config)
    return models


def eval_resolve_tasks(
    tasks: Tasks,
    task_args: dict[str, Any] | str,
    models: list[Model],
    model_roles: dict[str, str | Model] | None,
    config: GenerateConfig,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None,
    sandbox: SandboxEnvironmentType | None,
) -> tuple[list[ResolvedTask], list[ApprovalPolicy] | None]:
    resolved_model_roles = resolve_model_roles(model_roles)
    task_args = resolve_args(task_args)
    with task_display().suspend_task_app():
        resolved_tasks: list[ResolvedTask] = []
        for m in models:
            init_active_model(m, config)
            resolved_tasks.extend(
                resolve_tasks(tasks, task_args, m, resolved_model_roles, sandbox)
            )

    if isinstance(approval, str | ApprovalPolicyConfig):
        approval = approval_policies_from_config(approval)
    init_tool_approval(approval)

    # return tasks and approval
    return resolved_tasks, approval


def init_eval_display(
    display: DisplayType | None,
    trace: bool | None,
    max_tasks: int | None,
    max_samples: int | None,
    model: Any = None,
) -> tuple[int | None, int | None]:
    # propagate any trace value to display_type
    if trace:
        warn_once(
            log,
            "WARNING: The --trace flag is deprecated (use --display=conversation instead)",
        )
        display = "conversation"

    # apply default and init
    display = display or display_type()
    init_display_type(display)

    # adapt task/samples as required if we are in conversation mode
    if display_type() == "conversation":
        # single task at a time
        if max_tasks is not None:
            max_tasks = 1

        # single sample at a time
        max_samples = 1

        # multiple models not allowed in trace mode
        if isinstance(model, list) and len(model) > 1:
            raise PrerequisiteError(
                "Conversation mode cannot be used when evaluating multiple models."
            )

    return max_tasks, max_samples


# A list of eval logs is returned from eval(). We've already displayed
# all of the output we need to to though, so we make the return
# value 'invisible'
class EvalLogs(list[EvalLog]):
    def _ipython_display_(self) -> None:
        pass

    def __repr__(self) -> str:
        return ""
