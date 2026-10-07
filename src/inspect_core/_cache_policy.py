from typing import Optional

from pydantic import BaseModel, Field


def _parse_expiry(period: str) -> int:
    """Returns the number of seconds in the period where period is a string of the format "12h" or "1W" etc."""
    factor = period[-1]
    match factor:
        case "s":
            return int(period[:-1])
        case "m":
            return int(period[:-1]) * 60
        case "h":
            return int(period[:-1]) * 60 * 60
        case "D":
            return int(period[:-1]) * 60 * 60 * 24
        case "W":
            return int(period[:-1]) * 60 * 60 * 24 * 7
        case "M":
            return int(period[:-1]) * 60 * 60 * 24 * 30
        case "Y":
            return int(period[:-1]) * 60 * 60 * 24 * 365
        case _:
            raise ValueError(f"Invalid expiry: {period}")


class CachePolicy(BaseModel):
    """Caching options for model generation."""

    expiry: str | None = Field(default="1W")
    """The expiry time for cache entries (Default "1W").
    This is a string of the format "12h" for 12 hours or "1W" for a week,
    etc. This is how long we will keep the cache entry, if we access it
    after this point we'll clear it. Setting to `None` will cache
    indefinitely."""

    per_epoch: bool = Field(default=True)
    """Default True. By default we cache responses separately
    for different epochs. The general use case is that if there are
    multiple epochs, we should cache each response separately because
    scorers will aggregate across epochs. However, sometimes a response
    can be cached regardless of epoch if the call being made isn't under
    test as part of the evaluation. If False, this option allows you to
    bypass that and cache independently of the epoch."""

    scopes: dict[str, str] = Field(default_factory=dict)
    """A dictionary of additional metadata that should
    be included in the cache key. This allows for more fine-grained
    control over the cache key generation."""

    @staticmethod
    def from_string(expiry: str) -> Optional["CachePolicy"]:
        try:
            _parse_expiry(expiry)  # confirm this is a legit expiry
            return CachePolicy(expiry=expiry)
        except ValueError:
            return None
