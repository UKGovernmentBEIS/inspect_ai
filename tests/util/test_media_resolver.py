import base64
import ipaddress
import os
import socket
import tempfile
from collections.abc import AsyncIterator
from contextvars import Token
from pathlib import Path
from unittest.mock import AsyncMock, patch

import anyio
import httpcore
import httpx
import pytest

from inspect_ai._util.images import (
    _PROVIDER_IMAGE_MAX_BYTES,
    MediaKind,
    UnresolvedMediaError,
    _get_resolver,
    _is_public_ip_address,
    _media_resolvers,
    _provider_image_response_data_uri,
    _PublicNetworkBackend,
    file_as_data,
    file_as_data_uri,
    inline_media_data,
    inline_media_data_uri,
    materialize_media,
    media_resolver,
    provider_image_data_uri,
)


class TestMediaResolver:
    _token: Token[dict] | None = None

    def setup_method(self) -> None:
        # Save current state and set empty dict
        self._token = _media_resolvers.set({})

    def teardown_method(self) -> None:
        # Reset to previous state
        if self._token is not None:
            _media_resolvers.reset(self._token)

    def test_resolver_registration(self) -> None:
        async def resolver(uri: str) -> str:
            return uri

        assert _get_resolver("gs") is None
        with media_resolver("gs", resolver):
            assert _get_resolver("gs") is resolver
        assert _get_resolver("gs") is None

    def test_cleanup_on_exception(self) -> None:
        async def resolver(uri: str) -> str:
            return uri

        try:
            with media_resolver("gs", resolver):
                raise ValueError("test")
        except ValueError:
            pass
        assert _get_resolver("gs") is None

    def test_nested_same_scheme(self) -> None:
        async def outer(uri: str) -> str:
            return "outer"

        async def inner(uri: str) -> str:
            return "inner"

        with media_resolver("s3", outer):
            assert _get_resolver("s3") is outer
            with media_resolver("s3", inner):
                assert _get_resolver("s3") is inner
            assert _get_resolver("s3") is outer
        assert _get_resolver("s3") is None

    def test_multiple_schemes_simultaneously(self) -> None:
        async def s3_resolver(uri: str) -> str:
            return "s3_resolved"

        async def gs_resolver(uri: str) -> str:
            return "gs_resolved"

        with media_resolver("s3", s3_resolver):
            with media_resolver("gs", gs_resolver):
                assert _get_resolver("s3") is s3_resolver
                assert _get_resolver("gs") is gs_resolver
            assert _get_resolver("s3") is s3_resolver
            assert _get_resolver("gs") is None
        assert _get_resolver("s3") is None


class TestConcurrentIsolation:
    _token: Token[dict] | None = None

    def setup_method(self) -> None:
        self._token = _media_resolvers.set({})

    def teardown_method(self) -> None:
        if self._token is not None:
            _media_resolvers.reset(self._token)

    async def test_concurrent_tasks_isolated(self) -> None:
        results: dict[str, str] = {}

        async def resolver_a(uri: str) -> str:
            return "data:text/plain;base64,QQ=="

        async def resolver_b(uri: str) -> str:
            return "data:text/plain;base64,Qg=="

        async def task_a() -> None:
            with media_resolver("test", resolver_a):
                await anyio.sleep(0.01)
                data, _ = await file_as_data("test://bucket/file")
                results["a"] = data.decode()

        async def task_b() -> None:
            with media_resolver("test", resolver_b):
                await anyio.sleep(0.01)
                data, _ = await file_as_data("test://bucket/file")
                results["b"] = data.decode()

        async with anyio.create_task_group() as tg:
            tg.start_soon(task_a)
            tg.start_soon(task_b)

        assert results["a"] == "A"
        assert results["b"] == "B"


class TestFileAsDataResolver:
    _token: Token[dict] | None = None

    def setup_method(self) -> None:
        self._token = _media_resolvers.set({})

    def teardown_method(self) -> None:
        if self._token is not None:
            _media_resolvers.reset(self._token)

    async def test_resolver_called(self) -> None:
        calls: list[str] = []

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name

        try:

            async def resolver(uri: str) -> str:
                calls.append(uri)
                return path

            with media_resolver("test", resolver):
                await file_as_data("test://bucket/image.png")
            assert calls == ["test://bucket/image.png"]
        finally:
            os.unlink(path)

    async def test_resolver_returns_data_uri(self) -> None:
        content = b"test"
        b64 = base64.b64encode(content).decode()

        async def resolver(uri: str) -> str:
            return f"data:text/plain;base64,{b64}"

        with media_resolver("custom", resolver):
            data, mime = await file_as_data("custom://x")
        assert data == content
        assert mime == "text/plain"

    async def test_windows_path_not_matched(self) -> None:
        called = False

        async def resolver(uri: str) -> str:
            nonlocal called
            called = True
            return "data:text/plain;base64,Yw=="

        with media_resolver("c", resolver):
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".txt", delete=False
            ) as f:
                f.write(b"local")
                path = f.name

            try:
                data, _ = await file_as_data(path)
                assert not called
                assert data == b"local"
            finally:
                os.unlink(path)

    async def test_resolver_failure_raises_value_error(self) -> None:
        async def failing_resolver(uri: str) -> str:
            raise RuntimeError("Connection failed")

        with media_resolver("fail", failing_resolver):
            with pytest.raises(ValueError) as exc_info:
                await file_as_data("fail://bucket/file")
            assert "Media resolver for scheme 'fail' failed" in str(exc_info.value)
            assert "fail://bucket/file" in str(exc_info.value)
            assert exc_info.value.__cause__ is not None
            assert isinstance(exc_info.value.__cause__, RuntimeError)

    async def test_resolver_returns_custom_scheme_not_reresolved(self) -> None:
        """Verify that returning another custom scheme URI does not trigger re-resolution."""
        calls: list[str] = []

        async def outer_resolver(uri: str) -> str:
            calls.append(f"outer:{uri}")
            # Return another custom scheme URI
            return "inner://should/not/resolve"

        async def inner_resolver(uri: str) -> str:
            calls.append(f"inner:{uri}")
            return "data:text/plain;base64,dGVzdA=="

        with media_resolver("outer", outer_resolver):
            with media_resolver("inner", inner_resolver):
                # This should fail because inner:// is not re-resolved
                # and "inner://should/not/resolve" is not a valid file
                with pytest.raises(Exception):
                    await file_as_data("outer://test")

        # Only outer resolver should have been called
        assert calls == ["outer:outer://test"]


class TestFileAsDataUri:
    _token: Token[dict] | None = None

    def setup_method(self) -> None:
        self._token = _media_resolvers.set({})

    def teardown_method(self) -> None:
        if self._token is not None:
            _media_resolvers.reset(self._token)

    async def test_data_uri_passthrough(self) -> None:
        uri = "data:text/plain;base64,aGVsbG8="
        assert await file_as_data_uri(uri) == uri

    @pytest.mark.parametrize(
        "uri",
        [
            "data:;base64,AAAA",
            "data:application/octet-stream;base64,AAAA",
            "data:binary/octet-stream;base64,AAAA",
        ],
    )
    async def test_materialize_media_applies_hint_to_untyped_inline_data(
        self, uri: str
    ) -> None:
        assert await materialize_media(uri, "application/pdf") == (
            "data:application/pdf;base64,AAAA"
        )

    async def test_materialize_media_preserves_specific_inline_type(self) -> None:
        uri = "data:text/plain;base64,AAAA"
        assert await materialize_media(uri, "application/pdf") == uri

    async def test_data_scheme_not_matched(self) -> None:
        called = False

        async def resolver(uri: str) -> str:
            nonlocal called
            called = True
            return "data:text/plain;base64,eA=="

        with media_resolver("data", resolver):
            uri = "data:text/plain;base64,aGVsbG8="
            result = await file_as_data_uri(uri)
        assert not called
        assert result == uri

    async def test_mime_type_hint_for_extensionless_file(self, tmp_path: Path) -> None:
        path = tmp_path / "audio"
        path.write_bytes(b"audio")

        uri = await file_as_data_uri(str(path), mime_type="audio/mpeg")

        assert uri.startswith("data:audio/mpeg;base64,")


class TestFileAsDataHttp:
    async def test_response_content_type_is_used(self) -> None:
        request = httpx.Request("GET", "https://example.com/download")
        response = httpx.Response(
            200,
            content=b"audio",
            headers={"content-type": "audio/mpeg; charset=binary"},
            request=request,
        )

        with patch.object(
            httpx.AsyncClient,
            "get",
            new=AsyncMock(return_value=response),
        ):
            data, mime_type = await file_as_data(str(request.url))

        assert data == b"audio"
        assert mime_type == "audio/mpeg"

    async def test_generic_content_type_falls_back_to_url(self) -> None:
        request = httpx.Request("GET", "https://example.com/audio.mp3")
        response = httpx.Response(
            200,
            content=b"audio",
            headers={"content-type": "application/octet-stream"},
            request=request,
        )

        with patch.object(
            httpx.AsyncClient,
            "get",
            new=AsyncMock(return_value=response),
        ):
            _, mime_type = await file_as_data(str(request.url))

        assert mime_type == "audio/mpeg"

    async def test_generic_content_type_falls_back_to_hint(self) -> None:
        request = httpx.Request("GET", "https://example.com/audio.bin")
        response = httpx.Response(
            200,
            content=b"audio",
            headers={"content-type": "application/octet-stream"},
            request=request,
        )

        with patch.object(
            httpx.AsyncClient,
            "get",
            new=AsyncMock(return_value=response),
        ):
            _, mime_type = await file_as_data(str(request.url), mime_type="audio/mpeg")

        assert mime_type == "audio/mpeg"

    async def test_redirect_is_followed(self) -> None:
        requests: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            if request.url.path == "/media":
                return httpx.Response(302, headers={"location": "/secret"})
            return httpx.Response(200, content=b"secret")

        client_type = httpx.AsyncClient

        def client_factory(*, follow_redirects: bool) -> httpx.AsyncClient:
            return client_type(
                transport=httpx.MockTransport(handler),
                follow_redirects=follow_redirects,
            )

        with patch(
            "inspect_ai._util.images.httpx.AsyncClient",
            side_effect=client_factory,
        ):
            data, _ = await file_as_data("https://example.com/media")

        assert data == b"secret"
        assert requests == [
            "https://example.com/media",
            "https://example.com/secret",
        ]

    @pytest.mark.parametrize("status_code", [404, 500])
    async def test_non_success_status_rejected(self, status_code: int) -> None:
        request = httpx.Request("GET", "https://example.com/media")
        response = httpx.Response(status_code, request=request)

        with (
            patch.object(
                httpx.AsyncClient,
                "get",
                new=AsyncMock(return_value=response),
            ),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await file_as_data(str(request.url))


class TestFileAsDataSniffing:
    @pytest.mark.parametrize(
        ("data", "expected_mime_type"),
        [
            pytest.param(b"\x89PNG\r\n\x1a\n", "image/png", id="png"),
            pytest.param(b"\xff\xd8\xff\xe0", "image/jpeg", id="jpeg"),
            pytest.param(b"GIF87a", "image/gif", id="gif87a"),
            pytest.param(b"GIF89a", "image/gif", id="gif89a"),
            pytest.param(b"RIFF\x00\x00\x00\x00WEBP", "image/webp", id="webp"),
            pytest.param(b"BM\x00\x00", "image/bmp", id="bmp"),
            pytest.param(
                b"unknown",
                "application/octet-stream",
                id="unknown",
            ),
        ],
    )
    async def test_extensionless_file(
        self,
        tmp_path: Path,
        data: bytes,
        expected_mime_type: str,
    ) -> None:
        path = tmp_path / "media"
        path.write_bytes(data)

        _, mime_type = await file_as_data(str(path))

        assert mime_type == expected_mime_type


class TestProviderImageDataUri:
    async def test_inline_image_is_returned_without_network_access(self) -> None:
        image = "data:image/png;base64,iVBORw0KGgo="
        with patch("inspect_ai._util.images.httpcore.AsyncConnectionPool") as pool:
            assert await provider_image_data_uri(image) == image
        pool.assert_not_called()

    async def test_mime_less_inline_image_is_sniffed(self) -> None:
        image = "data:;base64,iVBORw0KGgo="

        assert await provider_image_data_uri(image) == (
            "data:image/png;base64,iVBORw0KGgo="
        )

    @pytest.mark.parametrize(
        ("image", "message"),
        [
            ("data:image/png;base64,not-valid!", "invalid base64"),
            ("data:image/png;base64,bm90cG5n", "recognized raster image"),
        ],
    )
    async def test_invalid_inline_image_is_rejected(
        self, image: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            await provider_image_data_uri(image)

    async def test_oversized_inline_image_is_rejected(self) -> None:
        image = "data:image/png;base64,iVBORw0KGgpY"
        with (
            patch("inspect_ai._util.images._PROVIDER_IMAGE_MAX_BYTES", 8),
            pytest.raises(ValueError, match="20 MiB"),
        ):
            await provider_image_data_uri(image)

    @pytest.mark.parametrize(
        ("url", "message"),
        [
            ("http://example.com/image.png", "HTTPS"),
            ("https://user:pass@example.com/image.png", "credentials"),
            ("https://example.com:8443/image.png", "default HTTPS port"),
        ],
    )
    async def test_unsafe_url_is_rejected(self, url: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            await provider_image_data_uri(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/image.png",
            "https://169.254.169.254/latest/meta-data",
            "https://224.0.0.1/image.png",
            "https://[::1]/image.png",
            "https://[::ffff:127.0.0.1]/image.png",
            "https://[::ffff:0:169.254.169.254]/image.png",
            "https://[64:ff9b::169.254.169.254]/image.png",
            "https://[64:ff9b::192.168.0.1]/image.png",
            "https://[64:ff9b::224.0.0.1]/image.png",
            "https://[64:ff9b:1::a9fe:a9fe]/image.png",
            "https://[ff02::1]/image.png",
        ],
    )
    async def test_private_ip_address_is_rejected(self, url: str) -> None:
        with pytest.raises(ValueError, match="public address"):
            await provider_image_data_uri(url)

    @pytest.mark.parametrize(
        "address",
        [
            "93.184.216.34",
            "2606:2800:220:1:248:1893:25c8:1946",
            "::ffff:0:93.184.216.34",
            "64:ff9b::93.184.216.34",
        ],
    )
    def test_public_ip_address_is_accepted(self, address: str) -> None:
        assert _is_public_ip_address(ipaddress.ip_address(address))

    async def test_private_dns_result_is_rejected(self) -> None:
        address_info = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("169.254.169.254", 443),
            )
        ]
        with patch(
            "inspect_ai._util.images.anyio.getaddrinfo",
            new=AsyncMock(return_value=address_info),
        ):
            with pytest.raises(ValueError, match="public address"):
                await _PublicNetworkBackend().connect_tcp("metadata.test", 443)

    async def test_dns_result_is_pinned_to_validated_address(self) -> None:
        address_info = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", 443),
            )
        ]
        stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
        delegate = AsyncMock(spec=httpcore.AsyncNetworkBackend)
        delegate.connect_tcp.return_value = stream

        with patch(
            "inspect_ai._util.images.anyio.getaddrinfo",
            new=AsyncMock(return_value=address_info),
        ):
            result = await _PublicNetworkBackend(delegate).connect_tcp(
                "example.com", 443, timeout=1.0
            )

        assert result is stream
        delegate.connect_tcp.assert_awaited_once_with(
            host="93.184.216.34",
            port=443,
            timeout=1.0,
            local_address=None,
            socket_options=None,
        )

    async def test_valid_raster_response_is_inlined(self) -> None:
        png = b"\x89PNG\r\n\x1a\n"
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n"
            b"Content-Type: application/octet-stream\r\n\r\n" + png
        )
        backend = httpcore.AsyncMockBackend([response])

        with patch(
            "inspect_ai._util.images._PublicNetworkBackend", return_value=backend
        ):
            result = await provider_image_data_uri(
                "https://example.com/image?signature=secret"
            )

        assert result == "data:image/png;base64,iVBORw0KGgo="

    async def test_redirect_is_revalidated(self) -> None:
        response = (
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n"
            b"Location: http://127.0.0.1/image.png\r\n\r\n"
        )
        backend = httpcore.AsyncMockBackend([response])

        with patch(
            "inspect_ai._util.images._PublicNetworkBackend", return_value=backend
        ):
            with pytest.raises(ValueError, match="HTTPS"):
                await provider_image_data_uri("https://example.com/image.png")

    async def test_redirect_to_private_address_is_rejected(self) -> None:
        response = (
            b"HTTP/1.1 302 Found\r\nContent-Length: 0\r\n"
            b"Location: https://169.254.169.254/latest/meta-data\r\n\r\n"
        )
        network_backend = _PublicNetworkBackend(httpcore.AsyncMockBackend([response]))
        address_info = [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", 443),
            )
        ]

        with (
            patch(
                "inspect_ai._util.images.anyio.getaddrinfo",
                new=AsyncMock(return_value=address_info),
            ),
            patch(
                "inspect_ai._util.images._PublicNetworkBackend",
                return_value=network_backend,
            ),
            pytest.raises(ValueError, match="public address"),
        ):
            await provider_image_data_uri("https://example.com/image.png")

    async def test_declared_oversized_response_is_rejected(self) -> None:
        response = (
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(_PROVIDER_IMAGE_MAX_BYTES + 1).encode()
            + b"\r\n\r\n"
        )
        backend = httpcore.AsyncMockBackend([response])

        with patch(
            "inspect_ai._util.images._PublicNetworkBackend", return_value=backend
        ):
            with pytest.raises(ValueError, match="20 MiB"):
                await provider_image_data_uri("https://example.com/image.png")

    async def test_streamed_oversized_response_is_rejected(self) -> None:
        async def content() -> AsyncIterator[bytes]:
            yield b"\x89PNG\r\n\x1a\n"
            yield b"X"

        response = httpcore.Response(status=200, content=content())
        with (
            patch("inspect_ai._util.images._PROVIDER_IMAGE_MAX_BYTES", 8),
            pytest.raises(ValueError, match="20 MiB"),
        ):
            await _provider_image_response_data_uri(response)

    async def test_non_image_response_is_rejected(self) -> None:
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nnotpng"
        backend = httpcore.AsyncMockBackend([response])

        with patch(
            "inspect_ai._util.images._PublicNetworkBackend", return_value=backend
        ):
            with pytest.raises(ValueError, match="recognized raster image"):
                await provider_image_data_uri("https://example.com/image.png")

    async def test_error_does_not_disclose_signed_query(self) -> None:
        response = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
        backend = httpcore.AsyncMockBackend([response])

        with patch(
            "inspect_ai._util.images._PublicNetworkBackend", return_value=backend
        ):
            with pytest.raises(ValueError) as exc_info:
                await provider_image_data_uri(
                    "https://example.com/image?signature=secret"
                )

        assert "signature" not in str(exc_info.value)
        assert "secret" not in str(exc_info.value)


class TestInlineMedia:
    def test_inline_media_data(self) -> None:
        data, mime_type = inline_media_data("data:image/png;base64,aGVsbG8=", "image")
        assert data == b"hello"
        assert mime_type == "image/png"

    def test_inline_media_data_uri(self) -> None:
        uri = "data:application/pdf;base64,aGVsbG8="
        assert inline_media_data_uri(uri, "document") == uri

    def test_inline_media_data_uri_does_not_decode(self) -> None:
        uri = "data:image/png;base64,aGVsbG8="
        with patch("inspect_ai._util.images.base64.b64decode") as decode:
            assert inline_media_data_uri(uri, "image") == uri
        decode.assert_not_called()

    def test_mime_less_image_is_sniffed(self) -> None:
        uri = "data:;base64,iVBORw0KGgo="
        assert inline_media_data_uri(uri, "image") == (
            "data:image/png;base64,iVBORw0KGgo="
        )

    def test_mime_less_image_uses_compatibility_default(self) -> None:
        assert inline_media_data_uri("data:;base64,PHN2Zy8+", "image") == (
            "data:image/png;base64,PHN2Zy8+"
        )

    @pytest.mark.parametrize(
        ("kind", "mime_type"),
        [
            pytest.param("audio", "audio/mpeg", id="audio"),
            pytest.param("video", "video/quicktime", id="video"),
            pytest.param("document", "application/pdf", id="document"),
        ],
    )
    def test_mime_less_media_uses_hint(self, kind: MediaKind, mime_type: str) -> None:
        assert (
            inline_media_data_uri("data:;base64,AAAA", kind, mime_type_hint=mime_type)
            == f"data:{mime_type};base64,AAAA"
        )

    def test_mime_less_non_image_without_hint_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="could not be inferred"):
            inline_media_data_uri("data:;base64,AAAA", "audio")

    def test_non_inline_media_rejected(self) -> None:
        with pytest.raises(UnresolvedMediaError, match="materialized"):
            inline_media_data_uri("/tmp/image.png", "image")

    def test_mismatched_media_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="incompatible MIME type"):
            inline_media_data_uri("data:text/plain;base64,aGVsbG8=", "image")

    def test_invalid_base64_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid base64"):
            inline_media_data("data:image/png;base64,not-valid!", "image")


class TestGetResolverWithoutContext:
    def test_get_resolver_without_context_returns_none(self) -> None:
        """Test that _get_resolver returns None for an unregistered scheme."""
        # Verify it returns None for an unregistered scheme (tests the .get() part)
        assert _get_resolver("nonexistent") is None

    async def test_media_resolver_works_without_prior_context(self) -> None:
        """Test that media_resolver context manager works even without prior set()."""

        # This tests the LookupError handling in media_resolver
        async def resolver(uri: str) -> str:
            return "data:text/plain;base64,dGVzdA=="

        # Should not raise even if ContextVar was never set
        with media_resolver("fresh", resolver):
            assert _get_resolver("fresh") is resolver
            data, _ = await file_as_data("fresh://test")
            assert data == b"test"
