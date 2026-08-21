"""Guard that the test environment matches the injectable's dependency pins.

The injectable binary is built against the dependency resolution of
src/inspect_sandbox_tools/pyproject.toml. If this suite instead runs in an
environment resolved from the repo root (whose lockfile can and does diverge —
e.g. mcp 2.x vs this package's mcp<2 pin), it silently exercises versions the
shipped artifact never runs, and regressions against the pinned versions pass
unnoticed. This test turns that divergence into an explicit failure.

Pins are read from the installed distribution's metadata rather than from
pyproject.toml: editing that file marks the injectable source as changed, which
obliges a version bump and a new published binary (see
design/sandbox-tools-ci-gates.md), and the metadata is written from the same
pyproject at install time anyway.
"""

from importlib.metadata import PackageNotFoundError, requires, version

from packaging.requirements import Requirement

_PACKAGE = "inspect_sandbox_tools"

_REMEDY = f"""
The test environment does not satisfy {_PACKAGE}'s own dependency pins, so
these tests are exercising versions the shipped injectable binary never uses.
Run them in an environment resolved from the injectable's pyproject, e.g. from
the repo root:

    uv venv .venv-sandbox-tools
    uv pip install --python .venv-sandbox-tools/bin/python './src/inspect_sandbox_tools[dev]'
    uv run --no-project --python .venv-sandbox-tools/bin/python pytest src/inspect_sandbox_tools/tests/

Plain `uv run` re-syncs the environment to the repo root lockfile before running,
which is what puts the wrong versions in place; --no-project (or --no-sync, as
CI uses) prevents that.
"""


def test_environment_matches_injectable_pins() -> None:
    try:
        declared = requires(_PACKAGE) or []
    except PackageNotFoundError:
        raise AssertionError(f"{_PACKAGE} is not installed.\n{_REMEDY}") from None

    # extras are excluded: the binary ships only the runtime dependencies, and
    # markers referencing an unset `extra` evaluate false against "".
    dependencies = [
        requirement
        for requirement in map(Requirement, declared)
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""})
    ]

    problems: list[str] = []
    for requirement in dependencies:
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            problems.append(
                f"{requirement.name}: not installed (declared '{requirement}')"
            )
            continue
        if not requirement.specifier.contains(installed, prereleases=True):
            problems.append(
                f"{requirement.name}: installed {installed} does not satisfy '{requirement}'"
            )

    assert dependencies, f"no runtime dependencies found for {_PACKAGE}"
    assert not problems, "\n".join(problems) + "\n" + _REMEDY
