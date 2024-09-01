import re
import numpy as np
import string
from inspect_ai.scorer import Score, Target, bootstrap_std, mean, scorer
from inspect_ai.solver import (
    TaskState,
)

from pprint import pp
from typing import List, Tuple, Union
from scipy.optimize import linear_sum_assignment  # type: ignore


"""
FROM PAPER:

4.1 Evaluation Metrics
Our core evaluation metric, word-level F1, is im- plemented similarly to SQuAD (Rajpurkar et al., 
2016): precision and recall are computed by con- sidering the portion of words in the prediction 
and references that overlap after removing stop- words.12 For no answer questions, we give the 
system an F1 of one if it correctly predicts no answerandzerootherwise.13 Like 
SQuAD,we compute the maximum F1 among all references; however, since many questions have 
multiple valid answers, this metric varies significantly with

the number of reference annotations. To make or- acle human and system performance comparable, 
given n references, we report the average of the maximum F1 computed from each n − 1 
subset with respect to the heldout reference.
Additionally, since averaged F1 can be mislead- ing for 
questions with multiple valid answers, we introduce the human equivalence score (HEQ)
,a performance measure for judging whether a sys- tem’s output is as good as that of 
an average hu- man.14 HEQmeasuresthepercentageofexamples for which system F1 exceeds 
or matches human F1. We compute two variants: (1) the percentage of questions for 
which this is true (HEQ-Q), and (2) the percentage of dialogs for which this is 
true for every question in the dialog (HEQ-D). A sys- tem that achieves a value of
100 on HEQ-D can by definition maintain average human quality output over full dialogs.
For dialog acts, we report accuracy with respect to the majority annotation, breaking ties randomly.

"""

# !!!!
# WIP
# Taken from drop benchmark, need to refactor or add directly to inspect library as new f1 scorer
@scorer(metrics=[mean(), bootstrap_std()])
def f1_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        # Get generated answer and extract relevant answer text
        answer = state.output.completion
        match = re.search(r"(?i)answer\s*:\s*([^\n]+)", answer)
        answer = match.group(1) if match else answer

        # Get target answers (convert str elm to tuple by splitting on "|")
        ref_answers = [tuple(elm.split("|")) for elm in target.target]
        
        em_score, f1_score = await process_results(answer, ref_answers)

        # F1 score reported as main aggregated metric, EM score added to metadata
        return Score(
            value=f1_score,
            answer=answer,
            metadata={
                "metrics": {
                    "f1_score": f1_score,
                    "em_score": em_score,
                },
                "gold_answers": ref_answers,
            },
        )


    return score

async def process_results(
    preds: Union[str, List[str]], golds: List
) -> Tuple[float, float]:
    max_em = 0.0
    max_f1 = 0.0
    for gold_answer in golds:
        exact_match, f1_score = await get_metrics(preds, gold_answer)
        if gold_answer[0].strip():
            max_em = max(max_em, exact_match)
            max_f1 = max(max_f1, f1_score)
    return (max_em, max_f1)


async def get_metrics(
    predicted: Union[str, List[str]], gold: Union[str, List[str], Tuple[str]]
) -> Tuple[float, float]:
    """Takes a predicted answer and a gold answer (that are both either a string or a list of strings), and returns exact match and the DROP F1 metric for the prediction.

    If you are writing a script for evaluating objects in memory (say, the output of predictions during
    validation, or while training), this is the function you want to call, after using
    :func:`answer_json_to_strings` when reading the gold answer from the released data file.
    """
    predicted_bags = await _answer_to_bags(predicted)
    gold_bags = await _answer_to_bags(gold)

    if set(predicted_bags[0]) == set(gold_bags[0]) and len(predicted_bags[0]) == len(
        gold_bags[0]
    ):
        exact_match = 1.0
    else:
        exact_match = 0.0

    f1_per_bag = await _align_bags(predicted_bags[1], gold_bags[1])
    f1 = np.mean(f1_per_bag).item()
    f1 = round(f1, 2)
    return exact_match, f1


async def _answer_to_bags(
    answer: Union[str, List[str], Tuple[str]],
) -> Tuple[list, list]:
    if isinstance(answer, list | tuple):
        raw_spans = answer
    else:
        raw_spans = [answer]
    normalized_spans = []
    token_bags = []
    for raw_span in raw_spans:
        normalized_span = await _normalize(raw_span)
        normalized_spans.append(normalized_span)
        token_bags.append(set(normalized_span.split()))
    return normalized_spans, token_bags


async def _align_bags(predicted: List[set], gold: List[set]) -> np.ndarray:
    """Takes gold and predicted answer sets and first finds the optimal 1-1 alignment between them and gets maximum metric values over all the answers."""
    scores = np.zeros([len(gold), len(predicted)])
    for gold_index, gold_item in enumerate(gold):
        for pred_index, pred_item in enumerate(predicted):
            match_numbers = await _match_numbers_if_present(gold_item, pred_item)
            if match_numbers:
                scores[gold_index, pred_index] = await _compute_f1(pred_item, gold_item)
    row_ind, col_ind = linear_sum_assignment(-scores)

    max_scores = np.zeros([max(len(gold), len(predicted))])
    for row, column in zip(row_ind, col_ind):
        max_scores[row] = max(max_scores[row], scores[row, column])
    return max_scores


async def _compute_f1(predicted_bag: set, gold_bag: set) -> float:
    intersection = len(gold_bag.intersection(predicted_bag))
    if not predicted_bag:
        precision = 1.0
    else:
        precision = intersection / float(len(predicted_bag))
    if not gold_bag:
        recall = 1.0
    else:
        recall = intersection / float(len(gold_bag))
    f1 = (
        (2 * precision * recall) / (precision + recall)
        if not (precision == 0.0 and recall == 0.0)
        else 0.0
    )
    return f1


async def _match_numbers_if_present(gold_bag: set, predicted_bag: set) -> bool:
    gold_numbers = set()
    predicted_numbers = set()
    for word in gold_bag:
        is_number = await _is_number(word)
        if is_number:
            gold_numbers.add(word)
    for word in predicted_bag:
        is_number = await _is_number(word)
        if is_number:
            predicted_numbers.add(word)
    if (not gold_numbers) or gold_numbers.intersection(predicted_numbers):
        return True
    return False


async def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


async def _remove_articles(text: str) -> str:
    _ARTICLES = re.compile(r"\b(a|an|the)\b", re.UNICODE)
    return _ARTICLES.sub(" ", text)


async def _white_space_fix(text: str) -> str:
    return " ".join(text.split())


async def _remove_punc(text: str) -> str:
    exclude = set(string.punctuation)
    is_number = await _is_number(text)
    if not is_number:
        return "".join(ch for ch in text if ch not in exclude)
    else:
        return text


async def _fix_number(text: str) -> str:
    is_number = await _is_number(text)
    if is_number:
        return str(float(text))
    else:
        return text


async def _tokenize(text: str) -> List[str]:
    return re.split(" |-", text)


async def _normalize(answer: str) -> str:
    tokens = []
    tokenized_answer = await _tokenize(answer)
    for token in tokenized_answer:
        token = await _remove_punc(token.lower())
        token = await _fix_number(token)
        token = await _remove_articles(token)
        token = await _white_space_fix(token)
        tokens.append(token)
    tokens = [token for token in tokens if token.strip()]
    normalized = " ".join(tokens).strip()
    return normalized
