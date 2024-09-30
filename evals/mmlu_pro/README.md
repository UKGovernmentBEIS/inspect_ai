# MMLU-Pro: A More Robust and Challenging Multi-Task Language Understanding Benchmark

[MMLU-Pro](https://arxiv.org/pdf/2406.01574) is a more robust and challenging massive multi-task understanding dataset tailored to more rigorously benchmark large language models' capabilities. This dataset contains 12K complex questions across 14 disciplines (including 'Other'). There are three major differences compared to original MMLU:
1. MMLU-Pro increases the number of options from 4 to 10, making the evaluation more realistic and challenging.
2. In this dataset, the creators increase the problem difficulty and integrate more reasoning-focused problems.
3. The benchmark is made more robust by increasing the number of distractor options.

## Execution
Here is an example from the dataset:
```python
Question: Approximately how far away is the Andromeda Galaxy?
Options:
A) 5 million light years
B) 2.5 million light years
C) 2.1 million light years
D) 1.9 million light years
E) 3.2 million light years
F) 4 million light years
G) 1.7 million light years
H) 3.5 million light years
I) 1.2 million light years
J) 2.8 million light years
```
The model is tasked to answer the question and choose the appropriate option.

## Evaluation
The prompts are based on EleutherAI's [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness/tree/main/lm_eval/tasks/mmlu_pro) and  [MultipleChoiceTemplate.SINGLE_ANSWER](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/solver/_multiple_choice.py). The in-built `choice` scorer is used for evaluation.
