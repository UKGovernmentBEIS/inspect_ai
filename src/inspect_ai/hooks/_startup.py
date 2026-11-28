import importlib
import os

from rich import print
from rich.markup import escape

from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.entrypoints import ensure_entry_points, entry_point_load_errors
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import registry_info
from inspect_ai.hooks._hooks import Hooks
from inspect_ai.hooks._legacy import init_legacy_hooks

_registry_hooks_loaded: bool = False


def init_hooks() -> None:
    # messages we'll print for hooks if we have them
    messages = init_legacy_hooks()

    registry_hooks = _load_registry_hooks()
    if registry_hooks:
        enabled_hooks = [h for h in registry_hooks if h.enabled()]
        hook_names = [f"  {_format_hook_for_printing(hook)}" for hook in enabled_hooks]
        hook_names_joined = "\n".join(hook_names)
        messages.append(
            f"[bold]hooks enabled: {len(hook_names)}[/bold]\n{hook_names_joined}"
        )

    # if any hooks are enabled, let the user know
    if len(messages) > 0:
        version = importlib.metadata.version(PKG_NAME)
        all_messages = "\n".join([f"- {message}" for message in messages])
        print(
            f"[blue][bold]inspect_ai v{version}[/bold][/blue]\n"
            f"[bright_black]{all_messages}[/bright_black]\n"
        )


def _load_registry_hooks() -> list[Hooks]:
    global _registry_hooks_loaded
    if _registry_hooks_loaded:
        return []

    from inspect_ai.hooks._hooks import get_all_hooks

    # registry_find() falls back to loading entry points only when its scan comes up
    # empty, so a hook registered by an earlier import (e.g. init_legacy_hooks()
    # importing the INSPECT_TELEMETRY package) would otherwise hide every
    # entry-point hook from this once-per-process load.
    ensure_entry_points()

    # Note that hooks loaded by virtue of load_file_tasks() -> load_module() (e.g.
    # if the user defines an @hook alongside their task) won't be loaded by now.
    hooks = get_all_hooks()
    _verify_all_required_hooks(hooks)
    _registry_hooks_loaded = True
    return hooks


def _verify_all_required_hooks(installed: list[Hooks]) -> None:
    """Verify that all required hooks are installed.

    Required hooks are configured via the `INSPECT_REQUIRED_HOOKS` environment variable.
    If an entry point from a required hook's package failed to load, or any
    required hooks are missing, a `PrerequisiteError` is raised.

    Set the `INSPECT_REQUIRED_HOOKS` environment variable to a comma-separated list of
    required hook names e.g. `INSPECT_REQUIRED_HOOKS=package/hooks_1,package/hooks_2`.
    """
    required_hooks_env_var = os.environ.get("INSPECT_REQUIRED_HOOKS", "")
    # Create a set of required hook names, remove the empty string element if it exists.
    required_names = set(required_hooks_env_var.split(",")) - {""}
    if not required_names:
        return
    _raise_for_required_hook_load_errors(required_names, required_hooks_env_var)
    installed_names = {registry_info(hook).name for hook in installed}
    missing_names = required_names - installed_names
    if missing_names:
        raise PrerequisiteError(
            f"Required hook(s) missing: {missing_names}.\n"
            f"INSPECT_REQUIRED_HOOKS is set to '{required_hooks_env_var}'.\n"
            f"Installed hooks: {installed_names}.\n"
            "Please ensure required hooks are installed in your virtual environment."
        )


def _raise_for_required_hook_load_errors(
    required_names: set[str], required_hooks_env_var: str
) -> None:
    """Raise if an entry point from a required hook's package failed to load.

    A hook's registry name is prefixed with the top-level package of the module
    that registered it, so an entry point is matched by its name or by the
    top-level package of its module.
    """
    errors: list[str] = []
    first_exception: Exception | None = None
    for ep, ex in entry_point_load_errors().items():
        ep_package = ep.value.partition(":")[0].partition(".")[0]
        hook_names = sorted(
            name
            for name in required_names
            if "/" in name and name.partition("/")[0] in (ep.name, ep_package)
        )
        if hook_names:
            first_exception = first_exception or ex
            errors.append(
                escape(
                    f"  {', '.join(hook_names)} from entry point '{ep.value}': "
                    f"{type(ex).__name__}: {ex}"
                )
            )
    if errors:
        raise PrerequisiteError(
            "Entry point(s) for required hook(s) failed to load:\n"
            + "\n".join(errors)
            + f"\nINSPECT_REQUIRED_HOOKS is set to '{required_hooks_env_var}'."
        ) from first_exception


def _format_hook_for_printing(hook: Hooks) -> str:
    info = registry_info(hook)
    description = info.metadata["description"]
    return f"[bold]{info.name}[/bold]: {description}"
