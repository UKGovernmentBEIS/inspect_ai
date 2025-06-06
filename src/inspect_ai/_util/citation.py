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


class ContentCitation(CitationBase):
    """A generic content citation."""

    type: Literal["content"] = Field(default="content")
    """Type."""


class DocumentRange(BaseModel):
    """A range specifying a section of a document."""

    type: Literal["block", "page", "char"]
    """The type of the document section specified by the range."""

    start_index: int
    """0 based index of the start of the range."""

    end_index: int
    """0 based index of the end of the range."""


class DocumentCitation(CitationBase):
    """A citation that refers to a page range in a document."""

    type: Literal["document"] = Field(default="document")
    """Type."""

    range: DocumentRange | None = Field(default=None)
    """Range of the document that is cited."""


class UrlCitation(CitationBase):
    """A citation that refers to a URL."""

    type: Literal["url"] = Field(default="url")
    """Type."""

    url: str
    """URL of the cited resource."""


Citation: TypeAlias = Annotated[
    Union[
        ContentCitation,
        DocumentCitation,
        UrlCitation,
    ],
    Discriminator("type"),
]
"""A citation sent to or received from a model."""
