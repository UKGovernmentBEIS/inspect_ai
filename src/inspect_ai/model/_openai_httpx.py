"""The httpx flavor matching the installed openai SDK.

openai < 3 is built on ``httpx``; openai >= 3 is built on ``httpx2`` (a
separate package installed only alongside openai 3). Objects handed to the
SDK (Response/Request/Timeout) must be built with the same flavor the SDK
was built against — the wrong flavor either fails mypy or, worse, is
silently misinterpreted at runtime (e.g. a legacy ``httpx.Timeout`` passed
to an ``httpx2`` client is treated as a scalar). Use ``openai_httpx`` for
any such object instead of importing ``httpx`` directly.

The runtime import is keyed on the installed openai version — not on
whether ``httpx2`` is importable, since an environment can have httpx2
installed alongside openai 2.x (e.g. leftovers from a package downgrade)
and the SDK's version is the only signal that matters.

The static type is keyed on the installed openai's *own* httpx import
(``openai._base_client.httpx2``), which exists exactly when the SDK types
against httpx2: mypy checks shim uses strictly against ``httpx2`` in
openai 3.x environments and falls back to ``Any`` in openai 2.x ones
(where ``httpx2`` types wouldn't exist to check against anyway).
"""

from typing import TYPE_CHECKING

import openai

if TYPE_CHECKING:
    from openai import _base_client as _openai_base_client

    openai_httpx = _openai_base_client.httpx2  # type: ignore[attr-defined]
elif int(openai.__version__.partition(".")[0]) >= 3:
    import httpx2 as openai_httpx
else:
    import httpx as openai_httpx

__all__ = ["openai_httpx"]
