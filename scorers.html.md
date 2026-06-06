# Scorers – Inspect

## Overview

Scorers evaluate whether solvers were successful in finding the right `output` for the `target` defined in the dataset, and in what measure. Scorers generally take one of the following forms:

1.  Extracting a specific answer out of a model’s completion output using a variety of heuristics.

2.  Applying a text similarity algorithm to see if the model’s completion is close to what is set out in the `target`.

3.  Using another model to assess whether the model’s completion satisfies a description of the ideal answer in `target`.

4.  Using another rubric entirely (e.g. did the model produce a valid version of a file format, etc.)

Scorers also define one or more metrics which are used to aggregate scores (e.g. [accuracy()](./reference/inspect_ai.scorer.html.md#accuracy) which computes what percentage of scores are correct, or [mean()](./reference/inspect_ai.scorer.html.md#mean) which provides an average for scores that exist on a continuum).

This page covers the built-in scorers that ship with Inspect. The [Scoring](./scoring.html.md) section covers everything else: writing your own scorers, defining and customising metrics, combining multiple scorers, and the offline scoring workflow.

Inspect includes both text matching scorers as well as model graded scorers. Below is a summary of these scorers. See the [`inspect_ai.scorer`](./reference/inspect_ai.scorer.html.md) reference for complete function signatures and options.

[includes()](./reference/inspect_ai.scorer.html.md#includes)  
Check whether the `target` appears anywhere in the model output (a substring match). Case sensitive or insensitive (defaults to insensitive).

[match()](./reference/inspect_ai.scorer.html.md#match)  
Check whether the `target` appears at a known position: `begin`, `end` (the default), or `any`. With `location="exact"` the whole output must equal the target. Ignores case and white-space by default. Pass `numeric=True` to compare numbers rather than text; currency symbols (`$`, `€`, `£`), thousands separators (`,`), and formatting markers (`*`, `_`) are stripped first.

[pattern()](./reference/inspect_ai.scorer.html.md#pattern)  
Extract the answer from model output using a regular expression, for cases where the answer is embedded in templated text. Requires at least one capture group; with multiple groups, set `match_all=True` to require every captured value to match the target (the default matches any one group). Returns a `NOANSWER` score when the pattern does not match.

[answer()](./reference/inspect_ai.scorer.html.md#answer)  
For prompts that instruct the model to end with `ANSWER: X`. Extracts the letter, word, or remainder of the line that follows.

[model_graded_qa()](./reference/inspect_ai.scorer.html.md#model_graded_qa)  
Have another model assess whether the output is a correct answer, based on grading guidance in `target`. Use it for open-ended answers. The built-in template can be customised; see [Model Grading](./model-graded.html.md).

[model_graded_fact()](./reference/inspect_ai.scorer.html.md#model_graded_fact)  
Like [model_graded_qa()](./reference/inspect_ai.scorer.html.md#model_graded_qa) but narrower: have another model assess whether the output contains the fact set out in `target`. Use it when the output is too complex to assess with [match()](./reference/inspect_ai.scorer.html.md#match) or [pattern()](./reference/inspect_ai.scorer.html.md#pattern). See [Model Grading](./model-graded.html.md).

[exact()](./reference/inspect_ai.scorer.html.md#exact)  
Normalize the answer and target(s) and require the whole output to match one or more targets exactly, returning `CORRECT` on a match. Reports `mean` and `stderr` metrics.

[f1()](./reference/inspect_ai.scorer.html.md#f1)  
Compute the F1 score (the harmonic mean of precision and recall) over token overlap, for short free-text answers such as extractive QA. Accepts an `answer_fn` to extract the answer from the completion and a `stop_words` list to exclude from tokenization. Reports `mean` and `stderr` metrics.

[choice()](./reference/inspect_ai.scorer.html.md#choice)  
Score multiple-choice questions produced by the [multiple_choice()](./reference/inspect_ai.solver.html.md#multiple_choice) solver. Unshuffles any choices the solver shuffled before scoring, and supports multiple correct answers via a comma-separated `target` (e.g. `"A,B"`).

[math()](./reference/inspect_ai.scorer.html.md#math)  
Compare answers for mathematical equivalence rather than as text. Extracts answers (supporting both `\boxed{}` LaTeX notation and plain text), normalizes expressions, and uses SymPy to check equivalence across LaTeX, fractions, roots, percentages, and algebra. Requires the optional `sympy` dependency (install with `pip install sympy`).

[perplexity()](./reference/inspect_ai.scorer.html.md#perplexity)  
Compute per-token negative log-likelihood (NLL) from prompt log probabilities, for full-text perplexity benchmarks (WikiText, C4). Requires `prompt_logprobs` in [GenerateConfig](./reference/inspect_ai.model.html.md#generateconfig). See [Perplexity](./perplexity.html.md).

[target_perplexity()](./reference/inspect_ai.scorer.html.md#target_perplexity)  
Compute NLL of target-completion tokens only, given a prompt context, for benchmarks like ARC-C, MMLU, and HumanEval where only trailing target tokens are scored. See [Perplexity](./perplexity.html.md).

## Metrics

Each scorer provides one or more built-in metrics. Most report `accuracy` and `stderr`; [exact()](./reference/inspect_ai.scorer.html.md#exact) and [f1()](./reference/inspect_ai.scorer.html.md#f1) report `mean` and `stderr`; and the perplexity scorers report `perplexity_per_token` and `perplexity_per_seq`. You can override these by passing your own `metrics` to the [Task](./reference/inspect_ai.html.md#task):

``` python
Task(
    dataset=dataset,
    solver=generate(),
    scorer=match(),
    metrics=[custom_metric()],
)
```

See [Scoring Metrics](./metrics.html.md) for the built-in metrics, metric grouping, clustered standard errors, and writing your own.

## Going Further

The [Scoring](./scoring.html.md) section covers the rest of the scoring system in depth:

- [Custom Scorers](./custom-scorers.html.md): write your own scorers using the [Score](./reference/inspect_ai.scorer.html.md#score), [Value](./reference/inspect_ai.scorer.html.md#value), and [Target](./reference/inspect_ai.scorer.html.md#target) types.

- [Model Grading](./model-graded.html.md): customise the model graders, use multiple grader models, and present chat history.

- [Multiple Scorers](./multiple-scorers.html.md): use several scorers together, emit multiple scores, and reduce them.

- [Scoring Workflow](./scoring-workflow.html.md): defer scoring, re-score logs with `inspect score`, and edit scores.

- [Perplexity](./perplexity.html.md): score how well a model predicts text using prompt log probabilities.

You can also customise how scores are displayed in the log viewer. See [Task Views](./task-views.html.md).
