from __future__ import annotations

from pydantic import BaseModel, field_validator


class Variant(BaseModel, frozen=True):
    prompt: str
    # See ChallengeInfo.files.
    files: dict[str, str] = {}
    # Arbitrary metadata to associate with the variant.
    metadata: dict = {}


class ChallengeInfo(BaseModel, frozen=True):
    """
    Represents the contents of a challenge.yaml file.

    This class is immutable.
    """

    name: str
    flag: str
    # The key is the destination file path.
    # The value is the source file path or inline content.
    files: dict[str, str] = {}
    variants: dict[str, Variant]
    # Arbitrary metadata to associate with the challenge.
    metadata: dict = {}

    @field_validator("variants")
    @classmethod
    def validate(cls, variants):
        if len(variants) < 1:
            raise ValueError("At least one variant is required.")
        return variants
