"""The httpx flavor matching the installed openai SDK.

openai < 3 is built on ``httpx``; openai >= 3 is built on ``httpx2`` (a
separate package installed only alongside openai 3). Objects handed to the
SDK (Response/Request/Timeout) must be built with the same flavor the SDK
was built against — the wrong flavor either fails mypy or, worse, is
silently misinterpreted at runtime (e.g. a legacy ``httpx.Timeout`` passed
to an ``httpx2`` client is treated as a scalar). Use ``openai_httpx`` for
any such object instead of importing ``httpx`` directly.

mypy note: when openai 2.x is installed, ``httpx2`` doesn't exist, so a
pyproject override resolves it as ``Any`` there (making the ignore below
unused — harmless, as unused-ignore is disabled for inspect_ai modules).
"""

try:
    import httpx2 as openai_httpx
except ModuleNotFoundError:
    import httpx as openai_httpx  # type: ignore[no-redef]

__all__ = ["openai_httpx"]
