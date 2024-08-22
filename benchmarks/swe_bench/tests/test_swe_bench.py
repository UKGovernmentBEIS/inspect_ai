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
    
    build_test_image()

    # We check that the image has been built
    image_name = json.load(open(SAMPLE_TO_IMAGE_PATH))[INSTANCE_ID][ENVIRONMENT_COMMIT]["image_name"]
    assert image_name == CORRECT_IMAGE_NAME, "Image name should match the ground truth image name."
    assert image_name in [image_tag for image in DockerClient.from_env().images.list() for image_tag in image.tags], f"Image name {image_name} should be in the list of built images after running build_docker_images.py."


def test_golden_patch_succeeds() -> None:

    build_test_image()

    swe_bench_task = swe_bench(instance_id="pvlib__pvlib-python-1854",dataset_name=str(TEST_DATASET), split=TEST_DATASET_SPLIT)
    golden_patch = swe_bench_task.dataset[0].metadata["patch"]

    def custom_model_outputs():
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="bash",
            tool_arguments={
                "cmd": f"echo {shlex.quote(golden_patch)} >patch.diff"
            },  # Used to confirm that code is executed
        )
        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="bash",
            tool_arguments={
                "cmd": "cd /testbed/;git apply /root/patch.diff"
            },  # Use to confirm that state is maintained
        )
        while True:
            yield ModelOutput.from_content(model="mockllm/model", content="I've already finished, please stop calling me!", stop_reason="stop")

    model = get_model(
        "mockllm/model",
        custom_outputs=custom_model_outputs(),
    )


    result = eval(
        swe_bench_task,
        model,
        log_level="INFO",
        max_messages=4
    )[0]

    assert result.results.scores[0].metrics["mean"].value == 1.0, "SWE-bench should mark a correct application successfully."

    result = eval(
        swe_bench_task,
        model,
        log_level="INFO",
    )[0]

    result.results.scores[0].metrics["mean"].value == 1.0, "SWE-bench should mark a correct application successfully."


def test_incorrect_patch_fails() -> None:

    build_test_image()

    def custom_model_outputs():

        yield ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="bash",
            tool_arguments={
                "cmd": "rm /testbed/README.md"
            }
        )

        while True:
            yield ModelOutput.from_content(
                model="mockllm/model",
                content="I've already finished, please stop calling me!",
                stop_reason="stop"
            )

    model = get_model(
        "mockllm/model",
        custom_outputs=custom_model_outputs()
    )

    result = eval(
        swe_bench(instance_id="pvlib__pvlib-python-1854",dataset_name=str(TEST_DATASET),split=TEST_DATASET_SPLIT),
        model,
        log_level="INFO",
        max_messages=2
    )[0]

    assert result.results.scores[0].metrics["mean"].value == 0.0, "SWE-bench should mark an incorrect application as a failure."

test_golden_patch_succeeds()
