import random
import re

from inspect_ai.model import Model, get_model
from inspect_ai.util import resource

from ._judge import Judge
from ._verdict import JudgeVerdict, Winner

DEFAULT_JUDGE_TEMPLATE = """\
You are an impartial judge comparing two responses to the same prompt.

[PROMPT]
{prompt}

[RESPONSE A]
{response_a}

[RESPONSE B]
{response_b}

{instructions}
"""

DEFAULT_JUDGE_INSTRUCTIONS = """\
Decide which response better addresses the prompt. Briefly justify your choice,
then end your reply on a new line with exactly one of:

  VERDICT: A
  VERDICT: B
  VERDICT: TIE

Use TIE only when neither response is meaningfully better than the other.
"""

DEFAULT_VERDICT_PATTERN = r"(?is).*VERDICT\s*:\s*(A|B|TIE)"


def llm_judge(
    template: str | None = None,
    instructions: str | None = None,
    verdict_pattern: str | None = None,
    randomize_order: bool = True,
    both_orders: bool = False,
    model: str | Model | None = None,
    model_role: str | None = "judge",
) -> Judge:
    """Built-in `Judge` backed by an LLM.

    Follows the conventions of `model_graded_qa`: customisable template /
    instructions / verdict regex, and `model_role` binding via the
    `model_roles` argument to `eval()`.

    Position-bias controls (mutually exclusive — `both_orders` wins):

    - `randomize_order` (default): swap the two responses with probability
      0.5 per call. The verdict is un-swapped before returning, so position
      bias averages out across many samples without doubling cost.
    - `both_orders`: invoke the judge twice with swapped orderings and
      aggregate. Agreement on a winner returns that winner; disagreement
      returns a tie. Doubles judge calls per pair.
    """
    template_str = template if template else DEFAULT_JUDGE_TEMPLATE
    judge_template = resource(template_str)
    judge_instructions = instructions if instructions else DEFAULT_JUDGE_INSTRUCTIONS
    pattern = verdict_pattern or DEFAULT_VERDICT_PATTERN

    async def _ask(
        judge_model: Model, prompt: str, resp_a: str, resp_b: str
    ) -> JudgeVerdict:
        rendered = judge_template.format(
            prompt=prompt,
            response_a=resp_a,
            response_b=resp_b,
            instructions=judge_instructions,
        )
        result = await judge_model.generate(rendered)
        match = re.search(pattern, result.completion)
        if match is None:
            return JudgeVerdict(
                winner="tie",
                explanation=result.completion,
                metadata={"reason": "verdict_pattern_not_matched"},
            )
        letter = match.group(1).upper()
        winner: Winner = "a" if letter == "A" else "b" if letter == "B" else "tie"
        return JudgeVerdict(winner=winner, explanation=result.completion)

    def _flip(verdict: JudgeVerdict) -> JudgeVerdict:
        flipped: Winner = (
            "a" if verdict.winner == "b" else "b" if verdict.winner == "a" else "tie"
        )
        return JudgeVerdict(
            winner=flipped,
            explanation=verdict.explanation,
            metadata=verdict.metadata,
        )

    async def judge(prompt: str, response_a: str, response_b: str) -> JudgeVerdict:
        # Resolve the judge model lazily, mirroring model_graded_qa.
        if model is not None:
            judge_model = model if isinstance(model, Model) else get_model(model)
        elif model_role is not None:
            judge_model = get_model(role=model_role)
        else:
            judge_model = get_model()

        if both_orders:
            # Show each ordering to the judge once. The second verdict comes
            # back in the swapped coordinate system, so flip it before
            # comparing to the first.
            v1 = await _ask(judge_model, prompt, response_a, response_b)
            v2_swapped = await _ask(judge_model, prompt, response_b, response_a)
            v2 = _flip(v2_swapped)
            if v1.winner == v2.winner:
                return JudgeVerdict(winner=v1.winner)
            return JudgeVerdict(
                winner="tie",
                metadata={"reason": "both_orders_disagree"},
            )

        if randomize_order and random.random() < 0.5:
            # Show the judge the swapped order to neutralise position bias,
            # then flip the verdict back so callers always see "a"/"b" in
            # the original (response_a, response_b) coordinates.
            verdict = await _ask(judge_model, prompt, response_b, response_a)
            return _flip(verdict)

        return await _ask(judge_model, prompt, response_a, response_b)

    return judge
