from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, RootModel


class BaseParams(BaseModel):
    command: Literal["view", "create", "str_replace", "insert", "undo_edit"]
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


class EditorParams(RootModel):
    root: Annotated[
        ViewParams | CreateParams | StrReplaceParams | InsertParams | UndoEditParams,
        Discriminator("command"),
    ]


class EditorResult(BaseModel):
    status: int
    stdout: str
    stderr: str


# Custom editing tool for viewing, creating and editing files
# * State is persistent across command calls and discussions with the user
# * If `path` is a file, `view` displays the result of applying `cat -n`. If `path` is a directory, `view` lists non-hidden files and directories up to 2 levels deep
# * The `create` command cannot be used if the specified `path` already exists as a file
# * If a `command` generates a long output, it will be truncated and marked with `<response clipped>`
# * The `undo_edit` command will revert the last edit made to the file at `path`

# Notes for using the `str_replace` command:
# * The `old_str` parameter should match EXACTLY one or more consecutive lines from the original file. Be mindful of whitespaces!
# * If the `old_str` parameter is not unique in the file, the replacement will not be performed. Make sure to include enough context in `old_str` to make it unique
# * The `new_str` parameter should contain the edited lines that should replace the `old_str`
# * The `new_str` parameter should contain the edited lines that should replace the `old_str`
