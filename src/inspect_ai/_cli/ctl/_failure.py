"""The ``--json`` error envelope for terminal CLI failures.

See the comment below for the agent output contract this implements.
"""

from __future__ import annotations

import functools
import inspect
import json as json_lib
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Literal, NamedTuple, NoReturn, ParamSpec, TypeVar

import click
import httpx

from ._render import _echo, _echo_raw

#
# The error-path half of the agent output contract (see "Agent output
# contract" in design/ctl/control-channel.md): the success path is enveloped
# (`{as_of, ...}` reads, `{target, applied, ...}` mutations), so a failure
# surfacing stderr prose or a traceback on a --json invocation would send
# agents straight back to the string-scraping the JSON-first rule exists to
# prevent. On --json, every terminal failure emits
# `{"error": {kind, exception, message, status}}` on stdout, with the exit
# code still non-zero; human (non---json) output is unchanged.
#
# Consequently, every terminal error site in this package must raise
# _CtlFailure — usually via _fail() — never a bare click.exceptions.Exit:
# _structured_failures deliberately passes a plain Exit through un-enveloped
# (it is click control flow, e.g. --help), so a bare Exit at an error site
# silently breaks the contract (issue #69 — the config version gates did
# exactly that). test_no_bare_click_exit_in_ctl_error_sites enforces this.


# The envelope's closed `kind` vocabulary (the field agents branch on).
# Typed as a Literal so mypy rejects a typo'd kind at a raise site rather
# than shipping it as a new vocabulary entry.
_ErrorKind = Literal[
    "busy",
    "connect_timeout",
    "read_timeout",
    "connect_error",
    "not_found",
    "ambiguous",
    "http_error",
    "invalid_request",
    "invalid_response",
    "internal",
]


class _CtlFailure(click.exceptions.Exit):
    """A terminal ctl failure carrying the ``--json`` error envelope fields.

    Subclasses :class:`click.exceptions.Exit` (code 1) so a path that never
    passes through :func:`_structured_failures` still exits non-zero exactly
    as before. Raisers echo their human prose to stderr first (unchanged in
    both output modes — stderr stays narration); ``message`` must therefore
    be self-contained, since the envelope is all a ``--json`` consumer reads
    (e.g. the ambiguity error folds its candidate ids into it rather than
    pointing at the stderr table).
    """

    def __init__(
        self,
        kind: _ErrorKind,
        message: str,
        *,
        exception: str | None = None,
        status: int | None = None,
        missing_route: bool = False,
    ) -> None:
        super().__init__(1)
        self.kind = kind
        self.message = message
        self.exception = exception
        self.status = status
        # a router 404 (endpoint absent — older server) rather than an
        # entity 404; classification for callers that must tell the two
        # apart (e.g. the bulk-requeue sweep aborts on it), not an
        # envelope field
        self.missing_route = missing_route
        self._emitted = False

    @classmethod
    def from_exception(cls, message: str, exc: BaseException) -> "_CtlFailure":
        """Build a failure whose kind/status derive from ``exc``."""
        kind, status = _classify(exc)
        return cls(kind, message, exception=_exception_name(exc), status=status)

    def emit(self) -> None:
        """Print the stdout envelope (idempotent — nested wrappers can't double-print)."""
        if self._emitted:
            return
        self._emitted = True
        envelope = {
            "error": {
                "kind": self.kind,
                "exception": self.exception,
                "message": self.message,
                "status": self.status,
            }
        }
        _echo_raw(json_lib.dumps(envelope, indent=2))


def _fail(
    kind: _ErrorKind,
    message: str,
    *,
    exception: str | None = None,
    status: int | None = None,
    missing_route: bool = False,
) -> NoReturn:
    """Echo ``message`` to stderr and raise the matching :class:`_CtlFailure`.

    The standard shape for a terminal error site: the same self-contained
    message serves as both the human stderr prose and the envelope
    ``message``. Sites that interleave extra stderr output between the echo
    and the raise (warnings, a candidates table) or derive the failure from
    an exception (``raise ... from exc``) construct :class:`_CtlFailure`
    directly instead.
    """
    _echo(message, err=True)
    raise _CtlFailure(
        kind, message, exception=exception, status=status, missing_route=missing_route
    )


class _FailureKind(NamedTuple):
    """Result of :func:`_classify` (envelope ``kind`` + HTTP status when applicable)."""

    kind: _ErrorKind
    status: int | None


def _classify(exc: BaseException) -> _FailureKind:
    """Coarse machine-branchable envelope ``kind`` for a transport exception.

    The vocabulary is deliberately small — an agent branches on ``kind``
    rather than regexing ``exception``/``message``: ``connect_timeout`` /
    ``read_timeout`` (single-shot timeouts; retry-exhausted timeouts are
    ``busy`` — see :func:`_unreachable_failure`), ``connect_error``
    (refused/reset — the process is likely gone), ``not_found`` /
    ``http_error`` (non-2xx, ``status`` carries the code),
    ``invalid_response`` (undecodable body), ``internal`` (anything else).
    Timeouts test before :class:`httpx.TransportError`, which subsumes them.
    """
    if isinstance(exc, httpx.ConnectTimeout):
        return _FailureKind("connect_timeout", None)
    if isinstance(exc, httpx.TimeoutException):
        return _FailureKind("read_timeout", None)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return _FailureKind("not_found" if status == 404 else "http_error", status)
    if isinstance(exc, (httpx.TransportError, OSError)):
        return _FailureKind("connect_error", None)
    if isinstance(exc, ValueError):
        return _FailureKind("invalid_response", None)
    return _FailureKind("internal", None)


def _exception_name(exc: BaseException) -> str:
    """Exception class for the envelope, package-qualified (``httpx.ReadTimeout``).

    The top-level package (not the defining module) qualifies the name — a
    ``httpx._exceptions.ReadTimeout`` spelling would leak a private module
    path that agents would then match on.
    """
    cls = type(exc)
    package = cls.__module__.partition(".")[0]
    if package == "builtins":
        return cls.__qualname__
    return f"{package}.{cls.__qualname__}"


@contextmanager
def _structured_failures(as_json: bool) -> Iterator[None]:
    """Emit the ``--json`` error envelope for any terminal failure inside.

    Error sites raise :class:`_CtlFailure` (after echoing their stderr
    prose) to carry the structured fields here; an unexpected exception
    still gets an envelope (kind ``internal``), with its traceback preserved
    on stderr for debugging. Other click control-flow exceptions (a plain
    ``Exit``, usage errors, Ctrl+C) pass through untouched — which is why an
    error site must never raise a bare ``Exit`` (see the module comment).
    """
    if not as_json:
        yield
        return
    try:
        yield
    except _CtlFailure as exc:
        exc.emit()
        raise
    except (click.exceptions.Exit, click.ClickException, click.exceptions.Abort):
        raise
    except Exception as exc:
        _echo(traceback.format_exc(), err=True, nl=False)
        _CtlFailure(
            "internal",
            str(exc) or _exception_name(exc),
            exception=_exception_name(exc),
        ).emit()
        raise click.exceptions.Exit(code=1) from exc


_P = ParamSpec("_P")
_T = TypeVar("_T")


def _envelope_failures(fn: Callable[_P, None]) -> Callable[_P, None]:
    """Wrap a command runner in :func:`_structured_failures`.

    Reads the runner's ``as_json`` argument off the bound call, so the
    wrapper needs no per-runner plumbing. Every runner must take an
    ``as_json`` parameter —
    enforced at decoration time so a missing/renamed parameter fails at
    import rather than silently reverting that command to unstructured
    failures.
    """
    signature = inspect.signature(fn)
    if "as_json" not in signature.parameters:
        raise TypeError(
            f"{fn.__name__} must take an as_json parameter to use @_envelope_failures"
        )

    @functools.wraps(fn)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        as_json = bool(bound.arguments["as_json"])
        with _structured_failures(as_json):
            fn(*args, **kwargs)

    return wrapper
