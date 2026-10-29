from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, NamedTuple

from .context import (
    default_sandbox_environment,
    raise_no_sandbox,
    sandbox_default,
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from .environment import SandboxEnvironment


class SandboxIdentityError(RuntimeError):
    """Model-facing sandbox work cannot run as the current sandbox identity.

    Raised when scopes are nested, when a tool is configured to run as another
    user inside a scope, or when a tool cannot run as a user at all.
    """


@contextmanager
def sandbox_identity(
    user: str, *, cwd: str | None = None, sandbox: str = "default"
) -> Iterator[None]:
    """Run model-facing work in a sandbox as `user`, starting in `cwd`.

    Inside the block, built-in tools that run commands in `sandbox` run them
    as `user`: `bash()`, `python()`, `grep()`, `list_files()`, `read_file()`,
    `skill()`, `bash_session()` and `text_editor()`. The exec-based ones also
    start in `cwd`. A tool configured with a different `user` raises
    `SandboxIdentityError`, and so do `computer()` and `web_browser()`, which
    cannot run as a user. `exec_remote()` and the sandbox tools' launches use
    `user` and `cwd` when they are not given, and keep them when they are.

    Inside the block `sandbox` is also the default sandbox (as with
    `sandbox_default()`), and tools that find their sandbox by injection use it.
    Tools given another sandbox by name keep that sandbox and its user.
    `SandboxEnvironment.exec()`, `read_file()` and `write_file()` themselves are
    unchanged, so custom tools that call them run as the sandbox's default user
    unless they resolve their user with `sandbox_identity_user()`.

    The scope is held in a context variable, so tasks started inside the block
    inherit it.

    Args:
       user: User to run as.
       cwd: Working directory for commands that do not set one.
       sandbox: Name of the sandbox environment the identity applies to.

    Raises:
       SandboxIdentityError: If a scope is already active.
       ValueError: If `user` is empty or `sandbox` is not one of the sample's
          environments.
       ProcessLookupError: If there are no sandboxes available.
    """
    if not user:
        raise ValueError("sandbox_identity() requires a user.")
    if (outer := _sandbox_identity.get()) is not None:
        raise SandboxIdentityError(
            f"A sandbox identity scope for user '{outer.user}' is already active; "
            "sandbox identity scopes cannot be nested."
        )
    environments = sandbox_environments_context_var.get(None)
    if not environments:
        raise_no_sandbox()
    if sandbox == "default":
        name = sandbox_default_context_var.get()
        environment = default_sandbox_environment(environments)
    elif sandbox in environments:
        name = sandbox
        environment = environments[sandbox]
    else:
        raise ValueError(
            f"SandboxEnvironment '{sandbox}' is not a recognized environment name."
            f" Available environments: {', '.join(environments)}."
        )

    token = _sandbox_identity.set(_SandboxIdentity(user, cwd, environment))
    try:
        with sandbox_default(name):
            yield
    finally:
        _sandbox_identity.reset(token)


def sandbox_identity_user(
    env: SandboxEnvironment, user: str | None, *, strict: bool
) -> str | None:
    """The user a command in `env` runs as.

    Outside a `sandbox_identity()` scope, or for an environment other than the
    scope's, `user` is returned unchanged. Inside a scope for `env`, `None`
    becomes the scope's user. Another explicit user is kept when `strict` is
    False and raises `SandboxIdentityError` when `strict` is True.

    Tools that run model-chosen commands resolve with `strict=True`.

    Args:
       env: Sandbox environment the command runs in.
       user: User the caller asked for, if any.
       strict: Raise rather than keep a user other than the scope's.

    Raises:
       SandboxIdentityError: If `strict` and `user` is not the scope's user.
    """
    identity = _identity_for(env)
    if identity is None:
        return user
    if user is None or user == identity.user:
        return identity.user
    if not strict:
        return user
    raise SandboxIdentityError(
        f"A tool configured to run as '{user}' cannot run inside the sandbox "
        f"identity scope for '{identity.user}'."
    )


def sandbox_identity_cwd(env: SandboxEnvironment, cwd: str | None) -> str | None:
    """The working directory for a command in `env`.

    An explicit `cwd` wins. Otherwise the working directory of the
    `sandbox_identity()` scope for `env`, if any.

    Args:
       env: Sandbox environment the command runs in.
       cwd: Working directory the caller asked for, if any.
    """
    if cwd is not None:
        return cwd
    identity = _identity_for(env)
    return identity.cwd if identity is not None else None


def sandbox_identity_active(env: SandboxEnvironment | None = None) -> bool:
    """Whether a `sandbox_identity()` scope is active.

    Args:
       env: Only report a scope for this sandbox environment.
    """
    identity = _sandbox_identity.get()
    return identity is not None and (env is None or identity.environment is env)


def sandbox_identity_environment() -> SandboxEnvironment | None:
    """The sandbox environment of the active scope, if any."""
    identity = _sandbox_identity.get()
    return identity.environment if identity is not None else None


def check_sandbox_identity_supported(env: SandboxEnvironment, tool: str) -> None:
    """Refuse a tool that cannot run as a user inside a scope for `env`."""
    if (identity := _identity_for(env)) is not None:
        raise SandboxIdentityError(
            f"{tool}() cannot run as a user, so it cannot run inside the sandbox "
            f"identity scope for '{identity.user}'."
        )


class _SandboxIdentity(NamedTuple):
    user: str
    cwd: str | None
    environment: SandboxEnvironment


def _identity_for(env: SandboxEnvironment) -> _SandboxIdentity | None:
    identity = _sandbox_identity.get()
    return identity if identity is not None and identity.environment is env else None


_sandbox_identity: ContextVar[_SandboxIdentity | None] = ContextVar(
    "sandbox_identity", default=None
)
