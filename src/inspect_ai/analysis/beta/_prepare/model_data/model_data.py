from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, ValidationError


class BaseModelDefinition(BaseModel):
    """Base model definition with common fields"""

    display_name: Optional[str] = None
    release_date: Optional[date] = None
    knowledge_cutoff_date: Optional[date] = None
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

    display_name: str
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


def create_model_info(
    family_name: str,
    model_name: str,
    family_short_name: str,
    model_def: BaseModelDefinition,
    version_data: Optional[BaseModelDefinition] = None,
) -> "ModelInfo":
    """Create a ModelInfo object, merging model and version data"""
    # Use version data if provided, otherwise use model data
    data_source = version_data if version_data is not None else model_def

    return ModelInfo(
        family=family_name,
        model=model_name,
        snapshot=data_source.snapshot,
        family_display_name=family_short_name,
        model_display_name=data_source.display_name or model_def.display_name,
        knowledge_cutoff_date=data_source.knowledge_cutoff_date
        or model_def.knowledge_cutoff_date,
        release_date=data_source.release_date or model_def.release_date,
        context_length=data_source.context_length or model_def.context_length,
        output_tokens=data_source.output_tokens or model_def.output_tokens,
        reasoning=data_source.reasoning or model_def.reasoning,
    )


class ModelInfo(BaseModel):
    """Model information and metadata"""

    family: str
    model: str
    snapshot: str | None = None

    family_display_name: str | None = None
    model_display_name: str | None = None

    knowledge_cutoff_date: date | None = None
    release_date: date | None = None

    context_length: float | None = None
    output_tokens: float | None = None

    reasoning: bool | None = None


def read_model_info() -> dict[str, ModelInfo]:
    """Load model information from YAML files in the current directory."""
    current_dir = Path(__file__).parent
    model_infos: dict[str, ModelInfo] = {}

    # YAML data files
    info_files = list(current_dir.glob("*.yml"))

    # Read each YAML file's model info
    for info_file in info_files:
        try:
            # Load and validate YAML
            families = load_families_from_yaml(info_file)

            for family_name, family_data in families.items():
                family_short_name = family_data.display_name

                for model_name, model_def in family_data.models.items():
                    # Create the base model
                    base_model = create_model_info(
                        family_name, model_name, family_short_name, model_def
                    )
                    model_infos[model_key(base_model)] = base_model

                    # Resolve model versions, if present
                    if model_def.versions:
                        for version_name, version_data in model_def.versions.items():
                            version_model = create_model_info(
                                family_name,
                                version_name,
                                family_short_name,
                                model_def,
                                version_data,
                            )
                            model_infos[model_key(version_model)] = version_model

                    # Resolve aliases for the base model
                    if model_def.aliases:
                        for alias in model_def.aliases:
                            alias_model = create_model_info(
                                family_name, alias, family_short_name, model_def
                            )
                            model_infos[model_key(alias_model)] = alias_model

                    # Resolve any aliases for each version
                    if model_def.versions:
                        for version_name, version_data in model_def.versions.items():
                            if version_data.aliases:
                                for alias in version_data.aliases:
                                    alias_version_model = create_model_info(
                                        family_name,
                                        alias,
                                        family_short_name,
                                        model_def,
                                        version_data,
                                    )
                                    model_infos[model_key(alias_version_model)] = (
                                        alias_version_model
                                    )

        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file {info_file}: {e}") from e
        except ValidationError as e:
            raise ValidationError(f"Validation error in {info_file}: {str(e)}") from e
        except (KeyError, TypeError) as e:
            raise type(e)(f"Data structure error in {info_file}: {e}") from e

    return model_infos


def model_key(model_info: ModelInfo) -> str:
    """Generate a unique key for the model based on its family and model name."""
    return f"{model_info.family}/{model_info.model}"
