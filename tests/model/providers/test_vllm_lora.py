"""Tests for vLLM LoRA adapter support."""

import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model
from inspect_ai.model._providers._vllm_lora import (
    VLLMServerInfo,
    parse_vllm_model,
)
from inspect_ai.solver import solver


class TestParseVLLMModel:
    """Tests for parse_vllm_model function."""

    def test_base_model_only(self) -> None:
        """Test parsing a model name without adapter."""
        base, adapter_path, adapter_name = parse_vllm_model("meta-llama/Llama-3-8B")
        assert base == "meta-llama/Llama-3-8B"
        assert adapter_path is None
        assert adapter_name is None

    def test_with_hf_adapter(self) -> None:
        """Test parsing a model name with HuggingFace adapter."""
        base, adapter_path, adapter_name = parse_vllm_model(
            "meta-llama/Llama-3-8B:myorg/my-lora-adapter"
        )
        assert base == "meta-llama/Llama-3-8B"
        assert adapter_path == "myorg/my-lora-adapter"
        assert adapter_name == "myorg_my-lora-adapter"

    def test_with_local_adapter(self) -> None:
        """Test parsing a model name with local path adapter."""
        base, adapter_path, adapter_name = parse_vllm_model(
            "meta-llama/Llama-3-8B:/path/to/adapter"
        )
        assert base == "meta-llama/Llama-3-8B"
        assert adapter_path == "/path/to/adapter"
        assert adapter_name == "_path_to_adapter"

    def test_with_relative_path_adapter(self) -> None:
        """Test parsing a model name with relative path adapter."""
        base, adapter_path, adapter_name = parse_vllm_model("llama:./local/adapter")
        assert base == "llama"
        assert adapter_path == "./local/adapter"
        assert adapter_name == "._local_adapter"

    def test_simple_model_name(self) -> None:
        """Test parsing a simple model name without slashes."""
        base, adapter_path, adapter_name = parse_vllm_model("gpt2")
        assert base == "gpt2"
        assert adapter_path is None
        assert adapter_name is None

    def test_nested_hf_path(self) -> None:
        """Test parsing with deeply nested HF paths."""
        base, adapter_path, adapter_name = parse_vllm_model(
            "org/model:other-org/sub/adapter"
        )
        assert base == "org/model"
        assert adapter_path == "other-org/sub/adapter"
        assert adapter_name == "other-org_sub_adapter"


class TestVLLMServerInfo:
    """Tests for VLLMServerInfo dataclass."""

    def test_get_adapter_lock_creates_new(self) -> None:
        """Test that get_adapter_lock creates new locks."""
        server_info = VLLMServerInfo(
            base_url="http://localhost:8000/v1",
            api_key="test-key",
        )
        lock1 = server_info.get_adapter_lock("adapter1")
        lock2 = server_info.get_adapter_lock("adapter2")

        assert lock1 is not lock2
        assert "adapter1" in server_info._adapter_locks
        assert "adapter2" in server_info._adapter_locks

    def test_get_adapter_lock_returns_same(self) -> None:
        """Test that get_adapter_lock returns same lock for same adapter."""
        server_info = VLLMServerInfo(
            base_url="http://localhost:8000/v1",
            api_key="test-key",
        )
        lock1 = server_info.get_adapter_lock("adapter1")
        lock2 = server_info.get_adapter_lock("adapter1")

        assert lock1 is lock2

    def test_loaded_adapters_tracking(self) -> None:
        """Test that loaded_adapters set works correctly."""
        server_info = VLLMServerInfo(
            base_url="http://localhost:8000/v1",
            api_key="test-key",
        )

        assert len(server_info.loaded_adapters) == 0

        server_info.loaded_adapters.add("adapter1")
        server_info.loaded_adapters.add("adapter2")

        assert "adapter1" in server_info.loaded_adapters
        assert "adapter2" in server_info.loaded_adapters
        assert "adapter3" not in server_info.loaded_adapters


# =============================================================================
# Integration tests - require GPU and vLLM installed
# =============================================================================

# Base model and LoRA adapter for integration tests
# Using small models to keep tests fast
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

    # Same prompt, temperature=0 -> deterministic but different outputs
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
