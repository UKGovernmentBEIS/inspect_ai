from logging import getLogger

from inspect_ai._util.logger import warn_once

from ._file import EvalLogInfo, read_eval_log_headers

logger = getLogger(__name__)


def retryable_eval_logs(logs: list[EvalLogInfo]) -> list[EvalLogInfo]:
    """Extract the list of retryable logs from a list of logs.

    Retryable logs are logs with status "error" or "cancelled" that
    do not have a corresponding log with status "success" (indicating
    they were subsequently retried and completed)

    Args:
      logs (list[EvalLogInfo]): List of logs to examine.

    Returns:
      List of retryable eval logs found in the list of logs.
    """
    warn_once(
        logger,
        "The retryable_eval_logs function is deprecated. Please use the eval_set() function instead.",
    )

    # first collect up all of the headers (so we can look at status)
    log_headers = read_eval_log_headers(logs)

    # build a set of completed task ids
    completed_task_ids = set(
        [
            log_header.eval.task_id
            for log_header in log_headers
            if log_header.status == "success"
        ]
    )

    # find all logs for incomplete tasks ("started", "error", or "cancelled") that # # have not been subsequently completed (keep a map by task_id, and perserve only
    # the most recent one)
    retryable_logs: dict[str, EvalLogInfo] = {}
    for log, log_header in zip(logs, log_headers):
        if log_header.status == "cancelled" or log_header.status == "error":
            if log_header.eval.task_id not in completed_task_ids:
                existing_log = retryable_logs.get(log_header.eval.task_id, None)
                if existing_log:
                    if (
                        existing_log.mtime is not None
                        and log.mtime is not None
                        and log.mtime > existing_log.mtime
                    ):
                        retryable_logs[log_header.eval.task_id] = log
                else:
                    retryable_logs[log_header.eval.task_id] = log

    # return the retryable logs
    return list(retryable_logs.values())
