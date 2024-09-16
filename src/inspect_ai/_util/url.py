import re


def is_http_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def is_data_uri(url: str) -> bool:
    pattern = r"^data:([^;]+);base64,.*"
    return re.match(pattern, url) is not None


def data_uri_mime_type(data_url: str) -> str | None:
    pattern = r"^data:([^;]+);.*"
    match = re.match(pattern, data_url)
    if match:
        mime_type = match.group(1)
        return mime_type
    else:
        return None


def data_uri_to_base64(data_uri: str) -> str:
    pattern = r"^data:[^,]+,"
    stripped_uri = re.sub(pattern, "", data_uri)
    return stripped_uri
