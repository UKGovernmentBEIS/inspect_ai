# Scoring – Inspect

Scoring turns the raw `output` a model produces for each sample into a [Score](./reference/inspect_ai.scorer.html.md#score), and aggregates those scores into the metrics that summarise an evaluation. The scoring system is documented across the following articles:

| Article | Description |
|----|----|
| [Standard Scorers](./standard-scorers.html.md) | The built-in scorers (text matching, multiple choice, math, model grading, perplexity) and how to choose among them. |
| [Custom Scorers](./custom-scorers.html.md) | Write your own scorers using the [Score](./reference/inspect_ai.scorer.html.md#score), [Value](./reference/inspect_ai.scorer.html.md#value), and [Target](./reference/inspect_ai.scorer.html.md#target) types, including scorers that call models or inspect a sandbox. |
| [Model Grading](./model-graded.html.md) | Use another model to grade open-ended answers; customise templates, instructions, grader models, and chat history. |
| [Scoring Metrics](./metrics.html.md) | Built-in metrics, grouping, clustered standard errors, custom metrics, and reducing epochs. |
| [Multiple Scorers](./multiple-scorers.html.md) | Use several scorers together, emit multiple scores from one scorer, and reduce multiple scores into one. |
| [Scoring Workflow](./scoring-workflow.html.md) | Defer scoring with `--no-score`, re-score logs with `inspect score`, and edit scores. |
| [Perplexity](./perplexity.html.md) | Score how well a model predicts text using prompt log probabilities. |

To review transcripts for issues that could undermine results (refusals, evaluation awareness, environment misconfiguration) rather than grading task success, see [Scanners](./scanners.html.md). To customise how scores render in the log viewer, see [Task Views](./task-views.html.md).
