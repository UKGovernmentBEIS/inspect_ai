# WinoGrande

[WinoGrande](https://arxiv.org/pdf/1907.10641) is a collection of 44k problems inspired by the [Winograd Schema Challenge](https://cdn.aaai.org/ocs/4492/4492-21843-1-PB.pdf). Formulated as a fill-in-a-blank task with binary options, the goal is to choose the right option for a given sentence which requires commonsense reasoning.

## Execution
Here is an example from the dataset:
```python
Sentence: He never comes to my home, but I always go to his house because the [BLANK] is smaller.
Options: home, house
```
The model is tasked to fill the `[BLANK]` with either of the two options. 

## Evaluation
The model is prompted with the sentence and both options as input and required to choose one option by generating the corresponding answer choice A or B. The prompt tempate is based on the multiple choice template in OpenAI's [simple evals](https://github.com/openai/simple-evals/blob/main/mmlu_eval.py).
