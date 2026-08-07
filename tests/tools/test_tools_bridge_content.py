import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias

import anyio
import pytest
from pydantic import BaseModel, Field
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, task
from inspect_ai.agent import BridgedToolsSpec, sandbox_agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import Solver, solver
from inspect_ai.tool import ContentImage, ContentText, Tool, tool
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.util import sandbox

IMAGE_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB"
    "9WlPz2QAAAAASUVORK5CYII="
)
IMAGE_DATA_URI = f"data:image/png;base64,{IMAGE_DATA}"
LEGACY_TEXT_CONTENT = '[\n  {\n    "type": "text",\n    "text": "legacy text"\n  }\n]'


class MCPTextContent(BaseModel):
    type: Literal["text"]
    text: str


class MCPImageContent(BaseModel):
    type: Literal["image"]
    data: str
    mimeType: str


MCPToolContent: TypeAlias = Annotated[
    MCPTextContent | MCPImageContent, Field(discriminator="type")
]


class MCPToolCallResult(BaseModel):
    content: list[MCPToolContent]


class MCPToolCallResponse(BaseModel):
    jsonrpc: Literal["2.0"]
    id: int
    result: MCPToolCallResult


ToolFactory: TypeAlias = Callable[[], Tool]


@dataclass(frozen=True, slots=True)
class BridgedToolContentCase:
    tool_factory: ToolFactory
    expected_content: tuple[MCPToolContent, ...]


@tool
def image_returning_tool():
    """Return a PNG image."""

    async def execute():
        """Return a PNG image."""
        return [ContentImage(image=IMAGE_DATA_URI)]

    return execute


@tool
def mixed_content_returning_tool():
    """Return a caption and PNG image."""

    async def execute():
        """Return a caption and PNG image."""
        return [ContentText(text="Screenshot:"), ContentImage(image=IMAGE_DATA_URI)]

    return execute


@tool
def plain_string_returning_tool():
    """Return plain text."""

    async def execute():
        """Return plain text."""
        return "plain text result"

    return execute


@tool
def text_content_returning_tool():
    """Return legacy text content."""

    async def execute():
        """Return legacy text content."""
        return [ContentText(text="legacy text")]

    return execute


@tool
def url_image_returning_tool():
    """Return an image URL."""

    async def execute():
        """Return an image URL."""
        return [ContentImage(image="https://example.com/screenshot.png")]

    return execute


@task
def bridged_tool_content_task(test_solver: Solver) -> Task:
    return Task(
        dataset=[Sample(input="Test", target="Test")],
        solver=[test_solver],
        scorer=includes(),
        sandbox="docker",
    )


async def call_mcp_tool(
    config: MCPServerConfigHTTP, tool_name: str
) -> MCPToolCallResponse:
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
        }
    )
    last_error = "MCP endpoint did not return a response"
    for attempt in range(30):
        result = await sandbox().exec(
            cmd=[
                "curl",
                "-s",
                "-f",
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-d",
                request,
                config.url,
            ],
            timeout=30,
        )
        if result.success and result.stdout.strip():
            return MCPToolCallResponse.model_validate_json(result.stdout)
        last_error = (
            f"curl failed: returncode={result.returncode}, "
            f"stdout={result.stdout}, stderr={result.stderr}"
        )
        if attempt < 29:
            await anyio.sleep(0.5)
    raise RuntimeError(f"MCP request failed after 30 retries: {last_error}")


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize(
    "case",
    (
        BridgedToolContentCase(
            tool_factory=image_returning_tool,
            expected_content=(
                MCPImageContent(type="image", data=IMAGE_DATA, mimeType="image/png"),
            ),
        ),
        BridgedToolContentCase(
            tool_factory=mixed_content_returning_tool,
            expected_content=(
                MCPTextContent(type="text", text="Screenshot:"),
                MCPImageContent(type="image", data=IMAGE_DATA, mimeType="image/png"),
            ),
        ),
        BridgedToolContentCase(
            tool_factory=plain_string_returning_tool,
            expected_content=(MCPTextContent(type="text", text="plain text result"),),
        ),
        BridgedToolContentCase(
            tool_factory=text_content_returning_tool,
            expected_content=(MCPTextContent(type="text", text=LEGACY_TEXT_CONTENT),),
        ),
        BridgedToolContentCase(
            tool_factory=url_image_returning_tool,
            expected_content=(
                MCPTextContent(type="text", text="https://example.com/screenshot.png"),
            ),
        ),
    ),
    ids=(
        "image_only",
        "mixed_text_and_image",
        "plain_string",
        "content_text_list",
        "non_data_uri_image",
    ),
)
def test_bridged_tool_content_when_returning_images_or_legacy_text(
    case: BridgedToolContentCase,
) -> None:
    @solver
    def test_solver():
        async def solve(state, _generate):
            async with sandbox_agent_bridge(
                bridged_tools=[
                    BridgedToolsSpec(name="content", tools=[case.tool_factory()])
                ]
            ) as bridge:
                response = await call_mcp_tool(
                    bridge.mcp_server_configs[0], case.tool_factory.__name__
                )
                assert response.result.content == list(case.expected_content)
            return state

        return solve

    log = eval(
        bridged_tool_content_task(test_solver()), model=get_model("mockllm/model")
    )[0]
    assert log.status == "success"
