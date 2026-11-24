import pytest

from inspect_ai._util.http_defaults import (
    CONNECT_RETRIES_ENV,
    CONNECT_TIMEOUT_ENV,
    KEEPALIVE_EXPIRY_ENV,
    POOL_CONNECTIONS_ENV,
    POOL_KEEPALIVE_CONNECTIONS_ENV,
    REQUEST_TIMEOUT_ENV,
)

HTTP_ENV_VARS = (
    CONNECT_TIMEOUT_ENV,
    REQUEST_TIMEOUT_ENV,
    POOL_CONNECTIONS_ENV,
    POOL_KEEPALIVE_CONNECTIONS_ENV,
    KEEPALIVE_EXPIRY_ENV,
    CONNECT_RETRIES_ENV,
)


@pytest.fixture(autouse=True)
def clean_http_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ambient HTTP settings out of every provider test in this tree.

    One exported variable is enough to fail an assertion about an SDK default.
    Proxy variables are left alone: `providers/test_openai_proxy.py` sets its
    own.
    """
    for var in HTTP_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
