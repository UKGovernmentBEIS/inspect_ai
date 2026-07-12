import pytest

from test_helpers.utils import simple_task_state

from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    ModelOutput,
    get_model,
)
from inspect_ai.scorer import Target, claim_support


@pytest.mark.anyio
async def test_claim_support_includes_transcript_and_claim() -> None:
    grader_model = get_model(
        "mockllm/grader",
        custom_outputs=[
            ModelOutput.from_content("mockllm/grader", content="GRADE: C")
        ],
    )
    scorer = claim_support(model=grader_model)
    state = simple_task_state(
        messages=[
            ChatMessageUser(content="Please inspect the site."),
            ChatMessageAssistant(content="I used the browser to inspect the page."),
            ChatMessageTool(
                content="Archive page returned 200 OK",
                function="browser",
            ),
            ChatMessageAssistant(content="The page was accessible."),
        ],
        model_output="The page was accessible.",
    )

    result = await scorer(state, Target(""))

    assert result.value == "C"
    assert result.metadata is not None
    prompt = result.metadata["grading"][0]
    prompt_text = prompt.content if isinstance(prompt.content, str) else prompt.text
    assert "Transcript" in prompt_text
    assert "Please inspect the site." in prompt_text
    assert "Tool (browser)" in prompt_text
    assert "The page was accessible." in prompt_text


@pytest.mark.anyio
async def test_claim_support_atomic_benchmark() -> None:
    cases = [
        (
            "The server saw 500 login attempts from one IP in one minute.",
            "The server saw 500 login attempts from one IP in one minute.",
            "C",
        ),
        (
            "The server saw 500 login attempts from one IP in one minute.",
            "The server saw 500 login attempts from one IP in one minute and the host was compromised.",
            "P",
        ),
        (
            "The server saw 500 login attempts from one IP in one minute.",
            "The attack came from two IP addresses.",
            "I",
        ),
    ]

    baseline_model = get_model(
        "mockllm/grader",
        custom_outputs=[
            ModelOutput.from_content("mockllm/grader", content="GRADE: C"),
            ModelOutput.from_content("mockllm/grader", content="GRADE: C"),
            ModelOutput.from_content("mockllm/grader", content="GRADE: I"),
        ],
    )
    atomic_model = get_model(
        "mockllm/grader",
        custom_outputs=[
            ModelOutput.from_content(
                "mockllm/grader",
                content="The server saw 500 login attempts from one IP in one minute.",
            ),
            ModelOutput.from_content("mockllm/grader", content="GRADE: C"),
            ModelOutput.from_content(
                "mockllm/grader",
                content=(
                    "The server saw 500 login attempts from one IP in one minute.\n"
                    "The host was compromised."
                ),
            ),
            ModelOutput.from_content("mockllm/grader", content="GRADE: C"),
            ModelOutput.from_content("mockllm/grader", content="GRADE: I"),
            ModelOutput.from_content(
                "mockllm/grader", content="The attack came from two IP addresses."
            ),
            ModelOutput.from_content("mockllm/grader", content="GRADE: I"),
        ],
    )

    baseline_scorer = claim_support(model=baseline_model)
    atomic_scorer = claim_support(model=atomic_model, decompose_claims=True)

    baseline_correct = 0
    atomic_correct = 0

    for transcript, claim, target in cases:
        state = simple_task_state(
            messages=[
                ChatMessageUser(content=transcript),
                ChatMessageAssistant(content=claim),
            ],
            model_output=claim,
        )

        baseline_result = await baseline_scorer(state, Target(target))
        atomic_result = await atomic_scorer(state, Target(target))

        baseline_correct += baseline_result.value == target
        atomic_correct += atomic_result.value == target

    assert baseline_correct == 2
    assert atomic_correct == 3
    assert atomic_correct > baseline_correct
