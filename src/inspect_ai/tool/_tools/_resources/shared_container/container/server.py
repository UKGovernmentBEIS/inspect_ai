import asyncio
import subprocess
import sys


async def _run_subprocess(command):
    process = await asyncio.create_subprocess_exec(
        *command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    async def pipe_stream(stream, target):
        while True:
            line = await stream.readline()
            if not line:
                break
            target.write(line.decode())
            target.flush()

    await asyncio.gather(
        pipe_stream(process.stdout, sys.stdout), pipe_stream(process.stderr, sys.stderr)
    )

    await process.wait()


async def main():
    command1 = ["python3", "-u", "./web_browser/web_server.py"]
    command2 = ["python3", "-u", "./bash/bash_server.py"]

    await asyncio.gather(
        _run_subprocess(command1),
        _run_subprocess(command2)
    )


if __name__ == "__main__":
    asyncio.run(main())
