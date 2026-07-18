"""Real-Docker adversarial and fail-closed acceptance tests for the egress guard."""
# noqa: SIZE_OK — approved plan defines this as one acceptance suite (Task 7, file structure).

import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.compose import ComposeConfig, ComposeService
from inspect_ai.util._sandbox.docker.network import (
    EGRESS_GUARD_DIR,
    EGRESS_GUARD_SERVICE,
    apply_egress_guard,
    write_guard_configs,
)
from inspect_ai.util._sandbox.network import NetworkAccess

GUARD_TAG = "inspect-egress-guard:e2e"
WORKLOAD_TAG = "inspect-egress-workload:e2e"
WORKLOAD_DOCKERFILE = Path(__file__).parent / "egress_guard_e2e" / "workload.Dockerfile"
MULTI_SERVICE_TAG = "inspect-egress-multi-service:e2e"
MULTI_SERVICE_DOCKERFILE = (
    Path(__file__).parent / "egress_guard_e2e" / "multi_service.Dockerfile"
)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _build(tag: str, dockerfile: Path, context: Path) -> None:
    result = _docker(
        "buildx",
        "build",
        "--builder",
        "default",
        "--load",
        "-t",
        tag,
        "-f",
        dockerfile.as_posix(),
        context.as_posix(),
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _compose(
    project: str, compose_file: str, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return _docker("compose", "-p", project, "-f", compose_file, *args, check=check)


def _exec_workload(
    project: str, compose_file: str, script: str
) -> subprocess.CompletedProcess[str]:
    return _compose(
        project,
        compose_file,
        "exec",
        "-T",
        "workload",
        "sh",
        "-c",
        script,
        check=False,
    )


def _exec_service(
    project: str, compose_file: str, service: str, script: str
) -> subprocess.CompletedProcess[str]:
    return _compose(
        project,
        compose_file,
        "exec",
        "-T",
        service,
        "sh",
        "-c",
        script,
        check=False,
    )


def _guard_pid(project: str, compose_file: str) -> str:
    result = _compose(
        project,
        compose_file,
        "exec",
        "-T",
        EGRESS_GUARD_SERVICE,
        "sh",
        "-c",
        "for proc in /proc/[0-9]*; do "
        '[ "$(cat "$proc/comm")" = squid ] && { echo "${proc##*/}"; exit 0; }; '
        "done; exit 1",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _attacker_ip(project: str, compose_file: str) -> str:
    result = _exec_service(
        project,
        compose_file,
        "attacker",
        "getent hosts \"$(hostname)\" | cut -d' ' -f1",
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _wait_for_attacker_ready(project: str, compose_file: str) -> None:
    for _ in range(15):
        probe = _exec_service(
            project,
            compose_file,
            "attacker",
            "openssl s_client -connect 127.0.0.1:443 -quiet </dev/null >/dev/null 2>&1",
        )
        if probe.returncode == 0:
            return
        time.sleep(1)
    pytest.fail("attacker TLS server never became ready on loopback")


@pytest.fixture(scope="module")
def guarded_env(tmp_path_factory):
    _build(GUARD_TAG, EGRESS_GUARD_DIR / "Dockerfile", EGRESS_GUARD_DIR)
    _build(WORKLOAD_TAG, WORKLOAD_DOCKERFILE, WORKLOAD_DOCKERFILE.parent)

    project = f"inspect-egress-e2e-{uuid.uuid4().hex[:8]}"
    network_access = NetworkAccess(
        allow_domains=["example.com", "oauth2.googleapis.com"],
        allow_cidr=["1.1.1.1/32"],
    )
    mount_paths = write_guard_configs(network_access, project)
    guarded = apply_egress_guard(
        ComposeConfig(
            services={
                "workload": ComposeService(
                    image=WORKLOAD_TAG,
                    init=True,
                    command=["sleep", "infinity"],
                    user="1000",
                )
            }
        ),
        network_access,
        guard_context=EGRESS_GUARD_DIR.resolve().as_posix(),
        mount_paths=mount_paths,
    )
    guard = guarded.services[EGRESS_GUARD_SERVICE]
    guard.build = None
    guard.image = GUARD_TAG
    guarded.services["attacker"] = ComposeService(
        image=WORKLOAD_TAG,
        init=True,
        command=[
            "sh",
            "-c",
            "openssl req -x509 -newkey rsa:2048 -nodes -days 1 "
            "-keyout /tmp/attacker-key.pem -out /tmp/attacker-cert.pem "
            "-subj '/CN=attacker.invalid' && "
            "while true; do openssl s_server -quiet -naccept 1 -accept 443 "
            "-cert /tmp/attacker-cert.pem -key /tmp/attacker-key.pem; done",
        ],
    )

    workdir = tmp_path_factory.mktemp("egress-e2e")
    compose_file = workdir / "compose.yaml"
    compose_file.write_text(
        yaml.dump(
            guarded.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    up = _compose(
        project,
        compose_file.as_posix(),
        "up",
        "--wait",
        "--wait-timeout",
        "180",
        check=False,
    )
    assert up.returncode == 0, up.stderr
    try:
        yield project, compose_file.as_posix()
    finally:
        _compose(project, compose_file.as_posix(), "down", "--volumes", check=False)
        for path in mount_paths.values():
            Path(path).unlink(missing_ok=True)


@pytest.fixture(scope="module")
def multi_service_env(tmp_path_factory):
    _build(GUARD_TAG, EGRESS_GUARD_DIR / "Dockerfile", EGRESS_GUARD_DIR)
    _build(
        MULTI_SERVICE_TAG,
        MULTI_SERVICE_DOCKERFILE,
        MULTI_SERVICE_DOCKERFILE.parent,
    )
    _build(WORKLOAD_TAG, WORKLOAD_DOCKERFILE, WORKLOAD_DOCKERFILE.parent)

    project = f"inspect-egress-multi-{uuid.uuid4().hex[:8]}"
    network_access = NetworkAccess(allow_domains=["example.com"])
    mount_paths = write_guard_configs(network_access, project)
    guarded = apply_egress_guard(
        ComposeConfig(
            services={
                "workload": ComposeService(
                    image=MULTI_SERVICE_TAG,
                    init=True,
                    command=["/usr/bin/supervisord", "-n"],
                    user="0",
                ),
                "sidecar": ComposeService(
                    image=WORKLOAD_TAG,
                    init=True,
                    command=["sleep", "infinity"],
                    user="0",
                ),
            }
        ),
        network_access,
        guard_context=EGRESS_GUARD_DIR.resolve().as_posix(),
        mount_paths=mount_paths,
    )
    guard = guarded.services[EGRESS_GUARD_SERVICE]
    guard.build = None
    guard.image = GUARD_TAG

    workdir = tmp_path_factory.mktemp("egress-multi-service")
    compose_file = workdir / "compose.yaml"
    compose_file.write_text(
        yaml.dump(
            guarded.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    up = _compose(
        project,
        compose_file.as_posix(),
        "up",
        "--wait",
        "--wait-timeout",
        "180",
        check=False,
    )
    assert up.returncode == 0, up.stderr
    try:
        yield project, compose_file.as_posix()
    finally:
        _compose(project, compose_file.as_posix(), "down", "--volumes", check=False)
        for path in mount_paths.values():
            Path(path).unlink(missing_ok=True)


@skip_if_no_docker
@pytest.mark.slow
def test_allowlisted_https_reachable(guarded_env):
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "curl -sS -o /dev/null -w '%{http_code}' --max-time 25 https://example.com/",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "200", result.stdout


@skip_if_no_docker
@pytest.mark.slow
def test_multi_ip_allowlisted_https_reaches_upstream_without_host_forgery(guarded_env):
    # Given a real allowlisted Google endpoint with multiple A records.
    # When a workload uses transparent HTTPS egress with no proxy configuration.
    # Then Squid tunnels the request to the original destination instead of returning
    # ERR_CONFLICT_HOST from host verification.
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "curl -sS --noproxy '*' -o /dev/null -w '%{http_code}' "
        "--max-time 25 https://oauth2.googleapis.com/",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != "409", result.stdout
    assert result.stdout.strip().isdigit(), result.stdout


@skip_if_no_docker
@pytest.mark.slow
def test_non_allowlisted_https_blocked(guarded_env):
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "curl -sS -o /dev/null --max-time 25 https://example.org/",
    )
    assert result.returncode != 0, result.stdout + result.stderr


@skip_if_no_docker
@pytest.mark.slow
def test_dns_nxdomain_libc_and_direct(guarded_env):
    project, compose_file = guarded_env
    allowed = _exec_workload(project, compose_file, "getent hosts example.com")
    assert allowed.returncode == 0, allowed.stderr
    denied = _exec_workload(project, compose_file, "getent hosts example.org")
    assert denied.returncode != 0, denied.stdout
    direct = _exec_workload(
        project,
        compose_file,
        "dig +time=5 +tries=1 @1.1.1.1 evil.example.org A | grep -E 'status:'",
    )
    assert "NXDOMAIN" in direct.stdout, direct.stdout


@skip_if_no_docker
@pytest.mark.slow
def test_exact_domain_blocks_subdomain_dns_and_preserves_nftset(
    guarded_env: tuple[str, str],
) -> None:
    project, compose_file = guarded_env
    apex = _exec_workload(
        project,
        compose_file,
        "getent ahostsv4 example.com | awk 'NR==1 {print $1}'",
    )
    assert apex.returncode == 0, apex.stderr
    apex_ip = apex.stdout.strip()

    before = _exec_service(
        project,
        compose_file,
        EGRESS_GUARD_SERVICE,
        "nft list set inet egress allowed_domain_ips4",
    )
    assert before.returncode == 0, before.stderr
    assert apex_ip in before.stdout

    named_subdomain = _exec_workload(
        project, compose_file, "getent hosts foo.example.com"
    )
    assert named_subdomain.returncode != 0, named_subdomain.stdout

    tunnel_label = uuid.uuid4().hex
    tunnel = _exec_workload(
        project,
        compose_file,
        f"dig +time=5 +tries=1 @1.1.1.1 {tunnel_label}.example.com A",
    )
    assert tunnel.returncode == 0, tunnel.stderr
    assert "NXDOMAIN" in tunnel.stdout, tunnel.stdout

    after = _exec_service(
        project,
        compose_file,
        EGRESS_GUARD_SERVICE,
        "nft list set inet egress allowed_domain_ips4",
    )
    assert after.returncode == 0, after.stderr
    assert after.stdout == before.stdout


@skip_if_no_docker
@pytest.mark.slow
def test_real_forged_sni_to_allowlisted_connect_blocked(guarded_env):
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "openssl s_client -connect example.com:443 -servername example.org </dev/null",
    )
    assert result.returncode != 0, result.stdout + result.stderr


@skip_if_no_docker
@pytest.mark.slow
def test_forged_sni_to_unallowlisted_attacker_ip_blocked(guarded_env):
    # Given an attacker-controlled TLS endpoint whose IP is NOT DNS-resolved for any
    # allowlisted domain (only example.com/1.1.1.1 are allowed).
    # When the workload connects directly to the attacker IP but forges the TLS SNI
    # to an allowlisted domain name (the naive redirect-gating bypass PoC).
    # Then the connection must never reach the attacker: the transparent redirect
    # itself is gated on the destination IP being DNS-resolved-and-allowlisted, so a
    # forged SNI to a non-allowlisted IP falls through to the default-deny filter
    # chain and is dropped before Squid ever sees the ClientHello.
    project, compose_file = guarded_env
    attacker_ip = _attacker_ip(project, compose_file)
    _wait_for_attacker_ready(project, compose_file)
    result = _exec_workload(
        project,
        compose_file,
        f"openssl s_client -connect {attacker_ip}:443 "
        "-servername example.com </dev/null",
    )
    assert result.returncode != 0, (
        "forged-SNI attack reached the attacker IP: " + result.stdout + result.stderr
    )


@skip_if_no_docker
@pytest.mark.slow
def test_raw_ip_connect_blocked(guarded_env):
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "curl --fail -sS -k -o /dev/null --max-time 15 https://8.8.8.8/",
    )
    assert result.returncode != 0, result.stdout + result.stderr


@skip_if_no_docker
@pytest.mark.slow
def test_allow_cidr_reachable(guarded_env):
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "curl -sS -k -o /dev/null -w '%{http_code}' --max-time 25 https://1.1.1.1/",
    )
    assert result.returncode == 0 and result.stdout.strip().startswith(
        ("2", "3", "4")
    ), result.stdout


@skip_if_no_docker
@pytest.mark.slow
def test_transparent_redirect_enforces_policy_without_client_proxy_config(guarded_env):
    # Given a client that sets no proxy env var and passes --noproxy '*'.
    # When it reaches an allowed vs a non-allowed domain over HTTP and HTTPS.
    # Then the nftables redirect still routes it through Squid either way.
    project, compose_file = guarded_env
    for url in ("http://example.com/", "https://example.com/"):
        allowed = _exec_workload(
            project,
            compose_file,
            f"curl --fail -sS -o /dev/null --max-time 15 --noproxy '*' {url}",
        )
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    for url in ("http://example.org/", "https://example.org/"):
        denied = _exec_workload(
            project,
            compose_file,
            f"curl -sS -o /dev/null --max-time 15 --noproxy '*' {url}",
        )
        assert denied.returncode != 0, denied.stdout


@skip_if_no_docker
@pytest.mark.slow
def test_http_host_enforcement_on_port_80(guarded_env):
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "curl --fail -sS -o /dev/null --max-time 15 http://example.org/",
    )
    assert result.returncode != 0, result.stdout


# Note: allow_domains_ports scoped to a non-HTTP(S) port (e.g. SMTP/587) is no
# longer a supported configuration -- NetworkAccess now fails loud on it, directing
# users to allow_cidr instead (see test_network_access.py::
# test_rejects_non_http_ports_because_ip_based_egress_has_no_identity_check).
# allow_cidr already grants any port on an allowlisted IP with no code changes
# needed (see test_allow_cidr_reachable above), so no replacement e2e is required.


@skip_if_no_docker
@pytest.mark.slow
def test_squid_runs_as_trusted_egress_uid(guarded_env):
    project, compose_file = guarded_env
    pid = _guard_pid(project, compose_file)
    status = _compose(
        project,
        compose_file,
        "exec",
        "-T",
        EGRESS_GUARD_SERVICE,
        "sh",
        "-c",
        f"cat /proc/{pid}/status",
    )
    uid_line = next(
        line for line in status.stdout.splitlines() if line.startswith("Uid:")
    )
    assert uid_line.split()[1] == "4242", uid_line


@skip_if_no_docker
@pytest.mark.slow
def test_setuid_to_trusted_uid_cannot_bypass_cgroup_enforcement(guarded_env):
    project, compose_file = guarded_env
    result = _exec_workload(
        project,
        compose_file,
        "setpriv --reuid 4242 curl -sS -o /dev/null --max-time 15 https://8.8.8.8/",
    )
    assert result.returncode != 0, result.stdout + result.stderr


@skip_if_no_docker
@pytest.mark.slow
def test_failclosed_guard_process_restart_no_gap(guarded_env):
    project, compose_file = guarded_env
    pid = _guard_pid(project, compose_file)
    _compose(
        project,
        compose_file,
        "exec",
        "-T",
        EGRESS_GUARD_SERVICE,
        "kill",
        "-9",
        pid,
        check=False,
    )
    blocked = _exec_workload(
        project,
        compose_file,
        "curl -sS -o /dev/null --max-time 15 https://example.org/",
    )
    assert blocked.returncode != 0, "deny policy gapped while Squid was down"
    nft = _compose(
        project,
        compose_file,
        "exec",
        "-T",
        EGRESS_GUARD_SERVICE,
        "nft",
        "list",
        "table",
        "inet",
        "egress",
        check=False,
    )
    assert nft.returncode == 0 and "policy drop" in nft.stdout, nft.stderr

    for _ in range(10):
        recovered = _exec_workload(
            project,
            compose_file,
            "curl -sS -o /dev/null -w '%{http_code}' --max-time 15 https://example.com/",
        )
        if recovered.returncode == 0 and recovered.stdout.strip() == "200":
            break
        time.sleep(2)
    else:
        pytest.fail("Squid did not recover after the supervisor restart")


@skip_if_no_docker
@pytest.mark.slow
def test_failclosed_guard_container_death(guarded_env):
    project, compose_file = guarded_env
    _compose(project, compose_file, "kill", EGRESS_GUARD_SERVICE, check=False)
    for _ in range(5):
        dead = _exec_workload(
            project,
            compose_file,
            "curl -sS -o /dev/null --max-time 10 https://example.com/",
        )
        if dead.returncode != 0:
            break
        time.sleep(1)
    else:
        pytest.fail("workload retained egress after guard death")


@skip_if_no_docker
@pytest.mark.slow
def test_health_gate_present_in_generated_compose(guarded_env):
    _, compose_file = guarded_env
    workload = yaml.safe_load(Path(compose_file).read_text(encoding="utf-8"))[
        "services"
    ]["workload"]
    assert workload["network_mode"] == f"service:{EGRESS_GUARD_SERVICE}"
    assert (
        workload["depends_on"][EGRESS_GUARD_SERVICE]["condition"] == "service_healthy"
    )


@skip_if_no_docker
@pytest.mark.slow
def test_multi_service_setuid_and_transparent_egress_fail_closed(multi_service_env):
    # Given a root supervisor that must start a non-root HTTP service in the shared netns.
    # When its service uses loopback and external network destinations.
    # Then local traffic works, external policy is enforced by cgroup, and guard failure closes egress.
    project, compose_file = multi_service_env

    service = _exec_service(
        project, compose_file, "workload", "supervisorctl status internal-http"
    )
    assert service.returncode == 0 and "RUNNING" in service.stdout, (
        service.stdout + service.stderr
    )

    non_root = _exec_service(
        project, compose_file, "workload", "ps -o user= -C python3"
    )
    assert non_root.returncode == 0 and "service" in non_root.stdout, non_root.stdout

    internal = _exec_service(
        project,
        compose_file,
        "sidecar",
        "curl -sS --noproxy '*' --resolve epm.acme-corp.com:8080:127.0.0.1 "
        "http://epm.acme-corp.com:8080/",
    )
    assert (
        internal.returncode == 0 and "internal egress guard service" in internal.stdout
    )

    allowed = _exec_service(
        project,
        compose_file,
        "sidecar",
        "curl -sS -o /dev/null -w '%{http_code}' --max-time 25 https://example.com/",
    )
    assert allowed.returncode == 0 and allowed.stdout.strip() == "200", allowed.stderr

    denied_dns = _exec_service(
        project, compose_file, "sidecar", "getent hosts example.org"
    )
    assert denied_dns.returncode != 0, denied_dns.stdout
    denied_tls = _exec_service(
        project,
        compose_file,
        "sidecar",
        "curl -k -sS -o /dev/null --max-time 15 --resolve example.org:443:93.184.216.34 "
        "https://example.org/",
    )
    assert denied_tls.returncode != 0, denied_tls.stdout + denied_tls.stderr

    forged_identity = _exec_service(
        project,
        compose_file,
        "sidecar",
        "setpriv --reuid 4242 --regid 4242 --clear-groups curl -k -sS -o /dev/null "
        "--max-time 15 https://8.8.8.8/",
    )
    assert forged_identity.returncode != 0, (
        forged_identity.stdout + forged_identity.stderr
    )

    squid_pid = _guard_pid(project, compose_file)
    _compose(
        project,
        compose_file,
        "exec",
        "-T",
        EGRESS_GUARD_SERVICE,
        "kill",
        "-9",
        squid_pid,
        check=False,
    )
    restart_gap = _exec_service(
        project,
        compose_file,
        "sidecar",
        "curl -sS -o /dev/null --max-time 15 https://example.com/",
    )
    assert restart_gap.returncode != 0, "egress opened while Squid restarted"

    for _ in range(10):
        recovered = _exec_service(
            project,
            compose_file,
            "sidecar",
            "curl -sS -o /dev/null -w '%{http_code}' --max-time 15 https://example.com/",
        )
        if recovered.returncode == 0 and recovered.stdout.strip() == "200":
            break
        time.sleep(2)
    else:
        pytest.fail("Squid did not recover after the supervisor restart")

    _compose(project, compose_file, "kill", EGRESS_GUARD_SERVICE, check=False)
    guard_death = _exec_service(
        project,
        compose_file,
        "sidecar",
        "curl -sS -o /dev/null --max-time 10 https://example.com/",
    )
    assert guard_death.returncode != 0, "sidecar retained egress after guard death"


@pytest.fixture(scope="module")
def wildcard_domain_env(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[str, str]]:
    _build(GUARD_TAG, EGRESS_GUARD_DIR / "Dockerfile", EGRESS_GUARD_DIR)
    _build(WORKLOAD_TAG, WORKLOAD_DOCKERFILE, WORKLOAD_DOCKERFILE.parent)

    project = f"inspect-egress-wildcard-{uuid.uuid4().hex[:8]}"
    network_access = NetworkAccess(allow_domains=["*.example.com"])
    mount_paths = write_guard_configs(network_access, project)
    guarded = apply_egress_guard(
        ComposeConfig(
            services={
                "workload": ComposeService(
                    image=WORKLOAD_TAG,
                    init=True,
                    command=["sleep", "infinity"],
                    user="1000",
                )
            }
        ),
        network_access,
        guard_context=EGRESS_GUARD_DIR.resolve().as_posix(),
        mount_paths=mount_paths,
    )
    guard = guarded.services[EGRESS_GUARD_SERVICE]
    guard.build = None
    guard.image = GUARD_TAG

    workdir = tmp_path_factory.mktemp("egress-wildcard")
    compose_file = workdir / "compose.yaml"
    compose_file.write_text(
        yaml.dump(
            guarded.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    up = _compose(
        project,
        compose_file.as_posix(),
        "up",
        "--wait",
        "--wait-timeout",
        "180",
        check=False,
    )
    assert up.returncode == 0, up.stderr
    try:
        yield project, compose_file.as_posix()
    finally:
        _compose(project, compose_file.as_posix(), "down", "--volumes", check=False)
        for path in mount_paths.values():
            Path(path).unlink(missing_ok=True)


@skip_if_no_docker
@pytest.mark.slow
def test_wildcard_domain_splices_subdomains_and_terminates_apex(
    wildcard_domain_env: tuple[str, str],
) -> None:
    project, compose_file = wildcard_domain_env
    resolved = _exec_workload(
        project,
        compose_file,
        "getent ahostsv4 www.example.com | awk 'NR==1 {print $1}'",
    )
    assert resolved.returncode == 0, resolved.stderr
    subdomain_ip = resolved.stdout.strip()

    subdomain = _exec_workload(
        project,
        compose_file,
        "curl -sS -o /dev/null -w '%{http_code}' --max-time 25 https://www.example.com/",
    )
    assert subdomain.returncode == 0, subdomain.stderr
    assert subdomain.stdout.strip() == "200", subdomain.stdout

    apex_dns = _exec_workload(project, compose_file, "getent hosts example.com")
    assert apex_dns.returncode != 0, apex_dns.stdout

    apex_tls = _exec_workload(
        project,
        compose_file,
        "curl -k -sS -o /dev/null --max-time 15 "
        f"--resolve example.com:443:{subdomain_ip} https://example.com/",
    )
    assert apex_tls.returncode != 0, apex_tls.stdout + apex_tls.stderr
