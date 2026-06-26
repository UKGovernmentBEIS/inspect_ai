from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.requests import Request

from inspect_ai._view import fastapi_server
from inspect_ai._view.path_scope import (
    VIEW_SCOPE_HEADER,
    VIEW_SCOPE_KIND_HEADER,
    PathScope,
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
        rejected = client.get(
            f"/scout/transcripts/{encode('s3://other/logs')}/item",
            headers=headers,
        )

    assert allowed.status_code == 200
    assert rejected.status_code == 403
