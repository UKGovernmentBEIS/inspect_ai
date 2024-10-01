# AI2 Reasoning Challenge (ARC)

[ARC](https://arxiv.org/pdf/1803.05457) is a benchmark using natural science questions to evaluate a model's knowledge and reasoning capabilities. The dataset ships with `Easy` and `Challenge` sets. 

## Execution
Here is an example prompt from the dataset (after it has been further processed by Inspect):
```
Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of A,B,C,D.

An astronomer observes that a planet rotates faster after a meteorite impact. Which is the most likely effect of this increase in rotation?

A) Planetary density will decrease.
B) Planetary years will become longer.
C) Planetary days will become shorter.
D) Planetary gravity will become stronger.
```
The model is then tasked to pick the correct choice.

## Evaluation
A simple accuracy is calculated over the datapoints.
