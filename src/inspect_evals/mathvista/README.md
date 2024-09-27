# MathVista: Evaluating Mathematical Reasoning in Visual Contexts

[MathVista](https://arxiv.org/pdf/2310.02255) to evaluate model performance in answering mathematics problems that have a visual component. Each problem has an associated image which is required to solve the problem. The dataset is made up of 6,141 questions from 28 existing multimodal datasets as well as 3 new datasets created for MathVista, where each dataset contains different styles of questions. There are both multiple-choice questions and free-form questions, where the free-form questions ask for a response in the form of an integer, floating-point number, or list.

## Execution
Here is an example from the dataset:

**Question:** The derivative of f(x) at x=2 is ____ that at x=5

**Choices:** "larger than", "equal to", "smaller than"

**Image:**

![Image for example question](example.png)

**Correct answer:** "equal to"


## Evaluation

First, install the `inspect_evals` Python package with:

```bash
pip install inspect_ai[inspect_evals]@git+https://github.com/UKGovernmentBEIS/inspect_ai
```

Then, evaluate against one more models with:

```bash
inspect eval inspect_evals/mathvista --model openai/gpt-4o
```

