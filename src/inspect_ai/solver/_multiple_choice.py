import logging
import re
from random import Random

from inspect_ai._util.pattern import (
    ANSWER_PATTERN_LETTER,
)
from inspect_ai.util import resource

from ._solver import Generate, Solver, TaskState, solver

logger = logging.getLogger(__name__)

# this template is based on the multiple choice template in openai simple evals:
# https://github.com/openai/simple-evals/blob/main/mmlu_eval.py


MULTIPLE_CHOICE_TEMPLATE = r"""
Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}.

{question}

{choices}
""".strip()


MULTIPLE_CHOICE_TEMPLATE_COT = r"""
Answer the following multiple choice question. The last line of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of {letters}. Think step by step before answering.

{question}

{choices}
"""


# max tokens for differnet variations
MULTIPLE_CHOICE_MAX_TOKENS = 32
MULTIPLE_CHOICE_MAX_TOKENS_COT = 1024


@solver
def multiple_choice(
    *,
    cot: bool = False,
    template: str | None = None,
    max_tokens: int | None = None,
    shuffle: bool | Random = False,
    answer_pattern: str | None = None,
) -> Solver:
    """Multiple choice question solver.

    Formats a multiple choice question prompt, then calls `generate()`
    (so you don't need to call `generate()` separately after this solver runs).

    The `template` and `max_tokens` parameters have defaults that vary based
    on whether `cot` is `True`. When NOT using chain of thought,
    `max_tokens` is set to 32 (otherwise it is set to 1024). If you provide your
    own template, you will also need to determine an appropriate value for
    `max_tokens` (as well as `answer_pattern` if `shuffle` is `True`).

    If shuffling is requested, then the choices will be presented in random order,
    and the model output mapped back to the correct choices from the dataset.
    When shuffling is enabled, you must also provide an `answer_pattern` that
    allows this substitution to find the answer in the model output.

    Args:
        cot (bool): `True` to use chain of thought prompting (defaults to `False`).
          Note that using chain of thought will be slower and use more tokens,
          so you should assess carefully whether your eval benefits from it or not.
        template (str | None): Alternate prompt template for questions/answers.
          Templates have 3 variables: `letters`, `question`, and `choices
          (where letters is e.g. 'ABCD').
        max_tokens (int | None): Maximum number of tokens to output.
        shuffle (Random | None): Present answers in a shuffled order (defaults to
          `False`, pass `True` or an instance of `Random` to shuffle)
        answer_pattern (str | None): Regex used to find the answer letter. This is
          only used when `shuffle` is enabled. The regex should have 3 capture groups
         (before the answer, the answer, and after the answer). If the answer is
         expected at the beginning or end then you can use explicit capture groups
         for beginning or end of string, for example (^.*) or (.*$).
    """
    # resolve parameters
    template = (
        template
        if template
        else MULTIPLE_CHOICE_TEMPLATE_COT if cot else MULTIPLE_CHOICE_TEMPLATE
    )
    max_tokens = (
        max_tokens
        if max_tokens
        else MULTIPLE_CHOICE_MAX_TOKENS_COT if cot else MULTIPLE_CHOICE_MAX_TOKENS
    )
    answer_pattern = answer_pattern if answer_pattern else ANSWER_PATTERN_LETTER

    # resolve template contents
    template = resource(template)

    # resolve shuffle
    if shuffle is True:
        shuffle = Random()

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # confirm we have choices
        if not state.choices:
            raise ValueError("The multiple choice solver requires samples with choices")

        # resolve letters
        letters = "".join(chr(65 + i) for i in range(len(state.choices)))

        # build choices str, key, and prompt

        # unshuffled version (this is what we'll write into history)
        choices_str, _ = make_choices(choices=state.choices)
        user_prompt_text = template.format(
            letters=letters,
            question=state.user_prompt.text,
            choices=choices_str,
        )

        # shuffled version (this is what we'll present to the model)
        choices_str_shuffled, choices_key = make_choices(
            choices=state.choices, shuffle=shuffle if shuffle else None
        )
        state.user_prompt.text = template.format(
            letters=letters,
            question=state.user_prompt.text,
            choices=choices_str_shuffled,
        )

        # generate
        state = await generate(state, max_tokens=max_tokens)

        # unshuffle if necessary
        if shuffle:
            state.output.completion = re.sub(
                answer_pattern,
                lambda m: f"{m.group(1)}{choices_key.get(m.group(2), '')}{m.group(3)}",
                state.output.completion,
            )

        # update last message and restore user prompt
        state.messages[-1].content = state.output.completion
        state.user_prompt.text = user_prompt_text

        # return state
        return state

    return solve


def make_choices(
    choices: list[str],
    shuffle: Random | None = None,
) -> tuple[str, dict[str, str]]:
    # helper to go from index to char
    def answer_char(index: int) -> str:
        return chr(ord("A") + index)

    # shuffle if requested
    indexes = list(range(len(choices)))
    if shuffle:
        shuffle.shuffle(indexes)

    # build choices
    choices_str = "\n".join(
        [f"{answer_char(i)}) {choices[j]}" for i, j in enumerate(indexes)]
    )

    # build key for going from randomized letter to actual label
    choices_key = dict(
        zip(
            [answer_char(i) for i in range(0, len(indexes))],
            [answer_char(i) for i in indexes],
        )
    )

    # return
    return choices_str, choices_key
