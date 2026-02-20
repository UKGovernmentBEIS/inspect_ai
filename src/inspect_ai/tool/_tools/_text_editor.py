import inspect
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, RootModel

from inspect_ai._util._json_rpc import exec_scalar_request
from inspect_ai.tool import ToolResult
from inspect_ai.tool._sandbox_tools_utils._error_mapper import (
    SandboxToolsErrorMapper,
)
from inspect_ai.tool._sandbox_tools_utils.sandbox import sandbox_with_injected_tools
from inspect_ai.util._sandbox._cli import SANDBOX_CLI
from inspect_ai.util._sandbox._json_rpc_transport import SandboxJSONRPCTransport

from .._tool import Tool, tool

# These models are cloned from the container code. If/when we decide to create
# a package that is shared between the inspect and tool-container codebases, we'll
# just have to live with it.


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


class TextEditorParams(
    RootModel[
        ViewParams | CreateParams | StrReplaceParams | InsertParams | UndoEditParams
    ]
):
    root: Annotated[
        ViewParams | CreateParams | StrReplaceParams | InsertParams | UndoEditParams,
        Discriminator("command"),
    ]


TextEditorResult = str


@tool()
def text_editor(timeout: int | None = None, user: str | None = None) -> Tool:
    """Custom editing tool for viewing, creating and editing files.

    Perform text editor operations using a sandbox environment (e.g. "docker").

    IMPORTANT: This tool does not currently support Subtask isolation. This means
    that a change made to a file by on Subtask will be visible to another Subtask.

    Args:
      timeout: Timeout (in seconds) for command. Defaults to 180 if not provided.
      user: User to execute commands as.

    Returns:
      String with command output (stdout) or command error (stderr).
    """
    timeout = timeout or 180

    async def execute(
        command: Literal["view", "create", "str_replace", "insert", "undo_edit"],
        path: str,
        file_text: str | None = None,
        insert_line: int | None = None,
        new_str: str | None = None,
        old_str: str | None = None,
        view_range: list[int] | None = None,
    ) -> ToolResult:
        """
        Use this function to execute text editing commands.

        Args:
          command: The command to execute.
          path: Path to file or directory, e.g. `/repo/file.py` or `../repo`.
          file_text: Required parameter of `create` command, with the content of the file to be created.
          insert_line: Required parameter of `insert` command. The `new_str` will be inserted AFTER the line `insert_line` of `path`.
          new_str: Optional parameter of `str_replace` command containing the new string (if not given, no string will be added). Required parameter of `insert` command containing the string to insert.
          old_str: Required parameter of `str_replace` command containing the string in `path` to replace.
          view_range: Optional parameter of `view` command when `path` points to a file. If none is given, the full file is shown. If provided, the file will be shown in the indicated line number range, e.g. [11, 12] will show lines 11 and 12. Indexing at 1 to start. Setting `[start_line, -1]` shows all lines from `start_line` to the end of the file.

        Returns:
          The output of the command.
        """
        sandbox = await sandbox_with_injected_tools()

        # Create a dictionary of the parameters
        params = {
            k: v
            for k, v in locals().items()
            if k in inspect.signature(execute).parameters
        }

        return await exec_scalar_request(
            method="text_editor",
            params=params,
            result_type=TextEditorResult,
            transport=SandboxJSONRPCTransport(sandbox, SANDBOX_CLI),
            error_mapper=SandboxToolsErrorMapper,
            timeout=timeout,
            user=user,
        )

    return execute
