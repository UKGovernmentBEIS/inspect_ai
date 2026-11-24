from pydantic import BaseModel, Field

from inspect_ai.event._sentinel import SentinelAction, SentinelStage


class SentinelStepCounts(BaseModel):
    """Steps a sentinel saw at one stage, and whether each was judged.

    Experimental: not yet a stable API; may change without notice.
    """

    total: int = Field(default=0)
    """Steps that reached the sentinel."""

    judged: int = Field(default=0)
    """Steps the sentinel judged."""

    unjudged: dict[str, int] = Field(default_factory=dict)
    """Steps whose judging didn't finish, by reason."""


class SentinelReviewCounts(BaseModel):
    """Questions a sentinel asked a person, and how they ended.

    Experimental: not yet a stable API; may change without notice.
    """

    asked: int = Field(default=0)
    """Questions asked."""

    answered: int = Field(default=0)
    """Questions answered."""

    timed_out: int = Field(default=0)
    """Questions that timed out unanswered."""

    cancelled: int = Field(default=0)
    """Questions cancelled before an answer took effect."""


class SentinelSidecarStats(BaseModel):
    """What only a sentinel sidecar's stats have: the sidecar, and the model calls Inspect sent through it.

    Experimental: not yet a stable API; may change without notice.
    """

    proxy: str
    """The proxy's address, through which Inspect reached the sidecar."""

    model_calls: int = Field(default=0)
    """Model calls Inspect sent through the sidecar, one per `x-irid`, so a generate Inspect retried is several."""

    unknown_calls: int = Field(default=0)
    """Model calls the sidecar had no record of (it answered `unknown` or `dropped`)."""

    results_withheld: bool | None = Field(default=None)
    """Whether the sidecar withheld its results from the eval; `None` where it didn't say."""


class SentinelStats(BaseModel):
    """What a sentinel did over a sample, filled the same way whether it ran inside Inspect or in a sidecar.

    Experimental: not yet a stable API; may change without notice.
    """

    steps: dict[SentinelStage, SentinelStepCounts] | None = Field(default=None)
    """Steps at each stage; `None` where the counts are unavailable (see `complete`)."""

    actions: dict[SentinelAction, int] | None = Field(default=None)
    """Decisions taken, by action."""

    human_reviews: SentinelReviewCounts | None = Field(default=None)
    """Questions asked of a person, and how they ended."""

    complete: bool = Field(default=True)
    """Whether the counts cover the whole sample."""

    incomplete_reason: str | None = Field(default=None)
    """Why the counts don't cover the whole sample, where they don't."""

    sidecar: SentinelSidecarStats | None = Field(default=None)
    """Where the stats came from, for a sentinel in a sidecar; `None` inside Inspect."""


class SentinelEvalStats(SentinelStats):
    """A sentinel's stats added up over an eval's samples whose stats are complete.

    `complete` is false where any sample was left out.

    Experimental: not yet a stable API; may change without notice.
    """

    samples: int = Field(default=0)
    """Samples whose stats were added up."""

    incomplete_samples: int = Field(default=0)
    """Samples left out because their stats were incomplete."""
