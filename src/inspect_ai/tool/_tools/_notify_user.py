from inspect_ai.util._notify import active_apprise, notify

from .._tool import Tool, tool


@tool
def notify_user() -> Tool:
    """Send the user an out-of-band status notification."""

    async def execute(title: str, message: str) -> str:
        """Send a notification to the user (fire-and-forget; no reply expected).

        The notification is delivered via whichever channels the operator
        configured for this eval (Slack, desktop, SMS, etc.). Use this to
        surface progress, blocking conditions, or status updates that the
        operator should see without having to watch the eval in real time.

        ## When to use
        - Long-running step reached a meaningful milestone or has stalled
        - You hit a condition the operator should know about but you don't
          need an answer (use `ask_user` if you do)
        - Wrapping up: notify the operator the eval is done / awaiting review

        ## When NOT to use
        - Routine progress that's already obvious from the transcript
        - Per-step pings — operators get noise fatigue; batch into milestones
        - You need an answer back — use `ask_user` instead

        ## Title vs. message
        The title is the headline the operator sees in the notification
        preview (lock screen / banner / Slack subject), so make it triageable
        on its own. The message is the longer body for context.

        Args:
          title: Short subject / headline (the operator sees this first).
          message: The notification body.

        Returns:
          A short status string describing whether the notification was sent.
          When no notification channels are configured for the eval, returns
          a hint that the operator will not see this out-of-band — if it
          matters, include it in your response text too.
        """
        if active_apprise() is None:
            return (
                "No notification channels are configured for this eval, so "
                "the message was not delivered out-of-band. If you need the "
                "operator to see this, include it in your response text."
            )
        await notify(message, title=title)
        return "Notification sent."

    return execute
