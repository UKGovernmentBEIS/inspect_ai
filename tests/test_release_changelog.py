"""Tests for the Release Please changelog handling and release configuration.

Covers .github/scripts/release_changelog.py, the release-prep carve-out in
changelog-lint.yml (run against real git diffs), and invariants of the
committed Release Please config.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).parents[1]

spec = importlib.util.spec_from_file_location(
    "release_changelog", REPO / ".github" / "scripts" / "release_changelog.py"
)
assert spec is not None and spec.loader is not None
release_changelog: ModuleType = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_changelog)
ChangelogError = release_changelog.ChangelogError

DAY = date(2026, 10, 12)

CHANGELOG = """\
## Unreleased

- Added a thing.
- Fixed a thing.

- Fixed another thing.

## 0.3.277 (06 October 2026)

- Older entry.

## 0.3.276 (02 October 2026)

- Oldest entry.
"""

PREPARED = """\
## Unreleased

## 0.3.278 (12 October 2026)

- Added a thing.
- Fixed a thing.

- Fixed another thing.

## 0.3.277 (06 October 2026)

- Older entry.

## 0.3.276 (02 October 2026)

- Oldest entry.
"""


def test_format_date_matches_existing_headings() -> None:
    assert release_changelog.format_date(date(2026, 10, 6)) == "06 October 2026"
    assert release_changelog.format_date(date(2027, 1, 31)) == "31 January 2027"


def test_prepare_renames_unreleased_and_adds_empty_one() -> None:
    assert release_changelog.prepare(CHANGELOG, "0.3.278", DAY) == PREPARED


def test_prepare_is_idempotent() -> None:
    assert release_changelog.prepare(PREPARED, "0.3.278", DAY) == PREPARED


def test_prepare_rerun_moves_new_entries_and_redates() -> None:
    later = PREPARED.replace(
        "## Unreleased\n", "## Unreleased\n\n- Landed after the release PR opened.\n"
    )
    result = release_changelog.prepare(later, "0.3.278", date(2026, 10, 13))
    assert result == PREPARED.replace(
        "## 0.3.278 (12 October 2026)\n\n",
        "## 0.3.278 (13 October 2026)\n\n- Landed after the release PR opened.\n\n",
    )
    release_changelog.check(result, "0.3.278")


def test_prepare_keeps_text_before_first_heading() -> None:
    result = release_changelog.prepare("# Changelog\n\n" + CHANGELOG, "0.3.278", DAY)
    assert result == "# Changelog\n\n" + PREPARED


def test_prepare_last_section_in_file() -> None:
    result = release_changelog.prepare("## Unreleased\n\n- Only.\n", "0.1.0", DAY)
    assert result == "## Unreleased\n\n## 0.1.0 (12 October 2026)\n\n- Only.\n"


def test_prepare_empty_unreleased_leaves_an_empty_section_that_check_rejects() -> None:
    empty = "## Unreleased\n\n## 0.3.277 (06 October 2026)\n\n- Older entry.\n"
    result = release_changelog.prepare(empty, "0.3.278", DAY)
    assert result == (
        "## Unreleased\n\n## 0.3.278 (12 October 2026)\n\n"
        "## 0.3.277 (06 October 2026)\n\n- Older entry.\n"
    )
    with pytest.raises(ChangelogError, match="'## 0.3.278' is empty"):
        release_changelog.check(result, "0.3.278")
    with pytest.raises(ChangelogError, match="is empty"):
        release_changelog.notes(result, "0.3.278")


@pytest.mark.parametrize(
    "text,error",
    [
        ("## 0.3.277 (06 October 2026)\n\n- x\n", "must be the first section"),
        ("- stray\n", "must be the first section"),
        (
            "## 0.3.277 (06 October 2026)\n\n## Unreleased\n\n- x\n",
            "must be the first section",
        ),
        (
            "## Unreleased\n\n- x\n\n## 0.3.277 (06 October 2026)\n\n"
            "## 0.3.278 (01 October 2026)\n",
            "already exists below another release",
        ),
    ],
)
def test_prepare_rejects(text: str, error: str) -> None:
    with pytest.raises(ChangelogError, match=error):
        release_changelog.prepare(text, "0.3.278", DAY)


@pytest.mark.parametrize("version", ["v0.3.278", "0.3", "0.3.278rc1", ""])
def test_rejects_non_release_versions(version: str) -> None:
    for call in (
        lambda: release_changelog.prepare(CHANGELOG, version, DAY),
        lambda: release_changelog.check(PREPARED, version),
        lambda: release_changelog.notes(PREPARED, version),
    ):
        with pytest.raises(ChangelogError, match="not a release version"):
            call()


def test_check_accepts_prepared_changelog() -> None:
    release_changelog.check(PREPARED, "0.3.278")


@pytest.mark.parametrize(
    "text,error",
    [
        (CHANGELOG, "'## Unreleased' has entries"),
        (PREPARED.replace("(12 October 2026)", ""), "Expected '## 0.3.278"),
        (
            PREPARED.replace("(12 October 2026)", "(2026-10-12)"),
            "Expected '## 0.3.278",
        ),
        (PREPARED.replace("0.3.278", "0.3.279"), "found '## 0.3.279"),
        ("## Unreleased\n", "found nothing"),
    ],
)
def test_check_rejects(text: str, error: str) -> None:
    with pytest.raises(ChangelogError, match=re.escape(error)):
        release_changelog.check(text, "0.3.278")


def test_notes_returns_section_entries() -> None:
    assert release_changelog.notes(PREPARED, "0.3.278") == (
        "- Added a thing.\n- Fixed a thing.\n\n- Fixed another thing.\n"
    )
    assert release_changelog.notes(PREPARED, "0.3.276") == "- Oldest entry.\n"
    with pytest.raises(ChangelogError, match="No '## 0.3.270' section"):
        release_changelog.notes(PREPARED, "0.3.270")


def test_notes_for_a_released_version_of_the_committed_changelog() -> None:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = release_changelog.notes(text, "0.3.277")
    assert notes.startswith("- ")
    assert "## " not in notes


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO / ".github" / "scripts" / "release_changelog.py")]
        + list(args),
        capture_output=True,
        text=True,
    )


def test_cli_prepare_check_notes(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG)

    result = _run_script(
        "--path", str(path), "prepare", "0.3.278", "--date", "2026-10-12"
    )
    assert result.returncode == 0, result.stderr
    assert path.read_text() == PREPARED

    result = _run_script(
        "--path", str(path), "prepare", "0.3.278", "--date", "2026-10-12"
    )
    assert result.returncode == 0
    assert "already prepared" in result.stdout

    assert _run_script("--path", str(path), "check", "0.3.278").returncode == 0
    result = _run_script("--path", str(path), "notes", "0.3.278")
    assert result.stdout == release_changelog.notes(PREPARED, "0.3.278")


def test_cli_reports_errors_as_annotations(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG)
    result = _run_script("--path", str(path), "check", "0.3.278")
    assert result.returncode == 1
    assert result.stderr.startswith(f"::error file={path}::")


def test_cli_prepare_warns_on_empty_release(tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text("## Unreleased\n\n## 0.3.277 (06 October 2026)\n\n- x\n")
    result = _run_script("--path", str(path), "prepare", "0.3.278")
    assert result.returncode == 0
    assert "::warning" in result.stdout and "is empty" in result.stdout


# ---------------------------------------------------------------------------
# changelog-lint.yml against the diff `prepare` makes
# ---------------------------------------------------------------------------


def _changelog_lint_script() -> str:
    workflow = (REPO / ".github" / "workflows" / "changelog-lint.yml").read_text()
    match = re.search(r"<<'PY'\n(.*?)\n\s*PY\n", workflow, re.DOTALL)
    assert match
    lines = match.group(1).splitlines()
    indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    return "\n".join(line[indent:] for line in lines)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _lint(tmp_path: Path, before: str, after: str) -> subprocess.CompletedProcess[str]:
    _git(tmp_path, "init", "-q")
    (tmp_path / "CHANGELOG.md").write_text(before)
    _git(tmp_path, "add", "CHANGELOG.md")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "CHANGELOG.md").write_text(after)
    _git(tmp_path, "commit", "-qam", "change")
    return subprocess.run(
        [sys.executable, "-", "HEAD^1"],
        input=_changelog_lint_script(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_changelog_lint_accepts_release_prep(tmp_path: Path) -> None:
    result = _lint(tmp_path, CHANGELOG, PREPARED)
    assert result.returncode == 0, result.stdout
    assert "Release-prep change" in result.stdout


def test_changelog_lint_accepts_release_prep_of_committed_changelog(
    tmp_path: Path,
) -> None:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    result = _lint(tmp_path, text, release_changelog.prepare(text, "9.9.9", DAY))
    assert result.returncode == 0, result.stdout


def test_changelog_lint_still_rejects_entries_under_a_new_version_heading(
    tmp_path: Path,
) -> None:
    after = PREPARED.replace(
        "## 0.3.278 (12 October 2026)\n",
        "## 0.3.278 (12 October 2026)\n\n- Sneaked in.\n",
    )
    result = _lint(tmp_path, CHANGELOG, after)
    assert result.returncode == 1
    assert "outside the '## Unreleased' section" in result.stdout


def test_changelog_lint_still_rejects_entries_under_released_heading(
    tmp_path: Path,
) -> None:
    after = CHANGELOG.replace("- Older entry.\n", "- Older entry.\n- Misplaced.\n")
    result = _lint(tmp_path, CHANGELOG, after)
    assert result.returncode == 1


# ---------------------------------------------------------------------------
# Release Please configuration
# ---------------------------------------------------------------------------


def test_release_please_config_invariants() -> None:
    config = json.loads((REPO / ".release-please-config.json").read_text())
    manifest = json.loads((REPO / ".release-please-manifest.json").read_text())
    package = config["packages"]["."]

    assert config["release-type"] == "python"
    # Bare tags; release-please ignores these two at the top level.
    assert package["include-v-in-tag"] is False
    assert package["include-component-in-tag"] is False
    # 0.x: feat and fix bump the patch, breaking changes bump the minor.
    assert package["bump-minor-pre-major"] is True
    assert package["bump-patch-for-minor-pre-major"] is True
    # CHANGELOG.md is curated by hand.
    assert package["skip-changelog"] is True
    # package-name or component would change the release branch name from
    # release-please--branches--main, which the workflows refer to.
    assert "package-name" not in package and "component" not in package

    assert list(manifest) == ["."]
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["."])


def test_release_workflow_passes_no_release_type() -> None:
    """A release-type input puts the action in simple mode, ignoring the config."""
    workflow = (REPO / ".github" / "workflows" / "release.yml").read_text()
    assert "release-type:" not in workflow
    assert "config-file: .release-please-config.json" in workflow
