from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import web_browser


@task
def browser():
    return Task(
        dataset=[
            Sample(
                input="Use the web browser tool to navigate to https://www.aisi.gov.uk/. Then, see if you can find a page on the site that describes the work of the UK AISI. Then, summarize this work in two paragraphs."
            )
        ],
        solver=[
            # web_browser() is deprecated and will be removed in a future release,
            # together with this example (see inspect_ai issue #5497)
            use_tools(web_browser()),
            generate(),
        ],
        scorer=includes(),
        sandbox="docker",
    )
