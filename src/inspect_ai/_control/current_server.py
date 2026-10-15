"""Route dependency resolving the :class:`ControlServer` behind the app.

The FastAPI app is built once per process and shared by every
``ControlServer`` (see ``ControlServer._build_app``), so routes can't
close over the server instance; the live one rides ``app.state.server``
and routes that need it (``GET /tasks`` for the run's ``started_at``,
``POST /release`` for the park condition) take it via this dependency.

Lives in its own module for the same reason as ``disconnect.py`` and
``strict.py``: a ``Request``-annotated parameter needs ``fastapi`` imported
at module scope to resolve, and ``server.py`` imports FastAPI lazily under
``from __future__ import annotations``. Imported lazily from
``_create_app``, preserving the no-FastAPI-cost-at-import property.
"""

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from inspect_ai._control.server import ControlServer


def current_control_server(request: Request) -> "ControlServer":
    """The ``ControlServer`` currently bound to the shared app."""
    server: ControlServer = request.app.state.server
    return server
