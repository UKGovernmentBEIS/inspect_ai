"""This is a utility script which installs all of the environment images for the SWE-bench dataset. These images contain all of the dependencies required to run the tests in the dataset."""

import argparse
import json
import os

from docker.client import DockerClient  # type: ignore
from swe_bench import SAMPLE_TO_IMAGE_PATH  # type: ignore
from swebench.harness.docker_build import build_env_images  # type: ignore
from swebench.harness.test_spec import get_test_specs_from_dataset, make_test_spec  # type: ignore
from swebench.harness.utils import load_swebench_dataset  # type: ignore
from datasets import load_dataset
from inspect_ai.dataset import Sample


def build_images_for_samples(
    sample: list[Sample],
    max_workers: int = 4,
    force_rebuild=False,
) -> dict[str, str]:
    """This function uses the swe_bench library to build the docker images for the SWE-bench dataset.

    Args:
        dataset_name (str): The name of the huggingface dataset to build images for. Can be a local path or the name of a dataset on the huggingface hub.
        split (str, optional): The split of the dataset to build images for. Defaults to None.
        max_workers (int, optional): The maximum number of workers to use for building images. Defaults to 4.
        force_rebuild (bool, optional): Whether to force a rebuild of the images. Defaults to False.
    """
    # Code copied from the swe_bench repository
    docker_client = DockerClient.from_env()

    # The swebench library requires a huggingface version of the code to be loaded in order to build the images. We load the dataset and then use the library to build the images.
    samples_hf = [sample_to_hf(s) for s in sample]

    # We also keep a mapping from instance_ids to the name of the docker image
    id_to_docker_image = {}
    for swebench_instance in samples_hf:
        docker_image_name = make_test_spec(swebench_instance).env_image_key
        id_to_docker_image[swebench_instance["instance_id"]] = docker_image_name

    # Build the images
    available_docker_images = [image.tags[0] for image in docker_client.images.list()]
    samples_to_build_images_for = [
        s
        for s in samples_hf
        if id_to_docker_image[s["instance_id"]] not in available_docker_images
    ]

    if len(samples_to_build_images_for) > 0:
        print(
            f"BUILDING SWE-BENCH IMAGES. NOTE: This can take a long time - up to several hours for the full dataset."
        )
        build_env_images(docker_client, samples_hf, force_rebuild, max_workers)

    # Check that all the images were built
    available_docker_images = [image.tags[0] for image in docker_client.images.list()]
    assert all(
        [
            id_to_docker_image[s["instance_id"]] in available_docker_images
            for s in samples_hf
        ]
    ), "Not all images were built"

    return id_to_docker_image


def sample_to_hf(sample: Sample) -> dict[str, str]:
    return {
        "instance_id": sample.id,
        "patch": sample.metadata["patch"],
        "PASS_TO_PASS": sample.metadata["PASS_TO_PASS"],
        "FAIL_TO_PASS": sample.metadata["FAIL_TO_PASS"],
        "test_patch": sample.metadata["test_patch"],
        "version": sample.metadata["version"],
        "repo": sample.metadata["repo"],
        "environment_setup_commit": sample.metadata["environment_setup_commit"],
    }
