from dataclasses import dataclass

from pydantic import BaseModel
from typing_extensions import TypedDict

from inspect_ai import Task, task
from inspect_ai._cli.util import parse_cli_args
from inspect_ai._eval.registry import task_create
from inspect_ai.dataset import Sample


class AuditorConfig(BaseModel):
    system_message: str
    seed: int


@dataclass
class ScorerConfig:
    method: str
    threshold: float


class MetaInfo(TypedDict):
    author: str
    version: int


@task
def typed_params_task(
    auditor: AuditorConfig,
    scorer: ScorerConfig,
    meta: MetaInfo,
) -> Task:
    assert isinstance(auditor, AuditorConfig)
    assert auditor.system_message == "hello"
    assert auditor.seed == 42
    assert isinstance(scorer, ScorerConfig)
    assert scorer.method == "exact"
    assert scorer.threshold == 0.8
    assert isinstance(meta, dict)
    assert meta["author"] == "test"
    assert meta["version"] == 1
    return Task(dataset=[Sample(input="")], plan=[])


def test_dot_prefixed_cli_args_consolidation() -> None:
    args = parse_cli_args(
        (
            "auditor.system_message=hello",
            "auditor.seed=42",
            "scorer.method=exact",
            "scorer.threshold=0.8",
            "meta.author=test",
            "meta.version=1",
        )
    )
    assert args == {
        "auditor": {"system_message": "hello", "seed": 42},
        "scorer": {"method": "exact", "threshold": 0.8},
        "meta": {"author": "test", "version": 1},
    }


def test_task_with_typed_params() -> None:
    """End-to-end: task_create with BaseModel, dataclass, and TypedDict params."""
    task_instance = task_create(
        "typed_params_task",
        auditor={"system_message": "hello", "seed": 42},
        scorer={"method": "exact", "threshold": 0.8},
        meta={"author": "test", "version": 1},
    )
    assert isinstance(task_instance, Task)
