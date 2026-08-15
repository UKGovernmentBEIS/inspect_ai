import base64
import json
import os
from typing import Sequence, cast

from pydantic import JsonValue

from ._model_call import ModelCall, _walk_json_value

MODEL_ALIASES_ENV_VAR = "INSPECT_MODEL_ALIASES"
"""Environment variable with comma-separated model alias pairs."""


def parse_model_aliases(aliases: Sequence[str] | None) -> dict[str, str]:
    """Parse model aliases from CLI or environment variable values.

    Each value holds one or more comma-separated `alias=model` pairs
    (e.g. "safe/name=openai/gpt-4o"). Both the alias and the model it
    resolves to must be fully qualified (i.e. include a provider prefix).

    Args:
        aliases: Values to parse.

    Returns:
        Dictionary mapping aliases to the models they resolve to.

    Raises:
        ValueError: A value is not a valid alias pair, an alias or its
            model is not fully qualified, or an alias is defined twice
            with different models.
    """
    parsed: dict[str, str] = {}
    for value in aliases or []:
        for pair in value.split(","):
            pair = pair.strip()
            if not pair:
                continue
            alias, sep, model = pair.partition("=")
            alias = alias.strip()
            model = model.strip()
            if not sep or not alias or not model:
                raise ValueError(
                    f"Invalid model alias {pair!r} (should be in the format of "
                    + "<alias>=<model>, e.g. safe/name=openai/gpt-4o)."
                )
            for name in (alias, model):
                api_name, _, model_name = name.partition("/")
                if not api_name or not model_name:
                    raise ValueError(
                        f"Invalid model alias {pair!r} ({name!r} should be in "
                        + "the format of <api_name>/<model_name>)."
                    )
            if alias in parsed and parsed[alias] != model:
                raise ValueError(
                    f"Model alias {alias!r} is defined more than once "
                    + f"(as {parsed[alias]!r} and {model!r})."
                )
            parsed[alias] = model
    return parsed


def init_model_aliases(aliases: dict[str, str] | None) -> None:
    """Initialize model aliases for the current process.

    Args:
        aliases: Aliases to resolve in `get_model()` (pass `None` to
            restore the default behavior of reading aliases from the
            `INSPECT_MODEL_ALIASES` environment variable).
    """
    global _model_aliases
    _model_aliases = aliases


def model_aliases() -> dict[str, str]:
    """Active model aliases.

    Aliases explicitly initialized via `init_model_aliases()`, or otherwise
    read from the `INSPECT_MODEL_ALIASES` environment variable.
    """
    if _model_aliases is not None:
        return _model_aliases
    env_aliases = os.environ.get(MODEL_ALIASES_ENV_VAR, None)
    if env_aliases:
        return parse_model_aliases([env_aliases])
    return {}


def resolve_model_alias(model: str) -> str | None:
    """Model that `model` is an alias for (`None` if it is not an alias)."""
    return model_aliases().get(model, None)


def model_aliases_for_log() -> str | None:
    """Active model aliases encoded for the eval log.

    The alias mapping is base64-encoded so that the real models behind
    aliases are not stored in plaintext in the log (the mapping remains
    recoverable with `model_aliases_from_log()`).

    Returns:
        Encoded alias mapping (`None` if there are no active aliases).
    """
    aliases = model_aliases()
    if aliases:
        return base64.b64encode(json.dumps(aliases).encode()).decode("ascii")
    else:
        return None


def model_aliases_from_log(encoded: str) -> dict[str, str]:
    """Decode a model alias mapping recorded in an eval log.

    Args:
        encoded: Encoded alias mapping (i.e. the `model_aliases`
            field of an eval log header).

    Returns:
        Dictionary mapping aliases to the models they resolve to.
    """
    aliases = json.loads(base64.b64decode(encoded.encode("ascii")).decode())
    if not isinstance(aliases, dict):
        raise ValueError("Invalid model aliases encoding.")
    return {str(k): str(v) for k, v in aliases.items()}


def redact_aliased_model(text: str, alias: str, model: str) -> str:
    """Replace occurrences of an aliased model's real name with the alias.

    Args:
        text: Text to redact.
        alias: Model alias (e.g. "safe/name").
        model: Real model the alias resolves to (e.g. "openai/gpt-4o").

    Returns:
        Text with occurrences of the real model name replaced by the alias.
    """
    text = text.replace(model, alias)
    model_name = model.partition("/")[2]
    alias_name = alias.partition("/")[2]
    if model_name and alias_name:
        text = text.replace(model_name, alias_name)
    return text


def redact_aliased_model_call(call: ModelCall, alias: str, model: str) -> None:
    """Replace an aliased model's real name in raw model call data.

    Args:
        call: Model call to redact (modified in place).
        alias: Model alias (e.g. "safe/name").
        model: Real model the alias resolves to (e.g. "openai/gpt-4o").
    """

    def redact(key: JsonValue | None, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return redact_aliased_model(value, alias, model)
        else:
            return value

    call.request = cast(
        dict[str, JsonValue], _walk_json_value(None, call.request, redact)
    )
    if call.response is not None:
        call.response = cast(
            dict[str, JsonValue], _walk_json_value(None, call.response, redact)
        )


_model_aliases: dict[str, str] | None = None
