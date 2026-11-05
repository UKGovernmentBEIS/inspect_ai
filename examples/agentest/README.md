# agentest checklist

Community example of the open [agentest](https://github.com/srpadmanabhuni/agentest) checklist with Inspect. This is not an official Inspect integration. inspect-ai is not an agentest dependency; install Inspect separately.

The checklist is an open set of 110 tests across 4 pillars (evals, security, privacy, and responsible behaviour), with examples, labelled traces, and the open-source agentest runner.

This task loads the Hugging Face dataset [`srinivaspadmanabhuni/agentic-ai-test-checklist-110`](https://huggingface.co/datasets/srinivaspadmanabhuni/agentic-ai-test-checklist-110), config `examples`. Each row is a synthetic example: an input (often a fixture and a trigger) and an `expected_behavior`. The task asks the model to describe what it would do, then uses `model_graded_qa()` to compare that description with `expected_behavior`. It does not run the agentest runner, and it does not score labelled traces. The full checklist of 110 tests is config `all`.

Contact: srinivas AT testAIng.com

## Smoke run

The command below uses Inspect's offline `mockllm` model for the evaluated model and the grader role, so it does not call a hosted model API. `mockllm` does not emit a grade that `model_graded_qa()` can parse, so the accuracy it prints is not a checklist score. The command checks that the task loads and runs. Loading the task still downloads the `examples` config from the Hugging Face Hub, which needs the `datasets` package and network access to the Hub.

```bash
inspect eval examples/agentest/task.py --model mockllm/model --model-role grader=mockllm/model --limit 3
```
