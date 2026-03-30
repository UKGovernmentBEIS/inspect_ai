import click


@click.command("attach")
@click.argument("socket_path", required=False, default=None)
def attach_command(socket_path: str | None) -> None:
    """Attach to a running eval's socket server.

    If no SOCKET_PATH is given, auto-detects the most recent socket.
    Press q to detach. Use the Running Samples tab to cancel samples.
    """
    from inspect_ai._display.socket.client import main as client_main

    client_main(socket_path)
