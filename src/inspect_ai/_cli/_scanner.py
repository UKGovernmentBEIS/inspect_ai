"""CLI helpers for resolving `--scanner` specs into eval_set inputs."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from inspect_ai._cli.util import (
    parse_cli_args,
    parse_cli_config,
    parse_model_role_cli_args,
)
from inspect_ai._util.registry import registry_lookup

if TYPE_CHECKING:
    from inspect_ai._eval.task.scan import EvalSetScanners


def _parse_comma_separated(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [v.strip() for v in value.split(",") if v.strip()] or None


def resolve_cli_scanner(
    scanner: str | None,
    scanner_arg: tuple[str, ...] | None,
    *,
    scans: str | None = None,
    scan_name: str | None = None,
    scan_tags: str | None = None,
    scan_metadata: tuple[str, ...] | None = None,
    scan_filter: tuple[str, ...] | None = None,
    scan_model: str | None = None,
    scan_model_base_url: str | None = None,
    scan_model_arg: tuple[str, ...] | None = None,
    scan_model_config: str | None = None,
    scan_model_role: tuple[str, ...] | None = None,
    scan_generate_config: str | None = None,
) -> "EvalSetScanners | None":
    """Resolve a CLI `--scanner` spec into an `EvalSetScanners` argument.

    Mirrors the input formats accepted by `scout scan`:

    - YAML/JSON config file (`.yaml`/`.yml`/`.json`) → loaded via
      `EvalSetScannerConfig.from_file` (carries scanners + tags /
      metadata / filter / model overrides).
    - Python file (`.py`, optionally `file.py@func` to pick one) → all
      `@scanner`-decorated functions in the file.
    - Registry reference (`pkg/scanner_name`) → single scanner created
      with the given args.

    `scanner_arg` are `KEY=VALUE` pairs forwarded to scanner
    constructors (analogous to `-T`/`-S`/`-M` for tasks/solvers/models).
    For YAML/JSON configs the args are ignored — put them in the file.

    Any of the `scan_*` overrides set on the CLI are applied to the
    resolved config (a base list of scanners is wrapped in
    `EvalSetScannerConfig`). CLI flags take precedence over equivalent
    fields in a YAML/JSON config so quick overrides work without
    editing the file.
    """
    overrides = _build_overrides(
        scans=scans,
        scan_name=scan_name,
        scan_tags=scan_tags,
        scan_metadata=scan_metadata,
        scan_filter=scan_filter,
        scan_model=scan_model,
        scan_model_base_url=scan_model_base_url,
        scan_model_arg=scan_model_arg,
        scan_model_config=scan_model_config,
        scan_model_role=scan_model_role,
        scan_generate_config=scan_generate_config,
    )

    if not scanner:
        if overrides:
            raise click.UsageError(
                "Scan-side options (--scans, --scan-model, etc.) require "
                "--scanner to be set."
            )
        return None

    base = _resolve_base_scanner(scanner, scanner_arg)

    if not overrides:
        return base

    return _apply_overrides(base, overrides)


def _resolve_base_scanner(
    scanner: str,
    scanner_arg: tuple[str, ...] | None,
) -> "EvalSetScanners":
    from inspect_ai import EvalSetScannerConfig

    args = parse_cli_args(scanner_arg) if scanner_arg else {}

    # YAML/JSON config file
    if scanner.endswith((".yaml", ".yml", ".json")):
        return EvalSetScannerConfig.from_file(scanner)

    # Python file with @scanner-decorated functions (optionally @func)
    file_part = scanner.split("@", 1)[0]
    if file_part.endswith(".py") and Path(file_part).exists():
        from inspect_scout._scanner.scanner import scanners_from_file

        scanners = scanners_from_file(scanner, args)
        if not scanners:
            raise click.UsageError(
                f"No @scanner decorated functions found in '{scanner}'."
            )
        return scanners

    # Registry reference (e.g. "pkg/scanner_name")
    if "/" in scanner and registry_lookup("scanner", scanner) is not None:
        from inspect_scout._scanner.scanner import scanner_create

        return [scanner_create(scanner, args)]

    raise click.UsageError(
        f"Could not resolve --scanner '{scanner}'. Expected a YAML/JSON "
        "config file, a Python file with @scanner functions, or a "
        "registered scanner name (pkg/name)."
    )


def _build_overrides(
    *,
    scans: str | None,
    scan_name: str | None,
    scan_tags: str | None,
    scan_metadata: tuple[str, ...] | None,
    scan_filter: tuple[str, ...] | None,
    scan_model: str | None,
    scan_model_base_url: str | None,
    scan_model_arg: tuple[str, ...] | None,
    scan_model_config: str | None,
    scan_model_role: tuple[str, ...] | None,
    scan_generate_config: str | None,
) -> dict[str, Any]:
    """Collect the CLI scan-* options into an override dict.

    Empty/unset options are dropped so they don't clobber config-file
    values. Multi-value options are parsed into their final shapes here.
    """
    overrides: dict[str, Any] = {}

    if scans is not None:
        overrides["scans"] = scans
    if scan_name is not None:
        overrides["name"] = scan_name

    tags = _parse_comma_separated(scan_tags)
    if tags is not None:
        overrides["tags"] = tags

    if scan_metadata:
        overrides["metadata"] = parse_cli_args(scan_metadata)

    if scan_filter:
        overrides["filter"] = list(scan_filter)

    if scan_model is not None:
        overrides["model"] = scan_model
    if scan_model_base_url is not None:
        overrides["model_base_url"] = scan_model_base_url

    if scan_model_arg or scan_model_config:
        overrides["model_args"] = parse_cli_config(scan_model_arg, scan_model_config)

    if scan_model_role:
        overrides["model_roles"] = parse_model_role_cli_args(scan_model_role)

    if scan_generate_config is not None:
        from inspect_ai._util.config import resolve_args
        from inspect_ai.model import GenerateConfig

        overrides["generate_config"] = GenerateConfig.model_validate(
            resolve_args(scan_generate_config)
        )

    return overrides


def _apply_overrides(
    base: "EvalSetScanners",
    overrides: dict[str, Any],
) -> "EvalSetScanners":
    """Apply CLI overrides to the resolved scanner.

    Promotes a bare list-of-scanners to an `EvalSetScannerConfig` so
    overrides have somewhere to land. CLI-set fields win over fields
    that came from a YAML/JSON config (or were left at default).
    """
    from inspect_ai import EvalSetScannerConfig

    if isinstance(base, EvalSetScannerConfig):
        return base.model_copy(update=overrides)

    return EvalSetScannerConfig(scanners=base, **overrides)
