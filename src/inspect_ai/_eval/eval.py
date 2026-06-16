import contextlib
import logging
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Literal, cast

import anyio
from anyio.abc import TaskGroup

from inspect_ai._control.eval_state import clear_all_eval_states
from inspect_ai._control.server import (
    control_server,
    keep_alive_requested,
    release_requested,
    request_keep_alive,
    reset_keep_alive_requested,
    reset_release_requested,
    resolve_ctl_server,
    wait_for_shutdown_async,
)
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai.agent._acp.server import acp_server as _acp_server
from inspect_ai.agent._agent import Agent, is_agent
from inspect_ai.agent._as_solver import as_solver
from inspect_ai.model._model_config import model_roles_config_to_model_roles
from inspect_ai.model._model_data.model_data import ModelCost
from inspect_ai.model._model_info import set_model_cost
from inspect_ai.model._util import resolve_model_costs, resolve_model_roles
from inspect_ai.util._anyio import inner_exception

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

from shortuuid import uuid
from typing_extensions import Unpack

from inspect_ai._cli.util import parse_cli_args
from inspect_ai._display.core.active import active_display as active_task_display
from inspect_ai._display.core.active import display as task_display
from inspect_ai._eval.task.scan import Scanners, scan_context
from inspect_ai._util.asyncfiles import with_async_fs
from inspect_ai._util.config import resolve_args
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_LOG_FORMAT,
    DEFAULT_LOG_SHARED,
    JSON_LOG_FORMAT,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import absolute_file_path, filesystem
from inspect_ai._util.log_context import set_run_shape
from inspect_ai._util.logger import warn_once
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_lookup, registry_package_name
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
from inspect_ai.model._model import (
    get_model,
    init_active_model,
    init_model_roles,
    resolve_models,
)
from inspect_ai.scorer._reducer import reducer_log_names
from inspect_ai.solver._chain import chain
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util import SandboxEnvironmentType
from inspect_ai.util._checkpoint import CheckpointConfig, normalize_checkpoint
from inspect_ai.util._concurrency import AdaptiveConcurrency
from inspect_ai.util._display import (
    DisplayType,
    display_type,
    display_type_initialized,
    init_display_type,
)
from inspect_ai.util._notify import build_apprise, init_apprise

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
    checkpoint: CheckpointConfig | bool | None = None,
    acp_server: bool | int | str | None = None,
    ctl_server: bool | str | None = None,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = None,
    scanner: "Scanners | None" = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace: bool | None = None,
    display: DisplayType | None = None,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = None,
    notification: bool | str | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    sample_shuffle: bool | int | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    continue_on_fail: bool | None = None,
    retry_on_error: int | None = None,
    score_on_error: bool | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    cost_limit: float | None = None,
    model_cost_config: str | dict[str, ModelCost] | None = None,
    max_samples: int | None = None,
    max_dataset_memory: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_model_api: bool | None = None,
    log_refusals: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    log_header_only: bool | None = None,
    run_samples: bool = True,
    score: bool = True,
    score_display: bool | None = None,
    eval_set_id: str | None = None,
    scan_id: str | None = None,
    task_retry_attempts: int | None = None,
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
        checkpoint: Checkpoint configuration for this eval, or `True` to
            enable checkpointing with the default trigger (every 500k
            tokens) — equivalent to the bare `--checkpoint` CLI flag.
            Overrides any task- or sample-level `checkpoint` when set.
        acp_server: Expose this eval over an Agent Client Protocol server.
            `True` enables a default AF_UNIX socket at `<inspect_data_dir>/acp/<run_id>.sock`;
            an integer binds a TCP loopback port; a string is taken as a custom
            UNIX socket path; `None` (default) does not start an ACP server.
        ctl_server: Control-channel server for this eval process.
            `True` or `None` (default) binds the default AF_UNIX socket;
            `False` disables the control endpoint; `"keep"` additionally
            keeps the process running after the eval finishes so external
            clients can still query its state — exit via `inspect ctl release`
            (or `POST /release`).
        solver: Alternative solver for task(s).
            Optional (uses task solver by default).
        scanner: Scanner(s) to apply to each sample's transcript after the
            sample completes.
        tags: Tags to associate with this evaluation run.
        metadata: Metadata to associate with this evaluation run.
        trace: Trace message interactions with evaluated model to terminal.
        display: Task display type (defaults to 'full').
        approval: Tool use approval policies.
            Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies.
            Defaults to no approval policy.
        notification: Enable out-of-band notifications when a human-in-the-loop
            interaction (`ask_user`, human approval) is posted. Pass `True` to
            send via the URL(s) in the `INSPECT_EVAL_NOTIFICATION` environment
            variable (single URL, comma-separated list, or path to an Apprise
            config file). Alternatively pass a path to an Apprise YAML/text
            config file. URLs are not accepted directly so secrets never end up
            in source code, shell history, process listings, or eval logs.
            Requires the `apprise` package.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
            "info", "warning", "error", "critical", or "notset" (defaults to "warning")
        log_level_transcript: Level for logging to the log file (defaults to "info")
        log_dir: Output path for logging results
            (defaults to file log in ./logs directory).
        log_format: Format for writing log files (defaults
            to "eval", the native high-performance format).
        limit: Limit evaluated samples
            (defaults to all samples).
        sample_id: Evaluate specific sample(s) from the dataset. Use plain ids or preface with task names as required to disambiguate ids across tasks (e.g. `popularity:10`)..
        sample_shuffle: Shuffle order of samples (pass a seed to make the order deterministic).
        epochs: Epochs to repeat samples for and optional score
            reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error: `True` to fail on first sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail
            eval if a count of samples fails.
        continue_on_fail: `True` to continue running and only fail at the end if the `fail_on_error` condition is met.
            `False` to fail eval immediately when the `fail_on_error` condition is met (default).
        retry_on_error: Number of times to retry samples if they encounter errors
            (by default, no retries occur).
        score_on_error: Score samples that error rather than failing the eval mid-run.
            Errors still count toward the `fail_on_error` threshold for marking the eval
            log as 'error'. Only takes effect after retries (if any) are exhausted.
        debug_errors: Raise task errors (rather than logging them)
            so they can be debugged (defaults to False).
        message_limit: Limit on total messages used for each sample.
        token_limit: Limit on total tokens used for each sample.
        time_limit: Limit on clock time (in seconds) for samples.
        working_limit: Limit on working time (in seconds) for sample. Working
            time includes model generation, tool calls, etc. but does not include
            time spent waiting on retries or shared resources.
        cost_limit: Limit on total cost (in dollars) for each sample.
            Requires model cost data via set_model_cost() or --model-cost-config.
        model_cost_config: YAML or JSON file with model prices for cost tracking
            or dict of model -> `ModelCost`
        max_samples: Maximum number of samples to run in parallel
            (default is max_connections)
        max_dataset_memory: Maximum MB of dataset sample data to hold in
            memory per task. When exceeded, samples are paged to a temporary
            file on disk (defaults to None, which keeps all samples in memory).
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
        log_model_api: Log raw model api requests and responses. True logs all calls, False logs only errors, None (default) logs the first few calls per model plus errors.
        log_refusals: Log warnings for model refusals.
        log_buffer: Number of samples to buffer before writing log file.
            If not specified, an appropriate default for the format and filesystem is
            chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Sync sample events to log directory so that users on other systems
            can see log updates in realtime (defaults to no syncing). Specify `True`
            to sync every 10 seconds, otherwise an integer to sync every `n` seconds.
        log_header_only: If `True`, the function should return only log headers rather
            than full logs with samples (defaults to `False`).
        run_samples: Run samples. If `False`, a log with `status=="started"` and an
            empty `samples` list is returned.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        eval_set_id: Unique id for eval set (this is passed from `eval_set()` and should not be specified directly).
        scan_id: Override the scan-dir identifier (defaults to `eval_set_id` or `run_id`). Set by `eval_retry` to reuse the original eval's scan dir.
        task_retry_attempts: Number of times to retry tasks (defaults to 0)
        **kwargs: Model generation options.

    Returns:
        List of EvalLog (one for each task)
    """
    # standard platform init for top level entry points
    platform_init()

    # resolve eval trace
    max_tasks, max_samples = init_eval_display(
        display, trace, max_tasks, max_samples, model, run_samples
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
                checkpoint=checkpoint,
                solver=solver,
                scanner=scanner,
                tags=tags,
                metadata=metadata,
                approval=approval,
                notification=notification,
                log_level=log_level,
                log_level_transcript=log_level_transcript,
                log_dir=log_dir,
                log_format=log_format,
                limit=limit,
                sample_id=sample_id,
                sample_shuffle=sample_shuffle,
                epochs=epochs,
                fail_on_error=fail_on_error,
                continue_on_fail=continue_on_fail,
                retry_on_error=retry_on_error,
                score_on_error=score_on_error,
                debug_errors=debug_errors,
                message_limit=message_limit,
                token_limit=token_limit,
                time_limit=time_limit,
                working_limit=working_limit,
                cost_limit=cost_limit,
                model_cost_config=model_cost_config,
                max_samples=max_samples,
                max_dataset_memory=max_dataset_memory,
                max_tasks=max_tasks,
                max_subprocesses=max_subprocesses,
                max_sandboxes=max_sandboxes,
                log_samples=log_samples,
                log_realtime=log_realtime,
                log_images=log_images,
                log_model_api=log_model_api,
                log_refusals=log_refusals,
                log_buffer=log_buffer,
                log_shared=log_shared,
                log_header_only=log_header_only,
                run_samples=run_samples,
                score=score,
                score_display=score_display,
                acp_server=acp_server,
                ctl_server=ctl_server,
                eval_set_id=eval_set_id,
                scan_id=scan_id,
                task_retry_attempts=task_retry_attempts,
                **kwargs,
            )
        # exceptions can escape when debug_errors is True and that's okay
        except ExceptionGroup as ex:
            if debug_errors:
                raise ex.exceptions[0] from None
            else:
                raise

    result = task_display().run_task_app(with_async_fs(run_task_app))

    # print scan status after the task display has exited so the
    # message lands AFTER the panel + `Log:` line. Only when eval owns
    # the scan lifecycle (standalone call, not nested in eval_set).
    if scanner is not None and eval_set_id is None:
        from inspect_ai._eval.task.scan import print_scan_status

        resolved_log_dir = absolute_file_path(
            log_dir if log_dir else os.environ.get("INSPECT_LOG_DIR", "./logs")
        )
        print_scan_status(resolved_log_dir, scanner)

    return result


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
    checkpoint: CheckpointConfig | bool | None = None,
    acp_server: bool | int | str | None = None,
    ctl_server: bool | str | None = None,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = None,
    scanner: "Scanners | None" = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = None,
    notification: bool | str | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    sample_shuffle: bool | int | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    continue_on_fail: bool | None = None,
    retry_on_error: int | None = None,
    score_on_error: bool | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    cost_limit: float | None = None,
    model_cost_config: str | dict[str, ModelCost] | None = None,
    max_samples: int | None = None,
    max_dataset_memory: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_model_api: bool | None = None,
    log_refusals: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    log_header_only: bool | None = None,
    run_samples: bool = True,
    score: bool = True,
    score_display: bool | None = None,
    eval_set_id: str | None = None,
    scan_id: str | None = None,
    task_retry_attempts: int | None = None,
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
        checkpoint: Checkpoint configuration for this eval, or `True` to enable checkpointing with the default trigger (every 500k tokens), equivalent to the bare `--checkpoint` CLI flag. Overrides any task- or sample-level `checkpoint` when set.
        acp_server: Expose this eval over an Agent Client Protocol server.
            `True` enables a default AF_UNIX socket at `<inspect_data_dir>/acp/<run_id>.sock`;
            an integer binds a TCP loopback port; a string is taken as a custom
            UNIX socket path; `None` (default) does not start an ACP server.
        ctl_server: Control-channel server for this eval process.
            `True` or `None` (default) binds the default AF_UNIX socket;
            `False` disables the control endpoint; `"keep"` additionally
            keeps the process running after the eval finishes so external
            clients can still query its state — exit via `inspect ctl release`
            (or `POST /release`).
        solver: Alternative solver for task(s).  Optional (uses task solver by default).
        scanner: Scanner(s) to apply to each sample's transcript after the sample completes.
        tags: Tags to associate with this evaluation run.
        metadata: Metadata to associate with this evaluation run.
        approval: Tool use approval policies.
            Either a path to an approval policy config file, an ApprovalPolicyConfig, or a list of approval policies.
            Defaults to no approval policy.
        notification: Enable out-of-band notifications when a human-in-the-loop
            interaction (`ask_user`, human approval) is posted. Pass `True` to
            send via the URL(s) in the `INSPECT_EVAL_NOTIFICATION` environment
            variable (single URL, comma-separated list, or path to an Apprise
            config file). Alternatively pass a path to an Apprise YAML/text
            config file. URLs are not accepted directly so secrets never end up
            in source code, shell history, process listings, or eval logs.
            Requires the `apprise` package.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
            "info", "warning", "error", "critical", or "notset" (defaults to "warning")
        log_level_transcript: Level for logging to the log file (defaults to "info")
        log_dir: Output path for logging results (defaults to file log in ./logs directory).
        log_format: Format for writing log files (defaults to "eval", the native high-performance format).
        limit: Limit evaluated samples (defaults to all samples).
        sample_id: Evaluate specific sample(s) from the dataset. Use plain ids or preface with task names as required to disambiguate ids across tasks (e.g. `popularity:10`).
        sample_shuffle: Shuffle order of samples (pass a seed to make the order deterministic).
        epochs: Epochs to repeat samples for and optional score
            reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error: `True` to fail on first sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail eval if a count of samples fails.
        continue_on_fail: `True` to continue running and only fail at the end if the `fail_on_error` condition is met.
            `False` to fail eval immediately when the `fail_on_error` condition is met (default).
        retry_on_error: Number of times to retry samples if they encounter errors
            (by default, no retries occur).
        score_on_error: Score samples that error rather than failing the eval mid-run.
            Errors still count toward the `fail_on_error` threshold for marking the eval
            log as 'error'. Only takes effect after retries (if any) are exhausted.
        debug_errors: Raise task errors (rather than logging them) so they can be debugged (defaults to False).
        message_limit: Limit on total messages used for each sample.
        token_limit: Limit on total tokens used for each sample.
        time_limit: Limit on clock time (in seconds) for samples.
        working_limit: Limit on working time (in seconds) for sample. Working
            time includes model generation, tool calls, etc. but does not include
            time spent waiting on retries or shared resources.
        cost_limit: Limit on total cost (in dollars) for each sample.
            Requires model cost data via set_model_cost() or --model-cost-config.
        model_cost_config: YAML or JSON file with model prices for cost tracking
            or dict of model -> `ModelCost`
        max_samples: Maximum number of samples to run in parallel (default is max_connections)
        max_dataset_memory: Maximum MB of dataset sample data to hold in
            memory per task. When exceeded, samples are paged to a temporary
            file on disk (defaults to None, which keeps all samples in memory).
        max_tasks: Maximum number of tasks to run in parallel
            (defaults to number of models being evaluated)
        max_subprocesses: Maximum number of subprocesses to run in parallel (default is os.cpu_count())
        max_sandboxes: Maximum number of sandboxes (per-provider) to run in parallel.
        log_samples: Log detailed samples and scores (defaults to True)
        log_realtime: Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.
        log_images: Log base64 encoded version of images, even if specified as a filename or URL (defaults to False)
        log_model_api: Log raw model api requests and responses. True logs all calls, False logs only errors, None (default) logs the first few calls per model plus errors.
        log_refusals: Log warnings for model refusals.
        log_buffer: Number of samples to buffer before writing log file.
            If not specified, an appropriate default for the format and filesystem is
            chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Indicate that the log directory is shared, which results in additional syncing of realtime log data for Inspect View.
        log_header_only: If `True`, the function should return only log headers rather than full logs with samples (defaults to `False`).
        run_samples: Run samples. If `False`, a log with `status=="started"` and an empty `samples` list is returned.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        eval_set_id: Unique id for eval set (this is passed from `eval_set()` and should not be specified directly).
        scan_id: Override the scan-dir identifier (defaults to `eval_set_id` or `run_id`). Set by `eval_retry` to reuse the original eval's scan dir.
        task_retry_attempts: Number of times to retry tasks (defaults to 0)
        **kwargs: Model generation options.

    Returns:
        List of EvalLog (one for each task)
    """
    # normalize `checkpoint=True` (enable, defer trigger) to a config;
    # this is the single choke point for the eval layer — `eval`,
    # `eval_set`, `eval_retry`, and `eval_retry_async` all funnel here.
    checkpoint = normalize_checkpoint(checkpoint)

    # validate ctl_server here too (it's resolved where it's consumed, at the
    # control-server bind inside the run) so a bad value fails fast as an
    # argument error rather than after models, tasks, and run-start hooks
    # have already initialized
    resolve_ctl_server(ctl_server)

    # clear any release latch left by a prior run in this process (we run
    # before this run's control server binds, so a release received during
    # the run still latches)
    reset_release_requested()
    # Likewise clear a stale keep-alive latch — but only for a standalone
    # eval. When nested in an eval-set (eval_set_id set), eval_set() owns the
    # latch: it sets it BEFORE this inner eval() runs to advertise the
    # impending park, so resetting here would erase that intent.
    if eval_set_id is None:
        reset_keep_alive_requested()

    result: list[EvalLog] | None = None

    async def run(tg: TaskGroup) -> None:
        try:
            nonlocal result
            result = await _eval_async_inner(
                tg=tg,
                tasks=tasks,
                model=model,
                model_base_url=model_base_url,
                model_args=model_args,
                model_roles=model_roles,
                task_args=task_args,
                sandbox=sandbox,
                sandbox_cleanup=sandbox_cleanup,
                checkpoint=checkpoint,
                solver=solver,
                scanner=scanner,
                tags=tags,
                metadata=metadata,
                approval=approval,
                notification=notification,
                log_level=log_level,
                log_level_transcript=log_level_transcript,
                log_dir=log_dir,
                log_format=log_format,
                limit=limit,
                sample_id=sample_id,
                sample_shuffle=sample_shuffle,
                epochs=epochs,
                fail_on_error=fail_on_error,
                continue_on_fail=continue_on_fail,
                retry_on_error=retry_on_error,
                score_on_error=score_on_error,
                debug_errors=debug_errors,
                message_limit=message_limit,
                token_limit=token_limit,
                time_limit=time_limit,
                working_limit=working_limit,
                cost_limit=cost_limit,
                model_cost_config=model_cost_config,
                max_samples=max_samples,
                max_dataset_memory=max_dataset_memory,
                max_tasks=max_tasks,
                max_subprocesses=max_subprocesses,
                max_sandboxes=max_sandboxes,
                log_samples=log_samples,
                log_realtime=log_realtime,
                log_images=log_images,
                log_model_api=log_model_api,
                log_refusals=log_refusals,
                log_buffer=log_buffer,
                log_shared=log_shared,
                log_header_only=log_header_only,
                run_samples=run_samples,
                score=score,
                score_display=score_display,
                acp_server=acp_server,
                ctl_server=ctl_server,
                eval_set_id=eval_set_id,
                scan_id=scan_id,
                task_retry_attempts=task_retry_attempts,
                **kwargs,
            )
        finally:
            tg.cancel_scope.cancel()

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(run, tg)
    except Exception as ex:
        raise inner_exception(ex)
    except anyio.get_cancelled_exc_class():
        # Cancelled exceptions are expected and handled by _eval_async_inner
        if result is None:
            raise

    assert result is not None, "Eval async did not return a result."

    return result


async def _eval_async_inner(
    tg: TaskGroup,
    tasks: Tasks,
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    model_roles: dict[str, str | Model] | None = None,
    task_args: dict[str, Any] | str = dict(),
    sandbox: SandboxEnvironmentType | None = None,
    sandbox_cleanup: bool | None = None,
    checkpoint: CheckpointConfig | None = None,
    acp_server: bool | int | str | None = None,
    ctl_server: bool | str | None = None,
    solver: Solver | SolverSpec | Agent | list[Solver] | None = None,
    scanner: "Scanners | None" = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    approval: str | list[ApprovalPolicy] | ApprovalPolicyConfig | None = None,
    notification: bool | str | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_dir: str | None = None,
    log_format: Literal["eval", "json"] | None = None,
    limit: int | tuple[int, int] | None = None,
    sample_id: str | int | list[str] | list[int] | list[str | int] | None = None,
    sample_shuffle: bool | int | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    continue_on_fail: bool | None = None,
    retry_on_error: int | None = None,
    score_on_error: bool | None = None,
    debug_errors: bool | None = None,
    message_limit: int | None = None,
    token_limit: int | None = None,
    time_limit: int | None = None,
    working_limit: int | None = None,
    cost_limit: float | None = None,
    model_cost_config: str | dict[str, ModelCost] | None = None,
    max_samples: int | None = None,
    max_dataset_memory: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    max_sandboxes: int | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_model_api: bool | None = None,
    log_refusals: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    log_header_only: bool | None = None,
    run_samples: bool = True,
    score: bool = True,
    score_display: bool | None = None,
    eval_set_id: str | None = None,
    scan_id: str | None = None,
    task_retry_attempts: int | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    from inspect_ai.hooks._hooks import emit_run_end, emit_run_start

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

    # apply model cost config
    if isinstance(model_cost_config, str):
        cost_data = resolve_args(model_cost_config)
        for cost_model_name, cost in cost_data.items():
            set_model_cost(cost_model_name, ModelCost(**cost))
    elif isinstance(model_cost_config, dict):
        for k, v in model_cost_config.items():
            set_model_cost(k, v)

    run_id = uuid()

    try:
        # intialise eval
        model = eval_init(
            model=model,
            model_base_url=model_base_url,
            model_args=model_args,
            max_subprocesses=max_subprocesses,
            log_level=log_level,
            log_level_transcript=log_level_transcript,
            log_refusals=log_refusals,
            task_group=tg,
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
            sample_shuffle,
            checkpoint,
            notification,
        )

        # warn and return empty string if we resolved no tasks
        if len(resolved_tasks) == 0:
            raise PrerequisiteError(
                "Error: No inspect tasks were found at the specified paths."
            )

        resolve_model_costs(resolved_tasks, cost_limit)

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

        # resolve header only
        log_header_only = log_header_only is True

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

        # ensure consistency of limit and sample_id/sample_shuffe
        if sample_id is not None and limit is not None:
            raise ValueError("You cannot specify both sample_id and limit.")
        if sample_id is not None and sample_shuffle is not None:
            raise ValueError("You cannot specify both sample_id and sample_shuffle")

        # resolve epochs
        if isinstance(epochs, int):
            epochs = Epochs(epochs)
        if epochs is not None and epochs.epochs < 1:
            raise ValueError("epochs must be a positive integer.")

        # resolve log_model_api from env var if not explicitly set
        if log_model_api is None:
            log_model_api_env = os.environ.get("INSPECT_EVAL_LOG_MODEL_API")
            if log_model_api_env is not None:
                log_model_api = log_model_api_env.lower() in ("true", "1", "yes")

        # create config
        epochs_reducer = epochs.reducer if epochs else None
        eval_config = EvalConfig(
            limit=limit,
            sample_id=sample_id,
            sample_shuffle=sample_shuffle,
            epochs=epochs.epochs if epochs else None,
            epochs_reducer=reducer_log_names(epochs_reducer)
            if epochs_reducer is not None
            else None,
            approval=config_from_approval_policies(approval) if approval else None,
            notification=notification,
            fail_on_error=fail_on_error,
            continue_on_fail=continue_on_fail,
            retry_on_error=retry_on_error,
            score_on_error=score_on_error,
            message_limit=message_limit,
            token_limit=token_limit,
            cost_limit=cost_limit,
            time_limit=time_limit,
            working_limit=working_limit,
            max_samples=max_samples,
            max_dataset_memory=max_dataset_memory,
            max_tasks=max_tasks,
            max_subprocesses=max_subprocesses,
            max_sandboxes=max_sandboxes,
            sandbox_cleanup=sandbox_cleanup,
            log_samples=log_samples,
            log_realtime=log_realtime,
            log_images=log_images,
            log_model_api=log_model_api,
            log_buffer=log_buffer,
            log_shared=log_shared,
            score_display=score_display,
            acp_server=acp_server,
        )

        # run tasks - 2 codepaths, one for the traditional task at a time
        # (w/ optional multiple models) and the other for true multi-task
        # (which requires different scheduling and UI)
        task_definitions = len(resolved_tasks) // len(model)
        parallel = 1 if (task_definitions == 1 or max_tasks is None) else max_tasks

        # set run shape for log record enhancement
        if eval_config.epochs is not None:
            run_max_epochs = eval_config.epochs
        else:
            run_max_epochs = max(
                (t.task.epochs or DEFAULT_EPOCHS for t in resolved_tasks),
                default=DEFAULT_EPOCHS,
            )
        set_run_shape(
            (t.task.name for t in resolved_tasks),
            run_max_epochs,
        )
        await emit_run_start(eval_set_id, run_id, resolved_tasks)

        # scan_id is whichever the caller passed explicitly (e.g. eval_retry
        # forwards the prior log's scan_id so the scan dir is reused), else
        # the eval_set_id (when nested inside `eval_set`), else this run's
        # uuid for a standalone eval. eval_set already wraps the run loop
        # in scan_context, so skip the wrap here when eval_set_id is set
        # to avoid double init/finalize.
        scan_id = scan_id or eval_set_id or run_id
        if scanner is not None and eval_set_id is None:
            scan_cm: contextlib.AbstractContextManager[None] = scan_context(
                scanner, scan_id=scan_id, log_dir=log_dir
            )
        else:
            scan_cm = contextlib.nullcontext()

        # Stand up the optional ACP server for this eval's run_id. When
        # `acp_server` (the EvalConfig field / CLI flag value) is falsy
        # the context manager yields None and binds nothing. The server
        # lives for the duration of the eval_run loop so any agent that
        # opens an `acp_session()` can be reached by external clients
        # via the discovery file in `<inspect_data_dir>/acp/`. Nested
        # rather than parenthesized because ``scan_cm`` is a sync
        # context manager and Python disallows mixing in the comma form.
        #
        # The control channel HTTP server is default-on (unlike ACP,
        # which is opt-in; disable with ctl_server=False). It exposes
        # live-eval read / direct / event-subscription operations to
        # `inspect ctl` CLI clients, TUIs, and agents. Bind failures are
        # logged and swallowed — eval correctness never depends on the
        # control channel coming up. See design/control-channel.md
        # "Implementation notes".
        #
        ctl = resolve_ctl_server(ctl_server)
        # Advertise keep-alive via the process-global latch (the single source
        # of truth the control server reports and the park gates on). A runtime
        # `POST /keep` sets the same latch. An eval-set demotes its inner eval()
        # to a plain on/off server and owns the latch itself, so ctl.keep_alive
        # is only ever set here for a standalone eval.
        if ctl.keep_alive:
            request_keep_alive()
        async with (
            control_server(run_id=run_id, enabled=ctl.enabled) as _ctl_server,
            _acp_server(eval_id=run_id, transport=acp_server),
        ):
            with scan_cm:
                # single task definition (could be multi-model) or max_tasks capped to 1
                if parallel == 1:
                    results: list[EvalLog] = []
                    for sequence in sorted(set(t.sequence for t in resolved_tasks)):
                        task_batch = list(
                            filter(lambda t: t.sequence == sequence, resolved_tasks)
                        )
                        results.extend(
                            await eval_run(
                                eval_set_id=eval_set_id,
                                run_id=run_id,
                                tasks=task_batch,
                                parallel=parallel,
                                eval_config=eval_config,
                                eval_sandbox=sandbox,
                                eval_checkpoint=checkpoint,
                                recorder=recorder,
                                header_only=log_header_only,
                                epochs_reducer=epochs_reducer,
                                solver=solver,
                                scanner=scanner,
                                scan_id=scan_id,
                                tags=tags,
                                metadata=metadata,
                                run_samples=run_samples,
                                score=score,
                                debug_errors=debug_errors is True,
                                task_retry_attempts=task_retry_attempts,
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
                        eval_set_id=eval_set_id,
                        run_id=run_id,
                        tasks=resolved_tasks,
                        parallel=parallel,
                        eval_config=eval_config,
                        eval_sandbox=sandbox,
                        eval_checkpoint=checkpoint,
                        recorder=recorder,
                        header_only=log_header_only,
                        epochs_reducer=epochs_reducer,
                        solver=solver,
                        scanner=scanner,
                        scan_id=scan_id,
                        tags=tags,
                        metadata=metadata,
                        run_samples=run_samples,
                        score=score,
                        task_retry_attempts=task_retry_attempts,
                        **kwargs,
                    )
                    logs = EvalLogs(results)

            # keep-alive: after the body, park while the control / ACP
            # servers are still up so `inspect ctl` can read state and
            # request shutdown. (Standalone eval parks here, inside the
            # task display; eval-set instead parks after the display has
            # closed — so this gate is scoped to standalone via eval_set_id.)
            # The latch covers both the launch flag and a runtime `POST /keep`.
            # EvalStates are cleared at the run boundary below. A release
            # received while the eval was still running latches ("exit when
            # done") — skip the park (and its notice) entirely.
            if (
                eval_set_id is None
                and keep_alive_requested()
                and _ctl_server is not None
                and not release_requested()
            ):
                import rich

                rich.get_console().print(
                    "Eval finished. Keeping process alive — press Ctrl+C "
                    "or run `inspect ctl release` to let it exit.",
                    markup=False,
                    highlight=False,
                )
                await wait_for_shutdown_async(_ctl_server)

        # cleanup sample buffers if required
        cleanup_sample_buffers(log_dir)

        try:
            await emit_run_end(eval_set_id, run_id, logs)
        except UnboundLocalError:
            await emit_run_end(eval_set_id, run_id, EvalLogs([]))
        _eval_async_running = False

    except BaseException as e:
        await emit_run_end(eval_set_id, run_id, EvalLogs([]), e)
        _eval_async_running = False
        raise e

    finally:
        # Clear the process-level EvalState registry at the run boundary
        # (after any keep-alive park) — but only for a standalone eval.
        # When nested in an eval-set (eval_set_id set) the eval-set owns
        # this, clearing after its own park.
        if eval_set_id is None:
            clear_all_eval_states()

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
    continue_on_fail: bool | None = None,
    retry_on_error: int | None = None,
    score_on_error: bool | None = None,
    debug_errors: bool | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_model_api: bool | None = None,
    log_refusals: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    acp_server: bool | int | str | None = None,
    ctl_server: bool | str | None = None,
    scanner: "Scanners | None" = None,
    max_retries: int | None = None,
    timeout: int | None = None,
    attempt_timeout: int | None = None,
    max_connections: int | None = None,
    adaptive_connections: bool | int | AdaptiveConcurrency | None = None,
    checkpoint: CheckpointConfig | bool | None = None,
) -> list[EvalLog]:
    """Retry a previously failed evaluation task.

    Args:
        tasks: Log files for task(s) to retry.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
            "info", "warning", "error", "critical", or "notset" (defaults to "warning")
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
        fail_on_error: `True` to fail on a sample error
            (default); `False` to never fail on sample errors; Value between 0 and 1
            to fail if a proportion of total samples fails. Value greater than 1 to fail
            eval if a count of samples fails.
        continue_on_fail: `True` to continue running and only fail at the end if the `fail_on_error` condition is met.
            `False` to fail eval immediately when the `fail_on_error` condition is met (default).
        retry_on_error: Number of times to retry samples if they encounter errors
            (by default, no retries occur).
        score_on_error: Score samples that error rather than failing the eval mid-run.
            Errors still count toward the `fail_on_error` threshold for marking the eval
            log as 'error'. Only takes effect after retries (if any) are exhausted.
        debug_errors: Raise task errors (rather than logging them)
            so they can be debugged (defaults to False).
        log_samples: Log detailed samples and scores (defaults to True)
        log_realtime: Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.
        log_images: Log base64 encoded version of images,
            even if specified as a filename or URL (defaults to False)
        log_model_api: Log raw model api requests and responses. True logs all calls, False logs only errors, None (default) logs the first few calls per model plus errors.
        log_refusals: Log warnings for model refusals.
        log_buffer: Number of samples to buffer before writing log file.
            If not specified, an appropriate default for the format and filesystem is
            chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Sync sample events to log directory so that users on other systems
            can see log updates in realtime (defaults to no syncing). Specify `True`
            to sync every 10 seconds, otherwise an integer to sync every `n` seconds.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        ctl_server: Control-channel server for this eval process.
            `True` or `None` (default) binds the default AF_UNIX socket;
            `False` disables the control endpoint; `"keep"` additionally
            keeps the process running after the eval finishes so external
            clients can still query its state — exit via `inspect ctl release`
            (or `POST /release`).
        acp_server: Override the original eval's ACP server transport on retry.
            `True` enables a default AF_UNIX socket; an integer binds a TCP
            loopback port; a string is taken as a custom UNIX socket path;
            `None` (default) replays whatever transport (or no transport) was
            persisted in the original log's `EvalConfig.acp_server`.
        scanner: Scanner(s) to apply to each sample's transcript after the sample
            completes. When provided, the existing scan dir from the original
            eval (keyed by its `eval_set_id` or `run_id`) is reused — same resume
            contract as `eval_set`: matching scanner config attaches, divergent
            config raises `PrerequisiteError`.
        max_retries:
            Maximum number of times to retry request.
        timeout:
            Request timeout (in seconds)
        attempt_timeout:
            Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries).
        max_connections:
            Maximum number of concurrent connections to Model API (default is per Model API)
        adaptive_connections:
            Adaptive concurrency for Model API connections. Defaults to enabled
            (resolves to `AdaptiveConcurrency()` defaults: min=10, start=20, max=100).
            Pass `False` to opt out (uses static concurrency), an integer `N` as
            shorthand for `AdaptiveConcurrency(max=N)`, or an `AdaptiveConcurrency`
            to fully customize bounds and tuning (cooldown_seconds, decrease_factor,
            scale_up_percent). An explicit `max_connections` or `batch=True`
            takes precedence and uses static concurrency.
        checkpoint:
            Checkpoint configuration for this retry, or `True` to enable
            checkpointing with the default trigger (every 500k tokens).
            Must match the config used on the original eval for resume
            detection to find the checkpoint files (the original
            `--checkpoint` is not recorded in the log file).

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
            continue_on_fail=continue_on_fail,
            retry_on_error=retry_on_error,
            score_on_error=score_on_error,
            debug_errors=debug_errors,
            log_samples=log_samples,
            log_realtime=log_realtime,
            log_images=log_images,
            log_model_api=log_model_api,
            log_refusals=log_refusals,
            log_buffer=log_buffer,
            log_shared=log_shared,
            score=score,
            score_display=score_display,
            acp_server=acp_server,
            ctl_server=ctl_server,
            scanner=scanner,
            max_retries=max_retries,
            timeout=timeout,
            attempt_timeout=attempt_timeout,
            max_connections=max_connections,
            adaptive_connections=adaptive_connections,
            checkpoint=checkpoint,
        )

    result = task_display().run_task_app(with_async_fs(run_task_app))

    # print scan status after the task display has exited so the
    # message lands AFTER the panel + `Log:` line. Matches `eval` /
    # `eval_set`'s trailing summary.
    if scanner is not None:
        from inspect_ai._eval.task.scan import print_scan_status

        resolved_log_dir = absolute_file_path(
            log_dir if log_dir else os.environ.get("INSPECT_LOG_DIR", "./logs")
        )
        print_scan_status(resolved_log_dir, scanner)

    return result


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
    continue_on_fail: bool | None = None,
    retry_on_error: int | None = None,
    score_on_error: bool | None = None,
    debug_errors: bool | None = None,
    log_samples: bool | None = None,
    log_realtime: bool | None = None,
    log_images: bool | None = None,
    log_model_api: bool | None = None,
    log_refusals: bool | None = None,
    log_buffer: int | None = None,
    log_shared: bool | int | None = None,
    score: bool = True,
    score_display: bool | None = None,
    acp_server: bool | int | str | None = None,
    ctl_server: bool | str | None = None,
    scanner: "Scanners | None" = None,
    max_retries: int | None = None,
    timeout: int | None = None,
    attempt_timeout: int | None = None,
    max_connections: int | None = None,
    adaptive_connections: bool | int | AdaptiveConcurrency | None = None,
    checkpoint: CheckpointConfig | bool | None = None,
) -> list[EvalLog]:
    """Retry a previously failed evaluation task.

    Args:
        tasks: Log files for task(s) to retry.
        log_level: Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", "critical", or "notset" (defaults to "warning")
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
        continue_on_fail: `True` to continue running and only fail at the end if the `fail_on_error` condition is met.
            `False` to fail eval immediately when the `fail_on_error` condition is met (default).
        retry_on_error: Number of times to retry samples if they encounter errors
           (by default, no retries occur).
        score_on_error: Score samples that error rather than failing the eval mid-run.
            Errors still count toward the `fail_on_error` threshold for marking the eval
            log as 'error'. Only takes effect after retries (if any) are exhausted.
        debug_errors: Raise task errors (rather than logging them)
           so they can be debugged (defaults to False).
        log_samples: Log detailed samples and scores (defaults to True)
        log_realtime: Log events in realtime (enables live viewing of samples in inspect view). Defaults to True.
        log_images: Log base64 encoded version of images,
           even if specified as a filename or URL (defaults to False)
        log_model_api: Log raw model api requests and responses. True logs all calls, False logs only errors, None (default) logs the first few calls per model plus errors.
        log_refusals: Log warnings for model refusals.
        log_buffer: Number of samples to buffer before writing log file.
           If not specified, an appropriate default for the format and filesystem is
           chosen (10 for most all cases, 100 for JSON logs on remote filesystems).
        log_shared: Indicate that the log directory is shared, which results in
            additional syncing of realtime log data for Inspect View.
        score: Score output (defaults to True)
        score_display: Show scoring metrics in realtime (defaults to True)
        ctl_server: Control-channel server for this eval process.
            `True` or `None` (default) binds the default AF_UNIX socket;
            `False` disables the control endpoint; `"keep"` additionally
            keeps the process running after the eval finishes so external
            clients can still query its state — exit via `inspect ctl release`
            (or `POST /release`).
        acp_server: Override the original eval's ACP server transport on retry.
            `True` enables a default AF_UNIX socket; an integer binds a TCP
            loopback port; a string is taken as a custom UNIX socket path;
            `None` (default) replays whatever transport (or no transport) was
            persisted in the original log's `EvalConfig.acp_server`.
        scanner: Scanner(s) to apply to each sample's transcript after the sample
            completes. When provided, the existing scan dir from the original
            eval (keyed by its `eval_set_id` or `run_id`) is reused — same resume
            contract as `eval_set`: matching scanner config attaches, divergent
            config raises `PrerequisiteError`.
        max_retries: Maximum number of times to retry request.
        timeout: Request timeout (in seconds)
        attempt_timeout: Timeout (in seconds) for any given attempt (if exceeded, will abandon attempt and retry according to max_retries).
        max_connections: Maximum number of concurrent connections to Model API (default is per Model API)
        adaptive_connections: Adaptive concurrency for Model API connections. Defaults to enabled (resolves to `AdaptiveConcurrency()` defaults: min=10, start=20, max=100). Pass `False` to opt out, an integer `N` as shorthand for `AdaptiveConcurrency(max=N)`, or an `AdaptiveConcurrency` to fully customize bounds and tuning (cooldown_seconds, decrease_factor, scale_up_percent). An explicit `max_connections` or `batch=True` takes precedence and uses static concurrency.
        checkpoint: Checkpoint configuration for this retry, or `True` to enable checkpointing with the default trigger (every 500k tokens). Must match the config used on the original eval for resume detection to find the checkpoint files (the original `--checkpoint` is not recorded in the log file).

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

    # opportunistically recover crashed logs before retrying
    recovered_files: dict[int, str] = {}
    for i, eval_log in enumerate(retry_eval_logs):
        if eval_log.status == "started" and eval_log.location:
            from inspect_ai.log._recover import (
                RecoveryNotAvailable,
                recover_eval_log_async,
            )

            try:
                recovered = await recover_eval_log_async(
                    eval_log.location, cleanup=False
                )
                retry_eval_logs[i] = recovered
                if recovered.location:
                    recovered_files[i] = recovered.location
            except RecoveryNotAvailable:
                pass  # no recovery data available — proceed with flushed samples
            except Exception as ex:
                logging.getLogger(__name__).warning(
                    f"Recovery failed for {eval_log.location}: {ex}"
                )

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
            if registry_lookup("task", task_name) is None and not task_name.startswith(
                "hf/"
            ):
                # if this object is in a package then let the user know
                # that they need to register it to work with eval-retry
                package_name = registry_package_name(task_name)
                if package_name is not None:
                    raise FileNotFoundError(
                        f"Task '{task_name}' is located in package '{package_name}' but has not been registered so cannot be retried. See https://inspect.aisi.org.uk/tasks.html#packaging for additional details on registering tasks in packages."
                    )
                else:
                    raise FileNotFoundError(f"Task '{task_name}' not found.")
            task = task_name

        # see if there is solver spec in the eval log
        solver = (
            SolverSpec(
                eval_log.eval.solver,
                eval_log.eval.solver_args or {},
                eval_log.eval.solver_args_passed or {},
            )
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
        task_args = eval_log.eval.task_args_passed
        tags = eval_log.eval.tags
        metadata = eval_log.eval.metadata
        limit = eval_log.eval.config.limit
        # try to match log format of retried log
        if log_format is None and eval_log.location:
            ext = os.path.splitext(eval_log.location)[1]
            match ext:
                case ".eval":
                    log_format = "eval"
                case ".json":
                    log_format = "json"
        sample_id = eval_log.eval.config.sample_id
        sample_shuffle = eval_log.eval.config.sample_shuffle
        epochs = (
            Epochs(eval_log.eval.config.epochs, eval_log.eval.config.epochs_reducer)
            if eval_log.eval.config.epochs
            else None
        )
        approval = eval_log.eval.config.approval
        notification: bool | str | None = eval_log.eval.config.notification
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
        continue_on_fail = (
            continue_on_fail
            if continue_on_fail is not None
            else eval_log.eval.config.continue_on_fail
        )
        retry_on_error = (
            retry_on_error
            if retry_on_error is not None
            else eval_log.eval.config.retry_on_error
        )
        score_on_error = (
            score_on_error
            if score_on_error is not None
            else eval_log.eval.config.score_on_error
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
        # resolve log_model_api from env var if not explicitly set
        if log_model_api is None:
            log_model_api_env = os.environ.get("INSPECT_EVAL_LOG_MODEL_API")
            if log_model_api_env is not None:
                log_model_api = log_model_api_env.lower() in ("true", "1", "yes")
        log_model_api = (
            log_model_api
            if log_model_api is not None
            else eval_log.eval.config.log_model_api
        )
        # resolve log_refusals from env var if not explicitly set
        if log_refusals is None:
            log_refusals_env = os.environ.get("INSPECT_EVAL_LOG_REFUSALS")
            if log_refusals_env is not None:
                log_refusals = log_refusals_env.lower() in ("true", "1", "yes")
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
        # ACP server: explicit retry-time value wins; otherwise replay
        # whatever transport the original eval used.
        acp_server = (
            acp_server if acp_server is not None else eval_log.eval.config.acp_server
        )

        config = eval_log.plan.config
        config.max_retries = max_retries or config.max_retries
        config.timeout = timeout or config.timeout
        config.attempt_timeout = attempt_timeout or config.attempt_timeout
        config.max_connections = max_connections or config.max_connections
        if adaptive_connections is not None:
            config.adaptive_connections = adaptive_connections

        # model_usage / role_usage are rolled forward per-task inside task_run
        # via PreviousTask.log.stats -> ResolvedTask.initial_*_usage; nothing
        # to seed here.

        # When the user passes scanners on retry, reuse the prior log's
        # scan_id so the existing scan dir is attached to (rather than a
        # fresh one being created from the new run_id). scan_init's
        # _verify_scanner_config_unchanged then enforces the same resume
        # contract eval_set uses — matching config attaches, divergent
        # config raises before any samples run.
        retry_scan_id = (
            (eval_log.eval.eval_set_id or eval_log.eval.run_id)
            if scanner is not None
            else None
        )

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
                    log_info=None,
                ),
                model=model,
                model_roles=cast(dict[str, str | Model], model_roles),
                task_args=task_args,
                sandbox=eval_log.eval.sandbox,
                sandbox_cleanup=sandbox_cleanup,
                solver=solver,
                scanner=scanner,
                scan_id=retry_scan_id,
                tags=tags,
                metadata=metadata,
                approval=approval,
                notification=notification,
                log_level=log_level,
                log_level_transcript=log_level_transcript,
                log_dir=log_dir,
                log_format=log_format,
                limit=limit,
                sample_id=sample_id,
                sample_shuffle=sample_shuffle,
                epochs=epochs,
                fail_on_error=fail_on_error,
                continue_on_fail=continue_on_fail,
                retry_on_error=retry_on_error,
                score_on_error=score_on_error,
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
                log_model_api=log_model_api,
                log_refusals=log_refusals,
                log_buffer=log_buffer,
                log_shared=log_shared,
                score=score,
                score_display=score_display,
                checkpoint=checkpoint,
                acp_server=acp_server,
                ctl_server=ctl_server,
                **dict(config),
            )
        )[0]

        # add it to our results
        eval_logs.append(log)

    # Clean up recovered files only for retries that succeeded. On failure,
    # the recovered file serves as a safety net with samples that would
    # otherwise be lost.
    for idx, recovered_file in recovered_files.items():
        if eval_logs[idx].status == "success":
            try:
                filesystem(recovered_file).rm(recovered_file)
            except Exception:
                pass

    return EvalLogs(eval_logs)


def eval_init(
    model: str | Model | list[str] | list[Model] | None | NotGiven = NOT_GIVEN,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | str = dict(),
    max_subprocesses: int | None = None,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
    log_refusals: bool | None = None,
    task_group: TaskGroup | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[Model]:
    # init eval context
    init_eval_context(
        log_level, log_level_transcript, log_refusals, max_subprocesses, task_group
    )

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
    sample_shuffle: bool | int | None,
    eval_checkpoint: CheckpointConfig | None = None,
    notification: bool | str | None = None,
) -> tuple[list[ResolvedTask], list[ApprovalPolicy] | None]:
    # resolve model roles and initialize them in the eval context -- this
    # will enable tasks that reference model roles in their initialization
    # to pickup these mappings
    resolved_model_roles = resolve_model_roles(model_roles)
    init_model_roles(resolved_model_roles or {})

    task_args = resolve_args(task_args)
    # To support inspect-flow using this method directly, make sure not to create the display if it does not already exist.
    active_display = active_task_display()
    with active_display.suspend_task_app() if active_display else nullcontext():
        resolved_tasks: list[ResolvedTask] = []
        for m in models:
            init_active_model(m, config)
            resolved_tasks.extend(
                resolve_tasks(
                    tasks,
                    task_args,
                    m,
                    resolved_model_roles,
                    sandbox,
                    sample_shuffle,
                    eval_checkpoint,
                )
            )

    if isinstance(approval, str | ApprovalPolicyConfig):
        approval = approval_policies_from_config(approval)
    init_tool_approval(approval)

    # install Apprise notification target for the eval scope
    init_apprise(build_apprise(notification))

    # return tasks and approval
    return resolved_tasks, approval


def init_eval_display(
    display: DisplayType | None,
    trace: bool | None,
    max_tasks: int | None,
    max_samples: int | None,
    model: Any = None,
    run_samples: bool = True,
) -> tuple[int | None, int | None]:
    # propagate any trace value to display_type
    if trace:
        warn_once(
            log,
            "WARNING: The --trace flag is deprecated (use --display=conversation instead)",
        )
        display = "conversation"

    # apply default and init
    if not run_samples:
        display = "none"
    else:
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

    def __str__(self) -> str:
        return list.__repr__(self)
