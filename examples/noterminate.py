from inspect_ai import Task, task
from inspect_ai import eval as ins_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    scorer,
)
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox


@task(name="always_infinite_loop")
def always_infinite_loop() -> Task:
    d = MemoryDataset(
        samples=[Sample(input="", target="", id=1), Sample(input="", target="", id=2)]
    )
    return Task(dataset=d, epochs=1, sandbox="docker", time_limit=10, scorer=verify())


@scorer(metrics=[accuracy()])
def verify() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        code = "while True: pass"
        explanation = ""

        try:
            result = await sandbox().exec(cmd=["python", "-c", code], timeout=1)
        except TimeoutError:
            return Score(
                value=INCORRECT,
                answer=code,
                explanation="Code execution timed out after 1 second",
            )
        except Exception as e:
            return Score(
                value=INCORRECT,
                answer=code,
                explanation=f"Error: {e}",
            )

        if result.success:
            explanation += "All test cases passed.\n"
        else:
            explanation += "Code did not pass all test cases.\n"
        return Score(
            value=CORRECT if result.success else INCORRECT,
            answer=code,
            explanation=explanation,
        )

    return score


if __name__ == "__main__":
    ins_eval(
        always_infinite_loop(),
        model="openai/gpt-4o-mini",
    )
