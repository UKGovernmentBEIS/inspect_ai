from pathlib import Path

from inspect_ai import Task, eval
from inspect_ai.agent._human.agent import human_cli
from inspect_ai.agent._react import react
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import MemoryDataset
from inspect_ai.tool._tools._execute import bash

FILES_DIR = Path(__name__).parent / "test_sandbox_files"


# @skip_if_no_docker
# @pytest.mark.slow
def test_docker_sandbox_files() -> None:
    dataset = MemoryDataset(
        [
            Sample(
                input="Is there a directory named 'dir1' in the working directory? What are its contents?",
                files={"dir1": (FILES_DIR / "dir1").as_posix()},
            )
        ]
    )

    task = Task(
        dataset=dataset,
        solver=react(tools=[bash()]),
        sandbox="docker",
    )

    eval(task, model="openai/gpt-4o", solver=human_cli())[0]


if __name__ == "__main__":
    test_docker_sandbox_files()
