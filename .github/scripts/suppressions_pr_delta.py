#!/usr/bin/env python3
"""Markdown body for the sticky PR comment on suppression ledger changes.

Prints nothing when the ledger is unchanged.

Usage: python3 suppressions_pr_delta.py <base.json> <head.json>
"""

import json
import sys
from pathlib import Path
from typing import NamedTuple

MARKER = "<!-- suppressions-delta -->"


class Counts(NamedTuple):
    total: int
    undescribed: int


NONE = Counts(0, 0)

Key = tuple[str, str]  # (file, rule)


def load(path: str) -> dict[Key, Counts]:
    try:
        ledger = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        ledger = {}
    return {
        (file, rule): Counts(tally["count"], tally.get("undescribed", 0))
        for file, rules in ledger.items()
        for rule, tally in rules.items()
    }


class Row(NamedTuple):
    key: Key
    before: Counts
    after: Counts


def main() -> int:
    base_path, head_path = sys.argv[1:3]
    base = load(base_path)
    head = load(head_path)

    # Undescribed-only changes count too (someone added/removed a reason):
    # otherwise such a ledger diff would render nothing and the workflow
    # would falsely reset the sticky comment to "no longer changes the
    # ledger".
    rows = [
        row
        for key in sorted(base.keys() | head.keys())
        if (row := Row(key, base.get(key, NONE), head.get(key, NONE))).before
        != row.after
    ]
    if not rows:
        return 0

    total_before = sum(c.total for c in base.values())
    total_after = sum(c.total for c in head.values())
    delta = total_after - total_before
    heading = (
        f"⚠️ Suppression ledger grew: {total_before} → {total_after} (+{delta})"
        if delta > 0
        else f"Suppression ledger changed: {total_before} → {total_after} "
        f"({'±0' if delta == 0 else delta})"
    )

    def render(row: Row) -> str:
        file, rule = row.key
        change = row.after.total - row.before.total
        change_cell = "±0" if change == 0 else f"{change:+d}"
        reason_note = (
            ""
            if row.before.undescribed == row.after.undescribed
            else f" (reason-less {row.before.undescribed} → {row.after.undescribed})"
        )
        return f"| `{file}` | `{rule}` | {change_cell}{reason_note} |"

    table = "\n".join(render(row) for row in rows)

    undescribed_before = sum(c.undescribed for c in base.values())
    undescribed_after = sum(c.undescribed for c in head.values())
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
        if delta > 0
        else ""
    )

    print(
        f"{MARKER}\n### {heading}\n\n| File | Rule | Change |\n|---|---|---|\n"
        f"{table}\n{undescribed_line}{footer}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
