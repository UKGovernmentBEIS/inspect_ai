from inspect_ai._util.url import is_data_uri


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
