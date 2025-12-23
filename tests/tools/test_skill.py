"""End-to-end tests for the skill() tool."""

from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.tool import bash, skill

# Path to test skills directory
SKILLS_DIR = Path(__file__).parent / "skills"


@skip_if_no_openai
@skip_if_no_docker
@pytest.mark.slow
def test_skill_end_to_end() -> None:
    """Test that the skill tool works end-to-end with Docker sandbox.

    This test verifies that:
    1. The model invokes the skill to get instructions
    2. The model reads the asset file (contains ALPHA-BRAVO-CHARLIE)
    3. The model runs the provided script (outputs DELTA-ECHO-FOXTROT)
    """
    task = Task(
        dataset=[
            Sample(
                input=(
                    "What is the secret code? You MUST first read the asset file "
                    "and tell me what it contains, then run the script to get the answer."
                ),
                target=["ALPHA-BRAVO-CHARLIE", "DELTA-ECHO-FOXTROT"],
            ),
        ],
        solver=react(
            prompt=(
                "You have access to a skill that will tell you how to find the secret code. "
                "Use the skill tool first to get instructions, then follow them exactly. "
                "You must read the asset file AND run the script as instructed."
            ),
            tools=[
                skill([SKILLS_DIR / "secret-code"]),
                bash(),
            ],
        ),
        message_limit=20,
        scorer=includes(),
        sandbox=("docker", str(SKILLS_DIR / "compose.yaml")),
    )

    result = eval(
        task,
        model="openai/gpt-5.1-codex",
    )[0]

    assert result.status == "success", f"Eval failed with status: {result.status}"

    # Get the final model output
    samples = result.samples
    assert samples is not None and len(samples) > 0

    sample = samples[0]
    messages = sample.messages

    # Find all assistant messages and tool outputs to check content
    all_content = []
    for msg in messages:
        if hasattr(msg, "content"):
            if isinstance(msg.content, str):
                all_content.append(msg.content)
            elif isinstance(msg.content, list):
                for item in msg.content:
                    if hasattr(item, "text"):
                        all_content.append(item.text)

    combined_output = " ".join(all_content)

    # Verify the model read the asset (ALPHA-BRAVO-CHARLIE should appear)
    assert "ALPHA-BRAVO-CHARLIE" in combined_output, (
        "Model did not read the asset file. "
        f"Expected 'ALPHA-BRAVO-CHARLIE' in output but got: {combined_output[:500]}..."
    )

    # Verify the model ran the script (DELTA-ECHO-FOXTROT should appear)
    assert "DELTA-ECHO-FOXTROT" in combined_output, (
        "Model did not run the script. "
        f"Expected 'DELTA-ECHO-FOXTROT' in output but got: {combined_output[:500]}..."
    )
