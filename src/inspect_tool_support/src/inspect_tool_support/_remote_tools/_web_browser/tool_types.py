from typing import Literal

from pydantic import BaseModel


class NewSessionParams(BaseModel):
    headful: bool


class CrawlerBaseParams(BaseModel):
    session_name: str


class GoParams(CrawlerBaseParams):
    url: str


class ClickParams(CrawlerBaseParams):
    element_id: int


class ScrollParams(CrawlerBaseParams):
    direction: Literal["up", "down"]


class TypeOrSubmitParams(CrawlerBaseParams):
    element_id: int
    text: str


class NewSessionResult(BaseModel):
    session_name: str


class CrawlerResult(BaseModel):
    web_url: str
    main_content: str | None = None
    web_at: str
    error: str | None = None
