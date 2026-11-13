import base64
import posixpath

from inspect_ai._util.content import ContentImage
from inspect_ai._util.images import _sniff_image_mime_type, as_data_uri
from inspect_ai.util import sandbox as sandbox_env
from inspect_ai.util._sandbox.identity import (
    sandbox_identity_cwd,
    sandbox_identity_user,
)

from .._tool import Tool, ToolError, tool

_SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@tool(parallel=True)
def view_image(
    user: str | None = None,
    sandbox: str | None = None,
) -> Tool:
    """Image viewing tool.

    Read a PNG, JPEG, GIF or WebP file from a sandbox environment and
    return it to the model as an image.

    Args:
        user: User to read the file as.
        sandbox: Optional sandbox environment name.
    """

    async def execute(file_path: str) -> ContentImage:
        """View an image file.

        Supports PNG, JPEG, GIF and WebP files.

        Args:
            file_path: Path to the image file.
        """
        sbox = sandbox_env(sandbox)
        cwd = sandbox_identity_cwd(sbox, None)
        path = (
            posixpath.join(cwd, file_path)
            if cwd is not None and not posixpath.isabs(file_path)
            else file_path
        )
        data = await sbox.read_file(
            path, text=False, user=sandbox_identity_user(sbox, user, strict=True)
        )
        mime_type = _sniff_image_mime_type(data)
        if mime_type not in _SUPPORTED_MIME_TYPES:
            raise ToolError(f"{file_path} is not a PNG, JPEG, GIF or WebP image.")
        return ContentImage(
            image=as_data_uri(mime_type, base64.b64encode(data).decode("ascii"))
        )

    return execute
