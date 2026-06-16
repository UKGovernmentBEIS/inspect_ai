import pytest

from inspect_ai.util import current_checkpointer
from inspect_ai.util._checkpoint.checkpointer_noop import _NoopCheckpointer


def test_current_checkpointer_none_outside_sample() -> None:
    # No active sample → no session to return.
    assert current_checkpointer() is None


async def test_noop_current_tracks_entry() -> None:
    noop = _NoopCheckpointer()
    # Not entered yet.
    assert noop.current() is None
    async with noop as cp:
        assert cp is noop
        assert noop.current() is noop
    # Reset on exit, symmetric with the real setup (whose current() goes
    # None once the session is torn down).
    assert noop.current() is None


async def test_current_checkpointer_returns_entered_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    noop = _NoopCheckpointer()

    class _FakeActiveSample:
        checkpointer = noop

    monkeypatch.setattr(
        "inspect_ai.log._samples.sample_active",
        lambda: _FakeActiveSample(),
    )

    # Active sample exists but the agent hasn't opened the session yet.
    assert current_checkpointer() is None

    # Once entered, the accessor returns the live session.
    async with noop:
        assert current_checkpointer() is noop
