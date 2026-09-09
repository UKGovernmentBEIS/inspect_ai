import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.agent import StateFilter, sandbox_agent_bridge
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage, GenerateConfig, ModelOutput, get_model
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_bridge_cannot_read_host_media(tmp_path: Path) -> None:
    secret = tmp_path / "host-only-secret.txt"
    secret_bytes = b"SANDBOX_MUST_NOT_RECEIVE_THIS"
    secret.write_bytes(secret_bytes)
    provider_requests: list[dict[str, Any]] = []

    target_model = get_model(
        "openai/gpt-5",
        api_key="local-fake-key",
        base_url="http://127.0.0.1:9/v1",
        memoize=False,
        responses_api=True,
        config=GenerateConfig(reasoning_summary="none"),
    )

    async def capture_create(**kwargs: Any) -> None:
        provider_requests.append(kwargs)
        raise RuntimeError("Stop after capturing provider request.")

    cast(Any, target_model.api).client.responses.create = capture_create

    @solver
    def bridge_solver() -> Solver:
        async def solve(state, generate):
            async with sandbox_agent_bridge(
                model_aliases={"inspect": target_model}
            ) as bridge:
                request = {
                    "model": "inspect",
                    "input": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_file",
                                    "file_data": str(secret),
                                    "filename": "secret.txt",
                                }
                            ],
                        }
                    ],
                    "tools": [],
                }
                script = (
                    "import urllib.error, urllib.request\n"
                    f"body = {json.dumps(request)!r}.encode()\n"
                    "request = urllib.request.Request(\n"
                    f"    'http://127.0.0.1:{bridge.port}/v1/responses',\n"
                    "    data=body,\n"
                    "    headers={'Content-Type': 'application/json'},\n"
                    "    method='POST',\n"
                    ")\n"
                    "try:\n"
                    "    print(urllib.request.urlopen(request).read().decode())\n"
                    "except urllib.error.HTTPError as ex:\n"
                    "    print(ex.read().decode())\n"
                )
                await sandbox().write_file("bridge_media_test.py", script)
                result = await sandbox().exec(
                    ["python3", "bridge_media_test.py"], timeout=60
                )
                state.metadata["bridge_stdout"] = result.stdout
                state.metadata["bridge_stderr"] = result.stderr
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="sample", input="test")],
            solver=bridge_solver(),
            sandbox="docker",
        ),
        model="mockllm/model",
        display="none",
        log_dir=str(tmp_path / "logs"),
    )

    try:
        assert logs[0].status == "success"
        assert logs[0].samples is not None
        metadata = logs[0].samples[0].metadata
        output = metadata["bridge_stdout"] + metadata["bridge_stderr"]
        assert secret_bytes.decode() not in output
        assert provider_requests == []
        serialized_requests = json.dumps(provider_requests)
        assert str(secret) not in serialized_requests
        assert secret_bytes.decode() not in serialized_requests
    finally:
        asyncio.run(target_model.api.aclose())


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_agent_bridge_forwards_state_filter(tmp_path: Path) -> None:
    """Filtered requests respond normally without replacing canonical state."""

    def accepts_main(messages: Sequence[ChatMessage]) -> bool:
        return messages[-1].text != "auxiliary"

    state_filter: StateFilter = accepts_main

    @solver
    def bridge_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            async with sandbox_agent_bridge(state_filter=state_filter) as bridge:
                requests = [
                    [{"role": "user", "content": "test"}],
                    [
                        {"role": "user", "content": "test"},
                        {"role": "assistant", "content": "retained reply"},
                        {"role": "user", "content": "auxiliary"},
                    ],
                ]
                script = (
                    "import json, urllib.error, urllib.request\n"
                    "responses = []\n"
                    f"for messages in {requests!r}:\n"
                    "    request = urllib.request.Request(\n"
                    f"        'http://127.0.0.1:{bridge.port}/v1/chat/completions',\n"
                    "        data=json.dumps({'model': 'inspect', 'messages': messages}).encode(),\n"
                    "        headers={'Content-Type': 'application/json'},\n"
                    "    )\n"
                    "    try:\n"
                    "        with urllib.request.urlopen(request, timeout=30) as response:\n"
                    "            responses.append(json.load(response))\n"
                    "    except urllib.error.HTTPError as ex:\n"
                    "        raise RuntimeError(ex.read().decode()) from ex\n"
                    "print(json.dumps(responses))\n"
                )
                result = await sandbox().exec(["python3", "-c", script], timeout=60)
                assert result.success, result.stderr
                state.metadata["responses"] = json.loads(result.stdout)
                state.messages = bridge.state.messages
                state.output = bridge.state.output
            return state

        return solve

    logs = eval(
        Task(
            dataset=[Sample(id="sample", input="test")],
            solver=bridge_solver(),
            sandbox="docker",
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content(model="mockllm/model", content=reply)
                for reply in ("retained reply", "auxiliary reply")
            ],
            memoize=False,
        ),
        display="none",
        log_dir=str(tmp_path / "logs"),
    )

    assert logs[0].status == "success", logs[0].error
    assert logs[0].samples is not None
    sample = logs[0].samples[0]
    assert [
        response["choices"][0]["message"]["content"]
        for response in sample.metadata["responses"]
    ] == ["retained reply", "auxiliary reply"]
    assert [message.text for message in sample.messages] == ["test", "retained reply"]
    assert sample.output.completion == "retained reply"
