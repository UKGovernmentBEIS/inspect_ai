"""apply_egress_guard transform and compile hook tests without Docker."""

import os
from pathlib import Path

import pytest
import yaml

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._sandbox.compose import ComposeConfig, ComposeService
from inspect_ai.util._sandbox.docker.network import (
    EGRESS_GUARD_SERVICE,
    apply_egress_guard,
    compile_compose_file,
    compile_egress_guard,
    is_allow_all,
    unsupported_entities,
)
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._sandbox.network import DomainPort, NetworkAccess

MOUNTS = {
    "nftables": "/host/nftables.conf",
    "dnsmasq": "/host/dnsmasq.conf",
    "squid": "/host/squid.conf",
}


def _cfg(**service_kwargs) -> ComposeConfig:
    return ComposeConfig(
        services={"default": ComposeService(image="ubuntu", **service_kwargs)}
    )


def test_is_allow_all():
    assert is_allow_all(NetworkAccess(allow_domains=["*"]))
    assert is_allow_all(NetworkAccess(allow_entities=["world"]))
    assert is_allow_all(NetworkAccess(allow_entities=["all"]))
    assert not is_allow_all(NetworkAccess(allow_domains=["a.com"]))
    assert not is_allow_all(NetworkAccess())


def test_unsupported_entities_fail_loud():
    network_access = NetworkAccess(allow_entities=["cluster", "world"])
    assert unsupported_entities(network_access) == ["cluster"]
    with pytest.raises(PrerequisiteError, match="cluster"):
        apply_egress_guard(
            _cfg(), network_access, guard_context="/g", mount_paths=MOUNTS
        )


@pytest.mark.parametrize(
    "domain_port",
    [
        pytest.param(DomainPort(port=8443, protocol="TCP"), id="tcp-8443"),
        pytest.param(DomainPort(port=80, protocol="TCP"), id="tcp-80"),
        pytest.param(DomainPort(port=443, protocol="ANY"), id="any-443"),
    ],
)
def test_unsupported_domain_ports_fail_loud_in_docker_provider(
    domain_port: DomainPort,
):
    network_access = NetworkAccess(
        allow_domains=["example.com"], allow_domains_ports=[domain_port]
    )
    with pytest.raises(PrerequisiteError, match=r"docker provider.*allow_cidr"):
        apply_egress_guard(
            _cfg(), network_access, guard_context="/g", mount_paths=MOUNTS
        )


def test_exact_domain_port_with_wildcard_sibling_fails_loud() -> None:
    network_access = NetworkAccess(
        allow_domains=["example.com", "*.example.com"],
        allow_domains_ports=[
            DomainPort(port=443, protocol="UDP", domain="example.com")
        ],
    )

    with pytest.raises(PrerequisiteError, match=r"example\.com.*overlaps"):
        apply_egress_guard(
            _cfg(), network_access, guard_context="/g", mount_paths=MOUNTS
        )


def test_wildcard_domain_port_with_exact_sibling_fails_loud() -> None:
    network_access = NetworkAccess(
        allow_domains=["example.com", "*.example.com"],
        allow_domains_ports=[
            DomainPort(port=443, protocol="UDP", domain="*.example.com")
        ],
    )

    with pytest.raises(PrerequisiteError, match=r"example\.com.*overlaps"):
        apply_egress_guard(
            _cfg(), network_access, guard_context="/g", mount_paths=MOUNTS
        )


def test_guard_service_added():
    out = apply_egress_guard(
        _cfg(network_mode="none"),
        NetworkAccess(allow_domains=["a.com"]),
        guard_context="/pkg/egress_guard",
        mount_paths=MOUNTS,
    )
    guard = out.services[EGRESS_GUARD_SERVICE]
    assert guard.build is not None and guard.build.context == "/pkg/egress_guard"
    assert guard.cap_add == ["NET_ADMIN"]
    assert guard.init is True
    assert guard.healthcheck is not None
    assert guard.healthcheck.test == ["CMD", "/usr/local/bin/egress-guard-healthcheck"]
    assert "/host/nftables.conf:/etc/egress-guard/nftables.conf:ro" in guard.volumes
    assert "/host/dnsmasq.conf:/etc/egress-guard/dnsmasq.conf:ro" in guard.volumes
    assert "/host/squid.conf:/etc/egress-guard/squid.conf:ro" in guard.volumes


def test_workload_rewired_and_health_gated():
    out = apply_egress_guard(
        _cfg(),
        NetworkAccess(allow_domains=["a.com"]),
        guard_context="/g",
        mount_paths=MOUNTS,
    )
    workload = out.services["default"]
    assert workload.network_mode == f"service:{EGRESS_GUARD_SERVICE}"
    assert workload.depends_on == {
        EGRESS_GUARD_SERVICE: {"condition": "service_healthy"}
    }
    assert {"NET_ADMIN", "NET_RAW"} <= set(workload.cap_drop)
    assert "SETUID" not in workload.cap_drop
    assert "SETGID" not in workload.cap_drop
    assert workload.environment is None
    assert workload.networks is None


def test_network_mode_none_service_stays_isolated():
    config = ComposeConfig(
        services={
            "isolated": ComposeService(image="ubuntu", network_mode="none"),
            "app": ComposeService(image="ubuntu"),
        }
    )
    out = apply_egress_guard(
        config,
        NetworkAccess(allow_domains=["a.com"]),
        guard_context="/g",
        mount_paths=MOUNTS,
    )
    assert out.services["isolated"].network_mode == "none"
    assert out.services["app"].network_mode == f"service:{EGRESS_GUARD_SERVICE}"


def test_published_ports_fail_loud():
    with pytest.raises(PrerequisiteError, match="ports"):
        apply_egress_guard(
            _cfg(ports=["8080:80"]),
            NetworkAccess(allow_domains=["a.com"]),
            guard_context="/g",
            mount_paths=MOUNTS,
        )


def test_privileged_workload_fail_loud():
    with pytest.raises(PrerequisiteError, match="privileged"):
        apply_egress_guard(
            _cfg(privileged=True),
            NetworkAccess(allow_domains=["a.com"]),
            guard_context="/g",
            mount_paths=MOUNTS,
        )


@pytest.mark.parametrize("user", ["root", "0", 0, "4242"])
def test_root_and_egress_uid_workloads_retain_their_service_identity(user):
    out = apply_egress_guard(
        _cfg(user=user),
        NetworkAccess(allow_domains=["a.com"]),
        guard_context="/g",
        mount_paths=MOUNTS,
    )

    assert out.services["default"].user == user


@pytest.mark.parametrize("capability", ["NET_ADMIN", "CAP_NET_RAW", "SYS_ADMIN", "ALL"])
def test_dangerous_workload_cap_add_fails_loud(capability):
    with pytest.raises(PrerequisiteError, match="cap_add"):
        apply_egress_guard(
            _cfg(cap_add=[capability]),
            NetworkAccess(allow_domains=["a.com"]),
            guard_context="/g",
            mount_paths=MOUNTS,
        )


def test_setuid_and_setgid_cap_add_are_retained_for_service_supervision():
    out = apply_egress_guard(
        _cfg(cap_add=["SETUID", "SETGID"]),
        NetworkAccess(allow_domains=["a.com"]),
        guard_context="/g",
        mount_paths=MOUNTS,
    )

    assert out.services["default"].cap_add == ["SETUID", "SETGID"]


def test_workload_dns_and_dependencies_are_merged_without_proxy_environment():
    out = apply_egress_guard(
        _cfg(
            dns=["9.9.9.9"],
            dns_search=["corp.invalid"],
            depends_on={"database": {"condition": "service_started"}},
            environment={"KEEP": "yes", "NO_PROXY": "caller.invalid"},
        ),
        NetworkAccess(allow_domains=["a.com"], allow_cidr=["203.0.113.0/24"]),
        guard_context="/g",
        mount_paths=MOUNTS,
    )
    workload = out.services["default"]
    assert workload.dns is None and workload.dns_search is None
    assert workload.depends_on == {
        "database": {"condition": "service_started"},
        EGRESS_GUARD_SERVICE: {"condition": "service_healthy"},
    }
    assert workload.environment == {"KEEP": "yes", "NO_PROXY": "caller.invalid"}


def test_list_form_environment_is_preserved_without_proxy_injection():
    out = apply_egress_guard(
        _cfg(environment=["KEEP=yes"]),
        NetworkAccess(allow_domains=["a.com"]),
        guard_context="/g",
        mount_paths=MOUNTS,
    )

    assert out.services["default"].environment == ["KEEP=yes"]


def test_compile_no_extension_is_noop():
    config = ComposeConfig(services={"default": ComposeService(image="ubuntu")})
    out = compile_egress_guard(config, "project-no-extension")
    assert EGRESS_GUARD_SERVICE not in out.services


def test_compile_allow_all_strips_extension_and_adds_no_guard():
    config = ComposeConfig.model_validate(
        {
            "services": {"default": {"image": "ubuntu"}},
            "x-inspect-network": {"allow_domains": ["*"]},
        }
    )
    out = compile_egress_guard(config, "project-allow-all")
    assert EGRESS_GUARD_SERVICE not in out.services
    assert "x-inspect-network" not in out.extensions


def test_compile_builds_guard_and_writes_configs():
    config = ComposeConfig.model_validate(
        {
            "services": {"default": {"image": "ubuntu"}},
            "x-inspect-network": {
                "allow_domains": ["example.com"],
                "allow_cidr": ["1.1.1.1/32"],
            },
        }
    )
    out = compile_egress_guard(config, "project-guard")
    try:
        assert EGRESS_GUARD_SERVICE in out.services
        assert out.services["default"].network_mode == f"service:{EGRESS_GUARD_SERVICE}"
        assert "x-inspect-network" not in out.extensions
        volumes = out.services[EGRESS_GUARD_SERVICE].volumes
        for kind in ("nftables", "dnsmasq", "squid"):
            host = next(
                volume.split(":")[0] for volume in volumes if f"egress-{kind}" in volume
            )
            assert os.path.exists(host)
            content = Path(host).read_text(encoding="utf-8")
            if kind == "nftables":
                assert "policy drop" in content and "1.1.1.1/32" in content
            elif kind == "dnsmasq":
                assert "server=/example.com/" in content and "address=/#/" in content
            else:
                assert "ssl_bump peek step1" in content
    finally:
        for volume in out.services[EGRESS_GUARD_SERVICE].volumes:
            host = volume.split(":")[0]
            if os.path.exists(host):
                os.unlink(host)


def test_compile_compose_file_guards_raw_and_auto_discovered_paths(tmp_path):
    raw = tmp_path / "compose.yaml"
    raw.write_text(
        "services:\n  default:\n    image: ubuntu\nx-inspect-network:\n  allow_domains: [example.com]\n",
        encoding="utf-8",
    )
    compiled = compile_compose_file(raw, tmp_path)
    assert compiled != raw.as_posix()
    data = yaml.safe_load(Path(compiled).read_text(encoding="utf-8"))
    assert EGRESS_GUARD_SERVICE in data["services"]
    assert "x-inspect-network" not in data


@pytest.mark.anyio
async def test_compose_project_create_compiles_network_extension():
    config = ComposeConfig.model_validate(
        {
            "services": {"default": {"image": "ubuntu"}},
            "x-inspect-network": {"allow_domains": ["example.com"]},
        }
    )
    project = await ComposeProject.create("project-create-guard", config)
    assert project.config is not None
    guard_mounts: list[str] = []
    try:
        data = yaml.safe_load(Path(project.config).read_text(encoding="utf-8"))
        assert EGRESS_GUARD_SERVICE in data["services"]
        assert "x-inspect-network" not in data
        guard_mounts = data["services"][EGRESS_GUARD_SERVICE]["volumes"]
    finally:
        Path(project.config).unlink(missing_ok=True)
        for mount in guard_mounts:
            Path(mount.split(":")[0]).unlink(missing_ok=True)
