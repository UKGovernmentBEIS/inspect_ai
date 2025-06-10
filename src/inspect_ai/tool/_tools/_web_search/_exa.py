from typing import Any, Literal

from pydantic import BaseModel

from inspect_ai._util.citation import UrlCitation
from inspect_ai._util.content import ContentText

from ._base_http_provider import BaseHttpProvider
from ._web_search_provider import SearchProvider


class ExaOptions(BaseModel):
    # See https://docs.exa.ai/reference/answer
    text: bool | None = None
    """Whether to include text content in citations"""
    model: Literal["exa", "exa-pro"] | None = None
    """LLM model to use for generating the answer"""
    max_connections: int | None = None
    """max_connections is not an Exa API option, but an inspect option"""


class ExaCitation(BaseModel):
    id: str
    url: str
    title: str
    author: str | None = None
    publishedDate: str | None = None
    text: str


class ExaSearchResponse(BaseModel):
    answer: str
    citations: list[ExaCitation]


class ExaSearchProvider(BaseHttpProvider):
    def __init__(self, options: dict[str, Any] | None = None):
        super().__init__(
            env_key_name="EXA_API_KEY",
            api_endpoint="https://api.exa.ai/answer",
            provider_name="Exa",
            concurrency_key="exa_web_search",
            options=options,
        )

    def prepare_headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

    def set_default_options(self, options: dict[str, Any]) -> dict[str, Any]:
        return options

    def parse_response(self, response_data: dict[str, Any]) -> ContentText | None:
        exa_search_response = ExaSearchResponse.model_validate(response_data)

        if not exa_search_response.answer and not exa_search_response.citations:
            return None

        return ContentText(
            text=exa_search_response.answer,
            citations=[
                UrlCitation(
                    cited_text=citation.text, title=citation.title, url=citation.url
                )
                for citation in exa_search_response.citations
            ],
        )


def exa_search_provider(
    in_options: dict[str, object] | None = None,
) -> SearchProvider:
    options = ExaOptions.model_validate(in_options) if in_options else None
    return ExaSearchProvider(
        options.model_dump(exclude_none=True) if options else None
    ).search
