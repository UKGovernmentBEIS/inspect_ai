import hashlib
import logging
from typing import Any, Literal, NamedTuple, Set, cast

import rich
from pydantic_core import to_json
from rich.status import Status
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_not_result,
    stop_after_attempt,
    wait_exponential,
)
from typing_extensions import Unpack

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import basename, filesystem
from inspect_ai._util.notgiven import NOT_GIVEN, NotGiven
from inspect_ai.agent._agent import Agent
from inspect_ai.approval._policy import ApprovalPolicy
from inspect_ai.log import EvalLog
from inspect_ai.log._bundle import bundle_log_dir
from inspect_ai.log._file import (
    EvalLogInfo,
    list_eval_logs,
    read_eval_log,
    read_eval_log_headers,
    write_log_dir_manifest,
)
from inspect_ai.log._model import model_roles_to_model_roles_config
from inspect_ai.model import (
    GenerateConfigArgs,
    Model,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util import DisplayType, SandboxEnvironmentType
from inspect_ai.util._display import display_type_initialized, init_display_type

from .eval import eval, eval_init, eval_resolve_tasks
from .loader import resolve_task_args
from .task import Epochs
from .task.resolved import ResolvedTask
from .task.task import PreviousTask
from .task.tasks import Tasks

logger = logging.getLogger(__name__)


class Log(NamedTuple):
    info: EvalLogInfo
    header: EvalLog
    task_identifier: str


def eval_set(
    tasks: Tasks,
    log_dir: str,
    retry_attempts: int | None = None,
    retry_wait: float | None = None,
    retry_connections: float | None = None,
    retry_cleanup: bool | None = None,
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
    score: bool = True,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
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
    bundle_dir: str | None = None,
    bundle_overwrite: bool = False,
    **kwargs: Unpack[GenerateConfigArgs],
) -> tuple[bool, list[EvalLog]]:
    r"""Evaluate a set of tasks.

    Args:
        tasks: Task(s) to evaluate. If None, attempt
            to evaluate a task in the current working directory
        log_dir: Output path for logging results
            (required to ensure that a unique storage scope is assigned for the set).
        retry_attempts: Maximum number of retry attempts before giving up
            (defaults to 10).
        retry_wait: Time to wait between attempts, increased exponentially.
            (defaults to 30, resulting in waits of 30, 60, 120, 240, etc.). Wait time
            per-retry will in no case by longer than 1 hour.
        retry_connections: Reduce max_connections at this rate with each retry
            (defaults to 0.5)
        retry_cleanup: Cleanup failed log files after retries
            (defaults to True)
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
        solver: Alternative solver(s) for
            evaluating task(s). ptional (uses task solver by default).
        tags: Tags to associate with this evaluation run.
        metadata: Metadata to associate with this evaluation run.
        trace: Trace message interactions with evaluated model to terminal.
        display: Task display type (defaults to 'full').
        approval: Tool use approval policies.
            Either a path to an approval policy config file or a list of approval policies.
            Defaults to no approval policy.
        score: Score output (defaults to True)
        log_level: Level for logging to the console: "debug", "http", "sandbox",
            "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript: Level for logging to the log file (defaults to "info")
        log_format: Format for writing
            log files (defaults to "eval", the native high-performance format).
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
        bundle_dir: If specified, the log viewer and logs generated
            by this eval set will be bundled into this directory.
        bundle_overwrite: Whether to overwrite files in the bundle_dir.
            (defaults to False).
        **kwargs: Model generation options.

    Returns:
        Tuple of bool (whether all tasks completed successfully) and list of EvalLog
        (one for each task)
    """

    # helper function to run a set of evals
    def run_eval(tasks: list[ResolvedTask] | list[PreviousTask]) -> list[EvalLog]:
        # run evals
        results = eval(
            tasks=tasks,
            model=None,  # ResolvedTask/PreviousTask already carries its model
            model_base_url=model_base_url,
            model_args=model_args,
            model_roles=model_roles,
            task_args=task_args,
            sandbox=sandbox,
            sandbox_cleanup=sandbox_cleanup,
            solver=solver,
            tags=tags,
            metadata=metadata,
            trace=trace,
            display=display,
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
            **kwargs,
        )

        # check for cancelled
        if evals_cancelled(results):
            raise KeyboardInterrupt

        # if specified, bundle the output directory
        if bundle_dir:
            bundle_log_dir(
                log_dir=log_dir, output_dir=bundle_dir, overwrite=bundle_overwrite
            )

        # return results
        return results

    # initialise display (otherwise eval_init will set it to full)
    if not display_type_initialized():
        display = init_display_type(display)
    if display == "conversation":
        raise RuntimeError("eval_set cannot be used with conversation display.")

    # initialize eval
    models = eval_init(
        model=model,
        model_base_url=model_base_url,
        model_args=model_args,
        max_subprocesses=max_subprocesses,
        log_level=log_level,
        log_level_transcript=log_level_transcript,
        **kwargs,
    )

    # ensure log_dir
    fs = filesystem(log_dir)
    fs.mkdir(log_dir, exist_ok=True)

    # resolve some parameters
    retry_connections = retry_connections or 0.5
    retry_cleanup = retry_cleanup is not False
    max_connections = starting_max_connections(models, GenerateConfig(**kwargs))
    max_tasks = max_tasks if max_tasks is not None else len(models)

    # prepare console/status
    console = rich.get_console()
    status: Status | None = None

    # before sleep
    def before_sleep(retry_state: RetryCallState) -> None:
        # compute/update next max_connections
        nonlocal max_connections
        max_connections = max(round(max_connections * retry_connections), 1)
        kwargs["max_connections"] = max_connections

        # print waiting status
        nonlocal status
        console.print("")
        msg = (
            f"Evals not complete, waiting {round(retry_state.upcoming_sleep)} "
            + "seconds before retrying...\n"
        )
        status = console.status(status_msg(msg), spinner="clock")
        status.start()

    def before(retry_state: RetryCallState) -> None:
        # clear waiting status
        nonlocal status
        if status is not None:
            status.stop()
            status = None

    # function which will be called repeatedly to attempt to complete
    # the evaluations. for this purpose we will divide tasks into:
    #   - tasks with no log at all (they'll be attempted for the first time)
    #   - tasks with a successful log (they'll just be returned)
    #   - tasks with failed logs (they'll be retried)
    def try_eval() -> list[EvalLog]:
        # resolve tasks
        resolved_tasks, _ = eval_resolve_tasks(
            tasks,
            task_args,
            models,
            model_roles,
            GenerateConfig(**kwargs),
            approval,
            sandbox,
        )

        # list all logs currently in the log directory (update manifest if there are some)
        all_logs = list_all_eval_logs(log_dir)
        if len(all_logs) > 0:
            write_log_dir_manifest(log_dir)

        # validate that:
        #  (1) All tasks have a unique identifier
        #  (2) All logs have identifiers that map to tasks
        validate_eval_set_prerequisites(resolved_tasks, all_logs)

        # see which tasks are yet to run (to complete successfully we need
        # a successful eval for every [task_file/]task_name/model combination)
        # for those that haven't run, schedule them into models => tasks groups
        log_task_identifiers = [log.task_identifier for log in all_logs]
        all_tasks = [(task_identifier(task), task) for task in resolved_tasks]
        pending_tasks = [
            task[1] for task in all_tasks if task[0] not in log_task_identifiers
        ]

        # we have some pending tasks yet to run, run them
        if len(pending_tasks) > 0:
            # run the tasks
            run_logs = run_eval(pending_tasks)

            # if this was the entire list of resolved tasks, return results
            if len(pending_tasks) == len(all_tasks):
                return run_logs
            # otherwise query the filesystem
            else:
                latest_logs = latest_completed_task_eval_logs(
                    logs=list_all_eval_logs(log_dir), cleanup_older=False
                )
                return [log.header for log in latest_logs]

        # all tasks have had an initial run, perform retries
        else:
            # look for retryable eval logs and cleave them into success/failed
            success_logs, failed_logs = list_latest_eval_logs(all_logs, retry_cleanup)

            # retry the failed logs (look them up in resolved_tasks)
            if len(failed_logs) > 0:
                # schedule the re-execution of the failed tasks
                failed_task_identifiers = [log.task_identifier for log in failed_logs]
                failed_tasks = [
                    task
                    for task in resolved_tasks
                    if task_identifier(task) in failed_task_identifiers
                ]

                # run previous tasks (no models passed b/c previous task already carries its model)
                retried_logs = run_eval(
                    tasks=as_previous_tasks(failed_tasks, failed_logs)
                )

                # return success
                return [log.header for log in success_logs] + retried_logs

            # no failed logs to retry, just return sucesss logs
            else:
                return [log.header for log in success_logs]

    # create retry policy
    retry = Retrying(
        retry=retry_if_not_result(all_evals_succeeded),
        retry_error_callback=return_last_value,
        reraise=True,
        stop=stop_after_attempt(10 if retry_attempts is None else retry_attempts),
        wait=wait_exponential(retry_wait or 30, max=(60 * 60)),
        before_sleep=before_sleep,
        before=before,
    )

    # execute w/ retry
    results = retry(try_eval)

    # final sweep to remove failed log files
    if retry_cleanup:
        cleanup_older_eval_logs(log_dir)

    # report final status
    success = all_evals_succeeded(results)
    if success:
        msg = status_msg(f"Completed all tasks in '{log_dir}' successfully")
    else:
        msg = status_msg(f"Did not successfully complete all tasks in '{log_dir}'.")
    console.print(f"{msg}")

    # update manifest
    write_log_dir_manifest(log_dir)

    # return status + results
    return success, results


# convert resolved tasks to previous tasks
def as_previous_tasks(
    tasks: list[ResolvedTask], failed_logs: list[Log]
) -> list[PreviousTask]:
    def task_to_failed_log(task: ResolvedTask) -> Log:
        resolved_task_identifier = task_identifier(task)
        return next(
            log
            for log in failed_logs
            if log.task_identifier == resolved_task_identifier
        )

    previous_tasks: list[PreviousTask] = []
    for task, log in zip(tasks, map(task_to_failed_log, tasks)):
        previous_tasks.append(
            PreviousTask(
                id=log.header.eval.task_id,
                task=task.task,
                task_args=resolve_task_args(task.task),
                model=task.model,
                model_roles=task.model_roles,
                log=read_eval_log(log.info),
            )
        )

    return previous_tasks


# filters to determine when we are done


def all_evals_succeeded(logs: list[EvalLog]) -> bool:
    return all([log.status == "success" for log in logs])


# filter for determining when we are done
def evals_cancelled(logs: list[EvalLog]) -> bool:
    return any([log.status == "cancelled" for log in logs])


# return last value if we get to the end
def return_last_value(retry_state: RetryCallState) -> list[EvalLog]:
    if retry_state.outcome:
        return cast(list[EvalLog], retry_state.outcome.result())
    else:
        return []


# list all eval logs
def list_all_eval_logs(log_dir: str) -> list[Log]:
    log_files = list_eval_logs(log_dir)
    log_headers = read_eval_log_headers(log_files)
    task_identifiers = [task_identifier(log_header) for log_header in log_headers]
    return [
        Log(info=info, header=header, task_identifier=task_identifier)
        for info, header, task_identifier in zip(
            log_files, log_headers, task_identifiers
        )
    ]


# get the latest logs (cleaning if requested). returns tuple of successful/unsuccessful
def list_latest_eval_logs(
    logs: list[Log], cleanup_older: bool
) -> tuple[list[Log], list[Log]]:
    latest_logs = latest_completed_task_eval_logs(
        logs=logs, cleanup_older=cleanup_older
    )
    success_logs = [log for log in latest_logs if log.header.status == "success"]
    failed_logs = [log for log in latest_logs if log.header.status != "success"]
    return (success_logs, failed_logs)


# cleanup logs that aren't the latest
def cleanup_older_eval_logs(log_dir: str) -> None:
    latest_completed_task_eval_logs(
        logs=list_all_eval_logs(log_dir), cleanup_older=True
    )


def latest_completed_task_eval_logs(
    logs: list[Log], cleanup_older: bool = False
) -> list[Log]:
    # collect logs by id
    logs_by_id: dict[str, list[Log]] = {}
    for log in logs:
        id = log.header.eval.task_id
        if id not in logs_by_id:
            logs_by_id[id] = []
        logs_by_id[id].append(log)

    # take the most recent completed log for each id
    latest_completed_logs: list[Log] = []
    for id, id_logs in logs_by_id.items():
        # continue if there are no target logs
        if len(id_logs) == 0:
            continue

        # sort by last file write time
        id_logs.sort(
            key=lambda id_log: (id_log[0].mtime if id_log[0].mtime else 0), reverse=True
        )

        # take the most recent
        latest_completed_logs.append(id_logs[0])

        # remove the rest if requested
        # (don't remove 'started' in case its needed for post-mortum debugging)
        if cleanup_older:
            fs = filesystem(id_logs[0][0].name)
            for id_log in id_logs[1:]:
                try:
                    if id_log.header.status != "started":
                        fs.rm(id_log.info.name)
                except Exception as ex:
                    logger.warning(f"Error attempt to remove '{id_log[0].name}': {ex}")

    return latest_completed_logs


# ensure that preconditions for eval_set are met:
#  (1) all tasks have unique identfiers (so we can pair task -> log file)
#  (2) all log files have identifiers that map to tasks (so we know we
#      are running in a log dir created for this eval_set)
def validate_eval_set_prerequisites(
    resolved_tasks: list[ResolvedTask], all_logs: list[Log]
) -> None:
    # do all resolved tasks have unique identfiers?
    task_identifiers: Set[str] = set()
    for task in resolved_tasks:
        identifier = task_identifier(task)
        if identifier in task_identifiers:
            raise PrerequisiteError(
                f"[bold]ERROR[/bold]: The task '{task.task.name}' is not distinct.\n\nTasks in an eval_set must have distinct names OR use the @task decorator and have distinct combinations of name and task args. Solvers passed to tasks should also use the @solver decorator."
            )
        else:
            task_identifiers.add(identifier)

    # do all logs in the log directory correspond to task identifiers?
    for log in all_logs:
        if log.task_identifier not in task_identifiers:
            raise PrerequisiteError(
                f"[bold]ERROR[/bold]: Existing log file '{basename(log.info.name)}' in log_dir is not "
                + "associated with a task passed to eval_set (you must run eval_set "
                + "in a fresh log directory)"
            )


# yield a unique identifier for a task (used to pair resolved tasks to log files)
def task_identifier(task: ResolvedTask | EvalLog) -> str:
    if isinstance(task, ResolvedTask):
        task_file = task.task_file or ""
        task_name = task.task.name
        task_args = task.task_args
        model = str(task.model)
        model_roles = model_roles_to_model_roles_config(task.model_roles) or {}
    else:
        task_file = task.eval.task_file or ""
        task_name = task.eval.task
        task_args = task.eval.task_args
        model = str(task.eval.model)
        model_roles = task.eval.model_roles or {}

    # hash for task args
    task_args_hash = hashlib.sha256(
        to_json(task_args, exclude_none=True, fallback=lambda _x: None)
    ).hexdigest()

    # hash for model roles
    if len(model_roles):
        model = (
            model
            + "/"
            + hashlib.sha256(
                to_json(model_roles, exclude_none=True, fallback=lambda _x: None)
            ).hexdigest()
        )

    if task_file:
        return f"{task_file}@{task_name}#{task_args_hash}/{model}"
    else:
        return f"{task_name}#{task_args_hash}/{model}"


def task_identifier_without_model(identifier: str) -> str:
    parts = identifier.split("/")
    parts = parts[:-2]
    identifier = "/".join(parts)
    return identifier


class ModelList:
    def __init__(self, models: list[Model]) -> None:
        self.models = models

    def __hash__(self) -> int:
        # Hash based on the result of the key function
        return hash(self._key())

    def __eq__(self, other: object) -> bool:
        # Compare based on the result of the key function
        if not isinstance(other, ModelList):
            return False
        return self._key() == other._key()

    def __str__(self) -> str:
        return ",".join([str(model) for model in self.models])

    def _key(self) -> str:
        model_names = [str(model) for model in self.models]
        model_names.sort()
        return ",".join(model_names)


def starting_max_connections(models: list[Model], config: GenerateConfig) -> int:
    # if there is an explicit config use that
    if config.max_connections is not None:
        return config.max_connections

    # else take the smallest model max connections
    else:
        return min(
            models, key=lambda model: model.api.max_connections()
        ).api.max_connections()


def status_msg(msg: str) -> str:
    STATUS_FMT = "blue bold"
    return f"[{STATUS_FMT}]{msg}[/{STATUS_FMT}]"
