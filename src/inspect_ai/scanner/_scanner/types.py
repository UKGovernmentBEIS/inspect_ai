"""Type definitions for scanner and loader modules."""

from typing import Sequence, TypeVar, Union

from inspect_ai.log._transcript import Event
from inspect_ai.model._chat_message import ChatMessage

from .._transcript.types import Transcript

# Define the union of all valid scanner/loader input types
# This constrains scanners and loaders to only accept/yield these types
# Using Sequence instead of list for covariance and broader compatibility
ScannerInput = Union[
    Transcript,
    ChatMessage,
    Sequence[ChatMessage],
    Event,
    Sequence[Event],
]

# Additional TypeVars for specific overloads (maintaining existing behavior)
# These are used in the overload signatures for type narrowing
TMessage = TypeVar("TMessage", ChatMessage, list[ChatMessage])
TEvent = TypeVar("TEvent", Event, list[Event])
