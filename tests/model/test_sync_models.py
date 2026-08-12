"""Tests for the model data sync script.

The sync script must never emit an entry that collides (on the
case-normalized lookup key) with a model curated by hand in one of the
sibling YAML files: such entries shadow the richer curated data in
`_build_lookup_index()` (last write wins) and drift on functional fields
like context_length (e.g. Together reports Kimi K3 as 1,000,000 while
Moonshot's docs give 1,048,576).
"""

from pathlib import Path

import pytest
import yaml

from inspect_ai.model._model_data import model_data, sync_models
from inspect_ai.model._model_info import PROVIDER_SCOPED_ORGS, _normalize_for_lookup

DATA_DIR = Path(model_data.__file__).parent


class TestNormalizationMirror:
    """sync_models keeps a dependency-free copy of _normalize_for_lookup."""

    @pytest.mark.parametrize(
        "name",
        [
            "moonshotai/Kimi-K3",
            "moonshotai/kimi-k3",
            "org/Model_Name_X",
            "ORG/MODEL-1.5_pro",
            "zai-org/GLM-5.2",
        ],
    )
    def test_matches_model_info_normalization(self, name: str) -> None:
        assert sync_models._normalize_for_lookup(name) == _normalize_for_lookup(name)


class TestLoadCuratedModelKeys:
    def _write(self, path: Path, content: str) -> None:
        path.write_text(content)

    def test_expands_models_aliases_and_versions(self, tmp_path: Path) -> None:
        self._write(
            tmp_path / "acme.yml",
            """
acme:
  display_name: Acme
  models:
    Widget_Pro:
      context_length: 1000
      aliases:
        - widget
      versions:
        widget-pro-latest:
          snapshot: latest
          aliases:
            - widget-newest
""",
        )
        keys = sync_models.load_curated_model_keys(tmp_path)
        assert keys == {
            "acme/widget-pro",
            "acme/widget",
            "acme/widget-pro-latest",
            "acme/widget-newest",
        }

    @pytest.mark.parametrize("generated", ["together.yml", "fireworks.yml"])
    def test_excludes_the_generated_files(self, tmp_path: Path, generated: str) -> None:
        self._write(
            tmp_path / generated,
            """
acme:
  display_name: acme
  models:
    FromGenerated:
      context_length: 1000
""",
        )
        assert sync_models.load_curated_model_keys(tmp_path) == set()


class TestProcessModelsSkipsCurated:
    def test_skips_case_normalized_collisions(self) -> None:
        api_models = [
            {"id": "moonshotai/Kimi-K3", "context_length": 1000000},
            {"id": "acme/Widget", "context_length": 4096},
        ]
        result = sync_models.process_together_models(
            api_models, curated_keys={"moonshotai/kimi-k3"}
        )
        assert "moonshotai" not in result
        assert "Widget" in result["acme"]["models"]

    def test_no_curated_keys_keeps_everything(self) -> None:
        api_models = [{"id": "moonshotai/Kimi-K3", "context_length": 1000000}]
        result = sync_models.process_together_models(api_models)
        assert "Kimi-K3" in result["moonshotai"]["models"]


class TestProcessFireworksModels:
    """Fireworks records collapse into a single provider-keyed organization."""

    def _model(self, slug: str, **overrides: object) -> dict[str, object]:
        model: dict[str, object] = {
            "name": f"accounts/fireworks/models/{slug}",
            "displayName": slug.upper(),
            "contextLength": 131072,
            "state": "READY",
        }
        model.update(overrides)
        return model

    def test_keys_models_under_the_fireworks_org(self) -> None:
        result = sync_models.process_fireworks_models([self._model("kimi-k3")])
        assert result == {
            "fireworks": {
                "display_name": "Fireworks AI",
                "models": {
                    "kimi-k3": {"display_name": "KIMI-K3", "context_length": 131072}
                },
            }
        }

    def test_skips_models_without_a_usable_context_length(self) -> None:
        models = [
            self._model("no-context", contextLength=None),
            self._model("zero-context", contextLength=0),
            self._model("good"),
        ]
        result = sync_models.process_fireworks_models(models)
        assert list(result["fireworks"]["models"]) == ["good"]

    def test_skips_models_that_are_not_ready(self) -> None:
        models = [self._model("importing", state="IMPORTING"), self._model("good")]
        result = sync_models.process_fireworks_models(models)
        assert list(result["fireworks"]["models"]) == ["good"]

    def test_skips_records_outside_the_fireworks_account(self) -> None:
        models = [
            {
                "name": "accounts/someone-else/models/private",
                "contextLength": 4096,
                "state": "READY",
            },
            self._model("good"),
        ]
        result = sync_models.process_fireworks_models(models)
        assert list(result["fireworks"]["models"]) == ["good"]

    def test_falls_back_to_a_generated_display_name(self) -> None:
        result = sync_models.process_fireworks_models(
            [self._model("qwen3-14b", displayName=None)]
        )
        assert result["fireworks"]["models"]["qwen3-14b"]["display_name"] == "qwen3 14b"

    def test_skips_curated_collisions(self) -> None:
        result = sync_models.process_fireworks_models(
            [self._model("Kimi-K3"), self._model("good")],
            curated_keys={"fireworks/kimi-k3"},
        )
        assert list(result["fireworks"]["models"]) == ["good"]

    def test_no_qualifying_models_yields_no_organization(self) -> None:
        assert sync_models.process_fireworks_models([]) == {}


class TestRemoveCuratedModels:
    def test_removes_colliding_entries_and_empty_orgs(self) -> None:
        data = {
            "moonshotai": {
                "display_name": "moonshotai",
                "models": {
                    "Kimi-K3": {"display_name": "Kimi K3", "context_length": 1000000},
                    "Kimi-K2-Thinking": {
                        "display_name": "Kimi K2 Thinking",
                        "context_length": 262144,
                    },
                },
            },
            "onlycurated": {
                "display_name": "onlycurated",
                "models": {
                    "Dupe": {"display_name": "Dupe", "context_length": 1},
                },
            },
        }
        filtered, removed = sync_models.remove_curated_models(
            data, {"moonshotai/kimi-k3", "onlycurated/dupe"}
        )
        assert removed == 2
        assert "Kimi-K3" not in filtered["moonshotai"]["models"]
        assert "Kimi-K2-Thinking" in filtered["moonshotai"]["models"]
        assert "onlycurated" not in filtered
        # input is not mutated
        assert "Kimi-K3" in data["moonshotai"]["models"]


class TestGeneratedYmlDataInvariant:
    @pytest.mark.parametrize("generated", sorted(sync_models.GENERATED_FILES))
    def test_generated_yml_contains_no_curated_collisions(self, generated: str) -> None:
        """A generated file must not define any model curated in a sibling file.

        If this fails after a sync, either regenerate the file with a fixed
        sync_models.py or move the entry's curation into the org's own YAML
        file.
        """
        curated = sync_models.load_curated_model_keys(DATA_DIR)
        with open(DATA_DIR / generated) as f:
            data = yaml.safe_load(f)
        collisions = [
            f"{org}/{model_name}"
            for org, org_data in data.items()
            for model_name in org_data.get("models", {})
            if sync_models._normalize_for_lookup(f"{org}/{model_name}") in curated
        ]
        assert collisions == []

    def test_fireworks_yml_uses_only_the_provider_scoped_org(self) -> None:
        """Every fireworks.yml key must sit under an org the fuzzy matcher skips.

        A creator-keyed org slipping into this file would be excluded from
        fuzzy matching (see PROVIDER_SCOPED_ORGS) and silently stop resolving.
        """
        with open(DATA_DIR / "fireworks.yml") as f:
            data = yaml.safe_load(f)
        assert set(data) <= PROVIDER_SCOPED_ORGS
