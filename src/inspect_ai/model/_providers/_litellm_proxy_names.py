"""Map LiteLLM model strings to candidate keys in Inspect's model database.

A LiteLLM deployment names its upstream model as `<provider>/<native id>`,
where only the first segment is LiteLLM's provider and the native id can hold
route segments, regions, versions and further slashes (see "Name forms" in
`design/litellm-proxy.md`). `database_candidates()` turns such a string into
an ordered list of Inspect database keys (`org/model`) to try with an exact or
case-insensitive lookup. It never guesses beyond these rewrites: a fuzzy match
often picks a different model (`gpt-5-pro` for `gpt-5`).
"""

import re
from logging import getLogger
from typing import Iterable, NamedTuple

from inspect_ai._util.logger import warn_once

from .._model_info import _strict_db_key
from ._litellm_proxy_model_info import ProxyDeployment

logger = getLogger(__name__)

# LiteLLM providers whose names can lead a model string (from LiteLLM's
# `LlmProviders`, chat-capable ones). A first segment outside this set is
# read as an `org/model` path (e.g. an Inspect or Hugging Face style
# `base_model`).
LITELLM_PROVIDERS = frozenset(
    {
        "ai21",
        "ai21_chat",
        "aiml",
        "anthropic",
        "anthropic_text",
        "azure",
        "azure_ai",
        "azure_text",
        "baseten",
        "bedrock",
        "bedrock_converse",
        "bedrock_mantle",
        "cerebras",
        "chatgpt",
        "chutes",
        "cloudflare",
        "codestral",
        "cohere",
        "cohere_chat",
        "custom_openai",
        "dashscope",
        "databricks",
        "deepinfra",
        "deepseek",
        "featherless_ai",
        "fireworks_ai",
        "friendliai",
        "gemini",
        "github",
        "github_copilot",
        "groq",
        "hosted_vllm",
        "huggingface",
        "hyperbolic",
        "lambda_ai",
        "litellm_proxy",
        "lm_studio",
        "meta_llama",
        "minimax",
        "mistral",
        "moonshot",
        "nebius",
        "novita",
        "nscale",
        "nvidia_nim",
        "oci",
        "ollama",
        "ollama_chat",
        "openai",
        "openai_like",
        "openrouter",
        "parasail",
        "perplexity",
        "sambanova",
        "sagemaker",
        "sagemaker_chat",
        "snowflake",
        "text-completion-openai",
        "together_ai",
        "vercel_ai_gateway",
        "vertex_ai",
        "vertex_ai_beta",
        "vllm",
        "volcengine",
        "wandb",
        "watsonx",
        "xai",
        "zai",
    }
)

PROVIDER_ALIASES = {
    "vertex_ai_beta": "vertex_ai",
    "bedrock_converse": "bedrock",
    "azure_text": "azure",
    "text-completion-openai": "openai",
    "anthropic_text": "anthropic",
    "cohere_chat": "cohere",
    "ollama_chat": "ollama",
}

# Inspect database organizations for the model families a provider serves
# under bare ids (e.g. `anthropic/claude-sonnet-4-5`).
PROVIDER_ORGS: dict[str, tuple[str, ...]] = {
    "openai": ("openai",),
    "azure": ("openai",),
    "chatgpt": ("openai",),
    "anthropic": ("anthropic",),
    "gemini": ("google",),
    "xai": ("grok",),
    "mistral": ("mistral", "mistralai"),
    "codestral": ("mistral", "mistralai"),
    "deepseek": ("DeepSeek", "deepseek-ai"),
    "moonshot": ("moonshotai",),
    "zai": ("z-ai", "zai-org"),
    "minimax": ("MiniMaxAI", "minimax"),
    "meta_llama": ("meta-llama",),
    "dashscope": ("Qwen",),
}

# Inspect database organizations for a vendor prefix: Bedrock and OCI
# `vendor.model` ids and aggregator `vendor/model` paths.
VENDOR_ORGS: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic",),
    "openai": ("openai",),
    "google": ("google",),
    "x-ai": ("grok",),
    "xai": ("grok",),
    "meta": ("meta-llama", "meta"),
    "meta-llama": ("meta-llama",),
    "mistral": ("mistral", "mistralai"),
    "mistralai": ("mistralai", "mistral"),
    "deepseek": ("DeepSeek", "deepseek-ai"),
    "deepseek-ai": ("deepseek-ai", "DeepSeek"),
    "qwen": ("Qwen",),
    "moonshot": ("moonshotai",),
    "moonshotai": ("moonshotai",),
    "zai": ("z-ai", "zai-org"),
    "z-ai": ("z-ai", "zai-org"),
    "zai-org": ("zai-org", "z-ai"),
    "minimax": ("MiniMaxAI", "minimax"),
    "minimaxai": ("MiniMaxAI", "minimax"),
    "nvidia": ("nvidia",),
}

# Model name prefixes that identify a family's Inspect database organization.
NAME_ORGS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("claude",), ("anthropic",)),
    (("gpt-", "chatgpt", "codex"), ("openai",)),
    (("gemini", "gemma", "medgemma"), ("google",)),
    (("grok",), ("grok",)),
    (
        (
            "mistral",
            "mixtral",
            "magistral",
            "devstral",
            "codestral",
            "ministral",
            "pixtral",
        ),
        ("mistral", "mistralai"),
    ),
    (("kimi",), ("moonshotai",)),
    (("deepseek",), ("DeepSeek", "deepseek-ai")),
    (("glm",), ("z-ai", "zai-org")),
    (("qwen", "qwq"), ("Qwen",)),
    (("llama", "meta-llama"), ("meta-llama",)),
    (("minimax",), ("MiniMaxAI",)),
)

# Bedrock `vendor.model` ids (version suffix removed) whose Inspect keys are
# not a mechanical rewrite.
BEDROCK_IDS = {
    "meta.llama3-3-70b-instruct": "meta-llama/Llama-3.3-70B-Instruct",
    "meta.llama3-1-405b-instruct": "meta-llama/Llama-3.1-405B-Instruct",
    "meta.llama3-2-1b-instruct": "meta-llama/Llama-3.2-1B-Instruct",
    "meta.llama3-2-3b-instruct": "meta-llama/Llama-3.2-3B-Instruct",
    "meta.llama4-scout-17b-instruct": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "mistral.mistral-7b-instruct": "mistralai/Mistral-7B-Instruct-v0.2",
    "mistral.mixtral-8x7b-instruct": "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "deepseek.r1": "deepseek-ai/DeepSeek-R1",
    "deepseek.v3": "deepseek-ai/DeepSeek-V3.1",
}

# Bedrock path segments that name a LiteLLM route or invoke vendor rather
# than the model (LiteLLM `get_bedrock_route`, BEDROCK_INVOKE_PROVIDERS_LITERAL).
BEDROCK_ROUTE_SEGMENTS = frozenset(
    {
        "converse",
        "invoke",
        "converse_like",
        "claude_platform",
        "agent",
        "agentcore",
        "async_invoke",
        "openai",
        "mantle",
        "nova",
        "nova-2",
        "cohere",
        "anthropic",
        "mistral",
        "amazon",
        "meta",
        "llama",
        "ai21",
        "deepseek_r1",
        "qwen3",
        "qwen2",
        "twelvelabs",
        "stability",
        "moonshot",
    }
)
BEDROCK_CROSS_REGIONS = ("global", "us-gov", "us", "eu", "apac", "jp", "au", "ca")
AWS_REGION = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-\d+$")
BEDROCK_VERSION = re.compile(r"-v\d+(:\d+)?$|-\d+:\d+$|:\d+$")
BEDROCK_COMMITMENT = re.compile(r"^\d+-month-commitment$")

AZURE_ROUTE_SEGMENTS = frozenset(
    {"responses", "o_series", "gpt5_series", "us", "eu", "global"}
)
FIREWORKS_PREFIX = re.compile(r"^accounts/[^/]+/(models|routers)/")
VERTEX_STABLE_SUFFIX = re.compile(r"-00\d$")
DATE_SUFFIX = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2})$")
DOTTED_VERSION = re.compile(r"(?<=\d)\.(?=\d)")


class ProxyResolution(NamedTuple):
    """The upstream model behind a proxy alias."""

    db_key: str | None
    """Inspect database key, when a candidate matched exactly."""

    upstream: str | None
    """Normalized upstream name (the first candidate, else the raw string)."""


def resolve_deployments(
    alias: str, deployments: list[ProxyDeployment]
) -> ProxyResolution | None:
    """Resolve an alias from its deployments (None when there are none).

    Deployments behind one alias usually serve the same model. Resolved keys
    are compared: when they agree (ignoring deployments that did not
    resolve, such as an opaque ARN) that key is used; when they differ, the
    first deployment's key is used and a warning is logged.
    """
    if not deployments:
        return None
    resolutions = [_resolve_deployment(d) for d in deployments]
    keys = list(dict.fromkeys(r.db_key for r in resolutions if r.db_key))
    if len(keys) > 1:
        warn_once(
            logger,
            f"LiteLLM proxy alias '{alias}' has deployments of different models "
            f"({', '.join(keys)}); using {keys[0]} for model info.",
        )
    if keys:
        return next(r for r in resolutions if r.db_key == keys[0])
    return resolutions[0]


def _resolve_deployment(deployment: ProxyDeployment) -> ProxyResolution:
    upstream = upstream_model(deployment)
    if upstream is None:
        return ProxyResolution(db_key=None, upstream=None)
    candidates = database_candidates(upstream)
    db_key = next((key for c in candidates if (key := _strict_db_key(c))), None)
    return ProxyResolution(
        db_key=db_key, upstream=candidates[0] if candidates else upstream
    )


def upstream_model(deployment: ProxyDeployment) -> str | None:
    """The upstream model a deployment serves, in LiteLLM or Inspect form.

    The operator's `model_info.base_model` wins; otherwise
    `litellm_params.model`, with `custom_llm_provider` prepended when it is
    not already the first segment (LiteLLM does the same when routing).
    """
    if deployment.base_model:
        return deployment.base_model
    model = deployment.model
    if model is None:
        return None
    provider = deployment.custom_llm_provider
    if provider and model.split("/", 1)[0] != provider:
        return f"{provider}/{model}"
    return model


def database_candidates(upstream: str) -> list[str]:
    """Ordered, de-duplicated Inspect database keys to try for `upstream`."""
    provider, _, rest = upstream.partition("/")
    provider = provider.lower()
    if not rest:
        # a bare id; `base_model` is often a Bedrock id without `bedrock/`
        candidates = (
            _bedrock_candidates(upstream)
            if _is_bedrock_id(upstream)
            else _bare_candidates(None, upstream)
        )
    elif provider not in LITELLM_PROVIDERS:
        candidates = _path_candidates(upstream)
    else:
        provider = PROVIDER_ALIASES.get(provider, provider)
        match provider:
            case "bedrock" | "bedrock_mantle":
                candidates = _bedrock_candidates(rest)
            case "vertex_ai":
                candidates = _vertex_candidates(rest)
            case "azure" | "azure_ai":
                candidates = _azure_candidates(provider, rest)
            case "openai" | "chatgpt" | "custom_openai":
                candidates = _openai_candidates(provider, rest)
            case "fireworks_ai":
                candidates = _fireworks_candidates(rest)
            case "openrouter":
                # variant suffixes (`:free`, `:nitro`, `:exacto`) select
                # routing, not a different model
                candidates = _path_candidates(re.sub(r":[a-z-]+$", "", rest))
            case _:
                candidates = (
                    _path_candidates(rest)
                    if "/" in rest
                    else _bare_candidates(provider, rest)
                )
    return _with_variants(candidates)


def _bare_candidates(provider: str | None, name: str) -> list[str]:
    orgs = (PROVIDER_ORGS.get(provider, ()) if provider else ()) + _name_orgs(name)
    return [f"{org}/{name}" for org in orgs]


def _path_candidates(path: str) -> list[str]:
    """An `org/model` (or deeper) path: as is, then under mapped orgs.

    A deeper path whose first segment is not a known vendor may be
    `host/org/model` for a host LiteLLM configures by name only (e.g.
    `replicate/`, OpenAI-compatible hosts), so the path without that segment
    is tried too.
    """
    vendor, _, name = path.partition("/")
    orgs = VENDOR_ORGS.get(vendor.lower(), ()) + _name_orgs(name.split("/")[-1])
    candidates = [path, *(f"{org}/{name}" for org in orgs)]
    if "/" in name and vendor.lower() not in VENDOR_ORGS:
        candidates += _path_candidates(name)
    return candidates


def _bedrock_candidates(rest: str) -> list[str]:
    segments = [s for s in rest.split("/") if s]
    if segments and segments[0].startswith("arn:"):
        segments = ["/".join(segments)]
    while len(segments) > 1 and (
        segments[0] in BEDROCK_ROUTE_SEGMENTS
        or segments[0] == "*"
        or AWS_REGION.match(segments[0])
        or BEDROCK_COMMITMENT.match(segments[0])
    ):
        segments = segments[1:]
    model_id = "/".join(segments)
    if model_id.startswith("arn:"):
        if ":application-inference-profile/" in model_id:
            return []  # an opaque id; only base_model identifies it
        model_id = model_id.split("/")[-1]
    # throughput (`:51k`) and context window (`[1m]`) suffixes
    model_id = re.sub(r"(:\d+):\d+k$", r"\1", model_id)
    model_id = re.sub(r"\[\w+\]$", "", model_id)
    for region in BEDROCK_CROSS_REGIONS:
        if model_id.startswith(f"{region}."):
            model_id = model_id[len(region) + 1 :]
            break

    vendor, dot, name = model_id.partition(".")
    if not dot:
        unversioned = BEDROCK_VERSION.sub("", model_id)
        return [c for n in (model_id, unversioned) for c in _bare_candidates(None, n)]
    unversioned = BEDROCK_VERSION.sub("", name)
    orgs = VENDOR_ORGS.get(vendor.lower(), ()) + _name_orgs(name)
    names = [name, unversioned]
    if vendor.lower() == "nvidia":
        # Hugging Face names NVIDIA models `NVIDIA-Nemotron-...`
        names.append(f"NVIDIA-{name}")
    # the model's own key first, then the Bedrock id (the database keeps
    # some as aliases, e.g. `anthropic/anthropic.claude-opus-4-5-...-v1:0`)
    candidates = [f"{org}/{n}" for n in names for org in orgs]
    candidates += [f"{org}/{model_id}" for org in orgs]
    known = BEDROCK_IDS.get(f"{vendor}.{unversioned}".lower())
    return candidates + ([known] if known else [])


def _is_bedrock_id(name: str) -> bool:
    """Whether a bare id has a Bedrock `[region.]vendor.model` form."""
    for region in BEDROCK_CROSS_REGIONS:
        if name.startswith(f"{region}."):
            name = name[len(region) + 1 :]
            break
    vendor, dot, _ = name.partition(".")
    return bool(dot) and vendor.lower() in VENDOR_ORGS


def _vertex_candidates(rest: str) -> list[str]:
    if "/" in rest:
        # partner models: `meta/llama-...-maas`, `deepseek-ai/...`
        vendor, _, name = rest.partition("/")
        name = re.sub(r"-maas$", "", name)
        return _path_candidates(f"{vendor}/{name}")
    base, at, date = rest.partition("@")
    names = [rest, f"{base}-{date}"] if at else [rest]
    names += [base, VERTEX_STABLE_SUFFIX.sub("", base)]
    orgs = _name_orgs(base)
    return [f"{org}/{name}" for name in names for org in orgs]


def _azure_candidates(provider: str, rest: str) -> list[str]:
    segments = [s for s in rest.split("/") if s.lower() not in AZURE_ROUTE_SEGMENTS]
    name = "/".join(segments)
    if "/" in name:
        return _path_candidates(name)
    name = re.sub(r"^gpt-35-", "gpt-3.5-", name)
    # azure_ai hosts many vendors; azure hosts OpenAI models
    return _bare_candidates(None if provider == "azure_ai" else "azure", name)


def _openai_candidates(provider: str, rest: str) -> list[str]:
    rest = re.sub(r"^responses/", "", rest)
    if "/" in rest:
        # an OpenAI-compatible server serving `org/model`
        return _path_candidates(rest)
    if rest.startswith("ft:"):
        rest = rest.split(":")[1]
    return _bare_candidates(provider, rest)


def _fireworks_candidates(rest: str) -> list[str]:
    return [f"fireworks/{FIREWORKS_PREFIX.sub('', rest)}"]


def _name_orgs(name: str) -> tuple[str, ...]:
    lowered = name.lower()
    if re.match(r"^o\d", lowered):
        return ("openai",)
    for prefixes, orgs in NAME_ORGS:
        if lowered.startswith(prefixes):
            return orgs
    return ()


def _with_variants(candidates: Iterable[str]) -> list[str]:
    """De-duplicate, adding dashed Claude versions and date-stripped names."""
    ordered: list[str] = []
    for candidate in candidates:
        ordered.append(candidate)
        org, _, name = candidate.partition("/")
        if org == "anthropic" and DOTTED_VERSION.search(name):
            # OpenRouter spells Claude versions with dots
            ordered.append(f"{org}/{DOTTED_VERSION.sub('-', name)}")
    ordered += [DATE_SUFFIX.sub("", c) for c in ordered if DATE_SUFFIX.search(c)]
    return list(dict.fromkeys(ordered))
