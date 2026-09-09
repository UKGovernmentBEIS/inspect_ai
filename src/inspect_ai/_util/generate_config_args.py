"""Building a `GenerateConfig` from the way a command line spells one.

`GenerateConfigArgs` is a typed mapping; the strings a person types at a shell
are not. Between the two sits a normalisation pass — `--stop-seqs` splits on
commas, `--cache 7` becomes a seven-day `CachePolicy`, `--batch` alone becomes
the default batch size, `--logit-bias` parses to a token map — and that pass is
what `config_from_locals` is.

**It lives here rather than in `_cli` because the CLI is no longer its only
caller.** `eval_set_env.resolve_eval_env` reads the same values from the
environment variables those options are bound to, and has to reach the same
answer: `INSPECT_EVAL_CACHE=7` means a seven-day policy there exactly as it
does on a command line. Reproducing the pass in `_eval` was tried and produced
a second parser that agreed with this one about two thirds of the time —
`cache` arriving as the string `"7"` and failing validation, `batch=true`
resolving to a size of one rather than the default. So the pass has one
implementation and two callers, and neither of them owns it.

A command's locals are still the common way in: `_cli/eval.py` imports
`config_from_locals` and hands it `dict(locals())`, which is why the signature
is a mapping of everything rather than a parameter per option.
"""

import json
from typing import Any

import click
import yaml
from pydantic import TypeAdapter

from inspect_ai._util.config import parse_cli_args, resolve_args
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import filesystem
from inspect_ai.model._cache import CachePolicy
from inspect_ai.model._generate_config import (
    BatchConfig,
    GenerateConfigArgs,
    ImageOutput,
    OutputModality,
    ResponseSchema,
)
from inspect_ai.util import AdaptiveConcurrency
from inspect_ai.util._resource import resource


def config_from_locals(locals: dict[str, Any]) -> GenerateConfigArgs:
    # start with config file if specified
    adapter = TypeAdapter(GenerateConfigArgs)
    run_config_file = locals.get("run_config")
    generate_config_file = locals.pop("generate_config", None)
    if run_config_file and generate_config_file:
        raise PrerequisiteError("--run-config cannot be used with --generate-config.")
    if generate_config_file:
        # read file
        generate_config = resolve_args(generate_config_file)

        # validate all the fields are valid
        extra_keys = generate_config.keys() - GenerateConfigArgs.__annotations__.keys()
        if extra_keys:
            raise PrerequisiteError(
                f"Unexpected GenerateConfig fields in {generate_config_file}: {extra_keys}"
            )

        # create base config
        base_config = adapter.validate_python(generate_config, strict=True)
    else:
        base_config = GenerateConfigArgs()

    # build generate config
    config_keys = list(GenerateConfigArgs.__mutable_keys__)  # type: ignore
    config = GenerateConfigArgs(**base_config)
    for key, value in locals.items():
        if key in config_keys and value is not None:
            if key == "stop_seqs":
                value = value.split(",")
            if key == "fallback_models":
                value = [m.strip() for m in value.split(",")]
            if key == "logprobs" and value is False:
                value = None
            if key == "logit_bias" and value is not None:
                value = parse_logit_bias(value)
            if key == "cache_prompt":
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
            if key == "parallel_tool_calls":
                if value is not False:
                    value = None
            if key == "internal_tools":
                if value is not False:
                    value = None
            if key == "response_schema":
                if value is not None:
                    value = ResponseSchema.model_validate_json(value)
            if key == "cache":
                match value:
                    case str():
                        policy = CachePolicy.from_string(value)
                        if policy is not None:
                            value = policy
                        else:
                            value = CachePolicy.model_validate(resolve_args(value))
                    case int():
                        value = CachePolicy(expiry=f"{value}D")

            if key == "batch":
                match value:
                    case str():
                        value = BatchConfig.model_validate(resolve_args(value))

            if key == "adaptive_connections" and isinstance(value, str):
                value = _parse_adaptive_connections_cli(value)

            if key == "modalities":
                value = parse_modalities(value)

            config[key] = value  # type: ignore
    return config


def parse_modalities(value: str) -> list[Any]:
    """Parse modalities from comma-separated names or YAML/JSON file."""
    # Check if it's a file path
    fs = filesystem(value)
    if fs.exists(value):
        content = resource(value, type="file")
        is_json = content.strip().startswith("[") or content.strip().startswith("{")
        config = json.loads(content) if is_json else yaml.safe_load(content)
        if not isinstance(config, list):
            raise PrerequisiteError(
                f"Modalities config file must contain a list, got: {type(config).__name__}"
            )
        result: list[OutputModality] = []
        for item in config:
            if isinstance(item, str):
                result.append(item)  # type: ignore[arg-type]
            elif isinstance(item, dict):
                result.append(ImageOutput.model_validate(item))
            else:
                raise PrerequisiteError(f"Invalid modality item: {item}")
        return result
    else:
        # Check if it looks like a file path that doesn't exist
        if "/" in value or "\\" in value or value.endswith((".json", ".yaml", ".yml")):
            raise PrerequisiteError(f"Modalities file not found: {value}")
        # Comma-separated literal names (e.g. "image" or "image,audio")
        tokens = [m.strip() for m in value.split(",")]
        return [t for t in tokens if t]  # type: ignore[misc]


def parse_logit_bias(logit_bias: str | None) -> dict[int, float] | None:
    logit_biases = parse_cli_args(logit_bias.split(",")) if logit_bias else None
    if logit_biases:
        return dict(
            zip([int(key) for key in logit_biases.keys()], logit_biases.values())
        )
    else:
        return None


def _parse_adaptive_connections_cli(
    value: str | None,
) -> bool | int | AdaptiveConcurrency | None:
    """Parse a CLI string into an adaptive_connections value.

    Accepts: None (passthrough), bool keywords ("true"/"yes" / "false"/"no",
    case-insensitive), a bare integer N (shorthand for
    `AdaptiveConcurrency(max=N)`), or a min-max / min-start-max shorthand
    like "4-80" / "4-20-80" delegated to AdaptiveConcurrency's parser.
    Raises `click.BadParameter` on invalid input so the CLI surfaces a
    clean usage message instead of a raw pydantic ValidationError.

    Note: `"1"`/`"0"` are treated as the integer-max shorthand, not as
    bool aliases. Users who want explicit on/off should pass `true`/`false`.
    """
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "yes"):
        return True
    if v in ("false", "no"):
        return False
    # Bare integer → max shorthand.
    if v.isdigit():
        return int(v)
    try:
        return AdaptiveConcurrency.model_validate(value)
    except Exception as ex:
        raise click.BadParameter(
            f"{value!r} is not a valid value. Expected `true`, `false`, an "
            f"integer max (e.g. `200`), or bounds shorthand like `4-80` "
            f"or `4-20-80`.",
            param_hint="--adaptive-connections",
        ) from ex
