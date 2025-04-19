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
        self._idle_timeout: int | None = None

    def clear(self, idle_timeout: int) -> None:
        """
        Clear the event and configure the timeout for future timer starts.

        This method does not start the timer - call start_timer() to begin the countdown.

        Args:
            idle_timeout: The timeout period in seconds to use for future timer starts
        """
        self._idle_timeout = idle_timeout
        self._ready_event.clear()

    def start_timer(self) -> None:
        """
        Start or restart the countdown timer.

        When the timer expires, the event will be automatically set.
        If a timer is already running, it will be cancelled and replaced with a new one.
        """
        self._cancel_timer()

        async def _timeout_handler():
            try:
                await asyncio.sleep(self._idle_timeout)
                self.set()
            except asyncio.CancelledError:
                # Task was cancelled, don't set the event
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
