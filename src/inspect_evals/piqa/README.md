# PIQA

[PIQA](https://arxiv.org/pdf/1911.11641) is a benchmark to measure the model's physical commonsense reasoning.

## Execution
Here is an example prompt from the dataset (after it has been further processed by Inspect):
```
The entire content of your response should be of the following format: 'ANSWER:\n$LETTER' (without quotes) where LETTER is one of A,B.

Given either a question or a statement followed by two possible solutions
labelled A and B, choose the most appropriate solution. If a question is given,
the solutions answer the question. If a statement is given, the solutions
explain how to achieve the statement.

How do I ready a guinea pig cage for it's new occupants?

A) Provide the guinea pig with a cage full of a few inches of bedding made of ripped paper strips, you will also need to supply it with a water bottle and a food dish.
B) Provide the guinea pig with a cage full of a few inches of bedding made of ripped jeans material, you will also need to supply it with a water bottle and a food dish.
```
The model is then tasked to pick the correct choice.

## Evaluation
A simple accuracy is calculated over the datapoints.
