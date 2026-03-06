from pydantic import Field

from inspect_ai import Task, eval, score
from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatMessage, ChatMessageBase
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import StoreModel, store, store_as


def test_score_store_access() -> None:
    class MyStore(StoreModel):
        messages: list[ChatMessage] = Field(default_factory=list)

    @solver
    def store_writer() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            # typed store value
            my_store = store_as(MyStore)
            my_store.messages = state.messages

            # raw store value
            store().set("answer", 42)

            return state

        return solve

    # run eval
    log = eval(Task(solver=store_writer(), model="mockllm/model"))[0]

    # re-read log from disk
    log = read_eval_log(log.location)

    @scorer(metrics=[accuracy()])
    def store_reader() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            # read from typed store
            my_store = store_as(MyStore)

            messages = my_store.messages
            assert isinstance(messages[0], ChatMessageBase)

            # read raw store value and validate answer
            return Score(value=store().get("answer") == 42)

        return score

    log = score(log, store_reader())
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1
