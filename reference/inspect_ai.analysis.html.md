# inspect_ai.analysis.beta


## Evals

### evals_df

Read a dataframe containing evals.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/4579cef590a1aa7081f602acf24ee145c9429723/src/inspect_ai/analysis/beta/_dataframe/evals/table.py#L53)

``` python
def evals_df(
    logs: LogPaths,
    columns: Columns = EvalDefault,
    recursive: bool = True,
    reverse: bool = False,
    strict: bool = True,
) -> "pd.DataFrame" | tuple["pd.DataFrame", ColumnErrors]
```

`logs` LogPaths  
One or more paths to log files or log directories.

`columns` Columns  
Specification for what columns to read from the log file.

`recursive` bool  
Include recursive contents of directories (defaults to `True`)

`reverse` bool  
Reverse the order of the data frame (by default, items are ordered from
oldest to newest).

`strict` bool  
Raise import errors immediately. Defaults to `True`. If `False` then a
tuple of `DataFrame` and errors is returned.
