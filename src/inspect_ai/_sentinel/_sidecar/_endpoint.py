"""Finding a sentinel sidecar behind a model's proxy, and calling its endpoint for evals."""

import base64
import re
import secrets
import sys
import traceback
from dataclasses import dataclass, field
from itertools import count
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, NoReturn
from urllib.parse import unquote, urlsplit

import anyio

from ._sign import answer_message, eval_call_message, now, sign

if TYPE_CHECKING:
    import httpx2

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

UNKNOWN_QUESTION = -32011
"""The sidecar's error code for an answer to a question it doesn't hold for the eval.

The question has closed, or its call has ended.
"""

QUESTION_ANSWERED = -32012
"""The sidecar's error code for an answer to a question that already has an answer."""


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
    registrations_begun: int = 0
    """How many registrations of the task the eval has begun to send, each counted before it is sent. The sidecar may replace what it held for the task with any of them, so a sample's registration counts only while this is what it was when the sample's was sent."""
    registered: bool = False
    """Whether the sidecar has answered a registration of the task, and so holds the eval's token."""
    restarts_found: int = 0
    """How many times the sidecar was found to hold no token for an eval it had registered, as after a restart. It lost with the token everything it held for the eval: the monitor state of each attempt it had begun judging."""

    async def wait_for_registration(self) -> None:
        """Wait while a registration of the task is on its way, however it ends."""
        async with self.lock:
            pass

    def credentials(self, method: str) -> dict[str, Any]:
        """The eval's id, and a signature of a call to a method made now, for the call's params."""
        timestamp = now()
        return {
            "eval_id": self.eval_id,
            "timestamp": timestamp,
            "mac": sign(self.token, eval_call_message(method, self.eval_id, timestamp)),
        }

    def answer_params(
        self, id: str, decision: str, reason: str | None
    ) -> dict[str, Any]:
        """The params for `answer_question`, signed now.

        The signature covers the answer itself.
        """
        timestamp = now()
        params: dict[str, Any] = {
            "eval_id": self.eval_id,
            "timestamp": timestamp,
            "mac": sign(
                self.token,
                answer_message(self.eval_id, timestamp, id, decision, reason),
            ),
            "id": id,
            "decision": decision,
        }
        if reason is not None:
            params["reason"] = reason
        return params


@dataclass
class Sidecar:
    """A sidecar that answered the probe, reached through the model's proxy with the model's own credentials."""

    origin: str
    """The proxy's scheme, host and port, as the model's base URL gives them, credentials included, since Inspect's calls to the sidecar authenticate with them. It holds no path, query or fragment."""
    release: Literal["whole", "early"]
    client: Any = field(repr=False)
    version: int = 1
    """The version of the endpoint for evals Inspect speaks to it."""
    review: bool = False
    """Whether the sidecar sends a sentinel's questions for a person to the eval.

    Inspect shows them in its approval UI.
    """
    access: EvalAccess | None = field(default=None, repr=False)
    base_url: str | None = field(default=None, repr=False)
    """The model's base URL, whose query and fragment, which the origin drops, an error may still repeat. Where it isn't given, the origin's credentials are the only secrets the URL holds."""

    @property
    def proxy_url(self) -> str:
        """The proxy's address without its credentials, for messages and the log."""
        return without_credentials(self.origin)

    """The eval's id and token for this sidecar, shared by every model of the task whose calls go through it."""
    _ids: "count[int]" = field(default_factory=lambda: count(1), repr=False)

    async def eval_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a method of the endpoint for evals for the eval, presenting its id and signing the call with its token.

        Raises:
            SidecarCallError: If the call failed, or was answered with an error, including `unauthorized` when the sidecar keeps another token for the eval or the call's timestamp is outside its window.
        """
        access = self.access
        if access is None or not access.registered:
            _raise_unchained(
                SidecarCallError(method, "the eval hasn't registered with the sidecar")
            )
        return await self.call(method, {**params, **access.credentials(method)})

    async def answer_question(
        self, id: str, decision: str, reason: str | None
    ) -> dict[str, Any]:
        """Send a person's answer to one of the sidecar's questions.

        The call's signature covers the answer, so it can't be reused to send a
        different answer.

        Raises:
            SidecarCallError: If the call failed, or the sidecar refused the answer.
        """
        access = self.access
        if access is None or not access.registered:
            _raise_unchained(
                SidecarCallError(
                    "answer_question", "the eval hasn't registered with the sidecar"
                )
            )
        return await self.call(
            "answer_question", access.answer_params(id, decision, reason)
        )

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a method of the endpoint for evals, and return its result.

        A registration's request holds the eval's token, the base URL may hold the proxy's credentials, in its user info, query or fragment, and an error may repeat the request or the base URL, as a proxy's error page does, or keep the request. So no error raised here holds either in its message, nor is chained to one that may.
        """
        try:
            return await self._call(method, params)
        except SidecarCallError as ex:
            _raise_unchained(ex)

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        handling = sys.exception()
        failed: Exception | None = None
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
            failed = ex
        if failed is not None:
            # Described and raised outside the handler, so that neither this
            # error nor one in describing it is chained to the failure. Each
            # part is redacted before it is trimmed, which could cut a secret
            # short.
            described = " <- ".join(
                self._without_secrets(part).strip()
                for part in _described(failed, handling)
            )
            raise SidecarCallError(method, described)
        if not isinstance(answer, dict):
            raise SidecarCallError(method, "the answer isn't JSON-RPC")
        error = answer.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            raise SidecarCallError(
                method,
                self._without_secrets(str(error.get("message", ""))),
                code if isinstance(code, int) else None,
            )
        result = answer.get("result")
        if not isinstance(result, dict):
            raise SidecarCallError(method, "the answer has no result")
        return result

    def _secrets(self) -> list[tuple[str, str]]:
        # each secret an error may repeat, with what stands in its place
        secrets = _credentials(self.origin if self.base_url is None else self.base_url)
        if self.access is not None:
            secrets.append((self.access.token, REDACTED))
        return secrets

    def _without_secrets(self, text: str) -> str:
        # the text with the proxy's credentials and the eval's token taken out
        return _replaced(text, self._secrets())


def _raise_unchained(error: Exception) -> NoReturn:
    # raised while the caller handles an error, such as a failed model call
    # through the proxy, an error takes that for its context, which keeps the
    # request to the proxy
    try:
        raise error
    finally:
        error.__context__ = None


def _described(error: BaseException, handling: BaseException | None) -> list[str]:
    # the error's message, then each error it was raised from or while
    # handling, as a traceback names them, up to the one the caller was
    # handling; a context an SDK hid with `from None` too, as it may name
    # what failed
    described = [str(error)]
    seen = {id(error)}
    found = _chained(error)
    while found is not None and found is not handling and id(found) not in seen:
        seen.add(id(found))
        described.append("".join(traceback.format_exception_only(found)))
        found = _chained(found)
    return described


def _chained(error: BaseException) -> BaseException | None:
    # the error this one was raised from, or else while handling
    return error.__cause__ if error.__cause__ is not None else error.__context__


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
    base_url = str(client.sdk.base_url)
    origin = _origin(base_url)
    shown = without_credentials(origin)
    failed: Exception | None = None
    response: Any = None
    try:
        response = await client.sdk.get(
            f"{origin}/sentinel/info",
            cast_to=_response_type(),
            options={"max_retries": 0, "timeout": PROBE_TIMEOUT},
        )
    except Exception as ex:
        failed = ex
    if failed is not None:
        # redacted outside the handler, so that an error in redacting isn't
        # chained to the failure
        failure = _replaced(str(failed), _credentials(base_url))
        return NoSidecar(
            *_no_answer(shown, getattr(failed, "status_code", None), failure)
        )

    try:
        info = response.json()
    except Exception:
        # not JSON, or nested past what Python's parser takes
        info = None
    if not isinstance(info, dict) or info.get("service") != "inspect_sentinel":
        return NoSidecar(
            f"{shown} answered the probe, but not as a sidecar", definite=True
        )

    # The errors repeat nothing the sidecar answered but its integer
    # versions, as text may hold a secret: of the base URL, or the eval's
    # token, which this probe doesn't know. Raised while the caller handles an
    # error, such as a failed model call through the proxy, they keep none.
    versions = info.get("versions")
    served = [
        v
        for v in (versions if isinstance(versions, list) else [])
        if isinstance(v, int) and not isinstance(v, bool)
    ]
    if not any(v in VERSIONS for v in served):
        _raise_unchained(
            SentinelProxyError(
                f"The sentinel sidecar at {shown} serves versions {served} of its endpoint for evals, and this Inspect speaks {list(VERSIONS)}."
            )
        )
    release = info.get("release", "whole")
    if release != "whole":
        _raise_unchained(
            SentinelProxyError(
                f"The sentinel sidecar at {shown} releases replies early, which Inspect doesn't support yet. Run the sidecar with `--release whole`."
            )
        )
    version = max(v for v in served if v in VERSIONS)
    # A sidecar that doesn't report `review`, such as one from before sidecars
    # could ask a person through an eval, asks no questions through the eval.
    review = info.get("review") is True
    return Sidecar(origin, release, client.sdk, version, review, base_url=base_url)


def _no_answer(origin: str, status: object, failure: str) -> tuple[str, bool]:
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
    return f"probing {origin} for a sidecar failed: {failure}", False


def _origin(url: "httpx2.URL | str") -> str:
    # a proxy forwards /sentinel/ at its root, an OpenAI base URL ends in /v1,
    # and a base URL's query or fragment isn't the proxy's
    import httpx2

    root = httpx2.URL(url).copy_with(path="/", query=None, fragment=None)
    return str(root).removesuffix("/")


def without_credentials(origin: str) -> str:
    """An origin without the user and password a base URL can carry, for showing or recording it."""
    import httpx2

    shown = httpx2.URL(origin).copy_with(username=None, password=None, path="/")
    return str(shown).removesuffix("/")


def _credentials(url: str) -> list[tuple[str, str]]:
    # each secret the URL holds, decoded, with what stands in its place: the
    # whole user info goes, and each of its parts is redacted, as is the
    # Basic authorization httpx sends for it. So is each query value, or the
    # name of an item with none, and the fragment. The slash the anthropic
    # SDK puts on the end of its base URL's query is left off, as redacting a
    # value covers it with the slash.
    import httpx2

    secrets: list[tuple[str, str]] = []

    def add(text: str, shown: str) -> None:
        # decoded keeping each byte that isn't UTF-8, decoded as Python does
        # by default, which writes one U+FFFD for a cut-off sequence, and
        # decoded as Latin-1 or Windows-1252, as a server may decode a query
        # or label its page; each trimmed too, form-decoded first, as the
        # anthropic SDK trims an error page that ends in it
        decoded = [
            unquote(text, errors=errors) for errors in ("surrogateescape", "replace")
        ]
        decoded += [
            unquote(text, encoding=encoding, errors="replace")
            for encoding in ("latin-1", "cp1252")
        ]
        secrets.extend(
            (secret, shown)
            for each in decoded
            for secret in (each, each.strip(), each.replace("+", " ").strip())
        )

    userinfo = httpx2.URL(url).userinfo.decode("ascii")
    if userinfo:
        user, _, password = userinfo.partition(":")
        add(f"{userinfo}@", "")
        add(user, REDACTED)
        add(password, REDACTED)
        basic = f"{unquote(user)}:{unquote(password)}".encode()
        secrets.append((base64.b64encode(basic).decode("ascii"), REDACTED))
    parts = urlsplit(url)
    # each item whole too, as a parser that splits at `;` inside a value, or
    # at `=` inside a name, repeats it
    for item in re.split("[&;]", parts.query.removesuffix("/")):
        name, _, value = item.partition("=")
        add(value or name, REDACTED)
        add(item, REDACTED)
    add(parts.fragment, REDACTED)
    return [(secret, shown) for secret, shown in secrets if secret]


def _spellings(secret: str) -> str:
    # a pattern for the secret however an error spells it: each character as
    # itself or percent-encoded, in either case, and a space and a plus as
    # either, as form encoding writes them. A byte that isn't UTF-8, kept as
    # its surrogate, is that or percent-encoded. The encoded spelling is tried
    # first, so that a `%` doesn't match alone where `%25` spells it.
    def spelled(char: str) -> list[str]:
        if "\udc80" <= char <= "\udcff":
            return [f"%(?i:{ord(char) - 0xDC00:02x})", re.escape(char)]
        encoded = "".join(f"%(?i:{byte:02x})" for byte in char.encode())
        return [encoded, re.escape(char)]

    pattern = []
    for char in secret:
        chars = {" ", "+"} if char in " +" else {char}
        pattern.append(
            f"(?:{'|'.join(form for c in sorted(chars) for form in spelled(c))})"
        )
    return "".join(pattern)


def _found(text: str, secrets: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    # where the secrets are in the text, however spelled, with what stands in
    # each place. Matches that overlap are merged, so that no part of a secret
    # is left beside another that starts before it; a span that overlaps the
    # whole user info goes, and any other is redacted.
    matches = [
        (found.start(), found.end(1), shown)
        for secret, shown in secrets
        if secret
        for found in re.finditer(f"(?=({_spellings(secret)}))", text)
    ]
    merged: list[tuple[int, int, str]] = []
    for start, end, shown in sorted(matches):
        if merged and start < merged[-1][1]:
            first, last, before = merged[-1]
            removed = "" if "" in (before, shown) else REDACTED
            merged[-1] = (first, max(last, end), removed)
        else:
            merged.append((start, end, shown))
    return merged


def _replaced(text: str, secrets: list[tuple[str, str]]) -> str:
    # the text with each secret, however spelled, replaced
    pieces: list[str] = []
    at = 0
    for start, end, shown in _found(text, secrets):
        pieces += [text[at:start], shown]
        at = end
    pieces.append(text[at:])
    return "".join(pieces)


def _response_type() -> type:
    # the provider SDKs' raw response type
    import httpx2

    return httpx2.Response
