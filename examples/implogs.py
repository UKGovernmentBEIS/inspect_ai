from inspect_ai.analysis import EvalDefault, evals_df
from inspect_ai.analysis._df.types import Column, Columns

ErrorSpecs: Columns = {"run_id": Column("eval.runid", required=True)}

df = evals_df("logs", columns=EvalDefault)
df = df[
    [
        "eval_id",
        "tags",
        "score_headline_name",
        "score_headline_metric",
        "score_headline_value",
    ]
]
print(df)
