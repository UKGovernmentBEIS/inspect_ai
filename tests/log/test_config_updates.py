"""Tests for `EvalLog.config_updates` (persisted `inspect ctl config` retunes).

Covers the record schema and effective-config fold
(`inspect_ai.log._config_update`), round-tripping through both log formats,
the `.eval` journal write / finish-time consolidation / crashed-log fallback
read, and the JSON streaming header reader.
"""

import zipfile
from pathlib import Path

from inspect_ai.log import (
    ConfigUpdate,
    ConfigValueChange,
    effective_eval_config,
    effective_generate_config,
    read_eval_log,
    write_eval_log,
)
from inspect_ai.log._config_update import fill_previous_from_launch
from inspect_ai.log._edit import ProvenanceData
from inspect_ai.log._log import EvalConfig, EvalDataset, EvalLog, EvalSpec
from inspect_ai.log._recorders.eval import EvalRecorder
from inspect_ai.log._recorders.json import JSONRecorder
from inspect_ai.model import GenerateConfig


def _make_log(config: EvalConfig | None = None) -> EvalLog:
    return EvalLog(
        version=2,
        eval=EvalSpec(
            eval_id="test_eval",
            run_id="test_run",
            created="2025-01-01T00:00:00Z",
            task="test_task",
            task_id="test_task_id",
            dataset=EvalDataset(),
            model="test_model",
            config=config or EvalConfig(),
            model_generate_config=GenerateConfig(timeout=60, max_connections=10),
        ),
    )


def _update(*changes: ConfigValueChange, scope: str = "process") -> ConfigUpdate:
    return ConfigUpdate(
        changes=list(changes),
        scope=scope,  # type: ignore[arg-type]
        provenance=ProvenanceData(author="tester", reason="test retune"),
    )


# ---------------------------------------------------------------------------
# Effective-config fold
# ---------------------------------------------------------------------------


def test_effective_config_no_updates_is_launch_copy() -> None:
    log = _make_log(EvalConfig(max_samples=4))
    effective = effective_eval_config(log)
    assert effective.max_samples == 4
    # a copy, not the launch object itself
    effective.max_samples = 99
    assert log.eval.config.max_samples == 4


def test_effective_config_applies_updates_in_order() -> None:
    log = _make_log(EvalConfig(max_samples=4))
    log.config_updates = [
        _update(ConfigValueChange(config="eval", name="max_samples", value=8)),
        _update(ConfigValueChange(config="eval", name="max_samples", value=16)),
    ]
    assert effective_eval_config(log).max_samples == 16


def test_effective_config_cleared_restores_launch_value() -> None:
    log = _make_log()
    log.config_updates = [
        _update(ConfigValueChange(config="generate", name="timeout", value=300)),
        _update(ConfigValueChange(config="generate", name="timeout", cleared=True)),
    ]
    assert effective_generate_config(log).timeout == 60


def test_effective_config_value_none_sets_nullable_knob_to_null() -> None:
    # `value: None, cleared: false` lifts a limit entirely — distinct from
    # `cleared: true`, which restores the launch value
    log = _make_log(EvalConfig(time_limit=3600))
    log.config_updates = [
        _update(ConfigValueChange(config="eval", name="time_limit", value=None))
    ]
    assert effective_eval_config(log).time_limit is None


def test_effective_config_skips_other_config_and_unknown_fields() -> None:
    log = _make_log(EvalConfig(max_samples=4))
    log.config_updates = [
        _update(
            ConfigValueChange(config="generate", name="max_connections", value=5),
            ConfigValueChange(config="eval", name="knob_from_the_future", value=1),
        )
    ]
    effective = effective_eval_config(log)
    assert effective.max_samples == 4
    assert not hasattr(effective, "knob_from_the_future")
    assert effective_generate_config(log).max_connections == 5


def test_fill_previous_from_launch() -> None:
    log = _make_log(EvalConfig(max_samples=4))
    update = _update(
        ConfigValueChange(config="eval", name="max_samples", value=8),
        ConfigValueChange(config="generate", name="timeout", value=300),
        ConfigValueChange(config="generate", name="max_retries", value=2, previous=5),
    )
    filled = fill_previous_from_launch(update, log.eval)
    assert filled.changes[0].previous == 4  # launch EvalConfig.max_samples
    assert filled.changes[1].previous == 60  # launch GenerateConfig.timeout
    assert filled.changes[2].previous == 5  # already known — untouched
    # the original is not mutated
    assert update.changes[0].previous is None


def test_effective_config_ignores_concurrency_changes() -> None:
    # a --key retune is audit-only: even a key sharing a config field's
    # spelling must never fold into effective config
    log = _make_log(EvalConfig(max_samples=4))
    log.config_updates = [
        _update(
            ConfigValueChange(config="concurrency", name="google_web_search", value=3),
            ConfigValueChange(config="concurrency", name="max_samples", value=99),
            ConfigValueChange(config="concurrency", name="timeout", value=99),
        )
    ]
    assert effective_eval_config(log).max_samples == 4
    assert effective_generate_config(log).timeout == 60


def test_fill_previous_skips_concurrency_changes() -> None:
    # a concurrency key's name is a registry key, not a config field — a key
    # that happens to share a field's spelling must not pick up its launch value
    update = _update(
        ConfigValueChange(config="concurrency", name="timeout", value=3),
    )
    filled = fill_previous_from_launch(update, _make_log().eval)
    assert filled.changes[0].previous is None


# ---------------------------------------------------------------------------
# Round-trips through both formats
# ---------------------------------------------------------------------------


def _roundtrip(tmp_path: Path, suffix: str) -> None:
    log = _make_log()
    log.config_updates = [
        _update(
            ConfigValueChange(
                config="generate", name="timeout", value=300, previous=60
            ),
            scope="process",
        )
    ]
    path = str(tmp_path / f"log{suffix}")
    write_eval_log(log, path)

    for header_only in (True, False):
        read = read_eval_log(path, header_only=header_only)
        assert read.config_updates is not None
        assert len(read.config_updates) == 1
        update = read.config_updates[0]
        assert update.scope == "process"
        assert update.provenance.author == "tester"
        assert update.provenance.reason == "test retune"
        change = update.changes[0]
        assert (change.config, change.name) == ("generate", "timeout")
        assert (change.value, change.previous, change.cleared) == (300, 60, False)


def test_config_updates_roundtrip_eval_format(tmp_path: Path) -> None:
    _roundtrip(tmp_path, ".eval")


def test_config_updates_roundtrip_json_format(tmp_path: Path) -> None:
    # header_only=True exercises the streaming header reader's
    # `config_updates` key handling
    _roundtrip(tmp_path, ".json")


def test_config_updates_absent_by_default(tmp_path: Path) -> None:
    log = _make_log()
    path = str(tmp_path / "log.eval")
    write_eval_log(log, path)
    assert read_eval_log(path).config_updates is None


# ---------------------------------------------------------------------------
# .eval journal: mid-run write, crashed-log fallback, finish consolidation
# ---------------------------------------------------------------------------


async def test_eval_recorder_journals_and_consolidates(tmp_path: Path) -> None:
    log = _make_log()
    recorder = EvalRecorder(str(tmp_path))
    location = await recorder.log_init(log.eval)
    await recorder.log_start(log.eval, log.plan)
    await recorder.flush(log.eval)

    update = _update(
        ConfigValueChange(config="eval", name="max_samples", value=8, previous=4),
        scope="task",
    )
    await recorder.log_config_update(log.eval, update)

    # the journal member was written (and pushed to the destination) — an
    # in-progress log has no header.json, so this is the crash-durable record
    with zipfile.ZipFile(location) as zf:
        names = zf.namelist()
    assert "_journal/config_updates/1.json" in names
    assert "header.json" not in names

    # the in-progress (crashed-shaped) read reconstructs the header from the
    # journal, config updates included
    in_progress = read_eval_log(location, header_only=True)
    assert in_progress.config_updates is not None
    assert in_progress.config_updates[0].changes[0].name == "max_samples"
    assert in_progress.config_updates[0].scope == "task"

    # finish consolidates the updates into header.json
    finished = await recorder.log_finish(log.eval, "success", log.stats, None, None)
    assert finished.config_updates is not None
    assert finished.config_updates[0].changes[0].value == 8
    final = read_eval_log(location, header_only=True)
    assert final.config_updates is not None
    assert final.config_updates[0].changes[0].value == 8


async def test_eval_recorder_multiple_updates_ordered(tmp_path: Path) -> None:
    log = _make_log()
    recorder = EvalRecorder(str(tmp_path))
    location = await recorder.log_init(log.eval)
    await recorder.log_start(log.eval, log.plan)
    for value in (8, 16):
        await recorder.log_config_update(
            log.eval,
            _update(
                ConfigValueChange(config="eval", name="max_samples", value=value),
                scope="task",
            ),
        )
    await recorder.log_finish(log.eval, "success", log.stats, None, None)
    read = read_eval_log(location, header_only=True)
    assert read.config_updates is not None
    assert [u.changes[0].value for u in read.config_updates] == [8, 16]


async def test_json_recorder_accumulates_updates(tmp_path: Path) -> None:
    log = _make_log()
    recorder = JSONRecorder(str(tmp_path))
    location = await recorder.log_init(log.eval)
    await recorder.log_start(log.eval, log.plan)
    await recorder.log_config_update(
        log.eval,
        _update(
            ConfigValueChange(config="generate", name="max_retries", value=2),
            scope="process",
        ),
    )
    await recorder.log_finish(log.eval, "success", log.stats, None, None)
    read = read_eval_log(location, header_only=True)
    assert read.config_updates is not None
    assert read.config_updates[0].changes[0].name == "max_retries"


def test_full_rewrite_preserves_config_updates(tmp_path: Path) -> None:
    """write_eval_log of a log with updates keeps them (recorder rewrite path)."""
    log = _make_log()
    log.config_updates = [
        _update(ConfigValueChange(config="generate", name="timeout", value=300))
    ]
    path = str(tmp_path / "log.eval")
    write_eval_log(log, path)
    read = read_eval_log(path)
    assert read.config_updates is not None
    # rewrite the full log again from the read copy
    path2 = str(tmp_path / "log2.eval")
    write_eval_log(read, path2)
    reread = read_eval_log(path2, header_only=True)
    assert reread.config_updates is not None
    assert reread.config_updates[0].changes[0].value == 300
