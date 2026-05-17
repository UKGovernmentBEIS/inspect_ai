"""Shared fixtures for the Phase 1 TUI tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from inspect_ai.agent._acp.discovery import TargetAddress
from inspect_ai.agent._acp.tui.client import SessionRow


@pytest.fixture
def sample_rows() -> list[SessionRow]:
    """Three rows across two evals — exercises eval-id filtering."""
    target_a = TargetAddress(socket_path=Path("/tmp/acp_eval_a.sock"))
    target_b = TargetAddress(host="127.0.0.1", port=43210)
    return [
        SessionRow(
            eval_id="eval-aaa",
            session_id="sess-1",
            task="my_task",
            sample_id="0",
            epoch=1,
            agent_name="react",
            # Fixed offsets from the snapshot time below give
            # deterministic "running" column values.
            started_at=1_700_000_000.0,
            target=target_a,
        ),
        SessionRow(
            eval_id="eval-aaa",
            session_id="sess-2",
            task="my_task",
            sample_id="1",
            epoch=1,
            agent_name="react",
            started_at=1_700_000_000.0 - 65,
            target=target_a,
        ),
        SessionRow(
            eval_id="eval-bbb",
            session_id="sess-3",
            task="other_task",
            sample_id="0",
            epoch=1,
            agent_name="deepagent",
            started_at=1_700_000_000.0 - 3700,
            target=target_b,
        ),
    ]


def make_fake_client(
    rows: list[SessionRow],
    *,
    enumerate_raises: Exception | None = None,
    attach_raises: Exception | None = None,
) -> SimpleNamespace:
    """Build a stub object satisfying the TUI's client surface.

    Returned namespace exposes ``enumerate_sessions`` (returns the
    supplied rows, honoring ``eval_id_filter``) and ``attach_session``
    (returns a minimal stand-in with a never-set ``disconnected``
    event). Tests can inject failures via the raises kwargs.
    """

    async def _enumerate(
        addresses: list[tuple[str, TargetAddress]],
        *,
        eval_id_filter: str | None = None,
    ) -> list[SessionRow]:
        if enumerate_raises is not None:
            raise enumerate_raises
        if eval_id_filter is not None:
            return [r for r in rows if r.eval_id == eval_id_filter]
        return list(rows)

    async def _attach(row: SessionRow, **kwargs: object) -> "object":
        # Accept (and ignore) keyword args like ``on_session_update`` so
        # tests exercise the same call signature production uses; if the
        # fake silently dropped the kwarg, app-level tests would mount a
        # screen that never sees notifications and false-positive.
        if attach_raises is not None:
            raise attach_raises
        import asyncio

        # Minimal stand-in: just enough surface for SessionScreen to
        # render and tear down cleanly without an actual socket.
        evt = asyncio.Event()

        class _FakeWriter:
            def is_closing(self) -> bool:
                return False

            def close(self) -> None:
                pass

            async def wait_closed(self) -> None:
                pass

        class _FakeConnection:
            """Records outbound JSON-RPC calls so tests can assert them.

            ``send_request`` returns ``None`` — production code only
            uses the response shape for picker-mode rebinds (handled
            elsewhere); the prompt path treats it as fire-and-forget
            once the request is acknowledged.
            """

            def __init__(self) -> None:
                self.requests: list[tuple[str, dict[str, object]]] = []
                self.notifications: list[tuple[str, dict[str, object]]] = []

            async def send_request(
                self, method: str, params: dict[str, object]
            ) -> None:
                self.requests.append((method, params))

            async def send_notification(
                self, method: str, params: dict[str, object]
            ) -> None:
                self.notifications.append((method, params))

        class _FakeSession:
            def __init__(self) -> None:
                self.connection = _FakeConnection()
                self.writer = _FakeWriter()
                self.session_id = row.session_id
                self.row = row
                self.disconnected = evt

            @property
            def is_connected(self) -> bool:
                return not self.disconnected.is_set()

            async def close(self) -> None:
                if self.disconnected.is_set():
                    return
                self.disconnected.set()

        return _FakeSession()

    return SimpleNamespace(
        enumerate_sessions=_enumerate,
        attach_session=_attach,
    )


@pytest.fixture
def fake_client_factory() -> Callable[..., SimpleNamespace]:
    """Returns the :func:`make_fake_client` builder for parametrized use."""
    return make_fake_client
