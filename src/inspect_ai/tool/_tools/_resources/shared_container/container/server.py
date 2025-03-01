import asyncio
import os
import subprocess
import sys


async def _run_subprocess(command: str, cwd: str):
    process = await asyncio.create_subprocess_exec(
        *command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd
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
    command1 = ["python3", "-u", "-m", "web_browser.web_server"]
    command2 = ["python3", "-u", "-m", "bash.bash_server"]
    root_dir = os.path.dirname(__file__)
    print(f"XXXXX about to load subprocesses with {root_dir=}")

    await asyncio.gather(
        _run_subprocess(command1, root_dir), _run_subprocess(command2, root_dir)
    )


print(f"XXXXX server.py loaded with {__name__=}")
if __name__ == "__main__":
    asyncio.run(main())
