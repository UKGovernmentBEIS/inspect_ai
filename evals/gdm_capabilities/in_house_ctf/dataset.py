import platform
import sys

from inspect_ai.dataset import Dataset, Sample, json_dataset

DATA_DIR = "challenges"
SOLUTION_SIGNATURE = "## Possible solution"


def read_dataset(challenges: str | list[str] | None = None) -> Dataset:
    """Reads a dataset from a challenges.json file."""

    # record to sample
    def record_to_sample(record):
        # id and assets
        task_id = record["challenge_name"]
        task_assets = f"{DATA_DIR}/{task_id}"

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
                "challenge_type": record["challenge_type"],
                "challenge_address": record["challenge_address"],
                "objective_prompt": record["prompts"],
                "solution": solution,
                "get_flag_cmd": record["get_flag_cmd"],
                "get_flag_service": record["get_flag_service"],
            },
            sandbox=("docker", f"{task_assets}/compose.yaml"),
        )

    dataset = json_dataset(
        json_file=f"{DATA_DIR}/challenges.json", sample_fields=record_to_sample
    )

    # filter if requested
    if challenges:
        # get challenges and validate them
        challenges = challenges if isinstance(challenges, list) else [challenges]
        challenge_ids = [sample.id for sample in dataset]
        invalid_challenges = [c for c in challenges if c not in challenge_ids]
        if invalid_challenges:
            challenge_names = ", ".join(invalid_challenges)
            raise ValueError(f"Invalid challenge names: {challenge_names}")

        # apply filter
        dataset = dataset.filter(lambda x: x.id in challenges)

    # Remove db_3 as we get error when attempting to initialise it
    # TODO: restore db_3 once it is working on ARM macs
    if sys.platform == "darwin" and platform.processor() == "arm":
        dataset = dataset.filter(lambda x: x.id != "db_3")

    return dataset
