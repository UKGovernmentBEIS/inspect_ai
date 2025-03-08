from jsonrpcserver import method

from inspect_tool_container._in_process_tools._editor.editor import (
    create,
    insert,
    str_replace,
    undo_edit,
    view,
)
from inspect_tool_container._in_process_tools._editor.tool_types import (
    CreateParams,
    EditorParams,
    InsertParams,
    StrReplaceParams,
    UndoEditParams,
    ViewParams,
)
from inspect_tool_container._util._json_rpc_helpers import (
    with_validated_rpc_method_params,
)


@method
async def editor(**params: object) -> object:
    return await with_validated_rpc_method_params(EditorParams, _editor, **params)


async def _editor(params: EditorParams) -> str:
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
