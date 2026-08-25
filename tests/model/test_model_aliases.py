import logging
import re
from typing import Any, Iterator, NoReturn

import pytest
from tenacity import RetryCallState
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalLog
from inspect_ai.model import (
    ModelCall,
    ModelCost,
    ModelInfo,
    ModelName,
    ModelOutput,
    ModelUsage,
    get_model,
    model_aliases_from_log,
    set_model_info,
)
from inspect_ai.model._model_alias import (
    MODEL_ALIASES_ENV_VAR,
    init_model_aliases,
    model_aliases,
    parse_model_aliases,
    redact_aliased_model,
    redact_aliased_model_call,
    redact_aliased_model_exception,
)
from inspect_ai.model._model_info import clear_model_info_cache
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.model._retry import ModelRetryConfig, model_retry_config
from inspect_ai.scorer import CORRECT, includes, model_graded_qa
from inspect_ai.solver import generate

ALIAS = "safe/name"
TARGET = "mockllm/model"


@pytest.fixture(autouse=True)
def reset_model_aliases(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(MODEL_ALIASES_ENV_VAR, raising=False)
    init_model_aliases(None)
    yield
    init_model_aliases(None)


# parsing


def test_parse_model_aliases_single_pair() -> None:
    assert parse_model_aliases([f"{ALIAS}={TARGET}"]) == {ALIAS: TARGET}


def test_parse_model_aliases_multiple_pairs() -> None:
    expected = {ALIAS: TARGET, "other/alias": "mockllm/model2"}
    # repeated CLI args
    assert (
        parse_model_aliases([f"{ALIAS}={TARGET}", "other/alias=mockllm/model2"])
        == expected
    )
    # comma-separated (env var form)
    assert (
        parse_model_aliases([f"{ALIAS}={TARGET},other/alias=mockllm/model2"])
        == expected
    )
    # whitespace tolerated
    assert (
        parse_model_aliases([f" {ALIAS} = {TARGET} , other/alias=mockllm/model2 ,"])
        == expected
    )


def test_parse_model_aliases_empty() -> None:
    assert parse_model_aliases(None) == {}
    assert parse_model_aliases([]) == {}


@pytest.mark.parametrize(
    "value",
    [
        "safe/name",  # no target
        "=mockllm/model",  # no alias
        "safe/name=",  # empty target
        "name=mockllm/model",  # alias not fully qualified
        "safe/name=model",  # target not fully qualified
        "safe/=mockllm/model",  # empty model_name part
        "/name=mockllm/model",  # empty api_name part
    ],
)
def test_parse_model_aliases_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_model_aliases([value])


def test_parse_model_aliases_conflicting_duplicate() -> None:
    with pytest.raises(ValueError):
        parse_model_aliases([f"{ALIAS}={TARGET}", f"{ALIAS}=mockllm/model2"])
    # non-conflicting duplicate is allowed
    assert parse_model_aliases([f"{ALIAS}={TARGET}", f"{ALIAS}={TARGET}"]) == {
        ALIAS: TARGET
    }


def test_model_aliases_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        MODEL_ALIASES_ENV_VAR, f"{ALIAS}={TARGET},other/alias=mockllm/model2"
    )
    assert model_aliases() == {ALIAS: TARGET, "other/alias": "mockllm/model2"}
    # explicit initialization takes precedence over the environment
    init_model_aliases({ALIAS: TARGET})
    assert model_aliases() == {ALIAS: TARGET}


# get_model()


def test_get_model_alias_dispatch() -> None:
    init_model_aliases({ALIAS: TARGET})
    model = get_model(ALIAS)

    # dispatched to the real provider
    assert isinstance(model.api, MockLLM)
    assert model.api.model_name == "model"

    # displayed/recorded as the alias
    assert str(model) == ALIAS
    assert model.name == "name"
    model_name = ModelName(model)
    assert model_name.api == "safe"
    assert model_name.name == "name"


def test_get_model_alias_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MODEL_ALIASES_ENV_VAR, f"{ALIAS}={TARGET}")
    model = get_model(ALIAS)
    assert isinstance(model.api, MockLLM)
    assert str(model) == ALIAS


def test_get_model_alias_with_role() -> None:
    init_model_aliases({ALIAS: TARGET})
    model = get_model(ALIAS, role="grader")
    assert isinstance(model.api, MockLLM)
    assert str(model) == ALIAS
    assert model.role == "grader"


def test_get_model_real_name_unaffected() -> None:
    init_model_aliases({ALIAS: TARGET})
    model = get_model(TARGET)
    assert str(model) == TARGET
    assert model.name == "model"


def test_get_model_alias_memoized_distinctly() -> None:
    init_model_aliases({"safe/none": "none/none"})
    aliased = get_model("safe/none")
    real = get_model("none/none")
    assert aliased is not real
    assert str(aliased) == "safe/none"
    assert str(real) == "none/none"


@skip_if_trio
async def test_generate_records_alias() -> None:
    init_model_aliases({ALIAS: TARGET})
    model = get_model(
        ALIAS,
        custom_outputs=[
            ModelOutput.from_content(model="mockllm", content="Hello World")
        ],
    )
    output = await model.generate("Just reply with the greeting")
    assert output.model == ALIAS
    assert output.message.model == ALIAS


# eval log


@skip_if_trio
def test_eval_log_records_alias_only(tmp_path) -> None:
    init_model_aliases({ALIAS: TARGET, "other/alias": TARGET})
    model = get_model(
        ALIAS,
        custom_outputs=[
            ModelOutput.from_content(model="mockllm", content="Hello World")
        ],
    )
    task = Task(
        dataset=[Sample(input="Just reply with the greeting", target="Hello World")],
        solver=[generate()],
        scorer=includes(),
    )
    log = eval(
        task,
        model=model,
        model_roles={"grader": "other/alias"},
        log_dir=tmp_path.as_posix(),
        display="none",
    )[0]
    assert log.status == "success"
    assert log.samples

    # model fields carry the alias only
    assert log.eval.model == ALIAS
    assert log.eval.model_roles is not None
    assert log.eval.model_roles["grader"].model == "other/alias"
    sample = log.samples[0]
    assert sample.output.model == ALIAS
    assert sample.output.message.model == ALIAS
    assert list(sample.model_usage.keys()) == [ALIAS]
    assert list(log.stats.model_usage.keys()) == [ALIAS]

    # model events (and raw model calls) carry the alias only
    model_events = [event for event in sample.events if isinstance(event, ModelEvent)]
    assert model_events
    for event in model_events:
        assert event.model == ALIAS
        assert event.call is not None
        assert event.call.request["model"] == "name"

    # the alias mapping is recorded (base64-encoded) and recoverable
    assert log.eval.model_aliases is not None
    assert model_aliases_from_log(log.eval.model_aliases) == {
        ALIAS: TARGET,
        "other/alias": TARGET,
    }

    # the real model name appears nowhere in plaintext in the log
    log_json = log.model_dump_json(exclude_none=True)
    assert not re.search("mockllm", log_json)


@skip_if_trio
def test_model_graded_scorer_resolves_alias(tmp_path) -> None:
    grader_alias = "grader/alias"
    init_model_aliases({ALIAS: TARGET, grader_alias: TARGET})
    model = get_model(
        ALIAS,
        custom_outputs=[
            ModelOutput.from_content(model="mockllm", content="Hello World")
        ],
    )
    # note: the grader Model (including its custom_outputs model_args) is
    # serialized into the log's scorer params, so the fixture output uses a
    # neutral model string (generate() replaces it with the alias regardless)
    grader = get_model(
        grader_alias,
        custom_outputs=[ModelOutput.from_content(model="grader", content="GRADE: C")],
    )
    task = Task(
        dataset=[Sample(input="Just reply with the greeting", target="Hello World")],
        solver=[generate()],
        scorer=model_graded_qa(model=grader),
    )
    log = eval(
        task,
        model=model,
        log_dir=tmp_path.as_posix(),
        display="none",
    )[0]
    assert log.status == "success"
    assert log.samples

    # the grader scored the sample
    sample = log.samples[0]
    assert sample.scores is not None
    assert sample.scores["model_graded_qa"].value == CORRECT

    # model usage and events for the grader carry the alias only
    assert set(sample.model_usage.keys()) == {ALIAS, grader_alias}
    grader_events = [
        event
        for event in sample.events
        if isinstance(event, ModelEvent) and event.model == grader_alias
    ]
    assert grader_events
    for event in grader_events:
        assert event.output.model == grader_alias

    # the real model name appears nowhere in plaintext in the log
    log_json = log.model_dump_json(exclude_none=True)
    assert not re.search("mockllm", log_json)


# redaction


def test_redact_aliased_model_word_boundaries() -> None:
    alias, model = "safe/name", "openai/gpt-4o"

    # the aliased model is redacted, fully qualified and bare
    assert redact_aliased_model('"model": "openai/gpt-4o"', alias, model) == (
        '"model": "safe/name"'
    )
    # a bare name is replaced with the bare alias name
    assert redact_aliased_model('"model": "gpt-4o"', alias, model) == (
        '"model": "name"'
    )
    # ...including when embedded in a URL path
    assert (
        redact_aliased_model("https://host/v1/openai/gpt-4o/chat", alias, model)
        == "https://host/v1/safe/name/chat"
    )
    # ...and when followed by sentence punctuation
    assert redact_aliased_model("model openai/gpt-4o.", alias, model) == (
        "model safe/name."
    )

    # a longer, unrelated model identifier is left intact
    assert redact_aliased_model("gpt-4o-mini", alias, model) == "gpt-4o-mini"
    assert redact_aliased_model("openai/gpt-4o-mini", alias, model) == (
        "openai/gpt-4o-mini"
    )
    assert redact_aliased_model("gpt-4o-mini-2024", alias, model) == "gpt-4o-mini-2024"

    # a version suffix is part of the identifier, not a boundary
    assert redact_aliased_model("gpt-4.1", "safe/name", "openai/gpt-4") == "gpt-4.1"


def test_redact_aliased_model_call_preserves_conversation_text() -> None:
    alias, model = "safe/name", "openai/gpt-4o"
    call = ModelCall(
        request={
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "which is better, gpt-4o or gpt-4o-mini?"}
            ],
            "metadata": {"deployment": "openai/gpt-4o"},
        },
        response={
            "model": "gpt-4o-2024-11-20",
            "choices": [{"message": {"content": "I am gpt-4o."}}],
        },
    )
    redact_aliased_model_call(call, alias, model)

    # protocol metadata is redacted
    assert call.request["model"] == "name"
    assert call.request["metadata"] == {"deployment": alias}
    assert call.response is not None
    # a longer identifier is untouched by the boundary match
    assert call.response["model"] == "gpt-4o-2024-11-20"

    # prompt and model-generated text are preserved verbatim, matching the
    # treatment of the model event's input/output
    messages = call.request["messages"]
    assert isinstance(messages, list)
    assert messages[0]["content"] == "which is better, gpt-4o or gpt-4o-mini?"  # type: ignore[index,call-overload]
    choices = call.response["choices"]
    assert isinstance(choices, list)
    assert choices[0]["message"]["content"] == "I am gpt-4o."  # type: ignore[index,call-overload]


def test_redact_aliased_model_exception_preserves_type_and_chain() -> None:
    class ProviderError(Exception):
        def __init__(self, message: str) -> None:
            super().__init__(message)
            self.message = message

    try:
        try:
            raise ValueError("model mockllm/model not found")
        except ValueError as cause:
            raise ProviderError("The model mockllm/model had an error") from cause
    except ProviderError as ex:
        redacted = redact_aliased_model_exception(ex, ALIAS, TARGET)

        # redacted in place: same object, same type (so retry classification
        # and `except` clauses upstream keep working)
        assert redacted is ex
        assert type(redacted) is ProviderError
        assert TARGET not in str(redacted)
        assert ALIAS in str(redacted)
        assert TARGET not in redacted.message
        # the cause chain is redacted too (it is rendered into the traceback)
        assert ex.__cause__ is not None
        assert TARGET not in str(ex.__cause__)
        assert ALIAS in str(ex.__cause__)


# raised (rather than returned) provider errors


@skip_if_trio
def test_raised_provider_error_redacted_in_log(tmp_path, monkeypatch) -> None:
    init_model_aliases({ALIAS: TARGET})

    async def raise_error(self: MockLLM, *args: Any, **kwargs: Any) -> NoReturn:
        raise RuntimeError(f"The model {TARGET} had an error")

    monkeypatch.setattr(MockLLM, "generate", raise_error)

    task = Task(
        dataset=[Sample(input="Just reply with the greeting", target="Hello World")],
        solver=[generate()],
        scorer=includes(),
    )
    log = eval(
        task,
        model=ALIAS,
        log_dir=tmp_path.as_posix(),
        display="none",
        fail_on_error=False,
        retry_on_error=0,
    )[0]

    assert log.samples
    error = log.samples[0].error
    assert error is not None
    # the raised exception's message and traceback are recorded verbatim by
    # eval_error(), so both must carry the alias rather than the real model
    assert "mockllm" not in error.message
    assert ALIAS in error.message
    assert "mockllm" not in error.traceback
    assert "mockllm" not in error.traceback_ansi

    # ...and the real model name appears nowhere in plaintext in the log
    assert "mockllm" not in log.model_dump_json(exclude_none=True)


# retry logging


@skip_if_trio
async def test_retry_config_uses_alias_name(monkeypatch) -> None:
    init_model_aliases({ALIAS: TARGET})

    captured: list[str] = []

    def capture(model_name: str, *args: Any, **kwargs: Any) -> ModelRetryConfig:
        captured.append(model_name)
        return model_retry_config(model_name, *args, **kwargs)

    monkeypatch.setattr("inspect_ai.model._model.model_retry_config", capture)

    model = get_model(
        ALIAS,
        custom_outputs=[
            ModelOutput.from_content(model="mockllm", content="Hello World")
        ],
    )
    await model.generate("Just reply with the greeting")

    # log_model_retry() and report_active_sample_retry_wait() both receive this
    # name, and the retry message is logged at WARNING for long backoffs (so it
    # reaches the console and the log's logger events)
    assert captured
    assert captured == [model.name]
    assert "model" not in captured


@skip_if_trio
async def test_log_model_retry_redacts_provider_error(caplog) -> None:
    init_model_aliases({ALIAS: TARGET})
    model = get_model(ALIAS)

    class ProviderError(Exception):
        def __init__(self) -> None:
            super().__init__("rate limited")
            self.code = f"model_not_found: {TARGET}"

    retry_state = RetryCallState(None, None, (), {})  # type: ignore[arg-type]
    retry_state.attempt_number = 3
    # >= 20 minutes, i.e. the WARNING case that reaches the console and log
    retry_state.upcoming_sleep = 60 * 30
    retry_state.set_exception((ProviderError, ProviderError(), None))

    with caplog.at_level(logging.WARNING):
        await model._log_model_retry(model.name, retry_state)

    messages = [record.getMessage() for record in caplog.records]
    assert messages
    assert not any("mockllm" in message for message in messages)
    assert any("name" in message for message in messages)


# cost


@skip_if_trio
def test_aliased_model_omits_cost(tmp_path) -> None:
    def run(model_name: str) -> EvalLog:
        # registered under the canonical name so both the aliased and the
        # unaliased model resolve to the same (real) pricing
        set_model_info(
            "model",
            ModelInfo(
                cost=ModelCost(
                    input=1000.0,
                    output=1000.0,
                    input_cache_write=0.0,
                    input_cache_read=0.0,
                )
            ),
        )
        output = ModelOutput.from_content(model="model", content="Hello World")
        output.usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)
        model = get_model(model_name, custom_outputs=[output])
        task = Task(
            dataset=[Sample(input="Say Hello World", target="Hello World")],
            solver=[generate()],
            scorer=includes(),
        )
        return eval(task, model=model, log_dir=tmp_path.as_posix(), display="none")[0]

    try:
        # control: an unaliased model records cost as usual
        init_model_aliases({})
        log = run(TARGET)
        assert log.samples
        usage = log.samples[0].model_usage[TARGET]
        assert usage.total_cost == pytest.approx(0.007)

        # an aliased model records tokens but no cost: the cost is priced from
        # the real model, so the implied per-token rate is fingerprintable
        # against public price sheets
        init_model_aliases({ALIAS: TARGET})
        log = run(ALIAS)
        assert log.samples
        usage = log.samples[0].model_usage[ALIAS]
        assert usage.total_tokens == 7
        assert usage.total_cost is None
        assert log.stats.model_usage[ALIAS].total_cost is None
    finally:
        clear_model_info_cache()
