import os
from glob import glob

from inspect_ai.dataset import Dataset, Sample, json_dataset

DATA_DIR = "data"
SOLUTION_SIGNATURE = "## Possible solution"


def read_dataset(config_name: str, shuffle: bool=False, challenges: list[str]=[]) -> Dataset:
    """Reads a dataset from a challenges.json file."""
    # record to sample
    def record_to_sample(record):
        # collect files
        task_id = record["challenge_name"]
        task_assets = f"{DATA_DIR}/{task_id}"
        task_files = [
            os.path.relpath(f, task_assets)
            for f in glob(os.path.join(task_assets, '**'), recursive=True)
            if os.path.isfile(f)
        ]
        files = {os.path.basename(file): file for file in task_files}

        # read solution
        with open(f"{task_assets}/README.md") as f:
            readme = f.read()

        solution = ""
        if SOLUTION_SIGNATURE in readme:
            solution = readme.split(SOLUTION_SIGNATURE)[1].strip("\n")

        return Sample(
            id=task_id,
            input=record["prompts"],
            metadata={
                "challenge_address": record["challenge_address"],
                "objective_prompt": record["prompts"],
                "solution": solution,
                "get_flag_cmd": record["get_flag_cmd"],
            },
            files=files,
            sandbox=("docker", f"{task_assets}/compose.yaml"),
        )

    dataset = json_dataset(
        json_file=f"{DATA_DIR}/{config_name}.json",
        sample_fields=record_to_sample,
        shuffle=shuffle,
    )

    # challenges is empty by default, return all challenges
    if challenges:
        return dataset.filter(lambda x: x.id in challenges)
    return dataset
