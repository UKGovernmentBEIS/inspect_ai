"""Which model serves a bridged request (`resolve_bridge_model`).

The sandbox bridge serves only models the eval author chose: an alias, a
`model_resolver` result, `"inspect"`, the pinned `model`, or the eval's active
model. Any other requested name goes to the active model (or the pin) with a
once-per-name warning. The in-process bridge (`allow_client_model_names=True`)
keeps routing a name to the role or model it names.
"""

import logging
from typing import Any, Iterator, NamedTuple

import pytest

from inspect_ai.agent._agent import AgentState
from inspect_ai.agent._bridge import util
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import (
    BridgeModelResolution,
    BridgeModelRoute,
    bridge_generate,
    resolve_bridge_model,
    resolve_inspect_model,
)
from inspect_ai.model import ChatMessageUser, Model, ModelResolver, get_model
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    active_model_context_var,
    init_active_model,
    init_model_roles,
)

ACTIVE = "mockllm/active"
GRADER = "mockllm/grader-model"
PINNED = "mockllm/pinned"
ALIAS_TARGET = "mockllm/alias-target"
RESOLVER_TARGET = "mockllm/resolver-target"


@pytest.fixture(autouse=True)
def _isolate_active_model() -> Iterator[None]:
    """``init_active_model()`` sets a process-wide contextvar; don't leak it.

    Same idiom as ``tests/agent/test_bridge_generate_config_propagation.py``.
    """
    token = active_model_context_var.set(active_model_context_var.get(None))
    try:
        yield
    finally:
        active_model_context_var.reset(token)
        init_model_roles({})


@pytest.fixture(autouse=True)
def _reset_redirect_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(util, "_redirect_warned", set())


def _make_active(spec: str = ACTIVE) -> Model:
    active = get_model(spec)
    init_active_model(active, GenerateConfig())
    return active


def _resolver(name: str) -> str | None:
    return RESOLVER_TARGET if name == "openai/resolve-me" else None


def _resolve(
    requested: str,
    *,
    provider: str = "openai",
    model: str | None = None,
    allow_client_model_names: bool = False,
) -> BridgeModelResolution:
    return resolve_bridge_model(
        requested,
        model_aliases={"my-alias": ALIAS_TARGET},
        model_resolver=_resolver,
        model=model,
        allow_client_model_names=allow_client_model_names,
        provider=provider,
    )


class Row(NamedTuple):
    requested: str
    provider: str
    expected: str
    """'A' (the active instance), 'D' (the pin target), or a model spec."""
    route: BridgeModelRoute
    redirected: bool
    active: str = ACTIVE


# rows of the routing matrix in design/bridge-model-routing.md; active model A,
# role "grader", pin target D
DEFAULT_ROWS = [
    Row("my-alias", "openai", ALIAS_TARGET, "alias", False),
    Row("resolve-me", "openai", RESOLVER_TARGET, "resolver", False),
    Row("inspect", "openai", "A", "inspect", False),
    Row("mockllm/active", "openai", "A", "active", False),
    Row("active", "openai", "A", "active", False),
    Row("active", "anthropic", "A", "active", False),
    Row("inspect/mockllm/active", "", "A", "active", False),
    Row("grader", "openai", "A", "default", True),
    Row("inspect/grader", "", "A", "default", True),
    Row("grader", "anthropic", "A", "active", False, active="mockllm/grader"),
    Row("inspect/grader", "", "A", "active", False, active="mockllm/grader"),
    Row("inspect/openai/gpt-4o-mini", "", "A", "default", True),
    Row("gpt-4o-mini", "openai", "A", "default", True),
    Row("claude-haiku-4-5", "anthropic", "A", "default", True),
    Row("unknown-model", "", "A", "default", True),
]

PINNED_ROWS = [
    Row("my-alias", "openai", ALIAS_TARGET, "alias", False),
    Row("resolve-me", "openai", RESOLVER_TARGET, "resolver", False),
    Row("inspect", "openai", "A", "inspect", False),
    Row("mockllm/active", "openai", "D", "model", True),
    Row("active", "openai", "D", "model", True),
    Row("inspect/mockllm/active", "", "D", "model", True),
    Row("grader", "openai", "D", "model", True),
    Row("inspect/grader", "", "D", "model", True),
    Row("grader", "anthropic", "D", "model", True, active="mockllm/grader"),
    Row("inspect/openai/gpt-4o-mini", "", "D", "model", True),
    Row("gpt-4o-mini", "openai", "D", "model", True),
    Row("unknown-model", "", "D", "model", True),
    # the client names the pinned model itself: not a redirect
    Row("inspect/mockllm/pinned", "", "D", "model", False),
    Row("mockllm/pinned", "openai", "D", "model", False),
    Row("pinned", "openai", "D", "model", False),
]


def _check(row: Row, model: str | None) -> None:
    active = _make_active(row.active)
    init_model_roles({"grader": get_model(GRADER)})
    result = _resolve(row.requested, provider=row.provider, model=model)
    if row.expected == "A":
        assert result.model is active
    elif row.expected == "D":
        assert str(result.model) == PINNED
    else:
        assert str(result.model) == row.expected
    assert result.route == row.route
    assert result.redirected is row.redirected
    assert result.requested == row.requested


@pytest.mark.parametrize("row", DEFAULT_ROWS, ids=lambda r: f"{r.requested}@{r.active}")
@pytest.mark.parametrize("model", [None, "inspect"])
def test_routing_matrix_default(row: Row, model: str | None) -> None:
    _check(row, model)


@pytest.mark.parametrize("row", PINNED_ROWS, ids=lambda r: f"{r.requested}@{r.active}")
@pytest.mark.parametrize("model", [f"inspect/{PINNED}", PINNED])
def test_routing_matrix_pinned(row: Row, model: str) -> None:
    _check(row, model)


@pytest.mark.parametrize(
    "model", ["inspect/mockllm/active", "mockllm/active", "active"]
)
def test_pin_spec_naming_active_model_returns_active_instance(model: str) -> None:
    active = _make_active()
    result = _resolve("gpt-4o-mini", model=model)
    assert result.model is active
    assert result.route == "model"
    assert result.redirected

    # the client naming the active model under that pin is not a redirect
    assert not _resolve("mockllm/active", model=model).redirected


def test_pin_naming_role_resolves_role() -> None:
    _make_active()
    role_model = get_model(GRADER)
    init_model_roles({"grader": role_model})
    result = _resolve("gpt-4o-mini", model="inspect/grader")
    assert result.model is role_model
    assert result.route == "model"


def test_default_route_never_constructs_the_requested_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client's name never reaches get_model() on the default route."""
    active = _make_active()
    seen: list[object] = []
    real_get_model = get_model

    def spy(*args: Any, **kwargs: Any) -> Model:
        seen.append((args, kwargs))
        return real_get_model(*args, **kwargs)

    monkeypatch.setattr(util, "get_model", spy)
    result = _resolve("inspect/openai/gpt-4o-mini")
    assert result.model is active
    assert seen == [((), {})]


def test_default_route_without_active_model_uses_inspect_eval_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_model_context_var.set(None)
    monkeypatch.setenv("INSPECT_EVAL_MODEL", "mockllm/default")
    result = _resolve("gpt-4o-mini")
    assert str(result.model) == "mockllm/default"
    assert result.route == "default"


# in-process bridge: allow_client_model_names=True keeps today's routing


@pytest.mark.parametrize(
    "requested,provider,expected,route,active_spec",
    [
        ("inspect", "openai", "A", "inspect", ACTIVE),
        ("grader", "openai", GRADER, "role", ACTIVE),
        ("inspect/grader", "", GRADER, "role", ACTIVE),
        # a role beats the active-model match when the names collide
        ("grader", "anthropic", GRADER, "role", "mockllm/grader"),
        ("inspect/mockllm/active", "", "A", "active", ACTIVE),
        ("active", "openai", "A", "active", ACTIVE),
        ("inspect/mockllm/other", "", "mockllm/other", "passthrough", ACTIVE),
        ("other", "mockllm", "mockllm/other", "passthrough", ACTIVE),
        ("my-alias", "openai", ALIAS_TARGET, "alias", ACTIVE),
        ("resolve-me", "openai", RESOLVER_TARGET, "resolver", ACTIVE),
    ],
)
def test_in_process_routing_unchanged(
    requested: str,
    provider: str,
    expected: str,
    route: BridgeModelRoute,
    active_spec: str,
) -> None:
    active = _make_active(active_spec)
    init_model_roles({"grader": get_model(GRADER)})
    result = _resolve(requested, provider=provider, allow_client_model_names=True)
    if expected == "A":
        assert result.model is active
    else:
        assert str(result.model) == expected
    assert result.route == route
    assert not result.redirected


def test_in_process_pin_still_wins() -> None:
    _make_active()
    result = _resolve(
        "inspect/mockllm/other",
        provider="",
        model=PINNED,
        allow_client_model_names=True,
    )
    assert str(result.model) == PINNED
    assert result.route == "model"


def test_client_model_names_closed_by_default() -> None:
    assert not AgentBridge(AgentState(messages=[])).allow_client_model_names
    sandbox_bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
    )
    assert not sandbox_bridge.allow_client_model_names


async def test_agent_bridge_allows_client_model_names() -> None:
    from inspect_ai.agent import agent_bridge

    async with agent_bridge() as bridge:
        assert bridge.allow_client_model_names


# provider qualification and precedence (kept from the original resolver tests)


class _CapturingResolver(NamedTuple):
    seen: list[str]
    resolver: ModelResolver


def _capturing_resolver() -> _CapturingResolver:
    seen: list[str] = []

    def resolver(model_name: str) -> Model:
        seen.append(model_name)
        return get_model("mockllm/model")

    return _CapturingResolver(seen=seen, resolver=resolver)


def test_bare_name_qualified_by_provider_before_resolver() -> None:
    # A bare name on a provider-specific endpoint is qualified before the resolver sees it.
    seen, resolver = _capturing_resolver()
    resolve_inspect_model("gpt-5.1", model_resolver=resolver, provider="openai")
    assert seen == ["openai/gpt-5.1"]


def test_already_qualified_name_left_untouched() -> None:
    # A name that already contains a provider prefix is not double-qualified.
    seen, resolver = _capturing_resolver()
    resolve_inspect_model("openai/gpt-5.1", model_resolver=resolver, provider="openai")
    assert seen == ["openai/gpt-5.1"]


def test_no_provider_leaves_bare_name() -> None:
    # Default provider="" is a no-op: the resolver still receives the raw bare name.
    seen, resolver = _capturing_resolver()
    resolve_inspect_model("gpt-5.1", model_resolver=resolver)
    assert seen == ["gpt-5.1"]


def test_alias_wins_before_provider_qualification() -> None:
    # An explicit alias short-circuits before both qualification and the resolver.
    seen, resolver = _capturing_resolver()
    result = resolve_inspect_model(
        "gpt-5.1",
        model_aliases={"gpt-5.1": "mockllm/model"},
        model_resolver=resolver,
        provider="openai",
    )
    assert seen == []
    assert isinstance(result, Model)


def test_alias_before_resolver() -> None:
    def resolver(name: str) -> Model:
        raise AssertionError("resolver must not run when an alias matches")

    result = resolve_bridge_model(
        "my-alias",
        model_aliases={"my-alias": ALIAS_TARGET},
        model_resolver=resolver,
        model=None,
        allow_client_model_names=False,
    )
    assert result.route == "alias"


def test_resolver_none_defers() -> None:
    active = _make_active()
    result = resolve_bridge_model(
        "gpt-4o",
        model_aliases=None,
        model_resolver=lambda name: None,
        model=None,
        allow_client_model_names=False,
        provider="openai",
    )
    assert result.model is active
    assert result.route == "default"


def test_no_resolver_no_pin_in_process_resolves_via_get_model_with_provider() -> None:
    # bare name + provider endpoint + no resolver + no pin resolves via get_model()
    # using the provider-qualified name, on the in-process bridge (#4897 review)
    result = _resolve("model", provider="mockllm", allow_client_model_names=True)
    assert str(result.model) == "mockllm/model"
    assert result.route == "passthrough"


def test_bare_name_matches_active_model_under_different_provider() -> None:
    """Regression vs #4706 (e9add1d85318): qualification must not defeat the active-model match.

    Eval's active model is on a different provider than the bridge endpoint (e.g.
    ``azureai/gpt-4o`` while the client hits the openai-compatible endpoint and
    sends the bare name ``gpt-4o``). Provider qualification alone would widen that
    to ``openai/gpt-4o``, which no longer matches ``azureai/gpt-4o`` or its short
    name -- so the resolver must also compare the pre-qualification raw name
    against the active model's short name.
    """
    active = _make_active("mockllm/gpt-4o")
    assert resolve_inspect_model("gpt-4o", provider="azureai") is active


def test_fallback_model_wins_over_active_model_raw_name_match() -> None:
    """An explicit pin must not be silently shadowed.

    A bare name that happens to match the active model's short name must NOT
    override an explicitly configured pin -- the operator's pin wins.
    """
    _make_active("mockllm/gpt-4o")
    result = resolve_inspect_model(
        "gpt-4o", fallback_model="mockllm/other", provider="azureai"
    )
    assert str(result) == "mockllm/other"


# the redirect warning


@pytest.fixture
def bridge_warnings(
    caplog: pytest.LogCaptureFixture,
) -> Iterator[pytest.LogCaptureFixture]:
    """Messages the resolver module logged at WARNING.

    Attached directly because `init_logger` stops the inspect_ai logger
    propagating once an earlier test has triggered it.
    """
    module_logger = logging.getLogger(util.__name__)
    module_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=module_logger.name):
            yield caplog
    finally:
        module_logger.removeHandler(caplog.handler)


async def _bridged_request(
    bridge: AgentBridge, requested: str, provider: str = "anthropic"
) -> BridgeModelResolution:
    routing = resolve_bridge_model(
        requested,
        model_aliases=bridge.model_aliases,
        model_resolver=bridge.model_resolver,
        model=bridge.model,
        allow_client_model_names=bridge.allow_client_model_names,
        provider=provider,
    )
    await bridge_generate(
        bridge,
        routing.model,
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        routing=routing,
    )
    return routing


async def test_redirect_warns_once_per_name(
    bridge_warnings: pytest.LogCaptureFixture,
) -> None:
    _make_active("mockllm/model")
    first = AgentBridge(AgentState(messages=[]))
    second = AgentBridge(AgentState(messages=[]))
    await _bridged_request(first, "claude-haiku-4-5")
    await _bridged_request(second, "claude-haiku-4-5")
    await _bridged_request(second, "claude-opus-4-1")

    assert bridge_warnings.messages == [
        "Agent bridge routed a request for model 'claude-haiku-4-5' to the eval "
        "model 'mockllm/model'. Add 'claude-haiku-4-5' to model_aliases to route "
        "it to a model of your choice.",
        "Agent bridge routed a request for model 'claude-opus-4-1' to the eval "
        "model 'mockllm/model'. Add 'claude-opus-4-1' to model_aliases to route "
        "it to a model of your choice.",
    ]


async def test_redirect_warning_names_the_pin(
    bridge_warnings: pytest.LogCaptureFixture,
) -> None:
    _make_active("mockllm/model")
    bridge = AgentBridge(AgentState(messages=[]), model=f"inspect/{PINNED}")
    await _bridged_request(bridge, "claude-haiku-4-5")
    assert bridge_warnings.messages == [
        f"Agent bridge routed a request for model 'claude-haiku-4-5' to the model "
        f"'{PINNED}'. Add 'claude-haiku-4-5' to model_aliases to route it "
        f"elsewhere; it was pinned by model='inspect/{PINNED}'."
    ]


async def test_redirect_warning_for_role_names_the_alias(
    bridge_warnings: pytest.LogCaptureFixture,
) -> None:
    _make_active("mockllm/model")
    init_model_roles({"grader": get_model(GRADER)})
    bridge = AgentBridge(AgentState(messages=[]))
    await _bridged_request(bridge, "inspect/grader")
    assert bridge_warnings.messages == [
        "Agent bridge routed a request for model 'inspect/grader' to the eval "
        "model 'mockllm/model'. 'inspect/grader' is a model role; expose it with "
        "model_aliases={'inspect/grader': get_model(role='grader')}."
    ]


async def test_redirect_warning_escapes_and_truncates_name(
    bridge_warnings: pytest.LogCaptureFixture,
) -> None:
    _make_active("mockllm/model")
    bridge = AgentBridge(AgentState(messages=[]))
    await _bridged_request(bridge, "x\n" + "y" * 300)
    assert len(bridge_warnings.messages) == 1
    assert "\n" not in bridge_warnings.messages[0]
    assert "'x\\n" + "y" * 198 + "...'" in bridge_warnings.messages[0]
    assert "y" * 199 not in bridge_warnings.messages[0]


async def test_redirect_warning_cap(bridge_warnings: pytest.LogCaptureFixture) -> None:
    _make_active("mockllm/model")
    bridge = AgentBridge(AgentState(messages=[]))
    for i in range(util._MAX_REDIRECT_WARNINGS + 3):
        await _bridged_request(bridge, f"model-{i}")

    assert len(bridge_warnings.messages) == util._MAX_REDIRECT_WARNINGS + 1
    assert "further redirects are not reported" in bridge_warnings.messages[-1]
    assert "requested_model" in bridge_warnings.messages[-1]


async def test_active_and_alias_hits_do_not_warn(
    bridge_warnings: pytest.LogCaptureFixture,
) -> None:
    _make_active("mockllm/model")
    bridge = AgentBridge(
        AgentState(messages=[]), model_aliases={"my-alias": ALIAS_TARGET}
    )
    for requested in ["inspect", "model", "mockllm/model", "my-alias"]:
        await _bridged_request(bridge, requested)
    assert bridge_warnings.messages == []
