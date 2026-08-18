import re
from inspect import isgenerator
from typing import Any, Iterator

from pydantic import BaseModel, Field

from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import Model, get_model


class ModelConfig(BaseModel):
    """Model config."""

    model: str
    """Model name."""

    config: GenerateConfig = Field(default_factory=GenerateConfig)
    """Generate config"""

    base_url: str | None = Field(default=None)
    """Model base url."""

    args: dict[str, Any] = Field(default_factory=dict)
    """Model specific arguments."""


# A role bound to a list of models is stored in the log's flat
# dict[str, ModelConfig] as indexed keys: the first model under the bare role
# name and subsequent models under 'name#2', 'name#3', etc. This keeps the
# EvalSpec schema (and therefore the log viewer types) unchanged while
# round-tripping lists losslessly for eval_retry/score. resolve_model_roles()
# rejects user role names matching this pattern so the encoding is unambiguous.
INDEXED_ROLE_KEY_PATTERN = re.compile(r"(.+)#(\d+)$")


def model_roles_to_model_roles_config(
    model_roles: dict[str, Model | list[Model]] | None,
) -> dict[str, ModelConfig] | None:
    if model_roles is not None:
        config: dict[str, ModelConfig] = {}
        for k, v in model_roles.items():
            if isinstance(v, list):
                for i, model in enumerate(v):
                    config[k if i == 0 else f"{k}#{i + 1}"] = model_to_model_config(
                        model
                    )
            else:
                config[k] = model_to_model_config(v)
        return config
    else:
        return None


def model_roles_config_grouped(
    model_config: dict[str, ModelConfig],
) -> dict[str, ModelConfig | list[ModelConfig]]:
    """Regroup indexed keys ('name#N') under their base role name in N order.

    An indexed key is only treated as a list member when its base role name is
    also present (the encoder always writes the first model under the bare
    name), so a log written before the reserved suffix existed with a role
    literally named e.g. 'judge#2' -- but no 'judge' -- is left untouched.
    """
    indexed: dict[str, list[tuple[int, ModelConfig]]] = {}
    for k, v in model_config.items():
        match = INDEXED_ROLE_KEY_PATTERN.match(k)
        if match and match.group(1) in model_config:
            indexed.setdefault(match.group(1), []).append((int(match.group(2)), v))
        else:
            indexed.setdefault(k, []).append((1, v))
    grouped: dict[str, ModelConfig | list[ModelConfig]] = {}
    for k, entries in indexed.items():
        configs = [mc for _, mc in sorted(entries, key=lambda e: e[0])]
        grouped[k] = configs if len(configs) > 1 else configs[0]
    return grouped


def model_roles_config_to_model_roles(
    model_config: dict[str, ModelConfig] | None,
) -> dict[str, Model | list[Model]] | None:
    if model_config is not None:
        return {
            k: [model_config_to_model(mc) for mc in v]
            if isinstance(v, list)
            else model_config_to_model(v)
            for k, v in model_roles_config_grouped(model_config).items()
        }
    else:
        return None


def model_to_model_config(model: Model) -> ModelConfig:
    return ModelConfig(
        model=str(model),
        config=model.config,
        base_url=model.api.base_url,
        args=model_args_for_log(model.model_args),
    )


def model_config_to_model(model_config: ModelConfig) -> Model:
    return get_model(
        model=model_config.model,
        config=model_config.config,
        base_url=model_config.base_url,
        memoize=False,
        **model_config.args,
    )


def model_args_for_log(model_args: dict[str, Any]) -> dict[str, Any]:
    # redact authentication oriented model_args
    model_args = model_args.copy()
    if "api_key" in model_args:
        del model_args["api_key"]
    model_args = {k: v for k, v in model_args.items() if not k.startswith("aws_")}

    # don't try to serialise generators
    model_args = {
        k: v
        for k, v in model_args.items()
        if not isgenerator(v) and not isinstance(v, Iterator)
    }
    return model_args
