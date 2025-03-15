from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, RootModel


class BaseParams(BaseModel):
    path: str


class ViewParams(BaseParams):
    command: Literal["view"] = "view"
    view_range: list[int] | None = None


class CreateParams(BaseParams):
    command: Literal["create"] = "create"
    file_text: str


class StrReplaceParams(BaseParams):
    command: Literal["str_replace"] = "str_replace"
    old_str: str
    new_str: str | None = None


class InsertParams(BaseParams):
    command: Literal["insert"] = "insert"
    insert_line: int
    new_str: str


class UndoEditParams(BaseParams):
    command: Literal["undo_edit"] = "undo_edit"


class TextEditorParams(RootModel):
    root: Annotated[
        ViewParams | CreateParams | StrReplaceParams | InsertParams | UndoEditParams,
        Discriminator("command"),
    ]


TextEditorResult = str
