"""Pure-Python rendering of the egress-guard configuration files."""

from inspect_ai.util._sandbox.docker.network import (
    SQUID_CERT_PATH,
    render_dnsmasq_conf,
    render_nftables_conf,
    render_squid_conf,
)
from inspect_ai.util._sandbox.network import DomainPort, NetworkAccess


def test_nft_default_deny_uses_guard_cgroup_and_transparent_redirects() -> None:
    # Given no approved external destinations.
    # When rendering the nftables program.
    # Then the guard cgroup is the only bypass and TCP 80/443 are intercepted.
    rendered = render_nftables_conf(NetworkAccess())

    assert "type filter hook output priority filter; policy drop;" in rendered
    assert 'socket cgroupv2 level 0 "/" accept' in rendered
    assert "meta skuid" not in rendered
    assert "udp dport 443 drop" in rendered
    assert "type nat hook output priority -100; policy accept;" in rendered
    assert "fib daddr type local return" in rendered
    assert 'socket cgroupv2 level 0 "/" return' in rendered
    assert "udp dport 53 redirect to :53" in rendered
    assert "tcp dport 53 redirect to :53" in rendered
    assert "tcp dport 80 ip daddr @allowed_domain_ips4 redirect to :3128" in rendered
    assert "tcp dport 443 ip daddr @allowed_domain_ips4 redirect to :3129" in rendered


def test_nft_dns_redirect_ordering_avoids_resolver_leak_and_self_loop() -> None:
    # The guard's own cgroup (dnsmasq's upstream forwarding queries) must be exempted
    # BEFORE the DNS redirect, or dnsmasq's own outgoing :53 query gets redirected back
    # to its own listener and loops forever. Docker's embedded resolver (127.0.0.11) is
    # a loopback address; if the fib-local bypass were checked before the DNS redirect,
    # DNS queries to it would skip our dnsmasq and reach a real resolver, defeating
    # NXDOMAIN enforcement. So DNS redirect must be sandwiched: after cgroup-return,
    # before fib-local-return.
    rendered = render_nftables_conf(NetworkAccess())

    assert rendered.index('socket cgroupv2 level 0 "/" return') < rendered.index(
        "udp dport 53 redirect to :53"
    )
    assert rendered.index("udp dport 53 redirect to :53") < rendered.index(
        "fib daddr type local return"
    )
    assert rendered.index("tcp dport 53 redirect to :53") < rendered.index(
        "fib daddr type local return"
    )


def test_nft_allow_cidr_bypasses_transparent_redirect() -> None:
    rendered = render_nftables_conf(
        NetworkAccess(allow_cidr=["203.0.113.0/24", "2001:db8::/32"])
    )

    assert "elements = { 203.0.113.0/24 }" in rendered
    assert "elements = { 2001:db8::/32 }" in rendered
    assert "ip daddr @allowed_cidr4 accept" in rendered
    assert "ip6 daddr @allowed_cidr6 accept" in rendered
    assert "ip daddr @allowed_cidr4 return" in rendered
    assert "ip6 daddr @allowed_cidr6 return" in rendered


def test_nft_transparent_redirect_gated_by_allowlisted_domain_ip_sets() -> None:
    # Given an allowlisted domain.
    # When rendering the nftables program.
    # Then the 80/443 redirects only fire for destinations DNS-resolved for an
    # allowlisted domain -- an unconditional redirect would let a forged SNI to an
    # arbitrary attacker IP reach Squid's SNI-only identity check (the attacker IP
    # would never be in the allowlisted-domain set, so it must never even reach
    # Squid; it must fall through to the filter chain's default policy drop).
    rendered = render_nftables_conf(NetworkAccess(allow_domains=["example.com"]))

    assert "set allowed_domain_ips4 { type ipv4_addr; flags timeout; }" in rendered
    assert "set allowed_domain_ips6 { type ipv6_addr; flags timeout; }" in rendered
    assert "tcp dport 80 ip daddr @allowed_domain_ips4 redirect to :3128" in rendered
    assert "tcp dport 80 ip6 daddr @allowed_domain_ips6 redirect to :3128" in rendered
    assert "tcp dport 443 ip daddr @allowed_domain_ips4 redirect to :3129" in rendered
    assert "tcp dport 443 ip6 daddr @allowed_domain_ips6 redirect to :3129" in rendered
    # The old unconditional (unmatched-on-destination) redirect form must be gone.
    assert "tcp dport 80 redirect to :3128" not in rendered
    assert "tcp dport 443 redirect to :3129" not in rendered


def test_nft_domain_port_uses_dns_populated_sets() -> None:
    rendered = render_nftables_conf(
        NetworkAccess(
            allow_domains=["example.com", "example.org"],
            allow_domains_ports=[DomainPort(port=443, protocol="UDP")],
        )
    )

    for index in (0, 1):
        assert (
            f"set domain_ips4_{index} {{ type ipv4_addr; flags timeout; }}" in rendered
        )
        assert (
            f"set domain_ips6_{index} {{ type ipv6_addr; flags timeout; }}" in rendered
        )
        assert f"udp dport {{ 443 }} ip daddr @domain_ips4_{index} accept" in rendered


def test_nft_omits_per_port_domain_sets_without_extra_domain_ports() -> None:
    # The per-index domain_ips4_N/domain_ips6_N sets exist only to serve
    # allow_domains_ports (e.g. UDP/443 QUIC); the aggregate allowed_domain_ips4/6
    # sets that gate the transparent redirect are unrelated and always present.
    rendered = render_nftables_conf(NetworkAccess(allow_domains=["example.com"]))

    assert "domain_ips4_0" not in rendered
    assert "domain_ips6_0" not in rendered
    assert "allowed_domain_ips4" in rendered
    assert "allowed_domain_ips6" in rendered


def test_dnsmasq_default_deny_returns_nxdomain() -> None:
    rendered = render_dnsmasq_conf(NetworkAccess())

    assert "listen-address=127.0.0.1" in rendered
    assert "address=/#/" in rendered


def test_dnsmasq_forwards_only_allowed_domain_suffixes() -> None:
    rendered = render_dnsmasq_conf(
        NetworkAccess(
            allow_domains=["example.com", "*.debian.org"],
            allow_domains_ports=[DomainPort(port=443, protocol="UDP")],
        ),
        upstream=["1.1.1.1"],
    )

    assert "server=/example.com/1.1.1.1" in rendered
    assert "server=/*.debian.org/1.1.1.1" in rendered
    assert "address=/*.example.com/" in rendered
    assert "server=/*.example.com/1.1.1.1" not in rendered
    assert "server=/debian.org/1.1.1.1" not in rendered
    assert "nftset=/example.com/4#inet#egress#domain_ips4_0" in rendered
    assert "nftset=/debian.org/6#inet#egress#domain_ips6_1" in rendered


def test_dnsmasq_suppresses_exact_subdomain_blocker_when_wildcard_is_allowed() -> None:
    rendered = render_dnsmasq_conf(
        NetworkAccess(allow_domains=["example.com", "*.example.com"]),
        upstream=["1.1.1.1"],
    )

    assert "server=/example.com/1.1.1.1" in rendered
    assert "server=/*.example.com/1.1.1.1" in rendered
    assert "address=/*.example.com/" not in rendered


def test_dnsmasq_allow_all_forwards_everything() -> None:
    rendered = render_dnsmasq_conf(
        NetworkAccess(allow_domains=["*"]), upstream=["9.9.9.9"]
    )

    assert "server=9.9.9.9" in rendered
    assert "address=/#/" not in rendered


def test_squid_default_deny_uses_separate_transparent_listeners() -> None:
    rendered = render_squid_conf(NetworkAccess())

    assert "http_port 3128 intercept name=http_intercept" in rendered
    assert (
        f"https_port 3129 intercept ssl-bump cert={SQUID_CERT_PATH} "
        "generate-host-certificates=off"
    ) in rendered
    assert "host_verify_strict on" in rendered
    assert "http_access deny all" in rendered
    assert "ssl_bump terminate all" in rendered


def test_squid_domain_identity_uses_host_and_sni_acl_planes() -> None:
    rendered = render_squid_conf(
        NetworkAccess(allow_domains=["pypi.org", "*.debian.org"])
    )

    assert "acl allowed_sni_0 ssl::server_name pypi.org" in rendered
    assert (
        "acl allowed_sni_1 ssl::server_name_regex -i "
        r"^([a-z0-9-]+\.)+debian\.org$"
    ) in rendered
    assert "acl allowed_sni_1 ssl::server_name .debian.org" not in rendered
    assert "acl allowed_host_0 req_header Host -i ^pypi\\.org(:[0-9]+)?$" in rendered
    assert (
        "acl allowed_host_1 req_header Host -i ^([a-z0-9-]+\\.)+debian\\.org(:[0-9]+)?$"
        in rendered
    )
    assert "http_access allow http_intercept_port allowed_host_0" in rendered
    assert "ssl_bump splice allowed_sni_0" in rendered
    assert "ssl_bump splice allowed_sni_1" in rendered
    assert "dstdomain" not in rendered


def test_squid_domain_port_policy_stays_out_of_transparent_proxy() -> None:
    rendered = render_squid_conf(
        NetworkAccess(
            allow_domains=["example.com"],
            allow_domains_ports=[
                DomainPort(port=443, protocol="UDP", domain="example.com")
            ],
        )
    )

    assert "domain_port" not in rendered
    assert "acl CONNECT method CONNECT" in rendered


def test_squid_allow_all_bypasses_identity_acl() -> None:
    rendered = render_squid_conf(NetworkAccess(allow_domains=["*"]))

    assert "ssl_bump splice all" in rendered
    assert "http_access allow all" in rendered
    assert "allowed_sni" not in rendered
    assert "allowed_host" not in rendered
