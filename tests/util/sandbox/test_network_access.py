import pytest
from pydantic import ValidationError

from inspect_ai.util._sandbox.compose import ComposeConfig
from inspect_ai.util._sandbox.network import (
    DomainPort,
    NetworkAccess,
    network_access_from_extensions,
)


def test_defaults_are_empty_deny_all():
    na = NetworkAccess()
    assert na.allow_domains == []
    assert na.allow_domains_ports == []
    assert na.allow_cidr == []
    assert na.allow_entities == []


def test_domain_port_defaults_protocol_any():
    dp = DomainPort(port=22)
    assert dp.protocol == "ANY"
    assert dp.domain is None


def test_scoped_domain_must_be_in_allow_domains():
    with pytest.raises(ValidationError, match="must also appear in allow_domains"):
        NetworkAccess(
            allow_domains=["example.com"],
            allow_domains_ports=[
                DomainPort(port=443, protocol="UDP", domain="github.com")
            ],
        )


@pytest.mark.parametrize(
    "domain_port",
    [
        pytest.param(
            DomainPort(port=8443, protocol="TCP", domain="example.com"),
            id="tcp-8443",
        ),
        pytest.param(DomainPort(port=80, protocol="TCP"), id="tcp-80"),
        pytest.param(DomainPort(port=443, protocol="ANY"), id="any-443"),
    ],
)
def test_model_allows_arbitrary_domain_ports_for_provider_compilers(
    domain_port: DomainPort,
):
    na = NetworkAccess(allow_domains=["example.com"], allow_domains_ports=[domain_port])
    assert na.allow_domains_ports == [domain_port]


def test_rejects_domains_ports_without_allow_domains():
    # The k8s template renders allowDomainsPorts only inside `if .Values.allowDomains`
    # (network-policy.yaml:48), so a port-only policy would be silently inert. Core
    # rejects it loudly instead.
    with pytest.raises(ValidationError, match="requires allow_domains"):
        NetworkAccess(allow_domains_ports=[DomainPort(port=22)])


def test_extension_absent_returns_none():
    cfg = ComposeConfig.model_validate(
        {"services": {"default": {"image": "ubuntu", "network_mode": "none"}}}
    )
    assert network_access_from_extensions(cfg.extensions) is None


def test_parses_x_inspect_network_extension():
    cfg = ComposeConfig.model_validate(
        {
            "services": {"default": {"image": "ubuntu"}},
            "x-inspect-network": {
                "allow_domains": ["pypi.org", "*.debian.org"],
                "allow_cidr": ["1.1.1.1/32"],
                "allow_domains_ports": [
                    {"port": 443, "protocol": "UDP", "domain": "pypi.org"}
                ],
                "allow_entities": ["world"],
            },
        }
    )
    na = network_access_from_extensions(cfg.extensions)
    assert na is not None
    assert na.allow_domains == ["pypi.org", "*.debian.org"]
    assert na.allow_cidr == ["1.1.1.1/32"]
    assert na.allow_domains_ports[0].port == 443
    assert na.allow_entities == ["world"]


def test_extension_explicit_null_raises():
    cfg = ComposeConfig.model_validate(
        {
            "services": {"default": {"image": "ubuntu"}},
            "x-inspect-network": None,
        }
    )
    with pytest.raises(ValueError, match="present but null"):
        network_access_from_extensions(cfg.extensions)


def test_public_import_surface():
    from inspect_ai.util import DomainPort as PublicDomainPort
    from inspect_ai.util import NetworkAccess as PublicNetworkAccess

    assert PublicNetworkAccess().allow_domains == []
    assert PublicDomainPort(port=22).protocol == "ANY"


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_domain_port_rejects_out_of_range_port(port: int):
    with pytest.raises(ValidationError):
        DomainPort(port=port)


@pytest.mark.parametrize("port", [1, 80, 443, 65535])
def test_domain_port_accepts_in_range_port(port: int):
    assert DomainPort(port=port).port == port


@pytest.mark.parametrize(
    "domain",
    [
        "example.com",
        "*.debian.org",
        "*",
        "oauth2.googleapis.com",
        "cloudcode-pa.googleapis.com",
    ],
)
def test_accepts_valid_domain_forms(domain: str):
    assert NetworkAccess(allow_domains=[domain]).allow_domains == [domain]


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "exa mple.com",
        "evil.com\nserver=/x/1.2.3.4",
        "bad/../path",
        "example.com/inject",
        "*.",
        "-bad.com",
        "under_score.com",
    ],
)
def test_rejects_malformed_domain(domain: str):
    with pytest.raises(ValidationError, match="not a valid domain"):
        NetworkAccess(allow_domains=[domain])


@pytest.mark.parametrize("cidr", ["203.0.113.0/24", "2001:db8::/32", "1.1.1.1/32"])
def test_accepts_valid_cidr(cidr: str):
    assert NetworkAccess(allow_cidr=[cidr]).allow_cidr == [cidr]


@pytest.mark.parametrize(
    "cidr", ["not-a-cidr", "999.0.0.0/8", "203.0.113.0/33", "example.com"]
)
def test_rejects_invalid_cidr(cidr: str):
    with pytest.raises(ValidationError, match="not a valid CIDR"):
        NetworkAccess(allow_cidr=[cidr])


@pytest.mark.parametrize("entity", ["world", "all", "kube-apiserver", "remote-node"])
def test_accepts_valid_entities(entity: str):
    assert NetworkAccess(allow_entities=[entity]).allow_entities == [entity]


@pytest.mark.parametrize(
    "entity", ["bad entity", "world\ninject", "ent!ty", "", "WORLD", "World"]
)
def test_rejects_malformed_entity(entity: str):
    with pytest.raises(ValidationError, match="not a valid entity"):
        NetworkAccess(allow_entities=[entity])
