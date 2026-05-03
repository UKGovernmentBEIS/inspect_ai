import re
import time
from logging import getLogger
from typing import Any, Literal, Mapping, NamedTuple, cast

import httpx
from shortuuid import uuid

from inspect_ai._util.constants import HTTP
from inspect_ai._util.http import parse_retry_after
from inspect_ai._util.retry import report_http_retry

logger = getLogger(__name__)


# Classification of the most recent response for retry-reporting purposes.
# `None` means "infer from HTTP status" (default: status==429 is rate_limit).
RetryKind = Literal["rate_limit", "transient"]


class RequestInfo(NamedTuple):
    attempts: int
    last_request: float
    # populated by response_hook for the most recent attempt — used by
    # update_request_time on the next retry to classify rate_limit vs transient
    # and to honor server-provided wait times.
    last_status: int | None = None
    # Stored as an absolute monotonic deadline (time.monotonic() + retry_after)
    # rather than a duration. Between recording and consuming, the SDK may do
    # its own backoff, so we recompute the *remaining* seconds at consumption
    # time — otherwise the controller's `now + retry_after` cooldown formula
    # would double-count any time the SDK already waited.
    last_retry_after_deadline: float | None = None
    # Provider-supplied classification for the previous response. Set by
    # subclasses (e.g. ConverseHooks) when the HTTP status alone isn't enough
    # to classify (Bedrock throttling errors don't necessarily surface as 429).
    # When None, update_request_time falls back to inferring from status.
    last_kind: RetryKind | None = None


class HttpHooks:
    """Class which hooks various HTTP clients for improved tracking/logging.

    A special header is injected into requests which is then read from
    a request event hook -- this creates a record of when the request
    started. Note that with retries a single request_id could be started
    several times; our request hook makes sure we always track the time of
    the last request.

    There is an 'end_request()' method which gets the total request time
    for a request_id and then purges the request_id from our tracking (so
    the dict doesn't grow unbounded)

    Additionally, an http response hook is installed and used for logging
    requests for the 'http' log-level
    """

    REQUEST_ID_HEADER = "x-irid"

    def __init__(self) -> None:
        # track request start times
        self._requests: dict[str, RequestInfo] = {}

    def start_request(self) -> str:
        request_id = uuid()
        self._requests[request_id] = RequestInfo(0, time.monotonic())
        return request_id

    def end_request(self, request_id: str) -> float:
        # read the request info (if available) and purge from dict
        request_info = self._requests.pop(request_id, None)
        if request_info is None:
            logger.warning(f"Hooks: request_id not registered: {request_id}")
            return 0

        # return elapsed time
        return time.monotonic() - request_info.last_request

    def record_response(
        self,
        request_id: str | None,
        status: int,
        headers: Mapping[str, str] | None,
        *,
        kind: RetryKind | None = None,
    ) -> None:
        """Record the most recent response for a request_id.

        Called from response_hook so that the next request_hook (when this
        attempt is retried) can classify the retry based on what the previous
        attempt actually returned.

        Args:
            request_id: The Inspect request id (from User-Agent / header).
            status: HTTP status code.
            headers: Response headers (used to extract Retry-After fallback).
            kind: Optional explicit classification. Pass when the HTTP status
                alone doesn't determine kind — e.g. Bedrock's
                ThrottlingException, where the error code in the body is the
                authoritative signal. When None (default), update_request_time
                infers kind from `status == 429`.
        """
        if not request_id:
            return
        info = self._requests.get(request_id)
        if info is None:
            return
        # Convert the relative Retry-After to an absolute monotonic deadline
        # so any SDK-side backoff between now and the next retry is accounted
        # for when we report remaining seconds to the controller.
        deadline: float | None = None
        if headers is not None:
            try:
                retry_after = parse_retry_after(headers)
            except Exception:
                retry_after = None
            if retry_after is not None and retry_after > 0:
                deadline = time.monotonic() + retry_after
        self._requests[request_id] = RequestInfo(
            info.attempts, info.last_request, status, deadline, kind
        )

    def update_request_time(self, request_id: str) -> None:
        request_info = self._requests.get(request_id, None)
        if not request_info:
            logger.warning(f"Hooks: No request registered for request_id: {request_id}")
            return

        new_attempts = request_info.attempts + 1
        # snapshot the previous attempt's response info before clearing —
        # we use it to classify the retry below, and clearing prevents
        # reusing this 429 if a subsequent attempt fails before its own
        # response arrives (which would otherwise scale the controller down
        # again from stale state — classic infra-noise contamination).
        prev_status = request_info.last_status
        prev_kind = request_info.last_kind
        # Compute remaining seconds from the absolute deadline at the moment
        # the retry actually fires — accounts for any SDK-side backoff
        # already elapsed since the response was received.
        prev_retry_after: float | None = None
        if request_info.last_retry_after_deadline is not None:
            remaining = request_info.last_retry_after_deadline - time.monotonic()
            if remaining > 0:
                prev_retry_after = remaining

        # store the new attempts/timestamp; last_status/last_retry_after reset
        # to None so they're only repopulated by the next response_hook call.
        self._requests[request_id] = RequestInfo(
            new_attempts, time.monotonic(), None, None, None
        )

        # trace a retry if this is the 2nd or later attempt; classify based
        # on either an explicit provider-supplied kind (set via record_response
        # when the HTTP status alone is insufficient — e.g. Bedrock) or
        # falling back to status==429 detection.
        if new_attempts > 1:
            if prev_kind is not None:
                report_http_retry(kind=prev_kind, retry_after=prev_retry_after)
            elif prev_status == 429:
                report_http_retry(kind="rate_limit", retry_after=prev_retry_after)
            else:
                report_http_retry()


class ConverseHooks(HttpHooks):
    # Key under which we stash the Inspect request_id on botocore's per-call
    # context dict so the response-received handler can look it up.
    _CTX_REQUEST_ID = "_inspect_request_id"

    def __init__(self, session: Any) -> None:
        from aiobotocore.session import AioSession

        super().__init__()

        # register hooks. We use:
        #   * request-created (per-attempt): record start time + stash request_id
        #     on the request's context dict so response-received can look it up.
        #     We use this rather than before-send because before-send receives
        #     an AWSPreparedRequest, which has no `.context` — the AWSRequest
        #     emitted from request-created does, and that context dict IS the
        #     same per-call context that flows into response-received.
        #   * response-received (per-attempt): record the response status for
        #     the *next* retry's classification. (after-call fires only once
        #     at the end of all SDK-internal retries, so it would miss the
        #     per-attempt 429s that botocore swallows via adaptive retry.)
        session = cast(AioSession, session._session)
        session.register(
            "request-created.bedrock-runtime.Converse",
            self.converse_request_created,
        )
        session.register(
            "response-received.bedrock-runtime.Converse",
            self.converse_response_received,
        )

    def converse_request_created(self, **kwargs: Any) -> None:
        request = kwargs.get("request")
        if request is None:
            return
        user_agent = request.headers.get("User-Agent", b"")
        if isinstance(user_agent, bytes):
            user_agent = user_agent.decode()
        match = re.search(rf"{self.USER_AGENT_PREFIX}(\w+)", user_agent)
        if not match:
            return
        request_id = match.group(1)
        # stash request_id where response-received can find it. AWSRequest's
        # `.context` IS the per-call context dict (same identity, see
        # botocore.awsrequest.create_request_object), so this survives across
        # the request-created → response-received boundary, and across all
        # SDK-internal retries within one API call.
        ctx = getattr(request, "context", None)
        if isinstance(ctx, dict):
            ctx[self._CTX_REQUEST_ID] = request_id
        self.update_request_time(request_id)

    # AWS error codes that indicate true rate-limiting (the 429-equivalent on
    # Bedrock). Kept in sync with BedrockAPI._BEDROCK_THROTTLE_CODES — duplicated
    # here so the hook layer doesn't need to import the provider.
    _THROTTLE_CODES = frozenset(
        [
            "ThrottlingException",
            "RequestLimitExceeded",
            "Throttling",
            "RequestThrottled",
            "TooManyRequestsException",
            "ProvisionedThroughputExceededException",
        ]
    )

    def converse_response_received(
        self,
        response_dict: dict[str, Any] | None = None,
        parsed_response: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        # Fires after each HTTP attempt (including ones that botocore will
        # internally retry), so the recorded status arrives in time for the
        # next request-created to classify the retry.
        if response_dict is None:
            return
        status = response_dict.get("status_code")
        if status is None:
            return
        url = response_dict.get("url", "")
        logger.log(HTTP, f"POST {url} - {status}")
        request_id = (
            context.get(self._CTX_REQUEST_ID) if isinstance(context, dict) else None
        )
        if not request_id:
            return
        # Classify based on AWS error code (the authoritative signal on Bedrock,
        # since ThrottlingException doesn't always come back as HTTP 429). When
        # there's an error in parsed_response, look at its Code; otherwise let
        # update_request_time fall back to status-based inference.
        kind: RetryKind | None = None
        if isinstance(parsed_response, dict):
            error = parsed_response.get("Error")
            if isinstance(error, dict):
                code = error.get("Code", "")
                if code in self._THROTTLE_CODES:
                    kind = "rate_limit"
                elif code:
                    # Any non-throttle AWS error code → transient (don't let
                    # the status fallback misclassify a 429 from non-throttling
                    # validation errors, etc.)
                    kind = "transient"
        # Bedrock doesn't include Retry-After per AWS docs, but pass response
        # headers through anyway in case a future API does — parse_retry_after
        # just returns None when no recognized header is present.
        headers = response_dict.get("headers")
        self.record_response(request_id, status, headers, kind=kind)

    def user_agent_extra(self, request_id: str) -> str:
        return f"{self.USER_AGENT_PREFIX}{request_id}"

    USER_AGENT_PREFIX = "ins/rid#"


class HttpxHooks(HttpHooks):
    def __init__(self, client: httpx.AsyncClient):
        super().__init__()

        # install hooks
        client.event_hooks["request"].append(self.request_hook)
        client.event_hooks["response"].append(self.response_hook)

    async def request_hook(self, request: httpx.Request) -> None:
        # update the last request time for this request id (as there could be retries)
        request_id = request.headers.get(self.REQUEST_ID_HEADER, None)
        if request_id:
            self.update_request_time(request_id)

    async def response_hook(self, response: httpx.Response) -> None:
        message = f'{response.request.method} {response.request.url} "{response.http_version} {response.status_code} {response.reason_phrase}" '
        logger.log(HTTP, message)
        # record status + Retry-After / x-ratelimit-reset-* for next retry classification
        request_id = response.request.headers.get(self.REQUEST_ID_HEADER, None)
        self.record_response(request_id, response.status_code, response.headers)


def urllib3_hooks() -> HttpHooks:
    import urllib3
    from urllib3.connectionpool import HTTPConnectionPool
    from urllib3.response import BaseHTTPResponse

    class Urllib3Hooks(HttpHooks):
        def request_hook(self, headers: Mapping[str, str]) -> None:
            # update the last request time for this request id (as there could be retries)
            request_id = headers.get(self.REQUEST_ID_HEADER, None)
            if request_id:
                self.update_request_time(request_id)

        def response_hook(
            self,
            method: str,
            url: str,
            response: BaseHTTPResponse,
            request_headers: Mapping[str, str] | None = None,
        ) -> None:
            message = f'{method} {url} "{response.version_string} {response.status} {response.reason}" '
            logger.log(HTTP, message)
            # record status + headers for next retry classification
            request_id = (
                request_headers.get(self.REQUEST_ID_HEADER) if request_headers else None
            )
            # urllib3 BaseHTTPResponse.headers is HTTPHeaderDict, treat as Mapping[str, str]
            self.record_response(
                request_id,
                response.status,
                cast(Mapping[str, str], response.headers),
            )

    global _urlilb3_hooks
    if _urlilb3_hooks is None:
        # one time patch of urlopen
        urlilb3_hooks = Urllib3Hooks()
        original_urlopen = urllib3.connectionpool.HTTPConnectionPool.urlopen

        def patched_urlopen(
            self: HTTPConnectionPool, method: str, url: str, **kwargs: Any
        ) -> BaseHTTPResponse:
            headers = kwargs.get("headers", {})
            urlilb3_hooks.request_hook(headers)
            response = original_urlopen(self, method, url, **kwargs)
            urlilb3_hooks.response_hook(method, f"{self.host}{url}", response, headers)
            return response

        urllib3.connectionpool.HTTPConnectionPool.urlopen = patched_urlopen  # type: ignore[assignment,method-assign]

        # assign to global hooks instance
        _urlilb3_hooks = urlilb3_hooks

    return _urlilb3_hooks


_urlilb3_hooks: HttpHooks | None = None
