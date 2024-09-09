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

Evaluation metrics follow similar benchmarks such as HumanEval. The benchmark uses the $\text{pass}@k$ metric to measure functional correctness. In brief terms, this is the per-problem probability of at least 1 correct sample generation given $k$ generations. It is defined using the following expectation:

$$ \text{pass@}k := \underset{\text{Problems}}{\mathbb{E}}\left[1-\frac{{n-c}\choose{k}}{{n}\choose{k}}\right]$$

where we sample $n \geq k$ generations to reduce variance. Note that the default in this benchmark implementation is $n = 5$, and we evaluate $\text{pass}@k$ for $k \in \\{1, 2, 5\\}$.