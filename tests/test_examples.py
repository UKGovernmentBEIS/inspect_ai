from pathlib import Path

from test_helpers.utils import run_example, skip_if_github_action

from inspect_ai.util import parse_compose_yaml


@skip_if_github_action
def test_examples():
    run_example(example="security_guide.py", model="mockllm/model")
    run_example(example="popularity.py", model="mockllm/model")


def test_http_proxy_example_disables_network_egress() -> None:
    compose_file = Path(__file__).parents[1] / "examples/http_proxy/compose.yaml"

    config = parse_compose_yaml(compose_file.as_posix())

    assert config.services["default"].network_mode == "none"
