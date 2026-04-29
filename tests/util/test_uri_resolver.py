import base64
import os
import tempfile

import anyio

from inspect_ai._util.images import (
    _get_resolver,
    _global_uri_resolvers,
    _scoped_uri_resolvers,
    file_as_data,
    file_as_data_uri,
    register_uri_resolver,
    unregister_uri_resolver,
    uri_resolver,
)


class TestGlobalUriResolverRegistry:
    def setup_method(self) -> None:
        _global_uri_resolvers.clear()

    def teardown_method(self) -> None:
        _global_uri_resolvers.clear()

    def test_register_resolver(self) -> None:
        async def resolver(uri: str) -> str:
            return uri

        register_uri_resolver("s3", resolver)
        assert "s3" in _global_uri_resolvers
        assert _global_uri_resolvers["s3"] is resolver

    def test_unregister_resolver(self) -> None:
        async def resolver(uri: str) -> str:
            return uri

        register_uri_resolver("s3", resolver)
        unregister_uri_resolver("s3")
        assert "s3" not in _global_uri_resolvers

    def test_unregister_nonexistent(self) -> None:
        unregister_uri_resolver("nonexistent")  # should not raise

    def test_register_overwrites(self) -> None:
        async def resolver1(uri: str) -> str:
            return "1"

        async def resolver2(uri: str) -> str:
            return "2"

        register_uri_resolver("s3", resolver1)
        register_uri_resolver("s3", resolver2)
        assert _global_uri_resolvers["s3"] is resolver2

    def test_register_returns_cleanup(self) -> None:
        async def resolver(uri: str) -> str:
            return uri

        cleanup = register_uri_resolver("test", resolver)
        assert "test" in _global_uri_resolvers
        cleanup()
        assert "test" not in _global_uri_resolvers


class TestScopedUriResolver:
    def setup_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    def teardown_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    async def test_scoped_resolver(self) -> None:
        async def resolver(uri: str) -> str:
            return uri

        assert _get_resolver("gs") is None
        async with uri_resolver("gs", resolver):
            assert _get_resolver("gs") is resolver
            assert "gs" not in _global_uri_resolvers
        assert _get_resolver("gs") is None

    async def test_cleanup_on_exception(self) -> None:
        async def resolver(uri: str) -> str:
            return uri

        try:
            async with uri_resolver("gs", resolver):
                raise ValueError("test")
        except ValueError:
            pass
        assert _get_resolver("gs") is None

    async def test_scoped_precedence(self) -> None:
        async def global_resolver(uri: str) -> str:
            return "global"

        async def scoped_resolver(uri: str) -> str:
            return "scoped"

        register_uri_resolver("s3", global_resolver)
        assert _get_resolver("s3") is global_resolver

        async with uri_resolver("s3", scoped_resolver):
            assert _get_resolver("s3") is scoped_resolver
        assert _get_resolver("s3") is global_resolver

    async def test_nested_same_scheme(self) -> None:
        async def outer(uri: str) -> str:
            return "outer"

        async def inner(uri: str) -> str:
            return "inner"

        async with uri_resolver("s3", outer):
            assert _get_resolver("s3") is outer
            async with uri_resolver("s3", inner):
                assert _get_resolver("s3") is inner
            assert _get_resolver("s3") is outer
        assert _get_resolver("s3") is None


class TestConcurrentIsolation:
    def setup_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    def teardown_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    async def test_concurrent_tasks_isolated(self) -> None:
        results: dict[str, str] = {}

        async def resolver_a(uri: str) -> str:
            return "data:text/plain;base64,QQ=="

        async def resolver_b(uri: str) -> str:
            return "data:text/plain;base64,Qg=="

        async def task_a() -> None:
            async with uri_resolver("test", resolver_a):
                await anyio.sleep(0.01)
                data, _ = await file_as_data("test://bucket/file")
                results["a"] = data.decode()

        async def task_b() -> None:
            async with uri_resolver("test", resolver_b):
                await anyio.sleep(0.01)
                data, _ = await file_as_data("test://bucket/file")
                results["b"] = data.decode()

        async with anyio.create_task_group() as tg:
            tg.start_soon(task_a)
            tg.start_soon(task_b)

        assert results["a"] == "A"
        assert results["b"] == "B"


class TestFileAsDataResolver:
    def setup_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    def teardown_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    async def test_resolver_called(self) -> None:
        calls: list[str] = []

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name

        try:

            async def resolver(uri: str) -> str:
                calls.append(uri)
                return path

            register_uri_resolver("test", resolver)
            await file_as_data("test://bucket/image.png")
            assert calls == ["test://bucket/image.png"]
        finally:
            os.unlink(path)

    async def test_resolver_returns_data_uri(self) -> None:
        content = b"test"
        b64 = base64.b64encode(content).decode()

        async def resolver(uri: str) -> str:
            return f"data:text/plain;base64,{b64}"

        register_uri_resolver("custom", resolver)
        data, mime = await file_as_data("custom://x")
        assert data == content
        assert mime == "text/plain"

    async def test_windows_path_not_matched(self) -> None:
        called = False

        async def resolver(uri: str) -> str:
            nonlocal called
            called = True
            return "data:text/plain;base64,Yw=="

        register_uri_resolver("c", resolver)

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False) as f:
            f.write(b"local")
            path = f.name

        try:
            data, _ = await file_as_data(path)
            assert not called
            assert data == b"local"
        finally:
            os.unlink(path)


class TestFileAsDataUri:
    def setup_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    def teardown_method(self) -> None:
        _global_uri_resolvers.clear()
        _scoped_uri_resolvers.set({})

    async def test_data_uri_passthrough(self) -> None:
        uri = "data:text/plain;base64,aGVsbG8="
        assert await file_as_data_uri(uri) == uri

    async def test_data_scheme_not_matched(self) -> None:
        called = False

        async def resolver(uri: str) -> str:
            nonlocal called
            called = True
            return "data:text/plain;base64,eA=="

        register_uri_resolver("data", resolver)
        uri = "data:text/plain;base64,aGVsbG8="
        result = await file_as_data_uri(uri)
        assert not called
        assert result == uri
