import os
import shutil
import zipfile
from glob import glob

import requests

from inspect_ai.dataset import Sample, json_dataset

DATA_DIR = "data"
SOLUTION_SIGNATURE = "## Possible solution"


def read_dataset(shuffle=False, force_download=False):

    # record to sample
    def record_to_sample(record):
        # collect files
        task_id = record["challenge_name"]
        task_assets = f"{DATA_DIR}/{task_id}"
        task_files = [
            os.path.relpath(file, DATA_DIR)
            for file in glob(f"{task_assets}/**/*")
            # if os.path.isfile(file)
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
            input=record["prompts"]["hard"],
            target=record["flag"],
            metadata={
                "setup": record.get("setup", None),
                "agent": record["attacker_job"],
                "challenge": record["victim_jobs"],
                "challenge_address": record["challenge_address"],
                "solution": solution,
            },
            files=files,
        )

    # read dataset. we filter out samples that required internet access, as
    # is also done in the GDM paper (https://arxiv.org/pdf/2403.13793)
    return json_dataset(
        json_file=f"{DATA_DIR}/challenges.json",
        sample_fields=record_to_sample,
        shuffle=shuffle,
    )
