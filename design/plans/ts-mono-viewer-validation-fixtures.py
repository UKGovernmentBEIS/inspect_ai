"""Fixture log generator for the ts-mono viewer validation plan.

See ts-mono-viewer-validation.md (Setup -> Fixture log dir). Run from the
*new* checkout's venv; both viewers read the same output dir:

    python design/plans/ts-mono-viewer-validation-fixtures.py --output-dir ../viewer-validation/logs
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessageUser,
    ContentImage,
    ContentText,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, TaskState, generate, solver, use_tools
from inspect_ai.tool import tool

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_PATH = REPO_ROOT / "examples" / "images" / "bike.png"
MOCK = "mockllm/model"


@tool
def weather():
    async def execute(city: str) -> str:
        """Look up the weather for a city.

        Args:
            city: City to look up.

        Returns:
            Weather description.
        """
        return f"Sunny in {city}, 22C"

    return execute


def rich_task() -> Task:
    """5 samples: plain QA, tool call, image input, and score variety."""
    return Task(
        name="viewer_rich",
        dataset=[
            Sample(input="What is 2+2?", target="4"),
            Sample(
                input="Use the weather tool to check Berlin, then report.",
                target="Sunny",
            ),
            Sample(
                input=[
                    ChatMessageUser(
                        content=[
                            ContentText(text="What vehicle is in this image?"),
                            ContentImage(image=str(IMAGE_PATH)),
                        ]
                    )
                ],
                target="bike",
            ),
            Sample(input="Capital of France?", target="Paris"),
            Sample(input="Largest planet?", target="Jupiter"),
        ],
        solver=[use_tools(weather()), generate()],
        scorer=includes(),
    )


def rich_model() -> Model:
    """Fresh output iterator per run (outputs are consumed statefully)."""
    return get_model(
        MOCK,
        custom_outputs=[
            ModelOutput.from_content(model=MOCK, content="The answer is 4."),
            ModelOutput.for_tool_call(
                model=MOCK, tool_name="weather", tool_arguments={"city": "Berlin"}
            ),
            ModelOutput.from_content(model=MOCK, content="Sunny in Berlin."),
            ModelOutput.from_content(model=MOCK, content="It is a bike."),
            ModelOutput.from_content(model=MOCK, content="Paris."),
            ModelOutput.from_content(model=MOCK, content="Saturn."),  # wrong
        ],
    )


def breadth_task(name: str, n_correct: int, n_total: int) -> tuple[Task, Model]:
    """Small task with a controlled correct/incorrect split for score variety."""
    samples = [
        Sample(input=f"{name} question {i}", target="yes") for i in range(n_total)
    ]
    outputs = [
        ModelOutput.from_content(
            model=MOCK, content="yes" if i < n_correct else "no"
        )
        for i in range(n_total)
    ]
    return (
        Task(name=name, dataset=samples, solver=generate(), scorer=includes()),
        get_model(MOCK, custom_outputs=outputs),
    )


def grid_task() -> tuple[Task, Model]:
    """24 samples with metadata columns for samples-grid filter checks (D10)."""
    categories = ["math", "code", "trivia"]
    samples = [
        Sample(
            input=f"grid question {i}",
            target="yes",
            metadata={"difficulty": i % 5 + 1, "category": categories[i % 3]},
        )
        for i in range(24)
    ]
    outputs = [
        ModelOutput.from_content(model=MOCK, content="yes" if i % 2 == 0 else "no")
        for i in range(24)
    ]
    return (
        Task(name="viewer_grid", dataset=samples, solver=generate(), scorer=includes()),
        get_model(MOCK, custom_outputs=outputs),
    )


def error_task() -> Task:
    @solver
    def boom():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            raise RuntimeError("fixture: intentional task failure")

        return solve

    return Task(
        name="viewer_error",
        dataset=[Sample(input="will fail", target="n/a")],
        solver=boom(),
    )


@task
def viewer_slow() -> Task:
    """Slow task for the cancelled-status fixture (SIGINT'd subprocess)."""
    import anyio

    @solver
    def crawl():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await anyio.sleep(120)
            return state

        return solve

    return Task(
        name="viewer_cancelled",
        dataset=[Sample(input=f"slow {i}", target="n/a") for i in range(3)],
        solver=crawl(),
    )


def generate_cancelled(log_dir: Path) -> None:
    """Run viewer_slow in a subprocess and SIGINT it -> status 'cancelled'."""
    proc = subprocess.Popen(
        [
            "inspect",
            "eval",
            f"{__file__}@viewer_slow",
            "--model",
            MOCK,
            "--log-dir",
            str(log_dir),
            "--display",
            "plain",
        ],
        start_new_session=True,
    )
    time.sleep(15)
    proc.send_signal(signal.SIGINT)
    proc.wait(timeout=60)


def corrupt_copy(log_dir: Path) -> None:
    """Truncated .eval copy -> unreadable log for the S8 isolation check."""
    source = next(p for p in sorted(log_dir.glob("*.eval")) if p.stat().st_size > 0)
    corrupt = log_dir / "corrupt-truncated.eval"
    corrupt.write_bytes(source.read_bytes()[: source.stat().st_size // 2])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT.parent / "viewer-validation" / "logs",
    )
    args = parser.parse_args()
    log_dir: Path = args.output_dir
    if log_dir.exists():
        print(f"{log_dir} already exists; delete it to regenerate", file=sys.stderr)
        sys.exit(1)
    log_dir.mkdir(parents=True)
    common = dict(log_dir=str(log_dir), display="plain", max_samples=1)

    # rich task: .eval + .json twins; tagged for the edit-roundtrip baseline
    eval(
        rich_task(),
        model=rich_model(),
        tags=["baseline", "viewer-validation"],
        metadata={"purpose": "edit-roundtrip"},
        **common,
    )
    eval(rich_task(), model=rich_model(), log_format="json", **common)

    # listing breadth: varied task names and accuracies (12 logs)
    names = [
        "arithmetic", "geography", "chemistry", "history", "biology", "physics",
        "literature", "geology", "astronomy", "economics", "philosophy", "music",
    ]
    for i, name in enumerate(names):
        t, m = breadth_task(f"viewer_{name}", n_correct=i % 4, n_total=3)
        eval(t, model=m, **common)

    # samples-grid fixture (24 samples, metadata columns)
    t, m = grid_task()
    eval(t, model=m, **common)

    # error + cancelled statuses
    eval(error_task(), model=MOCK, **common)
    generate_cancelled(log_dir)

    # nested subdir for listing recursion
    t, m = breadth_task("viewer_nested", n_correct=2, n_total=3)
    eval(t, model=m, log_dir=str(log_dir / "sub" / "inner"), display="plain")

    corrupt_copy(log_dir)

    statuses = sorted(p.name for p in log_dir.rglob("*.eval"))
    json_logs = sorted(p.name for p in log_dir.rglob("*.json"))
    print(f"\n{len(statuses)} .eval + {len(json_logs)} .json logs in {log_dir}")


if __name__ == "__main__":
    main()
