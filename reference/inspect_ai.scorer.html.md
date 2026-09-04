# inspect_ai.scorer – Inspect

## Scorers

### match

Scorer which matches text or a number.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_match.py#L8)

``` python
@scorer(metrics=[accuracy(), stderr()])
def match(
    location: Literal["begin", "end", "any", "exact"] = "end",
    *,
    ignore_case: bool = True,
    numeric: bool = False,
) -> Scorer
```

`location` Literal\['begin', 'end', 'any', 'exact'\]  
Location to match at. “any” matches anywhere in the output; “exact” requires the output be exactly equal to the target (module whitespace, etc.)

`ignore_case` bool  
Do case insensitive comparison.

`numeric` bool  
Is this a numeric match? When True, currency symbols (`$`, `€`, `£`), thousands separators (`,`), and formatting markers (`*`, `_`) are stripped before numbers are normalized and compared. The percent sign is not stripped: `60%` is ambiguous (it could mean `60` or `0.6`), so an answer of `60%` will not match a numeric target of `60`. To accept a percentage-formatted answer, pass both forms as targets, e.g. `Target(["60", "60%"])`, where the non-numeric `"60%"` is matched as a string.

### includes

Check whether the specified text is included in the model output.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_match.py#L45)

``` python
@scorer(metrics=[accuracy(), stderr()])
def includes(ignore_case: bool = True) -> Scorer
```

`ignore_case` bool  
Use a case insensitive comparison.

### pattern

Scorer which extracts the model answer using a regex.

The regex can have a single capture group or multiple groups. In the case of multiple groups, the scorer can be configured to match either one or all of the extracted groups. If the pattern contains no capture groups, the full match is compared against the target.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_pattern.py#L55)

``` python
@scorer(metrics=[accuracy(), stderr()])
def pattern(pattern: str, ignore_case: bool = True, match_all: bool = False) -> Scorer
```

`pattern` str  
Regular expression for extracting the answer from model output.

`ignore_case` bool  
Ignore case when comparing the extract answer to the targets. (Default: True)

`match_all` bool  
With multiple captures, do all captured values need to match the target? (Default: False)

### answer

Scorer for model output that preceded answers with ANSWER:.

Some solvers including multiple_choice solicit answers from the model prefaced with “ANSWER:”. This scorer extracts answers of this form for comparison with the target.

Note that you must specify a `type` for the answer scorer.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_answer.py#L35)

``` python
@scorer(metrics=[accuracy(), stderr()])
def answer(pattern: Literal["letter", "word", "line"]) -> Scorer
```

`pattern` Literal\['letter', 'word', 'line'\]  
Type of answer to extract. “letter” is used with multiple choice and extracts a single letter; “word” will extract the next word (often used for yes/no answers); “line” will take the rest of the line (used for more more complex answers that may have embedded spaces). Note that when using “line” your prompt should instruct the model to answer with a separate line at the end.

### choice

Scorer for multiple choice answers, required by the `multiple_choice` solver.

This assumes that the model was called using a template ordered with letters corresponding to the answers, so something like:

    What is the capital of France?

    A) Paris
    B) Berlin
    C) London

The target for the dataset will then have a letter corresponding to the correct answer, e.g. the [Target](../reference/inspect_ai.scorer.html.md#target) would be `"A"` for the above question. If multiple choices are correct, the [Target](../reference/inspect_ai.scorer.html.md#target) can be an array of these letters.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_choice.py#L60)

``` python
@scorer(metrics=[accuracy(), stderr()])
def choice() -> Scorer
```

### math

Create a mathematical expression scorer.

Extracts a bounded final answer from model output, parses it without evaluating Python, and compares it to each target under bounded symbolic work.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_math.py#L1180)

``` python
@scorer(metrics=[accuracy(), stderr()])
def math(*, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> Scorer
```

`timeout` float  
Active-work budget in seconds for each parsing phase (target and answer). This is wall-clock time in the host process and so is sensitive to concurrent load; parsing that exceeds it is treated as an incorrect answer (or an unscored target). The first call gets a larger cold-start allowance to absorb one-time imports.

### f1

Scorer which produces an F1 score

Computes the `F1` score for the answer (which balances recall precision by taking the harmonic mean between recall and precision).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_classification.py#L14)

``` python
@scorer(metrics=[mean(), stderr()])
def f1(
    answer_fn: Callable[[str], str] | None = None, stop_words: list[str] | None = None
) -> Scorer
```

`answer_fn` Callable\[\[str\], str\] \| None  
Custom function to extract the answer from the completion (defaults to using the completion).

`stop_words` list\[str\] \| None  
Stop words to include in answer tokenization.

### exact

Scorer which produces an exact match score

Normalizes the text of the answer and target(s) and performs an exact matching comparison of the text. This scorer will return `CORRECT` when the answer is an exact match to one or more targets.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_classification.py#L43)

``` python
@scorer(metrics=[mean(), stderr()])
def exact() -> Scorer
```

### model_graded_qa

Score a question/answer task using a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_model.py#L114)

``` python
@scorer(metrics=[accuracy(), stderr()])
def model_graded_qa(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
    model_role: str | ModelRole | None = "grader",
    reducer: str | ScoreReducer = "majority",
) -> Scorer
```

`template` str \| None  
Template for grading prompt. This template has four variables: - `question`, `criterion`, `answer`, and `instructions` (which is fed from the `instructions` parameter). Variables from sample `metadata` are also available in the template.

`instructions` str \| None  
Grading instructions. This should include a prompt for the model to answer (e.g. with with chain of thought reasoning) in a way that matches the specified `grade_pattern`, for example, the default `grade_pattern` looks for one of GRADE: C, GRADE: P, or GRADE: I.

`grade_pattern` str \| None  
Regex to extract the grade from the model response. Defaults to looking for e.g. GRADE: C The regex should have a single capture group that extracts exactly the letter C, P, I.

`include_history` bool \| Callable\[\[[TaskState](../reference/inspect_ai.solver.html.md#taskstate)\], str\]  
Whether to include the full chat history in the presented question. Defaults to `False`, which presents only the original sample input. Optionally provide a function to customise how the chat history is presented.

`partial_credit` bool  
Whether to allow for “partial” credit for answers (by default assigned a score of 0.5). Defaults to `False`. Only used with the default `instructions` (as custom instructions provide their own prompts for grades). Under those defaults the grader is offered C/I, or C/P/I when this is `True`, and its final `GRADE:` verdict is validated against that set: a verdict outside it (a `P` that was never offered, or any other letter) is a grade-parse failure and leaves the sample unscored rather than being scored or silently falling back to an earlier grade mentioned in the reasoning. Custom `instructions` or an explicit `grade_pattern` are authoritative and keep every grade they match.

`model` list\[str \| [Model](../reference/inspect_ai.model.html.md#model)\] \| str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model or models to use for grading. If a list is provided, each model grades independently and the grades are combined by `reducer`. When this parameter is provided, it takes precedence over `model_role`.

`model_role` str \| [ModelRole](../reference/inspect_ai.model.html.md#modelrole) \| None  
Named model role to use for grading (default: “grader”). Pass `ModelRole(name, required=True)` to require a model to be bound to the role. Ignored if `model` is provided. If specified and a model is bound to this role (e.g. via the `model_roles` argument to [eval()](../reference/inspect_ai.html.md#eval)), that model is used. If a list of models is bound to this role, each model grades independently and the grades are combined by `reducer` (as when a list is passed for `model`). If no role-bound model is available and the role is not required, the model being evaluated (the default model) is used.

`reducer` str \| [ScoreReducer](../reference/inspect_ai.scorer.html.md#scorereducer)  
How the grades of a grader panel are combined (used when `model` — or the binding of `model_role` — is a list). Defaults to `"majority"`: a grade must be returned by more than half of the graders, and the sample is unscored otherwise, so a grader that returns no parseable grade withholds a vote rather than shrinking the panel. Pass `"mode"` for the previous behaviour, in which the most common grade wins and a tie is broken by the order of `model`.

### model_graded_fact

Score a question/answer task with a fact response using a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_model.py#L34)

``` python
@scorer(metrics=[accuracy(), stderr()])
def model_graded_fact(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
    model_role: str | ModelRole | None = "grader",
    reducer: str | ScoreReducer = "majority",
) -> Scorer
```

`template` str \| None  
Template for grading prompt. This template uses four variables: `question`, `criterion`, `answer`, and `instructions` (which is fed from the `instructions` parameter). Variables from sample `metadata` are also available in the template.

`instructions` str \| None  
Grading instructions. This should include a prompt for the model to answer (e.g. with with chain of thought reasoning) in a way that matches the specified `grade_pattern`, for example, the default `grade_pattern` looks for one of GRADE: C, GRADE: P, or GRADE: I).

`grade_pattern` str \| None  
Regex to extract the grade from the model response. Defaults to looking for e.g. GRADE: C The regex should have a single capture group that extracts exactly the letter C, P, or I.

`include_history` bool \| Callable\[\[[TaskState](../reference/inspect_ai.solver.html.md#taskstate)\], str\]  
Whether to include the full chat history in the presented question. Defaults to `False`, which presents only the original sample input. Optionally provide a function to customise how the chat history is presented.

`partial_credit` bool  
Whether to allow for “partial” credit for answers (by default assigned a score of 0.5). Defaults to `False`. Only used with the default `instructions` (as custom instructions provide their own prompts for grades). Under those defaults the grader is offered C/I, or C/P/I when this is `True`, and its final `GRADE:` verdict is validated against that set: a verdict outside it (a `P` that was never offered, or any other letter) is a grade-parse failure and leaves the sample unscored rather than being scored or silently falling back to an earlier grade mentioned in the reasoning. Custom `instructions` or an explicit `grade_pattern` are authoritative and keep every grade they match.

`model` list\[str \| [Model](../reference/inspect_ai.model.html.md#model)\] \| str \| [Model](../reference/inspect_ai.model.html.md#model) \| None  
Model or models to use for grading. If a list is provided, each model grades independently and the grades are combined by `reducer`. When this parameter is provided, it takes precedence over `model_role`.

`model_role` str \| [ModelRole](../reference/inspect_ai.model.html.md#modelrole) \| None  
Named model role to use for grading (default: “grader”). Pass `ModelRole(name, required=True)` to require a model to be bound to the role. Ignored if `model` is provided. If specified and a model is bound to this role (e.g. via the `model_roles` argument to [eval()](../reference/inspect_ai.html.md#eval)), that model is used. If a list of models is bound to this role, each model grades independently and the grades are combined by `reducer` (as when a list is passed for `model`). If no role-bound model is available and the role is not required, the model being evaluated (the default model) is used.

`reducer` str \| [ScoreReducer](../reference/inspect_ai.scorer.html.md#scorereducer)  
How the grades of a grader panel are combined (used when `model` — or the binding of `model_role` — is a list). Defaults to `"majority"`: a grade must be returned by more than half of the graders, and the sample is unscored otherwise, so a grader that returns no parseable grade withholds a vote rather than shrinking the panel. Pass `"mode"` for the previous behaviour, in which the most common grade wins and a tie is broken by the order of `model`.

### perplexity

Score samples by computing per-token negative log-likelihood from prompt logprobs.

Requires `prompt_logprobs` to be set in [GenerateConfig](../reference/inspect_ai.model.html.md#generateconfig) so that the model provider returns log probabilities for each prompt token.

The score value is the per-sample negative log-likelihood (NLL). Per-sample perplexity is `exp(value)`. The companion :func:`perplexity_per_token` metric computes corpus-level perplexity weighted by token count.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_perplexity.py#L26)

``` python
@scorer(metrics=[perplexity_per_token(), perplexity_per_seq()])
def perplexity() -> Scorer
```

### target_perplexity

Score samples by computing NLL of target-completion tokens.

*N* (number of target tokens) is resolved in order:

1.  The `num_target_tokens` argument (uniform for all samples).
2.  `state.metadata["num_target_tokens"]` (per-sample).
3.  Auto-tokenize `state.metadata[target_text_key]` via the model provider’s :meth:`~ModelAPI.tokenize` method.
4.  Raises an error if `target_text` is present but tokenization fails (no silent fallback to incorrect results).

If neither `num_target_tokens` nor `target_text` is available, defaults to `1` (single-token targets like `" A"`).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_target_perplexity.py#L42)

``` python
@scorer(metrics=[perplexity_per_token(), perplexity_per_seq()])
def target_perplexity(
    num_target_tokens: int | None = None,
    target_text_key: str = "target_text",
) -> Scorer
```

`num_target_tokens` int \| None  
Fixed number of trailing prompt tokens. When `None`, resolved per-sample from metadata or auto-tokenization.

`target_text_key` str  
Metadata key holding the target text for auto-tokenization. Defaults to `"target_text"`.

### multi_scorer

Returns a Scorer that runs multiple Scorers in parallel and aggregates their results into a single Score using the provided reducer function.

If every sub-scorer declines to score (returns `None`), the combined scorer returns `Score.unscored(reason="scoring_failed")` rather than invoking the reducer with no scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_multi.py#L19)

``` python
def multi_scorer(scorers: list[Scorer], reducer: str | ScoreReducer) -> Scorer
```

`scorers` list\[[Scorer](../reference/inspect_ai.scorer.html.md#scorer)\]  
a list of Scorers.

`reducer` str \| [ScoreReducer](../reference/inspect_ai.scorer.html.md#scorereducer)  
a function which takes in a list of Scores and returns a single Score.

### cascade

Score with each scorer in turn, stopping at the first that settles.

Runs `scorers` in the order given, cheapest first, and short-circuits at the first stage whose score settles the sample, so later (typically more expensive) stages such as a grader model only run on samples the earlier stages did not settle. This complements `multi_scorer`, which runs every scorer concurrently and reduces their scores, and so cannot skip a stage based on a cheaper stage’s result.

Scorers are passed as keyword arguments so each stage is named explicitly rather than relying on the registry (a scorer is not guaranteed to be a registry object, and registry names are not always meaningful here). `**scorers` preserves call order, which is the order the stages run in.

A stage *settles* the sample when `value_to_float` of its score is at least `threshold` (default `1.0`, i.e. a `CORRECT` verdict). A stage that declines (returns `None`) or is unscored (`nan`) is skipped and the cascade continues. If no stage settles, the last stage that produced a real score is returned; if no stage produced a real score (every stage declined or was unscored), the cascade returns `Score.unscored(reason="scoring_failed")`. The returned score is a copy of the settling stage’s score with `decided_by` added to its metadata, naming the stage whose verdict is returned (the settling stage, or the last scored stage on fall-through); the sub-scorer’s own [Score](../reference/inspect_ai.scorer.html.md#score) object is not mutated.

The cascade assumes earlier (cheaper) scorers do not produce false positives, so a `CORRECT` from exact match or symbolic equivalence can be trusted without running the grader model. That assumption is the caller’s to uphold. `value_to_float` warns and returns `0` for list/dict values, so cascade is intended for scalar `CORRECT`/`INCORRECT`-style scorers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_cascade.py#L12)

``` python
@scorer(metrics=[accuracy(), stderr()])
def cascade(threshold: float = 1.0, **scorers: Scorer) -> Scorer
```

`threshold` float  
Minimum `value_to_float` score for a stage to settle the sample and short-circuit the remaining stages. Defaults to `1.0`.

`**scorers` [Scorer](../reference/inspect_ai.scorer.html.md#scorer)  
Named scorers, run in the order given. A stage cannot be named `threshold`, which is a reserved parameter.

### precomputed_scores

Scorer that applies scores computed outside of Inspect.

Reads scores from a file and applies them to samples by id, for example to attach human ratings to an existing log using the [score()](../reference/inspect_ai.scorer.html.md#score) function or the `inspect score` command. Samples with no matching record are left unscored, or fail the eval if `on_missing` is “error”. Records matching no sample are always ignored.

The file must contain a list of records with an `id` field matching a sample id, a `value` field with the score value, and optionally `epoch`, `answer`, `explanation`, and `metadata` fields (other fields are ignored). Records without an `epoch` apply to every epoch of the sample, and a record with a matching `epoch` takes precedence over one without.

Supported formats are JSON (an array of objects) and JSON Lines (`.jsonl`, one object per line).

To also name the score, wrap this scorer in your own `@scorer`-decorated factory (the score takes the factory’s name):

``` python
@scorer(metrics={"helpful": [mean()], "harmless": [mean()]})
def human_rubric() -> Scorer:
    return precomputed_scores("ratings.json")
```

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_precomputed.py#L15)

``` python
def precomputed_scores(
    scores: str,
    on_missing: Literal["unscored", "error"] = "unscored",
    metrics: list[Metric | dict[str, list[Metric]]]
    | dict[str, list[Metric]]
    | None = None,
) -> Scorer
```

`scores` str  
Path to the scores file. Can be a local filesystem path or a path to an S3 bucket (e.g. “s3://my-bucket/scores.json”).

`on_missing` Literal\['unscored', 'error'\]  
What to do with a sample that has no matching record. “unscored” (the default) leaves it unscored, so metrics are computed over the matched samples only. “error” raises, for a scores file intended to cover every sample.

`metrics` list\[[Metric](../reference/inspect_ai.scorer.html.md#metric) \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\]\] \| dict\[str, list\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\] \| None  
Metrics to aggregate the scores with, defaulting to accuracy and stderr. Use a dict mapping subscore keys to metrics for dict-valued scores. Recorded in the log’s scorer entry, so rescoring the log reuses them.

## Metrics

### accuracy

Compute proportion of total answers which are correct.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/accuracy.py#L14)

``` python
@metric
def accuracy(to_float: ValueToFloat = value_to_float()) -> Metric
```

`to_float` ValueToFloat  
Function for mapping [Value](../reference/inspect_ai.scorer.html.md#value) to float for computing metrics. The default `value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0, PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to float directly, and prints a warning and returns 0 if the Value is a complex object (list or dict).

### categorical

Default metrics for a categorical scorer.

Convenience helper that returns `[frequency(categories)]` for use as the `metrics=` argument of :func:`~inspect_ai.scorer.scorer`. Pass a [StrEnum](../reference/inspect_ai.util.html.md#strenum) to declare the full category set::

    class Verdict(StrEnum):
        YES = "yes"
        NO = "no"
        UNSURE = "unsure"

    @scorer(metrics=categorical(Verdict))
    def my_grader() -> Scorer: ...

For dict-valued scores, use the per-key form::

    @scorer(metrics={"*": categorical(Verdict)})
    def my_grader() -> Scorer: ...

[frequency()](../reference/inspect_ai.scorer.html.md#frequency) declares `@metric(scores="unreduced")`: when epochs are used, each epoch’s score is treated as an independent observation even when a reducer is configured for metrics that use reduced scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/categorical.py#L99)

``` python
def categorical(categories: Categories = None) -> list[Metric]
```

`categories` Categories  
The full set of possible categories (typically a [StrEnum](../reference/inspect_ai.util.html.md#strenum)). Resolved to its member values so the category list is recorded in the metric params and survives [recompute_metrics()](../reference/inspect_ai.log.html.md#recompute_metrics). If `None`, only observed categories are reported.

### frequency

Frequency of each distinct categorical score value.

Returns a mapping from category label to its proportion (or count) among scored samples. Intended for scorers that emit string-valued (categorical) scores, e.g. `Score(value="sandbagging")`.

For dict-valued scores, use the per-key metrics form so that each key gets its own scorer block in the results::

    @scorer(metrics={"*": [frequency()]})
    def my_scorer() -> Scorer: ...

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/categorical.py#L68)

``` python
def frequency(
    categories: Categories = None,
    normalize: bool = True,
) -> Metric
```

`categories` Categories  
The full set of possible categories, as a [StrEnum](../reference/inspect_ai.util.html.md#strenum) type or a sequence of labels. Declare this so that categories with zero observations are still reported as `0.0` and the metric round-trips identically through [recompute_metrics()](../reference/inspect_ai.log.html.md#recompute_metrics). If `None`, only observed categories are reported.

`normalize` bool  
If `True` (default) report proportions in `[0, 1]`; if `False` report raw counts.

### grouped

Creates a grouped metric that applies the given metric to subgroups of samples.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/grouped.py#L14)

``` python
@metric
def grouped(
    metric: Metric,
    group_key: str,
    *,
    all: Literal["samples", "groups"] | Literal[False] = "samples",
    all_label: str = "all",
    value_to_float: ValueToFloat = value_to_float(),
    name_template: str = "{group_name}",
) -> Metric
```

`metric` [Metric](../reference/inspect_ai.scorer.html.md#metric)  
The metric to apply to each group of samples.

`group_key` str  
The metadata key used to group samples. Each sample must have this key in its metadata.

`all` Literal\['samples', 'groups'\] \| Literal\[False\]  
How to compute the “all” aggregate score: - “samples”: Apply the metric to all samples regardless of groups - “groups”: Calculate the mean of all group scores - False: Don’t calculate an aggregate score

`all_label` str  
The label for the “all” key in the returned dictionary.

`value_to_float` ValueToFloat  
Function to convert metric values to floats, used when all=“groups”.

`name_template` str  
Template for the name of each group. The default is “{group_name}”.

### aggregate

Apply `agg` to a single key extracted from each dict-valued `Score.value`.

Many scorers emit dict-valued scores (multiple numeric fields per sample). `aggregate` selects one field by `key` and feeds the resulting scalar [SampleScore](../reference/inspect_ai.scorer.html.md#samplescore)s into `agg`, so any standard metric (`mean`, `stderr`, `std`, `accuracy`, …) can be applied per key.

A missing key (either `key not in value` or `value[key] is None`) is routed through `on_missing`. This matches the convention used by `inspect_evals.utils.metrics.mean_of`, so a `mean_of` → `aggregate` swap preserves behaviour.

`on_missing="skip"` reduces the number of samples seen by `agg`, which changes the result of any aggregator that depends on sample count (e.g. `stderr`, `mean`, `std`, `var`). Two evals run with the same scorer can therefore report different stderrs purely because the rate of missing keys differed, not because of any difference in the underlying variance. Prefer `"zero"` if you want a constant denominator.

If every sample is filtered out by `on_missing="skip"`, the aggregator returns `NaN` rather than calling `agg([])` (which most built-in metrics would raise on). This matches the `Score.unscored()` / NaN sentinel used elsewhere in the framework.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/aggregate.py#L17)

``` python
@metric
def aggregate(
    key: str,
    agg: Metric,
    *,
    to_float: ValueToFloat | None = None,
    on_missing: Literal["error", "skip", "zero"] = "error",
) -> Metric
```

`key` str  
Field to extract from each sample’s dict-valued `Score.value`.

`agg` [Metric](../reference/inspect_ai.scorer.html.md#metric)  
Metric to apply to the extracted values.

`to_float` ValueToFloat \| None  
Optional function for mapping the extracted [Value](../reference/inspect_ai.scorer.html.md#value) to a float before it reaches `agg`. The default (`None`) passes the raw extracted value straight through, so `agg`’s own conversion applies (e.g. [accuracy()](../reference/inspect_ai.scorer.html.md#accuracy)’s `to_float`, or [mean()](../reference/inspect_ai.scorer.html.md#mean)’s `as_float()`). Set this only when `agg` cannot convert the value itself — e.g. to feed string grades (“C”/“I”) into [mean()](../reference/inspect_ai.scorer.html.md#mean), which expects numerics. When set, pass `value_to_float()` (or a customised variant) to get the standard CORRECT/INCORRECT/PARTIAL/NOANSWER mapping.

`on_missing` Literal\['error', 'skip', 'zero'\]  
How to handle samples whose `score.value` does not contain `key`, or contains `key` with a `None` value:

- `"error"` (default): raise `ValueError`.
- `"skip"`: exclude the sample from `agg`. Returns `NaN` if every sample is skipped.
- `"zero"`: include the sample with value `0.0`.

### mean

Compute mean of all scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/mean.py#L10)

``` python
@metric
def mean(to_float: ValueToFloat = value_to_float()) -> Metric
```

`to_float` ValueToFloat  
Function for mapping [Value](../reference/inspect_ai.scorer.html.md#value) to float for computing metrics. The default `value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0, PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to float directly, and prints a warning and returns 0 if the Value is a complex object (list or dict).

### std

Calculates the sample standard deviation of a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/std.py#L538)

``` python
@metric
def std(to_float: ValueToFloat = value_to_float()) -> Metric
```

`to_float` ValueToFloat  
Function for mapping [Value](../reference/inspect_ai.scorer.html.md#value) to float for computing metrics. The default `value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0, PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to float directly, and prints a warning and returns 0 if the Value is a complex object (list or dict).

### stderr

Standard error of the mean using Central Limit Theorem.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/std.py#L121)

``` python
@metric
def stderr(
    to_float: ValueToFloat = value_to_float(), cluster: str | None = None
) -> Metric
```

`to_float` ValueToFloat  
Function for mapping [Value](../reference/inspect_ai.scorer.html.md#value) to float for computing metrics. The default `value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0, PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to float directly, and prints a warning and returns 0 if the Value is a complex object (list or dict).

`cluster` str \| None  
The key from the Sample metadata corresponding to a cluster identifier for computing [clustered standard errors](https://en.wikipedia.org/wiki/Clustered_standard_errors).

### bootstrap_stderr

Standard error of the mean using bootstrap.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/std.py#L17)

``` python
@metric
def bootstrap_stderr(
    num_samples: int = 1000, to_float: ValueToFloat = value_to_float()
) -> Metric
```

`num_samples` int  
Number of bootstrap samples to take.

`to_float` ValueToFloat  
Function for mapping Value to float for computing metrics. The default `value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0, PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to float directly, and prints a warning and returns 0 if the Value is a complex object (list or dict).

### ci

Confidence interval for the mean of a list of scores.

Reports the two-sided `level` confidence interval for the mean score as a mapping with `lower` and `upper` bounds. This complements [stderr()](../reference/inspect_ai.scorer.html.md#stderr) (which reports only the standard error) by giving directly comparable interval bounds — e.g. for deciding whether two models’ accuracies overlap.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/std.py#L171)

``` python
@metric
def ci(
    level: float = 0.95,
    method: Literal["t", "bootstrap"] = "t",
    num_samples: int = 1000,
    to_float: ValueToFloat = value_to_float(),
    cluster: str | None = None,
) -> Metric
```

`level` float  
Confidence level for the interval (e.g. `0.95` for a 95% interval). Must be in the open interval (0, 1).

`method` Literal\['t', 'bootstrap'\]  
Interval method. `"t"` (the default) computes `mean ± t · stderr` where `t` is the Student-t critical value with `n - 1` degrees of freedom (`clusters - 1` for clustered intervals); this converges to the normal-approximation interval for large samples while remaining honest for small ones. `"bootstrap"` uses a percentile bootstrap of the mean, which is useful for skewed score distributions.

`num_samples` int  
Number of bootstrap resamples (only used when `method="bootstrap"`).

`to_float` ValueToFloat  
Function for mapping [Value](../reference/inspect_ai.scorer.html.md#value) to float for computing metrics. The default `value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0, PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to float directly, and prints a warning and returns 0 if the [Value](../reference/inspect_ai.scorer.html.md#value) is a complex object (list or dict).

`cluster` str \| None  
The key from the Sample metadata corresponding to a cluster identifier for computing [clustered](https://en.wikipedia.org/wiki/Clustered_standard_errors) intervals. When set, `method="t"` uses the clustered standard error with `clusters - 1` degrees of freedom and `method="bootstrap"` resamples whole clusters (cluster bootstrap), so the interval accounts for within-cluster correlation.

### ci_wilson

Wilson score confidence interval for the mean of binary (0/1) scores.

Treats the mean score as a binomial proportion and reports the two-sided `level` Wilson score interval as a mapping with `lower` and `upper` bounds. Unlike the t interval from [ci()](../reference/inspect_ai.scorer.html.md#ci), the bounds are always within \[0, 1\] and remain well calibrated for small samples and for proportions near 0 or 1 — prefer this metric over [ci()](../reference/inspect_ai.scorer.html.md#ci) for binary scores such as accuracy.

Score values must lie in \[0, 1\]: values outside that range raise a `ValueError` (there is no binomial reading of such data). Non-binary values within \[0, 1\] (e.g. PARTIAL scored as 0.5) are accepted; because the variance of any \[0, 1\]-bounded variable is at most `p̂(1 − p̂)`, the resulting interval is conservative (a little wider than necessary) rather than misleadingly narrow.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/std.py#L261)

``` python
@metric
def ci_wilson(
    level: float = 0.95,
    to_float: ValueToFloat = value_to_float(),
    cluster: str | None = None,
) -> Metric
```

`level` float  
Confidence level for the interval (e.g. `0.95` for a 95% interval). Must be in the open interval (0, 1).

`to_float` ValueToFloat  
Function for mapping [Value](../reference/inspect_ai.scorer.html.md#value) to float for computing metrics. The default `value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0, PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to float directly, and prints a warning and returns 0 if the [Value](../reference/inspect_ai.scorer.html.md#value) is a complex object (list or dict).

`cluster` str \| None  
The key from the Sample metadata corresponding to a cluster identifier for computing [clustered](https://en.wikipedia.org/wiki/Clustered_standard_errors) intervals. When set, the interval uses the Korn-Graubard effective sample size `p̂(1 − p̂) / v̂` (capped at `n`), where `v̂` is the clustered variance of the mean, and a Student-t critical value with `clusters − 1` degrees of freedom in place of the normal one, so the interval accounts for within-cluster correlation and for the uncertainty of the variance estimate when clusters are few. Requires at least two clusters (the clustered variance is unestimable otherwise); when the effective size cannot be estimated (`p̂` exactly 0 or 1, or zero clustered variance) the unadjusted `n` is used. See Franco et al. (<https://pmc.ncbi.nlm.nih.gov/articles/PMC6690503/>).

### perplexity_per_token

Corpus-level perplexity weighted by token count.

Longer samples contribute proportionally more. Computed as `exp(-total_sum_log_probs / total_num_tokens)`.

This is the standard definition of corpus perplexity used in the HuggingFace Transformers documentation and the EleutherAI lm-evaluation-harness (`weighted_perplexity`).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/perplexity.py#L64)

``` python
@metric
def perplexity_per_token() -> Metric
```

### perplexity_per_seq

Corpus-level perplexity with equal weight per sample.

Each sample’s per-token NLL is averaged, then exponentiated. Computed as `exp(mean_over_samples(-sum_log_probs_i / num_tokens_i))` – the geometric mean of per-sample perplexities.

Unlike `perplexity_per_token`, this gives equal weight to each sample regardless of length, preventing long samples from dominating the metric. The EleutherAI lm-evaluation-harness `perplexity` aggregation is a different metric, `exp(-mean(loglikelihood_i))` over raw per-document log-likelihoods with no per-token normalization.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/perplexity.py#L93)

``` python
@metric
def perplexity_per_seq() -> Metric
```

### krippendorff_alpha

Krippendorff’s α coefficient of inter-rater agreement.

Computes Krippendorff’s α across multiple judges/raters for each sample. Each [SampleScore](../reference/inspect_ai.scorer.html.md#samplescore) passed to the metric must have a sequence-valued `Score.value`, where each element is one judge’s rating of that sample; produce these per-judge lists by pairing [multi_scorer()](../reference/inspect_ai.scorer.html.md#multi_scorer) with the `collect` reducer. Samples whose `Score.value` is not a sequence (or contains fewer than two ratings) are skipped.

α = 1 indicates perfect agreement; α = 0 indicates agreement equal to chance; α \< 0 indicates systematic disagreement.

For the 2-judge nominal case, α coincides with Scott’s π (its many-judge analogue is Fleiss’ κ); the two converge only as the number of units grows, since α applies a small-sample correction.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metrics/krippendorff.py#L21)

``` python
@metric
def krippendorff_alpha(
    level: KrippendorffLevel = "nominal",
    to_float: ValueToFloat | None = None,
) -> Metric
```

`level` KrippendorffLevel  
Measurement scale. `"nominal"` (default) treats ratings as unordered categories (any difference is a full disagreement). Use for correct/incorrect labels and unordered category IDs. `"ordinal"` treats ratings as ordered categories whose gaps are not assumed equal; δ² is weighted by the marginal frequency of intermediate ranks (Krippendorff 2007). Use for Likert-style ratings. `"interval"` treats ratings as numbers on an equal-interval scale; δ² is the squared numeric difference. Use for continuous scores.

`to_float` ValueToFloat \| None  
Optional `ValueToFloat` used to coerce non-numeric ratings to floats for `"ordinal"` and `"interval"` (e.g., `value_to_float()` to map CORRECT/INCORRECT/PARTIAL/NOANSWER to 1/0/0.5/0). Numeric ratings need no coercion. Raises if `"ordinal"` or `"interval"` is selected with non-numeric ratings and no `to_float`. Ignored for `"nominal"`.

## Reducers

### at_least

Score correct if there are at least k score values greater than or equal to the value.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L129)

``` python
@score_reducer
def at_least(
    k: int, value: float = 1.0, value_to_float: ValueToFloat = value_to_float()
) -> ScoreReducer
```

`k` int  
Number of score values that must exceed `value`.

`value` float  
Score value threshold.

`value_to_float` ValueToFloat  
Function to convert score values to float.

### pass_at

Probability of at least 1 correct sample given `k` epochs (<https://arxiv.org/pdf/2107.03374>).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L163)

``` python
@score_reducer
def pass_at(
    k: int, value: float = 1.0, value_to_float: ValueToFloat = value_to_float()
) -> ScoreReducer
```

`k` int  
Epochs to compute probability for.

`value` float  
Score value threshold.

`value_to_float` ValueToFloat  
Function to convert score values to float.

### pass_k

Probability that all `k` epoch attempts succeed (<https://arxiv.org/pdf/2406.12045>).

Computed as the draw-without-replacement estimator `C(correct, k) / C(total, k)`, dual to `pass_at`’s Chen 2021 estimator.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L208)

``` python
@score_reducer
def pass_k(
    k: int, value: float = 1.0, value_to_float: ValueToFloat = value_to_float()
) -> ScoreReducer
```

`k` int  
Epochs to compute probability for.

`value` float  
Score value threshold.

`value_to_float` ValueToFloat  
Function to convert score values to float.

### max_score

Take the maximum value from a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L247)

``` python
@score_reducer(name="max")
def max_score(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer
```

`value_to_float` ValueToFloat  
Function to convert the value to a float

### mean_score

Take the mean of a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L85)

``` python
@score_reducer(name="mean")
def mean_score(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer
```

`value_to_float` ValueToFloat  
Function to convert the value to a float

### median_score

Take the median value from a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L107)

``` python
@score_reducer(name="median")
def median_score(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer
```

`value_to_float` ValueToFloat  
Function to convert the value to a float

### mode_score

Take the mode from a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L12)

``` python
@score_reducer(name="mode")
def mode_score() -> ScoreReducer
```

### majority_score

Take the strict majority of a panel of scores.

A value wins only if more than half of the scores carry it. Unscored (NaN) scores count towards the total rather than being filtered out of it, so a panel member that fails to produce a value withholds a vote without lowering the bar for the remaining values. Where nothing reaches a majority the reduced score is unscored, rather than being decided by the order the panel was declared in.

For dict and list values the threshold applies per key and per index, and the total is still the number of scores reduced: a value missing from one key (or a score that is unscored at the root) withholds a vote for that key alone, or for every key, respectively.

The reduced score’s metadata records the individual votes under a `panel` key (replacing any `panel` carried over from the first score), since a majority is only auditable alongside what was cast.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L41)

``` python
@score_reducer(name="majority")
def majority_score() -> ScoreReducer
```

### collect_score

Collect each score’s value into a list, preserving every value.

Keeps the individual values intact instead of aggregating them into one. Score values must be scalar; unscored (NaN) scores are dropped.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/reducer.py#L304)

``` python
@score_reducer(name="collect")
def collect_score() -> ScoreReducer
```

## Types

### Scorer

Score model outputs.

Evaluate the passed outputs and targets and return a dictionary with scoring outcomes and context.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_scorer.py#L36)

``` python
class Scorer(Protocol):
    async def __call__(
        self,
        state: TaskState,
        target: Target,
    ) -> Score | None
```

`state` [TaskState](../reference/inspect_ai.solver.html.md#taskstate)  
Task state

`target` [Target](../reference/inspect_ai.scorer.html.md#target)  
Ideal target for the output.

#### Examples

``` python
@scorer
def custom_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # Compare state / model output with target
        # to yield a score
        return Score(value=...)

    return score
```

### Target

Target for scoring against the current TaskState.

Target is a sequence of one or more strings. Use the `text` property to access the value as a single string.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_target.py#L4)

``` python
class Target(Sequence[str])
```

### Score

Score generated by a scorer.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L112)

``` python
class Score(BaseModel)
```

#### Attributes

`value` [Value](../reference/inspect_ai.scorer.html.md#value)  
Score value.

`answer` str \| None  
Answer extracted from model output (optional)

`explanation` str \| None  
Explanation of score (optional).

`reason` ScoreReason \| str \| None  
Machine-readable reason for an abnormal score (optional).

`metadata` dict\[str, Any\] \| None  
Additional metadata related to the score

`history` list\[ScoreEdit\]  
Edit history - users can access intermediate states.

`text` str  
Read the score as text.

#### Methods

unscored  
Construct a Score that is preserved but excluded from metrics and reducers.

Use this when a scorer cannot produce a value for a sample but you still want to record context (reason, answer, explanation, metadata). Sets `value` to NaN, which is the canonical sentinel that aggregate metrics and reducers skip.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L157)

``` python
@classmethod
def unscored(
    cls,
    *,
    reason: ScoreReason | str | None = None,
    answer: str | None = None,
    explanation: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> "Score"
```

`reason` ScoreReason \| str \| None  

`answer` str \| None  

`explanation` str \| None  

`metadata` dict\[str, Any\] \| None  

as_str  
Read the score as a string.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L186)

``` python
def as_str(self) -> str
```

as_int  
Read the score as an integer.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L190)

``` python
def as_int(self) -> int
```

as_float  
Read the score as a float.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L194)

``` python
def as_float(self) -> float
```

as_bool  
Read the score as a boolean.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L198)

``` python
def as_bool(self) -> bool
```

as_list  
Read the score as a list.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L202)

``` python
def as_list(self) -> list[str | int | float | bool]
```

as_dict  
Read the score as a dictionary.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L209)

``` python
def as_dict(self) -> dict[str, str | int | float | bool | None]
```

### Reference

Reference from a score to content in the scored transcript.

References are stored as a list of dicts under a score’s `metadata["scanner_references"]` key. Inspect View identifies scanner scores by the presence of that key and renders cites in the score’s explanation (e.g. `[M22]`) as links to the referenced content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L223)

``` python
class Reference(BaseModel)
```

#### Attributes

`type` Literal\['message', 'event'\]  
Reference type.

`cite` str \| None  
Cite text used when the entity was referenced (optional).

For example, a model may have pointed to a message using something like \[M22\], which is the cite.

`id` str  
Reference id (message or event id)

### Value

Value provided by a score.

Use the methods of [Score](../reference/inspect_ai.scorer.html.md#score) to easily treat the [Value](../reference/inspect_ai.scorer.html.md#value) as a simple scalar of various types.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L67)

``` python
Value = Union[
    str | int | float | bool,
    Sequence[str | int | float | bool],
    Mapping[str, str | int | float | bool | None],
]
```

### ScoreReducer

Reduce a set of scores to a single score.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/types.py#L8)

``` python
class ScoreReducer(Protocol):
    def __call__(self, scores: list[Score]) -> Score
```

`scores` list\[[Score](../reference/inspect_ai.scorer.html.md#score)\]  
List of scores.

### Metric

Metric protocol.

The Metric signature changed in release v0.3.64. Both the previous and new signatures are supported – you should use [MetricProtocol](../reference/inspect_ai.scorer.html.md#metricprotocol) for new code as the depreacated signature will eventually be removed.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L371)

``` python
Metric = MetricProtocol | MetricDeprecated
```

### MetricProtocol

Compute a metric on a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L350)

``` python
class MetricProtocol(Protocol):
    def __call__(self, scores: list[SampleScore]) -> Value
```

`scores` list\[[SampleScore](../reference/inspect_ai.scorer.html.md#samplescore)\]  
List of scores.

#### Examples

``` python
@metric
def mean() -> Metric:
    def metric(scores: list[SampleScore]) -> Value:
        return np.mean([score.score.as_float() for score in scores]).item()
    return metric
```

### SampleScore

Score for a Sample.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L245)

``` python
class SampleScore(BaseModel)
```

#### Attributes

`score` [Score](../reference/inspect_ai.scorer.html.md#score)  
A score

`sample_id` str \| int \| None  
A sample id

`sample_metadata` dict\[str, Any\] \| None  
Metadata from the sample

`scorer` str \| None  
Registry name of scorer that created this score.

#### Methods

sample_metadata_as  
Pydantic model interface to sample metadata.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L257)

``` python
def sample_metadata_as(self, metadata_cls: Type[MT]) -> MT | None
```

`metadata_cls` Type\[MT\]  
Pydantic model type

## Decorators

### scorer

Decorator for registering scorers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_scorer.py#L133)

``` python
def scorer(
    metrics: Sequence[Metric | Mapping[str, Sequence[Metric]]]
    | Mapping[str, Sequence[Metric]],
    name: str | None = None,
    **metadata: Any,
) -> Callable[[Callable[P, Scorer]], Callable[P, Scorer]]
```

`metrics` Sequence\[[Metric](../reference/inspect_ai.scorer.html.md#metric) \| Mapping\[str, Sequence\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\]\] \| Mapping\[str, Sequence\[[Metric](../reference/inspect_ai.scorer.html.md#metric)\]\]  
One or more metrics to calculate over the scores.

`name` str \| None  
Optional name for scorer. If the decorator has no name argument then the name of the underlying ScorerType object will be used to automatically assign a name.

`**metadata` Any  
Additional values to serialize in metadata.

#### Examples

``` python
@scorer
def custom_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        # Compare state / model output with target
        # to yield a score
        return Score(value=...)

    return score
```

### metric

Decorator for registering metrics.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_metric.py#L505)

``` python
def metric(
    name: str | Callable[P, Metric] | None = None,
    *,
    scores: MetricScores = "auto",
) -> Callable[[Callable[P, Metric]], Callable[P, Metric]] | Callable[P, Metric]
```

`name` str \| Callable\[P, [Metric](../reference/inspect_ai.scorer.html.md#metric)\] \| None  
Optional name for metric. If the decorator has no name argument then the name of the underlying MetricType will be used to automatically assign a name.

`scores` MetricScores  
Epoch-reduction contract for the metric’s `scores` input. `"auto"` (default) preserves legacy behavior, receiving reduced scores unless reducers are explicitly disabled. `"reduced"` requires one score per sample after the configured [ScoreReducer](../reference/inspect_ai.scorer.html.md#scorereducer) runs. `"unreduced"` receives one score per sample per epoch — use this for metrics that treat each epoch as an independent observation (e.g. [frequency()](../reference/inspect_ai.scorer.html.md#frequency)).

#### Examples

\`\`\`python @metric def mean() -\> Metric: def metric(scores: list\[SampleScore\]) -\> Value: return np.mean(\[score.score.as_float() for score in scores\]).item() return metric

### score_reducer

Decorator for registering Score Reducers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_reducer/registry.py#L35)

``` python
def score_reducer(
    func: ScoreReducerType | None = None, *, name: str | None = None
) -> Callable[[ScoreReducerType], ScoreReducerType] | ScoreReducerType
```

`func` ScoreReducerType \| None  
Function returning [ScoreReducer](../reference/inspect_ai.scorer.html.md#scorereducer) targeted by plain task decorator without attributes (e.g. `@score_reducer`)

`name` str \| None  
Optional name for reducer. If the decorator has no name argument then the name of the function will be used to automatically assign a name.

## Intermediate Scoring

### score

Score a model conversation.

Score a model conversation (you may pass [TaskState](../reference/inspect_ai.solver.html.md#taskstate) or [AgentState](../reference/inspect_ai.agent.html.md#agentstate) as the value for `conversation`)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/7aa7343e4a14fa7be07e5a09c7431df5e88c17ee/src/inspect_ai/scorer/_score.py#L14)

``` python
async def score(conversation: ModelConversation) -> list[Score]
```

`conversation` [ModelConversation](../reference/inspect_ai.model.html.md#modelconversation)  
Conversation to submit for scoring. Note that both [TaskState](../reference/inspect_ai.solver.html.md#taskstate) and [AgentState](../reference/inspect_ai.agent.html.md#agentstate) can be passed as the `conversation` parameter.
