import importlib
import os

from rich import print

from inspect_ai._util.constants import PKG_NAME
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
        hook_names = [f"  {_format_hook_for_printing(hook)}" for hook in registry_hooks]
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

    # Note that hooks loaded by virtue of load_file_tasks() -> load_module() (e.g.
    # if the user defines an @hook alongside their task) won't be loaded by now.
    hooks = get_all_hooks()
    _registry_hooks_loaded = True
    _verify_all_required_hooks(hooks)
    return hooks


def _verify_all_required_hooks(installed: list[Hooks]) -> None:
    """Verify that all required hooks are installed.

    Required hooks are configured via the `INSPECT_REQUIRED_HOOKS` environment variable.
    If any required hooks are missing, a `PrerequisiteError` is raised.

    Set the `INSPECT_REQUIRED_HOOKS` environment variable to a comma-separated list of
    required hook names e.g. `INSPECT_REQUIRED_HOOKS=package/hooks_1,package/hooks_2`.
    """
    required_hooks_env_var = os.environ.get("INSPECT_REQUIRED_HOOKS", "")
    # Create a set of required hook names, remove the empty string element if it exists.
    required_names = set(required_hooks_env_var.split(",")) - {""}
    if not required_names:
        return
    installed_names = {registry_info(hook).name for hook in installed}
    missing_names = required_names - installed_names
    if missing_names:
        raise PrerequisiteError(
            f"Required hook(s) missing: {missing_names}.\n"
            f"INSPECT_REQUIRED_HOOKS is set to '{required_hooks_env_var}'.\n"
            f"Installed hooks: {installed_names}.\n"
            "Please ensure required hooks are installed in your virtual environment."
        )


def _format_hook_for_printing(hook: Hooks) -> str:
    info = registry_info(hook)
    description = info.metadata["description"]
    return f"[bold]{info.name}[/bold]: {description}"
