"""Unit tests for :mod:`inspect_ai._util.cpu`.

The cgroup filesystem is synthesized under `tmp_path` rather than mocked: the
whole point of the module is that it reads files whose layout differs between
cgroup v1 and v2 and between a container and a host, and a mock of the read
would assert the layout this code already believes in.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from inspect_ai._util import cpu
from inspect_ai._util.cpu import cgroup_cpu_quota, effective_cpu_count

# a cgroup v2 container states both halves in `cpu.max`, at the root of the
# filesystem, with the literal `max` standing in for "no quota"
V2 = [
    ("uncapped", "max 100000\n", None),
    ("two processors", "200000 100000\n", 2.0),
    ("one processor", "100000 100000\n", 1.0),
    ("half a processor", "50000 100000\n", 0.5),
    ("a non-default period", "150000 50000\n", 3.0),
    ("a quota of zero", "0 100000\n", None),
    ("a period of zero", "100000 0\n", None),
    ("unparseable", "not a quota\n", None),
    ("one field", "100000\n", None),
    ("empty", "", None),
]


@pytest.mark.parametrize(
    ("content", "expected"),
    [(text, quota) for _, text, quota in V2],
    ids=[c for c, _, _ in V2],
)
def test_a_cgroup_v2_quota_is_read_from_cpu_max(
    content: str, expected: float | None, tmp_path: Path
) -> None:
    (tmp_path / "cpu.max").write_text(content)

    assert cgroup_cpu_quota(root=tmp_path, proc=tmp_path / "absent") == expected


# a cgroup v1 container mounts the cpu controller as its own directory and uses
# two files, spelling "no quota" as -1
V1 = [
    ("uncapped", "-1", "100000", None),
    ("two processors", "200000", "100000", 2.0),
    ("a quarter processor", "25000", "100000", 0.25),
    ("unparseable", "", "100000", None),
]


@pytest.mark.parametrize("controller", ["cpu", "cpu,cpuacct"])
@pytest.mark.parametrize(
    ("quota", "period", "expected"),
    [(quota, period, value) for _, quota, period, value in V1],
    ids=[case for case, _, _, _ in V1],
)
def test_a_cgroup_v1_quota_is_read_from_the_cpu_controller(
    controller: str, quota: str, period: str, expected: float | None, tmp_path: Path
) -> None:
    directory = tmp_path / controller
    directory.mkdir()
    (directory / "cpu.cfs_quota_us").write_text(quota)
    (directory / "cpu.cfs_period_us").write_text(period)

    assert cgroup_cpu_quota(root=tmp_path, proc=tmp_path / "absent") == expected


def test_no_cgroup_filesystem_is_no_quota(tmp_path: Path) -> None:
    # every platform without cgroups, and every unconstrained Linux host
    assert cgroup_cpu_quota(root=tmp_path / "absent", proc=tmp_path / "absent") is None


def test_a_nested_cgroup_is_found_through_proc_self_cgroup(tmp_path: Path) -> None:
    # a pod sharing the host's cgroup namespace sees the whole hierarchy, so
    # the limit is not at the root -- it is on the directory this file names
    nested = tmp_path / "kubepods" / "podabc" / "container"
    nested.mkdir(parents=True)
    (nested / "cpu.max").write_text("400000 100000\n")
    proc = tmp_path / "proc-self-cgroup"
    proc.write_text("0::/kubepods/podabc/container\n")

    assert cgroup_cpu_quota(root=tmp_path, proc=proc) == 4.0


def test_the_tightest_cgroup_on_the_path_is_the_one_that_binds(tmp_path: Path) -> None:
    # a quota on an ancestor caps its descendants no matter what they say
    parent = tmp_path / "kubepods"
    nested = parent / "container"
    nested.mkdir(parents=True)
    (parent / "cpu.max").write_text("200000 100000\n")
    (nested / "cpu.max").write_text("800000 100000\n")
    proc = tmp_path / "proc-self-cgroup"
    proc.write_text("0::/kubepods/container\n")

    assert cgroup_cpu_quota(root=tmp_path, proc=proc) == 2.0


def test_the_v1_cpu_controller_names_its_own_path(tmp_path: Path) -> None:
    # on cgroup v1 each controller has its own path, and the memory hierarchy's
    # is not the one the cpu quota lives under
    nested = tmp_path / "cpu,cpuacct" / "docker" / "abc123"
    nested.mkdir(parents=True)
    (nested / "cpu.cfs_quota_us").write_text("300000")
    (nested / "cpu.cfs_period_us").write_text("100000")
    proc = tmp_path / "proc-self-cgroup"
    proc.write_text(
        "5:memory:/docker/elsewhere\n4:cpu,cpuacct:/docker/abc123\n1:name=systemd:/\n"
    )

    assert cgroup_cpu_quota(root=tmp_path, proc=proc) == 3.0


@pytest.fixture
def cgroup_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the module at a synthesized cgroup filesystem, cache cleared.

    Cleared on the way out as well as in: the count is memoized for the life of
    the process, and a value read from a directory pytest is about to delete
    would otherwise be the answer every later caller got.
    """
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(cpu, "PROC_SELF_CGROUP", tmp_path / "absent")
    effective_cpu_count.cache_clear()
    yield tmp_path
    effective_cpu_count.cache_clear()


def test_a_quota_narrows_the_processor_count(cgroup_at: Path) -> None:
    # the defect this module exists for: a one-processor container on a host
    # with many must not report the host's
    (cgroup_at / "cpu.max").write_text("100000 100000\n")

    assert effective_cpu_count() == 1


def test_a_fractional_quota_still_leaves_one_processor(cgroup_at: Path) -> None:
    # rounding down is deliberate, but zero would multiply out to no
    # concurrency at all
    (cgroup_at / "cpu.max").write_text("50000 100000\n")

    assert effective_cpu_count() == 1


def test_a_quota_above_the_machine_does_not_inflate_it(cgroup_at: Path) -> None:
    # the quota is a ceiling, never a grant: 1000 processors' worth of quota on
    # a laptop is still a laptop
    (cgroup_at / "cpu.max").write_text("100000000 100000\n")

    assert effective_cpu_count() <= (os.cpu_count() or 1)


def test_no_quota_leaves_the_machines_count_alone(cgroup_at: Path) -> None:
    assert 1 <= effective_cpu_count() <= (os.cpu_count() or 1)


def test_the_docker_default_is_two_sandboxes_per_available_processor(
    cgroup_at: Path,
) -> None:
    # the call site the fix is for: a 2-CPU container defaults to 4 sandboxes,
    # not to twice the host's processors
    from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment

    (cgroup_at / "cpu.max").write_text("200000 100000\n")

    assert DockerSandboxEnvironment.default_concurrency() == 4


def test_the_subprocess_default_is_one_per_available_processor(
    cgroup_at: Path,
) -> None:
    from inspect_ai.util._subprocess import default_max_subprocesses

    (cgroup_at / "cpu.max").write_text("300000 100000\n")

    assert default_max_subprocesses() == 3
