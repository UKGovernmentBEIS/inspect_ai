from inspect_ai.analysis.beta import SampleColumn, evals_df, samples_df
from inspect_ai.analysis.beta._dataframe.samples.columns import (
    SampleMessages,
    SampleSummary,
)

# df = samples_df(
#     "logs",
#     columns=SampleMessages  # noqa: F821
#     + [
#         SampleColumn("epoch", path="epoch"),
#         # SampleColumn("epoch", path="epoch", full=True),
#     ],
# )
# print(df.head())


# import duckdb

# from inspect_ai.analysis.beta import SampleColumn, evals_df, samples_df
# from inspect_ai.analysis.beta._dataframe.samples.columns import SampleSummary

# con = duckdb.connect()
# con.register("evals", evals_df("logs"))
# con.register("samples", samples_df("logs"))

# result = con.execute("""
#     SELECT *
#     FROM evals e
#     JOIN samples s ON e.eval_id = s.eval_id
#     WHERE e.model LIKE 'google/%'
# """).fetchdf()

# print(result)


from inspect_ai.analysis.beta import messages_df

df = messages_df("logs", filter=["tool"])
df.info()
