import re
import tomllib
from pathlib import Path

import pytest

from inspect_ai.tool._sandbox_tools_utils._build_config import (
    SandboxToolsBuildConfig,
    config_to_filename,
    filename_to_config,
)


# Table-driven test for valid filename_to_config cases
@pytest.mark.parametrize(
    "filename, expected",
    [
        (
            "inspect-sandbox-tools-amd64-v123",
            dict(arch="amd64", version=123, suffix=None, musl=False),
        ),
        (
            "inspect-sandbox-tools-arm64-v200",
            dict(arch="arm64", version=200, suffix=None),
        ),
        (
            "inspect-sandbox-tools-amd64-v123-dev",
            dict(arch="amd64", version=123, suffix="dev"),
        ),
        (
            "inspect-sandbox-tools-arm64-v123-dev",
            dict(arch="arm64", version=123, suffix="dev"),
        ),
        (
            "inspect-sandbox-tools-amd64-musl-v123",
            dict(arch="amd64", version=123, suffix=None, musl=True),
        ),
        (
            "inspect-sandbox-tools-arm64-musl-v19-dev",
            dict(arch="arm64", version=19, suffix="dev", musl=True),
        ),
    ],
)
def test_filename_to_config_valid(filename, expected):
    config = filename_to_config(filename)
    for k, v in expected.items():
        assert getattr(config, k) == v


@pytest.mark.parametrize(
    "filename, error_match",
    [
        # Invalid version format (semantic versioning)
        ("inspect-sandbox-tools-arm64-v1.2.3", "Invalid configuration"),
        # Invalid arch
        ("inspect-sandbox-tools-x86-v123", "Invalid configuration"),
        # Invalid feature
        ("inspect-sandbox-tools-amd64-v123+web", "Invalid configuration"),
        # Invalid suffix
        ("inspect-sandbox-tools-amd64-v123-beta", "Invalid configuration"),
        # Invalid pattern
        ("invalid-filename", "doesn't match expected pattern"),
        # Multiple suffixes (should fail)
        (
            "inspect-sandbox-tools-amd64-v123-dev-test",
            "doesn't match expected pattern",
        ),
        # Extra/invalid characters in arch
        ("inspect-sandbox-tools-amd64$-v123", "doesn't match expected pattern"),
        # Extra/invalid characters in version
        ("inspect-sandbox-tools-amd64-v12a3", "doesn't match expected pattern"),
        # Extra/invalid characters in suffix
        ("inspect-sandbox-tools-amd64-v123-dev!", "doesn't match expected pattern"),
        # Extra characters after suffix
        (
            "inspect-sandbox-tools-amd64-v123-dev-extra",
            "doesn't match expected pattern",
        ),
        # Case sensitivity (should fail)
        ("inspect-sandbox-tools-AMD64-v123", "Invalid configuration"),
        ("inspect-sandbox-tools-amd64-v123-DEV", "Invalid configuration"),
    ],
)
def test_filename_to_config_invalid(filename, error_match):
    with pytest.raises(ValueError):
        filename_to_config(filename)


# Table-driven test for valid config_to_filename cases
@pytest.mark.parametrize(
    "config, expected_filename",
    [
        (
            SandboxToolsBuildConfig(arch="amd64", version=123, suffix=None),
            "inspect-sandbox-tools-amd64-v123",
        ),
        (
            SandboxToolsBuildConfig(arch="arm64", version=200, suffix=None),
            "inspect-sandbox-tools-arm64-v200",
        ),
        (
            SandboxToolsBuildConfig(arch="amd64", version=123, suffix="dev"),
            "inspect-sandbox-tools-amd64-v123-dev",
        ),
        (
            SandboxToolsBuildConfig(arch="arm64", version=123, suffix="dev"),
            "inspect-sandbox-tools-arm64-v123-dev",
        ),
        (
            SandboxToolsBuildConfig(arch="amd64", version=123, suffix=None, musl=True),
            "inspect-sandbox-tools-amd64-musl-v123",
        ),
        (
            SandboxToolsBuildConfig(arch="arm64", version=19, suffix="dev", musl=True),
            "inspect-sandbox-tools-arm64-musl-v19-dev",
        ),
    ],
)
def test_config_to_filename_valid(config, expected_filename):
    filename = config_to_filename(config)
    assert filename == expected_filename


@pytest.mark.parametrize(
    "filename",
    [
        "inspect-sandbox-tools-amd64-v123",
        "inspect-sandbox-tools-arm64-v200",
        "inspect-sandbox-tools-amd64-v123-dev",
        "inspect-sandbox-tools-arm64-v123-dev",
        "inspect-sandbox-tools-amd64-musl-v123",
        "inspect-sandbox-tools-arm64-musl-v123-dev",
    ],
)
def test_roundtrip_conversion(filename):
    """Test that filename -> config -> filename is consistent."""
    config = filename_to_config(filename)
    reconstructed = config_to_filename(config)
    assert reconstructed == filename


# The release builders install only pinned, hashed inputs (see RELEASING.md).
REPO = Path(__file__).parents[3]
UTILS = REPO / "src" / "inspect_ai" / "tool" / "_sandbox_tools_utils"
DOCKERFILES = ["Dockerfile.pyinstaller", "Dockerfile.pyinstaller.musl"]


def from_images(dockerfile: str) -> list[str]:
    """External images in FROM lines, skipping references to earlier stages."""
    text = (UTILS / dockerfile).read_text()
    stages = re.findall(r"^FROM \S+ AS (\S+)$", text, re.MULTILINE)
    images = re.findall(r"^FROM (\S+)", text, re.MULTILINE)
    return [i for i in images if i not in stages and "${" not in i]


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_builder_base_images_are_pinned_by_digest(dockerfile: str) -> None:
    images = from_images(dockerfile)
    assert images
    assert all(re.fullmatch(r"\S+:\S+@sha256:[0-9a-f]{64}", i) for i in images)


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_builders_pip_install_only_the_hashed_lock(dockerfile: str) -> None:
    text = (UTILS / dockerfile).read_text().replace("\\\n", " ")
    installs = [line for line in text.splitlines() if "pip install" in line]
    assert len(installs) == 1
    assert {
        "--require-hashes",
        "--no-deps",
        "--only-binary",
        "--no-build-isolation",
    } <= set(installs[0].split())
    assert installs[0].split()[-1] == "/tmp/requirements.txt"


def test_build_lock_covers_the_package_dependencies() -> None:
    # Hashes are enforced at install time by --require-hashes (test above).
    pyproject = tomllib.loads(
        (REPO / "src" / "inspect_sandbox_tools" / "pyproject.toml").read_text()
    )
    requirements = (UTILS / "requirements.txt").read_text()
    pins = set(re.findall(r"^([a-z0-9-]+)==", requirements, re.MULTILINE))
    names = {
        re.split(r"[<>=\[ ;]", dep)[0].lower()
        for dep in pyproject["project"]["dependencies"]
    }
    assert names | {"pyinstaller", "setuptools", "wheel"} <= pins


@pytest.mark.parametrize("arch", ["amd64", "arm64"])
def test_conda_lock_is_explicit_and_matches_the_base_image(arch: str) -> None:
    lines = (UTILS / f"conda-{arch}.lock").read_text().splitlines()
    (image,) = from_images("Dockerfile.pyinstaller")
    assert f"# from {image}" in lines
    packages = lines[lines.index("@EXPLICIT") + 1 :]
    assert packages
    assert all(
        re.fullmatch(
            r"https://conda\.anaconda\.org/conda-forge/\S+\.conda#sha256:[0-9a-f]{64}",
            p,
        )
        for p in packages
    )
    assert any("/python-3.10." in p for p in packages)
