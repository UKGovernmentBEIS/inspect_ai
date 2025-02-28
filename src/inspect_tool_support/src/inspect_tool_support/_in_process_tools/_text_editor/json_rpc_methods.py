from jsonrpcserver import method

from inspect_tool_support._in_process_tools._text_editor.text_editor import (
    create,
    insert,
    str_replace,
    undo_edit,
    view,
)
from inspect_tool_support._in_process_tools._text_editor.tool_types import (
    CreateParams,
    InsertParams,
    StrReplaceParams,
    TextEditorParams,
    UndoEditParams,
    ViewParams,
)
from inspect_tool_support._util._json_rpc_helpers import (
    with_validated_rpc_method_params,
)


@method
async def text_editor(**params: object) -> object:
    return await with_validated_rpc_method_params(
        TextEditorParams, _text_editor, **params
    )


async def _text_editor(params: TextEditorParams) -> str:
    match params.root:
        case ViewParams(path=path, view_range=view_range):
            return await view(path, view_range)
        case CreateParams(path=path, file_text=file_text):
            return await create(path, file_text)
        case StrReplaceParams(path=path, old_str=old_str, new_str=new_str):
            return await str_replace(path, old_str, new_str)
        case InsertParams(path=path, insert_line=insert_line, new_str=new_str):
            return await insert(path, insert_line, new_str)
        case UndoEditParams(path=path):
            return await undo_edit(path)
