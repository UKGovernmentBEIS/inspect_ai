import { EvalHeader, LogPreview } from "../api/types";

export function toLogOverview(header: EvalHeader): LogPreview {
  const { eval: evalSpec, version, status, error, stats, results } = header;

  // Get the first metric from the first score's metrics
  let primary_metric = undefined;
  if (results?.scores && results.scores.length > 0) {
    const firstScore = results.scores[0];
    // Get the first metric from the score's metrics object
    const metricsValues = Object.values(firstScore.metrics || {});
    if (metricsValues.length > 0) {
      primary_metric = metricsValues[0];
    }
  }

  return {
    eval_id: evalSpec.eval_id,
    run_id: evalSpec.run_id,
    task: evalSpec.task,
    task_id: evalSpec.task_id,
    task_version: evalSpec.task_version,
    version,
    status,
    error,
    model: evalSpec.model,
    started_at: evalSpec.created,
    completed_at: stats?.completed_at,
    primary_metric,
  };
}
