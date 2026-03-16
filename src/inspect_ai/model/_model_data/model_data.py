from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, PrivateAttr, ValidationError

from inspect_ai._util.dateutil import UtcDate


class ModelCost(BaseModel):
    """Model cost in $/million tokens."""

    input: float
    """Price per million input tokens."""

    output: float
    """Price per million output tokens."""

    input_cache_write: float
    """Price per million input tokens written to cache."""

    input_cache_read: float
    """Price per million input tokens read from cache."""


class BaseModelDefinition(BaseModel):
    """Base model definition with common fields"""

    display_name: Optional[str] = None
    release_date: Optional[UtcDate] = None
    knowledge_cutoff_date: Optional[UtcDate] = None
    context_length: Optional[int] = None
    output_tokens: Optional[int] = None
    input_tokens: Optional[int] = None
    reasoning: Optional[bool] = None
    snapshot: Optional[str] = None
    aliases: Optional[List[str]] = None


class ModelDefinition(BaseModelDefinition):
    """Model definition from YAML with optional versions"""

    versions: Optional[Dict[str, BaseModelDefinition]] = None


class OrganizationData(BaseModel):
    """Organization data from YAML"""

    display_name: str
    models: Dict[str, ModelDefinition]


def load_organizations_from_yaml(file_path: Path) -> Dict[str, OrganizationData]:
    """Load and validate organization data from a YAML file"""
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)

    if not data:
        return {}

    # Validate each organization in the YAML file
    result = {}
    for organization, organization_data in data.items():
        result[organization] = OrganizationData.model_validate(organization_data)

    return result


def create_model_info(
    organization_name: str,
    model_def: BaseModelDefinition,
    version_data: Optional[BaseModelDefinition] = None,
) -> "ModelInfo":
    """Create a ModelInfo object, merging model and version data"""
    # Use version data if provided, otherwise use model data
    data_source = version_data if version_data is not None else model_def

    return ModelInfo(
        snapshot=data_source.snapshot,
        organization=organization_name,
        model=data_source.display_name or model_def.display_name,
        knowledge_cutoff_date=data_source.knowledge_cutoff_date
        or model_def.knowledge_cutoff_date,
        release_date=data_source.release_date or model_def.release_date,
        context_length=data_source.context_length or model_def.context_length,
        output_tokens=data_source.output_tokens or model_def.output_tokens,
        _input_tokens=data_source.input_tokens or model_def.input_tokens,
        reasoning=data_source.reasoning or model_def.reasoning,
    )


class ModelInfo(BaseModel):
    """Model information and metadata"""

    organization: str | None = Field(default=None)
    """Model organization (e.g. Anthropic, OpenAI)."""

    model: str | None = Field(default=None)
    """Model name (e.g. Gemini 2.5 Flash)."""

    snapshot: str | None = Field(default=None)
    """A snapshot (version) string, if available (e.g. "latest" or "20240229")."""

    release_date: UtcDate | None = Field(default=None)
    """The mode's release date."""

    knowledge_cutoff_date: UtcDate | None = Field(default=None)
    """The model's knowledge cutoff date."""

    context_length: int | None = Field(default=None)
    """The model's context length in tokens."""

    output_tokens: int | None = Field(default=None)
    """"The model's maximum output tokens."""

    reasoning: bool | None = Field(default=None)
    """Is this a reasoning model."""

    cost: ModelCost | None = Field(default=None)
    """Cost per million tokens for this model."""

    _input_tokens: int | None = PrivateAttr(default=None)
    """Private attribute for explicit input_tokens override from YAML."""

    def __init__(self, _input_tokens: int | None = None, **data: object) -> None:
        super().__init__(**data)
        self._input_tokens = _input_tokens

    @property
    def input_tokens(self) -> int | None:
        """Effective input capacity in tokens.

        Returns the explicit input_tokens value if set in model data,
        otherwise falls back to context_length.

        This provides a single property callers can use without needing
        to know about context_length vs input capacity differences.
        """
        if self._input_tokens is not None:
            return self._input_tokens
        return self.context_length


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
            organizations = load_organizations_from_yaml(info_file)

            for organization, organization_data in organizations.items():
                organization_name = organization_data.display_name

                for model_name, model_def in organization_data.models.items():
                    # Create the base model
                    base_model = create_model_info(organization_name, model_def)
                    model_infos[model_key(organization, model=model_name)] = base_model

                    # Resolve model versions, if present
                    if model_def.versions:
                        for version_name, version_data in model_def.versions.items():
                            version_model = create_model_info(
                                organization_name,
                                model_def,
                                version_data,
                            )
                            model_infos[model_key(organization, model=version_name)] = (
                                version_model
                            )

                    # Resolve aliases for the base model
                    if model_def.aliases:
                        for alias in model_def.aliases:
                            alias_model = create_model_info(
                                organization_name, model_def
                            )
                            model_infos[model_key(organization, model=alias)] = (
                                alias_model
                            )

                    # Resolve any aliases for each version
                    if model_def.versions:
                        for version_name, version_data in model_def.versions.items():
                            if version_data.aliases:
                                for alias in version_data.aliases:
                                    alias_version_model = create_model_info(
                                        organization_name,
                                        model_def,
                                        version_data,
                                    )
                                    model_infos[
                                        model_key(organization, model=alias)
                                    ] = alias_version_model

        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML file {info_file}: {e}") from e
        except ValidationError as e:
            raise ValidationError(f"Validation error in {info_file}: {str(e)}") from e
        except (KeyError, TypeError) as e:
            raise type(e)(f"Data structure error in {info_file}: {e}") from e

    return model_infos


def model_key(organization: str, model: str) -> str:
    """Generate a unique key for the model based on its organization and model name."""
    return f"{organization}/{model}"
