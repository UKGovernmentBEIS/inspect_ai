from test_helpers.utils import skip_if_no_mistral

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate, user_message


@skip_if_no_mistral
def test_mistral_reasoning():
    task = Task(
        dataset=[
            Sample(
                input="John is one of 4 children. The first sister is 4 years old. Next year, the second sister will be twice as old as the first sister. The third sister is two years older than the second sister. The third sister is half the age of her older brother. How old is John?"
            )
        ],
        solver=[
            generate(),
            user_message("That's great, did you enjoy reasoning?"),
            generate(),
        ],
    )
    log = eval(
        task,
        model="mistral/magistral-small-2506",
    )[0]
    assert log.status == "success"
    assert log.samples
    assert isinstance(log.samples[0].messages[1].content[0], ContentReasoning)
