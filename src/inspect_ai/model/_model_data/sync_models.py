#!/usr/bin/env python3
"""Sync model data from external sources.

This script fetches model information from the TogetherAI API and writes it
to a YAML file organized by model creator (not data source).

Usage:
    python -m inspect_ai.model._model_data.sync_models

Requirements:
    - TOGETHER_API_KEY environment variable must be set

The output file (together.yml) is organized by model creator:
    meta-llama:
      display_name: Meta
      models:
        Llama-3.1-8B-Instruct:
          context_length: 131072
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import requests  # type: ignore
import yaml

TOGETHER_API_URL = "https://api.together.xyz/v1/models"
OUTPUT_FILE = Path(__file__).parent / "together.yml"


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
}


def get_org_display_name(org_id: str) -> str:
    """Get display name for an organization."""
    return ORG_DISPLAY_NAMES.get(org_id, org_id)


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


def fetch_together_models() -> list[dict[str, Any]]:
    """Fetch model list from TogetherAI API."""
    api_key = os.environ.get("TOGETHER_API_KEY")
    if not api_key:
        print("Error: TOGETHER_API_KEY environment variable not set")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = requests.get(TOGETHER_API_URL, headers=headers, timeout=30)
        response.raise_for_status()
        return cast(list[dict[str, Any]], response.json())
    except requests.RequestException as e:
        print(f"Error fetching models from Together API: {e}")
        sys.exit(1)


def process_models(models: list[dict[str, Any]]) -> dict[str, Any]:
    """Process raw model data into organized YAML structure.

    Args:
        models: List of model dictionaries from the API

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


def backup_existing_file() -> Path | None:
    """Create a backup of the existing YAML file if it exists."""
    if OUTPUT_FILE.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = OUTPUT_FILE.with_suffix(f".{timestamp}.bak")
        shutil.copy(OUTPUT_FILE, backup_path)
        return backup_path
    return None


def write_yaml(data: dict[str, Any]) -> None:
    """Write data to YAML file with header comment."""
    header = f"""\
# Together AI Model Database
# Auto-generated by sync_models.py on {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC
# Source: {TOGETHER_API_URL}
#
# This file contains model information fetched from the TogetherAI API.
# Models are organized by their creator organization, not by the inference provider.
#
# To regenerate this file:
#   TOGETHER_API_KEY=your_key python -m inspect_ai.model._model_data.sync_models

"""
    with open(OUTPUT_FILE, "w") as f:
        f.write(header)
        yaml.dump(
            data, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def main() -> None:
    """Main entry point for the sync script."""
    print(f"Fetching models from {TOGETHER_API_URL}...")
    models = fetch_together_models()
    print(f"Fetched {len(models)} models")

    print("Processing models...")
    data = process_models(models)
    model_count = sum(len(org["models"]) for org in data.values())
    print(f"Processed {model_count} models from {len(data)} organizations")

    # Backup existing file
    backup_path = backup_existing_file()
    if backup_path:
        print(f"Backed up existing file to {backup_path}")

    # Write new file
    write_yaml(data)
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
