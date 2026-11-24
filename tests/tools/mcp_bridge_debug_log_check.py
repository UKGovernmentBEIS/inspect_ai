"""Run in a fresh process by `test_bridge_mcp_credentials_not_logged_at_debug_level`.

The target model is OpenAI Responses (mocked HTTP), so no `AnthropicAPI` is
constructed and only the agent bridge can install the Anthropic SDK
debug-record redactor. The agent sends messages through the bridge and submits
message batches (mocked HTTP), whose MCP servers are under
`requests[].params`. Expects `tests` and `tests/tools` on `sys.path`.
"""

import sys
import zipfile
from pathlib import Path
from typing import Any

import httpx2
from anthropic import Anthropic, AsyncAnthropic
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
MCP_BETA = "mcp-client-2025-04-04"
BATCH_REQUESTS: list[Any] = [
    {
        "custom_id": "r1",
        "params": {
            "model": "claude-sonnet-4-6",
            "max_tokens": 1024,
            "messages": MESSAGES,
            "mcp_servers": MCP_SERVERS,
        },
    }
]
BATCH_RESPONSE = {
    "id": "msgbatch_01",
    "type": "message_batch",
    "processing_status": "in_progress",
    "request_counts": {
        "processing": 1,
        "succeeded": 0,
        "errored": 0,
        "canceled": 0,
        "expired": 0,
    },
    "created_at": "2026-01-01T00:00:00Z",
    "expires_at": "2026-01-02T00:00:00Z",
    "ended_at": None,
    "cancel_initiated_at": None,
    "archived_at": None,
    "results_url": None,
}


def batch_response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json=BATCH_RESPONSE, request=request)


async def submit_batches() -> None:
    """Stable and beta batch submissions, async and sync clients."""
    async with AsyncAnthropic(
        api_key="test",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(batch_response)),
    ) as client:
        await client.messages.batches.create(requests=BATCH_REQUESTS)
        await client.beta.messages.batches.create(
            requests=BATCH_REQUESTS, betas=[MCP_BETA]
        )
    with Anthropic(
        api_key="test",
        http_client=httpx2.Client(transport=httpx2.MockTransport(batch_response)),
    ) as sync_client:
        sync_client.messages.batches.create(requests=BATCH_REQUESTS)
        sync_client.beta.messages.batches.create(
            requests=BATCH_REQUESTS, betas=[MCP_BETA]
        )


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
                    betas=[MCP_BETA],
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
            await submit_batches()
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
