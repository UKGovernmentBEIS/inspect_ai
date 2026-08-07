from pathlib import Path
from unittest.mock import AsyncMock

import anyio
import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge.bridge import agent_bridge
from inspect_ai.agent._bridge.sandbox import bridge as sandbox_bridge_module
from inspect_ai.agent._bridge.sandbox.bridge import sandbox_agent_bridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.log import EvalLog
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    GenerateFilter,
    GenerateInput,
    Model,
    ModelResponseFilter,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo


class _FakeProxy:
    def __aiter__(self) -> "_FakeProxy":
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration

    async def kill(self) -> None:
        return None


class _FakeSandbox:
    def __init__(self) -> None:
        self.exec_remote = AsyncMock(return_value=_FakeProxy())


REPLACED_SENTINEL = "9E5C8B41-D8AE-4E15-A8E7-2A86C5C73D5C"
SANDBOX_REPLACED_SENTINEL = "1F4D8E62-A93B-4E72-B6F1-9B3C20A8B4F8"


def _run_eval_with_filters(
    tmp_path: Path,
    *,
    filter: GenerateFilter | None = None,
    response_filter: ModelResponseFilter | None = None,
    retry_refusals: int | None = None,
) -> EvalLog:
    """Run a one-turn agent_bridge eval against mockllm with supplied filters."""
    from openai import AsyncOpenAI

    from inspect_ai import Task, eval, task
    from inspect_ai.agent import Agent, agent
    from inspect_ai.dataset import Sample
    from inspect_ai.model._openai_convert import messages_to_openai

    @agent
    def my_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(
                state,
                filter=filter,
                response_filter=response_filter,
                retry_refusals=retry_refusals,
            ) as bridge:
                async with AsyncOpenAI(api_key="sk-test") as client:
                    await client.chat.completions.create(
                        model="inspect",
                        messages=await messages_to_openai(state.messages),
                    )
                return bridge.state

        return execute

    @task
    def t() -> Task:
        return Task(dataset=[Sample(input="Say hi.")], solver=my_agent())

    log = eval(t(), model="mockllm/model", log_dir=str(tmp_path), display="plain")
    return log[0]


def test_agent_bridge_constructor_accepts_response_filter() -> None:
    """AgentBridge construction must accept response_filter."""

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return output

    bridge = AgentBridge(
        state=AgentState(messages=[]),
        response_filter=my_filter,
    )

    assert bridge.response_filter is my_filter


async def test_agent_bridge_entry_point_accepts_response_filter() -> None:
    """The agent_bridge() async context manager must accept response_filter."""

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return None

    async with agent_bridge(
        response_filter=my_filter,
    ) as bridge:
        assert bridge.response_filter is my_filter


async def test_sandbox_agent_bridge_entry_point_accepts_response_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sandbox_agent_bridge() async context manager must accept response_filter."""

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return output

    async def fake_run_model_service(
        _sandbox_env: object,
        _web_search: object,
        _code_execution: object,
        _bridge: object,
        _instance: str,
        started: anyio.Event,
    ) -> None:
        started.set()
        await anyio.sleep_forever()

    fake_sandbox = _FakeSandbox()
    monkeypatch.setattr(
        sandbox_bridge_module,
        "sandbox_with_injected_tools",
        AsyncMock(return_value=fake_sandbox),
    )
    monkeypatch.setattr(
        sandbox_bridge_module,
        "run_model_service",
        fake_run_model_service,
    )

    async with sandbox_agent_bridge(response_filter=my_filter) as bridge:
        assert bridge.response_filter is my_filter


def test_response_filter_passthrough(tmp_path: Path) -> None:
    """When response_filter returns None, output is unchanged."""
    call_count = {"n": 0}

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        call_count["n"] += 1
        return None

    _run_eval_with_filters(tmp_path, response_filter=my_filter)
    assert call_count["n"] >= 1


def test_response_filter_replaces_output(tmp_path: Path) -> None:
    """When response_filter returns a ModelOutput, that output is used."""

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return ModelOutput.from_content(model.name, REPLACED_SENTINEL)

    log = _run_eval_with_filters(tmp_path, response_filter=my_filter)
    log_json = log.model_dump_json()
    assert REPLACED_SENTINEL in log_json


def test_response_filter_refusal_triggers_retry(tmp_path: Path) -> None:
    """A response_filter returning content_filter triggers a retry."""
    call_log: list[str] = []

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        call_log.append(output.stop_reason)
        return ModelOutput.from_content(
            model.name,
            "blocked",
            stop_reason="content_filter",
        )

    _run_eval_with_filters(tmp_path, response_filter=my_filter, retry_refusals=2)
    assert len(call_log) == 3, (
        f"expected 3 filter calls, got {len(call_log)}: {call_log}"
    )


def test_response_filter_can_suppress_refusal(tmp_path: Path) -> None:
    """A response_filter that clears content_filter suppresses retry."""
    call_count = {"n": 0}

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        call_count["n"] += 1
        return ModelOutput.from_content(
            model.name,
            "all good",
            stop_reason="stop",
        )

    _run_eval_with_filters(tmp_path, response_filter=my_filter, retry_refusals=5)
    assert call_count["n"] == 1, f"expected 1 filter call, got {call_count['n']}"


def test_response_filter_no_retry_budget(tmp_path: Path) -> None:
    """When retry_refusals is None, content_filter must not loop."""
    call_count = {"n": 0}

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        call_count["n"] += 1
        return ModelOutput.from_content(
            model.name,
            "blocked",
            stop_reason="content_filter",
        )

    _run_eval_with_filters(tmp_path, response_filter=my_filter)
    assert call_count["n"] == 1, f"expected 1 call, got {call_count['n']}"


def test_request_and_response_filter_compose(tmp_path: Path) -> None:
    """Request filter runs before model.generate; response filter runs after.

    This is the narrow contract the state-mutation symmetry pattern relies on:
    callers can use the request filter to re-scrub assistant tool_use arguments
    before the next model request, and the response filter still observes the
    exact post-request-filter inputs whose output it may mutate.

    Also locks the contract that the response_filter observes the request_filter's
    mutations: the request filter INJECTS a sentinel tool, and the response filter
    must see that tool in its tool_info argument. The underlying request carries 0
    tools, so asserting `len(tool_info) == 0` would be vacuous — asserting that the
    sentinel is present is the only way to prove post-request-filter visibility.
    """
    call_order: list[str] = []
    response_seen_tools: list[list[str]] = []
    sentinel_tool = ToolInfo(
        name="sentinel_tool",
        description="injected by request filter",
    )

    async def req_filter(
        model: Model,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> GenerateInput:
        call_order.append("request_filter")
        return GenerateInput(input_messages, [sentinel_tool], tool_choice, config)

    async def resp_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        call_order.append("response_filter")
        response_seen_tools.append([t.name for t in tool_info])
        return None

    _run_eval_with_filters(tmp_path, filter=req_filter, response_filter=resp_filter)
    assert call_order == ["request_filter", "response_filter"], (
        f"unexpected ordering: {call_order}"
    )
    assert response_seen_tools == [["sentinel_tool"]], (
        "response_filter must observe the request filter's injected tools; "
        f"saw {response_seen_tools}"
    )


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_response_filter_replaces_output(tmp_path: Path) -> None:
    """The response_filter hook fires through the sandbox bridge."""
    import json

    from inspect_ai import Task, eval, task
    from inspect_ai.agent import Agent, agent
    from inspect_ai.dataset import Sample
    from inspect_ai.util import sandbox

    async def my_filter(
        model: Model,
        output: ModelOutput,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | None:
        return ModelOutput.from_content(model.name, SANDBOX_REPLACED_SENTINEL)

    @agent
    def my_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with sandbox_agent_bridge(
                state,
                response_filter=my_filter,
            ) as bridge:
                payload = json.dumps(
                    {
                        "model": "inspect",
                        "messages": [{"role": "user", "content": "Say hi."}],
                    }
                )
                script = (
                    "import os\n"
                    "import time\n"
                    "import urllib.error\n"
                    "import urllib.request\n"
                    "\n"
                    "for attempt in range(30):\n"
                    "    request = urllib.request.Request(\n"
                    "        os.environ['OPENAI_BASE_URL'] + '/chat/completions',\n"
                    "        data=os.environ['PAYLOAD'].encode(),\n"
                    "        headers={'Content-Type': 'application/json'},\n"
                    "    )\n"
                    "    try:\n"
                    "        print(urllib.request.urlopen(request).read().decode())\n"
                    "        break\n"
                    "    except urllib.error.URLError:\n"
                    "        if attempt == 29:\n"
                    "            raise\n"
                    "        time.sleep(0.5)\n"
                )
                result = await sandbox().exec(
                    cmd=[
                        "python3",
                        "-c",
                        script,
                    ],
                    env={
                        "OPENAI_BASE_URL": "http://localhost:13131/v1",
                        "PAYLOAD": payload,
                    },
                    timeout=30,
                )
                assert result.success, result.stderr
                assert SANDBOX_REPLACED_SENTINEL in result.stdout
                return bridge.state

        return execute

    @task
    def t() -> Task:
        return Task(
            dataset=[Sample(input="Say hi.")],
            solver=my_agent(),
            sandbox="docker",
        )

    log = eval(t(), model="mockllm/model", log_dir=str(tmp_path), display="plain")
    log_json = log[0].model_dump_json()
    assert SANDBOX_REPLACED_SENTINEL in log_json
