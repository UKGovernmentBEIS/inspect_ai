import base64
import mimetypes

import httpx

from .file import file
from .url import (
    data_uri_mime_type,
    data_uri_to_base64,
    is_data_uri,
    is_http_url,
)


async def image_as_data(image: str) -> tuple[bytes, str]:
    if is_data_uri(image):
        # resolve mime type and base64 content
        mime_type = data_uri_mime_type(image) or "image/png"
        image_base64 = data_uri_to_base64(image)
        image_bytes = base64.b64decode(image_base64)
    else:
        # guess mime type; need strict=False for webp images
        type, _ = mimetypes.guess_type(image, strict=False)
        if type:
            mime_type = type
        else:
            mime_type = "image/png"

        # handle url or file
        if is_http_url(image):
            client = httpx.AsyncClient()
            image_bytes = (await client.get(image)).content
        else:
            with file(image, "rb") as f:
                image_bytes = f.read()

    # return bytes and type
    return image_bytes, mime_type


async def image_as_data_uri(image: str) -> str:
    bytes, mime_type = await image_as_data(image)
    base64_image = base64.b64encode(bytes).decode("utf-8")
    image = f"data:{mime_type};base64,{base64_image}"
    return image
