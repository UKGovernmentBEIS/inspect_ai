#!/usr/bin/env python3
"""Markdown body for the sticky PR comment on suppression ledger changes.

Prints nothing when the ledger is unchanged.

Usage: python3 suppressions_pr_delta.py <base.json> <head.json>
"""

import html
import json
import sys
from pathlib import Path
from typing import TypeGuard

# Sibling-script import: resolves because sys.path[0] is this script's
# directory when invoked by path (as the workflow does); the test suite
# pre-registers the module in sys.modules instead.
from check_suppressions import Delta, Ledger, diff_ledgers, totals

MARKER = "<!-- suppressions-delta -->"


def _is_ledger(data: object) -> TypeGuard[Ledger]:
    """Whether data has the shape flatten/totals rely on (see Ledger).

    `type(...) is int`, not isinstance: bool subclasses int, and a JSON
    boolean is not a count.
    """
    return isinstance(data, dict) and all(
        isinstance(rules, dict)
        and all(
            isinstance(tally, dict)
            and "count" in tally
            and all(type(value) is int for value in tally.values())
            for tally in rules.values()
        )
        for rules in data.values()
    )


def _load(path: str) -> Ledger | None:
    """The ledger at path, or None when unreadable or not ledger-shaped.

    The PR side is author-controlled data, so a broken ledger must degrade
    into a reportable value rather than crash the comment job. ValueError
    covers json.JSONDecodeError and the UnicodeDecodeError of a non-UTF-8
    file; RecursionError is json.loads on pathologically deep nesting.
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError, RecursionError):
        return None
    return data if _is_ledger(data) else None


def _cell(value: str) -> str:
    """Render untrusted ledger text safely inside a Markdown table cell."""
    value = value.replace("\r", " ").replace("\n", " ")
    return f"<code>{html.escape(value).replace('|', '&#124;')}</code>"


def render(base: Ledger, head: Ledger) -> str | None:
    """The comment body for a base -> head ledger change, or None if none.

    An undescribed-only change (a reason added or removed) renders too:
    otherwise such a ledger diff would produce nothing and the workflow
    would falsely reset the sticky comment to "no longer changes the
    ledger".
    """
    rows = diff_ledgers(base, head)
    if not rows:
        return None

    total_before, undescribed_before = totals(base)
    total_after, undescribed_after = totals(head)
    delta = total_after - total_before
    undescribed_delta = undescribed_after - undescribed_before
    needs_attention = delta > 0 or undescribed_delta > 0
    if undescribed_delta > 0 and delta <= 0:
        heading = (
            f"⚠️ Reason-less suppressions grew: {undescribed_before} → "
            f"{undescribed_after} (+{undescribed_delta}); total "
            f"{total_before} → {total_after} ({'±0' if delta == 0 else delta})"
        )
    elif delta > 0:
        heading = (
            f"⚠️ Suppression ledger grew: {total_before} → {total_after} (+{delta})"
        )
    else:
        heading = (
            f"Suppression ledger changed: {total_before} → {total_after} "
            f"({'±0' if delta == 0 else delta})"
        )

    def render_row(row: Delta) -> str:
        file, rule = row.key
        change = row.after.total - row.before.total
        change_cell = "±0" if change == 0 else f"{change:+d}"
        reason_note = (
            ""
            if row.before.undescribed == row.after.undescribed
            else f" (reason-less {row.before.undescribed} → {row.after.undescribed})"
        )
        return f"| {_cell(file)} | {_cell(rule)} | {change_cell}{reason_note} |"

    table = "\n".join(render_row(row) for row in rows)

    undescribed_line = (
        ""
        if undescribed_before == undescribed_after
        else f"\nReason-less (baselined) suppressions: "
        f"{undescribed_before} → {undescribed_after}\n"
    )

    footer = (
        "\nEvery new suppression needs a trailing `# reason` comment and "
        "maintainer sign-off of this ledger diff — see the Suppression gate "
        "section in AGENTS.md."
        if needs_attention
        else ""
    )

    return (
        f"{MARKER}\n### {heading}\n\n| File | Rule | Change |\n|---|---|---|\n"
        f"{table}\n{undescribed_line}{footer}"
    )


def body_for(base: Ledger | None, head: Ledger | None) -> str | None:
    """The comment body for the two loaded ledgers (None = malformed).

    A malformed ledger is reported rather than treated as empty: an
    empty-ledger stand-in would render a false "all suppressions removed"
    delta for the reviewer to approve.
    """
    if head is None:
        return (
            f"{MARKER}\n⚠️ This PR's `suppressions.json` is not a valid "
            "suppression ledger, so the delta cannot be computed. "
            "Regenerate it with `make suppressions-update`."
        )
    if base is None:
        return (
            f"{MARKER}\n⚠️ The base `suppressions.json` (at the merge-base) "
            "is not a valid suppression ledger, so the delta cannot be "
            "computed. Update the branch once the base ledger is fixed."
        )
    return render(base, head)


def main() -> int:
    base_path, head_path = sys.argv[1:3]
    body = body_for(_load(base_path), _load(head_path))
    if body is not None:
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
