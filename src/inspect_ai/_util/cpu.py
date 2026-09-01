"""Processor accounting that respects container CPU limits.

``os.cpu_count()`` reports the processors the *machine* has, which is not what
a process running under a CPU limit is allowed to use. A container started with
``--cpus=2`` on a 64-core host still sees 64, so a default derived from
``os.cpu_count()`` oversubscribes by a factor of 32. The kernel responds by
throttling the cgroup rather than by refusing the work, so the symptom is
everything running slowly — not an error anybody can attribute.

Two mechanisms narrow what a process may use, and they compose:

- A **CPU set** (``--cpuset-cpus``, ``taskset``) pins the process to particular
  processors. ``os.sched_getaffinity()`` reports it; ``os.cpu_count()`` does
  not.
- A **CPU quota** (``--cpus``, ``--cpu-quota``, Kubernetes' ``limits.cpu``,
  systemd's ``CPUQuota=``) caps the CPU time the cgroup may accumulate per
  period without pinning anything. Only the cgroup filesystem reports it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
"""Where the cgroup filesystem is mounted (patched by tests)."""

PROC_SELF_CGROUP = Path("/proc/self/cgroup")
"""Which cgroup this process is in, relative to the hierarchy root."""


@lru_cache(maxsize=1)
def effective_cpu_count() -> int:
    """Processors this process may actually use (never less than one).

    Narrows `os.cpu_count()` by the CPU set the process is pinned to and by the
    cgroup CPU quota in force, neither of which `os.cpu_count()` reports. A
    fractional quota rounds *down*: the number is used to size concurrency, and
    half a processor does not run another unit of work.
    """
    count = float(_available_cpus())
    quota = cgroup_cpu_quota()
    if quota is not None:
        count = min(count, quota)
    return max(1, int(count))


def cgroup_cpu_quota(
    root: Path | None = None, proc: Path | None = None
) -> float | None:
    """Processors the cgroup this process belongs to may use.

    `None` when no quota applies, which is the answer on an unconstrained host
    and on any platform without a cgroup filesystem.

    Args:
      root: Where the cgroup filesystem is mounted (defaults to `CGROUP_ROOT`).
      proc: File naming this process's own cgroup (defaults to `PROC_SELF_CGROUP`).
    """
    quotas = [
        quota
        for directory in _cgroup_dirs(
            CGROUP_ROOT if root is None else root,
            _own_cgroup(PROC_SELF_CGROUP if proc is None else proc),
        )
        if (quota := _quota_at(directory)) is not None
    ]
    # every cgroup on the path to this one binds, so the tightest one wins
    return min(quotas) if quotas else None


def _available_cpus() -> int:
    # the affinity mask is what a CPU set narrows, and reading it is Linux-only
    if sys.platform == "linux":
        try:
            return len(os.sched_getaffinity(0))
        except OSError:
            pass
    return os.cpu_count() or 1


def _cgroup_dirs(root: Path, relative: str) -> Iterator[Path]:
    """Directories that might state a CPU quota for this process.

    Inside a container the container's own cgroup is mounted at the root of the
    cgroup filesystem — under `root` itself on cgroup v2, under the `cpu`
    controller on v1 — so `root` is usually where the limit is. When the host's
    hierarchy is visible instead (a pod on a cluster that shares the host's
    cgroup namespace, a systemd unit with a `CPUQuota=`), the limit is on the
    nested directory `/proc/self/cgroup` names, or on one of its ancestors.
    """
    parts = [part for part in relative.split("/") if part]
    branches = ["/".join(parts[:depth]) for depth in range(len(parts), -1, -1)]
    for base in (root, root / "cpu", root / "cpu,cpuacct"):
        for branch in branches:
            yield base / branch


def _quota_at(directory: Path) -> float | None:
    """The CPU quota one cgroup directory states, in processors."""
    # cgroup v2 puts both halves in one file, and spells "uncapped" as the
    # literal `max` in place of the quota
    unified = _read(directory / "cpu.max")
    if unified is not None:
        fields = unified.split()
        return _ratio(fields[0], fields[1]) if len(fields) == 2 else None

    # cgroup v1 uses two files, and spells "uncapped" as a quota of -1
    quota = _read(directory / "cpu.cfs_quota_us")
    period = _read(directory / "cpu.cfs_period_us")
    return None if quota is None or period is None else _ratio(quota, period)


def _own_cgroup(proc: Path) -> str:
    """This process's cgroup path, relative to the hierarchy root.

    `/proc/self/cgroup` carries one line per hierarchy: `0::<path>` for the
    unified (v2) hierarchy, and `<id>:<controllers>:<path>` for each v1
    controller set. Empty when nothing there speaks about CPU — and empty is
    also what a container reports, since the process sits at the root of its
    own cgroup namespace.
    """
    text = _read(proc)
    if text is None:
        return ""
    unified = ""
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3:
            continue
        hierarchy, controllers, path = fields
        if "cpu" in controllers.split(","):
            return path.strip("/")
        if hierarchy == "0":
            unified = path.strip("/")
    return unified


def _ratio(quota: str, period: str) -> float | None:
    try:
        limit, interval = int(quota), int(period)
    except ValueError:
        return None
    return limit / interval if limit > 0 and interval > 0 else None


def _read(path: Path) -> str | None:
    # a helper reading /sys and /proc must never raise: the files are absent on
    # most platforms, unreadable under some sandboxes, and this is a default
    try:
        return path.read_text().strip()
    except (OSError, ValueError):
        return None
