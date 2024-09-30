import os
from pathlib import Path

from datasets import load_dataset  # type: ignore
from platformdirs import user_cache_dir

from inspect_ai import Task, eval
from inspect_ai.log import EvalLog
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox
from inspect_evals.swe_bench import (
    swe_bench,
    swe_bench_baseline_scorer,
    swe_bench_scorer,
)

MAX_CONCURRENCY = int(os.getenv("INSPECT_MAX_CONCURRENCY", 4))
TIMEOUT_SECONDS = 2


SWE_BENCH_SPLIT = ("princeton-nlp/SWE-bench_Verified", "test")
TEST_INSTANCE_ID = "scikit-learn__scikit-learn-15100"


@solver
def apply_patch_solver(patch: str) -> Solver:
    # Solver which applies a patch to a github repository, and then exists.

    async def _apply_patch_solver(state: TaskState, generate: Generate) -> TaskState:
        state.metadata["patch"] = patch
        patch_location = "/tmp/patch.diff"
        await sandbox().write_file(patch_location, patch)
        output = await sandbox().exec(["git", "apply", patch_location])

        assert (
            output.returncode == 0
        ), f"Failed to write patch to {patch_location}. Stdout:\n\n {output.stdout}\n\nStderr:\n\n{output.stderr}"

        return state

    return _apply_patch_solver


@solver
def delete_readme_solver() -> Solver:
    # Solver which just deletes the README.md file from the repository.

    async def _delete_readme_solver(state: TaskState, generate: Generate) -> TaskState:
        await sandbox().exec(["rm", "/testbed/README.md"])
        return state

    return _delete_readme_solver


def test_correct_patch_succeeds() -> None:
    test_task = swe_bench(
        SWE_BENCH_SPLIT[0], SWE_BENCH_SPLIT[1], instance_ids=[TEST_INSTANCE_ID]
    )
    golden_patch = test_task.dataset[0].metadata["patch"]
    test_task.solver = apply_patch_solver(golden_patch)

    result = eval(test_task, "mockllm/model", max_messages=4, debug_errors=True)[0]

    assert (
        result.results and result.results.scores[0].metrics["mean"].value == 1.0
    ), "SWE-bench should mark a correct application successfully."


def test_incorrect_patch_fails() -> None:
    test_task = swe_bench(
        SWE_BENCH_SPLIT[0],
        SWE_BENCH_SPLIT[1],
        solver=delete_readme_solver(),
        instance_ids=[TEST_INSTANCE_ID],
    )

    result = eval(test_task, "mockllm/model", max_messages=2, debug_errors=True)[0]

    assert (
        result.results and result.results.scores[0].metrics["mean"].value == 0.0
    ), "SWE-bench should mark an incorrect application as a failure."


TESTS_RESOURCES_DIR = Path(user_cache_dir("inspect_swebench_test"))
TEST_DATASET = (
    TESTS_RESOURCES_DIR / "test_dataset.hf",
    "train",
)  # The dataset we are using to test on - should be created by the "create_test_repos.py" script
BASELINE_DIR = (
    TESTS_RESOURCES_DIR / "swebench_baselines" / "20240620_sweagent_claude3.5sonnet"
)  # The baseline we are comparing agents. Should be created by the script README


def test_same_scores_as_a_baseline(
    dataset: tuple[Path, str] = TEST_DATASET, baseline: Path = BASELINE_DIR
) -> None:
    # Very slow test
    # This test checks that the output of our implementation of swe_bench is the same as the original implementation.
    # By default, the script in create_tests_repos.py will create a dataset which contains a subset of the SWE-bench dataset which contains one of each repo in the datset

    if not dataset[0].exists():
        raise FileNotFoundError(
            f"Huggingface dataset {dataset} does not exist. To run this test, please run the create_test_repos.py script to generate a subset of SWE-bench you wish to test on"
        )

    if not baseline.exists():
        raise FileNotFoundError(
            f"The baseline directory you are pointing towards does not exist. Please use the script in the README to download the baseline from the SWE-bench baselines directory, and copy it to {BASELINE_DIR}"
        )

    # We load the dataset in both the original and huggingface versions.
    test_task = swe_bench(
        dataset=dataset[0].as_posix(),
        split=dataset[1],
        scorer=[
            swe_bench_scorer(),
            swe_bench_baseline_scorer(
                str(baseline), name=baseline.name
            ),  # We compare the baselines to the original scorers
        ],
    )
    test_dataset = load_dataset(dataset[0].as_posix(), split=dataset[1])

    # We create a task for each sample in the dataset.
    test_tasks = []
    for test_sample, swe_agent_patch in zip(
        test_task.dataset, test_dataset["swe_agent_patch"]
    ):
        test_tasks.append(
            Task(
                dataset=[test_sample],
                solver=apply_patch_solver(swe_agent_patch),
                scorer=test_task.scorer,
            )
        )

    results: list[EvalLog] = eval(
        test_tasks,
        "mockllm/model",
        max_tasks=MAX_CONCURRENCY,
        max_samples=MAX_CONCURRENCY,
        max_subprocesses=MAX_CONCURRENCY,
        fail_on_error=False,
    )

    error_str = ""
    for result in results:
        if result.status == "error":
            error_str += (
                f"Error occurred while evaluating task. Error:\n\n {result.error}"
            )
            continue

        if result.samples:
            for sample in result.samples:
                if sample.error:
                    error_str += f"Error occurred in a sample while evaluating task. Error:\n\n {sample.error}"
                    continue

            if result.samples[0].scores:
                score = result.samples[0].scores[swe_bench_scorer.__name__]
                swe_agent_score = result.samples[0].scores[baseline.name]

            if score.value != swe_agent_score.value:
                error_str += f"Result of evaluating {result.samples[0].id} did not agree with the swe_bench ground truth. Our score: '{score.value}'. swe-agent score: '{swe_agent_score.value}' Scorer results: {score.explanation}"

    assert error_str == "", error_str
