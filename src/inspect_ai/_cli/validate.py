"""PROTOTYPE: `inspect validate` (tamper-evident eval logs, step 1)."""

import click

from inspect_ai._util.error import PrerequisiteError


@click.command("validate")
@click.argument("log_dir", type=str)
@click.option(
    "--store",
    type=str,
    required=True,
    envvar="INSPECT_VALIDATE_STORE",
    help="s3://bucket/prefix of the add-only store. Taken from this option, "
    "never from a .eval file. Use one prefix per log directory: every eval "
    "under the prefix with no .eval file in LOG_DIR is reported.",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="List every record with its arrival time.",
)
def validate_command(log_dir: str, store: str, verbose: bool) -> None:
    """Check the add-only store, and compare the .eval files in LOG_DIR with it.

    A pass means each .eval file matches what was stored, not that the run
    was honest: records written after a compromise pass too.
    """
    from inspect_ai.log._addonly._validate import validate_store

    report = validate_store(store, log_dir)
    if verbose:
        for record in report.records:
            click.echo(f"{record.arrival.isoformat()}  {record.key}")
    for finding in report.findings:
        click.echo(
            f"{finding.kind} {finding.key or finding.eval_id or ''}: {finding.message}"
        )
    summary = (
        f"{len(report.evals)} eval(s), {report.samples_compared} sample(s) "
        f"compared, {len(report.findings)} finding(s)."
    )
    if not report.passed:
        raise PrerequisiteError(summary)
    click.echo(
        f"{summary} The .eval files match the add-only store. This does not "
        "show that the run was honest."
    )
