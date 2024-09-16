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

# TODO: The constants actaully make thins a bit uglier, I'd love it if people were like "wow look at how clean it is to onboard the dataset"
INPUT_PROMPT = """Please answer the question below. You should:

- Return only your answer, which should be a number, or a short phrase with as few words as possible, or a comma separated list of numbers and/or strings.
- If the answer is a number, return only the number without any units unless specified otherwise.
- If the answer is a string, don't include articles, and don't use abbreviations (e.g. for states).
- If the answer is a comma separated list, apply the above rules to each element in the list.

Any files mentioned in the question can be found in your home directory. Here is the question:

{question}"""

#TODO: This is a little awkward, since initalizing the web search tool requires you to have an API key, but I don't want to force people to have to download that
DEFAULT_PLAN = basic_agent(
    init=system_message(
        "Please solve the coding task below. Once you are done, use your submit tool."
    ),
    tools=[ bash()], # + [web_search()] 
)

GAIA_DATASET_LOCATION = Path(__file__).parent / "resources" / "GAIA"


@task
def gaia(
    plan=DEFAULT_PLAN,
    split: Literal["test", "validation"] = "validation",
    filter: Callable[Sample, bool] = lambda x: True,
) -> Task:
    # TODO: Is this the right interface?
    dataset = hf_dataset(
        GAIA_DATASET_LOCATION,
        split=split,
        sample_fields=FieldSpec(
            input="Question",
            target="Final answer",
            id="task_id",
            metadata=["file_name", "Annotator Metadata"],
        ),
    )

    dataset = dataset.filter(filter)

    add_gaia_files(dataset, split)

    return Task(dataset=dataset, plan=plan, scorer=match(), sandbox="docker")


def add_gaia_files(dataset: list[Sample], split: str) -> None:
    files = GAIA_DATASET_LOCATION / "2024" / split
    for sample in dataset:
        sample.input = INPUT_PROMPT.format(question=sample.input)

        # Setup files into the sample
        file = next([file for file in os.listdir(files) if sample.id in file], None)
        if file:
            sample.files = {file: str((files / file))}


if not GAIA_DATASET_LOCATION.exists():
    snapshot_download(
        repo_id="gaia-benchmark/GAIA",
        repo_type="dataset",
        local_dir=GAIA_DATASET_LOCATION.parent,
    )

gaia()