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

Finding the quota means finding the hierarchy that enforces it, and that is a
question for the mount table rather than for directory names: a cgroup v1
hierarchy may be mounted anywhere under any name, cgroup v2 is a single
hierarchy that may equally be mounted anywhere, and a directory called ``cpu``
under a v2 mount is an ordinary child cgroup whose quota binds somebody else.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

CGROUP_ROOT = Path("/sys/fs/cgroup")
"""Conventional cgroup mount point, consulted only when the mount table is silent."""

PROC_SELF_CGROUP = Path("/proc/self/cgroup")
"""Which cgroup this process is in, relative to its hierarchy's root."""

PROC_SELF_MOUNTINFO = Path("/proc/self/mountinfo")
"""Mount table: where each cgroup hierarchy is mounted, and which version it is."""


class CgroupHierarchy(NamedTuple):
    """A mounted cgroup hierarchy that carries the `cpu` controller."""

    version: int
    """1 for a per-controller hierarchy, 2 for the unified one."""

    mountpoint: Path
    """Where the hierarchy is mounted in this process's mount namespace."""

    mount_root: str
    """The hierarchy path `mountpoint` exposes, `/` for the hierarchy entire."""


def effective_cpu_count() -> int:
    """Processors this process may actually use (never less than one).

    Narrows `os.cpu_count()` by the CPU set the process is pinned to and by the
    cgroup CPU quota in force, neither of which `os.cpu_count()` reports. A
    fractional quota rounds *down*: the number is used to size concurrency, and
    half a processor does not run another unit of work.

    Deliberately not memoized. Both inputs are live kernel state that changes
    under a running process (`docker update --cpus`, a Kubernetes in-place
    resize, `taskset -p`), and a value frozen at first call would answer for
    every later eval in the process. Each call is a few small reads of `/proc`
    and `/sys`, against call sites that size a limiter or spawn a process.
    """
    count = float(_available_cpus())
    quota = cgroup_cpu_quota()
    if quota is not None:
        count = min(count, quota)
    return max(1, int(count))


def cgroup_cpu_quota(
    root: Path | None = None, proc: Path | None = None, mounts: Path | None = None
) -> float | None:
    """Processors the cgroup this process belongs to may use.

    `None` when no quota applies, which is the answer on an unconstrained host
    and on any platform without a cgroup filesystem.

    Args:
      root: Cgroup mount point to fall back on when `mounts` names no cgroup
        mount at all (defaults to `CGROUP_ROOT`).
      proc: File naming this process's own cgroup (defaults to `PROC_SELF_CGROUP`).
      mounts: Mount table to resolve the hierarchy from (defaults to
        `PROC_SELF_MOUNTINFO`).
    """
    hierarchy = _cpu_hierarchy(
        PROC_SELF_MOUNTINFO if mounts is None else mounts,
        CGROUP_ROOT if root is None else root,
    )
    if hierarchy is None:
        return None

    relative = _own_cgroup(
        PROC_SELF_CGROUP if proc is None else proc, hierarchy.version
    )
    quotas = [
        quota
        for directory in _cgroup_dirs(hierarchy, relative)
        if (quota := _quota_at(directory, hierarchy.version)) is not None
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


def _cpu_hierarchy(mounts: Path, root: Path) -> CgroupHierarchy | None:
    """The mounted hierarchy whose files state this process's CPU quota.

    A controller lives on exactly one hierarchy, so a v1 mount carrying `cpu`
    settles it: the unified hierarchy alongside it (a "hybrid" system mounts
    both) does not have the controller and has nothing to say about CPU.
    """
    unified: CgroupHierarchy | None = None
    for line in (_read(mounts) or "").splitlines():
        hierarchy = _cgroup_mount(line)
        if hierarchy is None:
            continue
        if hierarchy.version == 1:
            return hierarchy
        unified = unified or hierarchy
    return unified or _hierarchy_at(root)


def _cgroup_mount(line: str) -> CgroupHierarchy | None:
    """The cgroup hierarchy one `/proc/self/mountinfo` line mounts, if any.

    Fields are `id parent major:minor root mountpoint options...` up to a `-`
    separator, then `fstype source super-options` — `cgroup2` for the unified
    hierarchy, `cgroup` plus a `cpu` super-option for the v1 controller.
    """
    fields = line.split()
    try:
        separator = fields.index("-", 6)
    except ValueError:
        return None
    if len(fields) < separator + 4:
        return None
    mount_root, mountpoint = _unescape(fields[3]), Path(_unescape(fields[4]))
    fstype, options = fields[separator + 1], fields[separator + 3]
    if fstype == "cgroup2":
        return CgroupHierarchy(2, mountpoint, mount_root)
    if fstype == "cgroup" and "cpu" in options.split(","):
        return CgroupHierarchy(1, mountpoint, mount_root)
    return None


def _hierarchy_at(root: Path) -> CgroupHierarchy | None:
    """Which hierarchy is mounted at `root`, when the mount table is unavailable.

    Version first, name second, so that a v2 child cgroup named `cpu` is never
    mistaken for the v1 controller directory of the same name: `cgroup.controllers`
    marks a v2 cgroup, and `cpu.max` marks one that a container namespace has put
    at the root of the filesystem.
    """
    if (root / "cgroup.controllers").exists() or (root / "cpu.max").exists():
        return CgroupHierarchy(2, root, "/")
    for child in _children(root):
        # v1 comounts controllers under a directory naming all of them
        if "cpu" in child.name.split(","):
            return CgroupHierarchy(1, child, "/")
    if (root / "cpu.cfs_quota_us").exists():
        return CgroupHierarchy(1, root, "/")
    return None


def _cgroup_dirs(hierarchy: CgroupHierarchy, relative: str) -> Iterator[Path]:
    """Directories that might state a CPU quota for this process.

    Inside a container the container's own cgroup is mounted at the root of the
    hierarchy, so the mount point is usually where the limit is. When the host's
    hierarchy is visible instead (a pod on a cluster that shares the host's
    cgroup namespace, a systemd unit with a `CPUQuota=`), the limit is on the
    nested directory `/proc/self/cgroup` names, or on one of its ancestors.
    """
    parts = _within_mount(hierarchy.mount_root, relative)
    for depth in range(len(parts), -1, -1):
        yield hierarchy.mountpoint.joinpath(*parts[:depth])


def _within_mount(mount_root: str, relative: str) -> list[str]:
    """`relative` rewritten against the mount point that exposes `mount_root`.

    A hierarchy is not always mounted at its own root: a runtime that hands a
    container its own cgroup mounts that subtree, and the path
    `/proc/self/cgroup` reports is still the one the subtree is rooted at.
    """
    prefix = [part for part in mount_root.split("/") if part]
    parts = [part for part in relative.split("/") if part]
    if not prefix:
        return parts
    # not below the mount root means this cgroup is not visible here at all,
    # leaving the mount point itself as the only directory worth reading
    return parts[len(prefix) :] if parts[: len(prefix)] == prefix else []


def _quota_at(directory: Path, version: int) -> float | None:
    """The CPU quota one cgroup directory states, in processors."""
    if version == 2:
        # cgroup v2 puts both halves in one file, and spells "uncapped" as the
        # literal `max` in place of the quota
        fields = (_read(directory / "cpu.max") or "").split()
        return _ratio(fields[0], fields[1]) if len(fields) == 2 else None

    # cgroup v1 uses two files, and spells "uncapped" as a quota of -1
    quota = _read(directory / "cpu.cfs_quota_us")
    period = _read(directory / "cpu.cfs_period_us")
    return None if quota is None or period is None else _ratio(quota, period)


def _own_cgroup(proc: Path, version: int) -> str:
    """This process's cgroup path, relative to its hierarchy's root.

    `/proc/self/cgroup` carries one line per hierarchy: `0::<path>` for the
    unified (v2) hierarchy, and `<id>:<controllers>:<path>` for each v1
    controller set. Empty when nothing there speaks about CPU — and empty is
    also what a container reports, since the process sits at the root of its
    own cgroup namespace.
    """
    text = _read(proc)
    if text is None:
        return ""
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3:
            continue
        hierarchy, controllers, path = fields
        ours = hierarchy == "0" if version == 2 else "cpu" in controllers.split(",")
        if ours:
            return path.strip("/")
    return ""


def _ratio(quota: str, period: str) -> float | None:
    try:
        limit, interval = int(quota), int(period)
    except ValueError:
        return None
    return limit / interval if limit > 0 and interval > 0 else None


def _unescape(field: str) -> str:
    # mountinfo octal-escapes the characters that would otherwise end a field,
    # the escape for backslash itself last so its payload is not re-read
    for escape, character in (
        ("\\040", " "),
        ("\\011", "\t"),
        ("\\012", "\n"),
        ("\\134", "\\"),
    ):
        field = field.replace(escape, character)
    return field


def _children(directory: Path) -> list[Path]:
    # sorted so that a hierarchy mounted twice resolves the same way each time
    try:
        return sorted(child for child in directory.iterdir() if child.is_dir())
    except OSError:
        return []


def _read(path: Path) -> str | None:
    # a helper reading /sys and /proc must never raise: the files are absent on
    # most platforms, unreadable under some sandboxes, and this is a default
    try:
        return path.read_text().strip()
    except (OSError, ValueError):
        return None
