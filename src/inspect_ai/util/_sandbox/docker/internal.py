from inspect_ai._util.constants import PKG_PATH
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._display import display_type
from inspect_ai.util._subprocess import subprocess

INSPECT_WEB_BROWSER_IMAGE_DOCKERHUB_DEPRECATED = "aisiuk/inspect-web-browser-tool"

INSPECT_WEB_BROWSER_IMAGE_DEPRECATED = "inspect_web_browser"
INSPECT_COMPUTER_IMAGE = "inspect-computer-tool"

INTERNAL_IMAGES = {
    INSPECT_WEB_BROWSER_IMAGE_DEPRECATED: PKG_PATH
    / "tool"
    / "_tools"
    / "_web_browser"
    / "_resources",
    INSPECT_COMPUTER_IMAGE: PKG_PATH / "tool" / "beta" / "_computer" / "_resources",
}


async def is_internal_image_built(image: str, docker_host: str | None = None) -> bool:
    docker_cmd = ["docker"]
    if docker_host:
        docker_cmd.extend(["-H", docker_host])
    docker_cmd.extend(["images", "--filter", f"reference={image}", "--format", "json"])

    result = await subprocess(docker_cmd)
    return len(result.stdout.strip()) > 0


async def build_internal_image(image: str, docker_host: str | None = None) -> None:
    args = ["docker"]
    if docker_host:
        args.extend(["-H", docker_host])
    args.extend(
        [
            "build",
            "--tag",
            image,
            "--progress",
            "plain" if display_type() == "plain" else "auto",
        ]
    )
    if display_type() == "none":
        args.append("--quiet")
    result = await subprocess(
        args + [INTERNAL_IMAGES[image].as_posix()],
        capture_output=False,
    )
    if not result.success:
        raise PrerequisiteError(f"Unexpected error building Docker image '{image}'")


def is_internal_image(image: str) -> bool:
    return any([image == internal for internal in INTERNAL_IMAGES.keys()])
