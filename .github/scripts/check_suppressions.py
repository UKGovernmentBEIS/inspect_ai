#!/usr/bin/env python3
"""Gate for lint/type-check suppression comments.

suppressions.json (the ledger) must exactly match the per-file, per-rule
suppression counts in the code. Count and reason-status changes fail CI until
the ledger is regenerated, so they show up as a reviewable ledger diff in the
PR. Moving or replacing an occurrence within the same file under the same rule
does not change these aggregate counts and is reviewed in the source diff.

The `undescribed` count (suppressions lacking a reason — a trailing hash
comment segment on the same line, the only style mypy accepts after
`type: ignore`) is a ratchet: --update refuses to increase any rule's
repo-wide total, so new suppressions must carry a reason while the
baselined reason-less ones burn down over time. The ratchet is per rule,
not per file, so moving a file doesn't trip it. `--update --allow-growth`
overrides the refusal for the one sanctioned case — a merge from upstream
that brings in reason-less suppressions on lines this repo must not edit —
and prints every rule that grew so the override is loud in the run log
(the growth still shows in the ledger diff for review). See the
"Suppression gate" section in AGENTS.md.

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
#
# The file-level ruff/flake8 form is spelled loosely to match what ruff
# honors (verified against the pinned ruff): the noqa token in any case and
# whitespace tolerated around the colons ("ruff : NOQA" suppresses
# file-wide). The ruff/flake8 prefix itself stays case-sensitive — ruff
# ignores "RUFF: NOQA" (verified).
#
# The colon-and-codes tails mirror ruff's parse (all verified): a colon
# with no parseable code list — codes are case-sensitive uppercase, so
# "noqa:" or "noqa: e501" — invalidates the whole directive (ruff warns
# and suppresses nothing); _rules maps that to no records. A line-level
# code list opens only when the colon is attached ("noqa : F401" is a
# BLANKET noqa with trailing junk), hence no \s* before noqa_colon; the
# file-level form tolerates whitespace around its second colon, hence
# the \s* before file_noqa_colon.
DIRECTIVE_RE = re.compile(
    r"""\#+\s*(?:
        (?:ruff|flake8)\s*:\s*(?P<file_noqa>(?i:noqa))(?:\s*(?P<file_noqa_colon>:)\s*(?P<file_noqa_codes>{noqa_codes})?)?
      | (?P<noqa>(?i:noqa))(?![\w])(?:(?P<noqa_colon>:)\s*(?P<noqa_codes>{noqa_codes})?)?
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

# A legacy type comment (PEP 484 `x = f()  # type: List[int]`), which may
# carry a trailing suppression: mypy honors the ignore in
# `x = f()  # type: List[int]  # type: ignore` (verified) even though it
# doesn't open the comment, but only when the ignore is the type comment's
# first embedded segment — a prose segment in between defeats it (verified).
# The lookahead keeps a leading `type: ignore` directive from qualifying as
# a type comment, so its duplicate/reason segments stay inert.
_LEGACY_TYPE_COMMENT_RE = re.compile(r"#\s*type:(?!\s*ignore\b)[^#]*")


class Suppression(NamedTuple):
    rule: str
    described: bool


def _split_codes(codes: str) -> list[str]:
    return [c for c in re.split(r"[,\s]+", codes) if c]


def _noqa_rules(colon: str | None, codes: str | None) -> list[str]:
    """Rule keys for one noqa directive.

    None for a colon with no parseable code list — an invalid directive,
    see the DIRECTIVE_RE comment.
    """
    if colon and not codes:
        return []
    return [f"noqa:{c}" for c in _split_codes(codes)] if codes else ["noqa"]


def _rules(m: re.Match[str]) -> list[str]:
    """Ledger rule keys for one directive match (one per code)."""
    if m.group("file_noqa"):
        rules = _noqa_rules(m.group("file_noqa_colon"), m.group("file_noqa_codes"))
        return [rule + FILE_WIDE for rule in rules]
    if m.group("noqa"):
        return _noqa_rules(m.group("noqa_colon"), m.group("noqa_codes"))
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


def _is_file_wide(m: re.Match[str]) -> bool:
    return any(m.group(g) for g in ("file_noqa", "mypy_ignore", "mypy_codes"))


def _active(m: re.Match[str], text: str, own_line: bool, col: int) -> bool:
    # mypy honors `type: ignore` and `mypy:` config comments only when they
    # open the comment (verified: `# prose  # type: ignore` and
    # `## type: ignore` suppress nothing), except for a `type: ignore`
    # trailing a legacy type comment (see _LEGACY_TYPE_COMMENT_RE). ruff's
    # file-level directives (`ruff: noqa` / `flake8: noqa` opening a
    # comment) must open the comment the same way, and are additionally
    # honored only on a comment line of their own — trailing code, they
    # draw a ruff warning and suppress nothing (all verified; the quoted
    # spellings here avoid a literal hash before the directive because
    # newer ruff warns on that even inside prose). mypy config comments
    # must further start at column 0: an indented own-line
    # `mypy: ignore-errors` comment suppresses nothing (verified), while
    # ruff's file-level forms are honored even indented (verified).
    # Line-level ruff/pyright directives count in any comment segment.
    if m.group("type_ignore") and m.start() != 0:
        return bool(_LEGACY_TYPE_COMMENT_RE.fullmatch(text, 0, m.start()))
    if _is_mypy(m) or m.group("file_noqa"):
        if m.start() != 0 or text.startswith("##"):
            return False
    if _is_file_wide(m):
        return own_line if m.group("file_noqa") else own_line and col == 0
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


def scan_comment(text: str, own_line: bool = True, col: int = 0) -> list[Suppression]:
    """Suppression records in one comment token's text.

    `own_line` says whether the comment is a line of its own (nothing but
    whitespace before it) and `col` where it starts — file-wide directives
    are inert in a trailing comment, and mypy's config comments further
    require column 0. A directive is "described" when reason text follows
    it in the comment, stopping at the next directive — see _described for
    the per-tool rules.
    """
    # Inert matches (see _active) produce no records but still bound the
    # reason region: a duplicated `# type: ignore  # type: ignore` must not
    # read its inert twin as a reason.
    matches = list(DIRECTIVE_RE.finditer(text))
    ends = [n.start() for n in matches[1:]] + [len(text)]
    return [
        Suppression(rule, _described(m, text[m.end() : end]))
        for m, end in zip(matches, ends)
        if _active(m, text, own_line, col)
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
            own_line = not tok.line[: tok.start[1]].strip()
            for record in scan_comment(tok.string, own_line, tok.start[1]):
                # A bare `# type: ignore` on its own line before any code or
                # docstring silences the entire module in mypy (verified,
                # indented included; the bracketed form there is a mypy
                # error, not file-wide). Only a comment the directive opens
                # qualifies: a preamble legacy type comment is a mypy
                # syntax error (verified), not a module-wide ignore.
                if (
                    preamble
                    and record.rule == "type: ignore"
                    and DIRECTIVE_RE.match(tok.string)
                ):
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


def flatten(ledger: Ledger) -> dict[Key, Counts]:
    """Ledger as a flat (file, rule) -> Counts map (suppressions_pr_delta.py reuses this)."""
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
    before = flatten(ledger)
    after = flatten(actual)
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
    counts = flatten(ledger).values()
    return Counts(sum(c.total for c in counts), sum(c.undescribed for c in counts))


def _list_files() -> list[str]:
    out = subprocess.run(
        # *.pyi too: mypy type-checks stubs, so a `type: ignore` there is a
        # real suppression (tokenize handles stub syntax fine).
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
            "*.pyi",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # Include untracked, non-ignored files so an update run before `git add`
    # sees newly authored code; omit unstaged deletions still present in the
    # index so ordinary edit-then-update workflows do not fail opening them.
    return [f for f in out.split("\0") if f and Path(f).is_file()]


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

    args = sys.argv[1:]
    if unknown := [a for a in args if a not in ("--update", "--allow-growth")]:
        # A silently-ignored typo (e.g. --updat) would run check mode instead.
        print(
            f"unknown argument(s): {' '.join(unknown)} "
            f"(expected --update and/or --allow-growth)",
            file=sys.stderr,
        )
        return 2
    update = "--update" in args
    allow_growth = "--allow-growth" in args
    if allow_growth and not update:
        print("--allow-growth is only meaningful with --update.", file=sys.stderr)
        return 2

    # No ledger yet: the first --update captures the baseline as-is.
    bootstrap = not LEDGER_PATH.exists()
    ledger: Ledger = json.loads(LEDGER_PATH.read_text()) if not bootstrap else {}
    actual = _scan_repo()

    violations = [] if update and bootstrap else ratchet_violations(ledger, actual)
    for v in violations:
        prefix = "ALLOWED GROWTH" if allow_growth else "UNDESCRIBED"
        print(
            f"{prefix}: {v.rule} — {v.after} suppression(s) without a "
            f"reason repo-wide, ledger allows {v.before}. New suppressions "
            f"need a trailing `# reason` comment.",
            file=sys.stderr,
        )

    if update:
        if violations and not allow_growth:
            print(
                "refusing to record reason-less growth; fix the code or add "
                "a `# reason` segment. For a merge from upstream that brings "
                "in suppressions on lines this repo must not edit, rerun "
                "with --allow-growth (the growth stays visible in the "
                "ledger diff).",
                file=sys.stderr,
            )
            return 1
        if bootstrap:
            # A missing ledger silently skips the ratchet above; say so, or
            # deleting the file becomes an invisible bypass.
            print("no existing ledger: baseline captured, ratchet not applied.")
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
