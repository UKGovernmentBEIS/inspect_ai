"""Tests for the dist-validation job in .github/workflows/log_viewer.yml.

The job builds the viewer and checks that the committed bundle in
src/inspect_ai/_view/dist matches the build output. These tests run the
check step's script against a temporary repository whose committed dist and
build output each case changes. The build is not run, so the working-tree
dist stays as committed, as it does when the build skips its copy.
"""

import os
import pathlib
import shutil
import subprocess
import sys
from collections.abc import Callable

import pytest
import yaml

WORKFLOW = (
    pathlib.Path(__file__).parents[1] / ".github" / "workflows" / "log_viewer.yml"
)
DIST = pathlib.Path("src/inspect_ai/_view/dist")
BUILD = pathlib.Path("src/inspect_ai/_view/ts-mono/apps/inspect/dist")
NOT_A_TREE = "src/inspect_ai/_view/dist is missing or not a directory in the commit"
FILES = {
    "index.html": "<script src='assets/index.js'></script>\n",
    "assets/index.js": "console.log('viewer');\n",
}

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="needs bash and POSIX symlinks and file modes",
)


def check_script() -> str:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["dist-validation"]["steps"]
    matching = [s for s in steps if s.get("name") == "Check dist is up-to-date"]
    assert len(matching) == 1
    script: str = matching[0]["run"]
    return script


class Repo:
    """A repository with the bundle committed and an identical build output."""

    def __init__(self, tmp_path: pathlib.Path) -> None:
        self.root = tmp_path / "repo"
        self.runner_temp = tmp_path / "runner-temp"
        self.runner_temp.mkdir()
        (tmp_path / "gitconfig").write_text("")
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "RUNNER_TEMP": str(self.runner_temp),
        }
        self.git("init", "-q", str(self.root), cwd=tmp_path)
        for directory in (DIST, BUILD):
            for name, content in FILES.items():
                self.write(directory / name, content)
        self.write(BUILD / "assets" / "index.js.map", "{}\n")

    def git(self, *args: str, cwd: pathlib.Path | None = None) -> None:
        subprocess.run(
            ["git", *args],
            cwd=cwd or self.root,
            env=self.env,
            check=True,
            capture_output=True,
        )

    def write(self, path: pathlib.Path, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def commit_dist(self) -> None:
        self.git("add", "--force", str(DIST))
        self.git("commit", "-q", "-m", "dist")

    def run_check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-c", check_script()],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )


def edit_committed(repo: Repo) -> None:
    repo.write(DIST / "assets" / "index.js", "console.log('edited');\n")


def extra_committed_file(repo: Repo) -> None:
    repo.write(DIST / "404.html", "<script>alert(1)</script>\n")


def extra_built_file(repo: Repo) -> None:
    repo.write(BUILD / "assets" / "worker.js", "self.onmessage = null;\n")


def committed_file_as_symlink(repo: Repo) -> None:
    repo.write(DIST.parent / "index.js", FILES["assets/index.js"])
    (repo.root / DIST / "assets" / "index.js").unlink()
    (repo.root / DIST / "assets" / "index.js").symlink_to("../../index.js")


def export_ignored_file(repo: Repo) -> None:
    repo.write(DIST / "404.html", "<script>alert(1)</script>\n")
    repo.write(
        DIST / ".gitattributes",
        ".gitattributes export-ignore\n404.html export-ignore\n",
    )


def committed_source_map(repo: Repo) -> None:
    repo.write(DIST / "assets" / "payload.map", "{}\n")


def committed_executable(repo: Repo) -> None:
    (repo.root / DIST / "assets" / "index.js").chmod(0o755)


def dist_as_symlink(repo: Repo) -> None:
    (repo.root / DIST).rename(repo.root / DIST.parent / "viewer")
    (repo.root / DIST).symlink_to("viewer")
    repo.git("add", str(DIST.parent / "viewer"))


def test_check_passes_when_dist_matches_build(tmp_path: pathlib.Path) -> None:
    repo = Repo(tmp_path)
    repo.commit_dist()

    result = repo.run_check()

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "change",
    [
        edit_committed,
        extra_committed_file,
        extra_built_file,
        committed_file_as_symlink,
        export_ignored_file,
        committed_source_map,
        committed_executable,
    ],
)
def test_check_fails_when_dist_differs_from_build(
    tmp_path: pathlib.Path, change: Callable[[Repo], None]
) -> None:
    repo = Repo(tmp_path)
    change(repo)
    repo.commit_dist()

    result = repo.run_check()

    assert result.returncode != 0, result.stdout + result.stderr


def test_check_passes_when_git_excludes_match_built_files(
    tmp_path: pathlib.Path,
) -> None:
    repo = Repo(tmp_path)
    repo.commit_dist()
    (repo.root / ".git" / "info").mkdir(exist_ok=True)
    (repo.root / ".git" / "info" / "exclude").write_text("*.js\n")

    result = repo.run_check()

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("dist_is_symlink", [True, False])
def test_check_names_a_dist_that_is_not_a_committed_directory(
    tmp_path: pathlib.Path, dist_is_symlink: bool
) -> None:
    repo = Repo(tmp_path)
    if dist_is_symlink:
        dist_as_symlink(repo)
        repo.commit_dist()
    else:
        repo.write(pathlib.Path("README.md"), "no dist\n")
        repo.git("add", "README.md")
        repo.git("commit", "-q", "-m", "no dist")

    result = repo.run_check()

    assert result.returncode != 0
    assert NOT_A_TREE in result.stdout


def test_check_fails_when_dist_is_a_gitlink_to_the_built_tree(
    tmp_path: pathlib.Path,
) -> None:
    """A submodule entry whose id is the build's tree hash is not a directory."""
    repo = Repo(tmp_path)
    repo.commit_dist()
    built = subprocess.run(
        ["git", "rev-parse", "HEAD:" + str(DIST)],
        cwd=repo.root,
        env=repo.env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    repo.git("rm", "-r", "-q", "--cached", str(DIST))
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{built},{DIST}")
    repo.git("commit", "-q", "-m", "gitlink")

    result = repo.run_check()

    assert result.returncode != 0, result.stdout + result.stderr
    assert NOT_A_TREE in result.stdout
