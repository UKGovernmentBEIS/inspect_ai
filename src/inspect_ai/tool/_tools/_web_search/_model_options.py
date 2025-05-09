from dataclasses import dataclass
from typing import (
    Literal,
    Optional,
    Required,
    TypedDict,
)


# TODO: OpenAI options are cloned from their API for now. I need to verify if we
# delay load those types are runtime or not.
class UserLocation(TypedDict, total=False):
    type: Required[Literal["approximate"]]
    """The type of location approximation. Always `approximate`."""

    city: Optional[str]
    """Free text input for the city of the user, e.g. `San Francisco`."""

    country: Optional[str]
    """
    The two-letter [ISO country code](https://en.wikipedia.org/wiki/ISO_3166-1) of
    the user, e.g. `US`.
    """

    region: Optional[str]
    """Free text input for the region of the user, e.g. `California`."""

    timezone: Optional[str]
    """
    The [IANA timezone](https://timeapi.io/documentation/iana-timezones) of the
    user, e.g. `America/Los_Angeles`.
    """


@dataclass
class OpenAIOptions:
    search_context_size: Literal["low", "medium", "high"]
    user_location: Optional[UserLocation]
    """The user's location."""
