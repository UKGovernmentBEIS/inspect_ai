import os
import json
from glob import glob

from inspect_ai.dataset import Sample

DATA_DIR = "data"
SOLUTION_SIGNATURE = "## Possible solution"


def get_task_sample(task_name: str) -> Sample:
    with open(f"{DATA_DIR}/{task_name}/task.json") as json_file:
        record = json.load(json_file)

    task_id = record["challenge_name"]
    task_assets = f"{DATA_DIR}/{task_id}"
    task_files = [
        os.path.relpath(file, DATA_DIR)
        for file in glob(f"{task_assets}/**/*")
    ]
    files = {os.path.basename(file): file for file in task_files}

    # read solution
    with open(f"{task_assets}/README.md") as f:
        readme = f.read()

    solution = ""
    if SOLUTION_SIGNATURE in readme:
        solution = readme.split(SOLUTION_SIGNATURE)[1].strip("\n")

    # return sample
    return Sample(
        id=task_id,
        input=record["prompts"],
        target=record["flag"],
        metadata={
            "challenge_address": record["challenge_address"],
            "solution": solution,
        },
        files=files,
    )
