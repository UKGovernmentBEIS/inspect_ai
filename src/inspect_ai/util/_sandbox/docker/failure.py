"""Classification of `docker compose exec` results.

One exit code and one pair of streams carry two different outcomes: a failure
attributable to the caller's command, or a provider failure before the caller's
command was reached. Only the first is a result. Returning the second as an
`ExecResult` is what made a dead sandbox look to a model like ordinary command
output (#4709).

Telling them apart is a matter of who wrote the message, since the exit codes
collide. Exit 126 is the runtime refusing to exec a non-executable file *and*
a shell reporting the same about the model's own script; exit 127 is a missing
binary whether it is one Inspect injected or one the caller named.

Recognition is deliberately partial because the streams being matched can
also contain output from the caller's command. Broad matching could
misclassify a healthy sandbox as unavailable. Two consequences worth knowing:

- A launch failure is attributed to the sandbox only when the binary named is
  the wrapper `exec` injected. With no timeout there is no wrapper, so the two
  runc-reported cases go unrecognised.
- Only messages docker emits on the `compose exec` path are matched. Wordings
  that only a bare `docker exec` produces are left alone: they cannot reach us,
  and a model running docker inside its sandbox emits them verbatim. One
  collision is accepted: a model running `docker compose exec` against a
  stopped service of its *own* inner compose project emits the same wording we
  match, and nothing in the result tells the two apart. The cost is bounded —
  the model's real output is embedded in the tool error and the sample
  continues.
"""

import re
from typing import NamedTuple

from inspect_ai.util._subprocess import ExecResult

from ..environment import SandboxUnavailableError


class InjectedWrapper(NamedTuple):
    """Binary `exec` inserted ahead of the caller's command."""

    binary: str
    """The wrapper itself, e.g. `timeout`."""

    target: str
    """The binary the wrapper was asked to run, i.e. the caller's own."""


# compose has no running container to exec into. This is the only wording the
# `compose exec` path produces for it — the daemon's own "Error response from
# daemon: … is not running" comes from a bare `docker exec`, so matching it
# would buy nothing here while misreading a docker-in-docker model's output.
_NO_CONTAINER = re.compile(r'^service "[^"]*" is not running\b')

# containerd/runc could not start the process; it names the binary it tried
_RUNC_PREFIX = "oci runtime exec failed"
_RUNC_NOT_FOUND = re.compile(r'exec: "([^"]*)": executable file not found')

# the binary a `timeout`-style wrapper quotes in its complaint, verbatim as
# handed to it. GNU quotes with U+2018/U+2019, busybox with ASCII quotes.
# anchored to the colon that follows the name in both wordings, since a bare
# apostrophe also appears in prose ("can't execute 'bash': ...").
_WRAPPER_QUOTED = re.compile(r"[‘']([^’']*)[’']:")


def classify_exec_failure(
    result: ExecResult[str], *, wrapper: InjectedWrapper | None
) -> Exception | None:
    """Classify a `docker compose exec` result that did not succeed.

    Args:
        result: Result of the `docker compose exec` invocation.
        wrapper: Binary Inspect injected ahead of the caller's command, or
            `None` if it ran the command directly. A launch failure naming the
            wrapper means provider-required execution machinery is unavailable;
            one naming the caller's own binary is an ordinary result.

    Returns:
        An error to raise in place of returning `result`, or `None` when
        `result` is an ordinary command result and should be returned.
    """
    # a successful exec always ran the command
    if result.returncode == 0:
        return None

    stdout, stderr = result.stdout.strip(), result.stderr.strip()

    # docker reports its own failure on one stream and nothing on the other;
    # output on both means a process produced some of it. Which stream is not
    # something to rely on: runc writes to stdout, GNU timeout to stderr.
    if stdout and stderr:
        return None

    output = stdout or stderr
    if not output:
        return None

    # docker's exec stream uses CRLF; splitlines() handles both. every message
    # docker itself emits here is a single line and nothing else, so a phrase
    # arriving with company was produced by a process, not by docker.
    lines = output.splitlines()
    if len(lines) != 1:
        return None
    head = lines[0].strip().lower()

    # docker's shape exactly: the known wording as the whole line, and the
    # exit code compose uses for it. suffixes, extra lines and other codes
    # are model-producible; docker's own message never varies. (a false
    # negative from a docker version changing this is the original bug
    # returning for that version — loosen here if one ever does.)
    if result.returncode == 1 and _NO_CONTAINER.fullmatch(head):
        return SandboxUnavailableError(
            f"The sandbox is not running and cannot execute: {output}"
        )

    if head.startswith(_RUNC_PREFIX):
        # search the original line: the binary-name comparison is case-exact
        not_found = _RUNC_NOT_FOUND.search(lines[0])
        if not_found is not None:
            # our own wrapper has gone missing, so the provider could not reach
            # the caller's command. a binary the *caller* named is their problem,
            # and stays an ordinary result as it has always been. 127 is the
            # code runc reports exec-not-found with.
            if (
                result.returncode == 127
                and wrapper is not None
                and not_found.group(1) == wrapper.binary
            ):
                return SandboxUnavailableError(
                    "The sandbox could not execute the command because required "
                    f"execution machinery is unavailable: {output}"
                )
            return None
        if result.returncode == 126 and "permission denied" in head:
            return PermissionError(f"Permission denied executing command: {result}")
        return None

    # the wrapper launched but could not exec what we handed it, so the
    # sandbox's shell is unusable. requiring the quoted binary to be exactly
    # our target keeps a model's own `timeout ./script` out of this (the
    # wrapper quotes argv verbatim, so a mere substring match would let
    # `./bash_helper.sh` pass for `bash`). wordings differ — GNU says "failed
    # to run command", busybox "can't execute" — so match on the reporter and
    # the quoted binary rather than the phrasing between them.
    if (
        wrapper is not None
        and result.returncode == 126
        and head.startswith(f"{wrapper.binary}: ")
        and "permission denied" in output.lower()
    ):
        quoted = _WRAPPER_QUOTED.search(output)
        if quoted is not None and quoted.group(1) == wrapper.target:
            return PermissionError(f"Permission denied executing command: {result}")

    return None
