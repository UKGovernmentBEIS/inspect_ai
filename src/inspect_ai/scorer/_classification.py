import re
import string
from typing import Callable, List

from inspect_ai.solver._task_state import TaskState

from ._metric import CORRECT, INCORRECT, Score
from ._metrics import mean, stderr
from ._scorer import Scorer, scorer
from ._target import Target


@scorer(metrics=[mean(), stderr()])
def f1(
    answer_fn: Callable[[str], str] | None = None,
) -> Scorer:
    """Scorer which produces an F1 score

    Computes the `F1` score for the answer (which balances recall precision by taking the harmonic mean between recall and precision).
    """

    async def score(state: TaskState, target: Target) -> Score:
        # Get generated answer and extract relevant answer text
        answer = (
            answer_fn(state.output.completion) if answer_fn else state.output.completion
        )
        targets = target.target

        f1_score = max_f1_score(answer, targets)
        return Score(
            value=f1_score,
            answer=answer,
        )

    return score


@scorer(metrics=[mean(), stderr()])
def exact() -> Scorer:
    """Scorer which produces an exact match score

    Normalizes the text of the answer and target(s) and performs an exact matching comparison of the text. This scorer will return `CORRECT` when the answer is an exact match to one or more targets.
    """

    async def score(state: TaskState, target: Target) -> Score:
        # Get generated answer and extract relevant answer text
        answer = state.output.completion
        targets = target.target

        exact_score = max_exact_score(answer, targets)
        return Score(value=CORRECT if exact_score == 1.0 else INCORRECT, answer=answer)

    return score


def max_f1_score(answer: str, targets: List[str]) -> float:
    # Find the maximum F1 score for this answer
    max_f1 = 0.0
    for target in targets:
        if target[0].strip():
            f1_score = compute_f1(answer, target)
            max_f1 = max(max_f1, f1_score)
    return round(max_f1, 2)


def max_exact_score(answer: str, targets: List[str]) -> float:
    # Find the maximum exact score for this answer
    max_exact = 0.0
    answer_words = _to_words(answer)
    for target in targets:
        if target[0].strip():
            target_words = _to_words(target)
            exact_score = 1.0 if target_words == answer_words else 0.0
            max_exact = max(max_exact, exact_score)
    return max_exact


def compute_f1(answer: str, target: str) -> float:
    """Takes a predicted answer and a gold answer (that are both either a string or a list of strings), and returns exact match and the SQuAD F1 metric for the prediction."""
    answer_words = _to_words(answer)
    target_words = _to_words(target)

    return _f1(answer_words=answer_words, target_words=target_words)


def _to_words(
    answer: str,
) -> set[str]:
    normalized = _normalize(answer)
    token_bag = set(normalized.split())
    return token_bag


def _f1(answer_words: set[str], target_words: set[str]) -> float:
    intersection = len(answer_words.intersection(target_words))
    if not answer_words:
        precision = 1.0
    else:
        precision = intersection / float(len(answer_words))
    if not target_words:
        recall = 1.0
    else:
        recall = intersection / float(len(target_words))
    f1 = (
        (2 * precision * recall) / (precision + recall)
        if not (precision == 0.0 and recall == 0.0)
        else 0.0
    )
    return f1


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _remove_articles(text: str) -> str:
    _ARTICLES = re.compile(r"\b(a|an|the)\b", re.UNICODE)
    return _ARTICLES.sub(" ", text)


def _remove_punc(text: str) -> str:
    exclude = set(string.punctuation)
    is_number = _is_number(text)
    if not is_number:
        return "".join(ch for ch in text if ch not in exclude)
    else:
        return text


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _normalize_number(text: str) -> str:
    is_number = _is_number(text)
    if is_number:
        return str(float(text))
    else:
        return text


def _tokenize(text: str) -> List[str]:
    return re.split(" |-", text)


def _normalize(answer: str) -> str:
    """Normalize text to remove extraneous characters and words."""
    tokens = []
    tokenized_answer = _tokenize(answer)
    for token in tokenized_answer:
        token = _remove_punc(token.casefold())
        token = _normalize_number(token)
        token = _remove_articles(token)
        token = _normalize_whitespace(token)
        tokens.append(token)
    tokens = [token for token in tokens if token.strip()]
    normalized = " ".join(tokens).strip()
    return normalized
