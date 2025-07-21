from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, ValidationError


class BaseModelDefinition(BaseModel):
    """Base model definition with common fields"""

    short_name: str
    release_date: Optional[str] = None
    knowledge_cutoff_date: Optional[str] = None
    context_length: Optional[float] = None
    output_tokens: Optional[float] = None
    reasoning: Optional[bool] = None
    snapshot: Optional[str] = None
    aliases: Optional[List[str]] = None


class ModelDefinition(BaseModelDefinition):
    """Model definition from YAML with optional versions"""

    versions: Optional[Dict[str, BaseModelDefinition]] = None


class FamilyData(BaseModel):
    """Family data from YAML"""

    short_name: str
    models: Dict[str, ModelDefinition]


def load_families_from_yaml(file_path: Path) -> Dict[str, FamilyData]:
    """Load and validate family data from a YAML file"""
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)

    if not data:
        return {}

    # Validate each family in the YAML file
    result = {}
    for family_name, family_data_dict in data.items():
        result[family_name] = FamilyData.model_validate(family_data_dict)

    return result


class ModelInfo(BaseModel):
    """Model information and metadata"""

    family: str
    model: str
    snapshot: str | None = None

    family_short_name: str | None = None
    model_short_name: str | None = None

    knowledge_cutoff_date: str | None = None
    release_date: str | None = None

    context_length: float | None = None
    output_tokens: float | None = None

    reasoning: bool | None = None


def read_model_info() -> list[ModelInfo]:
    """Load model information from YAML files in the current directory."""
    current_dir = Path(__file__).parent
    model_infos: list[ModelInfo] = []

    # YAML data files
    info_files = list(current_dir.glob("*.yml"))

    # Read each YAML file's model info
    for info_file in info_files:
        try:
            # Load and validate YAML data using Pydantic
            families = load_families_from_yaml(info_file)

            for family_name, family_data in families.items():
                family_short_name = family_data.short_name

                for model_name, model_def in family_data.models.items():
                    # Handle models with direct snapshot (no versions)
                    if model_def.snapshot is not None:
                        model_info_obj = ModelInfo(
                            family=family_name,
                            model=model_name,
                            snapshot=model_def.snapshot,
                            family_short_name=family_short_name,
                            model_short_name=model_def.short_name,
                            knowledge_cutoff_date=model_def.knowledge_cutoff_date,
                            release_date=model_def.release_date,
                            context_length=model_def.context_length,
                            output_tokens=model_def.output_tokens,
                            reasoning=model_def.reasoning,
                        )
                        model_infos.append(model_info_obj)

                        # Handle aliases at model level
                        if model_def.aliases:
                            for alias in model_def.aliases:
                                alias_model_info = ModelInfo(
                                    family=family_name,
                                    model=alias,
                                    snapshot=model_def.snapshot,
                                    family_short_name=family_short_name,
                                    model_short_name=model_def.short_name,
                                    knowledge_cutoff_date=model_def.knowledge_cutoff_date,
                                    release_date=model_def.release_date,
                                    context_length=model_def.context_length,
                                    output_tokens=model_def.output_tokens,
                                    reasoning=model_def.reasoning,
                                )
                                model_infos.append(alias_model_info)

                    # Handle models with versions
                    if model_def.versions:
                        for version_name, version_data in model_def.versions.items():
                            # Merge parent values with version-specific values
                            model_info_obj = ModelInfo(
                                family=family_name,
                                model=version_name,
                                family_short_name=family_short_name,
                                model_short_name=version_data.short_name
                                or model_def.short_name,
                                knowledge_cutoff_date=version_data.knowledge_cutoff_date
                                or model_def.knowledge_cutoff_date,
                                release_date=version_data.release_date
                                or model_def.release_date,
                                context_length=version_data.context_length
                                or model_def.context_length,
                                output_tokens=version_data.output_tokens
                                or model_def.output_tokens,
                                reasoning=version_data.reasoning or model_def.reasoning,
                                snapshot=version_data.snapshot,
                            )
                            model_infos.append(model_info_obj)

                            # Handle aliases at version level
                            if version_data.aliases:
                                for alias in version_data.aliases:
                                    alias_model_info = ModelInfo(
                                        family=family_name,
                                        model=alias,
                                        family_short_name=family_short_name,
                                        model_short_name=version_data.short_name
                                        or model_def.short_name,
                                        knowledge_cutoff_date=version_data.knowledge_cutoff_date
                                        or model_def.knowledge_cutoff_date,
                                        release_date=version_data.release_date
                                        or model_def.release_date,
                                        context_length=version_data.context_length
                                        or model_def.context_length,
                                        output_tokens=version_data.output_tokens
                                        or model_def.output_tokens,
                                        reasoning=version_data.reasoning
                                        or model_def.reasoning,
                                        snapshot=version_data.snapshot,
                                    )
                                    model_infos.append(alias_model_info)

        except (yaml.YAMLError, ValidationError, KeyError, TypeError):
            # Skip files that can't be parsed or validated
            continue

    return model_infos
