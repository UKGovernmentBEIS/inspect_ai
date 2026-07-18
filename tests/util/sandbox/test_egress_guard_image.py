"""Build the egress-guard image and assert its baked-in invariants."""

import subprocess
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

import inspect_ai.util._sandbox.docker as docker_pkg

GUARD_TAG = "inspect-egress-guard:pytest"


def _guard_dir() -> Path:
    d = Path(next(iter(docker_pkg.__path__))) / "egress_guard"
    assert (d / "Dockerfile").exists(), f"missing Dockerfile in {d}"
    return d


def test_entrypoint_requires_private_cgroup_v2_before_installing_nftables() -> None:
    entrypoint = (_guard_dir() / "entrypoint.sh").read_text(encoding="utf-8")
    healthcheck = (_guard_dir() / "healthcheck.sh").read_text(encoding="utf-8")

    assert "test -f /sys/fs/cgroup/cgroup.controllers" in entrypoint
    assert 'grep -qx "0::/" /proc/self/cgroup' in entrypoint
    assert entrypoint.index('grep -qx "0::/" /proc/self/cgroup') < entrypoint.index(
        'nft -f "$NFT_CONF"'
    )
    assert "sport = :3129" in healthcheck


@skip_if_no_docker
@pytest.mark.slow
def test_guard_image_builds_with_required_invariants() -> None:
    ctx = _guard_dir()
    build = subprocess.run(
        [
            "docker",
            "buildx",
            "build",
            "--builder",
            "default",
            "--load",
            "-t",
            GUARD_TAG,
            str(ctx),
        ],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, f"guard image build failed:\n{build.stderr}"

    def run(cmd: list[str]) -> str:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", cmd[0], GUARD_TAG, *cmd[1:]],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, f"{cmd} failed:\n{r.stderr}"
        return r.stdout.strip()

    assert run(["id", "-u", "egress"]) == "4242"
    assert "--with-openssl" in run(["squid", "-v"])
    for tool in ("nft", "dnsmasq", "squid", "ss"):
        assert run(["sh", "-c", f"command -v {tool}"]).endswith(tool)
    assert run(["sh", "-c", "test -f /etc/squid/ssl_cert/guard.pem && echo ok"]) == "ok"
