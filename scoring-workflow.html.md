# Scoring Workflow – Inspect

## Unscored Evals

By default, model output in evaluations is automatically scored. However, you can defer scoring by using the `--no-score` option. For example:

``` bash
inspect eval popularity.py --model openai/gpt-4 --no-score
```

This will produce a log with samples that have not yet been scored and with no evaluation metrics.

> **TIP:**
>
> Using a distinct scoring step is particularly useful during scorer development, as it bypasses the entire generation phase, saving lots of time and inference costs.

## Score Command

You can score an evaluation previously run this way using the `inspect score` command:

``` bash
# score an unscored eval
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval
```

This will use the scorers and metrics that were declared when the evaluation was run, applying them to score each sample and generate metrics for the evaluation.

You may choose to use a different scorer than the task scorer to score a log file. In this case, you can use the `--scorer` option to pass the name of a scorer (including one in a package) or the path to a source code file containing a scorer to use. For example:

``` bash
# use built in match scorer
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --scorer match

# use scorer in a package
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --scorer scorertools/custom_scorer

# use scorer in a file
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --scorer custom_scorer.py

# use a custom scorer named 'classify' in a file with more than one scorer
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --scorer custom_scorers.py@classify
```

If you need to pass arguments to the scorer, you can do do using scorer args (`-S`) like so:

``` bash
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --scorer match -S location=end
```

### Overwriting Logs

When you use the `inspect score` command, you will prompted whether or not you’d like to overwrite the existing log file (with the scores added), or create a new scored log file. By default, the command will create a new log file with a `-scored` suffix to distinguish it from the original file. You may also control this using the `--overwrite` flag as follows:

``` bash
# overwrite the log with scores from the task defined scorer
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --overwrite
```

### Overwriting Scores

When rescoring a previously scored log file you have two options:

1.  Append Mode (Default): The new scores will be added alongside the existing scores in the log file, keeping both the old and new results.
2.  Overwrite Mode: The new scores will replace the existing scores in the log file, removing the old results.

You can choose which mode to use based on whether you want to preserve or discard the previous scoring data.

> **NOTE:**
>
> When using append mode, the new scorer uses its own metrics independently; the original eval’s metric configuration is not applied to the appended scorer. This means append works even when the original eval used metrics from packages that are not available in the current environment.

To control this, use the `--action` arg:

``` bash
# append scores from custom scorer
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --scorer custom_scorer.py --action append

# overwrite scores with new scores from custom scorer
inspect score ./logs/2024-02-23_task_gpt-4_TUhnCn473c6.eval --scorer custom_scorer.py --action overwrite
```

## Score Function

You can also use the [score()](./reference/inspect_ai.scorer.html.md#score) function in your Python code to score evaluation logs. For example, if you are exploring the performance of different scorers, you might find it more useful to call the [score()](./reference/inspect_ai.scorer.html.md#score) function using varying scorers or scorer options. For example:

``` python
log = eval(popularity, model="openai/gpt-4")[0]

grader_models = [
    "openai/gpt-4",
    "anthropic/claude-3-opus-20240229",
    "google/gemini-2.5-pro",
    "mistral/mistral-large-latest"
]

scoring_logs = [score(log, model_graded_qa(model=model))
                for model in grader_models]

plot_results(scoring_logs)
```

You can also use this function to score an existing log file (appending or overwriting results) like so:

``` python
# read the log
input_log_path = "./logs/2025-02-11T15-17-00-05-00_popularity_dPiJifoWeEQBrfWsAopzWr.eval"
log = read_eval_log(input_log_path)

grader_models = [
    "openai/gpt-4",
    "anthropic/claude-3-opus-20240229",
    "google/gemini-2.5-pro",
    "mistral/mistral-large-latest"
]

# perform the scoring using various models
scoring_logs = [score(log, model_graded_qa(model=model), action="append")
                for model in grader_models]

# write log files with the model name as a suffix
for model, scored_log in zip(grader_models, scoring_logs):
    base, ext = os.path.splitext(input_log_path)
    output_file = f"{base}_{model.replace('/', '_')}{ext}"
    write_eval_log(scored_log, output_file)
```

## Editing Scores

You may need to modify the results, for example correcting scoring errors or adjusting sample scores based on manual review. Inspect provides functions for modifying logs while maintaining data integrity and audit trails. Learn more about modifying scores in [Editing Logs](./eval-logs.html.md#sec-eval-log-modification).
