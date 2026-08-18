"""Restic inside an inspect sandbox: inject binary, init repo, backup, egress.

Composes the generic :mod:`inspect_ai.util._restic` primitives with
:class:`~inspect_ai.util._sandbox.environment.SandboxEnvironment` to
run restic against an inspect-managed sandbox container.

- :mod:`.repo` — inject the binary + init / backup the in-sandbox repo.
- :mod:`.egress` — ship pack files out (2-phase manifest) and ingress
  a host-side repo back in on resume.
"""

from .egress import egress_sandbox, ingress_sandbox
from .repo import init_sandbox_repo, inject_restic, run_sandbox_backup

__all__ = [
    "egress_sandbox",
    "ingress_sandbox",
    "init_sandbox_repo",
    "inject_restic",
    "run_sandbox_backup",
]
