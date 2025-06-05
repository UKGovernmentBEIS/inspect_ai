from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, Discriminator, Field, JsonValue


class BaseCitation(BaseModel):
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
    """The cited text or the position of the cited text   within the current ContentText the citation refers to."""
    title: str | None = None
    internal: dict[str, JsonValue] | None = Field(default=None)
    """Model provider specific payload - typically used to aid transformation back to model types."""


class GenericCitation(BaseCitation):
    type: Literal["generic"] = Field(default="generic")


class DocumentCitation(BaseCitation):
    type: Literal["document"] = Field(default="document")


class DocumentPageCitation(BaseCitation):
    type: Literal["document_page"] = Field(default="document_page")
    page_range: tuple[int, int] | None = Field(default=None)


class DocumentCharCitation(BaseCitation):
    type: Literal["document_char"] = Field(default="document_char")
    char_range: tuple[int, int] | None = Field(default=None)


class DocumentBlockCitation(BaseCitation):
    type: Literal["document_block"] = Field(default="document_block")
    block_range: tuple[int, int] | None = Field(default=None)


class UrlCitation(BaseCitation):
    type: Literal["url"] = Field(default="url")
    url: str


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
