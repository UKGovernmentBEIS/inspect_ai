import hashlib
import logging
from copy import deepcopy
from typing import Any, Callable, Literal, NamedTuple, Set, cast

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
from inspect_ai.model import (
    GenerateConfigArgs,
    Model,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util import SandboxEnvironmentType

from .eval import eval, eval_init
from .loader import ResolvedTask, resolve_task_args
from .task import Epochs, Tasks
from .task.task import PreviousTask, Task

logger = logging.getLogger(__name__)


def eval_set(
    tasks: Tasks,
    log_dir: str,
    retry_attempts: int | None = None,
    retry_wait: float | None = None,
    retry_connections: float | None = None,
    retry_cleanup: bool | None = None,
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
    score: bool = True,
    log_level: str | None = None,
    log_level_transcript: str | None = None,
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
    bundle_dir: str | None = None,
    bundle_overwrite: bool = False,
    **kwargs: Unpack[GenerateConfigArgs],
) -> tuple[bool, list[EvalLog]]:
    r"""Evaluate a set of tasks.

    Args:
        tasks: (Tasks): Task(s) to evaluate. If None, attempt
            to evaluate a task in the current working directory
        log_dir (str): Output path for logging results
           (required to ensure that a unique storage scope is assigned for the set).
        retry_attempts: (int | None): Maximum number of retry attempts before giving up
          (defaults to 10).
        retry_wait (float | None): Time to wait between attempts, increased exponentially.
          (defaults to 30, resulting in waits of 30, 60, 120, 240, etc.). Wait time
          per-retry will in no case by longer than 1 hour.
        retry_connections (float | None): Reduce max_connections at this rate with each retry
          (defaults to 0.5)
        retry_cleanup (bool | None): Cleanup failed log files after retries
          (defaults to True)
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
        solver (Solver | list[Solver] | SolverSpec | None): Alternative solver(s) for
           evaluating task(s). ptional (uses task solver by default).
        tags (list[str] | None): Tags to associate with this evaluation run.
        trace: (bool | None): Trace message interactions with evaluated model to terminal.
        approval: (str | list[ApprovalPolicy] | None): Tool use approval policies.
          Either a path to an approval policy config file or a list of approval policies.
          Defaults to no approval policy.
        score (bool): Score output (defaults to True)
        log_level (str | None): Level for logging to the console: "debug", "http", "sandbox",
          "info", "warning", "error", or "critical" (defaults to "warning")
        log_level_transcript (str | None): Level for logging to the log file (defaults to "info")
        log_format (Literal["eval", "json"] | None): Format for writing
          log files (defaults to "eval", the native high-performance format).
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
        bundle_dir: (str | None): If specified, the log viewer and logs generated
            by this eval set will be bundled into this directory.
        bundle_overwrite (bool): Whether to overwrite files in the bundle_dir.
            (defaults to False).
        **kwargs (GenerateConfigArgs): Model generation options.

    Returns:
        Tuple of bool (whether all tasks completed successfully) and list of EvalLog
        (one for each task)
    """

    # helper function to run a set of evals
    def run_eval(
        tasks: list[Task] | list[PreviousTask], models: list[Model]
    ) -> list[EvalLog]:
        # run evals
        results = eval(
            tasks=tasks,
            model=models,
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

    # helper function to run a list of task groups
    def run_task_groups(
        task_groups: list[TaskGroup],
        run_tasks: Callable[[list[ResolvedTask]], list[Task] | list[PreviousTask]],
    ) -> list[EvalLog]:
        logs: list[EvalLog] = []
        for task_group in task_groups:
            # alias
            group_models, group_tasks = task_group

            # info log
            logger.info(
                f"eval_set (running task group): {','.join([task.task.name for task in group_tasks])}: {group_models}"
            )

            # run the evals
            logs.extend(
                run_eval(
                    tasks=run_tasks(group_tasks),
                    models=group_models.models,
                )
            )

        return logs

    # resolve tasks
    models, _, resolved_tasks = eval_init(
        tasks=tasks,
        model=model,
        model_base_url=model_base_url,
        model_args=model_args,
        task_args=task_args,
        sandbox=sandbox,
        max_subprocesses=max_subprocesses,
        log_level=log_level,
        log_level_transcript=log_level_transcript,
        **kwargs,
    )

    # ensure log_dir and list all logs
    fs = filesystem(log_dir)
    fs.mkdir(log_dir, exist_ok=True)

    # validate that:
    #  (1) All tasks have a unique identifier
    #  (2) All logs have identifiers that map to tasks
    validate_eval_set_prerequisites(resolved_tasks, list_all_eval_logs(log_dir))

    # resolve some parameters
    retry_connections = retry_connections or 0.5
    retry_cleanup = retry_cleanup is not False
    max_connections = starting_max_connections(models, GenerateConfig(**kwargs))

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
        # list all logs currently in the log directory (update manifest if there are some)
        all_logs = list_all_eval_logs(log_dir)
        if len(all_logs) > 0:
            write_log_dir_manifest(log_dir)

        # see which tasks are yet to run (to complete successfully we need
        # a successful eval for every [task_file/]task_name/model combination)
        # for those that haven't run, schedule them into models => tasks groups
        log_task_identifers = [log.task_identifier for log in all_logs]
        all_tasks = [(task_identifer(task), task) for task in resolved_tasks]
        pending_tasks = [
            task[1] for task in all_tasks if task[0] not in log_task_identifers
        ]
        task_groups = schedule_pending_tasks(pending_tasks)

        # we have some pending tasks yet to run, run them
        if len(task_groups) > 0:
            # run the tasks
            run_logs = run_task_groups(
                task_groups=task_groups,
                run_tasks=lambda tasks: [task.task for task in tasks],
            )

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
                failed_task_identifers = [log.task_identifier for log in failed_logs]
                failed_tasks = [
                    task
                    for task in resolved_tasks
                    if task_identifer(task) in failed_task_identifers
                ]
                task_groups = schedule_retry_tasks(failed_tasks)

                # execute task groups (run previous task so we get the samples from the log)
                def run_previous_tasks(tasks: list[ResolvedTask]) -> list[PreviousTask]:
                    def task_to_failed_log(task: ResolvedTask) -> Log:
                        resolved_task_identifier = task_identifer(task)
                        return next(
                            log
                            for log in failed_logs
                            if log.task_identifier == resolved_task_identifier
                        )

                    previous_tasks: list[PreviousTask] = []
                    for task, log in zip(tasks, map(task_to_failed_log, tasks)):
                        # NOTE: we used to try to recreate registry objects by
                        # by just passing the task name, but that didn't work
                        # when evals were run from another directory. we may
                        # want to bring this back but we'd need to resolve the
                        # directory issues.

                        # deepcopy so the same instance is not run twice
                        prev_task = deepcopy(task.task)

                        previous_tasks.append(
                            PreviousTask(
                                id=log.header.eval.task_id,
                                task=prev_task,
                                task_args=resolve_task_args(task.task),
                                log=read_eval_log(log.info),
                            )
                        )

                    return previous_tasks

                retried_logs = run_task_groups(
                    task_groups=task_groups, run_tasks=run_previous_tasks
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


class Log(NamedTuple):
    info: EvalLogInfo
    header: EvalLog
    task_identifier: str


# list all eval logs
def list_all_eval_logs(log_dir: str) -> list[Log]:
    log_files = list_eval_logs(log_dir)
    log_headers = read_eval_log_headers(log_files)
    task_identifers = [task_identifer(log_header) for log_header in log_headers]
    return [
        Log(info=info, header=header, task_identifier=task_identifier)
        for info, header, task_identifier in zip(
            log_files, log_headers, task_identifers
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
        # filter on completed
        id_logs = [id_log for id_log in id_logs if id_log[1].status != "started"]

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
        if cleanup_older:
            fs = filesystem(id_logs[0][0].name)
            for id_log in id_logs[1:]:
                try:
                    fs.rm(id_log[0].name)
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
        identifer = task_identifer(task)
        if identifer in task_identifiers:
            raise PrerequisiteError(
                f"[bold]ERROR[/bold]: The task '{task.task.name}' is not distinct.\n\nTasks in an eval_set must have distinct names OR use the @task decorator and have distinct combinations of name and task args. Solvers passed to tasks should also use the @solver decorator."
            )
        else:
            task_identifiers.add(identifer)

    # do all logs in the log directory correspond to task identifiers?
    for log in all_logs:
        if log.task_identifier not in task_identifiers:
            raise PrerequisiteError(
                f"[bold]ERROR[/bold]: Existing log file '{basename(log.info.name)}' in log_dir is not "
                + "associated with a task passed to eval_set (you must run eval_set "
                + "in a fresh log directory)"
            )


# yield a unique identifier for a task (used to pair resolved tasks to log files)
def task_identifer(task: ResolvedTask | EvalLog) -> str:
    if isinstance(task, ResolvedTask):
        task_file = task.task_file or ""
        task_name = task.task.name
        task_args = task.task_args
        model = str(task.model)
    else:
        task_file = task.eval.task_file or ""
        task_name = task.eval.task
        task_args = task.eval.task_args
        model = task.eval.model

    # hash for task args
    task_args_hash = hashlib.sha256(
        to_json(task_args, exclude_none=True, fallback=lambda _x: None)
    ).hexdigest()

    if task_file:
        return f"{task_file}@{task_name}#{task_args_hash}/{model}"
    else:
        return f"{task_name}#{task_args_hash}/{model}"


def task_identifer_without_model(identifier: str) -> str:
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


class TaskGroup(NamedTuple):
    models: ModelList
    tasks: list[ResolvedTask]


# group into models => tasks for maximum parallelism
def schedule_pending_tasks(pending_tasks: list[ResolvedTask]) -> list[TaskGroup]:
    # build a map of task identifiers and the models they target
    task_id_model_targets: dict[str, ModelList] = {}
    for pending_task in pending_tasks:
        task_id = task_identifer_without_model(task_identifer(pending_task))
        if task_id not in task_id_model_targets:
            task_id_model_targets[task_id] = ModelList([])
        if pending_task.model not in task_id_model_targets[task_id].models:
            task_id_model_targets[task_id].models.append(pending_task.model)

    # build a list of unique model targets
    unique_model_targets: Set[ModelList] = set(task_id_model_targets.values())

    # create schedule
    schedule: list[TaskGroup] = [
        TaskGroup(models=model_target, tasks=[])
        for model_target in unique_model_targets
    ]

    for models, tasks in schedule:
        # which task ids have this set of models
        task_ids: list[str] = []
        for task_id, task_models in task_id_model_targets.items():
            if task_models == models:
                task_ids.append(task_id)

        # find a task for each of these ids
        for task_id in task_ids:
            tasks.append(
                next(
                    (
                        task
                        for task in pending_tasks
                        if task_id == task_identifer_without_model(task_identifer(task))
                    )
                )
            )

    # deterministic return order
    schedule.sort(key=lambda x: str(x[0]))

    return schedule


# group into model => tasks (can't do multiple models b/c these are PreviousTask
# instances (and therefore model/task pair specific -- we don't want to create
# multiple instances of these tasks)
def schedule_retry_tasks(retry_tasks: list[ResolvedTask]) -> list[TaskGroup]:
    # build a list of unique model targets
    unique_model_targets: Set[ModelList] = set()
    for retry_task in retry_tasks:
        unique_model_targets.add(ModelList([retry_task.model]))

    # create a task group for reach model target
    schedule: list[TaskGroup] = []
    for model_target in unique_model_targets:
        group_tasks = [
            task for task in retry_tasks if ModelList([task.model]) == model_target
        ]
        schedule.append(TaskGroup(model_target, group_tasks))

    # deterministic return order
    schedule.sort(key=lambda x: str(x[0]))

    return schedule


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
