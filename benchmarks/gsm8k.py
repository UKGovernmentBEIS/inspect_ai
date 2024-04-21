"""
Training Verifiers to Solve Math Word Problems

Karl Cobbe, Vineet Kosaraju, Mohammad Bavarian, Mark Chen, Heewoo Jun, Lukasz Kaiser, Matthias Plappert, Jerry Tworek, Jacob Hilton, Reiichiro Nakano, Christopher Hesse, John Schulman
https://arxiv.org/abs/2110.14168

# run with default fewshots (10)
inspect eval gsm8k.py

# run with less  or no fewshots
inspect eval gsm8k.py -T fewshot=5
inspect eval gsm8k.py -T fewshot=false
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, hf_dataset
from inspect_ai.scorer import match
from inspect_ai.solver import generate, system_message


def record_to_sample(record):
    DELIM = "####"
    input = record["question"]
    answer = record["answer"].split(DELIM)
    target = answer.pop().strip()
    reasoning = DELIM.join(answer)
    return Sample(
        input=input,
        target=target,
        metadata={"reasoning": reasoning.strip()}
    )

def sample_to_fewshot(sample):
    ANSWER_TRIGGER = "The answer is"
    return (
        f"Question: {sample.input}\nAnswer: "
        + f"{sample.metadata['reasoning']} "
        + f"{ANSWER_TRIGGER} {sample.target}"
    )

@task
def gsm8k(fewshot=10, fewshot_seed=42):

    # build plan dynamically (may or may not be doing fewshot)
    plan = [generate()]
    if fewshot:
        fewshots = hf_dataset(
            path="gsm8k",
            data_dir="main",
            split="train",
            sample_fields=record_to_sample,
            shuffle=True,
            seed=fewshot_seed,
            limit=fewshot,
        )
        plan.insert(0, system_message("\n\n".join(
            [sample_to_fewshot(sample) for sample in fewshots]
        )))

    # define task
    return Task(
        dataset=hf_dataset(
            path="gsm8k",
            data_dir="main",
            split="test",
            sample_fields=record_to_sample,
        ),
        plan=plan,
        scorer=match(numeric=True)
    )

