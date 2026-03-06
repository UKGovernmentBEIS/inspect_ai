"""
Agent Skills Example

This example demonstrates how to use the skill() tool to provide
specialized instructions to agents for Linux system exploration tasks.

Run with:
    inspect eval examples/skills/task.py --model openai/gpt-5

Skills provide structured guidance that agents can invoke on-demand,
including instructions and executable scripts.
"""

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.agent._react import react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import model_graded_qa
from inspect_ai.tool import bash, skill

# Path to skills directory (relative to this file)
SKILLS_DIR = Path(__file__).parent / "skills"


@task
def skills_example() -> Task:
    """Demonstrate agent skills for Linux system exploration."""
    return Task(
        dataset=[
            Sample(
                input="What Linux distribution is this system running? Include the version.",
                target="The system is running Ubuntu 24.04",
            ),
            Sample(
                input="How many CPU cores does this system have?",
                target="The number of CPU cores available on the system",
            ),
            Sample(
                input="What is the total amount of memory (RAM) on this system?",
                target="The total RAM available on the system",
            ),
            Sample(
                input="What is the IP address of this system?",
                target="The IP address(es) configured on the system's network interfaces",
            ),
            Sample(
                input="How much disk space is available on the root filesystem?",
                target="The available disk space on the root (/) filesystem",
            ),
        ],
        solver=react(
            prompt="You are a Linux system administrator. You have access to skills "
            "that provide guidance for system exploration tasks. Use the skill "
            "tool to get instructions before attempting tasks, then use bash "
            "to execute the appropriate commands.",
            tools=[
                skill(
                    [
                        SKILLS_DIR / "system-info",
                        SKILLS_DIR / "network-info",
                        SKILLS_DIR / "disk-usage",
                    ]
                ),
                bash(),
            ],
        ),
        scorer=model_graded_qa(),
        sandbox=("docker", "compose.yaml"),
    )
