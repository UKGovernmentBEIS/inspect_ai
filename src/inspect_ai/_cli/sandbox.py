import asyncio

import click

from inspect_ai.util._sandbox.registry import registry_find_sandboxenv


@click.group("sandbox")
def sandbox_command() -> None:
    """Manage Sandbox Environments."""
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
    asyncio.run(cli_cleanup(environment_id))
