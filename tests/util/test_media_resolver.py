import base64
import os
import tempfile
from contextvars import Token
from pathlib import Path
from unittest.mock import AsyncMock, patch

import anyio
import httpx
import pytest

from inspect_ai._util.images import (
    UnresolvedMediaError,
    _get_resolver,
    _media_resolvers,
    file_as_data,
    file_as_data_uri,
    inline_media_data,
    inline_media_data_uri,
    media_resolver,
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

    @pytest.mark.parametrize("status_code", [302, 404, 500])
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
