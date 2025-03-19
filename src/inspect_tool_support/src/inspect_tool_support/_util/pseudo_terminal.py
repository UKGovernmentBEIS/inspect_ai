import asyncio
import os
import pty
import termios
from contextlib import AbstractAsyncContextManager


class PseudoTerminalIO:
    """Encapsulates the I/O resources of a pseudo-terminal (PTY).

    This class is constructed exclusively by `PseudoTerminal` but its instances
    can be used externally to manually manage the lifetime of PTY resources. It
    provides access to:
    - `coordinator_fd`: Used to send and receive data from the PTY.
    - `subprocess_fd`: Used to interact with the subprocess connected to the PTY.
    - `writer`: An `asyncio.StreamWriter` for writing to the coordinator side.
    - `reader`: An `asyncio.StreamReader` for reading from the coordinator side.

    Methods:
        cleanup():
            Releases the resources by closing the file descriptors, reader and writer.
    """

    def __init__(
        self,
        coordinator_fd: int,
        subprocess_fd: int,
        writer: asyncio.StreamWriter,
        reader: asyncio.StreamReader,
        read_transport: asyncio.ReadTransport,
    ) -> None:
        self._coordinator_fd = coordinator_fd
        self._subprocess_fd = subprocess_fd
        self._writer = writer
        self._reader = reader
        self._read_transport = read_transport

    @property
    def coordinator_fd(self) -> int:
        """The file descriptor for the coordinator side of the PTY."""
        return self._coordinator_fd

    @property
    def subprocess_fd(self) -> int:
        """The file descriptor for the subprocess side of the PTY."""
        return self._subprocess_fd

    @property
    def writer(self) -> asyncio.StreamWriter:
        """A StreamWriter for writing to the coordinator side."""
        return self._writer

    @property
    def reader(self) -> asyncio.StreamReader:
        """A StreamReader for reading from the coordinator side."""
        return self._reader

    def cleanup(self) -> None:
        self._writer.transport.close()
        # Close the read transport
        self._read_transport.close()
        try:
            os.close(self._subprocess_fd)
        except OSError:
            pass
        try:
            os.close(self._coordinator_fd)
        except OSError:
            pass


class PseudoTerminal(AbstractAsyncContextManager):
    """A context manager for creating and managing a pseudo-terminal (PTY).

    The PTY has a pair of file descriptors for the two ends of the PTY. The
    coordinator side is used for reading and writing, while the terminal side is used
    for reading and writing to the subprocess.

    This class handles the lifecycle of a PTY, including:
    - Creating the PTY pair (coordinator and terminal)
    - Setting up a reader and writer for the coordinator side
    - Properly closing resources when done

    Usage:
        async with PseudoTerminal() as pty_resources:
            # Use pty_resources.subprocess_fd as stdin for a subprocess
            # Use pty_resources.writer to write to the subprocess
            # Use pty_resources.reader to read from the subprocess

    Alternatively, you can use the class method create() to create and the
    cleanup method to clean up the resources manually if the lifetime extends
    beyond a single lexical scope. e.g.:
        pty_resources = await PseudoTerminal.create()
        # Use pty_resources.subprocess_fd as stdin for a subprocess
        # Use pty_resources.writer to write to the subprocess
        # Use pty_resources.reader to read from the subprocess
        pty_resources.cleanup()
    """

    @classmethod
    async def create(cls) -> "PseudoTerminalIO":
        """Convenience method to create and initialize a PseudoTerminal."""
        instance = cls()
        resources = await instance.__aenter__()
        return resources

    async def cleanup(self) -> None:
        await self.__aexit__(None, None, None)

    def __init__(self) -> None:
        self._inner: PseudoTerminalIO | None = None

    async def __aenter__(self) -> PseudoTerminalIO:
        """Create the PTY and set up the reader and writer."""
        # Create the PTY pair
        coordinator_fd, subprocess_fd = pty.openpty()

        # Attempt to disable control characters to make it easier to read the output
        # In practice, this isn't working, and we still strip them at a higher level
        attrs = termios.tcgetattr(coordinator_fd)
        # attrs[0] &= ~termios.IEXTEN  # Disable extended input processing
        # Disable output processing - this prevents translation of characters like LF to CR-LF
        attrs[1] &= ~termios.OPOST
        # Disable echo and any other local modes
        attrs[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON)

        termios.tcsetattr(coordinator_fd, termios.TCSANOW, attrs)

        # We need to duplicate the file descriptor for reading and writing separately
        read_fd = os.dup(coordinator_fd)
        write_fd = os.dup(coordinator_fd)

        # Set up the reader and writer for the coordinator side
        loop = asyncio.get_event_loop()

        # Set up reader
        reader = asyncio.StreamReader()
        read_protocol = asyncio.StreamReaderProtocol(reader)
        read_transport, _ = await loop.connect_read_pipe(
            lambda: read_protocol, os.fdopen(read_fd, "rb")
        )

        # Set up writer
        write_flow_control = asyncio.streams.FlowControlMixin()
        write_transport, _ = await loop.connect_write_pipe(
            lambda: write_flow_control, os.fdopen(write_fd, "wb")
        )
        writer = asyncio.StreamWriter(
            write_transport, protocol=write_flow_control, reader=None, loop=loop
        )

        self._inner = PseudoTerminalIO(
            coordinator_fd=coordinator_fd,
            subprocess_fd=subprocess_fd,
            writer=writer,
            reader=reader,
            read_transport=read_transport,
        )
        return self._inner

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._inner:
            self._inner.cleanup()
            self._inner = None
