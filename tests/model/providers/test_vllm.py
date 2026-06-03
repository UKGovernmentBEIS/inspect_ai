import logging
import os
import sys
from subprocess import Popen
from types import ModuleType
from typing import Any, cast

import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._providers import vllm as vllm_provider


def _mock_vllm_start(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def start_local_server(
        base_cmd: list[str],
        host: str,
        port: int | None = None,
        api_key: str | None = None,
        server_type: str = "server",
        timeout: int | None = None,
        server_args: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[str, Popen[str], int]:
        captured.update(
            {
                "base_cmd": base_cmd,
                "host": host,
                "port": port,
                "api_key": api_key,
                "server_type": server_type,
                "timeout": timeout,
                "server_args": server_args,
                "env": env,
            }
        )
        return ("http://localhost:3000/v1", cast(Popen[str], object()), 3000)

    monkeypatch.setitem(sys.modules, "vllm", ModuleType("vllm"))
    monkeypatch.setattr(vllm_provider, "start_local_server", start_local_server)
    monkeypatch.delenv(vllm_provider.VLLM_CONFIGURE_LOGGING, raising=False)
    return captured


def test_vllm_configure_logging_respects_explicit_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vllm_provider.logger, "isEnabledFor", lambda level: True)

    assert vllm_provider._configure_logging_enabled(False) is False

    monkeypatch.setattr(vllm_provider.logger, "isEnabledFor", lambda level: False)

    assert vllm_provider._configure_logging_enabled(True) is True


def test_vllm_configure_logging_follows_inspect_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def info_enabled(level: int) -> bool:
        return level >= logging.INFO

    monkeypatch.setattr(vllm_provider.logger, "isEnabledFor", info_enabled)

    assert vllm_provider._configure_logging_enabled(None) is True

    monkeypatch.setattr(vllm_provider.logger, "isEnabledFor", lambda level: False)

    assert vllm_provider._configure_logging_enabled(None) is False


def test_vllm_start_server_sets_configure_logging_from_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _mock_vllm_start(monkeypatch)
    monkeypatch.setattr(
        vllm_provider.logger,
        "isEnabledFor",
        lambda level: level == logging.INFO,
    )

    api = vllm_provider.VLLMAPI("mock/model")
    api._start_server("mock/model")

    assert os.environ[vllm_provider.VLLM_CONFIGURE_LOGGING] == "1"
    assert captured["server_args"] == {}


def test_vllm_start_server_respects_explicit_configure_logging_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _mock_vllm_start(monkeypatch)
    monkeypatch.setattr(vllm_provider.logger, "isEnabledFor", lambda level: True)

    api = vllm_provider.VLLMAPI("mock/quiet-model", configure_logging=False)
    api._start_server("mock/quiet-model")

    assert os.environ[vllm_provider.VLLM_CONFIGURE_LOGGING] == "0"
    assert captured["server_args"] == {}


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_api() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,
            top_p=0.9,
            top_k=None,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        ),
        device=0,
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_disable_chat_template() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,
        ),
        device=0,
        use_chat_template=False,
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
