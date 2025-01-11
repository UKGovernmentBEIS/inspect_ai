import os

from test_helpers.utils import (
    skip_if_no_google,
    skip_if_no_openai,
    skip_if_no_vertex,
)

from inspect_ai import Task, eval, task
from inspect_ai.dataset import json_dataset
from inspect_ai.scorer import includes
from inspect_ai.solver import generate


@task
def audio():
    return Task(
        dataset=json_dataset(
            os.path.join("tests", "util", "test_media", "audio.jsonl")
        ),
        solver=[generate()],
        scorer=includes(),
    )


def check_audio(model):
    eval(audio(), model)


@task
def video():
    return Task(
        dataset=json_dataset(
            os.path.join("tests", "util", "test_media", "video.jsonl")
        ),
        solver=[generate()],
        scorer=includes(),
    )


def check_video(model):
    eval(video(), model)


@skip_if_no_google
def test_media_google_audio():
    check_audio("google/gemini-1.5-flash")


@skip_if_no_google
def test_media_google_video():
    check_video("google/gemini-1.5-flash")


@skip_if_no_vertex
def test_media_vertex_audio():
    check_audio("vertex/gemini-1.5-flash")


@skip_if_no_openai
def test_media_openai_audio():
    check_audio("openai/gpt-4o-audio-preview")
