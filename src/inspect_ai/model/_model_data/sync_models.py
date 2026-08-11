#!/usr/bin/env python3
"""Sync model data from external sources.

This script fetches model information from inference provider APIs and writes
one YAML file per source:

- `together.yml` is organized by model creator. Together serves
  HuggingFace-style `org/model` names, which already match the database's
  creator-keyed format.
- `fireworks.yml` is a single `fireworks` organization. Fireworks model names
  carry no creator component (`accounts/fireworks/models/deepseek-r1-0528`), so
  `FireworksAIAPI.canonical_name()` keys them under the provider instead. The
  context length Fireworks reports is authoritative for what Fireworks serves,
  which can differ from the creator's own deployment of the same weights
  (DeepSeek's API served R1-0528 at 64K; Fireworks serves it at 160K).

Models that are curated by hand in one of the sibling YAML files are skipped
(matched on the case-normalized org/model lookup key, including aliases and
versions): the lookup index in _model_info.py resolves colliding keys by
file-load order, so a bare auto-generated entry would otherwise shadow the
richer curated one. This is also the escape hatch for restoring metadata the
provider APIs don't report (e.g. `reasoning`) on a specific model: curate it in
a sibling file and the sync leaves it alone.

This script must stay self-contained (stdlib + pyyaml + requests only, no
inspect_ai imports): the sync workflow runs it without installing the package
(see .github/workflows/sync_model_data.yml).

Usage:
    python -m inspect_ai.model._model_data.sync_models [--source SOURCE]

    SOURCE is `together`, `fireworks`, or `all` (the default).

Requirements:
    - TOGETHER_API_KEY environment variable (for the together source)
    - FIREWORKS_API_KEY environment variable (for the fireworks source)
"""

from __future__ import annotations

import argparse
import copy
import os
import re
import shutil
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import AbstractSet, Any, Callable, NamedTuple, cast

import yaml

DATA_DIR = Path(__file__).parent

TOGETHER_API_URL = "https://api.together.xyz/v1/models"
TOGETHER_OUTPUT_FILE = DATA_DIR / "together.yml"

# Fireworks' control-plane API (not the OpenAI-compatible inference API, which
# omits context lengths). Records come back complete, so no per-model fetch.
FIREWORKS_API_URL = "https://api.fireworks.ai/v1/accounts/fireworks/models"
FIREWORKS_OUTPUT_FILE = DATA_DIR / "fireworks.yml"
FIREWORKS_MODEL_PREFIX = "accounts/fireworks/models/"
FIREWORKS_ORG = "fireworks"
FIREWORKS_PAGE_SIZE = 200
# 10k models at the page size above; guards against a pagination loop
FIREWORKS_MAX_PAGES = 50

# Files this script generates. Never treated as a source of curated keys.
GENERATED_FILES = {TOGETHER_OUTPUT_FILE.name, FIREWORKS_OUTPUT_FILE.name}


# Known organization display names
ORG_DISPLAY_NAMES: dict[str, str] = {
    "meta-llama": "Meta",
    "mistralai": "Mistral AI",
    "Qwen": "Qwen",
    "google": "Google",
    "deepseek-ai": "DeepSeek",
    "microsoft": "Microsoft",
    "nvidia": "NVIDIA",
    "databricks": "Databricks",
    "togethercomputer": "Together AI",
    "upstage": "Upstage",
    "allenai": "Allen AI",
    "NousResearch": "Nous Research",
    "Gryphe": "Gryphe",
    "openchat": "OpenChat",
    "teknium": "Teknium",
    "Open-Orca": "Open Orca",
    "lmsys": "LMSYS",
    "garage-bAInd": "Garage-bAInd",
    "zero-one-ai": "01.AI",
    "Snowflake": "Snowflake",
    "scb10x": "SCB 10X",
    "cognitivecomputations": "Cognitive Computations",
    FIREWORKS_ORG: "Fireworks AI",
}


def get_org_display_name(org_id: str) -> str:
    """Get display name for an organization."""
    return ORG_DISPLAY_NAMES.get(org_id, org_id)


def _normalize_for_lookup(name: str) -> str:
    """Normalize a model name for case-insensitive lookup.

    Mirror of inspect_ai.model._model_info._normalize_for_lookup, duplicated
    because this script must run with no inspect_ai install (see the module
    docstring); tests/model/test_sync_models.py asserts the two stay in sync.
    """
    return name.lower().replace("_", "-")


def load_curated_model_keys(data_dir: Path) -> set[str]:
    """Collect normalized org/model lookup keys defined by the curated files.

    Scans every YAML file in `data_dir` except the auto-generated ones and
    expands each model to the full set of names the lookup index will see: the
    model key itself, its aliases, and its version names and aliases.
    """
    keys: set[str] = set()
    for info_file in sorted(data_dir.glob("*.yml")):
        if info_file.name in GENERATED_FILES:
            continue
        with open(info_file) as f:
            data = yaml.safe_load(f) or {}
        for org, org_data in data.items():
            for model_name, model_def in (org_data.get("models") or {}).items():
                model_def = model_def or {}
                names = [model_name, *(model_def.get("aliases") or [])]
                for version_name, version_data in (
                    model_def.get("versions") or {}
                ).items():
                    version_data = version_data or {}
                    names.append(version_name)
                    names.extend(version_data.get("aliases") or [])
                keys.update(_normalize_for_lookup(f"{org}/{name}") for name in names)
    return keys


def parse_model_id(model_id: str) -> tuple[str, str] | None:
    """Parse a model ID into (organization, model_name).

    Args:
        model_id: Full model ID like 'meta-llama/Llama-3.1-8B-Instruct'

    Returns:
        Tuple of (organization, model_name) or None if unparseable.
    """
    if "/" not in model_id:
        return None
    parts = model_id.split("/", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def generate_display_name(model_name: str) -> str:
    """Generate a human-readable display name from a model name.

    Args:
        model_name: Raw model name like 'Llama-3.1-8B-Instruct'

    Returns:
        Human-readable name like 'Llama 3.1 8B Instruct'
    """
    # Replace hyphens with spaces, keeping version numbers together
    name = re.sub(r"-(?=\d)", " ", model_name)
    name = name.replace("-", " ")
    # Clean up double spaces
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def fetch_together_models(api_key: str) -> list[dict[str, Any]]:
    """Fetch model list from TogetherAI API."""
    # Imported here so the module stays importable (e.g. by tests) in
    # environments where requests is not installed.
    import requests  # type: ignore

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(TOGETHER_API_URL, headers=headers, timeout=30)
        response.raise_for_status()
        return cast(list[dict[str, Any]], response.json())
    except requests.RequestException as e:
        print(f"Error fetching models from Together API: {e}")
        sys.exit(1)


def fetch_fireworks_models(api_key: str) -> list[dict[str, Any]]:
    """Fetch the public model list from the Fireworks control-plane API."""
    import requests  # type: ignore

    headers = {"Authorization": f"Bearer {api_key}"}
    models: list[dict[str, Any]] = []
    page_token: str | None = None

    try:
        for _ in range(FIREWORKS_MAX_PAGES):
            params: dict[str, Any] = {"pageSize": FIREWORKS_PAGE_SIZE}
            if page_token:
                params["pageToken"] = page_token
            response = requests.get(
                FIREWORKS_API_URL, headers=headers, params=params, timeout=30
            )
            response.raise_for_status()
            payload = response.json()
            page = payload.get("models") or []
            models.extend(page)
            page_token = payload.get("nextPageToken")
            if not page_token or not page:
                return models
    except requests.RequestException as e:
        print(f"Error fetching models from Fireworks API: {e}")
        sys.exit(1)

    print(f"Warning: stopped paging Fireworks models after {FIREWORKS_MAX_PAGES} pages")
    return models


def process_together_models(
    models: list[dict[str, Any]],
    curated_keys: AbstractSet[str] = frozenset(),
) -> dict[str, Any]:
    """Process raw Together model data into organized YAML structure.

    Args:
        models: List of model dictionaries from the API
        curated_keys: Normalized org/model keys curated in other data files;
            colliding API models are skipped so the curated entries keep
            winning the case-normalized lookup.

    Returns:
        Dictionary organized by organization for YAML output.
    """
    organizations: dict[str, dict[str, Any]] = {}

    for model in models:
        model_id = model.get("id", "")
        parsed = parse_model_id(model_id)
        if not parsed:
            continue

        org_id, model_name = parsed
        context_length = model.get("context_length")

        # Skip models without context length
        if context_length is None:
            continue

        # Skip models curated by hand in another data file
        if _normalize_for_lookup(f"{org_id}/{model_name}") in curated_keys:
            continue

        # Initialize organization if needed
        if org_id not in organizations:
            organizations[org_id] = {
                "display_name": get_org_display_name(org_id),
                "models": {},
            }

        # Add model info
        model_info: dict[str, Any] = {
            "display_name": generate_display_name(model_name),
            "context_length": context_length,
        }

        organizations[org_id]["models"][model_name] = model_info

    # Sort organizations alphabetically
    return dict(sorted(organizations.items()))


def process_fireworks_models(
    models: list[dict[str, Any]],
    curated_keys: AbstractSet[str] = frozenset(),
) -> dict[str, Any]:
    """Process raw Fireworks model data into organized YAML structure.

    Everything lands under a single `fireworks` organization, matching the key
    `FireworksAIAPI.canonical_name()` produces (see the module docstring).

    Args:
        models: List of model records from the control-plane API
        curated_keys: Normalized org/model keys curated in other data files.

    Returns:
        Dictionary with the single `fireworks` organization, or empty if no
        model qualified.
    """
    entries: dict[str, Any] = {}

    for model in models:
        name = model.get("name", "")
        if not name.startswith(FIREWORKS_MODEL_PREFIX):
            continue
        model_name = name[len(FIREWORKS_MODEL_PREFIX) :]
        if not model_name:
            continue

        # Anything not READY is still importing or has failed
        if model.get("state") != "READY":
            continue

        # A missing or zero contextLength covers draft addons, Flumina
        # (image/audio) models, and records Fireworks hasn't calibrated
        context_length = model.get("contextLength")
        if not context_length:
            continue

        if _normalize_for_lookup(f"{FIREWORKS_ORG}/{model_name}") in curated_keys:
            continue

        entries[model_name] = {
            "display_name": model.get("displayName")
            or generate_display_name(model_name),
            "context_length": context_length,
        }

    if not entries:
        return {}

    return {
        FIREWORKS_ORG: {
            "display_name": get_org_display_name(FIREWORKS_ORG),
            "models": dict(sorted(entries.items())),
        }
    }


class Source(NamedTuple):
    """A provider API the script can sync from."""

    name: str
    api_url: str
    api_key_env: str
    output_file: Path
    title: str
    organization_note: str
    fetch: Callable[[str], list[dict[str, Any]]]
    process: Callable[[list[dict[str, Any]], AbstractSet[str]], dict[str, Any]]


SOURCES: dict[str, Source] = {
    "together": Source(
        name="together",
        api_url=TOGETHER_API_URL,
        api_key_env="TOGETHER_API_KEY",
        output_file=TOGETHER_OUTPUT_FILE,
        title="Together AI Model Database",
        organization_note=(
            "Models are organized by their creator organization, not by the "
            "inference provider."
        ),
        fetch=fetch_together_models,
        process=process_together_models,
    ),
    "fireworks": Source(
        name="fireworks",
        api_url=FIREWORKS_API_URL,
        api_key_env="FIREWORKS_API_KEY",
        output_file=FIREWORKS_OUTPUT_FILE,
        title="Fireworks AI Model Database",
        organization_note=(
            "Fireworks model names carry no creator component, so models are "
            "organized under a single `fireworks` organization matching the "
            "key FireworksAIAPI.canonical_name() produces. Context lengths are "
            "what Fireworks serves, which can differ from the creator's own "
            "deployment of the same weights."
        ),
        fetch=fetch_fireworks_models,
        process=process_fireworks_models,
    ),
}


def load_existing_data(output_file: Path) -> dict[str, Any]:
    """Load existing model data from the YAML file.

    Returns:
        Dictionary of existing org/model data, or empty dict if file doesn't exist.
    """
    if not output_file.exists():
        return {}

    with open(output_file) as f:
        content = yaml.safe_load(f)

    return cast(dict[str, Any], content) if content else {}


def merge_models(
    existing: dict[str, Any], new: dict[str, Any]
) -> tuple[dict[str, Any], int, int, int]:
    """Merge new API data with existing model data.

    New models are added, existing models are updated, and models no longer
    in the API are preserved (not deleted).

    Args:
        existing: Existing org/model data from YAML file.
        new: New org/model data from the API.

    Returns:
        Tuple of (merged data, models added, models updated, models preserved).
    """
    merged = copy.deepcopy(existing)
    new_model_ids = set()
    added = 0
    updated = 0

    # Collect all model keys from new data
    for org_id, org_data in new.items():
        for model_name in org_data.get("models", {}):
            new_model_ids.add((org_id, model_name))

    # Add/update from new data
    for org_id, org_data in new.items():
        if org_id not in merged:
            merged[org_id] = org_data
            added += len(org_data.get("models", {}))
        else:
            # Update org display_name from API
            merged[org_id]["display_name"] = org_data["display_name"]
            existing_models = merged[org_id].get("models", {})
            for model_name, model_info in org_data.get("models", {}).items():
                if model_name not in existing_models:
                    existing_models[model_name] = model_info
                    added += 1
                else:
                    existing_models[model_name]["context_length"] = model_info[
                        "context_length"
                    ]
                    existing_models[model_name]["display_name"] = model_info[
                        "display_name"
                    ]
                    updated += 1
            merged[org_id]["models"] = existing_models

    # Count preserved models (in existing but not in new API data)
    preserved = 0
    for org_id, org_data in merged.items():
        for model_name in org_data.get("models", {}):
            if (org_id, model_name) not in new_model_ids:
                preserved += 1

    # Sort by org name
    merged = dict(sorted(merged.items()))

    return merged, added, updated, preserved


def remove_curated_models(
    data: dict[str, Any], curated_keys: AbstractSet[str]
) -> tuple[dict[str, Any], int]:
    """Remove entries that collide with curated models from other data files.

    Backstop for entries already present in the generated file before a model
    became curated (merge_models preserves models no longer in the API, so
    skipping in the process step alone would never remove them).

    Returns:
        Tuple of (filtered copy of data, number of models removed).
    """
    filtered: dict[str, Any] = {}
    removed = 0
    for org_id, org_data in data.items():
        models = {
            model_name: model_info
            for model_name, model_info in org_data.get("models", {}).items()
            if _normalize_for_lookup(f"{org_id}/{model_name}") not in curated_keys
        }
        removed += len(org_data.get("models", {})) - len(models)
        if models:
            filtered[org_id] = {**org_data, "models": models}
    return filtered, removed


def backup_existing_file(output_file: Path) -> Path | None:
    """Create a backup of the existing YAML file if it exists."""
    if output_file.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = output_file.with_suffix(f".{timestamp}.bak")
        shutil.copy(output_file, backup_path)
        return backup_path
    return None


def write_yaml(data: dict[str, Any], source: Source) -> None:
    """Write data to the source's YAML file with header comment."""
    note = textwrap.fill(
        source.organization_note, width=76, initial_indent="# ", subsequent_indent="# "
    )
    header = f"""\
# {source.title}
# Auto-generated by sync_models.py on {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC
# Source: {source.api_url}
#
{note}
#
# To regenerate this file:
#   {source.api_key_env}=your_key python -m inspect_ai.model._model_data.sync_models --source {source.name}

"""
    with open(source.output_file, "w") as f:
        f.write(header)
        yaml.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def sync_source(source: Source, api_key: str, curated_keys: AbstractSet[str]) -> None:
    """Fetch, merge and write model data for a single source."""
    print(f"Fetching models from {source.api_url}...")
    models = source.fetch(api_key)
    print(f"Fetched {len(models)} models")

    print("Processing models...")
    new_data = source.process(models, curated_keys)
    new_model_count = sum(len(org["models"]) for org in new_data.values())
    print(f"Processed {new_model_count} models from {len(new_data)} organizations")

    # Load existing data and merge
    existing_data = load_existing_data(source.output_file)
    if existing_data:
        print("Merging with existing model data...")
        data, added, updated, preserved = merge_models(existing_data, new_data)
        total = sum(len(org["models"]) for org in data.values())
        print(f"  {added} new models added")
        print(f"  {updated} existing models updated")
        print(f"  {preserved} deprecated models preserved")
        print(f"  {total} total models")
    else:
        data = new_data

    # Drop any previously synced entries that have since become curated
    data, removed = remove_curated_models(data, curated_keys)
    if removed:
        print(f"  {removed} models removed (curated in other data files)")

    # Backup existing file
    backup_path = backup_existing_file(source.output_file)
    if backup_path:
        print(f"Backed up existing file to {backup_path}")

    # Write new file
    write_yaml(data, source)
    print(f"Wrote {source.output_file}")


def main() -> None:
    """Main entry point for the sync script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=[*SOURCES, "all"],
        default="all",
        help="Provider catalog to sync (default: all)",
    )
    args = parser.parse_args()

    sources = list(SOURCES.values()) if args.source == "all" else [SOURCES[args.source]]

    # Validate credentials up front so a partial sync can't leave one file
    # updated and another stale
    api_keys: dict[str, str] = {}
    missing: list[str] = []
    for source in sources:
        api_key = os.environ.get(source.api_key_env)
        if api_key:
            api_keys[source.name] = api_key
        else:
            missing.append(source.api_key_env)
    if missing:
        print(f"Error: environment variable(s) not set: {', '.join(missing)}")
        sys.exit(1)

    curated_keys = load_curated_model_keys(DATA_DIR)
    print(f"Loaded {len(curated_keys)} curated model keys to skip")

    for source in sources:
        print(f"\n=== {source.name} ===")
        sync_source(source, api_keys[source.name], curated_keys)


if __name__ == "__main__":
    main()
