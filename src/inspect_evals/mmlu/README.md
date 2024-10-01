# MMLU

[MMLU](https://arxiv.org/pdf/2009.03300) is a benchmark to measure the model's multitask accuracy. This dataset covers 57 tasks such as elementary mathematics, US history, computer science, law, and more.

## Execution
Here is an example prompt from the dataset (after it has been further processed by Inspect):
```
Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of A,B,C,D.

The constellation ... is a bright W-shaped constellation in the northern sky.

A) Centaurus
B) Cygnus
C) Cassiopeia
D) Cepheus
```
The model is then tasked to pick the correct choice.

## Evaluation
A simple accuracy is calculated over the datapoints.
