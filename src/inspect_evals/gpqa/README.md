# GPQA

[GPQA](https://arxiv.org/pdf/2311.12022) is an evaluation dataset consisting of graduate-level multiple-choice questions in subdomains of physics, chemistry, and biology.

This implementation is based on [simple-eval](https://github.com/openai/simple-evals/blob/main/gpqa_eval.py)'s implementation. This script evaluates on the GPQA-Diamond subset.

## Dataset

Here is an example prompt from the dataset (after it has been further processed by Inspect):
```

Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of A,B,C,D.

Two quantum states with energies E1 and E2 have a lifetime of 10^-9 sec and 10^-8 sec, respectively. We want to clearly distinguish these two energy levels. Which one of the following options could be their energy difference so that they can be clearly resolved?


A) 10^-4 eV
B) 10^-11 eV
C) 10^-8 eV
D) 10^-9 eV
```

The model is then tasked to pick the correct answer choice.

## Evaluation

First, install the `inspect_evals` Python package with:

```bash
pip install inspect_ai[inspect_evals]@git+https://github.com/UKGovernmentBEIS/inspect_ai
```

Then, evaluate against one more models with:

```bash
inspect eval inspect_evals/gpqa_diamond --model openai/gpt-4o
```


