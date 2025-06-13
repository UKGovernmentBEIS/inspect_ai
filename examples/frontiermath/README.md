# FrontierMath Scorer Example

This example demonstrates how to use a custom scorer that verifies a submitted
Python function. The agent provides a `python` tool for exploration and a
`submit_answer` tool used to submit a function named `answer`.

The `project_euler.py` task includes a few [Project Euler](https://projecteuler.net/)
problems. Each problem contains Python code in `metadata['verification_code']`
that defines a `verify(answer)` function. The scorer runs this code inside the
Inspect sandbox to check whether the submitted answer is correct.

To run the evaluation:

```bash
inspect eval examples/frontiermath/project_euler.py --model <model-name>
```

Replace `<model-name>` with the ID of the model you want to evaluate. The model
will receive the problem statement along with instructions on how to use the
`python` and `submit_answer` tools.
