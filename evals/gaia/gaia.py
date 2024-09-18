import os
from pathlib import Path
from typing import Any, Callable, Literal

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import match
from inspect_ai.solver import Plan, basic_agent, system_message
from inspect_ai.tool import bash, web_search

GAIA_DATASET_LOCATION = Path(__file__).parent / "resources" / "GAIA"


@task
def gaia(
    plan: Plan | None = None,
    split: Literal["test", "validation"] = "validation",
    subset: Literal[
        "2023_all", "2023_level1", "2023_level2", "2023_level3"
    ] = "2023_all",
    filter: Callable[[Sample], bool] = lambda x: True,
    input_prompt: str | None = None,
    max_messages: int = 30,
) -> Task:
    if not os.path.exists(GAIA_DATASET_LOCATION):
        raise FileNotFoundError(
            "GAIA dataset not found. Please run 'python dataset.py.' to download the dataset."
        )

    dataset = hf_dataset(
        str(GAIA_DATASET_LOCATION),
        split=split,
        sample_fields=gaia_hf_record_to_sample(input_prompt, split),
        trust=True,  # Trust GAIA's remote code execution during dataset loading
        name=subset,
    )

    dataset = dataset.filter(filter)

    return Task(
        dataset=dataset,
        plan=plan if plan is not None else DEFAULT_PLAN,
        scorer=match() if split == "validation" else None,  # Test split has no answers
        sandbox="docker",
        max_messages=max_messages,
    )


def gaia_hf_record_to_sample(
    input_prompt: str | None, split: str
) -> Callable[[dict[str, Any]], Sample]:
    input_prompt = input_prompt if input_prompt is not None else DEFAULT_INPUT_PROMPT
    files_location = GAIA_DATASET_LOCATION / "2023" / split

    def gaia_hf_record_to_sample(record: dict[str, Any]) -> Sample:
        sample = Sample(
            input=input_prompt.format(question=record["Question"]),
            target=record["Final answer"],
            id=record["task_id"],
            metadata={
                "level": record["level"],
                "Annotator Metadata": record["Annotator Metadata"],
            },
        )

        sample.input = input_prompt.format(question=sample.input)

        # Setup files into the sample
        files = [file for file in os.listdir(files_location) if str(sample.id) in file]
        if len(files) > 0:
            sample.files = {"/shared_files/" + files[0]: str((files / files[0]))}

        return sample

    return gaia_hf_record_to_sample


DEFAULT_INPUT_PROMPT = """Please answer the question below. You should:

- Return only your answer, which should be a number, or a short phrase with as few words as possible, or a comma separated list of numbers and/or strings.
- If the answer is a number, return only the number without any units unless specified otherwise.
- If the answer is a string, don't include articles, and don't use abbreviations (e.g. for states).
- If the answer is a comma separated list, apply the above rules to each element in the list.

Any files or attachments mentioned in the question can be found in the /shared_files/ directory (some questions do not have associated files). Here is the question:

{question}"""

DEFAULT_PLAN = basic_agent(
    init=system_message(
        "Please solve the coding task below. Once you are done, use your submit tool."
    ),
    tools=[bash(), web_search()],
)
