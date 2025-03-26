from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
    skip_if_trio,
)

from inspect_ai import Task, eval, task
from inspect_ai._util.constants import PKG_PATH
from inspect_ai._util.images import file_as_data_uri
from inspect_ai.dataset import Sample
from inspect_ai.model._model import get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import ContentImage, tool

IMAGES_PATH = PKG_PATH / ".." / ".." / "tests" / "dataset" / "test_dataset" / "images"


@tool
def camera():
    async def execute() -> ContentImage:
        """
        Take a picture of the environment.

        Returns:
            Image with a picture of the environment
        """
        ballons = (IMAGES_PATH / "ballons.png").as_posix()

        return ContentImage(image=await file_as_data_uri(ballons))

    return execute


@task
def camera_task():
    return Task(
        dataset=[
            Sample(
                input="Use the 'camera' tool to take a picture of the environment. What do you see?",
                target="balloons",
            )
        ],
        solver=[use_tools(camera()), generate()],
        scorer=includes(),
    )


@skip_if_no_openai
def test_openai_tool_image_result():
    check_tool_image_result("openai/gpt-4o")


@skip_if_no_openai
def test_openai_responses_tool_image_result():
    check_tool_image_result(get_model("openai/gpt-4o-mini", responses_api=True))


@skip_if_no_google
@skip_if_trio
def test_google_tool_image_result():
    check_tool_image_result("google/gemini-1.5-pro")


@skip_if_no_anthropic
def test_anthropic_tool_image_result():
    check_tool_image_result("anthropic/claude-3-5-sonnet-20240620")


def check_tool_image_result(model):
    log = eval(camera_task(), model=model)[0]
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].scores
    assert log.samples[0].scores["includes"].as_str() == "C"
