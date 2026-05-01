import base64
import os
import tempfile
from contextvars import Token

import anyio
import pytest

from inspect_ai._util.images import (
    _get_resolver,
    _media_resolvers,
    file_as_data,
    file_as_data_uri,
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
