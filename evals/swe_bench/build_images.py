"""This is a utility script which installs all of the environment images for the SWE-bench dataset. These images contain all of the dependencies required to run the tests in the dataset."""

import argparse
import json
import os

from docker.client import DockerClient  # type: ignore
from swe_bench import SAMPLE_TO_IMAGE_PATH  # type: ignore
from swebench.harness.docker_build import build_env_images  # type: ignore
from swebench.harness.test_spec import get_test_specs_from_dataset  # type: ignore
from swebench.harness.utils import load_swebench_dataset  # type: ignore


def build_images(
    dataset_name: str,
    split: str | None = None,
    max_workers: int = 4,
    force_rebuild=False,
) -> None:
    """This function uses the swe_bench library to build the docker images for the SWE-bench dataset.

    Args:
        dataset_name (str): The name of the huggingface dataset to build images for. Can be a local path or the name of a dataset on the huggingface hub.
        split (str, optional): The split of the dataset to build images for. Defaults to None.
        max_workers (int, optional): The maximum number of workers to use for building images. Defaults to 4.
        force_rebuild (bool, optional): Whether to force a rebuild of the images. Defaults to False.
    """
    # Code copied from the swe_bench repository
    docker_client = DockerClient.from_env()
    swebench_dataset = load_swebench_dataset(dataset_name, split)

    # We then use a couple of internal functions from swebench to build the environment images
    test_specs = get_test_specs_from_dataset(swebench_dataset)
    build_env_images(docker_client, swebench_dataset, force_rebuild, max_workers)

    # We build a mapping of insance_ids and envirnoment_commits to the name of the docker images. This is used to find the images in our main swe_bench code
    environment_name_mapping = (
        {}
        if not os.path.exists(SAMPLE_TO_IMAGE_PATH)
        else json.load(open(SAMPLE_TO_IMAGE_PATH))
    )

    for spec, swebench_instance in zip(test_specs, swebench_dataset):
        assert spec.env_image_key in [
            image_tag
            for image in docker_client.images.list()
            for image_tag in image.tags
        ], f"Image {spec.env_image_key} not found in docker images"
        # Check if entry already exists
        if swebench_instance["instance_id"] not in environment_name_mapping:
            environment_name_mapping[swebench_instance["instance_id"]] = {}
            if (
                swebench_instance["environment_setup_commit"]
                in environment_name_mapping[swebench_instance["instance_id"]]
            ):
                assert (
                    environment_name_mapping[swebench_instance["instance_id"]][
                        swebench_instance["environment_setup_commit"]
                    ]["image_key"]
                    == spec.env_image_key
                ), f"Image {spec.env_image_key} already mapped to a different image"
            else:
                environment_name_mapping[swebench_instance["instance_id"]][
                    swebench_instance["environment_setup_commit"]
                ] = {
                    "image_key": spec.env_image_key,
                    "env_setup_script": "\n".join(spec.env_script_list),
                }

    # Add the mappings to a file
    json.dump(environment_name_mapping, open(SAMPLE_TO_IMAGE_PATH, "w+"), indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build environment images for SWE-bench"
    )

    parser.add_argument(
        "--dataset_path",
        type=str,
        help="Name of the dataset to build images for",
        required=False,
        default="princeton-nlp/SWE-bench_Verified",
    )

    parser.add_argument(
        "--split",
        type=str,
        help="Split of the dataset to build images for",
        required=False,
        default="test",
    )

    parser.add_argument(
        "--max_workers",
        type=int,
        help="Maximum number of workers to use for building images",
        required=False,
        default=4,
    )

    parser.add_argument(
        "--force_rebuild",
        action="store_true",
        help="Force rebuild of images",
        required=False,
        default=False,
    )

    args = parser.parse_args()
    build_images(args.dataset_path, args.split, args.max_workers, args.force_rebuild)
