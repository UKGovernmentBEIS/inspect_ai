#!/usr/bin/env python3
"""Gate for lint/type-check suppression comments.

suppressions.json (the ledger) must exactly match the suppression comments
in the code — any add, remove, or move fails CI until the ledger is
regenerated, so every change shows up as a reviewable ledger diff in the PR.

The `undescribed` count (suppressions lacking a reason — a trailing hash
comment segment on the same line, the only style mypy accepts after
`type: ignore`) is a ratchet: --update refuses to increase any rule's
repo-wide total, so new suppressions must carry a reason while the
baselined reason-less ones burn down over time. The ratchet is per rule,
not per file, so moving a file doesn't trip it. See the "Suppression gate"
section in AGENTS.md.

Scanned directives (found via tokenize, so directive text inside string
literals is never counted):
  line-level: noqa / noqa: <codes> (ruff), type: ignore /
    type: ignore[<codes>] (mypy), pyright: ignore / pyright: ignore[<rules>]
  file-wide: ruff: noqa / flake8: noqa (optionally with codes),
    mypy: ignore-errors, mypy: disable-error-code=<codes>

Stdlib only by design — CI runs it with no dependency install.
"""

import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import NamedTuple

LEDGER_PATH = Path("suppressions.json")
UPDATE_HINT = "run `make suppressions-update`"

# File-wide directives suppress for the whole file. Key them distinguishably
# so swapping a line-scoped directive for the file-wide form is a ledger
# diff, not a count-neutral no-op.
FILE_WIDE = " (file-wide)"

_NOQA_CODES = r"[A-Z]+[0-9]+(?:[,\s]+[A-Z]+[0-9]+)*"
_BRACKET = r"\[\s*(?P<{name}>[\w-]+(?:\s*,\s*[\w-]+)*)\s*\]"

# A directive counts only when it opens a comment segment (anchored at `#`),
# mirroring how ruff and mypy themselves locate directives, so prose like
# "remove the type: ignore below" never matches.
DIRECTIVE_RE = re.compile(
    r"""\#+\s*(?:
        (?:ruff|flake8):\s*(?P<file_noqa>noqa)(?:\s*:\s*(?P<file_noqa_codes>{noqa_codes}))?
      | (?P<noqa>(?i:noqa))(?![\w])(?:\s*:\s*(?P<noqa_codes>{noqa_codes}))?
      | type:\s*(?P<type_ignore>ignore)(?![\w])(?:\s*{type_codes})?
      | pyright:\s*(?P<pyright>ignore)(?![\w])(?:\s*{pyright_codes})?
      | mypy:\s*(?:
            (?P<mypy_ignore>ignore-errors)(?![\w-])
          | disable-error-code\s*=\s*"?(?P<mypy_codes>[\w-]+(?:\s*,\s*[\w-]+)*)"?
        )
    )""".format(
        noqa_codes=_NOQA_CODES,
        type_codes=_BRACKET.format(name="type_codes"),
        pyright_codes=_BRACKET.format(name="pyright_codes"),
    ),
    re.VERBOSE,
)

# Text that is only separators (hashes, dashes, whitespace) is not a reason.
_SEPARATORS_RE = re.compile(r"[#\s—–-]+")


class Suppression(NamedTuple):
    rule: str
    described: bool


def _split_codes(codes: str) -> list[str]:
    return [c for c in re.split(r"[,\s]+", codes) if c]


def _rules(m: re.Match[str]) -> list[str]:
    """Ledger rule keys for one directive match (one per code)."""
    if m.group("file_noqa"):
        codes = m.group("file_noqa_codes")
        prefixed = [f"noqa:{c}" for c in _split_codes(codes)] if codes else ["noqa"]
        return [rule + FILE_WIDE for rule in prefixed]
    if m.group("noqa"):
        codes = m.group("noqa_codes")
        return [f"noqa:{c}" for c in _split_codes(codes)] if codes else ["noqa"]
    if m.group("type_ignore"):
        codes = m.group("type_codes")
        if codes:
            return [f"type: ignore[{c}]" for c in _split_codes(codes)]
        return ["type: ignore"]
    if m.group("pyright"):
        codes = m.group("pyright_codes")
        if codes:
            return [f"pyright: ignore[{c}]" for c in _split_codes(codes)]
        return ["pyright: ignore"]
    if m.group("mypy_ignore"):
        return ["mypy: ignore-errors" + FILE_WIDE]
    codes = m.group("mypy_codes")
    assert codes is not None
    return [f"mypy: disable-error-code[{c}]{FILE_WIDE}" for c in _split_codes(codes)]


def _is_mypy(m: re.Match[str]) -> bool:
    return any(m.group(g) for g in ("type_ignore", "mypy_ignore", "mypy_codes"))


def _active(m: re.Match[str], text: str) -> bool:
    # mypy honors `type: ignore` and `mypy:` config comments only when they
    # open the comment (verified: `# prose  # type: ignore` and
    # `## type: ignore` suppress nothing), so a match elsewhere is inert.
    # ruff, in contrast, honors a noqa directive in any comment segment.
    if _is_mypy(m):
        return m.start() == 0 and not text.startswith("##")
    return True


def _described(m: re.Match[str], rest: str) -> bool:
    # For `type: ignore` a reason must be a new `#` segment: mypy rejects
    # the whole directive when bare prose follows it (verified), so prose
    # there is a broken comment, not a reason. After noqa codes ruff
    # tolerates prose (and the repo already uses `— reason`), so any
    # non-separator text counts.
    if m.group("type_ignore") and not rest.lstrip().startswith("#"):
        return False
    return bool(_SEPARATORS_RE.sub("", rest))


def scan_comment(text: str) -> list[Suppression]:
    """Suppression records in one comment token's text.

    A directive is "described" when reason text follows it in the comment,
    stopping at the next directive — see _described for the per-tool rules.
    """
    # Inert matches (see _active) produce no records but still bound the
    # reason region: a duplicated `# type: ignore  # type: ignore` must not
    # read its inert twin as a reason.
    matches = list(DIRECTIVE_RE.finditer(text))
    ends = [n.start() for n in matches[1:]] + [len(text)]
    return [
        Suppression(rule, _described(m, text[m.end() : end]))
        for m, end in zip(matches, ends)
        if _active(m, text)
        for rule in _rules(m)
    ]


# Tokens that can precede a module's first docstring/code line.
_PREAMBLE_TOKENS = (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING)


def scan_source(source: str) -> list[Suppression]:
    """Suppression records in Python source text (comments only)."""
    records: list[Suppression] = []
    preamble = True
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type not in _PREAMBLE_TOKENS:
            preamble = False
        if tok.type == tokenize.COMMENT:
            for record in scan_comment(tok.string):
                # A bare `# type: ignore` on its own line before any code or
                # docstring silences the entire module in mypy (verified;
                # the bracketed form there is a mypy error, not file-wide).
                if preamble and record.rule == "type: ignore":
                    record = Suppression(record.rule + FILE_WIDE, record.described)
                records.append(record)
    return records


Tally = dict[str, int]  # {"count": n} or {"count": n, "undescribed": u}
Ledger = dict[str, dict[str, Tally]]  # file -> rule -> tally


def _tally_rules(records: list[Suppression]) -> dict[str, Tally]:
    by_rule: dict[str, list[Suppression]] = {}
    for record in records:
        by_rule.setdefault(record.rule, []).append(record)
    return {
        rule: (
            {"count": len(group), "undescribed": undescribed}
            if (undescribed := sum(1 for r in group if not r.described))
            else {"count": len(group)}
        )
        for rule, group in sorted(by_rule.items())
    }


def build_ledger(per_file: dict[str, list[Suppression]]) -> Ledger:
    return {
        file: _tally_rules(records)
        for file, records in sorted(per_file.items())
        if records
    }


class Counts(NamedTuple):
    total: int
    undescribed: int


NONE = Counts(0, 0)

Key = tuple[str, str]  # (file, rule)


def _entries(ledger: Ledger) -> dict[Key, Counts]:
    return {
        (file, rule): Counts(tally["count"], tally.get("undescribed", 0))
        for file, rules in ledger.items()
        for rule, tally in rules.items()
    }


class Delta(NamedTuple):
    key: Key
    before: Counts
    after: Counts


def diff_ledgers(ledger: Ledger, actual: Ledger) -> list[Delta]:
    """Every (file, rule) pair whose count or undescribed count differs.

    An undescribed-only change (a reason added or removed) must be recorded
    too, or a stale undescribed allowance would let the reason be deleted
    again unnoticed.
    """
    before = _entries(ledger)
    after = _entries(actual)
    deltas = [
        Delta(key, before.get(key, NONE), after.get(key, NONE))
        for key in sorted(before.keys() | after.keys())
    ]
    return [d for d in deltas if d.before != d.after]


def _base_rule(rule: str) -> str:
    # The ratchet ignores the file-wide suffix: scope is a per-entry property
    # the ledger diff already surfaces, while the ratchet tracks the repo-wide
    # reason-less total per rule — a line ↔ file-wide swap moves between keys
    # without changing that total.
    return rule[: -len(FILE_WIDE)] if rule.endswith(FILE_WIDE) else rule


def _undescribed_by_rule(ledger: Ledger) -> dict[str, int]:
    totals: dict[str, int] = {}
    for rules in ledger.values():
        for rule, tally in rules.items():
            base = _base_rule(rule)
            totals[base] = totals.get(base, 0) + tally.get("undescribed", 0)
    return totals


class RatchetViolation(NamedTuple):
    rule: str
    before: int
    after: int


def ratchet_violations(ledger: Ledger, actual: Ledger) -> list[RatchetViolation]:
    """Every rule whose repo-wide reason-less count grew.

    Summed across files so moving a file never trips the ratchet; a move
    still shows in the ledger diff via diff_ledgers, and --update records it.
    """
    before = _undescribed_by_rule(ledger)
    return [
        RatchetViolation(rule, before.get(rule, 0), after)
        for rule, after in sorted(_undescribed_by_rule(actual).items())
        if after > before.get(rule, 0)
    ]


def totals(ledger: Ledger) -> Counts:
    counts = _entries(ledger).values()
    return Counts(sum(c.total for c in counts), sum(c.undescribed for c in counts))


def _list_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [f for f in out.split("\0") if f]


def _scan_repo() -> Ledger:
    def scan_file(path: str) -> list[Suppression]:
        with tokenize.open(path) as fh:
            source = fh.read()
        try:
            return scan_source(source)
        except (tokenize.TokenError, SyntaxError) as ex:
            # tokenize reports positions but not the file; name it.
            raise RuntimeError(f"cannot tokenize {path}: {ex}") from ex

    return build_ledger({f: scan_file(f) for f in _list_files()})


def _summarize(ledger: Ledger) -> str:
    count, undescribed = totals(ledger)
    return (
        f"{count} suppressions ({undescribed} without a reason) in {len(ledger)} files"
    )


def _key_of(key: Key) -> str:
    return " — ".join(key)


def _diff_message(d: Delta) -> str:
    if d.after.total > d.before.total:
        return (
            f"NEW: {_key_of(d.key)} — {d.after.total} in code, "
            f"{d.before.total} in ledger. Fix the code instead if at all "
            f"possible; a genuinely unavoidable suppression needs a trailing "
            f"`# reason` comment — then {UPDATE_HINT} and get maintainer "
            f"sign-off on the ledger diff."
        )
    if d.after.total < d.before.total:
        return (
            f"REMOVED: {_key_of(d.key)} — {d.after.total} in code, "
            f"{d.before.total} in ledger. {UPDATE_HINT} to record the shrink."
        )
    return (
        f"REASONS: {_key_of(d.key)} — {d.after.undescribed} without a reason "
        f"in code, {d.before.undescribed} in ledger. {UPDATE_HINT} to "
        f"record it."
    )


def main() -> int:
    # git ls-files scopes to cwd and LEDGER_PATH is relative — anchor both to
    # the repo root so invocation from a subdirectory can't scan or write a
    # partial ledger.
    os.chdir(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    update = "--update" in sys.argv[1:]
    # No ledger yet: the first --update captures the baseline as-is.
    bootstrap = not LEDGER_PATH.exists()
    ledger: Ledger = json.loads(LEDGER_PATH.read_text()) if not bootstrap else {}
    actual = _scan_repo()

    violations = [] if update and bootstrap else ratchet_violations(ledger, actual)
    for v in violations:
        print(
            f"UNDESCRIBED: {v.rule} — {v.after} suppression(s) without a "
            f"reason repo-wide, ledger allows {v.before}. New suppressions "
            f"need a trailing `# reason` comment.",
            file=sys.stderr,
        )

    if update:
        if violations:
            return 1
        LEDGER_PATH.write_text(json.dumps(actual, indent=2) + "\n")
        print(f"{LEDGER_PATH} updated: {_summarize(actual)}.")
        return 0

    diffs = diff_ledgers(ledger, actual)
    for d in diffs:
        print(_diff_message(d), file=sys.stderr)

    if diffs or violations:
        return 1
    print(f"suppressions ledger matches: {_summarize(actual)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
