# RACE-H

[RACE](https://arxiv.org/abs/1704.04683) is a benchmark for testing reading comprehension and reasoning abilities of neural models. It is constructed from Chinese middle and high school examinations. 

Here, we implement the evaluation for the high school subset (RACE-H) of the RACE dataset. It is formulated as a multiple choice question task. The goal is to choose one out of four options in response to a question based on the provided article. The questions are designed to not merely be text spans in the article, and hence answering them requires reasoning.

## Execution
Here is an example from the dataset (cropped for brevity):
```
Article: In a small village in England about 150 years ago, a mail coach was standing on the street. It didn’t come to that village often. People had to pay a lot to get a letter. The person who sent the letter didn’t have to pay the postage, while the receiver had to. ...

Question: The first postage stamp was made ____ .

Options: A. in England B. in America C. by Alice D. in 1910
```
The model is tasked to choose one of the four options. 

## Evaluation
The model is prompted with the article, the question and four options as input. It is required to choose one option by generating the corresponding answer choice A, B, C or D. The prompt template is based on the multiple choice template in OpenAI's [simple-evals](https://github.com/openai/simple-evals/blob/main/mmlu_eval.py).
