import re
import string

from typing import List, Tuple, Union

import numpy as np
from scipy.optimize import linear_sum_assignment  # type: ignore

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import Score, Target, bootstrap_std, mean, scorer
from inspect_ai.solver import system_message, generate, TaskState


SYSTEM_MESSAGE = """
Using only the context provided in the question itself, you are tasked with answering a question in as few words as possible.
"""

@task
def squad():
   
    dataset = hf_dataset(
        path="rajpurkar/squad",
        split="validation",
        sample_fields=record_to_sample,
        trust=True,
        shuffle=True
    )

    return Task(
        dataset=dataset,
        plan=build_plan(),
        scorer=squad_f1_scorer()
    )

def record_to_sample(record):
  return Sample(
      input=format_input(record),
      target=format_target(record),
      id=record["id"],
  )

def format_input(record) -> str:
  passage_str = f"""Context: {record["context"]}"""
  question_str = f"""Question: {record["question"]}"""
  input_str = "\n".join([passage_str, question_str])

  return input_str


def format_target(record) -> List[str]:
  answers = record["answers"]
  choices = answers["text"]

  target = choices
  return target

def build_plan() -> List:
    
  sys_msg = system_message(SYSTEM_MESSAGE)

  plan = [
    sys_msg,
    generate(),
  ]

  return plan


@scorer(metrics=[mean(), bootstrap_std()])
def squad_f1_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        # Get generated answer and extract relevant answer text
        prediction = state.output.completion
        ref_answers = target.target

        # Compute exact match (EM) and F1 score
        em_score, f1_score = await process_results(prediction, ref_answers)

        # F1 score and EM reported as main aggregated metrics, EM score currently added to metadata
        return Score(
            value=f1_score,
            answer=prediction,
            metadata={
                "metrics": {
                    "f1_score": f1_score,
                    "em_score": em_score,
                },
                "gold_answers": ref_answers,
            },
        )

    return score

# From here until '_normalize()' is copied from
# https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/tasks/drop/utils.py,
# and all functions are converted to async functions.
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
    """Takes a predicted answer and a gold answer (that are both either a string or a list of strings), and returns exact match and the SQuAD F1 metric for the prediction.

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
    """Normalization used in official SQuAD evaluation script."""
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