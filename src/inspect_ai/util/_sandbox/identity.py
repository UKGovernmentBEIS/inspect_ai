import posixpath
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Literal, NamedTuple

from ._framework_operation import in_framework_sandbox_operation
from ._privileged import privileged_shell
from .context import (
    default_sandbox_environment,
    raise_no_sandbox,
    sandbox_default,
    sandbox_default_context_var,
    sandbox_environments_context_var,
)
from .environment import SandboxEnvironment, SandboxUserUnsupportedError
from .events import SandboxEnvironmentProxy


class SandboxIdentityError(RuntimeError):
    """Model-facing sandbox work cannot run as the current sandbox identity.

    Raised when scopes are nested, when a tool is configured to run as another
    user inside a scope, or when a tool cannot run as a user at all.
    """


@contextmanager
def sandbox_identity(
    user: str, *, cwd: str | None = None, sandbox: str = "default"
) -> Iterator[None]:
    """Run model-facing work in a sandbox as `user`.

    Inside the block, built-in tools that run commands in `sandbox` run them
    as `user`: `bash()`, `python()`, `grep()`, `list_files()`, `read_file()`,
    `bash_session()` and `text_editor()`. `bash()`, `python()`, `grep()`,
    `list_files()` and `read_file()` also start in `cwd`, a `bash_session()`
    shell created in the block starts (and restarts) there, and `text_editor()`
    resolves relative paths against it. A `bash_session()` shell created in the
    block works only with the sandbox tools server that created it, and needs
    inspect-sandbox-tools 1.3.0 or later. A tool configured with a different
    `user` raises `SandboxIdentityError`, and so do `computer()`, which
    cannot run as a user, and `skill()`, which does not
    yet install skills as a user. `exec_remote()` uses the
    scope's user and cwd when omitted and keeps explicit values. Other
    sandbox-tool launches inherit the scope's user when omitted; they keep
    their existing working-directory behavior.

    `bash()`, `python()`, `grep()`, `list_files()` and `read_file()` set `HOME`
    to the user's home from the sandbox's passwd database, looked up once per
    block. They keep the inherited `HOME` if the user has no passwd entry and
    raise `RuntimeError` if the entry has an empty home. `bash_session()`,
    `text_editor()` and `exec_remote()` set `HOME` only when switching user; if
    their tools process already runs as that user, they keep its inherited
    `HOME`.

    Inside the block `sandbox` is also the default sandbox (as with
    `sandbox_default()`), and tools that find their sandbox by injection use it.
    If code inside the block replaces the sample's sandbox environments with a
    set that does not list `sandbox`, those tools raise `SandboxIdentityError`.
    Tools given another sandbox by name keep that sandbox and its user.

    `SandboxEnvironment.exec()`, `read_file()` and `write_file()` calls on the
    sample's `sandbox` that name no user also run as `user`, so custom tools
    and scaffold code act as `user` with no change of their own. A call that
    names a user keeps it. Inspect's own sandbox operations (tool injection,
    sandbox services, checkpoints, in-loop scoring) keep the sandbox's default
    user. A provider whose `read_file()` or `write_file()` cannot take a user
    raises `SandboxUserUnsupportedError` for such a call rather than using the
    default user. Calls on the provider returned by `as_type()` do not take
    the scope's user. The scope's `cwd` does not apply to these calls.

    The scope is held in a context variable, so tasks started inside the block
    inherit it.

    A scope cannot be opened inside Inspect's own sandbox operations, which
    include in-loop scoring: a scorer called through `score()` (for example by
    `react(attempts=...)`) that opens a scope raises `SandboxIdentityError`.
    Inside those operations an omitted user means the sandbox's default user,
    so the scope would not apply.

    Args:
       user: User to run as: a username or a numeric uid. A `user:group`
          selector is not supported.
       cwd: Absolute working directory for the tools above and for
          `exec_remote()` commands that do not set one.
       sandbox: Name of the sandbox environment the identity applies to.

    Raises:
       SandboxIdentityError: If a scope is already active, or the block is
          opened inside one of Inspect's own sandbox operations (such as
          in-loop scoring).
       ValueError: If `user` is empty or contains `:`, `cwd` is not absolute, or
          `sandbox` is not one of the sample's environments.
       ProcessLookupError: If there are no sandboxes available.
    """
    if not user:
        raise ValueError("sandbox_identity() requires a user.")
    if ":" in user:
        raise ValueError(
            f"sandbox_identity() takes a username or a numeric uid, not '{user}'."
        )
    if cwd is not None and not posixpath.isabs(cwd):
        raise ValueError(f"sandbox_identity() requires an absolute cwd, not '{cwd}'.")
    if (outer := _sandbox_identity.get()) is not None:
        raise SandboxIdentityError(
            f"A sandbox identity scope for user '{outer.user}' is already active; "
            "sandbox identity scopes cannot be nested."
        )
    if in_framework_sandbox_operation():
        raise SandboxIdentityError(
            f"A sandbox identity scope for user '{user}' cannot be opened inside "
            "an Inspect framework sandbox operation such as in-loop scoring, where "
            "sandbox operations run as the sandbox's default user."
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

    token = _sandbox_identity.set(
        SandboxIdentityScope(user, cwd, name, environment, _ScopeHome())
    )
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
    identity = sandbox_identity_scope(env)
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


def sandbox_operation_user(env: SandboxEnvironment, user: str | None) -> str | None:
    """The user a sandbox operation on `env` runs as.

    Inside a `sandbox_identity()` scope for `env`, an omitted `user` becomes the
    scope's user, unless the call is part of a `framework_sandbox_operation()`.
    An explicit `user` is always kept.

    Args:
       env: Sandbox environment the operation runs in.
       user: User the caller asked for, if any.
    """
    if user is not None or in_framework_sandbox_operation():
        return user
    return sandbox_identity_user(env, None, strict=False)


def sandbox_file_user_params(
    env: SandboxEnvironment,
    operation: Literal["read_file", "write_file"],
    user: str | None,
) -> dict[str, Any]:
    """Keyword arguments that run `operation` on `env` as its operation user.

    The user is resolved with `sandbox_operation_user()`. No user gives no
    arguments, so the provider uses its default user.

    Args:
       env: Sandbox environment the operation runs in.
       operation: The file operation.
       user: User the caller asked for, if any.

    Raises:
       SandboxUserUnsupportedError: If there is a user and the provider's
          `operation` cannot take one. When the user came from the scope, the
          message names the scope.
    """
    resolved = sandbox_operation_user(env, user)
    if resolved is None:
        return {}
    if env._supports_file_user(operation):
        return {"user": resolved}
    provider = env
    while isinstance(provider, SandboxEnvironmentProxy):
        provider = provider._sandbox
    method = f"{type(provider).__name__}.{operation}"
    if user is None and (identity := sandbox_identity_scope(env)) is not None:
        verb = "read" if operation == "read_file" else "write"
        raise SandboxUserUnsupportedError(
            f"{method} does not support a user, so it cannot run as "
            f"{resolved!r} inside the sandbox identity scope for sandbox "
            f"{identity.sandbox!r}. Update the sandbox provider to support file "
            f"users, or {verb} the file with exec()."
        )
    raise SandboxUserUnsupportedError(
        f"{method} does not support user={resolved!r}. "
        "Update the sandbox provider to support file users."
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
    identity = sandbox_identity_scope(env)
    return identity.cwd if identity is not None else None


async def sandbox_identity_vars(
    env: SandboxEnvironment, timeout: int | None
) -> dict[str, str] | None:
    """Environment variables for a command the scope's user runs in `env`.

    None outside a `sandbox_identity()` scope for `env`. Inside one, `HOME` set
    to the user's home directory from the sandbox's passwd database, or None if
    it has no entry for the user. The lookup runs once per scope and is cached;
    concurrent first calls may each run it, which is harmless. A lookup that
    fails, times out or is cancelled is not cached, and neither is an entry
    with an empty home directory.

    Args:
       env: Sandbox environment the command runs in.
       timeout: Timeout (in seconds) of the caller's command, if any. The lookup
          times out after this or `PASSWD_LOOKUP_TIMEOUT`, whichever is shorter.

    Raises:
       RuntimeError: If the lookup command fails, or the user's passwd entry
          has an empty home directory.
       TimeoutError: If the lookup times out.
    """
    identity = sandbox_identity_scope(env)
    if identity is None:
        return None
    if not identity.home.resolved:
        lookup_timeout = min(timeout or PASSWD_LOOKUP_TIMEOUT, PASSWD_LOOKUP_TIMEOUT)
        identity.home.value = await _passwd_home(env, identity.user, lookup_timeout)
        identity.home.resolved = True
    return {"HOME": identity.home.value} if identity.home.value is not None else None


PASSWD_LOOKUP_TIMEOUT = 30
"""Longest time (in seconds) the home directory lookup may take."""

# Prints the home directory of the user named (or numbered) $1, followed by a
# newline (a bare newline when the home field is empty), or nothing when the
# passwd database has no entry for it; any other failure, an entry without
# exactly seven fields included, exits non-zero. Uses getent so NSS sources
# count (exit status 2 means no entry), and reads /etc/passwd on images without
# getent. Like getent, the fallback matches an all-digit $1 against the uid
# field as a number and anything else against the name field, and like glibc
# it skips lines whose first non-blank character is #. It fails unless
# /etc/passwd is a readable regular file. Entries are split with parameter
# expansion, which cannot fail.
_PASSWD_HOME_SCRIPT = """
print_home() {
    case $1 in
        *:*:*:*:*:*:*:*) ;;
        *:*:*:*:*:*:*)
            rest=$1
            for _ in 1 2 3 4 5; do rest=${rest#*:}; done
            printf '%s\\n' "${rest%%:*}"
            exit 0
            ;;
    esac
    echo "$2 has a malformed entry for the user" >&2
    exit 1
}
if command -v getent >/dev/null 2>&1; then
    entry=$(getent passwd "$1")
    status=$?
    [ "$status" -eq 2 ] && exit 0
    if [ "$status" -ne 0 ]; then
        echo "getent passwd exited with status $status" >&2
        exit 1
    fi
    print_home "$entry" "getent passwd"
fi
if [ ! -f /etc/passwd ] || [ ! -r /etc/passwd ]; then
    echo "no getent and /etc/passwd is not a readable file" >&2
    exit 1
fi
case $1 in
    *[!0-9]*) by_uid=false ;;
    *) by_uid=true ;;
esac
while IFS= read -r entry || [ -n "$entry" ]; do
    case ${entry#"${entry%%[! \t]*}"} in
        "#"*) continue ;;
    esac
    if [ "$by_uid" = true ]; then
        uid=${entry#*:*:}
        uid=${uid%%:*}
        case $uid in
            "" | *[!0-9]*) continue ;;
        esac
        [ "$uid" -eq "$1" ] 2>/dev/null || continue
    else
        [ "${entry%%:*}" = "$1" ] || continue
    fi
    print_home "$entry" /etc/passwd
done < /etc/passwd
"""


async def _passwd_home(env: SandboxEnvironment, user: str, timeout: int) -> str | None:
    """The home directory of `user` in the passwd database of `env`, if any.

    The path is kept exactly as the passwd entry gives it, whitespace included.
    The lookup runs in `/`, so it does not depend on the provider's default
    working directory.

    Raises:
       RuntimeError: If the lookup fails or the entry's home directory is empty.
    """
    result = await privileged_shell(
        env,
        _PASSWD_HOME_SCRIPT,
        user,
        user=None,
        cwd="/",
        timeout=timeout,
        timeout_retry=False,
    )
    if not result.success:
        error = result.stderr.strip() or f"exit status {result.returncode}"
    elif not result.stdout:
        return None
    elif home := result.stdout.removesuffix("\n"):
        return home
    else:
        error = "its passwd entry has an empty home directory"
    raise RuntimeError(
        f"Could not look up the home directory of sandbox user '{user}': {error}"
    )


def sandbox_identity_active(env: SandboxEnvironment | None = None) -> bool:
    """Whether a `sandbox_identity()` scope is active.

    Args:
       env: Only report a scope for this sandbox environment.
    """
    identity = _sandbox_identity.get()
    return identity is not None and (
        env is None or _same_sandbox(identity.environment, env)
    )


def sandbox_identity_environment() -> SandboxEnvironment | None:
    """The sandbox environment of the active scope, if any.

    For tools that find their sandbox by injection. The scope's environment must
    still be one of the current context's environments: code that replaces the
    environment map inside the scope (as an inspect_swarm member does) can leave
    it out, or expose it by name only.

    Raises:
       SandboxIdentityError: If the current context does not list the scope's
          environment.
    """
    identity = _sandbox_identity.get()
    if identity is None:
        return None
    environments = sandbox_environments_context_var.get(None) or {}
    if not any(
        _same_sandbox(env, identity.environment) for env in environments.values()
    ):
        raise SandboxIdentityError(
            f"The sandbox identity scope for '{identity.user}' is on sandbox "
            f"'{identity.sandbox}', which the current sandbox context does not "
            "offer to tools that find their sandbox by injection."
        )
    return identity.environment


def check_sandbox_identity_supported(env: SandboxEnvironment, tool: str) -> None:
    """Refuse a tool that cannot run as a user inside a scope for `env`."""
    if (identity := sandbox_identity_scope(env)) is not None:
        raise SandboxIdentityError(
            f"The {tool} tool cannot run as a user, so it cannot run inside the "
            f"sandbox identity scope for '{identity.user}'."
        )


class _ScopeHome:
    """Cache for the home directory of a scope's user."""

    def __init__(self) -> None:
        self.resolved = False
        self.value: str | None = None


class SandboxIdentityScope(NamedTuple):
    """An active `sandbox_identity()` scope."""

    user: str
    cwd: str | None
    sandbox: str
    """Name of the sandbox environment."""
    environment: SandboxEnvironment
    home: _ScopeHome
    """The user's home directory, looked up on first use."""


def sandbox_identity_scope(env: SandboxEnvironment) -> SandboxIdentityScope | None:
    """The active scope for `env`, if any.

    For tools that cache sandbox state across calls, so they can tell whether a
    later call runs in the same scope.
    """
    identity = _sandbox_identity.get()
    if identity is not None and _same_sandbox(identity.environment, env):
        return identity
    return None


def _same_sandbox(a: SandboxEnvironment, b: SandboxEnvironment) -> bool:
    """Whether `a` and `b` are views of one sandbox.

    A sample's environments are event-recording proxies, and `as_type()` returns
    the provider object behind one.
    """
    while isinstance(a, SandboxEnvironmentProxy):
        a = a._sandbox
    while isinstance(b, SandboxEnvironmentProxy):
        b = b._sandbox
    return a is b


_sandbox_identity: ContextVar[SandboxIdentityScope | None] = ContextVar(
    "sandbox_identity", default=None
)
