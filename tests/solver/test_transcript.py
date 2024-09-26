from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import transcript
from inspect_ai.scorer import match
from inspect_ai.solver import (
    Generate,
    TaskState,
    generate,
    solver,
)


def test_sample_transcript():
    @solver
    def transcript_solver():
        async def solve(state: TaskState, generate: Generate):
            with transcript().step("info"):
                state.metadata["foo"] = "bar"
                transcript().info(str(state.sample_id))
            return state

        return solve

    task = Task(
        dataset=[
            Sample(input="Say Hello", target="Hello"),
        ],
        solver=[transcript_solver(), generate()],
        scorer=match(),
    )

    log = eval(task, model="mockllm/model")[0]

    # we sometimes use this for debugging our transcript assertions
    # print(
    #     json.dumps(
    #         to_jsonable_python(log.samples[0].transcript, exclude_none=True), indent=2
    #     )
    # )

    assert log.samples[0].transcript.events[1].type == "solver"
    assert log.samples[0].transcript.events[3].data == "1"
    assert log.samples[0].transcript.events[6].event == "state"
