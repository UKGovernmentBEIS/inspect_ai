from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import CORRECT, includes
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox
from inspect_ai.util._sandbox.docker.config import is_dockerfile

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
        dataset=[Sample(input="Say hello.", setup=SANDBOX_SETUP_ERROR_FILE)],
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
