# BoolQ

[BoolQ](https://arxiv.org/pdf/1905.10044) is a benchmark containing natural questions that have simple yes/no answers.

## Execution
Here is an example prompt from the dataset (after it has been further processed by Inspect):
```
Answer the following question with either Yes or No. Include nothing else in your response.

Question: can an odd number be divided by an even number
```
The model is then tasked to give a `Yes` or `No` answer.

## Evaluation
A simple accuracy is calculated over the datapoints.
