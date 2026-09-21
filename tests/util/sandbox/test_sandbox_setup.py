from pathlib import Path
from typing import ClassVar, Literal, overload

import anyio
import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, includes
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import (
    ExecResult,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
    is_dockerfile,
    sandbox,
)
from inspect_ai.util._sandbox.context import init_sandbox_environments_sample

SANDBOX_SETUP_FILE = (Path(__file__).parent / "sandbox_setup.sh").as_posix()
SANDBOX_SETUP_ERROR_FILE = (Path(__file__).parent / "sandbox_setup_error.sh").as_posix()
SANDBOX_SETUP_SYMLINK_FILE = (
    Path(__file__).parent / "sandbox_setup_symlink.sh"
).as_posix()

with open(SANDBOX_SETUP_FILE, "r") as f:
    sandbox_setup = f.read()

SUCCESS = "FOUND"
NOT_FOUND = "MISSING"


@solver
def check_file(expected_content: str | None = None) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        """
        Check if a file exists, and if it contains the expected_content.

        Returns SUCCESS if the file exists with expected content. Otherwise
        returns NOT_FOUND if file is missing or the mismatched set of strings
        if expected_content doesn't match actual content.
        """
        try:
            value = await sandbox().read_file(state.metadata["file"])
            # Strip before comparing values to avoid trailing newline mismatches
            if not expected_content or expected_content.strip() == value.strip():
                completion = SUCCESS
            else:
                # Unexpected contents,
                completion = f"{repr(value)} != {repr(expected_content)}"
        except FileNotFoundError:
            completion = NOT_FOUND

        state.output = ModelOutput.from_content("mockllm/model", completion)

        return state

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_setup():
    def sample(file: str, target: str, setup: str) -> Sample:
        return Sample(
            input=f"Does the file '{file}' exist? Answer {SUCCESS} or {NOT_FOUND}",
            target=target,
            metadata={"file": file},
            setup=setup,
        )

    dataset = [
        sample("foo.txt", SUCCESS, sandbox_setup),
        sample("bar.txt", NOT_FOUND, sandbox_setup),
        sample("foo.txt", SUCCESS, SANDBOX_SETUP_FILE),
        sample("bar.txt", NOT_FOUND, SANDBOX_SETUP_FILE),
    ]

    task = Task(
        dataset=dataset,
        solver=check_file(),
        scorer=includes(),
        sandbox="docker",
    )

    log = eval(task, model="mockllm/model")[0]

    assert log.samples
    for sample in log.samples:
        assert sample.scores["includes"].value == CORRECT


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_setup_symlink():
    def sample(file: str, target: str, setup: str) -> Sample:
        return Sample(
            input=f"Does the file '{file}' exist? Answer {SUCCESS} or {NOT_FOUND}",
            target=target,
            metadata={"file": file},
            setup=setup,
        )

    dataset = [
        sample("link_simple", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("link_dot_slash", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/link_up_one", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/inner/link_up_two", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("link_absolute", SUCCESS, SANDBOX_SETUP_SYMLINK_FILE),
        sample("missing_simple", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("missing_dot_slash", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/missing_up_one", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("nested/inner/missing_up_two", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
        sample("missing_absolute", NOT_FOUND, SANDBOX_SETUP_SYMLINK_FILE),
    ]

    task = Task(
        dataset=dataset,
        solver=check_file(expected_content="hello world"),
        scorer=includes(),
        sandbox="docker",
    )

    log = eval(task, model="mockllm/model")[0]

    assert log.samples
    for sample in log.samples:
        assert sample.scores["includes"].value == CORRECT, (
            f"Failure for '{sample.metadata['file']}': {sample.scores['includes'].answer}'"
        )


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_setup_fail_on_error():
    task = Task(
        dataset=[
            Sample(input="Say hello.", setup=SANDBOX_SETUP_ERROR_FILE),
            Sample(input="Say hello.", setup=SANDBOX_SETUP_FILE),
        ],
        sandbox="docker",
    )

    # fail_on_error=True (entire eval fails)
    log = eval(task, model="mockllm/model", fail_on_error=True)[0]
    assert log.status == "error"

    # fail_on_error=False (sample fails not entire eval)
    log = eval(task, model="mockllm/model", fail_on_error=False)[0]
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].error
    assert not log.samples[1].error

    # fail_on_error=True, continue_on_fail=True (entire eval fails, but all samples are evaluated)
    log = eval(task, model="mockllm/model", fail_on_error=True, continue_on_fail=True)[
        0
    ]
    assert log.status == "error"
    assert log.samples
    assert log.samples[0].error
    assert not log.samples[1].error


class HangingSetupSandbox(SandboxEnvironment):
    """Sandbox whose ``exec`` blocks until the sample is cancelled.

    ``sample_init`` records the environment it creates in ``created``; ``exec``
    sets ``started`` and then waits forever, so a test can cancel from inside the
    setup-script phase; ``sample_cleanup`` crosses a cancellation checkpoint, as
    a real provider's cleanup does, and then records its ``environments`` and
    ``interrupted`` arguments in ``cleanups``. A test calls ``reset()`` first
    (inside the event loop, as it creates an ``anyio.Event``).
    """

    started: ClassVar[anyio.Event]
    created: ClassVar[list[SandboxEnvironment]]
    cleanups: ClassVar[list[tuple[dict[str, SandboxEnvironment], bool]]]

    @classmethod
    def reset(cls) -> None:
        cls.started = anyio.Event()
        cls.created = []
        cls.cleanups = []

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        environment = cls()
        cls.created.append(environment)
        return {"default": environment}

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        await anyio.lowlevel.checkpoint()
        cls.cleanups.append((environments, interrupted))

    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.started.set()
        await anyio.sleep_forever()
        raise AssertionError("sleep_forever() returned")

    async def write_file(self, file: str, contents: str | bytes) -> None:
        pass

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        raise NotImplementedError


class HangingCopySandbox(HangingSetupSandbox):
    """Variant whose ``write_file`` blocks, to cancel from inside the file-copy phase."""

    async def write_file(self, file: str, contents: str | bytes) -> None:
        self.started.set()
        await anyio.sleep_forever()


@pytest.mark.parametrize(
    ("sandbox_type", "files"),
    [
        pytest.param(HangingSetupSandbox, {}, id="setup-script"),
        pytest.param(HangingCopySandbox, {"file.txt": b"contents"}, id="file-copy"),
    ],
)
async def test_sandbox_setup_cancelled_cleans_up_sample(
    sandbox_type: type[HangingSetupSandbox], files: dict[str, bytes]
) -> None:
    """Cancelling a sample during file copy or its setup script still tears its sandbox down.

    Cancellation is not an ``Exception``, so it must get its own cleanup path in
    ``init_sandbox_environments_sample``: the caller only cleans up environments
    it was handed, and init never returns them when it is cancelled. That
    cleanup must also be shielded, or the cancellation that triggered it would
    interrupt it at its first checkpoint.
    """
    sandbox_type.reset()

    async def cancel_once_setup_started(scope: anyio.CancelScope) -> None:
        await sandbox_type.started.wait()
        scope.cancel()

    async with anyio.create_task_group() as tg:
        tg.start_soon(cancel_once_setup_started, tg.cancel_scope)
        with pytest.raises(anyio.get_cancelled_exc_class()):
            await init_sandbox_environments_sample(
                sandboxenv_type=sandbox_type,
                task_name="task",
                config=None,
                files=files,
                setup=b"#!/usr/bin/env bash\n\ntrue\n",
                metadata={},
            )

    assert len(sandbox_type.created) == 1
    assert sandbox_type.cleanups == [({"default": sandbox_type.created[0]}, True)]


def test_is_dockerfile():
    assert is_dockerfile("/path/to/Dockerfile")
    assert is_dockerfile("/path/to/name.Dockerfile")
    assert is_dockerfile("/path/to/Dockerfile.name")
    assert not is_dockerfile("/path/to/Dockerfile-name")
    assert not is_dockerfile("/path/to/Dockerfile_name")
    assert not is_dockerfile("/path/to/name-Dockerfile")
    assert not is_dockerfile("/path/to/name_Dockerfile")
    assert not is_dockerfile("/path/to/docker-compose.yaml")
    assert not is_dockerfile("/path/to/not_a_dockerfile.txt")


if __name__ == "__main__":
    test_docker_sandbox_setup()
