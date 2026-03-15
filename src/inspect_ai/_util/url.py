import re
from urllib.parse import parse_qs, urlparse, urlunparse


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


def location_without_query(location: str) -> str:
    """Return the location path without query parameters.

    Useful for checking file extensions on locations that may have query params.

    Args:
        location: URL or file path, possibly with query parameters.

    Returns:
        Location without query parameters.

    Examples:
        >>> location_without_query("s3://bucket/file.eval?versionId=abc")
        's3://bucket/file.eval'
        >>> location_without_query("s3://bucket/file.eval")
        's3://bucket/file.eval'
    """
    parsed = urlparse(location)
    return urlunparse(parsed._replace(query=""))


def location_query_param(location: str, param: str) -> str | None:
    """Extract a specific query parameter value from a location.

    Args:
        location: URL or file path with query parameters.
        param: Name of the query parameter to extract.

    Returns:
        The value of the query parameter, or None if not present.

    Examples:
        >>> location_query_param("s3://bucket/file.eval?versionId=abc", "versionId")
        'abc'
        >>> location_query_param("s3://bucket/file.eval", "versionId")
        None
    """
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    values = query.get(param)
    return values[0] if values else None
