"""Finding a sentinel sidecar behind a model's proxy, and calling its endpoint for evals."""

from dataclasses import dataclass, field
from itertools import count
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

if TYPE_CHECKING:
    from inspect_ai.model._model import ModelAPI

logger = getLogger(__name__)

VERSIONS = (1,)
"""The versions of the sidecar's endpoint for evals that Inspect speaks."""

PROBE_TIMEOUT = 10.0
CALL_TIMEOUT = 60.0


class SentinelProxyError(RuntimeError):
    """A sidecar the task needs is missing, or the one found can't be used."""


class SidecarCallError(RuntimeError):
    """A call to the sidecar's endpoint for evals failed, or was answered with an error."""

    def __init__(self, method: str, message: str, code: int | None = None) -> None:
        super().__init__(f"The sidecar's {method} failed: {message}")
        self.method = method
        self.code = code


@dataclass
class Sidecar:
    """A sidecar that answered the probe, reached through the model's proxy with the model's own credentials."""

    origin: str
    release: Literal["whole", "early"]
    client: Any = field(repr=False)
    _ids: "count[int]" = field(default_factory=lambda: count(1), repr=False)

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a method of the endpoint for evals, and return its result."""
        try:
            response = await self.client.post(
                f"{self.origin}/sentinel/v1",
                body={
                    "jsonrpc": "2.0",
                    "id": next(self._ids),
                    "method": method,
                    "params": params,
                },
                cast_to=_response_type(),
                options={"max_retries": 0, "timeout": CALL_TIMEOUT},
            )
            answer = response.json()
        except Exception as ex:
            raise SidecarCallError(method, str(ex)) from ex
        if not isinstance(answer, dict):
            raise SidecarCallError(method, "the answer isn't JSON-RPC")
        error = answer.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            raise SidecarCallError(
                method,
                str(error.get("message", "")),
                code if isinstance(code, int) else None,
            )
        result = answer.get("result")
        if not isinstance(result, dict):
            raise SidecarCallError(method, "the answer has no result")
        return result


class _Client(NamedTuple):
    sdk: Any
    base_url: str


def proxy_client(api: "ModelAPI") -> _Client | None:
    """The SDK client of a model whose calls a sidecar can read, when its base URL was set.

    Only a base URL someone set can point at a proxy, so a provider's own default address is never probed.
    """
    from inspect_ai.model._providers.util import model_base_url

    # as each provider resolves its base URL; its SDK is installed when it is
    # the model's provider, so its module imports
    module = type(api).__module__
    if module == "inspect_ai.model._providers.anthropic":
        from inspect_ai.model._providers.anthropic import AnthropicAPI

        if isinstance(api, AnthropicAPI) and api.service is None:
            if model_base_url(api.base_url, "ANTHROPIC_BASE_URL") is not None:
                return _Client(api.client, str(api.client.base_url))
    elif module == "inspect_ai.model._providers.openai":
        from inspect_ai.model._providers.openai import OpenAIAPI

        if isinstance(api, OpenAIAPI) and not (api.is_azure() or api.is_bedrock()):
            if model_base_url(api.base_url, "OPENAI_BASE_URL") is not None:
                return _Client(api.client, str(api.client.base_url))
    return None


async def probe(client: _Client) -> Sidecar | str:
    """Ask the proxy behind a model's base URL whether a sidecar is there.

    Returns:
        The sidecar, or why none can be used, when the answer means there is none or can't tell.

    Raises:
        SentinelProxyError: If a sidecar answered that Inspect can't work with.
    """
    origin = _origin(client.sdk.base_url)
    try:
        response = await client.sdk.get(
            f"{origin}/sentinel/info",
            cast_to=_response_type(),
            options={"max_retries": 0, "timeout": PROBE_TIMEOUT},
        )
    except Exception as ex:
        status = getattr(ex, "status_code", None)
        if status == 404:
            return f"{origin} has no sidecar"
        logger.debug(f"Probing {origin} for a sentinel sidecar failed: {ex}")
        return f"probing {origin} for a sidecar failed: {ex}"

    try:
        info = response.json()
    except ValueError:
        return f"{origin} answered the probe, but not as a sidecar"
    if not isinstance(info, dict) or info.get("service") != "inspect_sentinel":
        return f"{origin} answered the probe, but not as a sidecar"

    versions = info.get("versions")
    if not isinstance(versions, list) or not any(v in VERSIONS for v in versions):
        raise SentinelProxyError(
            f"The sentinel sidecar at {origin} serves versions {versions} of its endpoint for evals, and this Inspect speaks {list(VERSIONS)}."
        )
    release = info.get("release", "whole")
    if release != "whole":
        raise SentinelProxyError(
            f"The sentinel sidecar at {origin} releases replies early ({release!r}), which Inspect doesn't support yet. Run the sidecar with `--release whole`."
        )
    return Sidecar(origin, release, client.sdk)


def _origin(base_url: Any) -> str:
    # a proxy forwards /sentinel/ at its root, and an OpenAI base URL ends in /v1
    url = str(base_url)
    scheme, _, rest = url.partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}"


def _response_type() -> type:
    # the provider SDKs' raw response type
    import httpx2

    return httpx2.Response
