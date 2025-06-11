import logging
import os
from datetime import datetime

from inspect_ai import Task, eval, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util._sandbox.context import sandbox
from inspect_ai.util._sandbox.limits import OutputLimitExceededError

logger = logging.getLogger("debug_logging")

FILE_PATH = "large-file.txt"


@solver
def exec_hang_solver():
    async def run(state: TaskState, generate: Generate) -> TaskState:
        try:
            logger.info(f"Epoch {state.epoch}; Solver starting execution.")
            await sandbox().exec(["cat", FILE_PATH], timeout=1)
            logger.info(f"Epoch {state.epoch}; Solver executed successfully.")
        except OutputLimitExceededError:
            # Expected (limit is 10 MiB).
            logger.info(
                f"Epoch {state.epoch}; Solver caught OutputLimitExceededError; ignoring"
            )
            pass
        except TimeoutError:
            logger.info(f"Epoch {state.epoch}; Solver caught TimeoutError; ignoring.")
            pass
        except Exception as e:
            logger.error(
                f"Epoch {state.epoch}; Solver caught exception: {e}. Re-raising."
            )
            raise
        return state

    return run


setup_script = f"""
dd if=/dev/zero bs=1M count=11 > {FILE_PATH} 2>/dev/null
"""


@task
def exec_hang_mre():
    samples = [
        Sample(
            input="[placeholder]",
            setup=setup_script,
        )
    ]

    return Task(
        dataset=MemoryDataset(samples),
        solver=exec_hang_solver(),
        sandbox="local",
    )


if __name__ == "__main__":
    os.environ["INSPECT_DOCKER_CLI_CONCURRENCY"] = "500"
    os.makedirs("logs", exist_ok=True)
    os.environ["INSPECT_PY_LOGGER_FILE"] = (
        f"logs/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    )
    os.environ["INSPECT_PY_LOGGER_LEVEL"] = "INFO"
    eval(
        exec_hang_mre(),
        model="mockllm/model",
        epochs=40,
        max_sandboxes=500,
        max_connections=500,
        max_subprocesses=500,
        log_level="INFO",
        display="full",
    )
