import importlib
import inspect
from pathlib import Path

import pytest
from httpx import Response
from starlette.testclient import TestClient
from starlette.types import ASGIApp

from inspect_ai._view.fastapi_server import (
    VIEW_REQUEST_HEADER,
    VIEW_REQUEST_HEADER_VALUE,
    standalone_view_app,
    view_server,
)
from inspect_ai._view.network import (
    Authority,
    Origin,
    ViewerNetworkPolicy,
    ViewerNetworkPolicyError,
    resolve_viewer_network_policy,
    unsafe_network_warning,
)


def _policy(
    *,
    bind_host: str = "127.0.0.1",
    port: int = 7575,
    trusted_hosts: tuple[str, ...] = (),
    trusted_origins: tuple[str, ...] = (),
    authorization: str | None = None,
    unsafe_allow_unauthenticated: bool = False,
) -> ViewerNetworkPolicy:
    return resolve_viewer_network_policy(
        bind_host=bind_host,
        port=port,
        trusted_hosts=trusted_hosts,
        trusted_origins=trusted_origins,
        authorization=authorization,
        unsafe_allow_unauthenticated=unsafe_allow_unauthenticated,
    )


def _app(tmp_path: Path, policy: ViewerNetworkPolicy) -> tuple[ASGIApp, Path]:
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html>viewer</html>", encoding="utf-8")
    app = standalone_view_app(
        log_dir=str(log_dir),
        network_policy=policy,
        dist_dir=dist_dir,
    )
    return app, log_dir


def _assert_framing_headers(response: Response) -> None:
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"


def test_loopback_policy_defaults() -> None:
    policy = _policy()
    assert Authority("127.0.0.1", 7575) in policy.trusted_hosts
    assert Authority("localhost", 7575) in policy.trusted_hosts
    assert Origin("http", Authority("127.0.0.1", 7575)) in policy.trusted_origins
    assert Origin("http", Authority("localhost", 7575)) in policy.trusted_origins


def test_ipv6_loopback_policy_defaults() -> None:
    policy = _policy(bind_host="::1")
    assert Authority("::1", 7575) in policy.trusted_hosts
    assert Authority("localhost", 7575) in policy.trusted_hosts


def test_custom_loopback_dns_origin_adds_host_authority() -> None:
    policy = _policy(
        trusted_origins=("HTTP://My-Inspect.:7575/",),
    )
    authority = Authority("my-inspect", 7575)
    assert authority in policy.trusted_hosts
    assert Origin("http", authority) in policy.trusted_origins


def test_trusted_host_does_not_authorize_browser_origin() -> None:
    policy = _policy(trusted_hosts=("my-inspect:7575",))
    assert Authority("my-inspect", 7575) in policy.trusted_hosts
    assert Origin("http", Authority("my-inspect", 7575)) not in policy.trusted_origins


def test_default_origin_ports_are_canonicalized() -> None:
    policy = _policy(trusted_origins=("https://Inspect.Example:443",))
    origin = Origin("https", Authority("inspect.example"))
    assert origin in policy.trusted_origins
    assert origin.authority in policy.trusted_hosts


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "ftp://inspect.example",
        "http://user@inspect.example",
        "http://inspect.example/path",
        "http://inspect.example?query",
        "http://inspect.example#fragment",
        "http://*.inspect.example",
        "http://inspect_example",
        "http://inspect.example:",
        "http://inspect.example:0",
        "http://inspect.example:65536",
    ],
)
def test_invalid_trusted_origins_rejected(origin: str) -> None:
    with pytest.raises(ViewerNetworkPolicyError):
        _policy(trusted_origins=(origin,))


@pytest.mark.parametrize(
    "host",
    [
        "*.inspect.example",
        "inspect.example/path",
        "user@inspect.example",
        "inspect_example",
        "[::1",
        "::1",
        "inspect.example:0",
        "inspect.example:65536",
    ],
)
def test_invalid_trusted_hosts_rejected(host: str) -> None:
    with pytest.raises(ViewerNetworkPolicyError):
        _policy(trusted_hosts=(host,))


def test_concrete_non_loopback_bind_requires_authorization() -> None:
    with pytest.raises(ViewerNetworkPolicyError, match="without request authorization"):
        _policy(bind_host="192.0.2.10")

    policy = _policy(bind_host="192.0.2.10", authorization="secret")
    assert Authority("192.0.2.10", 7575) in policy.trusted_hosts
    assert Origin("http", Authority("192.0.2.10", 7575)) in policy.trusted_origins


def test_wildcard_bind_requires_explicit_trust_even_with_authorization() -> None:
    with pytest.raises(ViewerNetworkPolicyError, match="explicit trusted"):
        _policy(bind_host="0.0.0.0", authorization="secret")

    policy = _policy(
        bind_host="0.0.0.0",
        trusted_origins=("https://inspect.example",),
        authorization="secret",
    )
    assert Origin("https", Authority("inspect.example")) in policy.trusted_origins


def test_explicit_unsafe_non_loopback_policy_warns() -> None:
    policy = _policy(
        bind_host="0.0.0.0",
        trusted_origins=("http://192.0.2.10:7575",),
        unsafe_allow_unauthenticated=True,
    )
    warning = unsafe_network_warning(policy)
    assert warning is not None
    assert "0.0.0.0:7575" in warning
    assert "Any network client" in warning


def test_unsafe_flag_does_not_warn_when_authorization_is_configured() -> None:
    policy = _policy(
        bind_host="0.0.0.0",
        trusted_origins=("https://inspect.example",),
        authorization="secret",
        unsafe_allow_unauthenticated=True,
    )
    assert unsafe_network_warning(policy) is None


def test_attacker_selected_host_rejected_for_document_and_api(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, _policy())
    with TestClient(app, base_url="http://localhost:7575") as client:
        document = client.get("/", headers={"Host": "rebind.test:7575"})
        api = client.get(
            "/api/app-config",
            headers={
                "Host": "rebind.test:7575",
                "Origin": "http://rebind.test:7575",
                "Sec-Fetch-Site": "same-origin",
            },
        )

    assert document.status_code == 400
    assert api.status_code == 400
    _assert_framing_headers(document)
    _assert_framing_headers(api)


def test_trusted_host_only_rejects_browser_fetch_but_allows_non_browser(
    tmp_path: Path,
) -> None:
    app, _ = _app(
        tmp_path,
        _policy(trusted_hosts=("health.internal:7575",)),
    )
    with TestClient(app, base_url="http://health.internal:7575") as client:
        browser = client.get(
            "/api/app-config",
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        non_browser = client.get("/api/app-config")

    assert browser.status_code == 403
    assert non_browser.status_code == 200


def test_duplicate_host_headers_are_rejected(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, _policy())
    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.get(
            "/",
            headers=[
                ("Host", "localhost:7575"),
                ("Host", "rebind.test:7575"),
            ],
        )

    assert response.status_code == 400


def test_matching_loopback_host_and_origin_can_read_api(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, _policy())
    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.get(
            "/api/app-config",
            headers={
                "Origin": "http://localhost:7575",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        without_origin = client.get(
            "/api/app-config",
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 200
    assert without_origin.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    _assert_framing_headers(response)


def test_custom_loopback_dns_origin_is_configurable(tmp_path: Path) -> None:
    trusted_app, _ = _app(
        tmp_path / "trusted",
        _policy(trusted_origins=("http://my-inspect:7575",)),
    )
    with TestClient(trusted_app, base_url="http://my-inspect:7575") as client:
        trusted = client.get(
            "/api/app-config",
            headers={"Origin": "http://my-inspect:7575"},
        )

    untrusted_app, _ = _app(tmp_path / "untrusted", _policy())
    with TestClient(untrusted_app, base_url="http://my-inspect:7575") as client:
        untrusted = client.get(
            "/api/app-config",
            headers={"Origin": "http://my-inspect:7575"},
        )

    assert trusted.status_code == 200
    assert untrusted.status_code == 400


def test_untrusted_or_mismatched_browser_origin_rejected(tmp_path: Path) -> None:
    app, _ = _app(
        tmp_path,
        _policy(
            trusted_origins=(
                "http://my-inspect:7575",
                "http://other-inspect:7575",
            )
        ),
    )
    with TestClient(app, base_url="http://my-inspect:7575") as client:
        attacker = client.get(
            "/api/app-config",
            headers={"Origin": "https://attacker.example"},
        )
        other_trusted_host = client.get(
            "/api/app-config",
            headers={"Origin": "http://other-inspect:7575"},
        )

    assert attacker.status_code == 403
    assert other_trusted_host.status_code == 403
    _assert_framing_headers(attacker)


def test_origin_scheme_must_match_request_scheme(tmp_path: Path) -> None:
    app, _ = _app(
        tmp_path,
        _policy(trusted_origins=("https://inspect.example",)),
    )
    with TestClient(app, base_url="http://inspect.example") as client:
        response = client.get(
            "/api/app-config",
            headers={"Origin": "https://inspect.example"},
        )

    assert response.status_code == 403


def test_cross_site_fetch_metadata_rejected_without_origin(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, _policy())
    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.get(
            "/api/app-config",
            headers={"Sec-Fetch-Site": "cross-site"},
        )

    assert response.status_code == 403


def test_same_site_fetch_metadata_rejected_with_trusted_origin(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, _policy())
    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.get(
            "/api/app-config",
            headers={
                "Origin": "http://localhost:7575",
                "Sec-Fetch-Site": "same-site",
            },
        )

    assert response.status_code == 403


def test_null_and_duplicate_origins_are_rejected(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, _policy())
    with TestClient(app, base_url="http://localhost:7575") as client:
        null_origin = client.get(
            "/api/app-config",
            headers={"Origin": "null"},
        )
        duplicate_origin = client.get(
            "/api/app-config",
            headers=[
                ("Origin", "http://localhost:7575"),
                ("Origin", "https://attacker.example"),
            ],
        )

    assert null_origin.status_code == 403
    assert duplicate_origin.status_code == 403


def test_authorized_non_browser_request_without_origin_succeeds(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, _policy(authorization="secret"))
    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.get(
            "/api/app-config",
            headers={"Authorization": "secret"},
        )
        unauthorized = client.get("/api/app-config")

    assert response.status_code == 200
    assert unauthorized.status_code == 401
    _assert_framing_headers(unauthorized)


def test_authorization_does_not_bypass_origin_validation(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, _policy(authorization="secret"))
    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.get(
            "/api/app-config",
            headers={
                "Authorization": "secret",
                "Origin": "https://attacker.example",
            },
        )

    assert response.status_code == 403


def test_authenticated_reverse_proxy_origin_succeeds(tmp_path: Path) -> None:
    policy = _policy(
        bind_host="0.0.0.0",
        trusted_origins=("https://inspect.example",),
        authorization="secret",
    )
    app, _ = _app(tmp_path, policy)
    with TestClient(app, base_url="https://inspect.example") as client:
        response = client.get(
            "/api/app-config",
            headers={
                "Authorization": "secret",
                "Origin": "https://inspect.example",
                "Sec-Fetch-Site": "same-origin",
            },
        )

    assert response.status_code == 200


def test_untrusted_origin_cannot_delete_with_public_frontend_headers(
    tmp_path: Path,
) -> None:
    app, log_dir = _app(tmp_path, _policy())
    fixture = log_dir / "fixture.eval"
    fixture.write_bytes(b"fixture")

    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.delete(
            f"/api/log-delete/{fixture}",
            headers={
                "Origin": "https://attacker.example",
                VIEW_REQUEST_HEADER: VIEW_REQUEST_HEADER_VALUE,
                "Sec-Fetch-Dest": "empty",
            },
        )

    assert response.status_code == 403
    assert fixture.exists()


def test_local_origin_switch_cannot_delete(tmp_path: Path) -> None:
    app, log_dir = _app(tmp_path, _policy())
    fixture = log_dir / "fixture.eval"
    fixture.write_bytes(b"fixture")

    with TestClient(app, base_url="http://localhost:7575") as client:
        response = client.delete(
            f"/api/log-delete/{fixture}",
            headers={
                "Host": "rebind.test:7575",
                "Origin": "http://rebind.test:7575",
                "Sec-Fetch-Site": "same-origin",
                VIEW_REQUEST_HEADER: VIEW_REQUEST_HEADER_VALUE,
                "Sec-Fetch-Dest": "empty",
            },
        )

    assert response.status_code == 400
    assert fixture.exists()


def test_framing_headers_cover_static_and_error_responses(
    tmp_path: Path,
) -> None:
    app, _ = _app(tmp_path, _policy())
    with TestClient(app, base_url="http://localhost:7575") as client:
        root = client.get("/")
        missing = client.get("/missing")
        forbidden = client.get(
            "/api/app-config",
            headers={"Origin": "https://attacker.example"},
        )

    assert root.status_code == 200
    assert missing.status_code == 404
    assert forbidden.status_code == 403
    _assert_framing_headers(root)
    _assert_framing_headers(missing)
    _assert_framing_headers(forbidden)


def test_unsafe_bind_is_rejected_before_port_acquisition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view_module = importlib.import_module("inspect_ai._view.view")
    acquired = False

    def acquire_port(_app_dir: Path, _port: int) -> None:
        nonlocal acquired
        acquired = True

    monkeypatch.setattr(view_module, "init_dotenv", lambda: None)
    monkeypatch.setattr(view_module, "init_logger", lambda _level: None)
    monkeypatch.setattr(view_module, "view_acquire_port", acquire_port)

    with pytest.raises(ViewerNetworkPolicyError):
        view_module.view(
            log_dir=str(tmp_path),
            host="0.0.0.0",
            trusted_origins=("http://192.0.2.10:7575",),
        )

    assert acquired is False


def test_existing_view_positional_parameter_order_is_preserved() -> None:
    view_module = importlib.import_module("inspect_ai._view.view")
    assert list(inspect.signature(view_module.view).parameters)[:7] == [
        "log_dir",
        "recursive",
        "host",
        "port",
        "authorization",
        "log_level",
        "fs_options",
    ]
    assert list(inspect.signature(view_server).parameters)[:7] == [
        "log_dir",
        "recursive",
        "host",
        "port",
        "authorization",
        "fs_options",
        "generate_direct_urls",
    ]
