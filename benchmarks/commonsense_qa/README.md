# CommonsenseQA: A Question Answering Challenge Targeting Commonsense Knowledge

[CommonsenseQA](https://arxiv.org/pdf/1811.00937) is a dataset designed to evaluate commonsense reasoning capabilities in natural language processing models. It consists of 12,247 multiple-choice questions that require background knowledge and commonsense to answer correctly. The dataset was constructed using CONCEPTNET, a graph-based knowledge base, where crowd-workers authored questions with complex semantics to challenge existing AI models.

## Execution
Here is an example from the dataset:
```
Question: Where can I stand on a river to see water falling without getting wet?
Options: 
A) Waterfall 
B) Bridge 
C) Valley 
D) Stream 
E) Bottom
```
The model is required to choose the correct answer from the given options. In this case, the correct answer is B) Bridge.

## Evaluation
The model is prompted with the question and 5 options as input and required to choose one option by generating the corresponding answer choice A, B, C, D or E. The prompt tempate is based on the multiple choice template in OpenAI's [simple evals](https://github.com/openai/simple-evals/blob/main/mmlu_eval.py).
