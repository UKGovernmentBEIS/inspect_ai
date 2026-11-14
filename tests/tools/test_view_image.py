import base64

import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import resolve_sample_attachments
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import ContentImage, view_image
from inspect_ai.util import sandbox

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@solver
def _write_file(path: str, data: bytes) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await sandbox().write_file(path, data)
        return state

    return solve


def _run_view_image(
    path: str, data: bytes, file_path: str, sandbox_type: str = "local"
) -> ChatMessageTool:
    task = Task(
        dataset=[Sample(input="View the image")],
        solver=[_write_file(path, data), use_tools(view_image()), generate()],
        message_limit=3,
        sandbox=sandbox_type,
    )
    log = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="view_image",
                    tool_arguments={"file_path": file_path},
                ),
            ],
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    messages = resolve_sample_attachments(log.samples[0], "full").messages
    tool_call = get_tool_call(messages, "view_image")
    assert tool_call is not None
    response = get_tool_response(messages, tool_call)
    assert response is not None
    return response


def test_view_image_returns_image() -> None:
    response = _run_view_image("plot.png", PNG_BYTES, "plot.png")
    assert response.error is None
    assert isinstance(response.content, list)
    [content] = response.content
    assert isinstance(content, ContentImage)
    assert content.image == (
        f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode('ascii')}"
    )


@pytest.mark.parametrize("data", [b"hello", b"BM" + b"\x00" * 16])
def test_view_image_rejects_unsupported_file(data: bytes) -> None:
    response = _run_view_image("file", data, "file")
    assert response.error is not None
    assert "not a PNG, JPEG, GIF or WebP image" in response.error.message


@pytest.mark.parametrize("file_path", ["missing.png", "plot.png/x"])
def test_view_image_unreadable_path_is_a_tool_error(file_path: str) -> None:
    response = _run_view_image("plot.png", PNG_BYTES, file_path)
    assert response.error is not None
    assert file_path in response.error.message


@skip_if_no_docker
@pytest.mark.slow
def test_view_image_docker() -> None:
    response = _run_view_image("plot.png", PNG_BYTES, "plot.png", "docker")
    assert response.error is None
    assert isinstance(response.content, list)
    [content] = response.content
    assert isinstance(content, ContentImage)
    for file_path in ["plot.png/x", "/dev/null"]:
        response = _run_view_image("plot.png", PNG_BYTES, file_path, "docker")
        assert response.error is not None
