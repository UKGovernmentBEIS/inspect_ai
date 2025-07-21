from inspect_ai.analysis.beta import evals_df, model_info, prepare
from inspect_ai.analysis.beta._prepare.model_info import ModelInfo

data = {
    "mockllm/model": ModelInfo(
        family="gpt-4",
        model="gpt-4",
        model_display_name="GPT-4",
        version="2023-03-14",
        release_date="2023-03-14",
    )
}

df = evals_df("logs")
print(df[["model"]].head())
df = prepare(df, [model_info(data)])

print(df[["model_short_name"]].head())
