from typing import Literal

from pydantic import BaseModel, Field


class Reference(BaseModel):
    """Reference from a score to content in the scored transcript.

    References are stored as a list of dicts under a score's
    `metadata["scanner_references"]` key. Inspect View identifies scanner
    scores by the presence of that key and renders cites in the score's
    explanation (e.g. `[M22]`) as links to the referenced content.
    """

    type: Literal["message", "event"]
    """Reference type."""

    cite: str | None = Field(default=None)
    """Cite text used when the entity was referenced (optional).

    For example, a model may have pointed to a message using something like [M22], which is the cite.
    """

    id: str
    """Reference id (message or event id)"""
