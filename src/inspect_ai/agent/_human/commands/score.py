from argparse import Namespace
from copy import deepcopy
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from inspect_ai._util.ansi import render_text
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._score import score

from ..._agent import AgentState
from ..state import HumanAgentState, IntermediateScoring
from .command import HumanAgentCommand, call_human_agent


class ScoreCommand(HumanAgentCommand):
    def __init__(self, state: AgentState):
        self._state = state

    @property
    def name(self) -> str:
        return "score"

    @property
    def description(self) -> str:
        return "Score the task to check progress."

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
        # first validate (print and exit if we get a str back)
        call_args = vars(args)
        error = call_human_agent("validate", **call_args)
        if error:
            print(error)
            return

        print(call_human_agent("score", **call_args))

    def service(self, state: HumanAgentState) -> Callable[..., Awaitable[JsonValue]]:
        async def score_task(answer: str | None) -> str:
            # make a copy of TaskState, add the answer, then score
            if answer:
                agent_state = deepcopy(self._state)
                agent_state.output = ModelOutput.from_content("human_agent", answer)
                result = await score(agent_state)
            else:
                result = await score(self._state)

            # record the scoring action in our state
            state.scorings.append(IntermediateScoring(time=state.time, scores=result))

            # notify user
            return render_text(
                f"[bold]Answer:[/bold] {result[0].answer}, [bold]Score:[/bold] {result[0].as_str()}"
            )

        return score_task
