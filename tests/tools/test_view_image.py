import base64
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_helpers.sandbox import CannedSandbox
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log, resolve_sample_attachments
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, use_tools
from inspect_ai.tool import ContentImage, ToolError, view_image
from inspect_ai.util import OutputLimitExceededError, SandboxTimeoutError, sandbox
from inspect_ai.util._sandbox.context import (
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from inspect_ai.util._subprocess import ExecResult

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@solver
def _write_file(path: str, data: bytes) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await sandbox().write_file(path, data)
        return state

    return solve


def _run_view_image(
    path: str,
    data: bytes,
    file_path: str,
    sandbox_type: str = "local",
    timeout: int | None = None,
) -> ChatMessageTool:
    task = Task(
        dataset=[Sample(input="View the image")],
        solver=[
            _write_file(path, data),
            use_tools(view_image(timeout=timeout)),
            generate(),
        ],
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


@pytest.mark.timeout(30, method="thread")
def test_view_image_timeout_is_enforced() -> None:
    response = _run_view_image("plot.png", PNG_BYTES, "/dev/zero", timeout=1)
    assert response.error is not None
    assert response.error.type == "timeout"
    assert "AAAA" not in str(response.content)


def test_view_image_data_not_logged_when_log_images_false(tmp_path: Path) -> None:
    task = Task(
        dataset=[Sample(input="View the image")],
        solver=[
            _write_file("plot.png", PNG_BYTES),
            use_tools(view_image()),
            generate(),
        ],
        message_limit=3,
        sandbox="local",
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="view_image",
                tool_arguments={"file_path": "plot.png"},
            ),
        ],
    )
    [log] = eval(task, model=model, log_images=False, log_dir=str(tmp_path))
    assert log.status == "success"
    saved = read_eval_log(log.location)
    assert saved.samples
    assert base64.b64encode(PNG_BYTES).decode("ascii") not in (
        saved.samples[0].model_dump_json()
    )


def test_view_image_over_output_limit_is_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE", str(64 * 1024))
    data = PNG_BYTES + bytes(range(256)) * 800
    response = _run_view_image("plot.png", data, "plot.png")
    assert response.error is not None
    assert "too large to view" in response.error.message


@contextmanager
def _default_sandbox(env: CannedSandbox) -> Iterator[None]:
    environments_token = sandbox_environments_context_var.set({"default": env})
    default_token = sandbox_default_context_var.set("default")
    try:
        yield
    finally:
        sandbox_default_context_var.reset(default_token)
        sandbox_environments_context_var.reset(environments_token)


async def test_view_image_undecodable_output_is_a_tool_error() -> None:
    env = CannedSandbox.returning(ExecResult(True, 0, "#\nnot base64!\n", ""))
    with _default_sandbox(env):
        with pytest.raises(ToolError, match="could not be decoded"):
            await view_image()(file_path="plot.png")


async def test_view_image_output_limit_exception_is_a_tool_error() -> None:
    def raise_limit(_cmd: list[str], _user: str | None) -> ExecResult[str]:
        raise OutputLimitExceededError("64 bytes", "iVBORw0KGgo=")

    with _default_sandbox(CannedSandbox(raise_limit)):
        with pytest.raises(ToolError, match="too large to view"):
            await view_image()(file_path="plot.png")


async def test_view_image_timeout_raises_sandbox_timeout_without_output() -> None:
    def raise_timeout(_cmd: list[str], _user: str | None) -> ExecResult[str]:
        raise SandboxTimeoutError("timed out", truncated_output="#\nAAAA")

    with _default_sandbox(CannedSandbox(raise_timeout)):
        with pytest.raises(SandboxTimeoutError) as excinfo:
            await view_image(timeout=1)(file_path="plot.png")
    assert excinfo.value.truncated_output is None


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
    response = _run_view_image("plot.png", PNG_BYTES, "/dev/zero", "docker", 2)
    assert response.error is not None
    assert response.error.type == "timeout"
    assert "AAAA" not in str(response.content)
