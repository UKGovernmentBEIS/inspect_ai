import codecs
import os
import sys
import threading
from concurrent.futures import Future
from functools import partial

import anyio
from anyio.lowlevel import RunVar
from rich.console import Console
from rich.prompt import InvalidResponse, Prompt

from inspect_ai._util.platform import running_in_notebook
from inspect_ai._util.transcript import transcript_panel
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.util._console import input_screen

from .._approval import Approval, ApprovalDecision
from .util import (
    HUMAN_APPROVED,
    HUMAN_ESCALATED,
    HUMAN_REJECTED,
    HUMAN_TERMINATED,
    render_tool_approval,
)


async def console_approval(
    message: str,
    view: ToolCallView,
    choices: list[ApprovalDecision],
    call: ToolCall,
) -> Approval:
    """Ask for an approval on the console.

    The wait for a key runs off the event loop, so other samples keep running
    and a cancel (a time limit, an interrupt, or a caller withdrawing the
    approval) withdraws the prompt. Prompts are shown one at a time.
    """
    async with _console_prompt_lock():
        _stdin.discard_typed_ahead()
        with input_screen(width=None) as console:
            console.print(
                transcript_panel(
                    title="Approve Tool",
                    content=render_tool_approval(message, view, call.arguments, call),
                )
            )

            # provide choices
            prompts: dict[str, str] = {}
            for choice in choices:
                prompts[choice[0]] = f"{choice.capitalize()} ({choice[0]})"
            values = list(prompts.values())
            prompt_text = ", ".join(values[:-1])
            prompt_text = f"{prompt_text}, or {values[-1]}"
            prompt = Prompt(prompt_text, console=console, choices=list(prompts.keys()))

            def render_approval(approval: Approval) -> Approval:
                console.print(f"Decision: {approval.decision.capitalize()}")
                return approval

            while True:
                # the loop `Prompt.ask` runs, with the line read off the loop
                console.print(prompt.make_prompt("a"), end="")
                try:
                    line = await _read_answer(console)
                except anyio.get_cancelled_exc_class():
                    console.print("")
                    console.print("Approval withdrawn.")
                    raise
                if line == "":
                    decision = "a"
                else:
                    try:
                        decision = prompt.process_response(line)
                    except InvalidResponse as error:
                        prompt.on_validate_error(line, error)
                        continue

                if decision == "a":
                    return render_approval(
                        Approval(decision="approve", explanation=HUMAN_APPROVED)
                    )
                elif decision == "r":
                    return render_approval(
                        Approval(decision="reject", explanation=HUMAN_REJECTED)
                    )
                elif decision == "t":
                    return render_approval(
                        Approval(decision="terminate", explanation=HUMAN_TERMINATED)
                    )
                elif decision == "e":
                    return render_approval(
                        Approval(decision="escalate", explanation=HUMAN_ESCALATED)
                    )


async def _read_answer(console: Console) -> str:
    """Read the operator's line for the prompt and record it with the screen.

    In a notebook the frontend answers `input()`, and nothing arrives on the
    process's stdin, so the prompt reads with `input()` there and blocks the
    loop while it waits, as it did before.
    """
    # deferred, as `input_screen` defers it: importing `inspect_ai._display`
    # loads the displays
    from inspect_ai._display.core.rich import record_console_line

    if running_in_notebook():
        # `input_screen` records what `Console.input` returns
        return console.input()
    line = await _stdin.readline()
    record_console_line(console, line)
    return line


_prompt_lock: RunVar[anyio.Lock] = RunVar("_console_approval_prompt_lock")


def _console_prompt_lock() -> anyio.Lock:
    """The lock that shows console approval prompts one at a time.

    Waiting for a key no longer blocks the loop, so two samples could otherwise
    show prompts at once and read each other's answers. A `RunVar` gives each
    event loop run its own lock.
    """
    try:
        return _prompt_lock.get()
    except LookupError:
        lock = anyio.Lock()
        _prompt_lock.set(lock)
        return lock


def _read_stdin_chunk() -> bytes:
    """Read what stdin has, up to a limit, waiting until it has something.

    `os.read` rather than `input()`: it holds no lock of `sys.stdin` (a daemon
    thread holding one when the process exits makes it abort) and, unlike
    `readline`, leaves the terminal's mode alone.
    """
    return os.read(sys.stdin.fileno(), 4096)


_WAIT_SLICE = 0.5
"""Seconds a worker thread waits for a read before handing back to the loop."""


class _StdinLines:
    """Lines from stdin, read on a daemon thread.

    A thread blocked in a read cannot be stopped, so a cancelled prompt leaves
    its read running. The next prompt waits on that same read rather than
    starting a second one, so the two never compete for input. Only the event
    loop thread calls these methods.
    """

    def __init__(self) -> None:
        self._pending: Future[bytes] | None = None
        self._text = ""
        self._decoder = codecs.getincrementaldecoder(
            getattr(sys.stdin, "encoding", None) or "utf-8"
        )(errors="replace")

    def discard_typed_ahead(self) -> None:
        """Drop input that arrived while no prompt waited.

        Only what has been read: lines still in the terminal's buffer are read
        by the next prompt, as they are by `input()`.
        """
        self._text = ""
        self._decoder.reset()
        if self._pending is not None and self._pending.done():
            self._pending = None

    async def readline(self) -> str:
        """Wait for the next line, without its line ending.

        Raises:
            EOFError: When stdin is closed.
        """
        while "\n" not in self._text:
            chunk = await self._read()
            if not chunk:
                text, self._text = self._text, ""
                if text:
                    return text
                # a Ctrl+C on Windows ends a console read as end of input:
                # give the cancel it also causes a moment to arrive first, so
                # the sample is cancelled rather than failed (best effort)
                await anyio.sleep(0.1)
                raise EOFError("EOF when reading a line")
            self._text += self._decoder.decode(chunk)
        line, _, self._text = self._text.partition("\n")
        return line.removesuffix("\r")

    async def _read(self) -> bytes:
        if self._pending is None:
            pending: Future[bytes] = Future()
            threading.Thread(
                target=_read_into,
                args=(pending,),
                name="inspect-console-approval-input",
                daemon=True,
            ).start()
            self._pending = pending
        pending = self._pending
        while True:
            try:
                # a bounded wait, so a worker thread never outlives the loop
                # by more than a moment: worker threads are not daemon
                # threads, so one still waiting for input would keep the
                # process from exiting
                chunk = await anyio.to_thread.run_sync(
                    partial(pending.result, timeout=_WAIT_SLICE),
                    abandon_on_cancel=True,
                )
            except TimeoutError:
                continue
            finally:
                # a cancelled wait leaves the read for the next prompt
                if pending.done():
                    self._pending = None
            return chunk


def _read_into(pending: "Future[bytes]") -> None:
    try:
        pending.set_result(_read_stdin_chunk())
    except BaseException as ex:
        pending.set_exception(ex)


_stdin = _StdinLines()
