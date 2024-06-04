from inspect_ai import Task, task
from inspect_ai.dataset import example_dataset
from inspect_ai.scorer import model_graded_fact
from inspect_ai.solver import chain_of_thought, generate, self_critique


@task
def theory_of_mind(critique=False):
    # use self_critique if requested
    plan = [chain_of_thought(), generate()]
    if critique:
        plan.append(self_critique())

    return Task(
        dataset=example_dataset("theory_of_mind"),
        plan=plan,
        scorer=model_graded_fact(),
    )
