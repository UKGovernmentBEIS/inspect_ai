"""Tests for get_url() port-to-URL scheme selection."""

from inspect_ai._display.textual.widgets.port_mappings import get_url


def test_http_ports_use_http_scheme() -> None:
    assert get_url(80, "HTTP") == "http://localhost:80"
    assert get_url(8080, "HTTP Alternate") == "http://localhost:8080"


def test_https_ports_use_https_scheme() -> None:
    assert get_url(443, "HTTPS") == "https://localhost:443"
    assert get_url(8443, "HTTPS Alternate") == "https://localhost:8443"


def test_novnc_uses_http_scheme() -> None:
    assert get_url(6080, "noVNC") == (
        "http://localhost:6080?view_only=true&autoconnect=true&resize=scale"
    )


def test_vnc_uses_vnc_scheme() -> None:
    assert get_url(5900, "VNC") == "vnc://localhost:5900"


def test_unknown_or_missing_service_returns_none() -> None:
    assert get_url(3306, "MySQL") is None
    assert get_url(80, None) is None
