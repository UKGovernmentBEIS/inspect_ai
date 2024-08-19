from pathlib import Path

from inspect_ai import eval
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model

from agent_framework.experimental.tools import (
    ipython_tool,
)
from agent_framework.integration.inspect import AgentFrameworkError
from agent_framework.tools import (
    submit_answer_tool,
)
from swebench import swe_bench
from agent_framework.experimental.agents.base_aisi_agent import base_aisi_agent
from agent_framework.tools import submit_answer_tool
from agent_framework.tools import bash_tool
import shlex

INFRASTRUCTURE_DIR = Path(__file__).parent / "resources"
TIMEOUT_SECONDS = 2
GOLDEN_PATCH = """diff --git a/pvlib/pvsystem.py b/pvlib/pvsystem.py --- a/pvlib/pvsystem.py +++ b/pvlib/pvsystem.py @@ -101,10 +101,11 @@ class PVSystem: Parameters ---------- - arrays : iterable of Array, optional - List of arrays that are part of the system. If not specified - a single array is created from the other parameters (e.g. - `surface_tilt`, `surface_azimuth`). Must contain at least one Array, + arrays : Array or iterable of Array, optional + An Array or list of arrays that are part of the system. If not + specified a single array is created from the other parameters (e.g. + `surface_tilt`, `surface_azimuth`). If specified as a list, the list + must contain at least one Array; if length of arrays is 0 a ValueError is raised. If `arrays` is specified the following PVSystem parameters are ignored: @@ -220,6 +221,8 @@ def __init__(self, strings_per_inverter, array_losses_parameters, ),) + elif isinstance(arrays, Array): + self.arrays = (arrays,) elif len(arrays) == 0: raise ValueError("PVSystem must have at least one Array. " "If you want to create a PVSystem instance """

def test_golden_patch_correct() -> None:


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
        swe_bench(),
        model,
        log_level="INFO",
    )[0]

    model_patch = result.samples[0].scores["swebench_scorer"].metadata["model_patch"]
    assert "PVSystem must have at least one Array." in model_patch

test_golden_patch_correct()