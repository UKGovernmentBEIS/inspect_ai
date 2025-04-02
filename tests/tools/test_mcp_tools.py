from test_helpers.utils import skip_if_no_mcp_fetch_package

from inspect_ai.model import get_model
from inspect_ai.tool import mcp_server_stdio, mcp_tools
from inspect_ai.tool._mcp._types import MCPServer


@skip_if_no_mcp_fetch_package
async def test_mcp_server_stdio():
    async with mcp_server_stdio(
        command="python", args=["-m", "mcp_server_fetch"]
    ) as server:
        await check_fetch_server(server)


# to run this test:
# git clone https://github.com/modelcontextprotocol/python-sdk
# cd pip install python-sdk/examples/servers/simple-tool/
# mcp-simple-tool --transport sse --port 8000
#
# async def test_mcp_server_sse():
#     async with mcp_server_sse(url="http://localhost:8000/sse") as server:
#         await check_fetch_server(server)


async def check_fetch_server(server: MCPServer):
    _, output = await get_model("openai/gpt-4o").generate_loop(
        "Use the fetch tool to read the website at https://example.com/, then please tell me what is there.",
        tools=mcp_tools(server),
    )
    assert "example.com" in output.completion
