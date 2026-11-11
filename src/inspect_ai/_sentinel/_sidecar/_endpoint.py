"""Finding a sentinel sidecar behind a model's proxy, and calling its endpoint for evals."""

import secrets
from dataclasses import dataclass, field
from itertools import count
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

import anyio

from ._sign import eval_call_message, now, sign

if TYPE_CHECKING:
    from inspect_ai.model._model import ModelAPI

logger = getLogger(__name__)

VERSIONS = (1,)
"""The versions of the sidecar's endpoint for evals that Inspect speaks."""

PROBE_TIMEOUT = 10.0
CALL_TIMEOUT = 60.0

REDACTED = "<redacted>"
"""What the eval's token is replaced with wherever it would otherwise be logged or reported."""

UNAUTHORIZED = -32010
"""The sidecar's error for a call whose token or signature doesn't match the token it keeps for the eval, or whose timestamp is outside its window."""


class SentinelProxyError(RuntimeError):
    """A sidecar the task needs is missing, or the one found can't be used."""


class SidecarCallError(RuntimeError):
    """A call to the sidecar's endpoint for evals failed, or was answered with an error."""

    def __init__(self, method: str, message: str, code: int | None = None) -> None:
        super().__init__(f"The sidecar's {method} failed: {message}")
        self.method = method
        self.code = code


@dataclass
class EvalAccess:
    """The eval's id and token for one sidecar, which signs every call to it but a registration the sidecar holds no token for."""

    eval_id: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    """The token the eval made for the sidecar, which never changes. It is sent only in a registration to a sidecar that holds no token for the eval, and signs everything else."""
    lock: anyio.Lock = field(default_factory=anyio.Lock, repr=False)
    """Held while the eval registers, so a sidecar that lost the task is registered again once, not by every sample that finds it lost."""
    registrations: int = 0
    """How many registrations of the task the sidecar has taken."""

    def credentials(self, method: str) -> dict[str, Any]:
        """The eval's id, and a signature of a call to a method made now, for the call's params."""
        timestamp = now()
        return {
            "eval_id": self.eval_id,
            "timestamp": timestamp,
            "mac": sign(self.token, eval_call_message(method, self.eval_id, timestamp)),
        }


@dataclass
class Sidecar:
    """A sidecar that answered the probe, reached through the model's proxy with the model's own credentials."""

    origin: str
    release: Literal["whole", "early"]
    client: Any = field(repr=False)
    version: int = 1
    """The version of the endpoint for evals Inspect speaks to it."""
    access: EvalAccess | None = field(default=None, repr=False)
    """The eval's id and token for this sidecar, shared by every model of the task whose calls go through it."""
    _ids: "count[int]" = field(default_factory=lambda: count(1), repr=False)

    async def eval_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a method of the endpoint for evals for the eval, presenting its id and signing the call with its token.

        Raises:
            SidecarCallError: If the call failed, or was answered with an error, including `unauthorized` when the sidecar keeps another token for the eval or the call's timestamp is outside its window.
        """
        access = self.access
        if access is None or access.registrations == 0:
            raise SidecarCallError(
                method, "the eval hasn't registered with the sidecar"
            )
        return await self.call(method, {**params, **access.credentials(method)})

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a method of the endpoint for evals, and return its result.

        A registration's request holds the eval's token, and an error may repeat the request, as a proxy's error page does. So no error raised here holds the token, in its message or in an error it is chained to.
        """
        failed: str | None = None
        answer: Any = None
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
            if not self._holds_token(ex):
                raise SidecarCallError(method, str(ex)) from ex
            failed = self._without_token(str(ex))
        if failed is not None:
            # Raised outside the handler, so the error that holds the token
            # is neither this one's cause nor its context: a traceback prints
            # both.
            raise SidecarCallError(method, failed)
        if not isinstance(answer, dict):
            raise SidecarCallError(method, "the answer isn't JSON-RPC")
        error = answer.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            raise SidecarCallError(
                method,
                self._without_token(str(error.get("message", ""))),
                code if isinstance(code, int) else None,
            )
        result = answer.get("result")
        if not isinstance(result, dict):
            raise SidecarCallError(method, "the answer has no result")
        return result

    def _without_token(self, text: str) -> str:
        # the text with the eval's token taken out
        access = self.access
        return text.replace(access.token, REDACTED) if access is not None else text

    def _holds_token(self, error: BaseException) -> bool:
        # whether the error, or one it is chained to, holds the eval's token
        access = self.access
        if access is None:
            return False
        seen: set[int] = set()
        pending: list[BaseException | None] = [error]
        while pending:
            found = pending.pop()
            if found is None or id(found) in seen:
                continue
            seen.add(id(found))
            if access.token in str(found):
                return True
            pending += [found.__cause__, found.__context__]
        return False


class _Client(NamedTuple):
    sdk: Any
    base_url: str


class NoSidecar(NamedTuple):
    """Why a probe found no sidecar to use."""

    reason: str
    definite: bool
    """Whether the answer settles it for the task: a 404 or an answer that isn't a sidecar does, and a failure that may pass next time doesn't."""


async def proxy_client(api: "ModelAPI") -> _Client | None:
    """The SDK client of a model whose calls a sidecar can read, when its base URL was set.

    Anthropic, OpenAI and OpenAI-compatible providers (such as Together, vLLM, Ollama and `openai-api/<service>/<model>`) are probed. Only a base URL someone set can point at a proxy, so a provider's own default address is never probed.
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
    else:
        # the provider knows whether its base URL was set or is the service's
        # own; the openai SDK may be absent for other providers
        try:
            from inspect_ai.model._providers.openai_compatible import (
                OpenAICompatibleAPI,
            )
        except ImportError:
            return None
        if isinstance(api, OpenAICompatibleAPI):
            found = await api.proxy_endpoint()
            if found is not None:
                sdk, _ = found
                return _Client(sdk, str(sdk.base_url))
    return None


async def probe(client: _Client) -> Sidecar | NoSidecar:
    """Ask the proxy behind a model's base URL whether a sidecar is there.

    Returns:
        The sidecar, or why none can be used: definite when the answer means there is none, and not when it can't tell.

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
        return NoSidecar(*_no_answer(origin, getattr(ex, "status_code", None), ex))

    try:
        info = response.json()
    except ValueError:
        info = None
    if not isinstance(info, dict) or info.get("service") != "inspect_sentinel":
        return NoSidecar(
            f"{origin} answered the probe, but not as a sidecar", definite=True
        )

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
    version = max(v for v in versions if v in VERSIONS)
    return Sidecar(origin, release, client.sdk, version)


def _no_answer(origin: str, status: object, ex: Exception) -> tuple[str, bool]:
    # An HTTP status means the endpoint answered: a 404 says there is no
    # sidecar, and any other 4xx that none can be reached there with the
    # model's credentials, as from a gateway that answers an unknown route
    # with 403 or 405. A 408 or 429, a 5xx, a timeout or no connection may
    # pass next time, so none of those settles it.
    if status == 404:
        return f"{origin} has no sidecar", True
    if isinstance(status, int) and 400 <= status < 500 and status not in (408, 429):
        return (
            f"{origin} answered the probe with {status}, so no sidecar can be reached there",
            True,
        )
    return f"probing {origin} for a sidecar failed: {ex}", False


def _origin(base_url: Any) -> str:
    # a proxy forwards /sentinel/ at its root, and an OpenAI base URL ends in /v1
    url = str(base_url)
    scheme, _, rest = url.partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}"


def _response_type() -> type:
    # the provider SDKs' raw response type
    import httpx2

    return httpx2.Response
