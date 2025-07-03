import pytest

from inspect_ai.tool.sandbox_tools_utils._build_config import (
    SandboxToolsBuildConfig,
    config_to_filename,
    filename_to_config,
)


# Table-driven test for valid filename_to_config cases
@pytest.mark.parametrize(
    "filename, expected",
    [
        (
            "inspect-tool-support-amd64-v123",
            dict(arch="amd64", version=123, browser=False, suffix=None),
        ),
        (
            "inspect-tool-support-arm64-v200+browser",
            dict(arch="arm64", version=200, browser=True, suffix=None),
        ),
        (
            "inspect-tool-support-amd64-v123-dev",
            dict(arch="amd64", version=123, browser=False, suffix="dev"),
        ),
        (
            "inspect-tool-support-arm64-v123+browser-dev",
            dict(arch="arm64", version=123, browser=True, suffix="dev"),
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
        ("inspect-tool-support-arm64-v1.2.3", "Invalid configuration"),
        # Invalid arch
        ("inspect-tool-support-x86-v123", "Invalid configuration"),
        # Invalid feature
        ("inspect-tool-support-amd64-v123+web", "Invalid configuration"),
        # Invalid suffix
        ("inspect-tool-support-amd64-v123-beta", "Invalid configuration"),
        # Invalid pattern
        ("invalid-filename", "doesn't match expected pattern"),
        # Multiple features (should fail)
        (
            "inspect-tool-support-amd64-v123+browser+other",
            "doesn't match expected pattern",
        ),
        # Extra/invalid characters in arch
        ("inspect-tool-support-amd64$-v123", "doesn't match expected pattern"),
        # Extra/invalid characters in version
        ("inspect-tool-support-amd64-v12a3", "doesn't match expected pattern"),
        # Extra/invalid characters in feature
        ("inspect-tool-support-amd64-v123+browser!", "doesn't match expected pattern"),
        # Extra/invalid characters in suffix
        (
            "inspect-tool-support-amd64-v123+browser-dev!",
            "doesn't match expected pattern",
        ),
        # Case sensitivity (should fail)
        ("inspect-tool-support-AMD64-v123", "Invalid configuration"),
        ("inspect-tool-support-amd64-v123+Browser", "Invalid configuration"),
        ("inspect-tool-support-amd64-v123-DEV", "Invalid configuration"),
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
            SandboxToolsBuildConfig(
                arch="amd64", version=123, browser=False, suffix=None
            ),
            "inspect-tool-support-amd64-v123",
        ),
        (
            SandboxToolsBuildConfig(
                arch="arm64", version=200, browser=True, suffix=None
            ),
            "inspect-tool-support-arm64-v200+browser",
        ),
        (
            SandboxToolsBuildConfig(
                arch="amd64", version=123, browser=False, suffix="dev"
            ),
            "inspect-tool-support-amd64-v123-dev",
        ),
        (
            SandboxToolsBuildConfig(
                arch="arm64", version=123, browser=True, suffix="dev"
            ),
            "inspect-tool-support-arm64-v123+browser-dev",
        ),
    ],
)
def test_config_to_filename_valid(config, expected_filename):
    filename = config_to_filename(config)
    assert filename == expected_filename


@pytest.mark.parametrize(
    "filename",
    [
        "inspect-tool-support-amd64-v123",
        "inspect-tool-support-arm64-v200+browser",
        "inspect-tool-support-amd64-v123-dev",
        "inspect-tool-support-arm64-v123+browser-dev",
    ],
)
def test_roundtrip_conversion(filename):
    """Test that filename -> config -> filename is consistent."""
    config = filename_to_config(filename)
    reconstructed = config_to_filename(config)
    assert reconstructed == filename
