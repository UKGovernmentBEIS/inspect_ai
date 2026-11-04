from typing import Literal

from pydantic import Field, JsonValue

from inspect_ai.event._base import BaseEvent


class SwarmEvent(BaseEvent):
    """Evidence from an agent swarm (inspect_swarm) other than communication: a member's result, the final answer's selection, the swarm's ledger or its metrics.

    The swarm defines `kind` and the format of `data`. Experimental: not yet a stable API.
    """

    event: Literal["swarm"] = Field(default="swarm")
    """Event type."""

    kind: str
    """What the event records (`"member_result"`, `"final"`, `"ledger"`, `"metrics"`)."""

    member: str | None = Field(default=None)
    """The member the event concerns, if any."""

    data: dict[str, JsonValue]
    """The evidence, in the format the swarm defines for `kind`, with that format's version in `data["version"]`."""
