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


def test_subcommand_help_does_not_import_eval_machinery() -> None:
    """``inspect <cmd> --help`` does not load the eval stack either.

    Importing the subcommand module and rendering its options must work
    without pulling in pydantic / fsspec / the eval loop. Runs each
    subcommand in a fresh interpreter so leakage from one doesn't mask
    another.
    """
    for name in _SUBCOMMANDS:
        probe = (
            "import sys\n"
            f"sys.argv = ['inspect', {name!r}, '--help']\n"
            "try:\n"
            "    import inspect_ai._cli.main as m; m.main()\n"
            "except SystemExit:\n"
            "    pass\n"
            "heavy = [m for m in ('inspect_ai._eval.eval', 'inspect_ai.model',\n"
            "                     'pydantic', 'fsspec', 'anyio')\n"
            "         if m in sys.modules]\n"
            "assert not heavy, f'heavy modules loaded: {heavy}'\n"
            "print('ok')\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, check=False
        )
        assert out.returncode == 0, f"{name}: {out.stderr}"
        assert out.stdout.splitlines()[-1] == "ok", f"{name}: {out.stdout}"
