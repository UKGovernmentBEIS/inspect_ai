"""SWE-bench: Can Language Models Resolve Real-World GitHub Issues?

Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan
https://arxiv.org/abs/2310.06770
"""

from inspect_ai.solver import Plan
from inspect_ai import Task, eval 
from inspect_ai.solver import TaskState
from inspect_ai.dataset import hf_dataset, Sample, FieldSpec
from typing import Callable
from inspect_ai.scorer import mean, std
from inspect_ai.scorer import Score, Target, scorer, Scorer
from inspect_ai.util import sandbox
from datasets import load_dataset
from agent_framework.experimental.agents.base_aisi_agent import base_aisi_agent
from agent_framework.tools import submit_answer_tool, bash_tool
from swebench.harness.constants import MAP_REPO_VERSION_TO_SPECS
from swebench.harness.utils import get_test_directives
import shlex
import re

INPUT_PROMPT = """
Please solve the following issue:

{issue_text}
"""

def swe_bench(
    instance_id="pvlib__pvlib-python-1854",
    split: str | None = "dev",
    dataset="princeton-nlp/SWE-bench_Lite",
) -> Task:
    
    swebench_dataset = hf_dataset(
        dataset,
        split=split,
        sample_fields=FieldSpec(
            input="problem_statement",
            id="instance_id",
            metadata=["base_commit","patch","test_patch","version","repo","environment_setup_commit","PASS_TO_PASS","FAIL_TO_PASS"],
        )
    )

    swebench_dataset = [sample for sample in swebench_dataset if sample.id == instance_id]
    assert len(swebench_dataset) == 1, f"There should be exactly one sample matching the input instance_id, found {instance_id}"

    # Put the input in context 
    swebench_dataset[0].input = INPUT_PROMPT.format(swebench_dataset[0].input)
    load_environment_images(hf_dataset)

    return Task(
        dataset=swebench_dataset,
        plan=base_aisi_agent(
            tools=[submit_answer_tool(), bash_tool()], max_iterations=5
        ),
        sandbox=(
            "docker",
            "/home/ubuntu/inspect_ai/benchmarks/swe_bench/resources/compose_files/test/compose.yaml",
        ),
        scorer=swebench_scorer()
    )

def load_environment_images(hf_dataset):
    pass

CREATE_MODEL_PATCH = """cd /testbed
git add -A
git diff --cached {base_commit} > model.patch"""

GET_AGENT_PATCH = """cd /testbed/
cat model.patch"""

@scorer(metrics=[mean(), std()])
def swebench_scorer() -> Scorer:

    async def scorer(state: TaskState, target: Target) -> Score:

        # Get the changes the model made, for logging
        await sandbox().exec(["bash","-c",CREATE_MODEL_PATCH.format(base_commit=state.metadata["base_commit"])])
        agent_patch = await sandbox().exec(["bash","-c",GET_AGENT_PATCH])

        # Run the evaluation script
        eval_script = get_eval_script(test_patch=state.metadata["test_patch"], repo=state.metadata["repo"],version=state.metadata["version"],base_commit=state.metadata["base_commit"])
        eval_output = await sandbox().exec(["bash","-c",eval_script])

        return Score(value=0.0,explanation=eval_output.stdout,metadata={"model_patch":agent_patch.stdout})
    
    return scorer


def get_eval_script(test_patch :str , repo :str, version : str, base_commit : str) -> str:

    #First we fetch the repository-specific 'specification' which SWE-bench provides 
    conda_env="testbed"
    repo_directory=f"/testbed"

    # Fetch the command which runs the test. Often simply the string 'pytest'
    test_command = MAP_REPO_VERSION_TO_SPECS[repo][version]["test_cmd"]
    
    # Fetch any repo-specific setup commands, e.g. any environment variables
    eval_setup_commands = MAP_REPO_VERSION_TO_SPECS[repo][version].get("eval_commands",[])
    
    # Find all the files which have been modified by the test patch
    test_patch_files = re.findall(r"--- a/(.*)", test_patch)

    #Find all the files which contain tests. Ugly interface is due to swebench
    test_files = get_test_directives({"repo":repo,"test_patch":test_patch}) #type: ignore

    # Reset test files to the state they should be in before the patch.
    eval_script = f"""set -euox pipefail
#We switch to the repository and activate the environment needed to run the tests
cd {repo_directory}
source /opt/miniconda3/bin/activate
conda activate {conda_env}

#We run all of the repo-specific setup commands (If they)
{"\n".join(eval_setup_commands)}

#We make sure we're back in the correct environment, in case the repo setup created issues
cd {repo_directory}
source /opt/miniconda3/bin/activate
conda activate {conda_env}

#First we reset all of the files which out test patch touches
git checkout {base_commit} {' '.join(test_patch_files)}

#Then we apply the test patch given to us by SWE-bench, setting up the test we need to run
git apply {shlex.quote(test_patch)}

#Then we run all the tests in the repository.
{test_command} {" ".join(test_files)}"""

    return eval_script