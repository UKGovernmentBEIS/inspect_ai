from huggingface_hub import snapshot_download
from pathlib import Path
from inspect_ai import task
from inspect_ai.scorer import Score, match
from inspect_ai.solver import basic_agent, system_message, TaskState
from inspect_ai.tool import web_search, bash
from inspect_ai.scorer import scorer, Target
from inspect_ai.dataset import Sample, hf_dataset
from typing import Callable, Literal
from inspect_ai import Task
from inspect_ai.dataset._dataset import FieldSpec
import os
from typing import Sequence

# TODO: The constants actaully make thins a bit uglier, I'd love it if people were like "wow look at how clean it is to onboard the dataset"
DEFAULT_INPUT_PROMPT = """Please answer the question below. You should:

- Return only your answer, which should be a number, or a short phrase with as few words as possible, or a comma separated list of numbers and/or strings.
- If the answer is a number, return only the number without any units unless specified otherwise.
- If the answer is a string, don't include articles, and don't use abbreviations (e.g. for states).
- If the answer is a comma separated list, apply the above rules to each element in the list.

Any files or attachments mentioned in the question can be found in your home directory (some questions do not have associated files). Here is the question:

{question}"""

# TODO: This is a little awkward, since initalizing the web search tool requires you to have an API key, but I don't want to force people to have to download that
DEFAULT_PLAN = basic_agent(
    init=system_message(
        "Please solve the coding task below. Once you are done, use your submit tool."
    ),
    tools=[bash()],  # + [web_search()]
)

GAIA_DATASET_LOCATION = Path(__file__).parent / "resources" / "GAIA"
GAIA_SUBSETS = ["2023_all", "2023_level1", "2023_level2", "2023_level3"]


@task
def gaia(
    plan=DEFAULT_PLAN,
    split: Literal["test", "validation"] = "validation",
    subset: Literal[*GAIA_SUBSETS] = "2023_all",
    filter: Callable[Sample, bool] = lambda x: True,
    input_prompt: str = DEFAULT_INPUT_PROMPT,
    max_messages: int = 30,
) -> Task:
    # TODO: Is this the right interface?
    dataset = hf_dataset(
        str(GAIA_DATASET_LOCATION),
        split=split,
        sample_fields=FieldSpec(
            input="Question",
            target="Final answer",
            id="task_id",
            metadata=["file_name", "Annotator Metadata"],
        ),
        trust=True,  # Trust GAIA's remote code execution during dataset loading
        name=subset,
    )

    dataset = dataset.filter(filter)

    for sample in dataset:
        sample.input = input_prompt.format(question=sample.input)

    add_gaia_files(dataset, split)

    return Task(
        dataset=dataset,
        plan=plan,
        scorer=match() if split == "validation" else None,  # Test split has no answers
        sandbox="docker",
        max_messages=max_messages,
    )


def add_gaia_files(dataset: Sequence[Sample], split: str) -> None:
    files = GAIA_DATASET_LOCATION / "2023" / split
    for sample in dataset:
        # Setup files into the sample
        file = next((file for file in os.listdir(files) if sample.id in file), None)
        if file:
            sample.files = {file: str((files / file))}


if not Path(GAIA_DATASET_LOCATION).exists():
    GAIA_DATASET_LOCATION.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id="gaia-benchmark/GAIA",
        repo_type="dataset",
        local_dir=GAIA_DATASET_LOCATION,
    )
