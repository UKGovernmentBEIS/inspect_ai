"""Lazy-loading click command group.

This is the ``LazyGroup`` recipe from the click documentation:
https://click.palletsprojects.com/en/stable/complex/#lazily-loading-subcommands

It defers importing a subcommand's module until that subcommand is actually
requested, so ``inspect --help`` / ``inspect --version`` don't pay the cost of
importing the whole ``inspect_ai`` package.

Deviation from the upstream recipe: ``lazy_subcommands`` maps each name to
``("pkg.module:attr", short_help)`` rather than a bare dotted path. The
``short_help`` is stored statically so the top-level ``--help`` screen can be
rendered without importing any subcommand (the upstream recipe calls
``get_command()`` for each entry to read its help string, which would import
everything). An empty ``short_help`` marks a hidden command. The ``:``
separator is used because module paths themselves contain dots.
"""

import importlib
from typing import Any

import click


class LazyGroup(click.Group):
    def __init__(
        self,
        *args: Any,
        lazy_subcommands: dict[str, tuple[str, str]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # {command-name} -> ({module-path}:{command-attr}, {short-help})
        self.lazy_subcommands = lazy_subcommands or {}
        self._dotenv_done = False

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        lazy = sorted(self.lazy_subcommands)
        return base + [name for name in lazy if name not in base]

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name in self.lazy_subcommands:
            return self._lazy_load(cmd_name)
        return super().get_command(ctx, cmd_name)

    def format_commands(
        self, ctx: click.Context, formatter: click.HelpFormatter
    ) -> None:
        rows: list[tuple[str, str]] = []
        for name in self.list_commands(ctx):
            entry = self.lazy_subcommands.get(name)
            if entry is not None:
                _, short_help = entry
                if short_help:
                    rows.append((name, short_help))
            else:
                cmd = super().get_command(ctx, name)
                if cmd is not None and not cmd.hidden:
                    rows.append((name, cmd.get_short_help_str()))
        if rows:
            with formatter.section("Commands"):
                formatter.write_dl(rows)

    def _lazy_load(self, cmd_name: str) -> click.Command:
        # load .env before click parses subcommand options (envvar= defaults).
        if not self._dotenv_done:
            self._dotenv_done = True
            from inspect_ai._util.dotenv import init_dotenv

            init_dotenv()

        import_path, _ = self.lazy_subcommands[cmd_name]
        modname, cmd_object_name = import_path.rsplit(":", 1)
        mod = importlib.import_module(modname)
        cmd_object = getattr(mod, cmd_object_name)
        if not isinstance(cmd_object, click.Command):
            raise TypeError(
                f"Lazy loading of {import_path} did not yield a click.Command"
            )

        # ``set_exception_hook`` lives in ``_util.error`` which pulls in
        # pydantic + rich, so defer it past click's ``--help`` short-circuit
        # by hooking it onto leaf-command ``invoke()``.
        self._wrap_leaves(cmd_object)

        self.add_command(cmd_object, name=cmd_name)
        return cmd_object

    def _wrap_leaves(self, cmd: click.Command) -> None:
        if isinstance(cmd, click.Group):
            for sub in cmd.commands.values():
                self._wrap_leaves(sub)
            return
        original_invoke = cmd.invoke

        def invoke_with_hook(ctx: click.Context) -> Any:
            from inspect_ai._util.error import set_exception_hook

            set_exception_hook()
            return original_invoke(ctx)

        cmd.invoke = invoke_with_hook  # type: ignore[method-assign]
