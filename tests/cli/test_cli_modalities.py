import json
import os
import tempfile

import yaml

from inspect_ai import Task, eval
from inspect_ai._cli.eval import parse_modalities
from inspect_ai.dataset import Sample
from inspect_ai.model._generate_config import ImageOutput
from inspect_ai.solver import generate


def test_parse_modalities_comma_separated():
    result = parse_modalities("image")
    assert result == ["image"]


def test_parse_modalities_multiple_comma_separated():
    result = parse_modalities("image,audio")
    assert result == ["image", "audio"]


def test_parse_modalities_yaml_file():
    config = [{"quality": "high", "size": "1024x1024"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        f.flush()
        try:
            result = parse_modalities(f.name)
            assert len(result) == 1
            assert isinstance(result[0], ImageOutput)
            assert result[0].quality == "high"
            assert result[0].size == "1024x1024"
        finally:
            os.unlink(f.name)


def test_parse_modalities_json_file():
    config = [{"quality": "low", "size": "1024x1024"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        f.flush()
        try:
            result = parse_modalities(f.name)
            assert len(result) == 1
            assert isinstance(result[0], ImageOutput)
            assert result[0].quality == "low"
        finally:
            os.unlink(f.name)


def test_parse_modalities_yaml_mixed():
    config = ["image", {"quality": "high"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config, f)
        f.flush()
        try:
            result = parse_modalities(f.name)
            assert len(result) == 2
            assert result[0] == "image"
            assert isinstance(result[1], ImageOutput)
        finally:
            os.unlink(f.name)


def test_eval_modalities_passed_through():
    """Verify --modalities flows through to eval's generate_config."""
    task = Task(
        dataset=[Sample(input="Say hello", target="hello")],
        solver=[generate()],
    )
    log = eval(task, model="mockllm/model", modalities=["image"])[0]
    assert log.plan.config.modalities == ["image"]
