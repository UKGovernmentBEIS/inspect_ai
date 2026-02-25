"""Tests for vLLM LoRA adapter support."""

from unittest.mock import patch

import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from inspect_ai.model._providers._vllm_lora import (
    VLLMServer,
    _normalize_api_base,
    _vllm_servers,
    ensure_adapter_loaded,
    parse_vllm_model,
)
from inspect_ai.model._providers.vllm import VLLMAPI
from inspect_ai.solver import solver


@pytest.fixture(autouse=True)
def _clean_vllm_servers():
    """Reset global server registry between tests."""
    _vllm_servers.clear()
    yield
    _vllm_servers.clear()


# =============================================================================
# parse_vllm_model
# =============================================================================


class TestParseVLLMModel:
    """Tests for parse_vllm_model function."""

    def test_base_model_only(self) -> None:
        base, adapter_path, adapter_name = parse_vllm_model("meta-llama/Llama-3-8B")
        assert base == "meta-llama/Llama-3-8B"
        assert adapter_path is None
        assert adapter_name is None

    def test_with_hf_adapter(self) -> None:
        base, adapter_path, adapter_name = parse_vllm_model(
            "meta-llama/Llama-3-8B:myorg/my-lora-adapter"
        )
        assert base == "meta-llama/Llama-3-8B"
        assert adapter_path == "myorg/my-lora-adapter"
        assert adapter_name == "myorg_my-lora-adapter"

    def test_with_local_adapter(self) -> None:
        base, adapter_path, adapter_name = parse_vllm_model(
            "meta-llama/Llama-3-8B:/path/to/adapter"
        )
        assert base == "meta-llama/Llama-3-8B"
        assert adapter_path == "/path/to/adapter"
        assert adapter_name == "_path_to_adapter"

    def test_with_relative_path_adapter(self) -> None:
        base, adapter_path, adapter_name = parse_vllm_model("llama:./local/adapter")
        assert base == "llama"
        assert adapter_path == "./local/adapter"
        assert adapter_name == "._local_adapter"

    def test_simple_model_name(self) -> None:
        base, adapter_path, adapter_name = parse_vllm_model("gpt2")
        assert base == "gpt2"
        assert adapter_path is None
        assert adapter_name is None

    def test_nested_hf_path(self) -> None:
        base, adapter_path, adapter_name = parse_vllm_model(
            "org/model:other-org/sub/adapter"
        )
        assert base == "org/model"
        assert adapter_path == "other-org/sub/adapter"
        assert adapter_name == "other-org_sub_adapter"


# =============================================================================
# _normalize_api_base
# =============================================================================


class TestNormalizeApiBase:
    def test_strips_v1_suffix(self) -> None:
        assert (
            _normalize_api_base("http://localhost:8000/v1") == "http://localhost:8000"
        )

    def test_strips_trailing_slash_then_v1(self) -> None:
        assert (
            _normalize_api_base("http://localhost:8000/v1/") == "http://localhost:8000"
        )

    def test_leaves_bare_url_alone(self) -> None:
        assert _normalize_api_base("http://localhost:8000") == "http://localhost:8000"

    def test_strips_only_trailing_slash(self) -> None:
        assert _normalize_api_base("http://localhost:8000/") == "http://localhost:8000"

    def test_does_not_strip_v1_in_middle(self) -> None:
        assert (
            _normalize_api_base("http://localhost:8000/v1/models")
            == "http://localhost:8000/v1/models"
        )


# =============================================================================
# VLLMServer dataclass
# =============================================================================


class TestVLLMServer:
    def test_defaults(self) -> None:
        server = VLLMServer()
        assert server.enable_lora is False
        assert server.max_lora_rank is None
        assert server.base_url is None
        assert server.api_key is None
        assert server.process is None
        assert len(server.loaded_adapters) == 0


# =============================================================================
# VLLMAPI.__init__ — lazy init, shared server, LoRA accumulation
# =============================================================================


class TestVLLMAPIInit:
    """Test the __init__ path without starting a real server."""

    @patch("inspect_ai.model._providers.vllm.get_adapter_rank", return_value=None)
    def test_half_init_state(self, _mock_rank: object) -> None:
        """model_name and base_url exist immediately (before _resolve_server)."""
        api = VLLMAPI("base-model:some-adapter")

        assert api.model_name == "base-model"
        assert api.base_url is None
        assert api._server_resolved is False

    @patch("inspect_ai.model._providers.vllm.get_adapter_rank", return_value=None)
    def test_shared_server_across_instances(self, _mock_rank: object) -> None:
        """Two instances for the same base model share one VLLMServer."""
        api1 = VLLMAPI("base-model:adapter-a")
        api2 = VLLMAPI("base-model:adapter-b")

        assert api1._server is api2._server
        assert "base-model" in _vllm_servers

    @patch("inspect_ai.model._providers.vllm.get_adapter_rank", return_value=None)
    def test_different_base_models_get_separate_servers(
        self, _mock_rank: object
    ) -> None:
        api1 = VLLMAPI("model-a:adapter")
        api2 = VLLMAPI("model-b:adapter")

        assert api1._server is not api2._server

    def test_lora_accumulation_across_adapters(self) -> None:
        """max_lora_rank is the max across all adapters for a base model."""
        rank_map = {"adapter-a": 16, "adapter-b": 256}
        with patch(
            "inspect_ai.model._providers.vllm.get_adapter_rank",
            side_effect=lambda p: rank_map.get(p),
        ):
            api1 = VLLMAPI("base-model:adapter-a")
            api2 = VLLMAPI("base-model:adapter-b")

        assert api1._server.enable_lora is True
        assert api1._server.max_lora_rank == 256
        assert api2._server is api1._server

    def test_lora_accumulation_none_rank_ignored(self) -> None:
        """Adapter whose rank can't be detected doesn't clobber existing rank."""
        with patch(
            "inspect_ai.model._providers.vllm.get_adapter_rank",
            side_effect=[64, None],
        ):
            VLLMAPI("base-model:adapter-known")
            VLLMAPI("base-model:adapter-unknown")

        server = _vllm_servers["base-model"]
        assert server.enable_lora is True
        assert server.max_lora_rank == 64

    @patch("inspect_ai.model._providers.vllm.get_adapter_rank", return_value=None)
    def test_base_model_without_adapter_does_not_enable_lora(
        self, _mock_rank: object
    ) -> None:
        VLLMAPI("base-model")

        server = _vllm_servers["base-model"]
        assert server.enable_lora is False
        assert server.max_lora_rank is None

    @patch("inspect_ai.model._providers.vllm.get_adapter_rank", return_value=None)
    def test_base_url_and_port_raises(self, _mock_rank: object) -> None:
        with pytest.raises(ValueError, match="cannot both be provided"):
            VLLMAPI("model", base_url="http://x", port=8000)


# =============================================================================
# ensure_adapter_loaded
# =============================================================================


class TestEnsureAdapterLoaded:
    def _make_server(self) -> VLLMServer:
        server = VLLMServer()
        server.base_url = "http://localhost:8000/v1"
        server.api_key = "test-key"
        return server

    def test_already_loaded_skips_http(self) -> None:
        """Fast path: adapter already in loaded_adapters → no HTTP calls."""
        server = self._make_server()
        server.loaded_adapters.add("org/adapter")

        with (
            patch(
                "inspect_ai.model._providers._vllm_lora._adapter_on_server"
            ) as mock_check,
            patch("inspect_ai.model._providers._vllm_lora._load_adapter") as mock_load,
        ):
            ensure_adapter_loaded(server, "org/adapter", "org_adapter")

        mock_check.assert_not_called()
        mock_load.assert_not_called()

    def test_on_server_skips_load(self) -> None:
        """Adapter already on server → mark loaded, don't POST."""
        server = self._make_server()

        with (
            patch(
                "inspect_ai.model._providers._vllm_lora._adapter_on_server",
                return_value=True,
            ),
            patch("inspect_ai.model._providers._vllm_lora._load_adapter") as mock_load,
        ):
            ensure_adapter_loaded(server, "org/adapter", "org_adapter")

        mock_load.assert_not_called()
        assert "org/adapter" in server.loaded_adapters

    def test_not_on_server_loads_adapter(self) -> None:
        """Adapter not on server → load via HTTP POST."""
        server = self._make_server()

        with (
            patch(
                "inspect_ai.model._providers._vllm_lora._adapter_on_server",
                return_value=False,
            ),
            patch("inspect_ai.model._providers._vllm_lora._load_adapter") as mock_load,
        ):
            ensure_adapter_loaded(server, "org/adapter", "org_adapter")

        mock_load.assert_called_once_with(
            "http://localhost:8000/v1", "org_adapter", "org/adapter", "test-key"
        )
        assert "org/adapter" in server.loaded_adapters

    def test_unresolved_server_raises(self) -> None:
        """Calling before server is resolved raises RuntimeError."""
        server = VLLMServer()

        with pytest.raises(RuntimeError, match="Server must be resolved"):
            ensure_adapter_loaded(server, "org/adapter", "org_adapter")


# =============================================================================
# Integration tests - require GPU and vLLM installed
# =============================================================================

SMOL_BASE = "HuggingFaceTB/SmolLM2-135M-Instruct"
SMOL_LORA_SWEDISH = "jekunz/smollm-135m-lora-fineweb-swedish"  # r=256
SMOL_LORA_DIGEST = "soumitsr/SmolLM2-135M-Instruct-article-digestor-lora"  # r=16


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_lora_basic() -> None:
    """Test basic LoRA adapter loading and inference."""
    model = get_model(
        f"vllm/{SMOL_BASE}:{SMOL_LORA_SWEDISH}",
        config=GenerateConfig(max_tokens=10, seed=42),
        gpu_memory_utilization=0.5,
    )
    message = ChatMessageUser(content="Hej! Hur mår du?")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_base_and_lora_shared_server() -> None:
    """Test base model and two LoRA adapters sharing the same vLLM server.

    Verifies that:
    - LoRA config is computed lazily on first generate() from the model
      registry, so enable_lora is set correctly even when the base model
      (no adapter) appears first in the model list
    - max_lora_rank is auto-detected as max(256, 16) = 256 across adapters
    - All three models produce output on the same server
    - Completions differ between base and each adapter at temp=0
    """
    from inspect_ai.model._model import resolve_models

    config = GenerateConfig(max_tokens=30, temperature=0)
    models = resolve_models(
        model=[
            f"vllm/{SMOL_BASE}",
            f"vllm/{SMOL_BASE}:{SMOL_LORA_SWEDISH}",
            f"vllm/{SMOL_BASE}:{SMOL_LORA_DIGEST}",
        ],
        model_args={"gpu_memory_utilization": 0.5},
        config=config,
    )
    assert len(models) == 3
    base_model, swedish_model, digest_model = models

    message = ChatMessageUser(content="Tell me about the weather today")
    base_response = await base_model.generate(input=[message])
    swedish_response = await swedish_model.generate(input=[message])
    digest_response = await digest_model.generate(input=[message])

    assert len(base_response.completion) >= 1
    assert len(swedish_response.completion) >= 1
    assert len(digest_response.completion) >= 1
    assert base_response.completion != swedish_response.completion
    assert base_response.completion != digest_response.completion


@pytest.mark.asyncio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_lora_in_solver() -> None:
    """Test using LoRA model from inside a solver.

    This test reuses the server started by previous tests.
    """
    from inspect_ai import Task, eval_async

    lora_model = get_model(
        f"vllm/{SMOL_BASE}:{SMOL_LORA_SWEDISH}",
        config=GenerateConfig(max_tokens=20, seed=42),
        gpu_memory_utilization=0.5,
    )

    @solver
    def lora_solver():
        async def solve(state, generate):
            response = await lora_model.generate(state.messages)
            state.output = response
            state.messages.append(response.message)
            return state

        return solve

    task = Task(
        dataset=[Sample(input="Berätta om Sverige", target="Sverige")],
        solver=lora_solver(),
    )

    log = (
        await eval_async(
            task,
            model="mockllm/model",
        )
    )[0]

    assert log.status == "success"
    assert log.samples
