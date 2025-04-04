import asyncio
import os
import pty
from contextlib import AbstractAsyncContextManager


class PseudoTerminalStdIn:
    """Encapsulates the stdin resources of a pseudo-terminal (PTY).

    This class is constructed exclusively by `PseudoTerminal` but its instances
    can be used externally to manually manage the lifetime of PTY resources. It
    provides access to:
    - `coordinator_fd`: Used to send data to the PTY.
    - `terminal_fd`: Used to interact with the subprocess connected to the PTY.
    - `writer`: An `asyncio.StreamWriter` for writing to the coordinator side.

    Methods:
        cleanup():
            Releases the resources by closing the file descriptors and the writer.
    """

    def __init__(
        self, coordinator_fd: int, terminal_fd: int, writer: asyncio.StreamWriter
    ) -> None:
        self.coordinator_fd = coordinator_fd
        self.terminal_fd = terminal_fd
        self.writer = writer

    def cleanup(self) -> None:
        self.writer.transport.close()
        try:
            os.close(self.terminal_fd)
        except OSError:
            pass
        try:
            os.close(self.coordinator_fd)
        except OSError:
            pass


class PseudoTerminal(AbstractAsyncContextManager):
    """A context manager for creating and managing a pseudo-terminal (PTY).

    The PTY has a pair of file descriptors for the two ends of the PTY. The
    coordinator side is used for writing, while the terminal side is used
    for reading and writing to the subprocess.

    This class handles the lifecycle of a PTY, including:
    - Creating the PTY pair (coordinator and terminal)
    - Setting up a writer for the coordinator side
    - Properly closing resources when done

    Usage:
        async with PseudoTerminal() as pty_resources:
            # Use pty_resources.terminal_fd as stdin for a subprocess
            # Use pty_resources.writer to write to the subprocess

    Alternatively, you can use the class method create() to create and the
    cleanup method to clean up the resources manually if the lifetime extends
    beyond a single lexical scope. e.g.:
        pty_resources = await PseudoTerminal.create()
        # Use pty_resources.terminal_fd as stdin for a subprocess
        # Use pty_resources.writer to write to the subprocess
        pty_resources.cleanup()
    """

    @classmethod
    async def create(cls) -> "PseudoTerminalStdIn":
        """Convenience method to create and initialize a PseudoTerminal."""
        instance = cls()
        resources = await instance.__aenter__()
        return resources

    async def cleanup(self) -> None:
        await self.__aexit__(None, None, None)

    def __init__(self) -> None:
        self._inner: PseudoTerminalStdIn | None = None

    async def __aenter__(self) -> PseudoTerminalStdIn:
        """Create the PTY and set up the writer."""

        # Create the PTY pair
        coordinator_fd, terminal_fd = pty.openpty()

        # Set up the writer for the coordinator side
        loop = asyncio.get_event_loop()
        flow_control = asyncio.streams.FlowControlMixin()
        transport, _ = await loop.connect_write_pipe(
            lambda: flow_control, os.fdopen(coordinator_fd, "wb")
        )
        writer = asyncio.StreamWriter(
            transport, protocol=flow_control, reader=None, loop=loop
        )

        self._inner = PseudoTerminalStdIn(
            coordinator_fd=coordinator_fd,
            terminal_fd=terminal_fd,
            writer=writer,
        )
        return self._inner

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._inner:
            self._inner.cleanup()
            self._inner = None
