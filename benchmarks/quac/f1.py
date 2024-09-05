import logging
import re
import string
import nltk

from collections import Counter
from statistics import mean
from typing import List
from nltk.corpus import stopwords

from inspect_ai.scorer import scorer, mean, stderr, Score, Target, CORRECT, INCORRECT
from inspect_ai.solver import (
    TaskState,
)

logger = logging.getLogger(__name__)
nltk.download("stopwords", quiet=True)

STOP_WORDS = set(stopwords.words("english"))
MIN_HUMAN_F1 = 0.4  # 0.4 was used in the paper


@scorer(metrics=[mean(), stderr()])
def f1_scorer():
    async def score(state: TaskState, targets: Target) -> Score:
        prediction = state.output.completion

        if prediction.upper() == "CANNOTANSWER":
            return Score(
                value=CORRECT
                if any(t.upper() == "CANNOTANSWER" for t in targets)
                else INCORRECT,
                answer="CANNOTANSWER",
            )
        else:
            human_f1 = calculate_human_f1(targets)
            if human_f1 < MIN_HUMAN_F1:
                logger.info(
                    f"Human F1 score {human_f1} is below threshold {MIN_HUMAN_F1}. Skipping evaluation."
                )
                return Score(
                    value=1,  # TODO: How can we skip current state instead of returning 1? If not we need to do some workaround...
                    answer=prediction,
                    explanation=f"Human F1 score {human_f1} below threshold {MIN_HUMAN_F1}. Evaluation skipped.",
                    metadata={"human_f1": human_f1, "skipped": True},
                )

            if len(targets) == 1:
                f1 = f1_score(prediction, targets[0])
            else:
                f1_scores = []
                for i in range(len(targets)):
                    other_references = targets[:i] + targets[i + 1 :]
                    f1_with_others = max(
                        f1_score(prediction, ref) for ref in other_references
                    )
                    f1_scores.append(f1_with_others)
                f1 = sum(f1_scores) / len(f1_scores)

            return Score(value=f1, answer=prediction, explanation=f"F1 score: {f1}")

    return score


# TODO: Can we use _f1 from the core library instead?
def f1_score(prediction: str, ground_truth: str) -> float:
    prediction_tokens = normalize_answer(prediction)
    ground_truth_tokens = normalize_answer(ground_truth)

    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = (2 * precision * recall) / (precision + recall)
    return f1


def normalize_answer(s: str) -> List[str]:
    """Lowercase, remove punctuation, articles, stopwords, and extra whitespace."""

    def remove_articles(text):
        return re.sub(r"\b(a|an|the)\b", " ", text)

    def white_space_fix(text):
        return " ".join(text.split())

    def remove_punc(text):
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)

    def lower(text):
        return text.lower()

    # TODO: Can we use _normalize from the core library and also add the following after:
    def remove_stopwords(text):
        return [word for word in text.split() if word not in STOP_WORDS]

    result = remove_stopwords(white_space_fix(remove_articles(remove_punc(lower(s)))))
    return result


def calculate_human_f1(references: List[str]) -> float:
    if len(references) <= 1:
        return 1.0

    # comparing each reference against the subset of other references
    leave_one_out_f1s = []
    for i, reference in enumerate(references):
        other_references = references[:i] + references[i + 1 :]
        f1_scores = [f1_score(reference, other) for other in other_references]
        leave_one_out_f1s.append(max(f1_scores))

    return sum(leave_one_out_f1s) / len(leave_one_out_f1s)
