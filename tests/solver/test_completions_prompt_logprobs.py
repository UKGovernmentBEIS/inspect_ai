"""Tests for the completions_prompt_logprobs solver."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inspect_ai.model._openai import parse_vllm_prompt_logprobs_raw
from inspect_ai.solver._completions_prompt_logprobs import (
    _parse_completion_logprobs,
    _resolve_base_url,
    _resolve_model_id,
    completions_prompt_logprobs,
)

# ---------------------------------------------------------------------------
# _resolve_base_url
# ---------------------------------------------------------------------------


class TestResolveBaseUrl:
    async def test_override_with_v1_suffix(self) -> None:
        assert (
            await _resolve_base_url("http://localhost:30000/v1")
            == "http://localhost:30000/v1"
        )

    async def test_override_without_v1_suffix(self) -> None:
        assert (
            await _resolve_base_url("http://localhost:30000")
            == "http://localhost:30000/v1"
        )

    async def test_override_strips_trailing_slash(self) -> None:
        assert (
            await _resolve_base_url("http://localhost:30000/v1/")
            == "http://localhost:30000/v1"
        )

    async def test_override_no_v1_trailing_slash(self) -> None:
        assert (
            await _resolve_base_url("http://localhost:30000/")
            == "http://localhost:30000/v1"
        )

    async def test_no_override_no_model_raises(self) -> None:
        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.get_model",
            side_effect=RuntimeError("no model"),
        ):
            with pytest.raises(RuntimeError, match="no model"):
                await _resolve_base_url(None)

    async def test_no_override_model_without_api_raises(self) -> None:
        mock_model = MagicMock(spec=[])  # no 'api' attribute
        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.get_model",
            return_value=mock_model,
        ):
            with pytest.raises(RuntimeError, match="no 'api' attribute"):
                await _resolve_base_url(None)

    async def test_no_override_model_with_base_url(self) -> None:
        mock_api = MagicMock()
        mock_api.base_url = "http://auto:8000/v1"
        mock_api._ensure_server_started = AsyncMock()
        mock_model = MagicMock()
        mock_model.api = mock_api
        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.get_model",
            return_value=mock_model,
        ):
            assert await _resolve_base_url(None) == "http://auto:8000/v1"


# ---------------------------------------------------------------------------
# _resolve_model_id
# ---------------------------------------------------------------------------


class TestResolveModelId:
    def test_override(self) -> None:
        assert _resolve_model_id("my-model") == "my-model"

    def test_from_active_model(self) -> None:
        mock_api = MagicMock()
        mock_api.model_name = "auto-detected-model"
        mock_model = MagicMock()
        mock_model.api = mock_api
        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.get_model",
            return_value=mock_model,
        ):
            assert _resolve_model_id(None) == "auto-detected-model"


# ---------------------------------------------------------------------------
# parse_vllm_prompt_logprobs_raw
# ---------------------------------------------------------------------------


class TestParsePromptLogprobsRaw:
    def test_empty_list(self) -> None:
        assert parse_vllm_prompt_logprobs_raw([]) is None

    def test_all_none_entries(self) -> None:
        assert parse_vllm_prompt_logprobs_raw([None, None]) is None

    def test_single_token(self) -> None:
        raw: list[Any] = [
            None,  # BOS
            {"739": {"logprob": -3.49, "rank": 6, "decoded_token": "The"}},
        ]
        result = parse_vllm_prompt_logprobs_raw(raw)
        assert result is not None
        assert len(result.content) == 1
        assert result.content[0].token == "The"
        assert result.content[0].logprob == pytest.approx(-3.49)
        assert result.content[0].top_logprobs is None

    def test_multiple_tokens(self) -> None:
        raw: list[Any] = [
            None,
            {"739": {"logprob": -3.49, "rank": 6, "decoded_token": "The"}},
            {"6827": {"logprob": -10.80, "rank": 2007, "decoded_token": " capital"}},
            {"297": {"logprob": -1.13, "rank": 1, "decoded_token": " of"}},
        ]
        result = parse_vllm_prompt_logprobs_raw(raw)
        assert result is not None
        assert len(result.content) == 3
        assert [lp.token for lp in result.content] == ["The", " capital", " of"]

    def test_with_top_n_alternatives(self) -> None:
        raw: list[Any] = [
            None,
            {
                "739": {"logprob": -3.49, "rank": 6, "decoded_token": "The"},
                "16": {"logprob": -1.62, "rank": 1, "decoded_token": "#"},
            },
        ]
        result = parse_vllm_prompt_logprobs_raw(raw)
        assert result is not None
        assert len(result.content) == 1
        lp = result.content[0]
        assert lp.token == "The"
        assert lp.logprob == pytest.approx(-3.49)
        assert lp.top_logprobs is not None
        assert len(lp.top_logprobs) == 1
        assert lp.top_logprobs[0].token == "#"
        assert lp.top_logprobs[0].logprob == pytest.approx(-1.62)

    def test_non_dict_entries_skipped(self) -> None:
        raw: list[Any] = [
            None,
            "bad",
            42,
            {"1": {"logprob": -1.0, "decoded_token": "ok"}},
        ]
        result = parse_vllm_prompt_logprobs_raw(raw)
        assert result is not None
        assert len(result.content) == 1
        assert result.content[0].token == "ok"

    def test_malformed_entry_missing_logprob_raises(self) -> None:
        raw: list[Any] = [{"1": {"decoded_token": "bad"}}]  # missing logprob
        with pytest.raises(KeyError):
            parse_vllm_prompt_logprobs_raw(raw)


# ---------------------------------------------------------------------------
# _parse_completion_logprobs
# ---------------------------------------------------------------------------


class TestParseCompletionLogprobs:
    def test_none_input(self) -> None:
        assert _parse_completion_logprobs(None) is None

    def test_empty_tokens(self) -> None:
        sdk_lp = SimpleNamespace(tokens=[], token_logprobs=[], top_logprobs=[])
        assert _parse_completion_logprobs(sdk_lp) is None

    def test_basic_logprobs(self) -> None:
        sdk_lp = SimpleNamespace(
            tokens=[" Paris", "."],
            token_logprobs=[-0.595, -0.837],
            top_logprobs=None,
        )
        result = _parse_completion_logprobs(sdk_lp)
        assert result is not None
        assert len(result.content) == 2
        assert result.content[0].token == " Paris"
        assert result.content[0].logprob == pytest.approx(-0.595)
        assert result.content[0].top_logprobs is None
        assert result.content[1].token == "."

    def test_with_top_logprobs(self) -> None:
        sdk_lp = SimpleNamespace(
            tokens=[" Paris"],
            token_logprobs=[-0.595],
            top_logprobs=[{" Paris": -0.595, " London": -2.1}],
        )
        result = _parse_completion_logprobs(sdk_lp)
        assert result is not None
        lp = result.content[0]
        assert lp.top_logprobs is not None
        assert len(lp.top_logprobs) == 2
        assert lp.top_logprobs[0].token == " Paris"
        assert lp.top_logprobs[1].token == " London"

    def test_null_logprob_skipped(self) -> None:
        """BOS token has null logprob in echo mode."""
        sdk_lp = SimpleNamespace(
            tokens=["[BOS]", "The"],
            token_logprobs=[None, -3.49],
            top_logprobs=None,
        )
        result = _parse_completion_logprobs(sdk_lp)
        assert result is not None
        assert len(result.content) == 1
        assert result.content[0].token == "The"


# ---------------------------------------------------------------------------
# completions_prompt_logprobs solver (solve function)
# ---------------------------------------------------------------------------


def _make_completion_response(
    text: str = " Paris",
    finish_reason: str = "length",
    prompt_logprobs: list[Any] | None = None,
    logprobs: dict[str, Any] | None = None,
    prompt_tokens: int = 6,
    completion_tokens: int = 1,
    total_tokens: int = 7,
) -> Any:
    """Build a fake openai.types.Completion-like object."""
    choice = SimpleNamespace(
        index=0,
        text=text,
        finish_reason=finish_reason,
        logprobs=(SimpleNamespace(**logprobs) if logprobs else None),
        model_extra=(
            {"prompt_logprobs": prompt_logprobs}
            if prompt_logprobs is not None
            else None
        ),
    )
    return SimpleNamespace(
        id="cmpl-test",
        model="TestModel",
        choices=[choice],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


def _make_task_state(input_text: str = "The capital of France is Paris") -> Any:
    """Build a minimal TaskState-like object for testing."""
    state = MagicMock()
    state._input = input_text
    state.input_text = input_text
    state.output = None
    return state


class TestVllmCompletionsSolve:
    async def test_basic_completion(self) -> None:
        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(
            return_value=_make_completion_response()
        )

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ):
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
            )
            state = _make_task_state()
            result = await s(state=state, generate=AsyncMock())

        assert result.output is not None
        assert result.output.model == "TestModel"
        assert len(result.output.choices) == 1
        assert result.output.choices[0].message.content == " Paris"
        assert result.output.choices[0].stop_reason == "max_tokens"

    async def test_prompt_logprobs_parsed(self) -> None:
        prompt_lps: list[Any] = [
            None,
            {"739": {"logprob": -3.49, "rank": 6, "decoded_token": "The"}},
            {"342": {"logprob": -1.24, "rank": 2, "decoded_token": " is"}},
        ]
        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(
            return_value=_make_completion_response(prompt_logprobs=prompt_lps)
        )

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ):
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
            )
            state = _make_task_state()
            result = await s(state=state, generate=AsyncMock())

        plps = result.output.choices[0].prompt_logprobs
        assert plps is not None
        assert len(plps.content) == 2
        assert plps.content[0].token == "The"
        assert plps.content[1].token == " is"

    async def test_completion_logprobs_parsed(self) -> None:
        logprobs_data = {
            "tokens": [" Paris"],
            "token_logprobs": [-0.595],
            "top_logprobs": [{" Paris": -0.595}],
            "text_offset": [0],
        }
        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(
            return_value=_make_completion_response(logprobs=logprobs_data)
        )

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ):
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
            )
            state = _make_task_state()
            result = await s(state=state, generate=AsyncMock())

        lps = result.output.choices[0].logprobs
        assert lps is not None
        assert len(lps.content) == 1
        assert lps.content[0].token == " Paris"
        assert lps.content[0].logprob == pytest.approx(-0.595)

    async def test_usage_parsed(self) -> None:
        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(
            return_value=_make_completion_response(
                prompt_tokens=7,
                completion_tokens=1,
                total_tokens=8,
            )
        )

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ):
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
            )
            state = _make_task_state()
            result = await s(state=state, generate=AsyncMock())

        assert result.output.usage is not None
        assert result.output.usage.input_tokens == 7
        assert result.output.usage.output_tokens == 1
        assert result.output.usage.total_tokens == 8

    async def test_empty_choices(self) -> None:
        response = SimpleNamespace(
            id="cmpl-test",
            model="TestModel",
            choices=[],
            usage=None,
        )
        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(return_value=response)

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ):
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
            )
            state = _make_task_state()
            result = await s(state=state, generate=AsyncMock())

        assert result.output.choices == []

    async def test_not_found_error_raises_runtime_error(self) -> None:
        import httpx
        from openai import NotFoundError

        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(
            side_effect=NotFoundError(
                message="Not Found",
                response=httpx.Response(
                    status_code=404,
                    request=httpx.Request(
                        method="POST", url="http://localhost/v1/completions"
                    ),
                ),
                body={"error": {"message": "Not Found"}},
            )
        )

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ):
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
            )
            state = _make_task_state()
            with pytest.raises(RuntimeError, match="does not support /v1/completions"):
                await s(state=state, generate=AsyncMock())

    async def test_request_params_passed_correctly(self) -> None:
        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(
            return_value=_make_completion_response()
        )

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ):
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
                max_tokens=5,
                temperature=0.5,
                prompt_logprobs=2,
                logprobs=3,
            )
            state = _make_task_state("Hello world")
            await s(state=state, generate=AsyncMock())

        call_kwargs = mock_client.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "TestModel"
        assert call_kwargs["prompt"] == "Hello world"
        assert call_kwargs["max_tokens"] == 5
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["logprobs"] == 3
        assert call_kwargs["extra_body"] == {"prompt_logprobs": 2}

    async def test_client_reused_across_calls(self) -> None:
        mock_client = AsyncMock()
        mock_client.completions.create = AsyncMock(
            return_value=_make_completion_response()
        )

        with patch(
            "inspect_ai.solver._completions_prompt_logprobs.AsyncOpenAI",
            return_value=mock_client,
        ) as mock_constructor:
            s = completions_prompt_logprobs(
                base_url="http://localhost:30000/v1",
                model_id="TestModel",
            )
            state1 = _make_task_state()
            state2 = _make_task_state()
            await s(state=state1, generate=AsyncMock())
            await s(state=state2, generate=AsyncMock())

        # AsyncOpenAI constructed only once
        assert mock_constructor.call_count == 1
        # But completions.create called twice
        assert mock_client.completions.create.call_count == 2

    async def test_multi_message_input_raises(self) -> None:
        s = completions_prompt_logprobs(
            base_url="http://localhost:30000/v1",
            model_id="TestModel",
        )
        state = MagicMock()
        state._input = [{"role": "user", "content": "hello"}]
        state.output = None
        with pytest.raises(TypeError, match="plain string"):
            await s(state=state, generate=AsyncMock())
