import os

from test_helpers.utils import (
    skip_if_no_google,
    skip_if_no_openai,
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
    log = eval(audio(), model)[0]
    assert log.status == "success"


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
    log = eval(video(), model)[0]
    assert log.status == "success"


@skip_if_no_google
def test_media_google_audio():
    check_audio("google/gemini-1.5-flash")


@skip_if_no_google
def test_media_google_video():
    check_video("google/gemini-1.5-flash")


@skip_if_no_openai
def test_media_openai_audio():
    check_audio("openai/gpt-4o-audio-preview")
