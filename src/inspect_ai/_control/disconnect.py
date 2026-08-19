"""Client-disconnect guard for nontrivial control-server read routes.

Structural guard from the endpoint cost audit
(``design/ctl/endpoint-cost-audit.md`` "Structural guards"): uvicorn keeps
processing queued requests after their clients disconnect, so a timed-out
poller (or a CLI killed mid-request) leaves the server computing and
serializing answers nobody will read — on the eval's own event loop, at the
eval's expense. The dependency here answers such requests with an unread 499
before the handler runs.

Attached per-route, to the reads that do nontrivial work (listing builds and
the per-sample detail / events / messages reads) — NOT app-wide: mutations
must not carry it (a directive's intent was expressed when the request was
sent; skipping it because the client gave up waiting would silently drop
it), and on the trivially cheap handlers — the O(registry entries) config
views included — the check adds nothing. Guarded routes must also never read
a request body: the poll consumes a buffered ``http.request`` message, so a
later body read would hang. Fine for the body-less GETs the guard is
attached to; a hard constraint on extending it.

Best-effort by design, in two ways. The check is a non-blocking poll of the
connection's receive channel, so it only helps when the loop yields between
queued requests — which cheap handlers guarantee and a CPU-bound handler
would defeat (handlers first, guard second: the ordering lesson of the
audit's incident). And uvicorn only marks a connection disconnected once its
``connection_lost`` callback runs, which the event loop schedules *behind*
already-queued request tasks — so the first wave of requests after a loop
stall is typically served even though their clients are gone; what the guard
trims is the sustained backlog behind it.

Lives in its own module for the same reason as ``strict.py``: it needs
``fastapi`` imported at module scope — ``server.py`` imports FastAPI lazily
inside ``_build_app`` and uses ``from __future__ import annotations``, so a
``Request``-annotated parameter defined there can't be resolved when FastAPI
evaluates the dependency signature. This module is itself imported lazily
from ``_build_app``, preserving the no-FastAPI-cost-at-import property.
"""

from logging import getLogger

from fastapi import Request

logger = getLogger(__name__)


class ClientDisconnectedError(Exception):
    """The request's client hung up before the handler ran.

    Raised by :func:`reject_disconnected_client`; ``server.py``'s exception
    handler converts it to a 499 (nginx's "client closed request"
    convention). Nobody observes that response — the client is gone, uvicorn
    drops writes to disconnected transports, and access logging is off — so
    the debug log line below is the guard's only trace.
    """


async def reject_disconnected_client(request: Request) -> None:
    """Dependency that skips serving a client that already hung up.

    See the module docstring for the rationale and for which routes attach
    it. Raises :class:`ClientDisconnectedError` (answered 499) when the
    client has disconnected; otherwise the request proceeds normally.
    """
    if await request.is_disconnected():
        logger.debug(
            "Control request %s skipped: client disconnected", request.url.path
        )
        raise ClientDisconnectedError()
