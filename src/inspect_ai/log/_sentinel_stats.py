from typing import Literal

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


class SentinelHumanReviewCounts(BaseModel):
    """Questions a sentinel's `human()` asked a person, and how they ended.

    Only reviews a sentinel's `human()` asked for. Approvals by `inspect_ai.approval` approvers and reviews by `inspect_ai.review` reviewers are not counted here.

    Experimental: not yet a stable API; may change without notice.
    """

    total: int = Field(default=0)
    """Questions asked."""

    answered: int = Field(default=0)
    """Questions answered."""

    timed_out: int = Field(default=0)
    """Questions that timed out unanswered."""

    cancelled: int = Field(default=0)
    """Questions cancelled before an answer took effect."""


class SentinelRemoteStats(BaseModel):
    """What only a remote sentinel's stats have: how Inspect reached it, and the model calls Inspect sent through it.

    Experimental: not yet a stable API; may change without notice.
    """

    proxy_url: str
    """The address of the model's proxy, through which Inspect reached the remote sentinel, without any credentials it held."""

    version: int
    """The version of the remote sentinel's endpoint for evals that Inspect spoke."""

    release: Literal["whole", "early"] | str
    """How the remote sentinel passes on a streamed reply."""

    model_calls: int = Field(default=0)
    """Model calls Inspect sent through the remote sentinel, one per `x-irid`, so a generate Inspect retried is several."""

    unrecorded_calls: int = Field(default=0)
    """Model calls the remote sentinel kept no record of (it answered `unknown` or `dropped`)."""

    results_withheld: bool | None = Field(default=None)
    """Whether the remote sentinel withheld its results from the eval; `None` where it didn't say."""


class SentinelStats(BaseModel):
    """What a sentinel did over a sample, filled the same way whether it ran inside Inspect or outside the eval.

    Experimental: not yet a stable API; may change without notice.
    """

    steps: dict[SentinelStage, SentinelStepCounts] | None = Field(default=None)
    """Steps at each stage; `None` where the counts are unavailable (see `complete`)."""

    actions: dict[SentinelAction, int] | None = Field(default=None)
    """Decisions taken, by action."""

    human_reviews: SentinelHumanReviewCounts | None = Field(default=None)
    """Questions the sentinel's `human()` asked a person, and how they ended.

    Only reviews a sentinel's `human()` asked for. Approvals by `inspect_ai.approval` approvers and reviews by `inspect_ai.review` reviewers are not counted here.
    """

    complete: bool = Field(default=True)
    """Whether the counts cover the whole sample."""

    incomplete_reason: str | None = Field(default=None)
    """Why the counts don't cover the whole sample, where they don't."""

    remote: SentinelRemoteStats | None = Field(default=None)
    """How Inspect reached the sentinel, where it ran outside the eval; `None` inside Inspect."""


class SentinelEvalStats(BaseModel):
    """A sentinel's stats added up over an eval's samples whose stats are complete: only the fields that add up.

    Experimental: not yet a stable API; may change without notice.
    """

    steps: dict[SentinelStage, SentinelStepCounts] | None = Field(default=None)
    """Steps at each stage, over the samples counted."""

    actions: dict[SentinelAction, int] | None = Field(default=None)
    """Decisions taken, by action, over the samples counted."""

    human_reviews: SentinelHumanReviewCounts | None = Field(default=None)
    """Questions the sentinel's `human()` asked a person, over the samples counted."""

    model_calls: int = Field(default=0)
    """Model calls Inspect sent through the sentinel where it ran outside the eval, over the samples counted."""

    unrecorded_calls: int = Field(default=0)
    """Model calls a remote sentinel kept no record of, over the samples counted."""

    samples: int = Field(default=0)
    """Samples whose stats were added up."""

    incomplete_samples: int = Field(default=0)
    """Samples left out because their stats were incomplete."""
