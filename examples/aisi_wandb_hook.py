import os

import wandb

from inspect_ai import Task, task
from inspect_ai._util.lifecycle import (
    EvalEndEvent,
    EvalStartEvent,
    LifecycleHook,
    ModelUsageEvent,
    SampleScoredEvent,
    lifecycle_hook,
)
from inspect_ai.analysis.beta._dataframe.evals.table import evals_df
from inspect_ai.dataset import example_dataset
from inspect_ai.dataset._dataset import Sample
from inspect_ai.scorer import exact, model_graded_fact
from inspect_ai.solver import chain_of_thought, generate, self_critique


@lifecycle_hook(name="aisi_wandb_hook")
class AisiWBHook(LifecycleHook):
    """An example lifecycle event hook for AISI which writes to Weights and Biases."""

    # TODO: If display=rich, we send too much logging data to wandb.
    # Can we ask Inspect what display mode is being used, and warn if it is rich/full?
    # Or can we supply a "plain" logger to W&B in addition to whatever is shown in the
    # terminal?
    async def on_eval_start(self, event: EvalStartEvent) -> None:
        wandb.init(
            project="inspect-integration-test",
            # TODO: Should we be using Task ID (used in inspect log filename) or run ID?
            name=event.run_id,
            config={"aisi-platform-user": os.environ.get("AISI_PLATFORM_USER", None)},
        )
        wandb.log({"resolved_tasks": event.task_names})

    async def on_eval_end(self, event: EvalEndEvent) -> None:
        # TODO: When can we expect to have multiple logs?
        for log in event.logs:
            assert wandb.run is not None
            # Provide our own name because the the Inspect log name may contain chars
            # not supported by W&B. Give it a unique name, otherwise W&B treats it as a
            # new version of Inspect logs from other runs.
            wandb.log_artifact(
                log.location, type="inspect_log", name=f"inspect_log_{wandb.run.name}"
            )
            if log.results is not None:
                score_metrics = log.results.scores[0].metrics
                first_metric = next(iter(score_metrics.values()))
                wandb.log(
                    {
                        "log_status": log.status,
                        f"log_score_{first_metric.name}": first_metric.value,
                    }
                )
        df = evals_df([log.location for log in event.logs])
        wandb.log({"evals_df": wandb.Table(dataframe=df.fillna("N/A"))})
        wandb.finish()

    async def on_sample_scored(self, event: SampleScoredEvent) -> None:
        serializable_scores = {}
        if event.sample_summary.scores is not None:
            serializable_scores = {
                k: v.value for k, v in event.sample_summary.scores.items()
            }
        wandb.log(
            {
                "sample_id": event.sample_summary.id,
                "sample_scores": serializable_scores,
                "sample_total_time": event.sample_summary.total_time,
            }
        )

    async def on_model_usage(self, event: ModelUsageEvent) -> None:
        # TODO: This ends up being a bit misleading in the W&B UI, as the latest one of
        # these to have been logged will appear in the summary metrics, making it look
        # like only _this_ model usage was used for the whole eval.
        wandb.log(
            {
                "model_usage.model_name": event.model_name,
                "model_usage.usage": event.usage.model_dump(),
                "model_usage.call_duration": event.call_duration,
            }
        )


@task
def hello_world():
    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[
            generate(),
        ],
        scorer=exact(),
    )


@task
def theory_of_mind(critique=False):
    # use self_critique if requested
    solver = [chain_of_thought(), generate()]
    if critique:
        solver.append(self_critique())

    return Task(
        dataset=example_dataset("theory_of_mind"),
        solver=solver,
        scorer=model_graded_fact(),
    )
