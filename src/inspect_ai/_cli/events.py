import asyncio
import sys

import click


@click.command("events")
@click.argument("socket_path", required=False, default=None)
def events_command(socket_path: str | None) -> None:
    """Stream raw JSON events from a running eval to stdout.

    Pipe to jq, grep, or curl for filtering and forwarding.
    """
    from inspect_ai._display.socket.client import find_socket

    if socket_path is None:
        socket_path = find_socket()
        if socket_path is None:
            click.echo("No running inspect eval found. Specify a socket path.", err=True)
            sys.exit(1)

    import os

    if not os.path.exists(socket_path):
        click.echo(f"Socket not found: {socket_path}", err=True)
        sys.exit(1)

    async def stream() -> None:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                sys.stdout.write(line.decode("utf-8"))
                sys.stdout.flush()
        except asyncio.CancelledError:
            pass
        finally:
            writer.close()

    try:
        asyncio.run(stream())
    except KeyboardInterrupt:
        pass
