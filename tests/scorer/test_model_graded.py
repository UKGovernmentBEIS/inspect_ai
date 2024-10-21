from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.scorer import model_graded_fact


def test_model_graded_include_history():
    task = Task(
        dataset=[
            Sample(
                input=[
                    ChatMessageUser(content="Who wrote 'The 39 Steps'?"),
                    ChatMessageAssistant(
                        content="Do you mean the movie or the adaption for the stage?"
                    ),
                    ChatMessageUser(content="The movie."),
                ],
                target="Alfred Hitchcock",
            )
        ],
        scorer=model_graded_fact(include_history=True, model="mockllm/model"),
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.samples
    assert "Do you mean the movie" in log.samples[0].model_dump_json()
