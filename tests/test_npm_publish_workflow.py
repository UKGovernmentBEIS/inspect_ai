"""Tests for .github/workflows/npm-publish.yml.

The build job selects the viewer package with ``pnpm --filter``. A filter
that matches no workspace package makes pnpm print "No projects matched the
filters" and exit 0, which turned the quality checks and the prerelease
library build into silent no-ops. These tests resolve every filter against
the ts-mono workspace, require ``--fail-if-no-match``, and check that the
gitignored CSS-module typings are generated before ``check-all`` runs tsc.

They also check the build/publish split: only the publish job holds the
publishing id-token, and it runs nothing from the repository.
"""

import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from typing import Any, NamedTuple

import pytest
import yaml

REPO = pathlib.Path(__file__).parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "npm-publish.yml"
TS_MONO = REPO / "src" / "inspect_ai" / "_view" / "ts-mono"

_submodule_missing = not (TS_MONO / "pnpm-workspace.yaml").exists()


def job(name: str) -> dict[str, Any]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    config: dict[str, Any] = workflow["jobs"][name]
    return config


def job_steps(name: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job(name)["steps"]
    return steps


def pnpm_commands() -> list[list[str]]:
    """Every ``pnpm ...`` command line in the build job's run scripts, tokenized."""
    commands = []
    for step in job_steps("build"):
        for line in step.get("run", "").splitlines():
            if line.strip().startswith("pnpm "):
                commands.append(shlex.split(line))
    return commands


def filter_selectors(command: list[str]) -> list[str]:
    """Package names selected by ``--filter`` in a pnpm command line.

    Strips the ``...`` dependency and ``^`` exclusion markers so that
    ``pkg...`` and ``^pkg`` resolve to ``pkg``.
    """
    selectors = []
    for i, token in enumerate(command):
        if token == "--filter" and i + 1 < len(command):
            selectors.append(command[i + 1])
        elif token.startswith("--filter="):
            selectors.append(token.removeprefix("--filter="))
    return [s.strip("^").removesuffix("...").removeprefix("...") for s in selectors]


def filtered_commands() -> list[list[str]]:
    commands = [c for c in pnpm_commands() if filter_selectors(c)]
    assert commands, "expected the build job to filter pnpm to the viewer package"
    return commands


def workspace_package_names() -> set[str]:
    globs = yaml.safe_load((TS_MONO / "pnpm-workspace.yaml").read_text())["packages"]
    return {
        json.loads(pkg.read_text())["name"]
        for pattern in globs
        for pkg in TS_MONO.glob(f"{pattern}/package.json")
    }


@pytest.mark.skipif(_submodule_missing, reason="ts-mono submodule not initialized")
def test_filters_name_a_workspace_package() -> None:
    names = workspace_package_names()
    for command in filtered_commands():
        for selector in filter_selectors(command):
            assert selector in names, (
                f"{shlex.join(command)!r} filters on {selector!r}, which is not "
                f"a ts-mono workspace package; pnpm would silently run nothing"
            )


def test_filters_fail_if_no_match() -> None:
    for command in filtered_commands():
        assert "--fail-if-no-match" in command, (
            f"{shlex.join(command)!r} must fail loudly if its filter matches "
            f"no package instead of exiting 0 having run nothing"
        )


def test_css_typings_generated_before_checks() -> None:
    steps = job_steps("build")
    checks = [i for i, s in enumerate(steps) if "check-all" in s.get("run", "")]
    assert len(checks) == 1, "expected exactly one step running check-all"
    generated = [i for i, s in enumerate(steps) if "generate:css" in s.get("run", "")]
    assert generated and generated[0] < checks[0], (
        "check-all runs tsc outside turbo, so the gitignored *.module.css.d.ts "
        "typings must be generated in an earlier step"
    )


def npm_upgrade_spec(job_name: str) -> str:
    upgrade = next(s for s in job_steps(job_name) if "npm-upgrade" in s.get("run", ""))
    (install,) = [
        shlex.split(line)
        for line in upgrade["run"].splitlines()
        if line.strip().startswith("npm install")
    ]
    assert "--ignore-scripts" in install
    (spec,) = [token for token in install if token.startswith("npm@")]
    return spec


def test_npm_upgrade_is_pinned_without_install_scripts() -> None:
    # The publish job holds the npm publishing id-token, so the npm it runs
    # must not float or run install scripts. The build job's dry-run uses the
    # same npm, so it applies the same publish checks.
    spec = npm_upgrade_spec("publish")
    assert re.fullmatch(r"npm@\d+\.\d+\.\d+", spec), spec
    assert npm_upgrade_spec("build") == spec


def test_only_the_publish_job_holds_the_id_token() -> None:
    build = job("build")
    assert build["permissions"] == {"contents": "read"}
    assert "environment" not in build

    publish = job("publish")
    assert publish["needs"] == "build"
    assert publish["permissions"]["id-token"] == "write"
    assert publish["environment"] == "npm"


def test_publish_job_runs_nothing_from_the_repository() -> None:
    steps = job_steps("publish")
    actions = [s["uses"].split("@")[0] for s in steps if "uses" in s]
    assert actions == ["actions/setup-node", "actions/download-artifact"]
    for step in steps:
        assert "pnpm" not in step.get("run", "")
    publish = next(s for s in steps if s.get("name") == "Publish to NPM")
    assert publish["run"].startswith('npm publish "$TARBALL" --ignore-scripts')


def test_build_runs_prepublish_before_packing() -> None:
    # Publishing a tarball runs no lifecycle scripts, so the build job must run
    # prepublishOnly itself.
    runs = [s.get("run", "") for s in job_steps("build")]
    prepublish = next(i for i, r in enumerate(runs) if "run prepublishOnly" in r)
    pack = next(i for i, r in enumerate(runs) if "npm pack" in r)
    assert prepublish < pack
    assert "--ignore-scripts" in runs[pack]


class PackageCheck(NamedTuple):
    returncode: int
    stdout: str
    outputs: dict[str, str]


def run_package_check(
    tmp_path: pathlib.Path,
    version: str,
    tag: str,
    prerelease: str = "",
    name: str = "@meridianlabs/log-viewer",
    tarballs: int = 1,
) -> PackageCheck:
    """Run the publish job's "Check the package" script on packed tarballs."""
    package = tmp_path / "package"
    package.mkdir()
    (package / "package.json").write_text(
        json.dumps({"name": name, "version": version})
    )
    (tmp_path / "npm-package").mkdir()
    for i in range(tarballs):
        with tarfile.open(tmp_path / "npm-package" / f"pkg{i}.tgz", "w:gz") as tar:
            tar.add(package, arcname="package")
    output = tmp_path / "github_output"
    output.touch()

    script = next(s for s in job_steps("publish") if s.get("id") == "package")["run"]
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "TAG": tag,
            "PRERELEASE": prerelease,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return PackageCheck(result.returncode, result.stdout, outputs)


_no_package_check = sys.platform == "win32" or shutil.which("jq") is None


@pytest.mark.skipif(_no_package_check, reason="needs a POSIX shell and jq")
def test_package_check_hands_npm_an_absolute_tarball_path(
    tmp_path: pathlib.Path,
) -> None:
    # npm reads a relative `dir/file.tgz` as a GitHub `user/repo` shorthand.
    check = run_package_check(tmp_path, "0.3.285", "0.3.285")
    assert check.returncode == 0, check.stdout
    assert pathlib.Path(check.outputs["tarball"]).is_absolute()
    assert check.outputs["version"] == "0.3.285"


@pytest.mark.skipif(_no_package_check, reason="needs a POSIX shell and jq")
@pytest.mark.parametrize(
    "version,tag,prerelease,ok",
    [
        ("0.3.285", "0.3.284", "", False),
        ("0.3.285", "main", "", False),
        ("0.3.285", "main", "true", False),
        ("0.3.286-beta.1761500000", "main", "true", True),
    ],
)
def test_package_check_publishes_only_the_release_version(
    tmp_path: pathlib.Path, version: str, tag: str, prerelease: str, ok: bool
) -> None:
    check = run_package_check(tmp_path, version, tag, prerelease)
    assert (check.returncode == 0) is ok, check.stdout


@pytest.mark.skipif(_no_package_check, reason="needs a POSIX shell and jq")
@pytest.mark.parametrize(
    "name,tarballs,error",
    [
        ("@meridianlabs/log-viewer", 0, "Expected one package tarball, found 0"),
        ("@meridianlabs/log-viewer", 2, "Expected one package tarball, found 2"),
        ("@meridianlabs/other", 1, "Unexpected package name '@meridianlabs/other'"),
    ],
)
def test_package_check_rejects_anything_but_one_log_viewer_tarball(
    tmp_path: pathlib.Path, name: str, tarballs: int, error: str
) -> None:
    check = run_package_check(
        tmp_path, "0.3.285", "0.3.285", name=name, tarballs=tarballs
    )
    assert check.returncode != 0
    assert f"::error::{error}" in check.stdout
    assert check.outputs == {}
