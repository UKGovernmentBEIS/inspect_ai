from typing import Dict

from inspect_ai.analysis._prepare.model_data.model_data import (
    ModelInfo,
    read_model_info,
)
from inspect_ai.analysis._prepare.operation import Operation


def model_info(
    model_info: Dict[str, ModelInfo] | None = None,
) -> Operation:
    """Amend data frame with model metadata.

    Fields added (when available) include:

    `model_organization_name`
    : Displayable model organization (e.g. OpenAI, Anthropic, etc.)

    `model_display_name`
    : Displayable model name (e.g. Gemini Flash 2.5)

    `model_snapshot`
    : A snapshot (version) string, if available (e.g. "latest" or "20240229")

    `model_release_date`
    : The model's release date

    `model_knowledge_cutoff_date`
    : The model's knowledge cutoff date

    Inspect includes built in support for many models (based upon the `model` string in the dataframe). If you are using models for which Inspect does not include model metadata, you may include your own model metadata via the `model_info` argument.

    Args:
        model_info: Additional model info for models not supported directly by Inspect's internal database.
    """
    import pandas as pd

    # Read built in model info
    builtin_model_info = read_model_info()

    # Merge with user provided model info
    resolved_model_info = builtin_model_info | (model_info or {})

    def transform(df: pd.DataFrame) -> pd.DataFrame:
        # Column mapping from DataFrame to ModelInfo field to read
        fields = {
            "model_organization_name": "organization",
            "model_display_name": "model",
            "model_snapshot": "snapshot",
            "model_release_date": "release_date",
            "model_knowledge_cutoff_date": "knowledge_cutoff_date",
        }

        # Set default values for all fields
        for field in fields.keys():
            if field == "model_display_name":
                df[field] = df["model"].astype(str)
            else:
                df[field] = None

        for idx in df.index:
            model = df.loc[idx, "model"]
            model_data = resolved_model_info.get(str(model))
            if model_data is not None:
                for df_field, model_field in fields.items():
                    value = getattr(model_data, model_field, None)
                    if value is not None:
                        df.loc[idx, df_field] = value

        return df

    return transform
