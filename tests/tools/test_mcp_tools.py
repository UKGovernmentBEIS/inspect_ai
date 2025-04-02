import pytest
from test_helpers.utils import skip_if_no_mcp_fetch_package

from inspect_ai.model import get_model
from inspect_ai.tool import mcp_server_stdio, mcp_tools


@pytest.mark.slow
@skip_if_no_mcp_fetch_package
async def test_mcp_server_stdio():
    async with mcp_server_stdio(
        command="python", args=["-m", "mcp_server_fetch"]
    ) as client:
        _, output = await get_model("openai/gpt-4o").generate_loop(
            "Use the fetch tool to read the website at https://example.com/, then please tell me what is there.",
            tools=await mcp_tools(client),
        )
        assert "example.com" in output.completion
