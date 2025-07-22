from typing import Dict

import pandas as pd

from inspect_ai.analysis.beta._prepare.model_data.model_data import (
    ModelInfo,
    read_model_info,
)
from inspect_ai.analysis.beta._prepare.operation import Operation


def model_info(
    model_info: Dict[str, ModelInfo] | None = None,
) -> Operation:
    # Read built in model info
    builtin_model_info = read_model_info()

    # Merge with user provided model info
    resolved_model_info = builtin_model_info | (model_info or {})

    def transform(df: pd.DataFrame) -> pd.DataFrame:
        # Column mapping from DataFrame to ModelInfo field to read
        fields = {
            "model_organization_name": "organization_name",
            "model_display_name": "model_name",
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
