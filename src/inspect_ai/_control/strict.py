"""Strict query-param validation for control-server mutation routes.

FastAPI silently drops query params a handler doesn't declare, so a newer
client sending a knob an older server doesn't know would get a partial
apply behind a success-shaped response. The dependency here fails such
requests closed — 400 *before* the handler runs, so the mutation is
atomic: either every requested knob is recognized or nothing changes.

Lives in its own module (rather than ``server.py``) because it needs
``fastapi`` imported at module scope: ``server.py`` imports FastAPI lazily
inside ``_build_app`` and uses ``from __future__ import annotations``, so a
``Request``-annotated parameter defined there can't be resolved when FastAPI
evaluates the endpoint signature. This module is itself imported lazily from
``_build_app``, preserving the no-FastAPI-cost-at-import property.

GET routes stay tolerant: an ignored read param can't corrupt anything, and
rejecting reads would break older clients against newer servers if a read
param were ever removed.
"""

from fastapi import Request


class UnknownQueryParamsError(Exception):
    """A mutation request carried query params its route doesn't declare.

    Raised by :func:`reject_unknown_query_params` before the handler runs;
    ``server.py`` registers an exception handler that converts it to a 400
    with the ``{"error": ...}`` body shape the control clients expect.
    """

    def __init__(self, unknown: list[str]) -> None:
        super().__init__(
            f"unknown config parameter(s): {', '.join(unknown)} "
            "(this inspect version does not support them)"
        )


async def reject_unknown_query_params(request: Request) -> None:
    """Fail closed on query params the matched route doesn't declare.

    Attach as a route dependency (``dependencies=[Depends(...)]``) to any
    mutation route whose knobs ride query params. The allowed set is derived
    from the matched route's own declared query parameters, so it can't
    drift as knobs are added — a new knob on the handler signature is
    allowed automatically, with no companion list to maintain.

    Raises:
        UnknownQueryParamsError: For any query param the route doesn't
            declare, naming every unknown param (sorted).
    """
    allowed = {
        param.alias or param.name
        for param in request.scope["route"].dependant.query_params
    }
    unknown = sorted(set(request.query_params.keys()) - allowed)
    if unknown:
        raise UnknownQueryParamsError(unknown)
