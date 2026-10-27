"""The sandbox-tools version-bump gate, exercised end to end.

The gate lives in `.github/workflows/build.yml` as two `run:` steps: the
`injectable` step in `detect-slow` computes `injectable_src_changed` from
`injectable_paths.txt`, and the `bump` step in `check-version-bump` requires a
version bump whenever an injectable input changed (and forbids a bump without
one). These tests extract the real step scripts and run them with bash in a
throwaway git repo, so they cover the actual shell the gate runs.

The regression they pin: a change to a build input that feeds the binary but
lives outside `src/inspect_sandbox_tools/` (a lockfile, a Dockerfile, the
`requirements.txt` build lock — the shape of inspect_ai PR 6102) must now fail
the gate without a version bump. Three invariants also check that
`injectable_paths.txt` covers everything the build reads, sits inside the
provenance `BUILD_INPUTS` set, and excludes the host-side files.
"""

import ast
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml
from test_sandbox_tools_release import (
    GIT_ENV,
    REPO,
    _build_inputs,
    _commit,
    _git,
    _init_repo,
    _write,
)

UTILS = "src/inspect_ai/tool/_sandbox_tools_utils"
V_PATH = f"{UTILS}/sandbox_tools_version.txt"
INJECTABLE_PATHS = f"{UTILS}/injectable_paths.txt"

BASE_VERSION = "36"

# One seed file per category a test edits; every path a PR touches must exist on
# the base commit so a diff can be produced against it.
SEED_FILES = [
    f"{UTILS}/requirements.txt",
    f"{UTILS}/Dockerfile.pyinstaller",
    f"{UTILS}/Dockerfile.pyinstaller.musl",
    f"{UTILS}/conda-amd64.lock",
    f"{UTILS}/conda-arm64.lock",
    f"{UTILS}/build_executable.py",
    f"{UTILS}/sandbox.py",
    "src/inspect_sandbox_tools/pyproject.toml",
    "src/inspect_sandbox_tools/src/inspect_sandbox_tools/foo.py",
    "src/inspect_sandbox_tools/tests/x.py",
    "src/inspect_sandbox_tools/design/x.md",
    "src/inspect_sandbox_tools/README.md",
]


def _step_run(job: str, step_id: str) -> str:
    """Extract a step's `run:` script from build.yml by job and step id."""
    workflow = yaml.safe_load((REPO / ".github/workflows/build.yml").read_text())
    for step in workflow["jobs"][job]["steps"]:
        if step.get("id") == step_id:
            run = step.get("run")
            assert run, f"step id={step_id} in {job} has no run script"
            return str(run)
    raise AssertionError(f"no step id={step_id} in job {job}")


def _bash(
    script: str, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    # Match GitHub Actions' default bash invocation for `run:` steps.
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def _github_output(path: Path) -> dict[str, str]:
    pairs = (
        line.split("=", 1) for line in path.read_text().splitlines() if "=" in line
    )
    return {k: v for k, v in pairs}


def _seed_repo(repo: Path) -> None:
    _init_repo(repo)
    _write(repo, V_PATH, f"{BASE_VERSION}\n")
    # Use the production injectable_paths.txt so the pathspecs under test are the
    # real ones, not a hand-copied list that could drift.
    _write(repo, INJECTABLE_PATHS, (REPO / INJECTABLE_PATHS).read_text())
    for rel in SEED_FILES:
        _write(repo, rel, "base\n")
    base = _commit(repo, "base")
    # The gate diffs against origin/${BASE_REF}; make that ref resolve locally.
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _git(repo, "checkout", "-q", "-b", "pr")


class GateResult(NamedTuple):
    injectable_src: str
    bump_returncode: int
    bump_output: str
    correctly_bumped: str | None


def _run_gate(repo: Path, tmp_path: Path) -> GateResult:
    inj_out = tmp_path / "injectable_output"
    inj_out.write_text("")
    inj = _bash(
        _step_run("detect-slow", "injectable"),
        repo,
        {**GIT_ENV, "BASE_REF": "main", "GITHUB_OUTPUT": str(inj_out)},
    )
    assert inj.returncode == 0, inj.stderr + inj.stdout
    injectable_src = _github_output(inj_out)["injectable_src"]

    bump_out = tmp_path / "bump_output"
    bump_out.write_text("")
    bump = _bash(
        _step_run("check-version-bump", "bump"),
        repo,
        {
            **GIT_ENV,
            "BASE_REF": "main",
            "INJECTABLE_SRC_CHANGED": injectable_src,
            "GITHUB_OUTPUT": str(bump_out),
        },
    )
    return GateResult(
        injectable_src=injectable_src,
        bump_returncode=bump.returncode,
        bump_output=bump.stdout + bump.stderr,
        correctly_bumped=_github_output(bump_out).get("correctly_bumped"),
    )


def _change(repo: Path, edits: dict[str, str], version: str | None = None) -> None:
    for rel, content in edits.items():
        _write(repo, rel, content)
    if version is not None:
        _write(repo, V_PATH, f"{version}\n")
    _commit(repo, "pr change")


# --- Gate behavior -----------------------------------------------------------

# Build inputs outside src/inspect_sandbox_tools/ that must require a bump. The
# lock (requirements.txt) is the PR-6102 regression this change fixes.
INJECTABLE_BUILD_FILES = [
    f"{UTILS}/requirements.txt",
    f"{UTILS}/Dockerfile.pyinstaller",
    f"{UTILS}/Dockerfile.pyinstaller.musl",
    f"{UTILS}/conda-amd64.lock",
    f"{UTILS}/build_executable.py",
    "src/inspect_sandbox_tools/pyproject.toml",
]


@pytest.mark.parametrize("path", INJECTABLE_BUILD_FILES)
def test_injectable_change_without_bump_fails(path: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _change(repo, {path: "edited\n"})
    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "true"
    assert result.bump_returncode == 1
    assert "bump it above" in result.bump_output


def test_source_change_with_bump_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _change(
        repo,
        {"src/inspect_sandbox_tools/src/inspect_sandbox_tools/foo.py": "edited\n"},
        version="37",
    )
    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "true"
    assert result.bump_returncode == 0
    assert result.correctly_bumped == "true"


def test_lock_change_with_bump_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _change(repo, {f"{UTILS}/requirements.txt": "edited\n"}, version="37")
    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "true"
    assert result.bump_returncode == 0
    assert result.correctly_bumped == "true"


# Changes that do not feed the binary: excluded subtrees and host-side files.
NON_INJECTABLE_FILES = [
    "src/inspect_sandbox_tools/tests/x.py",
    "src/inspect_sandbox_tools/design/x.md",
    "src/inspect_sandbox_tools/README.md",
    f"{UTILS}/sandbox.py",
]


@pytest.mark.parametrize("path", NON_INJECTABLE_FILES)
def test_non_injectable_change_without_bump_passes(path: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _change(repo, {path: "edited\n"})
    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "false"
    assert result.bump_returncode == 0
    assert result.correctly_bumped == "false"


@pytest.mark.parametrize("path", NON_INJECTABLE_FILES)
def test_non_injectable_change_with_bump_fails(path: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _change(repo, {path: "edited\n"}, version="37")
    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "false"
    assert result.bump_returncode == 1
    assert "unchanged" in result.bump_output


def test_bump_alone_without_content_change_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _seed_repo(repo)
    _change(repo, {}, version="37")
    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "false"
    assert result.bump_returncode == 1
    assert "unchanged" in result.bump_output


def test_base_advance_after_merge_commit_not_attributed_to_pr(
    tmp_path: Path,
) -> None:
    """A base-only injectable change made after the merge commit isn't the PR's.

    GitHub's refs/pull/N/merge commit is cut from the base tip at generation
    time. If the base then advances with an injectable change, the three-dot
    diff (merge-base of base and merge commit .. merge commit) must attribute it
    to the base, not the PR. The two-dot form (base tip .. merge commit) wrongly
    flags it and demands a bump the PR never caused.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, V_PATH, f"{BASE_VERSION}\n")
    _write(repo, INJECTABLE_PATHS, (REPO / INJECTABLE_PATHS).read_text())
    for rel in SEED_FILES:
        _write(repo, rel, "base\n")
    base = _commit(repo, "base")

    # PR branch off the base touches only a doc file (not injectable).
    _git(repo, "checkout", "-q", "-b", "pr", base)
    _write(repo, "src/inspect_sandbox_tools/README.md", "pr doc\n")
    pr = _commit(repo, "pr doc change")

    # The base advances with a lock change made after the PR branched.
    _git(repo, "checkout", "-q", "-b", "newbase", base)
    _write(repo, f"{UTILS}/requirements.txt", "advanced base lock\n")
    advanced = _commit(repo, "base advances the lock")
    _git(repo, "update-ref", "refs/remotes/origin/main", advanced)

    # Reconstruct the PR merge commit Actions checks out: first parent the old
    # base, second the PR head, cut before the base advanced.
    _git(repo, "checkout", "-q", "--detach", base)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge pr", pr)

    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "false"
    assert result.bump_returncode == 0
    assert result.correctly_bumped == "false"


def test_whitespace_padded_injectable_entry_still_matches(tmp_path: Path) -> None:
    """A padded pathspec in injectable_paths.txt is trimmed like sandbox.py does.

    The CI step must strip leading and trailing whitespace off each line; a
    verbatim padded entry would match no path and silently miss its input.
    """
    repo = tmp_path / "repo"
    _seed_repo(repo)
    req_line = f"{UTILS}/requirements.txt"
    padded = (
        (REPO / INJECTABLE_PATHS).read_text().replace(req_line, f"   {req_line}   ")
    )
    _change(repo, {INJECTABLE_PATHS: padded, req_line: "edited\n"})
    result = _run_gate(repo, tmp_path)
    assert result.injectable_src == "true"
    assert result.bump_returncode == 1
    assert "bump it above" in result.bump_output


# --- Invariants between injectable_paths.txt, the build, and BUILD_INPUTS -----


def _read_injectable_pathspecs() -> list[str]:
    text = (REPO / INJECTABLE_PATHS).read_text()
    return [
        line
        for raw in text.splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    ]


def _ls_files(pathspecs: list[str]) -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *pathspecs],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {p for p in out.split("\0") if p}


def _dockerfile_copy_sources(dockerfile: Path) -> list[str]:
    """Context-relative COPY sources from a Dockerfile, ${TARGETARCH} expanded.

    The build context root is _sandbox_tools_utils (build_within_container.py
    runs `docker build ... .` from that directory), so sources resolve there.
    """
    sources: list[str] = []
    for line in dockerfile.read_text().splitlines():
        if line.strip().upper().startswith("COPY "):
            tokens = line.split()[1:]
            # all but the destination are sources
            for src in tokens[:-1]:
                for arch in ("amd64", "arm64"):
                    sources.append(src.replace("${TARGETARCH}", arch))
    return sources


def _same_dir_imports(script: Path) -> set[Path]:
    """Transitively resolve modules imported from `script`'s own directory."""
    directory = script.parent
    resolved: set[Path] = set()
    queue = [script]
    while queue:
        current = queue.pop()
        tree = ast.parse(current.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.rsplit(".", 1)[-1])
            elif isinstance(node, ast.ImportFrom):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                names.extend(alias.name.rsplit(".", 1)[-1] for alias in node.names)
            for name in names:
                candidate = directory / f"{name}.py"
                if candidate.exists() and candidate not in resolved:
                    resolved.add(candidate)
                    queue.append(candidate)
    return resolved


def test_injectable_paths_cover_everything_the_build_reads() -> None:
    utils = REPO / UTILS
    dockerfiles = [
        utils / "Dockerfile.pyinstaller",
        utils / "Dockerfile.pyinstaller.musl",
    ]
    build_scripts = [utils / "build_within_container.py", utils / "build_executable.py"]

    required: set[Path] = set(dockerfiles) | set(build_scripts)
    for dockerfile in dockerfiles:
        for src in _dockerfile_copy_sources(dockerfile):
            required.add(utils / src)
    for script in build_scripts:
        required |= _same_dir_imports(script)

    required_rel = {p.relative_to(REPO).as_posix() for p in required}
    for path in required_rel:
        assert (REPO / path).exists(), f"build reads {path} but it is missing"

    covered = _ls_files(_read_injectable_pathspecs())
    missing = required_rel - covered
    assert not missing, (
        f"injectable_paths.txt does not cover build inputs: {sorted(missing)}"
    )


def test_injectable_set_is_subset_of_build_inputs() -> None:
    injectable = _ls_files(_read_injectable_pathspecs())
    build_inputs = _ls_files(
        _build_inputs((REPO / ".github/workflows/build.yml").read_text())
    )
    assert injectable, "no injectable files resolved"
    extra = injectable - build_inputs
    assert not extra, (
        f"injectable files outside BUILD_INPUTS provenance set: {sorted(extra)}"
    )


def test_host_side_files_are_not_injectable() -> None:
    injectable = _ls_files(_read_injectable_pathspecs())
    host_side = [
        f"{UTILS}/sandbox.py",
        f"{UTILS}/upload_to_s3.py",
        f"{UTILS}/_digests.py",
        f"{UTILS}/SHA256SUMS",
        f"{UTILS}/sandbox_tools_version.txt",
        f"{UTILS}/requirements.in",
    ]
    for path in host_side:
        assert (REPO / path).exists(), f"expected {path} to exist in the repo"
        assert path not in injectable, f"{path} must not be an injectable input"
