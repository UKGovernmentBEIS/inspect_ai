import time
from dataclasses import dataclass

import httpx


@dataclass
class RequestTime:
    start: float
    end: float | None


class HttpxTimeTracker:
    """Class which tracks the duration of successful (200 status) http requests.

    A special header is injected into requests which is then read from
    an httpx 'request' event hook -- this creates a record of when the request
    started. Note that with retries a single request id could be started
    several times; our request hook makes sure we always track the time of
    the most recnet request.

    To determine the total time, we also install an httpx response hook. In
    this hook we look for:
      - 200 responses
      - Which have a request id header
      - Which have a start time from the 'request' hook
    When we find one, we update the end time of the request.

    There is a separate 'collect_time()' method which gets the
    total request time for a request_id (if available) and then purges
    the request_id from our tracking (so the dict doesn't grow unbounded)
    """

    REQUEST_ID_HEADER = "x-rid"

    def __init__(self, client: httpx.AsyncClient):
        # track requests
        self._requests: dict[str, RequestTime] = {}

        # install httpx hooks
        client.event_hooks["request"].append(self.request_hook)
        client.event_hooks["response"].append(self.response_hook)

    async def request_hook(self, request: httpx.Request) -> None:
        # insert or update the last request time for this request id
        # (as there could be multiple retries)
        request_id = request.headers.get(self.REQUEST_ID_HEADER, None)
        if request_id:
            request_time = self._requests.get(request_id, None)
            # update existing (this must be retry)
            if request_time:
                request_time.start = time.monotonic()
            # create new (this is the first request)
            else:
                self._requests[request_id] = RequestTime(
                    start=time.monotonic(), end=None
                )

    async def response_hook(self, response: httpx.Response) -> None:
        # collect successful responses that we are already tracking a request id for
        if response.status_code == 200:
            request_id = response.request.headers.get(self.REQUEST_ID_HEADER, None)
            if request_id:
                request_time = self._requests.get(request_id, None)
                if request_time:
                    request_time.end = time.monotonic()

    def collect_time(self, request_id: str) -> float | None:
        # read the total request if (if available) and purge from dict
        request_time = self._requests.pop(request_id, None)
        if request_time and request_time.end:
            return request_time.end - request_time.start
        else:
            return None
