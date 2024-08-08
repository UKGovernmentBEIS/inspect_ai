# HumanEval

[HumanEval](https://arxiv.org/pdf/2107.03374) is a benchmark to evaluate a model's performance on synthesizing programs from docstrings. This implementation is based on the [official implementation](https://github.com/openai/human-eval).

## Execution
Here is an example prompt from the dataset:
```python
from typing import List

def has_close_elements(numbers: List[float], threshold: float) -> bool:
    """Check if in given list of numbers, are any two numbers closer to each other than given threshold.
    >>> has_close_elements([1.0, 2.0, 3.0], 0.5)
    False
    >>> has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
    True
    """
```
The model is then tasked to fill in the missing code pieces in order to make this a working function.

## Evaluation
Once a generation is completed, the entire function, accompanied with unit tests, is run in a subprocess and is considered a success if all unit tests pass.

The benchmark uses the $\text{pass}@k$ metric to measure functional correctness. In brief terms, this is the per problem probability of at least 1 correct sample generation given $k$ generations. It is defined using the following expectation:

$$ \text{pass@}k := \underset{\text{Problems}}{\mathbb{E}}\left[1-\frac{{n-c}\choose{k}}{{n}\choose{k}}\right]$$

where we sample $n \geq k$ generations to reduce variance. Note that the default in this benchmark implementation is $n = 5$, and we evaluate $\text{pass}@k$ for $k \in \\{1, 2, 5\\}$.
