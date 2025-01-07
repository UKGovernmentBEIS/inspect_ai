import os

from test_helpers.utils import (
    skip_if_no_google,
    skip_if_no_openai,
    skip_if_no_vertex,
)

from inspect_ai import Task, eval, task
from inspect_ai.dataset import json_dataset
from inspect_ai.scorer._classification import f1
from inspect_ai.solver import generate


@task
def audio():
    return Task(
        dataset=json_dataset(
            os.path.join("tests", "util", "test_audio", "audio.jsonl")
        ),
        solver=[generate()],
        scorer=f1(),
    )


def check_audio(model):
    eval(audio(), model)


@skip_if_no_google
def test_google_audio():
    check_audio("google/gemini-1.5-flash")


@skip_if_no_vertex
def test_vertex_audio():
    check_audio("vertex/gemini-1.5-flash")


@skip_if_no_openai
def test_openai_audio():
    check_audio("openai/gpt-4o")
