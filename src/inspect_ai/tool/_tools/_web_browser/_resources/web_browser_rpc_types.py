from typing import Literal, TypedDict

from pydantic import BaseModel


class NewSessionArgs(TypedDict):
    headful: bool


class CrawlerBaseArgs(TypedDict):
    session_name: str


class GoArgs(CrawlerBaseArgs):
    url: str


class ClickArgs(CrawlerBaseArgs):
    element_id: str


class ScrollArgs(CrawlerBaseArgs):
    direction: Literal["up", "down"]


class TypeOrSubmitArgs(CrawlerBaseArgs):
    element_id: str
    text: str


class NewSessionResponse(BaseModel):
    session_name: str


class CrawlerResponse(BaseModel):
    web_url: str
    main_content: str | None = None
    web_at: str
    error: str | None = None
