import pytest

from inspect_ai._util.url import data_uri_mime_type, data_uri_to_base64, is_data_uri


@pytest.mark.parametrize(
    "data_url,expected",
    [
        ("data:image/png;base64,iVBORw0KAAAA", "image/png"),
        ("data:text/html;charset=utf-8;base64,PGh0bWw+", "text/html"),
        ("data:text/plain;charset=utf-8,hello", "text/plain"),
        ("data:image/png,iVBORw0KAAAA", "image/png"),
        ("data:image/svg+xml,%3Csvg%3E%3C/svg%3E", "image/svg+xml"),
        ("data:text/plain,hello", "text/plain"),
        ("data:text/plain,hello;world", "text/plain"),
        ("data:text/plain,", "text/plain"),
        ("data:;base64,SGVsbG8=", None),
        ("data:;charset=utf-8,hello", None),
        ("data:,hello", None),
        ("data:,hello;world", None),
        ("data:image/png", None),
        ("https://example.com/image.png", None),
        ("", None),
    ],
)
def test_data_uri_mime_type(data_url: str, expected: str | None) -> None:
    assert data_uri_mime_type(data_url) == expected


def test_is_data_uri_simple_base64() -> None:
    assert is_data_uri("data:image/png;base64,iVBORw0KAAAA")


def test_is_data_uri_with_media_type_parameters() -> None:
    # media-type parameters (e.g. charset, name) before ";base64," are valid
    assert is_data_uri("data:text/html;charset=utf-8;base64,PGh0bWw+")
    assert is_data_uri("data:image/svg+xml;charset=utf-8;base64,PHN2Zz4=")
    assert is_data_uri("data:image/jpeg;name=a.jpg;base64,QQ==")


def test_is_data_uri_empty_media_type() -> None:
    # RFC 2397 permits an omitted media type (defaults to text/plain)
    assert is_data_uri("data:;base64,SGVsbG8=")


def test_is_data_uri_rejects_non_base64_and_urls() -> None:
    assert not is_data_uri("data:text/plain,hello")
    assert not is_data_uri("data:text/plain;charset=utf-8,hello")
    assert not is_data_uri("https://example.com/x.png")


def test_data_uri_to_base64() -> None:
    assert data_uri_to_base64("data:image/png;base64,iVBORw0KAAAA") == "iVBORw0KAAAA"
    assert (
        data_uri_to_base64("data:text/html;charset=utf-8;base64,PGh0bWw+") == "PGh0bWw+"
    )
    assert data_uri_to_base64("data:;base64,SGVsbG8=") == "SGVsbG8="
    assert data_uri_to_base64("data:,SGVsbG8=") == "SGVsbG8="
