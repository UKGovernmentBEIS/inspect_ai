"""Deployment metadata published by a LiteLLM proxy at `GET /model/info`.

`proxy_model_info()` converts a deployment's metadata to Inspect model info.

The proxy returns one row per deployment (an alias can have several), with
the upstream model string and LiteLLM's model info for it. The rows are
fetched synchronously the first time a provider is constructed for a
(base URL, API key) pair and cached for the process. The key is part of the
cache key because the listing is filtered to the models the key may use.

There is no lock around the cache: Inspect constructs providers on a single
event loop thread, and two constructions racing the same key would at worst
fetch twice and store equal values.
"""

from collections.abc import Iterable
from typing import Any, NamedTuple, TypeVar

import httpx
from pydantic import JsonValue

from inspect_ai._util.error import PrerequisiteError

from .._model_data.model_data import ModelCost, ModelInfo

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


def proxy_model_info(deployments: list[ProxyDeployment]) -> ModelInfo | None:
    """Model info from the deployments' `model_info`, or None if they report none.

    The router can send a request to any deployment of an alias, so limits
    take the minimum and prices the maximum over the deployments that report
    them. Reasoning fields are used only when every deployment reporting them
    agrees. LiteLLM's `max_input_tokens` is input capacity, which is what
    Inspect uses `context_length` for when a model has no separate input limit.
    """
    infos = [d.model_info for d in deployments]
    context_length = _minimum(_count(info.get("max_input_tokens")) for info in infos)
    output_tokens = _minimum(_count(info.get("max_output_tokens")) for info in infos)
    reasoning = _agreed(
        value
        for value in (info.get("supports_reasoning") for info in infos)
        if isinstance(value, bool)
    )
    effort = _agreed(
        value
        for value in (info.get("default_reasoning_effort") for info in infos)
        if isinstance(value, str) and value
    )
    costs = [cost for cost in map(_cost, infos) if cost is not None]
    cost = (
        ModelCost(
            input=max(c.input for c in costs),
            output=max(c.output for c in costs),
            input_cache_write=max(c.input_cache_write for c in costs),
            input_cache_read=max(c.input_cache_read for c in costs),
        )
        if costs
        else None
    )
    info = ModelInfo(
        context_length=context_length,
        output_tokens=output_tokens,
        reasoning=reasoning,
        reasoning_effort_default=effort,
        cost=cost,
    )
    return info if info != ModelInfo() else None


def _cost(info: dict[str, JsonValue]) -> ModelCost | None:
    """Prices per million tokens; needs input and output prices."""
    input = _price(info.get("input_cost_per_token"))
    output = _price(info.get("output_cost_per_token"))
    if input is None or output is None:
        return None
    cache_write = _price(info.get("cache_creation_input_token_cost"))
    cache_read = _price(info.get("cache_read_input_token_cost"))
    return ModelCost(
        input=input,
        output=output,
        input_cache_write=input if cache_write is None else cache_write,
        input_cache_read=input if cache_read is None else cache_read,
    )


def _price(value: JsonValue) -> float | None:
    # per token to per million, rounded (1.25e-06 * 1e6 == 1.2499999999999998)
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return round(value * 1_000_000, 9)


def _count(value: JsonValue) -> int | None:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _minimum(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


T = TypeVar("T", bool, str)


def _agreed(values: Iterable[T]) -> T | None:
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else None


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
