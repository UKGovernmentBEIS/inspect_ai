import pytest

from inspect_ai.util import parse_compose_yaml
from inspect_ai.util._sandbox.compose import is_compose_yaml


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


def test_parse_compose_yaml_accepts_depends_on_short_form(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    depends_on:
      - judge
      - postgres
""")
    config = parse_compose_yaml(str(compose_file))
    assert config.services["default"].depends_on == ["judge", "postgres"]


def test_parse_compose_yaml_accepts_depends_on_long_form(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    depends_on:
      judge:
        condition: service_started
""")
    config = parse_compose_yaml(str(compose_file))
    assert config.services["default"].depends_on == {
        "judge": {"condition": "service_started"}
    }


def test_parse_compose_yaml_accepts_pull_policy(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    pull_policy: never
""")
    config = parse_compose_yaml(str(compose_file))
    assert config.services["default"].pull_policy == "never"


def test_parse_compose_yaml_accepts_privileged(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    privileged: true
""")
    config = parse_compose_yaml(str(compose_file))
    assert config.services["default"].privileged is True


def test_parse_compose_yaml_accepts_shm_size(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    shm_size: 2g
""")
    config = parse_compose_yaml(str(compose_file))
    assert config.services["default"].shm_size == "2g"


def test_parse_compose_yaml_accepts_ulimits(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    ulimits:
      nproc: 65535
      nofile:
        soft: 20000
        hard: 40000
""")
    config = parse_compose_yaml(str(compose_file))
    assert config.services["default"].ulimits == {
        "nproc": 65535,
        "nofile": {"soft": 20000, "hard": 40000},
    }


def test_parse_compose_yaml_accepts_memswap_limit(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services:
  default:
    image: ubuntu
    mem_limit: 12g
    memswap_limit: 20g
""")
    config = parse_compose_yaml(str(compose_file))
    assert config.services["default"].memswap_limit == "20g"


def test_parse_compose_yaml_rejects_unknown_field(tmp_path):
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("""
services: {}
unknown_field: value
""")

    with pytest.raises(Exception, match="Unknown field"):
        parse_compose_yaml(str(compose_file))


@pytest.mark.parametrize(
    "filename,expected",
    [
        # Standard compose files
        ("compose.yaml", True),
        ("compose.yml", True),
        ("docker-compose.yaml", True),
        ("docker-compose.yml", True),
        # Auto-compose pattern: ends with -compose.yaml or .compose.yaml
        (".compose.yaml", True),
        ("foo-compose.yaml", True),
        ("my-project-compose.yaml", True),
        ("inspect-task-i123abc-compose.yaml", True),
        # Should NOT match
        ("compose.txt", False),
        ("mycompose.yaml", False),  # no separator before "compose"
        ("compose-foo.yaml", False),  # compose not at end
        ("docker-compose.json", False),
        ("readme.yaml", False),
        ("compose.yaml.bak", False),
    ],
)
def test_is_compose_yaml_pattern(filename: str, expected: bool) -> None:
    """Test is_compose_yaml correctly identifies compose files by filename pattern."""
    assert is_compose_yaml(filename) == expected
