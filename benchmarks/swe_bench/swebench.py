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
from swebench.harness.constants import

INPUT_PROMPT = """
Please solve the following issue:

{issue_text}
"""

def swe_bench(
    instance_id="pvlib__pvlib-python-1854",
    split: str | None = "dev",
    dataset="princeton-nlp/SWE-bench_Lite",
) -> Task:
    hf_dataset = load_dataset(
        dataset,
        split=split,
    )
    load_environment_images(hf_dataset)

    instance = hf_dataset.filter(lambda record: instance_id == record["instance_id"])[0]
    sample = Sample(input=INPUT_PROMPT.format(issue_text=instance["problem_statement"]), id=instance_id,metadata={
        "base_commit":instance["base_commit"],
        "test_patch": instance["test_patch"],
        "patch": instance["patch"]

    })

    return Task(
        dataset=[sample],
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
        base_commit = state.metadata["base_commit"]
        test_patch = state.metadata["test_patch"]

        sandbox_output = await sandbox().exec(["bash","-c",CREATE_MODEL_PATCH.format(base_commit=base_commit)])
        agent_patch = await sandbox().exec(["bash","-c",GET_AGENT_PATCH])

        print("")

        return Score(value=0.0,metadata={"model_patch":agent_patch.stdout})
    
    return scorer


def run_instance(
        test_spec: TestSpec,
        pred: dict,
        rm_image: bool,
        force_rebuild: bool,
        client: docker.DockerClient,
        run_id: str,
        timeout: int | None = None,
    ):
    """
    Run a single instance with the given prediction.

    Args:
        test_spec (TestSpec): TestSpec instance
        pred (dict): Prediction w/ model_name_or_path, model_patch, instance_id
        rm_image (bool): Whether to remove the image after running
        force_rebuild (bool): Whether to force rebuild the image
        client (docker.DockerClient): Docker client
        run_id (str): Run ID
        timeout (int): Timeout for running tests
    """
    # Set up logging directory
    instance_id = test_spec.instance_id

    # Get git diff before running eval script
    git_diff_output_before = (
        sandbox.exec_run("git diff", workdir="/testbed").output.decode("utf-8").strip()
    )
    logger.info(f"Git diff before:\n{git_diff_output_before}")

    eval_file = Path(log_dir / "eval.sh")
    eval_file.write_text(test_spec.eval_script)
    logger.info(
        f"Eval script for {instance_id} written to {eval_file}; copying to container..."
    )
    copy_to_container(sandbox, eval_file, Path("/eval.sh"))

    # Run eval script, write output to logs
    test_output, timed_out, total_runtime = exec_run_with_timeout(sandbox, "/bin/bash /eval.sh", timeout)
    test_output_path = log_dir / "test_output.txt"
    logger.info(f'Test runtime: {total_runtime:_.2f} seconds')
    with open(test_output_path, "w") as f:
        f.write(test_output)
        logger.info(f"Test output for {instance_id} written to {test_output_path}")
        if timed_out:
            f.write(f"\n\nTimeout error: {timeout} seconds exceeded.")
            raise EvaluationError(
                instance_id,
                f"Test timed out after {timeout} seconds.",
                logger,
            )

    # Get git diff after running eval script
    git_diff_output_after = (
        sandbox.exec_run("git diff", workdir="/testbed").output.decode("utf-8").strip()
    )

    # Check if git diff changed after running eval script
    logger.info(f"Git diff after:\n{git_diff_output_after}")
    if git_diff_output_after != git_diff_output_before:
        logger.info(f"Git diff changed after running eval script")

    # Get report from test output
    logger.info(f"Grading answer for {instance_id}...")
    report = get_eval_report(
        test_spec=test_spec,
        prediction=pred,
        log_path=test_output_path,
        include_tests_status=True,
    )
    logger.info(
        f"report: {report}\n"
        f"Result for {instance_id}: resolved: {report[instance_id]['resolved']}"
    )


def get_eval_script(instance, repo, version, base_commit,env_name):

    """
    Applies the test patch and runs the tests.
    """

    spec = MAP_EVAL_VERSION_TO_SPECS[repo][version]
    env_name="testbed"
    repo_directory=f"/{env_name}"
    eval_instance = {"repo":repo,"version":version}
    

    # Find all the files which have been modified by the test patch
    test_files = re.findall(r"--- a/(.*)", test_patch)

    # Reset test files to the state they should be in before the patch.
    reset_tests_command = f"git checkout {base_commit} {' '.join(test_files)}"
    sandbox().exec(["bash","-c",reset_tests_command])

    #We write the test_patch to the container, and then apply it
    TEST_PATCH_LOCATION = "/tmp/test_patch.diff"
    sandbox().write_file(TEST_PATCH_LOCATION,test_patch)
    sandbox().exec(["bash","-c",f"git apply {TEST_PATCH_LOCATION}"])

    #We get a
    test_command = " ".join(
        [
            MAP_REPO_VERSION_TO_SPECS[repo][version]["test_cmd"],
            *get_test_directives(instance),
        ]
    )

    eval_commands = [
        f"source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
        f"cd {repo_directory}",
    ]

    if "eval_commands" in specs:
        eval_commands += specs["eval_commands"]
    
    eval_commands += [
        f"git config --global --add safe.directory {repo_directory}",  # for nonroot user
        f"cd {repo_directory}",
        # This is just informational, so we have a record
        f"git status",
        f"git show",
        f"git diff {base_commit}",
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
    ]

    if "install" in specs:
        eval_commands.append(specs["install"])
    
    eval_commands += [
        reset_tests_command,
        apply_test_patch_command,
        test_command,
        reset_tests_command,  # Revert tests after done, leave the repo in the same state as before
    ]
    return eval_commands