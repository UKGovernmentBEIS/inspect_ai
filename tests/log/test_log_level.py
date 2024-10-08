from logging import getLogger

from inspect_ai import Task, eval
from inspect_ai._util.constants import SANDBOX
from inspect_ai.log._transcript import LoggerEvent
from inspect_ai.model import get_model
from inspect_ai.solver import Generate, TaskState, solver

logger = getLogger(__name__)


def test_log_file_level() -> None:
    @solver
    def logging_solver():
        async def solve(state: TaskState, generate: Generate):
            logger.log(SANDBOX, "sandbox log entry")
            return state

        return solve

    log = eval(
        Task(solver=logging_solver()),
        model=get_model("mockllm/model"),
        log_level="debug",
        log_file_level="sandbox",
    )[0]

    assert log.status == "success"
    assert log.samples
    event: LoggerEvent | None = next(
        (
            event
            for event in log.samples[0].transcript.events
            if isinstance(event, LoggerEvent)
        ),
        None,
    )
    assert event
    assert event.message.level == "sandbox"
