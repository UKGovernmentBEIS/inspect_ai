"""ACP-specific discovery primitives.

Schema layer over :mod:`inspect_ai._util.discovery` — adds the ACP
discovery directory, the per-eval-id socket path, the
:class:`TargetAddress` / :class:`DiscoveredEval` shapes, and the
``--server`` / ``--eval-id`` target-resolution policy used by the
stdio bridge and TUI client.

Generic process-liveness, socket utilities, and discovery-file
mechanics live in :mod:`inspect_ai._util.process`,
:mod:`inspect_ai._util.sockets`, and :mod:`inspect_ai._util.discovery`
respectively — import from those modules directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from inspect_ai._util.appdirs import inspect_data_dir
from inspect_ai._util.sockets import parse_host_port


def discovery_dir() -> Path:
    """The directory where discovery JSON files + default sockets live."""
    return inspect_data_dir("acp")


def default_socket_path(eval_id: str) -> Path:
    """Default AF_UNIX socket path for a given eval_id."""
    return discovery_dir() / f"{eval_id}.sock"


# ---------------------------------------------------------------------------
# Target resolution for client-side attachment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetAddress:
    """A connectable address for one running ACP server.

    Exactly one of ``socket_path`` / ``(host, port)`` is populated.
    The CLI bridge opens the appropriate kind of asyncio connection;
    the TUI client uses the same shape.
    """

    socket_path: Path | None = None
    host: str | None = None
    port: int | None = None
    eval_id: str | None = None
    """Owning eval id when resolved via discovery; ``None`` for ``--server`` overrides."""

    def describe(self) -> str:
        """Short human-readable address form (for stderr logging / errors)."""
        if self.socket_path is not None:
            return str(self.socket_path)
        if self.host is not None and self.port is not None:
            host = self.host
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            return f"{host}:{self.port}"
        return "<invalid>"


@dataclass(frozen=True)
class DiscoveredEval:
    """One entry from the discovery directory.

    Used by callers that want to enumerate live evals (e.g. the
    unified TUI picker).
    """

    eval_id: str
    started_at: float
    target: TargetAddress


class TargetResolutionError(Exception):
    """Raised when :func:`resolve_target` cannot pick a connectable target.

    The CLI layer catches this and prints ``str(exc)`` to stderr +
    exits non-zero. The message is the user-facing diagnostic; keep it
    actionable.
    """


def _target_from_discovery_data(data: dict[str, object]) -> TargetAddress | None:
    """Build a :class:`TargetAddress` from a discovery JSON dict.

    Returns ``None`` if the file is structurally invalid (missing both
    socket_path and host:port). Callers using this on stale files should
    treat ``None`` as "skip this entry."
    """
    eval_id_raw = data.get("eval_id")
    eval_id = str(eval_id_raw) if eval_id_raw is not None else None
    sock = data.get("socket_path")
    if sock:
        return TargetAddress(socket_path=Path(str(sock)), eval_id=eval_id)
    host = data.get("host")
    port = data.get("port")
    if host is not None and port is not None:
        try:
            return TargetAddress(host=str(host), port=int(port), eval_id=eval_id)  # type: ignore[call-overload]
        except (TypeError, ValueError):
            return None
    return None


def list_discovered_evals() -> list[DiscoveredEval]:
    """Enumerate alive ACP servers from the discovery directory.

    Sorted most-recently-started first. Stale files (dead PID,
    malformed JSON, missing fields) are silently skipped — same
    resilience contract as :func:`list_alive_discovery_entries`.

    Uses the shared :func:`list_alive_discovery_entries` helper to
    walk the directory + filter on liveness, then applies the
    ACP-specific schema (``socket_path`` OR ``host`` + ``port``,
    ``eval_id`` field) to convert to :class:`DiscoveredEval`.
    """
    from inspect_ai._util.discovery import list_alive_discovery_entries

    results: list[DiscoveredEval] = []
    for data in list_alive_discovery_entries(discovery_dir()):
        target = _target_from_discovery_data(data)
        if target is None:
            continue
        try:
            started_at = float(data.get("started_at", 0.0))
        except (TypeError, ValueError):
            started_at = 0.0
        eval_id = target.eval_id or ""
        if not eval_id:
            continue
        results.append(
            DiscoveredEval(eval_id=eval_id, started_at=started_at, target=target)
        )
    results.sort(key=lambda e: e.started_at, reverse=True)
    return results


def resolve_target(
    eval_id: str | None,
    server: str | None,
) -> tuple[TargetAddress, list[DiscoveredEval] | None]:
    """Pick a connectable target from --eval-id / --server / discovery.

    Returns ``(target, picked_from)`` where ``picked_from`` is the
    full candidate list when discovery had to disambiguate (so the
    CLI can log "picked X out of N" to stderr), else ``None``.

    Raises :class:`TargetResolutionError` when no reasonable choice
    exists. Precedence:

    1. ``server`` (explicit override) — never touches the discovery
       dir; useful for editor configs that hard-code an address or
       for connecting to a remote ACP server.
    2. ``eval_id`` — look up the entry whose ``eval_id`` matches.
       Error if no live eval has that id.
    3. Otherwise — pick the most-recently-started live eval. Error
       only when zero are alive.

    ``server`` and ``eval_id`` are mutually exclusive at the CLI
    layer (the click decorator rejects when both are provided); this
    function tolerates either order if both happen to be set, but
    callers should not rely on that.
    """
    if server:
        try:
            host_port = parse_host_port(server)
        except ValueError as exc:
            # Syntactically host:port but out-of-range port; surface as
            # a resolution error rather than letting it fall through to
            # UNIX-path interpretation (where the eventual bind/connect
            # would fail with a confusing path-not-found).
            raise TargetResolutionError(
                f"invalid --server value {server!r}: {exc}"
            ) from exc
        if host_port is not None:
            host, port = host_port
            return TargetAddress(host=host, port=port), None
        return TargetAddress(socket_path=Path(server)), None

    discovered = list_discovered_evals()

    if eval_id is not None:
        for entry in discovered:
            if entry.eval_id == eval_id:
                return entry.target, None
        raise TargetResolutionError(
            f"no running eval with id {eval_id!r} (checked {discovery_dir()})"
        )

    if not discovered:
        raise TargetResolutionError(
            f"no running evals found in {discovery_dir()}. "
            f"Start one with `inspect eval <task> --acp-server`."
        )

    # Most-recently-started wins; report ambiguity to the caller so the
    # CLI can surface a "picked X of N" notice on stderr.
    if len(discovered) == 1:
        return discovered[0].target, None
    return discovered[0].target, discovered
