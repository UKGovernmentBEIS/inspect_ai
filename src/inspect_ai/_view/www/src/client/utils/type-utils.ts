import { EvalMetric, EvalResults } from "../../@types/log";
import { EvalHeader, EvalSummary, LogOverview } from "../api/types";

export const toBasicInfo = (header: EvalHeader | EvalSummary): LogOverview => {
  return {
    eval_id: header.eval.eval_id,
    run_id: header.eval.run_id,

    task: header.eval.task,
    task_id: header.eval.task_id,
    task_version: header.eval.task_version,

    version: header.version,
    status: header.status,
    error: header.error,

    model: header.eval.model,

    started_at: header.stats?.started_at,
    completed_at: header.stats?.completed_at,

    primary_metric: primaryMetric(header.results),
  };
};

const primaryMetric = (
  evalResults?: EvalResults | null,
): EvalMetric | undefined => {
  if (evalResults?.scores && evalResults?.scores.length > 0) {
    const evalMetrics = evalResults.scores[0].metrics;
    const metrics = Object.values(evalMetrics);
    if (metrics.length > 0) {
      return metrics[0];
    }
  }
  return undefined;
};
