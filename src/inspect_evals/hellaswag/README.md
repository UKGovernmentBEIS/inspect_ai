 # HellaSwag

 [HellaSwag](https://arxiv.org/pdf/1905.07830) is a dataset for commonsense inference. The model is prompted with a sentence and the model is tasked to pick the sentence choice that is the best suited continuation.

 ## Execution
 Here is an example prompt from the dataset (after it has been further processed by Inspect):
 ```
Choose the most plausible continuation for the story.

Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of A,B,C,D.

A man is sitting on a roof. he

A) is using wrap to wrap a pair of skis.
B) is ripping level tiles off.
C) is holding a rubik's cube.
D) starts pulling up roofing on a roof.
 ```
 The model is then expected to generate reasoning steps and provide a final answer.

 ## Evaluation
An accuracy is calculated over the datapoints.