# MBPP: Mostly Basic Python Problems

[MBPP](https://arxiv.org/abs/2108.07732) is a dataset for evaluating the ability of models to synthesize short Python programs from natural language descriptions. It contains programming tasks that are designed to be solvable by entry-level programmers. We evaluate on the [sanitized test split](https://huggingface.co/datasets/google-research-datasets/mbpp/viewer/sanitized/test) of the dataset, which was hand-verified to remove samples that lacked detail or were ambiguous.

## Execution
Here is a sample from the dataset:
```python
task_id: 14
prompt: Write a python function to find the volume of a triangular prism.
test_list: [ "assert find_Volume(10,8,6) == 240", "assert find_Volume(3,2,2) == 6", "assert find_Volume(1,2,1) == 1" ]
```

The model is tasked to write Python code that will pass the assert statements in the `test_list`.

## Evaluation
The model is prompted to solve the problem, given its description and test cases to pass. Additionally, [few shot examples](https://github.com/google-research/google-research/tree/master/mbpp) can be included in the prompt, with prompts patterned after an [AgentCoder implementation](https://github.com/huangd1999/AgentCoder/blob/main/prompts/mbpp_prompt.txt) which topped the [leaderboard](https://paperswithcode.com/sota/code-generation-on-mbpp). 
