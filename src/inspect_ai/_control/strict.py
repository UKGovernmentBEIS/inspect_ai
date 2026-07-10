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
param were ever removed. The dependency is attached app-wide and enforces
this policy itself by short-circuiting on safe methods, so every mutation
route — including ones added later — is born strict with no per-route
annotation to remember.

``route.dependant`` and ``get_flat_dependant`` are FastAPI internals (no
public API exposes a route's declared query params), and the fastapi pin is
unbounded. If a future FastAPI moves them, the error surfaces when
``_build_app`` imports this module, and ``control_server()`` degrades to
running the eval without the control surface (warning logged) — the tests
exercising this dependency keep that breakage visible in CI on version bumps.
"""

from fastapi import Request
from fastapi.dependencies.utils import get_flat_dependant


class UnknownQueryParamsError(Exception):
    """A mutation request carried query params its route doesn't declare.

    Raised by :func:`reject_unknown_query_params` before the handler runs;
    ``server.py`` registers an exception handler that converts it to a 400
    with the ``{"error": ...}`` body shape the control clients expect.
    """

    def __init__(self, unknown: list[str]) -> None:
        super().__init__(
            f"unknown query parameter(s): {', '.join(unknown)} "
            "(this inspect version does not support them)"
        )


async def reject_unknown_query_params(request: Request) -> None:
    """Fail closed on query params the matched route doesn't declare.

    Attach app-wide (``FastAPI(dependencies=[Depends(...)])``) so every
    mutation route is strict from the moment it's added. Safe methods
    (reads) short-circuit here — see the module docstring for why GETs
    stay tolerant. The allowed set is derived from the matched route's
    own declared query parameters, so it can't drift as knobs are added —
    a new knob on the handler signature is allowed automatically, with no
    companion list to maintain.

    One caveat: declare knobs as individual scalar parameters, not a
    Pydantic query model (``Annotated[Model, Query()]``). The flattened
    dependant records the function parameter's name rather than the model's
    field names, so a route using that idiom would falsely 400 every real
    param. The failure is loud (the route's own tests would catch it
    immediately), but the idiom is unsupported here.

    Raises:
        UnknownQueryParamsError: For any query param a mutation route
            doesn't declare, naming every unknown param (sorted).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    # get_flat_dependant includes query params declared by sub-dependencies,
    # which route.dependant.query_params alone would miss (falsely 400ing).
    allowed = {
        param.alias or param.name
        for param in get_flat_dependant(request.scope["route"].dependant).query_params
    }
    unknown = sorted(set(request.query_params.keys()) - allowed)
    if unknown:
        raise UnknownQueryParamsError(unknown)
