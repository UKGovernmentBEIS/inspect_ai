import logging
import os
from typing import Any, Set, cast

import rich
from rich.status import Status
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_not_result,
    stop_after_attempt,
    wait_exponential,
)
from typing_extensions import Unpack

from inspect_ai._eval.task.task import Task
from inspect_ai._util.file import filesystem
from inspect_ai.log import EvalLog
from inspect_ai.log._file import (
    EvalLogInfo,
    list_eval_logs,
    read_eval_log_headers,
)
from inspect_ai.model import (
    GenerateConfigArgs,
    Model,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.solver import Plan, Solver
from inspect_ai.util import SandboxEnvironmentSpec

from .eval import eval, eval_init, eval_retry
from .loader import ResolvedTask
from .task import Epochs, Tasks

logger = logging.getLogger(__name__)


def eval_set(
    tasks: Tasks,
    log_dir: str,
    retry_attempts: int = 10,
    retry_wait: int = 30,
    retry_connections: float = 0.5,
    retry_cleanup: bool = True,
    model: str | Model | list[str] | list[Model] | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] = dict(),
    task_args: dict[str, Any] = dict(),
    sandbox: SandboxEnvironmentSpec | None = None,
    sandbox_cleanup: bool | None = None,
    plan: Plan | Solver | list[Solver] | None = None,
    log_level: str | None = None,
    limit: int | tuple[int, int] | None = None,
    epochs: int | Epochs | None = None,
    fail_on_error: bool | float | None = None,
    max_messages: int | None = None,
    max_samples: int | None = None,
    max_tasks: int | None = None,
    max_subprocesses: int | None = None,
    log_samples: bool | None = None,
    log_images: bool | None = None,
    log_buffer: int | None = None,
    score: bool = True,
    **kwargs: Unpack[GenerateConfigArgs],
) -> tuple[bool, list[EvalLog]]:
    r"""Evaluate a set of tasks.

    Args:
        tasks: (Tasks): Task(s) to evaluate. If None, attempt
            to evaluate a task in the current working directory
        log_dir (str): Output path for logging results
           (required to ensure that a unique storage scope is assigned for the set).
        retry_attempts: (int): Maximum number of retry attempts before giving up
          (defaults to 10).
        retry_wait (int): Time to wait between attempts, increased exponentially.
          (defaults to 30, resulting in waits of 30, 60, 120, 240, etc.). Wait time
          per-retry will in no case by longer than 1 hour.
        retry_connections (float): Reduce max_connections at this rate with each retry
          (defaults to 0.5)
        retry_cleanup (bool): Cleanup failed log files after retries
          (defaults to True)
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
        limit (int | tuple[int, int] | None): Limit evaluated samples
           (defaults to all samples).
        epochs (int | Epochs | None): Epochs to repeat samples for and optional score
           reducer function(s) used to combine sample scores (defaults to "mean")
        fail_on_error (bool | float | None): `True` to fail on first sample error
           (default); `False` to never fail on sample errors; Value between 0 and 1
           to fail if a proportion of total samples fails. Value greater than 1 to fail
           eval if a count of samples fails.
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
        Tuple of bool (whether all tasks completed successfully) and list of EvalLog
        (one for each task)
    """
    # resolve tasks
    models, resolved_tasks = eval_init(
        tasks=tasks,
        model=model,
        model_base_url=model_base_url,
        model_args=model_args,
        task_args=task_args,
        sandbox=sandbox,
        max_subprocesses=max_subprocesses,
        log_level=log_level,
        **kwargs,
    )

    # ensure that all tasks have unique identfiers (will need this for pairing
    # tasks with log files). will throw if the constraint is violated
    validate_unique_identifers(resolved_tasks)

    # ensure log_dir
    fs = filesystem(log_dir)
    fs.mkdir(log_dir, exist_ok=True)

    # pick out the max_connections so we can tweak it
    max_connections = starting_max_connections(models, GenerateConfig(**kwargs))

    # status display
    status: Status | None = None

    # before sleep
    def before_sleep(retry_state: RetryCallState) -> None:
        # compute next max_connections
        nonlocal max_connections
        max_connections = max(round(max_connections * retry_connections), 1)
        kwargs["max_connections"] = max_connections

        nonlocal status
        console = rich.get_console()
        console.print("")
        status = console.status(
            f"[blue bold]Evals not complete, waiting {round(retry_state.upcoming_sleep)} seconds before retrying...\n[/blue bold]",
            spinner="clock",
        )
        status.start()

    def before(retry_state: RetryCallState) -> None:
        nonlocal status
        if status is not None:
            status.stop()
            status = None

    # filter for determining when we are done
    def all_evals_succeeded(logs: list[EvalLog]) -> bool:
        return all([log.status == "success" for log in logs])

    # return last value if we get to the end
    def return_last_value(retry_state: RetryCallState) -> list[EvalLog]:
        if retry_state.outcome:
            return cast(list[EvalLog], retry_state.outcome.result())
        else:
            return []

    # helper function that gets the latest logs (cleaning if requested)
    def latest_eval_logs() -> list[tuple[EvalLogInfo, EvalLog]]:
        log_files = list_eval_logs(log_dir)
        log_headers = read_eval_log_headers(log_files)
        return latest_completed_task_eval_logs(
            log_files, log_headers, cleanup_older=retry_cleanup
        )

    # helper function to run a set of evals
    def run_eval(tasks: Tasks, models: list[Model]) -> list[EvalLog]:
        return eval(
            tasks=tasks,
            model=models,
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
            fail_on_error=fail_on_error,
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

    # function which will be called repeatedly to attempt to complete
    # the evaluations. for this purpose we will divide tasks into:
    #   - tasks with no log at all (they'll be attempted for the first time)
    #   - tasks with a successful log (they'll just be returned)
    #   - tasks with failed logs (they'll be retried)
    def try_eval() -> list[EvalLog]:
        # see which tasks are yet to run (to complete successfully we need
        # a successful eval for every [task_file/]task_name/model combination)
        logs = list_eval_logs(log_dir)
        log_headers = read_eval_log_headers(logs)
        log_task_identifers = [task_identifer(log) for log in log_headers]
        all_tasks = [(task_identifer(task), task) for task in resolved_tasks]
        pending_tasks = [
            task[1] for task in all_tasks if task[0] not in log_task_identifers
        ]

        # schedule pending tasks (they need to be grouped by which models to
        # run them on -- if all tasks are pending then there will be only 1 group)
        task_groups = schedule_pending_tasks(pending_tasks)

        # run the task groups (each will have a different model list)
        if len(task_groups) > 0:
            for task_group in task_groups:
                # alias
                group_models, group_tasks = task_group

                # info log
                logger.info(
                    f"eval_set (initial run for tasks): {','.join([task.name for task in group_tasks])}: {group_models}"
                )

                # run the evals
                run_eval(tasks=list(group_tasks), models=group_models.models)

            # return latest
            return [log[1] for log in latest_eval_logs()]

        # we've already run the first pass on all the task groups, now do retries
        else:
            # look for retryable eval logs and cleave them into success/failed
            latest_logs = latest_eval_logs()
            success_logs = [log[1] for log in latest_logs if log[1].status == "success"]
            failed_logs = [log[0] for log in latest_logs if log[1].status != "success"]

            # retry the failed logs
            if len(failed_logs) > 0:
                newline = "\n  "
                logger.info(
                    f"eval_set (retrying failed evals):{newline}{newline.join([os.path.basename(log.name) for log in failed_logs])}"
                )

                # create previous tasks
                previous_tasks = failed_logs

                retried_logs = eval_retry(
                    previous_tasks, log_dir=log_dir, max_connections=max_connections
                )
                return success_logs + retried_logs
            else:
                return success_logs

    # create retry policy
    retry = Retrying(
        retry=retry_if_not_result(all_evals_succeeded),
        retry_error_callback=return_last_value,
        reraise=True,
        stop=stop_after_attempt(retry_attempts),
        wait=wait_exponential(retry_wait, max=(60 * 60)),
        before_sleep=before_sleep,
        before=before,
    )

    # execute w/ retry
    results = retry(try_eval)

    # final sweep to remove failed log files
    if retry_cleanup:
        latest_eval_logs()

    # return status + results
    return all_evals_succeeded(results), results


# validate that all of the tasks have a unique identfier
def validate_unique_identifers(resolved_tasks: list[ResolvedTask]) -> None:
    identifiers: Set[str] = set()
    for task in resolved_tasks:
        identifer = task_identifer(task)
        if identifer in identifiers:
            raise ValueError(
                f"Tasks in an eval_set must have distinct names (found duplicate name '{task_identifer_without_model(identifer)}')"
            )
        else:
            identifiers.add(identifer)


# yield a unique identifier for a task (used to pair resolved tasks to log files)
def task_identifer(task: ResolvedTask | EvalLog) -> str:
    if isinstance(task, ResolvedTask):
        task_file = task.task_file or ""
        task_name = task.task.name
        model = str(task.model)
    else:
        task_file = task.eval.task_file or ""
        task_name = task.eval.task
        model = task.eval.model

    if task_file:
        return f"{task_file}@{task_name}/{model}"
    else:
        return f"{task_name}/{model}"


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


def schedule_pending_tasks(
    pending_tasks: list[ResolvedTask],
) -> list[tuple[ModelList, Set[Task]]]:
    # build a map of task identifiers and the models they target
    task_id_model_targets: dict[str, ModelList] = {}
    for pending_task in pending_tasks:
        task_id = task_identifer_without_model(task_identifer(pending_task))
        if task_id not in task_id_model_targets:
            task_id_model_targets[task_id] = ModelList([])
        task_id_model_targets[task_id].models.append(pending_task.model)

    # build a list of unique model targets
    unique_model_targets: Set[ModelList] = set(task_id_model_targets.values())

    # create schedule
    schedule: list[tuple[ModelList, Set[Task]]] = [
        (model_target, set()) for model_target in unique_model_targets
    ]
    for models, tasks in schedule:
        # which task ids have this set of models
        task_ids: list[str] = []
        for task_id, task_models in task_id_model_targets.items():
            if task_models == models:
                task_ids.append(task_id)

        # go find the tasks that have this id
        for task_id in task_ids:
            for t in [
                task.task
                for task in pending_tasks
                if task_id == task_identifer_without_model(task_identifer(task))
            ]:
                tasks.add(t)

    # deterministic return order
    schedule.sort(key=lambda x: str(x[0]))

    return schedule


def latest_completed_task_eval_logs(
    log_files: list[EvalLogInfo], logs: list[EvalLog], cleanup_older: bool = False
) -> list[tuple[EvalLogInfo, EvalLog]]:
    # collect logs by id
    logs_by_id: dict[str, list[tuple[EvalLogInfo, EvalLog]]] = {}
    for log, log_header in zip(log_files, logs):
        id = log_header.eval.task_id
        if id not in logs_by_id:
            logs_by_id[id] = []
        logs_by_id[id].append((log, log_header))

    # take the most recent completed log for each id
    latest_completed_logs: list[tuple[EvalLogInfo, EvalLog]] = []
    for id, id_logs in logs_by_id.items():
        # filter on completed
        id_logs = [id_log for id_log in id_logs if id_log[1].status != "started"]

        # sort by last file write time
        id_logs.sort(key=lambda id_log: id_log[0].mtime, reverse=True)

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


def starting_max_connections(models: list[Model], config: GenerateConfig) -> int:
    # if there is an explicit config use that
    if config.max_connections is not None:
        return config.max_connections

    # else take the smallest model max connections
    else:
        return min(
            models, key=lambda model: model.api.max_connections()
        ).api.max_connections()
