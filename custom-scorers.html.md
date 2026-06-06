# Custom Scorers – Inspect

## Overview

Custom scorers are functions that take a [TaskState](./reference/inspect_ai.solver.html.md#taskstate) and [Target](./reference/inspect_ai.scorer.html.md#target), and yield a [Score](./reference/inspect_ai.scorer.html.md#score).

``` python
async def score(state: TaskState, target: Target):
     # Compare state / model output with target
     # to yield a score
     return Score(value=...)
```

First we’ll talk about the core [Score](./reference/inspect_ai.scorer.html.md#score) and [Value](./reference/inspect_ai.scorer.html.md#value) objects, then provide some examples of custom scorers to make things more concrete.

## Example

This scorer extracts the last number from the model’s output and marks the sample correct when it falls within a relative tolerance of the `target`. It registers metrics with `@scorer`, reads the model output from `state`, compares against `target.text`, and returns a [Score](./reference/inspect_ai.scorer.html.md#score) with an `answer` and `explanation`:

``` python
import re

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState, generate


@scorer(metrics=[accuracy(), stderr()])
def close_enough(rel_tol: float = 0.01):
    async def score(state: TaskState, target: Target) -> Score:
        numbers = re.findall(
            r"-?\d+(?:\.\d+)?", state.output.completion
        )
        if not numbers:
            return Score(
                value=INCORRECT, 
                explanation="No number found in output."
            )

        answer = numbers[-1]
        expected = float(target.text)
        correct = abs(float(answer) - expected) <= rel_tol * abs(expected)
        return Score(
            value=CORRECT if correct else INCORRECT,
            answer=answer,
            explanation=state.output.completion,
        )

    return score


@task
def arithmetic():
    return Task(
        dataset=[
            Sample(
                input="What is 18 * 7?",
                target="126"
            ),
        ],
        solver=generate(),
        scorer=close_enough(),
    )
```

The sections below describe the pieces this example relies on.

## Score

The components of [Score](./reference/inspect_ai.scorer.html.md#score) include:

| Field | Type | Description |
|----|----|----|
| `value` | [Value](./reference/inspect_ai.scorer.html.md#value) | Value assigned to the sample (e.g. “C” or “I”, or a raw numeric value). |
| `answer` | `str` | Text extracted from model output for comparison (optional). |
| `explanation` | `str` | Explanation of score, e.g. full model output or grader model output (optional). |
| `metadata` | `dict[str,Any]` | Additional metadata about the score to record in the log file (optional). |

For example, the following are all valid [Score](./reference/inspect_ai.scorer.html.md#score) objects:

``` python
Score(value="C")
Score(value="I")
Score(value=0.6)
Score(
    value="C" if extracted == target.text else "I",
    answer=extracted,
    explanation=state.output.completion
)
```

`Score.value` may be any [Value](./reference/inspect_ai.scorer.html.md#value) that your metrics know how to interpret. Built-in correctness scorers use the constants `CORRECT` (`"C"`), `INCORRECT` (`"I"`), `PARTIAL` (`"P"`), and `NOANSWER` (`"N"`). The default `value_to_float()` converter used by metrics such as [accuracy()](./reference/inspect_ai.scorer.html.md#accuracy) maps these values to `1.0`, `0.0`, `0.5`, and `0.0` respectively. It also converts numeric values, numeric strings, and common boolean strings such as `"yes"` / `"no"` and `"true"` / `"false"`.

You can return other strings, but aggregate metrics need a converter that understands them. For example:

``` python
from inspect_ai.scorer import accuracy, value_to_float

accuracy(
    to_float=value_to_float(correct="pass", incorrect="fail")
)
```

If you are extracting an answer from within a completion (e.g. looking for text using a regex pattern, looking at the beginning or end of the completion, etc.) you should strive to *always* return an `answer` as part of your [Score](./reference/inspect_ai.scorer.html.md#score), as this makes it much easier to understand the details of scoring when viewing the eval log file.

### Unscored Samples

When a scorer cannot produce a value for a sample (e.g. an external grader returned no result, the model refused, or an error occurred) but you still want to record context, use `Score.unscored()`:

``` python
return Score.unscored(
    answer=extracted,
    explanation="grader returned no result",
    metadata={"reason": "timeout"},
)
```

Unscored samples are skipped by aggregate metrics and epoch reducers and are counted toward `EvalScore.unscored_samples` rather than included as zeros. This works for scalar, dict-valued, and list-valued scorers.

## Score Value

[Value](./reference/inspect_ai.scorer.html.md#value) is union over the main scalar types as well as a `list` or `dict` of the same types:

``` python
Value = Union[
    str | int | float | bool,
    Sequence[str | int | float | bool],
    Mapping[str, str | int | float | bool],
]
```

The vast majority of scorers will use `str` (e.g. for correct/incorrect via “C” and “I”) or `float` (the other types are there to meet more complex scenarios). One thing to keep in mind is that whatever [Value](./reference/inspect_ai.scorer.html.md#value) type you use in a scorer must be supported by the metrics declared for the scorer (more on this below).

Next, we’ll take a look at the source code for a couple of the built in scorers as a jumping off point for implementing your own scorers. If you are working on custom scorers, you should also review the [Scoring Workflow](./scoring-workflow.html.md) for tips on optimising your development process.

## Models in Scorers

You’ll often want to use models in the implementation of scorers. Use the [get_model()](./reference/inspect_ai.model.html.md#get_model) function to get either the currently evaluated model or another model interface. For example:

``` python
# use the model being evaluated for grading
grader_model = get_model()

# use another model for grading
grader_model = get_model("google/gemini-2.5-pro")
```

Use the `config` parameter of [get_model()](./reference/inspect_ai.model.html.md#get_model) to override default generation options:

``` python
grader_model = get_model(
    "google/gemini-2.5-pro",
    config = GenerateConfig(
        temperature = 0.0
    )
)
```

## Example: Includes

Here is the source code for the built-in [includes()](./reference/inspect_ai.scorer.html.md#includes) scorer:

``` python
1@scorer(metrics=[accuracy(), stderr()])
def includes(ignore_case: bool = True):

2    async def score(state: TaskState, target: Target):

        # check for correct
        answer = state.output.completion
3        target = target.text
        if ignore_case:
            correct = answer.lower().rfind(target.lower()) != -1
        else:
            correct = answer.rfind(target) != -1

        # return score
        return Score(
4            value = CORRECT if correct else INCORRECT,
5            answer=answer
        )

    return score
```

1  
The function applies the `@scorer` decorator and registers two metrics for use with the scorer.

2  
The `score` function is declared as `async`. This is so that it can participate in Inspect’s optimised scheduling for expensive model generation calls (this scorer doesn’t call a model but others will).

3  
We make use of the `text` property on the [Target](./reference/inspect_ai.scorer.html.md#target). This is a convenience property to get a simple text value out of the [Target](./reference/inspect_ai.scorer.html.md#target) (as targets can technically be a list of strings).

4  
We use the special constants `CORRECT` and `INCORRECT` for the score value (as the [accuracy()](./reference/inspect_ai.scorer.html.md#accuracy), [stderr()](./reference/inspect_ai.scorer.html.md#stderr), and [bootstrap_stderr()](./reference/inspect_ai.scorer.html.md#bootstrap_stderr) metrics know how to convert these special constants to float values (1.0 and 0.0 respectively).

5  
We provide the full model completion as the answer for the score (`answer` is optional, but highly recommended as it is often useful to refer to during evaluation development).

## Example: Model Grading

Here’s a somewhat simplified version of the code for the [model_graded_qa()](./reference/inspect_ai.scorer.html.md#model_graded_qa) scorer:

``` python

@scorer(metrics=[accuracy(), stderr()])
def model_graded_qa(
    template: str = DEFAULT_MODEL_GRADED_QA_TEMPLATE,
    instructions: str = DEFAULT_MODEL_GRADED_QA_INSTRUCTIONS,
    grade_pattern: str = DEFAULT_GRADE_PATTERN,
    model: str | Model | None = None,
) -> Scorer:

    # resolve grading template and instructions,
    # (as they could be file paths or URLs)
    template = resource(template)
    instructions = resource(instructions)

    # resolve model
    grader_model = get_model(model)

    async def score(state: TaskState, target: Target) -> Score:
        # format the model grading template
        score_prompt = template.format(
            question=state.input_text,
            answer=state.output.completion,
            criterion=target.text,
            instructions=instructions,
        )

        # query the model for the score
        result = await grader_model.generate(score_prompt)

        # extract the grade
        match = re.search(grade_pattern, result.completion)
        if match:
            return Score(
                value=match.group(1),
                answer=match.group(0),
                explanation=result.completion,
            )
        else:
            return Score(
                value=INCORRECT,
                explanation="Grade not found in model output: "
                + f"{result.completion}",
            )

    return score
```

Note that the call to `model_grader.generate()` is done with `await`. This is critical to ensure that the scorer participates correctly in the scheduling of generation work.

Note also we use the `input_text` property of the [TaskState](./reference/inspect_ai.solver.html.md#taskstate) to access a string version of the original user input to substitute it into the grading template. Using the `input_text` has two benefits: (1) It is guaranteed to cover the original input from the dataset (rather than a transformed prompt in `messages`); and (2) It normalises the input to a string (as it could have been a message list).

For the full set of customisation options on the built-in graders, see [Model Grading](./model-graded.html.md).
