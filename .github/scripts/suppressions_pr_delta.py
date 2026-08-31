#!/usr/bin/env python3
"""Markdown body for the sticky PR comment on suppression ledger changes.

Prints nothing when the ledger is unchanged.

Usage: python3 suppressions_pr_delta.py <base.json> <head.json>
"""

import html
import json
import sys
from pathlib import Path

# Sibling-script import: resolves because sys.path[0] is this script's
# directory when invoked by path (as the workflow does); the test suite
# pre-registers the module in sys.modules instead.
from check_suppressions import Delta, Ledger, diff_ledgers, totals

MARKER = "<!-- suppressions-delta -->"


def _load(path: str) -> Ledger:
    try:
        ledger: Ledger = json.loads(Path(path).read_text())
        return ledger
    except (OSError, json.JSONDecodeError):
        return {}


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


def main() -> int:
    base_path, head_path = sys.argv[1:3]
    body = render(_load(base_path), _load(head_path))
    if body is not None:
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
