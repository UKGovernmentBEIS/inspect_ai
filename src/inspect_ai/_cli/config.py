import os
import json
import click
import yaml
from pathlib import Path
from typing import Any, Dict, List, Union
from dataclasses import dataclass
from typing_extensions import TypedDict

from inspect_ai._util.dotenv import init_dotenv
from inspect_ai._cli.common import common_options

# Get the directory where this file is located
CLI_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(CLI_DIR, "config.yaml")


class LoggingConfig(TypedDict):
    level: str
    format: str
    file: str
    transcript_level: str


class DisplayConfig(TypedDict):
    type: str
    max_width: int
    show_timestamps: bool
    color_scheme: str
    no_ansi: bool


class ModelConfig(TypedDict):
    default: str
    temperature: float
    max_tokens: int
    timeout: int
    max_connections: int


class CacheConfig(TypedDict):
    enabled: bool
    directory: str
    max_size: int
    ttl: int


class EvaluationConfig(TypedDict):
    default_metrics: List[str]
    max_samples: int
    max_tasks: int
    max_subprocesses: int | None
    max_sandboxes: int | None
    batch_size: int
    parallel: bool
    fail_on_error: bool
    log_samples: bool
    log_images: bool
    log_buffer: int
    log_shared: bool
    score: bool
    score_display: bool


class ToolsConfig(TypedDict):
    max_concurrent: int
    timeout: int
    retry_attempts: int
    parallel_tool_calls: bool
    internal_tools: bool
    max_tool_output: int | None


class APIConfig(TypedDict):
    base_url: str
    timeout: int
    retry_attempts: int
    verify_ssl: bool


class DebugConfig(TypedDict):
    enabled: bool
    port: int
    raise_errors: bool


class ConfigSchema(TypedDict):
    logging: LoggingConfig
    display: DisplayConfig
    model: ModelConfig
    cache: CacheConfig
    evaluation: EvaluationConfig
    tools: ToolsConfig
    api: APIConfig
    debug: DebugConfig


@dataclass
class ValidationError:
    path: str
    message: str
    expected: Any
    actual: Any


def validate_config(config: Dict[str, Any]) -> List[ValidationError]:
    """Validate the configuration against the schema."""
    errors: List[ValidationError] = []

    # Define expected types and values
    schema: Dict[str, Any] = {
        "logging": {
            "level": {
                "type": str,
                "values": [
                    "debug",
                    "trace",
                    "http",
                    "sandbox",
                    "info",
                    "warning",
                    "error",
                    "critical",
                ],
            },
            "format": {"type": str},
            "file": {"type": str},
            "transcript_level": {
                "type": str,
                "values": [
                    "debug",
                    "trace",
                    "http",
                    "sandbox",
                    "info",
                    "warning",
                    "error",
                    "critical",
                ],
            },
        },
        "display": {
            "type": {
                "type": str,
                "values": ["full", "conversation", "rich", "plain", "none"],
            },
            "max_width": {"type": int, "min": 1},
            "show_timestamps": {"type": bool},
            "color_scheme": {"type": str, "values": ["default", "dark", "light"]},
            "no_ansi": {"type": bool},
        },
        "model": {
            "default": {"type": str},
            "temperature": {"type": (int, float), "min": 0, "max": 1},
            "max_tokens": {"type": int, "min": 1},
            "timeout": {"type": int, "min": 1},
            "max_connections": {"type": int, "min": 1},
        },
        "cache": {
            "enabled": {"type": bool},
            "directory": {"type": str},
            "max_size": {"type": int, "min": 1},
            "ttl": {"type": int, "min": 1},
        },
        "evaluation": {
            "default_metrics": {"type": list},
            "max_samples": {"type": int, "min": 1},
            "max_tasks": {"type": int, "min": 1},
            "max_subprocesses": {"type": (int, type(None)), "min": 1},
            "max_sandboxes": {"type": (int, type(None)), "min": 1},
            "batch_size": {"type": int, "min": 1},
            "parallel": {"type": bool},
            "fail_on_error": {"type": bool},
            "log_samples": {"type": bool},
            "log_images": {"type": bool},
            "log_buffer": {"type": int, "min": 1},
            "log_shared": {"type": bool},
            "score": {"type": bool},
            "score_display": {"type": bool},
        },
        "tools": {
            "max_concurrent": {"type": int, "min": 1},
            "timeout": {"type": int, "min": 1},
            "retry_attempts": {"type": int, "min": 0},
            "parallel_tool_calls": {"type": bool},
            "internal_tools": {"type": bool},
            "max_tool_output": {"type": (int, type(None)), "min": 1},
        },
        "api": {
            "base_url": {"type": str},
            "timeout": {"type": int, "min": 1},
            "retry_attempts": {"type": int, "min": 0},
            "verify_ssl": {"type": bool},
        },
        "debug": {
            "enabled": {"type": bool},
            "port": {"type": int, "min": 1, "max": 65535},
            "raise_errors": {"type": bool},
        },
    }

    def validate_value(path: str, value: Any, rules: Dict[str, Any]) -> None:
        # Check if value exists
        expected_type = rules.get("type")
        if value is None:
            if not (isinstance(expected_type, tuple) and type(None) in expected_type):
                errors.append(
                    ValidationError(
                        path=path,
                        message="Value is required",
                        expected="non-null value",
                        actual=None,
                    )
                )
                return

        # Check type
        if expected_type:
            if isinstance(expected_type, tuple):
                if not isinstance(value, expected_type):
                    errors.append(
                        ValidationError(
                            path=path,
                            message=f"Invalid type",
                            expected=expected_type,
                            actual=type(value),
                        )
                    )
                    return
            else:
                if not isinstance(value, expected_type):
                    errors.append(
                        ValidationError(
                            path=path,
                            message=f"Invalid type",
                            expected=expected_type,
                            actual=type(value),
                        )
                    )
                    return

        # Check allowed values
        allowed_values = rules.get("values")
        if allowed_values and value not in allowed_values:
            errors.append(
                ValidationError(
                    path=path,
                    message="Value not in allowed set",
                    expected=allowed_values,
                    actual=value,
                )
            )

        # Check numeric ranges
        if isinstance(value, (int, float)):
            min_val = rules.get("min")
            if min_val is not None and value < min_val:
                errors.append(
                    ValidationError(
                        path=path,
                        message="Value below minimum",
                        expected=f">= {min_val}",
                        actual=value,
                    )
                )
            max_val = rules.get("max")
            if max_val is not None and value > max_val:
                errors.append(
                    ValidationError(
                        path=path,
                        message="Value above maximum",
                        expected=f"<= {max_val}",
                        actual=value,
                    )
                )

    def validate_section(
        section: str, data: Dict[str, Any], schema: Dict[str, Any]
    ) -> None:
        if section not in schema:
            errors.append(
                ValidationError(
                    path=section,
                    message="Unknown section",
                    expected="valid section name",
                    actual=section,
                )
            )
            return

        for key, rules in schema[section].items():
            path = f"{section}.{key}"
            if key not in data:
                errors.append(
                    ValidationError(
                        path=path,
                        message="Missing required key",
                        expected="value",
                        actual=None,
                    )
                )
            else:
                validate_value(path, data[key], rules)

    # Validate each section
    for section, data in config.items():
        validate_section(section, data, schema)

    return errors


@click.group(name="config")
@common_options
def config_command(**kwargs: Any) -> None:
    """View and modify configuration settings."""
    pass


@config_command.command(name="validate")
def validate_config_command() -> None:
    """Validate the current configuration."""
    config_path = Path(CONFIG_FILE)

    if not config_path.exists():
        click.echo(f"No configuration file found at {CONFIG_FILE}")
        return

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        errors = validate_config(config)

        if not errors:
            click.echo(click.style("✓ Configuration is valid", fg="green"))
            return

        click.echo(click.style("✗ Configuration has errors:", fg="red"))
        for error in errors:
            click.echo(f"\n{click.style(error.path, fg='yellow')}:")
            click.echo(f"  {error.message}")
            click.echo(f"  Expected: {error.expected}")
            click.echo(f"  Actual: {error.actual}")

    except Exception as e:
        click.echo(f"Error validating configuration: {e}")


@config_command.command(name="view")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["yaml", "json"]),
    default="yaml",
    help="Output format",
)
def view_config(format: str) -> None:
    """Display the current configuration."""
    config_path = Path(CONFIG_FILE)

    if not config_path.exists():
        click.echo(f"No configuration file found at {CONFIG_FILE}")
        return

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        if format == "json":
            click.echo(json.dumps(config, indent=2))
        else:
            click.echo(yaml.dump(config, default_flow_style=False))
    except Exception as e:
        click.echo(f"Error reading configuration: {e}")


@config_command.command(name="set")
@click.argument("key")
@click.argument("value")
def set_config(key: str, value: str) -> None:
    """Set a configuration value."""
    config_path = Path(CONFIG_FILE)
    config = {}

    # Create directory if it doesn't exist
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config if available
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            click.echo(f"Error reading existing configuration: {e}")
            return

    # Update the configuration
    # Handle nested keys like "logging.level"
    keys = key.split(".")
    current = config
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]

    # Try to convert value to appropriate type
    try:
        # Try as int
        value = int(value)
    except ValueError:
        try:
            # Try as float
            value = float(value)
        except ValueError:
            # Try as boolean
            if value.lower() in ("true", "yes", "y", "1"):
                value = True
            elif value.lower() in ("false", "no", "n", "0"):
                value = False
            # Otherwise keep as string

    current[keys[-1]] = value

    # Save the updated configuration
    try:
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)
        click.echo(f"Successfully set {key} to {value}")
    except Exception as e:
        click.echo(f"Error saving configuration: {e}")


@config_command.command(name="get")
@click.argument("key")
def get_config(key: str) -> None:
    """Get a specific configuration value."""
    config_path = Path(CONFIG_FILE)

    if not config_path.exists():
        click.echo(f"No configuration file found at {CONFIG_FILE}")
        return

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        # Handle nested keys
        keys = key.split(".")
        value = config
        for k in keys:
            if k not in value:
                click.echo(f"Key '{key}' not found in configuration")
                return
            value = value[k]

        click.echo(f"{key}: {value}")
    except Exception as e:
        click.echo(f"Error reading configuration: {e}")


@config_command.command(name="list")
def list_config() -> None:
    """List all configuration keys."""
    config_path = Path(CONFIG_FILE)

    if not config_path.exists():
        click.echo(f"No configuration file found at {CONFIG_FILE}")
        return

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        def print_keys(data: dict, prefix: str = "") -> None:
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, dict):
                        print_keys(value, f"{prefix}{key}.")
                    else:
                        click.echo(f"{prefix}{key}")

        print_keys(config)
    except Exception as e:
        click.echo(f"Error reading configuration: {e}")


@config_command.command(name="reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def reset_config(yes: bool) -> None:
    """Reset configuration to defaults."""
    config_path = Path(CONFIG_FILE)

    if not config_path.exists():
        click.echo("No configuration file to reset")
        return

    if not yes and not click.confirm(
        "Are you sure you want to reset the configuration?"
    ):
        click.echo("Operation cancelled")
        return

    try:
        os.remove(config_path)
        click.echo("Configuration reset successfully")
    except Exception as e:
        click.echo(f"Error resetting configuration: {e}")
