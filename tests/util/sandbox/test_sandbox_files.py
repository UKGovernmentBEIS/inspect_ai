from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import MemoryDataset
from inspect_ai.solver._solver import Solver, solver
from inspect_ai.util._sandbox.context import sandbox

FILES_DIR = Path(__file__).parent / "test_sandbox_files"


@skip_if_no_docker
@pytest.mark.slow
def test_docker_sandbox_files_dir() -> None:
    def check_sandbox_files_dir(files_dir: Path) -> None:
        files = {files_dir.name: files_dir.as_posix()}
        dataset = MemoryDataset([Sample(input="Here are some files", files=files)])

        task = Task(
            dataset=dataset,
            solver=[verify_files(files_dir)],
            sandbox="docker",
        )

        log = eval(task, model="mockllm/model")[0]
        assert log.status == "success"

    check_sandbox_files_dir(FILES_DIR / "dir1")
    check_sandbox_files_dir(FILES_DIR / "dir1" / "dirA")


@solver
def verify_files(files_dir: Path) -> Solver:
    # list of relative file paths
    relative_paths = [
        f"{files_dir.name}/{str(path.relative_to(files_dir))}"
        for path in files_dir.rglob("*")
        if path.is_file()
    ]

    async def solve(state, generate):
        for path in relative_paths:
            try:
                await sandbox().read_file(path)
            except FileNotFoundError:
                assert False

        return state

    return solve
