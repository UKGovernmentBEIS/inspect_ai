from statistics import mean
from typing import List, Callable
from collections import Counter
import string
import re
import nltk
from nltk.corpus import stopwords

from inspect_ai.scorer import scorer, mean, stderr, Score, Target, CORRECT, INCORRECT
from inspect_ai.solver import (
    TaskState,
)

nltk.download('stopwords', quiet=True)
STOP_WORDS = set(stopwords.words('english'))

@scorer(metrics=[mean(), stderr()])
def f1_scorer():
    async def score(state: TaskState, targets: Target) -> Score:
        prediction = state.output.completion

        if prediction.upper() == "CANNOTANSWER":
            return Score(
                value=CORRECT if any(t.upper() == "CANNOTANSWER" for t in targets) else INCORRECT,
                answer="CANNOTANSWER"
            )

        f1_scores = []
        for i in range(len(targets)):
            current_reference = targets[i]
            other_references = targets[:i] + targets[i+1:]
            f1_with_current = f1_score(prediction, current_reference)
            f1_with_others = max((f1_score(prediction, ref) for ref in other_references), default=0)
            max_f1 = max(f1_with_current, f1_with_others)
            f1_scores.append(max_f1)

        final_f1 = sum(f1_scores) / len(f1_scores)

        return Score(
            value=final_f1,
            answer=prediction,
            explanation=f"F1 score: {final_f1}"
        )
    return score

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
        return re.sub(r'\b(a|an|the)\b', ' ', text)
    def white_space_fix(text):
        return ' '.join(text.split())
    def remove_punc(text):
        exclude = set(string.punctuation)
        return ''.join(ch for ch in text if ch not in exclude)
    def lower(text):
        return text.lower()
    def remove_stopwords(text):
        return [word for word in text.split() if word not in STOP_WORDS]
    
    result = remove_stopwords(white_space_fix(remove_articles(remove_punc(lower(s)))))
    return result
