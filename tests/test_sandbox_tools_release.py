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

import hashlib
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

REPO = Path(__file__).parents[1]
WIZARD = REPO / "scripts" / "release-sandbox-tools.sh"
WORKFLOWS = REPO / ".github" / "workflows"
PUBLISH_WORKFLOW = WORKFLOWS / "sandbox-tools-publish.yml"

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


# ──────────────────────────────────────────────────────────────────────────
# The sandbox-tools-publish.yml workflow: the only credentialed uploader.
# ──────────────────────────────────────────────────────────────────────────

FOUR_PERMISSIONS = {
    "id-token": "write",
    "actions": "read",
    "attestations": "read",
    "contents": "read",
}


def _job_steps(config: dict[str, Any], job: str) -> list[dict[str, Any]]:
    return config["jobs"][job].get("steps") or []


def _uses_aws_credentials(step: dict[str, Any]) -> bool:
    action = step.get("uses", "").split("@")[0]
    inputs = step.get("with") or {}
    return (
        action == "aws-actions/configure-aws-credentials" or "role-to-assume" in inputs
    )


def test_only_publish_job_assumes_an_aws_role() -> None:
    """configure-aws-credentials / role-to-assume appears in exactly one job."""
    found: set[tuple[str, str]] = set()
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        config = yaml.safe_load(workflow.read_text())
        for job in config.get("jobs", {}):
            for step in _job_steps(config, job):
                if _uses_aws_credentials(step):
                    found.add((workflow.name, job))
    assert found == {("sandbox-tools-publish.yml", "publish")}


def test_publish_workflow_is_locked_down() -> None:
    config = yaml.safe_load(PUBLISH_WORKFLOW.read_text())
    # Top-level permissions empty; the job grants exactly the four it needs.
    assert config["permissions"] == {}
    job = config["jobs"]["publish"]
    assert job["permissions"] == FOUR_PERMISSIONS
    assert job["environment"] == "sandbox-tools-s3"
    # Concurrency serializes publishes and never cancels one mid-upload.
    assert config["concurrency"]["group"] == "sandbox-tools-publish"
    assert config["concurrency"]["cancel-in-progress"] is False


def test_publish_job_installs_nothing_and_restores_no_cache() -> None:
    config = yaml.safe_load(PUBLISH_WORKFLOW.read_text())
    toolchain = {
        "actions/setup-python",
        "astral-sh/setup-uv",
        "actions/setup-node",
        "actions/cache",
        "actions/cache/restore",
    }
    for step in _job_steps(config, "publish"):
        action = step.get("uses", "").split("@")[0]
        assert action not in toolchain, f"publish must not use {action}"
        run = step.get("run", "")
        assert "pip install" not in run
        assert not re.search(r"\buv\b", run)
        assert not re.search(r"\bnpm\b", run)


def test_wizard_publish_title_matches_workflow_run_name() -> None:
    run_name = yaml.safe_load(PUBLISH_WORKFLOW.read_text())["run-name"]
    run_name = run_name.replace("${{ inputs.version }}", "9").replace(
        "${{ inputs.run_id }}", "123"
    )
    match = re.search(
        r'displayTitle == \\"(Publish sandbox tools[^\\"]*)\\"', WIZARD.read_text()
    )
    assert match, "publish run-name match not found in the wizard"
    title = match.group(1).replace("$2", "9").replace("$1", "123")
    assert title == run_name


# ──────────────────────────────────────────────────────────────────────────
# upload_to_s3.py: skip matching objects, upload missing, abort on mismatch.
# ──────────────────────────────────────────────────────────────────────────

ARCH_VARIANTS = ["amd64", "amd64-musl", "arm64", "arm64-musl"]


def _make_binaries(tmp_path: Path, version: int) -> tuple[Path, dict[str, str]]:
    bindir = tmp_path / "binaries"
    bindir.mkdir()
    digests: dict[str, str] = {}
    for variant in ARCH_VARIANTS:
        name = f"inspect-sandbox-tools-{variant}-v{version}"
        data = f"bytes-of-{name}".encode()
        (bindir / name).write_bytes(data)
        digests[name] = hashlib.sha256(data).hexdigest()
    return bindir, digests


class _FakeS3:
    """A public-read bucket and `aws s3api put-object`, keyed by object name."""

    def __init__(self, published: dict[str, str]) -> None:
        self.published = dict(published)  # name -> digest; absent means not published
        self.puts: list[list[str]] = []

    def hash_obj(self, name: str) -> str | None:
        return self.published.get(name)

    def run(self, cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
        self.puts.append(cmd)
        key = cmd[cmd.index("--key") + 1]
        body = cmd[cmd.index("--body") + 1]
        self.published[key] = hashlib.sha256(Path(body).read_bytes()).hexdigest()
        return subprocess.CompletedProcess(cmd, 0)


def _setup_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: int,
    make_published: Callable[[dict[str, str]], dict[str, str]],
) -> tuple[Any, _FakeS3, dict[str, str]]:
    from inspect_ai.tool._sandbox_tools_utils import upload_to_s3

    bindir, digests = _make_binaries(tmp_path, version)
    version_file = tmp_path / "sandbox_tools_version.txt"
    version_file.write_text(f"{version}\n")
    fake = _FakeS3(make_published(digests))
    monkeypatch.setattr(upload_to_s3, "BINARIES_DIR", bindir)
    monkeypatch.setattr(upload_to_s3, "VERSION_FILE", version_file)
    monkeypatch.setattr(upload_to_s3, "_sha256_of_s3_object", fake.hash_obj)
    # upload_to_s3 calls subprocess.run via this same module object.
    monkeypatch.setattr(subprocess, "run", fake.run)
    monkeypatch.setattr(
        upload_to_s3, "write_sha256sums", lambda entries, path=None: None
    )
    monkeypatch.setattr(sys, "argv", ["upload_to_s3.py", str(version)])
    return upload_to_s3, fake, digests


def test_upload_skips_matching_and_uploads_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    version = 36

    def make_published(digests: dict[str, str]) -> dict[str, str]:
        names = list(digests)
        # Two already published with matching bytes; the other two missing.
        return {names[0]: digests[names[0]], names[1]: digests[names[1]]}

    mod, fake, digests = _setup_upload(monkeypatch, tmp_path, version, make_published)
    mod.main()

    names = list(digests)
    uploaded = {cmd[cmd.index("--key") + 1] for cmd in fake.puts}
    assert uploaded == {names[2], names[3]}
    for cmd in fake.puts:
        assert cmd[:3] == ["aws", "s3api", "put-object"]
        assert cmd[cmd.index("--bucket") + 1] == "inspect-sandbox-tools"
        assert cmd[cmd.index("--if-none-match") + 1] == "*"
        assert cmd[cmd.index("--acl") + 1] == "public-read"


def test_upload_is_idempotent_when_all_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    version = 36
    mod, fake, _ = _setup_upload(monkeypatch, tmp_path, version, lambda d: dict(d))
    mod.main()
    assert fake.puts == []


def test_upload_aborts_on_mismatch_without_uploading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    version = 36

    def make_published(digests: dict[str, str]) -> dict[str, str]:
        names = list(digests)
        # Mismatch on the LAST filename, earlier ones missing (would be queued
        # for upload): proves every check runs before any upload happens.
        return {names[3]: "0" * 64}  # published with different bytes

    mod, fake, _ = _setup_upload(monkeypatch, tmp_path, version, make_published)
    with pytest.raises(SystemExit):
        mod.main()
    assert fake.puts == []
