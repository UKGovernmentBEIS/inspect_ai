import os
from pathlib import Path

from build_images import build_images
from datasets import load_dataset
from swe_bench import swe_bench, swebench_baseline_scorer

from inspect_ai import Task, eval
from inspect_ai.log import EvalLog
from inspect_ai.solver import Generate, Plan, TaskState, solver
from inspect_ai.util import sandbox

RESOURCE_DIR = Path(__file__).parent / "resources"
TIMEOUT_SECONDS = 2
GOLDEN_PATCH_TEST_ID = "sphinx-doc__sphinx-8475"
SIMPLE_TEST_DATASET = str(
    RESOURCE_DIR / "tests" / "swebench_one_sample.hf"
)  # A dataset with a single swe-bench example
SWEBENCH_BASELINE_NAME = "swebench_verified_20240620_sweagent_claude3.5sonnet"
SWEAGENT_BASELINE: str = str(RESOURCE_DIR / "baselines" / SWEBENCH_BASELINE_NAME)

SLOW_TEST_DATASET: str = str(
    RESOURCE_DIR / "tests" / "all_repos_swe_agent_50_percent.hf"
)  # A dataset with one instance from each of the repositories scraped in SWE-bench-verified, and also a column indicating whether it was resolved by swe-agent.

MAX_CONCURRENCY = int(os.getenv("INSPECT_MAX_CONCURRENCY", 10))

if not Path(SLOW_TEST_DATASET).exists():
    raise FileNotFoundError(
        f"Test datasets have not been created. Please run the script at {(RESOURCE_DIR / "tests"/"create_test_repos.py").absolute()} to run the tests."
    )


def build_test_image(
    dataset_name: str = str(SIMPLE_TEST_DATASET),
    split: str | None = "train",
    max_workers: int = 4,
) -> None:
    build_images(dataset_name=dataset_name, split=split, max_workers=max_workers)


@solver
def apply_patch_solver(patch: str):
    # Solver to apply a specific patch to a git repository.

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
def delete_readme_solver():
    async def _delete_readme_solver(state: TaskState, generate: Generate) -> TaskState:
        sandbox().exec(["rm", "/testbed/README.md"])
        return state

    return _delete_readme_solver


def test_golden_patch_succeeds() -> None:
    build_test_image()

    test_task = swe_bench(filter=lambda s: s.id == GOLDEN_PATCH_TEST_ID)
    golden_patch = test_task.dataset[0].metadata["patch"]
    test_task.plan = Plan([apply_patch_solver(golden_patch)])

    result = eval(test_task, "mockllm/model", max_messages=4)[0]

    assert (
        result.results.scores[0].metrics["mean"].value == 1.0
    ), "SWE-bench should mark a correct application successfully."


def test_incorrect_edit_fails() -> None:
    build_test_image()

    test_task = swe_bench(filter=lambda s: s.id == GOLDEN_PATCH_TEST_ID)
    test_task.plan = Plan([delete_readme_solver()])

    result = eval(test_task, "mockllm/model", max_messages=2)[0]

    assert (
        result.results.scores[0].metrics["mean"].value == 0.0
    ), "SWE-bench should mark an incorrect application as a failure."


def test_same_results_for_swe_agent() -> None:
    # Very slow test
    # This test checks that we agree with the original swe-bench implementation patches outputted by swe-agent, across all of the repositories in SWE-bench

    build_test_image(dataset_name=SLOW_TEST_DATASET, split="train")

    # We load the whole dataset
    test_task = swe_bench(dataset=SLOW_TEST_DATASET, split="train")
    test_dataset = load_dataset(SLOW_TEST_DATASET, split="train")

    # Add a scorer which compares the value of the swe-agents's patch with the ground truth
    scorers = [
        test_task.scorer[0],
        swebench_baseline_scorer(SWEAGENT_BASELINE, name="sweagent_baseline"),
    ]

    # Make plans which apply the swe-agent's patch for each  swebench instance
    test_tasks = []
    for test_sample, swe_agent_patch in zip(
        test_task.dataset, test_dataset["swe_agent_patch"]
    ):
        test_tasks.append(
            Task(
                dataset=[test_sample],
                plan=apply_patch_solver(swe_agent_patch),
                scorer=scorers,
            )
        )

    results: list[EvalLog] = eval(
        test_tasks,
        "mockllm/model",
        max_tasks=MAX_CONCURRENCY,
        max_samples=MAX_CONCURRENCY,
        max_subprocess=MAX_CONCURRENCY,
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
                    error_str += f"Error occurred while evaluating task. Error:\n\n {sample.error}"
                    continue

        score = result.samples[0].scores["swebench_scorer"]
        swe_agent_score = result.samples[0].scores["sweagent_baseline"]

        if score.value != swe_agent_score.value:
            error_str += f"Result of evaluating {result.samples[0].id} did not agree with the swe_bench ground truth. Scorer output: {score.explanation}"

    assert error_str == "", error_str


test_same_results_for_swe_agent()
