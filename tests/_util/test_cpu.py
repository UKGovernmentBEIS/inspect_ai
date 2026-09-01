"""Unit tests for :mod:`inspect_ai._util.cpu`.

The cgroup filesystem is synthesized under `tmp_path` rather than mocked: the
whole point of the module is that it reads files whose layout differs between
cgroup v1 and v2 and between a container and a host, and a mock of the read
would assert the layout this code already believes in.

Every case names its own mount table for the same reason it names its own
`root` — a test that let either default through would read the host's cgroups
and answer differently on every machine it ran on.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from inspect_ai._util import cpu
from inspect_ai._util.cpu import cgroup_cpu_quota, effective_cpu_count

AVAILABLE = 8
"""Processors the tests pretend the machine offers, so a small runner agrees."""


def quota(
    root: Path, proc: Path | None = None, mounts: Path | None = None
) -> float | None:
    """`cgroup_cpu_quota` against a synthesized filesystem and nothing else."""
    absent = root / "absent"
    return cgroup_cpu_quota(
        root=root,
        proc=absent if proc is None else proc,
        mounts=absent if mounts is None else mounts,
    )


def mountinfo(path: Path, *entries: str) -> Path:
    """A `/proc/self/mountinfo` naming the given ` - fstype source options` mounts."""
    path.write_text(
        "".join(
            f"{index} 24 0:{index} {entry}\n" for index, entry in enumerate(entries)
        )
    )
    return path


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
    [(text, value) for _, text, value in V2],
    ids=[case for case, _, _ in V2],
)
def test_a_cgroup_v2_quota_is_read_from_cpu_max(
    content: str, expected: float | None, tmp_path: Path
) -> None:
    (tmp_path / "cpu.max").write_text(content)
    mounts = mountinfo(tmp_path / "mountinfo", f"/ {tmp_path} rw - cgroup2 cgroup2 rw")

    assert quota(tmp_path, mounts=mounts) == expected


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
    ("cfs_quota", "period", "expected"),
    [(cfs_quota, period, value) for _, cfs_quota, period, value in V1],
    ids=[case for case, _, _, _ in V1],
)
def test_a_cgroup_v1_quota_is_read_from_the_cpu_controller(
    controller: str,
    cfs_quota: str,
    period: str,
    expected: float | None,
    tmp_path: Path,
) -> None:
    directory = tmp_path / controller
    directory.mkdir()
    (directory / "cpu.cfs_quota_us").write_text(cfs_quota)
    (directory / "cpu.cfs_period_us").write_text(period)
    mounts = mountinfo(
        tmp_path / "mountinfo", f"/ {directory} rw - cgroup cgroup rw,{controller}"
    )

    assert quota(tmp_path, mounts=mounts) == expected


def test_no_cgroup_filesystem_is_no_quota(tmp_path: Path) -> None:
    # every platform without cgroups, and every unconstrained Linux host
    assert quota(tmp_path / "absent") is None


def test_a_nested_cgroup_is_found_through_proc_self_cgroup(tmp_path: Path) -> None:
    # a pod sharing the host's cgroup namespace sees the whole hierarchy, so
    # the limit is not at the root -- it is on the directory this file names
    nested = tmp_path / "kubepods" / "podabc" / "container"
    nested.mkdir(parents=True)
    (nested / "cpu.max").write_text("400000 100000\n")
    proc = tmp_path / "proc-self-cgroup"
    proc.write_text("0::/kubepods/podabc/container\n")
    mounts = mountinfo(tmp_path / "mountinfo", f"/ {tmp_path} rw - cgroup2 cgroup2 rw")

    assert quota(tmp_path, proc=proc, mounts=mounts) == 4.0


def test_the_tightest_cgroup_on_the_path_is_the_one_that_binds(tmp_path: Path) -> None:
    # a quota on an ancestor caps its descendants no matter what they say
    parent = tmp_path / "kubepods"
    nested = parent / "container"
    nested.mkdir(parents=True)
    (parent / "cpu.max").write_text("200000 100000\n")
    (nested / "cpu.max").write_text("800000 100000\n")
    proc = tmp_path / "proc-self-cgroup"
    proc.write_text("0::/kubepods/container\n")
    mounts = mountinfo(tmp_path / "mountinfo", f"/ {tmp_path} rw - cgroup2 cgroup2 rw")

    assert quota(tmp_path, proc=proc, mounts=mounts) == 2.0


def test_the_v1_cpu_controller_names_its_own_path(tmp_path: Path) -> None:
    # on cgroup v1 each controller has its own path, and the memory hierarchy's
    # is not the one the cpu quota lives under
    controller = tmp_path / "cpu,cpuacct"
    nested = controller / "docker" / "abc123"
    nested.mkdir(parents=True)
    (nested / "cpu.cfs_quota_us").write_text("300000")
    (nested / "cpu.cfs_period_us").write_text("100000")
    proc = tmp_path / "proc-self-cgroup"
    proc.write_text(
        "5:memory:/docker/elsewhere\n4:cpu,cpuacct:/docker/abc123\n1:name=systemd:/\n"
    )
    mounts = mountinfo(
        tmp_path / "mountinfo", f"/ {controller} rw - cgroup cgroup rw,cpu,cpuacct"
    )

    assert quota(tmp_path, proc=proc, mounts=mounts) == 3.0


def test_a_child_cgroup_named_cpu_is_not_the_v1_controller(tmp_path: Path) -> None:
    # the directory-name guess this module used to make: under cgroup v2 `cpu`
    # is an ordinary child cgroup, and its quota binds whatever runs in it --
    # not us
    child = tmp_path / "cpu"
    child.mkdir()
    (tmp_path / "cpu.max").write_text("max 100000\n")
    (child / "cpu.max").write_text("100000 100000\n")
    (child / "cpu.cfs_quota_us").write_text("100000")
    (child / "cpu.cfs_period_us").write_text("100000")
    mounts = mountinfo(tmp_path / "mountinfo", f"/ {tmp_path} rw - cgroup2 cgroup2 rw")

    assert quota(tmp_path, mounts=mounts) is None


def test_a_v1_hierarchy_is_found_wherever_it_is_mounted(tmp_path: Path) -> None:
    # nothing requires a v1 hierarchy to be mounted under a name naming its
    # controllers, or under /sys/fs/cgroup at all
    mountpoint = tmp_path / "elsewhere" / "sched"
    mountpoint.mkdir(parents=True)
    (mountpoint / "cpu.cfs_quota_us").write_text("600000")
    (mountpoint / "cpu.cfs_period_us").write_text("100000")
    mounts = mountinfo(
        tmp_path / "mountinfo", f"/ {mountpoint} rw - cgroup cgroup rw,cpu,cpuacct"
    )

    assert quota(tmp_path, mounts=mounts) == 6.0


def test_the_v1_cpu_hierarchy_wins_over_a_unified_one(tmp_path: Path) -> None:
    # a "hybrid" system mounts both, but a controller lives on exactly one
    # hierarchy: with cpu on v1, the v2 mount has nothing to say about CPU
    unified = tmp_path / "unified"
    controller = tmp_path / "cpu,cpuacct"
    unified.mkdir()
    controller.mkdir()
    (unified / "cpu.max").write_text("100000 100000\n")
    (controller / "cpu.cfs_quota_us").write_text("500000")
    (controller / "cpu.cfs_period_us").write_text("100000")
    mounts = mountinfo(
        tmp_path / "mountinfo",
        f"/ {unified} rw - cgroup2 cgroup2 rw",
        f"/ {controller} rw - cgroup cgroup rw,cpu,cpuacct",
    )

    assert quota(tmp_path, mounts=mounts) == 5.0


def test_a_mount_of_part_of_the_hierarchy_is_read_from_its_own_root(
    tmp_path: Path,
) -> None:
    # a runtime that hands a container its own cgroup mounts that subtree, and
    # /proc/self/cgroup still reports the path the subtree is rooted at
    (tmp_path / "cpu.max").write_text("700000 100000\n")
    proc = tmp_path / "proc-self-cgroup"
    proc.write_text("0::/docker/abc123\n")
    mounts = mountinfo(
        tmp_path / "mountinfo", f"/docker/abc123 {tmp_path} rw - cgroup2 cgroup2 rw"
    )

    assert quota(tmp_path, proc=proc, mounts=mounts) == 7.0


def test_a_mount_point_containing_a_space_is_unescaped(tmp_path: Path) -> None:
    # mountinfo octal-escapes the characters that would otherwise end a field
    mountpoint = tmp_path / "cgroup fs"
    mountpoint.mkdir()
    (mountpoint / "cpu.max").write_text("900000 100000\n")
    escaped = str(mountpoint).replace(" ", "\\040")
    mounts = mountinfo(tmp_path / "mountinfo", f"/ {escaped} rw - cgroup2 cgroup2 rw")

    assert quota(tmp_path, mounts=mounts) == 9.0


def test_a_real_mount_table_is_read_past_its_other_mounts(tmp_path: Path) -> None:
    # verbatim shapes: optional fields ahead of the `-` separator, and a table
    # in which cgroup mounts are a handful of lines among dozens
    (tmp_path / "cpu.max").write_text("800000 100000\n")
    mounts = tmp_path / "mountinfo"
    mounts.write_text(
        "24 30 0:22 / /proc rw,nosuid,nodev,noexec,relatime shared:5 - proc proc rw\n"
        "25 30 0:23 / /sys rw,nosuid,nodev,noexec,relatime shared:6 - sysfs sysfs rw\n"
        f"26 25 0:26 / {tmp_path} ro,nosuid,nodev,noexec shared:9 - cgroup2 cgroup rw\n"
        "27 30 0:1 / / rw,relatime - overlay overlay rw,lowerdir=/var/lib\n"
    )

    assert quota(tmp_path, mounts=mounts) == 8.0


def test_an_unreadable_mount_table_falls_back_to_the_conventional_root(
    tmp_path: Path,
) -> None:
    # /proc is not always mounted, and losing quota detection there would put
    # the host's processor count back in a container's defaults
    (tmp_path / "cpu.max").write_text("200000 100000\n")

    assert quota(tmp_path) == 2.0


def test_the_fallback_reads_a_v1_controller_directory(tmp_path: Path) -> None:
    controller = tmp_path / "cpu,cpuacct"
    controller.mkdir()
    (controller / "cpu.cfs_quota_us").write_text("400000")
    (controller / "cpu.cfs_period_us").write_text("100000")

    assert quota(tmp_path) == 4.0


def test_the_fallback_does_not_mistake_a_child_named_cpu_for_a_controller(
    tmp_path: Path,
) -> None:
    child = tmp_path / "cpu"
    child.mkdir()
    (tmp_path / "cgroup.controllers").write_text("cpuset cpu memory\n")
    (child / "cpu.max").write_text("100000 100000\n")

    assert quota(tmp_path) is None


@pytest.fixture
def cgroup_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the module at a synthesized cgroup filesystem on a fixed machine.

    The processor count is fixed too: `effective_cpu_count()` is a minimum of
    the quota and what the machine offers, and a runner with a two-processor
    affinity mask would otherwise fail tests about the quota.
    """
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(cpu, "PROC_SELF_CGROUP", tmp_path / "absent")
    monkeypatch.setattr(cpu, "PROC_SELF_MOUNTINFO", tmp_path / "absent")
    monkeypatch.setattr(cpu, "_available_cpus", lambda: AVAILABLE)
    yield tmp_path


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

    assert effective_cpu_count() == AVAILABLE


def test_no_quota_leaves_the_machines_count_alone(cgroup_at: Path) -> None:
    assert effective_cpu_count() == AVAILABLE


def test_a_quota_raised_at_runtime_is_seen(cgroup_at: Path) -> None:
    # quotas are live kernel state -- `docker update --cpus`, a Kubernetes
    # in-place resize -- so a count frozen at first call answers for evals the
    # limit no longer applies to
    (cgroup_at / "cpu.max").write_text("100000 100000\n")
    assert effective_cpu_count() == 1

    (cgroup_at / "cpu.max").write_text("400000 100000\n")

    assert effective_cpu_count() == 4


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
