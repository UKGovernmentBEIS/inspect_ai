import asyncio

import click

from inspect_ai.solver._tool.environment.registry import registry_find_toolenv


@click.group("toolenv")
def toolenv_command() -> None:
    """Manage Tool Environments."""
    return None


@toolenv_command.command("cleanup")
@click.argument("type", type=str, required=True)
@click.argument("environment_id", type=str, required=False)
def toolenv_cleanup(type: str, environment_id: str | None) -> None:
    """Cleanup Tool Environments.

    TYPE specifies the tool environment type (e.g. 'docker')

    Pass an ENVIRONMENT_ID to cleanup only a single environment
    (otherwise all environments will be cleaned up).
    """
    toolenv_type = registry_find_toolenv(type)
    cli_cleanup = getattr(toolenv_type, "cli_cleanup")
    asyncio.run(cli_cleanup(environment_id))
