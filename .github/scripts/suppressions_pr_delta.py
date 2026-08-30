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
Ledger = dict[str, dict[str, dict[str, int]]]


def flatten(ledger: Ledger) -> dict[Key, Counts]:
    return {
        (file, rule): Counts(tally["count"], tally.get("undescribed", 0))
        for file, rules in ledger.items()
        for rule, tally in rules.items()
    }


def _load(path: str) -> Ledger:
    try:
        ledger: Ledger = json.loads(Path(path).read_text())
        return ledger
    except (OSError, json.JSONDecodeError):
        return {}


class Row(NamedTuple):
    key: Key
    before: Counts
    after: Counts


def render(base: dict[Key, Counts], head: dict[Key, Counts]) -> str | None:
    """The comment body for a base -> head ledger change, or None if none.

    An undescribed-only change (a reason added or removed) renders too:
    otherwise such a ledger diff would produce nothing and the workflow
    would falsely reset the sticky comment to "no longer changes the
    ledger".
    """
    rows = [
        row
        for key in sorted(base.keys() | head.keys())
        if (row := Row(key, base.get(key, NONE), head.get(key, NONE))).before
        != row.after
    ]
    if not rows:
        return None

    total_before = sum(c.total for c in base.values())
    total_after = sum(c.total for c in head.values())
    delta = total_after - total_before
    heading = (
        f"⚠️ Suppression ledger grew: {total_before} → {total_after} (+{delta})"
        if delta > 0
        else f"Suppression ledger changed: {total_before} → {total_after} "
        f"({'±0' if delta == 0 else delta})"
    )

    def render_row(row: Row) -> str:
        file, rule = row.key
        change = row.after.total - row.before.total
        change_cell = "±0" if change == 0 else f"{change:+d}"
        reason_note = (
            ""
            if row.before.undescribed == row.after.undescribed
            else f" (reason-less {row.before.undescribed} → {row.after.undescribed})"
        )
        return f"| `{file}` | `{rule}` | {change_cell}{reason_note} |"

    table = "\n".join(render_row(row) for row in rows)

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

    return (
        f"{MARKER}\n### {heading}\n\n| File | Rule | Change |\n|---|---|---|\n"
        f"{table}\n{undescribed_line}{footer}"
    )


def main() -> int:
    base_path, head_path = sys.argv[1:3]
    body = render(flatten(_load(base_path)), flatten(_load(head_path)))
    if body is not None:
        print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
