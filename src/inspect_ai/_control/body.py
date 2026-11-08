"""Raw request body dependency for control-server routes that take a body.

Lives in its own module for the same reason as ``disconnect.py``: a
``Request``-annotated parameter needs ``fastapi`` imported at module scope,
which ``server.py`` avoids (it imports FastAPI lazily and uses
``from __future__ import annotations``). Imported lazily from ``_build_app``.
"""

from fastapi import Request


async def request_body(request: Request) -> bytes:
    """The request's raw body (empty when it has none)."""
    return await request.body()
