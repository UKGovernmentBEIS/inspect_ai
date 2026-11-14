"""Run in a fresh process by `test_bridge_mcp_credentials_not_logged_at_debug_level`.

The target model is OpenAI Responses (mocked HTTP), so no `AnthropicAPI` is
constructed and only the agent bridge can install the Anthropic SDK
debug-record redactor. Expects `tests` and `tests/tools` on `sys.path`.
"""

import sys
import zipfile
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from test_mcp_tools_remote import remote_mcp_model

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, agent, agent_bridge
from inspect_ai.dataset import Sample

TOKEN = "mcp-bridge-token-7c3e51"
MCP_SERVERS: list[Any] = [
    {
        "type": "url",
        "name": "deepwiki",
        "url": "https://mcp.deepwiki.com/mcp",
        "authorization_token": TOKEN,
    }
]
MESSAGES: list[Any] = [{"role": "user", "content": "hello"}]


@agent
def mcp_agent() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        async with agent_bridge(state) as bridge:
            async with AsyncAnthropic(api_key="test") as client:
                create: dict[str, Any] = dict(
                    model="inspect", max_tokens=1024, messages=MESSAGES
                )
                stable = dict(create, extra_body={"mcp_servers": MCP_SERVERS})
                beta = dict(
                    create,
                    mcp_servers=MCP_SERVERS,
                    betas=["mcp-client-2025-04-04"],
                )
                raw = await client.messages.with_raw_response.create(**stable)
                await raw.parse()
                raw = await client.beta.messages.with_raw_response.create(**beta)
                await raw.parse()
                async with client.messages.with_streaming_response.create(
                    **stable
                ) as response:
                    await response.parse()
                async with client.beta.messages.with_streaming_response.create(
                    **beta
                ) as response:
                    await response.parse()
            return bridge.state

    return execute


def main(log_dir: str) -> None:
    model = remote_mcp_model("openai", [])
    log = eval(
        Task(dataset=[Sample(input="hello")], solver=mcp_agent()),
        model=model,
        log_dir=log_dir,
        log_level="debug",
        log_level_transcript="debug",
        display="none",
    )[0]
    assert log.status == "success", log.error.message if log.error else None
    request_options = 0
    hits = 0
    for file in Path(log_dir).rglob("*.eval"):
        with zipfile.ZipFile(file) as z:
            for member in z.namelist():
                data = z.read(member)
                request_options += data.count(b"Request options:")
                hits += data.count(TOKEN.encode())
    print(f"request_options={request_options} token_hits={hits}")


if __name__ == "__main__":
    main(sys.argv[1])
