import os
import shutil
from pathlib import Path
from typing import Any, Callable, Literal

from huggingface_hub import snapshot_download  # type: ignore
from platformdirs import user_cache_dir

from inspect_ai import Task, task
from inspect_ai.dataset import Dataset, Sample, hf_dataset
from inspect_ai.scorer import match
from inspect_ai.solver import Solver, basic_agent, system_message
from inspect_ai.tool import bash, web_search


@task
def gaia(
    solver: Solver | None = None,
    input_prompt: str | None = None,
    max_messages: int = 30,
    subset: Literal[
        "2023_all", "2023_level1", "2023_level2", "2023_level3"
    ] = "2023_all",
    split: Literal["test", "validation"] = "validation",
    instance_ids: list[str] | None = None,
) -> Task:
    # read dataset
    dataset = gaia_dataset(
        input_prompt=input_prompt or DEFAULT_INPUT_PROMPT,
        subset=subset,
        split=split,
    )

    if instance_ids:
        dataset = dataset.filter(lambda x: x.id in instance_ids)

    # provide default plan if required
    if solver is None:
        solver = basic_agent(
            init=system_message(
                "Please solve the coding task below. Once you are done, "
                + "use the submit() tool to provide your answer."
            ),
            tools=[bash(), web_search()],
        )

    # resolve scorer (test split has no answers)
    scorer = match() if split == "validation" else None

    # docker compose file is alongside
    COMPOSE_FILE = Path(__file__).parent / "compose.yaml"

    # return task
    return Task(
        dataset=dataset,
        plan=solver,
        scorer=scorer,
        sandbox=("docker", COMPOSE_FILE.as_posix()),
        max_messages=max_messages,
    )


DEFAULT_INPUT_PROMPT = """Please answer the question below. You should:

- Return only your answer, which should be a number, or a short phrase with as
  few words as possible, or a comma separated list of numbers and/or strings.
- If the answer is a number, return only the number without any units unless
  specified otherwise.
- If the answer is a string, don't include articles, and don't use
  abbreviations (e.g. for states).
- If the answer is a comma separated list, apply the above rules to each
  element in the list.

Any files or attachments mentioned in the question can be found in the
/shared_files/ directory (some questions do not have associated files). Here
is the question:

{question}"""


def gaia_dataset(
    input_prompt: str,
    subset: str,
    split: str,
    filter: Callable[[Sample], bool] = lambda x: True,
) -> Dataset:
    # use user cache dir for dataset
    GAIA_DATASET_LOCATION = (
        Path(user_cache_dir("inspect_evals")) / "gaia_dataset" / "GAIA"
    )

    # download dataset if required
    if not os.path.exists(GAIA_DATASET_LOCATION):
        GAIA_DATASET_LOCATION.mkdir(parents=True, exist_ok=True)
        try:
            snapshot_download(
                repo_id="gaia-benchmark/GAIA",
                repo_type="dataset",
                local_dir=GAIA_DATASET_LOCATION,
            )
        except Exception as ex:
            shutil.rmtree(GAIA_DATASET_LOCATION, True)
            raise ex

    # map record to sample
    def record_to_sample(record: dict[str, Any]) -> Sample:
        # map fields
        sample = Sample(
            input=input_prompt.format(question=record["Question"]),
            target=record["Final answer"],
            id=record["task_id"],
            metadata={
                "level": record["Level"],
                "Annotator Metadata": record["Annotator Metadata"],
            },
            setup="mkdir -p /shared_files/",
        )

        # apply input prompt
        sample.input = input_prompt.format(question=sample.input)

        # provide sample files
        files_location = GAIA_DATASET_LOCATION / "2023" / split
        files = [file for file in os.listdir(files_location) if str(sample.id) in file]
        if len(files) > 0:
            sample.files = {
                "/shared_files/" + files[0]: (files_location / files[0]).as_posix()
            }

        return sample

    # read dataset
    dataset = hf_dataset(
        GAIA_DATASET_LOCATION.as_posix(),
        name=subset,
        split=split,
        sample_fields=record_to_sample,
        trust=True,  # Trust GAIA's remote code execution during dataset loading
    )

    # apply filter (if any) and return
    return dataset.filter(filter)
