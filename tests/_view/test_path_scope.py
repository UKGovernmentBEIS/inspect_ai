from __future__ import annotations

import asyncio
import base64
import urllib.parse
from pathlib import Path, PureWindowsPath
from typing import Any

import anyio
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request

from inspect_ai._util.file import filesystem
from inspect_ai._view import fastapi_server
from inspect_ai._view.path_scope import (
    VIEW_SCOPE_HEADER,
    VIEW_SCOPE_KIND_HEADER,
    PathScope,
    _local_path_from_file_uri,
)


def _request(*headers: tuple[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (name.lower().encode(), value.encode()) for name, value in headers
            ],
        }
    )


def test_local_directory_scope_uses_canonical_containment(tmp_path: Path) -> None:
    root = tmp_path / "logs"
    root.mkdir()
    sibling = tmp_path / "logs-archive"
    sibling.mkdir()

    scope = PathScope.parse("directory", str(root))
    assert scope.allows(str(root))
    assert scope.allows(str(root / "nested" / "run.eval"))
    assert scope.allows((root / "run.eval").as_uri())
    assert not scope.allows(str(sibling / "run.eval"))
    assert not scope.allows(str(root / ".." / "outside" / "run.eval"))
    assert not scope.allows("s3://bucket/logs/run.eval")


def test_local_directory_scope_resolves_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    selected = tmp_path / "selected"
    outside = tmp_path / "outside"
    outside.mkdir()
    nested_escape = target / "outside"
    try:
        selected.symlink_to(target, target_is_directory=True)
        nested_escape.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is not supported")

    scope = PathScope.parse("directory", str(selected))
    assert scope.allows(str(selected / "run.eval"))
    assert not scope.allows(str(nested_escape / "secret.eval"))


def test_local_directory_scope_retains_selected_symlink_target(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    selected = tmp_path / "selected"
    first.mkdir()
    second.mkdir()
    (first / "allowed.eval").write_text("allowed", encoding="utf-8")
    (second / "secret.eval").write_text("secret", encoding="utf-8")
    try:
        selected.symlink_to(first, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is not supported")

    scope = PathScope.parse("directory", str(selected))
    selected.unlink()
    selected.symlink_to(second, target_is_directory=True)

    assert not scope.allows(str(selected / "secret.eval"))


def test_local_file_scope_is_exact(tmp_path: Path) -> None:
    selected = tmp_path / "selected.eval"
    sibling = tmp_path / "sibling.eval"
    scope = PathScope.parse("file", selected.as_uri())

    assert scope.allows(str(selected))
    assert scope.allows(selected.as_uri())
    assert not scope.allows(str(sibling))


def test_remote_directory_scope_requires_same_authority_and_components() -> None:
    scope = PathScope.parse("directory", "s3://bucket/logs")
    assert scope.allows("s3://bucket/logs/run.eval")
    assert scope.allows("s3://bucket/logs/nested/run.eval")

    rejected = [
        "s3://bucket/logs-archive/run.eval",
        "s3://other/logs/run.eval",
        "s3://bucket/logs/../private/run.eval",
        "s3://bucket/logs/%2e%2e/private/run.eval",
        "file:///tmp/run.eval",
        "https://bucket/logs/run.eval",
    ]
    for location in rejected:
        assert not scope.allows(location)


def test_remote_file_scope_resolves_alias_to_authorized_location() -> None:
    selected = "memory://bucket/logs/secret.eval"
    scope = PathScope.parse("file", selected)

    assert scope.resolve("memory://bucket/logs//secret.eval") == selected


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_http_scopes_are_exact_file_only(scheme: str) -> None:
    selected = f"{scheme}://example.test/logs/run.eval"
    with pytest.raises(ValueError, match="directory scheme"):
        PathScope.parse("directory", f"{scheme}://example.test/logs")

    scope = PathScope.parse("file", selected)
    assert scope.allows(selected)
    assert not scope.allows(f"{scheme}://example.test/logs/other.eval")
    assert not scope.allows(f"{scheme}://other.test/logs/run.eval")
    assert not scope.allows(f"{selected}?token=value")


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_signed_http_file_scopes_require_the_exact_query(scheme: str) -> None:
    selected = f"{scheme}://example.test/logs/run.eval?expires=60&signature=selected"
    scope = PathScope.parse("file", selected)

    assert scope.allows(selected)
    assert not scope.allows(
        f"{scheme}://example.test/logs/run.eval?expires=60&signature=other"
    )
    assert not scope.allows(f"{scheme}://example.test/logs/run.eval")


def test_signed_query_values_use_canonical_rfc3986_encoding() -> None:
    selected = (
        "https://example.test/run.eval?credential=team%2Fmember&label=hello%20world"
    )
    scope = PathScope.parse("file", selected)

    assert (
        scope.resolve(
            "https://example.test/run.eval?credential=team/member&label=hello world"
        )
        == selected
    )


def test_scoped_authorization_canonicalizes_signed_query_values() -> None:
    selected = (
        "https://example.test/run.eval?credential=team%2Fmember&label=hello%20world"
    )
    request = _request(
        (VIEW_SCOPE_KIND_HEADER, "file"),
        (VIEW_SCOPE_HEADER, selected),
    )
    policy = fastapi_server.ScopedAuthorizationAccessPolicy()

    assert (
        asyncio.run(
            policy.resolve_read(
                request,
                "https://example.test/run.eval?"
                "credential=team/member&label=hello world",
            )
        )
        == selected
    )


def test_remote_directory_scopes_reject_queries() -> None:
    with pytest.raises(ValueError, match="cannot contain a query"):
        PathScope.parse("directory", "s3://bucket/logs?version=selected")

    scope = PathScope.parse("directory", "s3://bucket/logs")
    assert not scope.allows("s3://bucket/logs/run.eval?version=selected")


def test_file_uri_parsing_supports_windows_unc_paths() -> None:
    assert _local_path_from_file_uri(
        "file://server/share/logs/run.eval", windows=True
    ) == str(PureWindowsPath("//server/share/logs/run.eval"))
    assert (
        _local_path_from_file_uri("file://server/share/logs/run.eval", windows=False)
        is None
    )


def test_scoped_authorization_directory_policy() -> None:
    policy = fastapi_server.ScopedAuthorizationAccessPolicy()
    request = _request(
        (VIEW_SCOPE_KIND_HEADER, "directory"),
        (VIEW_SCOPE_HEADER, "s3://bucket/logs"),
    )

    assert asyncio.run(policy.can_list(request, "s3://bucket/logs"))
    assert asyncio.run(policy.can_read(request, "s3://bucket/logs/run.eval"))
    assert asyncio.run(policy.can_write(request, "s3://bucket/logs/run.eval"))
    assert not asyncio.run(policy.can_read(request, "s3://other/logs/run.eval"))


def test_scoped_authorization_file_policy() -> None:
    policy = fastapi_server.ScopedAuthorizationAccessPolicy()
    request = _request(
        (VIEW_SCOPE_KIND_HEADER, "file"),
        (VIEW_SCOPE_HEADER, "https://example.test/run.eval"),
    )

    assert asyncio.run(policy.can_read(request, "https://example.test/run.eval"))
    assert asyncio.run(policy.can_write(request, "https://example.test/run.eval"))
    assert not asyncio.run(policy.can_read(request, "https://example.test/other.eval"))
    assert not asyncio.run(policy.can_list(request, "https://example.test"))


def test_scoped_authorization_uses_resolved_remote_location() -> None:
    selected = "memory://bucket/logs/secret.eval"
    alias = "memory://bucket/logs//secret.eval"
    fs = filesystem(selected)
    fs.fs.pipe_file(fs.fs._strip_protocol(selected), b"selected")
    fs.fs.pipe_file(fs.fs._strip_protocol(alias), b"alias")

    app = fastapi_server.view_server_app(
        access_policy=fastapi_server.ScopedAuthorizationAccessPolicy()
    )
    headers = {
        VIEW_SCOPE_KIND_HEADER: "file",
        VIEW_SCOPE_HEADER: selected,
    }
    encoded_alias = urllib.parse.quote(alias, safe="")

    with TestClient(app) as client:
        response = client.get(
            f"/log-bytes/{encoded_alias}?start=0&end=7",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.content == b"selected"


def test_boolean_access_policy_still_uses_canonical_location() -> None:
    class AllowAccess(fastapi_server.AccessPolicy):
        async def can_read(self, request: Request, file: str) -> bool:
            return True

        async def can_delete(self, request: Request, file: str) -> bool:
            return True

        async def can_list(self, request: Request, dir: str) -> bool:
            return True

        async def can_write(self, request: Request, file: str) -> bool:
            return True

    selected = "memory://bucket/boolean/secret.eval"
    alias = "memory://bucket/boolean//secret.eval"
    fs = filesystem(selected)
    fs.fs.pipe_file(fs.fs._strip_protocol(selected), b"selected")
    fs.fs.pipe_file(fs.fs._strip_protocol(alias), b"alias")
    app = fastapi_server.view_server_app(access_policy=AllowAccess())
    encoded_alias = urllib.parse.quote(alias, safe="")

    with TestClient(app) as client:
        response = client.get(f"/log-bytes/{encoded_alias}?start=0&end=7")

    assert response.status_code == 200
    assert response.content == b"selected"


def test_scoped_authorization_uses_a_canonical_local_scope(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    selected = tmp_path / "selected"
    first.mkdir()
    second.mkdir()
    (second / "secret.eval").write_text("secret", encoding="utf-8")
    try:
        selected.symlink_to(first, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is not supported")

    request = _request(
        (VIEW_SCOPE_KIND_HEADER, "directory"),
        (VIEW_SCOPE_HEADER, first.resolve().as_uri()),
    )
    selected.unlink()
    selected.symlink_to(second, target_is_directory=True)

    policy = fastapi_server.ScopedAuthorizationAccessPolicy()
    assert not asyncio.run(policy.can_read(request, str(selected / "secret.eval")))


def test_canonical_local_scope_rejects_relative_and_symlink_paths(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    selected = tmp_path / "selected"
    target.mkdir()
    try:
        selected.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is not supported")

    with pytest.raises(ValueError, match="Invalid viewer path scope"):
        PathScope.parse_canonical("directory", "relative/logs")
    with pytest.raises(ValueError, match="Invalid viewer path scope"):
        PathScope.parse_canonical("directory", str(selected))


@pytest.mark.parametrize(
    "headers",
    [
        (),
        ((VIEW_SCOPE_KIND_HEADER, "directory"),),
        ((VIEW_SCOPE_HEADER, "/tmp/logs"),),
        (
            (VIEW_SCOPE_KIND_HEADER, "unknown"),
            (VIEW_SCOPE_HEADER, "/tmp/logs"),
        ),
        (
            (VIEW_SCOPE_KIND_HEADER, "directory"),
            (VIEW_SCOPE_HEADER, "/tmp/logs"),
            (VIEW_SCOPE_HEADER, "/tmp/other"),
        ),
    ],
)
def test_scoped_authorization_rejects_missing_or_conflicting_headers(
    headers: tuple[tuple[str, str], ...],
) -> None:
    policy = fastapi_server.ScopedAuthorizationAccessPolicy()
    assert not asyncio.run(policy.can_read(_request(*headers), "/tmp/logs/run.eval"))


@pytest.mark.parametrize(
    ("authorization", "scoped", "expected_type"),
    [
        (None, False, fastapi_server.OnlyDirAccessPolicy),
        ("secret", False, type(None)),
        ("secret", True, fastapi_server.ScopedAuthorizationAccessPolicy),
    ],
)
def test_view_server_selects_access_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
    scoped: bool,
    expected_type: type[Any],
) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    captured: list[fastapi_server.AccessPolicy | None] = []
    original = fastapi_server.view_server_app

    def capture(**kwargs: Any) -> Any:
        captured.append(kwargs.get("access_policy"))
        return original(**kwargs)

    monkeypatch.setattr(fastapi_server, "view_server_app", capture)
    monkeypatch.setattr(anyio, "run", lambda _func: None)

    fastapi_server.view_server(
        log_dir=str(log_dir),
        authorization=authorization,
        scoped_authorization=scoped,
    )

    assert len(captured) == 1
    assert isinstance(captured[0], expected_type)


def test_scoped_authorization_requires_authorization(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires request authorization"):
        fastapi_server.view_server(
            log_dir=str(tmp_path),
            scoped_authorization=True,
        )


def test_mounted_scout_routes_use_inspect_path_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = APIRouter()

    @router.get("/transcripts/{dir}/item")
    async def transcript_item(dir: str) -> dict[str, str]:
        return {"dir": dir}

    monkeypatch.setattr(fastapi_server, "get_scout_search_router", lambda: router)
    app = fastapi_server.view_server_app(
        access_policy=fastapi_server.ScopedAuthorizationAccessPolicy()
    )
    headers = {
        VIEW_SCOPE_KIND_HEADER: "directory",
        VIEW_SCOPE_HEADER: "s3://bucket/logs",
    }

    def encode(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    with TestClient(app) as client:
        allowed = client.get(
            f"/scout/transcripts/{encode('s3://bucket/logs')}/item",
            headers=headers,
        )
        canonicalized = client.get(
            f"/scout/transcripts/{encode('s3://bucket/logs//team')}/item",
            headers=headers,
        )
        rejected = client.get(
            f"/scout/transcripts/{encode('s3://other/logs')}/item",
            headers=headers,
        )

    assert allowed.status_code == 200
    assert canonicalized.status_code == 200
    assert canonicalized.json()["dir"] == encode("s3://bucket/logs/team")
    assert rejected.status_code == 403
