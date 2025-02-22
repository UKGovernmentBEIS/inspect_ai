import time
from dataclasses import dataclass

import httpx
from shortuuid import uuid


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
    the last request.

    To determine the total time, we also install an httpx response hook. In
    this hook we look for 200 responses which have a registered request id.
    When we find one, we update the end time of the request.

    There is an 'end_request()' method which gets the total requeset time
    for a request_id and then purges the request_id from our tracking (so
    the dict doesn't grow unbounded)
    """

    REQUEST_ID_HEADER = "x-rid"

    def __init__(self, client: httpx.AsyncClient):
        # track request start times
        self._requests: dict[str, float] = {}

        # install httpx request hook
        client.event_hooks["request"].append(self.request_hook)

    def start_request(self) -> str:
        request_id = uuid()
        self._requests[request_id] = time.monotonic()
        return request_id

    def end_request(self, request_id: str) -> float:
        # read the request time if (if available) and purge from dict
        request_time = self._requests.pop(request_id, None)
        if request_time is None:
            raise RuntimeError(f"request_id not registered: {request_id}")

        # return elapsed time
        return time.monotonic() - request_time

    async def request_hook(self, request: httpx.Request) -> None:
        # update the last request time for this request id (as there could be retries)
        request_id = request.headers.get(self.REQUEST_ID_HEADER, None)
        if request_id:
            request_time = self._requests.get(request_id, None)
            if not request_time:
                raise RuntimeError(
                    f"No request registered for request_id: {request_id}"
                )

            # update the request time
            self._requests[request_id] = time.monotonic()
