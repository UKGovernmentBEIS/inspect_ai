"""Compatibility shims for the agent-client-protocol SDK."""

from __future__ import annotations

from typing import Any

import acp.connection as _conn_mod

_PATCH_FLAG = "_acp_eager_task_init_patch_applied"


def _apply_eager_task_init_patch() -> None:
    """Patch ``acp.connection.Connection.__init__`` for eager-task safety.

    Makes Connection safe under ``asyncio.eager_task_factory`` (which
    Textual installs on its loop).

    Upstream bug (agent-client-protocol 0.10.0): ``__init__`` spawns the
    receive task before assigning ``self._receive_timeout``. With the
    eager task factory the receive coroutine runs synchronously up to
    its first ``await``, reading ``self._receive_timeout`` before it
    exists and raising ``AttributeError`` — connection torn down.

    See https://github.com/agentclientprotocol/python-sdk/issues/97.

    We pre-set ``_receive_timeout`` from the caller's kwargs, then
    delegate. The original ``__init__`` reassigns the same value at
    the end (harmless). On SDK versions without the attribute (0.9.0
    and earlier) the pre-set attribute is unused.

    Idempotency flag is namespaced to the upstream module so other
    consumers applying the same workaround can settle on the same key
    and avoid stacking redundant wrappers.
    """
    if getattr(_conn_mod.Connection, _PATCH_FLAG, False):
        return

    original_init = _conn_mod.Connection.__init__

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:  # noqa: N807
        self._receive_timeout = kwargs.get("receive_timeout")
        original_init(self, *args, **kwargs)

    _conn_mod.Connection.__init__ = __init__  # type: ignore[method-assign]
    setattr(_conn_mod.Connection, _PATCH_FLAG, True)


_apply_eager_task_init_patch()
