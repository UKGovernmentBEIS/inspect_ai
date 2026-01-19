import pytest

from inspect_ai.util import parse_compose_yaml


def test_parse_compose_yaml_valid(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    working_dir: /app
    x-default: true
    x-timeout: 300
    healthcheck:
      x-custom: nested

x-inspect_k8s_sandbox:
  allow_domains:
    - example.com
""")

    config = parse_compose_yaml(str(compose_file))

    assert config.services["default"].image == "ubuntu"
    assert config.services["default"].working_dir == "/app"
    assert config.services["default"].x_default is True
    assert config.services["default"].extensions["x-timeout"] == 300
    assert config.services["default"].healthcheck.extensions["x-custom"] == "nested"
    assert config.extensions["x-inspect_k8s_sandbox"]["allow_domains"] == [
        "example.com"
    ]


def test_parse_compose_yaml_rejects_multiple_services(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  web:
    image: nginx
  db:
    image: postgres
""")

    with pytest.raises(ValueError, match="does not support multiple services"):
        parse_compose_yaml(str(compose_file), multiple_services=False)


def test_parse_compose_yaml_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_compose_yaml("/nonexistent/compose.yaml")


def test_parse_compose_yaml_non_dict(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("- just\n- a\n- list")

    with pytest.raises(ValueError, match="Invalid compose file"):
        parse_compose_yaml(str(compose_file))


def test_parse_compose_yaml_missing_services(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
x-inspect_k8s_sandbox:
  allow_domains:
    - example.com
""")

    with pytest.raises(ValueError, match="must have 'services'"):
        parse_compose_yaml(str(compose_file))


def test_parse_compose_yaml_rejects_unknown_field(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services: {}
unknown_field: value
""")

    with pytest.raises(Exception, match="Unknown field"):
        parse_compose_yaml(str(compose_file))
