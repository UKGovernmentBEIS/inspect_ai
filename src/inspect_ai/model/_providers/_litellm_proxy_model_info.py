"""Deployment metadata published by a LiteLLM proxy at `GET /model/info`.

The proxy returns one row per deployment (an alias can have several), with
the upstream model string and LiteLLM's model info for it. The rows are
fetched synchronously the first time a provider is constructed for a
(base URL, API key) pair and cached for the process. The key is part of the
cache key because the listing is filtered to the models the key may use.

There is no lock around the cache: Inspect constructs providers on a single
event loop thread, and two constructions racing the same key would at worst
fetch twice and store equal values.
"""

from typing import Any, NamedTuple

import httpx
from pydantic import JsonValue

from inspect_ai._util.error import PrerequisiteError

MODEL_INFO_TIMEOUT = 30.0
"""Seconds to wait for `/model/info` before failing provider construction."""


class ProxyDeployment(NamedTuple):
    """One deployment row from `/model/info`."""

    model_name: str
    """The alias clients send."""

    model: str | None
    """Upstream model string (`litellm_params.model`)."""

    custom_llm_provider: str | None
    """LiteLLM provider override (`litellm_params.custom_llm_provider`)."""

    base_model: str | None
    """Operator-declared upstream model (`model_info.base_model`)."""

    model_info: dict[str, JsonValue]
    """The row's `model_info` as returned."""


_deployments: dict[tuple[str, str], list[ProxyDeployment]] = {}


def proxy_deployments(
    base_url: str, api_key: str, headers: dict[str, str] | None = None
) -> list[ProxyDeployment]:
    """Every deployment the proxy lists for this key, fetching on first use.

    Raises:
        PrerequisiteError: The proxy could not be reached, rejected the
            request, or returned a body that is not a model info listing.
    """
    base_url = base_url.rstrip("/")
    key = (base_url, api_key)
    if key not in _deployments:
        _deployments[key] = _fetch(base_url, api_key, headers or {})
    return _deployments[key]


def _clear_cache() -> None:
    _deployments.clear()


def _fetch(
    base_url: str, api_key: str, headers: dict[str, str]
) -> list[ProxyDeployment]:
    # LiteLLM serves /model/info and /v1/model/info, so this works whether or
    # not the base URL ends in /v1
    url = f"{base_url}/model/info"
    try:
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"} | headers,
            timeout=MODEL_INFO_TIMEOUT,
        )
    except httpx.TimeoutException as ex:
        raise _fetch_error(url, f"no response within {MODEL_INFO_TIMEOUT:g}s") from ex
    except httpx.HTTPError as ex:
        raise _fetch_error(url, f"{type(ex).__name__}: {ex}") from ex

    if response.status_code in (401, 403):
        raise _fetch_error(
            url, f"HTTP {response.status_code}; the proxy rejected the API key"
        )
    if not response.is_success:
        raise _fetch_error(
            url, f"HTTP {response.status_code}: {_error_message(response):.500}"
        )
    try:
        body = response.json()
    except ValueError as ex:
        raise _fetch_error(
            url, f"the response is not JSON: {response.text:.500}"
        ) from ex
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise _fetch_error(url, f"the response has no 'data' list: {body!r:.500}")
    return [_deployment(url, row) for row in rows]


def _deployment(url: str, row: Any) -> ProxyDeployment:
    if not isinstance(row, dict) or not isinstance(row.get("model_name"), str):
        raise _fetch_error(url, f"unexpected deployment row: {row!r:.500}")
    params = row.get("litellm_params")
    params = params if isinstance(params, dict) else {}
    info = row.get("model_info")
    info = info if isinstance(info, dict) else {}
    return ProxyDeployment(
        model_name=row["model_name"],
        model=_str(params.get("model")),
        custom_llm_provider=_str(params.get("custom_llm_provider")),
        base_model=_str(info.get("base_model")),
        model_info=info,
    )


def _error_message(response: httpx.Response) -> str:
    """The message from LiteLLM's `{"error": {"message": ...}}` body, else the text."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return response.text
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else response.text


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _fetch_error(url: str, cause: str) -> PrerequisiteError:
    return PrerequisiteError(
        f"Could not read model info from the LiteLLM proxy at {url} ({cause}).\n\n"
        "Inspect uses it to identify the model behind the alias. To run "
        "without it, pass -M model_info=false."
    )
