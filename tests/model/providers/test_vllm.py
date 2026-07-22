import pytest
from test_helpers.utils import skip_if_github_action, skip_if_no_vllm

from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    get_model,
)
from inspect_ai.model._model_info import _get_model_info_direct
from inspect_ai.model._providers.vllm import (
    CONTEXT_WINDOW_MAX_ATTEMPTS,
    VLLMAPI,
    _server_context_length,
)


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_api() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,
            top_p=0.9,
            top_k=None,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        ),
        device=0,
        # this allows us to run base models with the chat message scaffolding:
        chat_template="{% for message in messages %}{{ message.content }}{% endfor %}",
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1


def test_server_context_length_matches_model_id() -> None:
    data = {
        "data": [
            {"id": "other/model", "max_model_len": 4096},
            {"id": "my/model", "max_model_len": 8192},
        ]
    }
    assert _server_context_length(data, "my/model") == 8192


def test_server_context_length_falls_back_to_sole_entry() -> None:
    data = {"data": [{"id": "served/model", "max_model_len": 8192}]}
    assert _server_context_length(data, "unmatched") == 8192


def test_server_context_length_ambiguous_no_match_returns_none() -> None:
    data = {
        "data": [
            {"id": "a/model", "max_model_len": 4096},
            {"id": "b/model", "max_model_len": 8192},
        ]
    }
    assert _server_context_length(data, "unmatched") is None


def test_server_context_length_missing_or_empty() -> None:
    assert (
        _server_context_length({"data": [{"id": "served/model"}]}, "served/model")
        is None
    )
    assert _server_context_length({"data": []}, "x") is None
    assert _server_context_length({}, "x") is None


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stands in for ``http_client``, replaying one outcome per GET."""

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self._last: object = None
        self.calls = 0

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls += 1
        outcome = self._outcomes.pop(0) if self._outcomes else self._last
        self._last = outcome
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, _FakeResponse)
        return outcome


def _vllm_api(model_name: str, client: _FakeClient) -> VLLMAPI:
    api = VLLMAPI(model_name=model_name, base_url="http://localhost:8000/v1")
    api.base_url = "http://localhost:8000/v1"
    api.http_client = client
    return api


@pytest.fixture
def isolated_model_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep set_model_info() writes out of the process-wide registry."""
    import inspect_ai.model._model_info as _model_info

    monkeypatch.setattr(_model_info, "_custom_models", dict(_model_info._custom_models))
    monkeypatch.setattr(_model_info, "_result_cache", {})


@pytest.mark.anyio
async def test_context_window_unreachable_server_retries(
    isolated_model_registry: None,
) -> None:
    """A server that is briefly unreachable doesn't permanently latch the catalog.

    generate() itself retries through a transient connection failure, so
    latching on the first one would silently revert to the catalog window for
    the rest of the run.
    """
    client = _FakeClient(
        ConnectionError("connection refused"),
        _FakeResponse({"data": [{"id": "my/model", "max_model_len": 4096}]}),
    )
    api = _vllm_api("my/model", client)

    await api._register_context_window()
    assert api._context_window_registered is False

    await api._register_context_window()
    assert api._context_window_registered is True
    assert client.calls == 2
    registered = _get_model_info_direct("my/model")
    assert registered is not None and registered.context_length == 4096


@pytest.mark.anyio
async def test_context_window_unreachable_server_gives_up(
    isolated_model_registry: None,
) -> None:
    """Retries are bounded so an unreachable endpoint isn't re-probed forever."""
    client = _FakeClient(ConnectionError("connection refused"))
    api = _vllm_api("my/model", client)

    for _ in range(CONTEXT_WINDOW_MAX_ATTEMPTS + 2):
        await api._register_context_window()

    assert api._context_window_registered is True
    assert client.calls == CONTEXT_WINDOW_MAX_ATTEMPTS


@pytest.mark.anyio
async def test_context_window_error_response_latches(
    isolated_model_registry: None,
) -> None:
    """An HTTP response settles the question, whatever its status."""
    client = _FakeClient(_FakeResponse({}, status=404))
    api = _vllm_api("my/model", client)

    await api._register_context_window()
    await api._register_context_window()

    assert api._context_window_registered is True
    assert client.calls == 1


@pytest.mark.anyio
async def test_context_window_lookup_does_not_resolve_provider(
    isolated_model_registry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Looking up the catalog entry must not instantiate another provider.

    A model whose org prefix collides with an Inspect provider name and which
    misses the catalog (``openai/...``, ``google/...``) would otherwise import
    and construct that provider mid-generate(), just for metadata.
    """
    import inspect_ai.model._model as _model

    # recorded rather than raised: _resolve_model_info swallows any exception
    # from the resolution it attempts, so raising here would go unnoticed
    resolved: list[object] = []

    def spy(model: object, *args: object, **kwargs: object) -> object:
        resolved.append(model)
        raise ValueError("provider unavailable")

    monkeypatch.setattr(_model, "get_model", spy)

    name = "openai/gpt-oss-safeguard-20b"
    assert _get_model_info_direct(name) is None  # catalog miss

    client = _FakeClient(_FakeResponse({"data": [{"id": name, "max_model_len": 4096}]}))
    await _vllm_api(name, client)._register_context_window()

    assert resolved == []
    registered = _get_model_info_direct(name)
    assert registered is not None and registered.context_length == 4096


@pytest.mark.anyio
async def test_context_window_overrides_explicit_input_tokens(
    isolated_model_registry: None,
) -> None:
    """The served window replaces a catalog entry's explicit input_tokens.

    ``ModelInfo.input_tokens`` prefers the private override read from the
    catalog YAML over ``context_length``, and that is the value compaction
    consumes, so registering the served window has to clear it. max_model_len
    bounds input and output together, so it caps input capacity too.
    """
    catalog = _get_model_info_direct("openai/gpt-5.1")
    assert catalog is not None
    assert catalog.input_tokens != catalog.context_length  # the trap

    client = _FakeClient(
        _FakeResponse({"data": [{"id": "openai/gpt-5.1", "max_model_len": 8192}]})
    )
    api = _vllm_api("openai/gpt-5.1", client)

    await api._register_context_window()

    registered = _get_model_info_direct("openai/gpt-5.1")
    assert registered is not None
    assert registered.context_length == 8192
    assert registered.input_tokens == 8192


@pytest.mark.anyio
@skip_if_github_action
@skip_if_no_vllm
async def test_vllm_disable_chat_template() -> None:
    model = get_model(
        "vllm/EleutherAI/pythia-70m",
        config=GenerateConfig(
            max_tokens=1,
            seed=42,
            temperature=0.7,
        ),
        device=0,
        use_chat_template=False,
    )
    message = ChatMessageUser(content="Lorem ipsum dolor")
    response = await model.generate(input=[message])
    assert len(response.completion) >= 1
