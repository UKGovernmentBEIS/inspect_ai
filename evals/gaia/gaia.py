from huggingface_hub import snapshot_download
from pathlib import Path
from evals.drop.drop import sample_to_fewshot
from inspect_ai import task
from inspect_ai.scorer import Score, match
from inspect_ai.solver import basic_agent, system_message, TaskState, Plan
from inspect_ai.tool import web_search, bash
from inspect_ai.scorer import scorer, Target
from inspect_ai.dataset import Sample, hf_dataset
from typing import Callable, Literal
from inspect_ai import Task
from inspect_ai.dataset._dataset import FieldSpec
import os
from typing import Sequence, Any

GAIA_DATASET_LOCATION = Path(__file__).parent / "resources" / "GAIA"
GAIA_SUBSETS = ["2023_all", "2023_level1", "2023_level2", "2023_level3"]


@task
def gaia(
    plan: Plan | None = None,
    split: Literal["test", "validation"] = "validation",
    subset: Literal[*GAIA_SUBSETS] = "2023_all",
    filter: Callable[Sample, bool] = lambda x: True,
    input_prompt: str = None,
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
    files = GAIA_DATASET_LOCATION / "2023" / split

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
        file = next((file for file in os.listdir(files) if sample.id in file), None)
        if file:
            sample.files = {"/shared_files/" + file: str((files / file))}

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
