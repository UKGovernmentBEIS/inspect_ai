from inspect_ai import Task, task
from inspect_ai.dataset import example_dataset
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, system_message

SYSTEM_MESSAGE = """
Classify the following sentence of a news article as either:
- fact (statment free of rephrasing, interpretation, opinions,
  and emotions)
- opinion (expression of a personal view, judgement, appraisal,
  opinion, or nterpretation)
- claim (assertion of unverified information, rephrased facts
  or affirmation of opinions),
- argument (data, information, reference, opinion, or narrative
  used to support a claim),
- data (raw data or statistics, must incluide the source which
  cant be a person, and must exclude any data interpretation
- quote (direct quote from a person or a document)
- narrative (a story, account of events, experiences, or context
  used to illustrate a claim or argument)
- sensationalism (when it incluides exaggerations, sarcasm,
  emotion inducing manipulation, scandal-mongering, or other
  sensational behavior to induce emotions)
- speculation (assumption, theory or opinion about a future
  event or a hypothetical scenario).

Please provide a reasoning for your classification and then
state your final answer enclosed in square brackets.
"""

@task
def bias_detection():
    return Task(
        dataset=example_dataset("bias_detection"),
        plan=[system_message(SYSTEM_MESSAGE), generate()],
        scorer=includes(),
    )

