# inspect_ai.scorer


## Scorers

### match

Scorer which matches text or a number.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_match.py#L8)

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
Location to match at. “any” matches anywhere in the output; “exact”
requires the output be exactly equal to the target (module whitespace,
etc.)

`ignore_case` bool  
Do case insensitive comparison.

`numeric` bool  
Is this a numeric match? (in this case different punctuation removal
rules are used and numbers are normalized before comparison).

### includes

Check whether the specified text is included in the model output.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_match.py#L39)

``` python
@scorer(metrics=[accuracy(), stderr()])
def includes(ignore_case: bool = True) -> Scorer
```

`ignore_case` bool  
Use a case insensitive comparison.

### pattern

Scorer which extracts the model answer using a regex.

Note that at least one regex group is required to match against the
target.

The regex can have a single capture group or multiple groups. In the
case of multiple groups, the scorer can be configured to match either
one or all of the extracted groups

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_pattern.py#L46)

``` python
@scorer(metrics=[accuracy(), stderr()])
def pattern(pattern: str, ignore_case: bool = True, match_all: bool = False) -> Scorer
```

`pattern` str  
Regular expression for extracting the answer from model output.

`ignore_case` bool  
Ignore case when comparing the extract answer to the targets. (Default:
True)

`match_all` bool  
With multiple captures, do all captured values need to match the target?
(Default: False)

### answer

Scorer for model output that preceded answers with ANSWER:.

Some solvers including multiple_choice solicit answers from the model
prefaced with “ANSWER:”. This scorer extracts answers of this form for
comparison with the target.

Note that you must specify a `type` for the answer scorer.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_answer.py#L35)

``` python
@scorer(metrics=[accuracy(), stderr()])
def answer(pattern: Literal["letter", "word", "line"]) -> Scorer
```

`pattern` Literal\['letter', 'word', 'line'\]  
Type of answer to extract. “letter” is used with multiple choice and
extracts a single letter; “word” will extract the next word (often used
for yes/no answers); “line” will take the rest of the line (used for
more more complex answers that may have embedded spaces). Note that when
using “line” your prompt should instruct the model to answer with a
separate line at the end.

### choice

Scorer for multiple choice answers, required by the `multiple_choice`
solver.

This assumes that the model was called using a template ordered with
letters corresponding to the answers, so something like:

    What is the capital of France?

    A) Paris
    B) Berlin
    C) London

The target for the dataset will then have a letter corresponding to the
correct answer, e.g. the `Target` would be `"A"` for the above question.
If multiple choices are correct, the `Target` can be an array of these
letters.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_choice.py#L40)

``` python
@scorer(metrics=[accuracy(), stderr()])
def choice() -> Scorer
```

### f1

Scorer which produces an F1 score

Computes the `F1` score for the answer (which balances recall precision
by taking the harmonic mean between recall and precision).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_classification.py#L13)

``` python
@scorer(metrics=[mean(), stderr()])
def f1(
    answer_fn: Callable[[str], str] | None = None, stop_words: list[str] | None = None
) -> Scorer
```

`answer_fn` Callable\[\[str\], str\] \| None  
Custom function to extract the answer from the completion (defaults to
using the completion).

`stop_words` list\[str\] \| None  
Stop words to include in answer tokenization.

### exact

Scorer which produces an exact match score

Normalizes the text of the answer and target(s) and performs an exact
matching comparison of the text. This scorer will return `CORRECT` when
the answer is an exact match to one or more targets.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_classification.py#L42)

``` python
@scorer(metrics=[mean(), stderr()])
def exact() -> Scorer
```

### model_graded_qa

Score a question/answer task using a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_model.py#L76)

``` python
@scorer(metrics=[accuracy(), stderr()])
def model_graded_qa(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
) -> Scorer
```

`template` str \| None  
Template for grading prompt. This template has four variables: -
`question`, `criterion`, `answer`, and `instructions` (which is fed from
the `instructions` parameter). Variables from sample `metadata` are also
available in the template.

`instructions` str \| None  
Grading instructions. This should include a prompt for the model to
answer (e.g. with with chain of thought reasoning) in a way that matches
the specified `grade_pattern`, for example, the default `grade_pattern`
looks for one of GRADE: C, GRADE: P, or GRADE: I.

`grade_pattern` str \| None  
Regex to extract the grade from the model response. Defaults to looking
for e.g. GRADE: C The regex should have a single capture group that
extracts exactly the letter C, P, I.

`include_history` bool \| Callable\[\[[TaskState](inspect_ai.solver.qmd#taskstate)\], str\]  
Whether to include the full chat history in the presented question.
Defaults to `False`, which presents only the original sample input.
Optionally provide a function to customise how the chat history is
presented.

`partial_credit` bool  
Whether to allow for “partial” credit for answers (by default assigned a
score of 0.5). Defaults to `False`. Note that this parameter is only
used with the default `instructions` (as custom instructions provide
their own prompts for grades).

`model` list\[str \| [Model](inspect_ai.model.qmd#model)\] \| str \| [Model](inspect_ai.model.qmd#model) \| None  
Model or Models to use for grading. If multiple models are passed, a
majority vote of their grade will be returned. By default the model
being evaluated is used.

### model_graded_fact

Score a question/answer task with a fact response using a model.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_model.py#L28)

``` python
@scorer(metrics=[accuracy(), stderr()])
def model_graded_fact(
    template: str | None = None,
    instructions: str | None = None,
    grade_pattern: str | None = None,
    include_history: bool | Callable[[TaskState], str] = False,
    partial_credit: bool = False,
    model: list[str | Model] | str | Model | None = None,
) -> Scorer
```

`template` str \| None  
Template for grading prompt. This template uses four variables:
`question`, `criterion`, `answer`, and `instructions` (which is fed from
the `instructions` parameter). Variables from sample `metadata` are also
available in the template.

`instructions` str \| None  
Grading instructions. This should include a prompt for the model to
answer (e.g. with with chain of thought reasoning) in a way that matches
the specified `grade_pattern`, for example, the default `grade_pattern`
looks for one of GRADE: C, GRADE: P, or GRADE: I).

`grade_pattern` str \| None  
Regex to extract the grade from the model response. Defaults to looking
for e.g. GRADE: C The regex should have a single capture group that
extracts exactly the letter C, P, or I.

`include_history` bool \| Callable\[\[[TaskState](inspect_ai.solver.qmd#taskstate)\], str\]  
Whether to include the full chat history in the presented question.
Defaults to `False`, which presents only the original sample input.
Optionally provide a function to customise how the chat history is
presented.

`partial_credit` bool  
Whether to allow for “partial” credit for answers (by default assigned a
score of 0.5). Defaults to `False`. Note that this parameter is only
used with the default `instructions` (as custom instructions provide
their own prompts for grades).

`model` list\[str \| [Model](inspect_ai.model.qmd#model)\] \| str \| [Model](inspect_ai.model.qmd#model) \| None  
Model or Models to use for grading. If multiple models are passed, a
majority vote of their grade will be returned. By default the model
being evaluated is used.

### multi_scorer

Returns a Scorer that runs multiple Scorers in parallel and aggregates
their results into a single Score using the provided reducer function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_multi.py#L13)

``` python
def multi_scorer(scorers: list[Scorer], reducer: str | ScoreReducer) -> Scorer
```

`scorers` list\[[Scorer](inspect_ai.scorer.qmd#scorer)\]  
a list of Scorers.

`reducer` str \| [ScoreReducer](inspect_ai.scorer.qmd#scorereducer)  
a function which takes in a list of Scores and returns a single Score.

## Metrics

### accuracy

Compute proportion of total answers which are correct.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metrics/accuracy.py#L14)

``` python
@metric
def accuracy(to_float: ValueToFloat = value_to_float()) -> Metric
```

`to_float` ValueToFloat  
Function for mapping `Value` to float for computing metrics. The default
`value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0,
PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to
float directly, and prints a warning and returns 0 if the Value is a
complex object (list or dict).

### mean

Compute mean of all scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metrics/mean.py#L6)

``` python
@metric
def mean() -> Metric
```

### std

Calculates the sample standard deviation of a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metrics/std.py#L137)

``` python
@metric
def std(to_float: ValueToFloat = value_to_float()) -> Metric
```

`to_float` ValueToFloat  
Function for mapping `Value` to float for computing metrics. The default
`value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0,
PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to
float directly, and prints a warning and returns 0 if the Value is a
complex object (list or dict).

### stderr

Standard error of the mean using Central Limit Theorem.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metrics/std.py#L50)

``` python
@metric
def stderr(
    to_float: ValueToFloat = value_to_float(), cluster: str | None = None
) -> Metric
```

`to_float` ValueToFloat  
Function for mapping `Value` to float for computing metrics. The default
`value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0,
PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to
float directly, and prints a warning and returns 0 if the Value is a
complex object (list or dict).

`cluster` str \| None  
The key from the Sample metadata corresponding to a cluster identifier
for computing [clustered standard
errors](https://en.wikipedia.org/wiki/Clustered_standard_errors).

### bootstrap_stderr

Standard error of the mean using bootstrap.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metrics/std.py#L17)

``` python
@metric
def bootstrap_stderr(
    num_samples: int = 1000, to_float: ValueToFloat = value_to_float()
) -> Metric
```

`num_samples` int  
Number of bootstrap samples to take.

`to_float` ValueToFloat  
Function for mapping Value to float for computing metrics. The default
`value_to_float()` maps CORRECT (“C”) to 1.0, INCORRECT (“I”) to 0,
PARTIAL (“P”) to 0.5, and NOANSWER (“N”) to 0, casts numeric values to
float directly, and prints a warning and returns 0 if the Value is a
complex object (list or dict).

## Reducers

### at_least

Score correct if there are at least k score values greater than or equal
to the value.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/reducer.py#L77)

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

Probability of at least 1 correct sample given `k` epochs
(<https://arxiv.org/pdf/2107.03374>).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/reducer.py#L109)

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

### max_score

Take the maximum value from a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/reducer.py#L144)

``` python
@score_reducer(name="max")
def max_score(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer
```

`value_to_float` ValueToFloat  
Function to convert the value to a float

### mean_score

Take the mean of a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/reducer.py#L39)

``` python
@score_reducer(name="mean")
def mean_score(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer
```

`value_to_float` ValueToFloat  
Function to convert the value to a float

### median_score

Take the median value from a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/reducer.py#L58)

``` python
@score_reducer(name="median")
def median_score(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer
```

`value_to_float` ValueToFloat  
Function to convert the value to a float

### mode_score

Take the mode from a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/reducer.py#L13)

``` python
@score_reducer(name="mode")
def mode_score() -> ScoreReducer
```

## Types

### Scorer

Score model outputs.

Evaluate the passed outputs and targets and return a dictionary with
scoring outcomes and context.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_scorer.py#L34)

``` python
class Scorer(Protocol):
    async def __call__(
        self,
        state: TaskState,
        target: Target,
    ) -> Score
```

`state` [TaskState](inspect_ai.solver.qmd#taskstate)  
Task state

`target` [Target](inspect_ai.scorer.qmd#target)  
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

Target is a sequence of one or more strings. Use the `text` property to
access the value as a single string.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_target.py#L4)

``` python
class Target(Sequence[str])
```

### Score

Score generated by a scorer.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L57)

``` python
class Score(BaseModel)
```

#### Attributes

`value` [Value](inspect_ai.scorer.qmd#value)  
Score value.

`answer` str \| None  
Answer extracted from model output (optional)

`explanation` str \| None  
Explanation of score (optional).

`metadata` dict\[str, Any\] \| None  
Additional metadata related to the score

`text` str  
Read the score as text.

#### Methods

as_str  
Read the score as a string.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L77)

``` python
def as_str(self) -> str
```

as_int  
Read the score as an integer.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L81)

``` python
def as_int(self) -> int
```

as_float  
Read the score as a float.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L85)

``` python
def as_float(self) -> float
```

as_bool  
Read the score as a boolean.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L89)

``` python
def as_bool(self) -> bool
```

as_list  
Read the score as a list.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L93)

``` python
def as_list(self) -> list[str | int | float | bool]
```

as_dict  
Read the score as a dictionary.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L100)

``` python
def as_dict(self) -> dict[str, str | int | float | bool | None]
```

### Value

Value provided by a score.

Use the methods of `Score` to easily treat the `Value` as a simple
scalar of various types.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L45)

``` python
Value = Union[
    str | int | float | bool,
    list[str | int | float | bool],
    dict[str, str | int | float | bool | None],
]
```

### ScoreReducer

Reduce a set of scores to a single score.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/types.py#L8)

``` python
class ScoreReducer(Protocol):
    def __call__(self, scores: list[Score]) -> Score
```

`scores` list\[[Score](inspect_ai.scorer.qmd#score)\]  
List of scores.

### Metric

Metric protocol.

The Metric signature changed in release v0.3.64. Both the previous and
new signatures are supported – you should use `MetricProtocol` for new
code as the depreacated signature will eventually be removed.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L230)

``` python
Metric = MetricProtocol | MetricDeprecated
```

### MetricProtocol

Compute a metric on a list of scores.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L209)

``` python
class MetricProtocol(Protocol):
    def __call__(self, scores: list[SampleScore]) -> Value
```

`scores` list\[[SampleScore](inspect_ai.scorer.qmd#samplescore)\]  
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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L114)

``` python
class SampleScore(BaseModel)
```

#### Attributes

`score` [Score](inspect_ai.scorer.qmd#score)  
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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L126)

``` python
def sample_metadata_as(self, metadata_cls: Type[MT]) -> MT | None
```

`metadata_cls` Type\[MT\]  
Pydantic model type

## Decorators

### scorer

Decorator for registering scorers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_scorer.py#L123)

``` python
def scorer(
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]],
    name: str | None = None,
    **metadata: Any,
) -> Callable[[Callable[P, Scorer]], Callable[P, Scorer]]
```

`metrics` list\[[Metric](inspect_ai.scorer.qmd#metric) \| dict\[str, list\[[Metric](inspect_ai.scorer.qmd#metric)\]\]\] \| dict\[str, list\[[Metric](inspect_ai.scorer.qmd#metric)\]\]  
One or more metrics to calculate over the scores.

`name` str \| None  
Optional name for scorer. If the decorator has no name argument then the
name of the underlying ScorerType object will be used to automatically
assign a name.

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_metric.py#L316)

``` python
def metric(
    name: str | Callable[P, Metric],
) -> Callable[[Callable[P, Metric]], Callable[P, Metric]] | Callable[P, Metric]
```

`name` str \| Callable\[P, [Metric](inspect_ai.scorer.qmd#metric)\]  
Optional name for metric. If the decorator has no name argument then the
name of the underlying MetricType will be used to automatically assign a
name.

#### Examples

\`\`\`python @metric def mean() -\> Metric: def metric(scores:
list\[SampleScore\]) -\> Value: return np.mean(\[score.score.as_float()
for score in scores\]).item() return metric

### score_reducer

Decorator for registering Score Reducers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0e09a1dd322c69c6beb64aaa961c6c876c19d0c7/src/inspect_ai/scorer/_reducer/registry.py#L37)

``` python
def score_reducer(
    func: ScoreReducerType | None = None, *, name: str | None = None
) -> Callable[[ScoreReducerType], ScoreReducerType] | ScoreReducerType
```

`func` ScoreReducerType \| None  
Function returning `ScoreReducer` targeted by plain task decorator
without attributes (e.g. `@score_reducer`)

`name` str \| None  
Optional name for reducer. If the decorator has no name argument then
the name of the function will be used to automatically assign a name.
