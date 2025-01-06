import base64
import mimetypes

import httpx

from .file import file as open_file
from .url import (
    data_uri_mime_type,
    data_uri_to_base64,
    is_data_uri,
    is_http_url,
)


async def file_as_data(file: str) -> tuple[bytes, str]:
    if is_data_uri(file):
        # resolve mime type and base64 content
        mime_type = data_uri_mime_type(file) or "image/png"
        file_base64 = data_uri_to_base64(file)
        file_bytes = base64.b64decode(file_base64)
    else:
        # guess mime type; need strict=False for webp images
        type, _ = mimetypes.guess_type(file, strict=False)
        if type:
            mime_type = type
        else:
            mime_type = "image/png"

        # handle url or file
        if is_http_url(file):
            client = httpx.AsyncClient()
            file_bytes = (await client.get(file)).content
        else:
            with open_file(file, "rb") as f:
                file_bytes = f.read()

    # return bytes and type
    return file_bytes, mime_type


async def file_as_data_uri(file: str) -> str:
    if is_data_uri(file):
        return file
    else:
        bytes, mime_type = await file_as_data(file)
        base64_file = base64.b64encode(bytes).decode("utf-8")
        file = f"data:{mime_type};base64,{base64_file}"
        return file
