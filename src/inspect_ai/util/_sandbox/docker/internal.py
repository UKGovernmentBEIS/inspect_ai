from inspect_ai._util.ansi import no_ansi
from inspect_ai._util.constants import PKG_PATH
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import subprocess

INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB = "aisiuk/inspect-web-browser-tool"

INSPECT_WEB_BROWSER_IMAGE = "inspect_web_browser"

INTERNAL_IMAGES = {
    INSPECT_WEB_BROWSER_IMAGE: PKG_PATH
    / "tool"
    / "_tools"
    / "_web_browser"
    / "_resources"
}


async def is_internal_image_built(image: str) -> bool:
    result = await subprocess(
        ["docker", "images", "--filter", f"reference={image}", "--format", "json"]
    )
    return len(result.stdout.strip()) > 0


async def build_internal_image(image: str) -> None:
    result = await subprocess(
        [
            "docker",
            "build",
            "--tag",
            image,
            "--progress",
            "plain" if no_ansi() else "auto",
            INTERNAL_IMAGES[image].as_posix(),
        ],
        capture_output=False,
    )
    if not result.success:
        raise PrerequisiteError(f"Unexpected error building Docker image '{image}'")


def is_internal_image(image: str) -> bool:
    return any([image == internal for internal in INTERNAL_IMAGES.keys()])
