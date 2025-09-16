import os
from typing import Callable

import pytest

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentImage, ContentText
from inspect_ai.dataset import Sample
from inspect_ai.dataset._sources.json import json_dataset
from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.model._model import get_model
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import model_graded_fact
from inspect_ai.solver._task_state import TaskState


def include_history_task(include_history: bool | Callable[[TaskState], str]) -> Task:
    return Task(
        dataset=[
            Sample(
                input=[
                    ChatMessageUser(content="Who wrote 'The 39 Steps'?"),
                    ChatMessageAssistant(
                        content="Do you mean the movie or the adaption for the stage?"
                    ),
                    ChatMessageUser(content="The movie."),
                ],
                target="Alfred Hitchcock",
            )
        ],
        scorer=model_graded_fact(
            include_history=include_history, model="mockllm/model"
        ),
    )


def test_model_graded_include_history():
    def check_include_history(include_history: bool | Callable[[TaskState], str]):
        log = eval(include_history_task(include_history), model="mockllm/model")[0]
        assert log.samples
        assert "Do you mean the movie" in log.samples[0].model_dump_json()

    check_include_history(True)
    check_include_history(
        lambda state: "\n".join([message.text for message in state.messages])
    )


def test_model_graded_multimodal():
    # grab the ballons image from the images tests dataset
    dataset = json_dataset(
        os.path.join("tests", "util", "test_images", "images.jsonl")
    )[0:1]

    # extract the image and use it to create a response with an image for mockllm
    assert isinstance(dataset[0].input, list)
    user_message = dataset[0].input[0]
    assert isinstance(user_message.content, list)
    target_image = user_message.content[1]
    assert isinstance(target_image, ContentImage)
    assistant_output = ModelOutput.from_content(
        "mockllm/model",
        content=[
            ContentText(text="I believe there are 3 ballons in the picture."),
            target_image,
        ],
    )
    model = get_model("mockllm/model", custom_outputs=[assistant_output])

    # run the task
    task = Task(
        dataset=dataset,
        scorer=model_graded_fact(model="mockllm/model"),
    )
    log = eval(task, model=model)[0]

    # confirm that the image was presented to the model for scoring
    sample = resolve_sample_attachments(log.samples[0])
    model_event = next(
        (event for event in reversed(sample.events) if event.event == "model")
    )
    content = model_event.input[0].content
    assert isinstance(content, list)
    assert len(content) > 1
    assert isinstance(content[0], ContentText)
    assert "attached" in content[0].text
    assert isinstance(content[1], ContentImage)


@pytest.mark.parametrize(
    ["model_graded_fact_kwargs", "expected_role"],
    [
        pytest.param({}, "grader", id="defaults_uses_grader_model"),
        pytest.param(
            {"model_role": "grader"},
            "grader",
            id="model_role_specified_uses_grader_model",
        ),
        pytest.param(
            {"model": "mockllm/model"}, None, id="model_specified_uses_specified_model"
        ),
        pytest.param(
            {"model_role": "grader", "model": "mockllm/model"},
            None,
            id="both_specified_uses_specified_model",
        ),
        pytest.param(
            {"model_role": None}, None, id="model_role_none_uses_default_model"
        ),
    ],
)
def test_model_role_precedence_for_model_graded_scorer(
    model_graded_fact_kwargs, expected_role
):
    grader_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", [ContentText(text="GRADE: C")])
        ],
    )
    task = Task(
        scorer=model_graded_fact(**model_graded_fact_kwargs),
        dataset=[Sample(input="What is 1 + 1?", target="2")],
    )
    log = eval(
        task,
        model="mockllm/model",
        model_roles={"grader": grader_model},
    )[0]

    # Locate the exact model event that performed grading by matching the prompt ID
    score = log.samples[0].scores["model_graded_fact"]
    grading_prompt_dict = score.metadata["grading"][0]  # ChatMessageUser dict
    sample = resolve_sample_attachments(log.samples[0])

    grading_event = next(
        e
        for e in reversed(sample.events)
        if e.event == "model" and e.input and e.input[0].id == grading_prompt_dict["id"]
    )

    assert grading_event.role == expected_role
