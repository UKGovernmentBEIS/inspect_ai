from pathlib import Path

from benchmarks.swe_bench import build_docker_images
from inspect_ai import eval
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model

from agent_framework.experimental.tools import (
    ipython_tool,
)
from agent_framework.integration.inspect import AgentFrameworkError
from agent_framework.tools import (
    submit_answer_tool,
)
from swe_bench import swe_bench
from agent_framework.experimental.agents.base_aisi_agent import base_aisi_agent
from agent_framework.tools import submit_answer_tool
from agent_framework.tools import bash_tool
import shlex 
from build_docker_images import build_docker_images

INFRASTRUCTURE_DIR = Path(__file__).parent / "resources"
TIMEOUT_SECONDS = 2
def test_golden_patch_succeeds() -> None:

    swe_bench_task = swe_bench()
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

    result.results.scores[0].metrics["mean"].value == 1.0, "SWE-bench should mark a  correct application successfully."



def test_incorrect_edit_fails() -> None:

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash",
                tool_arguments={
                    "code": f"rm /testbed/README.md"}),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit_answer",
                tool_arguments={"submission": "N/A"},  # Used to finish the task
            ),
        ],
    )

    result = eval(
        swe_bench(),
        model,
        log_level="INFO",
    )[0]

    assert result.results.scores[0].metrics["mean"].value == 0.0, "SWE-bench should mark an incorrect application as a failure."

TEST_DATASET = INFRASTRUCTURE_DIR / "swebench_one_sample.hf"
TEST_IMAGE_NAME = 
def test_build_docker() -> None:
    build_docker_images(
        dataset_name=TEST_DATASET,
        max_workers=1,
        force_rebuild=True
    )




test_golden_patch_succeeds()
test_incorrect_edit_fails()