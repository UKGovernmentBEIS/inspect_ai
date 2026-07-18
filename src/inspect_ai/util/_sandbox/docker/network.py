"""Docker provider enforcement of the core NetworkAccess egress policy."""
# noqa: SIZE_OK — approved policy compiler keeps Docker-specific enforcement co-located.

from __future__ import annotations

import ipaddress
from pathlib import Path

import yaml

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._sandbox.compose import (
    ComposeBuild,
    ComposeConfig,
    ComposeHealthcheck,
    ComposeService,
    parse_compose_yaml,
)
from inspect_ai.util._sandbox.docker.config import auto_compose_dir, auto_compose_file
from inspect_ai.util._sandbox.network import (
    DomainPort,
    NetworkAccess,
    network_access_from_extensions,
)

EGRESS_GUARD_SERVICE = "egress-guard"

GUARD_CONF_DIR = "/etc/egress-guard"
NFTABLES_CONF = f"{GUARD_CONF_DIR}/nftables.conf"
DNSMASQ_CONF = f"{GUARD_CONF_DIR}/dnsmasq.conf"
SQUID_CONF = f"{GUARD_CONF_DIR}/squid.conf"

DEFAULT_DNS_UPSTREAM = ["1.1.1.1", "8.8.8.8"]

EGRESS_GUARD_DIR = Path(__file__).parent / "egress_guard"

_ALLOW_ALL_ENTITIES = {"all", "world"}
_FORBIDDEN_WORKLOAD_CAP_ADD = frozenset(
    {
        "ALL",
        "BPF",
        "CHECKPOINT_RESTORE",
        "MAC_ADMIN",
        "MAC_OVERRIDE",
        "NET_ADMIN",
        "NET_RAW",
        "PERFMON",
        "SYS_ADMIN",
        "SYS_BOOT",
        "SYS_MODULE",
        "SYS_PTRACE",
        "SYS_RAWIO",
        "SYSLOG",
    }
)
_GUARD_HEALTHCHECK_CMD = ["CMD", "/usr/local/bin/egress-guard-healthcheck"]
_EXTENSION_KEY = "x-inspect-network"


def _split_cidrs(cidrs: list[str]) -> tuple[list[str], list[str]]:
    """Partition CIDR strings into IPv4 and IPv6 values, validating each."""
    v4: list[str] = []
    v6: list[str] = []
    for cidr in cidrs:
        network = ipaddress.ip_network(cidr, strict=False)
        if network.version == 4:
            v4.append(str(network))
        else:
            v6.append(str(network))
    return v4, v6


def _domain_indices_for_port(na: NetworkAccess, dp: DomainPort) -> list[int]:
    """Return the allow_domains indexes opened by one DomainPort entry."""
    if dp.domain is None:
        return list(range(len(na.allow_domains)))
    try:
        return [na.allow_domains.index(dp.domain)]
    except ValueError as ex:
        raise ValueError(
            f"DomainPort domain {dp.domain!r} must appear in allow_domains"
        ) from ex


def _domain_entries_with_ports(na: NetworkAccess) -> list[tuple[int, str]]:
    """Return ordered domain-index pairs that need nft sets."""
    indices = {
        index
        for domain_port in na.allow_domains_ports
        for index in _domain_indices_for_port(na, domain_port)
    }
    return [
        (index, domain)
        for index, domain in enumerate(na.allow_domains)
        if index in indices
    ]


def render_nftables_conf(na: NetworkAccess) -> str:
    """Render the nftables default-deny ruleset for a NetworkAccess policy."""
    v4, v6 = _split_cidrs(na.allow_cidr)
    domain_port_entries = _domain_entries_with_ports(na)

    lines: list[str] = ["table inet egress {"]

    if v4:
        lines.extend(
            [
                "  set allowed_cidr4 {",
                "    type ipv4_addr",
                "    flags interval",
                "    elements = { " + ", ".join(v4) + " }",
                "  }",
            ]
        )
    if v6:
        lines.extend(
            [
                "  set allowed_cidr6 {",
                "    type ipv6_addr",
                "    flags interval",
                "    elements = { " + ", ".join(v6) + " }",
                "  }",
            ]
        )
    lines.append("  set allowed_domain_ips4 { type ipv4_addr; flags timeout; }")
    lines.append("  set allowed_domain_ips6 { type ipv6_addr; flags timeout; }")
    for index, _domain in domain_port_entries:
        lines.append(f"  set domain_ips4_{index} {{ type ipv4_addr; flags timeout; }}")
        lines.append(f"  set domain_ips6_{index} {{ type ipv6_addr; flags timeout; }}")

    lines.extend(
        [
            "  chain output {",
            "    type filter hook output priority filter; policy drop;",
            '    oif "lo" accept',
            "    ip daddr 127.0.0.0/8 accept",
            "    ip6 daddr ::1 accept",
            "    ct state established,related accept",
            '    socket cgroupv2 level 0 "/" accept',
        ]
    )
    if v4:
        lines.append("    ip daddr @allowed_cidr4 accept")
    if v6:
        lines.append("    ip6 daddr @allowed_cidr6 accept")
    for domain_port in na.allow_domains_ports:
        protocols = (
            ["tcp", "udp"]
            if domain_port.protocol.lower() == "any"
            else [domain_port.protocol.lower()]
        )
        for index in _domain_indices_for_port(na, domain_port):
            for protocol in protocols:
                lines.append(
                    f"    {protocol} dport {{ {domain_port.port} }} ip daddr @domain_ips4_{index} accept"
                )
                lines.append(
                    f"    {protocol} dport {{ {domain_port.port} }} ip6 daddr @domain_ips6_{index} accept"
                )
    lines.extend(
        [
            "    udp dport 443 drop",
            "  }",
            "  chain nat_output {",
            "    type nat hook output priority -100; policy accept;",
            # The guard cgroup's own traffic (dnsmasq's upstream forwarding queries,
            # squid's own egress) must be exempted BEFORE the DNS redirect below --
            # otherwise dnsmasq's own outgoing :53 query gets redirected back to its
            # own listener and loops forever.
            '    socket cgroupv2 level 0 "/" return',
            # DNS is then redirected UNCONDITIONALLY for everything else (even to
            # loopback destinations like Docker's embedded 127.0.0.11 resolver) so a
            # workload can never reach a real resolver and skip NXDOMAIN enforcement.
            "    udp dport 53 redirect to :53",
            "    tcp dport 53 redirect to :53",
            # Only the remaining (non-DNS) 80/443 redirect below honors the loopback
            # bypass, so a workload's own in-netns fake-domain HTTP service is reachable.
            "    fib daddr type local return",
        ]
    )
    if v4:
        lines.append("    ip daddr @allowed_cidr4 return")
    if v6:
        lines.append("    ip6 daddr @allowed_cidr6 return")
    lines.extend(
        [
            # Gated on the destination IP being one dnsmasq actually resolved for an
            # allow_domains entry -- an unconditional redirect would let a forged SNI
            # (443) or Host (80) to a non-allowlisted attacker IP still reach Squid's
            # identity check, since Squid authorizes by SNI/Host alone and splices
            # (never terminates) once that check passes. Gating here means a
            # non-allowlisted destination falls through to the filter chain's
            # default policy drop before Squid ever sees the connection. Squid's
            # own SNI/Host ACLs still apply for allowlisted IPs, defending the
            # shared-CDN-IP / different-allowlisted-vhost case.
            "    tcp dport 80 ip daddr @allowed_domain_ips4 redirect to :3128",
            "    tcp dport 80 ip6 daddr @allowed_domain_ips6 redirect to :3128",
            "    tcp dport 443 ip daddr @allowed_domain_ips4 redirect to :3129",
            "    tcp dport 443 ip6 daddr @allowed_domain_ips6 redirect to :3129",
            "  }",
            "}",
        ]
    )
    return "\n".join(lines) + "\n"


def _domain_suffix(domain: str) -> str:
    """Map an allow_domains value to its dnsmasq forwarding suffix."""
    return domain[2:] if domain.startswith("*.") else domain


def render_dnsmasq_conf(
    na: NetworkAccess, *, upstream: list[str] = DEFAULT_DNS_UPSTREAM
) -> str:
    """Render dnsmasq configuration with NXDOMAIN as its default response."""
    lines = [
        "no-resolv",
        "no-hosts",
        "bind-interfaces",
        "listen-address=127.0.0.1",
        "port=53",
    ]

    if "*" in na.allow_domains:
        for resolver in upstream:
            lines.append(f"server={resolver}")
        return "\n".join(lines) + "\n"

    for domain in na.allow_domains:
        for resolver in upstream:
            lines.append(f"server=/{domain}/{resolver}")
        # dnsmasq's nftset directive, unlike server=/address=, does not honor the
        # `*.` wildcard glob: it always suffix-matches on the literal domain string
        # given (empirically verified against dnsmasq 2.90 — nftset=/*.example.com/
        # never populates for any resolved subdomain). The set below is a shared,
        # not-per-domain, "redirect this IP to Squid" gate, so suffix-matching here
        # is safe: Squid's SNI/Host ACLs (not this set) enforce exact-vs-wildcard
        # domain identity.
        suffix = _domain_suffix(domain)
        lines.append(f"nftset=/{suffix}/4#inet#egress#allowed_domain_ips4")
        lines.append(f"nftset=/{suffix}/6#inet#egress#allowed_domain_ips6")
        if not domain.startswith("*.") and f"*.{domain}" not in na.allow_domains:
            # A wildcard sibling already governs this domain's subdomains; without
            # one, block them explicitly so an exact allowlist entry cannot be used
            # as a DNS-tunnel channel via <anything>.{domain}.
            lines.append(f"address=/*.{domain}/")

    for index, domain in _domain_entries_with_ports(na):
        suffix = _domain_suffix(domain)
        lines.append(f"nftset=/{suffix}/4#inet#egress#domain_ips4_{index}")
        lines.append(f"nftset=/{suffix}/6#inet#egress#domain_ips6_{index}")

    lines.append("address=/#/")
    return "\n".join(lines) + "\n"


SQUID_CERT_PATH = "/etc/squid/ssl_cert/guard.pem"


def _squid_sni_acl(index: int, domain: str) -> str:
    """Return a Squid SNI ACL line enforcing exact-vs-wildcard domain identity."""
    if domain.startswith("*."):
        # ssl::server_name only supports exact/leading-dot matching (leading-dot
        # INCLUDES the apex), so a subdomain-only wildcard needs a regex ACL that
        # requires at least one label before the suffix — mirrors _squid_host_pattern.
        suffix = _domain_suffix(domain).replace(".", r"\.")
        return (
            f"acl allowed_sni_{index} ssl::server_name_regex -i "
            rf"^([a-z0-9-]+\.)+{suffix}$"
        )
    return f"acl allowed_sni_{index} ssl::server_name {domain}"


def _squid_host_pattern(domain: str) -> str:
    """Return a case-insensitive HTTP Host-header matcher for one allowed domain."""
    escaped = _domain_suffix(domain).replace(".", r"\.")
    if domain.startswith("*."):
        return rf"^([a-z0-9-]+\.)+{escaped}(:[0-9]+)?$"
    return rf"^{escaped}(:[0-9]+)?$"


def render_squid_conf(na: NetworkAccess) -> str:
    """Render transparent HTTP Host and HTTPS SNI authorization planes."""
    lines = [
        "http_port 3128 intercept name=http_intercept",
        f"https_port 3129 intercept ssl-bump cert={SQUID_CERT_PATH} generate-host-certificates=off name=https_intercept",
        # Squid's getMyPort() skips intercept ports when building internal object URLs
        # (icons, error pages); without one non-intercept port it FATALs at startup.
        # Loopback-only and denied by the same default-deny rule as everything else below,
        # so it grants no forward-proxy bypass.
        "http_port 127.0.0.1:3130 name=internal_only",
        "cache_effective_user egress",
        "cache_effective_group egress",
        "cache deny all",
        "dns_nameservers 127.0.0.1",
        "host_verify_strict on",
        "acl http_intercept_port myportname http_intercept",
        "acl https_intercept_port myportname https_intercept",
        "acl CONNECT method CONNECT",
        "acl step1 at_step SslBump1",
    ]

    if "*" in na.allow_domains:
        lines.extend(
            [
                "ssl_bump peek step1",
                "ssl_bump splice all",
                "http_access allow all",
            ]
        )
        return "\n".join(lines) + "\n"

    for index, domain in enumerate(na.allow_domains):
        lines.append(_squid_sni_acl(index, domain))
    for index, domain in enumerate(na.allow_domains):
        lines.append(
            f"acl allowed_host_{index} req_header Host -i {_squid_host_pattern(domain)}"
        )

    for index in range(len(na.allow_domains)):
        lines.append(f"http_access allow http_intercept_port allowed_host_{index}")
    lines.append("http_access deny http_intercept_port")
    # The intercepted-HTTPS synthetic CONNECT is created before the TLS ClientHello
    # is read, so no SNI/Host ACL is available yet here. Allow it through and let
    # ssl_bump (which peeks the SNI next) splice or terminate on domain identity.
    lines.append("http_access allow CONNECT https_intercept_port")
    lines.append("ssl_bump peek step1")
    for index in range(len(na.allow_domains)):
        lines.append(f"ssl_bump splice allowed_sni_{index}")
    lines.extend(["ssl_bump terminate all", "http_access deny all"])
    return "\n".join(lines) + "\n"


def is_allow_all(na: NetworkAccess) -> bool:
    """Return whether a policy selects the documented unrestricted escape hatch."""
    return "*" in na.allow_domains or bool(
        {entity.lower() for entity in na.allow_entities} & _ALLOW_ALL_ENTITIES
    )


def unsupported_entities(na: NetworkAccess) -> list[str]:
    """Return Cilium entities that the Docker provider cannot enforce."""
    return [
        entity
        for entity in na.allow_entities
        if entity.lower() not in _ALLOW_ALL_ENTITIES
    ]


def unsupported_domain_ports(na: NetworkAccess) -> list[DomainPort]:
    """Return domain ports the Docker egress guard cannot enforce safely."""
    return [
        domain_port
        for domain_port in na.allow_domains_ports
        if domain_port.port not in (80, 443) or domain_port.protocol != "UDP"
    ]


def _suffixes_overlap(a: str, b: str) -> bool:
    """Whether two bare domain suffixes share a subtree (equal or one nested in the other)."""
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _shadowed_domain_ports(na: NetworkAccess) -> list[DomainPort]:
    """Return scoped domain ports whose per-port nft set another allow_domains entry can pollute.

    Per-port nft sets are populated by dnsmasq's bare-suffix `nftset=` (the `*.` glob is
    stripped there -- dnsmasq does not honor it for `nftset`). A scoped DomainPort is only
    enforceable when no other allow_domains entry shares its suffix subtree; otherwise a
    name that other entry resolves can land in the scoped set outside the port's intended
    scope. This covers both an exact domain with a `*.` wildcard sibling and a `*.` wildcard
    domain with its exact apex sibling.
    """
    return [
        domain_port
        for domain_port in na.allow_domains_ports
        if domain_port.domain is not None
        and any(
            entry != domain_port.domain
            and _suffixes_overlap(
                _domain_suffix(domain_port.domain), _domain_suffix(entry)
            )
            for entry in na.allow_domains
        )
    ]


def validate_docker_network_access(na: NetworkAccess) -> None:
    """Raise PrerequisiteError for any policy the Docker egress guard cannot enforce.

    Shared by the Docker provider (`apply_egress_guard`) and downstream callers (agent-c)
    so both reject the exact same policies.
    """
    entities = unsupported_entities(na)
    if entities:
        raise PrerequisiteError(
            "NetworkAccess.allow_entities "
            f"{entities!r} cannot be enforced by the docker provider "
            "(only 'all'/'world' are supported; use the k8s provider for Cilium "
            "entities, or remove them)."
        )
    domain_ports = unsupported_domain_ports(na)
    if domain_ports:
        raise PrerequisiteError(
            "NetworkAccess.allow_domains_ports "
            f"{domain_ports!r} cannot be enforced by the docker provider: Docker/Squid "
            "only supports UDP on ports 80/443. TCP/ANY on those ports would bypass "
            "SNI/Host identity checks, and other ports are IP-only. Use allow_cidr for "
            "an explicit IP-only trust model."
        )
    shadowed = _shadowed_domain_ports(na)
    if shadowed:
        domains = sorted({dp.domain for dp in shadowed if dp.domain is not None})
        raise PrerequisiteError(
            f"NetworkAccess.allow_domains_ports scopes a port to domain(s) {domains!r} "
            "whose suffix overlaps another allow_domains entry. The Docker guard's "
            "per-port nft set is populated by a bare-suffix match, so an overlapping "
            "entry would pollute the scoped set with IPs outside the port's scope. "
            "Use non-overlapping domains for scoped ports, or allow_cidr."
        )


def _guard_service(guard_context: str, mount_paths: dict[str, str]) -> ComposeService:
    """Create the netns-owning service with nftables and health-gate prerequisites."""
    return ComposeService(
        build=ComposeBuild(context=guard_context, dockerfile="Dockerfile"),
        init=True,
        cap_add=["NET_ADMIN"],
        healthcheck=ComposeHealthcheck(
            test=list(_GUARD_HEALTHCHECK_CMD),
            interval="2s",
            timeout="5s",
            retries=5,
            start_period="2s",
        ),
        volumes=[
            f"{mount_paths['nftables']}:{NFTABLES_CONF}:ro",
            f"{mount_paths['dnsmasq']}:{DNSMASQ_CONF}:ro",
            f"{mount_paths['squid']}:{SQUID_CONF}:ro",
        ],
    )


def _merge_cap_drop(existing: list[str] | None) -> list[str]:
    """Add every capability whose absence prevents a workload bypass."""
    capabilities = list(existing or [])
    for capability in ("NET_ADMIN", "NET_RAW"):
        if capability not in capabilities:
            capabilities.append(capability)
    return capabilities


def _merge_depends_on(
    existing: dict[str, object] | list[str] | None,
) -> dict[str, object]:
    """Preserve caller dependencies while adding the guard health gate."""
    if isinstance(existing, list):
        dependencies: dict[str, object] = {service: {} for service in existing}
    else:
        dependencies = dict(existing or {})
    dependencies[EGRESS_GUARD_SERVICE] = {"condition": "service_healthy"}
    return dependencies


def _forbidden_workload_cap_add(cap_add: list[str] | None) -> list[str]:
    """Return capability additions that can bypass netns egress enforcement."""
    return [
        capability
        for capability in cap_add or []
        if capability.upper().removeprefix("CAP_") in _FORBIDDEN_WORKLOAD_CAP_ADD
    ]


def apply_egress_guard(
    config: ComposeConfig,
    na: NetworkAccess,
    *,
    guard_context: str,
    mount_paths: dict[str, str],
) -> ComposeConfig:
    """Return a new ComposeConfig with a fail-closed shared-netns egress guard."""
    validate_docker_network_access(na)

    services: dict[str, ComposeService] = {}
    for name, service in config.services.items():
        if service.network_mode == "none":
            services[name] = service.model_copy(deep=True)
            continue
        if service.ports:
            raise PrerequisiteError(
                f"service '{name}' publishes ports {service.ports!r}, which is "
                "incompatible with the egress-guard (the workload has no network of "
                "its own). Remove the port mapping or the network policy."
            )
        if service.privileged:
            raise PrerequisiteError(
                f"service '{name}' is privileged, which would let it bypass the "
                "egress-guard. Remove 'privileged: true' or the network policy."
            )
        forbidden_cap_add = _forbidden_workload_cap_add(service.cap_add)
        if forbidden_cap_add:
            raise PrerequisiteError(
                f"service '{name}' requests forbidden cap_add {forbidden_cap_add!r}, which "
                "would let it bypass the egress-guard. Remove those capabilities or the "
                "network policy."
            )

        workload = service.model_copy(deep=True)
        workload.network_mode = f"service:{EGRESS_GUARD_SERVICE}"
        workload.depends_on = _merge_depends_on(workload.depends_on)
        workload.cap_drop = _merge_cap_drop(workload.cap_drop)
        workload.networks = None
        workload.hostname = None
        workload.extra_hosts = None
        workload.dns = None
        workload.dns_search = None
        services[name] = workload

    services[EGRESS_GUARD_SERVICE] = _guard_service(guard_context, mount_paths)
    return ComposeConfig(
        services=services,
        volumes=config.volumes,
        networks=config.networks,
    )


def write_guard_configs(na: NetworkAccess, project_name: str) -> dict[str, str]:
    """Render and persist the three egress-guard configuration files as UTF-8."""
    output_dir = auto_compose_dir()
    rendered = {
        "nftables": render_nftables_conf(na),
        "dnsmasq": render_dnsmasq_conf(na),
        "squid": render_squid_conf(na),
    }
    paths: dict[str, str] = {}
    for kind, content in rendered.items():
        path = output_dir / f"{project_name}-egress-{kind}.conf"
        path.write_text(content, encoding="utf-8")
        paths[kind] = path.resolve().as_posix()
    return paths


def _strip_extension(config: ComposeConfig) -> ComposeConfig:
    """Return a config copy that excludes the policy extension from emitted YAML."""
    if _EXTENSION_KEY not in config.extensions:
        return config
    data = config.model_dump(mode="json", by_alias=True, exclude_none=True)
    data.pop(_EXTENSION_KEY, None)
    return ComposeConfig.model_validate(data)


def compile_egress_guard(config: ComposeConfig, project_name: str) -> ComposeConfig:
    """Compile a NetworkAccess extension into native fail-closed Compose wiring."""
    network_access = network_access_from_extensions(config.extensions)
    if network_access is None or is_allow_all(network_access):
        return _strip_extension(config)

    stripped = _strip_extension(config)
    return apply_egress_guard(
        stripped,
        network_access,
        guard_context=EGRESS_GUARD_DIR.resolve().as_posix(),
        mount_paths=write_guard_configs(network_access, project_name),
    )


def compose_file_needs_guard(path: str) -> NetworkAccess | None:
    """Parse a raw Compose file only when it includes a network-policy extension."""
    if _EXTENSION_KEY not in Path(path).read_text(encoding="utf-8"):
        return None
    return network_access_from_extensions(parse_compose_yaml(path).extensions)


def compile_compose_file(path: str | Path, base_dir: str | Path) -> str:
    """Compile a guarded Compose file or preserve the original path when no guard is needed."""
    source = Path(path)
    if compose_file_needs_guard(source.as_posix()) is None:
        return source.as_posix()
    guarded = compile_egress_guard(parse_compose_yaml(source.as_posix()), source.stem)
    guarded_yaml = yaml.dump(
        guarded.model_dump(mode="json", by_alias=True, exclude_none=True),
        default_flow_style=False,
        sort_keys=False,
    )
    return auto_compose_file(
        guarded_yaml,
        source.stem,
        base_dir=Path(base_dir).as_posix(),
    )
