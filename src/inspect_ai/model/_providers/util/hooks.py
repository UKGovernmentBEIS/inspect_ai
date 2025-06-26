import re
import time
from logging import getLogger
from typing import Any, Mapping, NamedTuple, cast

import httpx
from shortuuid import uuid

from inspect_ai._util.constants import HTTP
from inspect_ai._util.retry import report_http_retry

logger = getLogger(__name__)


class RequestInfo(NamedTuple):
    attempts: int
    last_request: float


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
            raise RuntimeError(f"request_id not registered: {request_id}")

        # return elapsed time
        return time.monotonic() - request_info.last_request

    def update_request_time(self, request_id: str) -> None:
        request_info = self._requests.get(request_id, None)
        if not request_info:
            raise RuntimeError(f"No request registered for request_id: {request_id}")

        # update the attempts and last request time
        request_info = RequestInfo(request_info.attempts + 1, time.monotonic())
        self._requests[request_id] = request_info

        # trace a retry if this is attempt > 1
        if request_info.attempts > 1:
            report_http_retry()


class ConverseHooks(HttpHooks):
    def __init__(self, session: Any) -> None:
        from aiobotocore.session import AioSession

        super().__init__()

        # register hooks
        session = cast(AioSession, session._session)
        session.register(
            "before-send.bedrock-runtime.Converse", self.converse_before_send
        )
        session.register(
            "after-call.bedrock-runtime.Converse", self.converse_after_call
        )

    def converse_before_send(self, **kwargs: Any) -> None:
        user_agent = kwargs["request"].headers["User-Agent"].decode()
        match = re.search(rf"{self.USER_AGENT_PREFIX}(\w+)", user_agent)
        if match:
            request_id = match.group(1)
            self.update_request_time(request_id)

    def converse_after_call(self, http_response: Any, **kwargs: Any) -> None:
        from botocore.awsrequest import AWSResponse

        response = cast(AWSResponse, http_response)
        logger.log(HTTP, f"POST {response.url} - {response.status_code}")

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
            self, method: str, url: str, response: BaseHTTPResponse
        ) -> None:
            message = f'{method} {url} "{response.version_string} {response.status} {response.reason}" '
            logger.log(HTTP, message)

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
            urlilb3_hooks.response_hook(method, f"{self.host}{url}", response)
            return response

        urllib3.connectionpool.HTTPConnectionPool.urlopen = patched_urlopen  # type: ignore[assignment,method-assign]

        # assign to global hooks instance
        _urlilb3_hooks = urlilb3_hooks

    return _urlilb3_hooks


_urlilb3_hooks: HttpHooks | None = None
