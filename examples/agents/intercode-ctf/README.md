## InterCode CTF 

This directory includes an implementation of the [InterCode CTF](https://intercode-benchmark.github.io/#ctf) benchmark (originally published in [InterCode: Standardizing and Benchmarking Interactive Coding with Execution Feedback](https://arxiv.org/abs/2306.14898)). Here we evaluate 81 of the 100 challenges (excluding the 19 challenges that require internet access).

This implementation uses [tool calling](https://ukgovernmentbeis.github.io/inspect_ai/tools.html) to enable the model to execute bash and python code. The system prompt from the paper has been modified accordingly, and also asks the model to reason step by step about each action it takes (this strategy is also [explored](https://github.com/princeton-nlp/intercode/blob/master/experiments/eval_react.py) in the paper).

Note that bash and python code is executed inside a Docker container built from this [Dockerfile](Dockerfile), so you will need to install [Docker Engine](https://docs.docker.com/engine/install/) in order to run the evaluation. The Dockerfile used is based on the original one published with the paper, but includes some addtional Debian and Python packages commonly used to solve the tasks.

To evaluate against various models:

```bash
$ inspect eval task.py --model openai/gpt-4-turbo
$ inspect eval task.py --model anthropic/claude-3-opus-20240229
$ inspect eval task.py --model google/gemini-1.5-pro
$ inspect eval task.py --model mistral/mistral-large-latest
```

If you are experiementing, you might find it useful to evaluate only a random subset of the samples:

```bash
$ inspect eval task.py --model openai/gpt-4-turbo -T shuffle=true --limit 10
```

