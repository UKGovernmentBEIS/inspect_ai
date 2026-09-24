"""Load the log viewer's Content-Security-Policy from a built dist directory.

The viewer build emits its policy as `content-security-policy.json` rather
than baking it into `index.html` (the VS Code extension reads the same
`index.html` and delivers its own policy), so each host that serves the dist
delivers the policy itself. The file's `sha256` sources hash the inline
scripts of that same dist's `index.html`, so a policy is only valid for the
dist it was read from.
"""

import json
from pathlib import Path
from typing import Any

CSP_FILENAME = "content-security-policy.json"
CSP_VERSION = 1

# The host owns framing: `frame-ancestors` is ignored in a <meta> policy, and
# the view server appends its own.
_HOST_OWNED_DIRECTIVES = frozenset({"frame-ancestors"})


class ContentSecurityPolicyError(ValueError):
    """A viewer dist contains a malformed Content-Security-Policy file."""


def read_content_security_policy(dist_dir: Path) -> str | None:
    """Read the viewer Content-Security-Policy from a dist directory.

    Args:
        dist_dir: Local directory containing the built viewer (`index.html`).

    Returns:
        The policy string (directives in file order, each name followed by its
        space-separated sources, joined with `"; "`), or `None` if the dist
        has no policy file (a viewer built before the policy existed).

    Raises:
        ContentSecurityPolicyError: If the policy file is present but
            malformed. The dist is trusted build output, so this indicates a
            broken build rather than something to silently ignore.
    """
    policy_file = dist_dir / CSP_FILENAME
    if not policy_file.exists():
        return None

    try:
        data = json.loads(
            policy_file.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, ValueError) as ex:
        raise ContentSecurityPolicyError(
            f"Invalid viewer Content-Security-Policy file {policy_file}: {ex}"
        ) from ex

    try:
        return _policy_string(data)
    except ValueError as ex:
        raise ContentSecurityPolicyError(
            f"Invalid viewer Content-Security-Policy file {policy_file}: {ex}"
        ) from ex


def _policy_string(data: Any) -> str:
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")

    version = data.get("version")
    if type(version) is not int or version != CSP_VERSION:
        raise ValueError(f"unsupported version {version!r} (expected {CSP_VERSION})")

    directives = data.get("directives")
    if not isinstance(directives, dict) or not directives:
        raise ValueError("'directives' must be a non-empty object")

    seen: set[str] = set()
    parts: list[str] = []
    for name, sources in directives.items():
        _validate_token(name, "directive name")
        folded = name.lower()
        if folded in seen:
            raise ValueError(f"duplicate directive {name!r}")
        seen.add(folded)
        if folded in _HOST_OWNED_DIRECTIVES:
            raise ValueError(f"directive {name!r} is set by the host, not the dist")

        if not isinstance(sources, list) or not sources:
            raise ValueError(
                f"directive {name!r} must have a non-empty list of sources"
            )
        for source in sources:
            _validate_token(source, f"source in directive {name!r}")

        parts.append(" ".join([name, *sources]))

    return "; ".join(parts)


def _validate_token(value: Any, label: str) -> None:
    """Require a non-empty string of printable, non-space ASCII other than `;` and `,`.

    Whitespace would split a token, `;` would start a new directive, `,`
    would start a new policy, and control or non-ASCII characters can't be
    carried in a header value.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string, got {value!r}")
    if any(not 0x21 <= ord(char) <= 0x7E or char in ";," for char in value):
        raise ValueError(f"{label} {value!r} contains a disallowed character")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result
