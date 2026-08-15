import re
from typing import Iterator

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.model import ModelName, ModelOutput, get_model
from inspect_ai.model._model_alias import (
    MODEL_ALIASES_ENV_VAR,
    init_model_aliases,
    model_aliases,
    model_aliases_from_log,
    parse_model_aliases,
)
from inspect_ai.model._providers.mockllm import MockLLM
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
