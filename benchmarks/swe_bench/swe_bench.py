"""SWE-bench: Can Language Models Resolve Real-World GitHub Issues?

Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan
https://arxiv.org/abs/2310.06770
"""

import json
import os
import re
import shlex
from pathlib import Path
from inspect_ai.dataset import Dataset

from docker import DockerClient
from swebench.harness.constants import (
    APPLY_PATCH_FAIL,
    MAP_REPO_TO_INSTALL,
    MAP_REPO_VERSION_TO_SPECS,
    RESET_FAILED,
    TESTS_ERROR,
    TESTS_TIMEOUT,
)
from swebench.harness.log_parsers import MAP_REPO_TO_PARSER
from swebench.harness.utils import get_test_directives

from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, Sample, hf_dataset
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer, std
from inspect_ai.solver import TaskState, use_tools, system_message, generate
from inspect_ai.tool import bash, python
from inspect_ai.util import sandbox
from datasets import load_dataset
from inspect_ai.solver import Plan, Solver

from typing import Callable



INPUT_PROMPT = "Please solve the following issue:\n\n{issue_text}"
COMPOSE_FILE_DIR = Path(__file__).parent / "resources/compose_files/"
os.makedirs(COMPOSE_FILE_DIR, exist_ok=True)

SAMPLE_TO_IMAGE_PATH = COMPOSE_FILE_DIR / "sample_to_image.json"

DEFAULT_PLAN = [
    system_message("Please solve the task below."),
    use_tools([bash()]),
    generate(),
]
DEFAULT_MAX_MESSAGES = 10

def swe_bench(dataset_name : str = "princeton-nlp/SWE-bench_Verified", split : str = "test", filter :  Callable[Sample,bool] | None = None, plan : Plan | list[Solver] = DEFAULT_PLAN,
max_messages : int = DEFAULT_MAX_MESSAGES) -> list[Task]:

    dataset = hf_dataset(
        dataset_name,
        split=split,
        sample_fields=FieldSpec(
            input="problem_statement",
            id="instance_id",
            metadata=["base_commit","patch","test_patch","version","repo","environment_setup_commit","PASS_TO_PASS","FAIL_TO_PASS"],
        )
    )

    if filter:
        dataset = dataset.filter(filter)

    return [swe_bench_instance(dataset,sample.id,plan,max_messages) for sample in dataset]


@task
def swe_bench_instance(
    dataset : Dataset,
    instance_id : str,
    plan: Plan | list[Solver] = DEFAULT_PLAN,
    max_messages : int = DEFAULT_MAX_MESSAGES
) -> Task:
    """Takes in a dataset and an instance_id, and returns a task which can be used to solve the issue"""
    
    sample = swebench_sample_from_id(dataset, instance_id)
    docker_compose_file = get_compose_file(sample.metadata["environment_setup_commit"], instance_id)

    return Task(
        dataset=[sample],
        plan=plan,
        sandbox=(
            "docker",
            str(docker_compose_file.absolute()),
        ),
        scorer=swebench_scorer(),
        max_messages=max_messages
    )

def swebench_sample_from_id(dataset : Dataset, instance_id : str) -> Sample:

    swebench_sample = next(sample for sample in dataset if sample.id == instance_id)

    # Put the input in context
    swebench_sample.input = INPUT_PROMPT.format(issue_text=dataset[0].input)
    swebench_sample.setup = get_setup_script(repo=swebench_sample.metadata["repo"],version=swebench_sample.metadata["version"],base_commit=swebench_sample.metadata["base_commit"])

    return swebench_sample

def get_setup_script(repo : str, version :str , base_commit :str) -> str:
    """
    Create a list of bash commands to set up the repository for testing. These are ran at the start of the sample, and clone the repository - the installatoin
    """
    setup_script =f"""#!/bin/bash
set -euo pipefail -x

# We clone the repository and set the permissions so the non-root user can run tests
rm -rf /testbed/*
git clone -o origin https://github.com/{repo} /testbed/
chmod -R 777 /testbed/
cd /testbed/
git reset --hard {base_commit}
git remote remove origin

# We then do any repo-specific install scripts
{MAP_REPO_TO_INSTALL.get(repo,"")}
{'\n'.join(MAP_REPO_VERSION_TO_SPECS[repo][version].get('pre_install',[]))}
{MAP_REPO_VERSION_TO_SPECS[repo][version].get('install','')}"""

# We then do a pip install, in case the environment missed any installs (NOTE: This is due to swe-bench being bugged)
# set +x
# source /opt/miniconda3/bin/activate
# conda activate testbed
# pip install -e . || true""" #TODO: Should fix the issue, it seems to be in pvlib. Need to also check how much slower this makes things.

    return setup_script

def get_eval_script(test_patch :str , repo :str, version : str, base_commit : str) -> str:
    """Creates a script which runs the tests of all the files in the test_patch."""

    #First we fetch the repository-specific 'specification' which SWE-bench provides
    conda_env="testbed"
    repo_directory="/testbed"

    # Fetch the command which runs the test. Often simply the string 'pytest'
    test_command = MAP_REPO_VERSION_TO_SPECS[repo][version]["test_cmd"]

    # Fetch any repo-specific setup commands, e.g. any environment variables
    repo_specific_setup_command = MAP_REPO_VERSION_TO_SPECS[repo][version].get("eval_commands",[])

    # Find all the files which have been modified by the test patch
    test_patch_files = re.findall(r"--- a/(.*)", test_patch)

    #Find all the files which contain tests. Ugly interface is due to swebench
    test_files = get_test_directives({"repo":repo,"test_patch":test_patch}) #type: ignore

    # Reset test files to the state they should be in before the patch.
    eval_script =f"""#!/bin/bash
set -uo pipefail -x

#We switch to the repository directory and activate the environment needed to run the tests
cd {repo_directory}
set +x
source /opt/miniconda3/bin/activate
conda activate {conda_env}
set -x

#We run all of the repo-specific setup commands (If any exist)
{"\n".join(repo_specific_setup_command)}

#We make sure we're back in the correct cwd and environment, in case repo setup caused issues.
cd {repo_directory}
set +x
source /opt/miniconda3/bin/activate
conda activate {conda_env}
set -x

#First we reset all of the files which out test patch touches
git checkout {base_commit} {' '.join(test_patch_files)}

#Then we apply the test patch given to us by SWE-bench, setting up the test we need to run
echo {shlex.quote(test_patch)} > /tmp/test_patch.diff 
git apply --check /tmp/test_patch.diff
git apply /tmp/test_patch.diff

#Then we run all the tests in the repository.
set +x
{test_command} {" ".join(test_files)} || true"""

    return eval_script

CREATE_MODEL_PATCH = """cd /testbed
git add -A
git diff --cached {base_commit} > model.patch"""

GET_AGENT_PATCH = """cd /testbed/
cat model.patch"""

@scorer(metrics=[mean(), std()])
def swebench_scorer() -> Scorer:

    async def scorer(state: TaskState, target: Target) -> Score:

        # Get the changes the model made, for logging purposes
        await sandbox().exec(["bash","-c",CREATE_MODEL_PATCH.format(base_commit=state.metadata["base_commit"])])
        agent_patch = await sandbox().exec(["bash","-c",GET_AGENT_PATCH])

        # Run the evaluation script
        eval_script = get_eval_script(test_patch=state.metadata["test_patch"], repo=state.metadata["repo"],version=state.metadata["version"],base_commit=state.metadata["base_commit"])
        eval_output = await sandbox().exec(["bash","-c",eval_script])
        if not eval_output.success:
            raise RuntimeError(f"Test run failed. \n\nStderr: \n\n{eval_output.stderr}\n\nStdout: \n\n{eval_output.stdout}")

        # Search for the error strings defined by the swe-bench authors
        error_string_search = {
                    x : x in eval_output.stdout
                    for x in [
                        APPLY_PATCH_FAIL,
                        RESET_FAILED,
                        TESTS_ERROR,
                        TESTS_TIMEOUT,
                        "Failed to reset task environment"]
        }

        if any(error_string_search.values()):
            explanation = f"The tests did not run correctly. Output from searching for error strings:\n\n{error_string_search}\n\nOutput from tests:\n\n{eval_output.stdout}"
            value = 0.0
        else:
            test_output_parser =  MAP_REPO_TO_PARSER[state.metadata["repo"]]
            test_outputs = test_output_parser(eval_output.stdout)

            pass_to_pass_results = {}
            fail_to_pass_results = {}
            for k,v in test_outputs.items():
                has_passed = "PASSED" == v
                if k in state.metadata["PASS_TO_PASS"]:
                    pass_to_pass_results[k] = has_passed
                else:
                    fail_to_pass_results[k] = has_passed

            # Sort both so the the false values are at the top
            pass_to_pass_results, fail_to_pass_results = dict(sorted(pass_to_pass_results.items(), key=lambda x: x[1])), dict(sorted(fail_to_pass_results.items(), key=lambda x: x[1]))

            explanation = f"PASS_TO_PASS:\n\n{json.dumps(pass_to_pass_results,indent=2)}\n\nFAIL_TO_PASS:\n\n{json.dumps(fail_to_pass_results,indent=2)}\n\n"

            if all(pass_to_pass_results.values()) and all(fail_to_pass_results.values()):
                value = 1.0
            else:
                value = 0.0
 
        return Score(value=value,explanation=explanation,metadata={"model_patch":agent_patch.stdout})

    return scorer

def get_compose_file(environment_commit_id: Sample, instance_id : str) -> Path:

    if not os.path.exists(SAMPLE_TO_IMAGE_PATH):
        raise ValueError(f"No sample to image mapping found. Please run  to build the images")

    sample_to_image = json.load(open(SAMPLE_TO_IMAGE_PATH))
    if instance_id in sample_to_image and environment_commit_id in sample_to_image[instance_id]:
        environment_image_name = sample_to_image[instance_id][environment_commit_id]["image_key"]
    else:
        raise ValueError(f"No image found for instance_id {instance_id}. Please run 'build_docker_images.py --dataset_location DATASET_LOCATION --split SPLIT' to build the images")

    compose_file_path = f"{COMPOSE_FILE_DIR}/{environment_commit_id}.yaml"
    if os.path.exists(compose_file_path):
        return compose_file_path

    images = DockerClient.from_env().images.list()
    if environment_image_name not in [image_name for image in images for image_name in image.tags]:
        raise ValueError(f"Image {environment_image_name} not found in docker images. Please run 'build_docker_images.py --dataset_location DATASET_LOCATION --split SPLIT' to build the images")

    # If the image is found, we can now create the compose file.
    compose_file_path = COMPOSE_FILE_DIR / f"{environment_image_name}.yaml"
    with compose_file_path.open(mode="w+") as f:
        f.write(f"""services:
  default:
    image: {environment_image_name}
    command: "tail -f /dev/null"
    working_dir: /testbed
    x-local: true""")

    return compose_file_path