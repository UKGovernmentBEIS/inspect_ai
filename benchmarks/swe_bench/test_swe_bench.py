import json
import shlex
from pathlib import Path

from build_docker_images import build_docker_images
from docker import DockerClient
from swe_bench import SAMPLE_TO_IMAGE_PATH, swe_bench

from inspect_ai import eval
from inspect_ai.model import ModelOutput, get_model

INFRASTRUCTURE_DIR = Path(__file__).parent / "resources"
TIMEOUT_SECONDS = 2
INSTANCE_ID = "pvlib__pvlib-python-1854"
TEST_DATASET = INFRASTRUCTURE_DIR / "swebench_one_sample.hf"
TEST_DATASET_SPLIT = "train"
ENVIRONMENT_COMMIT =  "6072e0982c3c0236f532ddfa48fbf461180d834e"
CORRECT_IMAGE_NAME = "sweb.env.x86_64.257e69677081e19b89fe2d:latest"

def build_test_image():
    build_docker_images(
        dataset_name= str(TEST_DATASET),
        split="train",
        max_workers=4
    )

def test_build_docker() -> None:
    # This is a slow test

    docker_client = DockerClient.from_env()

    # We remove the image if its already been built
    all_images = docker_client.images.list()
    for image in all_images:
        if CORRECT_IMAGE_NAME in image.tags:
            docker_client.images.remove(image.id, force=True)
            print(f"Removed image {CORRECT_IMAGE_NAME}.")

    # We check that the image has been built
    image_name = json.load(open(SAMPLE_TO_IMAGE_PATH))[INSTANCE_ID][ENVIRONMENT_COMMIT]
    assert image_name == CORRECT_IMAGE_NAME, "Image name should match the ground truth image name."
    assert image_name in [image.tags[0] for image in DockerClient.from_env().images.list()], "Image name should be in the list of built images."


def test_golden_patch_succeeds() -> None:

    build_test_image()

    swe_bench_task = swe_bench(instance_id="pvlib__pvlib-python-1854",dataset_name=str(TEST_DATASET), split=TEST_DATASET_SPLIT)
    golden_patch = swe_bench_task.dataset[0].metadata["patch"]

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash",
                tool_arguments={
                    "code": f"echo {shlex.quote(golden_patch)} >patch.diff"
                },  # Used to confirm that code is executed
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash",
                tool_arguments={
                    "code": "cd /testbed/;git apply /root/patch.diff"
                },  # Use to confirm that state is maintained
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit_answer",
                tool_arguments={"submission": "N/A"},  # Used to finish the task
            ),
        ],
    )

    result = eval(
        swe_bench_task,
        model,
        log_level="INFO",
    )[0]

    result.results.scores[0].metrics["mean"].value == 1.0, "SWE-bench should mark a correct application successfully."


def test_incorrect_edit_fails() -> None:

    build_test_image()

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash",
                tool_arguments={
                    "code": "rm /testbed/README.md"}),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit_answer",
                tool_arguments={"submission": "N/A"},  # Used to finish the task
            ),
        ],
    )

    result = eval(
        swe_bench(instance_id="pvlib__pvlib-python-1854",dataset_name=str(TEST_DATASET),split=TEST_DATASET_SPLIT),
        model,
        log_level="INFO",
    )[0]

    assert result.results.scores[0].metrics["mean"].value == 0.0, "SWE-bench should mark an incorrect application as a failure."

test_golden_patch_succeeds()
