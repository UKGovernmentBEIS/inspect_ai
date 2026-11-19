class TerminateSampleError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class SampleRefusedError(RuntimeError):
    """A sample that can't run where its model calls go, such as one a sentinel sidecar wasn't registered to judge.

    It is never retried, since a retry would be refused the same way, and never scored, since the sample never ran. It counts toward `fail_on_error` like any other sample error.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class TerminateTaskError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class TaskRetryAbandonedError(RuntimeError):
    """A retry attempt found its retry abandoned at attempt start.

    Raised by ``task_run`` when a task drain/cancel stamped the
    retry-abandoned registry after the dispatcher dequeued the retry but
    before the attempt registered its ``EvalState`` (see
    ``design/ctl/task-drain.md`` "Tasks between attempts"). The dispatcher
    maps it to a side-effect-free finalize via ``TaskRunResult.abandoned``
    — the errored prior attempt's log stands as the task's final state.
    """

    def __init__(self) -> None:
        super().__init__("task retry abandoned by operator")
