import importlib
import subprocess
import sys

import pytest
from click.testing import CliRunner

from inspect_ai._cli.main import _SUBCOMMANDS, inspect


def test_help_lists_all_subcommands() -> None:
    """``inspect --help`` lists every visible lazy subcommand."""
    runner = CliRunner()
    result = runner.invoke(inspect, ["--help"])
    assert result.exit_code == 0
    for name, (_, short_help) in _SUBCOMMANDS.items():
        if short_help:  # hidden commands have empty short_help
            assert name in result.output
            assert short_help in result.output
        else:
            assert name not in result.output


def test_subcommand_help_resolves() -> None:
    """Every registered subcommand resolves to a real click command."""
    runner = CliRunner()
    for name in _SUBCOMMANDS:
        result = runner.invoke(inspect, [name, "--help"])
        assert result.exit_code == 0, f"{name}: {result.output}"
        assert "Usage:" in result.output


@pytest.mark.parametrize("name", sorted(n for n, (_, sh) in _SUBCOMMANDS.items() if sh))
def test_subcommand_short_help_matches_docstring(name: str) -> None:
    """The static ``short_help`` in ``_SUBCOMMANDS`` matches the command's own.

    The registry duplicates each subcommand's one-line help so that
    ``inspect --help`` can render without importing the subcommand
    module. This guards against the duplicate going stale when someone
    edits the command's docstring.
    """
    import_path, registry_short = _SUBCOMMANDS[name]
    modname, attr = import_path.rsplit(":", 1)
    cmd = getattr(importlib.import_module(modname), attr)
    actual_short = cmd.get_short_help_str(limit=200)
    assert registry_short.rstrip(".") == actual_short.rstrip("."), (
        f"_SUBCOMMANDS[{name!r}] short_help is stale:\n"
        f"  registry: {registry_short!r}\n"
        f"  command:  {actual_short!r}\n"
        f"Update the entry in inspect_ai/_cli/main.py to match."
    )


def test_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(inspect, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip()


def test_help_does_not_import_eval_machinery() -> None:
    """``inspect --help`` via the console script does not load the eval stack.

    Runs in a fresh interpreter so the test process's own imports don't
    contaminate ``sys.modules``.
    """
    # import the module path the console script uses and assert the heavy
    # modules were not pulled in.
    probe = (
        "import sys\n"
        "sys.argv = ['inspect', '--help']\n"
        "import inspect_ai._cli.main\n"
        "assert 'inspect_ai._eval.eval' not in sys.modules, 'eval loaded'\n"
        "assert 'pydantic' not in sys.modules, 'pydantic loaded'\n"
        "print('ok')\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


# Packages whose presence in sys.modules after a --help means the lazy
# loading was defeated. Each adds 100+ms and dozens-to-hundreds of modules.
HEAVY_MODULES = (
    "inspect_ai._eval.eval",
    "inspect_ai.model._model",
    "inspect_ai.log._log",
    "pydantic",
    "fsspec",
    "anyio",
    "httpx",
    "numpy",
    "textual",
    "rich.markdown",
    "jsonschema",
    "botocore",
)

# Module-count ceilings: deterministic proxy for "did something heavy
# leak in" that doesn't require enumerating every package. Current
# baselines (2026-05): import inspect_ai ~155, inspect --help ~172,
# inspect <cmd> --help ~210. Thresholds give ~50% headroom for small
# additions; a heavy dep leaking in adds 200-1000 and trips these.
MAX_MODULES_IMPORT_INSPECT_AI = 250
MAX_MODULES_ROOT_HELP = 250
MAX_MODULES_SUBCOMMAND_HELP = 350


def _probe_modules(argv: list[str]) -> tuple[int, list[str]]:
    """Run ``inspect <argv> --help`` in a fresh interpreter; return (module_count, heavy_loaded)."""
    probe = (
        "import sys\n"
        f"sys.argv = {['inspect', *argv, '--help']!r}\n"
        "try:\n"
        "    import inspect_ai._cli.main as m; m.main()\n"
        "except SystemExit:\n"
        "    pass\n"
        f"heavy = [m for m in {HEAVY_MODULES!r} if m in sys.modules]\n"
        "print(len(sys.modules), *heavy)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    parts = out.stdout.strip().splitlines()[-1].split()
    return int(parts[0]), parts[1:]


def test_root_help_import_footprint() -> None:
    """``inspect --help`` stays import-light.

    Asserts both (a) no known-heavy package is loaded and (b) total
    module count is under a ceiling, so a new heavy dep that isn't in
    the explicit list still trips the test.
    """
    n, heavy = _probe_modules([])
    assert not heavy, f"inspect --help loaded heavy modules: {heavy}"
    assert n < MAX_MODULES_ROOT_HELP, (
        f"inspect --help loaded {n} modules (ceiling {MAX_MODULES_ROOT_HELP}). "
        f"Something heavy is now imported at --help time; run with -s to see "
        f"sys.modules and find the new leak."
    )


@pytest.mark.parametrize("name", sorted(_SUBCOMMANDS))
def test_subcommand_help_import_footprint(name: str) -> None:
    """``inspect <cmd> --help`` stays import-light for every subcommand."""
    n, heavy = _probe_modules([name])
    assert not heavy, f"inspect {name} --help loaded heavy modules: {heavy}"
    assert n < MAX_MODULES_SUBCOMMAND_HELP, (
        f"inspect {name} --help loaded {n} modules "
        f"(ceiling {MAX_MODULES_SUBCOMMAND_HELP})."
    )


def test_import_inspect_ai_footprint() -> None:
    """Bare ``import inspect_ai`` stays import-light."""
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import inspect_ai; "
            f"heavy=[m for m in {HEAVY_MODULES!r} if m in sys.modules]; "
            "print(len(sys.modules), *heavy)",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    parts = out.stdout.strip().split()
    n, heavy = int(parts[0]), parts[1:]
    assert not heavy, f"import inspect_ai loaded heavy modules: {heavy}"
    assert n < MAX_MODULES_IMPORT_INSPECT_AI, (
        f"import inspect_ai loaded {n} modules "
        f"(ceiling {MAX_MODULES_IMPORT_INSPECT_AI})."
    )
