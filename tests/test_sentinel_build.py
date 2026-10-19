import json
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from inspect_ai._sentinel._build import (
    config_from_sentinel,
    sentinel_from_config,
    validate_instance_name,
)
from inspect_ai._util import registry
from inspect_ai._util.registry import (
    RegistryInfo,
    RegistryType,
    registry_add,
    registry_info,
    registry_params,
    registry_tag,
)
from inspect_ai.log import SentinelConfig


class Instance:
    """A configured monitor or protocol; the registry tags it."""


def _sentinel(
    kind: RegistryType, name: str, version: int = 0
) -> Callable[[Callable[..., Instance]], Callable[..., Instance]]:
    # registers a factory as @monitor and @protocol do, so that building and
    # recording see what they see in inspect_sentinel
    def register(factory: Callable[..., Instance]) -> Callable[..., Instance]:
        info = RegistryInfo(type=kind, name=name, metadata={"version": version})

        @wraps(factory)
        def wrapper(*args: Any, **kwargs: Any) -> Instance:
            instance = factory(*args, **kwargs)
            registry_tag(factory, instance, info, *args, **kwargs)
            return instance

        registry_add(wrapper, info)
        return wrapper

    return register


@pytest.fixture(autouse=True)
def scratch_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_registry", dict(registry._registry))
    _register()


def _register() -> None:
    @_sentinel("monitor", "cfg_suspicion")
    def cfg_suspicion(model: str | None = None) -> Instance:
        return Instance()

    @_sentinel("protocol", "cfg_rule")
    def cfg_rule(reason: str = "no") -> Instance:
        return Instance()

    @_sentinel("protocol", "cfg_bundle")
    def cfg_bundle(**groups: object) -> Instance:
        return Instance()

    @_sentinel("protocol", "cfg_pkg/gate")
    def gate(monitors: object = None, reject_at: float = 1.0) -> Instance:
        return Instance()

    @_sentinel("protocol", "cfg_pkg/combine")
    def combine(children: object) -> Instance:
        return Instance()

    @_sentinel("monitor", "cfg_versioned", version=2)
    def cfg_versioned() -> Instance:
        return Instance()

    @_sentinel("protocol", "cfg_strict")
    def cfg_strict(limit: int = 1) -> Instance:
        if limit < 0:
            raise ValueError("limit must be 0 or more")
        return Instance()


def _name(built: object) -> str:
    return registry_info(built).name


def _listed(built: object) -> list[object]:
    assert isinstance(built, list)
    return cast(list[object], built)


def _mapped(built: object) -> dict[str, object]:
    assert isinstance(built, dict)
    return cast(dict[str, object], built)


def test_a_list_builds_each_entry_through_the_registry() -> None:
    built = _listed(
        sentinel_from_config(
            [
                {"name": "cfg_suspicion", "params": {"model": "openai/gpt-4o-mini"}},
                {"name": "cfg_rule"},
            ]
        )
    )
    assert [_name(child) for child in built] == ["cfg_suspicion", "cfg_rule"]
    assert registry_params(built[0]) == {"model": "openai/gpt-4o-mini"}


def test_a_mapping_keeps_its_instance_names() -> None:
    built = _mapped(sentinel_from_config({"first": {"name": "cfg_rule"}}))
    assert list(built) == ["first"]
    assert registry_info(built["first"]).type == "protocol"


def test_a_bare_name_finds_a_package_factory() -> None:
    [built] = _listed(
        sentinel_from_config(
            [
                {
                    "name": "gate",
                    "params": {"reject_at": 0.8},
                    "monitors": [{"name": "cfg_suspicion"}],
                }
            ]
        )
    )
    assert _name(built) == "cfg_pkg/gate"
    assert registry_params(built)["reject_at"] == 0.8


def test_a_bare_name_in_two_packages_is_ambiguous() -> None:
    @_sentinel("protocol", "other_pkg/gate")
    def gate(monitors: object) -> Instance:
        return Instance()

    with pytest.raises(ValueError, match=r"'gate' is ambiguous"):
        sentinel_from_config([{"name": "gate", "monitors": [{"name": "cfg_rule"}]}])


def test_an_exact_name_wins_over_a_package_factory() -> None:
    @_sentinel("protocol", "gate")
    def gate(monitors: object) -> Instance:
        return Instance()

    config: Any = [
        {"name": "gate", "monitors": [{"name": "cfg_suspicion"}]},
        {"name": "cfg_pkg/gate", "monitors": [{"name": "cfg_suspicion"}]},
    ]
    built = _listed(sentinel_from_config(config))
    assert [_name(child) for child in built] == ["gate", "cfg_pkg/gate"]
    assert config_from_sentinel(built) == SentinelConfig.model_validate(config)


def test_a_parsed_config_model_is_accepted() -> None:
    config = SentinelConfig.model_validate(
        [{"name": "gate", "monitors": [{"name": "cfg_suspicion"}]}]
    )
    [built] = _listed(sentinel_from_config(config))
    assert _name(built) == "cfg_pkg/gate"


@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_a_file_holds_the_config_under_sentinel(tmp_path: Path, suffix: str) -> None:
    content = {"sentinel": {"escape": {"name": "cfg_rule"}}}
    file = tmp_path / f"sentinel{suffix}"
    file.write_text(json.dumps(content) if suffix == ".json" else yaml.dump(content))
    built = _mapped(sentinel_from_config(str(file)))
    assert _name(built["escape"]) == "cfg_rule"


def test_a_file_uri_is_read(tmp_path: Path) -> None:
    file = tmp_path / "sentinel.yaml"
    file.write_text(yaml.dump({"sentinel": [{"name": "cfg_rule"}]}))
    [built] = _listed(sentinel_from_config(file.as_uri()))
    assert _name(built) == "cfg_rule"


def test_a_bare_registered_name_is_a_lone_instance() -> None:
    assert _name(sentinel_from_config("cfg_suspicion")) == "cfg_suspicion"
    assert _name(sentinel_from_config("gate")) == "cfg_pkg/gate"


@pytest.mark.parametrize(
    "raw",
    [
        {"name": "cfg_rule", "params": {"reason": "stop"}},
        SentinelConfig.model_validate(
            {"name": "cfg_rule", "params": {"reason": "stop"}}
        ),
    ],
)
def test_an_entry_with_a_string_name_is_a_lone_instance(raw: Any) -> None:
    built = sentinel_from_config(raw)
    assert _name(built) == "cfg_rule"
    assert registry_params(built) == {"reason": "stop"}


@pytest.mark.parametrize(
    "raw",
    [
        {"name": {"name": "cfg_rule"}},
        {"name": {"name": "cfg_rule"}, "b": {"name": "cfg_rule"}},
    ],
)
def test_an_instance_named_name_is_still_a_mapping(raw: Any) -> None:
    assert set(_mapped(sentinel_from_config(raw))) == set(raw)


INVALID: list[tuple[Any, type[Exception], str]] = [
    (
        [{"name": "cfg_nope"}],
        ValueError,
        r"sentinel\[0\]: 'cfg_nope' is not a registered monitor or protocol",
    ),
    (
        [{"name": "cfg_rule", "monitors": [{"name": "cfg_suspicion"}]}],
        ValueError,
        r"sentinel\[0\]: 'monitors' is not a parameter of cfg_rule",
    ),
    (
        {"a": {"name": "combine", "children": [{"name": "cfg_rule"}, {"name": "x"}]}},
        ValueError,
        r"sentinel\.a\.children\[1\]: 'x' is not a registered",
    ),
    ([{"params": {}}], ValueError, r"sentinel\[0\]: an entry needs a 'name'"),
    ([{"name": 3}], ValueError, r"sentinel\[0\]: an entry needs a 'name'"),
    (
        [{"name": "cfg_rule", "params": ["no"]}],
        ValueError,
        r"sentinel\[0\]\.params must be a mapping",
    ),
    (
        [
            {
                "name": "gate",
                "params": {"monitors": []},
                "monitors": [{"name": "cfg_suspicion"}],
            }
        ],
        ValueError,
        r"sentinel\[0\]: 'monitors' is given both nested and in params",
    ),
    (
        [{"name": "gate", "monitors": "cfg_suspicion"}],
        ValueError,
        r"sentinel\[0\]\.monitors must be a list or a mapping of entries",
    ),
    (["cfg_rule"], ValueError, r"sentinel\[0\] must be a mapping with a 'name'"),
    (3, ValueError, r"sentinel must be a list or a mapping of entries"),
    (
        [{"name": "cfg_rule", "params": {"nope": 1}}],
        TypeError,
        r"sentinel\[0\]: .*nope",
    ),
    (
        [{"name": "cfg_strict", "params": {"limit": -1}}],
        ValueError,
        r"sentinel\[0\]: limit must be 0 or more",
    ),
    ({"": {"name": "cfg_rule"}}, ValueError, r"sentinel: Instance name ''"),
    ({"a/b": {"name": "cfg_rule"}}, ValueError, r"sentinel: Instance name 'a/b'"),
    (
        "cfg_no_such_thing",
        ValueError,
        r"'cfg_no_such_thing' is neither a config file nor a registered",
    ),
]


@pytest.mark.parametrize("config, error, message", INVALID)
def test_invalid_config_names_the_entry(
    config: Any, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        sentinel_from_config(config)


def test_a_factorys_type_error_keeps_its_class() -> None:
    class CheckError(TypeError):
        pass

    @_sentinel("monitor", "cfg_unportable")
    def cfg_unportable() -> Instance:
        raise CheckError("references os.getenv")

    with pytest.raises(CheckError, match=r"sentinel\[0\]: references os.getenv"):
        sentinel_from_config([{"name": "cfg_unportable"}])


@pytest.mark.parametrize("name", ["attempt", "a.b", "name"])
def test_an_instance_name_without_a_slash_is_valid(name: str) -> None:
    assert validate_instance_name(name) == name


@pytest.mark.parametrize("name", ["", "a/b", 3, None])
def test_an_instance_name_must_be_a_path_segment(name: object) -> None:
    with pytest.raises(ValueError, match="non-empty string without '/'"):
        validate_instance_name(name)


@pytest.mark.parametrize(
    "content", [{"approvers": []}, {"sentinel": [], "extra": 1}, [{"name": "cfg_rule"}]]
)
def test_a_file_must_hold_only_a_sentinel_key(tmp_path: Path, content: Any) -> None:
    file = tmp_path / "sentinel.yaml"
    file.write_text(yaml.dump(content))
    with pytest.raises(ValueError, match="only key is 'sentinel'"):
        sentinel_from_config(str(file))


@pytest.mark.parametrize(
    "text, where, key",
    [
        (
            "sentinel:\n  attempt:\n    name: cfg_rule\n  attempt:\n    name: cfg_rule\n",
            "sentinel",
            "attempt",
        ),
        (
            "sentinel:\n  - name: cfg_rule\n    params:\n      reason: a\n      reason: b\n",
            r"sentinel\[0\]\.params",
            "reason",
        ),
        ("sentinel: []\nsentinel: []\n", "the top level", "sentinel"),
        (
            '{"sentinel": {"a": {"name": "cfg_rule", "name": "cfg_suspicion"}}}',
            r"sentinel\.a",
            "name",
        ),
    ],
)
def test_a_repeated_key_in_a_file_is_an_error(
    tmp_path: Path, text: str, where: str, key: str
) -> None:
    file = tmp_path / "sentinel.yaml"
    file.write_text(text)
    with pytest.raises(
        ValueError, match=rf"sentinel\.yaml: {where}: duplicate key '{key}'"
    ):
        sentinel_from_config(str(file))


def test_tab_indented_json_is_read(tmp_path: Path) -> None:
    file = tmp_path / "sentinel.json"
    file.write_text('{\n\t"sentinel": [\n\t\t{"name": "cfg_rule"}\n\t]\n}\n')
    [built] = _listed(sentinel_from_config(str(file)))
    assert _name(built) == "cfg_rule"


def test_a_malformed_file_names_the_file(tmp_path: Path) -> None:
    file = tmp_path / "broken.yaml"
    file.write_text("sentinel: [\n")
    with pytest.raises(ValueError, match=r"broken\.yaml: could not parse"):
        sentinel_from_config(str(file))


ROUND_TRIPS: list[Any] = [
    {"name": "cfg_rule", "params": {"reason": "stop"}},
    {
        "name": "gate",
        "params": {"reject_at": 0.5},
        "monitors": [{"name": "cfg_suspicion", "params": {}}],
    },
    [{"name": "cfg_suspicion", "params": {"model": "openai/gpt-4o-mini"}}],
    [
        {
            "name": "gate",
            "params": {"reject_at": 0.8},
            "monitors": {
                "a": {"name": "cfg_suspicion"},
                "b": {"name": "cfg_suspicion"},
            },
        }
    ],
    {
        "attempt": {
            "name": "combine",
            "children": {
                "watch": {"name": "cfg_suspicion"},
                "inner": {
                    "name": "combine",
                    "children": [
                        {"name": "cfg_rule"},
                        {
                            "name": "gate",
                            "monitors": {"m": {"name": "cfg_versioned", "version": 2}},
                        },
                    ],
                },
            },
        },
        "escape": {"name": "cfg_rule"},
    },
    [
        {
            "name": "cfg_bundle",
            "fast": [{"name": "cfg_suspicion"}],
            "slow": {"s": {"name": "cfg_suspicion", "params": {"model": "m"}}},
        }
    ],
]


@pytest.mark.parametrize("raw", ROUND_TRIPS)
def test_config_to_sentinel_to_config_is_equal(raw: Any) -> None:
    config = SentinelConfig.model_validate(raw)
    recorded = config_from_sentinel(sentinel_from_config(raw))
    assert recorded == config
    assert SentinelConfig.model_validate_json(recorded.model_dump_json()) == config


def test_a_package_name_is_recorded_bare_only_when_that_finds_it() -> None:
    gate = registry.registry_lookup("protocol", "cfg_pkg/gate")
    assert callable(gate)
    built = gate([sentinel_from_config("cfg_suspicion")], reject_at=0.5)
    assert config_from_sentinel(built).model_dump()["name"] == "gate"

    @_sentinel("protocol", "other_pkg/gate")
    def other_gate(monitors: object) -> Instance:
        return Instance()

    assert config_from_sentinel(built).model_dump()["name"] == "cfg_pkg/gate"


def test_a_lone_instance_is_recorded_as_a_lone_entry() -> None:
    built = sentinel_from_config({"name": "cfg_rule", "params": {"reason": "stop"}})
    assert config_from_sentinel(built) == SentinelConfig.model_validate(
        {"name": "cfg_rule", "params": {"reason": "stop"}}
    )


def test_a_non_sentinel_is_not_recorded() -> None:
    factory = registry.registry_lookup("protocol", "cfg_rule")
    with pytest.raises(TypeError, match="not a configured monitor or protocol"):
        config_from_sentinel([factory])
    with pytest.raises(TypeError, match="not a configured monitor or protocol"):
        config_from_sentinel([Instance()])


def test_a_version_round_trips() -> None:
    config = config_from_sentinel(sentinel_from_config([{"name": "cfg_versioned"}]))
    assert config.model_dump() == [
        {"name": "cfg_versioned", "params": {}, "version": 2}
    ]
    assert config_from_sentinel(sentinel_from_config(config)) == config


def test_version_0_is_omitted() -> None:
    config = config_from_sentinel(sentinel_from_config({"name": "cfg_rule"}))
    assert "version" not in config.model_dump_json()


def test_a_version_mismatch_warns_once_and_still_builds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw = [{"name": "cfg_versioned", "version": 1}]
    [built] = _listed(sentinel_from_config(raw))
    assert _name(built) == "cfg_versioned"
    sentinel_from_config(raw)
    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == [
        "cfg_versioned was recorded at version 1 but version 2 is installed; building it anyway."
    ]


def test_a_matching_version_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    sentinel_from_config([{"name": "cfg_versioned", "version": 2}])
    assert not caplog.records


def test_a_version_must_be_an_integer() -> None:
    with pytest.raises(ValueError, match=r"sentinel\[0\]\.version must be an integer"):
        sentinel_from_config([{"name": "cfg_versioned", "version": "2"}])


def test_meta_is_ignored_when_building_and_not_written() -> None:
    raw = [
        {
            "name": "cfg_bundle",
            "meta": {"added": ["later"]},
            "fast": [{"name": "cfg_versioned", "version": 2, "meta": {"x": 1}}],
        }
    ]
    assert config_from_sentinel(
        sentinel_from_config(raw)
    ) == SentinelConfig.model_validate(
        [
            {
                "name": "cfg_bundle",
                "params": {},
                "fast": [{"name": "cfg_versioned", "params": {}, "version": 2}],
            }
        ]
    )
