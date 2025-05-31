from inspect_ai.analysis.beta import evals_df, samples_df
import json
import pandas as pd
from inspect_ai.analysis.beta import (
    EvalInfo,
    evals_df,
    SampleMessages,
    SampleSummary,
    EvalResults,
)

eval_path_reasoning = (
    "/home/ubuntu/logs/2025-05-31T08-15-11+00-00_gsm8k_fo8NmNdxgKbbREkbmfpi7E.eval"
)

eval_path = (
    "/home/ubuntu/logs/2025-05-31T09-18-52+00-00_gsm8k_fVaXTW6JpU7Y994JuEbnKa.eval"
)

df_non_reasoning = samples_df(
    eval_path, columns=EvalInfo + SampleMessages + SampleSummary + EvalResults
)
df_non_reasoning = df_non_reasoning.loc[
    :, ["score_match", "id", "sample_id", "model_usage", "input"]
]

df_non_reasoning["model_usage"] = df_non_reasoning["model_usage"].apply(
    lambda x: list(json.loads(x).keys())[0]
)

df_reasoning = samples_df(
    eval_path_reasoning, columns=SampleMessages + SampleSummary + EvalInfo + EvalResults
)
df_reasoning = df_reasoning.loc[
    :, ["score_match", "input", "id", "sample_id", "model_usage"]
]

df_reasoning["model_usage"] = df_reasoning["model_usage"].apply(
    lambda x: list(json.loads(x).keys())[0]
)

df = pd.merge(df_reasoning, df_non_reasoning, on=["id"], how="inner")

# Keep input_x and drop input_y since they should be the same
df["input"] = df["input_x"]
df = df.drop(["input_x", "input_y"], axis=1)


df.to_csv("gsm8k_reasoning_non_reasoning.csv", index=False)

dataset_df = df.loc[:, ["input", "score_match_x", "score_match_y", "id"]]

# Rename columns
dataset_df.rename(
    columns={
        "score_match_x": "score_match_reasoning",
        "score_match_y": "score_match_non_reasoning",
        "input": "query",
    },
    inplace=True,
)


# Split into train and test
train_df = dataset_df.sample(frac=0.8, random_state=42)
test_df = dataset_df.drop(train_df.index)

train_df.to_csv("gsm8k_reasoning_non_reasoning_train.csv", index=False)
test_df.to_csv("gsm8k_reasoning_non_reasoning_test.csv", index=False)
