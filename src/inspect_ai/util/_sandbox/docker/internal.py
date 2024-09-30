from inspect_ai._util.ansi import no_ansi
from inspect_ai._util.constants import PKG_PATH
from inspect_ai.util._subprocess import subprocess

INTERNAL_IMAGES = {
    "inspect-web-browser:0.5": PKG_PATH
    / "tool"
    / "_tools"
    / "web_browser"
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
        raise RuntimeError(
            f"Unexpected error building Docker image '{image}': {result.stderr}"
        )


def is_internal_image(image: str) -> bool:
    return any([image == internal for internal in INTERNAL_IMAGES.keys()])
