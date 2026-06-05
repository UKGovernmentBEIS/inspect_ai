

Inspect includes some simple text matching scorers as well as a couple of model graded scorers. Built in scorers can be imported from the `inspect_ai.scorer` module. Below is a summary of these scorers—see the [`inspect_ai.scorer`](reference/inspect_ai.scorer.qmd) reference for complete function signatures and options.

::: {.builtin-scorers}

`includes()`
:   Determine whether the `target` appears anywhere inside the model output (a substring match). Case sensitive or insensitive (defaults to insensitive).

`match()`
:   Determine whether the `target` appears at a known position—`begin`, `end` (the default), or `any`—or, with `location="exact"`, that the whole output equals the target. Ignores case and white-space by default. Pass `numeric=True` to compare numbers rather than text (currency symbols `$`/`€`/`£`, thousands separators `,`, and formatting markers `*`/`_` are stripped first).

`pattern()`
:   Extract the answer from model output using a regular expression—best when the answer is embedded in templated text. Requires at least one capture group; with multiple groups, set `match_all=True` to require every captured value to match the target (the default matches any one group). Returns a `NOANSWER` score when the pattern does not match.

`answer()`
:   For prompts that instruct the model to end with `ANSWER: X`. Extracts the letter, word, or remainder of the line that follows.

`model_graded_qa()`
:   Have another model assess whether the output is a correct answer based on grading guidance in `target`—suited to open-ended answers that need judgement. The built-in template can be customised; see [Model Grading](model-graded.qmd).

`model_graded_fact()`
:   Like `model_graded_qa()` but narrower—have another model assess whether the output contains the fact set out in `target`. Useful when the output is too complex to assess with a simple `match()` or `pattern()`. See [Model Grading](model-graded.qmd).

`exact()`
:   Normalize the answer and target(s) and require the whole output to match one or more targets exactly, returning `CORRECT` on a match. Reports `mean` and `stderr` metrics.

`f1()`
:   Compute the F1 score (the harmonic mean of precision and recall) over token overlap—suited to short free-text answers such as extractive QA. Accepts an `answer_fn` to extract the answer from the completion and a `stop_words` list to exclude from tokenization. Reports `mean` and `stderr` metrics.

`choice()`
:   Score multiple-choice questions produced by the `multiple_choice()` solver. Automatically unshuffles choices the solver shuffled before scoring, and supports multiple correct answers via a comma-separated `target` (e.g. `"A,B"`).

`math()`
:   Compare answers for *mathematical* equivalence rather than as text. Extracts answers (supporting both `\boxed{}` LaTeX notation and plain text), normalizes expressions, and uses SymPy to check equivalence across LaTeX, fractions, roots, percentages, and algebra. **Note:** requires the optional `sympy` dependency—install with `pip install sympy`.

`perplexity()`
:   Compute per-token negative log-likelihood (NLL) from prompt log probabilities, for full-text perplexity benchmarks (WikiText, C4). Requires `prompt_logprobs` in `GenerateConfig`. See [Perplexity](perplexity.qmd).

`target_perplexity()`
:   Compute NLL of target-completion tokens only, given a prompt context—for benchmarks like ARC-C, MMLU, and HumanEval where only trailing target tokens are scored. See [Perplexity](perplexity.qmd).

:::

## Metrics

Each scorer provides one or more built-in metrics: most report `accuracy` and `stderr`, while `exact()` and `f1()` report `mean` and `stderr`, and the perplexity scorers report `perplexity_per_token` and `perplexity_per_seq`. You can override these by passing your own `metrics` to the `Task`:

``` python
Task(
    dataset=dataset,
    solver=generate(),
    scorer=match(),
    metrics=[custom_metric()],
)
```

See [Scoring Metrics](metrics.qmd) for the built-in metrics, metric grouping, clustered standard errors, and writing your own.
