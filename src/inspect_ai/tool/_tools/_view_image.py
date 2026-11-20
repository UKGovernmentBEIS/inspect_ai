import base64
import binascii

from inspect_ai._util.content import ContentImage
from inspect_ai._util.images import as_data_uri, sniff_image_mime_type
from inspect_ai.util import (
    OutputLimitExceededError,
    SandboxEnvironmentLimits,
    SandboxTimeoutError,
)
from inspect_ai.util import sandbox as sandbox_env
from inspect_ai.util._sandbox.events import without_sandbox_events
from inspect_ai.util._sandbox.identity import (
    sandbox_identity_cwd,
    sandbox_identity_user,
    sandbox_identity_vars,
)

from .._tool import Tool, ToolError, tool

_SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
_HEADER = "#\n"


def _too_large_error(file_path: str) -> ToolError:
    return ToolError(
        f"{file_path} is too large to view: its base64 encoding exceeds the "
        f"{SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE_STR} sandbox output limit."
    )


@tool(parallel=True)
def view_image(
    timeout: int | None = None,
    user: str | None = None,
    sandbox: str | None = None,
) -> Tool:
    """Image viewing tool.

    Read a PNG, JPEG, GIF or WebP file from a sandbox environment and
    return it to the model as an image.

    Args:
        timeout: Timeout (in seconds) for read operation.
        user: User to execute as.
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
        exec_user = sandbox_identity_user(sbox, user, strict=True)
        env = await sandbox_identity_vars(sbox, timeout)
        with without_sandbox_events(sbox):
            try:
                result = await sbox.exec(
                    cmd=[
                        "sh",
                        "-c",
                        'printf "#\\n"; exec base64 < "$1"',
                        "sh",
                        file_path,
                    ],
                    cwd=cwd,
                    timeout=timeout,
                    user=exec_user,
                    env=env,
                )
            except OutputLimitExceededError as ex:
                raise _too_large_error(file_path) from ex
            except TimeoutError as ex:
                raise SandboxTimeoutError(str(ex)) from ex
        if not result.success:
            raise ToolError(
                result.stderr.strip()
                if result.stderr
                else f"Error reading: {file_path}"
            )

        if not result.stdout.startswith(_HEADER):
            raise _too_large_error(file_path)
        try:
            data = base64.b64decode(result.stdout[len(_HEADER) :])
        except binascii.Error as ex:
            raise ToolError(f"{file_path} could not be decoded: {ex}") from ex
        mime_type = sniff_image_mime_type(data)
        if mime_type not in _SUPPORTED_MIME_TYPES:
            raise ToolError(f"{file_path} is not a PNG, JPEG, GIF or WebP image.")
        return ContentImage(
            image=as_data_uri(mime_type, base64.b64encode(data).decode("ascii"))
        )

    return execute
