"""`inspect validate`: check .eval files against the add-only store (tamper-evident logs)."""

import click

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.log._log import EvalResults


@click.command("validate")
@click.argument("log_dir", type=str, required=False)
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
@click.option(
    "--nonce",
    "nonce_eval_id",
    type=str,
    default=None,
    metavar="EVAL_ID",
    help="Print only the nonce of eval EVAL_ID, from its start record, and "
    "check nothing (no LOG_DIR). `inspect score --tamper-evident-store` reads "
    "it from the INSPECT_TAMPER_EVIDENT_NONCE environment variable. Anyone "
    "with the nonce can rescore the eval, so give it only to the host that "
    "runs the rescore.",
)
def validate_command(
    log_dir: str | None, store: str, verbose: bool, nonce_eval_id: str | None
) -> None:
    """Check tamper-evident logs: compare the .eval files in LOG_DIR with the add-only store.

    Also checks the add-only store's settings and records. Exits non-zero on
    any finding. A pass covers the .eval fields the store holds (see the success line),
    not that the run was honest: records written after a compromise pass too.
    """
    from inspect_ai.log._addonly._validate import read_eval_nonce, validate_store

    if nonce_eval_id is not None:
        if log_dir is not None:
            raise click.UsageError("--nonce takes no LOG_DIR.")
        try:
            click.echo(read_eval_nonce(store, nonce_eval_id))
        except ValueError as ex:
            raise PrerequisiteError(str(ex)) from ex
        return
    if log_dir is None:
        raise click.UsageError("Missing argument 'LOG_DIR'.")

    report = validate_store(store, log_dir)
    if verbose:
        for record in report.records:
            click.echo(f"{record.arrival.isoformat()}  {record.key}")
    for key in report.stopped:
        click.echo(
            f"stopped {key}: No closing record: cut short, or its host stopped writing."
        )
    for key in report.not_logged:
        click.echo(
            f"not_logged {key}: Closed, not in the .eval file: the eval stopped "
            "before it logged the sample."
        )
    for eval_id, later_ids in report.prior_without_file.items():
        for later_id in later_ids:
            click.echo(
                f"prior_without_file {eval_id}: No .eval file; {later_id} names "
                "it as its prior eval."
            )
    for rescore in report.rescores:
        click.echo(
            f"rescored {rescore.eval_id} by {rescore.rescore_id} at "
            f"{rescore.arrival.isoformat()} ({rescore.action})"
        )
    for eval_id, results in {
        r.eval_id: r.original_results for r in report.rescores
    }.items():
        click.echo(f"original_results {eval_id}: {_results_line(results)}")
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
    click.echo(f"{summary}\n{CHECKED}")


def _results_line(results: EvalResults | None) -> str:
    """Each scorer's metrics, as ``<scorer> <metric>=<value>``."""
    if results is None:
        return "none (no eval closing record, or it has no results)"
    return ", ".join(
        f"{score.name} {metric.name}={metric.value}"
        for score in results.scores
        for metric in score.metrics.values()
    )


CHECKED = (
    "Checked against the add-only store: each sample's events and scores, which "
    "samples the .eval files have, and each eval's status, stats and results. "
    "Each sample summary is checked against its sample's scores.\n"
    "Not checked: everything else, including the eval spec and plan, each "
    "sample's messages, output and error, the sample summaries' other fields, "
    "invalidation and log_updates.\n"
    "A pass does not show that the run was honest."
)
"""What a pass covers (see ``_validate.py``: events through the buffer
read-back, scores and eval fields against the closing records)."""
