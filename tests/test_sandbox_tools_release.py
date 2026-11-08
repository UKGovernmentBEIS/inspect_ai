"""Contracts shared between the sandbox-tools CI gate and the release wizard.

`slow-tool-tests-release` in build.yml and `scripts/release-sandbox-tools.sh`
each carry a `BUILD_INPUTS` array. The gate uses it to reject published bytes
whose source differs from the PR; the wizard uses the same comparison to decide
when an earlier build can be reused instead of rebuilt. If the two drift, the
wizard could reuse bytes the gate then rejects, burning a version. They must be
identical.

A second test covers the wizard's `require_main_merged` guard. It computes the
PR's merge with main locally (`git merge-tree`) and stops the release when that
merge would change the build inputs away from HEAD, since the gate runs on the
same merge and would reject a build that lacks those changes.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path

REPO = Path(__file__).parents[1]
WIZARD = REPO / "scripts" / "release-sandbox-tools.sh"

# A file inside the build inputs, and one outside them (the excluded tests dir).
BUILD_INPUT = "src/inspect_ai/tool/_sandbox_tools_utils/sandbox.py"
NON_BUILD_INPUT = "src/inspect_sandbox_tools/tests/x.py"

# Isolate git from the developer's global/system config so these tests don't
# pick up signing, hooks, or an ambient identity. Signing is also disabled with
# a local `commit.gpgsign false` in _init_repo for safety.
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _build_inputs(text: str) -> list[str]:
    matches = re.findall(r"BUILD_INPUTS=\(\n(.*?)\n[ \t]*\)", text, re.S)
    assert len(matches) == 1, f"expected one BUILD_INPUTS array, found {len(matches)}"
    items = []
    for line in matches[0].splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            items.append(line.strip('"').strip("'"))
    return items


def test_build_inputs_match_between_gate_and_wizard() -> None:
    gate = _build_inputs((REPO / ".github" / "workflows" / "build.yml").read_text())
    wizard = _build_inputs(WIZARD.read_text())
    assert gate, "no BUILD_INPUTS entries parsed"
    assert gate == wizard


def _require_main_merged_fn(text: str) -> str:
    match = re.search(r"\nrequire_main_merged\(\) \{\n.*?\n\}\n", text, re.S)
    assert match, "require_main_merged function not found in the wizard"
    return match.group(0)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=GIT_ENV,
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "commit.gpgsign", "false")


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _run_require_main_merged(repo: Path, main: str) -> subprocess.CompletedProcess[str]:
    build_inputs = _build_inputs(WIZARD.read_text())
    array = "\n".join(f"  {shlex.quote(item)}" for item in build_inputs)
    script = (
        "set -euo pipefail\n"
        'warn() { printf "%s\\n" "$1" >&2; }\n'
        f"BUILD_INPUTS=(\n{array}\n)\n"
        f"{_require_main_merged_fn(WIZARD.read_text())}\n"
        f"require_main_merged {shlex.quote(main)}\n"
    )
    return subprocess.run(
        ["bash", "-c", script], cwd=repo, capture_output=True, text=True, env=GIT_ENV
    )


def _base_repo(repo: Path) -> tuple[str, str]:
    """Repo with one commit touching a build input and a non-build-input file.

    Returns the current branch name and the base commit SHA.
    """
    _init_repo(repo)
    _write(repo, BUILD_INPUT, "v0\n")
    _write(repo, NON_BUILD_INPUT, "t0\n")
    base = _commit(repo, "base")
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD"), base


def _main_side(repo: Path, branch: str, rel: str, content: str) -> str:
    """Commit a change to `rel` on a detached main line, then return to `branch`.

    Leaves HEAD back on `branch` at its original commit and returns main's SHA.
    """
    _git(repo, "checkout", "-q", "--detach")
    _write(repo, rel, content)
    main = _commit(repo, f"main: {rel}")
    _git(repo, "checkout", "-q", branch)
    return main


def test_require_main_merged_passes_when_main_changed_non_build_input(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "non_build"
    branch, _ = _base_repo(repo)
    main = _main_side(repo, branch, NON_BUILD_INPUT, "t1\n")
    result = _run_require_main_merged(repo, main)
    assert result.returncode == 0, result.stderr


def test_require_main_merged_fails_when_main_changed_build_input(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "build"
    branch, _ = _base_repo(repo)
    main = _main_side(repo, branch, BUILD_INPUT, "v1\n")
    result = _run_require_main_merged(repo, main)
    assert result.returncode == 1
    assert "merging main changes the build inputs" in result.stderr


def test_require_main_merged_passes_after_merging_main(tmp_path: Path) -> None:
    repo = tmp_path / "merged"
    branch, _ = _base_repo(repo)
    main = _main_side(repo, branch, BUILD_INPUT, "v1\n")
    # The PR branch does its own work, then merges main in.
    _write(repo, NON_BUILD_INPUT, "branch\n")
    _commit(repo, "branch work")
    _git(repo, "merge", "-q", "--no-edit", main)
    result = _run_require_main_merged(repo, main)
    assert result.returncode == 0, result.stderr


def test_require_main_merged_passes_when_branch_cherry_picked_main(
    tmp_path: Path,
) -> None:
    # The branch carries main's build-input change as an independent commit
    # (identical content). The three-dot diff would falsely block this; the
    # merge comparison sees the build inputs already equal.
    repo = tmp_path / "cherry"
    branch, _ = _base_repo(repo)
    main = _main_side(repo, branch, BUILD_INPUT, "v1\n")
    _git(repo, "cherry-pick", main)
    result = _run_require_main_merged(repo, main)
    assert result.returncode == 0, result.stderr


def test_require_main_merged_fails_when_branch_conflicts_with_main(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "conflict"
    branch, _ = _base_repo(repo)
    main = _main_side(repo, branch, BUILD_INPUT, "main-side\n")
    _write(repo, BUILD_INPUT, "branch-side\n")
    _commit(repo, "branch: sandbox.py")
    result = _run_require_main_merged(repo, main)
    assert result.returncode == 1
    assert "conflicts with main" in result.stderr
