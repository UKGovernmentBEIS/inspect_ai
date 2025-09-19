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
            dict(arch="amd64", version=123, suffix=None),
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
    ],
)
def test_roundtrip_conversion(filename):
    """Test that filename -> config -> filename is consistent."""
    config = filename_to_config(filename)
    reconstructed = config_to_filename(config)
    assert reconstructed == filename
