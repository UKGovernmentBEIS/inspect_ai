import anyio
import click

from inspect_ai._util._async import configured_async_backend
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv


@click.group("sandbox")
def sandbox_command() -> None:
    """Manage Sandbox Environments.

    Learn more about sandboxing at https://inspect.aisi.org.uk/sandboxing.html.
    """
    return None


@sandbox_command.command("cleanup")
@click.argument("type", type=str, required=True)
@click.argument("environment_id", type=str, required=False)
def sandbox_cleanup(type: str, environment_id: str | None) -> None:
    """Cleanup Sandbox Environments.

    TYPE specifies the sandbox environment type (e.g. 'docker')

    Pass an ENVIRONMENT_ID to cleanup only a single environment
    (otherwise all environments will be cleaned up).
    """
    sandboxenv_type = registry_find_sandboxenv(type)
    cli_cleanup = getattr(sandboxenv_type, "cli_cleanup")
    anyio.run(cli_cleanup, environment_id, backend=configured_async_backend())
