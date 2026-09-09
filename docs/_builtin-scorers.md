Inspect includes both text matching scorers as well as model graded scorers. Below is a summary of these scorers. See the [`inspect_ai.scorer`](reference/inspect_ai.scorer.qmd) reference for complete function signatures and options.

::: {.builtin-scorers}

`includes()`
:   Check whether the `target` appears anywhere in the model output (a substring match). Case sensitive or insensitive (defaults to insensitive).

`match()`
:   Check whether the `target` appears at a known position: `begin`, `end` (the default), or `any`. With `location="exact"` the whole output must equal the target. Ignores case and white-space by default. Pass `numeric=True` to compare numbers rather than text; currency symbols (`$`, `€`, `£`), thousands separators (`,`), and formatting markers (`*`, `_`) are stripped first.

`pattern()`
:   Extract an answer using a regular expression and compare it with the target. Uses the captured values when capture groups are present, or the full match otherwise. For example, `pattern(r"\d+")` extracts `42` from `The answer is 42`. With multiple groups, set `match_all=True` to require every captured value to match the target (the default matches any one group). Returns `INCORRECT` (with `reason="invalid_response_format"`) when the pattern does not match.

`answer()`
:   For prompts that instruct the model to end with `ANSWER: X`. Extracts the letter, word, or remainder of the line that follows.

`model_graded_qa()`
:   Have another model assess whether the output is a correct answer, based on grading guidance in `target`. Use it for open-ended answers. The built-in template can be customised; see [Model Grading](model-graded.qmd).

`model_graded_fact()`
:   Like `model_graded_qa()` but narrower: have another model assess whether the output contains the fact set out in `target`. Use it when the output is too complex to assess with `match()` or `pattern()`. See [Model Grading](model-graded.qmd).

`exact()`
:   Normalize the answer and target(s) and require the whole output to match one or more targets exactly, returning `CORRECT` on a match. Reports `mean` and `stderr` metrics.

`f1()`
:   Compute the F1 score (the harmonic mean of precision and recall) over token overlap, for short free-text answers such as extractive QA. Accepts an `answer_fn` to extract the answer from the completion and a `stop_words` list to exclude from tokenization. Reports `mean` and `stderr` metrics.

`choice()`
:   Score multiple-choice questions produced by the `multiple_choice()` solver. Unshuffles any choices the solver shuffled before scoring, and supports multiple correct answers via a comma-separated `target` (e.g. `"A,B"`). Raises a scoring error if the sample has no choices.

`math()`
:   Compare answers for mathematical equivalence rather than as text. Extracts answers (supporting both `\boxed{}` LaTeX notation and plain text), normalizes expressions, and uses a non-evaluating mathematical grammar with bounded SymPy comparison across LaTeX, fractions, roots, percentages, sets, matrices, and algebra. Mathematical answers are treated as data: parsing and comparison run in a time-bounded worker thread and never evaluate answer text as Python. Malformed or over-budget model answers are incorrect; a sample with no usable reference answer raises a scoring error. Requires the optional math dependencies (install with `pip install inspect-ai[math]`).

`perplexity()`
:   Compute per-token negative log-likelihood (NLL) from prompt log probabilities, for full-text perplexity benchmarks (WikiText, C4). Requires `prompt_logprobs` in `GenerateConfig`. See [Perplexity](perplexity.qmd).

`target_perplexity()`
:   Compute NLL of target-completion tokens only, given a prompt context, for benchmarks like ARC-C, MMLU, and HumanEval where only trailing target tokens are scored. See [Perplexity](perplexity.qmd).

:::

## When the output doesn't match

`includes()`, `match()`, and `exact()` return `INCORRECT` for a non-matching response. `pattern()` and `answer()` return `INCORRECT` when the extracted answer is wrong or the required pattern is absent. An absent pattern also sets `reason="invalid_response_format"`.

These incorrect scores contribute `0.0` to the default metrics. See [Scoring Policy](scoring-policy.qmd) for how scores, unscored results, and errors affect metrics and coverage.

## Metrics

Each scorer provides one or more built-in metrics. Most report `accuracy` and `stderr`; `exact()` and `f1()` report `mean` and `stderr`; and the perplexity scorers report `perplexity_per_token` and `perplexity_per_seq`. You can override these by passing your own `metrics` to the `Task`:

``` python
Task(
    dataset=dataset,
    solver=generate(),
    scorer=match(),
    metrics=[custom_metric()],
)
```

See [Scoring Metrics](metrics.qmd) for the built-in metrics, metric grouping, clustered standard errors, and writing your own.
