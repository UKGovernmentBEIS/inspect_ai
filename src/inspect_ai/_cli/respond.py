import asyncio
import json
import sys

import click


@click.command("respond")
@click.argument("socket_path", required=False, default=None)
@click.option("--request-id", "-r", default=None, help="ID of the pending input request")
@click.argument("text", required=False, default=None)
def respond_command(socket_path: str | None, request_id: str | None, text: str | None) -> None:
    """Send a response to a pending input request on a running eval.

    If no --request-id given, shows pending requests and prompts for selection.
    """
    from inspect_ai._display.socket.client import find_socket

    if socket_path is None:
        socket_path = find_socket()
        if socket_path is None:
            click.echo("No running inspect eval found.", err=True)
            sys.exit(1)

    import os

    if not os.path.exists(socket_path):
        click.echo(f"Socket not found: {socket_path}", err=True)
        sys.exit(1)

    async def run() -> None:
        reader, writer = await asyncio.open_unix_connection(socket_path)

        snapshot_line = await reader.readline()
        snapshot = json.loads(snapshot_line)

        pending = snapshot.get("pending_inputs", [])

        nonlocal request_id, text

        if request_id is None:
            if not pending:
                click.echo("No pending input requests.")
                writer.close()
                return

            click.echo("Pending input requests:")
            for i, p in enumerate(pending):
                click.echo(f"  [{i}] {p['request_id']}: {p['prompt']}")

            choice = click.prompt("Select request", type=int, default=0)
            if 0 <= choice < len(pending):
                request_id = pending[choice]["request_id"]
            else:
                click.echo("Invalid choice.")
                writer.close()
                return

        if text is None:
            prompt_text = ""
            for p in pending:
                if p["request_id"] == request_id:
                    prompt_text = p["prompt"]
                    break
            text = click.prompt(prompt_text or "Response")

        from inspect_ai._event_bus.protocol import InputResponseCommand, to_json_line

        cmd = InputResponseCommand(request_id=request_id, text=text)
        writer.write(to_json_line(cmd))
        await writer.drain()
        click.echo(f"Response sent for request {request_id}")
        writer.close()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
