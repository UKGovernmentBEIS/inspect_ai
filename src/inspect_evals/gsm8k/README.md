 # GSM8K

 [GSM8K](https://arxiv.org/pdf/2110.14168) is a dataset consisting of diverse grade school math word problems.

 ## Execution
 Here is an example prompt from the dataset (after it has been further processed by Inspect):
 ```
Solve the following math problem step by step. The last line of your response should be of the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem.

Janet’s ducks lay 16 eggs per day. She eats three for breakfast every morning and bakes muffins for her friends every day with four. She sells the remainder at the farmers' market daily for $2 per fresh duck egg. How much in dollars does she make every day at the farmers' market?

Remember to put your answer on its own line at the end in the form "ANSWER: $ANSWER" (without quotes) where $ANSWER is the answer to the problem, and you do not need to use a \\boxed command.

Reasoning:
 ```
 The model is then expected to generate reasoning steps and provide a final answer.

 ## Evaluation
An accuracy is calculated over the datapoints. The correctness is based on an exact-match criterion and whether the model's final answer is correct.