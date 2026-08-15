"""Concrete trigger for :class:`TokenInterval` specs."""

from __future__ import annotations

from .types import TriggerFire


class _TokenIntervalTrigger:
    """Fire when sample tokens used since the last fire ≥ ``every``.

    The reference count is set on the first ``tick()`` (not at
    construction), so the first fire is at least ``every`` tokens
    after the session's first turn rather than after construction.
    """

    def __init__(self, every: int) -> None:
        self._every = every
        self._reference: int | None = None

    def tick(self) -> TriggerFire | None:
        # Imported inside tick() to avoid a circular import: this
        # module is loaded during `inspect_ai.util._checkpoint`
        # package init, before `inspect_ai.model` finishes its own
        # init.
        from inspect_ai.model._model import sample_total_tokens

        current = sample_total_tokens()
        if self._reference is None:
            self._reference = current
            return None
        since_last_fire = current - self._reference
        if since_last_fire >= self._every:
            self._reference = current
            return TriggerFire(
                "token",
                {
                    "every": self._every,
                    "tokens_since_last_fire": since_last_fire,
                    "sample_total_tokens": current,
                },
            )
        return None
