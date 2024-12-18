from argparse import Namespace
from pathlib import Path
from re import Pattern, compile, match
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from inspect_ai._util.ansi import render_text

from ..state import HumanAgentState
from .command import HumanAgentCommand, call_human_agent


class SubmitCommand(HumanAgentCommand):
    @property
    def name(self) -> str:
        return "submit"

    @property
    def description(self) -> str:
        return "Submit your final answer for the task."

    @property
    def group(self) -> Literal[1, 2, 3]:
        return 1

    @property
    def cli_args(self) -> list[HumanAgentCommand.CLIArg]:
        return [
            HumanAgentCommand.CLIArg(
                name="answer",
                description="Answer to submit for scoring (optional, not required for all tasks)",
            )
        ]

    def cli(self, args: Namespace) -> None:
        # read cli args
        call_args = vars(args)

        # first validate (print and exit if we get a str back)
        error = call_human_agent("validate", **call_args)
        if error:
            print(error)
            return

        # verify that the user wants to proceed
        answer = call_args.get("answer", None)
        answer_text = f" '{answer}'" if answer else ""
        while True:
            response = (
                input(
                    f"\nDo you definitely want to end the task and submit{answer_text}?\n\nThis will disconnect you from the task environment and you won't be able to reconnect.\n\nYes (y) or No (n): "
                )
                .lower()
                .strip()
            )
            if response in ["yes", "y"]:
                break
            elif response in ["no", "n"]:
                return
            else:
                print("Please enter yes or no.")

        # thank the user!
        print(
            "\nThank you for working on this task!\n\n"
            + "Your task will now be scored and you will be disconnected from this container.\n"
        )

        # collect session logs if they exist
        sessions_dir = Path("/var/tmp/user-sessions")
        if sessions_dir.exists() and sessions_dir.is_dir():
            session_logs: dict[str, str] = {}
            for file in sessions_dir.iterdir():
                if file.is_file():
                    try:
                        with open(file, "r", newline="") as f:
                            session_logs[file.name] = f.read()
                    except Exception as e:
                        print(f"Error reading file {file.name}: {e}")
                        continue
            call_args["session_logs"] = session_logs

        # submit the task
        call_human_agent("submit", **call_args)

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def submit(
            answer: str | None, session_logs: dict[str, str] | None = None
        ) -> None:
            state.running = False
            state.answer = answer
            state.session_logs = session_logs

        return submit


class ValidateCommand(HumanAgentCommand):
    def __init__(self, answer: bool | str) -> None:
        self._answer = compile(answer) if isinstance(answer, str) else answer

    @property
    def name(self) -> str:
        return "validate"

    @property
    def description(self) -> str:
        return "Validate a task submission."

    @property
    def contexts(self) -> list[Literal["cli", "service"]]:
        return ["service"]

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def validate(answer: str | None) -> str | None:
            def failed(reason: str) -> str:
                return render_text(f"[bold]FAILED:[/bold] {reason}")

            if not state.running:
                return failed("Task is stopped (use 'task start' to start)")
            if self._answer:
                answer = answer.strip() if isinstance(answer, str) else answer
                if not answer:
                    return failed(
                        "An explicit answer is required for scoring this task."
                    )
                elif isinstance(self._answer, Pattern) and not match(
                    self._answer, answer
                ):
                    return failed(
                        "Your answer was not in the required format (please review the task instructions)"
                    )
            return None  # made it through verification

        return validate
