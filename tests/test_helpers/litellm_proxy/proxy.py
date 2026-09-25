"""Run a LiteLLM proxy in Docker for tests, optionally capturing upstream traffic.

The proxy runs from a locally available image (it is never pulled), so tests
work offline once the image is present:

    docker pull ghcr.io/berriai/litellm:main-latest

Set `LITELLM_PROXY_IMAGE` to use a different image or tag.

With capture enabled, a LiteLLM callback mounted into the container writes the
exact request body LiteLLM sends to each upstream provider, and the raw
upstream response for non-streaming calls, to a host directory. LiteLLM keeps
no raw bytes for streamed responses. Send an `x-litellm-call-id` header with a
request to find its records with `upstream_exchange()`.
"""

import functools
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, NamedTuple, TypeVar

import httpx
import pytest
import yaml

F = TypeVar("F", bound=Callable[..., Any])

LITELLM_PROXY_IMAGE = os.environ.get(
    "LITELLM_PROXY_IMAGE", "ghcr.io/berriai/litellm:main-latest"
)

# The proxy refuses to start with a weak master key.
MASTER_KEY = "sk-inspect-litellm-test-6f3a9c2e8b1d4705a"

# Host name a fake upstream running on the test host is reachable at from
# inside the proxy container.
DOCKER_HOST_ALIAS = "host.docker.internal"

CALL_ID_HEADER = "x-litellm-call-id"

# LiteLLM loads `custom_callbacks.proxy_handler_instance` from the directory
# holding the config file. Kept as source text because `litellm` is not
# installed in the test environment (it runs only inside the container).
CAPTURE_CALLBACK_SOURCE = """\
import json
import os
import time

from litellm.integrations.custom_logger import CustomLogger

CAPTURE_DIR = "/capture"
STREAM_PLACEHOLDER = "first stream response received"


def _json(value):
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _write(call_id, kind, record):
    # serialize immediately: LiteLLM mutates the logging kwargs after hooks return
    path = os.path.join(CAPTURE_DIR, f"{call_id}.{time.time_ns()}.{kind}.json")
    with open(path + ".tmp", "w") as f:
        json.dump(record, f, default=str)
    os.replace(path + ".tmp", path)


class InspectCapture(CustomLogger):
    def log_pre_api_call(self, model, messages, kwargs):
        args = kwargs.get("additional_args") or {}
        _write(
            kwargs.get("litellm_call_id"),
            "request",
            {
                "model": model,
                "url": args.get("api_base"),
                "call_type": kwargs.get("call_type"),
                "body": _json(args.get("complete_input_dict")),
            },
        )

    def log_post_api_call(self, kwargs, response_obj, start_time, end_time):
        raw = kwargs.get("original_response")
        if raw is None or raw == STREAM_PLACEHOLDER:
            return
        _write(kwargs.get("litellm_call_id"), "response", {"body": _json(raw)})


proxy_handler_instance = InspectCapture()
"""


def isolate_model_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep model info the provider registers out of other tests."""
    from inspect_ai.model import _model_info
    from inspect_ai.model._providers import litellm_proxy

    monkeypatch.setattr(_model_info, "_custom_models", dict(_model_info._custom_models))
    monkeypatch.setattr(_model_info, "_result_cache", {})
    monkeypatch.setattr(litellm_proxy, "_registrations", {})


@functools.cache
def litellm_proxy_image_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", LITELLM_PROXY_IMAGE],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def skip_if_no_litellm_proxy(func: F) -> F:
    return pytest.mark.slow(
        pytest.mark.skipif(
            not litellm_proxy_image_available(),
            reason=f"Requires Docker and the {LITELLM_PROXY_IMAGE} image available locally.",
        )(func)
    )


class LiteLLMProxy(NamedTuple):
    base_url: str
    """OpenAI-compatible base URL (ends in `/v1`)."""

    api_key: str

    capture_dir: Path | None
    """Directory holding upstream capture records (None when capture is off)."""


@contextmanager
def run_litellm_proxy(
    work_dir: Path,
    config: dict[str, Any],
    *,
    capture: bool = False,
    env_vars: Sequence[str] = (),
) -> Iterator[LiteLLMProxy]:
    """Run a LiteLLM proxy container for the duration of the context.

    Args:
        work_dir: Empty directory for the config and capture records.
        config: Proxy config (`model_list` etc.). The master key is added.
        capture: Record upstream requests and responses (see module docstring).
        env_vars: Host environment variables to pass through to the proxy
            (e.g. provider API keys). Names that are unset are skipped.
    """
    config = _with_master_key(config)
    config_dir = work_dir / "config"
    config_dir.mkdir()
    capture_dir: Path | None = None
    if capture:
        capture_dir = work_dir / "capture"
        capture_dir.mkdir()
        config = _with_capture(config)
        (config_dir / "custom_callbacks.py").write_text(CAPTURE_CALLBACK_SOURCE)
    (config_dir / "config.yaml").write_text(yaml.safe_dump(config))

    container = _start_proxy(config_dir, capture_dir, env_vars)
    try:
        base_url = _wait_for_proxy(container)
        yield LiteLLMProxy(
            base_url=f"{base_url}/v1", api_key=MASTER_KEY, capture_dir=capture_dir
        )
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


def _with_master_key(config: dict[str, Any]) -> dict[str, Any]:
    general_settings = dict(config.get("general_settings") or {})
    general_settings["master_key"] = MASTER_KEY
    return config | {"general_settings": general_settings}


def _with_capture(config: dict[str, Any]) -> dict[str, Any]:
    litellm_settings = dict(config.get("litellm_settings") or {})
    litellm_settings["callbacks"] = "custom_callbacks.proxy_handler_instance"
    litellm_settings["turn_off_message_logging"] = False
    return config | {"litellm_settings": litellm_settings}


def _start_proxy(
    config_dir: Path, capture_dir: Path | None, env_vars: Sequence[str]
) -> str:
    args = [
        "docker",
        "run",
        "-d",
        "--pull=never",
        "-p",
        "127.0.0.1::4000",
        f"--add-host={DOCKER_HOST_ALIAS}:host-gateway",
        "-v",
        f"{config_dir}:/app/config:ro",
    ]
    if capture_dir is not None:
        args += ["-v", f"{capture_dir}:/capture"]
    for name in env_vars:
        # `-e NAME` passes the host value without putting it on the command line
        if os.environ.get(name):
            args += ["-e", name]
    args += [
        LITELLM_PROXY_IMAGE,
        "--config",
        "/app/config/config.yaml",
        "--port",
        "4000",
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _wait_for_proxy(container: str, timeout: float = 120) -> str:
    port = (
        subprocess.run(
            ["docker", "port", container, "4000/tcp"],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.split(":")[-1]
        .strip()
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/health/liveliness").status_code == 200:
                return base_url
        except httpx.TransportError:
            pass
        time.sleep(1)
    logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
    raise RuntimeError(
        f"LiteLLM proxy did not become healthy within {timeout}s:\n"
        f"{logs.stdout}{logs.stderr}"
    )


class UpstreamExchange(NamedTuple):
    """One upstream call made by the proxy on behalf of a client request."""

    url: str | None
    request: Any
    """Request body LiteLLM sent upstream (parsed JSON)."""

    response: Any | None
    """Raw upstream response body (parsed JSON), or None for streamed calls.

    For providers LiteLLM calls through the OpenAI SDK, this is the SDK's
    parsed response re-serialized, so fields the provider omitted appear as
    nulls. Other providers record the response text as received.
    """


def upstream_exchange(capture_dir: Path, call_id: str) -> UpstreamExchange:
    """Return the final upstream exchange recorded for a client call id.

    Retries record one request per attempt; the last one is returned together
    with the response recorded after it.
    """
    records = sorted(
        capture_dir.glob(f"{call_id}.*.json"),
        key=lambda path: int(path.name.split(".")[-3]),
    )
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    for path in records:
        kind = path.name.split(".")[-2]
        record = json.loads(path.read_text())
        if kind == "request":
            request, response = record, None
        elif kind == "response":
            response = record
    if request is None:
        raise AssertionError(f"No upstream request captured for call id {call_id}")
    response_body = response.get("body") if response is not None else None
    return UpstreamExchange(
        url=request.get("url"),
        request=_wire_body(request.get("body")),
        # for some streamed calls LiteLLM records a placeholder string (e.g. the
        # repr of a coroutine) rather than a response body
        response=response_body if isinstance(response_body, (dict, list)) else None,
    )


def _wire_body(body: Any) -> Any:
    """The request body as sent on the wire.

    For providers that use the OpenAI SDK, LiteLLM records the SDK's
    `extra_body` argument as a key, which the SDK merges into the JSON body.
    """
    if isinstance(body, dict) and isinstance(body.get("extra_body"), dict):
        body = {k: v for k, v in body.items() if k != "extra_body"} | body["extra_body"]
    return body
