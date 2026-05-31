"""Tests for the `notify_user` model-callable tool."""

from unittest.mock import MagicMock

from inspect_ai.tool import notify_user
from inspect_ai.util._notify import apprise_scope


async def test_notify_user_with_no_apprise_returns_hint() -> None:
    """Without notification channels, the tool returns a fallback hint."""
    with apprise_scope(None):
        tool = notify_user()
        result = await tool(title="Status", message="Halfway through")

    assert isinstance(result, str)
    assert "not delivered" in result.lower() or "no notification" in result.lower()


async def test_notify_user_dispatches_when_apprise_active() -> None:
    """The tool delivers via notify() and confirms in its return value."""
    fake = MagicMock()
    fake.notify = MagicMock(return_value=True)

    with apprise_scope(fake):
        tool = notify_user()
        result = await tool(title="Status update", message="Step 3 of 5 done")

    assert result == "Notification sent."
    fake.notify.assert_called_once()
    kwargs = fake.notify.call_args.kwargs
    assert kwargs.get("body") == "Step 3 of 5 done"
    assert kwargs.get("title") == "Status update"
