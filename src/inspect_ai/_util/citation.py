from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, Discriminator, Field, JsonValue


class CitationBase(BaseModel):
    """Base class for citations."""

    cited_text: str | tuple[int, int] | None = Field(
        default=None,
        # without helping the schema generator, this will turn into [unknown, unknown] in TypeScript
        json_schema_extra={
            "anyOf": [
                {"type": "string"},
                {
                    "type": "array",
                    "items": [{"type": "integer"}, {"type": "integer"}],
                    "additionalItems": False,
                    "minItems": 2,
                    "maxItems": 2,
                },
                {"type": "null"},
            ]
        },
    )
    """
    The cited text

    This can be the text itself or a start/end range of the text content within
    the container that is the cited text.
    """

    title: str | None = None
    """Title of the cited resource."""

    internal: dict[str, JsonValue] | None = Field(default=None)
    """Model provider specific payload - typically used to aid transformation back to model types."""


class GenericCitation(CitationBase):
    """A generic citation."""

    type: Literal["generic"] = Field(default="generic")
    """Type."""


class DocumentCitation(CitationBase):
    """A citation that refers to a document."""

    type: Literal["document"] = Field(default="document")
    """Type."""


class DocumentPageCitation(CitationBase):
    """A citation that refers to a page range in a document."""

    type: Literal["document_page"] = Field(default="document_page")
    """Type."""
    page_range: tuple[int, int] | None = Field(default=None)
    """Page range in the document that this citation refers to."""


class DocumentCharCitation(CitationBase):
    """A citation that refers to a character range in a document."""

    type: Literal["document_char"] = Field(default="document_char")
    """Type."""
    char_range: tuple[int, int] | None = Field(default=None)
    """Character range in the document that this citation refers to."""


class DocumentBlockCitation(CitationBase):
    """
    A citation that refers to a block range in a document.

    A block is a model defined subset of a document
    """

    type: Literal["document_block"] = Field(default="document_block")
    """Type."""
    block_range: tuple[int, int] | None = Field(default=None)


class UrlCitation(CitationBase):
    """A citation that refers to a URL."""

    type: Literal["url"] = Field(default="url")
    """Type."""
    url: str
    """URL of the cited resource."""


Citation: TypeAlias = Annotated[
    Union[
        GenericCitation,
        DocumentCharCitation,
        DocumentPageCitation,
        DocumentBlockCitation,
        DocumentCitation,
        UrlCitation,
    ],
    Discriminator("type"),
]
"""A citation sent to or received from a model."""
