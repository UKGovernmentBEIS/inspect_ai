import re
from logging import getLogger
from typing import Callable, Literal

from inspect_ai._util.dict import omit
from inspect_ai.model._model import Model, ModelName, get_model
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import resource

from ._metric import Score
from ._metrics import accuracy, stderr
from ._model import (
    DEFAULT_GRADE_PATTERN,
    DEFAULT_MODEL_GRADED_QA_TEMPLATE,
    chat_history,
    default_instructions,
    model_scoring_prompt,
)
from ._scorer import Scorer, scorer
from ._target import Target

logger = getLogger(__name__)


@scorer(metrics=[accuracy(), stderr()])
def cross_model_verifier(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: str | Model | None = None,
    model_role: str | None = "grader",
    on_same_model: Literal["error", "warn", "allow"] = "error",
) -> Scorer:
    """Model-graded scorer that requires the grader to differ from the actor.

    This is `model_graded_qa` with one added guarantee: the model that grades
    the answer (the *verifier*) must not be the same model that produced the
    answer (the *actor*). A model grading its own output tends to be
    self-favouring, so keeping the two roles distinct is a common requirement
    for governed or third-party evaluations. This scorer makes that separation
    explicit and fails loudly (by default) when it is violated, rather than
    silently letting a model mark its own homework.

    The verifier is resolved with the same precedence as `model_graded_qa`
    (`model` > `model_role` > the model under evaluation). Because the default
    `model_role` is `"grader"`, the intended usage is to bind a distinct grader
    via the `model_roles` argument to `eval()`; if no such role is bound the
    verifier falls back to the model under evaluation, which is exactly the
    same-model case this scorer is designed to catch.

    Grade parsing, prompt templating, and prompt-injection hardening are
    inherited unchanged from `model_graded_qa`.

    Args:
      template: Template for the grading prompt. Uses four variables:
        `question`, `criterion`, `answer`, and `instructions` (fed from the
        `instructions` parameter). Variables from sample `metadata` are also
        available. Defaults to the `model_graded_qa` template.
      instructions: Grading instructions. Should prompt the grader to answer
        (e.g. with chain-of-thought reasoning) in a way that matches
        `grade_pattern` (the default looks for one of GRADE: C, GRADE: P, or
        GRADE: I).
      grade_pattern: Regex to extract the grade from the grader response.
        Defaults to looking for e.g. GRADE: C. The regex should have a single
        capture group that extracts exactly the letter C, P, or I.
      include_history: Whether to include the full chat history in the presented
        question. Defaults to `False`, which presents only the original sample
        input. Optionally provide a function to customise how the chat history
        is presented.
      partial_credit: Whether to allow "partial" credit for answers (by default
        assigned a score of 0.5). Defaults to `False`. Only used with the
        default `instructions`.
      model: Model to use for grading. When provided, takes precedence over
        `model_role`. Unlike `model_graded_qa`, a list is not accepted here;
        the actor≠verifier guarantee is defined for a single verifier.
      model_role: Named model role to use for grading (default: "grader").
        Ignored if `model` is provided. If a model is bound to this role (e.g.
        via the `model_roles` argument to `eval()`), that model is used. If no
        role-bound model is available, the model being evaluated is used — which
        will trigger the `on_same_model` behaviour below.
      on_same_model: What to do when the resolved verifier is the same model as
        the actor (the model under evaluation). `"error"` (default) raises a
        `ValueError`, so a misconfigured governance eval fails loudly rather
        than producing a self-graded score; `"warn"` logs a warning and grades
        anyway; `"allow"` grades silently. In every case the resolved actor and
        verifier names, and whether they were distinct, are recorded in the
        score metadata.

    Returns:
      Scorer that grades with a verifier model distinct from the actor.

    Examples:
      ```python
      from inspect_ai import Task, eval
      from inspect_ai.dataset import Sample
      from inspect_ai.model import get_model
      from inspect_ai.scorer import cross_model_verifier

      task = Task(
          dataset=[Sample(input="What is the capital of France?", target="Paris")],
          scorer=cross_model_verifier(),
      )

      # actor answers with one model; a *different* model grades it
      eval(
          task,
          model="openai/gpt-4o",
          model_roles={"grader": get_model("anthropic/claude-sonnet-4-latest")},
      )
      ```
    """
    # resolve grading template, instructions, and grade_pattern (identical to
    # model_graded_qa so behaviour is inherited exactly)
    template = template if template else DEFAULT_MODEL_GRADED_QA_TEMPLATE
    grading_template = resource(template)
    instructions = (
        instructions if instructions else default_instructions(partial_credit)
    )

    async def score(state: TaskState, target: Target) -> Score:
        # resolve verifier model
        # Order of precedence: `model` > `model_role` > model under evaluation
        if model is not None:
            verifier = model if isinstance(model, Model) else get_model(model)
        elif model_role is not None:
            verifier = get_model(role=model_role)
        else:
            verifier = get_model()

        # identify actor (model under evaluation) and verifier by fully
        # qualified name, then enforce the actor≠verifier requirement
        actor_name = str(state.model)
        verifier_name = str(ModelName(verifier))
        distinct = actor_name != verifier_name

        if not distinct:
            reason = (
                f"cross_model_verifier: the grader model ('{verifier_name}') is "
                f"the same as the model under evaluation ('{actor_name}'). A "
                "model grading its own output defeats the purpose of "
                "cross-model verification. Bind a distinct grader (e.g. via the "
                "`model_roles` argument to `eval()` or the `model` argument to "
                "this scorer), or pass `on_same_model='warn'`/`'allow'` to "
                "proceed anyway."
            )
            if on_same_model == "error":
                raise ValueError(reason)
            elif on_same_model == "warn":
                logger.warning(reason)

        verification = dict(
            actor_model=actor_name,
            verifier_model=verifier_name,
            actor_verifier_distinct=distinct,
        )

        # metadata without grading template variables
        metadata = omit(
            state.metadata, ["question", "answer", "criterion", "instructions"]
        )

        # present the question
        if include_history is True:
            question = chat_history(state)
        elif callable(include_history):
            question = include_history(state)
        else:
            question = state.input_text

        # format the scoring template
        scoring_prompt = model_scoring_prompt(
            template=grading_template,
            question=question,
            output=state.output,
            criterion=target.text,
            instructions=instructions,
            metadata=metadata,
        )

        # query the verifier for the grade
        result = await verifier.generate([scoring_prompt])

        # extract the grade
        default_grade_pattern = grade_pattern is None
        match = re.search(grade_pattern or DEFAULT_GRADE_PATTERN, result.completion)
        if match:
            value = match.group(1)
            if default_grade_pattern:
                value = value.upper()
            return Score(
                value=value,
                answer=state.output.completion,
                explanation=result.completion,
                metadata=dict(
                    **verification,
                    grading=[
                        scoring_prompt,
                        result.message,
                    ],
                ),
            )
        else:
            return Score.unscored(
                answer=state.output.completion,
                explanation="Grade not found in model output: "
                + f"{result.completion}",
                metadata=dict(
                    **verification,
                    unscored_reason="grade_parse_failure",
                    grading=[
                        scoring_prompt,
                        result.message,
                    ],
                ),
            )

    return score
