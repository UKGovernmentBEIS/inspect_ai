from test_helpers.utils import skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.solver import generate, user_message


def get_responses_model(config: GenerateConfig = GenerateConfig()):
    return get_model(
        "openai/gpt-4o-mini",
        config=config,
        responses_api=True,
    )


@skip_if_no_openai
def test_openai_responses_api():
    log = eval(
        Task(dataset=[Sample(input="This is a test string. What are you?")]),
        model=get_responses_model(
            config=GenerateConfig(
                max_tokens=50,
                temperature=0.5,
                top_p=1.0,
            )
        ),
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_responses_assistant_messages():
    log = eval(
        Task(dataset=[Sample(input="Please tell me your favorite color")]),
        solver=[
            generate(),
            user_message("Terrific! Now share your favorite shape."),
            generate(),
            user_message("Delightful! Now share your favorite texture."),
        ],
        model=get_responses_model(),
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_responses_o1_pro():
    log = eval(
        Task(dataset=[Sample(input="Please tell me your favorite color")]),
        model="openai/o1-pro",
    )[0]
    assert log.status == "success"


@skip_if_no_openai
def test_openai_responses_no_store():
    log = eval(Task(), model="openai/o4-mini", model_args=dict(responses_store=False))[
        0
    ]
    assert log.status == "success"
