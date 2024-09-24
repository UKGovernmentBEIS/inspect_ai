import os

from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
    skip_if_no_vertex,
)

from inspect_ai import Task, eval, task
from inspect_ai.dataset import json_dataset
from inspect_ai.scorer import match
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = """
For the following exercise, it is important that you answer with only a single word or numeric value in brackets. For example, [22] or [house]. Do not include any discussion, narrative, or rationale, just a single value in brackets.
"""


@task
def images():
    return Task(
        dataset=json_dataset(
            os.path.join("tests", "util", "test_images", "images.jsonl")
        ),
        solver=[system_message(SYSTEM_MESSAGE), generate()],
        scorer=match(),
    )


def check_images(model):
    eval(images, model)


@skip_if_no_google
def test_google_images():
    check_images("google/gemini-1.5-flash")


@skip_if_no_openai
def test_openai_images():
    check_images("openai/gpt-4")


@skip_if_no_vertex
def test_vertex_images():
    check_images("vertex/gemini-1.5-flash")


@skip_if_no_anthropic
def test_anthropic_images():
    check_images("anthropic/claude-3-sonnet-20240229")
