import asyncio


class TimeoutEvent:
    """
    An event that can be manually set or triggered by a timeout.

    This class combines the functionality of asyncio.Event with a timeout mechanism.
    It allows waiting for an event that can be triggered either manually (using set())
    or automatically after a specified timeout period.

    Key features:
    - Start/restart a timeout timer
    - Manually trigger the event
    - Wait for the event to be triggered
    - Cancel ongoing timers
    """

    def __init__(self) -> None:
        """
        Initialize a TimeoutEvent.

        The event is initially not set and no timer is active.
        """
        self._ready_event = asyncio.Event()
        self._idle_task: asyncio.Task[None] | None = None

    def is_set(self) -> bool:
        return self._ready_event.is_set()

    def clear(self) -> None:
        """Clear the event and cancel the timer."""
        self._cancel_timer()
        self._ready_event.clear()

    def start_timer(self, timeout: float) -> None:
        """Start or restart the countdown timer."""
        self.clear()

        async def _timeout_handler():
            try:
                await asyncio.sleep(timeout)
                self.set()
            except asyncio.CancelledError:
                pass

        self._idle_task = asyncio.create_task(_timeout_handler())

    def set(self) -> None:
        """
        Set the event, causing all waiters to be awakened.

        This also cancels any running timer as the event is now set.
        """
        self._cancel_timer()
        self._ready_event.set()

    async def wait(self) -> None:
        """
        Wait until the event is set.

        The event can be set either by an explicit call to set() or when the timer
        expires.

        Returns:
            None: Always returns None when the event is set.
        """
        await self._ready_event.wait()

    def cancel(self) -> None:
        """
        Cancel the timer without setting the event.

        This is typically used for cleanup when the TimeoutEvent is no longer needed.
        """
        self._cancel_timer()

    def _cancel_timer(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None
