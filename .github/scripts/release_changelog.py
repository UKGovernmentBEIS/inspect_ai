"""Release-time CHANGELOG.md edits for the Release Please flow.

CHANGELOG.md is curated by hand under `## Unreleased`. Release Please manages
the version, tag and GitHub Release but does not edit the changelog
(`skip-changelog` in .release-please-config.json); this script does instead.

  prepare VERSION  Run by release.yml on the release PR branch. Renames
                   `## Unreleased` to `## VERSION (DD Month YYYY)` and adds an
                   empty `## Unreleased` above it. On a re-run it moves entries
                   that have since landed under `## Unreleased` into the
                   VERSION section and refreshes its date.
  check VERSION    Fails unless the file has an empty `## Unreleased` followed
                   by a dated, non-empty VERSION section.
  notes VERSION    Prints the VERSION section's entries (the GitHub Release
                   body).

Stdlib only, so it runs on the runner's Python without setup.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple

# Spelled out so headings don't depend on the runner's locale.
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# Same pattern as changelog-lint.yml.
UNRELEASED_RE = re.compile(r"^##\s+Unreleased\s*$", re.IGNORECASE)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{2} (?:" + "|".join(MONTHS) + r") \d{4}$")


class ChangelogError(Exception):
    pass


class Section(NamedTuple):
    heading: str  # "" for the text before the first heading
    body: list[str]


def format_date(day: date) -> str:
    return f"{day.day:02d} {MONTHS[day.month - 1]} {day.year}"


def _version_heading_re(version: str) -> re.Pattern[str]:
    return re.compile(rf"^##\s+{re.escape(version)}(?:\s+\((?P<date>[^)]*)\))?\s*$")


def _parse(text: str) -> tuple[Section, list[Section]]:
    sections = [Section("", [])]
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append(Section(line, []))
        else:
            sections[-1].body.append(line)
    return sections[0], sections[1:]


def _render(sections: list[Section]) -> str:
    lines: list[str] = []
    for section in sections:
        if section.heading:
            lines.append(section.heading)
        lines.extend(section.body)
    return "\n".join(lines) + "\n"


def _strip_blank(body: list[str]) -> list[str]:
    start, end = 0, len(body)
    while start < end and not body[start].strip():
        start += 1
    while end > start and not body[end - 1].strip():
        end -= 1
    return body[start:end]


def _unreleased(sections: list[Section], version: str) -> Section:
    if not VERSION_RE.match(version):
        raise ChangelogError(f"'{version}' is not a release version (X.Y.Z)")
    if not sections or not UNRELEASED_RE.match(sections[0].heading):
        raise ChangelogError("'## Unreleased' must be the first section")
    return sections[0]


def prepare(text: str, version: str, day: date) -> str:
    """Return `text` with the `## Unreleased` entries released as `version`."""
    preamble, sections = _parse(text)
    unreleased = _unreleased(sections, version)
    entries = _strip_blank(unreleased.body)
    rest = sections[1:]

    version_re = _version_heading_re(version)
    if rest and version_re.match(rest[0].heading):
        released = _strip_blank(rest[0].body)
        if entries and released:
            entries = entries + [""] + released
        else:
            entries = entries or released
        rest = rest[1:]
    if any(version_re.match(s.heading) for s in rest):
        raise ChangelogError(
            f"'## {version}' already exists below another release section"
        )

    release_body = ([""] + entries if entries else []) + ([""] if rest else [])
    return _render(
        [
            preamble,
            Section(unreleased.heading, [""]),
            Section(f"## {version} ({format_date(day)})", release_body),
            *rest,
        ]
    )


def check(text: str, version: str) -> None:
    """Raise `ChangelogError` unless `text` is prepared for releasing `version`."""
    _, sections = _parse(text)
    unreleased = _unreleased(sections, version)
    if _strip_blank(unreleased.body):
        raise ChangelogError(
            f"'## Unreleased' has entries; they belong in '## {version}' on the "
            f"release PR (re-run the Release workflow to move them)"
        )
    expected = f"'## {version} (DD Month YYYY)', e.g. '## 0.3.277 (06 October 2026)'"
    match = (
        _version_heading_re(version).match(sections[1].heading)
        if len(sections) > 1
        else None
    )
    if not match or not DATE_RE.match(match.group("date") or ""):
        found = f"'{sections[1].heading}'" if len(sections) > 1 else "nothing"
        raise ChangelogError(
            f"Expected {expected} after '## Unreleased', found {found}"
        )
    if not _strip_blank(sections[1].body):
        raise ChangelogError(
            f"'## {version}' is empty; add changelog entries for this release"
        )


def notes(text: str, version: str) -> str:
    """Return the entries of the `version` section."""
    if not VERSION_RE.match(version):
        raise ChangelogError(f"'{version}' is not a release version (X.Y.Z)")
    version_re = _version_heading_re(version)
    _, sections = _parse(text)
    for section in sections:
        if version_re.match(section.heading):
            entries = _strip_blank(section.body)
            if not entries:
                raise ChangelogError(f"'## {version}' is empty")
            return "\n".join(entries) + "\n"
    raise ChangelogError(f"No '## {version}' section")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Release-time CHANGELOG.md edits")
    parser.add_argument("--path", type=Path, default=Path("CHANGELOG.md"))
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("version")
    prepare_parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Release date, YYYY-MM-DD (default: today in UTC)",
    )
    commands.add_parser("check").add_argument("version")
    commands.add_parser("notes").add_argument("version")
    args = parser.parse_args(argv)

    text = args.path.read_text(encoding="utf-8")
    try:
        if args.command == "prepare":
            day = args.date or datetime.now(timezone.utc).date()
            updated = prepare(text, args.version, day)
            if updated == text:
                print(f"{args.path} is already prepared for {args.version}")
            else:
                args.path.write_text(updated, encoding="utf-8")
                print(f"Prepared {args.path} for {args.version}")
            try:
                notes(updated, args.version)
            except ChangelogError as e:
                print(f"::warning file={args.path}::{e}")
        elif args.command == "check":
            check(text, args.version)
            print(f"{args.path} is ready to release {args.version}")
        else:
            sys.stdout.write(notes(text, args.version))
    except ChangelogError as e:
        print(f"::error file={args.path}::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
