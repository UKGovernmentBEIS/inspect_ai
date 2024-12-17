from argparse import Namespace
from copy import deepcopy
from time import time
from typing import Awaitable, Callable, Literal

from pydantic import JsonValue

from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._score import score
from inspect_ai.solver import TaskState

from ..state import HumanAgentState, IntermediateScore
from .command import HumanAgentCommand, call_human_agent


class ScoreCommand(HumanAgentCommand):
    def __init__(self, state: TaskState):
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
                task_state = deepcopy(self._state)
                task_state.output = ModelOutput.from_content("human_agent", answer)
                result = await score(task_state)
            else:
                result = await score(self._state)

            # record the scoring action
            state.intermediate_scores.append(
                IntermediateScore(time=time(), scores=result)
            )

            # provide feedback to user
            # TODO: feedback to user
            # TODO: log to transcript

            return ""

        return score_task
