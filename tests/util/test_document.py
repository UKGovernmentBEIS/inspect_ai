from pathlib import Path

from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
)

from inspect_ai import Task, eval
from inspect_ai.dataset import json_dataset
from inspect_ai.scorer import includes
from inspect_ai.solver import generate


@skip_if_no_openai
def test_document_openai() -> None:
    check_document("openai/gpt-4o")


@skip_if_no_openai
def test_document_openai_responses() -> None:
    check_document("openai/gpt-5-mini")


@skip_if_no_anthropic
def test_document_anthropic() -> None:
    check_document("anthropic/claude-3-7-sonnet-latest")


@skip_if_no_google
def test_document_google() -> None:
    check_document("google/gemini-2.5-flash")


def check_document(model: str) -> None:
    document_data = Path(__file__).parent / "test_media" / "document.jsonl"
    task = Task(
        dataset=json_dataset(document_data.as_posix()),
        solver=generate(),
        scorer=includes(),
    )
    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1
